# SPDX-License-Identifier: 0BSD
import importlib.util
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
CASES = json.loads((HERE / "semantic_cases.json").read_text(encoding="utf-8"))
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))
RUBRIC = PACKAGE / "workspaces/vc-chief/vc/scoring-rubric.v3.json"
BOUNDARY_CASES = PACKAGE / "tests/g3/scoring_boundary_cases.jsonl"
# vcops.py's display arithmetic, pinned as source text rather than copied as a
# formula. The tests below need the same computation, and a second hand-written
# copy of it is a third place to drift; asserting the line still exists makes a
# change to the runtime's rounding fail here instead of silently changing what
# the test means.
DISPLAY_EXPRESSION = (
    "display_5 = (final_100 / Decimal(20)).quantize(Decimal(" + chr(34) + "0.1" + chr(34) + "))"
)


def load_helper():
    if not str(HELPER) or not HELPER.is_file():
        raise AssertionError("VCOPS_HELPER must name the release vcops.py")
    spec = importlib.util.spec_from_file_location("vcops_g4_subject", HELPER)
    if not spec or not spec.loader:
        raise AssertionError(f"cannot load helper from {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SemanticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helper = load_helper()

    @staticmethod
    def criterion(score, *, state="mixed"):
        return {
            "evidence_state": state,
            "quality_score": score,
            "coverage": "complete",
            "evidence_quality": "high",
            "evidence_fact_ids": [1],
            "counterevidence_fact_ids": [],
            "rationale": "fixture evidence",
            "what_would_change": "a current contradictory verified fact",
        }

    def test_approval_tokens_are_cli_safe_even_when_random_payload_starts_with_hyphen(self):
        with patch.object(self.helper.secrets, "token_urlsafe", return_value="-unsafe-leading-value"):
            token = self.helper.new_approval_token()
        self.assertEqual("vc3_-unsafe-leading-value", token)
        parsed = self.helper.build_parser().parse_args(
            [
                "approval-consume", "--token", token, "--action", "crm.write",
                "--scope", "{}", "--target-system", "crm", "--payload-hash", "0" * 64,
                "--transaction-id", "tx-1", "--consumed-by", "worker-1",
            ]
        )
        self.assertEqual(token, parsed.token)

    def test_numeric_suffix_and_currency_normalization(self):
        function = getattr(self.helper, "parse_numeric_claim", None)
        if not callable(function):
            self.fail("vcops.py must expose parse_numeric_claim(text)")
        for case in CASES["numeric"]:
            with self.subTest(case=case["input"]):
                result = function(case["input"])
                self.assertIsInstance(result, dict)
                self.assertEqual(Decimal(str(result["value"])), Decimal(case["value"]))
                self.assertEqual(result["currency"], case["currency"])

    def test_fact_pair_classification_separates_contradiction_and_trajectory(self):
        function = getattr(self.helper, "classify_fact_pair", None)
        if not callable(function):
            self.fail("vcops.py must expose classify_fact_pair(left, right)")
        for case in CASES["fact_pairs"]:
            with self.subTest(case=case["name"]):
                result = function(case["left"], case["right"])
                if isinstance(result, dict):
                    result = result.get("classification")
                self.assertEqual(result, case["classification"])
                # Both orders, because the model-facing workflow imposes no
                # left/right convention: `cmd_trajectory_check` derives the
                # persisted up/down direction from the bounds precisely so a
                # caller passing the later fact first cannot invert it. An
                # asymmetric classifier would make the recorded contradiction or
                # trajectory depend on argument order, which no caller controls.
                reversed_result = function(case["right"], case["left"])
                if isinstance(reversed_result, dict):
                    reversed_result = reversed_result.get("classification")
                self.assertEqual(
                    reversed_result, case["classification"],
                    f"{case['name']}: classification is not symmetric — "
                    f"{case['left']!r} vs {case['right']!r} gives "
                    f"{case['classification']!r} but the reverse gives "
                    f"{reversed_result!r}",
                )

    def test_score_has_fixed_denominator_and_keeps_unknown_distinct_from_negative(self):
        function = getattr(self.helper, "calculate_score", None)
        if not callable(function):
            self.fail("vcops.py must expose calculate_score(criteria, weights=None)")
        for case in CASES["scores"]:
            with self.subTest(case=case["name"]):
                scores = case.get("criteria", {})
                if "uniform_score" in case:
                    scores = dict.fromkeys(CASES["weights"], case["uniform_score"])
                payload = {name: self.criterion(score) for name, score in scores.items()}
                result = function(
                    payload,
                    CASES["weights"],
                    {
                        "identity_reliable": True,
                        "contradiction_check_complete": True,
                        "trajectory_check_complete": True,
                    },
                )
                self.assertIsInstance(result, dict)
                self.assertEqual(Decimal(str(result["final_100"])), Decimal(str(case["expected_score"])))
                self.assertEqual(result["recommendation"], case["expected_recommendation"])
        one_dimension = function(
            {"founder_team_signal": self.criterion(5, state="positive")},
            CASES["weights"],
            {"identity_reliable": True},
        )
        self.assertEqual(Decimal(str(one_dimension["raw_100"])), Decimal("15"), "missing criteria must not redistribute weight")
        self.assertIn("market_buyer_timing", one_dimension.get("missing_criteria", []))
        missing_market = next(item for item in one_dimension["criteria"] if item["name"] == "market_buyer_timing")
        self.assertIsNone(missing_market["quality_score"])
        negative_market = function(
            {
                "founder_team_signal": self.criterion(5, state="positive"),
                "problem_product_depth": self.criterion(4, state="positive"),
                "market_buyer_timing": self.criterion(0, state="negative"),
            },
            CASES["weights"],
            {"identity_reliable": True},
        )
        negative_item = next(item for item in negative_market["criteria"] if item["name"] == "market_buyer_timing")
        self.assertEqual(Decimal("0"), Decimal(str(negative_item["quality_score"])))
        self.assertEqual("negative", negative_item["evidence_state"])
        self.assertGreater(negative_market["coverage"], one_dimension["coverage"])

    def test_score_rejects_out_of_range_values(self):
        function = self.helper.calculate_score
        error_types = (TypeError, ValueError, self.helper.VcopsError)
        with self.assertRaises(error_types):
            function({"founder_team_signal": self.criterion(6)}, CASES["weights"], {"identity_reliable": True})
        with self.assertRaises(error_types):
            function({"founder_team_signal": self.criterion(-0.1)}, CASES["weights"], {"identity_reliable": True})

    def test_adjustments_overrides_and_evidence_binding(self):
        criteria = {name: self.criterion(4.1, state="positive") for name in CASES["weights"]}
        adjusted = self.helper.calculate_score(
            criteria,
            CASES["weights"],
            {
                "identity_reliable": True,
                "contradiction_check_complete": True,
                "trajectory_check_complete": True,
                "adjustments": [
                    {"kind": "material_unresolved_contradiction", "points": -10, "reason": "open conflict", "evidence_fact_ids": [1]},
                    {"kind": "trajectory", "points": 5, "reason": "cited growth", "evidence_fact_ids": [1]},
                ],
            },
        )
        self.assertEqual(Decimal("77.000"), Decimal(str(adjusted["final_100"])))
        self.assertEqual("research_deeper", adjusted["recommendation"])
        review = self.helper.calculate_score(criteria, CASES["weights"], {"identity_reliable": True, "blocking_contradiction": True})
        self.assertEqual("needs_human_review", review["recommendation"])
        excluded = self.helper.calculate_score(criteria, CASES["weights"], {"identity_reliable": True, "hard_exclusion": True})
        self.assertEqual("pass", excluded["recommendation"])
        with self.assertRaises(self.helper.VcopsError):
            unsupported = self.criterion(5, state="positive")
            unsupported["evidence_fact_ids"] = []
            self.helper.calculate_score(
                {"founder_team_signal": unsupported},
                CASES["weights"],
                {"identity_reliable": True},
            )
        with self.assertRaises(self.helper.VcopsError):
            self.helper.calculate_score(criteria, {**CASES["weights"], "founder_team_signal": 14}, {"identity_reliable": True})


    def test_no_display_value_can_determine_a_recommendation(self):
        """`display_5` spans a band edge, so it never implies a single band.

        The rubric says there is "deliberately no display-scale equivalent" of the
        recommendation intervals, and that one must never read a recommendation off
        a display value. That was prose only, and three shipped artifacts
        contradicted it: `tests/g3/scoring_boundary_cases.jsonl` (one of the twenty
        hash-pinned reviewed artifacts, byte-verified by the G8 gate),
        `tests/g3/README.md` and `workspaces/vc-chief/vc/eval_fixtures.md` each
        mapped a display value to exactly one band, and no test bound any of them.

        `display_5` rounds `final_100 / 20` to one decimal, so each display value
        covers a two-point `final_100` window, and that window straddles a band
        edge rather than starting at it. Measured through the shipped helper:
        49.900 and 50.000 both display 2.5 and band `pass` / `watch`; 65.900 and
        66.000 both display 3.3 and band `watch` / `research_deeper`; 81.001 and
        82.000 both display 4.1 and band `research_deeper` / `high_priority`.

        Asserted as "more than one band per display value" -- the property that
        makes a display-to-band table impossible to write -- rather than as six
        independent expectations a future edit could satisfy one at a time.
        """
        source = HELPER.read_text(encoding="utf-8")
        # assertTrue, not assertIn: assertIn appends `safe_repr(container)` to the
        # message without truncating, and vcops.py is ~340 KB, so a failure dumped
        # 347,859 characters (measured). That is the defect class this wave
        # produced twice at 39-72 KB; the container is not the interesting part.
        self.assertTrue(
            DISPLAY_EXPRESSION in source,
            "vcops.py's display arithmetic changed; re-derive the straddle below "
            "against the new rounding instead of trusting these constants",
        )
        rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        straddle: dict[str, set[str]] = {}
        for raw in ("49.900", "50.000", "65.900", "66.000", "81.001", "82.000"):
            final_100 = Decimal(raw).quantize(Decimal("0.001"))
            display_5 = (final_100 / Decimal(20)).quantize(Decimal("0.1"))
            straddle.setdefault(str(display_5), set()).add(
                self.helper._recommendation_for_score(final_100, rubric)
            )
        for display, bands in sorted(straddle.items()):
            with self.subTest(display_5=display):
                self.assertGreater(
                    len(bands), 1,
                    f"display_5={display} resolved to the single band {bands}. If "
                    f"that became true of the whole two-point window then the "
                    f"rubric's 'deliberately no display-scale equivalent' needs "
                    f"revisiting -- but until it does, a display value must never "
                    f"identify a recommendation",
                )

    def test_the_reviewed_boundary_fixture_is_on_the_unrounded_scale(self):
        """The hash-pinned boundary fixture must not carry display-scale values.

        No in-package executor replays `tests/g3/scoring_boundary_cases.jsonl` --
        `tests/g3/README.md` says so, and its only code references are the
        `check_customization.py` and G8 byte verifications -- so nothing else can
        notice it drifting back onto the 0.0-5.0 display scale. It shipped that
        way, asserting one band per display value, which the straddle above shows
        is untrue of half of each window.

        Every `expected` is re-derived through the shipped helper here, so this is
        also the check that the fixture's bands are the runtime's bands.
        """
        rubric = json.loads(RUBRIC.read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in BOUNDARY_CASES.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(rows, "the reviewed boundary fixture is empty")
        for row in rows:
            with self.subTest(case=row.get("id")):
                self.assertNotIn(
                    "score", row,
                    "the ambiguous `score` field is back. Name the scale: the "
                    "recommendation is decided from unrounded `final_100`, and a "
                    "display value spans two bands.",
                )
                self.assertIn("final_100", row, "every case must name its scale")
                value = Decimal(str(row["final_100"]))
                self.assertTrue(
                    Decimal(0) <= value <= Decimal(100),
                    f"{row['id']}'s final_100 {value} is outside [0, 100], so it "
                    f"is a display-scale value sitting on a final_100 field",
                )
                self.assertEqual(
                    row["expected"],
                    self.helper._recommendation_for_score(
                        value.quantize(Decimal("0.001")), rubric
                    ),
                    f"{row['id']}'s expected band is not what the shipped helper "
                    f"returns for final_100={value}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
