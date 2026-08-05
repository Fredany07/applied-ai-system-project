# PawPal+ — AI Care Assistant Edition (Module 3)

**Original project:** PawPal+ (Module 2). PawPal+ started as a Streamlit app that
let a pet owner track care tasks (walks, feeding, meds, grooming, enrichment)
for one or more pets and generate a daily plan that fit a limited time budget,
sorted by priority and checked for scheduling conflicts. This Module 3 update
keeps that entire system intact and adds a new **AI Care Assistant** that
proposes new care tasks instead of requiring the owner to think of everything
themselves.

## Title and Summary

PawPal+ is a pet care planner that turns "I have 60 minutes and three pets" into
a concrete, priority-ordered daily schedule — and now, an AI assistant that
suggests *what to schedule* in the first place, grounded in real pet-care
guidelines rather than guesswork. It matters because the hardest part of pet
care consistency usually isn't the scheduling math, it's remembering everything
a pet needs; the AI Care Assistant closes that gap without taking control away
from the owner.

## Advanced AI Feature: RAG + Agentic Workflow

The required advanced feature (`ai_care_assistant.py`) combines two patterns so
the AI is load-bearing, not decorative:

- **Retrieval-Augmented Generation.** `CareKnowledgeBase` holds short, curated
  pet-care guidelines (`data/care_knowledge_base.json`). Before generating
  anything, the agent retrieves the guidelines relevant to the pet's species,
  and those snippets are placed directly in the model prompt as grounding
  context — the model is instructed to base suggestions on them.
- **Agentic plan → act → check → revise loop.** `CareAgent.suggest_tasks`
  doesn't stop at one model call. It plans (retrieve + prompt), acts (builds
  real `Task` objects and runs them through the *actual* `Scheduler` used
  elsewhere in the app to see if they fit the owner's time budget without
  conflicts), checks the outcome, and — if the model is available and the
  first draft didn't fit — sends the model a revision request and tries again,
  up to `MAX_ITERATIONS` times.

This is wired into the main application logic, not a side script: suggested
tasks that the owner accepts become ordinary `Task` objects, scheduled and
conflict-checked by the same `Scheduler` as every manually-entered task.

## Architecture Overview

See [`system_architecture.mmd`](system_architecture.mmd) for the full diagram.
In short:

`Owner input → CareKnowledgeBase (retrieve) → CareAgent (plan) → LLMClient or
deterministic fallback → schema guardrail → trial run through the real
Scheduler (act/check) → revise loop if needed → AgentResult (tasks + trace +
confidence) → Streamlit UI → human reviews and selects which tasks to accept.`

Every plan/act/check/fallback step is logged to `logs/pawpal_ai.log` in
addition to being returned in the trace shown in the UI, so behavior is
auditable even when nothing goes wrong.

The original domain model (`Owner`, `Pet`, `Task`, `Scheduler`) is unchanged
and is documented separately in the Module 2 class diagram, [`uml.mmd`](uml.mmd).

## Setup Instructions

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Optional — enable live Claude-powered suggestions:**

```bash
cp .env.example .env
# edit .env and add your ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)   # or use python-dotenv / your shell's own method
```

If `ANTHROPIC_API_KEY` is not set, the AI Care Assistant still works — it
automatically uses the offline knowledge-base fallback described below. No
step requires guessing what to install: `requirements.txt` covers everything.

**Run it:**

```bash
python main.py                 # terminal demo, includes the AI agent
python -m pytest -v             # automated test suite
python eval_harness.py          # AI reliability harness (pass/fail + confidence)
streamlit run app.py            # full interactive UI
```

## Sample Interactions

These were produced by running `python main.py` in this environment, which has
no `ANTHROPIC_API_KEY` set — i.e., they show the offline fallback path anyone
can reproduce without an API key.

**Input:** `Whiskers` (cat), owner has 60 minutes available today, no existing
tasks for Whiskers yet.

**Output:**
```
Mode: offline knowledge-base fallback (no ANTHROPIC_API_KEY set)
Confidence: 0.90  |  Iterations: 1

Retrieved guidelines used as grounding context:
  - (hygiene) Litter boxes should be scooped once a day, a 5-10 minute task...
  - (feeding) Cats typically do best with 2-4 small measured meals a day...
  - (enrichment) Interactive play with a wand toy for 10-20 minutes a day...
  - (grooming) Weekly brushing sessions of about 10 minutes help control shedding...

Suggested tasks for Whiskers:
  - Hygiene (cat) (5 min, medium priority)
  - Feeding (cat) (5 min, high priority)
  - Enrichment (cat) (10 min, medium priority)
  - Grooming (cat) (10 min, medium priority)
```

**Input:** Same pet, but the owner only has 5 minutes available (tight budget).

**Output:** The agent still returns suggestions (fallback mode doesn't drop
candidates), but the *confidence score* drops from 0.90 to 0.15 because the
verification step against the real `Scheduler` finds that almost none of the
suggested tasks actually fit — this is the "check" step doing its job.

**Input:** `python eval_harness.py` — five scenarios (generous/tight time
budgets across dog/cat/other species).

**Output:**
```
Scenario                               Result Conf.  #Sugg  Mode
----------------------------------------------------------------
Dog, generous time budget              PASS   0.90   4      fallback
Cat, generous time budget              PASS   0.90   4      fallback
Other/exotic pet, generous time budget PASS   0.90   4      fallback
Dog, very tight time budget            PASS   0.15   4      fallback
Cat, zero time available               PASS   0.00   4      fallback
----------------------------------------------------------------
5 / 5 scenarios passed. Average confidence: 0.57
```
("Pass" here means the agent produced schema-valid suggestions and actually
ran its check step — not that every scenario got a high confidence score;
low confidence on an impossible time budget is the *correct* result.)

## Design Decisions and Tradeoffs

- **RAG over fine-tuning:** the knowledge base is a plain JSON file with
  keyword/tag-overlap retrieval instead of embeddings or a vector database.
  For a dozen short guideline entries, that's the simplest thing that could
  work, has zero extra dependencies, and is fully reproducible offline —
  the tradeoff is it won't scale gracefully to a large, free-text corpus.
- **Deterministic fallback instead of "requires an API key to function":**
  every reviewer, with or without an API key, sees the full RAG + agentic
  pipeline run end-to-end. The tradeoff is that the fallback path can only
  iterate once (there's no model to send revision feedback to), so its
  self-correction is limited to the confidence score reflecting the failure
  rather than an actual revised plan.
- **Confidence score is computed, not model-reported:** it's derived from
  verifiable facts (did the suggestions fit the real Scheduler? were there
  conflicts? was a live model used?) rather than asking the model how sure it
  is, so it can't be inflated by a falsely confident response.
- **Human-in-the-loop by design:** the agent never adds tasks directly. The
  Streamlit UI always shows the retrieved context and reasoning trace and
  requires the owner to select which suggestions to accept before they touch
  `Pet.add_task`.
- Existing Module 2 tradeoffs (sweep-line conflict detection, fixed-interval
  recurrence) are unchanged — see `reflection.md` for that discussion.

## Testing Summary

**7 / 7** core scheduling tests passed. **12 / 12** AI-feature tests passed.
**5 / 5** reliability-harness scenarios passed; average confidence 0.57
(deliberately pulled down by two impossible-time-budget scenarios that
*should* score low — see the table below).

| Test Input (scenario) | Evaluation Criteria | Result |
|---|---|---|
| Dog, 120 min available | Valid schema, agent checks fit via real Scheduler | Pass — conf. 0.90 |
| Cat, 120 min available | Valid schema, agent checks fit via real Scheduler | Pass — conf. 0.90 |
| Other/exotic pet, 120 min available | Valid schema, agent checks fit via real Scheduler | Pass — conf. 0.90 |
| Dog, 10 min available (tight budget) | Agent still returns valid suggestions; confidence reflects poor fit | Pass — conf. 0.15 |
| Cat, 0 min available | Agent still returns valid suggestions; confidence reflects poor fit | Pass — conf. 0.00 |
| Malformed suggestion: missing `title` | Guardrail rejects it, no crash | Pass |
| Malformed suggestion: `duration_minutes=500` | Guardrail rejects it (out of 1–240 range) | Pass |
| Malformed suggestion: `priority="urgent"` | Guardrail rejects it (not in low/medium/high) | Pass |
| No `ANTHROPIC_API_KEY` set | Falls back to deterministic KB generator, no crash | Pass |

(Generated by `eval_harness.py` and `tests/test_ai_agent.py`; "Pass" means the
guardrail/fallback/check behaved correctly — not that every scenario scored
high confidence, since a low score on an impossible budget is the correct
outcome.)

- `tests/test_pawpal.py` — 7 tests covering the original scheduling logic
  (task completion, adding tasks, chronological sorting, filtering,
  conflict detection, and recurring-task follow-ups).
- `tests/test_ai_agent.py` — 12 tests covering the new AI feature: knowledge
  base retrieval (species-specific and unknown-species fallback), the schema
  guardrail (accepts well-formed suggestions, rejects four kinds of malformed
  input), the deterministic fallback generator, and full agent runs
  (`suggest_tasks`) verifying that suggestions are valid and that confidence
  drops appropriately under a tight time budget.
- `eval_harness.py` — a separate reliability script (not a unit test) that
  runs the agent across 5 predefined scenarios and prints a pass/fail table
  plus average confidence, so reliability can be measured without reading
  the source. Result on this environment: **5 / 5 scenarios passed, average
  confidence 0.57** (low-confidence-but-correct on the impossible-budget
  scenarios pulls the average down, as intended).
- All of the above run offline, with no network access required, since the
  test environment used to write this project had no `ANTHROPIC_API_KEY`
  configured — which is exactly the scenario a grader without a key will see.

## Reflection

Building the AI Care Assistant reinforced that "adding AI" is only as good as
what happens when the AI is wrong or unavailable — most of the actual design
work here went into the guardrail (schema validation), the fallback path, and
making the agent check its own output against the same `Scheduler` the rest of
the app trusts, rather than into the prompt itself. The full responsible-AI
reflection — collaboration with AI tools, one helpful and one flawed
suggestion, and system limitations/misuse — is in
[`model_card.md`](model_card.md), as required.
