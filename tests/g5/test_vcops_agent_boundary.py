# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
VCOPS = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"


class AgentVcopsBoundaryTests(unittest.TestCase):
    def invoke_agent(self, command: list[str]) -> tuple[int, dict[str, object]]:
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
            timeout=5,
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
                    timeout=5,
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
