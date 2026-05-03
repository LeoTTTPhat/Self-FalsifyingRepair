from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PredicateResult:
    accepted: bool
    error: str | None = None


def run_predicate(predicate_source: str, value: str, timeout_seconds: float = 1.0) -> PredicateResult:
    """Run an agent-emitted covers(value) predicate outside this process."""
    program = (
        "import json\n"
        f"{predicate_source}\n"
        f"value = json.loads({json.dumps(json.dumps(value))})\n"
        'print(json.dumps({"accepted": bool(covers(value))}))\n'
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", program],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return PredicateResult(False, "timeout")

    if completed.returncode != 0:
        return PredicateResult(False, completed.stderr.strip() or "predicate failed")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return PredicateResult(False, f"invalid predicate output: {exc}")

    return PredicateResult(bool(payload.get("accepted")))
