# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[2]
VCOPS = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"


class AgentVcopsBoundaryTests(unittest.TestCase):
    def invoke_agent(self, command: list[str]) -> tuple[int, dict[str, Any]]:
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "VCOPS_AGENT_MODE": "1",
        }
        process = subprocess.run(
            [sys.executable, str(VCOPS), *command],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return process.returncode, json.loads(process.stdout)

    def test_operator_dispatcher_and_bearer_token_commands_are_denied(self) -> None:
        commands = (
            [
                "approval-request",
                "--idempotency-key", "g5-deny",
                "--action", "external-write",
                "--scope", "{}",
                "--action-preview", "{}",
                "--target-system", "external",
                "--requested-by", "agent",
            ],
            [
                "approval-decide",
                "--request-id", "request",
                "--decision", "approve",
                "--approver", "agent",
                "--approval-channel", "session",
                "--reason", "forbidden",
            ],
            [
                "approval-consume",
                "--token", "bearer",
                "--action", "external-write",
                "--scope", "{}",
                "--target-system", "external",
                "--payload-hash", "0" * 64,
                "--transaction-id", "fabricated",
                "--consumed-by", "agent",
            ],
            ["notification-claim", "--worker", "agent"],
            [
                "notification-mark",
                "--notification-id", "fabricated",
                "--worker", "agent",
                "--status", "sent",
                "--provider-message-id", "fabricated",
            ],
            [
                "create-lead",
                "--company-id", "1",
                "--lead-title", "forbidden",
                "--idempotency-key", "g5-deny-write",
            ],
            [
                "compiled-truth",
                "--lead-id", "1",
            ],
            [
                "notification-enqueue",
                "--idempotency-key", "g5-deny-log",
                "--dedupe-key", "g5-deny-log",
                "--provider", "internal_log",
                "--destination", "audit",
                "--severity", "silent_log",
                "--subject", "forbidden",
                "--payload", "{}",
            ],
        )
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "VCOPS_AGENT_MODE": "1",
        }
        for command in commands:
            with self.subTest(command=command[0]):
                process = subprocess.run(
                    [sys.executable, str(VCOPS), *command],
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                self.assertEqual(1, process.returncode, process.stdout + process.stderr)
                payload = json.loads(process.stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual("agent_command_forbidden", payload["error"]["code"])

    def test_agent_cannot_choose_confidential_or_restricted_clearance(self) -> None:
        commands = (
            [
                "entity-resolve",
                "--name", "Boundary Test",
                "--domain", "boundary.invalid",
                "--requester-id", "agent:test",
                "--purpose", "research",
                "--max-confidentiality", "confidential",
            ],
            [
                "memory-lookup",
                "--query", "Boundary Test",
                "--max-confidentiality", "restricted",
            ],
        )
        for command in commands:
            with self.subTest(command=command[0]):
                returncode, payload = self.invoke_agent(command)
                self.assertEqual(1, returncode)
                self.assertEqual("confidentiality_denied", payload["error"]["code"])

    def test_evaluation_preview_returns_typed_errors_for_malformed_agent_json(self) -> None:
        # Malformed agent JSON is expected input on this lane: every probe must
        # produce a typed validation error at exit 2, never internal_error/3.
        valid_criterion = {
            "evidence_state": "positive",
            "quality_score": 4,
            "coverage": "partial",
            "evidence_quality": "medium",
            "evidence_fact_ids": [1],
            "counterevidence_fact_ids": [],
            "rationale": "sample rationale",
            "what_would_change": "sample falsifier",
        }
        probes = (
            ({"quality_score": "NaN"}, {}, "invalid_score"),
            ({"evidence_state": []}, {}, "invalid_criterion"),
            ({"coverage": {}}, {}, "invalid_criterion"),
            ({"rationale": True}, {}, "invalid_text"),
            ({}, {"adjustments": [{"kind": "trajectory", "points": "NaN",
                                   "reason": "r", "evidence_fact_ids": [1]}]}, "invalid_adjustment"),
            ({}, {"adjustments": {}}, "invalid_adjustment"),
        )
        for override, context, expected_code in probes:
            with self.subTest(code=expected_code, override=override, context=context):
                criteria = {"thesis_stage_geography_fit": {**valid_criterion, **override}}
                returncode, payload = self.invoke_agent(
                    [
                        "evaluation-preview",
                        "--criteria", json.dumps(criteria),
                        "--decision-context", json.dumps(context),
                    ]
                )
                self.assertEqual(2, returncode, payload)
                self.assertEqual(expected_code, payload["error"]["code"])

    def test_malformed_trusted_context_tokens_stay_typed(self) -> None:
        """A hostile token must be denied, never crash the helper.

        `compare_digest` raises TypeError on non-ASCII str operands and
        `.encode("ascii")` raises UnicodeEncodeError, so the token's shape has
        to be checked before any cryptographic work — this is the
        channel-facing verification path.
        """
        with tempfile.TemporaryDirectory(prefix="g5-tc-") as raw:
            key = Path(raw) / "trusted-context.key"
            key.write_bytes(b"g5-test-trusted-context-key-000000000000000000")
            probes = ("abc.dëf", "ä.def", "abc", "a.b.c", "eyJhIjoxfQ==.YWJj", "abc.")
            for token in probes:
                with self.subTest(token=token):
                    process = subprocess.run(
                        [
                            sys.executable, str(VCOPS), "preference-lookup",
                            "--trusted-context", token,
                        ],
                        env={
                            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                            "VCOPS_AGENT_MODE": "1",
                            "VC_TRUSTED_CONTEXT_KEY_FILE": str(key),
                        },
                        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                    )
                    payload = json.loads(process.stdout)
                    self.assertEqual("invalid_trusted_context", payload["error"]["code"])
                    self.assertEqual(1, process.returncode)

    def test_oversized_and_deeply_nested_agent_json_stay_typed(self) -> None:
        # int() raises ValueError past CPython's digit limit, and json.loads
        # raises RecursionError, neither of which is a validation error type.
        criterion = {
            "evidence_state": "positive", "quality_score": 4, "coverage": "partial",
            "evidence_quality": "medium", "evidence_fact_ids": ["9" * 4301],
            "counterevidence_fact_ids": [], "rationale": "r", "what_would_change": "w",
        }
        returncode, payload = self.invoke_agent([
            "evaluation-preview",
            "--criteria", json.dumps({"founder_team_signal": criterion}),
            "--decision-context", "{}",
        ])
        self.assertEqual(2, returncode)
        self.assertEqual("invalid_evidence_id", payload["error"]["code"])

        # 20_000 nested brackets is 40 KB in one argv element. Linux caps a
        # SINGLE argument at MAX_ARG_STRLEN = 32 * PAGE_SIZE = 131_072 bytes on
        # the usual 4 KB page, independently of `getconf ARG_MAX`, and exceeding
        # it raises OSError(errno 7) out of execve before the process starts.
        # The previous 200_000 (400 KB) therefore made this suite -- and so
        # `verify_offline.py` -- impossible to pass on any Linux host, including
        # the Debian host the gate certifies. Eighteen audit passes ran on macOS,
        # which has no per-argument cap, and never saw it. Measured in
        # python:3.11-slim: 130_000 bytes succeeds, 140_000 raises errno 7; and
        # json.loads still raises RecursionError at every depth from 1_000 up, so
        # the property under test is unchanged.
        depth = 20_000
        returncode, payload = self.invoke_agent([
            "evaluation-preview",
            "--criteria", "[" * depth + "]" * depth,
            "--decision-context", "{}",
        ])
        self.assertEqual(2, returncode)
        # Either typed rejection satisfies the property this test is named for,
        # and which one fires depends on the interpreter. No depth makes it
        # uniform: CPython 3.14 parses 65_000-deep JSON that 3.11 rejects with
        # RecursionError, while a depth deep enough to exhaust 3.14's budget
        # (200_000) needs a 400 KB argv element, which Linux refuses outright
        # (MAX_ARG_STRLEN). So on the deployed 3.11 floor this exercises the
        # RecursionError handler in vcops's JSON helper — the one that stops it
        # escaping as internal_error/exit 3 — and on a newer developer
        # interpreter it exercises the not-an-object branch. Both are typed, both
        # exit 2, and neither is a traceback, which is the contract.
        self.assertIn(
            payload["error"]["code"], {"invalid_json", "invalid_json_type"},
            f"deeply nested agent JSON produced {payload['error']['code']!r}; the "
            f"contract is a typed rejection, not an internal error",
        )

    def test_operator_decision_lanes_reject_non_ascii_principals(self) -> None:
        """approval-decide and proposal-decide share one authority contract.

        Both must answer a non-ASCII principal with the typed denial rather
        than a TypeError out of `compare_digest`.
        """
        commands = (
            ["approval-decide", "--request-id", "r", "--decision", "approve",
             "--approver", "appröver", "--approval-channel", "session", "--reason", "x"],
            ["proposal-decide", "--proposal-id", "1", "--decision", "accept",
             "--reviewer", "reviöwer", "--note", "x"],
        )
        for command in commands:
            with self.subTest(command=command[0]):
                process = subprocess.run(
                    [sys.executable, str(VCOPS), *command],
                    env={
                        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                        "VCOPS_OPERATOR_MODE": "1",
                        "VCOPS_OPERATOR_ID": "operator-1",
                    },
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                )
                payload = json.loads(process.stdout)
                self.assertEqual("operator_context_required", payload["error"]["code"])
                self.assertEqual(1, process.returncode)

    def test_agent_json_rejects_duplicate_object_keys(self) -> None:
        returncode, payload = self.invoke_agent(
            [
                "evaluation-preview",
                "--criteria", '{"x":1,"x":2}',
                "--decision-context", "{}",
            ]
        )
        self.assertEqual(2, returncode)
        self.assertEqual("invalid_json", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
