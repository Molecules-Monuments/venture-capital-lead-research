#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Validate Version 3 configs inside the exact built OpenClaw image.

This gate is deliberately offline: every container has networking disabled,
configuration is mounted read-only, and no provider or channel is contacted.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parent.parent
RENDERER = PACKAGE / "scripts/render_channel_config.py"
PROFILES = ("none", "slack", "msteams", "discord", "telegram")
# The gate must run exactly these checks: image provenance, the workshop guard,
# one schema validation per profile, and the hostile unknown-field rejection.
# Single-sourced so the offline contract test asserts the count behaviorally
# rather than grepping this file for a literal.
EXPECTED_CHECK_NAMES = (
    "image-package-provenance",
    "image-workshop-guard",
    *(f"openclaw-schema:{profile}" for profile in PROFILES),
    "openclaw-schema:unknown-field-rejected",
)
RUNTIME_VALUES = {
    "VC_MODEL_PROVIDER": "openai",
    "VC_PRIMARY_MODEL": "openai/gpt-5.6",
    "VC_FAST_MODEL": "openai/gpt-5.6",
    "VC_MODEL_INPUT": "text",
    "VC_MODEL_REASONING": "true",
    "VC_MODEL_CONTEXT_WINDOW": "272000",
    "VC_MODEL_MAX_TOKENS": "16384",
    "VC_MODEL_TIMEOUT_SECONDS": "300",
    "OPENAI_API_KEY": "offline-openai-key",
    "VC_OLLAMA_BASE_URL": "",
    "VC_CUSTOM_PROVIDER_ID": "",
    "VC_CUSTOM_BASE_URL": "",
    "VC_CUSTOM_API": "",
    "VC_CUSTOM_API_KEY": "",
    "VC_WEB_SEARCH_PROVIDER": "auto",
    "VC_WEB_FETCH_PROVIDER": "default",
    "FIRECRAWL_API_KEY": "",
    "TAVILY_API_KEY": "",
    "VC_CHANNEL_MEDIA_MAX_MB": "25",
}
EXPECTED_PACKAGES = {
    "lobster": "2026.6.11",
    "slack": "2026.7.1",
    "msteams": "2026.7.1",
    "discord": "2026.7.1",
    "telegram": "2026.7.1",
    "firecrawl": "2026.7.1",
    "tavily": "2026.7.1",
    "duckduckgo": "2026.7.1",
    "ollama": "2026.7.1",
    "trusted_context": "3.0.0",
}
EXPECTED_DEBIAN_PACKAGES = {
    "ca-certificates": "20230311+deb12u1",
    "curl": "7.88.1-10+deb12u15",
    "file": "1:5.44-3",
    "jq": "1.6-2.1+deb12u2",
    "libmagic1": "1:5.44-3",
    "poppler-utils": "22.12.0-2+deb12u2",
    "python3": "3.11.2-1+b1",
    "python3-pip": "23.0.1+dfsg-1",
    "python3-venv": "3.11.2-1+b1",
}
CHANNEL_VALUES = {
    "slack": {
        "SLACK_BOT_TOKEN": "xoxb-" + "A" * 24,
        "SLACK_APP_TOKEN": "xapp-" + "B" * 24,
        "SLACK_ALLOWED_USER_IDS": "U12345678,U87654321",
        "SLACK_ALLOWED_CHANNEL_ID": "C12345678",
    },
    "msteams": {
        "MSTEAMS_APP_ID": "11111111-1111-4111-8111-111111111111",
        "MSTEAMS_APP_PASSWORD": "offline-validation-password",
        "MSTEAMS_TENANT_ID": "22222222-2222-4222-8222-222222222222",
        "MSTEAMS_ALLOWED_USER_IDS": "33333333-3333-4333-8333-333333333333,44444444-4444-4444-8444-444444444444",
        "MSTEAMS_ALLOWED_TEAM_ID": "19:offline-team@thread.tacv2",
        "MSTEAMS_ALLOWED_CHANNEL_ID": "19:offline-channel@thread.tacv2",
        "MSTEAMS_PUBLIC_WEBHOOK_URL": "https://teams.invalid/api/messages",
    },
    "discord": {
        "DISCORD_BOT_TOKEN": "D" * 40,
        "DISCORD_APPLICATION_ID": "123456789012345678",
        "DISCORD_ALLOWED_USER_IDS": "223456789012345678,223456789012345679",
        "DISCORD_ALLOWED_GUILD_ID": "323456789012345678",
        "DISCORD_ALLOWED_CHANNEL_ID": "423456789012345678",
    },
    "telegram": {
        "TELEGRAM_BOT_TOKEN": "12345:" + "T" * 24,
        "TELEGRAM_ALLOWED_USER_IDS": "12345,12346",
        "TELEGRAM_ALLOWED_GROUP_ID": "-10012345678",
    },
}


def run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PACKAGE,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def env_values(profile: str) -> dict[str, str]:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    return {**RUNTIME_VALUES, "PRIMARY_CHANNEL": profile, **CHANNEL_VALUES.get(profile, {})}


def write_env(path: Path, profile: str) -> dict[str, str]:
    values = env_values(profile)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return values


def docker_config_command(image: str, config: Path, values: dict[str, str]) -> list[str]:
    command = [
        "docker", "run", "--rm", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
        "--memory", "512m", "-e", "HOME=/tmp/home", "-e",
        "OPENCLAW_STATE_DIR=/tmp/state", "-e",
        "OPENCLAW_CONFIG_PATH=/config/openclaw.json", "-e",
        "OPENCLAW_GATEWAY_TOKEN=offline-validation-token-00000000000000000000000000000000",
        "-e", "VC_PRIMARY_MODEL=openai/gpt-5.6", "-e",
        "VC_FAST_MODEL=openai/gpt-5.6",
    ]
    for key, value in sorted(values.items()):
        if key != "PRIMARY_CHANNEL":
            command.extend(("-e", f"{key}={value}"))
    command.extend(
        (
            "--mount", f"type=bind,src={config},target=/config/openclaw.json,readonly",
            "--entrypoint", "node", image, "dist/index.js", "config", "validate",
        )
    )
    return command


def package_provenance(image: str) -> dict[str, Any]:
    image_result = run(["docker", "image", "inspect", image], timeout=60)
    if image_result.returncode:
        raise RuntimeError(image_result.stderr.strip() or "image inspection failed")
    inspected = json.loads(image_result.stdout)
    if not isinstance(inspected, list) or len(inspected) != 1:
        raise RuntimeError("Docker returned an unexpected image inspection envelope")
    script = (
        "const fs=require('fs');"
        "const read=p=>JSON.parse(fs.readFileSync(p,'utf8')).version;"
        "console.log(JSON.stringify({"
        "lobster:read('/opt/openclaw-runtime/node_modules/@clawdbot/lobster/package.json'),"
        "slack:read('/opt/openclaw-runtime/node_modules/@openclaw/slack/package.json'),"
        "msteams:read('/opt/openclaw-runtime/node_modules/@openclaw/msteams/package.json'),"
        "discord:read('/opt/openclaw-runtime/node_modules/@openclaw/discord/package.json'),"
        "telegram:read('/app/extensions/telegram/package.json'),"
        "firecrawl:read('/opt/openclaw-runtime/node_modules/@openclaw/firecrawl-plugin/package.json'),"
        "tavily:read('/opt/openclaw-runtime/node_modules/@openclaw/tavily-plugin/package.json'),"
        "duckduckgo:read('/app/extensions/duckduckgo/package.json'),"
        "ollama:read('/app/extensions/ollama/package.json'),"
        "trusted_context:read('/opt/openclaw-extensions/vc-trusted-context/package.json')}));"
    )
    version_result = run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--entrypoint", "node", image, "-e", script,
        ],
        timeout=60,
    )
    if version_result.returncode:
        raise RuntimeError(version_result.stderr.strip() or "package inspection failed")
    versions = json.loads(version_result.stdout)
    if versions != EXPECTED_PACKAGES:
        raise RuntimeError(
            f"installed package versions differ: expected={EXPECTED_PACKAGES}, actual={versions}"
        )
    debian_result = run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--entrypoint", "dpkg-query", image, "-W", "-f=${Package}=${Version}\\n",
            *sorted(EXPECTED_DEBIAN_PACKAGES),
        ],
        timeout=60,
    )
    if debian_result.returncode:
        raise RuntimeError(debian_result.stderr.strip() or "Debian package inspection failed")
    debian_versions = dict(
        line.split("=", 1) for line in debian_result.stdout.splitlines() if "=" in line
    )
    if debian_versions != EXPECTED_DEBIAN_PACKAGES:
        raise RuntimeError(
            "installed Debian package versions differ: "
            f"expected={EXPECTED_DEBIAN_PACKAGES}, actual={debian_versions}"
        )
    return {
        "image_id": inspected[0].get("Id"),
        "repo_digests": inspected[0].get("RepoDigests", []),
        "installed_packages": versions,
        "installed_debian_packages": debian_versions,
    }


def workshop_guard_probe(image: str) -> dict[str, Any]:
    script = """
import plugin from 'file:///opt/openclaw-extensions/vc-trusted-context/index.js';
const hooks = {};
plugin.register({on: (name, handler) => { hooks[name] = handler; }});
const invoke = (action, agentId = 'vc-chief') =>
  hooks.before_tool_call({toolName: 'skill_workshop', params: {action}}, {agentId}) ?? null;
const result = {
  allowed: ['create', 'update', 'revise', 'list', 'inspect'].every((action) => invoke(action) === null),
  blocked: ['apply', 'reject', 'quarantine', 'future-action'].every((action) => invoke(action)?.block === true),
  workerBlocked: invoke('create', 'memo-writer')?.block === true,
  unrelatedAllowed: (hooks.before_tool_call(
    {toolName: 'read', params: {path: 'x'}}, {agentId: 'vc-chief'}
  ) ?? null) === null,
};
console.log(JSON.stringify(result));
"""
    result = run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--entrypoint", "node", image, "--input-type=module", "-e", script,
        ],
        timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Workshop guard probe failed")
    output = json.loads(result.stdout)
    expected = {
        "allowed": True,
        "blocked": True,
        "workerBlocked": True,
        "unrelatedAllowed": True,
    }
    if output != expected:
        raise RuntimeError(f"Workshop guard returned an unexpected result: {output}")
    return output


def render_profile(directory: Path, profile: str) -> tuple[Path, dict[str, str]]:
    env_path = directory / f"{profile}.env"
    config_path = directory / f"{profile}.json"
    values = write_env(env_path, profile)
    rendered = run([sys.executable, "-B", str(RENDERER), str(env_path), str(config_path)])
    if rendered.returncode:
        raise RuntimeError(rendered.stderr.strip() or rendered.stdout.strip())
    report = json.loads(rendered.stdout)
    if report.get("result") != "PASS" or report.get("selected_channel") != profile:
        raise RuntimeError(f"renderer returned an invalid report for {profile}")
    return config_path, values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        default="openclaw-lead-research:3.0.0",
        help="already-built local Version 3 image",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    try:
        provenance = package_provenance(args.image)
        checks.append({"name": "image-package-provenance", "result": "PASS"})
        workshop_guard_probe(args.image)
        checks.append({"name": "image-workshop-guard", "result": "PASS"})
        with tempfile.TemporaryDirectory(prefix="openclaw-v3-g6-") as raw:
            directory = Path(raw)
            rendered_profiles: dict[str, tuple[Path, dict[str, str]]] = {}
            for profile in PROFILES:
                config, values = render_profile(directory, profile)
                rendered_profiles[profile] = (config, values)
                validated = run(docker_config_command(args.image, config, values), timeout=90)
                passed = validated.returncode == 0 and "Config valid:" in validated.stdout
                checks.append(
                    {
                        "name": f"openclaw-schema:{profile}",
                        "result": "PASS" if passed else "FAIL",
                        "detail": None if passed else (validated.stderr + validated.stdout)[-10_000:],
                    }
                )

            slack_path, slack_values = rendered_profiles["slack"]
            hostile = json.loads(slack_path.read_text(encoding="utf-8"))
            hostile["channels"]["slack"]["unexpectedVersion3Probe"] = True
            invalid_path = directory / "invalid-unknown-channel-field.json"
            invalid_path.write_text(json.dumps(hostile), encoding="utf-8")
            invalid_path.chmod(0o600)
            rejected = run(
                docker_config_command(args.image, invalid_path, slack_values), timeout=90
            )
            passed = rejected.returncode != 0 and "unexpectedVersion3Probe" in (
                rejected.stderr + rejected.stdout
            )
            checks.append(
                {
                    "name": "openclaw-schema:unknown-field-rejected",
                    "result": "PASS" if passed else "FAIL",
                    "detail": None if passed else (rejected.stderr + rejected.stdout)[-10_000:],
                }
            )
    except Exception as exc:
        provenance = None
        checks.append(
            {
                "name": "image-gate-setup",
                "result": "FAIL",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    failures.extend(
        str(check.get("name")) for check in checks if check.get("result") != "PASS"
    )
    report = {
        "suite": "g6-pinned-image-channel-contract",
        "target_version": "3.0",
        "result": "PASS"
        if not failures
        and [c.get("name") for c in checks] == list(EXPECTED_CHECK_NAMES)
        else "FAIL",
        "cases": len(checks),
        "passed": sum(check.get("result") == "PASS" for check in checks),
        "failed": len(failures),
        "skipped": 0,
        "blocked": 0,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "command_or_method": f"python3 scripts/run_g6_image.py --image {args.image}",
        "failures": failures,
        "evidence_paths": [
            "Dockerfile.openclaw",
            "runtime-packages/package-lock.json",
            "runtime-extensions/vc-trusted-context/index.js",
            "scripts/run_g6_image.py",
        ],
        "provenance": provenance,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
