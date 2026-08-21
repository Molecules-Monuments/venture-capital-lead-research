# SPDX-License-Identifier: Apache-2.0
"""Entity resolution is a policy decision here, never a similarity score.

`vcops.decide_entity_resolution` is the one place a candidate becomes an
existing company, a new one, a human-review item, or a refusal, and the whole
point of it is that no confidence value authorises a merge on its own. Every
case in `entity_resolution_cases.json` asserts `auto_merge` is false alongside
its expected outcome, and the fuzzy test repeats that assertion against a
hand-built candidate at 0.99 confidence, so moving `FUZZY_REVIEW_THRESHOLD` or
adding a match method cannot quietly turn similarity into an automatic merge.
The fixture cases are precommitted: they are the decisions the resolver is
allowed to reach, not examples it may redefine.

The rest of the suite exists so that nothing routes around that decision. The
legacy `memory-lookup` adapter must stay literal-only — no `ILIKE`, no f-string
wildcard interpolation, still labelled DEPRECATED; the typed read surface
(`entity-resolve`) and the writing surface (`company-resolve-create`) must stay
on opposite sides of `AGENT_READ_ONLY_COMMANDS`; `decide_external_research`
must refuse, with a reason, a creation purpose, an unresolved or denied
outcome, and a match above the caller's confidentiality ceiling; and all four
lead-creating workflows must claim, then resolve, then create, with neither
`company-upsert` nor `memory-lookup` anywhere in the file. That last assertion
once covered two of the four, so the bypass it exists to catch was unguarded on
`inbound-text-intake` and `document-lead-intake` while reading as complete.

The migration assertions pin the requirement rather than the string, because
pinning the string once held the defect in place. Migration 006's
`company_aliases` backfill must derive `normalized_alias` as
`lower(btrim(normalize(name, NFKC)))` — normalise first, then trim — and must
not spell it the other way round: `btrim` with no character argument strips
only U+0020, NFKC then maps U+00A0 and U+3000 onto U+0020, and the edge
whitespace that reintroduces fails `company_aliases`' own
`btrim(normalized_alias) = normalized_alias` CHECK, aborting the upgrade for
any company whose name carries one. Migration 009 is read for the trigram
indexes and for the two `GRANT EXECUTE` lines without which the runtime role
cannot use the prefilter at all.
"""
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
        # Assert the ORDER, not the literal. This line previously pinned
        # `lower(normalize(btrim(name), NFKC))` -- the defective spelling -- so the
        # test actively held the defect in place: btrim with no character argument
        # strips only U+0020, and NFKC then maps U+00A0/U+3000 onto U+0020, so
        # trimming first let normalisation reintroduce edge whitespace and the
        # derived value failed company_aliases' own
        # `btrim(normalized_alias) = normalized_alias` CHECK, aborting the whole
        # migration. Pinning the requirement instead of the string means neither
        # order can be reinstated silently.
        self.assertTrue(
            "lower(btrim(normalize(name, NFKC)))" in sql,
            "migration 006's company_aliases backfill must derive "
            "normalized_alias as lower(btrim(normalize(name, NFKC))) -- "
            "normalise first, then trim",
        )
        self.assertFalse(
            "normalize(btrim(name)" in sql,
            "migration 006 trims before it normalises: NFKC then reintroduces "
            "edge whitespace (U+00A0, U+3000 -> U+0020) and the derived "
            "normalized_alias fails its own CHECK, aborting the upgrade for any "
            "company whose name carries one. Normalise first, then trim.",
        )
        # assertTrue, not assertIn: `sql` is the whole ~11 KB migration, and
        # assertIn renders its second argument in full, so the one useful
        # sentence arrived at the end of a screen of escaped SQL. The two
        # assertions above already avoid that; this one did not.
        self.assertTrue(
            "WHERE btrim(normalize(name, NFKC)) <> ''" in sql,
            "migration 006 must skip names that normalise to nothing; an empty "
            "normalized_alias fails the CHECK's `<> ''` half",
        )

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
