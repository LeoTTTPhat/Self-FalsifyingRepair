from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from sfr.counterfactuals.distinctness import unique_new
from sfr.counterfactuals.gate import predicate_gate
from sfr.differential.delta import subrates
from sfr.differential.runner import PATCHES, run_patch
from sfr.hypothesis.schema import Hypothesis
from sfr.hypothesis.vacuous_check import is_vacuous


FAILING_INPUT = 'a,"b,c",d'
COUNTERFACTUAL_BUDGET = 8
DELTA_THRESHOLD = 0.5

PREDICATE_SOURCE = """\
def covers(value: str) -> bool:
    in_quotes = False
    for index, char in enumerate(value):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and in_quotes:
            return True
    return False
"""

COUNTERFACTUAL_CANDIDATES = [
    'x,"y,z,w",p',
    '"a,b","c"',
    'left,"middle,with,commas",right',
    '"leading,comma",tail',
    'head,"trailing,comma"',
    '1,"2,3",4',
    '"nested,looking",plain,"again,here"',
    'alpha,"beta,gamma",delta',
]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def main() -> None:
    start = time.perf_counter()
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path("runs") / "smoketest" / timestamp

    hypothesis = Hypothesis(
        summary="The parser splits on commas without respecting commas inside double-quoted CSV fields.",
        predicate_source=PREDICATE_SOURCE,
        rationale=(
            "Any row containing a comma while the parser is inside double quotes should be treated "
            "as a single CSV field by a correct implementation."
        ),
        confidence=0.91,
    )

    candidates = unique_new(COUNTERFACTUAL_CANDIDATES, {FAILING_INPUT})
    counterfactuals = predicate_gate(hypothesis.predicate_source, candidates)[:COUNTERFACTUAL_BUDGET]
    if len(counterfactuals) < 4:
        raise SystemExit("smoketest failed: fewer than four valid counterfactuals")

    vacuous = is_vacuous(hypothesis.predicate_source, FAILING_INPUT)
    patch_results = {}
    for patch_name in PATCHES:
        outcomes = run_patch(patch_name, counterfactuals)
        rates = subrates(outcomes)
        patch_results[patch_name] = {
            "accepted": rates["delta"] >= DELTA_THRESHOLD,
            "rates": rates,
            "outcomes": [outcome.to_json() for outcome in outcomes],
        }

    elapsed_seconds = time.perf_counter() - start
    manifest = {
        "bug_id": "smoketest",
        "timestamp": timestamp,
        "elapsed_seconds": round(elapsed_seconds, 4),
        "failing_input": FAILING_INPUT,
        "k": len(counterfactuals),
        "delta_threshold": DELTA_THRESHOLD,
        "hypothesis_sha256": hashlib.sha256(
            hypothesis.predicate_source.encode("utf-8")
        ).hexdigest(),
        "vacuous_hypothesis": vacuous,
    }

    write_json(run_dir / "config.json", {"k": COUNTERFACTUAL_BUDGET, "delta_threshold": DELTA_THRESHOLD})
    write_json(run_dir / "hypothesis.json", hypothesis.to_json())
    for index, value in enumerate(counterfactuals):
        write_text(run_dir / "counterfactuals" / f"{index}.txt", value + "\n")
    write_json(run_dir / "differential.json", patch_results)
    write_json(run_dir / "result.json", {"manifest": manifest, "patches": patch_results})
    write_text(Path("runs") / "smoketest" / "LATEST", str(run_dir) + "\n")

    print(json.dumps({"run_dir": str(run_dir), "manifest": manifest, "patches": patch_results}, indent=2))


if __name__ == "__main__":
    main()
