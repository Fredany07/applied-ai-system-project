# Model Card & Responsible-AI Reflection — PawPal+ AI Care Assistant

## What the AI component does

`ai_care_assistant.py` retrieves short pet-care guidelines relevant to a pet's
species (RAG), asks a language model (Claude, via the Anthropic API) to draft
new care tasks grounded in those guidelines, verifies the draft against the
owner's real time budget using the app's own `Scheduler`, and — if the draft
doesn't fit — asks the model to revise, up to three times. If no API key is
configured or the API call fails, it falls back to a deterministic generator
built directly from the retrieved guidelines.

## Limitations and Biases

- **Knowledge base coverage is narrow.** `data/care_knowledge_base.json`
  contains a dozen hand-written entries for dogs, cats, and a generic "other"
  category. It reflects generalized, mainstream pet-care advice; it does not
  account for breed-specific needs, medical conditions, age (puppy/kitten vs.
  senior), or regional/cultural differences in pet care norms. An owner of an
  unusual pet, or a pet with special needs, will get generic or thin
  suggestions (the "other" species entries are especially sparse).
  Species not in the dataset silently fall back to only the "any"-tagged
  entries — reasonably graceful, but limited.
- **Durations and priorities are approximations.** Suggested task durations
  come from guideline text or a fallback default; they are estimates, not
  measurements, and shouldn't be read as authoritative time requirements for
  any specific animal.
- **Not veterinary or medical advice.** The knowledge base includes a general
  medication-reminder entry, but nothing here should be treated as guidance on
  what medication a pet needs, dosing, or how to handle a medical situation —
  it is scheduling support, not health guidance.
- **Fallback mode is less tailored.** The offline fallback (no API key)
  produces the same suggestions for any pet of a given species regardless of
  its existing task list, since it can't reason about context the way a live
  model call can. The confidence score already accounts for this (fallback
  runs score slightly lower), but it's a real capability gap, not just a
  scoring artifact.

## Potential Misuse and Mitigations

- **Over-trusting AI-generated schedules for a pet's actual welfare needs**
  (e.g., an owner skipping their own judgment about their specific animal in
  favor of generic suggestions) is the main risk. Mitigation: the UI always
  shows the retrieved guideline text next to each suggestion so the owner can
  see *why* something was suggested and judge it themselves, and no suggested
  task is ever added automatically — the owner must explicitly select and
  confirm it.
- **Prompt injection via pet/task names.** Since pet names and task titles
  are user-supplied strings that get interpolated into the model prompt, a
  user could in principle try to include instruction-like text in a pet's
  name to influence the model's output. Mitigation: model output is never
  executed as code or trusted structurally beyond the JSON schema check —
  even an adversarial prompt can only produce a task suggestion, which still
  has to pass duration/priority/title validation and still requires human
  acceptance before it affects anything.
- **API cost/availability abuse.** The iteration loop is capped at
  `MAX_ITERATIONS = 3` specifically so a pathological case (a model that never
  produces a fitting plan) can't loop indefinitely or run up API costs.

## What Surprised Me While Testing

Testing the tight-time-budget scenarios (`eval_harness.py`) was the most
useful part of building this. It would have been easy to just check "did the
agent return *something*" and call that reliability. Once budgets got small
(5 minutes, 0 minutes), the fallback path kept returning the same four
suggestions regardless — because the fallback doesn't re-plan, it only
reports a lower confidence score. That's the correct behavior for a
fallback, but it was a good reminder that "the AI produced an answer" and
"the AI's answer is trustworthy" are different things, and only the second
one is worth measuring.

## AI Collaboration

**A helpful suggestion I accepted:** while designing the agent's self-check
step, an AI coding assistant suggested computing the confidence score from
verifiable facts (fit ratio against the real Scheduler, conflict count,
whether a live model was used) instead of asking the model to self-report a
confidence number. That was a clear improvement — a model can't inflate a
score it never gets to produce, and the number stays meaningful even in
fallback mode where there's no model to ask.

**A flawed suggestion I did not accept as-is:** the AI assistant initially
suggested letting the agent auto-accept its own suggestions into the pet's
task list whenever confidence was above a threshold (e.g., "if confidence >
0.7, add automatically"). I rejected this: it would mean an AI system was
silently making decisions about a living animal's care schedule without the
owner ever seeing or approving them, which conflicts directly with the
human-in-the-loop principle the rest of this project is built around. I kept
the confidence score purely informational and required an explicit accept
step for every suggestion, regardless of how confident the agent is.
