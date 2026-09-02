#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
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
# The two reviewed artifacts this gate validates directly rather than through a
# render. Both are hash-pinned by scripts/check_customization.py, so what is
# read here is what the release ships.
REVIEWED_CONFIG = PACKAGE / "config/openclaw.json"
REVIEWED_EXEC_APPROVALS = PACKAGE / "config/exec-approvals.json"
PROFILES = ("none", "slack", "msteams", "discord", "telegram")
# The gate must run exactly these checks: image provenance, the workshop guard,
# the exec-approvals store round trip, one schema validation per profile, the
# reviewed artifact's own schema validation, and the hostile unknown-field
# rejection. Single-sourced so the offline contract test asserts the count
# behaviorally rather than grepping this file for a literal.
EXPECTED_CHECK_NAMES = (
    "image-package-provenance",
    "image-workshop-guard",
    "image-exec-approvals-row",
    # Emission order, not grouped by kind: the profile loop appends the schema
    # check and the plugin-load check together for each profile, and the gate
    # compares this tuple to the produced names positionally.
    *(
        name
        for profile in PROFILES
        for name in (f"openclaw-schema:{profile}", f"plugin-load:{profile}")
    ),
    "openclaw-schema:reviewed-artifact",
    "openclaw-schema:unknown-field-rejected",
)

# What the gateway actually loads, per profile. The reviewed config allowlists
# one plugin; the renderer builds the effective list, and the harness then adds
# memory-core through its own default memory slot without consulting the
# allowlist at all. Only an executed probe can see that, which is why this is a
# G6 check and not an offline assertion over the rendered JSON.
BASE_LOADED_PLUGINS = frozenset(
    {"memory-core", "openai", "vc-trusted-context", "web-readability"}
)
RUNTIME_VALUES = {
    "VC_MODEL_PROVIDER": "openai",
    "VC_PRIMARY_MODEL": "openai/gpt-5.6-sol",
    "VC_FAST_MODEL": "openai/gpt-5.6-sol",
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
    "slack": "2026.8.1",
    "msteams": "2026.8.1",
    "discord": "2026.8.1",
    "telegram": "2026.8.1",
    "firecrawl": "2026.8.1",
    "tavily": "2026.8.1",
    "duckduckgo": "2026.8.1",
    "ollama": "2026.8.1",
    "trusted_context": "3.0.1",
}
# Scope of this exact-pin set: it fixes the revisions of the package *names*
# written on the `apt-get install` line of Dockerfile.openclaw — the same list
# tests/g6/test_image_gate_contract.py parses out of that line and compares to
# this dict for equality. Packages apt pulls in transitively are not pinned by
# name, so a fresh build can install a different revision of one of them with
# the pins here still satisfied. What freezes that transitive closure is the
# snapshot.debian.org timestamp recipe in the RECOVERY comment of
# Dockerfile.openclaw (docs/RUNBOOK.md, "Rebuilding after a Debian point
# release"), not these pins.
EXPECTED_DEBIAN_PACKAGES = {
    # Moved with the 2026.8.1 base, which already ships 20250419~deb12u1 from
    # bookworm-security. The old pin is still in the pool at priority 500, so
    # apt does not fail to find it — it refuses to *downgrade* to it
    # (`E: Packages were downgraded and -y was used without --allow-downgrades`,
    # measured exit 100). Re-measured against the 8.1 base: of the ten pinned
    # names this is the only one that moved.
    "ca-certificates": "20250419~deb12u1",
    "curl": "7.88.1-10+deb12u15",
    "file": "1:5.44-3",
    "jq": "1.6-2.1+deb12u2",
    "libmagic1": "1:5.44-3",
    # Keep this pair in lockstep with Dockerfile.openclaw: poppler-utils depends
    # on exactly this libpoppler126 version, so pinning only the tool lets a
    # security bump to the library break a fresh build.
    "libpoppler126": "22.12.0-2+deb12u3",
    "poppler-utils": "22.12.0-2+deb12u3",
    # These two are the python3-defaults metapackages, so their `3.11.2` is that
    # source's revision and not the interpreter's: measured in
    # vc-lead-research:3.0.1, `/usr/bin/python3` is a symlink owned by
    # python3-minimal, while the interpreter binary `/usr/bin/python3.11` belongs
    # to python3.11-minimal=3.11.2-6+deb12u8, which the digest-pinned base image
    # already carries. The interpreter revision is therefore inherited, not
    # pinned here, and it can move on a fresh build: python3-venv pulls
    # python3.11-venv (unpinned by name), which declares
    # `Depends: python3.11 (= <revision>)`, while these pins constrain the
    # interpreter only as `python3.11 (>= 3.11.2-1~)`.
    # Adding `python3.11*` names is deliberately not the fix. It would have to
    # change three welded sites in lockstep — Dockerfile.openclaw, this dict, and
    # the hardcoded tuple in tests/infrastructure/test_infrastructure_contract.py
    # — and it would take on the fresh-build fragility the poppler pair above
    # demonstrated in 85feb53, where the pool moved to a newer revision under an
    # exact pin and no cached build noticed.
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
        "-e", "VC_PRIMARY_MODEL=openai/gpt-5.6-sol", "-e",
        "VC_FAST_MODEL=openai/gpt-5.6-sol",
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
        "slack:read('/app/dist/extensions/slack/package.json'),"
        "msteams:read('/app/dist/extensions/msteams/package.json'),"
        "discord:read('/app/dist/extensions/discord/package.json'),"
        "telegram:read('/app/extensions/telegram/package.json'),"
        "firecrawl:read('/opt/openclaw-runtime/node_modules/@openclaw/firecrawl-plugin/package.json'),"
        "tavily:read('/opt/openclaw-runtime/node_modules/@openclaw/tavily-plugin/package.json'),"
        "duckduckgo:read('/opt/openclaw-runtime/node_modules/@openclaw/duckduckgo-plugin/package.json'),"
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


def exec_approvals_row_probe(image: str) -> dict[str, Any]:
    """Seed the reviewed exec-approvals policy, then read it back out of the store.

    2026.8.1 moved exec approvals out of `$OPENCLAW_STATE_DIR/exec-approvals.json`
    and into `state/openclaw.sqlite#exec_approvals_config`, so any check that
    reads the file proves nothing about the policy the runtime enforces. That is
    why this asserts the store path as well as the contents: measured, the
    2026.8.1 image reports
    `<state>/state/openclaw.sqlite#exec_approvals_config` while the 2026.7.1
    image reports `<state>/exec-approvals.json` for the identical command. An
    image that still answers with a file fails here instead of certifying a
    policy the gateway ignores.

    Two things the round trip does not preserve, both measured rather than
    assumed, so do not add them back to the comparison: the stored policy is
    rooted at `file`, and each allowlist entry loses its `source`. `id` and
    `pattern` survive, and they are what the boundary is built on.

    The expectation is derived from the seed rather than restated here — a
    second copy of the policy inside the gate would be one more thing to drift.
    """
    result = run(
        [
            "docker", "run", "--rm", "--network", "none", "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "128",
            "--memory", "512m", "-e", "HOME=/tmp/home",
            # 2026.8.1 needs a writable cache root before it will open a SQLite
            # store at all; without it the CLI dies with "Unable to create
            # fallback OpenClaw temp dir". Point it inside the one tmpfs this
            # container already has so --read-only still holds.
            "-e", "XDG_CACHE_HOME=/tmp/cache",
            "-e", "OPENCLAW_STATE_DIR=/tmp/state",
            "--mount",
            f"type=bind,src={REVIEWED_EXEC_APPROVALS},target=/seed/exec-approvals.json,readonly",
            "--entrypoint", "sh", image, "-c",
            "node dist/index.js approvals set --file /seed/exec-approvals.json >/dev/null"
            " && node dist/index.js approvals get --json",
        ],
        timeout=120,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "exec approvals store probe failed")
    stored = json.loads(result.stdout)
    path = str(stored.get("path", ""))
    if not path.endswith("state/openclaw.sqlite#exec_approvals_config"):
        raise RuntimeError(
            "exec approvals are not held in the state database; this image would "
            f"read a policy the gateway ignores: path={path!r}"
        )
    if stored.get("exists") is not True:
        raise RuntimeError("the exec approvals row is absent after seeding it")
    reviewed = json.loads(REVIEWED_EXEC_APPROVALS.read_text(encoding="utf-8"))
    graded = ("security", "ask", "askFallback", "autoAllowSkills")

    def projection(policy: dict[str, Any]) -> dict[str, Any]:
        agents = policy.get("agents") or {}
        steward = agents.get("data-steward") or {}
        return {
            "version": policy.get("version"),
            "defaults": policy.get("defaults"),
            "agents": sorted(agents),
            "data-steward": {key: steward.get(key) for key in graded},
            "allowlist": sorted(
                (str(entry.get("id")), str(entry.get("pattern")))
                for entry in steward.get("allowlist") or []
            ),
        }

    expected = projection(reviewed)
    actual = projection(stored.get("file") or {})
    if actual != expected:
        raise RuntimeError(
            f"the stored exec approvals policy differs: expected={expected}, actual={actual}"
        )
    return {"path": path, "hash": stored.get("hash"), "policy": actual}


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


def plugin_load_probe(image: str, config: Path, values: dict[str, str], profile: str) -> set[str]:
    """Return the plugin ids the harness loads for one rendered profile.

    Runs in the same sealed container the schema check uses -- no network, no
    writable root -- so it observes plugin selection and nothing else. A channel
    profile must load its own channel plugin and no other channel's.
    """
    command = docker_config_command(image, config, values)
    # docker_config_command ends with the `config validate` argv; swap in the
    # plugin listing so the sandbox flags stay single-sourced. Raise rather than
    # assert: this runs as a release gate, where -O would strip an assert and
    # leave the probe silently validating the config instead of listing plugins.
    if command[-2:] != ["config", "validate"]:
        raise RuntimeError(f"unexpected sandbox argv tail: {command[-4:]}")
    command = [*command[:-2], "plugins", "list", "--json"]
    result = run(command, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"{profile}: plugins list exited {result.returncode}: {result.stderr[-400:]}")
    payload = json.loads(result.stdout)
    return {entry["id"] for entry in payload["plugins"] if entry.get("status") == "loaded"}


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
        default="vc-lead-research:3.0.1",
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
        exec_approvals_row_probe(args.image)
        checks.append({"name": "image-exec-approvals-row", "result": "PASS"})
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
                # A channel profile must load exactly its own channel plugin on
                # top of the base set: no other channel's, and nothing the
                # renderer did not allowlist except memory-core, which the
                # harness selects through its default memory slot.
                expected = set(BASE_LOADED_PLUGINS)
                if profile != "none":
                    expected.add(profile)
                try:
                    loaded = plugin_load_probe(args.image, config, values, profile)
                    detail = None if loaded == expected else (
                        f"expected {sorted(expected)}, loaded {sorted(loaded)}"
                    )
                except (RuntimeError, ValueError, KeyError) as error:
                    loaded, detail = set(), str(error)
                checks.append(
                    {
                        "name": f"plugin-load:{profile}",
                        "result": "PASS" if detail is None else "FAIL",
                        "detail": detail,
                    }
                )

            # The reviewed artifact, validated as committed rather than through
            # a render. Every profile check above validates the renderer's
            # output, so a key that only the base file carries — the whole of
            # `diagnostics`, `cron`, `commands`, `skills.workshop` — is judged
            # only after apply_runtime_selection has had its say. Upstream's
            # schema is strict everywhere in 2026.8.1 and the gateway exits 78
            # on an unrecognized key, so validate what the release ships.
            reviewed = run(
                docker_config_command(args.image, REVIEWED_CONFIG, env_values("none")),
                timeout=90,
            )
            passed = reviewed.returncode == 0 and "Config valid:" in reviewed.stdout
            checks.append(
                {
                    "name": "openclaw-schema:reviewed-artifact",
                    "result": "PASS" if passed else "FAIL",
                    "detail": None if passed else (reviewed.stderr + reviewed.stdout)[-10_000:],
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
            "config/exec-approvals.json",
            "config/openclaw.json",
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
