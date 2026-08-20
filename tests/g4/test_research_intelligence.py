# SPDX-License-Identifier: Apache-2.0
"""Adversarial end-to-end coverage for autonomous research-intelligence persistence.

Executes the real evidence-record / contradiction-record / trajectory-record /
memo-record workflow files against the live database and proves the CR-001
security invariants: agent-lane writes land as submitted_claim only, promotion
to verified_fact happens exclusively through the deterministic SECURITY DEFINER
predicate, untrusted uploads can never corroborate, a model label cannot make a
source official, memos cannot cite outside their frozen snapshot, and the memo
body round-trips through the integrity-checked read-back.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg

from test_workflow_execution import LobsterStepError, LobsterStepRunner, build_trusted_context
from typing import Any, ClassVar

OWNER_DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_URL = os.environ.get("G4_RUNTIME_DATABASE_URL", "")
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))
PYTHON = os.environ.get("G4_PYTHON", sys.executable)


def one_row(cur):
    """Return the row a RETURNING statement is required to have produced."""
    row = cur.fetchone()
    assert row is not None, "expected one row from the preceding statement"
    return row


class ResearchIntelligenceTests(unittest.TestCase):
    # State handed from one ordered test to the next via type(self).<name>.
    # Declared so the sharing is visible at the top of the class instead of
    # being implied by an assignment several hundred lines down.
    claim_hash: ClassVar[Any]
    cited_fact_id: ClassVar[Any]
    cited_source_id: ClassVar[Any]
    fact_id: ClassVar[Any]
    verified_fact_id: ClassVar[Any]

    @classmethod
    def setUpClass(cls):
        if not DATABASE_URL or not OWNER_DATABASE_URL:
            raise AssertionError("G4 database URLs are required; database tests may not skip")
        cls.prefix = "g4ri-" + uuid.uuid4().hex[:10]
        cls.tmp = tempfile.TemporaryDirectory(prefix="openclaw-g4-research-")
        base = Path(cls.tmp.name)
        cls.inbox = base / "inbox"
        cls.media = base / "media"
        cls.quarantine = base / "quarantine"
        cls.state_root = base / "state"
        for directory in (cls.inbox, cls.media, cls.quarantine, cls.state_root):
            directory.mkdir()
        cls.trusted_context_key = base / "trusted-context.key"
        cls.trusted_context_key.write_bytes(b"g4-test-trusted-context-key-00000000000000000000000000000000")
        cls.env_base = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "DATABASE_URL": DATABASE_URL,
            "VCOPS_WORKFLOW_MODE": "1",
            "VCOPS_INBOX_ROOT": str(cls.inbox),
            "VCOPS_MEDIA_ROOT": str(cls.media),
            "VCOPS_QUARANTINE_ROOT": str(cls.quarantine),
            "VCOPS_STATE_ROOT": str(cls.state_root),
            "VCOPS_APPROVAL_PEPPER": "g4-test-only-approval-pepper-0000000000000000",
            "VC_TRUSTED_CONTEXT_KEY_FILE": str(cls.trusted_context_key),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        company = cls.operator([
            "company-upsert", "--name", f"Researchable {uuid.uuid4().hex[:10]}",
            "--domain", f"{cls.prefix}.invalid", "--metadata", "{}",
        ])["company"]
        cls.company_id = company["id"]
        cls.lead_id = cls.operator([
            "create-lead", "--company-id", str(cls.company_id), "--lead-title", "G4RI lead",
            "--origin-group", "outbound", "--idempotency-key", cls.prefix + "-lead",
        ])["lead"]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def invoke(cls, arguments, expect_ok=True, env_extra=None):
        env = os.environ.copy()
        env.update({key: value for key, value in cls.env_base.items() if key != "VCOPS_WORKFLOW_MODE"})
        if env_extra:
            env.update(env_extra)
        process = subprocess.run(
            [PYTHON, str(HELPER), *arguments, "--json"], env=env, text=True, capture_output=True, timeout=30,
        )
        payload = json.loads(process.stdout)
        if expect_ok and (process.returncode != 0 or not payload.get("ok")):
            raise AssertionError(f"helper failed: args={arguments} payload={payload}")
        if not expect_ok and process.returncode == 0:
            raise AssertionError(f"helper unexpectedly succeeded: args={arguments} payload={payload}")
        return payload

    @classmethod
    def operator(cls, arguments, expect_ok=True):
        return cls.invoke(arguments, expect_ok=expect_ok)

    @classmethod
    def query(cls, sql, parameters=(), *, owner=False):
        with psycopg.connect(OWNER_DATABASE_URL if owner else DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, parameters)
            row = cur.fetchone() if cur.description is not None else None
            return row[0] if row else None

    def execute(self, workflow_file, args):
        return LobsterStepRunner(workflow_file, args, self.env_base).run()

    @classmethod
    def content_hash(cls, tag):
        return hashlib.sha256(f"{cls.prefix}:{tag}".encode("utf-8")).hexdigest()

    @classmethod
    def evidence(cls, url, claim=None, content_tag=None, **overrides):
        source = {"url": url}
        if content_tag is not None:
            # Verified-content identity of the fetched page bytes; web evidence
            # corroborates by this, not by the model-chosen host.
            source["content_sha256"] = cls.content_hash(content_tag)
        payload = {
            "claim": claim or f"{cls.prefix} ARR reached 1.2m EUR in H1 2026",
            "fact_type": "traction_adoption",
            "confidence": "high",
            "produced_by": "traction-analyst",
            "period_start": "2026-01-01",
            "period_end": "2026-06-30",
            "source": source,
        }
        payload.update(overrides)
        return json.dumps(payload)

    def test_01_evidence_lands_as_submitted_claim_with_provenance(self):
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ev1",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://news-{self.prefix}.invalid/arr", content_tag="A"),
        })
        run_id = state["workflow_start"]["json"]["workflow_run"]["run_id"]
        self.assertEqual(self.query("SELECT status FROM workflow_runs WHERE run_id=%s", (run_id,)), "succeeded")
        persisted = state["evidence_persist"]["json"]
        self.assertFalse(persisted["reused"])
        type(self).fact_id = persisted["fact"]["id"]
        type(self).claim_hash = persisted["claim_hash"]
        self.assertEqual(persisted["fact"]["fact_status"], "submitted_claim")
        self.assertEqual(
            self.query("SELECT count(*) FROM fact_sources WHERE fact_id=%s", (self.fact_id,)), 1,
        )
        promote = state["fact_promote"]["json"]
        self.assertFalse(promote["promoted"])
        self.assertEqual(promote["reason"], "insufficient_corroboration")
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE id=%s", (self.fact_id,)), "submitted_claim",
        )

    def test_02_replay_is_noop_and_independent_corroboration_promotes(self):
        # Content-addressed dedup: a fresh logical call with identical
        # claim/value content is a no-op on the fact — it reuses the existing
        # claim row and adds no duplicate source (same host).
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ev1-content-replay",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://news-{self.prefix}.invalid/arr", content_tag="A"),
        })
        replay = state["evidence_persist"]["json"]
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["fact"]["id"], self.fact_id)
        self.assertEqual(
            self.query("SELECT count(*) FROM fact_sources WHERE fact_id=%s", (self.fact_id,)), 1,
        )
        # Same-key replay of a completed run is refused at the transition step,
        # consistent with every fixed workflow: a crash-retry uses the same key
        # and reconciliation, not a silent re-run.
        with self.assertRaises(LobsterStepError) as same_key:
            self.execute("evidence-record.lobster", {
                "idempotency_key": self.prefix + "-ev1",
                "lead_id": str(self.lead_id),
                "evidence_json": self.evidence(f"https://news-{self.prefix}.invalid/arr", content_tag="A"),
            })
        self.assertIn("invalid_transition", str(same_key.exception))
        # A second source with DISTINCT verified content (content_tag "B") is the
        # independent corroboration that promotes: two distinct content hashes,
        # not two distinct hosts.
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ev2",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://registry-{self.prefix}.invalid/fact", content_tag="B"),
        })
        second = state["evidence_persist"]["json"]
        self.assertTrue(second["reused"])
        self.assertEqual(second["fact"]["id"], self.fact_id)
        promote = state["fact_promote"]["json"]
        self.assertTrue(promote["promoted"])
        verified = promote["fact"]
        self.assertEqual(verified["fact_status"], "verified_fact")
        self.assertEqual(verified["supersedes_fact_id"], self.fact_id)
        type(self).verified_fact_id = verified["id"]
        self.assertEqual(
            self.query("SELECT count(*) FROM fact_sources WHERE fact_id=%s", (verified["id"],)), 2,
        )
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE id=%s", (self.fact_id,)), "submitted_claim",
        )
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM audit_events WHERE event_type='fact.promoted' AND entity_id=%s",
                (str(verified["id"]),),
            ),
            1,
        )

    def _ingest_document(self, tag, body):
        document = self.media / f"{self.prefix}-{tag}.csv"
        document.write_text(body, encoding="utf-8")
        path_hash = hashlib.sha256(str(document.absolute()).encode("utf-8")).hexdigest()
        token = build_trusted_context(
            self.trusted_context_key,
            scopes=(f"document.read:{path_hash}", f"document.ingest:{path_hash}"),
            media_paths=(str(document.absolute()),),
        )
        ingest = self.execute("document-ingest.lobster", {
            "idempotency_key": f"{self.prefix}-ingest-{tag}",
            "document_path": str(document),
            "trusted_context": token,
        })
        return ingest["document_extract"]["json"]["extraction"]["id"]

    def test_03_two_untrusted_sources_record_locators_but_the_exclusion_blocks_promotion(self):
        # Two DISTINCT untrusted-upload sources: without the trust-level
        # exclusion the min_independent_sources=2 bar would be met and the claim
        # would promote. The exclusion is therefore the only thing refusing it —
        # so this proves the prompt-injection carrier cannot corroborate itself.
        first = self._ingest_document("deck", "metric,value\nburn,200000\n")
        second = self._ingest_document("memo", "metric,value\nburn,200001\n")
        claim = f"{self.prefix} monthly burn is 200k EUR"
        for tag, extraction_id, cell in (("a", first, "B2"), ("b", second, "B3")):
            state = self.execute("evidence-record.lobster", {
                "idempotency_key": f"{self.prefix}-doc-ev-{tag}",
                "lead_id": str(self.lead_id),
                "evidence_json": json.dumps({
                    "claim": claim,
                    "fact_type": "business_commercial_evidence",
                    "confidence": 0.8,
                    "produced_by": "document-intake-analyst",
                    "document": {"extraction_id": extraction_id, "sheet_name": "Sheet1", "cell_range": cell},
                }),
            })
            persisted = state["evidence_persist"]["json"]
            fact_id = persisted["fact"]["id"]
            self.assertEqual(persisted["source"]["trust_level"], "untrusted_upload")
            self.assertFalse(state["fact_promote"]["json"]["promoted"])
        self.assertEqual(
            self.query(
                "SELECT count(DISTINCT source_id) FROM fact_sources WHERE fact_id=%s", (fact_id,),
            ),
            2,
        )
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM document_facts WHERE fact_id=%s AND cell_range IN ('B2','B3')",
                (fact_id,),
            ),
            2,
        )
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE id=%s", (fact_id,)), "submitted_claim",
        )

    def test_04_model_assertions_cannot_mint_verified_facts(self):
        with self.assertRaises(LobsterStepError) as failure:
            self.execute("evidence-record.lobster", {
                "idempotency_key": self.prefix + "-inject",
                "lead_id": str(self.lead_id),
                "evidence_json": self.evidence(
                    f"https://inject-{self.prefix}.invalid/x",
                    claim=f"{self.prefix} injected claim",
                    fact_status="verified_fact",
                ),
            })
        self.assertIn("invalid_evidence", str(failure.exception))
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-regulatory",
            "lead_id": str(self.lead_id),
            "evidence_json": json.dumps({
                "claim": f"{self.prefix} claims official registration",
                "fact_type": "thesis_stage_geography_fit",
                "confidence": "high",
                "produced_by": "founder-researcher",
                "source": {"url": f"https://fake-registry-{self.prefix}.invalid/entry", "kind": "regulatory_filing"},
            }),
        })
        persisted = state["evidence_persist"]["json"]
        self.assertEqual(persisted["source"]["source_kind"], "public_web")
        self.assertFalse(state["fact_promote"]["json"]["promoted"])
        for mode, code in (
            ({"VCOPS_WORKFLOW_MODE": "1"}, "workflow_command_forbidden"),
            ({"VCOPS_AGENT_MODE": "1"}, "agent_command_forbidden"),
        ):
            refused = self.invoke([
                "fact-add", "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
                "--fact-type", "traction_adoption", "--definition", "direct write", "--value", "1",
                "--status", "verified_fact",
            ], expect_ok=False, env_extra=mode)
            self.assertEqual(refused["error"]["code"], code)
        elevated = self.invoke([
            "evidence-record", "--lead-id", str(self.lead_id),
            "--evidence", json.dumps({
                "claim": "elevated trust", "fact_type": "traction_adoption", "confidence": 1,
                "produced_by": "x", "source": {"url": "https://a.invalid/x", "trust_level": "internal_admin"},
            }),
        ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(elevated["error"]["code"], "invalid_evidence")

    def test_05_contradiction_and_trajectory_record_workflows_persist(self):
        source = self.operator([
            "source-add", "--kind", "public_web", "--trust-level", "public_web", "--uri",
            f"https://{self.prefix}.invalid/ops", "--provider", "manual", "--stable-id", self.prefix + "-ops",
        ])["source"]
        common = [
            "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "arr", "--definition", "annual recurring revenue", "--currency", "EUR",
            "--status", "verified_fact", "--confidence", "0.9", "--source-id", str(source["id"]),
            "--evidence-role", "primary",
        ]
        old = self.operator([
            "fact-add", *common, "--value", "900k", "--period-start", "2025-01-01", "--period-end", "2025-12-31",
        ])["fact"]
        current = self.operator([
            "fact-add", *common, "--value", "1.2m", "--period-start", "2026-01-01", "--period-end", "2026-06-30",
        ])["fact"]
        conflict = self.operator([
            "fact-add", *common, "--value", "800k", "--period-start", "2026-01-01", "--period-end", "2026-06-30",
        ])["fact"]
        state = self.execute("contradiction-record.lobster", {
            "idempotency_key": self.prefix + "-contra",
            "lead_id": str(self.lead_id),
            "left_fact_id": str(current["id"]),
            "right_fact_id": str(conflict["id"]),
            "severity": "blocking",
        })
        check = state["contradiction_check"]["json"]
        self.assertEqual(check["classification"], "contradiction")
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM contradiction_facts WHERE contradiction_id=%s",
                (check["contradiction"]["id"],),
            ),
            2,
        )
        state = self.execute("trajectory-record.lobster", {
            "idempotency_key": self.prefix + "-traj",
            "lead_id": str(self.lead_id),
            "left_fact_id": str(old["id"]),
            "right_fact_id": str(current["id"]),
        })
        check = state["trajectory_check"]["json"]
        self.assertEqual(check["classification"], "trajectory")
        self.assertEqual("up", check["trajectory"]["direction"])
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM trajectory_points WHERE trajectory_event_id=%s",
                (check["trajectory"]["id"],),
            ),
            2,
        )
        # Chronology, not argument order, decides direction: the same pair
        # recorded with left/right swapped must persist the same 'up', never a
        # caller-invertible 'down'.
        state = self.execute("trajectory-record.lobster", {
            "idempotency_key": self.prefix + "-traj-rev",
            "lead_id": str(self.lead_id),
            "left_fact_id": str(current["id"]),
            "right_fact_id": str(old["id"]),
        })
        check = state["trajectory_check"]["json"]
        self.assertEqual(check["classification"], "trajectory")
        self.assertEqual("up", check["trajectory"]["direction"])
        type(self).cited_fact_id = old["id"]
        type(self).cited_source_id = source["id"]

    def test_06_memo_record_persists_from_snapshot_and_reads_back_with_integrity(self):
        snapshot = self.operator(["compiled-truth", "--lead-id", str(self.lead_id)])["snapshot"]
        criterion = {
            "evidence_state": "positive", "quality_score": 5, "coverage": "complete",
            "evidence_quality": "high", "evidence_fact_ids": [self.cited_fact_id],
            "counterevidence_fact_ids": [], "rationale": "G4RI sourced criterion",
            "what_would_change": "a current contradictory verified fact",
        }
        criteria = {
            key: dict(criterion)
            for key in (
                "thesis_stage_geography_fit", "founder_team_signal", "problem_product_depth",
                "technical_differentiation", "traction_adoption", "market_buyer_timing",
                "business_commercial_evidence", "risk_decision_readiness",
            )
        }
        evaluation = self.operator([
            "evaluation-save", "--lead-id", str(self.lead_id), "--compiled-truth-id", str(snapshot["id"]),
            "--criteria", json.dumps(criteria),
            "--decision-context", json.dumps({"identity_reliable": True, "blocking_contradiction": True}),
            "--status", "final", "--evidence-hash", snapshot["evidence_packet_hash"],
        ])["evaluation"]
        # A2: the chief retrieves the ids memo-record needs via the read-only
        # evaluation-show command (the path that was previously missing).
        shown = self.invoke(
            ["evaluation-show", "--lead-id", str(self.lead_id)], env_extra={"VCOPS_AGENT_MODE": "1"},
        )["evaluation"]
        self.assertEqual(shown["id"], evaluation["id"])
        self.assertEqual(shown["compiled_truth_id"], snapshot["id"])
        self.assertEqual(shown["evidence_hash"], snapshot["evidence_packet_hash"])
        citations = [{
            "fact_id": self.cited_fact_id, "source_id": self.cited_source_id,
            "citation": "[F-1]", "locator": "G4RI locator",
        }]
        memo_markdown = "# G4RI memo\n\nEvidence-backed only. [F-1]"
        state = self.execute("memo-record.lobster", {
            "idempotency_key": self.prefix + "-memo",
            "lead_id": str(self.lead_id),
            "evaluation_id": str(evaluation["id"]),
            "compiled_truth_id": str(snapshot["id"]),
            "memo_title": "G4RI memo",
            "memo_markdown": memo_markdown,
            "citations_json": json.dumps(citations),
            "evidence_hash": snapshot["evidence_packet_hash"],
        })
        memo = state["memo_persist"]["json"]["memo"]
        self.assertEqual(memo["status"], "draft")
        self.assertEqual(
            self.query("SELECT count(*) FROM memo_citations WHERE memo_id=%s", (memo["id"],)), 1,
        )
        shown = self.invoke(
            ["memo-show", "--memo-id", str(memo["id"])], env_extra={"VCOPS_AGENT_MODE": "1"},
        )
        self.assertEqual(shown["content"], memo_markdown)
        self.assertEqual(shown["citations"][0]["fact_id"], self.cited_fact_id)

        # A memo inherits its lead's confidentiality boundary: the model lane
        # must not read a restricted lead's memo body, exactly like lead-show.
        self.query(
            "UPDATE leads SET confidentiality='restricted' WHERE id=%s", (self.lead_id,), owner=True,
        )
        try:
            denied = self.invoke(
                ["memo-show", "--memo-id", str(memo["id"])], expect_ok=False,
                env_extra={"VCOPS_AGENT_MODE": "1"},
            )
            self.assertEqual(denied["error"]["code"], "not_found")
            operator_view = self.invoke(["memo-show", "--memo-id", str(memo["id"])])
            self.assertEqual(operator_view["content"], memo_markdown)
        finally:
            self.query(
                "UPDATE leads SET confidentiality='internal' WHERE id=%s", (self.lead_id,), owner=True,
            )

        outside = self.operator([
            "source-add", "--kind", "public_web", "--trust-level", "public_web", "--uri",
            f"https://outside-{self.prefix}.invalid", "--provider", "manual",
            "--stable-id", self.prefix + "-outside",
        ])["source"]
        with self.assertRaises(LobsterStepError):
            self.execute("memo-record.lobster", {
                "idempotency_key": self.prefix + "-memo-outside",
                "lead_id": str(self.lead_id),
                "evaluation_id": str(evaluation["id"]),
                "compiled_truth_id": str(snapshot["id"]),
                "memo_title": "G4RI outside memo",
                "memo_markdown": "# Outside\n\n[F-2]",
                "citations_json": json.dumps([{
                    "fact_id": self.cited_fact_id, "source_id": outside["id"],
                    "citation": "[F-2]", "locator": "outside snapshot",
                }]),
                "evidence_hash": snapshot["evidence_packet_hash"],
            })
        memo_path = self.state_root / "memos" / f"{memo['content_sha256']}.md"
        memo_path.chmod(0o600)
        memo_path.write_text("# tampered", encoding="utf-8")
        tampered = self.invoke(
            ["memo-show", "--memo-id", str(memo["id"])], expect_ok=False,
            env_extra={"VCOPS_AGENT_MODE": "1"},
        )
        self.assertEqual(tampered["error"]["code"], "artifact_integrity_conflict")

    def test_08_evidence_without_a_source_is_refused(self):
        refused = self.invoke([
            "evidence-record", "--lead-id", str(self.lead_id),
            "--evidence", json.dumps({
                "claim": f"{self.prefix} sourceless assertion",
                "fact_type": "traction_adoption",
                "confidence": "high",
                "produced_by": "founder-researcher",
            }),
        ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(refused["error"]["code"], "invalid_evidence")
        both = self.invoke([
            "evidence-record", "--lead-id", str(self.lead_id),
            "--evidence", json.dumps({
                "claim": f"{self.prefix} double-sourced assertion",
                "fact_type": "traction_adoption", "confidence": "high", "produced_by": "x",
                "source": {"url": f"https://a-{self.prefix}.invalid/x"},
                "document": {"extraction_id": 1},
            }),
        ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(both["error"]["code"], "invalid_evidence")

    def test_09_concurrent_evidence_writes_dedup_to_one_claim(self):
        import threading

        second_lead = self.operator([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4RI concurrent lead",
            "--origin-group", "outbound", "--idempotency-key", self.prefix + "-lead2",
        ])["lead"]["id"]
        claim = f"{self.prefix} concurrent claim for one company"
        payload = {
            "claim": claim, "fact_type": "market_buyer_timing", "confidence": "high",
            "produced_by": "market-mapper",
        }
        barrier = threading.Barrier(2)
        results = {}

        # One shared host keeps independent_sources=1 so the claim never
        # promotes; the assertion then isolates the dedup race from corroboration.
        def writer(name, lead):
            spec = dict(payload, source={"url": f"https://shared-{self.prefix}.invalid/x"})
            barrier.wait()
            results[name] = self.invoke([
                "evidence-record", "--lead-id", str(lead), "--evidence", json.dumps(spec),
            ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})

        # The dedup race is lead-scoped: two concurrent identical writes for
        # ONE lead must land as one fact (the SELECT-then-INSERT window is
        # closed by the company advisory lock).
        threads = [
            threading.Thread(target=writer, args=("a", self.lead_id)),
            threading.Thread(target=writer, args=("b", self.lead_id)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        fact_ids = {results[name]["fact"]["id"] for name in ("a", "b")}
        self.assertEqual(len(fact_ids), 1, f"concurrent writes split the claim: {fact_ids}")
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM facts WHERE company_id=%s AND definition=%s AND lead_id=%s",
                (self.company_id, claim, self.lead_id),
            ),
            1,
        )
        # A second lead of the same company recording the same claim gets its
        # OWN fact: compiled-truth and the evaluation lineage guard are
        # lead-scoped, so reusing the first lead's fact id would strand the
        # claim outside the second lead's citable ledger (test_16 pins the
        # same boundary for document evidence).
        other = self.invoke([
            "evidence-record", "--lead-id", str(second_lead),
            "--evidence", json.dumps(dict(payload, source={"url": f"https://shared-{self.prefix}.invalid/x"})),
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertFalse(other["reused"], other)
        self.assertNotIn(other["fact"]["id"], fact_ids)
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM facts WHERE company_id=%s AND definition=%s",
                (self.company_id, claim),
            ),
            2,
        )

    def test_10_orchestration_audit_persists_and_reads_back(self):
        for kind, specialist, payload in (
            ("delegation_eval", "founder-researcher", {"question": "founder track record", "budget": 3}),
            ("return_assessment", "founder-researcher", {"accepted": True, "reason": "sourced and grounded"}),
            ("chief_output", "vc-chief", {"recommendation": "research_deeper", "consulted": ["founder-researcher"]}),
        ):
            state = self.execute("orchestration-record.lobster", {
                "idempotency_key": f"{self.prefix}-orch-{kind}",
                "lead_id": str(self.lead_id),
                "record_kind": kind,
                "specialist": specialist,
                "payload_json": json.dumps(payload),
            })
            run_id = state["workflow_start"]["json"]["workflow_run"]["run_id"]
            self.assertEqual(self.query("SELECT status FROM workflow_runs WHERE run_id=%s", (run_id,)), "succeeded")
        shown = self.invoke(
            ["orchestration-show", "--lead-id", str(self.lead_id)], env_extra={"VCOPS_AGENT_MODE": "1"},
        )
        kinds = [r["record_kind"] for r in shown["records"]]
        self.assertEqual(kinds, ["delegation_eval", "return_assessment", "chief_output"])
        self.assertEqual(shown["records"][0]["payload"]["question"], "founder track record")
        self.assertEqual(shown["records"][0]["specialist_agent"], "founder-researcher")
        # Immutable to the runtime: no UPDATE grant (and append-only trigger
        # behind it for the owner lane).
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.query(
                "UPDATE orchestration_audit SET created_by='x' WHERE lead_id=%s", (self.lead_id,),
            )
        with self.assertRaises(psycopg.errors.ObjectNotInPrerequisiteState):
            self.query(
                "UPDATE orchestration_audit SET created_by='x' WHERE lead_id=%s", (self.lead_id,), owner=True,
            )

    def test_11_proposal_capture_persists_and_reads_back(self):
        state = self.execute("proposal-record.lobster", {
            "idempotency_key": self.prefix + "-proposal",
            "proposal_kind": "source_policy",
            "title": "Add TechCrunch RSS to the watchlist",
            "summary": "Recurring high-yield funding signals observed for the thesis.",
            "content_json": json.dumps({"add_sources": ["https://techcrunch.com/feed/"], "cadence": "daily"}),
        })
        run_id = state["workflow_start"]["json"]["workflow_run"]["run_id"]
        self.assertEqual(self.query("SELECT status FROM workflow_runs WHERE run_id=%s", (run_id,)), "succeeded")
        proposal = state["proposal_record"]["json"]["proposal"]
        self.assertEqual(proposal["status"], "submitted")
        listed = self.invoke(
            ["proposal-list", "--kind", "source_policy"], env_extra={"VCOPS_AGENT_MODE": "1"},
        )
        ids = {p["id"] for p in listed["proposals"]}
        self.assertIn(proposal["id"], ids)
        row = next(p for p in listed["proposals"] if p["id"] == proposal["id"])
        self.assertEqual(row["content"]["cadence"], "daily")

        # A lead-scoped proposal inherits its lead's confidentiality: the model
        # lane sees it while the lead is internal, but not once it is confidential,
        # exactly like the other lead-scoped read commands. System-wide proposals
        # (NULL lead_id) carry no boundary and stay visible.
        scoped = self.operator([
            "proposal-record", "--kind", "schema_change",
            "--title", "Lead-scoped schema proposal", "--summary", "confidential lead-specific detail",
            "--content", json.dumps({"detail": "confidential"}), "--lead-id", str(self.lead_id),
        ])["proposal"]

        def agent_schema_ids():
            shown = self.invoke(
                ["proposal-list", "--kind", "schema_change"], env_extra={"VCOPS_AGENT_MODE": "1"},
            )
            return {p["id"] for p in shown["proposals"]}

        self.assertIn(scoped["id"], agent_schema_ids())
        self.query(
            "UPDATE leads SET confidentiality='confidential' WHERE id=%s", (self.lead_id,), owner=True,
        )
        try:
            self.assertNotIn(scoped["id"], agent_schema_ids())
            # the operator lane still sees the confidential lead-scoped proposal
            operator_ids = {p["id"] for p in self.operator(["proposal-list", "--kind", "schema_change"])["proposals"]}
            self.assertIn(scoped["id"], operator_ids)
            # and the system-wide source_policy proposal remains visible to the model lane
            still_ids = {p["id"] for p in self.invoke(
                ["proposal-list", "--kind", "source_policy"], env_extra={"VCOPS_AGENT_MODE": "1"},
            )["proposals"]}
            self.assertIn(proposal["id"], still_ids)
        finally:
            self.query(
                "UPDATE leads SET confidentiality='internal' WHERE id=%s", (self.lead_id,), owner=True,
            )

    def test_07_promotion_policy_is_reviewed_data_the_runtime_cannot_change(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.query("UPDATE fact_promotion_policy SET min_independent_sources = 1 WHERE id = 1")
        self.query("UPDATE fact_promotion_policy SET auto_promote = FALSE WHERE id = 1", owner=True)
        try:
            state = self.execute("evidence-record.lobster", {
                "idempotency_key": self.prefix + "-policy-a",
                "lead_id": str(self.lead_id),
                "evidence_json": self.evidence(
                    f"https://one-{self.prefix}.invalid/a", claim=f"{self.prefix} policy-off claim",
                ),
            })
            fact_id = state["evidence_persist"]["json"]["fact"]["id"]
            state = self.execute("evidence-record.lobster", {
                "idempotency_key": self.prefix + "-policy-b",
                "lead_id": str(self.lead_id),
                "evidence_json": self.evidence(
                    f"https://two-{self.prefix}.invalid/b", claim=f"{self.prefix} policy-off claim",
                ),
            })
            promote = state["fact_promote"]["json"]
            self.assertFalse(promote["promoted"])
            self.assertEqual(promote["reason"], "auto_promote_disabled")
            self.assertEqual(
                self.query("SELECT fact_status FROM facts WHERE id=%s", (fact_id,)), "submitted_claim",
            )
        finally:
            self.query("UPDATE fact_promotion_policy SET auto_promote = TRUE WHERE id = 1", owner=True)

    def test_12_proposal_decisions_are_operator_lane_at_the_database_boundary(self):
        proposal = self.operator([
            "proposal-record", "--kind", "other", "--title", "Update-path proposal",
            "--summary", "exercise the decision guard and the set_updated_at trigger",
            "--content", json.dumps({"k": "v"}),
        ])["proposal"]
        pid = proposal["id"]
        before = self.query("SELECT updated_at FROM proposals WHERE id=%s", (pid,))
        # The runtime holds UPDATE, so submitted -> under_review is allowed and
        # the set_updated_at trigger advances updated_at.
        self.query("UPDATE proposals SET status='under_review' WHERE id=%s", (pid,))
        self.assertEqual(self.query("SELECT status FROM proposals WHERE id=%s", (pid,)), "under_review")
        self.assertGreater(self.query("SELECT updated_at FROM proposals WHERE id=%s", (pid,)), before)
        # The guard trigger rejects a direct decision UPDATE by the runtime role
        # even when reviewer fields are supplied: decisions can only pass
        # through the audited SECURITY DEFINER decide_proposal function.
        with self.assertRaises(psycopg.errors.InvalidAuthorizationSpecification):
            self.query(
                "UPDATE proposals SET status='accepted', reviewed_by='rogue-agent',"
                " reviewed_at=clock_timestamp() WHERE id=%s",
                (pid,),
            )
        # The decision function itself requires a stable reviewer identity.
        with self.assertRaises(psycopg.errors.InvalidParameterValue):
            self.query("SELECT decide_proposal(%s,'accepted','','','vcops')", (pid,))
        # The helper refuses decisions outside the authenticated operator lane.
        denied = self.invoke([
            "proposal-decide", "--proposal-id", str(pid), "--decision", "accept",
            "--reviewer", "g4-operator", "--note", "not an operator runtime",
        ], expect_ok=False)
        self.assertEqual(denied["error"]["code"], "operator_context_required")
        # The operator lane decides through the audited function.
        decided = self.invoke([
            "proposal-decide", "--proposal-id", str(pid), "--decision", "accept",
            "--reviewer", "g4-operator", "--note", "reviewed and accepted",
        ], env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"})["proposal"]
        self.assertEqual(decided["status"], "accepted")
        self.assertEqual(decided["reviewed_by"], "g4-operator")
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM audit_events WHERE event_type='proposal.decided' AND entity_id=%s",
                (str(pid),),
            ),
            1,
        )
        # Decided proposals are immutable to the runtime role and cannot be
        # re-decided.
        with self.assertRaises(psycopg.errors.InvalidAuthorizationSpecification):
            self.query("UPDATE proposals SET summary='tampered' WHERE id=%s", (pid,))
        second = self.invoke([
            "proposal-decide", "--proposal-id", str(pid), "--decision", "reject",
            "--reviewer", "g4-operator", "--note", "second decision must fail",
        ], env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"}, expect_ok=False)
        # decide_proposal raises SQLSTATE 40001 on a re-decision attempt, now
        # surfaced as a typed error instead of an opaque internal_error.
        self.assertEqual(second["error"]["code"], "serialization_conflict")

    def test_14_web_corroboration_is_content_addressed_not_host_based(self):
        # Web independence is keyed by verified content hash, not by the
        # model-chosen host. This proves three properties in sequence on one claim:
        #   1. two DISTINCT hosts with NO content hash do NOT corroborate (the
        #      "two invented URLs auto-promote" gap is closed);
        #   2. a third host repeating an EARLIER content hash still does not
        #      corroborate (identical content collapses to one);
        #   3. a source with a genuinely DISTINCT content hash promotes.
        # The registrable_host helper survives as a reviewed utility even though
        # it no longer gates corroboration.
        self.assertEqual(self.query("SELECT registrable_host('a.b.example.com')"), "example.com")
        self.assertEqual(self.query("SELECT registrable_host('news.acme.co.uk')"), "acme.co.uk")
        claim = f"{self.prefix} churn fell to 1.1 percent in Q2 2026"
        # (1) Two distinct hosts, neither content-addressed: no promotion.
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ca-1",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://ir.pub-{self.prefix}.invalid/metrics", claim=claim),
        })
        claim_fact = state["evidence_persist"]["json"]["fact"]["id"]
        self.assertFalse(state["fact_promote"]["json"]["promoted"])
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ca-2",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://blog.other-{self.prefix}.invalid/churn", claim=claim),
        })
        self.assertEqual(state["evidence_persist"]["json"]["fact"]["id"], claim_fact)
        self.assertFalse(
            state["fact_promote"]["json"]["promoted"],
            "two model-supplied hosts with no verified content must not corroborate",
        )
        # (1b) A case-varied scheme cannot dodge the web classification: the
        # normalization CHECK refuses to store it at all, and the promotion
        # predicate matches the scheme case-insensitively as a second layer.
        with self.assertRaises(psycopg.errors.CheckViolation):
            with psycopg.connect(OWNER_DATABASE_URL) as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sources"
                    " (source_kind, trust_level, confidentiality, canonical_uri,"
                    "  provider, provider_account_id, stable_source_id)"
                    " VALUES ('public_web', 'public_web', 'internal', %s,"
                    "         'web-research', 'default', %s)",
                    (
                        f"HTTPS://upper-{self.prefix}.invalid/metrics",
                        "url:" + self.content_hash("upper-scheme"),
                    ),
                )
        predicate = self.query(
            "SELECT prosrc FROM pg_proc WHERE proname='promote_submitted_claim'", owner=True,
        )
        self.assertIn("~* '^https?://'", predicate)
        # (3-precursor) One content-addressed source (tag C): still one key.
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ca-3",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(
                f"https://registry-{self.prefix}-c.invalid/filing", claim=claim, content_tag="C"),
        })
        self.assertFalse(
            state["fact_promote"]["json"]["promoted"],
            "one content-addressed source is not yet independent corroboration",
        )
        # (2) A fourth host repeating content hash C: identical content collapses.
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ca-4",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(
                f"https://mirror-{self.prefix}-c.invalid/filing", claim=claim, content_tag="C"),
        })
        self.assertFalse(
            state["fact_promote"]["json"]["promoted"],
            "two sources with identical content hash must count as one",
        )
        self.assertEqual(
            self.query("SELECT fact_status FROM facts WHERE id=%s", (claim_fact,)), "submitted_claim",
        )
        # (3) A distinct content hash D: now two independent content keys → promote.
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ca-5",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(
                f"https://registry-{self.prefix}-d.invalid/filing", claim=claim, content_tag="D"),
        })
        promote = state["fact_promote"]["json"]
        self.assertTrue(promote["promoted"], "two distinct verified content hashes must corroborate")
        self.assertEqual(promote["fact"]["supersedes_fact_id"], claim_fact)

    def test_13b_orchestration_record_persists_taskflow_handles(self):
        # The native Task Flow correlation handles are first-class columns and are
        # populated when the chief supplies them, so the audit trail is queryable
        # by flow/task, not only by the opaque payload blob.
        args = {
            "idempotency_key": self.prefix + "-orch-handles",
            "lead_id": str(self.lead_id),
            "record_kind": "delegation_eval",
            "specialist": "founder-researcher",
            "payload_json": json.dumps({"decision_question": "assess founders"}),
            "flow_id": "flow-abc123",
            "flow_revision": "7",
            "task_id": "task-def456",
        }
        state = self.execute("orchestration-record.lobster", args)
        record = state["orchestration_record"]["json"]["orchestration_record"]
        self.assertEqual(record["flow_id"], "flow-abc123")
        self.assertEqual(int(record["flow_revision"]), 7)
        self.assertEqual(record["task_id"], "task-def456")
        row = self.query(
            "SELECT flow_id||'|'||flow_revision::text||'|'||task_id FROM orchestration_audit WHERE id=%s",
            (record["id"],),
        )
        self.assertEqual(row, "flow-abc123|7|task-def456")
        # Omitting the handles still records a valid entry (handles NULL).
        state = self.execute("orchestration-record.lobster", {
            "idempotency_key": self.prefix + "-orch-nohandles",
            "lead_id": str(self.lead_id),
            "record_kind": "return_assessment",
            "specialist": "traction-analyst",
            "payload_json": json.dumps({"disposition": "accept"}),
        })
        bare = state["orchestration_record"]["json"]["orchestration_record"]
        self.assertIsNone(bare["flow_id"])
        self.assertIsNone(bare["task_id"])
        self.assertIsNone(bare["flow_revision"])

    def test_13_orchestration_lineage_rejects_a_cross_lead_run(self):
        # The lineage trigger forbids attaching a run to an audit row for a
        # different lead — cross-lead audit contamination fails closed.
        run_id = self.query(
            "SELECT id FROM workflow_runs WHERE lead_id=%s ORDER BY id LIMIT 1", (self.lead_id,),
        )
        self.assertIsNotNone(run_id, "expected a lead-bound workflow_run from earlier tests")
        other_lead = self.operator([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4RI lineage lead",
            "--origin-group", "outbound", "--idempotency-key", self.prefix + "-lineage-lead",
        ])["lead"]["id"]
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            with self.assertRaises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO orchestration_audit "
                    "(lead_id,workflow_run_id,record_kind,payload,created_by) "
                    "VALUES (%s,%s,'chief_output','{}'::jsonb,'g4-lineage-test')",
                    (other_lead, run_id),
                )

    def test_12b_proposals_cannot_be_born_decided(self):
        # The guard trigger's INSERT branch: the runtime role cannot forge a
        # proposal that is already accepted with a self-supplied reviewer (that
        # would bypass decide_proposal and its audit event entirely).
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            with self.assertRaises(psycopg.errors.InvalidAuthorizationSpecification):
                cur.execute(
                    "INSERT INTO proposals (proposal_kind,title,summary,status,content,"
                    "reviewed_by,reviewed_at,created_by) "
                    "VALUES ('other','forged','born decided','accepted','{}'::jsonb,"
                    "'forged-operator',clock_timestamp(),'g4-forge-test')",
                )
        # Undecided runtime submissions stay allowed.
        self.query(
            "INSERT INTO proposals (proposal_kind,title,summary,content,created_by) "
            "VALUES ('other','undecided','runtime submission','{}'::jsonb,'g4-forge-test')",
        )
        self.assertEqual(self.query(
            "SELECT status FROM proposals WHERE title='undecided' AND created_by='g4-forge-test'",
        ), "submitted")

    def test_15_web_independence_is_content_addressed_not_host_addressed(self):
        # Content-addressing supersedes host-based independence in both
        # directions: identical content presented under disguised (userinfo,
        # trailing dot) or genuinely distinct hosts collapses to ONE independent
        # key, and only a genuinely distinct content hash corroborates. A model
        # can no longer split one piece of content into two "sources" by varying
        # the URL, nor invent two bare URLs.
        claim = f"{self.prefix} net revenue retention hit 130 percent in Q2 2026"
        shared = self.content_hash("nrr-shared")
        host = f"pub-{self.prefix}-ui.invalid"
        state = self.execute("evidence-record.lobster", {
            "idempotency_key": self.prefix + "-ui-1",
            "lead_id": str(self.lead_id),
            "evidence_json": self.evidence(f"https://{host}/a", claim=claim, content_tag="nrr-shared"),
        })
        fact_id = state["evidence_persist"]["json"]["fact"]["id"]
        self.assertFalse(state["fact_promote"]["json"]["promoted"])
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            # Two more sources — a userinfo-disguised same host and a genuinely
            # distinct host — carrying the SAME content hash: identical content
            # collapses to the single key already contributed above.
            for disguised in (f"https://audit@{host}/b", f"https://other-{self.prefix}.invalid/c"):
                cur.execute(
                    "INSERT INTO sources (source_kind,trust_level,confidentiality,canonical_uri,provider,content_sha256) "
                    "VALUES ('public_web','public_web','internal',%s,'web-research',%s) RETURNING id",
                    (disguised, shared),
                )
                source_id = one_row(cur)[0]
                cur.execute(
                    "INSERT INTO fact_sources (fact_id,source_id,evidence_role) "
                    "VALUES (%s,%s,'supporting')",
                    (fact_id, source_id),
                )
            cur.execute("SELECT count(*) FROM promote_submitted_claim(%s)", (fact_id,))
            self.assertEqual(
                one_row(cur)[0], 0,
                "identical content under different hosts must count as one independent key",
            )
            # A genuinely distinct content hash is the second independent key.
            cur.execute(
                "INSERT INTO sources (source_kind,trust_level,confidentiality,canonical_uri,provider,content_sha256) "
                "VALUES ('public_web','public_web','internal',%s,'web-research',%s) RETURNING id",
                (f"https://distinct-{self.prefix}.invalid/d", self.content_hash("nrr-distinct")),
            )
            distinct_source = one_row(cur)[0]
            cur.execute(
                "INSERT INTO fact_sources (fact_id,source_id,evidence_role) VALUES (%s,%s,'supporting')",
                (fact_id, distinct_source),
            )
            cur.execute("SELECT count(*) FROM promote_submitted_claim(%s)", (fact_id,))
            self.assertEqual(
                one_row(cur)[0], 1,
                "a genuinely distinct content hash provides the second independent key",
            )

    def test_16_document_evidence_cannot_cross_leads(self):
        # An artifact bound to lead A must not lend its (elevated) trust
        # boundary to claims about lead B; the bound lead itself may cite it.
        other_lead = self.operator([
            "create-lead", "--company-id", str(self.company_id), "--lead-title", "G4RI doc-bound lead",
            "--origin-group", "outbound", "--idempotency-key", self.prefix + "-doclead",
        ])["lead"]["id"]
        document = self.inbox / f"{self.prefix}-bound.csv"
        document.write_text("metric,value\nburn,123456\n", encoding="utf-8")
        extraction = self.operator([
            "document-extract", "--path", str(document), "--lead-id", str(other_lead),
            "--idempotency-key", self.prefix + "-bound-extract",
            "--trust-level", "allowlisted_operator", "--confidentiality", "internal",
            "--retention-class", "standard",
        ])["extraction"]["id"]
        evidence = {
            "claim": f"{self.prefix} monthly burn is 123456 EUR",
            "fact_type": "traction_adoption", "confidence": "high",
            "produced_by": "document-intake-analyst",
            "document": {"extraction_id": extraction, "cell_range": "B2"},
        }
        refused = self.invoke([
            "evidence-record", "--lead-id", str(self.lead_id),
            "--evidence", json.dumps(evidence),
        ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(refused["error"]["code"], "document_not_associated")
        accepted = self.invoke([
            "evidence-record", "--lead-id", str(other_lead),
            "--evidence", json.dumps(evidence),
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertTrue(accepted["ok"])
        self.assertEqual(accepted["fact"]["fact_status"], "submitted_claim")

    def test_17_fact_pair_commands_honor_the_model_confidentiality_ceiling(self):
        # Facts inherit their lead's confidentiality boundary. The fact-pair
        # and promotion commands return the facts' values, definitions, and
        # periods to the workflow lane, so they must be gated exactly like
        # lead-show and memo-show — otherwise the model reads a restricted
        # lead's evidence by fact id.
        source = self.operator([
            "source-add", "--kind", "public_web", "--trust-level", "public_web", "--uri",
            f"https://ceiling-{self.prefix}.invalid/x", "--provider", "manual",
            "--stable-id", self.prefix + "-ceiling",
        ])["source"]
        common = [
            "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "arr", "--definition", "ceiling probe revenue", "--currency", "EUR",
            "--status", "verified_fact", "--confidence", "0.9", "--source-id", str(source["id"]),
            "--evidence-role", "primary",
        ]
        early = self.operator([
            "fact-add", *common, "--value", "100k",
            "--period-start", "2025-01-01", "--period-end", "2025-06-30",
        ])["fact"]
        late = self.operator([
            "fact-add", *common, "--value", "200k",
            "--period-start", "2025-07-01", "--period-end", "2025-12-31",
        ])["fact"]
        self.query(
            "UPDATE leads SET confidentiality='restricted' WHERE id=%s", (self.lead_id,), owner=True,
        )
        try:
            for command in ("trajectory-check", "contradiction-check"):
                denied = self.invoke([
                    command, "--left-fact-id", str(early["id"]), "--right-fact-id", str(late["id"]),
                ], expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"})
                self.assertEqual(denied["error"]["code"], "not_found", command)
            denied = self.invoke(
                ["fact-promote", "--fact-id", str(early["id"])],
                expect_ok=False, env_extra={"VCOPS_WORKFLOW_MODE": "1"},
            )
            self.assertEqual(denied["error"]["code"], "not_found")
            # The operator lane is unrestricted, so the gate is a lane cap and
            # not an outage.
            operator_view = self.operator([
                "trajectory-check", "--left-fact-id", str(early["id"]),
                "--right-fact-id", str(late["id"]),
            ])
            self.assertEqual(operator_view["classification"], "trajectory")
        finally:
            self.query(
                "UPDATE leads SET confidentiality='internal' WHERE id=%s", (self.lead_id,), owner=True,
            )
        # Back at the ceiling the same pair is readable by the model lane.
        allowed = self.invoke([
            "trajectory-check", "--left-fact-id", str(early["id"]), "--right-fact-id", str(late["id"]),
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        self.assertEqual(allowed["classification"], "trajectory")


if __name__ == "__main__":
    unittest.main(verbosity=2)
