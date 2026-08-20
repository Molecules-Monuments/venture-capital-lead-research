# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import patch

import yaml


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
        payload: dict[str, Any] = {"ok": False, "error": {"code": "lobster_timeout"}}
        vcrun._attach_failure_reconciliation(
            payload,
            failure_hook=lambda reason: reconciliation,
            reason="lobster_timeout",
        )
        self.assertEqual(reconciliation, payload["postgres_reconciliation"])

        # A cleanup that itself fails must not replace the original failure:
        # the Lobster envelope carrying the broken step's error output (step
        # ids are named only for timeouts) is the diagnostic one, and
        # reporting only the downstream reconciliation error is what made a
        # failed retry look like a broken deployment.
        original: dict[str, Any] = {
            "ok": False,
            "error": {"code": "lobster_step_failure"},
            "lobster": {"ok": False, "error": {"code": "invalid_transition"}},
        }
        vcrun._attach_failure_reconciliation(
            original,
            failure_hook=lambda reason: (_ for _ in ()).throw(
                vcrun.VCRunError("revision conflict")
            ),
            reason="lobster_step_failure",
        )
        self.assertEqual("invalid_transition", original["lobster"]["error"]["code"])
        cleanup = original["postgres_reconciliation"]
        self.assertFalse(cleanup["ok"])
        self.assertEqual("reconciliation_failed", cleanup["error"]["code"])
        self.assertIn("revision conflict", cleanup["error"]["message"])

        invalid: dict[str, Any] = {"ok": False, "error": {"code": "lobster_timeout"}}
        vcrun._attach_failure_reconciliation(
            invalid,
            failure_hook=lambda reason: {"ok": False},
            reason="lobster_timeout",
        )
        self.assertEqual("reconciliation_invalid", invalid["postgres_reconciliation"]["error"]["code"])


def _closed_domain_row_values(document: str, workflow: str, argument: str) -> str | None:
    """The "Accepted values" cell documenting (workflow, argument), or None.

    The documentation half of this class used to search the whole of
    docs/WORKFLOWS.md for the backticked value. That could not see a value
    deleted from its own row, because the same token is often accepted by a
    second domain: `other` belongs to both `proposal-record --proposal_kind`
    and `source-watch --source_class`, so gutting the first row left the token
    in the second and the assertion still passed — reproducing exactly the
    "follow the table verbatim and it is incomplete" defect the class exists to
    close. Anchor on the row instead of the file.

    Returning None rather than raising lets the caller fail with a rot message:
    a reworded or moved table must fail loudly, not pass on nothing.
    """
    for line in document.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        # `| workflow | argument | values |` — the exact match on the argument
        # cell is what keeps the workflow-inventory table (also three columns,
        # and also leading with a backticked workflow name) out of the search.
        if len(cells) != 3 or cells[1] != f"`{argument}`":
            continue
        # `preference_key` documents two workflows in one cell, so the workflow
        # is matched inside the cell rather than against the whole of it.
        if f"`{workflow}`" in cells[0]:
            return cells[2]
    return None


def _preference_value_prose(document: str, preference_key: str) -> str | None:
    """The parenthesised value list docs/WORKFLOWS.md gives for one preference key.

    `preference_value` is the one closed domain with no table row, so its
    documentation is prose: ``\\`memo_length\\`\\n(\\`short\\`/...)``. Anchoring
    on "backticked key immediately followed by a parenthesis" skips the
    `preference_key` table row, where the key is followed by a comma.
    """
    match = re.search(rf"`{re.escape(preference_key)}`\s*\(([^)]*)\)", document)
    return match.group(1) if match else None


class DocumentedValueDomainTests(unittest.TestCase):
    """Every closed argument domain is enforced AND written down.

    Following docs/WORKFLOWS.md verbatim used to fail on first use for
    `contradiction-record --severity` and `inbound-text-intake --origin_subtype`:
    the accepted values existed only in vcrun.py. This binds the three together —
    if a domain changes in code, the behavioural half fails; if the table is not
    updated, the documentation half fails.

    "The table" means the operator's own row for that argument, not the
    document: see `_closed_domain_row_values` for the substring form this
    replaced and the value it could not miss.
    """

    DOMAINS: ClassVar[dict[tuple[str, str], tuple[str, ...]]] = {
        ("contradiction-record", "severity"): ("low", "medium", "high", "blocking"),
        ("inbound-text-intake", "origin_subtype"): (
            "direct_contact", "network_referral", "event_followup", "unknown",
        ),
        ("orchestration-record", "record_kind"): (
            "delegation_eval", "return_assessment", "chief_output",
        ),
        ("proposal-record", "proposal_kind"): (
            "schema_change", "source_policy", "skill_candidate", "other",
        ),
        ("source-watch", "source_class"): (
            "company_blog", "vc_portfolio", "news_rss", "press_release",
            "research_report", "open_source", "job_board", "other",
        ),
        ("source-watch", "cadence"): ("daily", "weekly", "monthly"),
        ("preference-observe", "preference_key"): (
            "memo_length", "communication_tone", "research_depth",
            "citation_density", "output_structure",
        ),
        ("preference-observe", "observation_kind"): ("explicit", "inferred"),
    }

    BASE: ClassVar[dict[str, dict[str, str]]] = {
        "contradiction-record": {
            "idempotency_key": "g5-domain", "lead_id": "1",
            "left_fact_id": "1", "right_fact_id": "2", "severity": "low",
        },
        "inbound-text-intake": {
            "idempotency_key": "g5-domain", "lead_title": "Lead", "company_name": "Acme",
            "company_domain": "acme.example", "origin_subtype": "direct_contact",
        },
        "orchestration-record": {
            "idempotency_key": "g5-domain", "lead_id": "1", "record_kind": "chief_output",
            "specialist": "founder-researcher", "payload_json": "{}",
        },
        "proposal-record": {
            "idempotency_key": "g5-domain", "proposal_kind": "other", "title": "T",
            "summary": "S", "content_json": "{}",
        },
        "source-watch": {
            "idempotency_key": "g5-domain", "source_name": "Blog",
            "source_uri": "https://acme.example/blog", "source_class": "company_blog",
            "cadence": "daily", "thesis_relevance": "relevant", "expected_signal": "launches",
        },
        "preference-observe": {
            "idempotency_key": "g5-domain", "trusted_context": "opaque.capability",
            "preference_key": "memo_length", "preference_value": "short",
            "observation_kind": "explicit",
        },
    }

    def test_each_documented_value_is_accepted_and_others_are_refused(self) -> None:
        for (workflow, argument), values in self.DOMAINS.items():
            for value in values:
                payload = {**self.BASE[workflow], argument: value}
                with self.subTest(workflow=workflow, argument=argument, value=value):
                    rendered = json.loads(
                        vcrun.validate_workflow_args(workflow, json.dumps(payload))
                    )
                    self.assertEqual(value, rendered[argument])
            with self.subTest(workflow=workflow, argument=argument, value="<outside>"):
                payload = {**self.BASE[workflow], argument: "not-a-reviewed-value"}
                with self.assertRaises(vcrun.VCRunError):
                    vcrun.validate_workflow_args(workflow, json.dumps(payload))

    def test_every_accepted_value_appears_in_the_operator_documentation(self) -> None:
        workflows_doc = (PACKAGE / "docs/WORKFLOWS.md").read_text(encoding="utf-8")
        for (workflow, argument), values in self.DOMAINS.items():
            row = _closed_domain_row_values(workflows_doc, workflow, argument)
            if row is None:
                self.fail(
                    f"docs/WORKFLOWS.md has no closed-domain table row for "
                    f"{workflow} --{argument}. The table moved or was reworded, "
                    "so this check was about to assert against nothing.",
                )
            for value in values:
                with self.subTest(workflow=workflow, argument=argument, value=value):
                    self.assertIn(
                        f"`{value}`",
                        row,
                        f"{workflow} --{argument} accepts {value!r} but its own "
                        f"docs/WORKFLOWS.md row does not list it: {row}",
                    )

    def test_preference_values_match_the_helper_schema(self) -> None:
        # preference_value is enforced by vcops, not vcrun, so bind the doc to
        # the helper's own table rather than to a second copy of it.
        workflows_doc = (PACKAGE / "docs/WORKFLOWS.md").read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "vcops_preferences", PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
        )
        assert spec is not None and spec.loader is not None
        vcops = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vcops)
        for key, values in vcops.PREFERENCE_VALUES.items():
            documented = _preference_value_prose(workflows_doc, key)
            if documented is None:
                self.fail(
                    f"docs/WORKFLOWS.md no longer states the values for "
                    f"preference_key {key!r} as a parenthesised list after the "
                    "key. Reword the prose back, or this check asserts nothing.",
                )
            for value in values:
                with self.subTest(preference_key=key, value=value):
                    self.assertIn(
                        f"`{value}`",
                        documented,
                        f"vcops accepts {value!r} for preference_key {key!r} but "
                        f"docs/WORKFLOWS.md lists ({documented}) for that key",
                    )


class ReplayProbeTests(unittest.TestCase):
    """The pre-flight classification that makes an unchanged retry a no-op."""

    ARGS: ClassVar[str] = json.dumps(
        {
            "idempotency_key": "g5-replay",
            "lead_id": "7",
            "evidence_json": '{"claim":"arr","value":"1"}',
        }
    )

    def _probe_result(self, outcome: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "workflow_replay_probe": {
                        "outcome": outcome,
                        "workflow_run": {"run_id": "r-1", "status": "succeeded"},
                    },
                }
            ),
            stderr="",
        )

    def test_the_injected_digest_covers_the_whole_argument_payload(self) -> None:
        # The audit found two evidence-record runs with completely different
        # evidence_json recording the SAME workflow input_hash, because
        # workflow-start saw only the workflow, lead and key.
        first = vcrun.validate_workflow_args("evidence-record", self.ARGS)
        changed = vcrun.validate_workflow_args(
            "evidence-record",
            json.dumps(
                {
                    "idempotency_key": "g5-replay",
                    "lead_id": "7",
                    "evidence_json": '{"claim":"arr","value":"999"}',
                }
            ),
        )
        self.assertNotEqual(first, changed)
        self.assertNotEqual(
            hashlib.sha256(first.encode()).hexdigest(),
            hashlib.sha256(changed.encode()).hexdigest(),
        )

    def test_a_caller_cannot_supply_its_own_digest(self) -> None:
        for workflow in sorted(vcrun.WORKFLOWS):
            contract = vcrun.WORKFLOWS[workflow]
            with self.subTest(workflow=workflow):
                self.assertNotIn("input_digest", contract["keys"])
                self.assertNotIn("input_digest", contract.get("optional_keys", set()))
        with self.assertRaises(vcrun.VCRunError):
            vcrun.validate_workflow_args(
                "runtime-preflight",
                json.dumps({"idempotency_key": "g5", "input_digest": "0" * 64}),
            )

    def test_every_workflow_declares_the_injected_argument(self) -> None:
        for workflow, contract in sorted(vcrun.WORKFLOWS.items()):
            body = yaml.safe_load(
                (PACKAGE / "workspaces/vc-chief/vc/workflows" / contract["file"]).read_text(
                    encoding="utf-8"
                )
            )
            with self.subTest(workflow=workflow):
                self.assertIn("input_digest", body["args"])
                start = next(
                    step for step in body["steps"] if step["id"] == "workflow_start"
                )
                self.assertIn('--input-digest "$LOBSTER_ARG_INPUT_DIGEST"', start["run"])

    def test_a_completed_replay_returns_the_existing_run_without_running_lobster(self) -> None:
        with patch.object(vcrun, "_validate_install"), patch.object(
            vcrun.subprocess, "run", return_value=self._probe_result("completed")
        ), patch.object(vcrun, "_execute") as execute, patch.object(vcrun, "_emit") as emit:
            self.assertEqual(0, vcrun.main(["run", "evidence-record", "--args-json", self.ARGS]))
        execute.assert_not_called()
        payload = emit.call_args.args[0]
        self.assertTrue(payload["ok"])
        self.assertEqual("completed", payload["idempotent_replay"]["outcome"])

    def test_a_resumable_or_absent_run_proceeds_to_lobster(self) -> None:
        for outcome in ("absent", "in_progress", "retried", "unverifiable"):
            with self.subTest(outcome=outcome), patch.object(
                vcrun, "_validate_install"
            ), patch.object(
                vcrun.subprocess, "run", return_value=self._probe_result(outcome)
            ), patch.object(vcrun, "_execute", return_value=0) as execute:
                self.assertEqual(
                    0, vcrun.main(["run", "evidence-record", "--args-json", self.ARGS])
                )
            execute.assert_called_once()
            command = execute.call_args.args[0]
            payload = json.loads(command[command.index("--args-json") + 1])
            self.assertEqual(64, len(payload["input_digest"]))

    def test_a_typed_probe_refusal_is_reported_verbatim(self) -> None:
        refusal = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "idempotency_payload_mismatch",
                        "message": "workflow replay arguments differ from the committed request",
                        "details": None,
                    },
                }
            ),
            stderr="",
        )
        with patch.object(vcrun, "_validate_install"), patch.object(
            vcrun.subprocess, "run", return_value=refusal
        ), patch.object(vcrun, "_execute") as execute, patch.object(vcrun, "_emit") as emit:
            self.assertEqual(2, vcrun.main(["run", "evidence-record", "--args-json", self.ARGS]))
        execute.assert_not_called()
        self.assertEqual(
            "idempotency_payload_mismatch", emit.call_args.args[0]["error"]["code"]
        )

    def test_an_unknown_probe_outcome_fails_closed(self) -> None:
        with patch.object(vcrun, "_validate_install"), patch.object(
            vcrun.subprocess, "run", return_value=self._probe_result("something_new")
        ), patch.object(vcrun, "_execute") as execute:
            self.assertEqual(2, vcrun.main(["run", "evidence-record", "--args-json", self.ARGS]))
        execute.assert_not_called()

    def test_dry_run_never_probes_or_mutates(self) -> None:
        with patch.object(vcrun, "_validate_install"), patch.object(
            vcrun.subprocess, "run"
        ) as helper, patch.object(vcrun, "_execute", return_value=0):
            self.assertEqual(
                0, vcrun.main(["dry-run", "evidence-record", "--args-json", self.ARGS])
            )
        helper.assert_not_called()


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


class IdentifierCeilingTests(unittest.TestCase):
    """Every contract argument is classified before the run row is created.

    `vcrun` enforced the PostgreSQL BIGINT ceiling for `lead_id` alone; the other
    identifier arguments accepted an in-shape value above 9223372036854775807 and
    failed later inside `vcops`, after `workflow-start` had already committed the
    run row — costing a fresh idempotency key to correct.

    Coverage is split deliberately. The classification is asserted as a TOTAL
    partition over every contract key, which is the part that stops a seventh
    identifier being added unbounded (that is how `flow_revision` was missed).
    The ceiling itself is asserted on the shared helper for every bounded key,
    plus one end-to-end pass through `validate_workflow_args` proving the helper
    is actually reached before dispatch. A contract-complete payload cannot be
    synthesised generically — `company_domain`, `severity` and friends have their
    own formats — so the end-to-end leg uses one hand-built valid object rather
    than a generated one that would fail for the wrong reason.
    """

    OVER = "9223372036854775808"  # BIGINT max + 1, still a legal shape
    MAX = "9223372036854775807"

    def test_no_identifier_argument_is_left_unclassified(self) -> None:
        self.assertEqual(
            set(), set(vcrun.UNCLASSIFIED_ID_ARG_KEYS),
            "these contract arguments are not classified as bigint, opaque "
            "text or non-identifier: "
            f"{sorted(vcrun.UNCLASSIFIED_ID_ARG_KEYS)}. Classify each one.",
        )

    def test_the_helper_bounds_every_key_declared_bigint(self) -> None:
        bounded = set(vcrun.BIGINT_ID_ARG_KEYS) | set(vcrun.NON_NEGATIVE_BIGINT_ARG_KEYS)
        self.assertTrue(bounded, "the bigint identifier sets are empty; the derivation has rotted")
        for key in sorted(bounded):
            with self.subTest(argument=key):
                zero_ok = key in vcrun.NON_NEGATIVE_BIGINT_ARG_KEYS
                vcrun._canonical_bigint({key: self.MAX}, key, allow_zero=zero_ok)
                with self.assertRaises(vcrun.VCRunError) as caught:
                    vcrun._canonical_bigint({key: self.OVER}, key, allow_zero=zero_ok)
                self.assertIn(
                    key, str(caught.exception),
                    f"the refusal for {key} does not name it, so an operator cannot "
                    f"tell which argument was out of range: {caught.exception}",
                )

    def test_zero_is_accepted_only_where_it_is_legitimate(self) -> None:
        # flow_revision is a Task Flow handle whose first value is 0; the row
        # identifiers are positive, so 0 must stay a refusal for them.
        for key in sorted(vcrun.NON_NEGATIVE_BIGINT_ARG_KEYS):
            with self.subTest(argument=key, expect="0 accepted"):
                vcrun._canonical_bigint({key: "0"}, key, allow_zero=True)
        for key in sorted(vcrun.BIGINT_ID_ARG_KEYS):
            with self.subTest(argument=key, expect="0 refused"):
                with self.assertRaises(vcrun.VCRunError):
                    vcrun._canonical_bigint({key: "0"}, key)

    # Contract-complete payloads, hand-built and verified: a generated one is
    # refused on `company_domain`/`severity`/`citations_json` formats long before
    # any ceiling, which would make this pass for the wrong reason. Each payload
    # is asserted key-complete below, so a changed contract fails loudly here
    # instead of silently degrading into a key-mismatch test.
    VALID: ClassVar[dict[str, dict[str, str]]] = {
        "evaluate-lead": {
            "idempotency_key": "k" * 20, "lead_id": "1",
            "criteria_json": "{}", "decision_context_json": "{}",
        },
        "contradiction-record": {
            "idempotency_key": "k" * 20, "lead_id": "1",
            "left_fact_id": "1", "right_fact_id": "1", "severity": "low",
        },
        "document-lead-intake": {
            "idempotency_key": "k" * 20, "extraction_id": "1",
            "company_domain": "example.com", "company_name": "x",
            "lead_title": "x", "trusted_context": "x",
        },
        "memo-record": {
            "idempotency_key": "k" * 20, "lead_id": "1", "evaluation_id": "1",
            "compiled_truth_id": "1", "memo_markdown": "x", "memo_title": "x",
            "evidence_hash": "a" * 64,
            "citations_json":
                '[{"fact_id": 1, "source_id": 1, "citation": "[C1]", "locator": "p1"}]',
        },
        # Carries the OPTIONAL `flow_revision` on purpose. It is the only
        # non-negative bounded identifier, and no other payload here (or
        # anywhere in tests/) supplies it, so without this entry the second
        # dispatch loop in `validate_workflow_args` was uncovered end to end:
        # deleting that loop kept every offline suite green while the runner
        # started accepting "abc", "-1" and BIGINT_MAX+1 for flow_revision.
        "orchestration-record": {
            "idempotency_key": "k" * 20, "lead_id": "1",
            "record_kind": "chief_output", "specialist": "founder-researcher",
            "payload_json": "{}", "flow_revision": "0",
        },
    }

    def test_validate_workflow_args_applies_the_ceiling_before_dispatch(self) -> None:
        """The end-to-end leg, over EVERY bounded identifier, not just lead_id.

        Asserting the helper alone was dead cover: reverting the dispatch loop to
        `{"lead_id"} & actual` left the helper's own tests green while five
        identifiers went unbounded again. This drives the real entry point, so an
        over-range value provably never reaches `workflow-start`.
        """
        bounded = set(vcrun.BIGINT_ID_ARG_KEYS) | set(vcrun.NON_NEGATIVE_BIGINT_ARG_KEYS)
        covered = set()
        for workflow, payload in sorted(self.VALID.items()):
            # Required keys, plus exactly the optional keys this payload chooses
            # to carry: an optional key stays legal, an unknown or missing one
            # still fails loudly. Comparing against the required set alone would
            # have made carrying `flow_revision` impossible, which is why the
            # non-negative dispatch loop went uncovered.
            allowed = set(vcrun.WORKFLOWS[workflow]["keys"]) | (
                set(payload) & set(vcrun.WORKFLOWS[workflow].get("optional_keys", ()))
            )
            self.assertEqual(
                sorted(payload), sorted(allowed),
                f"{workflow}'s contract moved; this payload is no longer complete "
                "and would be refused on key mismatch rather than on the ceiling",
            )
            vcrun.validate_workflow_args(workflow, json.dumps(payload))
            for key in sorted(bounded & set(payload)):
                covered.add(key)
                with self.subTest(workflow=workflow, argument=key):
                    with self.assertRaises(vcrun.VCRunError) as caught:
                        vcrun.validate_workflow_args(
                            workflow, json.dumps(dict(payload, **{key: self.OVER}))
                        )
                    self.assertIn(
                        key, str(caught.exception),
                        f"{workflow}: the refusal does not name {key}: {caught.exception}",
                    )
        self.assertEqual(
            covered, bounded,
            "these bounded identifiers are exercised by no end-to-end payload, so "
            f"a dispatch-loop regression would not be caught: {sorted(bounded - covered)}",
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
            ) and isinstance(node, ast.Assign) and isinstance(node.value, (ast.Set, ast.List, ast.Tuple)):
                return {
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
        raise AssertionError("RUNNER_FAILURE_CLASSES not found in vcops.py")

    def _vcrun_emitted_reasons(self) -> set[str]:
        import ast

        def branch_constants(expr: "ast.expr"):
            # Only the result branches of a conditional expression are emitted
            # values; its test condition compares unrelated strings (error
            # codes) that must not be mistaken for reasons.
            if isinstance(expr, ast.IfExp):
                yield from branch_constants(expr.body)
                yield from branch_constants(expr.orelse)
            elif isinstance(expr, ast.Constant) and isinstance(expr.value, str):
                yield expr.value

        source = (PACKAGE / "workspaces/vc-chief/vc/bin/vcrun.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        reasons: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "reason" and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    reasons.add(node.value.value)
            # vcrun also computes a reason through a conditional expression
            # bound to a local named `reason` before passing reason=reason.
            # Walk those assignments too — without this, half the emitted
            # reasons hide behind the variable and this parity gate could not
            # fail on their drift.
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "reason" for t in node.targets
            ):
                reasons.update(branch_constants(node.value))
        return reasons

    def test_every_vcrun_reason_is_accepted_by_vcops(self) -> None:
        accepted = self._vcops_failure_classes()
        emitted = self._vcrun_emitted_reasons()
        self.assertIn("lobster_no_exit", emitted, "expected vcrun to emit the no-exit reason")
        self.assertIn(
            "lobster_step_failure", emitted,
            "expected discovery to see through the reason-variable indirection",
        )
        self.assertTrue(emitted, "expected to discover at least one vcrun failure reason")
        self.assertLessEqual(
            emitted,
            accepted,
            f"vcrun emits reason(s) vcops rejects: {sorted(emitted - accepted)}",
        )


if __name__ == "__main__":
    unittest.main()
