# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]


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
            self.assertIsNotNone(match, skill_file)
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
                overlay = json.loads((ROOT / "config" / filename).read_text(encoding="utf-8"))
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

    def test_reviewed_customization_profile_can_pass(self) -> None:
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
        artifact_paths = profile["review"]["reviewed_artifacts"] = {
            relative: ""
            for relative in json.loads(
                (ROOT / "config/customization-profile.example.json").read_text(encoding="utf-8")
            )["review"]["reviewed_artifacts"]
        }
        for relative in artifact_paths:
            artifact_paths[relative] = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile), encoding="utf-8")
            env_path = Path(directory) / "reviewed.env"
            env_body = (ROOT / ".env.example").read_text(encoding="utf-8")
            env_body = env_body.replace(
                "VC_PRIMARY_MODEL=openai/gpt-5.6", "VC_PRIMARY_MODEL=provider/model-primary"
            ).replace(
                "VC_FAST_MODEL=openai/gpt-5.6", "VC_FAST_MODEL=provider/model-fast"
            ).replace(
                "VC_MODEL_PROVIDER=openai", "VC_MODEL_PROVIDER=custom"
            ).replace(
                "VC_WEB_SEARCH_PROVIDER=auto", "VC_WEB_SEARCH_PROVIDER=duckduckgo"
            )
            env_path.write_text(env_body, encoding="utf-8")
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
