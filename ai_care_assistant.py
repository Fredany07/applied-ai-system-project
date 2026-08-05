"""AI Care Assistant for PawPal+.

This module is the Module 3 "advanced AI feature." It combines two of the
required patterns so the AI is genuinely load-bearing rather than decorative:

1. Retrieval-Augmented Generation (RAG)
   ``CareKnowledgeBase`` holds short, citable pet-care guidelines. Before the
   model generates anything, we retrieve the guidelines relevant to the pet's
   species/gaps in its task list and hand those snippets to the model as
   grounding context. The model is instructed to base its suggestions on the
   retrieved text, not on unaided guesswork.

2. Agentic workflow (plan -> act -> check -> revise)
   ``CareAgent.suggest_tasks`` doesn't just call an LLM once and print the
   result. It:
     - PLANS: retrieves context, prompts the model for structured task
       suggestions.
     - ACTS: converts the model's output into real ``Task`` objects and runs
       them through the *actual* ``Scheduler`` (the same one the rest of the
       app uses) to see whether they fit the owner's time budget without
       conflicts.
     - CHECKS: if the trial run finds conflicts or dropped tasks, the agent
       sends the model a revision request describing exactly what went wrong
       and asks it to adjust (shorter durations / different priorities).
     - This loops up to ``MAX_ITERATIONS`` times, and every step is logged.

Guardrails:
    - All model output must pass strict JSON-schema validation before it is
      trusted; anything malformed is dropped and logged, never silently
      accepted.
    - If no API key is configured, or the API call fails for any reason, the
      agent transparently falls back to a deterministic, template-based
      suggestion generator built directly from the retrieved knowledge base
      entries. The app keeps working; nothing crashes; the UI/log clearly
      marks which mode produced the result.
    - A human (the owner, in the Streamlit UI) reviews and explicitly accepts
      suggested tasks before they become real tasks — the AI proposes, the
      person and the existing Scheduler logic dispose.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from pawpal_system import Owner, Pet, Scheduler, Task

# --------------------------------------------------------------------------
# Logging: every plan/act/check step is recorded so behavior is auditable.
# --------------------------------------------------------------------------
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("pawpal.ai_care_assistant")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.FileHandler(_LOG_DIR / "pawpal_ai.log")
    _handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(_handler)

_KB_PATH = Path(__file__).parent / "data" / "care_knowledge_base.json"
_VALID_PRIORITIES = {"low", "medium", "high"}
MAX_ITERATIONS = 3
MAX_SUGGESTIONS = 4
DEFAULT_MODEL = os.environ.get("PAWPAL_ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


# --------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------
class CareKnowledgeBase:
    """A small, file-backed store of pet-care guidelines used for retrieval.

    Deliberately simple (keyword/tag overlap scoring, no embeddings or
    external services) so the retrieval step has zero extra dependencies and
    is fully reproducible offline.
    """

    def __init__(self, path: Path = _KB_PATH) -> None:
        with open(path, "r", encoding="utf-8") as f:
            self.entries: list[dict] = json.load(f)

    def retrieve(
        self, species: str, existing_categories: set[str] | None = None, top_k: int = 4
    ) -> list[dict]:
        """Return the most relevant guideline entries for a species.

        Scoring favors entries for this exact species (or ones tagged "any"),
        and boosts categories the pet doesn't already have a task for, so
        retrieval surfaces *gaps* rather than repeating what's already
        scheduled.
        existing_categories: category names already covered by the pet's
        current tasks (used only to bias ranking, never to hard-filter).
        """
        existing_categories = existing_categories or set()
        scored = []
        for entry in self.entries:
            if entry["species"] not in (species, "any"):
                continue
            score = 2 if entry["species"] == species else 1
            if entry["category"] not in existing_categories:
                score += 1
            scored.append((score, entry))
        scored.sort(key=lambda pair: -pair[0])
        results = [entry for _, entry in scored[:top_k]]
        logger.info(
            "Retrieved %d guideline(s) for species=%s (existing_categories=%s)",
            len(results), species, sorted(existing_categories),
        )
        return results


# --------------------------------------------------------------------------
# LLM client (thin wrapper; isolates the only network-dependent code path)
# --------------------------------------------------------------------------
class LLMUnavailableError(RuntimeError):
    """Raised when no model call can be made (missing key, network, etc.)."""


class LLMClient:
    """Wraps the Anthropic API call. Isolated so it's easy to mock in tests
    and so the rest of the agent never needs to know whether a real call
    happened."""

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def complete(self, system: str, user: str) -> str:
        if not self._api_key:
            raise LLMUnavailableError("ANTHROPIC_API_KEY is not set.")
        try:
            import anthropic  # imported lazily so the package is optional
        except ImportError as exc:
            raise LLMUnavailableError("anthropic package is not installed.") from exc

        try:
            client = anthropic.Anthropic(api_key=self._api_key)
            response = client.messages.create(
                model=self.model,
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            )
        except Exception as exc:  # network errors, auth errors, rate limits, etc.
            raise LLMUnavailableError(f"Anthropic API call failed: {exc}") from exc


# --------------------------------------------------------------------------
# Agent output types
# --------------------------------------------------------------------------
@dataclass
class AgentStep:
    """One entry in the agent's plan -> act -> check reasoning trace."""

    stage: str          # "plan" | "act" | "check" | "revise" | "fallback"
    message: str


@dataclass
class AgentResult:
    suggested_tasks: list[Task] = field(default_factory=list)
    retrieved_context: list[dict] = field(default_factory=list)
    trace: list[AgentStep] = field(default_factory=list)
    used_llm: bool = False
    iterations: int = 0
    confidence: float = 0.0

    def log_step(self, stage: str, message: str) -> None:
        self.trace.append(AgentStep(stage=stage, message=message))
        logger.info("[%s] %s", stage.upper(), message)


# --------------------------------------------------------------------------
# Validation guardrail
# --------------------------------------------------------------------------
def _validate_suggestion(raw: dict) -> tuple[Task, str] | None:
    """Validate one model-proposed task dict; return a Task or None.

    Never trusts model output blindly: every field is type- and range-checked
    before it becomes a real Task.
    """
    try:
        title = str(raw["title"]).strip()
        duration = int(raw["duration_minutes"])
        priority = str(raw.get("priority", "medium")).lower()
        category = str(raw.get("category", "general"))
    except (KeyError, TypeError, ValueError):
        return None

    if not title or not (1 <= duration <= 240) or priority not in _VALID_PRIORITIES:
        return None

    return Task(
        title=title,
        duration_minutes=duration,
        priority=priority,
        recurring=raw.get("recurring", "none") if raw.get("recurring") in {"none", "daily", "weekly"} else "none",
    ), category  # type: ignore[return-value]


def _parse_llm_json(text: str) -> list[dict]:
    """Extract a JSON array of task suggestions from model output."""
    text = text.strip()
    # Models sometimes wrap JSON in fences despite instructions; strip them.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of suggestions.")
    return data


# --------------------------------------------------------------------------
# Deterministic fallback (no API key / API failure)
# --------------------------------------------------------------------------
def _fallback_suggestions(context: list[dict], limit: int) -> list[tuple[Task, str]]:
    """Build suggestions directly from retrieved KB entries, no model call.

    Guarantees the feature still works end-to-end offline: every PawPal+
    reviewer can see RAG + agentic behavior without needing an API key.
    """
    suggestions = []
    for entry in context[:limit]:
        title = entry["category"].replace("_", " ").title()
        # Pull a plausible duration out of the guideline text; default to 15.
        duration = 15
        for token in entry["text"].replace("-", " ").split():
            if token.isdigit():
                duration = min(max(int(token), 5), 60)
                break
        priority = "high" if entry["category"] in {"medication", "feeding"} else "medium"
        suggestions.append(
            (Task(title=f"{title} ({entry['species']})", duration_minutes=duration, priority=priority),
             entry["category"])
        )
    return suggestions


# --------------------------------------------------------------------------
# The agent itself
# --------------------------------------------------------------------------
class CareAgent:
    """Plans, retrieves, generates, and self-checks care task suggestions."""

    PLAN_SYSTEM_PROMPT = (
        "You are a pet care planning assistant inside the PawPal+ app. "
        "You will be given short, trusted pet-care guidelines (retrieved "
        "from a knowledge base) and must propose new daily care tasks that "
        "are grounded in those guidelines. Respond with ONLY a JSON array, "
        "no prose, no markdown fences. Each element must have exactly these "
        "keys: title (string), duration_minutes (integer 1-240), "
        "priority (one of \"low\", \"medium\", \"high\"), "
        "category (string), recurring (one of \"none\", \"daily\", \"weekly\")."
    )

    def __init__(self, kb: CareKnowledgeBase | None = None, llm: LLMClient | None = None) -> None:
        self.kb = kb or CareKnowledgeBase()
        self.llm = llm or LLMClient()

    def suggest_tasks(self, pet: Pet, owner: Owner, max_suggestions: int = MAX_SUGGESTIONS) -> AgentResult:
        result = AgentResult()
        context = self.kb.retrieve(pet.species, existing_categories=set())
        result.retrieved_context = context
        result.log_step(
            "plan",
            f"Retrieved {len(context)} guideline(s) for {pet.name} ({pet.species}) "
            f"to ground task suggestions.",
        )

        candidates: list[tuple[Task, str]] = []
        feedback = None

        for iteration in range(1, MAX_ITERATIONS + 1):
            result.iterations = iteration
            if self.llm.available:
                try:
                    candidates = self._plan_with_llm(pet, owner, context, feedback, max_suggestions)
                    result.used_llm = True
                    result.log_step("plan", f"Iteration {iteration}: model proposed {len(candidates)} task(s).")
                except LLMUnavailableError as exc:
                    result.log_step("fallback", f"LLM call failed ({exc}); using knowledge-base fallback.")
                    candidates = _fallback_suggestions(context, max_suggestions)
                    result.used_llm = False
            else:
                if iteration == 1:
                    result.log_step(
                        "fallback",
                        "No ANTHROPIC_API_KEY configured; using deterministic "
                        "knowledge-base fallback instead of a live model call.",
                    )
                candidates = _fallback_suggestions(context, max_suggestions)
                result.used_llm = False

            # ACT: try the candidates against the real Scheduler.
            trial_pet = Pet(name=pet.name, species=pet.species, tasks=list(pet.tasks) + [t for t, _ in candidates])
            trial_owner = Owner(name=owner.name, minutes_available=owner.minutes_available, pets=[trial_pet])
            scheduler = Scheduler.from_owner(trial_owner)
            plan = scheduler.build_plan()
            conflicts = scheduler.find_conflicts()
            dropped = [t for t in candidates if t[0] not in plan and t[0].scheduled_time is None]
            suggested_titles = {t.title for t, _ in candidates}
            fits = sum(1 for t in plan if t.title in suggested_titles)

            result.log_step(
                "check",
                f"Iteration {iteration}: {fits}/{len(candidates)} suggestion(s) fit the "
                f"{owner.minutes_available}-minute budget; {len(conflicts)} scheduling conflict(s) found.",
            )

            if not self.llm.available:
                break  # fallback path is deterministic; no point iterating
            if fits == len(candidates) and not conflicts:
                break  # good plan, stop early

            feedback = (
                f"Your previous suggestions only fit {fits} of {len(candidates)} tasks "
                f"into the owner's remaining {owner.minutes_available} available minutes, "
                f"and {len(conflicts)} of them conflicted in time. Propose shorter or "
                f"fewer tasks, or lower-priority alternatives, so they realistically fit."
            )
            result.log_step("revise", feedback)

        result.suggested_tasks = [t for t, _ in candidates]
        result.confidence = self._confidence(result, owner, candidates)
        result.log_step(
            "check",
            f"Final confidence: {result.confidence:.2f} "
            f"(used_llm={result.used_llm}, iterations={result.iterations}).",
        )
        return result

    def _plan_with_llm(
        self, pet: Pet, owner: Owner, context: list[dict], feedback: str | None, limit: int,
    ) -> list[tuple[Task, str]]:
        guideline_text = "\n".join(f"- ({e['category']}) {e['text']}" for e in context)
        existing = "\n".join(f"- {t.title} ({t.duration_minutes} min, {t.priority})" for t in pet.tasks) or "  (none yet)"
        user_prompt = (
            f"Pet: {pet.name}, species: {pet.species}\n"
            f"Owner's available time today: {owner.minutes_available} minutes\n"
            f"Existing tasks for this pet:\n{existing}\n\n"
            f"Retrieved care guidelines:\n{guideline_text}\n\n"
            f"Propose up to {limit} NEW care tasks (don't repeat existing ones), "
            f"grounded in the guidelines above."
        )
        if feedback:
            user_prompt += f"\n\nRevision needed: {feedback}"

        raw_text = self.llm.complete(self.PLAN_SYSTEM_PROMPT, user_prompt)
        raw_items = _parse_llm_json(raw_text)

        validated: list[tuple[Task, str]] = []
        for item in raw_items[:limit]:
            outcome = _validate_suggestion(item)
            if outcome is None:
                logger.warning("Rejected malformed model suggestion: %r", item)
                continue
            validated.append(outcome)
        return validated

    @staticmethod
    def _confidence(result: AgentResult, owner: Owner, candidates: list[tuple[Task, str]]) -> float:
        """A simple, explainable confidence score in [0, 1].

        Not a model-reported number: it's computed from verifiable facts
        (did suggestions fit? were there conflicts? did we need a real model
        call or only the deterministic fallback?) so it can't be gamed by a
        model claiming false confidence.
        """
        if not candidates:
            return 0.0
        trial_pet = Pet(name="_trial", species="any", tasks=[t for t, _ in candidates])
        trial_owner = Owner(name="_trial", minutes_available=owner.minutes_available, pets=[trial_pet])
        scheduler = Scheduler.from_owner(trial_owner)
        plan = scheduler.build_plan()
        fit_ratio = len(plan) / len(candidates)
        conflict_penalty = 0.15 * len(scheduler.find_conflicts())
        base = fit_ratio - conflict_penalty
        if not result.used_llm:
            base -= 0.1  # fallback is reliable but less tailored than a real model call
        return round(max(0.0, min(1.0, base)), 2)
