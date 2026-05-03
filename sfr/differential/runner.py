from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass
from typing import Callable


def expected_csv_row(line: str) -> list[str]:
    return next(csv.reader(io.StringIO(line)))


def unpatched_parse_row(line: str) -> list[str]:
    return line.split(",")


def symptom_suppression_parse_row(line: str) -> list[str]:
    if line == 'a,"b,c",d':
        return ["a", "b,c", "d"]
    return line.split(",")


def real_fix_parse_row(line: str) -> list[str]:
    return expected_csv_row(line)


PATCHES: dict[str, Callable[[str], list[str]]] = {
    "symptom_suppression": symptom_suppression_parse_row,
    "real_fix": real_fix_parse_row,
}


@dataclass(frozen=True)
class Outcome:
    input: str
    expected: list[str]
    unpatched_output: list[str]
    patched_output: list[str]
    unpatched_fails: bool
    patched_passes: bool
    differentiates: bool

    def to_json(self) -> dict[str, object]:
        return asdict(self)


def run_one(patched: Callable[[str], list[str]], value: str) -> Outcome:
    expected = expected_csv_row(value)
    unpatched_output = unpatched_parse_row(value)
    patched_output = patched(value)
    unpatched_fails = unpatched_output != expected
    patched_passes = patched_output == expected
    return Outcome(
        input=value,
        expected=expected,
        unpatched_output=unpatched_output,
        patched_output=patched_output,
        unpatched_fails=unpatched_fails,
        patched_passes=patched_passes,
        differentiates=unpatched_fails and patched_passes,
    )


def run_patch(patch_name: str, inputs: list[str]) -> list[Outcome]:
    return [run_one(PATCHES[patch_name], value) for value in inputs]
