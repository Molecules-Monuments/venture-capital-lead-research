# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import yaml


PACKAGE = Path(__file__).resolve().parents[2]
CHECK_ENV_PATH = PACKAGE / "scripts/check_env.py"
SPEC = importlib.util.spec_from_file_location("check_env_contract", CHECK_ENV_PATH)
assert SPEC is not None and SPEC.loader is not None
check_env = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = check_env
SPEC.loader.exec_module(check_env)


class EnvironmentFileSecurityTests(unittest.TestCase):
    def make_env(self, root: Path, body: str, mode: int = 0o600) -> Path:
        path = root / "fixture.env"
        path.write_text(body, encoding="utf-8")
        os.chmod(path, mode)
        return path

    def valid_env_body(self) -> str:
        body = (PACKAGE / ".env.example").read_text(encoding="utf-8")
        replacements = {
            "OPENCLAW_GATEWAY_TOKEN=": "OPENCLAW_GATEWAY_TOKEN=" + "a" * 64,
            "POSTGRES_PASSWORD=": "POSTGRES_PASSWORD=" + "b" * 32,
            "OPENCLAW_DB_PASSWORD=": "OPENCLAW_DB_PASSWORD=" + "c" * 32,
            "VCOPS_APPROVAL_PEPPER=": "VCOPS_APPROVAL_PEPPER=" + "d" * 32,
            "VC_TRUSTED_CONTEXT_KEY=": "VC_TRUSTED_CONTEXT_KEY=" + "f" * 64,
            "BACKUP_HMAC_KEY=": "BACKUP_HMAC_KEY=" + "e" * 64,
            "OPENAI_API_KEY=": "OPENAI_API_KEY=test-only-provider-key",
        }
        for old, new in replacements.items():
            body = body.replace(old + "\n", new + "\n", 1)
        return body

    @contextmanager
    def clean_deployment_environment(self):
        managed = set(check_env.ALLOWED_KEYS) | set(check_env.FORBIDDEN_AMBIENT_COMPOSE_KEYS)
        previous = {key: os.environ[key] for key in managed if key in os.environ}
        try:
            for key in managed:
                os.environ.pop(key, None)
            yield
        finally:
            for key in managed:
                os.environ.pop(key, None)
            os.environ.update(previous)

    def test_secure_regular_file_parses(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            path = self.make_env(Path(raw), "PRIMARY_CHANNEL=none\n")
            self.assertEqual("none", check_env.parse_dotenv(path)["PRIMARY_CHANNEL"])

    def test_duplicate_key_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            path = self.make_env(Path(raw), "PRIMARY_CHANNEL=none\nPRIMARY_CHANNEL=slack\n")
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                check_env.parse_dotenv(path)

    def test_compose_ambiguous_dotenv_syntax_fails(self) -> None:
        probes = (
            "export PRIMARY_CHANNEL=none\n",
            "PRIMARY_CHANNEL='none'\n",
            "PRIMARY_CHANNEL=no$ne\n",
            "PRIMARY_CHANNEL=none #comment\n",
            " PRIMARY_CHANNEL=none\n",
        )
        for body in probes:
            with self.subTest(body=body), tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
                path = self.make_env(Path(raw), body)
                with self.assertRaises(ValueError):
                    check_env.parse_dotenv(path)

    def test_non_0600_mode_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            path = self.make_env(Path(raw), "PRIMARY_CHANNEL=none\n", 0o640)
            with self.assertRaisesRegex(ValueError, "required mode is 0600"):
                check_env.parse_dotenv(path)

    def test_symlink_fails_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            root = Path(raw)
            target = self.make_env(root, "PRIMARY_CHANNEL=none\n")
            link = root / "linked.env"
            link.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                check_env.parse_dotenv(link)

    def test_main_rejects_ambient_compose_override(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            root = Path(raw)
            path = self.make_env(root, self.valid_env_body())
            previous_argv = sys.argv
            try:
                sys.argv = [str(CHECK_ENV_PATH), str(path)]
                with self.clean_deployment_environment():
                    os.environ["OPENCLAW_IMAGE"] = "ghcr.io/openclaw/openclaw:overridden"
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(1, check_env.main())
            finally:
                sys.argv = previous_argv

    def test_complete_inert_example_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            path = self.make_env(Path(raw), self.valid_env_body())
            previous_argv = sys.argv
            try:
                sys.argv = [str(CHECK_ENV_PATH), str(path)]
                output = io.StringIO()
                with self.clean_deployment_environment(), redirect_stdout(output):
                    self.assertEqual(0, check_env.main())
                self.assertIn('"selected_channel": "none"', output.getvalue())
            finally:
                sys.argv = previous_argv

    def test_unknown_compose_steering_key_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            path = self.make_env(
                Path(raw), self.valid_env_body() + "COMPOSE_FILE=unreviewed-compose.yml\n"
            )
            previous_argv = sys.argv
            try:
                sys.argv = [str(CHECK_ENV_PATH), str(path)]
                output = io.StringIO()
                with self.clean_deployment_environment(), redirect_stdout(output):
                    self.assertEqual(1, check_env.main())
                self.assertIn("unknown environment keys are forbidden", output.getvalue())
                self.assertIn("COMPOSE_FILE", output.getvalue())
            finally:
                sys.argv = previous_argv

    def test_configurable_volume_cannot_alias_fixed_or_default_state(self) -> None:
        probes = {
            "VC_QUARANTINE_VOLUME": "openclaw-lead-research-v3_postgres-data",
            "OPENCLAW_RUNTIME_CONFIG_VOLUME": "openclaw-lead-research-v3_openclaw-state",
        }
        for key, forbidden_name in probes.items():
            with self.subTest(key=key), tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
                body = self.valid_env_body()
                body = body.replace(f"{key}={check_env.VOLUME_DEFAULTS[key]}", f"{key}={forbidden_name}")
                path = self.make_env(Path(raw), body)
                previous_argv = sys.argv
                try:
                    sys.argv = [str(CHECK_ENV_PATH), str(path)]
                    output = io.StringIO()
                    with self.clean_deployment_environment(), redirect_stdout(output):
                        self.assertEqual(1, check_env.main())
                    self.assertIn("four distinct effective Docker volumes", output.getvalue())
                finally:
                    sys.argv = previous_argv


class RuntimeInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((PACKAGE / "config/openclaw.json").read_text(encoding="utf-8"))
        cls.compose = yaml.safe_load((PACKAGE / "docker-compose.yml").read_text(encoding="utf-8"))
        cls.dockerfile = (PACKAGE / "Dockerfile.openclaw").read_text(encoding="utf-8")

    def test_effective_tool_profile_can_supply_declared_agent_tools(self) -> None:
        tools = self.config["tools"]
        self.assertEqual("coding", tools["profile"])
        self.assertIn("agents_list", tools["alsoAllow"])
        self.assertIn("skill_workshop", tools["alsoAllow"])
        self.assertIn("exec", tools["subagents"]["tools"]["allow"])
        self.assertNotIn("exec", tools["subagents"]["tools"]["deny"])
        exec_agents = {
            agent["id"]
            for agent in self.config["agents"]["list"]
            if "exec" in agent["tools"]["allow"]
        }
        self.assertEqual({"data-steward"}, exec_agents)

    def test_immutable_preconfigured_workspaces_skip_runtime_bootstrap_writes(self) -> None:
        self.assertIs(
            True,
            self.config["agents"]["defaults"].get("skipBootstrap"),
            "OpenClaw must not try to seed files into image-owned read-only workspaces",
        )
        for agent in self.config["agents"]["list"]:
            workspace = PACKAGE / "workspaces" / agent["workspace"].removeprefix("/workspaces/")
            self.assertTrue(workspace.is_dir())
            self.assertTrue((workspace / "AGENTS.md").is_file())
            self.assertTrue((workspace / "TOOLS.md").is_file())

    def test_runtime_packages_and_workspaces_are_image_owned(self) -> None:
        self.assertIn("COPY runtime-packages/package.json runtime-packages/package-lock.json", self.dockerfile)
        self.assertIn("npm ci --prefix /opt/openclaw-runtime", self.dockerfile)
        self.assertIn("--omit=dev --omit=peer --ignore-scripts", self.dockerfile)
        self.assertIn("--require-hashes -r /tmp/requirements.lock", self.dockerfile)
        for package in (
            "ca-certificates=20230311+deb12u1",
            "curl=7.88.1-10+deb12u15",
            "file=1:5.44-3",
            "jq=1.6-2.1+deb12u2",
            "libmagic1=1:5.44-3",
            "poppler-utils=22.12.0-2+deb12u2",
            "postgresql-client=15+248+deb12u1",
            "python3=3.11.2-1+b1",
            "python3-pip=23.0.1+dfsg-1",
            "python3-venv=3.11.2-1+b1",
        ):
            self.assertIn(package, self.dockerfile)
        self.assertIn("COPY --chown=root:root workspaces/ /workspaces/", self.dockerfile)
        self.assertNotIn("/app/extensions/lobster/node_modules", self.dockerfile)
        self.assertNotIn("npm install --prefix", self.dockerfile)
        dockerignore = (PACKAGE / ".dockerignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual("*", dockerignore[0])
        self.assertNotIn("!.env", dockerignore)
        self.assertIn("!workspaces/**", dockerignore)
        self.assertIn("!runtime-packages/**", dockerignore)

    def test_developer_lock_is_standalone_hashed_and_complete(self) -> None:
        lock = (PACKAGE / "requirements-dev.lock").read_text(encoding="utf-8")
        self.assertNotIn("-r requirements.lock", lock)
        requirement_blocks = re.split(r"(?m)(?=^[a-z0-9-]+==)", lock)
        packages = set()
        for block in requirement_blocks:
            match = re.match(r"([a-z0-9-]+)==", block)
            if match is None:
                continue
            packages.add(match.group(1))
            self.assertIn("--hash=sha256:", block, match.group(1))
        self.assertTrue(
            {
                "jsonschema",
                "psycopg",
                "pyyaml",
                "pytest",
                "pytest-cov",
                "ruff",
                "typing-extensions",
            }.issubset(packages)
        )

        runtime_lock = (PACKAGE / "requirements.lock").read_text(encoding="utf-8")
        self.assertIn("typing-extensions==4.16.0", runtime_lock)
        self.assertIn(
            "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
            runtime_lock,
        )

    def test_config_and_approvals_use_supported_separate_paths(self) -> None:
        services = self.compose["services"]
        for name in ("openclaw-gateway", "openclaw-cli"):
            service = services[name]
            self.assertEqual("node", service["user"])
            self.assertNotIn("cap_add", service)
            self.assertEqual(
                "/home/node/.openclaw-config/openclaw.json",
                service["environment"]["OPENCLAW_CONFIG_PATH"],
            )
            self.assertTrue(
                any(
                    item == "openclaw-runtime-config:/home/node/.openclaw-config:ro"
                    for item in service["volumes"]
                )
            )
            serialized_volumes = json.dumps(service.get("volumes", []))
            self.assertNotIn("config/runtime/openclaw.json", serialized_volumes)
            self.assertNotIn("config/exec-approvals.json", serialized_volumes)
            self.assertNotIn("./workspaces", serialized_volumes)
        self.assertIn("openclaw-state-init", services)
        initializer = services["openclaw-state-init"]
        self.assertEqual("0:0", initializer["user"])
        self.assertEqual(["CHOWN", "DAC_OVERRIDE", "FOWNER"], initializer["cap_add"])
        self.assertTrue(
            any(item["source"] == "openclaw_runtime_config" for item in initializer["configs"])
        )
        init_command = "\n".join(initializer["command"])
        self.assertIn("install -m 0400 -o node -g node", init_command)
        self.assertIn("cmp -s", init_command)
        self.assertIn("node:node:400", init_command)
        self.assertIn('.defaults.askFallback == "deny"', init_command)
        self.assertIn('.agents["data-steward"].security == "allowlist"', init_command)
        self.assertIn("sort_by(.id)", init_command)
        self.assertEqual(
            "service_completed_successfully",
            services["openclaw-gateway"]["depends_on"]["openclaw-state-init"]["condition"],
        )

    def test_cli_has_gateway_diagnostic_environment(self) -> None:
        services = self.compose["services"]
        gateway = services["openclaw-gateway"]["environment"]
        cli = services["openclaw-cli"]["environment"]
        required = {
            "OPENCLAW_CONFIG_PATH",
            "OPENCLAW_STATE_DIR",
            "OPENCLAW_GATEWAY_TOKEN",
            "OPENAI_API_KEY",
            "VC_PRIMARY_MODEL",
            "VC_FAST_MODEL",
            "SLACK_BOT_TOKEN",
            "SLACK_APP_TOKEN",
            "MSTEAMS_APP_ID",
            "MSTEAMS_APP_PASSWORD",
            "MSTEAMS_TENANT_ID",
            "DISCORD_BOT_TOKEN",
            "TELEGRAM_BOT_TOKEN",
        }
        self.assertTrue(required <= gateway.keys())
        self.assertTrue(required <= cli.keys())

    def test_services_have_hard_resource_and_log_bounds(self) -> None:
        for name, service in self.compose["services"].items():
            with self.subTest(service=name):
                self.assertIn("mem_limit", service)
                self.assertIn("cpus", service)
                self.assertGreater(service.get("pids_limit", 0), 0)
                self.assertEqual("json-file", service["logging"]["driver"])
                self.assertIn("max-size", service["logging"]["options"])
                self.assertIn("max-file", service["logging"]["options"])

    def test_migrations_and_portable_named_volumes_are_fail_closed(self) -> None:
        postgres_mounts = json.dumps(self.compose["services"]["postgres"]["volumes"])
        self.assertIn("migrations/000_roles.sh", postgres_mounts)
        self.assertNotIn("./migrations:/docker-entrypoint-initdb.d", postgres_mounts)
        volumes = self.compose["volumes"]
        self.assertIn("name", volumes["openclaw-runtime-config"])
        self.assertIn("name", volumes["vc-quarantine"])
        gateway_mounts = json.dumps(self.compose["services"]["openclaw-gateway"]["volumes"])
        self.assertIn("vc-quarantine:/quarantine", gateway_mounts)
        self.assertNotIn("./quarantine", gateway_mounts)


class LifecycleScriptContractTests(unittest.TestCase):
    """Every lifecycle path that renders and deploys the runtime config must first
    validate the reviewed customization profile <-> environment binding, or a
    channel/model/score-band change that skipped the profile deploys unvalidated.
    """

    def test_every_deploying_lifecycle_script_validates_the_profile(self) -> None:
        for name in ("bootstrap.sh", "update.sh", "restore.sh", "rotate_runtime_role.sh"):
            body = (PACKAGE / "scripts" / name).read_text(encoding="utf-8")
            with self.subTest(script=name):
                self.assertIn(
                    "check_customization.py", body,
                    f"{name} renders/deploys config without validating the customization profile",
                )

    def test_agent_exec_allowlist_cannot_prefix_a_privileged_entrypoint(self) -> None:
        # The two agent-reachable launchers must live in an isolated bin/agent/
        # directory so no allowlisted path is a string prefix of a privileged
        # sibling (vcops-operator, vcops-workflow, vcrun-control, *.py) — keeping
        # the boundary safe under exact-, prefix-, or glob-match semantics.
        approvals = json.loads((PACKAGE / "config/exec-approvals.json").read_text(encoding="utf-8"))
        patterns = [e["pattern"] for e in approvals["agents"]["data-steward"]["allowlist"]]
        self.assertEqual(
            sorted(patterns),
            [
                "/workspaces/vc-chief/vc/bin/agent/vcops",
                "/workspaces/vc-chief/vc/bin/agent/vcrun",
            ],
        )
        bin_dir = PACKAGE / "workspaces/vc-chief/vc/bin"
        privileged = [
            str(p) for p in bin_dir.iterdir()
            if p.is_file()  # the *.py impls and privileged wrappers all sit in bin/, not bin/agent/
        ]
        image_bin = "/workspaces/vc-chief/vc/bin"
        for allowed in patterns:
            for name in (p.name for p in bin_dir.iterdir() if p.is_file()):
                sibling = f"{image_bin}/{name}"
                with self.subTest(allowed=allowed, sibling=sibling):
                    self.assertFalse(
                        sibling.startswith(allowed) and sibling != allowed,
                        f"privileged {sibling} is prefixed by allowlisted {allowed}",
                    )
        self.assertTrue(privileged, "expected privileged entrypoints to remain in bin/")


if __name__ == "__main__":
    unittest.main()
