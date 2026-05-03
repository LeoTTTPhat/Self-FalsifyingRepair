from __future__ import annotations

import unittest

from sfr.counterfactuals.gate import predicate_gate
from sfr.differential.delta import subrates
from sfr.differential.runner import run_patch
from sfr.harness.smoketest import COUNTERFACTUAL_CANDIDATES, FAILING_INPUT, PREDICATE_SOURCE
from sfr.hypothesis.vacuous_check import is_vacuous


class SmokeTestComponents(unittest.TestCase):
    def test_predicate_accepts_counterfactuals_but_not_plain_csv(self) -> None:
        accepted = predicate_gate(PREDICATE_SOURCE, COUNTERFACTUAL_CANDIDATES + ["a,b,c"])
        self.assertIn('x,"y,z,w",p', accepted)
        self.assertNotIn("a,b,c", accepted)

    def test_predicate_is_not_vacuous(self) -> None:
        self.assertFalse(is_vacuous(PREDICATE_SOURCE, FAILING_INPUT))

    def test_bad_patch_rejected_and_real_fix_accepted(self) -> None:
        counterfactuals = predicate_gate(PREDICATE_SOURCE, COUNTERFACTUAL_CANDIDATES)
        bad = subrates(run_patch("symptom_suppression", counterfactuals))
        good = subrates(run_patch("real_fix", counterfactuals))
        self.assertLess(bad["delta"], 0.5)
        self.assertGreaterEqual(good["delta"], 0.75)


if __name__ == "__main__":
    unittest.main()
