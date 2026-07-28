#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Render one fail-closed channel overlay into the immutable runtime config."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The sibling import below byte-compiles check_env into scripts/__pycache__,
# which then makes `verify_release.py --pristine` report an undeclared file and
# tells the operator their package is untrustworthy. Suppress it here so the
# renderer stays safe to run even when someone omits `-B`.
sys.dont_write_bytecode = True

from check_env import parse_dotenv, validate_channel_selection  # noqa: E402


PACKAGE_DIR = Path(__file__).resolve().parent.parent
BASE_CONFIG = PACKAGE_DIR / "config" / "openclaw.json"
DEFAULT_OUTPUT = PACKAGE_DIR / "config" / "runtime" / "openclaw.json"
CONNECTORS_CONFIG = PACKAGE_DIR / "config" / "connectors.json"
# Specialists that may be granted read-only third-party connector (MCP) tools.
# The steward, chief, and analysis-only roles are deliberately excluded.
CONNECTOR_GRANTABLE_AGENTS = {
    "founder-researcher", "traction-analyst", "market-mapper",
    "outbound-scout", "lead-signal-detector",
}
PROFILE_FILES = {
    "slack": "channel-slack.socket.json5",
    "msteams": "channel-msteams.json5",
    "discord": "channel-discord.json5",
    "telegram": "channel-telegram.json5",
}
SENTINEL_ENV = {
    "__SLACK_ALLOWED_CHANNEL_ID__": "SLACK_ALLOWED_CHANNEL_ID",
    "__MSTEAMS_ALLOWED_TEAM_ID__": "MSTEAMS_ALLOWED_TEAM_ID",
    "__MSTEAMS_ALLOWED_CHANNEL_ID__": "MSTEAMS_ALLOWED_CHANNEL_ID",
    "__DISCORD_APPLICATION_ID__": "DISCORD_APPLICATION_ID",
    "__DISCORD_ALLOWED_GUILD_ID__": "DISCORD_ALLOWED_GUILD_ID",
    "__DISCORD_ALLOWED_CHANNEL_ID__": "DISCORD_ALLOWED_CHANNEL_ID",
    "__TELEGRAM_ALLOWED_GROUP_ID__": "TELEGRAM_ALLOWED_GROUP_ID",
}
LIST_SENTINELS = {
    "__SLACK_ALLOWED_USER_IDS__": "SLACK_ALLOWED_USER_IDS",
    "__MSTEAMS_ALLOWED_USER_IDS__": "MSTEAMS_ALLOWED_USER_IDS",
    "__DISCORD_ALLOWED_USER_IDS__": "DISCORD_ALLOWED_USER_IDS",
    "__TELEGRAM_ALLOWED_USER_IDS__": "TELEGRAM_ALLOWED_USER_IDS",
}
SECRETS_DIR = PACKAGE_DIR / "config" / "runtime" / "secrets"
SECRET_FILES = {
    "postgres_owner_password": "POSTGRES_PASSWORD",
    "openclaw_db_password": "OPENCLAW_DB_PASSWORD",
    "vcops_approval_pepper": "VCOPS_APPROVAL_PEPPER",
    "vc_trusted_context_key": "VC_TRUSTED_CONTEXT_KEY",
}
SEARCH_PACKAGES = {
    "duckduckgo": ("duckduckgo", "/app/extensions/duckduckgo"),
    "firecrawl": ("firecrawl", "/opt/openclaw-runtime/node_modules/@openclaw/firecrawl-plugin"),
    "tavily": ("tavily", "/opt/openclaw-runtime/node_modules/@openclaw/tavily-plugin"),
    # Additional native providers. The plugin package must be present in the
    # image (pin it in runtime-packages and rebuild — a commissioning step for a
    # non-bundled provider). See CUSTOMIZATION.md.
    "brave": ("brave", "/opt/openclaw-runtime/node_modules/@openclaw/brave-plugin"),
    "perplexity": ("perplexity", "/opt/openclaw-runtime/node_modules/@openclaw/perplexity-plugin"),
    "exa": ("exa", "/opt/openclaw-runtime/node_modules/@openclaw/exa-plugin"),
    "searxng": ("searxng", "/opt/openclaw-runtime/node_modules/@openclaw/searxng-plugin"),
    # parallel-free is the keyless hosted Search-MCP variant the parallel plugin
    # registers (requiresCredential:false). The plugin package id is "parallel";
    # the selectable provider id is "parallel-free". The paid "parallel" provider
    # (needs PARALLEL_API_KEY) is intentionally not offered as a keyless option.
    "parallel-free": ("parallel", "/opt/openclaw-runtime/node_modules/@openclaw/parallel-plugin"),
}
CHANNEL_PACKAGES = {
    "slack": "/opt/openclaw-runtime/node_modules/@openclaw/slack",
    "msteams": "/opt/openclaw-runtime/node_modules/@openclaw/msteams",
    "discord": "/opt/openclaw-runtime/node_modules/@openclaw/discord",
    # telegram ships bundled at /app/extensions/telegram inside the pinned image;
    # give it an explicit load path too rather than relying on the base image's
    # default extensions scan (which is not guaranteed and untested).
    "telegram": "/app/extensions/telegram",
}
# Search-provider plugins that are actually present in the built image: the base
# image's /app/extensions and whatever runtime-packages/package.json pins via
# `npm ci`. A provider outside this set renders a plugins.load path that does not
# exist, so the gateway fails to load it at startup — caught here at render time
# with an actionable message instead of an opaque late failure.
BASE_IMAGE_SEARCH_PLUGINS = {"duckduckgo"}


def _bundled_search_providers() -> set[str]:
    try:
        deps = set(load_strict_json(PACKAGE_DIR / "runtime-packages" / "package.json").get("dependencies", {}))
    except (OSError, ValueError):
        deps = set()
    available = set(BASE_IMAGE_SEARCH_PLUGINS)
    for provider, (_plugin_id, plugin_path) in SEARCH_PACKAGES.items():
        if "/node_modules/" in plugin_path:
            if plugin_path.split("/node_modules/", 1)[1] in deps:
                available.add(provider)
        else:
            available.add(provider)
    return available


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_strict_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = json.loads(json.dumps(value))
    return merged


def materialize_sentinels(value: Any, env: dict[str, str]) -> Any:
    if isinstance(value, str):
        if value in LIST_SENTINELS:
            return [item for item in env[LIST_SENTINELS[value]].split(",") if item]
        if value == "__VC_CHANNEL_MEDIA_MAX_MB__":
            return float(env["VC_CHANNEL_MEDIA_MAX_MB"])
        return env[SENTINEL_ENV[value]] if value in SENTINEL_ENV else value
    if isinstance(value, list):
        return [materialize_sentinels(item, env) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            rendered_key = env[SENTINEL_ENV[key]] if key in SENTINEL_ENV else key
            if rendered_key in result:
                raise ValueError(f"rendered key collision at {rendered_key!r}")
            result[rendered_key] = materialize_sentinels(item, env)
        return result
    return value


def _secret_ref(name: str) -> dict[str, str]:
    return {"source": "env", "provider": "default", "id": name}


def _model_entry(model_id: str, env: dict[str, str]) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": model_id,
        "reasoning": env["VC_MODEL_REASONING"] == "true",
        "input": ["text", "image"] if env["VC_MODEL_INPUT"] == "text,image" else ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": int(env["VC_MODEL_CONTEXT_WINDOW"]),
        "maxTokens": int(env["VC_MODEL_MAX_TOKENS"]),
    }


def apply_runtime_selection(config: dict[str, Any], selected_channel: str, env: dict[str, str]) -> None:
    plugins = config.setdefault("plugins", {})
    allow = ["vc-trusted-context"]
    paths = ["/opt/openclaw-extensions/vc-trusted-context"]
    entries: dict[str, Any] = {"vc-trusted-context": {"enabled": True}}

    model_mode = env["VC_MODEL_PROVIDER"]
    if model_mode == "openai":
        allow.append("openai")
        entries["openai"] = {"enabled": True}
        config["models"] = {"providers": {"openai": {"agentRuntime": {"id": "openclaw"}}}}
    else:
        provider_id = "ollama" if model_mode == "ollama" else env["VC_CUSTOM_PROVIDER_ID"]
        if model_mode == "ollama":
            allow.append("ollama")
            paths.append("/app/extensions/ollama")
            entries["ollama"] = {
                "enabled": True,
                "config": {"discovery": {"enabled": False}, "nodeInference": {"enabled": False}},
            }
            base_url = env["VC_OLLAMA_BASE_URL"]
            api = "ollama"
            api_key: Any = "ollama-local"
        else:
            base_url = env["VC_CUSTOM_BASE_URL"]
            api = env["VC_CUSTOM_API"]
            api_key = _secret_ref("VC_CUSTOM_API_KEY")
        # check_env.py already requires the provider-qualified form on every
        # lifecycle path; guard it here too so a standalone render reports the
        # reason instead of an IndexError traceback.
        for key in ("VC_PRIMARY_MODEL", "VC_FAST_MODEL"):
            if "/" not in env[key]:
                raise SystemExit(f"{key} must be provider-qualified as <provider>/<model-id>")
        local_ids = [env["VC_PRIMARY_MODEL"].split("/", 1)[1], env["VC_FAST_MODEL"].split("/", 1)[1]]
        models = []
        for model_id in local_ids:
            if model_id not in [item["id"] for item in models]:
                models.append(_model_entry(model_id, env))
        config["models"] = {
            "mode": "merge",
            "providers": {
                provider_id: {
                    "baseUrl": base_url,
                    "apiKey": api_key,
                    "api": api,
                    "timeoutSeconds": int(env["VC_MODEL_TIMEOUT_SECONDS"]),
                    "models": models,
                }
            },
        }

    search = env["VC_WEB_SEARCH_PROVIDER"]
    fetch = env["VC_WEB_FETCH_PROVIDER"]
    bundled = _bundled_search_providers()
    if search != "auto" and search not in bundled:
        raise ValueError(
            f"VC_WEB_SEARCH_PROVIDER '{search}' has no plugin in this image "
            f"(bundled providers: {sorted(bundled)}). Pin its plugin package in "
            f"runtime-packages/package.json and rebuild, or choose a bundled provider."
        )
    if fetch not in ("default", "auto") and fetch not in bundled:
        raise ValueError(
            f"VC_WEB_FETCH_PROVIDER '{fetch}' has no plugin in this image "
            f"(bundled providers: {sorted(bundled)}). Pin its plugin package in "
            f"runtime-packages/package.json and rebuild, or use the default fetch provider."
        )
    tools_web: dict[str, Any] = {
        "search": {"enabled": True, "maxResults": 5, "timeoutSeconds": 30, "cacheTtlMinutes": 15},
        "fetch": {
            "enabled": True,
            "maxChars": 20000,
            "maxCharsCap": 20000,
            "maxResponseBytes": 750000,
            "timeoutSeconds": 30,
            "cacheTtlMinutes": 15,
            "maxRedirects": 3,
            "readability": True,
        },
    }
    selected_search_plugins = set()
    if search != "auto":
        plugin_id, plugin_path = SEARCH_PACKAGES[search]
        selected_search_plugins.add(plugin_id)
        tools_web["search"]["provider"] = search
        api_key_env = {
            "firecrawl": "FIRECRAWL_API_KEY", "tavily": "TAVILY_API_KEY",
            "brave": "BRAVE_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "exa": "EXA_API_KEY",
        }.get(search)
        if api_key_env:
            plugin_config = {"webSearch": {"apiKey": _secret_ref(api_key_env)}}
        elif search == "searxng":
            # searxng is keyed by its instance endpoint, not an API key; its
            # plugin config schema accepts a SecretRef object for baseUrl.
            plugin_config = {"webSearch": {"baseUrl": _secret_ref("SEARXNG_BASE_URL")}}
        else:
            plugin_config = {}
        entries[plugin_id] = {"enabled": True, **({"config": plugin_config} if plugin_config else {})}
        allow.append(plugin_id)
        paths.append(plugin_path)
    if fetch == "firecrawl":
        selected_search_plugins.add("firecrawl")
        tools_web["fetch"]["provider"] = "firecrawl"
        if "firecrawl" not in allow:
            allow.append("firecrawl")
            paths.append(SEARCH_PACKAGES["firecrawl"][1])
        config_value = entries.setdefault("firecrawl", {"enabled": True, "config": {}})
        config_value.setdefault("config", {})["webFetch"] = {"apiKey": _secret_ref("FIRECRAWL_API_KEY")}
    config.setdefault("tools", {})["web"] = tools_web

    if selected_channel != "none":
        allow.append(selected_channel)
        entries[selected_channel] = {"enabled": True}
        if selected_channel in CHANNEL_PACKAGES:
            paths.append(CHANNEL_PACKAGES[selected_channel])
    plugins["allow"] = list(dict.fromkeys(allow))
    plugins["load"] = {"paths": list(dict.fromkeys(paths))}
    plugins["entries"] = entries

    # Agents reason in the operator's timezone, not the packaged default. The
    # reviewed profile already binds organization.timezone to .env TZ (see
    # check_customization.py), so without this substitution a non-Berlin fund
    # passes every validator while its agents keep resolving "today" and the
    # notification_policy.md delivery window against Europe/Berlin.
    timezone = env.get("TZ", "").strip()
    if timezone:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TZ must be a valid IANA timezone: {exc}") from exc
        config.setdefault("agents", {}).setdefault("defaults", {})["userTimezone"] = timezone

    # The Control UI browser origin carries the HOST-published port, not the
    # fixed in-container 18789, so the allowed origins must follow the
    # operator-configured OPENCLAW_GATEWAY_PORT.
    control_ui = config.get("gateway", {}).get("controlUi")
    if isinstance(control_ui, dict) and "allowedOrigins" in control_ui:
        host_port = env.get("OPENCLAW_GATEWAY_PORT", "") or "18789"
        if not host_port.isdigit() or not 0 < int(host_port) < 65536:
            raise ValueError("OPENCLAW_GATEWAY_PORT must be a TCP port number")
        control_ui["allowedOrigins"] = [
            f"http://localhost:{host_port}",
            f"http://127.0.0.1:{host_port}",
        ]


def apply_connectors(config: dict[str, Any]) -> list[str]:
    """Inject config-driven third-party connectors (native OpenClaw MCP servers).

    Reads config/connectors.json (optional, operator-supplied, gitignored/runtime).
    Each entry adds one native `mcp.servers.<name>` block and grants its tools to
    the named research specialists via each agent's `tools.allow` glob. Secrets
    stay as `${VAR}` literals resolved by OpenClaw at load — never inlined here.
    Returns the list of enabled connector names (empty when the file is absent).
    """
    if not CONNECTORS_CONFIG.is_file() or CONNECTORS_CONFIG.is_symlink():
        return []
    definition = load_strict_json(CONNECTORS_CONFIG)
    servers = definition.get("mcp_servers")
    if not isinstance(servers, dict):
        raise ValueError("connectors.json must contain an mcp_servers object")
    agents = {
        agent["id"]: agent
        for agent in config.get("agents", {}).get("list", [])
        if isinstance(agent, dict) and "id" in agent
    }
    enabled: list[str] = []
    mcp = config.setdefault("mcp", {})
    mcp_servers = mcp.setdefault("servers", {})
    for name, entry in servers.items():
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,29}", name):
            raise ValueError(f"connector name is not a safe MCP server id: {name!r}")
        if not isinstance(entry, dict) or not isinstance(entry.get("server"), dict):
            raise ValueError(f"connector {name} must have a server object")
        if not entry.get("enabled", True):
            continue
        grant_to = entry.get("grant_to", [])
        if not isinstance(grant_to, list) or not grant_to:
            raise ValueError(f"connector {name} must grant_to at least one research specialist")
        for agent_id in grant_to:
            if agent_id not in CONNECTOR_GRANTABLE_AGENTS:
                raise ValueError(f"connector {name} may not be granted to {agent_id!r}")
            if agent_id not in agents:
                raise ValueError(f"connector {name} grants to unknown agent {agent_id!r}")
        mcp_servers[name] = entry["server"]
        tool_glob = f"{name}__*"
        for agent_id in grant_to:
            allow = agents[agent_id].setdefault("tools", {}).setdefault("allow", [])
            if tool_glob not in allow:
                allow.append(tool_glob)
        enabled.append(name)
    if not mcp_servers:
        config.pop("mcp", None)
    return enabled


def assert_effective_config(config: dict[str, Any], selected: str, env: dict[str, str]) -> None:
    channels = config.get("channels", {})
    bindings = config.get("bindings", [])
    plugin_allow = config.get("plugins", {}).get("allow", [])
    if selected == "none":
        if channels or bindings:
            raise ValueError("PRIMARY_CHANNEL=none did not render the inert base configuration")
    else:
        if set(channels) != {selected}:
            raise ValueError(f"effective config contains unexpected channels: {sorted(channels)}")
        expected_binding = [
            {"agentId": "vc-chief", "match": {"channel": selected, "accountId": "default"}}
        ]
        if bindings != expected_binding:
            raise ValueError("effective config does not contain the one exact vc-chief/default binding")
        if selected not in plugin_allow:
            raise ValueError("effective plugin allowlist omits the selected channel")
    required_plugins = {"vc-trusted-context"}
    if env["VC_MODEL_PROVIDER"] == "openai":
        required_plugins.add("openai")
    elif env["VC_MODEL_PROVIDER"] == "ollama":
        required_plugins.add("ollama")
    if env["VC_WEB_SEARCH_PROVIDER"] != "auto":
        # The selectable provider id and the plugin package id differ for
        # parallel-free (plugin id "parallel"); the allowlist carries plugin ids.
        required_plugins.add(SEARCH_PACKAGES[env["VC_WEB_SEARCH_PROVIDER"]][0])
    if env["VC_WEB_FETCH_PROVIDER"] == "firecrawl":
        required_plugins.add("firecrawl")
    if not required_plugins.issubset(set(plugin_allow)):
        raise ValueError("effective plugin allowlist omits a selected runtime provider")
    serialized = json.dumps(config, sort_keys=True)
    unresolved = sorted(
        sentinel
        for sentinel in {*SENTINEL_ENV, *LIST_SENTINELS, "__VC_CHANNEL_MEDIA_MAX_MB__"}
        if sentinel in serialized
    )
    if unresolved:
        raise ValueError(f"unresolved stable-ID sentinels: {unresolved}")


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".openclaw.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    env_requested = Path(sys.argv[1] if len(sys.argv) > 1 else PACKAGE_DIR / ".env").expanduser()
    env_path = Path(os.path.abspath(os.fspath(env_requested)))
    # Lifecycle renders (bootstrap/update/restore/rotate) omit the output
    # argument and target the in-package runtime config; only those may touch
    # deployment state. An explicit output path is a validation/test render and
    # must leave config/runtime/secrets/ untouched.
    lifecycle_render = len(sys.argv) <= 2
    output_requested = Path(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT).expanduser()
    output = Path(os.path.abspath(os.fspath(output_requested)))
    try:
        if lifecycle_render and os.path.realpath(env_path) != os.path.realpath(
            PACKAGE_DIR / ".env"
        ) and os.environ.get("OPENCLAW_RENDER_ALLOW_SNAPSHOT") != "1":
            # A lifecycle render overwrites the production runtime config and
            # all four secret files. Refuse to do that from anything but the
            # package .env, so an ad-hoc render of a scratch env cannot clobber
            # live deployment state. Validation renders pass an explicit output
            # path; the credential-rotation snapshot sets the env override.
            raise ValueError(
                "lifecycle render (no output path) only accepts the package "
                ".env; pass an explicit output path for a validation render"
            )
        values = parse_dotenv(env_path)
        errors = validate_channel_selection(values)
        if errors:
            raise ValueError("; ".join(errors))
        selected = values["PRIMARY_CHANNEL"]
        config = load_strict_json(BASE_CONFIG)
        if selected != "none":
            overlay_path = PACKAGE_DIR / "config" / PROFILE_FILES[selected]
            overlay = materialize_sentinels(load_strict_json(overlay_path), values)
            config = deep_merge(config, overlay)
        apply_runtime_selection(config, selected, values)
        connectors = apply_connectors(config)
        assert_effective_config(config, selected, values)
        payload = (json.dumps(config, indent=2, sort_keys=True) + "\n").encode("utf-8")
        write_atomic(output, payload)
        # Compose file-sourced secrets: every value is required by check_env and
        # written without a trailing newline (migrations/000_roles.sh enforces
        # single-line secrets). Non-swarm Compose bind-mounts each file into
        # /run/secrets preserving host ownership/mode, and the consumers run as
        # unprivileged container users (postgres uid 999, node), so the files
        # must be world-readable (0444). Host-side confidentiality comes from the
        # mode-0700 parent directory: only root (and the root docker daemon that
        # performs the bind mount) can traverse it, matching the .env boundary.
        if lifecycle_render:
            SECRETS_DIR.mkdir(parents=True, exist_ok=True)
            os.chmod(SECRETS_DIR, 0o700)
            for secret_name, env_key in sorted(SECRET_FILES.items()):
                secret_path = SECRETS_DIR / secret_name
                write_atomic(secret_path, values[env_key].encode("utf-8"))
                os.chmod(secret_path, 0o444)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}, indent=2), file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "result": "PASS",
                "selected_channel": selected,
                "output": str(output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "secrets_dir": str(SECRETS_DIR) if lifecycle_render else None,
                "connectors": connectors,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
