import importlib.util
import json
import os
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
CASES = json.loads((HERE / "semantic_cases.json").read_text(encoding="utf-8"))
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))


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
        self.assertTrue(callable(function), "vcops.py must expose parse_numeric_claim(text)")
        for case in CASES["numeric"]:
            with self.subTest(case=case["input"]):
                result = function(case["input"])
                self.assertIsInstance(result, dict)
                self.assertEqual(Decimal(str(result["value"])), Decimal(case["value"]))
                self.assertEqual(result["currency"], case["currency"])

    def test_fact_pair_classification_separates_contradiction_and_trajectory(self):
        function = getattr(self.helper, "classify_fact_pair", None)
        self.assertTrue(callable(function), "vcops.py must expose classify_fact_pair(left, right)")
        for case in CASES["fact_pairs"]:
            with self.subTest(case=case["name"]):
                result = function(case["left"], case["right"])
                if isinstance(result, dict):
                    result = result.get("classification")
                self.assertEqual(result, case["classification"])

    def test_score_has_fixed_denominator_and_keeps_unknown_distinct_from_negative(self):
        function = getattr(self.helper, "calculate_score", None)
        self.assertTrue(callable(function), "vcops.py must expose calculate_score(criteria, weights=None)")
        for case in CASES["scores"]:
            with self.subTest(case=case["name"]):
                scores = case.get("criteria", {})
                if "uniform_score" in case:
                    scores = {name: case["uniform_score"] for name in CASES["weights"]}
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
