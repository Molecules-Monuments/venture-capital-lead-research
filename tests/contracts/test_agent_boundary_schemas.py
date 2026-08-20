# SPDX-License-Identifier: Apache-2.0
"""Deterministic contract tests for the five dossier-backed v3 agent boundaries."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "workspaces" / "schemas"

BOUNDARIES = {
    "lead-signal-detector": (
        SCHEMA_DIR / "lead-signal-detector.output.schema.json",
        ROOT / "workspaces" / "lead-signal-detector" / "AGENTS.md",
        ROOT / "workspaces" / "shared-skills" / "lead-signal-detection" / "SKILL.md",
    ),
    "lead-router": (
        SCHEMA_DIR / "lead-router.output.schema.json",
        ROOT / "workspaces" / "lead-router" / "AGENTS.md",
        ROOT / "workspaces" / "shared-skills" / "lead-routing" / "SKILL.md",
    ),
    "outbound-scout": (
        SCHEMA_DIR / "outbound-scout.output.schema.json",
        ROOT / "workspaces" / "outbound-scout" / "AGENTS.md",
        ROOT / "workspaces" / "shared-skills" / "outbound-sourcing" / "SKILL.md",
    ),
    "inbound-intake-analyst": (
        SCHEMA_DIR / "inbound-intake-analyst.output.schema.json",
        ROOT / "workspaces" / "inbound-intake-analyst" / "AGENTS.md",
        ROOT / "workspaces" / "shared-skills" / "inbound-intake" / "SKILL.md",
    ),
    "document-intake-analyst": (
        SCHEMA_DIR / "document-intake-analyst.output.schema.json",
        ROOT / "workspaces" / "document-intake-analyst" / "AGENTS.md",
        ROOT / "workspaces" / "shared-skills" / "document-extraction" / "SKILL.md",
    ),
}


def load_schema(role: str) -> dict:
    return json.loads(BOUNDARIES[role][0].read_text(encoding="utf-8"))


def validate(role: str, packet: dict) -> list[str]:
    validator = Draft202012Validator(load_schema(role), format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(packet), key=lambda item: list(item.path))]


def base_packet(role: str, result: dict, *, evidence: list[dict] | None = None) -> dict:
    return {
        "schema_version": "3.0",
        "role": role,
        "status": "ok",
        "lead_id": None,
        "run_id": "run-001",
        "assumptions": [],
        "missing_data": [],
        "evidence": evidence or [],
        "confidence": 0.8,
        "result": result,
        "risks": [],
        "warnings": [],
        "recommended_next_agent": None,
        "persistence_request": {
            "requested": False,
            "operation": "none",
            "reason": None,
            "steward_required": True,
        },
        "error": None,
    }


def valid_packets() -> dict[str, dict]:
    counter = {
        "queries": 5,
        "results_inspected": 25,
        "page_fetches": 10,
        "sources": 4,
        "elapsed_minutes": 20,
    }
    signal = base_packet(
        "lead-signal-detector",
        {
            "signal_type": "traction",
            "signal_text": "The company reports a new enterprise contract.",
            "proposed_action": "update_candidate",
            "source_ids": ["message:123"],
            "origin_hint": "inbound",
            "materiality": "high",
            "urgency": "soon",
            "novelty": "changed",
            "source_independence": "direct",
            "freshness": {
                "observed_at": "2026-07-20T10:00:00Z",
                "prior_state_observed_at": "2026-06-01T10:00:00Z",
                "assessment": "current",
            },
            "identity_confidence": 0.9,
            "memory_summary": {"status": "possible_match", "match_ids": ["lead:44"]},
            "duplicate_or_update_risk": "medium",
            "approval_risk": "none",
            "reason": "A material state change is attributed to a stable sender and company reference.",
            "what_would_change_action": ["Independent confirmation would raise evidence confidence."],
        },
        evidence=[
            {
                "claim": "A new enterprise contract was reported.",
                "source_ref": "message:123",
                "observed_at": "2026-07-20T10:00:00Z",
                "fact_status": "submitted_claim",
                "confidence": 0.9,
            }
        ],
    )

    router = base_packet(
        "lead-router",
        {
            "lead_title": "ExampleCo",
            "origin_group": "inbound",
            "origin_subtype": "direct_contact",
            "origin_confidence": 0.9,
            "candidate_action": "new_candidate",
            "duplicate_risk": "low",
            "required_agents": ["founder-researcher"],
            "required_skills": ["evidence-research"],
            "route_steps": [
                {
                    "step_id": "company_research",
                    "sequence": 1,
                    "agent": "founder-researcher",
                    "skills": ["evidence-research"],
                    "decision_question": "Are identity and company claims supported?",
                    "information_needed": ["Canonical domain", "Primary-source company facts"],
                    "depends_on": [],
                    "parallelizable": False,
                    "cost_class": "standard",
                    "acceptance_condition": "Identity is resolved with cited evidence.",
                    "stop_condition": "Stop if identity cannot be resolved within budget.",
                }
            ],
            "blockers": [],
            "omitted_agents": [
                {"agent": "qualification-analyst", "reason": "Evidence collection is not complete."}
            ],
            "approval_risk": "none",
            "next_step": "Run the company research step.",
            "reason": "One identity-focused step is sufficient before broader diligence.",
        },
        evidence=[{"source_ref": "message:123", "supports": "Inbound founder-direct origin."}],
    )

    outbound = base_packet(
        "outbound-scout",
        {
            "candidates": [
                {
                    "candidate_ref": "candidate:1",
                    "company_name": "ExampleCo",
                    "website": "https://example.com",
                    "normalized_domain": "example.com",
                    "origin_subtype": "thematic_search",
                    "source_ids": ["source:company"],
                    "memory_match_ids": [],
                    "duplicate_or_merge_risk": "low",
                    "description": "Developer infrastructure company.",
                    "thesis_signal": "Open-source adoption is growing.",
                    "fit_inference": "May fit the infrastructure thesis.",
                    "thesis_gap": "Commercial retention is unknown.",
                    "outlier_reason": "Usage could support a non-consensus wedge.",
                    "novelty": "new",
                    "source_independence": "single_source",
                    "evidence_refs": ["evidence:1"],
                    "confidence": 0.65,
                }
            ],
            "duplicates": [],
            "sources_used": [
                {
                    "source_id": "source:company",
                    "url": "https://example.com",
                    "source_class": "company",
                    "query_count": 1,
                    "results_inspected": 5,
                    "candidates_yielded": 1,
                    "accessed_at": "2026-07-20T10:00:00Z",
                }
            ],
            "budget": {"limit": counter, "used": {**counter, "queries": 1, "results_inspected": 5}},
            "yield_summary": {
                "raw_results": 5,
                "unique_candidates": 1,
                "duplicate_candidates": 0,
                "candidates_proposed": 1,
                "marginal_yield": 0.2,
            },
            "stop_reason": "sufficient_evidence",
            "blocked_sources": [],
        },
        evidence=[
            {
                "evidence_id": "evidence:1",
                "candidate_ref": "candidate:1",
                "claim": "The company publishes an open-source infrastructure product.",
                "url": "https://example.com",
                "source_id": "source:company",
                "published_at": None,
                "accessed_at": "2026-07-20T10:00:00Z",
                "fact_status": "verified_fact",
                "confidence": 0.8,
            }
        ],
    )
    outbound["persistence_request"]["candidate_refs"] = []

    inbound = base_packet(
        "inbound-intake-analyst",
        {
            "origin": {"group": "inbound", "subtype": "network_referral", "confidence": 0.9},
            "intake_channel": "email_forward",
            "received_at": "2026-07-20T10:00:00Z",
            "source_ids": ["message:123"],
            "trust": {
                "level": "known_external",
                "authorized_sender": "unknown",
                "confidentiality": "confidential",
                "storage_tier": "confidential",
                "retention_class": "deal-intake-90d",
                "approval_required": True,
                "reason": "Sender is known but forwarding authority is not documented.",
            },
            "submitter_or_referrer": {
                "stable_id": "person:referrer-7",
                "display_label": "Known referrer",
                "relationship": "Introducer",
            },
            "company": {
                "name": "ExampleCo",
                "legal_name": None,
                "website": "https://example.com",
                "normalized_domain": "example.com",
            },
            "documents": [
                {"document_ref": "document:deck", "artifact_id": "artifact:9", "parse_status": "pending"}
            ],
            "submitted_claims": [
                {"claim_id": "claim:1", "claim": "The company reports $1m ARR.", "source_ref": "message:123"}
            ],
            "verified_public_facts": [],
            "consent": {"status": "unknown", "scope": None, "evidence_ref": None},
            "lawful_basis": {"status": "needs_review", "basis": "unknown", "evidence_ref": None},
            "duplicate_candidates": [],
            "approval_risks": [
                {
                    "code": "lawful_basis",
                    "reason": "No supplied lawful-basis decision.",
                    "required_action": "Obtain policy-owner review before persistence.",
                }
            ],
        },
        evidence=[
            {
                "evidence_id": "evidence:1",
                "claim": "The company reports $1m ARR.",
                "source_ref": "message:123",
                "fact_status": "submitted_claim",
                "received_or_verified_at": "2026-07-20T10:00:00Z",
            }
        ],
    )
    inbound["missing_data"] = [
        {
            "field": "company.legal_name",
            "status": "not_disclosed",
            "reason": "The referral did not disclose a legal name.",
            "source_ref": "message:123",
        }
    ]

    document = base_packet(
        "document-intake-analyst",
        {
            "artifact_id": "artifact:9",
            "document_ref": "document:deck",
            "filename": "deck.pdf",
            "sha256": "a" * 64,
            "declared_mime": "application/pdf",
            "detected_mime": "application/pdf",
            "storage_tier": "confidential",
            "confidentiality": "confidential",
            "retention_class": "deal-intake-90d",
            "parse_status": "complete",
            "parser": {"name": "pdf-parser", "version": "1.2.3"},
            "extraction_executor": "deterministic_pipeline",
            "deterministic_extraction_ref": "extract:9",
            "truncated": False,
            "claims": [
                {
                    "claim_id": "claim:doc-1",
                    "original_text": "The company reports $1m ARR.",
                    "fact_status": "submitted_claim",
                    "source_ref": "artifact:9",
                    "location": {"kind": "pdf", "page": 4, "bounding_context": "Metrics table"},
                    "formula_text": None,
                    "cached_value": None,
                }
            ],
            "coverage_manifest": [
                {"unit_id": "page:4", "unit_type": "page", "status": "extracted", "limitation_codes": []}
            ],
            "parse_limitations": [],
            "limits_applied": {
                "max_bytes": 10000000,
                "max_pages": 100,
                "max_sheets": None,
                "max_rows": None,
                "max_columns": None,
                "max_cells": None,
                "max_text_chars": 500000,
            },
            "quarantine": {
                "required": False,
                "recommended": False,
                "reason_codes": [],
                "approved_conversion_required": False,
                "conversion_path": "none",
            },
        },
        evidence=[
            {
                "evidence_id": "evidence:doc-1",
                "source_ref": "artifact:9",
                "claim": "The company reports $1m ARR.",
                "location": {"kind": "pdf", "page": 4, "bounding_context": "Metrics table"},
                "fact_status": "submitted_claim",
            }
        ],
    )
    return {
        "lead-signal-detector": signal,
        "lead-router": router,
        "outbound-scout": outbound,
        "inbound-intake-analyst": inbound,
        "document-intake-analyst": document,
    }


def assert_minimal_route_consistency(packet: dict) -> None:
    result = packet["result"]
    seen: set[str] = set()
    agents: set[str] = set()
    skills: set[str] = set()
    last_sequence = 0
    for step in result["route_steps"]:
        step_id = step["step_id"]
        if step_id in seen:
            raise ValueError(f"duplicate route step: {step_id}")
        if step["sequence"] <= last_sequence:
            raise ValueError("route sequence must increase")
        dangling = set(step["depends_on"]) - seen
        if dangling:
            raise ValueError(f"dependency must reference an earlier step: {sorted(dangling)}")
        seen.add(step_id)
        agents.add(step["agent"])
        skills.update(step["skills"])
        last_sequence = step["sequence"]
    if agents != set(result["required_agents"]):
        raise ValueError("required_agents must equal the route-step union")
    if skills != set(result["required_skills"]):
        raise ValueError("required_skills must equal the route-step union")


def assert_signal_reference_consistency(packet: dict) -> None:
    source_ids = set(packet["result"]["source_ids"])
    dangling = {item["source_ref"] for item in packet["evidence"]} - source_ids
    if dangling:
        raise ValueError(f"signal evidence has unresolved source refs: {sorted(dangling)}")


def assert_outbound_consistency(packet: dict) -> None:
    result = packet["result"]
    for counter, used in result["budget"]["used"].items():
        if used > result["budget"]["limit"][counter]:
            raise ValueError(f"outbound budget exceeded for {counter}")

    candidate_refs = [item["candidate_ref"] for item in result["candidates"]]
    if len(candidate_refs) != len(set(candidate_refs)):
        raise ValueError("candidate refs must be unique")
    evidence_ids = {item["evidence_id"] for item in packet["evidence"]}
    source_ids = {item["source_id"] for item in result["sources_used"]}
    for candidate in result["candidates"]:
        dangling_evidence = set(candidate["evidence_refs"]) - evidence_ids
        dangling_sources = set(candidate["source_ids"]) - source_ids
        if dangling_evidence:
            raise ValueError(f"candidate has unresolved evidence refs: {sorted(dangling_evidence)}")
        if dangling_sources:
            raise ValueError(f"candidate has unresolved source refs: {sorted(dangling_sources)}")
    for item in packet["evidence"]:
        if item["candidate_ref"] not in candidate_refs:
            raise ValueError(f"evidence has unresolved candidate ref: {item['candidate_ref']}")
        if item["source_id"] not in source_ids:
            raise ValueError(f"evidence has unresolved source ref: {item['source_id']}")
    if result["yield_summary"]["candidates_proposed"] != len(result["candidates"]):
        raise ValueError("yield candidates_proposed must equal emitted candidate count")
    if result["yield_summary"]["duplicate_candidates"] != len(result["duplicates"]):
        raise ValueError("yield duplicate_candidates must equal emitted duplicate count")


class AgentBoundarySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packets = valid_packets()

    def test_all_schemas_are_draft_2020_12_and_examples_validate(self) -> None:
        for role, packet in self.packets.items():
            with self.subTest(role=role):
                schema = load_schema(role)
                Draft202012Validator.check_schema(schema)
                self.assertEqual([], validate(role, packet))
        assert_signal_reference_consistency(self.packets["lead-signal-detector"])
        assert_minimal_route_consistency(self.packets["lead-router"])
        assert_outbound_consistency(self.packets["outbound-scout"])

    def test_prose_uses_schema_as_single_output_authority(self) -> None:
        for role, (schema_path, agent_path, skill_path) in BOUNDARIES.items():
            with self.subTest(role=role):
                for prose_path in (agent_path, skill_path):
                    text = prose_path.read_text(encoding="utf-8")
                    self.assertIn(schema_path.name, text)
                    self.assertIn("sole authority", text)

    def test_signal_rejects_legacy_actions_and_missing_decision_fields(self) -> None:
        packet = copy.deepcopy(self.packets["lead-signal-detector"])
        packet["result"]["proposed_action"] = "capture_lead"
        self.assertTrue(validate("lead-signal-detector", packet))
        # One field at a time: deleting both and asserting once would stay green
        # if the schema stopped requiring either one of them.
        for field in ("materiality", "urgency"):
            with self.subTest(missing=field):
                packet = copy.deepcopy(self.packets["lead-signal-detector"])
                del packet["result"][field]
                self.assertTrue(validate("lead-signal-detector", packet))

        packet = copy.deepcopy(self.packets["lead-signal-detector"])
        packet["evidence"][0]["source_ref"] = "message:missing"
        with self.assertRaises(ValueError):
            assert_signal_reference_consistency(packet)

    def test_router_requires_skills_and_a_consistent_minimal_dag(self) -> None:
        packet = copy.deepcopy(self.packets["lead-router"])
        assert_minimal_route_consistency(packet)
        del packet["result"]["required_skills"]
        self.assertTrue(validate("lead-router", packet))

        packet = copy.deepcopy(self.packets["lead-router"])
        packet["result"]["route_steps"][0]["depends_on"] = ["missing_step"]
        with self.assertRaises(ValueError):
            assert_minimal_route_consistency(packet)

    def test_outbound_requires_budget_yield_and_candidate_novelty(self) -> None:
        for field_path in (("budget",), ("yield_summary",), ("candidates", 0, "novelty")):
            packet = copy.deepcopy(self.packets["outbound-scout"])
            target = packet["result"]
            for component in field_path[:-1]:
                target = target[component]
            del target[field_path[-1]]
            with self.subTest(field_path=field_path):
                self.assertTrue(validate("outbound-scout", packet))

        packet = copy.deepcopy(self.packets["outbound-scout"])
        packet["result"]["budget"]["used"]["queries"] = 6
        with self.assertRaises(ValueError):
            assert_outbound_consistency(packet)
        packet = copy.deepcopy(self.packets["outbound-scout"])
        packet["result"]["candidates"][0]["evidence_refs"] = ["evidence:missing"]
        with self.assertRaises(ValueError):
            assert_outbound_consistency(packet)
        packet = copy.deepcopy(self.packets["outbound-scout"])
        packet["result"]["yield_summary"]["candidates_proposed"] = 2
        with self.assertRaises(ValueError):
            assert_outbound_consistency(packet)

    def test_inbound_requires_governance_and_typed_missingness(self) -> None:
        # One field at a time, for the same reason as the signal packet above.
        for field in ("consent", "lawful_basis"):
            with self.subTest(missing=field):
                packet = copy.deepcopy(self.packets["inbound-intake-analyst"])
                del packet["result"][field]
                self.assertTrue(validate("inbound-intake-analyst", packet))

        packet = copy.deepcopy(self.packets["inbound-intake-analyst"])
        packet["missing_data"][0]["status"] = "unknown"
        self.assertTrue(validate("inbound-intake-analyst", packet))

    def test_document_requires_claim_locations_and_parse_limitations(self) -> None:
        packet = copy.deepcopy(self.packets["document-intake-analyst"])
        del packet["result"]["claims"][0]["location"]
        self.assertTrue(validate("document-intake-analyst", packet))

        packet = copy.deepcopy(self.packets["document-intake-analyst"])
        del packet["result"]["parse_limitations"]
        self.assertTrue(validate("document-intake-analyst", packet))

        packet = copy.deepcopy(self.packets["document-intake-analyst"])
        packet["result"]["truncated"] = True
        self.assertTrue(validate("document-intake-analyst", packet))

    def test_legacy_xls_is_quarantined_and_cannot_emit_claims(self) -> None:
        packet = copy.deepcopy(self.packets["document-intake-analyst"])
        result = packet["result"]
        result.update(
            {
                "filename": "legacy.xls",
                "declared_mime": "application/vnd.ms-excel",
                "detected_mime": "application/vnd.ms-excel",
                "storage_tier": "quarantine",
                "parse_status": "quarantined_legacy_xls",
                "parser": None,
                "claims": [],
                "coverage_manifest": [
                    {"unit_id": "file:legacy", "unit_type": "file", "status": "quarantined", "limitation_codes": ["legacy_xls"]}
                ],
                "parse_limitations": [
                    {"code": "legacy_xls", "scope": "file", "detail": "Legacy XLS is not directly parsed."}
                ],
                "quarantine": {
                    "required": True,
                    "recommended": True,
                    "reason_codes": ["legacy_xls"],
                    "approved_conversion_required": True,
                    "conversion_path": "operator_approved_deterministic_conversion",
                },
            }
        )
        packet["evidence"] = []
        self.assertEqual([], validate("document-intake-analyst", packet))

        result["parse_status"] = "complete"
        result["claims"] = copy.deepcopy(self.packets["document-intake-analyst"]["result"]["claims"])
        self.assertTrue(validate("document-intake-analyst", packet))

    def test_persistence_is_only_a_steward_request(self) -> None:
        for role, packet in self.packets.items():
            with self.subTest(role=role):
                request = packet["persistence_request"]
                # Assert the schema, not this test's own fixture: the flag is
                # `"const": true`, so flipping it must be rejected. Reading it
                # back off base_packet() proved only that the fixture is intact.
                denied = copy.deepcopy(packet)
                denied["persistence_request"]["steward_required"] = False
                self.assertTrue(validate(role, denied))
                request["operation"] = next(
                    operation
                    for operation in load_schema(role)["$defs"]["persistenceRequest"]["properties"]["operation"]["enum"]
                    if operation != "none"
                )
                self.assertTrue(validate(role, packet))

    def test_status_error_contract_fails_closed(self) -> None:
        for role, source in self.packets.items():
            with self.subTest(role=role, case="failed_without_error"):
                packet = copy.deepcopy(source)
                packet["status"] = "failed"
                self.assertTrue(validate(role, packet))
            with self.subTest(role=role, case="ok_with_error"):
                packet = copy.deepcopy(source)
                packet["error"] = {"code": "unexpected", "message": "must fail"}
                self.assertTrue(validate(role, packet))


if __name__ == "__main__":
    unittest.main()
