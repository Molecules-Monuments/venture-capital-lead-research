# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = PACKAGE / "scripts/validate_workflows.py"
SPEC = importlib.util.spec_from_file_location("validate_g5_tests", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
g5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = g5
SPEC.loader.exec_module(g5)


class WorkflowValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parser, findings = g5._load_vcops_parser()
        assert cls.parser is not None, findings

    def validate(self, body: str) -> set[str]:
        with tempfile.TemporaryDirectory(prefix="g5-validator-") as temp:
            path = Path(temp) / "fixture.lobster"
            path.write_text(body, encoding="utf-8")
            findings, _ = g5.validate_workflow(path, self.parser)
        return {item.code for item in findings}

    def test_duplicate_yaml_key_is_rejected(self) -> None:
        codes = self.validate(
            "name: fixture\nname: replacement\nsteps:\n  - id: ok\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
        )
        self.assertIn("yaml_parse", codes)

    def test_duplicate_and_invalid_step_ids_are_rejected(self) -> None:
        codes = self.validate(
            "name: fixture\nsteps:\n"
            "  - id: repeated\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
            "  - id: repeated\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
            "  - id: '../bad'\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
        )
        self.assertIn("step_duplicate", codes)
        self.assertIn("step_id", codes)

    def test_unknown_vcops_command_and_option_are_rejected(self) -> None:
        unknown_command = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: /workspaces/vc-chief/vc/bin/agent/vcops invented\n    timeout_ms: 1000\n"
        )
        unknown_option = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight --invented yes\n    timeout_ms: 1000\n"
        )
        self.assertIn("command_unknown", unknown_command)
        self.assertIn("option_unknown", unknown_option)

    def test_shell_and_raw_argument_injection_are_rejected(self) -> None:
        command_substitution = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: '/workspaces/vc-chief/vc/bin/agent/vcops preflight $(id)'\n    timeout_ms: 1000\n"
        )
        raw_template = self.validate(
            "name: fixture\nargs:\n  lead_id: {default: ''}\nsteps:\n"
            "  - id: bad\n    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id ${lead_id}'\n    timeout_ms: 1000\n"
        )
        unquoted_env = self.validate(
            "name: fixture\nargs:\n  lead_id: {default: ''}\nsteps:\n"
            "  - id: bad\n    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id $LOBSTER_ARG_LEAD_ID'\n    timeout_ms: 1000\n"
        )
        # Step-env references carry channel-controlled values too (VCOPS_SENDER_ID
        # comes from the trusted context), so the quoting rule must cover them.
        unquoted_step_env = self.validate(
            "name: fixture\nsteps:\n"
            "  - id: bad\n    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id $VCOPS_SENDER_ID'\n    timeout_ms: 1000\n"
        )
        self.assertIn("command_substitution", command_substitution)
        self.assertIn("raw_env", raw_template)
        self.assertIn("arg_unquoted", unquoted_env)
        self.assertIn("arg_unquoted", unquoted_step_env)

    def test_legacy_future_and_unbounded_step_refs_are_rejected(self) -> None:
        legacy = self.validate(
            """name: fixture
steps:
  - id: first
    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight
    timeout_ms: 1000
  - id: second
    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id "$first.lead_id"'
    timeout_ms: 1000
"""
        )
        future = self.validate(
            """name: fixture
steps:
  - id: first
    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id "$later.json.lead.id"'
    timeout_ms: 1000
  - id: later
    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight
    timeout_ms: 1000
"""
        )
        unbounded = self.validate(
            """name: fixture
steps:
  - id: first
    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight
    timeout_ms: 1000
  - id: second
    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id "$first.json.arbitrary_text"'
    timeout_ms: 1000
"""
        )
        self.assertIn("step_ref_legacy", legacy)
        self.assertIn("step_ref_order", future)
        self.assertIn("step_ref_unbounded", unbounded)

    def test_openclaw_invoke_env_leak_and_unsafe_authority_are_rejected(self) -> None:
        invoke = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: openclaw.invoke --tool exec\n    timeout_ms: 1000\n"
        )
        leak = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: printenv\n    timeout_ms: 1000\n"
        )
        unsafe = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight --unsafe-ground\n    timeout_ms: 1000\n"
        )
        self.assertIn("openclaw_invoke", invoke)
        self.assertIn("shell_builtin", leak)
        self.assertIn("unsafe_authority", unsafe)

    def test_approval_bypass_and_self_decision_are_rejected(self) -> None:
        bypass = self.validate("name: fixture\nsteps:\n  - id: approve\n    approval: false\n")
        self_decision = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n"
            "    run: '/workspaces/vc-chief/vc/bin/agent/vcops approval-decide --request-id x --decision approve --approver x --approval-channel x --reason x'\n"
            "    timeout_ms: 1000\n"
        )
        self.assertIn("approval_bypass", bypass)
        self.assertIn("approval_boundary", self_decision)

    def test_non_run_interpolation_surfaces_are_validated(self) -> None:
        stdin_injection = self.validate(
            "name: fixture\nsteps:\n"
            "  - id: first\n    approval: {prompt: review}\n"
            "    stdin: '$(id) $later.json.arbitrary_text'\n"
            "  - id: later\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
        )
        self.assertIn("command_substitution", stdin_injection)
        self.assertIn("step_ref_order", stdin_injection)
        self.assertIn("step_ref_unbounded", stdin_injection)

    def test_shell_operators_and_bare_env_expansion_are_rejected(self) -> None:
        # The runner is `/bin/sh -lc`: any chaining/redirection operator or
        # unsanctioned bare `$VAR` sidesteps the command and option allowlists.
        operator_probes = (
            "; /bin/echo pwned",
            " && /bin/echo pwned",
            " | /bin/cat",
            " > /tmp/pwned",
            " &",
            " < /etc/passwd",
        )
        for payload in operator_probes:
            with self.subTest(payload=payload):
                codes = self.validate(
                    "name: fixture\nsteps:\n  - id: bad\n"
                    f"    run: '/workspaces/vc-chief/vc/bin/agent/vcops preflight{payload}'\n"
                    "    timeout_ms: 1000\n"
                )
                self.assertIn("shell_operator", codes)
        # A newline terminates a command exactly as `;` does, and YAML offers
        # three ways to put one inside `run:` — a literal block, an escape in a
        # double-quoted scalar, and a more-indented line inside the folded
        # style the shipped workflows use. shlex treats all three as ordinary
        # whitespace, so only an explicit check catches them.
        newline_probes = (
            "    run: |\n      /workspaces/vc-chief/vc/bin/agent/vcops preflight\n      /bin/echo pwned\n",
            '    run: "/workspaces/vc-chief/vc/bin/agent/vcops preflight\\n/bin/echo pwned"\n',
            '    run: "/workspaces/vc-chief/vc/bin/agent/vcops preflight\\r/bin/echo pwned"\n',
            "    run: >-\n      /workspaces/vc-chief/vc/bin/agent/vcops preflight\n       /bin/echo pwned\n",
        )
        for payload in newline_probes:
            with self.subTest(payload=payload):
                codes = self.validate("name: fixture\nsteps:\n  - id: bad\n" + payload + "    timeout_ms: 1000\n")
                self.assertIn("shell_operator", codes)
        bare_env = self.validate(
            "name: fixture\nsteps:\n  - id: bad\n"
            "    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id \"$HOME\"'\n"
            "    timeout_ms: 1000\n"
        )
        self.assertIn("raw_env", bare_env)
        sanctioned = self.validate(
            "name: fixture\nargs:\n  lead_id: {default: ''}\nsteps:\n"
            "  - id: ok\n    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id \"$LOBSTER_ARG_LEAD_ID\"'\n"
            "    timeout_ms: 1000\n"
        )
        self.assertNotIn("raw_env", sanctioned)
        self.assertNotIn("shell_operator", sanctioned)
        # The shell cannot act on a metacharacter inside quotes, so rejecting
        # one would block ordinary reviewed arguments (a company name carrying
        # an ampersand, a threshold phrased with `>`).
        quoted_literal = self.validate(
            "name: fixture\nsteps:\n  - id: ok\n"
            "    run: '/workspaces/vc-chief/vc/bin/agent/vcops company-upsert --name \"Ben & Co\" --metadata {}'\n"
            "    timeout_ms: 1000\n"
        )
        self.assertNotIn("shell_operator", quoted_literal)
        self.assertNotIn("raw_env", quoted_literal)

    def test_release_workflows_have_no_static_findings(self) -> None:
        for path in sorted(g5.WORKFLOWS.glob("*.lobster")):
            with self.subTest(path=path.name):
                findings, _ = g5.validate_workflow(path, self.parser)
                self.assertEqual([], [item.as_dict() for item in findings])


if __name__ == "__main__":
    unittest.main()
