# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CHECK_ENV_PATH = ROOT / "scripts/check_env.py"
VCOPS_PATH = ROOT / "workspaces/vc-chief/vc/bin/vcops.py"
PLUGIN_PATH = ROOT / "runtime-extensions/vc-trusted-context/index.js"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_env = load_module("runtime_choice_check_env", CHECK_ENV_PATH)
vcops = load_module("runtime_choice_vcops", VCOPS_PATH)


def configured_example() -> str:
    body = (ROOT / ".env.example").read_text(encoding="utf-8")
    replacements = {
        "OPENCLAW_GATEWAY_TOKEN=": "OPENCLAW_GATEWAY_TOKEN=" + "a" * 64,
        "POSTGRES_PASSWORD=": "POSTGRES_PASSWORD=" + "b" * 32,
        "OPENCLAW_DB_PASSWORD=": "OPENCLAW_DB_PASSWORD=" + "c" * 32,
        "VCOPS_APPROVAL_PEPPER=": "VCOPS_APPROVAL_PEPPER=" + "d" * 32,
        "VC_TRUSTED_CONTEXT_KEY=": "VC_TRUSTED_CONTEXT_KEY=" + "e" * 64,
        "BACKUP_HMAC_KEY=": "BACKUP_HMAC_KEY=" + "f" * 64,
        "OPENAI_API_KEY=": "OPENAI_API_KEY=test-only-openai-key",
    }
    for source, target in replacements.items():
        body = body.replace(source + "\n", target + "\n", 1)
    return body


def replace_line(body: str, key: str, value: str) -> str:
    lines = body.splitlines()
    found = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = f"{key}={value}"
            found = True
            break
    if not found:
        raise AssertionError(f"missing environment key: {key}")
    return "\n".join(lines) + "\n"


class RuntimeProviderTests(unittest.TestCase):
    def render(self, body: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="provider-render-") as raw:
            root = Path(raw)
            env_path = root / "runtime.env"
            output_path = root / "openclaw.json"
            env_path.write_text(body, encoding="utf-8")
            env_path.chmod(0o600)
            parsed = check_env.parse_dotenv(env_path)
            self.assertEqual([], check_env.validate_runtime_selection(parsed))
            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/render_channel_config.py"),
                    str(env_path),
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
            self.assertEqual(0, process.returncode, process.stdout + process.stderr)
            return json.loads(output_path.read_text(encoding="utf-8"))

    def render_expecting_failure(self, body: str) -> str:
        with tempfile.TemporaryDirectory(prefix="provider-reject-") as raw:
            root = Path(raw)
            env_path = root / "runtime.env"
            output_path = root / "openclaw.json"
            env_path.write_text(body, encoding="utf-8")
            env_path.chmod(0o600)
            process = subprocess.run(
                [
                    sys.executable, "-B", str(ROOT / "scripts/render_channel_config.py"),
                    str(env_path), str(output_path),
                ],
                cwd=ROOT, text=True, capture_output=True, check=False,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(1, process.returncode, process.stdout + process.stderr)
            self.assertFalse(output_path.exists(), "a rejected render must write no config")
            return process.stdout + process.stderr

    def test_renderer_refuses_every_runtime_selection_check_env_refuses(self) -> None:
        # The renderer is invoked directly in documented snippets, so it cannot
        # rely on check_env.sh having run first. Each case below was accepted by
        # the renderer while check_env rejected it, which meant a stale or
        # partial .env rendered a runtime config that no lifecycle path would
        # have allowed.
        cases = {
            "plain-HTTP custom provider": [
                ("VC_MODEL_PROVIDER", "custom"), ("OPENAI_API_KEY", ""),
                ("VC_CUSTOM_PROVIDER_ID", "acme"), ("VC_CUSTOM_BASE_URL", "http://models.acme.example/v1"),
                ("VC_CUSTOM_API", "anthropic-messages"), ("VC_CUSTOM_API_KEY", "test-only-key"),
                ("VC_PRIMARY_MODEL", "acme/model-a"), ("VC_FAST_MODEL", "acme/model-a"),
                ("VC_WEB_SEARCH_PROVIDER", "duckduckgo"),
            ],
            "public Ollama origin": [
                ("VC_MODEL_PROVIDER", "ollama"), ("OPENAI_API_KEY", ""),
                ("VC_OLLAMA_BASE_URL", "http://ollama.public.example:11434"),
                ("VC_PRIMARY_MODEL", "ollama/llama4"), ("VC_FAST_MODEL", "ollama/llama4"),
                ("VC_WEB_SEARCH_PROVIDER", "duckduckgo"),
            ],
            "auto search under a local model": [
                ("VC_MODEL_PROVIDER", "ollama"), ("OPENAI_API_KEY", ""),
                ("VC_OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
                ("VC_PRIMARY_MODEL", "ollama/llama4"), ("VC_FAST_MODEL", "ollama/llama4"),
                ("VC_WEB_SEARCH_PROVIDER", "auto"),
            ],
            "Tavily without its key": [
                ("VC_WEB_SEARCH_PROVIDER", "tavily"), ("TAVILY_API_KEY", ""),
            ],
        }
        for label, edits in cases.items():
            with self.subTest(case=label):
                body = configured_example()
                for key, value in edits:
                    body = replace_line(body, key, value)
                # Precondition: check_env genuinely refuses this environment.
                with tempfile.TemporaryDirectory(prefix="provider-precheck-") as raw:
                    probe = Path(raw) / "probe.env"
                    probe.write_text(body, encoding="utf-8")
                    probe.chmod(0o600)
                    parsed = check_env.parse_dotenv(probe)
                self.assertNotEqual([], check_env.validate_runtime_selection(parsed), label)
                self.render_expecting_failure(body)

    def _errors_for(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="provider-bounds-") as raw:
            probe = Path(raw) / "probe.env"
            probe.write_text(body, encoding="utf-8")
            probe.chmod(0o600)
            return check_env.validate_runtime_selection(check_env.parse_dotenv(probe))

    def _ollama_body(self, **overrides: str) -> str:
        body = configured_example()
        edits = {
            "VC_MODEL_PROVIDER": "ollama",
            "OPENAI_API_KEY": "",
            "VC_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
            "VC_PRIMARY_MODEL": "ollama/qwen3:14b",
            "VC_FAST_MODEL": "ollama/qwen3:14b",
            "VC_WEB_SEARCH_PROVIDER": "duckduckgo",
            "VC_MODEL_TIMEOUT_SECONDS": str(check_env.OLLAMA_MIN_TIMEOUT_SECONDS),
        }
        edits.update(overrides)
        for key, value in edits.items():
            body = replace_line(body, key, value)
        return body

    def test_context_window_must_clear_the_runtime_compaction_reserve(self) -> None:
        # A window under the floor validated, bootstrapped, and reported healthy
        # on a live deployment, and then answered every message with "Context
        # overflow: prompt too large for the model" — returned as an ordinary
        # payload with status "ok" and CLI exit code 0, so no signal an operator
        # checks reported a failure. The floor is what makes that loud.
        self.assertEqual(
            check_env.MODEL_CONTEXT_WINDOW_FLOOR,
            check_env.MODEL_COMPACTION_RESERVE_TOKENS
            + check_env.CHIEF_SYSTEM_PROMPT_TOKENS
            + check_env.MODEL_MIN_WORKING_TOKENS,
        )
        # The reserve alone is not enough: the chief's own prompt still has to fit.
        for window in (16_384, check_env.MODEL_COMPACTION_RESERVE_TOKENS,
                       check_env.MODEL_CONTEXT_WINDOW_FLOOR - 1):
            with self.subTest(window=window):
                errors = self._errors_for(
                    replace_line(configured_example(), "VC_MODEL_CONTEXT_WINDOW", str(window))
                )
                self.assertTrue(
                    any("VC_MODEL_CONTEXT_WINDOW" in error for error in errors),
                    f"{window} must be refused: {errors}",
                )
                self.assertTrue(
                    any("compaction" in error for error in errors),
                    f"the refusal must say why: {errors}",
                )
        at_floor = replace_line(
            configured_example(),
            "VC_MODEL_CONTEXT_WINDOW",
            str(check_env.MODEL_CONTEXT_WINDOW_FLOOR),
        )
        self.assertEqual([], self._errors_for(at_floor))

    def test_ollama_mode_requires_a_timeout_that_covers_a_cold_prefill(self) -> None:
        # The first turn after each model load prefills the whole system prompt
        # on the deployment host: 331 s measured on a CPU-only host, past the
        # shipped 300 s default. Prompt caching then answers the retry in about
        # 5 s, so the failure looks like a flake and re-arms on every restart.
        too_low = self._errors_for(self._ollama_body(VC_MODEL_TIMEOUT_SECONDS="300"))
        self.assertTrue(
            any("VC_MODEL_TIMEOUT_SECONDS" in error for error in too_low),
            f"300 s must be refused in Ollama mode: {too_low}",
        )
        self.assertEqual([], self._errors_for(self._ollama_body()))
        # The shipped default stays valid for hosted providers, which prefill
        # on the vendor's hardware.
        self.assertEqual([], self._errors_for(configured_example()))

    def _g6_channel_profiles(self) -> set[str]:
        """The channel roster scripts/run_g6_image.py validates inside the image.

        Read from that file's source rather than restated, so a fifth channel
        added to the image gate cannot quietly skip the load-path check below.
        """
        source = (ROOT / "scripts/run_g6_image.py").read_text(encoding="utf-8")
        match = re.search(r"^PROFILES = \(([^)]*)\)", source, re.M)
        self.assertIsNotNone(
            match,
            "scripts/run_g6_image.py no longer declares PROFILES as a literal "
            "tuple, so this test can no longer read the channel roster from it",
        )
        assert match is not None
        return set(re.findall(r'"([a-z]+)"', match.group(1))) - {"none"}

    def test_a_selected_channel_is_enabled_without_a_load_path(self) -> None:
        # The harness grants its keyed store only to a plugin whose registry
        # record is origin "bundled" (or a recorded trusted official install).
        # Naming a channel in plugins.load.paths makes it a path/config origin
        # instead, and every code path reaching openKeyedStore then throws
        # "openKeyedStore is only available for trusted plugins in this release".
        # Teams hits that while starting: the provider exited 40 ms in,
        # crash-looped through all ten auto-restarts, and never bound port 3978,
        # while bootstrap.sh exited 0 and the container reported healthy.
        # Dockerfile.openclaw now places all four channel distributions under the
        # harness's own extension scan root, so a load path must never come back.
        # The roster below is the image gate's own, checked against it; the slack
        # and discord credentials are scripts/run_g6_image.py's CHANNEL_VALUES
        # literals verbatim, and every value here is inert.
        families = {
            "slack": {
                "SLACK_BOT_TOKEN": "xoxb-" + "A" * 24,
                "SLACK_APP_TOKEN": "xapp-" + "B" * 24,
                "SLACK_ALLOWED_USER_IDS": "U12345678,U87654321",
                "SLACK_ALLOWED_CHANNEL_ID": "C12345678",
            },
            "discord": {
                "DISCORD_BOT_TOKEN": "D" * 40,
                "DISCORD_APPLICATION_ID": "123456789012345678",
                "DISCORD_ALLOWED_USER_IDS": "223456789012345678,223456789012345679",
                "DISCORD_ALLOWED_GUILD_ID": "323456789012345678",
                "DISCORD_ALLOWED_CHANNEL_ID": "423456789012345678",
            },
            "msteams": {
                "MSTEAMS_APP_ID": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                "MSTEAMS_APP_PASSWORD": "inert-render-test-app-password",
                "MSTEAMS_TENANT_ID": "72f988bf-86f1-41af-91ab-2d7cd011db47",
                "MSTEAMS_ALLOWED_USER_IDS": "29f1c4de-9a1b-4d0e-8f2a-11bb22cc33dd",
                "MSTEAMS_ALLOWED_TEAM_ID": "19:rendertestteam00000@thread.tacv2",
                "MSTEAMS_ALLOWED_CHANNEL_ID": "19:rendertestchan00000@thread.tacv2",
                "MSTEAMS_PUBLIC_WEBHOOK_URL": "https://teams.render-test.invalid/api/messages",
            },
            "telegram": {
                "TELEGRAM_BOT_TOKEN": "123456789:AAHrendertestinerttokenvalue00000000",
                "TELEGRAM_ALLOWED_USER_IDS": "123456789",
                "TELEGRAM_ALLOWED_GROUP_ID": "-1001234567890",
            },
        }
        self.assertEqual(
            set(families), self._g6_channel_profiles(),
            "the channel roster here has drifted from the one "
            "scripts/run_g6_image.py validates in the image; a channel absent "
            "from this dict gets no load-path assertion at all",
        )
        for channel, family in families.items():
            with self.subTest(channel=channel):
                body = replace_line(configured_example(), "PRIMARY_CHANNEL", channel)
                for key, value in family.items():
                    body = replace_line(body, key, value)
                config = self.render(body)
                plugins = config["plugins"]
                self.assertIn(channel, plugins["allow"])
                self.assertTrue(plugins["entries"][channel]["enabled"])
                # Check the rendered paths against the whole roster, not just
                # the selected channel: a path hardcoded for some other channel
                # revokes that channel's keyed store on the render that selects
                # it, and naming only `channel` here would never see it.
                for path in plugins["load"]["paths"]:
                    for name in sorted(families):
                        self.assertNotIn(
                            name, path,
                            f"the {channel} render carries a load path naming "
                            f"{name}: {path}. A channel named in "
                            "plugins.load.paths becomes a path-origin plugin, "
                            "and openKeyedStore then throws for it.",
                        )

    def test_rendered_config_disables_the_harness_heartbeat(self) -> None:
        # The harness runs a periodic main-session agent turn independently of
        # cron, and it is ON unless explicitly switched off. In the pinned
        # release isHeartbeatEnabledForAgent() falls through to
        # "resolvedAgentId === resolveDefaultAgentId(cfg)" when no heartbeat
        # config exists, so the default agent gets one; resolveHeartbeatIntervalMs
        # then defaults to "30m" and the module-level heartbeatsEnabled is true.
        # Measured on a live deployment: without this key the gateway logs
        # "[heartbeat] started" and vc-chief runs an autonomous turn every 30
        # minutes against the configured model, delivered nowhere (target
        # defaults to "none"). With it, the same gateway logs
        # "[heartbeat] disabled". Dropping the key would silently re-enable
        # autonomous execution that README, RUNBOOK and PRODUCTION_READINESS all
        # state this release does not perform, so it must never come back.
        for channel in ("none", "telegram"):
            with self.subTest(channel=channel):
                body = replace_line(configured_example(), "PRIMARY_CHANNEL", channel)
                if channel == "telegram":
                    for key, value in {
                        "TELEGRAM_BOT_TOKEN": "123456789:AAHrendertestinerttokenvalue00000000",
                        "TELEGRAM_ALLOWED_USER_IDS": "123456789",
                        "TELEGRAM_ALLOWED_GROUP_ID": "-1001234567890",
                    }.items():
                        body = replace_line(body, key, value)
                heartbeat = self.render(body)["agents"]["defaults"]["heartbeat"]
                self.assertEqual(
                    heartbeat["every"], "0m",
                    "agents.defaults.heartbeat.every must stay '0m'; any other "
                    "value (or removing the key) restores the harness default of "
                    "an autonomous vc-chief turn every 30 minutes",
                )

    def test_control_ui_origins_follow_the_configured_gateway_port(self) -> None:
        body = configured_example().replace(
            "OPENCLAW_GATEWAY_PORT=18789", "OPENCLAW_GATEWAY_PORT=28789"
        )
        config = self.render(body)
        self.assertEqual(
            config["gateway"]["controlUi"]["allowedOrigins"],
            ["http://localhost:28789", "http://127.0.0.1:28789"],
        )

    def test_validation_render_never_touches_package_secrets(self) -> None:
        # Explicit-output renders are validation/test runs; only lifecycle
        # renders (no output argument) may materialize config/runtime/secrets.
        # Compare digests, never raw bytes, so a failure cannot leak a real
        # deployment secret into gate logs.
        secrets_dir = ROOT / "config" / "runtime" / "secrets"

        def snapshot() -> dict[str, str] | None:
            if not secrets_dir.exists():
                return None
            return {
                item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                for item in sorted(secrets_dir.iterdir())
                if item.is_file()
            }

        before = snapshot()
        report = self.render(configured_example())
        self.assertIn("agents", report)
        self.assertEqual(before, snapshot())

    def test_lifecycle_render_refuses_a_non_package_env(self) -> None:
        # A lifecycle render (no output argument) overwrites the production
        # runtime config and all four secret files; from anything but the
        # package .env that is a footgun, so the renderer fails closed before
        # reading the env. The credential-rotation snapshot authorizes itself
        # via OPENCLAW_RENDER_ALLOW_SNAPSHOT=1.
        secrets_dir = ROOT / "config" / "runtime" / "secrets"

        def snapshot() -> dict[str, str] | None:
            if not secrets_dir.exists():
                return None
            return {
                item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                for item in sorted(secrets_dir.iterdir())
                if item.is_file()
            }

        before = snapshot()
        with tempfile.TemporaryDirectory(prefix="lifecycle-guard-") as raw:
            env_path = Path(raw) / "scratch.env"
            env_path.write_text(configured_example(), encoding="utf-8")
            env_path.chmod(0o600)
            process = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(ROOT / "scripts/render_channel_config.py"),
                    str(env_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
        self.assertEqual(1, process.returncode, process.stdout + process.stderr)
        payload = json.loads(process.stderr)
        self.assertEqual("FAIL", payload["result"])
        self.assertIn("only accepts the package .env", payload["errors"][0])
        self.assertEqual(before, snapshot())

    def test_openai_default_keeps_generic_auto_search(self) -> None:
        config = self.render(configured_example())
        self.assertIn("openai", config["plugins"]["allow"])
        self.assertNotIn("provider", config["tools"]["web"]["search"])
        self.assertEqual("openclaw", config["models"]["providers"]["openai"]["agentRuntime"]["id"])

    def test_runtime_config_keeps_the_two_silently_failing_plugin_settings(self) -> None:
        # Both of these fail silently when dropped, which is why they are pinned
        # here rather than left to review. Without the allowlist entry OpenClaw
        # never loads its own Readability extractor and web_fetch falls back to
        # whole-page raw HTML (and to a fetch provider, if one is loaded).
        # Without the hooks flag OpenClaw discards this extension's
        # before_model_resolve and before_agent_run registrations outright,
        # because it only grants conversation hooks to plugins it bundled
        # itself — and the unsupported-attachment block stops running.
        keyed = replace_line(configured_example(), "VC_WEB_SEARCH_PROVIDER", "tavily")
        keyed = replace_line(keyed, "TAVILY_API_KEY", "test-only-tavily-key")
        for body in (configured_example(), keyed):
            config = self.render(body)
            with self.subTest(search=config["tools"]["web"]["search"].get("provider", "auto")):
                self.assertIn("web-readability", config["plugins"]["allow"])
                self.assertTrue(config["tools"]["web"]["fetch"]["readability"])
                self.assertTrue(
                    config["plugins"]["entries"]["vc-trusted-context"]["hooks"][
                        "allowConversationAccess"
                    ]
                )

    def test_ollama_and_duckduckgo_are_configuration_only_choices(self) -> None:
        body = configured_example()
        for key, value in {
            "VC_MODEL_PROVIDER": "ollama",
            "VC_PRIMARY_MODEL": "ollama/qwen3:14b",
            "VC_FAST_MODEL": "ollama/qwen3:8b",
            "OPENAI_API_KEY": "",
            "VC_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
            "VC_WEB_SEARCH_PROVIDER": "duckduckgo",
            # Ollama mode prefills the system prompt on the deployment host, so
            # it carries a higher timeout floor than the hosted default this
            # example otherwise inherits.
            "VC_MODEL_TIMEOUT_SECONDS": str(check_env.OLLAMA_MIN_TIMEOUT_SECONDS),
        }.items():
            body = replace_line(body, key, value)
        config = self.render(body)
        self.assertTrue({"ollama", "duckduckgo", "vc-trusted-context"} <= set(config["plugins"]["allow"]))
        provider = config["models"]["providers"]["ollama"]
        self.assertEqual("ollama", provider["api"])
        self.assertEqual("http://host.docker.internal:11434", provider["baseUrl"])
        self.assertEqual("duckduckgo", config["tools"]["web"]["search"]["provider"])

    def test_tavily_selection_adds_only_its_secret_ref(self) -> None:
        body = replace_line(configured_example(), "VC_WEB_SEARCH_PROVIDER", "tavily")
        body = replace_line(body, "TAVILY_API_KEY", "test-only-tavily-key")
        config = self.render(body)
        entry = config["plugins"]["entries"]["tavily"]
        self.assertEqual("tavily", config["tools"]["web"]["search"]["provider"])
        self.assertEqual(
            {"source": "env", "provider": "default", "id": "TAVILY_API_KEY"},
            entry["config"]["webSearch"]["apiKey"],
        )
        self.assertNotIn("firecrawl", config["plugins"]["allow"])

    def test_custom_https_model_provider_renders_from_configuration(self) -> None:
        body = configured_example()
        for key, value in {
            "VC_MODEL_PROVIDER": "custom",
            "VC_PRIMARY_MODEL": "acme/model-primary",
            "VC_FAST_MODEL": "acme/model-fast",
            "OPENAI_API_KEY": "",
            "VC_CUSTOM_PROVIDER_ID": "acme",
            "VC_CUSTOM_BASE_URL": "https://models.example.test/v1",
            "VC_CUSTOM_API": "openai-responses",
            "VC_CUSTOM_API_KEY": "test-only-custom-key",
            "VC_WEB_SEARCH_PROVIDER": "duckduckgo",
        }.items():
            body = replace_line(body, key, value)
        config = self.render(body)
        provider = config["models"]["providers"]["acme"]
        self.assertEqual("openai-responses", provider["api"])
        self.assertEqual("https://models.example.test/v1", provider["baseUrl"])
        self.assertEqual(
            {"source": "env", "provider": "default", "id": "VC_CUSTOM_API_KEY"},
            provider["apiKey"],
        )

    def test_ollama_origin_rejects_public_or_api_compatible_urls(self) -> None:
        accepted = (
            "http://host.docker.internal:11434",
            "http://ollama:11434",
            "http://192.168.1.20:11434",
            "http://modelbox.local:11434",
        )
        rejected = (
            "https://host.docker.internal:11434",
            "http://api.example.com:11434",
            "http://host.docker.internal:11434/v1",
            "http://user:pass@ollama:11434",
            "http://ollama",
        )
        for value in accepted:
            with self.subTest(accepted=value):
                self.assertTrue(check_env._valid_ollama_origin(value))
        for value in rejected:
            with self.subTest(rejected=value):
                self.assertFalse(check_env._valid_ollama_origin(value))


class TrustedContextTests(unittest.TestCase):
    # Every hook payload below is shaped the way OpenClaw 2026.7.1 actually
    # builds it, because the extension's correctness is entirely a question of
    # conformance to the harness:
    #   - message_received carries NO runId. The run id is created when the
    #     agent turn starts, which is after this hook fires, so a capture keyed
    #     on it can never be written. Do not add one to make a test pass.
    #   - on message hooks ctx.channelId is the lowercased provider surface and
    #     ctx.conversationId is the conversation target; on agent hooks the
    #     provider surface is ctx.messageProvider/ctx.channel instead.
    #   - staged attachments arrive as event.metadata.mediaPaths, absolute under
    #     the state-dir media root, named "<sanitized original>---<uuid><ext>"
    #     with Unicode preserved.
    #   - before_model_resolve reports attachments as event.attachments.
    def test_plugin_pairs_each_message_with_its_own_run(self) -> None:
        # Two messages arrive in one session before either run starts, which is
        # what happens whenever a turn is queued behind a running one. Each run
        # must answer its own message: the deck must not be attributed to the
        # second message, and the macro-bearing message must block its own run
        # rather than whichever run happens to start next. Retried attempts of
        # the same run must keep seeing the same token.
        dm_key = "agent:vc-chief:slack:direct:u12345678"
        deck = "/home/node/.openclaw/media/inbound/deck---550e8400-e29b-41d4-a716-446655440000.pdf"
        macro = "/home/node/.openclaw/media/inbound/book---550e8400-e29b-41d4-a716-446655440001.xlsm"
        with tempfile.TemporaryDirectory(prefix="trusted-plugin-") as raw:
            key_path = Path(raw) / "key"
            key = b"k" * 64
            key_path.write_bytes(key)
            script = f"""
import plugin from {json.dumps(PLUGIN_PATH.as_uri())};
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
const ctxFor = (messageId) => ({{channelId: 'slack', accountId: 'acc-1', conversationId: 'D123', messageId, senderId: 'U1', sessionKey: {json.dumps(dm_key)}}});
hooks.message_received({{messageId: 'm1', senderId: 'U1', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: [{json.dumps(deck)}]}}}}, ctxFor('m1'));
hooks.message_received({{messageId: 'm2', senderId: 'U1', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: [{json.dumps(macro)}]}}}}, ctxFor('m2'));
const agentCtx = (runId) => ({{runId, senderId: 'U1', sessionKey: {json.dumps(dm_key)}, messageProvider: 'slack'}});
const first = hooks.before_prompt_build({{}}, agentCtx('run-1'));
const firstRetry = hooks.before_prompt_build({{}}, agentCtx('run-1'));
const firstBlocked = hooks.before_agent_run({{}}, agentCtx('run-1')) ?? null;
const second = hooks.before_prompt_build({{}}, agentCtx('run-2'));
const secondBlocked = hooks.before_agent_run({{}}, agentCtx('run-2')) ?? null;
console.log(JSON.stringify({{
  first: first?.prependContext ?? null,
  firstRetry: firstRetry?.prependContext ?? null,
  second: second?.prependContext ?? null,
  firstBlocked, secondBlocked,
}}));
"""
            process = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env={**os.environ, "VC_TRUSTED_CONTEXT_KEY_FILE": str(key_path)},
            )
            self.assertEqual(0, process.returncode, process.stderr)
            rendered = json.loads(process.stdout)

        def payload(context: str) -> dict[str, object]:
            encoded = context.split("[VC_TRUSTED_CONTEXT_V1]\n", 1)[1].split("\n", 1)[0].split(".", 1)[0]
            return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

        first = payload(rendered["first"])
        self.assertEqual("m1", first["event_id"])
        self.assertEqual([deck], first["media_paths"])
        self.assertIsNone(rendered["firstBlocked"])
        # A retried attempt of the same run rebuilds the prompt and must still
        # carry a token for the same message, so the claim cannot be consumed
        # destructively. The token itself is re-minted, with a fresh nonce.
        retry = payload(rendered["firstRetry"])
        for field in ("event_id", "media_paths", "sender_id", "run_id", "scopes"):
            self.assertEqual(first[field], retry[field])
        self.assertNotEqual(first["nonce"], retry["nonce"])
        second = payload(rendered["second"])
        self.assertEqual("m2", second["event_id"])
        # The macro workbook is never signed, and it blocks its own run.
        self.assertEqual([], second["media_paths"])
        self.assertEqual("unsupported_attachment_type", rendered["secondBlocked"]["reason"])

    def test_plugin_survives_a_turn_longer_than_the_stuck_session_budget(self) -> None:
        # A capture waits for the run that claims it, and a run can sit behind a
        # long one. config/openclaw.json allows a turn up to stuckSessionAbortMs
        # (960 s) and the reference host measures a 331 s first turn, so a
        # capture window shorter than that budget silently drops the token — and
        # with it the unsupported-attachment refusal. A claim must likewise
        # outlive the run that owns it, because before_prompt_build runs once per
        # attempt. The clock is driven explicitly rather than by sleeping.
        dm_key = "agent:vc-chief:slack:direct:u12345678"
        deck = "/home/node/.openclaw/media/inbound/deck---550e8400-e29b-41d4-a716-446655440000.pdf"
        macro = "/home/node/.openclaw/media/inbound/book---550e8400-e29b-41d4-a716-446655440001.xlsm"
        with tempfile.TemporaryDirectory(prefix="trusted-plugin-clock-") as raw:
            key_path = Path(raw) / "key"
            key_path.write_bytes(b"k" * 64)
            script = f"""
let clock = 1_000_000;
const realNow = Date.now;
Date.now = () => clock;
const plugin = (await import({json.dumps(PLUGIN_PATH.as_uri())})).default;
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
const ctxFor = (messageId) => ({{channelId: 'slack', accountId: 'acc-1', conversationId: 'D123', messageId, senderId: 'U1', sessionKey: {json.dumps(dm_key)}}});
const agentCtx = (runId) => ({{runId, senderId: 'U1', sessionKey: {json.dumps(dm_key)}, messageProvider: 'slack'}});

hooks.message_received({{messageId: 'm1', senderId: 'U1', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: [{json.dumps(deck)}]}}}}, ctxFor('m1'));
hooks.message_received({{messageId: 'm2', senderId: 'U1', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: [{json.dumps(macro)}]}}}}, ctxFor('m2'));

// The first run starts 900 s after its message was captured: inside the
// stuckSessionAbortMs budget, far outside the old 120 s window.
clock += 900_000;
const late = hooks.before_prompt_build({{}}, agentCtx('run-1'));
// The queued macro message, captured at the same time, must still block its own
// run. before_prompt_build claims the capture and registers the block, which is
// the order the runtime drives these hooks in.
hooks.before_prompt_build({{}}, agentCtx('run-2'));
const queuedBlocked = hooks.before_agent_run({{}}, agentCtx('run-2')) ?? null;
// run-1 is then retried another 900 s later, after a compaction. Its capture is
// long past the pending window by now, so only a claim that is *not* age-pruned
// can still answer.
clock += 900_000;
const lateRetry = hooks.before_prompt_build({{}}, agentCtx('run-1'));
Date.now = realNow;
console.log(JSON.stringify({{
  late: late?.prependContext ?? null,
  lateRetry: lateRetry?.prependContext ?? null,
  queuedBlocked,
}}));
"""
            process = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env={**os.environ, "VC_TRUSTED_CONTEXT_KEY_FILE": str(key_path)},
            )
            self.assertEqual(0, process.returncode, process.stderr)
            rendered = json.loads(process.stdout)

        def payload(context: str) -> dict[str, object]:
            encoded = context.split("[VC_TRUSTED_CONTEXT_V1]\n", 1)[1].split("\n", 1)[0].split(".", 1)[0]
            return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

        self.assertIsNotNone(
            rendered["late"],
            "a run dispatched 900 s after its message got no trusted-context token; "
            "the pending capture window is shorter than stuckSessionAbortMs",
        )
        late = payload(rendered["late"])
        self.assertEqual("m1", late["event_id"])
        self.assertEqual([deck], late["media_paths"])
        self.assertIsNotNone(
            rendered["lateRetry"],
            "a retried prompt build 900 s after the first attempt lost its token; "
            "the claim must outlive the run it is keyed to",
        )
        self.assertEqual("m1", payload(rendered["lateRetry"])["event_id"])
        self.assertEqual(
            "unsupported_attachment_type",
            (rendered["queuedBlocked"] or {}).get("reason"),
            "the queued macro-bearing message stopped blocking its own run",
        )

    def test_plugin_correlates_identity_media_and_dm_scope(self) -> None:
        dm_key = "agent:vc-chief:slack:direct:u12345678"
        group_key = "agent:vc-chief:slack:channel:c123"
        staged_doc = (
            "/home/node/.openclaw/media/inbound/"
            "Pitch_Deck_Übersicht.pdf---550e8400-e29b-41d4-a716-446655440000.pdf"
        )
        with tempfile.TemporaryDirectory(prefix="trusted-plugin-") as raw:
            key_path = Path(raw) / "key"
            key = b"k" * 64
            key_path.write_bytes(key)
            script = f"""
import plugin from {json.dumps(PLUGIN_PATH.as_uri())};
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
hooks.message_received(
  {{messageId: 'event-1', senderId: 'U12345678', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: [{json.dumps(staged_doc)}, '/home/node/.openclaw/media/inbound/nested/ignored.pdf']}}}},
  {{channelId: 'slack', accountId: 'acc-1', conversationId: 'D123', messageId: 'event-1', senderId: 'U12345678', sessionKey: {json.dumps(dm_key)}}}
);
const direct = hooks.before_prompt_build({{}}, {{runId: 'run-1', senderId: 'U12345678', sessionKey: {json.dumps(dm_key)}, messageProvider: 'slack'}});
hooks.message_received(
  {{messageId: 'event-2', senderId: 'U12345678', sessionKey: {json.dumps(group_key)}, metadata: {{}}}},
  {{channelId: 'slack', accountId: 'acc-1', conversationId: 'C123', messageId: 'event-2', senderId: 'U12345678', sessionKey: {json.dumps(group_key)}}}
);
const group = hooks.before_prompt_build({{}}, {{runId: 'run-2', senderId: 'U12345678', sessionKey: {json.dumps(group_key)}, messageProvider: 'slack'}});
hooks.message_received(
  {{messageId: 'event-3', senderId: 'U12345678', sessionKey: {json.dumps(dm_key)}, metadata: {{mediaPaths: ['/home/node/.openclaw/media/inbound/photo.png']}}}},
  {{channelId: 'slack', accountId: 'acc-1', conversationId: 'D123', messageId: 'event-3', senderId: 'U12345678', sessionKey: {json.dumps(dm_key)}}}
);
// The staged-media suffix check alone must block this turn: it is registered
// against the session, before any run id exists.
const blockedByStagedMedia = hooks.before_agent_run({{}}, {{runId: 'run-3', sessionKey: {json.dumps(dm_key)}}});
hooks.before_model_resolve({{attachments: [{{kind: 'image', mimeType: 'image/png'}}]}}, {{runId: 'run-4'}});
const blockedByAttachment = hooks.before_agent_run({{}}, {{runId: 'run-4', sessionKey: 'agent:vc-chief:slack:direct:u99'}});
console.log(JSON.stringify({{direct: direct.prependContext, group: group.prependContext, blockedByStagedMedia, blockedByAttachment}}));
"""
            process = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=False,
                env={**os.environ, "VC_TRUSTED_CONTEXT_KEY_FILE": str(key_path)},
            )
            self.assertEqual(0, process.returncode, process.stderr)
            rendered = json.loads(process.stdout)

        def payload(context: str) -> dict[str, object]:
            token = context.split("[VC_TRUSTED_CONTEXT_V1]\n", 1)[1].split("\n", 1)[0]
            encoded, signature = token.split(".", 1)
            expected = base64.urlsafe_b64encode(
                hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest()
            ).rstrip(b"=").decode("ascii")
            self.assertTrue(hmac.compare_digest(signature, expected))
            return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))

        direct = payload(rendered["direct"])
        group = payload(rendered["group"])
        self.assertFalse(direct["is_group"])
        self.assertTrue(group["is_group"])
        # The run id comes from the agent hook, the only place one exists.
        self.assertEqual("run-1", direct["run_id"])
        self.assertEqual("event-1", direct["event_id"])
        self.assertEqual("acc-1", direct["account_id"])
        self.assertEqual("D123", direct["conversation_id"])
        self.assertEqual("slack", direct["provider"])
        # A staged document keeps the Unicode of its original filename, so a
        # scope must still be minted for it.
        self.assertEqual([staged_doc], direct["media_paths"])
        path_hash = hashlib.sha256(staged_doc.encode("utf-8")).hexdigest()
        scopes = direct["scopes"]
        assert isinstance(scopes, list)
        self.assertIn(f"document.ingest:{path_hash}", scopes)
        for blocked_key in ("blockedByStagedMedia", "blockedByAttachment"):
            with self.subTest(blocked=blocked_key):
                self.assertEqual("block", rendered[blocked_key]["outcome"])
                self.assertEqual(
                    "unsupported_attachment_type", rendered[blocked_key]["reason"]
                )

    def test_plugin_blocks_unsupported_attachment_beyond_path_cap(self) -> None:
        # The 11th attachment exceeds MAX_MEDIA_PATHS; a disallowed suffix
        # there must still block the run instead of being truncated out of the
        # suffix check. The singular mediaPath variant lands last in the same
        # inspection list, so it is the natural over-cap probe.
        with tempfile.TemporaryDirectory(prefix="trusted-plugin-") as raw:
            key_path = Path(raw) / "key"
            key_path.write_bytes(b"k" * 64)
            supported = [
                f"/home/node/.openclaw/media/inbound/deck{index}.pdf" for index in range(10)
            ]
            script = f"""
import plugin from {json.dumps(PLUGIN_PATH.as_uri())};
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
hooks.message_received(
  {{messageId: 'event-1', senderId: 'U12345678', sessionKey: 'agent:vc-chief:slack:direct:u12345678', metadata: {{mediaPaths: {json.dumps(supported)}, mediaPath: '/home/node/.openclaw/media/inbound/macro.xlsm'}}}},
  {{channelId: 'slack', accountId: 'default', conversationId: 'D123', messageId: 'event-1', senderId: 'U12345678', sessionKey: 'agent:vc-chief:slack:direct:u12345678'}}
);
const blocked = hooks.before_agent_run({{}}, {{runId: 'run-cap', sessionKey: 'agent:vc-chief:slack:direct:u12345678'}});
console.log(JSON.stringify({{blocked}}));
"""
            process = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "VC_TRUSTED_CONTEXT_KEY_FILE": str(key_path)},
            )
            self.assertEqual(0, process.returncode, process.stderr)
            rendered = json.loads(process.stdout)
        self.assertEqual("block", rendered["blocked"]["outcome"])
        self.assertEqual("unsupported_attachment_type", rendered["blocked"]["reason"])

    def test_plugin_blocks_unsupported_attachment_with_an_irregular_name(self) -> None:
        # A path too irregular to sign (spaces, parentheses, a directory
        # segment) must still be suffix-inspected. Skipping it entirely would
        # let an unsupported attachment buy passage with an unparseable name,
        # while a supported document with the same irregularity must stay
        # unblocked — it is simply never signed.
        with tempfile.TemporaryDirectory(prefix="trusted-plugin-") as raw:
            key_path = Path(raw) / "key"
            key_path.write_bytes(b"k" * 64)
            root = "/home/node/.openclaw/media/inbound"
            probes = {
                "spaced_macro": f"{root}/board deck.xlsm",
                "parens_macro": f"{root}/Board Deck (1).xlsm",
                "nested_macro": f"{root}/nested/evil.xlsm",
                "spaced_pdf": f"{root}/Q3 Board Deck.pdf",
                "nested_pdf": f"{root}/nested/ignored.pdf",
            }
            # One session per probe: the staged-media block is registered
            # against the session key, so sharing one would let a block raised
            # by an earlier probe be consumed by the next and mask the result.
            statements = "\n".join(
                f"""hooks.message_received(
  {{messageId: 'event-{name}', senderId: 'U12345678', sessionKey: 'agent:vc-chief:slack:direct:u-{name}', metadata: {{mediaPaths: [{json.dumps(value)}]}}}},
  {{channelId: 'slack', accountId: 'default', conversationId: 'D123', messageId: 'event-{name}', senderId: 'U12345678', sessionKey: 'agent:vc-chief:slack:direct:u-{name}'}}
);
results[{json.dumps(name)}] = hooks.before_agent_run({{}}, {{runId: 'run-{name}', sessionKey: 'agent:vc-chief:slack:direct:u-{name}'}}) ?? null;"""
                for name, value in probes.items()
            )
            script = f"""
import plugin from {json.dumps(PLUGIN_PATH.as_uri())};
const hooks = {{}};
plugin.register({{on: (name, handler) => {{ hooks[name] = handler; }}}});
const results = {{}};
{statements}
console.log(JSON.stringify(results));
"""
            process = subprocess.run(
                ["node", "--input-type=module", "-e", script],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "VC_TRUSTED_CONTEXT_KEY_FILE": str(key_path)},
            )
            self.assertEqual(0, process.returncode, process.stderr)
            rendered = json.loads(process.stdout)
        for name in ("spaced_macro", "parens_macro", "nested_macro"):
            with self.subTest(attachment=name):
                self.assertEqual("block", (rendered[name] or {}).get("outcome"))
                self.assertEqual("unsupported_attachment_type", rendered[name]["reason"])
        for name in ("spaced_pdf", "nested_pdf"):
            with self.subTest(attachment=name):
                self.assertIsNone(rendered[name])

    def signed_token(self, key: bytes, *, exp_offset: int = 600) -> str:
        now = int(time.time())
        media_path = "/home/node/.openclaw/media/inbound/deck.pptx"
        digest = hashlib.sha256(media_path.encode("utf-8")).hexdigest()
        payload = {
            "v": 1,
            "nonce": "a" * 48,
            "iat": now,
            "exp": now + exp_offset,
            "provider": "slack",
            "account_id": "default",
            "conversation_id": "D123",
            "sender_id": "U12345678",
            "session_hash": "b" * 64,
            "run_id": "run-1",
            "event_id": "event-1",
            "is_group": False,
            "media_paths": [media_path],
            "scopes": ["preference.read", f"document.read:{digest}"],
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).rstrip(b"=").decode("ascii")
        signature = base64.urlsafe_b64encode(
            hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        return f"{encoded}.{signature}"

    def test_python_verifier_rejects_tamper_expiry_and_wrong_scope(self) -> None:
        with tempfile.TemporaryDirectory(prefix="trusted-vcops-") as raw:
            key_path = Path(raw) / "key"
            key = b"z" * 64
            key_path.write_bytes(key)
            token = self.signed_token(key)
            with patch.object(vcops, "TRUSTED_CONTEXT_KEY_FILE", key_path):
                verified = vcops.verify_trusted_context(token, "preference.read")
                self.assertEqual("U12345678", verified["sender_id"])
                with self.assertRaises(vcops.VcopsError):
                    vcops.verify_trusted_context(token + "x", "preference.read")
                with self.assertRaises(vcops.VcopsError):
                    vcops.verify_trusted_context(token, "preference.write")
                expired = self.signed_token(key, exp_offset=-1)
                with self.assertRaises(vcops.VcopsError):
                    vcops.verify_trusted_context(expired, "preference.read")


if __name__ == "__main__":
    unittest.main()
