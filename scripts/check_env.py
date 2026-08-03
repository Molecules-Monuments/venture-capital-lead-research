#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Validate deployment configuration without evaluating shell code."""

from __future__ import annotations

import json
import ipaddress
import math
import os
import re
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit


REQUIRED = {
    "OPENCLAW_IMAGE",
    "POSTGRES_IMAGE",
    "OPENCLAW_GATEWAY_TOKEN",
    "POSTGRES_PASSWORD",
    "OPENCLAW_DB_PASSWORD",
    "VCOPS_APPROVAL_PEPPER",
    "VC_TRUSTED_CONTEXT_KEY",
    "BACKUP_HMAC_KEY",
    "VC_MODEL_PROVIDER",
    "VC_PRIMARY_MODEL",
    "VC_FAST_MODEL",
    "VC_MODEL_INPUT",
    "VC_MODEL_REASONING",
    "VC_MODEL_CONTEXT_WINDOW",
    "VC_MODEL_MAX_TOKENS",
    "VC_MODEL_TIMEOUT_SECONDS",
    "VC_WEB_SEARCH_PROVIDER",
    "VC_WEB_FETCH_PROVIDER",
    "VC_CHANNEL_MEDIA_MAX_MB",
    "PRIMARY_CHANNEL",
}

CHANNEL_FIELDS = {
    "slack": (
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "SLACK_ALLOWED_USER_IDS",
        "SLACK_ALLOWED_CHANNEL_ID",
    ),
    "msteams": (
        "MSTEAMS_APP_ID",
        "MSTEAMS_APP_PASSWORD",
        "MSTEAMS_TENANT_ID",
        "MSTEAMS_ALLOWED_USER_IDS",
        "MSTEAMS_ALLOWED_TEAM_ID",
        "MSTEAMS_ALLOWED_CHANNEL_ID",
        "MSTEAMS_PUBLIC_WEBHOOK_URL",
    ),
    "discord": (
        "DISCORD_BOT_TOKEN",
        "DISCORD_APPLICATION_ID",
        "DISCORD_ALLOWED_USER_IDS",
        "DISCORD_ALLOWED_GUILD_ID",
        "DISCORD_ALLOWED_CHANNEL_ID",
    ),
    "telegram": (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_ALLOWED_GROUP_ID",
    ),
}

# Channels that this package installs, validates, and renders correctly, but
# that the pinned harness image cannot actually run.
#
# The GHCR release prunes the Slack, Teams, and Discord distributions, so
# Dockerfile.openclaw reinstalls them from the locked npm graph into
# /opt/openclaw-runtime and render_channel_config.py names that directory in
# plugins.load.paths. A path-loaded plugin is neither `origin: "bundled"` nor a
# recorded `trustedOfficialInstall`, and the harness gates its keyed store on
# exactly that pair, so any code path reaching openKeyedStore throws.
#
# msteams reaches it while *starting*: measured on a live deployment, the
# provider exited 40 ms after "starting provider (port 3978)" with "openKeyedStore
# is only available for trusted plugins in this release", then crash-looped
# through its ten auto-restart attempts. Port 3978 was never bound, yet
# bootstrap.sh exited 0 and the container stayed `healthy` — so selecting Teams
# produced a deployment that looked correct and could not receive a single
# message. Refusing it here is the honest outcome: this package would rather
# fail commissioning loudly than hand over a silently dead channel.
#
# slack and discord are deliberately NOT listed. They carry the same
# openKeyedStore call sites and the same non-bundled origin, so they are at risk
# of the same failure once a real credential lets them past authentication — but
# that has not been observed here, and refusing a channel on suspicion would cost
# an operator a working integration. See docs/RUNBOOK.md.
#
# The upstream message says "in this release", so re-test this on the next image
# bump and delete the entry once the provider starts.
INOPERABLE_CHANNELS = {
    "msteams": (
        "the pinned image loads the Teams plugin from a path, which the harness "
        "does not treat as a trusted plugin, so the provider crash-loops on "
        "startup and never binds its webhook port while the gateway still reports "
        "healthy (see docs/RUNBOOK.md)"
    ),
}

DEPLOYMENT_FIELDS = {
    "TZ",
    "OPENCLAW_HOST",
    "OPENCLAW_GATEWAY_PORT",
    "MSTEAMS_WEBHOOK_HOST",
    "MSTEAMS_WEBHOOK_PORT",
    "VC_QUARANTINE_VOLUME",
    "OPENCLAW_RUNTIME_CONFIG_VOLUME",
    "POSTGRES_MEMORY_LIMIT",
    "POSTGRES_CPU_LIMIT",
    "POSTGRES_LOG_MAX_SIZE",
    "POSTGRES_LOG_MAX_FILES",
    "OPENCLAW_INIT_MEMORY_LIMIT",
    "OPENCLAW_INIT_CPU_LIMIT",
    "OPENCLAW_INIT_LOG_MAX_SIZE",
    "OPENCLAW_INIT_LOG_MAX_FILES",
    "OPENCLAW_GATEWAY_MEMORY_LIMIT",
    "OPENCLAW_GATEWAY_CPU_LIMIT",
    "OPENCLAW_GATEWAY_LOG_MAX_SIZE",
    "OPENCLAW_GATEWAY_LOG_MAX_FILES",
    "OPENCLAW_CLI_MEMORY_LIMIT",
    "OPENCLAW_CLI_CPU_LIMIT",
    "OPENCLAW_CLI_LOG_MAX_SIZE",
    "OPENCLAW_CLI_LOG_MAX_FILES",
}
ALLOWED_KEYS = REQUIRED | DEPLOYMENT_FIELDS | {
    key for fields in CHANNEL_FIELDS.values() for key in fields
} | {
    "OPENAI_API_KEY",
    "VC_OLLAMA_BASE_URL",
    "VC_CUSTOM_PROVIDER_ID",
    "VC_CUSTOM_BASE_URL",
    "VC_CUSTOM_API",
    "VC_CUSTOM_API_KEY",
    "FIRECRAWL_API_KEY",
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
    "PERPLEXITY_API_KEY",
    "EXA_API_KEY",
    "SEARXNG_BASE_URL",
    # Third-party research-connector (MCP) secrets for the shipped example
    # connectors. Optional: set only when the matching connectors.json entry is
    # enabled. A connector that uses a different variable name must add it here
    # and to the docker-compose gateway/cli environment (a commissioning step —
    # see third_party_connectors.md).
    "CRUNCHBASE_API_KEY",
    "PITCHBOOK_API_KEY",
    "DEALROOM_API_KEY",
    # Optional: raises the bound backup.sh/restore.sh apply to the state
    # recovery archive. Document intake snapshots accumulate in that tier, so a
    # deployment with sustained attachment volume outgrows the shipped default.
    "OPENCLAW_STATE_ARCHIVE_MAX_BYTES",
}
STATE_ARCHIVE_DEFAULT_BYTES = 2 * 1024 * 1024 * 1024
STATE_ARCHIVE_MAX_BYTES = 100 * 1024 * 1024 * 1024
# The harness reserves a fixed slice of every context window for compaction
# headroom (`reserveTokensFloor ... ?? 2e4` in the pinned image's memory-core
# extension). This package does not override it — its only
# agents.defaults.compaction setting is memoryFlush.enabled — so the prompt
# budget an agent actually gets is VC_MODEL_CONTEXT_WINDOW minus this number.
MODEL_COMPACTION_RESERVE_TOKENS = 20_000
# The chief's assembled system prompt measured 40,137 characters / 12,669
# tokens on a live deployment (contextBudgetStatus.estimatedPromptTokens).
# Rounded up so a small future addition to the reviewed policy artifacts does
# not silently invalidate the floor below.
CHIEF_SYSTEM_PROMPT_TOKENS = 12_700
# Room for one document extract or tool result plus a few conversation turns.
# Without this the deployment validates, boots, and then answers every message
# with "Context overflow: prompt too large for the model" — which the harness
# returns as a normal payload with status "ok" and CLI exit code 0, so nothing
# an operator would check reports a failure.
MODEL_MIN_WORKING_TOKENS = 4_096
MODEL_CONTEXT_WINDOW_FLOOR = (
    MODEL_COMPACTION_RESERVE_TOKENS + CHIEF_SYSTEM_PROMPT_TOKENS + MODEL_MIN_WORKING_TOKENS
)
# A local model is prompted with the same ~12.7k-token system prompt as a hosted
# one, but prefills it on the deployment host's own CPU or GPU. Measured on a
# CPU-only host: 331.4 s to prefill 10,847 tokens at 32.7 tok/s — over the
# shipped 300 s default, so the *first* turn after every model load failed with
# "FailoverError: LLM request timed out". Prompt caching then made the retry
# succeed in 5.2 s, which is what makes it a commissioning trap rather than an
# obvious failure. Hosted providers are unaffected: this is a ceiling, not a wait.
OLLAMA_MIN_TIMEOUT_SECONDS = 600
FORBIDDEN_AMBIENT_COMPOSE_KEYS = {
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES",
    # Rebases the relative paths Compose resolves (build contexts, bind mounts)
    # and has no legitimate use here, since every lifecycle script passes an
    # explicit -f/-p/--env-file. DOCKER_HOST and DOCKER_CONTEXT are deliberately
    # absent: they are how an operator legitimately targets a rootless socket or
    # a remote engine, so failing on them would block a supported deployment.
    "COMPOSE_PROJECT_DIR",
}

# Microsoft directory object IDs (app, tenant, user) are GUIDs in the plain
# 8-4-4-4-12 hexadecimal form. This deliberately does NOT demand the RFC-4122
# version (1-5) and variant (8|9|a|b) nibbles: Entra guarantees the format, not
# those bits, and historic tenants do contain GUIDs that do not conform. Every
# such value would have been refused as "not a stable UUID" — a message pointing
# at the wrong cause, for an identifier that is perfectly stable.
#
# What this check exists to reject is a display name or a UPN in place of an
# immutable object ID, and the shape alone establishes that. The all-zero GUID
# is refused separately: it is well-formed but never a real principal.
MSTEAMS_GUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
NIL_GUID = "00000000-0000-0000-0000-000000000000"

OPENCLAW_IMAGE = (
    "ghcr.io/openclaw/openclaw:2026.7.1@"
    "sha256:6a31d44b2944e7adcd2b582bf6fb463111264ebca97a0201795b799135bd102c"
)
POSTGRES_IMAGE = (
    "postgres:17.10-bookworm@"
    "sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394"
)
VOLUME_DEFAULTS = {
    "OPENCLAW_RUNTIME_CONFIG_VOLUME": "openclaw-lead-research-v3_runtime-config",
    "VC_QUARANTINE_VOLUME": "openclaw-lead-research-v3_vc-quarantine",
}
FIXED_PROJECT_VOLUMES = {
    "postgres-data": "openclaw-lead-research-v3_postgres-data",
    "openclaw-state": "openclaw-lead-research-v3_openclaw-state",
}
# The six independently generated deployment secrets. No two may be equal; see
# the pairwise-distinctness check in validate().
DEPLOYMENT_SECRET_KEYS = (
    "OPENCLAW_GATEWAY_TOKEN",
    "POSTGRES_PASSWORD",
    "OPENCLAW_DB_PASSWORD",
    "VCOPS_APPROVAL_PEPPER",
    "VC_TRUSTED_CONTEXT_KEY",
    "BACKUP_HMAC_KEY",
)
# Compose defaults for the two published host ports. check_env must fold these
# in before checking for a collision: a .env that leaves one blank and sets the
# other to the omitted one's default would otherwise validate and then fail at
# `docker compose up` with a port-bind error.
PORT_DEFAULTS = {
    "OPENCLAW_GATEWAY_PORT": 18789,
    "MSTEAMS_WEBHOOK_PORT": 3978,
}


def parse_dotenv(path: Path) -> dict[str, str]:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{path}: environment file must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path}: environment file must be a regular file")
    if metadata.st_size > 1024 * 1024:
        raise ValueError(f"{path}: environment file exceeds the 1 MiB limit")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode != 0o600:
        raise ValueError(f"{path}: permissions are {mode:04o}; required mode is 0600")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{path}: environment file changed to a non-regular file")
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError(f"{path}: environment file changed while it was being opened")
        if stat.S_IMODE(opened.st_mode) != 0o600 or opened.st_size > 1024 * 1024:
            raise ValueError(f"{path}: environment file mode or size changed while opening")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            content = handle.read(1024 * 1024 + 1)
            if len(content) > 1024 * 1024:
                raise ValueError(f"{path}: environment file grew beyond the 1 MiB limit")
            # str.splitlines() strips a trailing \r, so a CRLF file would parse
            # cleanly here and pass every check — then bootstrap.sh's
            # `grep | cut` image lookup keeps the \r and `docker pull` fails
            # with a bare "invalid reference format". Reject it with an
            # actionable message instead of failing opaquely three steps later.
            if b"\r\n" in content or b"\r" in content:
                raise ValueError(
                    f"{path}: environment file has CRLF (Windows) line endings; "
                    "convert it to LF, e.g. `tr -d '\\r' < .env > .env.lf && "
                    "mv .env.lf .env && chmod 0600 .env`"
                )
            lines = content.decode("utf-8").splitlines()
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    values: dict[str, str] = {}
    first_seen: dict[str, int] = {}
    for number, raw in enumerate(lines, 1):
        if not raw or raw.startswith("#"):
            continue
        if raw != raw.strip():
            raise ValueError(f"line {number}: surrounding whitespace is forbidden")
        if raw.startswith("export "):
            raise ValueError(f"line {number}: export syntax is forbidden; use exact KEY=VALUE")
        if "=" not in raw:
            raise ValueError(f"line {number}: expected KEY=VALUE")
        key, value = raw.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"line {number}: invalid key {key!r}")
        if key in first_seen:
            raise ValueError(
                f"line {number}: duplicate key {key!r}; first defined on line {first_seen[key]}"
            )
        if re.search(r"[\s$'\"\\#]", value) or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(
                f"line {number}: value for {key} uses whitespace, substitution, quoting, "
                "escaping, comment, or control syntax; canonical env values must be literal"
            )
        values[key] = value
        first_seen[key] = number
    return values


def validate_channel_selection(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    selected = values.get("PRIMARY_CHANNEL", "")
    allowed = {"none", *CHANNEL_FIELDS}
    if selected not in allowed:
        errors.append(f"PRIMARY_CHANNEL must be one of {sorted(allowed)}")
        return errors
    if selected in INOPERABLE_CHANNELS:
        errors.append(
            f"PRIMARY_CHANNEL={selected} cannot be operated on the pinned image: "
            + INOPERABLE_CHANNELS[selected]
        )

    populated = {
        profile: [key for key in fields if values.get(key, "")]
        for profile, fields in CHANNEL_FIELDS.items()
    }
    complete = {
        profile: bool(fields) and all(values.get(key, "") for key in fields)
        for profile, fields in CHANNEL_FIELDS.items()
    }

    for profile, fields in CHANNEL_FIELDS.items():
        if populated[profile] and not complete[profile]:
            missing = [key for key in fields if not values.get(key, "")]
            errors.append(f"{profile} values are partial; missing: {missing}")

    if selected == "none":
        nonempty = [profile for profile, fields in populated.items() if fields]
        if nonempty:
            errors.append(
                "PRIMARY_CHANNEL=none requires every channel credential/ID family to be empty; "
                f"found: {nonempty}"
            )
        return errors

    if not complete[selected]:
        errors.append(f"PRIMARY_CHANNEL={selected} requires its complete credential and stable-ID family")
    nonselected = [
        profile for profile, fields in populated.items() if profile != selected and fields
    ]
    if nonselected:
        errors.append(f"unselected channel families must be empty; found: {nonselected}")

    if selected == "slack" and complete[selected]:
        if not re.fullmatch(r"xoxb-[A-Za-z0-9-]{20,}", values["SLACK_BOT_TOKEN"]):
            errors.append("SLACK_BOT_TOKEN must be an xoxb- bot token")
        if not re.fullmatch(r"xapp-[A-Za-z0-9-]{20,}", values["SLACK_APP_TOKEN"]):
            errors.append("SLACK_APP_TOKEN must be an xapp- app-level token")
        users = _comma_list(values["SLACK_ALLOWED_USER_IDS"], "SLACK_ALLOWED_USER_IDS", errors)
        if any(not re.fullmatch(r"[UW][A-Z0-9]{8,}", item) for item in users):
            errors.append("SLACK_ALLOWED_USER_IDS must contain stable U… or W… IDs")
        if not re.fullmatch(r"[CG][A-Z0-9]{8,}", values["SLACK_ALLOWED_CHANNEL_ID"]):
            errors.append("SLACK_ALLOWED_CHANNEL_ID must be a stable C… or G… ID")

    if selected == "msteams" and complete[selected]:
        for key in ("MSTEAMS_APP_ID", "MSTEAMS_TENANT_ID"):
            if not MSTEAMS_GUID_RE.fullmatch(values[key]):
                errors.append(
                    f"{key} must be a directory object GUID in 8-4-4-4-12 hexadecimal form, "
                    "not a display name or UPN"
                )
            elif values[key].lower() == NIL_GUID:
                errors.append(f"{key} must not be the all-zero GUID")
        users = _comma_list(values["MSTEAMS_ALLOWED_USER_IDS"], "MSTEAMS_ALLOWED_USER_IDS", errors)
        if any(not MSTEAMS_GUID_RE.fullmatch(item) for item in users):
            errors.append(
                "MSTEAMS_ALLOWED_USER_IDS must contain directory object GUIDs in 8-4-4-4-12 "
                "hexadecimal form, not display names or UPNs"
            )
        elif any(item.lower() == NIL_GUID for item in users):
            errors.append("MSTEAMS_ALLOWED_USER_IDS must not contain the all-zero GUID")
        if len(values["MSTEAMS_APP_PASSWORD"]) < 16 or re.search(r"\s", values["MSTEAMS_APP_PASSWORD"]):
            errors.append("MSTEAMS_APP_PASSWORD must contain at least 16 non-whitespace characters")
        conversation_id = re.compile(r"19:[^\s/]{5,}@thread\.(?:tacv2|skype)")
        if not conversation_id.fullmatch(values["MSTEAMS_ALLOWED_TEAM_ID"]):
            errors.append("MSTEAMS_ALLOWED_TEAM_ID must be a stable Teams conversation ID")
        if not conversation_id.fullmatch(values["MSTEAMS_ALLOWED_CHANNEL_ID"]):
            errors.append("MSTEAMS_ALLOWED_CHANNEL_ID must be a stable Teams conversation ID")
        webhook = values["MSTEAMS_PUBLIC_WEBHOOK_URL"]
        if not _valid_custom_base_url(webhook) or urlsplit(webhook).path != "/api/messages":
            errors.append(
                "MSTEAMS_PUBLIC_WEBHOOK_URL must be a credential-free public HTTPS "
                "URL ending in /api/messages"
            )

    if selected == "discord" and complete[selected]:
        snowflake = re.compile(r"[1-9][0-9]{14,21}")
        for key in (
            "DISCORD_APPLICATION_ID",
            "DISCORD_ALLOWED_GUILD_ID",
            "DISCORD_ALLOWED_CHANNEL_ID",
        ):
            if not snowflake.fullmatch(values[key]):
                errors.append(f"{key} must be a numeric Discord snowflake")
        users = _comma_list(values["DISCORD_ALLOWED_USER_IDS"], "DISCORD_ALLOWED_USER_IDS", errors)
        if any(not snowflake.fullmatch(item) for item in users):
            errors.append("DISCORD_ALLOWED_USER_IDS must contain numeric Discord snowflakes")
        token = values["DISCORD_BOT_TOKEN"]
        if len(token) < 32 or re.search(r"\s", token):
            errors.append("DISCORD_BOT_TOKEN must contain at least 32 non-whitespace characters")

    if selected == "telegram" and complete[selected]:
        if not re.fullmatch(r"[1-9][0-9]{4,14}:[A-Za-z0-9_-]{20,}", values["TELEGRAM_BOT_TOKEN"]):
            errors.append("TELEGRAM_BOT_TOKEN must use the numeric-id:secret Bot API format")
        users = _comma_list(values["TELEGRAM_ALLOWED_USER_IDS"], "TELEGRAM_ALLOWED_USER_IDS", errors)
        if any(not re.fullmatch(r"[1-9][0-9]{3,14}", item) for item in users):
            errors.append("TELEGRAM_ALLOWED_USER_IDS must contain positive numeric user IDs")
        if not re.fullmatch(r"-100[0-9]{5,15}", values["TELEGRAM_ALLOWED_GROUP_ID"]):
            errors.append("TELEGRAM_ALLOWED_GROUP_ID must be a negative -100… supergroup ID")
    return errors


def _comma_list(value: str, name: str, errors: list[str]) -> list[str]:
    items = value.split(",") if value else []
    if not items or any(not item for item in items):
        errors.append(f"{name} must be a comma-separated list without empty entries")
        return []
    if len(items) > 100:
        errors.append(f"{name} exceeds the 100-user deployment limit")
    if len(set(items)) != len(items):
        errors.append(f"{name} contains duplicate stable IDs")
    return items


def _ascii_int(raw: str) -> int | None:
    """Parse an ASCII-only integer, or None.

    str.isdigit() is true for superscripts and other Unicode digit forms:
    int('²') raises (a traceback instead of this validator's FAIL envelope) and
    int('٣') succeeds on a value Compose cannot read back.
    """
    return int(raw) if re.fullmatch(r"[0-9]+", raw) else None


def _valid_ollama_origin(value: str) -> bool:
    """Accept only a path-free HTTP origin on a private/local deployment host."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or not 1 <= port <= 65_535
    ):
        return False
    hostname = parsed.hostname.lower()
    if hostname == "host.docker.internal" or hostname.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # A single-label hostname may name an explicitly attached Compose/LAN host.
        return "." not in hostname and bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", hostname))
    return address.is_private or address.is_link_local


def _valid_custom_base_url(value: str) -> bool:
    """Accept only a credential-free HTTPS base URL with an optional path."""
    if not value or any(character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        # SplitResult.port parses lazily and raises here on a non-numeric or
        # out-of-range port, which the character-class regex this replaces
        # silently accepted.
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65_535)
    )


def validate_runtime_selection(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    mode = values.get("VC_MODEL_PROVIDER", "")
    if mode not in {"openai", "ollama", "custom"}:
        errors.append("VC_MODEL_PROVIDER must be one of openai, ollama, custom")
        return errors
    provider = {
        "openai": "openai",
        "ollama": "ollama",
        "custom": values.get("VC_CUSTOM_PROVIDER_ID", ""),
    }[mode]
    if mode == "custom" and not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", provider):
        errors.append("VC_CUSTOM_PROVIDER_ID must be a lowercase provider ID")
    for key in ("VC_PRIMARY_MODEL", "VC_FAST_MODEL"):
        value = values.get(key, "")
        if value and ("/" not in value or value.split("/", 1)[0] != provider):
            errors.append(f"{key} must use the configured {provider or '<provider>'}/model prefix")
    if values.get("VC_MODEL_INPUT") not in {"text", "text,image"}:
        errors.append("VC_MODEL_INPUT must be text or text,image")
    if values.get("VC_MODEL_REASONING") not in {"true", "false"}:
        errors.append("VC_MODEL_REASONING must be true or false")
    for key, minimum, maximum in (
        ("VC_MODEL_CONTEXT_WINDOW", MODEL_CONTEXT_WINDOW_FLOOR, 4_000_000),
        ("VC_MODEL_MAX_TOKENS", 1_024, 262_144),
        ("VC_MODEL_TIMEOUT_SECONDS", 30, 900),
    ):
        raw = values.get(key, "")
        parsed = _ascii_int(raw)
        if parsed is None or not minimum <= parsed <= maximum:
            errors.append(f"{key} must be an integer from {minimum} through {maximum}")
            if key == "VC_MODEL_CONTEXT_WINDOW":
                # The bare range is not actionable on its own: the floor is
                # derived, and a window under it produces a deployment that
                # validates and boots but cannot answer a single message.
                errors.append(
                    f"VC_MODEL_CONTEXT_WINDOW must leave the agent a usable prompt budget: "
                    f"{MODEL_COMPACTION_RESERVE_TOKENS} tokens are reserved by the runtime for "
                    f"compaction, the chief's system prompt is about {CHIEF_SYSTEM_PROMPT_TOKENS}, "
                    f"and {MODEL_MIN_WORKING_TOKENS} are needed for a document or tool result"
                )
    if mode == "openai":
        if not values.get("OPENAI_API_KEY"):
            errors.append("OPENAI_API_KEY is required when VC_MODEL_PROVIDER=openai")
        if any(values.get(key) for key in ("VC_OLLAMA_BASE_URL", "VC_CUSTOM_PROVIDER_ID", "VC_CUSTOM_BASE_URL", "VC_CUSTOM_API", "VC_CUSTOM_API_KEY")):
            errors.append("OpenAI mode requires Ollama/custom model fields to remain empty")
    elif mode == "ollama":
        url = values.get("VC_OLLAMA_BASE_URL", "")
        if not _valid_ollama_origin(url):
            errors.append(
                "VC_OLLAMA_BASE_URL must be a private IP, .local, host.docker.internal, "
                "or single-label HTTP origin with an explicit port and no API path, credentials, query, or fragment"
            )
        if any(values.get(key) for key in ("OPENAI_API_KEY", "VC_CUSTOM_PROVIDER_ID", "VC_CUSTOM_BASE_URL", "VC_CUSTOM_API", "VC_CUSTOM_API_KEY")):
            errors.append("Ollama mode requires OpenAI/custom model fields to remain empty")
        timeout = _ascii_int(values.get("VC_MODEL_TIMEOUT_SECONDS", ""))
        if timeout is not None and timeout < OLLAMA_MIN_TIMEOUT_SECONDS:
            errors.append(
                f"VC_MODEL_TIMEOUT_SECONDS must be at least {OLLAMA_MIN_TIMEOUT_SECONDS} in Ollama "
                "mode: the first turn after each model load prefills the whole system prompt on the "
                "deployment host, which measured 331 s on a CPU-only host and times out under the "
                "shipped 300 s default"
            )
    else:
        # Every adapter here authenticates with the single API key this renderer
        # emits. bedrock-converse-stream is deliberately absent: OpenClaw signs
        # Bedrock requests through the AWS credential chain, which it uses only
        # for a provider whose auth is "aws-sdk" and which carries no apiKey —
        # neither of which this renderer can express — so the mode would
        # validate here and then fail at the first model call.
        allowed_apis = {
            "openai-completions", "openai-responses", "anthropic-messages",
            "google-generative-ai", "google-vertex", "azure-openai-responses",
        }
        if values.get("VC_CUSTOM_API") not in allowed_apis:
            errors.append(f"VC_CUSTOM_API must be one of {sorted(allowed_apis)}")
        if not _valid_custom_base_url(values.get("VC_CUSTOM_BASE_URL", "")):
            errors.append("VC_CUSTOM_BASE_URL must be an HTTPS URL without credentials, query, or fragment")
        if not values.get("VC_CUSTOM_API_KEY"):
            errors.append("VC_CUSTOM_API_KEY is required in custom model mode")
        if values.get("OPENAI_API_KEY") or values.get("VC_OLLAMA_BASE_URL"):
            errors.append("Custom model mode requires OpenAI/Ollama fields to remain empty")

    # Native OpenClaw web-search providers. duckduckgo (keyless), firecrawl, and
    # tavily ship in the image; brave/perplexity/exa/searxng/parallel-free are
    # native too but their plugin package must be present in the image (a
    # documented commissioning step for a non-bundled provider — see
    # CUSTOMIZATION.md). parallel-free is the keyless variant of the parallel
    # plugin; the paid "parallel" provider (PARALLEL_API_KEY) is not offered.
    search_credential = {
        "brave": "BRAVE_API_KEY",
        "perplexity": "PERPLEXITY_API_KEY",
        "exa": "EXA_API_KEY",
        "searxng": "SEARXNG_BASE_URL",
    }
    keyless_search = {"auto", "duckduckgo", "parallel-free"}
    search = values.get("VC_WEB_SEARCH_PROVIDER", "")
    if search not in keyless_search | {"firecrawl", "tavily"} | set(search_credential):
        errors.append(
            "VC_WEB_SEARCH_PROVIDER must be one of auto, duckduckgo, firecrawl, tavily, "
            "brave, perplexity, exa, searxng, parallel-free"
        )
    if mode in {"ollama", "custom"} and search == "auto":
        errors.append("Ollama/custom model mode requires an explicit web-search provider")
    if values.get("VC_WEB_FETCH_PROVIDER") not in {"default", "firecrawl"}:
        errors.append("VC_WEB_FETCH_PROVIDER must be default or firecrawl")
    needs_firecrawl = search == "firecrawl" or values.get("VC_WEB_FETCH_PROVIDER") == "firecrawl"
    if needs_firecrawl != bool(values.get("FIRECRAWL_API_KEY")):
        errors.append("FIRECRAWL_API_KEY must be set exactly when Firecrawl search or fetch is selected")
    if (search == "tavily") != bool(values.get("TAVILY_API_KEY")):
        errors.append("TAVILY_API_KEY must be set exactly when Tavily is selected")
    for provider, credential in search_credential.items():
        if (search == provider) != bool(values.get(credential)):
            errors.append(f"{credential} must be set exactly when the {provider} search provider is selected")
    searxng = values.get("SEARXNG_BASE_URL", "")
    # A self-hosted SearXNG is reached either over public HTTPS or, more often,
    # as a plain-HTTP origin on the deployment's own private network — accept
    # exactly the two shapes the sibling endpoint validators already define.
    if searxng and not (_valid_custom_base_url(searxng) or _valid_ollama_origin(searxng)):
        errors.append(
            "SEARXNG_BASE_URL must be a credential-free HTTPS URL or a private/local HTTP origin"
        )
    state_cap = values.get("OPENCLAW_STATE_ARCHIVE_MAX_BYTES", "")
    if state_cap:
        # A bound that is not a plain positive integer would reach
        # validate_recovery_archive.py as a malformed --max-total-bytes and fail
        # the backup mid-run instead of here.
        if not re.fullmatch(r"[1-9][0-9]{0,14}", state_cap) or not (
            1024 * 1024 * 1024 <= int(state_cap) <= STATE_ARCHIVE_MAX_BYTES
        ):
            errors.append(
                "OPENCLAW_STATE_ARCHIVE_MAX_BYTES must be an integer number of bytes "
                f"from {1024 * 1024 * 1024} through {STATE_ARCHIVE_MAX_BYTES}"
            )
    media = values.get("VC_CHANNEL_MEDIA_MAX_MB", "")
    try:
        parsed_media = float(media)
    except ValueError:
        parsed_media = 0
    if not math.isfinite(parsed_media) or not 1 <= parsed_media <= 50:
        errors.append("VC_CHANNEL_MEDIA_MAX_MB must be a number from 1 through 50")
    return errors


def main() -> int:
    requested = Path(sys.argv[1] if len(sys.argv) > 1 else ".env").expanduser()
    path = Path(os.path.abspath(os.fspath(requested)))
    errors: list[str] = []
    warnings: list[str] = []
    try:
        values = parse_dotenv(path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}, indent=2))
        return 1

    missing = sorted(key for key in REQUIRED if not values.get(key))
    if missing:
        errors.append(f"required values are empty: {missing}")

    unknown = sorted(set(values) - ALLOWED_KEYS)
    if unknown:
        errors.append(f"unknown environment keys are forbidden: {unknown}")

    ambient_compose = sorted(key for key in FORBIDDEN_AMBIENT_COMPOSE_KEYS if key in os.environ)
    if ambient_compose:
        errors.append(
            "ambient Compose steering variables are forbidden for this release: "
            f"{ambient_compose}"
        )

    shadowed = sorted(
        key for key, value in values.items() if key in os.environ and os.environ[key] != value
    )
    if shadowed:
        errors.append(
            "ambient environment would override the reviewed .env values in Docker Compose: "
            f"{shadowed}; unset them or make them byte-identical"
        )

    # Compose gives the OS environment precedence even over ${VAR:-default}
    # defaults, so an ambient variable for an allowed key whose line was
    # removed from .env would steer the deployment without ever passing
    # through this validator.
    ambient_only = sorted(
        key for key in ALLOWED_KEYS - set(values) if key in os.environ
    )
    if ambient_only:
        errors.append(
            "ambient environment supplies deployment variables absent from the "
            f"reviewed .env: {ambient_only}; unset them or add the reviewed "
            "values to .env"
        )

    if values.get("OPENCLAW_IMAGE") != OPENCLAW_IMAGE:
        errors.append(f"OPENCLAW_IMAGE must be {OPENCLAW_IMAGE}")
    if values.get("POSTGRES_IMAGE") != POSTGRES_IMAGE:
        errors.append(f"POSTGRES_IMAGE must be {POSTGRES_IMAGE}")
    if not re.fullmatch(r"[0-9a-fA-F]{64,}", values.get("OPENCLAW_GATEWAY_TOKEN", "")):
        errors.append("OPENCLAW_GATEWAY_TOKEN must be at least 64 hexadecimal characters")
    for key in ("POSTGRES_PASSWORD", "OPENCLAW_DB_PASSWORD"):
        value = values.get(key, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", value):
            errors.append(
                f"{key} must contain 24-128 base64url-safe characters "
                "(letters, digits, underscore, or hyphen)"
            )
    if len(values.get("VCOPS_APPROVAL_PEPPER", "")) < 32:
        errors.append("VCOPS_APPROVAL_PEPPER must contain at least 32 characters")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", values.get("VC_TRUSTED_CONTEXT_KEY", "")):
        errors.append("VC_TRUSTED_CONTEXT_KEY must be exactly 64 hexadecimal characters")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", values.get("BACKUP_HMAC_KEY", "")):
        errors.append("BACKUP_HMAC_KEY must be exactly 64 hexadecimal characters")
    # Every one of the six deployment secrets must be independently generated.
    # README, RUNBOOK, and .env.example each print a separate `openssl rand`
    # line per field, but that rule was previously machine-checked for only two
    # of the fifteen possible pairings. Reuse is not symmetric in consequence:
    # OPENCLAW_GATEWAY_TOKEN is handed to every gateway client and is visible in
    # `docker inspect`, while VC_TRUSTED_CONTEXT_KEY signs the capability tokens
    # vcops verifies — so a deployment that sets both to the same value lets
    # anyone holding the gateway token mint trusted context for any sender.
    # Check all pairings, keeping the two specific legacy messages intact.
    if values.get("POSTGRES_PASSWORD") == values.get("OPENCLAW_DB_PASSWORD") and values.get("POSTGRES_PASSWORD"):
        errors.append("owner and runtime database passwords must differ")
    if values.get("BACKUP_HMAC_KEY") and values.get("BACKUP_HMAC_KEY") in {
        values.get("OPENCLAW_GATEWAY_TOKEN"),
        values.get("VCOPS_APPROVAL_PEPPER"),
        values.get("VC_TRUSTED_CONTEXT_KEY"),
    }:
        errors.append("BACKUP_HMAC_KEY must not be reused as another deployment secret")
    first_use: dict[str, str] = {}
    for key in DEPLOYMENT_SECRET_KEYS:
        value = values.get(key, "")
        if not value:
            continue
        if value in first_use:
            errors.append(
                f"{key} must not reuse the value of {first_use[value]}; generate every "
                "deployment secret independently with `openssl rand -hex 32`"
            )
        else:
            first_use[value] = key
    for key in ("VC_PRIMARY_MODEL", "VC_FAST_MODEL"):
        value = values.get(key, "")
        if value and ("/" not in value or re.search(r"replace|placeholder|example", value, re.I)):
            errors.append(f"{key} is not a concrete provider/model reference")
    if (
        values.get("VC_PRIMARY_MODEL")
        and values.get("VC_PRIMARY_MODEL") == values.get("VC_FAST_MODEL")
    ):
        warnings.append(
            "VC_PRIMARY_MODEL and VC_FAST_MODEL are identical; this is safe but "
            "does not create a cost/latency tier. Record the deliberate choice and "
            "benchmark in config/customization-profile.json."
        )

    for key in ("OPENCLAW_HOST", "MSTEAMS_WEBHOOK_HOST"):
        value = values.get(key, "")
        if value and value != "127.0.0.1":
            errors.append(f"{key} must remain 127.0.0.1")
    ports: dict[str, int] = {}
    for key, default in PORT_DEFAULTS.items():
        value = values.get(key, "")
        if not value:
            # An omitted port is not absent at runtime — Compose substitutes its
            # default. Fold it in so the collision check below sees the ports
            # the deployment will actually bind, matching how the volume check
            # below already folds in VOLUME_DEFAULTS.
            ports[key] = default
            continue
        parsed_port = _ascii_int(value)
        if parsed_port is None or not 1 <= parsed_port <= 65535:
            errors.append(f"{key} must be an integer from 1 through 65535")
        else:
            ports[key] = parsed_port
    if len(ports) == 2 and len(set(ports.values())) != 2:
        errors.append(
            "OPENCLAW_GATEWAY_PORT and MSTEAMS_WEBHOOK_PORT must bind different host "
            f"ports; the effective values collide: {ports}"
        )

    for key in ("VC_QUARANTINE_VOLUME", "OPENCLAW_RUNTIME_CONFIG_VOLUME"):
        value = values.get(key, "")
        if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,127}", value):
            errors.append(f"{key} must be a stable Docker volume name")
    effective_volumes = {
        **FIXED_PROJECT_VOLUMES,
        **{
            key: values.get(key, "") or default
            for key, default in VOLUME_DEFAULTS.items()
        },
    }
    names_to_roles: dict[str, list[str]] = {}
    for role, volume_name in effective_volumes.items():
        names_to_roles.setdefault(volume_name, []).append(role)
    collisions = {
        name: roles for name, roles in names_to_roles.items() if len(roles) > 1
    }
    if collisions:
        errors.append(
            "Postgres, OpenClaw state, runtime config, and quarantine "
            f"must use four distinct effective Docker volumes: {collisions}"
        )

    memory_fields = (
        "POSTGRES_MEMORY_LIMIT",
        "OPENCLAW_INIT_MEMORY_LIMIT",
        "OPENCLAW_GATEWAY_MEMORY_LIMIT",
        "OPENCLAW_CLI_MEMORY_LIMIT",
    )
    for key in memory_fields:
        value = values.get(key, "")
        if value and not re.fullmatch(r"[1-9][0-9]*(?:[kKmMgGtT](?:[bB])?|[bB])?", value):
            errors.append(f"{key} must be a positive Docker byte-size value")
    for key in (
        "POSTGRES_CPU_LIMIT",
        "OPENCLAW_INIT_CPU_LIMIT",
        "OPENCLAW_GATEWAY_CPU_LIMIT",
        "OPENCLAW_CLI_CPU_LIMIT",
    ):
        value = values.get(key, "")
        if value:
            try:
                parsed = float(value)
            except ValueError:
                parsed = 0.0
            if not math.isfinite(parsed) or parsed <= 0:
                errors.append(f"{key} must be a positive finite CPU count")
    for key in (
        "POSTGRES_LOG_MAX_SIZE",
        "OPENCLAW_INIT_LOG_MAX_SIZE",
        "OPENCLAW_GATEWAY_LOG_MAX_SIZE",
        "OPENCLAW_CLI_LOG_MAX_SIZE",
    ):
        value = values.get(key, "")
        if value and not re.fullmatch(r"[1-9][0-9]*[kKmMgG]", value):
            errors.append(f"{key} must be a positive json-file size such as 10m")
    for key in (
        "POSTGRES_LOG_MAX_FILES",
        "OPENCLAW_INIT_LOG_MAX_FILES",
        "OPENCLAW_GATEWAY_LOG_MAX_FILES",
        "OPENCLAW_CLI_LOG_MAX_FILES",
    ):
        value = values.get(key, "")
        parsed_files = _ascii_int(value)
        if value and (parsed_files is None or parsed_files < 1):
            errors.append(f"{key} must be a positive integer")

    errors.extend(validate_channel_selection(values))
    errors.extend(validate_runtime_selection(values))

    report = {
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checked_file": str(path),
        "channels_with_complete_credentials": [
            profile
            for profile, fields in CHANNEL_FIELDS.items()
            if all(values.get(key, "") for key in fields)
        ],
        "selected_channel": values.get("PRIMARY_CHANNEL", ""),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
