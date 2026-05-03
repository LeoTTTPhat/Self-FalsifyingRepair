from __future__ import annotations

from sfr.hypothesis.sandbox import run_predicate


def perturbed_strings(seed: str) -> list[str]:
    return [
        seed.replace("a", "x", 1),
        seed.replace("b,c", "y,z,w", 1),
        '"a,b","c"',
        'left,"middle,with,commas",right',
        'plain,unquoted,row',
        "",
    ]


def is_vacuous(predicate_source: str, failing_input: str) -> bool:
    if not run_predicate(predicate_source, failing_input).accepted:
        return True
    accepted = [
        candidate
        for candidate in perturbed_strings(failing_input)
        if candidate != failing_input and run_predicate(predicate_source, candidate).accepted
    ]
    return len(accepted) == 0
