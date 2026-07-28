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

    def test_blank_secrets_do_not_trigger_reuse_error(self) -> None:
        # A fresh `cp .env.example .env` leaves every deployment secret empty.
        # That run must fail for the real reason (unset secrets), never with the
        # secret-reuse accusation, which only applies to populated values.
        with tempfile.TemporaryDirectory(prefix="env-contract-") as raw:
            body = (PACKAGE / ".env.example").read_text(encoding="utf-8")
            path = self.make_env(Path(raw), body)
            previous_argv = sys.argv
            try:
                sys.argv = [str(CHECK_ENV_PATH), str(path)]
                output = io.StringIO()
                with self.clean_deployment_environment(), redirect_stdout(output):
                    self.assertEqual(1, check_env.main())
                self.assertNotIn("must not be reused", output.getvalue())
                self.assertNotIn("must not reuse", output.getvalue())
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
        self.assertIn("cmp -s /run/openclaw-source/openclaw.json /runtime-config/openclaw.json", init_command)
        # exec-approvals.json is deliberately runtime-writable (OpenClaw may
        # maintain its socket token in it), so init must never byte-compare it
        # against the seed — the jq reviewed-key assertion is the guard.
        self.assertNotIn("cmp -s /opt/openclaw-seed/exec-approvals.json", init_command)
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

    def test_services_drop_privileges_and_the_data_network_stays_internal(self) -> None:
        """Pin the container-hardening directives themselves.

        The resource bounds above are asserted but the privilege posture was
        not, so dropping `read_only`, `cap_drop` or `no-new-privileges` from a
        service — or giving the database network egress — was a silent edit.
        Postgres is the one writable root filesystem: its data directory is a
        mount the entrypoint must initialize.
        """
        for name, service in self.compose["services"].items():
            with self.subTest(service=name):
                self.assertEqual(["ALL"], service.get("cap_drop"))
                self.assertEqual(["no-new-privileges:true"], service.get("security_opt"))
                if name != "postgres":
                    self.assertIs(True, service.get("read_only"))
        self.assertIs(True, self.compose["networks"]["backend"].get("internal"))
        self.assertNotIn("egress", self.compose["services"]["postgres"].get("networks", []))

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

    def test_no_lifecycle_path_can_shed_bytecode_into_the_pristine_package(self) -> None:
        """`verify_release.py --pristine` rejects undeclared caches by design, so any
        packaged script that byte-compiles a module into the tree makes a working
        deployment report itself as tampered. Two independent guards must hold, and
        both are derived here rather than listed, so a new script or a new sibling
        import cannot reintroduce the defect silently.
        """
        # A module run as __main__ is never byte-compiled, so only modules that LOAD
        # another packaged module — by sibling import or importlib-by-path — can shed
        # a .pyc. Derive that set instead of listing it.
        loader = re.compile(r"^\s*(?:from\s+(?:check_env|vcrun)\s+import|.*spec_from_file_location)", re.M)
        roots = (PACKAGE / "scripts", PACKAGE / "workspaces/vc-chief/vc/bin")
        modules = sorted(p for root in roots for p in root.glob("*.py"))
        self.assertTrue(modules, "no packaged python modules discovered")
        loaders = {p.name for p in modules if loader.search(p.read_text(encoding="utf-8"))}
        self.assertTrue(loaders, "loader detection found nothing; the regex has drifted")

        # 1. Each loader module must set sys.dont_write_bytecode, so it is safe
        #    however it is invoked — including directly, without `-B`.
        for module in modules:
            if module.name not in loaders:
                continue
            with self.subTest(module=module.name):
                self.assertIn(
                    "sys.dont_write_bytecode = True", module.read_text(encoding="utf-8"),
                    f"{module.name} loads another packaged module but does not set "
                    "sys.dont_write_bytecode; running it without -B pollutes the package",
                )

        # 2. Defence in depth: a shell script that invokes a loader module must also
        #    export PYTHONDONTWRITEBYTECODE, so the guarantee does not rest on a
        #    single line inside the module.
        for script in sorted(PACKAGE.glob("scripts/*.sh")):
            body = script.read_text(encoding="utf-8")
            invoked = sorted(name for name in loaders if name in body)
            if not invoked:
                continue
            with self.subTest(script=script.name):
                self.assertIn(
                    "PYTHONDONTWRITEBYTECODE", body,
                    f"{script.name} invokes {invoked} without suppressing bytecode; a run "
                    "would leave scripts/__pycache__ and fail verify_release.py --pristine",
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
        # Pin the agent-lane inventory itself: a later sibling added inside
        # bin/agent/ (e.g. agent/vcops-admin) would be prefix-matched by the
        # allowlisted agent/vcops pattern, so its absence must be asserted, not
        # assumed.
        self.assertEqual(
            sorted(p.name for p in (bin_dir / "agent").iterdir()),
            ["vcops", "vcrun"],
            "bin/agent/ must contain exactly the two agent-reachable launchers",
        )
        image_bin = "/workspaces/vc-chief/vc/bin"
        siblings = [
            f"{image_bin}/{p.relative_to(bin_dir).as_posix()}"
            for p in bin_dir.rglob("*")
            if p.is_file()  # includes bin/agent/, so prefix-matched additions there fail too
        ]
        for allowed in patterns:
            for sibling in siblings:
                with self.subTest(allowed=allowed, sibling=sibling):
                    self.assertFalse(
                        sibling.startswith(allowed) and sibling != allowed,
                        f"privileged {sibling} is prefixed by allowlisted {allowed}",
                    )
        self.assertTrue(privileged, "expected privileged entrypoints to remain in bin/")

    def test_database_gate_refuses_a_postgres_major_the_package_never_deploys(self) -> None:
        """The G4 harness must bind itself to the pinned PostgreSQL major.

        It resolves initdb/pg_ctl/psql from PATH, so on a host carrying more
        than one PostgreSQL it would otherwise validate the migration set
        against whichever happens to be linked and still report PASS — proving
        nothing about the version operators actually run. The expected major
        must come from POSTGRES_IMAGE so there is only one pin to update.
        """
        spec = importlib.util.spec_from_file_location(
            "infra_run_g4", PACKAGE / "scripts/run_g4.py"
        )
        assert spec is not None and spec.loader is not None
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)

        env_spec = importlib.util.spec_from_file_location(
            "infra_check_env", PACKAGE / "scripts/check_env.py"
        )
        assert env_spec is not None and env_spec.loader is not None
        env_module = importlib.util.module_from_spec(env_spec)
        env_spec.loader.exec_module(env_module)

        expected = gate.pinned_postgres_major()
        self.assertTrue(
            env_module.POSTGRES_IMAGE.startswith(f"postgres:{expected}."),
            f"pinned major {expected} disagrees with {env_module.POSTGRES_IMAGE}",
        )
        compose = (PACKAGE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn(f"postgres:{expected}.", compose)

        # A mismatched toolchain must raise, not proceed.
        fake = PACKAGE / "scripts" / "_g4_fake_initdb_probe"
        self.assertFalse(fake.exists())
        with tempfile.TemporaryDirectory(prefix="g4-version-guard-") as temporary:
            wrong = Path(temporary) / "initdb"
            wrong.write_text(
                f"#!/bin/sh\necho 'initdb (PostgreSQL) {expected - 1}.4'\n", encoding="utf-8"
            )
            wrong.chmod(0o755)
            with self.assertRaises(gate.GateError) as raised:
                gate.require_pinned_postgres(str(wrong))
            self.assertIn(str(expected - 1), str(raised.exception))
            self.assertIn(str(expected), str(raised.exception))

            right = Path(temporary) / "initdb-ok"
            right.write_text(
                f"#!/bin/sh\necho 'initdb (PostgreSQL) {expected}.10'\n", encoding="utf-8"
            )
            right.chmod(0o755)
            gate.require_pinned_postgres(str(right))  # must not raise

    def test_channel_plugin_lock_agrees_with_the_npm_lockfile(self) -> None:
        """The reviewed channel-plugin pin must match what npm would install.

        config/channel-plugins.lock.json is a review artifact: no script reads
        it, so nothing else would notice if it drifted away from
        runtime-packages/package-lock.json — the file that actually determines
        the bytes in the image. A stale pin here would silently misdescribe the
        shipped channel plugins to a reviewer, so bind the two together.
        """
        reviewed = json.loads(
            (PACKAGE / "config/channel-plugins.lock.json").read_text(encoding="utf-8")
        )
        npm_lock = json.loads(
            (PACKAGE / "runtime-packages/package-lock.json").read_text(encoding="utf-8")
        )
        entries = npm_lock["packages"]
        checked = 0
        for name, pin in reviewed["packages"].items():
            # Bundled-private packages ship inside the upstream image and are
            # deliberately absent from the npm dependency graph.
            if pin.get("distribution") == "bundled-private":
                self.assertNotIn(f"node_modules/{name}", entries, name)
                self.assertNotIn("integrity", pin, f"{name} is bundled; it has no npm integrity")
                continue
            installed = entries.get(f"node_modules/{name}")
            self.assertIsNotNone(installed, f"{name} is pinned but absent from package-lock.json")
            self.assertEqual(pin["version"], installed["version"], f"{name} version drift")
            self.assertEqual(pin["integrity"], installed["integrity"], f"{name} integrity drift")
            checked += 1
        self.assertGreater(checked, 0, "expected at least one npm-installed channel plugin")

    def test_channel_plugin_lock_covers_every_shipped_channel(self) -> None:
        """Every channel this deployment can select must have a reviewed pin."""
        reviewed = json.loads(
            (PACKAGE / "config/channel-plugins.lock.json").read_text(encoding="utf-8")
        )
        pinned = set(reviewed["packages"])
        for channel in ("slack", "msteams", "discord", "telegram"):
            self.assertIn(f"@openclaw/{channel}", pinned, f"{channel} has no reviewed plugin pin")
        declared = json.loads(
            (PACKAGE / "runtime-packages/package.json").read_text(encoding="utf-8")
        )["dependencies"]
        for name, pin in reviewed["packages"].items():
            if pin.get("distribution") == "bundled-private":
                continue
            self.assertIn(name, declared, f"{name} is pinned but not a declared runtime dependency")
            self.assertEqual(declared[name], pin["version"], f"{name} version differs from package.json")


if __name__ == "__main__":
    unittest.main()
