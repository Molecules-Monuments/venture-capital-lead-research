# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
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
