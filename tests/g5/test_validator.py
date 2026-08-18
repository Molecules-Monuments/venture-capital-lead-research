# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = PACKAGE / "scripts/validate_workflows.py"

# The reviewed workflow-lane wrapper allowlist, written out here INDEPENDENTLY of
# the validator. `validate_workflows.WRAPPERS` is `frozenset(WRAPPER_COMMAND_SETS)`,
# so comparing it against `_wrapper_command_sets()` compares the key set of one
# dict with the key set of the same dict and cannot fail. Measured: with that as
# the only scope check, adding `/workspaces/vc-chief/vc/bin/vcops-operator` to
# WRAPPER_COMMAND_SETS passed the ENTIRE offline matrix with zero new failures,
# and the validator then certified the operator lane inside a workflow — a
# wrapper whose own header says "This path is for direct operator use and must
# never appear in exec approvals".
#
# Admitting an executable to the workflow lane is a reviewed change. Editing this
# set is how that review is recorded; if a genuine third wrapper is added, this
# line changes in the same commit as the validator.
REVIEWED_WORKFLOW_WRAPPERS = frozenset({
    "/workspaces/vc-chief/vc/bin/agent/vcops",
    "/workspaces/vc-chief/vc/bin/vcops-workflow",
})
# Must never be admitted: it sets VCOPS_OPERATOR_MODE=1.
OPERATOR_ONLY_WRAPPER = "/workspaces/vc-chief/vc/bin/vcops-operator"
SPEC = importlib.util.spec_from_file_location("validate_g5_tests", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
g5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = g5
SPEC.loader.exec_module(g5)

# The gate step runs two validators, each with its own strict mapping
# constructor. Load the second one too: its guards are otherwise exercised by
# nothing in tests/, so a refactor that drops one passes the whole offline gate.
SKILLS_VALIDATOR_PATH = PACKAGE / "scripts/validate_skill_system.py"
SKILLS_SPEC = importlib.util.spec_from_file_location(
    "validate_skill_system_g5_tests", SKILLS_VALIDATOR_PATH
)
assert SKILLS_SPEC is not None and SKILLS_SPEC.loader is not None
skills = importlib.util.module_from_spec(SKILLS_SPEC)
sys.modules[SKILLS_SPEC.name] = skills
SKILLS_SPEC.loader.exec_module(skills)

# Load the reviewed runtime module independently of the validator, the same way
# tests/g5/test_vcrun.py loads it for PREFERENCE_VALUES. The wrapper-scope test
# below claims the validator derives its per-wrapper command sets from vcops;
# reading those sets back through the validator alone compared the derivation
# with itself. Measured: replacing the derivation with a set carrying two extra
# operator-lane commands (`fact-add`, `source-add`) moved both sides of every
# comparison together, the whole file still reported `Ran 18 tests ... OK`, and
# the mutant validator certified `vcops-workflow fact-add` with zero findings.
VCOPS_SPEC = importlib.util.spec_from_file_location(
    "vcops_g5_validator_tests", PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
)
assert VCOPS_SPEC is not None and VCOPS_SPEC.loader is not None
vcops = importlib.util.module_from_spec(VCOPS_SPEC)
VCOPS_SPEC.loader.exec_module(vcops)


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

    def wrapper_step(self, wrapper: str, command: str) -> set[str]:
        """Validate a one-step workflow whose only step runs `wrapper command`."""
        return self.validate(
            f"name: fixture\nsteps:\n  - id: probe\n    run: {wrapper} {command}\n    timeout_ms: 1000\n"
        )

    def test_wrapper_scope_is_derived_from_the_runtime_command_sets(self) -> None:
        """`command_wrapper_scope` must cover exactly what the wrapper's mode refuses.

        Each wrapper `exec`s vcops with one mode flag, and vcops refuses any
        command outside that mode's own set. The parser-wide subcommand
        inventory is therefore not the world a workflow step can reach:
        validating against the parser alone accepted every command in the gap
        between the two, `data-erase-lead` included. Assert the covered set by
        identity against the runtime's own sets rather than spot-checking
        members, so a command that later moves between the sets — or a
        derivation quietly replaced by a hardcoded list — fails here. The
        second half of that claim rests entirely on the vcops identity check
        inside the loop: without it both sides of the enforcement comparison
        are read from the validator and drift together.
        """
        parser_commands = set(g5._command_parsers(self.parser))
        permitted = g5._wrapper_command_sets()
        # SCOPE. Which executables may appear in a workflow step at all, against
        # an independent literal. `WRAPPERS` is derived from
        # `WRAPPER_COMMAND_SETS`, so the derivation check below cannot answer this
        # question: both of its sides are the key set of the same dict.
        self.assertEqual(
            REVIEWED_WORKFLOW_WRAPPERS, frozenset(g5.WRAPPERS),
            "the workflow-lane wrapper allowlist changed. Admitting an executable "
            "here lets a workflow step run it under the reviewed lane, so it is a "
            "reviewed change: update REVIEWED_WORKFLOW_WRAPPERS in the same commit, "
            "and never admit the operator wrapper, which sets VCOPS_OPERATOR_MODE=1",
        )
        self.assertNotIn(
            OPERATOR_ONLY_WRAPPER, g5.WRAPPERS,
            "the operator wrapper must never be reachable from a workflow step",
        )
        for wrapper in sorted(REVIEWED_WORKFLOW_WRAPPERS | {OPERATOR_ONLY_WRAPPER}):
            # Every path named above must be a shipped executable, so this test
            # cannot be satisfied by a literal that no longer exists.
            shipped = PACKAGE / wrapper.lstrip("/")
            self.assertTrue(shipped.is_file(), f"{wrapper} is not a shipped file")
            self.assertTrue(
                shipped.stat().st_mode & 0o111, f"{wrapper} is not executable"
            )
        # DERIVATION. Each admitted wrapper must resolve to a runtime command set.
        # This is a real check of `_wrapper_command_sets()`'s completeness over the
        # mapping, and it is NOT a scope check; keep both.
        self.assertEqual(
            set(permitted), set(g5.WRAPPERS),
            "every reviewed wrapper must resolve to a runtime command set",
        )
        for wrapper in sorted(permitted):
            attribute = g5.WRAPPER_COMMAND_SETS[wrapper]
            # Pin the derivation to vcops before using it. `outside` and
            # `fired` below are both computed from `permitted`, so a validator
            # that answered from a stale hardcoded copy moved both sides
            # together and still balanced -- this assertion is the only thing
            # in the test that the runtime, rather than the validator, decides.
            # assertEqual on two frozensets dispatches to assertSetEqual, which
            # reports only the differing members, not both whole sets.
            # Name a rename before comparing: with the attribute gone the
            # comparison would be against the empty set and would print all
            # thirty-odd command names instead of the one fact that matters.
            self.assertTrue(
                hasattr(vcops, attribute),
                f"vcops no longer defines {attribute}, the set {wrapper}'s "
                "wrapper-scope rule is derived from",
            )
            runtime_set = frozenset(getattr(vcops, attribute, ()))
            self.assertEqual(
                permitted[wrapper], runtime_set,
                f"{wrapper}'s accepted command set is no longer vcops.{attribute} "
                "itself; the validator gates the workflow lane against a set the "
                "runtime does not enforce",
            )
            outside = parser_commands - permitted[wrapper]
            self.assertTrue(
                outside,
                f"vcops.{attribute} covers the whole parser, so this test would "
                f"prove nothing about {wrapper}",
            )
            fired = {
                command
                for command in sorted(parser_commands)
                if "command_wrapper_scope" in self.wrapper_step(wrapper, command)
            }
            uncovered = sorted(outside - fired)
            over_reached = sorted(fired - outside)
            self.assertFalse(
                bool(uncovered),
                f"{wrapper} accepted {uncovered}, which vcops.{attribute} does not "
                "permit and the runtime refuses",
            )
            self.assertFalse(
                bool(over_reached),
                f"{wrapper} rejected {over_reached}, which vcops.{attribute} permits",
            )

    def test_operator_lane_commands_are_rejected_in_the_workflow_lane(self) -> None:
        """Named exemplars of each gap set, plus a positive control per wrapper."""
        parser_commands = set(g5._command_parsers(self.parser))
        permitted = g5._wrapper_command_sets()
        agent = "/workspaces/vc-chief/vc/bin/agent/vcops"
        workflow = "/workspaces/vc-chief/vc/bin/vcops-workflow"
        for wrapper, command in ((workflow, "data-erase-lead"), (agent, "workflow-start")):
            with self.subTest(wrapper=wrapper, command=command):
                self.assertTrue(
                    command in parser_commands,
                    f"the probe no longer names a vcops command: {command}",
                )
                self.assertFalse(
                    command in permitted[wrapper],
                    f"{command} is now inside {g5.WRAPPER_COMMAND_SETS[wrapper]}, so this "
                    "probe no longer exercises the wrapper-scope rule",
                )
                self.assertIn(
                    "command_wrapper_scope", self.wrapper_step(wrapper, command),
                    f"{wrapper} {command} is refused by vcops at runtime, so the gate must "
                    "not certify a workflow that contains it",
                )
        for wrapper, command in ((workflow, "source-scan"), (agent, "lead-show")):
            with self.subTest(wrapper=wrapper, command=command):
                self.assertTrue(
                    command in permitted[wrapper],
                    f"the positive control no longer names a command {wrapper} permits: {command}",
                )
                self.assertNotIn(
                    "command_wrapper_scope", self.wrapper_step(wrapper, command),
                    f"{wrapper} {command} is inside the wrapper's own command set and must pass",
                )

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
        # The rule this replaced tested only the byte immediately before `$`,
        # so a quote character anywhere in front of the expansion satisfied it.
        # Verified against that rule: all four spellings below are accepted by
        # it and flagged by the current one, which decides on the command's
        # double-quote state instead. They run as subTests so a regression
        # reports each spelling rather than stopping at the first. The four are
        # not one failure mode: `""$X`, `"p"$X` and `"a"$X"b"` leave the
        # expansion unquoted, so `sh` word-splits and globs the
        # channel-controlled value, while `'$X'` is not expanded at all and the
        # helper receives the literal reference text as a lead id. Neither
        # delivers the value intact, and
        # docs/TASKFLOW_LOBSTER_COMPATIBILITY.md tells authors to double-quote.
        for spelling in ("'$VCOPS_SENDER_ID'", '""$VCOPS_SENDER_ID',
                         '"p"$VCOPS_SENDER_ID', '"a"$VCOPS_SENDER_ID"b"'):
            with self.subTest(spelling=spelling):
                # The shell spelling is carried inside a YAML double-quoted
                # scalar, so its own quotes are escaped for YAML; the validator
                # sees the unescaped shell text.
                escaped = spelling.replace('"', '\\"')
                codes = self.validate(
                    'name: fixture\nsteps:\n'
                    '  - id: bad\n    run: "/workspaces/vc-chief/vc/bin/agent/vcops lead-show'
                    f' --lead-id {escaped}"\n    timeout_ms: 1000\n'
                )
                self.assertNotIn(
                    "yaml_parse", codes,
                    f"the fixture for {spelling} did not parse, so the quoting rule "
                    "was never exercised",
                )
                self.assertIn(
                    "arg_unquoted", codes,
                    f"{spelling} leaves the expansion outside a double-quoted "
                    "region: `sh` either word-splits and globs the "
                    "channel-controlled value or, inside single quotes, does not "
                    "expand it at all and passes the literal reference text on. "
                    "Neither delivers the value intact",
                )
        # Positive control: the spelling the documentation tells authors to use
        # must not be flagged, or the rule is unusable.
        self.assertNotIn(
            "arg_unquoted",
            self.validate(
                'name: fixture\nsteps:\n'
                '  - id: ok\n    run: "/workspaces/vc-chief/vc/bin/agent/vcops lead-show'
                ' --lead-id \\"$VCOPS_SENDER_ID\\""\n    timeout_ms: 1000\n'
            ),
            "the documented fully-quoted spelling must pass the quoting rule",
        )

    def test_unhashable_yaml_key_is_a_finding_not_a_traceback(self) -> None:
        # `? [a, b]` is legal YAML whose key is a list. This validator's strict
        # mapping constructor replaces SafeConstructor's, so without its own
        # Hashable check (scripts/validate_workflows.py:107) the gate step
        # aborts with a traceback that never names the file. The gate's second
        # validator carries the same guard for the same reason and is covered
        # by SkillSystemValidatorTests below, not by this method — `validate()`
        # drives scripts/validate_workflows.py alone.
        self.assertIn(
            "yaml_parse",
            self.validate(
                "name: fixture\n? [a, b]\n: c\nsteps:\n  - id: ok\n"
                "    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n    timeout_ms: 1000\n"
            ),
        )

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

    def test_execution_influencing_step_env_keys_are_rejected(self) -> None:
        """Approving the `run:` text does not approve the executable that runs it.

        The pinned runtime resolves the inline shell from the step environment,
        so `LOBSTER_SHELL` demotes the validated command to an argument of an
        arbitrary binary — measured on openclaw-lead-research:3.0.0, a step
        with `LOBSTER_SHELL: /bin/echo` ran echo and never invoked
        `vcops-workflow`, while the run still reported `ok: true`. The
        validator must therefore constrain env KEY names, not just values, or
        the G5 "steps invoke only the exact immutable vcops path" claim is
        about the command text rather than the invocation.
        """
        step = (
            "name: fixture\nsteps:\n  - id: bad\n    env:\n      {key}: {value}\n"
            "    run: /workspaces/vc-chief/vc/bin/vcops-workflow preflight\n"
            "    timeout_ms: 1000\n"
        )
        for key, value in (
            ("LOBSTER_SHELL", "/bin/echo"),
            ("PATH", "/tmp/evil:/usr/bin"),
            ("IFS", "x"),
            ("LD_PRELOAD", "/tmp/evil.so"),
            ("ComSpec", "cmd.exe"),
            # A key that satisfies an anchored PREFIX match but not a full
            # one, so relaxing the rule to re.match — which every other probe
            # here survives — fails this test instead of passing silently.
            ("VCOPS_X-LOBSTER_SHELL", "/bin/echo"),
        ):
            with self.subTest(env_key=key):
                self.assertIn("env_key", self.validate(step.format(key=key, value=value)))
        # The reviewed namespace every shipped workflow uses still passes.
        self.assertNotIn(
            "env_key",
            self.validate(step.format(key="VCOPS_LEAD_ID", value="'123'")),
        )

    def test_step_references_are_rejected_in_run_text(self) -> None:
        """Quoting contains `$VCOPS_*`; it cannot contain a direct step reference.

        Lobster sets `env:` entries as real environment variables, so `sh` does
        not re-parse a double-quoted expansion of one — which is why the
        `arg_unquoted` rule is sufficient for `$VCOPS_*`/`$LOBSTER_ARG_*`. A
        direct `$step.json.path` reference is different in kind: it is
        substituted textually into the command string before the shell runs, so
        a channel-controlled value containing a double quote escapes its own
        quotes and injects. Both spellings carry the same value — the unquoted
        step-env form is rejected as `arg_unquoted`, so the direct form must be
        rejected too or the value simply moves to the uncovered surface.
        """
        step = (
            "name: fixture\nsteps:\n"
            "  - id: claim\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n"
            "    timeout_ms: 1000\n"
            "  - id: use\n    run: {command}\n    timeout_ms: 1000\n"
        )
        for command in (
            # Unquoted, quoted, and inside a larger string: textual substitution
            # makes all three injectable, so none may pass.
            "/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id $claim.json.lead.id",
            "'/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id \"$claim.json.lead.id\"'",
            "'/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id prefix-$claim.json.lead.id'",
        ):
            with self.subTest(command=command):
                self.assertIn("step_ref_in_command", self.validate(step.format(command=command)))
        # The sanctioned carrier — a quoted VCOPS_ step-env value — still passes.
        self.assertNotIn(
            "step_ref_in_command",
            self.validate(
                "name: fixture\nsteps:\n"
                "  - id: claim\n    run: /workspaces/vc-chief/vc/bin/agent/vcops preflight\n"
                "    timeout_ms: 1000\n"
                "  - id: use\n    env:\n      VCOPS_LEAD_ID: '$claim.json.lead.id'\n"
                "    run: '/workspaces/vc-chief/vc/bin/agent/vcops lead-show --lead-id \"$VCOPS_LEAD_ID\"'\n"
                "    timeout_ms: 1000\n"
            ),
        )

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

    def test_pathname_and_tilde_expansion_are_rejected(self) -> None:
        """Word expansions the operator and `$VAR` scans both miss.

        Glob is the sharper of the two because it changes the argv WORD COUNT
        rather than a word's value: `--path "$LOBSTER_ARG_DOCUMENT_PATH"*` puts
        the reference inside a double-quoted region, so `arg_unquoted` certifies
        it as unsplittable, and the trailing unquoted `*` hands the whole word
        back to pathname expansion anyway. Tilde is the same class one step
        earlier: `sh` rewrites `~/x.pdf` to a home directory before vcops sees
        argv. Both are inert inside either quote style, so the rules scan
        shell-active text and an ordinary quoted argument stays usable.
        """
        workflow = "/workspaces/vc-chief/vc/bin/vcops-workflow"
        step = "name: fixture\nsteps:\n  - id: probe\n    run: '{command}'\n    timeout_ms: 1000\n"
        for command, code in (
            (f"{workflow} document-preview --path /inbox/*", "glob_expansion"),
            (f'{workflow} document-preview --path "$LOBSTER_ARG_DOCUMENT_PATH"*', "glob_expansion"),
            (f"{workflow} document-preview --path /inbox/report?.pdf", "glob_expansion"),
            (f"{workflow} document-preview --path /inbox/[a-z].pdf", "glob_expansion"),
            (f"{workflow} document-preview --path ~/x.pdf", "tilde_expansion"),
            (f"{workflow} document-preview --path ~node/x.pdf", "tilde_expansion"),
        ):
            with self.subTest(command=command):
                codes = self.validate(step.format(command=command))
                self.assertNotIn(
                    "yaml_parse", codes,
                    f"the fixture for {command} did not parse, so the rule was never exercised",
                )
                self.assertIn(
                    code, codes,
                    f"the shell expands this word before vcops sees argv: {command}",
                )
        # Positive controls. The first is the spelling every shipped `--path`
        # step uses; the second is an ordinary reviewed argument whose `*` and
        # `~` are quoted literals the shell cannot act on. Either being flagged
        # makes the rules unusable, which is how a rule gets widened away. The
        # second is written with the `~` preceded by a space inside the quotes
        # on purpose: a rule that scanned the raw command text instead of the
        # shell-active text would pass a control spelled `"~a.example"`, whose
        # preceding byte is a quote, and fail only on this one.
        for command in (
            f'{workflow} document-preview --path "$LOBSTER_ARG_DOCUMENT_PATH"',
            f'{workflow} company-upsert --name "A*B ~ C"',
        ):
            with self.subTest(command=command):
                codes = self.validate(step.format(command=command))
                self.assertNotIn(
                    "yaml_parse", codes,
                    f"the fixture for {command} did not parse, so the control proves nothing",
                )
                self.assertNotIn("glob_expansion", codes, f"quoted text cannot glob: {command}")
                self.assertNotIn("tilde_expansion", codes, f"quoted text cannot tilde-expand: {command}")

    def test_release_workflows_have_no_static_findings(self) -> None:
        for path in sorted(g5.WORKFLOWS.glob("*.lobster")):
            with self.subTest(path=path.name):
                findings, _ = g5.validate_workflow(path, self.parser)
                self.assertEqual([], [item.as_dict() for item in findings])


class SkillSystemValidatorTests(unittest.TestCase):
    """The `skill-agent-system` gate step's own loader guards.

    `WorkflowValidatorTests.validate` drives scripts/validate_workflows.py only,
    so scripts/validate_skill_system.py's identical strict mapping constructor
    was reachable from no test: deleting its Hashable guard left every offline
    suite green and the gate step exiting 0.
    """

    def parse_skill_frontmatter(self, frontmatter: str) -> list[Any]:
        """Run `parse_skill` over a temp SKILL.md and return its findings.

        `add()` reports paths through `relative()`, which is anchored to the
        module's `PACKAGE`, so the fixture root is patched in rather than
        written into the package tree.
        """
        findings: list[Any] = []
        with tempfile.TemporaryDirectory(prefix="g5-skill-") as temp:
            root = Path(temp)
            path = root / "workspaces/shared-skills/fixture/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8")
            with mock.patch.object(skills, "PACKAGE", root):
                try:
                    skills.parse_skill(path, findings)
                except (TypeError, skills.DuplicateKeyError) as exc:
                    self.fail(
                        f"parse_skill let {type(exc).__name__}: {exc} escape its "
                        "`except (yaml.YAMLError, DuplicateKeyError)` handler. A key "
                        "this loader refuses has to surface as one of those two "
                        "types; otherwise the skill-agent-system gate step aborts "
                        "with a traceback that never names the offending file."
                    )
        return findings

    def test_unhashable_yaml_key_is_a_bounded_finding_not_a_traceback(self) -> None:
        # `? [a, b]` is legal YAML whose key is a list. Replacing
        # SafeConstructor.construct_mapping drops its Hashable check, and the
        # `key in result` lookup then raises TypeError from outside every
        # handler in the module.
        findings = self.parse_skill_frontmatter("name: fixture\n? [a, b]\n: c")
        codes = [item.code for item in findings]
        self.assertEqual(
            codes, ["skill_frontmatter"],
            "a complex YAML key must stop parse_skill at one bounded "
            f"skill_frontmatter finding; it reported {findings}",
        )
        self.assertEqual(
            findings[0].path,
            "workspaces/shared-skills/fixture/SKILL.md",
            "the finding must name the offending file",
        )
        self.assertIn("found unhashable key", findings[0].message)

    def test_duplicate_yaml_key_in_frontmatter_is_a_bounded_finding(self) -> None:
        # The same constructor's other guard. SafeConstructor merges duplicate
        # keys last-one-wins; this loader refuses them, and the refusal has to
        # reach the same handler rather than escaping as DuplicateKeyError.
        findings = self.parse_skill_frontmatter("name: fixture\nname: replacement")
        codes = [item.code for item in findings]
        self.assertIn(
            "skill_frontmatter", codes,
            "scripts/validate_skill_system.py did not reject a duplicated "
            f"frontmatter key as skill_frontmatter; it reported {findings}",
        )
        self.assertIn(
            "duplicate YAML key: name",
            next(item.message for item in findings if item.code == "skill_frontmatter"),
        )


if __name__ == "__main__":
    unittest.main()
