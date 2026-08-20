# SPDX-License-Identifier: Apache-2.0
"""Documentation inventories must enumerate the tree, not remember it.

Two fourteenth-audit-pass findings established the class this suite closes:
the README project structure enumerated 25 of 26 shipped scripts with no
elision marker — the missing one being the evidence-date tool
docs/MAINTAINING.md mandates — and OPERATIONS.md's rotation step list
omitted that the rotation script applies pending migrations and re-runs the
state initializer. An
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

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Importing a module by path byte-compiles it into scripts/__pycache__, which
# `verify_release.py --pristine` then reports as an undeclared file. Suppress
# that one source of debris, the way scripts/validate_workflows.py does. This
# does NOT make the suite safe to run without `-B`: the runner still caches
# the test modules themselves into tests/v3/__pycache__, which fails
# --pristine just as loudly. Run the suites with `-B`, as the offline gate does.
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


class SecretRotationRecreationTests(unittest.TestCase):
    def test_rotation_sequence_recreates_each_gateway_token_carrier(self):
        """The documented sequence omitted the profile-gated CLI container.

        `OPENCLAW_GATEWAY_TOKEN` is baked into a container's environment at
        creation, so rotating it reaches a service only by recreating that
        service. `docker compose up -d --force-recreate` with no service
        argument covers the default-profile services and skips anything behind
        a `profiles:` key, which has to be recreated by name with its
        `--profile` flag. Derive the carrier set from docker-compose.yml and
        classify each carrier by whether the block covers it the blanket way
        or the by-name way, so a service that gains the token — or gains a
        profile — fails here instead of quietly keeping its old secret.
        """
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        carriers = {
            name: tuple(service.get("profiles") or ())
            for name, service in compose["services"].items()
            if "OPENCLAW_GATEWAY_TOKEN" in (service.get("environment") or {})
        }
        self.assertIn(
            "openclaw-gateway", carriers,
            "the gateway-token carrier derivation has rotted: the gateway itself "
            "no longer reads OPENCLAW_GATEWAY_TOKEN from its compose environment",
        )

        operations = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
        anchor = "The sequence for the non-database secrets is:"
        self.assertIn(anchor, operations, "the secret-rotation sequence has rotted")
        fenced = operations.split(anchor, 1)[1]
        self.assertTrue(fenced.lstrip().startswith("```sh"), "the sequence is no longer a sh block")
        block = fenced.split("```sh", 1)[1].split("```", 1)[0]
        # Join the backslash continuations so each entry is one command.
        commands = [
            " ".join(command.split())
            for command in block.replace("\\\n", " ").splitlines()
            if command.strip()
        ]
        # A recreate command with no positional service argument is the one
        # that reaches every default-profile service.
        blanket = [
            command
            for command in commands
            if " up " in f" {command} "
            and "--force-recreate" in command
            and "--profile" not in command
            and not [
                token
                for token in command.split()[command.split().index("up") + 1:]
                if not token.startswith("-")
            ]
        ]

        for name, profiles in sorted(carriers.items()):
            with self.subTest(service=name):
                if not profiles:
                    self.assertTrue(
                        blanket,
                        f"{name} carries OPENCLAW_GATEWAY_TOKEN and sits in the default "
                        "profile, but the documented sequence has no `up ... "
                        "--force-recreate` command without a service argument, so nothing "
                        "in it recreates the service and the rotated token never reaches it",
                    )
                    continue
                named = [
                    command
                    for command in commands
                    if "--force-recreate" in command
                    and name in command.split()
                    and all(f"--profile {profile}" in command for profile in profiles)
                ]
                self.assertTrue(
                    named,
                    f"{name} carries OPENCLAW_GATEWAY_TOKEN and sits behind "
                    f"profiles {list(profiles)}, so `up -d --force-recreate` skips it. "
                    "The documented rotation sequence never recreates it by name with "
                    f"--profile {profiles[0]}, so the container keeps the pre-rotation "
                    "token it was created with, readable through `docker inspect`.",
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
    """The maintainer handbook argues against widening ruff.toml from two
    measured numbers.

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

        maintaining = (ROOT / "docs/MAINTAINING.md").read_text(encoding="utf-8")
        match = re.search(
            r"`ruff\.toml` selects \*\*(\d+)\*\* rules across (\d+) linter families", maintaining
        )
        if match is None:
            self.fail(
                "docs/MAINTAINING.md no longer states the ruff rule/family counts "
                "in the pinned form `ruff.toml` selects **N** rules across M "
                "linter families"
            )
        self.assertEqual(
            (int(match.group(1)), int(match.group(2))), (len(codes), len(families)),
            f"docs/MAINTAINING.md states {match.group(1)} rules across "
            f"{match.group(2)} families; the pinned ruff reports {len(codes)} "
            f"rules across {len(families)} "
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
        quarantine will copy), any input it cannot safely read, and a copy the
        filesystem refuses (`quarantine_write_failed` — the caller-controlled
        suffix can overflow the 255-byte filename limit). The documents now tell
        the operator to read `details.quarantine.materialized` instead of
        assuming. Pin the branches that make that field meaningful — the world
        here is the function's own `"materialized": False` returns, which is why
        this check can be exact where a prose universal could not.

        The reverse reading was wrong too: `quarantine_write_failed` used to be
        documented as "no copy". Quarantine names are content-addressed and the
        marker-failure branch removes the copy only when this call created it,
        so a repeat rejection of bytes an earlier rejection recorded returns
        `materialized: false` over a copy and marker that are still on the
        volume — `test_a_failed_marker_write_leaves_exactly_what_it_found`
        executes that. This test asserts the two documents carry the retention
        wording next to their first mention of the reason: the substrings
        "published nothing new" and "an earlier rejection" must both appear
        within 800 characters after it, in whitespace-normalized text.
        """
        vcops = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        start = vcops.index("def quarantine_document(")
        body = vcops[start:vcops.index("\ndef ", start + 1)]
        reasons = set(re.findall(r'"materialized":\s*False,\s*"reason":\s*"(\w+)"', body))
        self.assertEqual(
            reasons,
            {
                "input_path_not_safe_to_copy",
                "exceeds_quarantine_byte_limit",
                "quarantine_write_failed",
            },
            "quarantine_document's non-materializing branches changed: "
            f"{sorted(reasons)}. docs/RUNBOOK.md §9 'Malicious document' "
            "describes each of these to the operator as a reason a rejected "
            "document may leave no copy; update it with this change.",
        )
        runbook = (ROOT / "docs/RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn(
            "details.quarantine.materialized", runbook,
            "docs/RUNBOOK.md §9 no longer points the operator at the field that "
            "actually says whether a quarantine copy exists",
        )
        for name in ("docs/RUNBOOK.md", "docs/OPERATIONS.md"):
            with self.subTest(document=name):
                text = " ".join((ROOT / name).read_text(encoding="utf-8").split())
                self.assertIn(
                    "quarantine_write_failed", text,
                    f"{name} no longer names the quarantine_write_failed reason",
                )
                window = text[text.index("quarantine_write_failed"):][:800]
                for phrase in ("published nothing new", "an earlier rejection"):
                    self.assertIn(
                        phrase, window,
                        f"{name} describes quarantine_write_failed without saying "
                        f"(missing: {phrase!r}) that it only means this rejection "
                        "published nothing new, and that a copy and marker from an "
                        "earlier rejection of the same content-addressed bytes are "
                        "kept. The marker-failure branch of quarantine_document "
                        "deletes the copy only when that call created it, so this "
                        "wording is what stops an operator reading "
                        "materialized: false as an empty vc-quarantine volume.",
                    )

    def test_a_failed_marker_write_leaves_exactly_what_it_found(self) -> None:
        """Execute the write-failure branch instead of reading it.

        `materialized: false` promises the volume holds nothing from this
        rejection, so the branch removes the copy it wrote. Quarantine names are
        content-addressed, so on a repeat rejection that copy belongs to an
        EARLIER rejection that also published a marker — removing it would
        strand that marker and destroy the bytes RUNBOOK §9 says are retained.
        Both halves are asserted against the real filesystem: a source-text
        assertion cannot see either, which a mutation run proved.
        """
        import os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="v3-quarantine-branch-") as raw:
            root = Path(raw)
            inbox = root / "inbox"
            quarantine = root / "quarantine"
            inbox.mkdir()
            quarantine.mkdir()
            source = inbox / "rejected.bin"
            source.write_bytes(b"hostile payload")

            environment = {
                **os.environ,
                "VCOPS_INBOX_ROOT": str(inbox),
                "VCOPS_QUARANTINE_ROOT": str(quarantine),
            }
            with mock.patch.dict(os.environ, environment, clear=True):
                spec = importlib.util.spec_from_file_location(
                    "v3_quarantine_vcops", ROOT / "workspaces/vc-chief/vc/bin/vcops.py"
                )
                assert spec is not None and spec.loader is not None
                vcops = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = vcops
                spec.loader.exec_module(vcops)

            rejection = vcops.VcopsError("unsupported_format", "unsupported", exit_code=2)
            real_write = vcops.write_content_addressed

            def marker_write_fails(target_root, filename, payload):
                if filename.endswith(".json"):
                    raise OSError(28, "No space left on device")
                return real_write(target_root, filename, payload)

            # First rejection, marker write fails: nothing of this call survives.
            with mock.patch.object(vcops, "write_content_addressed", marker_write_fails):
                first = vcops.quarantine_document(source, rejection)
            self.assertEqual(
                {"materialized": False, "reason": "quarantine_write_failed"}, first
            )
            self.assertEqual(
                [], sorted(p.name for p in quarantine.iterdir()),
                "a failed marker write left an unmarked copy behind while reporting "
                "materialized: false",
            )

            # A rejection that fully succeeds, then a repeat whose marker fails:
            # the earlier recorded copy and marker must both survive.
            recorded = vcops.quarantine_document(source, rejection)
            self.assertTrue(recorded["materialized"], recorded)
            survivors = sorted(p.name for p in quarantine.iterdir())
            with mock.patch.object(vcops, "write_content_addressed", marker_write_fails):
                repeat = vcops.quarantine_document(source, rejection)
            self.assertFalse(repeat["materialized"], repeat)
            self.assertEqual(
                survivors, sorted(p.name for p in quarantine.iterdir()),
                "a later failed rejection deleted the copy an earlier recorded "
                "rejection had published, stranding its metadata marker",
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


class LifecycleLockOwnerFileTests(unittest.TestCase):
    """The stale-lock procedure rests on how the lock is acquired, so read it.

    docs/OPERATIONS.md tells an operator to identify a crash-left lifecycle
    lock from its `owner` file, and now also covers the state where that file
    is absent. The directory is created by `mkdir` and named by a separate
    write a few lines later, with the `*_LOCK_OWNED=1` line the exit trap
    consults sitting between them — so a signal before that flag is set leaves
    the lock on disk, unnamed, and the trap declines to remove it. The
    prescribed `cat`/`ps` identification then dead-ends, which is why the
    document now gives a fallback.

    Two claims that sentence makes are enumerated from `scripts/*.sh` here
    rather than trusted: which scripts take that lock, and that each of their
    acquisitions writes the `owner` line after the `mkdir` and not before it.
    """

    LOCK_PATH = "/tmp/vc-lead-research-v3-lifecycle.lock"

    def _acquisitions(self) -> list[tuple[str, str, str, int, int]]:
        """(script, variable, script text, mkdir start, mkdir end) per `mkdir`."""
        found: list[tuple[str, str, str, int, int]] = []
        for script in sorted((ROOT / "scripts").glob("*.sh")):
            text = script.read_text(encoding="utf-8")
            for variable in re.findall(
                rf'^([A-Z_]+)="{re.escape(self.LOCK_PATH)}"$', text, re.MULTILINE
            ):
                # Tolerate options on the mkdir. Keying on the bare
                # `mkdir "$VAR"` spelling meant respelling an acquisition as
                # `mkdir -m 0700 "$VAR"` silently removed that script from BOTH
                # tests -- the set test failed naming the wrong remedy, and the
                # ordering test simply stopped covering it.
                #
                # The option run consumes any unquoted token, not only tokens
                # that start with `-`: `(?:\s+-\S+)*` broke on the detached
                # argument in `mkdir -m 0700 "$VAR"`, i.e. on the one spelling
                # the comment above offers as the reason for widening. `[ \t]`
                # rather than `\s` keeps the run on the mkdir's own line, so an
                # unrelated `mkdir` earlier in the file cannot reach forward
                # across newlines and manufacture a match.
                matches = list(
                    re.finditer(rf'mkdir(?:[ \t]+[^"\s]+)*[ \t]+"\${variable}"', text)
                )
                if not matches:
                    raise AssertionError(
                        f"scripts/{script.name} assigns {variable} to "
                        f"{self.LOCK_PATH} but this test can no longer see it "
                        "create the directory. The detector has drifted -- widen "
                        "it rather than letting the script leave coverage."
                    )
                for match in matches:
                    found.append((script.name, variable, text, match.start(), match.end()))
        return found

    def test_the_scripts_taking_the_lifecycle_lock_are_the_five_documented(self):
        scripts = {name for name, _, _, _, _ in self._acquisitions()}
        self.assertEqual(
            scripts,
            {"backup.sh", "bootstrap.sh", "restore.sh", "rotate_runtime_role.sh", "update.sh"},
            f"the shell scripts that mkdir {self.LOCK_PATH} changed: "
            f"{sorted(scripts)}. docs/OPERATIONS.md opens its lifecycle-lock "
            "paragraph by naming them — 'Backup, restore, update, bootstrap, and "
            "direct role rotation share ...' — and the stale-lock procedure that "
            "follows is written for exactly those. Update the sentence with this "
            "change rather than relaxing this test.",
        )

    def test_operations_names_every_script_that_takes_the_lifecycle_lock(self):
        """The document is the comparand, not a literal restated in this file.

        The sibling test pins the acquiring scripts against a set written here,
        which proves the scripts agree with *this test* and says nothing about
        docs/OPERATIONS.md — the document the class is named for and whose
        stale-lock procedure is written for exactly those scripts. Both
        enumerations in that document are read here instead: the prose sentence
        that opens the lifecycle-lock paragraph, and the `ps | grep -E` recovery
        command that tells the operator which processes to look for.
        """
        operations = (ROOT / "docs/OPERATIONS.md").read_text(encoding="utf-8")
        acquiring = {name for name, _, _, _, _ in self._acquisitions()}

        prose_names = {
            "Backup": "backup.sh",
            "restore": "restore.sh",
            "update": "update.sh",
            "bootstrap": "bootstrap.sh",
            "direct role rotation": "rotate_runtime_role.sh",
        }
        sentence_start = operations.find("share `/tmp/vc-lead-research-v3-lifecycle.lock`")
        self.assertNotEqual(
            sentence_start, -1,
            "docs/OPERATIONS.md no longer contains the lifecycle-lock sentence "
            "this test reads; restore it or update the anchor",
        )
        # Bound the lookback at the paragraph, not at a character count. A fixed
        # 240-character window reached 179 characters back into the PREVIOUS
        # paragraph, so a script name occurring there satisfied this check for a
        # sentence that no longer named it: dropping `restore` from the
        # lifecycle-lock sentence while the paragraph above happened to mention
        # a restore left the whole suite green.
        paragraph_start = operations.rfind("\n\n", 0, sentence_start) + 2
        sentence = operations[paragraph_start:sentence_start]
        named = {script for word, script in prose_names.items() if word in sentence}
        self.assertEqual(
            named, acquiring,
            "docs/OPERATIONS.md's lifecycle-lock sentence names "
            f"{sorted(named)} but the scripts that actually take the lock are "
            f"{sorted(acquiring)}. Update the sentence.",
        )

        scan = re.search(r"grep -E 'scripts/\(([^)]+)\)\\?\.sh'", operations)
        if scan is None:
            self.fail(
                "docs/OPERATIONS.md no longer contains the `ps | grep -E "
                "'scripts/(...)\\.sh'` recovery scan; an operator clearing a stale "
                "lock has no way to check for a live holder"
            )
        scanned = {f"{name}.sh" for name in scan.group(1).split("|")}
        # migrate.sh does not take this lock, but it mutates the production
        # database, so the scan that decides whether a lock may be cleared must
        # see it. Everything that takes the lock must be there too.
        self.assertTrue(
            acquiring <= scanned,
            "docs/OPERATIONS.md's live-process scan does not look for "
            f"{sorted(acquiring - scanned)}, so an operator would read a running "
            "lifecycle script as absent and clear a live lock",
        )
        self.assertIn(
            "migrate.sh", scanned,
            "docs/OPERATIONS.md's live-process scan omits migrate.sh, the script "
            "that applies migrations to the production database; a run in "
            "progress would be invisible to the operator deciding whether to "
            "clear a lock",
        )

    def test_every_lifecycle_lock_acquisition_names_its_holder_after_the_mkdir(self):
        acquisitions = self._acquisitions()
        self.assertTrue(
            acquisitions,
            f"no shell script under scripts/ was found creating {self.LOCK_PATH}; "
            "this test can no longer see the acquisitions it is meant to check",
        )
        for name, variable, text, start, end in acquisitions:
            with self.subTest(script=name):
                owner_write = f'>"${variable}/owner"'
                # Decide between the two failure modes BEFORE asserting. Written
                # as assertIn-then-assertNotIn, a reordered acquisition failed on
                # the first assertion, so the second one's message -- the only
                # text that explains the ordering rule -- could never print.
                after = owner_write in text[end:end + 400]
                before = owner_write in text[:start]
                if before and not after:
                    self.fail(
                        f"scripts/{name} writes {owner_write} before it creates the "
                        "lock directory. docs/OPERATIONS.md explains a missing "
                        "`owner` file by that write coming second; with this order "
                        "the file can no longer be missing for the documented reason."
                    )
                self.assertTrue(
                    after,
                    f"scripts/{name} creates the lifecycle lock but does not write "
                    f"{owner_write} within 400 characters after the mkdir. "
                    "docs/OPERATIONS.md tells the operator that a crash-left lock "
                    "names its holder in `owner`, and reads a missing `owner` file "
                    "as an acquisition interrupted between those two steps; an "
                    "acquisition that never writes one breaks both readings.",
                )


class CsvFieldLimitDocPinTests(unittest.TestCase):
    """The CSV field ceiling document_intake.md quotes had no source to check.

    That number is the `csv` module's own `field_size_limit()` default, not one
    of the compiled-in `bin/vcops.py` constants the document's other extractor
    bounds point at, so a reader had nothing to grep and prose was its only
    home. Bind it to the interpreter instead.
    """

    def test_document_intake_csv_field_ceiling_matches_the_interpreter(self):
        import csv

        # The document attributes its figure to the image's interpreter; this
        # test reads `field_size_limit()` from whichever interpreter runs the
        # suite. Both were measured at 131072 for this release (dev venv 3.14.5,
        # and 3.11.2 in vc-lead-research:3.0.0 via `docker run --rm
        # --entrypoint python3`), so the substitution holds today — but only the
        # running one is checked here: were the image's default ever to diverge
        # from the dev interpreter's, this test would stay green while the
        # document's figure was wrong for the image it names.
        text = (ROOT / "workspaces/vc-chief/vc/document_intake.md").read_text(encoding="utf-8")
        match = re.search(r"field_size_limit\(\)`, measured at ([0-9]+) characters", text)
        if match is None:
            self.fail(
                "document_intake.md no longer says 'measured at N characters' "
                "after its field_size_limit() mention, so the CSV field ceiling "
                "it quotes is bound to nothing again"
            )
        self.assertEqual(
            int(match.group(1)),
            csv.field_size_limit(),
            f"document_intake.md states a CSV field ceiling of {match.group(1)} "
            f"characters; csv.field_size_limit() under {sys.version.split()[0]} "
            f"is {csv.field_size_limit()}. Re-measure on the image interpreter "
            "the document names and update the sentence.",
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


# The scripts the documented-invocation scan reaches today, pinned as a set so
# both directions of drift fail: a script that stops matching takes its
# documented flags out of coverage with it, and a newly documented script has to
# be added deliberately.
COVERED_INVOCATION_SCRIPTS = frozenset({
    "backup.sh",
    "bootstrap.sh",
    "build_release_manifest.py",
    "check_customization.py",
    "check_env.sh",
    "init_customization.py",
    "record_images.py",
    "render_channel_config.py",
    "restore.sh",
    "run_g4.py",
    "run_g6_image.py",
    "update.sh",
    "verify_offline.py",
    "verify_release.py",
})


class DocumentedInvocationTests(unittest.TestCase):
    """Commands the documents tell the operator to run must be runnable.

    Two defect classes converge here, and both have been observed. The
    fifteenth pass's own fix wave put a `git grep` recipe into RUNBOOK §8.1
    that dies with `Unimplemented pathspec magic` on the shipped git version —
    written, never executed. Its planted-defect calibration separately seeded a
    documented `--force` flag that `init_customization.py` does not accept, and
    five reviewers had to be paid to find it.

    A documented invocation is checkable without executing anything dangerous:
    the script must exist, and a long flag read off the command line must
    appear, quoted, in that script's source. What the scan reaches is bounded
    by construction rather than by accident, in the idiom
    `HostUtilityEnumerationTests` above uses:

    - It reads fenced `sh` blocks in tracked documents and matches names
      written as `scripts/<name>.py` or `scripts/<name>.sh`, with or without a
      leading `./`.
    - Flags are taken from the run of dash-prefixed tokens adjacent to the
      script name, so a flag written after a positional argument is not read:
      README writes `./scripts/restore.sh <directory>
      --confirm-destructive-restore` that way. Reading the rest of the line
      instead would attribute a later pipeline stage's flags to the script.
    - The quoted-substring oracle fits argparse, where `add_argument("--x")`
      quotes the flag it defines. It fits shell scripts poorly in both
      directions: a shell script need not quote the flag it parses, and
      `schedule_jobs.sh` quotes `--no-deliver`, which it passes through to the
      OpenClaw CLI rather than parsing itself. The `.sh` half of this check
      earns its place for script existence, not for flag validity.
    """

    # Absolute in-image paths (e.g. /app/skills/skill-creator/scripts/...) are
    # deliberately not package scripts; RUNBOOK §8.1 says so where it uses one.
    # The `./` prefix is consumed by the pattern rather than blocked by the
    # lookbehind, so `./scripts/x.py` is in scope while `.../skills/.../scripts/`
    # stays out.
    INVOCATION = re.compile(r"(?<![\w/])(?:\./)?scripts/([A-Za-z0-9_]+\.(?:py|sh))((?:\s+-{1,2}[A-Za-z0-9][\w-]*(?:[= ][^\s`|>]+)?)*)")
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
                    entry = found.setdefault(script, {"flags": {}, "docs": set()})
                    relative = path.relative_to(ROOT).as_posix()
                    # Flags are keyed by the document that wrote them. Keeping a
                    # flat set meant the offender line named every document that
                    # invokes the script, sending the reader to files that do
                    # not contain the flag.
                    for flag in self.LONG_FLAG.findall(tail):
                        entry["flags"].setdefault(flag, set()).add(relative)
                    entry["docs"].add(relative)
        return found

    def test_every_documented_script_exists(self):
        found = self.documented_invocations()
        # The covered SET, not a floor. A floor two below the measured world let
        # a reworded path prefix drop a script -- and any nonexistent flag it
        # documented -- out of scope while the guard stayed green. This is the
        # same shift COVERED_SKILL_COUNT_DOCUMENTS and OFFLINE_TOTAL_CLAIM_SITES
        # already make: pin identity, so both directions of drift fail here.
        self.assertEqual(
            set(found), COVERED_INVOCATION_SCRIPTS,
            "the documented-invocation scan's reach moved: "
            f"gone {sorted(COVERED_INVOCATION_SCRIPTS - set(found))}, "
            f"new {sorted(set(found) - COVERED_INVOCATION_SCRIPTS)}. A script "
            "that silently leaves this set takes its documented flags out of "
            "coverage with it; update the constant only when the change is "
            "deliberate.",
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

    def test_every_documented_flag_appears_in_its_script(self):
        offenders = {}
        for script, entry in self.documented_invocations().items():
            source_path = ROOT / "scripts" / script
            if not source_path.is_file():
                continue  # reported by the sibling test
            source = source_path.read_text(encoding="utf-8")
            if script.endswith(".py"):
                # Build the oracle from the parser, not the file. A quoted-substring
                # search over the whole source also matched a flag the script merely
                # FORWARDS to a subprocess, so `verify_offline.py --pristine` -- which
                # that script does not accept and which exits 2 -- was invisible here.
                accepted = set(re.findall(r'add_argument\(\s*["\'](--[A-Za-z][\w-]*)', source))
                accepted.add("--help")
            else:
                # Shell scripts need not quote the flags they parse, so the
                # substring oracle stays for them; see the class docstring.
                accepted = None
            for flag, documents in sorted(entry["flags"].items()):
                bad = (
                    flag not in accepted if accepted is not None
                    else (f'"{flag}"' not in source and f"'{flag}'" not in source)
                )
                if bad:
                    offenders.setdefault(script, []).append(
                        f"{flag} (documented in {', '.join(sorted(documents))})"
                    )
        self.assertEqual(
            offenders, {},
            "documents pass flags these scripts do not accept, so the "
            f"documented command fails for the operator: {offenders}",
        )

if __name__ == "__main__":
    unittest.main()
