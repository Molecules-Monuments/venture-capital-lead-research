from __future__ import annotations

import json
import os
import subprocess
import sys
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
        self.assertEqual({"enabled": False}, workshop["autonomous"])
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


if __name__ == "__main__":
    unittest.main()
