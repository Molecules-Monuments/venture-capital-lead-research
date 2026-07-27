# SPDX-License-Identifier: 0BSD
import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

import psycopg


DATABASE_URL = os.environ.get("G4_RUNTIME_DATABASE_URL")
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))
PYTHON = os.environ.get("G4_PYTHON", sys.executable)
TEST_APPROVAL_PEPPER = "g4-test-only-approval-pepper-0000000000000000"


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class HelperCliDatabaseTests(unittest.TestCase):
    @staticmethod
    def scored_criterion(score, evidence_fact_id, rationale):
        return {
            "evidence_state": "positive",
            "quality_score": score,
            "coverage": "complete",
            "evidence_quality": "high",
            "evidence_fact_ids": [evidence_fact_id],
            "counterevidence_fact_ids": [],
            "rationale": rationale,
            "what_would_change": "a current contradictory verified fact",
        }

    @classmethod
    def setUpClass(cls):
        if not DATABASE_URL:
            raise AssertionError("G4_RUNTIME_DATABASE_URL is required; helper integration tests must run as openclaw_runtime")
        if not HELPER.is_file():
            raise AssertionError("VCOPS_HELPER must name vcops.py")
        cls.prefix = "g4cli-" + uuid.uuid4().hex[:10]
        cls.tmp = tempfile.TemporaryDirectory(prefix="openclaw-g4-cli-")
        base = Path(cls.tmp.name)
        cls.inbox = base / "inbox"
        cls.quarantine = base / "quarantine"
        cls.state = base / "state"
        cls.trusted_context_key = base / "trusted-context.key"
        cls.trusted_context_key.write_bytes(b"g4-test-trusted-context-key-00000000000000000000000000000000")
        for directory in (cls.inbox, cls.quarantine, cls.state):
            directory.mkdir()
        company = cls.invoke([
            "company-upsert", "--name", "G4 CLI Company", "--domain", f"{cls.prefix}.invalid", "--metadata", "{}",
        ])
        cls.company_id = company["company"]["id"]
        lead = cls.invoke([
            "create-lead", "--company-id", str(cls.company_id), "--lead-title", "G4 CLI Lead",
            "--origin-group", "inbound", "--idempotency-key", cls.prefix + "_lead", "--metadata", "{}",
        ])
        cls.lead_id = lead["lead"]["id"]
        source = cls.invoke([
            "source-add", "--kind", "public_web", "--trust-level", "public_web", "--uri",
            f"https://{cls.prefix}.invalid/evidence", "--provider", "manual", "--stable-id", cls.prefix + "_source",
        ])
        cls.source_id = source["source"]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def invoke(cls, arguments, expect_ok=True, env_extra=None):
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": DATABASE_URL,
            "VCOPS_INBOX_ROOT": str(cls.inbox),
            "VCOPS_QUARANTINE_ROOT": str(cls.quarantine),
            "VCOPS_STATE_ROOT": str(cls.state),
            "VCOPS_APPROVAL_PEPPER": TEST_APPROVAL_PEPPER,
            "VC_TRUSTED_CONTEXT_KEY_FILE": str(cls.trusted_context_key),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [PYTHON, str(HELPER), *arguments, "--json"],
            text=True,
            capture_output=True,
            env=env,
            timeout=30,
        )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"helper emitted invalid JSON: args={arguments} rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}") from exc
        if expect_ok and (proc.returncode != 0 or not payload.get("ok")):
            raise AssertionError(f"helper failed: args={arguments} rc={proc.returncode} payload={payload} stderr={proc.stderr!r}")
        if not expect_ok and proc.returncode == 0:
            raise AssertionError(f"helper unexpectedly succeeded: args={arguments} payload={payload}")
        return payload

    @classmethod
    def trusted_context(
        cls,
        *,
        sender="sender-a",
        event=None,
        nonce=None,
        scopes=("preference.read", "preference.write", "preference.forget"),
        is_group=False,
    ):
        now = int(time.time())
        payload = {
            "v": 1,
            "nonce": nonce or uuid.uuid4().hex + uuid.uuid4().hex[:16],
            "iat": now,
            "exp": now + 900,
            "provider": "slack",
            "account_id": "workspace-a",
            "conversation_id": "dm-a",
            "sender_id": sender,
            "session_hash": hashlib.sha256(f"session:{sender}".encode()).hexdigest(),
            "run_id": "run-" + uuid.uuid4().hex,
            "event_id": event or "event-" + uuid.uuid4().hex,
            "is_group": is_group,
            "media_paths": [],
            "scopes": list(scopes),
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode()
        ).rstrip(b"=").decode()
        signature = base64.urlsafe_b64encode(
            hmac.new(cls.trusted_context_key.read_bytes(), encoded.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        return f"{encoded}.{signature}"

    @classmethod
    def query(cls, sql, parameters=()):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, parameters)
            row = cur.fetchone() if cur.description is not None else None
            return row[0] if row else None

    def test_preferences_are_principal_scoped_replay_safe_and_forget_resets_inference(self):
        sender_a = self.prefix + "-sender-a"
        sender_b = self.prefix + "-sender-b"
        explicit = self.invoke([
            "preference-observe", "--trusted-context", self.trusted_context(sender=sender_a),
            "--preference-key", "memo_length", "--preference-value", "detailed",
            "--observation-kind", "explicit", "--idempotency-key", self.prefix + "_pref_explicit",
        ])
        self.assertTrue(explicit["activated"])

        lookup_a = self.invoke([
            "preference-lookup", "--trusted-context", self.trusted_context(sender=sender_a),
        ])
        self.assertEqual(
            [(item["preference_key"], item["preference_value"]) for item in lookup_a["preferences"]],
            [("memo_length", "detailed")],
        )
        lookup_b = self.invoke([
            "preference-lookup", "--trusted-context", self.trusted_context(sender=sender_b),
        ])
        self.assertEqual(lookup_b["preferences"], [])

        forgotten = self.invoke([
            "preference-forget", "--trusted-context", self.trusted_context(sender=sender_a),
            "--preference-key", "memo_length", "--idempotency-key", self.prefix + "_pref_forget",
        ])
        self.assertIn("memo_length", forgotten["forgotten"])

        for index in range(1, 4):
            inferred = self.invoke([
                "preference-observe", "--trusted-context", self.trusted_context(sender=sender_a),
                "--preference-key", "memo_length", "--preference-value", "short",
                "--observation-kind", "inferred", "--idempotency-key", f"{self.prefix}_pref_inferred_{index}",
            ])
            self.assertEqual(inferred["activated"], index == 3)
            self.assertEqual(inferred["evidence_count"], index)

        replay_token = self.trusted_context(sender=sender_a)
        self.invoke([
            "preference-observe", "--trusted-context", replay_token,
            "--preference-key", "communication_tone", "--preference-value", "balanced",
            "--observation-kind", "explicit", "--idempotency-key", self.prefix + "_pref_replay_1",
        ])
        replay = self.invoke([
            "preference-observe", "--trusted-context", replay_token,
            "--preference-key", "communication_tone", "--preference-value", "balanced",
            "--observation-kind", "explicit", "--idempotency-key", self.prefix + "_pref_replay_2",
        ], expect_ok=False)
        self.assertEqual(replay["error"]["code"], "trusted_context_replay")

        group_write = self.invoke([
            "preference-observe", "--trusted-context", self.trusted_context(sender=sender_a, is_group=True),
            "--preference-key", "research_depth", "--preference-value", "deep",
            "--observation-kind", "explicit", "--idempotency-key", self.prefix + "_pref_group",
        ], expect_ok=False)
        self.assertEqual(group_write["error"]["code"], "group_preference_write_denied")

    def test_idempotent_lead_create_returns_same_row(self):
        repeated = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 CLI Lead",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_lead",
        ])
        self.assertEqual(repeated["lead"]["id"], self.lead_id)
        mismatch = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "Changed replay payload",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_lead",
        ], expect_ok=False)
        self.assertEqual(mismatch["error"]["code"], "idempotency_payload_mismatch")

    def test_invalid_underscore_domain_is_rejected(self):
        self.invoke(["company-upsert", "--name", "Bad DNS", "--domain", "bad_domain.invalid"], expect_ok=False)

    def test_workflow_lifecycle_uses_revisioned_sticky_cancellation(self):
        started = self.invoke([
            "workflow-start", "--workflow", "g4.cli.workflow", "--lead-id", str(self.lead_id),
            "--idempotency-key", self.prefix + "_workflow",
        ])["workflow_run"]
        running = self.invoke([
            "workflow-transition", "--run-id", started["run_id"], "--status", "running",
            "--expected-revision", str(started["record_version"]),
        ])["workflow_run"]
        self.assertEqual(running["status"], "running")
        requested = self.invoke([
            "workflow-cancel", "--run-id", started["run_id"], "--expected-revision",
            str(running["record_version"]), "--reason", "G4 cancellation",
        ])
        self.assertTrue(requested["cooperative_cancel_requested"])
        self.assertEqual(requested["workflow_run"]["status"], "running")
        self.assertIsNotNone(requested["workflow_run"]["cancel_requested_at"])
        cancelled = self.invoke([
            "workflow-transition", "--run-id", started["run_id"], "--status", "cancelled",
            "--expected-revision", str(requested["workflow_run"]["record_version"]),
        ])["workflow_run"]
        self.assertEqual(cancelled["status"], "cancelled")
        self.invoke([
            "workflow-transition", "--run-id", started["run_id"], "--status", "running",
            "--expected-revision", str(cancelled["record_version"]),
        ], expect_ok=False)

        reconcile_key = self.prefix + "_runner_failure"
        failed_run = self.invoke([
            "workflow-start", "--workflow", "evaluate-lead", "--lead-id", str(self.lead_id),
            "--idempotency-key", reconcile_key,
        ])["workflow_run"]
        self.invoke([
            "workflow-transition", "--run-id", failed_run["run_id"], "--status", "running",
            "--expected-revision", str(failed_run["record_version"]),
        ])
        reconciled = self.invoke([
            "workflow-reconcile-failure", "--workflow", "evaluate-lead",
            "--idempotency-key", reconcile_key, "--reason", "lobster_step_failure",
        ])
        self.assertEqual(reconciled["workflow_failure_reconciliation"]["outcome"], "transitioned_failed")
        self.assertEqual(reconciled["workflow_failure_reconciliation"]["workflow_run"]["status"], "failed")
        repeated = self.invoke([
            "workflow-reconcile-failure", "--workflow", "evaluate-lead",
            "--idempotency-key", reconcile_key, "--reason", "lobster_step_failure",
        ])
        self.assertEqual(repeated["workflow_failure_reconciliation"]["outcome"], "already_failed")
        self.assertEqual(repeated["workflow_failure_reconciliation"]["workflow_run"]["status"], "failed")
        missing = self.invoke([
            "workflow-reconcile-failure", "--workflow", "outbound-scout",
            "--idempotency-key", self.prefix + "_no_business_run", "--reason", "lobster_timeout",
        ])
        self.assertEqual(missing["workflow_failure_reconciliation"]["outcome"], "not_started")
        self.assertIsNone(missing["workflow_failure_reconciliation"]["workflow_run"])

    def test_workflow_request_claim_precedes_mutation_and_globally_binds_extraction(self):
        document = self.inbox / f"{self.prefix}-claimed.csv"
        document.write_text("metric,value\narr,1200000\n", encoding="utf-8")
        preview = self.invoke(["document-preview", "--path", str(document)])
        key = self.prefix + "_claimed_intake"
        claim_args = [
            "workflow-request-claim", "--workflow", "inbound-intake", "--idempotency-key", key,
            "--company-name", "G4 CLI Company", "--company-domain", f"{self.prefix}.invalid",
            "--lead-title", "G4 CLI Lead", "--document-path", str(document),
            "--document-sha256", preview["sha256"], "--channel-provider", "telegram",
            "--channel-account-id", "g4", "--channel-event-id", self.prefix + "_event",
        ]
        claim = self.invoke(claim_args)["workflow_request"]
        replay = self.invoke(claim_args)
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["workflow_request"]["id"], claim["id"])

        mismatch = list(claim_args)
        mismatch[mismatch.index("--company-domain") + 1] = f"changed-{self.prefix}.invalid"
        rejected = self.invoke(mismatch, expect_ok=False)
        self.assertEqual(rejected["error"]["code"], "idempotency_payload_mismatch")
        self.assertEqual(
            self.query("SELECT count(*) FROM companies WHERE canonical_domain=%s", (f"changed-{self.prefix}.invalid",)),
            0,
        )

        workflow = self.invoke([
            "workflow-start", "--workflow", "inbound-intake", "--lead-id", str(self.lead_id),
            "--company-id", str(self.company_id), "--idempotency-key", key,
        ])["workflow_run"]
        extract_args = [
            "document-extract", "--path", str(document), "--lead-id", str(self.lead_id),
            "--workflow-run-id", str(workflow["id"]), "--workflow-request-id", str(claim["id"]),
            "--idempotency-key", key, "--trust-level", "untrusted_upload",
            "--confidentiality", "confidential", "--retention-class", "standard",
        ]
        extracted = self.invoke(extract_args)
        repeated = self.invoke(extract_args)
        self.assertFalse(extracted["reused"])
        self.assertTrue(repeated["reused"])
        self.assertEqual(extracted["extraction"]["id"], repeated["extraction"]["id"])
        self.assertEqual(extracted["extraction"]["workflow_request_id"], claim["id"])

        document.write_text("metric,value\narr,9999999\n", encoding="utf-8")
        changed = self.invoke(extract_args, expect_ok=False)
        self.assertEqual(changed["error"]["code"], "idempotency_payload_mismatch")

    def test_entity_resolution_is_literal_private_and_atomically_consumed(self):
        resolution_rows_before = self.query("SELECT count(*) FROM entity_resolution_runs")
        resolved = self.invoke([
            "entity-resolve", "--domain", f"{self.prefix}.invalid",
            "--requester-id", "g4:read-only", "--purpose", "research",
            "--max-confidentiality", "internal",
        ])
        self.assertTrue(resolved["read_only"])
        self.assertFalse(resolved["persisted"])
        self.assertEqual(resolved["decision"]["outcome"], "existing")
        self.assertEqual(resolved["company"]["id"], self.company_id)
        self.assertTrue(resolved["external_research_allowed"])
        self.assertTrue(resolved["external_research"]["reason"])
        self.assertEqual(resolved["operational_history"]["bounded_per_type"], 10)
        self.assertNotIn("content", resolved["operational_history"])

        denied = self.invoke([
            "entity-resolve", "--domain", f"{self.prefix}.invalid",
            "--requester-id", "g4:public", "--purpose", "research",
            "--max-confidentiality", "public",
        ])
        self.assertEqual(denied["decision"]["outcome"], "denied")
        self.assertIsNone(denied["company"])
        self.assertEqual(denied["decision"]["candidates"], [])
        self.assertFalse(denied["external_research_allowed"])

        wildcard = self.invoke([
            "entity-resolve", "--alias", "%_", "--requester-id", "g4:literal",
            "--purpose", "research", "--max-confidentiality", "internal",
        ])
        self.assertEqual(wildcard["decision"]["outcome"], "no_match")
        self.assertEqual(wildcard["decision"]["candidates"], [])
        first_character_typo = self.invoke([
            "entity-resolve", "--name", "X4 CLI Company", "--requester-id", "g4:fuzzy",
            "--purpose", "research", "--max-confidentiality", "internal",
        ])
        self.assertEqual(first_character_typo["decision"]["outcome"], "human_review")
        self.assertTrue(first_character_typo["decision"]["candidates"])
        self.assertFalse(first_character_typo["decision"]["auto_merge"])
        self.assertFalse(first_character_typo["external_research_allowed"])

        self.assertEqual(self.query("SELECT count(*) FROM entity_resolution_runs"), resolution_rows_before)

        key = self.prefix + "_resolved_create"
        domain = f"resolved-{self.prefix}.invalid"
        resolved_name = f"Zeta {self.prefix} QX9"
        claim = self.invoke([
            "workflow-request-claim", "--workflow", "outbound-scout",
            "--idempotency-key", key, "--company-name", resolved_name,
            "--company-domain", domain, "--lead-title", "G4 resolver lead",
        ])["workflow_request"]
        command = [
            "company-resolve-create", "--workflow-request-id", str(claim["id"]),
            "--workflow", "outbound-scout", "--idempotency-key", key,
            "--name", resolved_name, "--domain", domain,
            "--requester-id", "workflow:outbound-scout", "--purpose", "company_creation",
            "--max-confidentiality", "internal",
        ]
        created = self.invoke(command, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        replay = self.invoke(command, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(created["company"]["id"], replay["company"]["id"])
        self.assertFalse(created["reused"])
        self.assertTrue(replay["reused"])
        self.assertEqual(created["resolution"]["consumption_outcome"], "created_new")
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM entity_resolution_consumptions WHERE resolution_decision_id=%s",
                (created["resolution"]["decision_id"],),
            ),
            1,
        )

        unicode_name = f"Straße {self.prefix}"
        unicode_company = self.invoke([
            "company-upsert", "--name", unicode_name,
            "--domain", f"unicode-{self.prefix}.invalid", "--metadata", "{}",
        ])["company"]
        unicode_resolved = self.invoke([
            "entity-resolve", "--name", f"STRASSE {self.prefix.upper()}",
            "--requester-id", "g4:unicode", "--purpose", "research",
            "--max-confidentiality", "internal",
        ])
        self.assertEqual(unicode_resolved["decision"]["outcome"], "existing")
        self.assertEqual(int(unicode_resolved["company"]["id"]), int(unicode_company["id"]))

        legacy_alias = f"Legacy Brand {self.prefix}"
        self.query(
            """INSERT INTO company_aliases
                 (company_id,alias_kind,alias_value,normalized_alias,status,confidentiality,confidence,created_by)
               VALUES (%s,'former_name',%s,%s,'active','internal',0.950,'g4') RETURNING id""",
            (unicode_company["id"], legacy_alias, legacy_alias.casefold()),
        )
        alias_resolved = self.invoke([
            "entity-resolve", "--alias", legacy_alias.upper(),
            "--requester-id", "g4:alias", "--purpose", "research",
            "--max-confidentiality", "internal",
        ])
        self.assertEqual(alias_resolved["decision"]["outcome"], "existing")
        self.assertEqual(int(alias_resolved["company"]["id"]), int(unicode_company["id"]))

        external_id = self.prefix + "_crm_company"
        self.query(
            """INSERT INTO company_external_ids
                 (company_id,provider,provider_account_id,external_id,status,confidentiality,created_by)
               VALUES (%s,'crm','g4',%s,'verified','internal','g4') RETURNING id""",
            (unicode_company["id"], external_id),
        )
        external_resolved = self.invoke([
            "entity-resolve", "--external-provider", "crm", "--external-account-id", "g4",
            "--external-id", external_id, "--requester-id", "g4:external-id",
            "--purpose", "qualification", "--max-confidentiality", "internal",
        ])
        self.assertEqual(external_resolved["decision"]["outcome"], "existing")
        self.assertEqual(int(external_resolved["company"]["id"]), int(unicode_company["id"]))

        conflict_key = self.prefix + "_name_domain_conflict"
        conflict_domain = f"conflict-{self.prefix}.invalid"
        conflict_claim = self.invoke([
            "workflow-request-claim", "--workflow", "outbound-scout",
            "--idempotency-key", conflict_key, "--company-name", "G4 CLI Company",
            "--company-domain", conflict_domain, "--lead-title", "G4 conflict lead",
        ])["workflow_request"]
        blocked = self.invoke([
            "company-resolve-create", "--workflow-request-id", str(conflict_claim["id"]),
            "--workflow", "outbound-scout", "--idempotency-key", conflict_key,
            "--name", "G4 CLI Company", "--domain", conflict_domain,
            "--requester-id", "workflow:outbound-scout", "--purpose", "company_creation",
            "--max-confidentiality", "internal",
        ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(blocked["error"]["code"], "entity_resolution_blocked")
        self.assertEqual(self.query("SELECT count(*) FROM companies WHERE canonical_domain=%s", (conflict_domain,)), 0)
        self.assertEqual(
            self.query(
                """SELECT count(*) FROM entity_resolution_runs r
                   JOIN entity_resolution_decisions d ON d.resolution_run_id=r.id
                   WHERE r.workflow_request_id=%s AND d.outcome='human_review'""",
                (conflict_claim["id"],),
            ),
            1,
        )

    def test_fact_trajectory_contradiction_compiled_truth_evaluation_and_memo(self):
        common = [
            "--lead-id", str(self.lead_id), "--company-id", str(self.company_id), "--fact-type", "arr",
            "--definition", "annual recurring revenue", "--currency", "EUR", "--status", "verified_fact",
            "--confidence", "0.9", "--source-id", str(self.source_id), "--evidence-role", "primary",
        ]
        old = self.invoke([
            "fact-add", *common, "--value", "900k", "--period-start", "2025-01-01", "--period-end", "2025-12-31",
        ])["fact"]
        current = self.invoke([
            "fact-add", *common, "--value", "1.2m", "--period-start", "2026-01-01", "--period-end", "2026-06-30",
        ])["fact"]
        conflict = self.invoke([
            "fact-add", *common, "--value", "800k", "--period-start", "2026-01-01", "--period-end", "2026-06-30",
        ])["fact"]
        trajectory = self.invoke([
            "trajectory-check", "--left-fact-id", str(old["id"]), "--right-fact-id", str(current["id"]),
        ])
        self.assertEqual(trajectory["classification"], "trajectory")
        contradiction = self.invoke([
            "contradiction-check", "--left-fact-id", str(current["id"]), "--right-fact-id", str(conflict["id"]),
        ])
        self.assertEqual(contradiction["classification"], "contradiction")
        snapshot = self.invoke(["compiled-truth", "--lead-id", str(self.lead_id)])["snapshot"]
        criteria = {
            key: self.scored_criterion(5, old["id"], "G4 sourced criterion evidence")
            for key in (
                "thesis_stage_geography_fit", "founder_team_signal", "problem_product_depth",
                "technical_differentiation", "traction_adoption", "market_buyer_timing",
                "business_commercial_evidence", "risk_decision_readiness",
            )
        }
        decision_context = {
            "identity_reliable": True,
            "contradiction_check_complete": True,
            "trajectory_check_complete": True,
            "adjustments": [],
        }
        evidence_hash = snapshot["evidence_packet_hash"]
        evaluation = self.invoke([
            "evaluation-save", "--lead-id", str(self.lead_id), "--compiled-truth-id", str(snapshot["id"]),
            "--criteria", json.dumps(criteria), "--decision-context", json.dumps(decision_context),
            "--status", "final", "--evidence-hash", evidence_hash,
        ])
        self.assertEqual(evaluation["evaluation"]["recommendation_band"], "research_deeper")
        self.assertIn(
            "trajectory_check_complete",
            evaluation["calculation"]["decision_context_audit"]["mismatches_overridden"],
        )
        evaluation = evaluation["evaluation"]
        citations = [
            {
                "fact_id": old["id"], "source_id": self.source_id,
                "citation": "[F-z]", "locator": "G4 second locator",
            },
            {
                "fact_id": old["id"], "source_id": self.source_id,
                "citation": "[F-a]", "locator": "G4 first locator",
            },
        ]
        persisted_citations = sorted(
            citations,
            key=lambda item: (item["fact_id"], item["source_id"], item["citation"], item["locator"]),
        )
        memo_args = [
            "memo-save", "--lead-id", str(self.lead_id), "--evaluation-id", str(evaluation["id"]),
            "--compiled-truth-id", str(snapshot["id"]), "--status", "draft", "--title", "G4 memo",
            "--content", "# G4 memo\n\nCited evidence only. [F-a] [F-z]", "--citations", json.dumps(citations),
            "--evidence-hash", evidence_hash,
        ]
        saved = self.invoke(memo_args)
        memo = saved["memo"]
        self.assertEqual(memo["status"], "draft")
        self.assertFalse(saved["reused"])
        replayed = self.invoke(memo_args)
        self.assertTrue(replayed["reused"])
        self.assertEqual(replayed["memo"]["id"], memo["id"])
        self.assertNotEqual(replayed["citations"], citations)
        self.assertEqual(replayed["citations"], persisted_citations)

        for option, changed_value in (
            ("--title", "Changed G4 memo title"),
            ("--status", "review"),
            ("--citations", json.dumps([{**citations[0], "locator": "Changed caller locator"}, citations[1]])),
        ):
            drifted = list(memo_args)
            drifted[drifted.index(option) + 1] = changed_value
            mismatch = self.invoke(drifted, expect_ok=False)
            self.assertEqual(mismatch["error"]["code"], "idempotency_payload_mismatch")

    def test_compiled_truth_rejects_empty_evidence_and_preserves_numeric_zero(self):
        empty_lead = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 empty truth lead",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_empty_truth",
        ])["lead"]
        empty = self.invoke(["compiled-truth", "--lead-id", str(empty_lead["id"])], expect_ok=False)
        self.assertEqual(empty["error"]["code"], "insufficient_evidence")
        zero_fact = self.invoke([
            "fact-add", "--lead-id", str(empty_lead["id"]), "--company-id", str(self.company_id),
            "--fact-type", "traction_adoption", "--definition", "paying customers", "--value", "0",
            "--value-kind", "numeric", "--status", "verified_fact", "--confidence", "0.9",
            "--source-id", str(self.source_id), "--evidence-role", "primary",
        ])["fact"]
        truth = self.invoke(["compiled-truth", "--lead-id", str(empty_lead["id"])])
        self.assertEqual(truth["snapshot"]["coverage_percent"], "12.50")
        self.assertEqual(truth["verified_fact_count"], 1)
        self.assertEqual(zero_fact["value_numeric"], "0")

    def test_compiled_truth_freezes_contradictions_and_evaluation_uses_database_guards(self):
        lead = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 guarded truth lead",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_guarded_truth",
        ])["lead"]
        common = [
            "--lead-id", str(lead["id"]), "--company-id", str(self.company_id),
            "--definition", "guarded decision evidence", "--status", "verified_fact",
            "--confidence", "0.9", "--source-id", str(self.source_id), "--evidence-role", "primary",
            "--period-start", "2026-01-01", "--period-end", "2026-12-31",
        ]
        safe = self.invoke([
            "fact-add", *common, "--fact-type", "founder_team_signal", "--value", "strong team",
            "--value-kind", "text",
        ])["fact"]
        left = self.invoke([
            "fact-add", *common, "--fact-type", "traction_adoption", "--value", "100",
            "--value-kind", "numeric",
        ])["fact"]
        right = self.invoke([
            "fact-add", *common, "--fact-type", "traction_adoption", "--value", "250",
            "--value-kind", "numeric",
        ])["fact"]
        contradiction = self.invoke([
            "contradiction-check", "--left-fact-id", str(left["id"]), "--right-fact-id", str(right["id"]),
            "--severity", "blocking",
        ])["contradiction"]
        truth = self.invoke(["compiled-truth", "--lead-id", str(lead["id"])])
        snapshot = truth["snapshot"]
        self.assertTrue(snapshot["decision_guards"]["blocking_contradiction"])
        self.assertIn(contradiction["id"], snapshot["decision_guards"]["blocking_contradiction_ids"])
        self.assertEqual(truth["history_fact_count"], 3)
        self.assertEqual(truth["contradiction_count"], 1)

        criteria = {
            key: self.scored_criterion(5, safe["id"], "G4 guarded evidence")
            for key in (
                "thesis_stage_geography_fit", "founder_team_signal", "problem_product_depth",
                "technical_differentiation", "traction_adoption", "market_buyer_timing",
                "business_commercial_evidence", "risk_decision_readiness",
            )
        }
        evaluation = self.invoke([
            "evaluation-save", "--lead-id", str(lead["id"]), "--compiled-truth-id", str(snapshot["id"]),
            "--criteria", json.dumps(criteria),
            "--decision-context", json.dumps({"identity_reliable": True, "blocking_contradiction": False}),
            "--status", "final", "--evidence-hash", snapshot["evidence_packet_hash"],
        ])
        self.assertEqual(evaluation["evaluation"]["recommendation_band"], "needs_human_review")
        self.assertIn("blocking_contradiction", evaluation["calculation"]["decision_context_audit"]["mismatches_overridden"])

        identity_lead = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 identity guard lead",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_identity_guard",
        ])["lead"]
        identity_fact = self.invoke([
            "fact-add", "--lead-id", str(identity_lead["id"]), "--company-id", str(self.company_id),
            "--fact-type", "founder_team_signal", "--definition", "identity guard evidence",
            "--value", "sourced", "--value-kind", "text", "--status", "verified_fact", "--confidence", "0.9",
            "--source-id", str(self.source_id), "--evidence-role", "primary",
        ])["fact"]
        identity_conflict_id = self.query(
            """INSERT INTO contradictions
                 (lead_id,company_id,finding_kind,severity,status,fact_type,definition,explanation,created_by)
               VALUES (%s,%s,'identity_conflict','blocking','open','company_identity','canonical identity',
                       'identity requires review','g4') RETURNING id""",
            (identity_lead["id"], self.company_id),
        )
        identity_truth = self.invoke(["compiled-truth", "--lead-id", str(identity_lead["id"])])["snapshot"]
        self.assertFalse(identity_truth["decision_guards"]["identity_reliable"])
        self.assertIn(identity_conflict_id, identity_truth["decision_guards"]["identity_conflict_ids"])
        identity_criteria = {
            key: self.scored_criterion(5, identity_fact["id"], "G4 identity evidence")
            for key in criteria
        }
        self.query(
            """INSERT INTO contradictions
                 (lead_id,company_id,finding_kind,severity,status,fact_type,definition,explanation,created_by)
               VALUES (%s,%s,'identity_conflict','high','open','company_identity','new identity signal',
                       'identity changed after compilation','g4')""",
            (identity_lead["id"], self.company_id),
        )
        stale = self.invoke([
            "evaluation-save", "--lead-id", str(identity_lead["id"]),
            "--compiled-truth-id", str(identity_truth["id"]), "--criteria", json.dumps(identity_criteria),
            "--decision-context", json.dumps({"identity_reliable": True, "blocking_contradiction": False}),
            "--status", "final", "--evidence-hash", identity_truth["evidence_packet_hash"],
        ], expect_ok=False)
        self.assertEqual(stale["error"]["code"], "stale_compiled_truth")
        identity_truth = self.invoke(["compiled-truth", "--lead-id", str(identity_lead["id"])])["snapshot"]
        identity_evaluation = self.invoke([
            "evaluation-save", "--lead-id", str(identity_lead["id"]),
            "--compiled-truth-id", str(identity_truth["id"]), "--criteria", json.dumps(identity_criteria),
            "--decision-context", json.dumps({"identity_reliable": True, "blocking_contradiction": False}),
            "--status", "final", "--evidence-hash", identity_truth["evidence_packet_hash"],
        ])
        self.assertNotEqual(identity_evaluation["evaluation"]["recommendation_band"], "high_priority")
        self.assertFalse(identity_evaluation["calculation"]["decision_context_audit"]["database_derived"]["identity_reliable"])

    def test_zz_approved_lead_erasure_consumes_the_approval_and_retracts_evidence(self):
        erase_lead = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 erasure lead",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_erase_lead",
        ])["lead"]["id"]
        fact = self.invoke([
            "fact-add", "--lead-id", str(erase_lead), "--company-id", str(self.company_id),
            "--fact-type", "founder_team_signal", "--definition", "personal detail", "--value", "sensitive",
            "--value-kind", "text", "--status", "verified_fact", "--confidence", "0.9",
            "--source-id", str(self.source_id), "--evidence-role", "primary",
        ])["fact"]
        # A non-standard-status fact (contradicted) must also be erased: erasure
        # retracts every live status, not just claim/verified/inference.
        contradicted_fact = self.invoke([
            "fact-add", "--lead-id", str(erase_lead), "--company-id", str(self.company_id),
            "--fact-type", "traction_signal", "--definition", "disputed metric", "--value", "leaked",
            "--value-kind", "text", "--status", "contradicted", "--confidence", "0.4",
            "--source-id", str(self.source_id), "--evidence-role", "contradicting",
        ])["fact"]
        scope = {"lead_id": erase_lead, "operation": "data.erase_lead"}
        payload_hash = canonical_hash({"lead_id": erase_lead})
        requested = self.invoke([
            "approval-request", "--idempotency-key", self.prefix + "_erase_appr", "--action", "data.erase_lead",
            "--scope", json.dumps(scope), "--action-preview", json.dumps({"lead_id": erase_lead}),
            "--target-system", "internal-erasure", "--lead-id", str(erase_lead),
            "--payload-hash", payload_hash, "--requested-by", "g4-operator",
        ])
        self.invoke([
            "approval-decide", "--request-id", requested["approval"]["request_id"], "--decision", "approve",
            "--approver", "g4-operator", "--approval-channel", "g4-channel", "--reason", "subject erasure reviewed",
        ], env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"})

        erase_args = [
            "data-erase-lead", "--lead-id", str(erase_lead), "--token", requested["token"],
            "--scope", json.dumps(scope), "--target-system", "internal-erasure",
            "--payload-hash", payload_hash, "--transaction-id", self.prefix + "_erase_tx", "--actor", "g4-operator",
        ]
        result = self.invoke(erase_args)["erasure"]
        self.assertEqual(result["retracted_facts"], 2)
        self.assertEqual(result["lead_status"], "archived")
        # lead archived, approval consumed, and both facts superseded by retracted rows
        self.assertEqual(self.query("SELECT status FROM leads WHERE id=%s", (erase_lead,)), "archived")
        self.assertEqual(
            self.query("SELECT status FROM approvals WHERE request_id=%s", (requested["approval"]["request_id"],)),
            "consumed",
        )
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE supersedes_fact_id=%s", (fact["id"],)), "retracted",
        )
        # the contradicted fact is retracted too (regression guard: the retraction
        # filter must exclude only the 'retracted' tombstone status)
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE supersedes_fact_id=%s", (contradicted_fact["id"],)),
            "retracted",
        )
        self.assertEqual(
            self.query("SELECT count(*) FROM audit_events WHERE event_type='data.erasure' AND entity_id=%s",
                       (str(erase_lead),)),
            1,
        )
        # the one-time approval is burned: a replay fails closed. The governed
        # consume_approval raises SQLSTATE 28000, now surfaced as a typed,
        # actionable error rather than an opaque internal_error.
        replay = self.invoke(erase_args, expect_ok=False)
        self.assertEqual(replay["error"]["code"], "authorization_denied")

    def test_erasure_binding_is_enforced_at_the_sql_boundary_not_only_in_the_helper(self):
        # A direct SQL caller (bypassing vcops entirely) holding a valid
        # approval scoped to lead A must not be able to erase lead B: the
        # database function re-verifies the consumed approval's own stored
        # scope against the target lead. The rejected attempt rolls back, so
        # the one-time approval survives for its legitimate use.
        lead_a = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 binding lead A",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_bind_lead_a",
        ])["lead"]["id"]
        lead_b = self.invoke([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4 binding lead B",
            "--origin-group", "inbound", "--idempotency-key", self.prefix + "_bind_lead_b",
        ])["lead"]["id"]
        scope = {"lead_id": lead_a, "operation": "data.erase_lead"}
        payload_hash = canonical_hash({"lead_id": lead_a})
        requested = self.invoke([
            "approval-request", "--idempotency-key", self.prefix + "_bind_appr", "--action", "data.erase_lead",
            "--scope", json.dumps(scope), "--action-preview", json.dumps({"lead_id": lead_a}),
            "--target-system", "internal-erasure", "--lead-id", str(lead_a),
            "--payload-hash", payload_hash, "--requested-by", "g4-operator",
        ])
        self.invoke([
            "approval-decide", "--request-id", requested["approval"]["request_id"], "--decision", "approve",
            "--approver", "g4-operator", "--approval-channel", "g4-channel", "--reason", "binding test",
        ], env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"})
        token_hash = hashlib.sha256((TEST_APPROVAL_PEPPER + requested["token"]).encode()).hexdigest()
        scope_hash = canonical_hash(scope)
        with self.assertRaises(psycopg.errors.InvalidAuthorizationSpecification):
            self.query(
                "SELECT consume_approval_and_erase_lead(%s,%s,%s,'data.erase_lead',%s,%s,%s,%s)",
                (lead_b, token_hash, scope_hash, "internal-erasure", payload_hash,
                 self.prefix + "_bind_cross_tx", "g4-attacker"),
            )
        # The cross-lead attempt rolled back completely: lead B untouched and
        # the approval still consumable for its own lead.
        self.assertNotEqual(self.query("SELECT status FROM leads WHERE id=%s", (lead_b,)), "archived")
        self.assertEqual(
            self.query("SELECT status FROM approvals WHERE request_id=%s", (requested["approval"]["request_id"],)),
            "approved",
        )
        legit = self.query(
            "SELECT consume_approval_and_erase_lead(%s,%s,%s,'data.erase_lead',%s,%s,%s,%s)",
            (lead_a, token_hash, scope_hash, "internal-erasure", payload_hash,
             self.prefix + "_bind_legit_tx", "g4-operator"),
        )
        self.assertEqual(legit["lead_status"], "archived")
        self.assertEqual(self.query("SELECT status FROM leads WHERE id=%s", (lead_a,)), "archived")

    def test_data_erase_lead_refuses_when_scope_lead_id_does_not_match_target(self):
        # The approval scope must bind lead_id to the erased lead; a scope naming a
        # different lead is refused before any approval is consumed, so an approval
        # reviewed for one lead can never be replayed to erase another.
        mismatched = self.invoke([
            "data-erase-lead", "--lead-id", str(self.lead_id), "--token", "irrelevant-token",
            "--scope", json.dumps({"lead_id": self.lead_id + 1, "operation": "data.erase_lead"}),
            "--target-system", "internal-erasure", "--payload-hash", "0" * 64,
            "--transaction-id", self.prefix + "_erase_mismatch_tx", "--actor", "g4-operator",
        ], expect_ok=False)
        self.assertEqual(mismatched["error"]["code"], "scope_lead_mismatch")

    def test_standalone_approval_consumption_is_refused_without_burning_token(self):
        scope = {"lead_id": self.lead_id, "operation": "crm.write"}
        preview = {"record": "g4", "operation": "create"}
        payload_hash = canonical_hash(preview)
        requested = self.invoke([
            "approval-request", "--idempotency-key", self.prefix + "_approval", "--action", "crm.write",
            "--scope", json.dumps(scope), "--action-preview", json.dumps(preview), "--target-system", "crm-test",
            "--lead-id", str(self.lead_id), "--payload-hash", payload_hash, "--requested-by", "g4-operator",
        ])
        decision_args = [
            "approval-decide", "--request-id", requested["approval"]["request_id"], "--decision", "approve",
            "--approver", "g4-operator", "--approval-channel", "g4-channel", "--reason", "exact scope reviewed",
        ]
        self.invoke(decision_args, expect_ok=False)
        approved = self.invoke(decision_args, env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"})
        self.assertEqual(approved["approval"]["status"], "approved")
        consumed_args = [
            "approval-consume", "--token", requested["token"], "--action", "crm.write", "--scope", json.dumps(scope),
            "--target-system", "crm-test", "--payload-hash", payload_hash, "--transaction-id", self.prefix + "_tx",
            "--consumed-by", "g4-worker",
        ]
        refused = self.invoke(consumed_args, expect_ok=False)
        self.assertEqual(refused["error"]["code"], "atomic_governed_action_required")
        self.assertEqual(
            "approved",
            self.query(
                "SELECT status FROM approvals WHERE request_id=%s",
                (requested["approval"]["request_id"],),
            ),
        )

    def test_notification_cli_is_internal_log_only_and_payload_bound(self):
        enqueued = self.invoke([
            "notification-enqueue", "--idempotency-key", self.prefix + "_notice", "--dedupe-key", self.prefix + "_dedupe",
            "--provider", "internal_log", "--account-id", "g4-account", "--destination", "g4-log", "--lead-id", str(self.lead_id),
            "--severity", "silent_log", "--subject", "G4 notification", "--payload", '{"text":"G4"}',
        ])["notification"]
        duplicate = self.invoke([
            "notification-enqueue", "--idempotency-key", self.prefix + "_notice", "--dedupe-key", self.prefix + "_dedupe",
            "--provider", "internal_log", "--account-id", "g4-account", "--destination", "g4-log", "--lead-id", str(self.lead_id),
            "--severity", "silent_log", "--subject", "G4 notification", "--payload", '{"text":"G4"}',
        ])["notification"]
        self.assertEqual(duplicate["id"], enqueued["id"])
        self.assertEqual(enqueued["status"], "logged")
        mismatch = self.invoke([
            "notification-enqueue", "--idempotency-key", self.prefix + "_notice", "--dedupe-key", self.prefix + "_dedupe",
            "--provider", "internal_log", "--account-id", "g4-account", "--destination", "g4-log", "--lead-id", str(self.lead_id),
            "--severity", "silent_log", "--subject", "Changed", "--payload", '{"text":"G4"}',
        ], expect_ok=False)
        self.assertEqual(mismatch["error"]["code"], "idempotency_payload_mismatch")
        self.invoke(["notification-claim", "--worker", "g4-worker", "--lease-seconds", "60"], expect_ok=False)
        self.invoke([
            "notification-enqueue", "--idempotency-key", self.prefix + "_proactive", "--dedupe-key", self.prefix + "_proactive",
            "--provider", "slack", "--destination", "g4-channel", "--severity", "normal",
            "--subject", "Not shipped", "--payload", "{}",
        ], expect_ok=False)

    def test_z_entity_resolution_returns_current_facts_with_allowed_provenance(self):
        verified = self.invoke([
            "fact-add", "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "resolver_current_metric", "--definition", "resolver current metric",
            "--value", "42", "--value-kind", "numeric", "--status", "verified_fact",
            "--confidence", "0.9", "--source-id", str(self.source_id), "--evidence-role", "primary",
        ])["fact"]
        submitted = self.invoke([
            "fact-add", "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "resolver_unverified_metric", "--definition", "resolver unverified metric",
            "--value", "99", "--value-kind", "numeric", "--status", "submitted_claim",
            "--confidence", "0.5", "--source-id", str(self.source_id), "--evidence-role", "supporting",
        ])["fact"]
        confidential_source = self.invoke([
            "source-add", "--kind", "primary_document", "--trust-level", "untrusted_upload",
            "--confidentiality", "confidential", "--provider", "manual",
            "--stable-id", self.prefix + "_confidential_resolver_source",
        ])["source"]
        confidential_fact = self.invoke([
            "fact-add", "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "resolver_confidential_metric", "--definition", "resolver confidential metric",
            "--value", "7", "--value-kind", "numeric", "--status", "verified_fact",
            "--confidence", "0.9", "--source-id", str(confidential_source["id"]),
            "--evidence-role", "primary",
        ])["fact"]

        resolved = self.invoke([
            "entity-resolve", "--company-id", str(self.company_id),
            "--requester-id", "g4:fact-provenance", "--purpose", "research",
            "--max-confidentiality", "internal", "--limit", "50",
        ])
        fact_by_id = {int(fact["id"]): fact for fact in resolved["current_facts"]}
        self.assertIn(int(verified["id"]), fact_by_id)
        self.assertNotIn(int(submitted["id"]), fact_by_id)
        self.assertNotIn(int(confidential_fact["id"]), fact_by_id)
        current = fact_by_id[int(verified["id"])]
        self.assertTrue(current["current_state"])
        self.assertTrue(current["provenance"])
        self.assertEqual(int(current["provenance"][0]["source_id"]), int(self.source_id))
        self.assertEqual(current["provenance"][0]["confidentiality"], "internal")

    def test_fact_add_refuses_verified_fact_without_a_source(self):
        # A dedicated company keeps this verified fact out of the shared
        # company's compiled-truth snapshots.
        company = self.invoke([
            "company-upsert", "--name", f"Provenance Gate {self.prefix}",
            "--domain", f"provgate-{self.prefix}.invalid", "--metadata", "{}",
        ])["company"]["id"]
        refused = self.invoke([
            "fact-add", "--company-id", str(company), "--fact-type", "test_metric",
            "--definition", "verified facts need provenance", "--value", "42",
            "--status", "verified_fact",
        ], expect_ok=False)
        self.assertEqual(refused["error"]["code"], "verified_fact_requires_source")
        accepted = self.invoke([
            "fact-add", "--company-id", str(company), "--fact-type", "test_metric",
            "--definition", "verified facts need provenance", "--value", "42",
            "--status", "verified_fact", "--source-id", str(self.source_id),
        ])
        self.assertEqual(accepted["fact"]["fact_status"], "verified_fact")

    def test_source_add_refuses_silent_trust_or_confidentiality_downgrade(self):
        base = [
            "source-add", "--kind", "public_web", "--provider", "manual",
            "--account-id", "default", "--stable-id", self.prefix + "_downgrade",
        ]
        created = self.invoke([
            *base, "--trust-level", "paid_connector", "--confidentiality", "restricted",
            "--uri", f"https://sec-{self.prefix}.invalid/filing",
        ])["source"]
        refused = self.invoke([
            *base, "--trust-level", "untrusted_upload", "--confidentiality", "public",
            "--uri", f"https://evil-{self.prefix}.invalid/replay",
        ], expect_ok=False)
        self.assertEqual(refused["error"]["code"], "source_downgrade_refused")
        row = self.query(
            "SELECT trust_level || ':' || confidentiality || ':' || canonical_uri"
            " FROM sources WHERE id=%s", (created["id"],),
        )
        self.assertEqual(
            row, f"paid_connector:restricted:https://sec-{self.prefix}.invalid/filing",
        )
        # A deliberate operator downgrade stays possible, but only explicitly.
        allowed = self.invoke([
            *base, "--trust-level", "untrusted_upload", "--confidentiality", "public",
            "--uri", f"https://evil-{self.prefix}.invalid/replay", "--allow-downgrade",
        ])["source"]
        self.assertEqual(allowed["trust_level"], "untrusted_upload")

    def test_workflow_cancel_refuses_a_mismatched_expected_workflow(self):
        started = self.invoke([
            "workflow-start", "--workflow", "g4.cli.cancelguard", "--lead-id", str(self.lead_id),
            "--idempotency-key", self.prefix + "_cancelguard",
        ])["workflow_run"]
        running = self.invoke([
            "workflow-transition", "--run-id", started["run_id"], "--status", "running",
            "--expected-revision", str(started["record_version"]),
        ])["workflow_run"]
        mismatch = self.invoke([
            "workflow-cancel", "--run-id", started["run_id"],
            "--expected-revision", str(running["record_version"]),
            "--reason", "guard test", "--expected-workflow", "evaluate-lead",
        ], expect_ok=False)
        self.assertEqual(mismatch["error"]["code"], "workflow_mismatch")
        self.assertEqual(
            mismatch["error"]["details"]["actual_workflow"], "g4.cli.cancelguard",
        )
        matched = self.invoke([
            "workflow-cancel", "--run-id", started["run_id"],
            "--expected-revision", str(running["record_version"]),
            "--reason", "guard test",
        ])
        self.assertTrue(matched["cooperative_cancel_requested"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
