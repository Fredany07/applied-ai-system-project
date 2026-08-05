# PawPal+ Project Reflection

## 1. System Design

**a. Initial design**

The initial UML (`uml.mmd`) centered on four classes: `Owner` (name, minutes
available, preferences, the pets they own), `Pet` (name, species, its list of
tasks), `Task` (title, duration, priority, recurrence), and `Scheduler`
(takes tasks + a time budget and produces an ordered plan). `Owner` owns
`Pet`s, `Pet`s own `Task`s, and `Scheduler` is a separate object that reads
tasks rather than living inside `Owner` — keeping "who owns the data" and
"who decides the plan" as separate responsibilities from the start.

**b. Design changes**

The biggest change from the initial design was giving `Scheduler` a
`from_owner()` classmethod instead of requiring callers to manually flatten
`owner.pets[*].tasks` into a list every time. Early versions of `app.py` and
`main.py` were doing that flattening inline, which meant the same "collect
all tasks" logic was duplicated in two places and easy to get out of sync.
Moving it into `Owner.get_all_tasks()` and exposing `Scheduler.from_owner()`
made the Scheduler's entry point a single line at every call site.

---

## 2. Scheduling Logic and Tradeoffs

**a. Constraints and priorities**

The scheduler considers three constraints: the owner's available minutes
today, each task's priority (low/medium/high, used to decide what gets
dropped when time is short), and duration. Priority mattered most because a
busy owner needs the *important* things (feeding, meds) to survive a time
crunch even if something lower-stakes (playtime) gets skipped — that's why
`sort_by_priority()` ranks by priority first and only breaks ties by
duration, and `filter_by_time()` greedily fills the time budget in that
order.

**b. Tradeoffs**

One deliberate tradeoff is in **conflict detection** (`Scheduler.find_conflicts()`).
It sorts tasks by start time and only compares each task against the *next* one
in that order — an O(n log n) sweep-line check rather than an O(n²) comparison of
every possible pair. As a result, when three or more tasks all overlap, it reports
them as a chain of adjacent pairs (A–B, B–C) instead of every combination (A–C too).

This is reasonable for a single owner's daily plan: the task count is small, the
performance win is minor at this scale, but the *readability* win is real — the
owner fixes conflicts in chronological order, one neighbor at a time, which mirrors
how they'd actually rearrange their day. A second tradeoff: recurring tasks advance
by a fixed `timedelta` (today + 1 day / + 1 week) and don't account for calendar
skips like "weekdays only," which keeps the logic simple and predictable.

---

## 3. AI Collaboration

**a. How you used AI**

AI tools were most useful for two things: brainstorming the plan → act →
check structure for the Module 3 AI Care Assistant (rather than a single
one-shot model call), and reviewing code for dead/leftover logic after
refactors. The most useful prompts were narrow and code-anchored — e.g.
"here's my agent loop, what happens if the model returns malformed JSON?" —
rather than open-ended "improve my code" requests.

**b. Judgment and verification**

The clearest case where I didn't accept an AI suggestion as-is: an early
version of the agent's design let it auto-accept its own high-confidence
suggestions directly into a pet's task list. I rejected that because it
removes the owner from a decision about their own pet's care, and instead
required every suggestion to go through an explicit human accept step in the
UI regardless of confidence. Full details are in `model_card.md`, since that
file carries the graded AI-collaboration reflection for this project.

---

## 4. Testing and Verification

**a. What you tested**

Core scheduling behaviors — task completion, adding tasks, chronological
sorting with unscheduled tasks last, filtering by pet/status, sweep-line
conflict detection, and recurring-task follow-up creation — plus, for the
Module 3 AI feature, knowledge-base retrieval, schema-guardrail validation
(both accepting well-formed input and rejecting four kinds of malformed
input), the deterministic fallback path, and full agent runs checking that
confidence drops appropriately under a tight time budget. These matter
because a scheduler that silently drops a high-priority task, or an AI
feature that silently accepts malformed model output, would fail exactly
where an owner would trust it most.

**b. Confidence**

I'm confident the core scheduler and the AI guardrails behave correctly for
the cases tested. Edge cases I'd test next with more time: three-or-more
overlapping tasks (to see the full adjacent-pair vs. all-pairs tradeoff in
practice), weekly recurrence chains, and a live-API run of the AI Care
Assistant's revision loop (all current AI tests exercise the offline fallback
path, since no API key was available while building this).

---

## 5. Reflection

**a. What went well**

The clean separation between `Scheduler` and the data model made it
straightforward to reuse the *exact same* scheduling logic inside the new AI
agent's "check" step — the agent doesn't have its own notion of what fits,
it asks the real `Scheduler`, which means the AI suggestions are checked
against the same rules the rest of the app already trusts.

**b. What you would improve**

I'd expand the pet-care knowledge base considerably (age ranges, breed
notes, more species) and let the retrieval step take existing tasks into
account more precisely instead of the current rough title-based proxy, so
suggestions get better at filling actual gaps rather than sometimes
repeating a category the pet already has covered.

**c. Key takeaway**

The most important thing I learned: an "AI feature" is judged by what
happens when it's wrong or unavailable, not by what happens when it works.
Most of the real design effort here went into the guardrail, the fallback,
and giving the agent a way to check its own output against ground truth —
not into the prompt itself.
