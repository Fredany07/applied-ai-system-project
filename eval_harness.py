"""Reliability harness for the AI Care Assistant.

Runs the agent (ai_care_assistant.CareAgent) against a fixed set of
scenarios and prints a pass/fail table plus confidence stats. This is what
Section 4 ("prove your AI works, don't just say so") and the optional Test
Harness stretch feature point to — a separate, reproducible measurement of
reliability, distinct from the pytest unit tests.

A scenario "passes" when:
  - the agent returns at least one suggested task, AND
  - every suggested task independently satisfies the same schema guardrail
    used inside the agent (valid duration/priority), AND
  - the reasoning trace contains a "check" step (i.e. the agent actually
    verified its plan against the Scheduler rather than skipping straight to
    an answer).

Run with:  python eval_harness.py
"""

from __future__ import annotations

from dataclasses import dataclass

from pawpal_system import Owner, Pet
from ai_care_assistant import CareAgent, _validate_suggestion


@dataclass
class Scenario:
    name: str
    species: str
    minutes_available: int


SCENARIOS = [
    Scenario("Dog, generous time budget", "dog", 120),
    Scenario("Cat, generous time budget", "cat", 120),
    Scenario("Other/exotic pet, generous time budget", "other", 120),
    Scenario("Dog, very tight time budget", "dog", 10),
    Scenario("Cat, zero time available", "cat", 0),
]


def run_scenario(agent: CareAgent, scenario: Scenario) -> dict:
    owner = Owner(name="EvalOwner", minutes_available=scenario.minutes_available)
    pet = Pet(name="EvalPet", species=scenario.species)
    owner.add_pet(pet)

    result = agent.suggest_tasks(pet, owner)

    schema_ok = all(
        _validate_suggestion(
            {
                "title": t.title,
                "duration_minutes": t.duration_minutes,
                "priority": t.priority,
            }
        )
        is not None
        for t in result.suggested_tasks
    )
    checked = any(step.stage == "check" for step in result.trace)
    passed = bool(result.suggested_tasks) and schema_ok and checked

    return {
        "scenario": scenario.name,
        "passed": passed,
        "confidence": result.confidence,
        "n_suggestions": len(result.suggested_tasks),
        "used_llm": result.used_llm,
    }


def main() -> None:
    agent = CareAgent()
    rows = [run_scenario(agent, s) for s in SCENARIOS]

    print("=" * 70)
    print("PawPal+ AI Care Assistant — Reliability Harness")
    print("=" * 70)
    header = f"{'Scenario':<38} {'Result':<6} {'Conf.':<6} {'#Sugg':<6} {'Mode'}"
    print(header)
    print("-" * len(header))
    for row in rows:
        mode = "live" if row["used_llm"] else "fallback"
        result_str = "PASS" if row["passed"] else "FAIL"
        print(
            f"{row['scenario']:<38} {result_str:<6} {row['confidence']:<6.2f} "
            f"{row['n_suggestions']:<6} {mode}"
        )

    n_passed = sum(1 for r in rows if r["passed"])
    avg_conf = sum(r["confidence"] for r in rows) / len(rows)
    print("-" * len(header))
    print(f"{n_passed} / {len(rows)} scenarios passed. Average confidence: {avg_conf:.2f}")


if __name__ == "__main__":
    main()
