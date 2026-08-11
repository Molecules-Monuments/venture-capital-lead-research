# SPDX-License-Identifier: 0BSD
"""Documentation inventories must enumerate the tree, not remember it.

Two fourteenth-audit-pass findings established the class this suite closes:
the README project structure enumerated 25 of 26 shipped scripts with no
elision marker — the missing one being the evidence-date tool CLAUDE.md
mandates — and OPERATIONS.md's rotation step list omitted that the rotation
script applies pending migrations and re-runs the state initializer. An
enumeration that reads as complete must be complete, and a step list for a
script that mutates state must name the mutating steps; both are bound to the
tree here so the next drift fails the offline gate instead of waiting for an
audit reviewer.
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Importing a module by path byte-compiles it into scripts/__pycache__, which
# `verify_release.py --pristine` then reports as an undeclared file. Suppress
# it the way scripts/validate_workflows.py does, so this suite stays safe to
# run even when someone omits `-B`.
sys.dont_write_bytecode = True

import check_env  # noqa: E402


class ReadmeScriptInventoryTests(unittest.TestCase):
    def test_readme_scripts_subtree_enumerates_the_shipped_scripts(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        marker = "├── scripts/"
        self.assertIn(marker, readme, "the README project structure has rotted")
        block = readme.split(marker, 1)[1].split("├── workspaces/", 1)[0]
        documented = set(re.findall(r"([a-z_0-9]+\.(?:py|sh))", block))
        shipped = {
            path.name
            for path in (ROOT / "scripts").iterdir()
            if path.suffix in (".py", ".sh")
        }
        missing = sorted(shipped - documented)
        self.assertEqual(
            missing, [],
            f"README's scripts/ subtree omits shipped scripts: {missing}. The "
            "subtree carries no elision marker, so it reads as complete — add "
            "a tree line rather than weakening this test.",
        )
        ghosts = sorted(documented - shipped)
        self.assertEqual(
            ghosts, [],
            f"README's scripts/ subtree names scripts that do not ship: {ghosts}",
        )


class RotationDocConsistencyTests(unittest.TestCase):
    def test_rotation_doc_names_the_mutating_steps_the_script_runs(self):
        script = (ROOT / "scripts/rotate_runtime_role.sh").read_text(encoding="utf-8")
        operations = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
        rotation_context = "\n\n".join(
            paragraph
            for paragraph in operations.split("\n\n")
            if "rotat" in paragraph.lower()
        )
        self.assertTrue(rotation_context, "OPERATIONS.md no longer describes rotation")
        # An incident operator is told to run this script directly, so every
        # state-mutating step the script performs must appear in the document's
        # rotation description: a rotation that silently applies migrations or
        # re-renders config is an unexpected deployment.
        #
        # Derive the step set from the script rather than listing instances —
        # a hand-written list only ever covers the steps someone noticed. Any
        # helper the rotation script invokes counts, so a step added later
        # fails here until the description names it.
        invoked = set(
            re.findall(r"(?:\./)?scripts/([a-z_0-9]+\.(?:sh|py))", script)
        ) | {
            service
            for service in ("openclaw-state-init",)
            if service in script
        }
        self.assertGreaterEqual(
            len(invoked), 4,
            "the rotation script's invoked-helper enumeration has rotted",
        )
        missing = sorted(name for name in invoked if name not in rotation_context)
        self.assertEqual(
            missing, [],
            f"rotate_runtime_role.sh invokes {missing}, but the rotation "
            "description in docs/OPERATIONS.md never names them — an operator "
            "running the script directly would not know it runs them",
        )


class PolicyVersionPinTests(unittest.TestCase):
    def test_every_policy_version_pin_agrees_with_the_rubric(self):
        """`3.0` is frozen across code, workflows, and an applied migration.

        CUSTOMIZATION.md used to list the rubric JSON `"version"` as an
        operator-editable coupled artifact. It is not: `_load_rubric` compares
        it against a hard-coded `"3.0"` and fails closed with `rubric_invalid`
        before the documented `rubric_version_mismatch` path is reachable, and
        migration 008 pins the same literal in a trigger that cannot be edited
        after bootstrap. Bind every pin to the rubric so the set cannot drift
        apart silently.
        """
        rubric = json.loads(
            (ROOT / "workspaces/vc-chief/vc/scoring-rubric.v3.json").read_text(
                encoding="utf-8"
            )
        )
        version = rubric["version"]
        self.assertEqual(version, "3.0")
        helper = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        self.assertIn(f'rubric.get("version") != "{version}"', helper)
        self.assertRegex(helper, rf'POLICY_VERSION\s*=\s*"{re.escape(version)}"')
        defaults = re.findall(r'--policy-version",\s*default="([^"]+)"', helper)
        self.assertGreaterEqual(len(defaults), 4, "the --policy-version defaults have rotted")
        self.assertEqual(set(defaults), {version})
        migration = (
            ROOT / "migrations/008_workflow_version_binding.sql"
        ).read_text(encoding="utf-8")
        self.assertIn(f"IS DISTINCT FROM '{version}'", migration)
        # The prose line in the rubric Markdown is the one member no gate
        # reached before this pass; bind it here so the ungated set is empty.
        rubric_md = (
            ROOT / "workspaces/vc-chief/vc/scoring-rubric.md"
        ).read_text(encoding="utf-8")
        self.assertIn(f"Policy version: `{version}`", rubric_md)
        workflow = (
            ROOT / "workspaces/vc-chief/vc/workflows/evaluate-lead.lobster"
        ).read_text(encoding="utf-8")
        literals = re.findall(r"--policy-version (\S+)", workflow)
        self.assertGreaterEqual(len(literals), 2, "the workflow policy-version literals have rotted")
        self.assertEqual(set(literals), {version})
        # The document must keep telling operators not to bump it.
        customization = (ROOT / "CUSTOMIZATION.md").read_text(encoding="utf-8")
        self.assertIn("frozen at `3.0` for this release", customization)


class ResolverConsumerTests(unittest.TestCase):
    def test_customization_names_every_lead_creating_workflow(self):
        """CUSTOMIZATION.md said "both intake workflows"; there are four.

        The resolver-consumer set is already gate-enforced through
        validate_skill_system's EXPECTED_WORKFLOW_STEPS, so bind the prose to
        that pinned inventory rather than introducing a third source of truth.
        """
        spec = importlib.util.spec_from_file_location(
            "v3_validate_skill_system", ROOT / "scripts/validate_skill_system.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Register before exec: the module defines frozen dataclasses, whose
        # construction resolves the owning module out of sys.modules.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        consumers = {
            name
            for name, steps in module.EXPECTED_WORKFLOW_STEPS.items()
            if "company_resolve_create" in steps
        }
        self.assertEqual(len(consumers), 4, "the resolver-consumer inventory moved")
        # Cross-check the pin against the workflow bodies themselves.
        from_files = {
            path.stem
            for path in (ROOT / "workspaces/vc-chief/vc/workflows").glob("*.lobster")
            if "company-resolve-create" in path.read_text(encoding="utf-8")
        }
        self.assertEqual(consumers, from_files)
        customization = (ROOT / "CUSTOMIZATION.md").read_text(encoding="utf-8")
        bullet = re.search(r"^- resolver policy,.*?;$", customization, re.M | re.S)
        self.assertIsNotNone(bullet, "the resolver coupling bullet has rotted")
        assert bullet is not None
        for name in sorted(consumers):
            self.assertIn(
                f"`{name}`", bullet.group(0),
                f"CUSTOMIZATION.md's resolver coupling bullet omits {name}",
            )
        self.assertNotIn(
            "both intake workflows", customization,
            "the resolver coupling bullet still uses a count word instead of "
            "naming the four lead-creating workflows",
        )


class ChannelVariableCoverageTests(unittest.TestCase):
    def test_every_required_channel_variable_is_named_in_channels_doc(self):
        """CHANNELS.md is where an operator collects these values.

        A required variable the setup document never names is one the operator
        discovers only when check_env rejects an incomplete family. Enumerate
        the requirement from check_env, not from the document.
        """
        channels = (ROOT / "docs/CHANNELS.md").read_text(encoding="utf-8")
        required = sorted(
            {key for fields in check_env.CHANNEL_FIELDS.values() for key in fields}
        )
        self.assertGreaterEqual(len(required), 15, "the channel field inventory has rotted")
        missing = [key for key in required if key not in channels]
        self.assertEqual(
            missing, [],
            f"docs/CHANNELS.md never names these required channel variables: "
            f"{missing}. Name each one where the operator collects its value.",
        )


class SkillOutputContractTests(unittest.TestCase):
    def test_every_skill_output_section_defers_to_its_schema(self):
        """A skill's Output section must defer to its schema, never restate it.

        Every agent output schema sets `additionalProperties: false`, so a
        skill that enumerates its own field list instructs the agent to emit
        schema-invalid output — which is what `data-persistence` did until the
        fourteenth pass, naming five fields (`ok`, `transaction_id`,
        `affected_ids`, `versions`, `approval_consumed`) that exist nowhere in
        the schema or the tree. Testing which backticked tokens are field
        names is not reliable (Output sections legitimately discuss workflow
        *argument* names in prose), so enforce the convention the sibling
        skills state instead: name the schema, and say it is authoritative.
        """
        # Two dialects of the same convention ship today: "## Output" sections
        # say the schema is the sole authority and forbid a parallel
        # definition, while "## Output boundary" sections say the procedure
        # defines no second format / the schema rather than the prose controls.
        # Either discharges the requirement; naming a schema and then listing
        # fields with neither does not.
        deferral = re.compile(
            r"(?i)sole authority"
            r"|not (?:this )?prose,? (?:is authoritative|controls)"
            r"|does not define a second output format"
            r"|do not maintain a parallel output definition"
        )
        # Pinned so the defect that motivated this test — an Output section
        # carrying a hand-written field list and NO schema reference at all —
        # fails here instead of being skipped for lack of a schema to check.
        must_defer = {
            "data-persistence",
            "document-extraction",
            "evidence-research",
            "evidence-scoring",
            "inbound-intake",
            "lead-routing",
            "lead-signal-detection",
            "memo-writing",
            "outbound-sourcing",
            "trajectory-check",
        }
        # The other sixteen shared skills describe an inner payload routed
        # through `data-steward`, not an agent output envelope, so they have no
        # canonical schema to defer to. That is a real distinction, but it must
        # be a pinned disposition rather than a silent skip: without this set a
        # skill that LOST its schema reference would drop out of the checked
        # world unnoticed, which is exactly the shape of the defect this suite
        # was added for.
        no_output_schema = {
            "approval-gates", "compiled-truth", "contradiction-check",
            "controlled-evolution", "eval-fixture-check", "governance-lint",
            "knowledge-modeling", "lead-memory-lookup", "quiet-hours-reporting",
            "research-depth-control", "resolver-check", "schema-proposal",
            "skillify", "source-improvement", "system-health-check",
            "trust-boundary",
        }
        deferring = set()
        checked = 0
        for skill in sorted((ROOT / "workspaces/shared-skills").glob("*/SKILL.md")):
            text = skill.read_text(encoding="utf-8")
            section = re.search(r"\n## Output(?: boundary)?\n(.*?)(?=\n## |\Z)", text, re.S)
            if section is None:
                continue
            body = section.group(1)
            named = re.findall(r"([a-z0-9.\-]+\.schema\.json)", body)
            if not named:
                continue
            deferring.add(skill.parent.name)
            with self.subTest(skill=skill.relative_to(ROOT)):
                for schema_name in named:
                    self.assertTrue(
                        (ROOT / "workspaces/schemas" / schema_name).is_file(),
                        f"{skill.relative_to(ROOT)} names a schema that does not "
                        f"exist: {schema_name}",
                    )
                self.assertRegex(
                    body, deferral,
                    f"{skill.relative_to(ROOT)} names {named} without stating the "
                    "schema is authoritative. An output schema sets "
                    "additionalProperties:false, so a prose field list here "
                    "instructs the agent to emit schema-invalid output.",
                )
                checked += 1
        self.assertGreaterEqual(
            checked, 10, "the skill Output-section scan has rotted"
        )
        self.assertEqual(
            sorted(must_defer - deferring), [],
            "these skills stopped pointing their Output section at an output "
            "schema; a hand-written field list in its place contradicts an "
            "additionalProperties:false contract",
        )
        # Enumerate the whole directory, so a new skill lands in one of the two
        # dispositions rather than escaping the check by being neither.
        every_skill = {
            path.parent.name
            for path in (ROOT / "workspaces/shared-skills").glob("*/SKILL.md")
        }
        self.assertEqual(
            every_skill, must_defer | no_output_schema,
            "a shared skill is in neither disposition. Either its Output "
            "section names its canonical output schema and declares the schema "
            "authoritative (add it to must_defer), or it describes an inner "
            "payload with no agent envelope (add it to no_output_schema).",
        )


if __name__ == "__main__":
    unittest.main()
