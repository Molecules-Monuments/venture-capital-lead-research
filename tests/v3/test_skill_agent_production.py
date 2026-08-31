# SPDX-License-Identifier: Apache-2.0
"""Skill self-modification must stop at a proposal an operator has to release.

The Skill Workshop lets this system draft skills for itself, which is only
safe while the line between drafting and installing holds. Three independent
layers hold it, and each is checked here because any one of them can be edited
away on its own: `config/openclaw.json` grants `skill_workshop` to `vc-chief`
and denies it to every other agent and to subagents outright; the
`before_tool_call` hook in `runtime-extensions/vc-trusted-context/index.js`
blocks the lifecycle actions (`apply`, `reject`, `quarantine`), blocks a
worker agent that reaches for the tool anyway, and blocks an action it does
not recognise, so an action added upstream arrives denied rather than
permitted; and the meta-skills' own prose has to say what the artifact they
produce really is — pending, not installed — because that prose is what the
agent reads. Autonomous transcript review stays off and the approval policy
stays `pending` alongside them.

`scripts/validate_skill_system.py` is the offline gate step that enumerates
the shipped inventory, and the first test requires it to answer PASS with no
findings over 26 skills, 12 agents and 18 workflows.

Its report envelope is what the last two tests defend. `main()` installs no
exception handler by design, so a read that raises escapes before anything is
printed and takes every finding already collected with it: the operator sees a
traceback and zero JSON, and `verify_offline.py`'s `skill-agent-system` step
fails with nothing to act on. One test corrupts each governed artifact in turn
and demands a parseable FAIL envelope that still carries findings; the other
enumerates every read site from the validator's AST, because a representative
sample cannot prove there is no unguarded read left. Both are enumerations
rather than spot checks for a reason their own docstrings record: the claim
that no unguarded read remained has been wrong twice.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = ROOT / "runtime-extensions/vc-trusted-context/index.js"


class SkillAgentProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))

    def test_production_validator_passes_complete_inventory(self) -> None:
        process = subprocess.run(
            [sys.executable, "-B", str(ROOT / "scripts/validate_skill_system.py")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("PASS", report["result"])
        self.assertEqual((26, 12, 18), (report["skills"], report["agents"], report["workflows"]))
        self.assertEqual([], report["findings"])

    def test_workshop_authority_is_exactly_one_guarded_chief(self) -> None:
        allowed = {
            agent["id"]
            for agent in self.config["agents"]["list"]
            if "skill_workshop" in agent["tools"]["allow"]
        }
        denied = {
            agent["id"]
            for agent in self.config["agents"]["list"]
            if "skill_workshop" in agent["tools"]["deny"]
        }
        self.assertEqual({"vc-chief"}, allowed)
        self.assertEqual(
            {agent["id"] for agent in self.config["agents"]["list"]} - {"vc-chief"},
            denied,
        )
        self.assertNotIn("skill_workshop", self.config["tools"]["deny"])
        self.assertIn("skill_workshop", self.config["tools"]["alsoAllow"])
        self.assertIn("skill_workshop", self.config["tools"]["subagents"]["tools"]["deny"])

    def test_workshop_hook_allows_pending_actions_and_blocks_lifecycle(self) -> None:
        script = f"""
import plugin from {json.dumps(PLUGIN_PATH.as_uri())};
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
const invoke = (action, agentId = 'vc-chief') =>
  hooks.before_tool_call({{toolName: 'skill_workshop', params: {{action}}}}, {{agentId}}) ?? null;
const output = {{
  create: invoke('create'), update: invoke('update'), revise: invoke('revise'),
  list: invoke('list'), inspect: invoke('inspect'), apply: invoke('apply'),
  reject: invoke('reject'), quarantine: invoke('quarantine'), unknown: invoke('future-action'),
  worker: invoke('create', 'memo-writer'), unrelated: hooks.before_tool_call(
    {{toolName: 'read', params: {{path: 'x'}}}}, {{agentId: 'vc-chief'}}
  ) ?? null,
}};
console.log(JSON.stringify(output));
"""
        process = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=os.environ.copy(),
        )
        self.assertEqual(0, process.returncode, process.stderr)
        output = json.loads(process.stdout)
        for action in ("create", "update", "revise", "list", "inspect"):
            self.assertIsNone(output[action], action)
        for action in ("apply", "reject", "quarantine", "unknown", "worker"):
            self.assertTrue(output[action]["block"], action)
        self.assertIn("operator-controlled repository release", output["apply"]["blockReason"])
        self.assertIn("restricted to the VC Chief", output["worker"]["blockReason"])
        self.assertIsNone(output["unrelated"])

    def test_skillify_creates_complete_pending_artifact_not_hot_install(self) -> None:
        body = (ROOT / "workspaces/shared-skills/skillify/SKILL.md").read_text(encoding="utf-8")
        for marker in (
            "action=create",
            "full `proposal_content`",
            "status is `pending`",
            "pending_operator_release",
            "official `skill-creator` validator",
            "release-manifest update",
            "Never claim that a pending proposal is active",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_autonomous_transcript_review_remains_disabled(self) -> None:
        workshop = self.config["skills"]["workshop"]
        self.assertEqual({"mode": "off"}, workshop["autonomous"])
        self.assertEqual("pending", workshop["approvalPolicy"])
        self.assertFalse(workshop["allowSymlinkTargetWrites"])

    def test_meta_skills_state_their_actual_production_side_effect(self) -> None:
        expectations = {
            "schema-proposal": "Never apply migrations",
            "source-improvement": "proposal",
            "controlled-evolution": "pending Workshop artifact",
            "skillify": "Skill Workshop artifact",
        }
        for skill, marker in expectations.items():
            body = (ROOT / f"workspaces/shared-skills/{skill}/SKILL.md").read_text(encoding="utf-8")
            with self.subTest(skill=skill):
                self.assertIn(marker.lower(), body.lower())

    def test_every_governed_read_records_a_finding_instead_of_raising(self) -> None:
        """A non-UTF-8 governed artifact must still produce a JSON envelope.

        `scripts/validate_skill_system.py` main() installs no exception handler by
        design, so a read that raises escapes before the report is printed and
        takes every finding the run had already collected with it. The operator
        sees a traceback and zero JSON, and `verify_offline.py`'s
        `skill-agent-system` step fails with nothing to act on.

        The claim that no such read remains has now been wrong twice. Round 1 of
        the eighteenth pass fixed two reads and its docstring asserted there was
        no sixth; a sixth existed. Measured on `config/exec-approvals.json`, whose
        handler named `json.JSONDecodeError` but not `UnicodeError` — the two are
        sibling `ValueError` subclasses, so the JSON error does not catch a decode
        error — two invalid bytes produced exit 1 with **zero bytes of stdout**.

        Enumerating the governed artifacts and corrupting each in turn is the only
        assertion that makes the docstring's rule enforceable rather than stated.
        """
        validator = ROOT / "scripts/validate_skill_system.py"
        with tempfile.TemporaryDirectory(prefix="v3-governed-reads-") as raw:
            package = Path(raw) / "pkg"
            shutil.copytree(
                ROOT, package,
                ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "_internal"),
            )
            # Derived from the validator's own module-level constants, not
            # hand-listed, plus one representative of each globbed family it
            # reads. A hand-written list here would reproduce the same
            # "no sixth read" fallacy this test exists to prevent; the static
            # companion test below is what proves the families are complete.
            source = validator.read_text(encoding="utf-8")
            constants = {
                name: value
                for name, value in (
                    ("CONFIG_PATH", "config/openclaw.json"),
                    ("RESOLVER_PATH", "workspaces/vc-chief/vc/RESOLVER.md"),
                    ("HOOK_PATH", "runtime-extensions/vc-trusted-context/index.js"),
                    ("VCRUN_PATH", "workspaces/vc-chief/vc/bin/vcrun.py"),
                )
                if f'{name} = PACKAGE / "{value}"' in source
            }
            self.assertEqual(
                4, len(constants),
                "the validator's governed-path constants moved; this test is "
                f"pinned to their spelling and found only {sorted(constants)}",
            )
            governed = [Path(value) for value in constants.values()]
            governed.append(Path("config/exec-approvals.json"))
            governed.append(Path("workspaces/schemas/lead-router.output.schema.json"))
            for pattern in ("workspaces/**/SKILL.md", "workspaces/*/AGENTS.md",
                            "workspaces/*/TOOLS.md",
                            "workspaces/vc-chief/vc/workflows/*.lobster"):
                matches = sorted(package.glob(pattern))
                self.assertTrue(matches, f"no governed artifact matched {pattern}")
                governed.append(matches[0].relative_to(package))

            for relative in governed:
                with self.subTest(governed=relative.as_posix()):
                    target = package / relative
                    self.assertTrue(target.is_file(), f"{relative} is not a file")
                    original = target.read_bytes()
                    # Inject AFTER the first line, never at a fixed byte offset.
                    # Offset 10 lands inside the shebang of a governed .py, and
                    # CPython exempts the FIRST LINE only: measured, invalid UTF-8
                    # there imports cleanly on 3.11, 3.12 and 3.13 and raises only
                    # on 3.14+. This suite ran on a 3.14 developer venv and passed
                    # while failing on the 3.11 floor the package deploys to, so
                    # `verify_offline.py` could not pass on its own documented
                    # platform. One newline further in, every supported version
                    # rejects the file, and a text read still raises
                    # UnicodeDecodeError wherever the bytes land.
                    head, newline, rest = original.partition(b"\n")
                    self.assertTrue(
                        newline,
                        f"{relative} has no newline, so there is no position that "
                        f"is invalid on every supported CPython",
                    )
                    target.write_bytes(head + newline + b"\xff\xfe" + rest)
                    try:
                        done = subprocess.run(
                            [sys.executable, "-B", str(package / "scripts/validate_skill_system.py")],
                            cwd=package, text=True, capture_output=True, timeout=300, check=False,
                        )
                    finally:
                        target.write_bytes(original)
                    self.assertTrue(
                        done.stdout.strip(),
                        f"a non-UTF-8 {relative} produced NO stdout, so the JSON "
                        f"report and every finding collected before it were lost: "
                        f"{done.stderr[-600:]}",
                    )
                    try:
                        report = json.loads(done.stdout)
                    except json.JSONDecodeError as exc:
                        self.fail(
                            f"a non-UTF-8 {relative} produced unparseable stdout "
                            f"({exc}): {done.stdout[:400]}"
                        )
                    self.assertEqual(
                        "FAIL", report.get("result"),
                        f"a non-UTF-8 {relative} was not reported as a failure: {report}",
                    )
                    self.assertTrue(
                        report.get("findings"),
                        f"a non-UTF-8 {relative} produced an empty-but-parseable "
                        f"envelope, which would pass a stdout-only assertion while "
                        f"reporting nothing: {report}",
                    )

    def test_no_read_in_the_skill_validator_can_escape_main(self) -> None:
        """Static companion: every read site is guarded, derived from the source.

        The dynamic test above corrupts a representative of each governed family.
        This one closes the gap that representation leaves: it enumerates EVERY
        read call in the validator from its AST and requires each to sit inside a
        `try` whose handlers catch a decode error — or, where the read lives in a
        helper, requires every call site of that helper to be so guarded (which
        is how `documented_tools` is legitimately protected).

        `UnicodeError` or `ValueError` both qualify; `json.JSONDecodeError` alone
        does not, because it is a sibling of `UnicodeDecodeError` rather than an
        ancestor. That distinction is precisely the defect this closes.
        """
        source = (ROOT / "scripts/validate_skill_system.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        catches_decode = {"UnicodeError", "UnicodeDecodeError", "ValueError", "Exception"}

        def handler_names(node: ast.Try) -> set[str]:
            names: set[str] = set()
            for handler in node.handlers:
                if handler.type is None:
                    names.add("Exception")
                for sub in ast.walk(handler.type) if handler.type else ():
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
                    elif isinstance(sub, ast.Attribute):
                        names.add(sub.attr)
            return names

        # Walk with an explicit ancestor stack: a read is guarded only by a `try`
        # that encloses it inside the SAME function, so a caller's try must not be
        # credited to a helper's body.
        reads: list[tuple[str, int, bool]] = []          # (function, line, guarded)
        functions: dict[str, ast.FunctionDef] = {}

        def visit(node: ast.AST, function: str | None, tries: tuple[set[str], ...]) -> None:
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = node
                function, tries = node.name, ()
            if isinstance(node, ast.Try):
                names = handler_names(node)
                for child in node.body:
                    visit(child, function, (*tries, names))
                for other in (*node.handlers, *node.orelse, *node.finalbody):
                    visit(other, function, tries)
                return
            if isinstance(node, ast.Call):
                target = node.func
                name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                if name in {"read_text", "read_bytes", "open"}:
                    guarded = any(names & catches_decode for names in tries)
                    reads.append((function or "<module>", node.lineno, guarded))
            for child in ast.iter_child_nodes(node):
                visit(child, function, tries)

        visit(tree, None, ())
        self.assertGreaterEqual(
            len(reads), 8,
            f"only {len(reads)} read sites found; the AST walk is not seeing them",
        )
        # No name is exempt, `read_body` included. Exempting the sanctioned
        # wrapper by name was a hole: with its own `except (OSError,
        # UnicodeError)` removed it would have been filtered out of this set and
        # the check would have passed. It does not need an exemption — its read is
        # inside a qualifying `try`, so it never enters this set while it is
        # correct, and it must enter it the moment it stops being.
        raising = sorted({function for function, _, guarded in reads if not guarded})

        # Defined once, outside the loop: a closure over the loop variable would
        # capture its final value (ruff B023) and every helper would be checked
        # against the same name.
        def call_sites_of(wanted: str) -> list[tuple[int, bool]]:
            sink: list[tuple[int, bool]] = []

            def walk(node: ast.AST, tries: tuple[set[str], ...]) -> None:
                if isinstance(node, ast.Try):
                    names = handler_names(node)
                    for child in node.body:
                        walk(child, (*tries, names))
                    for other in (*node.handlers, *node.orelse, *node.finalbody):
                        walk(other, tries)
                    return
                if isinstance(node, ast.Call):
                    target = node.func
                    name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
                    if name == wanted:
                        sink.append((node.lineno, any(n & catches_decode for n in tries)))
                for child in ast.iter_child_nodes(node):
                    walk(child, tries)

            walk(tree, ())
            return sink

        for function in raising:
            with self.subTest(helper=function):
                self.assertIn(
                    function, functions,
                    f"an unguarded read sits at module level in {function}",
                )
                call_sites = call_sites_of(function)
                self.assertTrue(
                    call_sites,
                    f"{function} contains an unguarded read and is never called, "
                    f"so it is dead code carrying a live hazard",
                )
                unguarded = [line for line, guarded in call_sites if not guarded]
                self.assertEqual(
                    [], unguarded,
                    f"{function} reads a file without catching a decode error, and "
                    f"its call site(s) at line(s) {unguarded} do not catch one "
                    f"either. main() installs no handler, so a non-UTF-8 file there "
                    f"aborts the whole gate step with zero JSON.",
                )


if __name__ == "__main__":
    unittest.main()
