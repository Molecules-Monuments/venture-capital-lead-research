# SPDX-License-Identifier: Apache-2.0
"""Pin vcops' decision arithmetic, and the artifacts that quote its results.

The release `vcops.py` named by `VCOPS_HELPER` is imported by path and its
pure functions are driven directly, so what is under test here is the
computation rather than the CLI: numeric suffix and currency normalisation,
the fact-pair classifier, `calculate_score`, and the `vc3_` token prefix that
keeps a random payload beginning with `-` from being read as an option.
`semantic_cases.json` supplies the table-driven cases; the weights, bands and
thresholds are read from `workspaces/vc-chief/vc/scoring-rubric.v3.json`
rather than restated, so a deployment that customises the rubric — it ships
`sample_only_must_customize` — gets its own numbers checked.

Two properties are asserted because no caller controls them. Classification
must be symmetric: `cmd_trajectory_check` derives the persisted up/down
direction from the bounds precisely so a caller passing the later fact first
cannot invert it, and an asymmetric classifier would make the recorded
contradiction or trajectory depend on argument order. And a criterion that is
absent must not redistribute its weight onto the ones that are present, which
is what keeps "not yet evidenced" distinct from "scored zero".

The rest of the file is about which scale a recommendation may be read from.
`display_5` rounds `final_100 / 20` to one decimal, so each display value
covers a two-point window on the deciding scale, and a window that straddles a
band edge belongs to two bands. The rubric says as much in prose — there is
"deliberately no display-scale equivalent" — but three shipped artifacts
contradicted it, each mapping a display value to exactly one band, and no test
bound any of them. One of the three,
`tests/g3/scoring_boundary_cases.jsonl`, is hash-pinned by
`check_customization.py` and byte-verified by the G8 gate yet was replayed by
nothing, so it could drift onto the display scale with every gate still green.
The last two methods here are its executor.

Both of those methods are shaped to survive a customised rubric. The straddle
is asserted as a disjunction over whatever edges the rubric in force declares
rather than a universal over them, because the universal form failed the
offline gate on a documented customisation path and one straddling edge is
already enough to make a display-to-band table impossible to write.
`vcops.py`'s rounding line is pinned as source text instead of copied as a
formula, so a change to the runtime's arithmetic fails here rather than
quietly changing what these constants mean. And the fixture's values are tied
to the rubric's own edges, because re-deriving each `expected` through the
helper proves only internal consistency: measured, a fixture rewritten wholly
onto the display scale passed that check.
"""

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


    def test_a_straddled_band_edge_makes_a_display_to_band_table_impossible(self):
        """At least one band edge falls INSIDE a display value, not on its boundary.

        Stated precisely, because the obvious phrasing is false twice over. First,
        of the 51 display values `display_5` can take, 48 DO determine the
        recommendation exactly (`3.0` is always `watch`); only the three sitting on
        a shipped band edge — `2.5`, `3.3`, `4.1` — map to two bands each. Three is
        enough: a display-to-band table cannot be written, and a fixture asserting
        one band for `4.1` is wrong for half of that value's window.

        Second, and this is why the method is no longer named `every_band_edge`:
        the body asserts a DISJUNCTION over whatever edges the rubric in force
        declares, not a universal over them. The three shipped edges all straddle,
        but an operator's edges need not — an integer edge fails to straddle
        exactly when it is congruent to 3 mod 4 — and a name promising a universal
        described a check that does not make one. The reasoning is set out at the
        assertion.

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

        Asserted as "at least one display value covers more than one band" -- the
        property that makes a display-to-band table impossible to write -- rather
        than as six independent expectations a future edit could satisfy one at a
        time.
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
        quantum = Decimal("0.001")

        def display_of(value: Decimal) -> Decimal:
            return (value / Decimal(20)).quantize(Decimal("0.1"))

        # Derived from the rubric's own interval minima, not a hand-listed set of
        # probe points: a deployment that customises its bands (they are
        # `sample_only_must_customize`) gets its own edges checked, and a band
        # edge added or moved is covered without editing this test.
        edges = [
            Decimal(str(interval["minimum"]))
            for interval in rubric["recommendation_intervals"]
            if Decimal(str(interval["minimum"])) > 0
        ]
        self.assertTrue(edges, "the rubric declares no interior band edge")

        # Each edge must really BE an edge — that keeps the derivation honest.
        for edge in edges:
            below = (edge - quantum).quantize(quantum)
            with self.subTest(edge=str(edge)):
                self.assertNotEqual(
                    self.helper._recommendation_for_score(below, rubric),
                    self.helper._recommendation_for_score(edge, rubric),
                    f"final_100={below} and {edge} band identically, so "
                    f"{edge} is not a band edge and this check is testing nothing",
                )

        # The straddle is asserted as a DISJUNCTION, not of every edge. Requiring
        # it of every edge is a stronger claim than the rubric makes and than the
        # arithmetic supports: `display_5` rounds to one decimal with
        # ROUND_HALF_EVEN, so an edge E straddles only when E/20 does not land on a
        # .x5 boundary. Of the 99 integer edges an operator could choose, 25 — every
        # E congruent to 3 mod 4 — do not straddle. The rubric is
        # `sample_only_must_customize` and CUSTOMIZATION.md tells operators to
        # change these bands, so the universal form failed the offline gate on a
        # documented customisation path (measured: edges 51/67/83 and 55/70/85 both
        # went red). What actually matters is that a display-to-band table cannot
        # be written, and ONE straddling edge is enough to make it impossible.
        #
        # Be exact about what that admits, because an earlier version of this
        # comment claimed the disjunction rescued BOTH customisations above and
        # it does not. Re-derived over all 99 integer edges: an edge straddles
        # unless E is congruent to 3 mod 4, so 55/70/85 passes (70 and 85
        # straddle) while 51/67/83 -- every one of them 3 mod 4 -- still goes red.
        #
        # That red is CORRECT rather than a gap. With no straddling edge every
        # display value maps to exactly one band, so a display-to-band table is
        # writable and the rubric's own "deliberately no display-scale
        # equivalent" prose has become false for that deployment. The gate
        # stopping there is the point; what was missing is a message that says
        # which knob to turn. The shipped rubric's edges are 50/66/82 and all
        # three straddle.
        straddling = [e for e in edges if display_of((e - quantum).quantize(quantum)) == display_of(e)]
        self.assertTrue(
            straddling,
            "no band edge is straddled by a display value, so every display value "
            "maps to exactly one recommendation and a display-to-band table WOULD "
            "be writable. The rubric says there is 'deliberately no display-scale "
            f"equivalent'; with edges {[str(e) for e in edges]} that claim no "
            "longer holds. An integer edge straddles unless it is congruent to 3 "
            "mod 4 (measured over all 99), so moving any one edge off 3 mod 4 -- "
            "51 to 50 or 52, say -- restores it. The alternative is to accept that "
            "this deployment CAN read a band off a display value, which means "
            "amending the rubric's prose and re-cutting "
            "tests/g3/scoring_boundary_cases.jsonl, tests/g3/README.md and "
            "workspaces/vc-chief/vc/eval_fixtures.md together.",
        )

    def test_the_reviewed_boundary_fixture_is_on_the_unrounded_scale(self):
        """The hash-pinned boundary fixture must not carry display-scale values.

        BEFORE this test nothing replayed `tests/g3/scoring_boundary_cases.jsonl`
        -- it was hash-pinned by `check_customization.py` and the G8 gate and read
        by nothing else -- so it could drift back onto the 0.0-5.0 display scale
        unnoticed. It shipped that way, asserting one band per display value,
        which the straddle above shows is untrue of half of each window. This
        test IS that executor now, so the fixture is live offline-gate cover:
        `tests/g3/README.md` and `CUSTOMIZATION.md` both say it must be re-cut
        when the recommendation bands change.

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
                    f"{row['id']}'s final_100 {value} is outside the scale's own "
                    f"range [0, 100]",
                )
                self.assertEqual(
                    row["expected"],
                    self.helper._recommendation_for_score(
                        value.quantize(Decimal("0.001")), rubric
                    ),
                    f"{row['id']}'s expected band is not what the shipped helper "
                    f"returns for final_100={value}",
                )

        # The range check above cannot separate the two scales: every display
        # value (0.0-5.0) is also inside [0, 100], and re-deriving `expected`
        # only proves internal consistency. Measured: a fixture rewritten
        # entirely onto the display scale, with each band re-derived, passed both
        # of those. Tie the fixture to the rubric's OWN edges instead — the one
        # property a display-scale fixture cannot satisfy.
        values = {Decimal(str(row["final_100"])) for row in rows}
        quantum = Decimal("0.001")
        for interval in rubric["recommendation_intervals"]:
            minimum = Decimal(str(interval["minimum"]))
            if minimum <= 0:
                continue
            with self.subTest(edge=str(minimum)):
                self.assertIn(
                    minimum, values,
                    f"the fixture does not probe the band edge at "
                    f"final_100={minimum}. Its values are {sorted(values)}; if "
                    f"those look like 0.0-5.0 numbers, the file has drifted back "
                    f"onto the display scale.",
                )
                self.assertIn(
                    (minimum - quantum).quantize(quantum), values,
                    f"the fixture probes the band edge at final_100={minimum} but "
                    f"not the value just below it, so it cannot show the edge is "
                    f"where the rubric says it is",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
