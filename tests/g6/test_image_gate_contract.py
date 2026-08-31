# SPDX-License-Identifier: Apache-2.0
"""This suite guards the G6 gate itself, not the image the gate certifies.

`scripts/run_g6_image.py` only runs where Docker and a built
`vc-lead-research:3.0.1` image exist, and `verify_offline.py` invokes it solely
behind the opt-in `--with-g6-image`. Its own self-check compares the checks it
emitted against `EXPECTED_CHECK_NAMES` — a tuple it derives from `PROFILES`.
Drop a profile and the check disappears from both sides of that comparison at
once, so the gate reports PASS over a smaller world without saying so. A gate
that can quietly stop running a check and still report PASS is worse than no
gate, because the report is what the release record keeps.

So the inventory is pinned here instead, in the `g6` suite that
`verify_offline.py` always runs: the ten check names spelled out as literals,
the count as a literal, `PROFILES` as a literal, the locked runtime package
set, and `workshop_guard_probe`, `exec_approvals_row_probe` and
`docker_config_command` asserted callable so a rename cannot silently drop a
check. The same suite pins the shape of the validation container —
`--network none`, `--read-only`, `--cap-drop`, `no-new-privileges` — because a
gate that gained network access would still pass every check while no longer
being the offline gate the evidence documents describe.

The package *versions* are pinned against Dockerfile.openclaw's own build-time
assertions, not merely the key set. A key set alone let a typo in a version
literal be invisible to every check that runs without Docker: the Dockerfile
would build the image the gate then declared unexpected, and the two would only
be compared on a host that could do both.

The Debian pins are read back out of `Dockerfile.openclaw` rather than counted:
a count-only pin let a name or version swap inside the gate's own list pass
unnoticed. That parse is bounded to the single `apt-get install` shell
continuation after a later `LABEL` block's line-continued `key=value` pairs
were read as package pins and failed this test with a package-drift message.
"""

from __future__ import annotations

import importlib.util
import json
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
        remainder = dockerfile.split("apt-get install -y --no-install-recommends", 1)[1]
        # Bound the parse to this one shell continuation. Splitting alone leaves
        # the whole rest of the file, where any later `key=value \` line matches
        # the same shape — a LABEL block did, and its keys were read as Debian
        # package pins, failing this test with a package-drift message.
        install_lines: list[str] = []
        for line in remainder.splitlines():
            install_lines.append(line)
            if not line.rstrip().endswith("\\"):
                break
        declared = dict(
            re.findall(
                r"^\s+([a-z0-9][a-z0-9.+-]*)=(\S+) \\$", "\n".join(install_lines), re.MULTILINE
            )
        )
        self.assertEqual(declared, dict(gate.EXPECTED_DEBIAN_PACKAGES))

    def test_expected_package_versions_are_bound_to_the_dockerfile(self) -> None:
        # The test above pins *which* packages the gate reads. This pins what it
        # expects to find, which nothing offline did: a mistyped version literal
        # in EXPECTED_PACKAGES produced an image the gate then rejected as
        # unexpected, and the two were only ever compared on a host that could
        # both build and run Docker.
        #
        # Nine of the ten are asserted by Dockerfile.openclaw at build time as
        # `test "$(node -p "require('<manifest>').version")" = "<version>"`.
        # Derive this gate's key from the package directory in that path,
        # dropping the `-plugin` suffix the npm names carry
        # (@openclaw/firecrawl-plugin -> firecrawl,
        # @openclaw/duckduckgo-plugin -> duckduckgo), so the binding survives a
        # package moving between the bundled tree and the npm runtime.
        dockerfile = (PACKAGE / "Dockerfile.openclaw").read_text(encoding="utf-8")
        pairs = re.findall(
            r'''require\('([^']+)/package\.json'\)\.version"\)" = "([^"]+)"''',
            dockerfile,
        )
        asserted = {
            path.rsplit("/", 1)[-1].removesuffix("-plugin"): version
            for path, version in pairs
        }
        self.assertEqual(
            len(pairs), len(asserted), "two Dockerfile assertions map to one gate key"
        )
        self.assertEqual(
            {
                name: version
                for name, version in gate.EXPECTED_PACKAGES.items()
                if name != "trusted_context"
            },
            asserted,
        )
        # The tenth is ours, not upstream's: vc-trusted-context is baked from
        # this tree, so bind it to VERSION rather than to the Dockerfile. Both
        # ends are pinned because moving VERSION without the extension manifest
        # produces an image G6 rejects only after a rebuild.
        version = (PACKAGE / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(version, gate.EXPECTED_PACKAGES["trusted_context"])
        manifest = json.loads(
            (PACKAGE / "runtime-extensions/vc-trusted-context/package.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(version, manifest["version"])

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
        # provenance, the workshop guard, the exec-approvals store round trip,
        # one schema validation per profile, the reviewed artifact's own schema
        # validation, and the hostile unknown-field rejection — ten checks,
        # single-sourced.
        self.assertEqual(
            gate.EXPECTED_CHECK_NAMES,
            (
                "image-package-provenance",
                "image-workshop-guard",
                "image-exec-approvals-row",
                "openclaw-schema:none",
                "openclaw-schema:slack",
                "openclaw-schema:msteams",
                "openclaw-schema:discord",
                "openclaw-schema:telegram",
                "openclaw-schema:reviewed-artifact",
                "openclaw-schema:unknown-field-rejected",
            ),
        )
        self.assertEqual(10, len(gate.EXPECTED_CHECK_NAMES))
        self.assertTrue(callable(gate.workshop_guard_probe))
        self.assertTrue(callable(gate.exec_approvals_row_probe))
        self.assertTrue(callable(gate.docker_config_command))
        # Both new checks read a reviewed artifact rather than a render, so the
        # gate must actually address those files.
        self.assertTrue(gate.REVIEWED_CONFIG.is_file())
        self.assertTrue(gate.REVIEWED_EXEC_APPROVALS.is_file())


if __name__ == "__main__":
    unittest.main()
