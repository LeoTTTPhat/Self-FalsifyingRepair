from __future__ import annotations


def canonicalize(value: str) -> str:
    return " ".join(value.strip().split())


def unique_new(candidates: list[str], existing: set[str]) -> list[str]:
    seen = {canonicalize(item) for item in existing}
    result: list[str] = []
    for candidate in candidates:
        key = canonicalize(candidate)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result
