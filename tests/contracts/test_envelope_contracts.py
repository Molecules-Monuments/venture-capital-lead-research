# SPDX-License-Identifier: 0BSD
"""Instance + cross-schema contract tests for the machine-consumed orchestration
envelopes (data-steward-output, vc-chief-output, return-assessment) and the
family-A/B boundary consistency invariants.

These were previously untested: the steward/chief envelopes had no instance test
and failed open on the status<->error coupling; the return-assessment accept gate
did not consult its own acceptance results. This suite pins the tightened contracts
and the unified error/id representations across all boundary schemas.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from typing import Any, ClassVar


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "workspaces" / "schemas"

SPECIALIST_SCHEMAS = sorted(SCHEMA_DIR.glob("*.output.schema.json"))
FAMILY_A = {
    "lead-router", "lead-signal-detector", "inbound-intake-analyst",
    "outbound-scout", "document-intake-analyst",
}
FAMILY_B = {
    "founder-researcher", "traction-analyst", "market-mapper",
    "qualification-analyst", "memo-writer",
}


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def errors(schema: dict, packet: dict) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [e.message for e in validator.iter_errors(packet)]


def steward_packet(**overrides) -> dict:
    packet = {
        "schema_version": "3.0",
        "role": "data-steward",
        "status": "ok",
        "lead_id": "42",
        "run_id": "run-1",
        "result": {
            "operation": "evidence-record",
            "availability": "fixed_workflow",
            "mode": "fixed_workflow",
            "pre_state": None,
            "post_state": {"fact_id": "7"},
            "record_ids": ["7"],
            "revision": 1,
            "idempotency_key": "k1",
            "rows_affected": 1,
            "preview": None,
            "approval_required": False,
            "verification": "row inserted and read back",
        },
        "evidence_refs": [],
        "missing_data": [],
        "warnings": [],
        "error": None,
    }
    packet.update(overrides)
    return packet


def chief_packet(**overrides) -> dict:
    packet = {
        "schema_version": "3.0",
        "role": "vc-chief",
        "status": "ok",
        "lead_id": "42",
        "run_id": "run-1",
        "policy_versions": {"scoring": "3.0"},
        "resolution": None,
        "decision": {
            "classification": "outbound",
            "recommendation": "advance",
            "rationale": ["strong team"],
            "cruxes": ["retention"],
            "what_would_change_view": ["churn spike"],
        },
        "delegations": [{
            "task_id": "t1",
            "agent": "founder-researcher",
            "pre_eval_ref": "eval-1",
            "return_assessment_ref": "ra-1",
            "disposition": "accept",
        }],
        "evidence_refs": [],
        "missing_data": [],
        "contradictions": [],
        "resource_usage": {
            "agents_spawned": 1, "sources_used": 3, "minutes_elapsed": 4.0,
            "cost": 0.5, "currency": "USD", "budget_status": "within",
        },
        "terminal_reason": "completed",
        "approval_required": False,
        "warnings": [],
        "error": None,
    }
    packet.update(overrides)
    return packet


def assessment_packet(**overrides) -> dict:
    packet = {
        "schema_version": "3.0",
        "task_id": "t1",
        "agent": "founder-researcher",
        "packet_schema_valid": True,
        "identifiers_match": True,
        "scope_respected": True,
        "source_policy_respected": True,
        "budget_respected": True,
        "material_claims_cited": True,
        "acceptance_results": [
            {"test_id": "pos-1", "status": "pass", "evidence_refs": ["e1"], "reason": "met"},
        ],
        "unexpected_evidence": [],
        "contradictions": [],
        "disposition": "accept",
        "reason": "all gates passed",
    }
    packet.update(overrides)
    return packet


class StewardEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.schema = load("data-steward-output.schema.json")

    def test_valid_ok_packet(self):
        self.assertEqual(errors(self.schema, steward_packet()), [])

    def test_valid_failed_packet_requires_error_object(self):
        self.assertEqual(errors(self.schema, steward_packet(
            status="failed", error={"code": "conflict", "message": "revision changed"})), [])

    def test_ok_with_error_object_fails_closed(self):
        # status<->error coupling: ok must carry a null error.
        self.assertTrue(errors(self.schema, steward_packet(
            error={"code": "x", "message": "y"})))

    def test_failed_without_error_fails_closed(self):
        self.assertTrue(errors(self.schema, steward_packet(status="failed", error=None)))

    def test_error_string_is_rejected(self):
        self.assertTrue(errors(self.schema, steward_packet(status="failed", error="boom")))

    def test_additional_properties_rejected(self):
        self.assertTrue(errors(self.schema, steward_packet(undeclared="x")))


class ChiefEnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.schema = load("vc-chief-output.schema.json")

    def test_valid_ok_packet(self):
        self.assertEqual(errors(self.schema, chief_packet()), [])

    def test_ok_with_error_object_fails_closed(self):
        self.assertTrue(errors(self.schema, chief_packet(error={"code": "x", "message": "y"})))

    def test_failed_requires_error_object(self):
        self.assertTrue(errors(self.schema, chief_packet(status="failed", error=None)))
        self.assertEqual(errors(self.schema, chief_packet(
            status="failed", error={"code": "e", "message": "m"})), [])

    def test_delegation_agent_must_be_in_roster(self):
        p = chief_packet()
        p["delegations"][0]["agent"] = "ghost-agent"
        self.assertTrue(errors(self.schema, p))

    def test_delegation_disposition_must_be_enum(self):
        p = chief_packet()
        p["delegations"][0]["disposition"] = "maybe"
        self.assertTrue(errors(self.schema, p))

    def test_self_delegation_is_rejected(self):
        # The chief can delegate only to the 11 specialists; recording a
        # delegation to itself contradicts delegation-eval and AGENTS.md.
        p = chief_packet()
        p["delegations"][0]["agent"] = "vc-chief"
        self.assertTrue(errors(self.schema, p))

    def test_missing_data_items_are_typed(self):
        typed = chief_packet(missing_data=[{
            "field": "retention",
            "state": "missing",
            "reason": "No cohort evidence.",
            "evidence_needed": "Dated cohort retention table.",
        }])
        self.assertEqual(errors(self.schema, typed), [])
        self.assertTrue(errors(self.schema, chief_packet(missing_data=["retention"])))


class ReturnAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.schema = load("return-assessment.schema.json")

    def test_valid_accept_packet(self):
        self.assertEqual(errors(self.schema, assessment_packet()), [])

    def test_accept_with_false_gate_fails_closed(self):
        self.assertTrue(errors(self.schema, assessment_packet(scope_respected=False)))

    def test_accept_with_failed_acceptance_result_fails_closed(self):
        # The gate must consult its own acceptance results: an accept cannot ship
        # with a failed falsification test.
        p = assessment_packet()
        p["acceptance_results"].append(
            {"test_id": "falsify-1", "status": "fail", "evidence_refs": [], "reason": "counterexample"})
        self.assertTrue(errors(self.schema, p))

    def test_non_accept_disposition_allows_failed_results(self):
        p = assessment_packet(disposition="targeted_retry")
        p["acceptance_results"].append(
            {"test_id": "falsify-1", "status": "fail", "evidence_refs": [], "reason": "counterexample"})
        self.assertEqual(errors(self.schema, p), [])

    def test_bad_disposition_rejected(self):
        self.assertTrue(errors(self.schema, assessment_packet(disposition="ship_it")))


class CrossSchemaConsistencyTests(unittest.TestCase):
    """Every specialist output schema must agree on the shared representations so
    a packet cannot silently change an id type, confidence scale, or error shape
    as it crosses a stage the chief aggregates.

    Scope is the ten `*.output.schema.json` specialists; the chief and steward
    envelopes are covered by their own tests, not by these equality checks.
    """

    CANONICAL_ERROR: ClassVar[dict[str, Any]] = {
        "oneOf": [
            {"type": "null"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                },
            },
        ]
    }

    def test_all_specialist_schemas_share_the_canonical_error_shape(self):
        for path in SPECIALIST_SCHEMAS:
            schema = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(schema=path.name):
                self.assertEqual(schema["$defs"]["error"], self.CANONICAL_ERROR)

    def test_all_specialist_schemas_share_the_canonical_id_shape(self):
        for path in SPECIALIST_SCHEMAS:
            schema = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(schema=path.name):
                self.assertEqual(schema["$defs"]["nullableId"], {"type": ["string", "null"], "minLength": 1})

    def test_confidence_split_is_intentional_and_by_family(self):
        # The two representations are a reviewed, intentional split: routing/intake
        # (family A) reason in a continuous 0..1 confidence; research analysts
        # (family B) reason in a qualitative low/medium/high enum. The evidence
        # boundary coerces both (see _evidence_confidence in vcops). This test
        # pins the split so it cannot drift silently.
        for path in SPECIALIST_SCHEMAS:
            role = path.name.replace(".output.schema.json", "")
            conf = json.loads(path.read_text(encoding="utf-8"))["$defs"].get("confidence")
            if role in FAMILY_A:
                with self.subTest(role=role, family="A"):
                    self.assertEqual(conf, {"type": "number", "minimum": 0, "maximum": 1})
            elif role in FAMILY_B:
                with self.subTest(role=role, family="B"):
                    self.assertEqual(conf, {"enum": ["low", "medium", "high"]})

    def test_families_partition_the_specialist_roster(self):
        roles = {p.name.replace(".output.schema.json", "") for p in SPECIALIST_SCHEMAS}
        self.assertEqual(roles, FAMILY_A | FAMILY_B)


class ChiefSchemaMirrorTests(unittest.TestCase):
    """The canonical schemas live at /workspaces/schemas, which is not reachable
    from the workspace-confined chief agent. A byte-identical mirror is shipped
    inside the chief's own workspace so it can read and inline the expected-schema
    bodies at runtime. This guards the mirror against drift."""

    MIRROR = ROOT / "workspaces" / "vc-chief" / "vc" / "schemas"

    def test_mirror_is_complete_and_byte_identical(self):
        canonical = {p.name: p.read_bytes() for p in SCHEMA_DIR.glob("*.json")}
        mirror = {p.name: p.read_bytes() for p in self.MIRROR.glob("*.json")}
        self.assertEqual(
            set(canonical), set(mirror),
            "chief schema mirror is missing or has extra files vs the canonical set",
        )
        for name, data in canonical.items():
            with self.subTest(schema=name):
                self.assertEqual(data, mirror[name], f"chief schema mirror drifted for {name}")


if __name__ == "__main__":
    unittest.main()
