# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator
from jsonschema.exceptions import ValidationError


PACKAGE = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = PACKAGE / "workspaces/schemas"
FIXTURES = Path(__file__).resolve().parent / "fixtures/specialist_outputs.json"

ROLE_SCHEMAS = {
    "founder-researcher": "founder-researcher.output.schema.json",
    "traction-analyst": "traction-analyst.output.schema.json",
    "market-mapper": "market-mapper.output.schema.json",
    "qualification-analyst": "qualification-analyst.output.schema.json",
    "memo-writer": "memo-writer.output.schema.json",
}


class SpecialistSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = {
            role: json.loads((SCHEMA_ROOT / filename).read_text(encoding="utf-8"))
            for role, filename in ROLE_SCHEMAS.items()
        }
        cls.fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def validator(self, role: str) -> Validator:
        return Draft202012Validator(self.schemas[role])

    def test_all_schemas_are_valid_draft_2020_12_and_examples_validate(self) -> None:
        for role, schema in self.schemas.items():
            with self.subTest(role=role):
                Draft202012Validator.check_schema(schema)
                self.validator(role).validate(self.fixtures[role])

    def test_all_boundaries_are_closed_to_undeclared_fields(self) -> None:
        for role in ROLE_SCHEMAS:
            with self.subTest(role=role):
                payload = copy.deepcopy(self.fixtures[role])
                payload["undeclared"] = "must fail closed"
                with self.assertRaises(ValidationError):
                    self.validator(role).validate(payload)

    def test_status_and_error_envelopes_fail_closed(self) -> None:
        for role in ROLE_SCHEMAS:
            with self.subTest(role=role, case="failed_without_error"):
                payload = copy.deepcopy(self.fixtures[role])
                payload["status"] = "failed"
                with self.assertRaises(ValidationError):
                    self.validator(role).validate(payload)
            with self.subTest(role=role, case="ok_with_error"):
                payload = copy.deepcopy(self.fixtures[role])
                payload["error"] = {"code": "unexpected", "message": "must fail"}
                with self.assertRaises(ValidationError):
                    self.validator(role).validate(payload)

    def test_founder_requires_team_falsifiers_and_prestige_bias_control(self) -> None:
        payload = copy.deepcopy(self.fixtures["founder-researcher"])
        del payload["result"]["team_assessment"]["falsifiers"]
        with self.assertRaises(ValidationError):
            self.validator("founder-researcher").validate(payload)
        payload = copy.deepcopy(self.fixtures["founder-researcher"])
        del payload["result"]["team_assessment"]["prestige_bias_check"]
        with self.assertRaises(ValidationError):
            self.validator("founder-researcher").validate(payload)

    def test_traction_requires_complete_comparable_metric_tuple(self) -> None:
        payload = copy.deepcopy(self.fixtures["traction-analyst"])
        del payload["result"]["metric_observations"][0]["cohort"]
        with self.assertRaises(ValidationError):
            self.validator("traction-analyst").validate(payload)
        payload = copy.deepcopy(self.fixtures["traction-analyst"])
        payload["result"]["comparisons"][0]["comparable"] = False
        payload["result"]["comparisons"][0]["direction"] = "up"
        with self.assertRaises(ValidationError):
            self.validator("traction-analyst").validate(payload)

    def test_market_requires_wedge_distribution_incumbent_response_and_ranges(self) -> None:
        for required_field in ("initial_wedge", "distribution_motions", "incumbent_responses"):
            payload = copy.deepcopy(self.fixtures["market-mapper"])
            del payload["result"][required_field]
            with self.assertRaises(ValidationError, msg=required_field):
                self.validator("market-mapper").validate(payload)
        # The schema leaves scenario-range internals free-form, so the ordering
        # checks below pin the reviewed fixture's sanity, not validator behavior.
        scenario = self.fixtures["market-mapper"]["result"]["scenario_ranges"][0]
        self.assertLessEqual(scenario["low"], scenario["base"])
        self.assertLessEqual(scenario["base"], scenario["high"])
        self.assertTrue(scenario["assumption_refs"])

    def test_qualification_keeps_unknown_separate_from_negative_and_score(self) -> None:
        payload = copy.deepcopy(self.fixtures["qualification-analyst"])
        criterion = payload["result"]["criteria"][0]
        criterion["evidence_state"] = "unknown"
        criterion["quality_score"] = 2
        with self.assertRaises(ValidationError):
            self.validator("qualification-analyst").validate(payload)
        payload = copy.deepcopy(self.fixtures["qualification-analyst"])
        payload["result"]["criteria"][0]["evidence_refs"] = []
        with self.assertRaises(ValidationError):
            self.validator("qualification-analyst").validate(payload)
        rubric_ids = {item["criterion_id"] for item in payload["result"]["rubric"]["weights"]}
        criterion_ids = {item["criterion_id"] for item in payload["result"]["criteria"]}
        self.assertEqual(rubric_ids, criterion_ids)

    def test_memo_verified_claims_require_evidence_and_inferences_require_basis(self) -> None:
        payload = copy.deepcopy(self.fixtures["memo-writer"])
        payload["result"]["claim_evidence_map"][0]["evidence_refs"] = []
        with self.assertRaises(ValidationError):
            self.validator("memo-writer").validate(payload)
        payload = copy.deepcopy(self.fixtures["memo-writer"])
        payload["result"]["claim_evidence_map"][1]["inference_basis"] = []
        with self.assertRaises(ValidationError):
            self.validator("memo-writer").validate(payload)

    def test_agent_and_skill_prose_points_to_canonical_schema(self) -> None:
        skill_paths = {
            "founder-researcher": "shared-skills/evidence-research/SKILL.md",
            "traction-analyst": "shared-skills/trajectory-check/SKILL.md",
            "market-mapper": "shared-skills/evidence-research/SKILL.md",
            "qualification-analyst": "shared-skills/evidence-scoring/SKILL.md",
            "memo-writer": "shared-skills/memo-writing/SKILL.md",
        }
        for role, filename in ROLE_SCHEMAS.items():
            with self.subTest(role=role):
                contract = (PACKAGE / f"workspaces/{role}/AGENTS.md").read_text(encoding="utf-8")
                tools = (PACKAGE / f"workspaces/{role}/TOOLS.md").read_text(encoding="utf-8")
                skill = (PACKAGE / f"workspaces/{skill_paths[role]}").read_text(encoding="utf-8")
                schema_path = f"/workspaces/schemas/{filename}"
                self.assertIn(schema_path, contract)
                self.assertIn(schema_path, skill)
                self.assertIn("Effective role skills", contract)
                self.assertIn("Effective role skills", tools)
                self.assertNotIn("Return exactly one valid JSON object with", contract)


if __name__ == "__main__":
    unittest.main()
