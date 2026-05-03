from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Hypothesis:
    summary: str
    predicate_source: str
    rationale: str
    confidence: float | None = None

    def to_json(self) -> dict[str, object]:
        return asdict(self)
