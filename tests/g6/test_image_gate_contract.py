# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[2]
SCRIPT = PACKAGE / "scripts/run_g6_image.py"
SPEC = importlib.util.spec_from_file_location("g6_image_gate_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class ImageChannelGateContractTests(unittest.TestCase):
    def test_inventory_covers_inert_and_every_supported_channel(self) -> None:
        self.assertEqual(
            ("none", "slack", "msteams", "discord", "telegram"), gate.PROFILES
        )
        self.assertEqual(
            {
                "lobster",
                "slack",
                "msteams",
                "discord",
                "telegram",
                "firecrawl",
                "tavily",
                "duckduckgo",
                "ollama",
                "trusted_context",
            },
            set(gate.EXPECTED_PACKAGES),
        )
        # Derived from the Dockerfile rather than counted: a count-only pin let
        # a name or version swap inside the gate's own list pass unnoticed.
        dockerfile = (PACKAGE / "Dockerfile.openclaw").read_text(encoding="utf-8")
        install_block = dockerfile.split("apt-get install -y --no-install-recommends", 1)[1]
        declared = dict(
            re.findall(r"^\s+([a-z0-9][a-z0-9.+-]*)=(\S+) \\$", install_block, re.MULTILINE)
        )
        self.assertEqual(declared, dict(gate.EXPECTED_DEBIAN_PACKAGES))

    def test_fixture_envs_are_secure_literal_complete_families(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            for profile in gate.PROFILES:
                with self.subTest(profile=profile):
                    path = Path(raw) / f"{profile}.env"
                    values = gate.write_env(path, profile)
                    self.assertEqual(0o600, path.stat().st_mode & 0o777)
                    self.assertEqual(profile, values["PRIMARY_CHANNEL"])
                    if profile != "none":
                        self.assertTrue(gate.CHANNEL_VALUES[profile].keys() <= values.keys())

    def test_container_validation_is_offline_read_only_and_unprivileged(self) -> None:
        command = gate.docker_config_command(
            "image:test", Path("/tmp/config.json"), gate.env_values("none")
        )
        self.assertIn("none", command[command.index("--network") + 1])
        self.assertIn("--read-only", command)
        self.assertIn("--cap-drop", command)
        self.assertIn("no-new-privileges:true", command)
        self.assertEqual(["config", "validate"], command[-2:])

    def test_gate_declares_the_complete_check_inventory(self) -> None:
        # Behavioral contract (not a self-grep): the gate must run exactly image
        # provenance, the workshop guard, one schema validation per profile, and
        # the hostile unknown-field rejection — eight checks, single-sourced.
        self.assertEqual(
            gate.EXPECTED_CHECK_NAMES,
            (
                "image-package-provenance",
                "image-workshop-guard",
                "openclaw-schema:none",
                "openclaw-schema:slack",
                "openclaw-schema:msteams",
                "openclaw-schema:discord",
                "openclaw-schema:telegram",
                "openclaw-schema:unknown-field-rejected",
            ),
        )
        self.assertEqual(8, len(gate.EXPECTED_CHECK_NAMES))
        self.assertTrue(callable(gate.workshop_guard_probe))
        self.assertTrue(callable(gate.docker_config_command))


if __name__ == "__main__":
    unittest.main()
