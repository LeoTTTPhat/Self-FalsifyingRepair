from __future__ import annotations

from sfr.differential.runner import Outcome


def differentiation_score(outcomes: list[Outcome]) -> float:
    if not outcomes:
        return 0.0
    return sum(outcome.differentiates for outcome in outcomes) / len(outcomes)


def subrates(outcomes: list[Outcome]) -> dict[str, float]:
    if not outcomes:
        return {"unpatched_fail_rate": 0.0, "patched_pass_rate": 0.0, "delta": 0.0}
    denominator = len(outcomes)
    return {
        "unpatched_fail_rate": sum(outcome.unpatched_fails for outcome in outcomes) / denominator,
        "patched_pass_rate": sum(outcome.patched_passes for outcome in outcomes) / denominator,
        "delta": differentiation_score(outcomes),
    }
