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
import verify_offline  # noqa: E402


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



def tracked_markdown() -> list[Path]:
    """Every tracked `.md` outside `_internal/`, from the release manifest.

    The manifest is the release inventory, so this enumerates the shipped
    world rather than a curated path list — which is the whole point: the
    fifteenth pass found RUNBOOK §8.1 prescribing a five-path grep for a
    count that eleven documents state.
    """
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    return sorted(
        ROOT / entry["path"]
        for entry in manifest["files"]
        if entry["path"].endswith(".md") and not entry["path"].startswith("_internal/")
    )


# Every tracked document whose skill count the pattern below can see. Pinned
# so that a reworded sentence which stops matching fails loudly instead of
# quietly leaving the document unbound.
COVERED_SKILL_COUNT_DOCUMENTS = frozenset({
    "README.md",
    "docs/PRODUCTION_READINESS.md",
    "docs/V3_RELEASE_EVIDENCE.md",
    "evals/V3_EVAL_RESULTS.md",
    "research/agents/02-lead-router.md",
    "workspaces/shared-skills/resolver-check/SKILL.md",
    "workspaces/vc-chief/vc/RESOLVER.md",
    "workspaces/vc-chief/vc/eval_fixtures.md",
    "workspaces/vc-chief/vc/governance_lint.md",
    "workspaces/vc-chief/vc/system_health.md",
})


class SkillCountPinTests(unittest.TestCase):
    """The shipped skill count is prose in many documents and checked in none.

    `validate_skill_system.py` derives the inventory and RUNBOOK §8.1 told the
    operator to grep five paths before changing it — but eleven tracked
    documents state the number, and the four the grep missed were exactly the
    ones no gate touched. A count restated in prose across the tree is a
    completeness claim: enumerate its world from the source of truth.
    """

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "v3_doc_tree_validate_skill_system", ROOT / "scripts/validate_skill_system.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        # Register before exec: the module defines frozen dataclasses, and
        # dataclasses resolves the defining module out of sys.modules.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        cls.skills = len(module.EXPECTED_SKILLS)

    def test_every_documented_skill_count_matches_the_validator_inventory(self):
        # Only the forward form counts: a number immediately qualifying the
        # word "skill(s)", optionally through up to two qualifier words
        # (README's "26 reusable bounded skills" needs both) and across a
        # line wrap. The reverse form ("skills … 78/78") matches unrelated
        # table cells, and a bare "26" elsewhere is a line number or a size.
        pattern = re.compile(
            r"(\d+)[\s-]+(?:[A-Za-z]+[\s-]+){0,2}skills?\b",
            re.I,
        )
        # The V2 baseline studies state V2's inventory deliberately; they are
        # history, not a claim about this release. Exempt them by PINNED
        # (path, value) pair rather than by proximity to the words "Version 2":
        # a character window around the match is not a sentence, so a heading
        # or a passing V2 reference anywhere nearby would silently exempt an
        # arbitrary wrong V3 count in the same file.
        baseline = {
            ("02_BASELINE_ASSESSMENT_AND_CHANGE_GATE.md", 25),
            ("research/agents/11-data-steward.md", 16),
        }
        stated = {}
        seen_baseline = set()
        for path in tracked_markdown():
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(text):
                value = int(match.group(1))
                if (relative, value) in baseline:
                    seen_baseline.add((relative, value))
                    continue
                stated.setdefault(relative, set()).add(value)
        # If a pinned exemption stops matching, it has become dead cover that
        # would silently start exempting nothing — or, worse, someone deleted
        # the sentence and left the exemption to shadow a future real drift.
        self.assertEqual(
            seen_baseline, baseline,
            "these pinned Version 2 baseline counts are no longer present: "
            f"{sorted(baseline - seen_baseline)}. Remove the stale exemption "
            "rather than leaving it to shadow a future count.",
        )
        # Guard the covered set, not just its contents. A reworded sentence
        # that stops matching would silently drop that document out of
        # coverage, and `stated` would stay non-empty — the same dead-cover
        # failure the baseline assertion above prevents on the V2 side.
        self.assertEqual(
            set(stated), COVERED_SKILL_COUNT_DOCUMENTS,
            "the set of documents whose skill count this pin can see has "
            f"changed: {sorted(set(stated) ^ COVERED_SKILL_COUNT_DOCUMENTS)}. If "
            "a document was reworded, widen the pattern or reword it back — a "
            "document that silently stops matching is no longer bound. If one "
            "was added or removed, update this set in the same change.",
        )
        wrong = {
            relative: sorted(values)
            for relative, values in stated.items()
            if values != {self.skills}
        }
        self.assertEqual(
            wrong, {},
            f"these documents state a skill count that is not the validator's "
            f"{self.skills}: {wrong}. validate_skill_system.py is the source of "
            "truth; update the prose, never this pin.",
        )

    def test_runbook_skill_change_recipe_states_the_current_count(self):
        """§8.1 tells the operator to grep for the outgoing number.

        RUNBOOK states the count as a bare numeral inside a prose sentence and
        two `sh` recipes, never as "N skills", so the prose pattern above
        cannot see it — yet §8.1 names this document among those the pin
        covers. Bind its instances directly rather than leaving the claim
        unbacked.
        """
        runbook = (ROOT / "docs/RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn(
            f"outgoing number is `{self.skills}`", runbook,
            "docs/RUNBOOK.md §8.1 no longer states the current skill count in "
            f"the pinned form: outgoing number is `{self.skills}`",
        )
        recipes = re.findall(r"```sh\n(.*?)```", runbook, re.S)
        grep_recipes = [
            recipe for recipe in recipes
            if "\\b" in recipe and ("--include='*.md'" in recipe or "'*.md'" in recipe)
        ]
        self.assertTrue(grep_recipes, "the §8.1 count-drift grep recipes have rotted")
        for recipe in grep_recipes:
            for number in re.findall(r"\\b(\d+)\\b", recipe):
                self.assertEqual(
                    int(number), self.skills,
                    f"a §8.1 grep recipe searches for {number} while the "
                    f"validator inventory is {self.skills}: {recipe.strip()}",
                )


class RuffRuleInventoryTests(unittest.TestCase):
    """CLAUDE.md argues against widening ruff.toml from two measured numbers.

    Both were asserted rather than derived, and the family count was wrong by
    one (pycodestyle, selected through `E4`/`E7`/`E9`/`W`, was uncounted). The
    argument only carries weight if the numbers are the tool's own, so derive
    them from ruff instead of trusting the sentence.
    """

    def test_claude_md_rule_and_family_counts_match_ruff(self):
        import subprocess

        # Resolve ruff exactly the way the gate's own `ruff` step does, rather
        # than restating a venv path: verify_offline treats ANY skipped test as
        # a suite failure, so a hardcoded path would turn this into a red gate
        # on every checkout whose venv lives elsewhere.
        ruff = verify_offline.locked_tool("ruff")
        if not ruff.is_file():
            self.fail(
                "the pinned ruff is missing; install the hash-locked "
                "requirements-dev.lock (the gate's own `ruff` step fails "
                f"identically). Resolved to {ruff}"
            )
        settings = subprocess.run(
            [str(ruff), "check", "--no-cache", "--show-settings", "."],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout
        block = settings.split("linter.rules.enabled = [", 1)
        self.assertEqual(len(block), 2, "ruff --show-settings no longer prints the enabled rules")
        codes = re.findall(r"\(([A-Z]+[0-9]+)\)", block[1].split("\n]", 1)[0])
        self.assertTrue(codes, "no enabled rule codes parsed from ruff --show-settings")

        linters = subprocess.run(
            [str(ruff), "linter"], cwd=ROOT, capture_output=True, text=True
        ).stdout
        prefixes = {}
        for line in linters.splitlines():
            match = re.match(r"\s*([A-Z0-9/]+)\s+(\S.*)$", line)
            if match:
                for prefix in match.group(1).split("/"):
                    prefixes[prefix] = match.group(2).strip()
        families = set()
        for code in codes:
            best = max(
                (p for p in prefixes if code.startswith(p)), key=len, default=None
            )
            self.assertIsNotNone(best, f"no ruff linter owns rule {code}")
            families.add(prefixes[best])

        claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        match = re.search(
            r"`ruff\.toml` selects \*\*(\d+)\*\* rules across (\d+) linter families", claude
        )
        if match is None:
            self.fail(
                "CLAUDE.md no longer states the ruff rule/family counts in the "
                "pinned form `ruff.toml` selects **N** rules across M linter families"
            )
        self.assertEqual(
            (int(match.group(1)), int(match.group(2))), (len(codes), len(families)),
            f"CLAUDE.md states {match.group(1)} rules across {match.group(2)} families; "
            f"the pinned ruff reports {len(codes)} rules across {len(families)} "
            f"({sorted(families)}). Update the sentence to the measured value.",
        )


class DocumentQuarantineLaneTests(unittest.TestCase):
    """Only the extract lane quarantines, and the docs must say which one.

    Every inspection-stage rejection (magic/MIME, macro or legacy format,
    encryption, archive expansion, active content, page and size limits) is
    raised inside `inspect_document`, which both shipped intake workflows
    reach first through `document-preview` — a read lane that deliberately
    performs no mutation and therefore writes no `vc-quarantine` copy. The G4
    document-security suite invokes `document-extract` directly for those
    classes, so it proves a lane the workflows never reach for them. Pin the
    structural facts the corrected documentation now rests on.
    """

    def test_only_the_extract_lane_writes_quarantine(self):
        vcops = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        callers = set()
        for match in re.finditer(r"\n(def (cmd_\w+)\(.*?)(?=\ndef )", vcops, re.S):
            if "quarantine_document(" in match.group(1):
                callers.add(match.group(2))
        self.assertEqual(
            callers, {"cmd_document_extract"},
            "the set of commands that write a quarantine copy moved: "
            f"{sorted(callers)}. docs/RUNBOOK.md §9 'Malicious document' and "
            "docs/OPERATIONS.md's vc-quarantine description both state that "
            "only the extract lane materializes one; update them together.",
        )

    def test_extract_lane_quarantines_inspection_failures_too(self):
        """The extract lane's handler wraps inspection, not just the parse.

        The fifteenth pass first documented `vc-quarantine` as receiving copies
        only for failures *after* the content-addressed snapshot. That is
        false: `cmd_document_extract`'s `try:` opens at `inspect_document`, so
        a hand-run `vcops-operator document-extract`, and the workflow
        preview→extract TOCTOU, both quarantine inspection-stage classes. The
        docs now say so; pin the boundary they rest on, since the sibling test
        above pins only *which command* quarantines, never *when*.
        """
        vcops = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        start = vcops.index("def cmd_document_extract(")
        body = vcops[start:vcops.index("\ndef ", start + 1)]
        try_at = body.index("\n    try:")
        self.assertLess(
            try_at, body.index("inspect_document("),
            "cmd_document_extract no longer inspects inside its quarantining "
            "try block, so inspection-stage rejections no longer route through "
            "the quarantine lane. docs/RUNBOOK.md §9 'Malicious document' and "
            "docs/OPERATIONS.md's vc-quarantine entry both describe that "
            "routing — update them together with this change.",
        )
        self.assertLess(
            body.index("inspect_document("), body.index("write_content_addressed("),
            "inspection no longer precedes the content-addressed snapshot",
        )

    def test_quarantine_can_decline_to_copy(self):
        """"Routes through the quarantine lane" is not "a copy exists".

        Three successive drafts of the RUNBOOK §9 entry asserted a universal
        about `vc-quarantine` and three were wrong, because `quarantine_document`
        has branches that deliberately write nothing: an oversized document (the
        same `MAX_DOCUMENT_BYTES` that raised `document_too_large` also caps what
        quarantine will copy) and any input it cannot safely read. The documents
        now tell the operator to read `details.quarantine.materialized` instead
        of assuming. Pin the branches that make that field meaningful — the
        world here is two return statements, which is why this check can be
        exact where a prose universal could not.
        """
        vcops = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        start = vcops.index("def quarantine_document(")
        body = vcops[start:vcops.index("\ndef ", start + 1)]
        reasons = set(re.findall(r'"materialized":\s*False,\s*"reason":\s*"(\w+)"', body))
        self.assertEqual(
            reasons, {"input_path_not_safe_to_copy", "exceeds_quarantine_byte_limit"},
            "quarantine_document's non-materializing branches changed: "
            f"{sorted(reasons)}. docs/RUNBOOK.md §9 'Malicious document' names "
            "both to the operator as the reasons a rejected document may leave "
            "no copy; update it with this change.",
        )
        runbook = (ROOT / "docs/RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn(
            "details.quarantine.materialized", runbook,
            "docs/RUNBOOK.md §9 no longer points the operator at the field that "
            "actually says whether a quarantine copy exists",
        )

    def test_shipped_intake_workflows_preview_before_extract(self):
        workflows = ROOT / "workspaces/vc-chief/vc/workflows"
        for name in ("document-ingest.lobster", "inbound-intake.lobster"):
            with self.subTest(workflow=name):
                body = (workflows / name).read_text(encoding="utf-8")
                self.assertLess(
                    body.index("document-preview"), body.index("document-extract"),
                    f"{name} no longer previews before extracting; if preview stops "
                    "being the first inspection point, the quarantine wording in "
                    "RUNBOOK §9 and OPERATIONS.md must be revisited.",
                )


class HostUtilityEnumerationTests(unittest.TestCase):
    """RUNBOOK §2 tells the operator which externals a recovery host needs.

    That list drifted through five hand-fixes before the fifteenth pass found
    it still missing `dirname` — the first external command every lifecycle
    script runs, and the only one whose absence does not fail closed (the
    `PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"` prologue
    silently resolves to `/`). A §5.4 recovery drill on a minimal host is
    exactly the situation the list exists for, so bind it to the scripts.

    The scan is deliberately vocabulary-driven rather than "every command-position
    word": its world is then trivially enumerable, which is the lesson the
    fourteenth pass's four-iteration dash guard paid for. A utility outside
    VOCABULARY is out of scope by construction, not by accident.
    """

    VOCABULARY = frozenset({
        "awk", "basename", "cat", "chmod", "chown", "cmp", "cp", "cut", "date",
        "dirname", "du", "find", "grep", "head", "id", "install", "ln", "ls",
        "mkdir", "mktemp", "mv", "od", "rm", "rmdir", "sed", "seq", "sha256sum",
        "shasum", "sleep", "sort", "stat", "tail", "tar", "tee", "touch", "tr",
        "uname", "uniq", "wc", "xargs", "gzip", "gunzip", "cksum", "comm",
    })

    COMMAND_POSITION = re.compile(
        r"(?:^|[|;&(!{]|\$\(|&&|\|\||\bthen\b|\bdo\b|\belse\b|\bxargs\b)\s*!?\s*([a-z][a-z0-9_-]*)"
    )

    def test_runbook_prerequisites_name_every_utility_the_scripts_call(self):
        scripts = sorted((ROOT / "scripts").glob("*.sh"))
        scripts.append(ROOT / "migrations/000_roles.sh")
        called = {}
        for path in scripts:
            for line in path.read_text(encoding="utf-8").splitlines():
                for match in self.COMMAND_POSITION.finditer(line.split("#", 1)[0]):
                    if match.group(1) in self.VOCABULARY:
                        called.setdefault(match.group(1), set()).add(path.name)
        self.assertIn(
            "dirname", called, "the command-position scan has rotted: every "
            "lifecycle script opens with a dirname prologue",
        )

        runbook = (ROOT / "docs/RUNBOOK.md").read_text(encoding="utf-8")
        start = runbook.index("a POSIX shell plus host")
        end = runbook.index("\n- ", start)
        prerequisites = runbook[start:end]
        undocumented = sorted(
            utility for utility in called
            if f"`{utility}`" not in prerequisites
            and f"`{utility}`/" not in prerequisites
            and f"/`{utility}`" not in prerequisites
        )
        callers = {utility: sorted(called[utility]) for utility in undocumented}
        self.assertEqual(
            undocumented, [],
            "docs/RUNBOOK.md §2's host-prerequisite enumeration omits utilities "
            f"the lifecycle scripts call: {callers}. A §5.4 recovery drill on a "
            "minimal host is where this list is load-bearing.",
        )


class DocumentedInvocationTests(unittest.TestCase):
    """Every command a document tells the operator to run must be runnable.

    Two defect classes converge here, and both have been observed. The
    fifteenth pass's own fix wave put a `git grep` recipe into RUNBOOK §8.1
    that dies with `Unimplemented pathspec magic` on the shipped git version —
    written, never executed. Its planted-defect calibration separately seeded a
    documented `--force` flag that `init_customization.py` does not accept, and
    five reviewers had to be paid to find it.

    A documented invocation is checkable without executing anything dangerous:
    the script must exist, and every long flag must appear in its argument
    parser. That is the whole world for package scripts, so it is exact.
    """

    # Absolute in-image paths (e.g. /app/skills/skill-creator/scripts/...) are
    # deliberately not package scripts; RUNBOOK §8.1 says so where it uses one.
    INVOCATION = re.compile(r"(?<![\w/])scripts/([A-Za-z0-9_]+\.py)((?:\s+-{1,2}[A-Za-z0-9][\w-]*(?:[= ][^\s`|>]+)?)*)")
    LONG_FLAG = re.compile(r"(?<!\w)--[A-Za-z][\w-]*")

    def documented_invocations(self):
        """{script: {flags}} over every fenced sh block in tracked docs."""
        found = {}
        for path in tracked_markdown():
            for block in re.findall(r"```sh\n(.*?)```", path.read_text(encoding="utf-8"), re.S):
                # Join backslash line continuations so a wrapped invocation is
                # read as one command, the way the operator's shell reads it.
                flat = re.sub(r"\\\n\s*", " ", block)
                for match in self.INVOCATION.finditer(flat):
                    script, tail = match.group(1), match.group(2) or ""
                    entry = found.setdefault(script, {"flags": set(), "docs": set()})
                    entry["flags"].update(self.LONG_FLAG.findall(tail))
                    entry["docs"].add(path.relative_to(ROOT).as_posix())
        return found

    def test_every_documented_script_exists(self):
        found = self.documented_invocations()
        self.assertGreaterEqual(
            len(found), 5, "the documented-invocation scan has rotted: no sh block matched"
        )
        missing = {
            script: sorted(entry["docs"])
            for script, entry in found.items()
            if not (ROOT / "scripts" / script).is_file()
        }
        self.assertEqual(
            missing, {},
            f"documents tell the operator to run scripts that do not ship: {missing}",
        )

    def test_every_documented_flag_exists_in_its_parser(self):
        offenders = {}
        for script, entry in self.documented_invocations().items():
            source_path = ROOT / "scripts" / script
            if not source_path.is_file():
                continue  # reported by the sibling test
            source = source_path.read_text(encoding="utf-8")
            for flag in sorted(entry["flags"]):
                if f'"{flag}"' not in source and f"'{flag}'" not in source:
                    offenders.setdefault(script, []).append(
                        f"{flag} (documented in {', '.join(sorted(entry['docs']))})"
                    )
        self.assertEqual(
            offenders, {},
            "documents pass flags these scripts do not accept, so the "
            f"documented command fails for the operator: {offenders}",
        )

if __name__ == "__main__":
    unittest.main()
