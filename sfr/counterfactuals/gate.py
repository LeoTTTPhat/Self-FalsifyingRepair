from __future__ import annotations

from sfr.hypothesis.sandbox import run_predicate


def predicate_gate(predicate_source: str, candidates: list[str]) -> list[str]:
    return [candidate for candidate in candidates if run_predicate(predicate_source, candidate).accepted]
