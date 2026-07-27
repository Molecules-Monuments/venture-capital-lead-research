from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[2]
VCRUN_PATH = PACKAGE / "workspaces/vc-chief/vc/bin/vcrun.py"
SPEC = importlib.util.spec_from_file_location("vcrun_tests", VCRUN_PATH)
assert SPEC is not None and SPEC.loader is not None
vcrun = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vcrun)

VCRUN_CONTROL_PATH = PACKAGE / "workspaces/vc-chief/vc/bin/vcrun_control.py"
CONTROL_SPEC = importlib.util.spec_from_file_location("vcrun_control_tests", VCRUN_CONTROL_PATH)
assert CONTROL_SPEC is not None and CONTROL_SPEC.loader is not None
vcrun_control = importlib.util.module_from_spec(CONTROL_SPEC)
CONTROL_SPEC.loader.exec_module(vcrun_control)


class FixedRunnerTests(unittest.TestCase):
    def test_installed_lobster_contract_matches_derived_image(self) -> None:
        self.assertEqual(
            Path("/opt/openclaw-runtime/node_modules/@clawdbot/lobster/bin/lobster.js"),
            vcrun.EXPECTED_LOBSTER_TARGET,
        )
        self.assertEqual(
            Path("/opt/openclaw-runtime/node_modules/@clawdbot/lobster/package.json"),
            vcrun.LOBSTER_PACKAGE_JSON,
        )
        dockerfile = (PACKAGE / "Dockerfile.openclaw").read_text(
            encoding="utf-8"
        )
        self.assertIn(str(vcrun.EXPECTED_LOBSTER_TARGET), dockerfile)

    def test_exact_runtime_preflight_contract_is_accepted(self) -> None:
        rendered = vcrun.validate_workflow_args(
            "runtime-preflight", json.dumps({"idempotency_key": "g5-runtime-fixture"})
        )
        self.assertEqual({"idempotency_key": "g5-runtime-fixture"}, json.loads(rendered))

    def test_unknown_missing_extra_and_nonobject_inputs_fail(self) -> None:
        bad_values = (
            "[]",
            "{}",
            json.dumps({"idempotency_key": "g5", "extra": "forbidden"}),
            '{"idempotency_key":"g5-a","idempotency_key":"g5-b"}',
            "{not-json}",
        )
        for raw in bad_values:
            with self.subTest(raw=raw[:40]):
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args("runtime-preflight", raw)

    def test_size_nul_path_domain_and_nested_json_bounds_fail_closed(self) -> None:
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "runtime-preflight", json.dumps({"idempotency_key": "x" * (33 * 1024)})
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "inbound-intake",
                json.dumps({"idempotency_key": "g5", "lead_title": "bad\u0000title", "company_name": "x", "company_domain": "x.invalid", "document_path": "/inbox/a.csv", "channel_provider": "manual", "channel_account_id": "default", "channel_event_id": "event"}),
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "inbound-intake",
                json.dumps({"idempotency_key": "g5", "lead_title": "lead", "company_name": "x", "company_domain": "x.invalid", "document_path": "/tmp/a.csv", "channel_provider": "manual", "channel_account_id": "default", "channel_event_id": "event"}),
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "outbound-scout",
                json.dumps({"idempotency_key": "g5", "company_name": "x", "company_domain": "https://bad", "lead_title": "x"}),
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "evaluate-lead",
                json.dumps({"idempotency_key": "g5", "lead_id": "00000000-0000-0000-0000-000000000000", "criteria_json": "[]", "decision_context_json": "{}"}),
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "evaluate-lead",
                json.dumps({"idempotency_key": "g5", "lead_id": "1", "criteria_json": '{"x":1,"x":2}', "decision_context_json": "{}"}),
            )

    def test_evaluate_lead_uses_canonical_postgres_bigint(self) -> None:
        payload = {"idempotency_key": "g5-evaluate", "lead_id": "1", "criteria_json": "{}", "decision_context_json": "{}"}
        self.assertEqual(payload, json.loads(vcrun.validate_workflow_args("evaluate-lead", json.dumps(payload))))
        for value in ("0", "01", "-1", "+1", "1.0", "9223372036854775808", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(value=value), self.assertRaises(vcrun.VCRunError):
                vcrun.validate_workflow_args("evaluate-lead", json.dumps({**payload, "lead_id": value}))

    def test_channel_document_and_preference_workflow_contracts_are_bounded(self) -> None:
        document = {
            "idempotency_key": "channel-doc-1",
            "document_path": "/home/node/.openclaw/media/inbound/deck.pptx",
            "trusted_context": "opaque.signed-capability",
        }
        self.assertEqual(
            document,
            json.loads(vcrun.validate_workflow_args("document-ingest", json.dumps(document))),
        )
        lead = {
            "idempotency_key": "channel-lead-1",
            "trusted_context": "opaque.signed-capability",
            "extraction_id": "1",
            "lead_title": "Inbound deck",
            "company_name": "Acme",
            "company_domain": "Acme.Example",
        }
        normalized = json.loads(
            vcrun.validate_workflow_args("document-lead-intake", json.dumps(lead))
        )
        self.assertEqual("acme.example", normalized["company_domain"])
        preference = {
            "idempotency_key": "preference-1",
            "trusted_context": "opaque.signed-capability",
            "preference_key": "memo_length",
            "preference_value": "detailed",
            "observation_kind": "explicit",
        }
        self.assertEqual(
            preference,
            json.loads(vcrun.validate_workflow_args("preference-observe", json.dumps(preference))),
        )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "document-ingest",
                json.dumps({**document, "document_path": "/home/node/.openclaw/media/inbound/nested/deck.pptx"}),
            )
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "preference-observe",
                json.dumps({**preference, "preference_key": "investment_decisions"}),
            )

    def test_parser_rejects_file_pipeline_cwd_env_and_output_overrides(self) -> None:
        parser = vcrun._build_parser()
        probes = (
            ["run", "unknown", "--args-json", "{}"],
            ["run", "runtime-preflight", "--file", "/tmp/x", "--args-json", "{}"],
            ["run", "runtime-preflight", "--cwd", "/tmp", "--args-json", "{}"],
            ["run", "runtime-preflight", "--env", "X=Y", "--args-json", "{}"],
            ["run", "runtime-preflight", "--max-stdout-bytes", "999999", "--args-json", "{}"],
        )
        for argv in probes:
            with self.subTest(argv=argv):
                # The parser raises the structured usage error (not SystemExit)
                # so main() can honor the one-JSON-object error contract.
                with self.assertRaises(vcrun._UsageError):
                    parser.parse_args(argv)

    def test_usage_errors_emit_exactly_one_json_object(self) -> None:
        import contextlib
        import io

        for argv in ([], ["bogus"], ["run"], ["run", "nope", "--args-json", "{}"]):
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                stdout = io.StringIO()
                with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
                    rc = vcrun.main(argv)
                self.assertEqual(rc, 2)
                self.assertEqual(stdout.getvalue(), "")
                payload = json.loads(stderr.getvalue())
                self.assertEqual(payload["error"]["code"], "usage_error")

    def test_source_scan_limit_matches_the_helper_bound(self) -> None:
        args = {"idempotency_key": "g5-limit-check", "limit": "600"}
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args("source-scan", json.dumps(args))
        args["limit"] = "500"
        vcrun.validate_workflow_args("source-scan", json.dumps(args))

    def test_tool_envelope_extraction_and_recursive_redaction(self) -> None:
        rendered = "[DRY RUN] plan\n" + json.dumps(
            {
                "ok": True,
                "requiresApproval": {
                    "approvalId": "deadbeef",
                    "resumeToken": "bearer-must-not-leak",
                    "nested": {"api_key": "secret", "safe": "retained"},
                },
            }
        )
        parsed = vcrun._last_json_object(rendered)
        self.assertIsNotNone(parsed)
        redacted = vcrun._redact_output(parsed)
        approval = redacted["requiresApproval"]
        self.assertEqual("deadbeef", approval["approvalId"])
        self.assertEqual("[REDACTED]", approval["resumeToken"])
        self.assertEqual("[REDACTED]", approval["nested"]["api_key"])
        self.assertEqual("retained", approval["nested"]["safe"])

    def test_exact_plain_upstream_version_becomes_one_json_runner_envelope(self) -> None:
        payload, lobster = vcrun._normalize_lobster_output(
            0,
            "2026.6.11\n",
            runner_metadata={
                "vcrun_version": "3.0.0",
                "required_lobster_version": "2026.6.11",
            },
            expected_plain_version="2026.6.11",
        )
        self.assertEqual(
            {
                "ok": True,
                "runner": "vcrun",
                "exit_code": 0,
                "lobster": {"ok": True, "version": "2026.6.11"},
                "vcrun_version": "3.0.0",
                "required_lobster_version": "2026.6.11",
            },
            payload,
        )
        self.assertEqual({"ok": True, "version": "2026.6.11"}, lobster)

        for rendered in ("2026.6.11", "2026.6.12\n", "prefix\n2026.6.11\n", "{}\n"):
            with self.subTest(rendered=rendered):
                rejected, parsed = vcrun._normalize_lobster_output(
                    0,
                    rendered,
                    expected_plain_version="2026.6.11",
                )
                self.assertIs(False, rejected["ok"])
                self.assertEqual("invalid_lobster_version", rejected["error"]["code"])
                self.assertIsNone(parsed)

    def test_failed_run_reconciliation_accepts_only_explicit_safe_outcomes(self) -> None:
        for outcome, workflow_run in (
            ("not_started", None),
            ("already_failed", {"status": "failed", "record_version": 3}),
            ("transitioned_failed", {"status": "failed", "record_version": 3}),
        ):
            result = {
                "ok": True,
                "workflow_failure_reconciliation": {
                    "outcome": outcome,
                    "workflow_run": workflow_run,
                    "workflow": "system.runtime-preflight",
                    "idempotency_key": "g5-failure",
                },
            }
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(result), stderr=""
            )
            with self.subTest(outcome=outcome), patch.object(
                vcrun.subprocess, "run", return_value=completed
            ) as run:
                self.assertEqual(
                    result,
                    vcrun._reconcile_workflow_failure(
                        workflow="runtime-preflight",
                        idempotency_key="g5-failure",
                        reason="lobster_step_failure",
                    ),
                )
                command = run.call_args.args[0]
                self.assertEqual("system.runtime-preflight", command[command.index("--workflow") + 1])

        unsafe = {
            "ok": True,
            "workflow_failure_reconciliation": {
                "outcome": "already_failed",
                "workflow_run": {"status": "succeeded"},
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(unsafe), stderr=""
        )
        with patch.object(vcrun.subprocess, "run", return_value=completed):
            with self.assertRaises(vcrun.VCRunError):
                vcrun._reconcile_workflow_failure(
                    workflow="runtime-preflight",
                    idempotency_key="g5-failure",
                    reason="lobster_step_failure",
                )

    def test_failure_cleanup_is_attached_and_cleanup_failure_is_never_hidden(self) -> None:
        reconciliation = {
            "ok": True,
            "workflow_failure_reconciliation": {
                "outcome": "transitioned_failed",
                "workflow_run": {"status": "failed"},
            },
        }
        payload = {"ok": False, "error": {"code": "lobster_timeout"}}
        vcrun._attach_failure_reconciliation(
            payload,
            failure_hook=lambda reason: reconciliation,
            reason="lobster_timeout",
        )
        self.assertEqual(reconciliation, payload["postgres_reconciliation"])

        with self.assertRaisesRegex(vcrun.VCRunError, "reconciliation also failed"):
            vcrun._attach_failure_reconciliation(
                {"ok": False},
                failure_hook=lambda reason: (_ for _ in ()).throw(
                    vcrun.VCRunError("revision conflict")
                ),
                reason="lobster_step_failure",
            )


class OperatorControlTests(unittest.TestCase):
    def _helper_result(self, status: str, *, already_terminal: bool = False) -> dict[str, object]:
        return {
            "ok": True,
            "workflow_run": {"run_id": "run-1", "record_version": 4, "status": status},
            "already_terminal": already_terminal,
        }

    def test_postgres_reconciliation_requires_explicit_cancelled_status(self) -> None:
        accepted = self._helper_result("cancelled", already_terminal=True)
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(accepted), stderr=""
        )
        with patch.object(vcrun_control.subprocess, "run", return_value=completed):
            self.assertEqual(
                accepted,
                vcrun_control._reconcile_postgres_cancellation(
                    run_id="run-1", expected_revision=4, operator_id="operator@example"
                ),
            )

        for terminal_status in ("succeeded", "failed", "lost"):
            with self.subTest(status=terminal_status):
                rejected = subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(self._helper_result(terminal_status, already_terminal=True)),
                    stderr="",
                )
                with patch.object(vcrun_control.subprocess, "run", return_value=rejected):
                    with self.assertRaises(vcrun_control._IMPL.VCRunError):
                        vcrun_control._reconcile_postgres_cancellation(
                            run_id="run-1",
                            expected_revision=4,
                            operator_id="operator@example",
                        )

    def test_rejection_reconciles_postgres_before_destructive_lobster_resume(self) -> None:
        events: list[str] = []
        reconciliation = self._helper_result("cancelled")
        execute_kwargs: dict[str, object] = {}

        def reconcile(**_kwargs: object) -> dict[str, object]:
            events.append("postgres")
            return reconciliation

        def execute(*_args: object, **kwargs: object) -> int:
            events.append("lobster")
            execute_kwargs.update(kwargs)
            return 0

        argv = [
            "vcrun-control",
            "resume",
            "--id",
            "deadbeef",
            "--cancel",
            "--run-id",
            "run-1",
            "--expected-revision",
            "2",
        ]
        with (
            patch.dict(os.environ, {"VCOPS_OPERATOR_ID": "operator@example"}, clear=True),
            patch.object(sys, "argv", argv),
            patch.object(vcrun_control, "_reconcile_postgres_cancellation", side_effect=reconcile),
            patch.object(vcrun_control._IMPL, "_execute", side_effect=execute),
            patch.object(vcrun_control._IMPL, "_emit"),
        ):
            self.assertEqual(0, vcrun_control.main())

        self.assertEqual(["postgres", "lobster"], events)
        self.assertEqual(
            {"postgres_reconciliation": reconciliation},
            execute_kwargs["runner_metadata"],
        )

    def test_failed_postgres_reconciliation_never_invokes_lobster(self) -> None:
        argv = [
            "vcrun-control",
            "resume",
            "--id",
            "deadbeef",
            "--approve",
            "no",
            "--run-id",
            "run-1",
            "--expected-revision",
            "2",
        ]
        with (
            patch.dict(os.environ, {"VCOPS_OPERATOR_ID": "operator@example"}, clear=True),
            patch.object(sys, "argv", argv),
            patch.object(
                vcrun_control,
                "_reconcile_postgres_cancellation",
                side_effect=vcrun_control._IMPL.VCRunError("revision conflict"),
            ),
            patch.object(vcrun_control._IMPL, "_execute") as execute,
            patch.object(vcrun_control._IMPL, "_emit"),
            patch.object(vcrun_control._IMPL, "_error", return_value=2),
        ):
            self.assertEqual(2, vcrun_control.main())
        execute.assert_not_called()


# Canonical valid arguments for the ten workflow selectors added this session.
# The prior FixedRunnerTests spot-checked only the original selectors, so the
# new selectors' per-contract branch validation (record_kind, proposal_kind,
# severity, cadence/source_class, limit, origin_subtype, evidence_hash,
# citations_json, json-object args) had no direct validate_workflow_args test.
NEW_SELECTOR_VALID_ARGS = {
    "inbound-text-intake": {
        "idempotency_key": "g5-fixture-inbound-text", "lead_title": "Example Lead",
        "company_name": "Example Inc", "company_domain": "example.com",
        "origin_subtype": "direct_contact",
    },
    "evidence-record": {
        "idempotency_key": "g5-fixture-evidence", "lead_id": "1",
        "evidence_json": '{"claim":"x"}',
    },
    "contradiction-record": {
        "idempotency_key": "g5-fixture-contradiction", "lead_id": "1",
        "left_fact_id": "1", "right_fact_id": "2", "severity": "high",
    },
    "trajectory-record": {
        "idempotency_key": "g5-fixture-trajectory", "lead_id": "1",
        "left_fact_id": "1", "right_fact_id": "2",
    },
    "memo-record": {
        "idempotency_key": "g5-fixture-memo", "lead_id": "1", "evaluation_id": "1",
        "compiled_truth_id": "1", "memo_title": "Memo", "memo_markdown": "# Memo",
        "citations_json": "[]", "evidence_hash": "a" * 64,
    },
    "source-watch": {
        "idempotency_key": "g5-fixture-watch", "source_name": "Example Blog",
        "source_uri": "https://example.com/feed", "source_class": "company_blog",
        "cadence": "daily", "thesis_relevance": "fintech", "expected_signal": "funding",
    },
    "source-unwatch": {
        "idempotency_key": "g5-fixture-unwatch", "source_uri": "https://example.com/feed",
    },
    "source-scan": {"idempotency_key": "g5-fixture-scan", "limit": "10"},
    "orchestration-record": {
        "idempotency_key": "g5-fixture-orch", "lead_id": "1",
        "record_kind": "chief_output", "specialist": "founder-researcher",
        "payload_json": '{"k":"v"}',
    },
    "proposal-record": {
        "idempotency_key": "g5-fixture-proposal", "proposal_kind": "schema_change",
        "title": "Prop", "summary": "Summary", "content_json": '{"k":"v"}',
    },
}


class NewSelectorContractTests(unittest.TestCase):
    def test_every_selector_rejects_empty_and_nonobject(self) -> None:
        # All 18 selectors require at least idempotency_key, so an empty object
        # and a non-object must both fail closed — proving each selector is wired
        # into validate_workflow_args with an enforced key contract.
        for selector in vcrun.WORKFLOWS:
            with self.subTest(selector=selector):
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args(selector, "{}")
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args(selector, "[]")

    def test_new_selectors_accept_canonical_args(self) -> None:
        for selector, args in NEW_SELECTOR_VALID_ARGS.items():
            with self.subTest(selector=selector):
                rendered = vcrun.validate_workflow_args(selector, json.dumps(args))
                self.assertEqual(set(json.loads(rendered)), set(args))

    def test_new_selectors_reject_extra_key_and_bad_enum(self) -> None:
        for selector, args in NEW_SELECTOR_VALID_ARGS.items():
            with self.subTest(selector=selector, case="extra"):
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args(selector, json.dumps({**args, "extra": "x"}))
        # Per-selector enumerations must fail closed on an out-of-taxonomy value.
        bad = {
            "contradiction-record": ("severity", "catastrophic"),
            "orchestration-record": ("record_kind", "gossip"),
            "proposal-record": ("proposal_kind", "freeform"),
            "source-watch": ("cadence", "hourly"),
            "inbound-text-intake": ("origin_subtype", "cold_call"),
        }
        for selector, (key, value) in bad.items():
            with self.subTest(selector=selector, case="enum"):
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args(
                        selector, json.dumps({**NEW_SELECTOR_VALID_ARGS[selector], key: value})
                    )


class FailureReasonParityTests(unittest.TestCase):
    """Every failure reason vcrun can hand to `workflow-reconcile-failure` must be
    a class vcops accepts, or the reconciliation is rejected and the run strands
    in 'running'. This pins the cross-file contract so the drift cannot recur."""

    def _vcops_failure_classes(self) -> set[str]:
        import ast

        source = (PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "RUNNER_FAILURE_CLASSES" for t in node.targets
            ):
                return {
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
        raise AssertionError("RUNNER_FAILURE_CLASSES not found in vcops.py")

    def _vcrun_emitted_reasons(self) -> set[str]:
        import ast

        source = (PACKAGE / "workspaces/vc-chief/vc/bin/vcrun.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        reasons: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "reason" and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    reasons.add(node.value.value)
        return reasons

    def test_every_vcrun_reason_is_accepted_by_vcops(self) -> None:
        accepted = self._vcops_failure_classes()
        emitted = self._vcrun_emitted_reasons()
        self.assertIn("lobster_no_exit", emitted, "expected vcrun to emit the no-exit reason")
        self.assertTrue(emitted, "expected to discover at least one vcrun failure reason")
        self.assertLessEqual(
            emitted,
            accepted,
            f"vcrun emits reason(s) vcops rejects: {sorted(emitted - accepted)}",
        )


if __name__ == "__main__":
    unittest.main()
