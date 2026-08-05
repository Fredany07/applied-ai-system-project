# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

Add the Module 3 required AI feature to PawPal+ so that it's genuinely
integrated into the app rather than a standalone script: an AI Care
Assistant that suggests new care tasks, grounded in retrieved pet-care
guidelines, and checks its own suggestions against the real time-budget
scheduler before presenting them.

**What did the agent do?**

1. Built `data/care_knowledge_base.json`, a small curated set of species-tagged
   pet-care guidelines to retrieve from.
2. Built `ai_care_assistant.py` containing `CareKnowledgeBase` (retrieval),
   `LLMClient` (isolated Anthropic API wrapper), and `CareAgent`
   (`suggest_tasks`, implementing plan → act → check → revise).
3. Wired schema validation (`_validate_suggestion`) so any model output has to
   pass type/range checks before becoming a real `Task`.
4. Added a deterministic fallback path (`_fallback_suggestions`) so the
   feature works with no API key.
5. Wrote `tests/test_ai_agent.py` and `eval_harness.py`, and ran them —
   *live agent reasoning trace from an actual run, captured verbatim*:

   ```
   [plan] Retrieved 4 guideline(s) for Whiskers (cat) to ground task suggestions.
   [fallback] No ANTHROPIC_API_KEY configured; using deterministic knowledge-base fallback instead of a live model call.
   [check] Iteration 1: 4/4 suggestion(s) fit the 60-minute budget; 0 scheduling conflict(s) found.
   [check] Final confidence: 0.90 (used_llm=False, iterations=1).
   ```

6. Integrated the agent into `app.py` (interactive review + accept UI) and
   `main.py` (terminal demo), so accepted suggestions flow through the exact
   same `Scheduler` as manually-entered tasks.

**What did I have to verify or fix manually?**

- The agent's first draft of `_validate_suggestion` returned a bare `Task`
  on success and `None` on failure, but the calling code also needed the
  category string for retrieval-gap tracking — I corrected the return type
  to `tuple[Task, str] | None` and fixed the type hint that had drifted out
  of sync with the implementation.
- An early version computed `existing_categories` twice (a leftover
  placeholder line using task priority instead of title), which I removed
  after noticing it during a code review pass — it didn't break anything
  functionally since the second assignment overwrote the first, but it was
  dead code that would have confused a future reader.
- I manually ran the full pipeline (`main.py`, the test suite, and
  `eval_harness.py`) in an environment with no network access and no API
  key, specifically to confirm the fallback path — the exact condition a
  grader without a key would hit — produces valid, schema-passing
  suggestions and a sensible (lower) confidence score rather than crashing or
  silently returning nothing.

---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | | |
| **Prompt** | | |
| **Response summary** | | |
| **What was useful** | | |
| **Problems noticed** | | |
| **Decision** | | |

**Which approach did you use in your final implementation and why?**

<!-- Your conclusion -->
