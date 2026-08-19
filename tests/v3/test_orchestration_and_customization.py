# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# Importing a script byte-compiles it into scripts/__pycache__, which
# `verify_release.py --pristine` then reports as an undeclared file. Suppress
# that one source of debris, the way tests/v3/test_doc_tree_consistency.py
# does. This does NOT make the suite safe to run without `-B`: the runner
# still caches the test modules themselves into tests/v3/__pycache__, which
# fails --pristine just as loudly. Run the suites with `-B`, as the offline
# gate does.
sys.dont_write_bytecode = True

import check_env  # noqa: E402


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys, which plain json.loads silently resolves last-wins."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


# Every shipped artifact that encodes the recommendation band EDGES, and what
# CUSTOMIZATION.md must say about it. The world is derived from the rubric's own
# interval minima below, so this map is a set of DISPOSITIONS, not the world
# itself: an artifact that starts naming an edge and is in neither the row nor
# this map fails the test until someone categorises it consciously. That is the
# erasure-gap pattern from CLAUDE.md, applied to band edges.
#
# The row omitted eval_fixtures.md, tests/g3/README.md and docs/DATA_MODEL.md,
# and an operator who followed it end to end shipped three artifacts still
# stating 50/66/82 with every offline suite green.
BAND_EDGE_DISPOSITIONS = {
    # Superseded: 004 drops 001's inline CHECK and adds its own; 007 drops and
    # recreates 004's `evaluations_score_band_check`. Only 007's edges are live.
    # These files must NOT be listed as things to edit -- `migrate.sh` compares
    # each applied migration against its recorded checksum and fails closed.
    "migrations/001_initial_v2.sql": "superseded",
    "migrations/004_domain_contract_hardening.sql": "superseded",
    # Derives the edges from the rubric at runtime; its literals are worked
    # examples in a docstring, re-derived by the test body itself.
    "tests/g4/test_semantics.py": "derived",
}


class BandEdgeCustomizationSurfaceTests(unittest.TestCase):
    """Everything that hard-codes a band edge is either in the procedure or dispositioned.

    The bands are `sample_only_must_customize` and CUSTOMIZATION.md carries the
    procedure for changing them. A shipped artifact that states the shipped edges
    but is absent from that procedure is a trap: the operator follows the row to
    the end, every offline suite passes, and their deployment still documents
    bands it no longer uses.

    Walked end to end on a scratch copy at ed23f35 -- edited both rubric files to
    40/60/80, edited the CHECK in 007, re-cut all eight rows of
    scoring_boundary_cases.jsonl and all six edge cases in semantic_cases.json --
    and all nine offline suites went green with three artifacts still stating the
    old edges.
    """

    @classmethod
    def setUpClass(cls) -> None:
        rubric = json.loads(
            (ROOT / "workspaces/vc-chief/vc/scoring-rubric.v3.json").read_text(encoding="utf-8")
        )
        intervals = rubric["recommendation_intervals"]
        cls.edges = sorted({int(i["minimum"]) for i in intervals if int(i["minimum"]) > 0})
        cls.band_names = sorted({str(i["name"]) for i in intervals})
        cls.row = next(
            (line for line in (ROOT / "CUSTOMIZATION.md").read_text(encoding="utf-8").split("\n")
             if line.startswith("| Scoring criteria, weights, missingness, thresholds |")),
            "",
        )

    def test_the_band_row_names_every_artifact_that_encodes_an_edge(self) -> None:
        self.assertTrue(self.edges, "the rubric declares no interior band edge")
        self.assertTrue(
            self.row, "CUSTOMIZATION.md's scoring row has been retitled; this binding is blind"
        )

        # An edge value is only interesting where it sits with a band name (the
        # arithmetic), where it appears as an interval endpoint (the notation), or
        # as the just-below probe value fixtures use. Matching the bare integer
        # would collect `MAX_SHEETS = 50` and say nothing.
        edge_pattern = re.compile(
            r"(?<![\d.])(" + "|".join(str(edge) for edge in self.edges) + r")(?![\d])"
        )
        probe_pattern = re.compile(
            r"(?<![\d.])(" + "|".join(f"{edge - 1}\\.999" for edge in self.edges) + r")"
        )
        # 'pass' and 'watch' are ordinary English words; the two compound band
        # names are not, so they identify a band context without false hits.
        name_pattern = re.compile(
            "|".join(re.escape(name) for name in self.band_names if "_" in name)
        )
        # `\[\d+, ` on the closing side, not a bare `, 50)`: vcops.py's
        # `int(os.environ.get("VCOPS_MAX_SHEETS", 50))` is not an interval, and a
        # detector that says it is trains the reader to ignore this test.
        interval_pattern = re.compile(
            "|".join(
                rf"\[{edge},|\[\d+, {edge}\)" for edge in self.edges
            )
        )

        world: dict[str, list[str]] = {}
        for path in sorted(ROOT.rglob("*")):
            relative = path.relative_to(ROOT).as_posix()
            if (
                not path.is_file()
                or relative.startswith("_internal/")
                or ".git/" in relative
                or "__pycache__" in relative
                or path.suffix not in {".md", ".json", ".jsonl", ".sql", ".py"}
            ):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            reasons = set()
            for line in text.split("\n"):
                if probe_pattern.search(line):
                    reasons.add("boundary probe value")
                if edge_pattern.search(line) and name_pattern.search(line):
                    reasons.add("edge beside a band name")
                if interval_pattern.search(line):
                    reasons.add("edge as an interval endpoint")
            if reasons:
                world[relative] = sorted(reasons)

        self.assertGreaterEqual(
            len(world), 8,
            f"only {len(world)} artifacts matched; the detector has rotted and "
            f"would pass while naming almost nothing",
        )
        # CUSTOMIZATION.md itself now quotes the values while telling operators
        # what to change, which is the procedure, not a drifted artifact.
        world.pop("CUSTOMIZATION.md", None)

        undocumented = {
            relative: reasons for relative, reasons in world.items()
            if relative not in self.row and relative not in BAND_EDGE_DISPOSITIONS
        }
        self.assertEqual(
            {}, undocumented,
            f"these shipped artifacts encode the band edges {self.edges} but "
            f"CUSTOMIZATION.md's band-change row never names them, and they carry "
            f"no disposition: {json.dumps(undocumented, indent=2, sort_keys=True)}. "
            f"An operator who follows that row end to end passes every offline "
            f"suite with these still stating the shipped edges. Either add the "
            f"path to the row, or add it to BAND_EDGE_DISPOSITIONS with the reason "
            f"its edges need no change.",
        )

        stale = [
            relative for relative in BAND_EDGE_DISPOSITIONS
            if relative not in world and (ROOT / relative).exists()
        ]
        self.assertEqual(
            [], stale,
            f"{stale} carry a band-edge disposition but no longer encode an edge; "
            f"a disposition that describes nothing hides the next real one",
        )
        missing = [
            relative for relative in BAND_EDGE_DISPOSITIONS
            if not (ROOT / relative).exists()
        ]
        self.assertEqual([], missing, f"dispositioned paths that no longer exist: {missing}")

    def test_no_document_claims_a_file_is_reviewed_when_it_is_not(self) -> None:
        """"One of the twenty hash-pinned reviewed artifacts" must be true of the file it names.

        CUSTOMIZATION.md carried that sentence attached to
        `tests/g4/semantic_cases.json`, which is not one of the twenty. The
        consequence is not cosmetic: it tells an operator their edit fails closed
        at the next lifecycle run when nothing checks that file's hash at all, so
        they skip the coverage they actually have (re-cutting it for the
        g4-semantics suite) believing a gate has them covered.

        The eighteenth pass's round-6 repair then REWROTE that sentence and
        preserved the false half, which is why this is a test and not a fix.
        `check_customization.py` owns the real list, so read it from there.
        """
        import check_customization

        reviewed = set(check_customization.REQUIRED_REVIEWED_ARTIFACTS)
        self.assertEqual(
            20, len(reviewed),
            f"the reviewed-artifact set is {len(reviewed)}, not twenty; every "
            f"document that says 'the twenty' is now wrong",
        )
        # Work in CLAUSES, not in a lookahead window. The first version of this
        # check used `[^.`]{0,120}` between the path and the claim, and a
        # backtick in that span -- i.e. any second path named in the same
        # sentence -- ended the match. Measured: restoring the exact false claim
        # this test exists for left it GREEN, because the true path sat between
        # the false one and the words "among the twenty".
        claim = re.compile(r"(?:one of the twenty|among the twenty)")
        negation = re.compile(r"\b(?:not|never|neither)\b", re.IGNORECASE)
        # A bare path, not a command line: `scripts/init_customization.py
        # --update-hashes` names a file but is an instruction, not a claim about
        # membership, so require a single whitespace-free token with a suffix.
        path_token = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")

        offenders: list[str] = []
        checked = 0
        for name in ("CUSTOMIZATION.md", "docs/RUNBOOK.md", "docs/OPERATIONS.md", "README.md"):
            document = ROOT / name
            if not document.is_file():
                continue
            for line in document.read_text(encoding="utf-8").split("\n"):
                for clause in re.split(r"(?<=[.;])\s+", line):
                    if not claim.search(clause) or negation.search(clause):
                        continue
                    for candidate in path_token.findall(clause):
                        if "/" not in candidate:
                            continue
                        checked += 1
                        if candidate not in reviewed:
                            offenders.append(f"{name}: {candidate}")
        self.assertGreater(
            checked, 0,
            "no document names a file alongside the twenty-reviewed-artifacts "
            "claim; either the phrasing moved or this check is now blind",
        )
        self.assertEqual(
            [], offenders,
            f"these documents call a file one of the twenty hash-pinned reviewed "
            f"artifacts when check_customization.py does not list it: {offenders}. "
            f"An operator reads that as 'my edit fails closed if I forget to "
            f"re-pin', and skips the coverage that actually applies.",
        )

    def test_the_two_superseded_migrations_really_are_superseded(self) -> None:
        """The disposition above is an arithmetic claim about the migration series.

        If it is wrong, CUSTOMIZATION.md now tells operators NOT to edit a file
        whose CHECK is still live, and their own bands would violate it at
        persistence. So verify the supersession rather than asserting it in a
        comment: the constraint each earlier migration adds must be dropped by a
        later one, and the last migration to add a band-edge CHECK is the one the
        row sends the operator to.
        """
        series = sorted((ROOT / "migrations").glob("*.sql"))
        self.assertTrue(series, "no migrations found")
        adds: list[tuple[str, str]] = []
        drops: dict[str, list[str]] = {}
        for path in series:
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"ADD CONSTRAINT (\w+) CHECK", text, re.IGNORECASE
            ):
                name = match.group(1)
                start = match.end()
                clause = text[start:start + 1200]
                if any(f"total_score >= {edge}" in clause for edge in self.edges):
                    adds.append((path.name, name))
            for match in re.finditer(
                r"DROP CONSTRAINT IF EXISTS (\w+)", text, re.IGNORECASE
            ):
                drops.setdefault(match.group(1), []).append(path.name)

        self.assertTrue(adds, "no migration adds a band-edge CHECK; the detector has rotted")
        # 001's edge CHECK is inline and unnamed; PostgreSQL names it
        # `evaluations_check`, which is what 004 drops.
        inline_dropped_by = drops.get("evaluations_check", [])
        self.assertTrue(
            inline_dropped_by,
            "no migration drops `evaluations_check`, so 001's inline band-edge "
            "CHECK is still live and an operator editing only 007 gets rows that "
            "violate it",
        )
        for source, name in adds[:-1]:
            with self.subTest(migration=source, constraint=name):
                later = [
                    other for other in drops.get(name, [])
                    if other > source
                ]
                self.assertTrue(
                    later,
                    f"{source} adds band-edge CHECK {name} and no later migration "
                    f"drops it, so its edges are still enforced. "
                    f"CUSTOMIZATION.md tells the operator to edit only "
                    f"{adds[-1][0]}, which would leave their own bands failing at "
                    f"persistence.",
                )
        self.assertIn(
            adds[-1][0], self.row,
            f"the last migration to add a band-edge CHECK is {adds[-1][0]}, but "
            f"CUSTOMIZATION.md's row does not name it",
        )


class Version3ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((ROOT / "config/openclaw.json").read_text(encoding="utf-8"))
        self.agents = {agent["id"]: agent for agent in self.config["agents"]["list"]}

    def test_canonical_schemas_are_valid_draft_2020_12(self) -> None:
        schemas = sorted((ROOT / "workspaces/schemas").glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 4)
        for path in schemas:
            schema = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(schema=path.name):
                Draft202012Validator.check_schema(schema)

    def test_release_has_complete_agent_skill_and_research_inventory(self) -> None:
        agent_ids = [agent["id"] for agent in self.config["agents"]["list"]]
        self.assertEqual(len(agent_ids), 12)
        for agent_id in agent_ids:
            workspace = ROOT / "workspaces" / agent_id
            for filename in ("AGENTS.md", "SOUL.md", "TOOLS.md", "USER.md"):
                with self.subTest(agent=agent_id, file=filename):
                    self.assertTrue((workspace / filename).is_file())

        expected_dossiers = [
            "01-lead-signal-detector.md", "02-lead-router.md", "03-outbound-scout.md",
            "04-inbound-intake-analyst.md", "05-document-intake-analyst.md",
            "06-founder-researcher.md", "07-traction-analyst.md", "08-market-mapper.md",
            "09-qualification-analyst.md", "10-memo-writer.md", "11-data-steward.md",
            "12-vc-chief-orchestrator.md",
        ]
        actual_dossiers = sorted(path.name for path in (ROOT / "research/agents").glob("*.md"))
        self.assertEqual(actual_dossiers, expected_dossiers)
        for filename in expected_dossiers:
            content = (ROOT / "research/agents" / filename).read_text(encoding="utf-8").lower()
            for required in (
                "current contract", "quantitative", "practitioner", "counterevidence",
                "proposed", "rejected imports", "precommitted eval",
            ):
                with self.subTest(dossier=filename, section=required):
                    self.assertIn(required, content)
            self.assertIn("2026-07-20", content)
            self.assertIn("https://", content)

        skill_names = []
        for skill_file in sorted((ROOT / "workspaces/shared-skills").glob("*/SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("---\n"), skill_file)
            match = re.search(r"(?m)^name:\s*([^\s]+)\s*$", text)
            if match is None:
                self.fail(f"{skill_file} has no frontmatter name")
            skill_names.append(match.group(1))
        self.assertEqual(26, len(skill_names))
        self.assertEqual(len(skill_names), len(set(skill_names)))
        configured_skills = {
            skill for agent in self.config["agents"]["list"] for skill in agent.get("skills", [])
        }
        self.assertEqual(set(skill_names), configured_skills)
        resolver = (ROOT / "workspaces/vc-chief/vc/RESOLVER.md").read_text(encoding="utf-8")
        self.assertIn("discovers 26 shared skills", resolver)
        self.assertIn("`controlled-evolution`", resolver)
        workshop = self.config["skills"]["workshop"]
        self.assertEqual({"enabled": False}, workshop["autonomous"])
        self.assertEqual("pending", workshop["approvalPolicy"])
        self.assertFalse(workshop["allowSymlinkTargetWrites"])
        self.assertNotIn("skill_workshop", self.config["tools"]["deny"])
        self.assertIn("skill_workshop", self.config["tools"]["subagents"]["tools"]["deny"])
        for agent in self.config["agents"]["list"]:
            if agent["id"] == "vc-chief":
                self.assertIn("skill_workshop", agent.get("tools", {}).get("allow", []))
                self.assertNotIn("skill_workshop", agent.get("tools", {}).get("deny", []))
            else:
                self.assertNotIn("skill_workshop", agent.get("tools", {}).get("allow", []))
                self.assertIn("skill_workshop", agent.get("tools", {}).get("deny", []))

    def test_required_assessment_and_release_decision_files_exist(self) -> None:
        for relative in (
            "00_RESEARCH_AND_IMPLEMENTATION_PLAN.md",
            "01_PRECOMMITTED_EVALS.md",
            "02_BASELINE_ASSESSMENT_AND_CHANGE_GATE.md",
            "03_CURRENT_DOCUMENT_ASSESSMENT.md",
            "CUSTOMIZATION.md",
            "research/13-memory-retrieval.md",
            "evals/V3_EVAL_RESULTS.md",
            "docs/V3_RELEASE_EVIDENCE.md",
        ):
            with self.subTest(file=relative):
                self.assertTrue((ROOT / relative).is_file())
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "3.0.0")
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["package_version"], "3.0.0")

    def test_only_chief_can_spawn_and_only_steward_can_exec(self) -> None:
        spawners = {
            agent_id
            for agent_id, agent in self.agents.items()
            if "sessions_spawn" in agent["tools"]["allow"]
        }
        executors = {
            agent_id
            for agent_id, agent in self.agents.items()
            if "exec" in agent["tools"]["allow"]
        }
        self.assertEqual(spawners, {"vc-chief"})
        self.assertEqual(executors, {"data-steward"})

    def test_specialists_have_no_markdown_memory_tools(self) -> None:
        for agent_id, agent in self.agents.items():
            with self.subTest(agent=agent_id):
                allowed = set(agent["tools"]["allow"])
                self.assertTrue({"memory_search", "memory_get"}.isdisjoint(allowed))
                self.assertFalse(agent.get("memorySearch", {}).get("enabled", False))
        defaults = self.config["agents"]["defaults"]
        self.assertFalse(defaults["memorySearch"]["enabled"])
        self.assertFalse(defaults["compaction"]["memoryFlush"]["enabled"])
        self.assertEqual(defaults["memorySearch"]["provider"], "none")
        self.assertNotIn("memory-core", self.config["plugins"]["allow"])

    def test_channel_overlays_preserve_disabled_memory_and_exact_plugin_scope(self) -> None:
        profiles = {
            "slack": "channel-slack.socket.json5",
            "msteams": "channel-msteams.json5",
            "discord": "channel-discord.json5",
            "telegram": "channel-telegram.json5",
        }
        for profile, filename in profiles.items():
            with self.subTest(profile=profile):
                # Strict JSON with the renderer's duplicate-key rejection
                # (scripts/render_channel_config.py load_strict_json): a second
                # "plugins" or "bindings" key would otherwise win last-wins here
                # and pass, while docs/CHANNELS.md promises these tests parse the
                # overlays the way the renderer does.
                overlay = json.loads(
                    (ROOT / "config" / filename).read_text(encoding="utf-8"),
                    object_pairs_hook=unique_object,
                )
                self.assertNotIn("plugins", overlay)
                self.assertEqual(
                    overlay["bindings"],
                    [{"agentId": "vc-chief", "match": {"channel": profile, "accountId": "default"}}],
                )

    def test_documented_tool_allowlists_equal_runtime_config(self) -> None:
        for agent_id, agent in self.agents.items():
            text = (ROOT / "workspaces" / agent_id / "TOOLS.md").read_text(encoding="utf-8")
            allowed_block = text.split("## Allowed tool IDs", 1)[1].split("## Denied tool IDs", 1)[0]
            documented = {
                line.removeprefix("- `").removesuffix("`")
                for line in allowed_block.splitlines()
                if line.startswith("- `") and line.endswith("`")
            }
            with self.subTest(agent=agent_id):
                self.assertEqual(documented, set(agent["tools"]["allow"]))

    def test_concurrency_and_exec_timeouts_match_policy(self) -> None:
        defaults = self.config["agents"]["defaults"]["subagents"]
        self.assertEqual(defaults["maxConcurrent"], 3)
        self.assertEqual(defaults["maxChildrenPerAgent"], 3)
        self.assertEqual(defaults["maxSpawnDepth"], 1)
        self.assertGreaterEqual(defaults["runTimeoutSeconds"], 45 * 60)
        self.assertGreaterEqual(self.config["tools"]["exec"]["timeoutSec"], 420)
        self.assertGreaterEqual(self.agents["data-steward"]["tools"]["exec"]["timeoutSec"], 420)
        depth = (ROOT / "workspaces/vc-chief/vc/research_depth.md").read_text(encoding="utf-8")
        self.assertIn("cap active children at three", depth)

    def test_chief_requires_pre_eval_before_spawn_and_post_eval_before_acceptance(self) -> None:
        contract = (ROOT / "workspaces/vc-chief/AGENTS.md").read_text(encoding="utf-8")
        pre_index = contract.index("Before every spawn")
        spawn_index = contract.index("sessions_spawn")
        self.assertLess(pre_index, spawn_index)
        self.assertIn("delegation-eval.schema.json", contract)
        self.assertIn("return-assessment.schema.json", contract)
        self.assertIn("A child never grades itself", contract)
        self.assertIn("Never average agent confidence", contract)

    def test_delegation_eval_requires_positive_and_falsification_oracles(self) -> None:
        schema = json.loads(
            (ROOT / "workspaces/schemas/delegation-eval.schema.json").read_text(encoding="utf-8")
        )
        digest = "0" * 64
        packet = {
            "schema_version": "3.0",
            "task_id": "task-1",
            "lead_id": "lead-1",
            "run_id": "run-1",
            "identifier_state": "present",
            "identifier_null_reason": None,
            "agent": "market-mapper",
            "decision_question": "Which buyer and budget path could falsify the wedge?",
            "why_this_agent": "Market structure is the bounded unresolved capability.",
            "dependencies": [{"task_id": "resolve-1", "status": "passed", "evidence_ref": "resolution-1"}],
            "dependency_packet_hash": digest,
            "authoritative_inputs": [{"id": "fact-1", "type": "verified_fact", "status": "current", "locator": "db:fact-1"}],
            "contradictions_to_resolve": [],
            "allowed_sources": ["public_primary"],
            "prohibited_actions": ["contact subjects", "write externally"],
            "policy_packets": [{"name": "thesis", "version": "3.0", "sha256": digest}],
            "budget": {"max_sources": 8, "max_minutes": 15, "max_cost": 0, "currency": "EUR"},
            "expected_schema": {"id": "market-mapper.output", "version": "3.0", "sha256": digest},
            "acceptance_tests": [
                {"test_id": "positive", "kind": "positive", "assertion": "Names the buyer and budget", "measurement": "field presence plus citation", "pass_condition": "both present"},
                {"test_id": "falsifier", "kind": "falsification", "assertion": "Does not promote an uncited TAM", "measurement": "claim ledger", "pass_condition": "zero uncited TAM facts"},
            ],
            "evidence_requirements": {"freshness_cutoff": "2025-07-20T00:00:00Z", "material_claim_citations": True, "direct_source_required": True},
            "stop_conditions": ["question answered", "budget exhausted"],
            "downstream_consumer": "qualification-input",
            "on_failure": "insufficient_evidence",
        }
        Draft202012Validator(schema).validate(packet)
        packet["acceptance_tests"] = [packet["acceptance_tests"][0]]
        with self.assertRaises(ValidationError):
            Draft202012Validator(schema).validate(packet)

    def test_example_customization_profile_fails_closed(self) -> None:
        result = subprocess.run(
            [
                "python3",
                str(ROOT / "scripts/check_customization.py"),
                str(ROOT / "config/customization-profile.example.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertEqual(report["result"], "FAIL")

    def test_required_customization_markers_resolve_to_real_files(self) -> None:
        required = [
            ROOT / ".env.example",
            ROOT / "workspaces/outbound-scout/USER.md",
            ROOT / "workspaces/vc-chief/USER.md",
            ROOT / "workspaces/vc-chief/vc/thesis.md",
            ROOT / "workspaces/vc-chief/vc/exclusion_criteria.md",
            ROOT / "workspaces/vc-chief/vc/prequalification.md",
            ROOT / "workspaces/vc-chief/vc/scoring-rubric.md",
            ROOT / "workspaces/vc-chief/vc/primary_sources.md",
            ROOT / "workspaces/vc-chief/vc/active_sourcing.md",
            ROOT / "workspaces/vc-chief/vc/passive_sourcing.md",
            ROOT / "workspaces/vc-chief/vc/inbound_sources.md",
            ROOT / "workspaces/vc-chief/vc/research_depth.md",
            ROOT / "workspaces/vc-chief/vc/approval-policy.md",
            ROOT / "workspaces/vc-chief/vc/trust_boundaries.md",
            ROOT / "workspaces/vc-chief/vc/storage_tiers.md",
            ROOT / "workspaces/vc-chief/vc/data_retention.md",
            ROOT / "workspaces/vc-chief/vc/channel_policy.md",
            ROOT / "workspaces/vc-chief/vc/notification_policy.md",
            ROOT / "workspaces/vc-chief/vc/third_party_connectors.md",
        ]
        for path in required:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertTrue(path.is_file())
                self.assertIn("[MUST_CUSTOMIZE]", path.read_text(encoding="utf-8"))
        guide = (ROOT / "CUSTOMIZATION.md").read_text(encoding="utf-8")
        self.assertIn("`MUST_CUSTOMIZE`", guide)
        self.assertIn("`REVIEW_AND_CONFIRM`", guide)
        self.assertIn("`DO_NOT_CUSTOMIZE_DIRECTLY`", guide)

    @staticmethod
    def reviewed_profile() -> dict:
        """Build the smallest profile scripts/check_customization.py accepts.

        Every value here is what an accountable reviewer would have written:
        the review flags set true, real hashes for the reviewed artifacts, and a
        models/search selection that matches the environment
        reviewed_env_body() renders beside it. That the flag set is complete is
        not asserted here but by test_reviewed_customization_profile_can_pass,
        which requires the validator to answer PASS on what this returns.
        """
        profile = json.loads(
            (ROOT / "config/customization-profile.example.json").read_text(encoding="utf-8")
        )
        profile.update(
            {
                "status": "reviewed",
                "organization": {
                    "name": "Example Fund",
                    "timezone": "Europe/Berlin",
                    "deployment_owner": "operator-1",
                },
                "review": {
                    "approved_by": "reviewer-1",
                    "approved_at": "2026-07-20T12:00:00Z",
                    "change_record": "CR-1",
                    "reviewed_artifacts": {},
                },
            }
        )
        profile["investment_policy"].update(
            {
                "fund_strategy": "seed_vc",
                "stages": ["seed"],
                "sectors": ["developer tools"],
                "geographies": ["Europe"],
                "hard_exclusions_reviewed": True,
                "rubric_reviewed": True,
                "rubric_id": "example-seed-v1",
                "rubric_backtest_record": "evals/rubric-1",
            }
        )
        for section, key in (
            ("operating_policy", "research_profiles_reviewed"),
            ("operating_policy", "source_allowlist_reviewed"),
            ("operating_policy", "cost_budget_reviewed"),
            ("operating_policy", "memo_template_reviewed"),
            ("models", "untrusted_input_policy_reviewed"),
            ("models", "provider_selection_reviewed"),
            ("search", "provider_selection_reviewed"),
            ("search", "source_quality_reviewed"),
            ("approvals", "separation_of_duties_reviewed"),
            ("privacy_retention", "lawful_bases_reviewed"),
            ("privacy_retention", "confidentiality_classes_reviewed"),
            ("privacy_retention", "retention_schedule_reviewed"),
            ("privacy_retention", "deletion_and_legal_hold_tested"),
            ("privacy_retention", "remote_processor_reviewed"),
            ("channels", "stable_identity_allowlist_reviewed"),
            ("channels", "attachment_intake_reviewed"),
            ("channels", "preference_memory_reviewed"),
            ("agent_profile", "schema_and_eval_updates_completed"),
        ):
            profile[section][key] = True
        profile["models"].update(
            {"provider": "custom", "primary": "provider/model-primary", "fast": "provider/model-fast", "benchmark_record": "evals/models-1"}
        )
        profile["search"].update(
            {"provider": "duckduckgo", "fetch_provider": "default", "evaluation_record": "evals/search-1"}
        )
        profile["approvals"].update(
            {"stable_approver_ids": ["approver-1"], "allowed_channel_ids": []}
        )
        profile["privacy_retention"]["jurisdictions"] = ["DE"]
        example_artifacts = json.loads(
            (ROOT / "config/customization-profile.example.json").read_text(encoding="utf-8")
        )["review"]["reviewed_artifacts"]
        artifact_paths = profile["review"]["reviewed_artifacts"] = dict.fromkeys(
            example_artifacts, ""
        )
        for relative in artifact_paths:
            artifact_paths[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        return profile

    @staticmethod
    def reviewed_env_body(overrides: dict[str, str]) -> str:
        """Render .env.example with whole KEY=VALUE lines replaced.

        Line-anchored, not substring: .env.example carries a commented
        custom-provider worked example (VC_CUSTOM_PROVIDER_ID=anthropic and
        three siblings), and a substring replace of a bare `KEY=` rewrites that
        comment instead of the live line. Raises if a key names no live line,
        so a renamed variable fails here rather than silently doing nothing.
        """
        lines = (ROOT / ".env.example").read_text(encoding="utf-8").split("\n")
        applied: set[str] = set()
        for index, line in enumerate(lines):
            if line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0]
            if key in overrides:
                lines[index] = f"{key}={overrides[key]}"
                applied.add(key)
        if applied != set(overrides):
            raise AssertionError(
                f".env.example has no assignment line for: {sorted(set(overrides) - applied)}"
            )
        return "\n".join(lines)

    def test_reviewed_customization_profile_can_pass(self) -> None:
        profile = self.reviewed_profile()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            env_path = Path(directory) / "reviewed.env"
            env_path.write_text(
                self.reviewed_env_body(
                    {
                        "VC_PRIMARY_MODEL": "provider/model-primary",
                        "VC_FAST_MODEL": "provider/model-fast",
                        "VC_MODEL_PROVIDER": "custom",
                        "VC_WEB_SEARCH_PROVIDER": "duckduckgo",
                    }
                ),
                encoding="utf-8",
            )
            env_path.chmod(0o600)
            result = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts/check_customization.py"),
                    str(path),
                    str(env_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            profile["models"]["fast"] = "provider/different-model"
            path.write_text(json.dumps(profile), encoding="utf-8")
            mismatch = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts/check_customization.py"),
                    str(path),
                    str(env_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["result"], "PASS")
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("models.fast does not match", mismatch.stdout)

    def test_model_reference_verdicts_are_pinned_across_both_validators(self) -> None:
        """Both validators must leave a deployable model id in reach.

        `check_customization.py` binds `models.primary`/`models.fast` to
        `VC_PRIMARY_MODEL`/`VC_FAST_MODEL` byte for byte, so a shape check_env
        accepts and the profile refuses is a value no operator can deploy:
        writing it fails the profile check, and writing anything else fails the
        binding. The seven rows below are verdicts measured against both
        validators, recorded rather than re-derived from their source.

        `hf/` is the one deliberate disagreement: check_env requires a slash and
        a prefix equal to the configured provider, while the profile
        additionally requires a non-empty model id after the slash. The closing
        assertion is over these seven rows — no sampled shape with a non-empty
        id after the first slash is accepted by check_env and refused by the
        profile.
        """
        shapes = (
            # (model reference, check_env accepts, check_customization accepts)
            ("openai/gpt-5.6", True, True),
            ("ollama/qwen3:14b", True, True),
            ("hf/meta-llama/Llama-3.3-70B-Instruct-Turbo", True, True),
            ("openrouter/google/gemini-3.1-flash", True, True),
            # No slash at all: check_env wants "<provider>/model", and the
            # profile wants a concrete provider/model reference.
            ("bare-model", False, False),
            ("hf/", True, False),
            # parse_dotenv refuses the whitespace before validate_runtime_selection
            # ever sees the value.
            ("hf/model id", False, False),
        )
        measured: list[tuple[str, bool, bool]] = []
        for shape, env_accepts, profile_accepts in shapes:
            profile = self.reviewed_profile()
            profile["models"]["primary"] = shape
            profile["models"]["fast"] = shape
            with tempfile.TemporaryDirectory() as directory:
                env_path = Path(directory) / "shape.env"
                env_path.write_text(
                    self.reviewed_env_body(
                        {
                            "VC_MODEL_PROVIDER": "custom",
                            "VC_PRIMARY_MODEL": shape,
                            "VC_FAST_MODEL": shape,
                            "VC_WEB_SEARCH_PROVIDER": "duckduckgo",
                            "VC_CUSTOM_PROVIDER_ID": shape.split("/", 1)[0],
                            "VC_CUSTOM_BASE_URL": "https://models.example.com",
                            "VC_CUSTOM_API": "openai-completions",
                            "VC_CUSTOM_API_KEY": "k" * 32,
                        }
                    ),
                    encoding="utf-8",
                )
                env_path.chmod(0o600)
                profile_path = Path(directory) / "profile.json"
                profile_path.write_text(json.dumps(profile), encoding="utf-8")
                try:
                    env_errors = check_env.validate_runtime_selection(
                        check_env.parse_dotenv(env_path)
                    )
                except (OSError, ValueError) as exc:
                    env_errors = [str(exc)]
                result = subprocess.run(
                    [
                        "python3",
                        "-B",
                        str(ROOT / "scripts/check_customization.py"),
                        str(profile_path),
                        str(env_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            concrete = "must be a concrete provider/model reference" in result.stdout
            measured.append((shape, not env_errors, not concrete))
            # A crash would leave stdout empty, so read the envelope defensively
            # rather than raising a decode error out of the failure message.
            profile_errors = (
                json.loads(result.stdout)["errors"] if result.stdout else [result.stderr]
            )
            with self.subTest(model=shape):
                self.assertEqual(
                    (not env_errors, not concrete),
                    (env_accepts, profile_accepts),
                    f"{shape}: check_env said {env_errors}; "
                    f"check_customization said {profile_errors}",
                )
                # Acceptance means the whole profile validates against this
                # environment, not merely that the model message is absent.
                self.assertEqual(
                    result.returncode == 0, profile_accepts, result.stdout
                )
        self.assertEqual(
            [],
            [
                shape
                for shape, env_ok, profile_ok in measured
                if env_ok and not profile_ok and shape.partition("/")[2]
            ],
            "a sampled model reference with a non-empty id after the provider "
            "prefix is accepted by check_env and refused by the profile; because "
            "check_customization binds models.primary/models.fast to "
            "VC_PRIMARY_MODEL/VC_FAST_MODEL byte for byte, no operator value "
            "satisfies both validators",
        )

    def test_customization_rejects_duplicate_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"profile_version":"3.0","profile_version":"2.0"}', encoding="utf-8"
            )
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/check_customization.py"), str(path)],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON key", result.stdout)

    def test_absent_and_non_regular_profiles_report_different_causes(self) -> None:
        """Two failures, two repairs — the messages must not collapse into one.

        A profile that was never written is fixed by running
        `scripts/init_customization.py`; a path that resolves to a directory (or
        a symlink) is fixed by correcting the path, and running the scaffold
        against it would not help. Both branches stay fatal, and the wrong-type
        branch must not claim the file does not exist.
        """
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / "absent.json"
            not_regular = Path(directory) / "dir.json"
            not_regular.mkdir()
            missing = subprocess.run(
                ["python3", "-B", str(ROOT / "scripts/check_customization.py"), str(absent)],
                check=False,
                capture_output=True,
                text=True,
            )
            wrong_type = subprocess.run(
                ["python3", "-B", str(ROOT / "scripts/check_customization.py"), str(not_regular)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(0, missing.returncode, missing.stdout)
            self.assertIn("does not exist", missing.stdout)
            self.assertIn(str(absent), missing.stdout)
            self.assertNotEqual(0, wrong_type.returncode, wrong_type.stdout)
            self.assertIn("regular, non-symlink", wrong_type.stdout)
            self.assertNotIn("does not exist", wrong_type.stdout)

    def test_reviewed_artifact_inventories_cannot_drift(self) -> None:
        """The reviewed-artifact set is written down in three places.

        `check_customization.py` demands it, the example profile carries a hash
        slot per entry, and the G8 gate builds the profile it bootstraps with
        from its own copy. If they disagree, the offline suites still pass and
        only a full deployment run fails, so pin them to each other here.
        """
        required = self.reviewed_artifact_set(
            ROOT / "scripts/check_customization.py", "REQUIRED_REVIEWED_ARTIFACTS"
        )
        gate = self.reviewed_artifact_set(
            ROOT / "scripts/run_g8_deployment.py", "REVIEWED_ARTIFACTS"
        )
        example = set(
            json.loads(
                (ROOT / "config/customization-profile.example.json").read_text(encoding="utf-8")
            )["review"]["reviewed_artifacts"]
        )
        self.assertEqual(required, gate)
        self.assertEqual(required, example)
        for relative in sorted(required):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file())

    def test_profile_scaffold_pins_hashes_without_asserting_review(self) -> None:
        """The scaffold removes hash toil, never the operator's attestation.

        Filling twenty SHA-256 values by hand says nothing about whether anyone
        read the files, so the script computes them — but the profile it writes
        must still FAIL validation, or it would let an operator bless artifacts
        sight-unseen.
        """
        with tempfile.TemporaryDirectory(prefix="scaffold-") as raw:
            staged = Path(raw) / "customization-profile.json"
            profile = json.loads(
                (ROOT / "config/customization-profile.example.json").read_text(encoding="utf-8")
            )
            for relative in profile["review"]["reviewed_artifacts"]:
                profile["review"]["reviewed_artifacts"][relative] = hashlib.sha256(
                    (ROOT / relative).read_bytes()
                ).hexdigest()
            staged.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
            staged.chmod(0o600)
            result = subprocess.run(
                ["python3", "-B", str(ROOT / "scripts/check_customization.py"), str(staged)],
                capture_output=True, text=True, check=False,
            )
        self.assertNotEqual(result.returncode, 0, "hash-only scaffold must not pass review")
        self.assertIn("status must be reviewed", result.stdout)
        self.assertIn("unresolved customization placeholders", result.stdout)

        source = (ROOT / "scripts/init_customization.py").read_text(encoding="utf-8")
        # The scaffold must never write an attestation of its own.
        self.assertNotIn('"status": "reviewed"', source)
        for flag in ("hard_exclusions_reviewed", "lawful_bases_reviewed", "separation_of_duties_reviewed"):
            self.assertNotIn(f'"{flag}": True', source)
            self.assertNotIn(f'"{flag}": true', source)

    def test_customization_counts_match_the_documented_twenty(self) -> None:
        """The 'exactly twenty' numerals are load-bearing prose in six files.

        A 21st review flag or reviewed artifact added consistently across the
        pinned copies passes every gate while CUSTOMIZATION.md's 'exactly
        twenty', the 'twenty-first' framing, and the README/RUNBOOK/OPERATIONS
        mentions all silently go wrong. Pin the measured sizes; moving them
        means consciously updating every documented mention in the same
        change.
        """
        source = ast.parse(
            (ROOT / "scripts/check_customization.py").read_text(encoding="utf-8")
        )
        flags = None
        for node in source.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name) and t.id == "REVIEW_FLAGS"
                    for t in node.targets
                )
                and isinstance(node.value, (ast.Set, ast.List, ast.Tuple))
            ):
                flags = node.value.elts
        if flags is None:
            self.fail("REVIEW_FLAGS not found in check_customization.py")
        artifacts = self.reviewed_artifact_set(
            ROOT / "scripts/check_customization.py", "REQUIRED_REVIEWED_ARTIFACTS"
        )
        self.assertEqual(
            (len(flags), len(artifacts)), (20, 20),
            "the review-flag or reviewed-artifact inventory moved; update every "
            "documented 'twenty'/'twenty-first' mention (CUSTOMIZATION.md, "
            "README.md, docs/RUNBOOK.md, docs/OPERATIONS.md, CLAUDE.md, "
            "scripts/init_customization.py) and this pin in the same change",
        )
        for relative, phrases in (
            ("CUSTOMIZATION.md", ("gates exactly twenty", "twenty-first")),
            ("docs/RUNBOOK.md", ("twenty review flags", "twenty-first")),
            # The script prints its own operator-facing count, which no other
            # check reads; a 21st flag must move it too.
            ("scripts/init_customization.py", ("twenty governed", "twenty review flags")),
            # The three below are named in this test's own failure message as
            # files that must move in the same change, but were not pinned —
            # so a drifted count in any of them passed the offline gate. The
            # fifteenth pass's planted-defect calibration exercised exactly
            # that hole in README.md.
            ("README.md", ("twenty reviewed-artifact", "twenty reviewed artifacts")),
            ("docs/OPERATIONS.md", ("twenty artifact hashes",)),
            ("CLAUDE.md", ("twenty hash-pinned reviewed artifacts",)),
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(
                    phrase, text,
                    f"{relative} no longer states '{phrase}'; the documented "
                    "count wording moved without this pin moving",
                )

    def test_customization_doc_paths_are_pinned_and_split_documented(self) -> None:
        """CUSTOMIZATION.md's coverage story must match the pin partition.

        The document tells operators which edits fail closed at the next
        lifecycle run (the twenty profile-pinned artifacts) and which are
        pinned in manifest.json alone. Every full `workspaces/...` path the
        document names must exist and be manifest-declared, and the subset
        carried by the reviewed-artifact profile is pinned here so a file
        migrating between the two coverage classes fails until the document's
        story is updated. Scope note: the extractor sees full paths only, not
        the bare backticked filenames the MUST_CUSTOMIZE table also uses.
        """
        text = (ROOT / "CUSTOMIZATION.md").read_text(encoding="utf-8")
        named = set(
            re.findall(r"`((?:workspaces|tests/g3)/[^`\s]+\.[a-z0-9]+)`", text)
        )
        self.assertGreaterEqual(
            len(named), 8, "the CUSTOMIZATION.md path inventory has rotted"
        )
        manifest = {
            entry["path"]
            for entry in json.loads(
                (ROOT / "manifest.json").read_text(encoding="utf-8")
            )["files"]
        }
        required = self.reviewed_artifact_set(
            ROOT / "scripts/check_customization.py", "REQUIRED_REVIEWED_ARTIFACTS"
        )
        for relative in sorted(named):
            with self.subTest(path=relative):
                self.assertTrue(
                    (ROOT / relative).is_file(),
                    f"CUSTOMIZATION.md names {relative}, which does not exist",
                )
                self.assertIn(
                    relative, manifest,
                    f"CUSTOMIZATION.md names {relative}, which is not "
                    "manifest-declared",
                )
        self.assertEqual(
            sorted(named & required),
            [
                # Named by the band-change procedure because the eighteenth pass
                # made it live offline-gate cover: tests/g4/test_semantics.py
                # re-derives every row's expected band through the shipped helper,
                # so an operator who changes the bands and does not re-cut this
                # file gets a red g4-semantics suite. It is also profile-pinned,
                # so it fails closed at the next lifecycle run too.
                "tests/g3/scoring_boundary_cases.jsonl",
                "workspaces/outbound-scout/USER.md",
                "workspaces/vc-chief/USER.md",
                # Joined the overlap in the eighteenth pass's round 6: the band row
                # referred to it only as "its machine JSON", so an operator had to
                # guess the filename and the row's fails-closed sentence covered
                # only semantic_cases.json. Both are profile-pinned; the row now
                # names both.
                "workspaces/vc-chief/vc/scoring-rubric.v3.json",
                "workspaces/vc-chief/vc/thesis.md",
            ],
            "the overlap between CUSTOMIZATION.md's `workspaces/` full-path mentions "
            "and the "
            "reviewed-artifact set moved; update the document's fails-closed "
            "coverage story and this pin together",
        )
        self.assertEqual(
            sorted(named - required),
            [
                # Added by the eighteenth pass's round-6 repair: the band-change
                # procedure named neither, and an operator who followed it end to
                # end left both stating the shipped edges with every offline suite
                # green. BandEdgeCustomizationSurfaceTests derives that world from
                # the rubric, so the omission cannot recur silently.
                "tests/g3/README.md",
                "workspaces/shared-skills/memo-writing/SKILL.md",
                "workspaces/shared-skills/research-depth-control/SKILL.md",
                "workspaces/vc-chief/vc/RESOLVER.md",
                "workspaces/vc-chief/vc/bin/vcops.py",
                "workspaces/vc-chief/vc/eval_fixtures.md",
                "workspaces/vc-chief/vc/governance_lint.md",
                "workspaces/vc-chief/vc/scoring-rubric.md",
                "workspaces/vc-chief/vc/workflows/evaluate-lead.lobster",
            ],
            "the manifest-only side of CUSTOMIZATION.md's `workspaces/` full-path "
            "mentions "
            "moved; a file joining or leaving the twenty must move the "
            "document's story and this pin together",
        )

    @staticmethod
    def reviewed_artifact_set(path: Path, name: str) -> set[str]:
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in module.body:
            targets = getattr(node, "targets", [])
            if (
                any(isinstance(t, ast.Name) and t.id == name for t in targets)
                and isinstance(node, ast.Assign)
                and isinstance(node.value, (ast.Set, ast.List, ast.Tuple))
            ):
                return {
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant) and isinstance(element.value, str)
                }
        raise AssertionError(f"{name} not found in {path}")

    def test_workflow_state_is_bound_to_v3_package_and_policy(self) -> None:
        helper = (ROOT / "workspaces/vc-chief/vc/bin/vcops.py").read_text(encoding="utf-8")
        migration = (ROOT / "migrations/008_workflow_version_binding.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn('"workflow_version": WORKFLOW_VERSION', helper)
        self.assertIn('"policy_version": POLICY_VERSION', helper)
        self.assertIn("workflow_runs_identity_immutable", migration)
        for filename in (
            "inbound-intake.lobster",
            "outbound-scout.lobster",
            "runtime-preflight.lobster",
            "evaluate-lead.lobster",
        ):
            first = (ROOT / "workspaces/vc-chief/vc/workflows" / filename).read_text(
                encoding="utf-8"
            ).splitlines()[0]
            self.assertTrue(first.endswith("-v3"), first)


if __name__ == "__main__":
    unittest.main()
