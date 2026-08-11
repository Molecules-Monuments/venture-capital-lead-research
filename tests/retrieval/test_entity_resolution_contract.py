# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import importlib.util
import inspect
import json
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
VCOPS_PATH = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
MIGRATION = PACKAGE / "migrations/006_entity_resolution.sql"
FUZZY_MIGRATION = PACKAGE / "migrations/009_indexed_fuzzy_resolution.sql"
FIXTURES = Path(__file__).with_name("entity_resolution_cases.json")

SPEC = importlib.util.spec_from_file_location("v3_entity_resolution_vcops", VCOPS_PATH)
assert SPEC is not None and SPEC.loader is not None
vcops = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vcops)


class EntityResolutionContractTests(unittest.TestCase):
    def test_precommitted_decision_cases(self) -> None:
        cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(case=case["name"]):
                decision = vcops.decide_entity_resolution(
                    exact_matches=case["exact_matches"],
                    fuzzy_candidates=case["fuzzy_candidates"],
                    identity=case["identity"],
                    purpose=case["purpose"],
                    denied_exact_count=case["denied_exact_count"],
                )
                self.assertEqual(case["expected_outcome"], decision["outcome"])
                self.assertEqual(case["expected_company_id"], decision["matched_company_id"])
                self.assertFalse(decision["auto_merge"])

    def test_legacy_lookup_cannot_interpolate_sql_wildcards(self) -> None:
        source = inspect.getsource(vcops.cmd_memory_lookup).upper()
        self.assertNotIn("ILIKE", source)
        self.assertNotIn('F"%{', source)
        self.assertIn("DEPRECATED", source)

    def test_typed_read_and_workflow_surfaces_are_separate(self) -> None:
        parser = vcops.build_parser()
        choices = next(
            action.choices
            for action in parser._actions
            if getattr(action, "choices", None)
        )
        self.assertIn("entity-resolve", choices)
        self.assertIn("company-resolve-create", choices)
        self.assertIn("entity-resolve", vcops.AGENT_READ_ONLY_COMMANDS)
        self.assertNotIn("company-resolve-create", vcops.AGENT_READ_ONLY_COMMANDS)
        self.assertIn("company-resolve-create", vcops.WORKFLOW_COMMANDS)

    def test_external_research_policy_is_deterministic_and_reasoned(self) -> None:
        allowed = vcops.decide_external_research(
            purpose="research", resolution_outcome="existing", matched_classification="internal"
        )
        self.assertTrue(allowed["allowed"])
        self.assertTrue(allowed["reason"])
        for purpose, outcome, classification in (
            ("company_creation", "existing", "internal"),
            ("research", "human_review", "internal"),
            ("qualification", "denied", "internal"),
            ("memo", "existing", "confidential"),
            ("research", "outage", None),
        ):
            with self.subTest(purpose=purpose, outcome=outcome, classification=classification):
                denied = vcops.decide_external_research(
                    purpose=purpose,
                    resolution_outcome=outcome,
                    matched_classification=classification,
                )
                self.assertFalse(denied["allowed"])
                self.assertTrue(denied["reason"])

    def test_forward_schema_has_identity_and_append_only_resolution_records(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")
        for table in (
            "company_aliases",
            "company_domains",
            "company_external_ids",
            "entity_resolution_runs",
            "entity_resolution_decisions",
            "entity_resolution_consumptions",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)
        self.assertIn("company_domains_active_hostname_uidx", sql)
        self.assertIn("entity_resolution_runs_request_uidx", sql)
        self.assertIn("prevent_domain_history_mutation", sql)
        self.assertIn("lower(normalize(btrim(name), NFKC))", sql)

    def test_fuzzy_candidates_use_review_only_indexed_prefilter(self) -> None:
        sql = FUZZY_MIGRATION.read_text(encoding="utf-8")
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pg_trgm", sql)
        self.assertIn("companies_name_trgm_idx", sql)
        self.assertIn("company_aliases_normalized_trgm_idx", sql)
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.similarity(TEXT, TEXT) TO openclaw_runtime",
            sql,
        )
        self.assertIn(
            "GRANT EXECUTE ON FUNCTION public.similarity_op(TEXT, TEXT) TO openclaw_runtime",
            sql,
        )
        source = inspect.getsource(vcops._resolve_entity)
        self.assertIn("pg_trgm.similarity_threshold", source)
        self.assertIn("similarity(a.normalized_alias", source)
        self.assertNotIn("ORDER BY abs(length", source)
        self.assertEqual(0.84, vcops.FUZZY_REVIEW_THRESHOLD)
        self.assertFalse(
            vcops.decide_entity_resolution(
                exact_matches=[],
                fuzzy_candidates=[
                    {
                        "company_id": 7,
                        "match_method": "fuzzy_alias",
                        "confidence": 0.99,
                    }
                ],
                identity={"normalized_name": "candidate"},
                purpose="research",
            )["auto_merge"]
        )

    def test_fixed_workflows_claim_then_resolve_create(self) -> None:
        """All four lead-creating workflows, not just the two obvious ones.

        RESOLVER.md states that "all four lead-creating workflows
        (`inbound-intake`, `inbound-text-intake`, `outbound-scout`,
        `document-lead-intake`) must consume the resolver decision", and
        tests/v3/test_doc_tree_consistency.py pins that consumer inventory at
        four. This anti-bypass assertion covered only two of them, so the
        `memory-lookup`/`company-upsert` bypass it exists to catch was
        unguarded on the other two.
        """
        workflows = PACKAGE / "workspaces/vc-chief/vc/workflows"
        for filename in (
            "inbound-intake.lobster",
            "outbound-scout.lobster",
            "inbound-text-intake.lobster",
            "document-lead-intake.lobster",
        ):
            with self.subTest(workflow=filename):
                body = (workflows / filename).read_text(encoding="utf-8")
                claim = body.index("- id: workflow_request_claim")
                resolve = body.index("- id: company_resolve_create")
                create_lead = body.index("- id: create_lead")
                self.assertLess(claim, resolve)
                self.assertLess(resolve, create_lead)
                self.assertIn("company-resolve-create", body)
                self.assertNotIn("company-upsert", body)
                self.assertNotIn("memory-lookup", body)


if __name__ == "__main__":
    unittest.main()
