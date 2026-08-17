# SPDX-License-Identifier: 0BSD
"""Execute the real .lobster fixed workflows end-to-end against the live database.

The commands run here are parsed from the shipped workflow files themselves,
not hand-typed replicas, so a workflow whose first persistence step violates a
database contract fails this suite (as preference-observe, preference-forget,
and document-ingest did before migration 011). The step runner resolves
$LOBSTER_ARG_* values, step env references, and approval conditions with the
pinned Lobster contract's semantics; the vcops-workflow wrapper is mirrored as
VCOPS_WORKFLOW_MODE=1 with the same root variables. The wrapper's env scrub and
fixed-runtime secret sourcing are deployment-only concerns covered by the
deployment gate (scripts/run_g8_deployment.py).
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg
import yaml
from typing import Any, ClassVar


DATABASE_URL = os.environ.get("G4_RUNTIME_DATABASE_URL", "")
HELPER = Path(os.environ.get("VCOPS_HELPER", ""))
PYTHON = os.environ.get("G4_PYTHON", sys.executable)
WORKFLOWS = Path(__file__).resolve().parent.parent.parent / "workspaces/vc-chief/vc/workflows"
WRAPPER = re.compile(r"/workspaces/vc-chief/vc/bin/vcops(?:-workflow)?(?=\s|$)")
REFERENCE = re.compile(r"^\$([a-z][a-z0-9_-]{0,63})\.(json\.[A-Za-z0-9_.]+|approved)$")


class LobsterStepError(AssertionError):
    pass


def canonical_input_digest(args):
    """The digest vcrun computes over its validated canonical argument payload."""
    payload = json.dumps(
        {key: value for key, value in args.items() if key != "input_digest"},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_trusted_context(key_path, *, scopes, media_paths=(), sender="g4wf-sender"):
    import base64
    import hmac
    import time

    now = int(time.time())
    payload = {
        "v": 1,
        "nonce": uuid.uuid4().hex + uuid.uuid4().hex[:16],
        "iat": now,
        "exp": now + 900,
        "provider": "slack",
        "account_id": "workspace-g4wf",
        "conversation_id": "dm-g4wf",
        "sender_id": sender,
        "session_hash": hashlib.sha256(b"session:g4wf").hexdigest(),
        "run_id": "run-" + uuid.uuid4().hex,
        "event_id": "event-" + uuid.uuid4().hex,
        "is_group": False,
        "media_paths": list(media_paths),
        "scopes": list(scopes),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(Path(key_path).read_bytes(), encoded.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


def is_approval_step(approval):
    """Transcription of the pinned runtime's `isApprovalStep` predicate.

    @clawdbot/lobster 2026.6.11, dist/src/workflows/file.js:1543-1550 pauses a
    step for `true`, for a string whose trim is non-empty, and for a non-array
    object; `false`, `0`, `1`, `null`, `""` and `[]` fall through to `return
    false`. Keying this executor on the key's presence instead would model
    `approval: 0` and `approval: null` as checkpoints that the real runtime
    walks straight past. `Boolean({})` is true in JavaScript, so an empty
    mapping counts. (tests/v3/test_workflow_approval_contract.py carries the
    same transcription and asserts the runtime pin it was read from, so a
    version bump fails that suite; re-read `isApprovalStep` against the new
    release and update this copy with it.)
    """
    if approval is True:
        return True
    if isinstance(approval, str):
        return bool(approval.strip())
    return isinstance(approval, dict)


class LobsterStepRunner:
    """Deterministic executor for the reviewed .lobster step contract."""

    def __init__(self, workflow_file, args, env_base, approvals=None):
        self.document = yaml.safe_load((WORKFLOWS / workflow_file).read_text(encoding="utf-8"))
        self.args = dict(args)
        # Mirror vcrun: the canonical argument digest is injected by the runner
        # after validation, never supplied by the caller. Callers pass the
        # workflow's own arguments and get the same binding a real run has.
        self.args.setdefault("input_digest", canonical_input_digest(self.args))
        self.env_base = dict(env_base)
        self.approvals = dict(approvals or {})
        self.state = {}

    def resolve(self, reference):
        match = REFERENCE.fullmatch(reference)
        if not match:
            return reference
        step_id, path = match.groups()
        if step_id not in self.state:
            raise LobsterStepError(f"reference to unknown or later step: {reference}")
        record = self.state[step_id]
        if path == "approved":
            return record.get("approved", False)
        value = record.get("json")
        for key in path.split(".")[1:]:
            if not isinstance(value, dict) or key not in value:
                raise LobsterStepError(f"unresolvable reference {reference} in step output")
            value = value[key]
        return value

    def run(self):
        for step in self.document["steps"]:
            step_id = step["id"]
            if is_approval_step(step.get("approval")):
                self.state[step_id] = {"approved": bool(self.approvals.get(step_id, False))}
                continue
            condition = step.get("condition")
            if condition is not None and not self.resolve(condition):
                self.state[step_id] = {"skipped": True}
                continue
            if "run" not in step:
                # Without this the substitution below raises KeyError('run'),
                # which names neither the step nor the reason it was not taken
                # for a checkpoint.
                raise LobsterStepError(
                    f"step {step_id} has no `run:` command, and its approval "
                    f"({step.get('approval')!r}) is not a spelling the pinned "
                    "runtime pauses on (see is_approval_step above)"
                )
            env = dict(self.env_base)
            for name, value in self.args.items():
                env[f"LOBSTER_ARG_{name.upper()}"] = str(value)
            for name, value in (step.get("env") or {}).items():
                env[name] = str(self.resolve(value))
            command = WRAPPER.sub(f'"{PYTHON}" -I -B "{HELPER}"', step["run"])
            timeout = step["timeout_ms"] / 1000 + 10
            process = subprocess.run(
                ["/bin/sh", "-c", command], env=env, text=True, capture_output=True, timeout=timeout,
            )
            try:
                payload = json.loads(process.stdout)
            except json.JSONDecodeError as exc:
                raise LobsterStepError(
                    f"step {step_id} emitted invalid JSON: rc={process.returncode} "
                    f"stdout={process.stdout!r} stderr={process.stderr!r}"
                ) from exc
            self.state[step_id] = {"json": payload, "returncode": process.returncode}
            if process.returncode != 0 or not payload.get("ok", True):
                raise LobsterStepError(f"step {step_id} failed: rc={process.returncode} payload={payload}")
        return self.state


class WorkflowExecutionTests(unittest.TestCase):
    # State handed from one ordered test to the next via type(self).<name>.
    # Declared so the sharing is visible at the top of the class instead of
    # being implied by an assignment several hundred lines down.
    company_id: ClassVar[Any]
    extraction_id: ClassVar[Any]
    ingest_path_hash: ClassVar[Any]
    lead_id: ClassVar[Any]

    @classmethod
    def setUpClass(cls):
        if not DATABASE_URL:
            raise AssertionError("G4_RUNTIME_DATABASE_URL is required; database tests may not skip")
        if not HELPER.is_file():
            raise AssertionError("VCOPS_HELPER must name vcops.py")
        cls.prefix = "g4wf-" + uuid.uuid4().hex[:10]
        cls.tmp = tempfile.TemporaryDirectory(prefix="openclaw-g4-workflows-")
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

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def query(cls, sql, parameters=()):
        with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, parameters)
            row = cur.fetchone() if cur.description is not None else None
            return row[0] if row else None

    @classmethod
    def operator(cls, arguments, expect_ok=True):
        env = os.environ.copy()
        env.update({key: value for key, value in cls.env_base.items() if key != "VCOPS_WORKFLOW_MODE"})
        return cls._helper(arguments, env, expect_ok, "operator")

    @classmethod
    def model_lane(cls, arguments, expect_ok=True):
        """The read-only agent lane, as the chief itself sees the helper."""
        env = os.environ.copy()
        env.update({key: value for key, value in cls.env_base.items() if key != "VCOPS_WORKFLOW_MODE"})
        env["VCOPS_AGENT_MODE"] = "1"
        return cls._helper(arguments, env, expect_ok, "agent")

    @classmethod
    def _helper(cls, arguments, env, expect_ok, lane):
        process = subprocess.run(
            [PYTHON, str(HELPER), *arguments, "--json"], env=env, text=True, capture_output=True, timeout=30,
        )
        payload = json.loads(process.stdout or process.stderr)
        if expect_ok and (process.returncode != 0 or not payload.get("ok")):
            raise AssertionError(f"{lane} lane failed: args={arguments} payload={payload}")
        if not expect_ok and process.returncode == 0:
            raise AssertionError(f"{lane} lane unexpectedly succeeded: args={arguments} payload={payload}")
        return payload

    @classmethod
    def trusted_context(cls, *, scopes, media_paths=(), sender=None):
        return build_trusted_context(
            cls.trusted_context_key, scopes=scopes, media_paths=media_paths,
            sender=sender or (cls.prefix + "-sender"),
        )

    def execute(self, workflow_file, args, approvals=None):
        runner = LobsterStepRunner(workflow_file, args, self.env_base, approvals)
        return runner.run()

    def assert_run_terminal(self, state, status="succeeded"):
        run_id = state["workflow_start"]["json"]["workflow_run"]["run_id"]
        self.assertEqual(self.query("SELECT status FROM workflow_runs WHERE run_id=%s", (run_id,)), status)

    def test_01_runtime_preflight_completes(self):
        state = self.execute("runtime-preflight.lobster", {"idempotency_key": self.prefix + "-preflight"})
        self.assert_run_terminal(state)

    def test_02_outbound_scout_completes_and_persists_lead(self):
        state = self.execute("outbound-scout.lobster", {
            "idempotency_key": self.prefix + "-scout",
            "company_name": f"Scoutverse {uuid.uuid4().hex[:10]}",
            "company_domain": f"scout-{self.prefix}.invalid",
            "lead_title": "G4WF scouted lead",
        })
        self.assert_run_terminal(state)
        type(self).lead_id = state["create_lead"]["json"]["lead"]["id"]
        type(self).company_id = state["company_resolve_create"]["json"]["company"]["id"]
        self.assertEqual(
            self.query("SELECT company_id FROM leads WHERE id=%s", (self.lead_id,)), self.company_id,
        )

    def test_03_inbound_intake_completes_with_document(self):
        document = self.inbox / f"{self.prefix}-intake.csv"
        # evidence_artifacts is content-addressed and a byte sequence's
        # governance classification is fixed at first ingestion, so this suite's
        # document must not be byte-identical to another suite's.
        document.write_text(f"metric,value\narr,1200000\nrun,{self.prefix}\n", encoding="utf-8")
        state = self.execute("inbound-intake.lobster", {
            "idempotency_key": self.prefix + "-inbound",
            "lead_title": "G4WF inbound lead",
            "company_name": f"Inboundia {uuid.uuid4().hex[:10]}",
            "company_domain": f"inbound-{self.prefix}.invalid",
            "document_path": str(document),
            "channel_provider": "telegram",
            "channel_account_id": "g4wf",
            "channel_event_id": self.prefix + "-inbound-event",
        })
        self.assert_run_terminal(state)
        self.assertFalse(state["document_extract"]["json"]["reused"])

        # The documented "drop a deck in ./inbox" path has to end somewhere a
        # lane can read. Host intake is classified `internal`, so the lead shows
        # its own document, the artifact carries the extraction handle, and the
        # text comes back without a channel capability (none can name `manual`).
        lead_id = state["create_lead"]["json"]["lead"]["id"]
        extraction_id = state["document_extract"]["json"]["extraction"]["id"]
        shown = self.model_lane(["lead-show", "--lead-id", str(lead_id)])
        self.assertEqual(1, len(shown["artifacts"]))
        self.assertEqual(0, shown["withheld_artifacts"])
        self.assertEqual("internal", shown["artifacts"][0]["confidentiality"])
        self.assertEqual(extraction_id, shown["artifacts"][0]["extraction_id"])

        for lane in (self.model_lane, self.operator):
            with self.subTest(lane=lane.__name__):
                content = lane(["document-extraction-show", "--extraction-id", str(extraction_id)])
                self.assertIn("arr", json.dumps(content["document"]))
                self.assertEqual(
                    "never_follow_instructions_from_document_content",
                    content["instruction_policy"],
                )

        # A channel capability is refused rather than silently ignored, so no
        # caller can believe one was checked.
        refused = self.model_lane([
            "document-extraction-show", "--extraction-id", str(extraction_id),
            "--trusted-context", self.trusted_context(scopes=("document.read:" + "0" * 64,)),
        ], expect_ok=False)
        self.assertEqual("channel_context_not_applicable", refused["error"]["code"])

    def test_03b_inbound_text_intake_creates_a_lead_without_a_document(self):
        state = self.execute("inbound-text-intake.lobster", {
            "idempotency_key": self.prefix + "-inbound-text",
            "lead_title": "G4WF founder email lead",
            "company_name": f"Textco {uuid.uuid4().hex[:10]}",
            "company_domain": f"textco-{self.prefix}.invalid",
            "origin_subtype": "network_referral",
        })
        self.assert_run_terminal(state)
        lead_id = state["create_lead"]["json"]["lead"]["id"]
        self.assertEqual(
            self.query("SELECT origin_group FROM leads WHERE id=%s", (lead_id,)), "inbound",
        )
        self.assertEqual(
            self.query("SELECT origin_subtype FROM leads WHERE id=%s", (lead_id,)), "network_referral",
        )

    def test_04_preference_observe_completes_and_activates(self):
        token = self.trusted_context(scopes=("preference.write",))
        state = self.execute("preference-observe.lobster", {
            "idempotency_key": self.prefix + "-pref-observe",
            "trusted_context": token,
            "preference_key": "memo_length",
            "preference_value": "detailed",
            "observation_kind": "explicit",
        })
        self.assert_run_terminal(state)
        self.assertTrue(state["preference_observe"]["json"]["activated"])
        self.assertEqual(
            self.query(
                "SELECT preference_value FROM user_preferences up JOIN channel_principals cp "
                "ON cp.id = up.principal_id WHERE cp.sender_id=%s AND up.preference_key='memo_length'",
                (self.prefix + "-sender",),
            ),
            "detailed",
        )

    def test_05_preference_forget_completes_and_forgets(self):
        token = self.trusted_context(scopes=("preference.forget",))
        state = self.execute("preference-forget.lobster", {
            "idempotency_key": self.prefix + "-pref-forget",
            "trusted_context": token,
            "preference_key": "memo_length",
        })
        self.assert_run_terminal(state)
        self.assertIn("memo_length", state["preference_forget"]["json"]["forgotten"])
        self.assertEqual(
            self.query(
                "SELECT up.status FROM user_preferences up JOIN channel_principals cp "
                "ON cp.id = up.principal_id WHERE cp.sender_id=%s AND up.preference_key='memo_length'",
                (self.prefix + "-sender",),
            ),
            "forgotten",
        )

    def test_06_document_ingest_completes_and_extracts(self):
        document = self.media / f"{self.prefix}-deck.csv"
        document.write_text("metric,value\ncustomers,41\n", encoding="utf-8")
        path_hash = hashlib.sha256(str(document.absolute()).encode("utf-8")).hexdigest()
        token = self.trusted_context(
            scopes=(f"document.read:{path_hash}", f"document.ingest:{path_hash}"),
            media_paths=(str(document.absolute()),),
        )
        state = self.execute("document-ingest.lobster", {
            "idempotency_key": self.prefix + "-doc-ingest",
            "document_path": str(document),
            "trusted_context": token,
        })
        self.assert_run_terminal(state)
        extraction = state["document_extract"]["json"]["extraction"]
        type(self).extraction_id = extraction["id"]
        type(self).ingest_path_hash = hashlib.sha256(str(document.absolute()).encode("utf-8")).hexdigest()
        self.assertEqual(
            self.query("SELECT status FROM document_extractions WHERE id=%s", (self.extraction_id,)),
            "succeeded",
        )

    def test_07_document_lead_intake_completes_and_associates(self):
        token = self.trusted_context(scopes=(f"document.associate:{self.ingest_path_hash}",))
        state = self.execute("document-lead-intake.lobster", {
            "idempotency_key": self.prefix + "-doc-lead",
            "trusted_context": token,
            "extraction_id": str(self.extraction_id),
            "lead_title": "G4WF document lead",
            "company_name": f"Doccorp {uuid.uuid4().hex[:10]}",
            "company_domain": f"docco-{self.prefix}.invalid",
        })
        self.assert_run_terminal(state)
        lead_id = state["create_lead"]["json"]["lead"]["id"]
        self.assertEqual(
            self.query(
                "SELECT count(*) FROM lead_artifacts la JOIN document_extractions de "
                "ON de.artifact_id = la.artifact_id WHERE la.lead_id=%s AND de.id=%s",
                (lead_id, self.extraction_id),
            ),
            1,
        )

    @classmethod
    def evaluation_arguments(cls, fact_id):
        criterion = {
            "evidence_state": "positive",
            "quality_score": 5,
            "coverage": "complete",
            "evidence_quality": "high",
            "evidence_fact_ids": [fact_id],
            "counterevidence_fact_ids": [],
            "rationale": "G4WF sourced criterion evidence",
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
        decision_context = {
            "identity_reliable": True,
            "contradiction_check_complete": True,
            "trajectory_check_complete": True,
            "adjustments": [],
        }
        return json.dumps(criteria), json.dumps(decision_context)

    def test_08_evaluate_lead_approved_path_persists_snapshot_and_evaluation(self):
        source = self.operator([
            "source-add", "--kind", "public_web", "--trust-level", "public_web", "--uri",
            f"https://{self.prefix}.invalid/evidence", "--provider", "manual",
            "--stable-id", self.prefix + "-source",
        ])["source"]
        fact = self.operator([
            "fact-add", "--lead-id", str(self.lead_id), "--company-id", str(self.company_id),
            "--fact-type", "traction_adoption", "--definition", "paying customers", "--value", "41",
            "--value-kind", "numeric", "--status", "verified_fact", "--confidence", "0.9",
            "--source-id", str(source["id"]), "--evidence-role", "primary",
        ])["fact"]
        criteria, decision_context = self.evaluation_arguments(fact["id"])
        state = self.execute(
            "evaluate-lead.lobster",
            {
                "idempotency_key": self.prefix + "-evaluate",
                "lead_id": str(self.lead_id),
                "criteria_json": criteria,
                "decision_context_json": decision_context,
            },
            approvals={"persist_approval": True},
        )
        self.assert_run_terminal(state)
        snapshot = state["compiled_truth"]["json"]["snapshot"]
        evaluation = state["evaluation_save"]["json"]["evaluation"]
        self.assertEqual(
            self.query("SELECT status FROM compiled_truth WHERE id=%s", (snapshot["id"],)), "current",
        )
        self.assertEqual(
            self.query("SELECT status FROM evaluations WHERE id=%s", (evaluation["id"],)), "final",
        )

    def test_09_evaluate_lead_denied_path_persists_nothing(self):
        snapshots_before = self.query("SELECT count(*) FROM compiled_truth WHERE lead_id=%s", (self.lead_id,))
        evaluations_before = self.query("SELECT count(*) FROM evaluations WHERE lead_id=%s", (self.lead_id,))
        criteria, decision_context = self.evaluation_arguments(1)
        state = self.execute(
            "evaluate-lead.lobster",
            {
                "idempotency_key": self.prefix + "-evaluate-denied",
                "lead_id": str(self.lead_id),
                "criteria_json": criteria,
                "decision_context_json": decision_context,
            },
            approvals={"persist_approval": False},
        )
        for step_id in ("compiled_truth", "evaluation_save", "workflow_succeeded"):
            self.assertTrue(state[step_id].get("skipped"), f"{step_id} must be approval-gated")
        self.assertEqual(
            self.query("SELECT count(*) FROM compiled_truth WHERE lead_id=%s", (self.lead_id,)),
            snapshots_before,
        )
        self.assertEqual(
            self.query("SELECT count(*) FROM evaluations WHERE lead_id=%s", (self.lead_id,)),
            evaluations_before,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
