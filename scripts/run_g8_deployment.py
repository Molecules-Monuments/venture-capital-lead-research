#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Run the real deployment path end-to-end on the pinned images (G8 gate).

This is the execution-based deployment coverage the offline suites cannot
provide: it generates throwaway credentials, runs ./scripts/bootstrap.sh to
completion, independently re-proves that an invalid password is rejected over
TCP, executes fixed workflows (including the historically lead/company-free
ones) through the real vcrun + pinned Lobster inside the deployed gateway
container, and tears the deployment down again.

Opt-in (requires Docker and network for the pinned pulls); wired as
`verify_offline.py --with-deployment`. The gate refuses to run over an
existing deployment: `.env` and `config/customization-profile.json` must be
absent and the pinned compose project must own no containers or volumes, so a
real operator installation can never be disturbed or credential-rotated by a
test run.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import secrets
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
COMPOSE_PROJECT = "openclaw-lead-research-v3"
PROJECT_VOLUMES = (
    f"{COMPOSE_PROJECT}_postgres-data",
    f"{COMPOSE_PROJECT}_openclaw-state",
    f"{COMPOSE_PROJECT}_runtime-config",
    f"{COMPOSE_PROJECT}_vc-quarantine",
)
LIFECYCLE_LOCK = Path("/tmp/openclaw-lead-research-v3-lifecycle.lock")
GENERATED_FILES = (
    ".env",
    "config/customization-profile.json",
    "config/runtime/openclaw.json",
    "config/runtime/secrets/postgres_owner_password",
    "config/runtime/secrets/openclaw_db_password",
    "config/runtime/secrets/vcops_approval_pepper",
    "config/runtime/secrets/vc_trusted_context_key",
    "deployment-lock.json",
)
SECRET_KEYS = (
    "OPENCLAW_GATEWAY_TOKEN",
    "POSTGRES_PASSWORD",
    "OPENCLAW_DB_PASSWORD",
    "VCOPS_APPROVAL_PEPPER",
    "VC_TRUSTED_CONTEXT_KEY",
    "BACKUP_HMAC_KEY",
)
REVIEWED_ARTIFACTS = (
    "config/openclaw.json",
    "tests/g3/routing_cases.jsonl",
    "tests/g3/scoring_boundary_cases.jsonl",
    "workspaces/vc-chief/USER.md",
    "workspaces/vc-chief/vc/approval-policy.md",
    "workspaces/vc-chief/vc/channel_policy.md",
    "workspaces/vc-chief/vc/data_retention.md",
    "workspaces/vc-chief/vc/document_intake.md",
    "workspaces/vc-chief/vc/evals/memo-eval.jsonl",
    "workspaces/vc-chief/vc/evals/routing-eval.jsonl",
    "workspaces/vc-chief/vc/evals/scoring-eval.jsonl",
    "workspaces/vc-chief/vc/exclusion_criteria.md",
    "workspaces/vc-chief/vc/prequalification.md",
    "workspaces/vc-chief/vc/primary_sources.md",
    "workspaces/vc-chief/vc/research_depth.md",
    "workspaces/vc-chief/vc/scoring-rubric.v3.json",
    "workspaces/vc-chief/vc/thesis.md",
    "workspaces/vc-chief/vc/trust_boundaries.md",
    "workspaces/vc-chief/vc/third_party_connectors.md",
)
MEDIA_DOCUMENT = "/home/node/.openclaw/media/inbound/g8-gate-document.csv"


class GateError(RuntimeError):
    pass


def run(command: list[str], *, timeout: int, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(command, cwd=PACKAGE, text=True, capture_output=True, timeout=timeout)
    if check and process.returncode:
        raise GateError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"stdout tail: {process.stdout[-4000:]}\nstderr tail: {process.stderr[-4000:]}"
        )
    return process


def compose(*arguments: str) -> list[str]:
    return [
        "docker", "compose", "-f", str(PACKAGE / "docker-compose.yml"),
        "-p", COMPOSE_PROJECT, "--env-file", str(PACKAGE / ".env"), *arguments,
    ]


def last_json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    found: dict | None = None
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            candidate, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(candidate, dict):
            found = candidate
        index = end
    if found is None:
        raise GateError(f"no JSON object found in output: {text[-2000:]!r}")
    return found


def precheck() -> None:
    for tool in ("docker",):
        if not shutil.which(tool):
            raise GateError(f"{tool} is required for the deployment gate")
    for relative in (".env", "config/customization-profile.json"):
        if (PACKAGE / relative).exists():
            raise GateError(
                f"{relative} already exists; the deployment gate only runs on a clean package "
                "so it can never disturb or credential-rotate a real deployment"
            )
    if LIFECYCLE_LOCK.exists():
        raise GateError(f"lifecycle lock {LIFECYCLE_LOCK} exists; another lifecycle operation ran or crashed")
    containers = run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}"],
        timeout=60,
    ).stdout.strip()
    if containers:
        raise GateError(f"compose project {COMPOSE_PROJECT} already has containers; refusing")
    existing = set(run(["docker", "volume", "ls", "-q"], timeout=60).stdout.split())
    collisions = sorted(existing.intersection(PROJECT_VOLUMES))
    if collisions:
        raise GateError(f"project volumes already exist: {collisions}; refusing")


def generate_runtime_files() -> dict[str, str]:
    values = {key: secrets.token_hex(32) for key in SECRET_KEYS}
    lines = []
    for line in (PACKAGE / ".env.example").read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            lines.append(f"{key}={values[key]}")
        elif key == "OPENAI_API_KEY":
            lines.append(f"OPENAI_API_KEY=sk-g8-throwaway-{secrets.token_hex(8)}")
        else:
            lines.append(line)
    (PACKAGE / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (PACKAGE / ".env").chmod(0o600)

    env = dict(
        item.split("=", 1) for item in lines if "=" in item and not item.lstrip().startswith("#")
    )
    profile = {
        "profile_version": "3.0",
        "status": "reviewed",
        "organization": {
            "name": "G8 Deployment Gate Fund",
            "timezone": env["TZ"],
            "deployment_owner": "g8-deployment-owner",
        },
        "investment_policy": {
            "fund_strategy": "seed",
            "stages": ["seed"],
            "sectors": ["ai-infrastructure"],
            "geographies": ["EU"],
            "check_size_currency": "EUR",
            "check_size_min": 100000,
            "check_size_max": 1000000,
            "ownership_target_percent": None,
            "hard_exclusions_reviewed": True,
            "rubric_reviewed": True,
            "rubric_id": "scoring-rubric.v3",
            "rubric_backtest_record": "g8-throwaway-record",
        },
        "operating_policy": {
            "research_profiles_reviewed": True,
            "source_allowlist_reviewed": True,
            "cost_budget_reviewed": True,
            "memo_template_reviewed": True,
        },
        "models": {
            "provider": env["VC_MODEL_PROVIDER"],
            "primary": env["VC_PRIMARY_MODEL"],
            "fast": env["VC_FAST_MODEL"],
            "benchmark_record": "g8-throwaway-record",
            "provider_selection_reviewed": True,
            "untrusted_input_policy_reviewed": True,
        },
        "search": {
            "provider": env["VC_WEB_SEARCH_PROVIDER"],
            "fetch_provider": env["VC_WEB_FETCH_PROVIDER"],
            "provider_selection_reviewed": True,
            "source_quality_reviewed": True,
            "evaluation_record": "g8-throwaway-record",
        },
        "approvals": {
            "stable_approver_ids": ["g8-approver"],
            "allowed_channel_ids": [],
            "expiry_minutes": 30,
            "separation_of_duties_reviewed": True,
        },
        "privacy_retention": {
            "lawful_bases_reviewed": True,
            "confidentiality_classes_reviewed": True,
            "retention_schedule_reviewed": True,
            "deletion_and_legal_hold_tested": True,
            "remote_processor_reviewed": True,
        },
        "channels": {
            "selected": env["PRIMARY_CHANNEL"],
            "stable_identity_allowlist_reviewed": True,
            "attachment_intake_reviewed": True,
            "preference_memory_reviewed": True,
        },
        "agent_profile": {
            "schema_and_eval_updates_completed": True,
        },
        "review": {
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approved_by": "g8-reviewer",
            "reviewed_artifacts": {
                relative: hashlib.sha256((PACKAGE / relative).read_bytes()).hexdigest()
                for relative in REVIEWED_ARTIFACTS
            },
        },
    }
    (PACKAGE / "config/customization-profile.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return values


def trusted_context(key: str, *, scopes: list[str], media_paths: list[str]) -> str:
    now = int(time.time())
    payload = {
        "v": 1,
        "nonce": uuid.uuid4().hex + uuid.uuid4().hex[:16],
        "iat": now,
        "exp": now + 900,
        "provider": "slack",
        "account_id": "g8-workspace",
        "conversation_id": "g8-dm",
        "sender_id": "g8-sender",
        "session_hash": hashlib.sha256(b"session:g8").hexdigest(),
        "run_id": "run-" + uuid.uuid4().hex,
        "event_id": "event-" + uuid.uuid4().hex,
        "is_group": False,
        "media_paths": media_paths,
        "scopes": scopes,
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = base64.urlsafe_b64encode(
        hmac.new(key.encode("ascii"), encoded.encode("ascii"), hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    return f"{encoded}.{signature}"


def vcrun(workflow: str, arguments: dict[str, str]) -> dict:
    process = run(
        compose(
            "exec", "-T", "openclaw-gateway", "/workspaces/vc-chief/vc/bin/agent/vcrun",
            "run", workflow, "--args-json", json.dumps(arguments),
        ),
        timeout=420,
        check=False,
    )
    payload = last_json_object(process.stdout)
    if process.returncode != 0 or payload.get("ok") is not True:
        raise GateError(
            f"vcrun {workflow} failed: rc={process.returncode} payload={json.dumps(payload)[:4000]}"
        )
    return payload


def check(name: str, action) -> dict:
    try:
        detail = action()
        return {"name": name, "result": "PASS", "detail": detail if isinstance(detail, str) else None}
    except Exception as exc:  # noqa: BLE001 - gate reports every failure
        return {"name": name, "result": "FAIL", "detail": str(exc)}


def negative_auth_proof() -> str:
    probe = (
        "set -eu; passfile=$(mktemp /dev/shm/g8-invalid-pgpass.XXXXXX); chmod 0600 \"$passfile\"; "
        "printf '127.0.0.1:5432:openclaw:openclaw_owner:%s\\n' 'G8InvalidCredentialProbe_0000000000000000' > \"$passfile\"; "
        "if PGPASSFILE=\"$passfile\" psql -X -w --host=127.0.0.1 --username openclaw_owner "
        "--dbname openclaw --command 'SELECT 1' >/dev/null 2>&1; then rm -f \"$passfile\"; "
        "echo INVALID_PASSWORD_ACCEPTED; exit 1; fi; rm -f \"$passfile\"; echo invalid-password-rejected"
    )
    process = run(compose("exec", "-T", "postgres", "sh", "-c", probe), timeout=60)
    if "invalid-password-rejected" not in process.stdout:
        raise GateError(f"negative proof did not observe a rejection: {process.stdout!r}")
    trust_lines = run(
        compose(
            "exec", "-T", "postgres", "sh", "-c",
            'grep -E "^[[:space:]]*host[a-z]*[[:space:]].*[[:space:]]trust[[:space:]]*$" '
            '"${PGDATA:-/var/lib/postgresql/data/pgdata}/pg_hba.conf" || true',
        ),
        timeout=60,
    ).stdout.strip()
    if trust_lines:
        raise GateError(f"pg_hba.conf still contains host trust rules: {trust_lines!r}")
    return "invalid password rejected over TCP; no host trust rules remain"


def workflow_proofs(secrets_map: dict[str, str]) -> str:
    key = secrets_map["VC_TRUSTED_CONTEXT_KEY"]
    prefix = "g8-" + uuid.uuid4().hex[:10]
    vcrun("runtime-preflight", {"idempotency_key": f"{prefix}-preflight"})
    vcrun("preference-observe", {
        "idempotency_key": f"{prefix}-observe",
        "trusted_context": trusted_context(key, scopes=["preference.write"], media_paths=[]),
        "preference_key": "memo_length",
        "preference_value": "detailed",
        "observation_kind": "explicit",
    })
    vcrun("preference-forget", {
        "idempotency_key": f"{prefix}-forget",
        "trusted_context": trusted_context(key, scopes=["preference.forget"], media_paths=[]),
        "preference_key": "memo_length",
    })
    run(
        compose(
            "exec", "-T", "openclaw-gateway", "sh", "-c",
            f"umask 077; printf 'metric,value\\ncustomers,7\\n' > {MEDIA_DOCUMENT}",
        ),
        timeout=60,
    )
    path_hash = hashlib.sha256(MEDIA_DOCUMENT.encode("utf-8")).hexdigest()
    vcrun("document-ingest", {
        "idempotency_key": f"{prefix}-ingest",
        "document_path": MEDIA_DOCUMENT,
        "trusted_context": trusted_context(
            key,
            scopes=[f"document.read:{path_hash}", f"document.ingest:{path_hash}"],
            media_paths=[MEDIA_DOCUMENT],
        ),
    })
    vcrun("outbound-scout", {
        "idempotency_key": f"{prefix}-scout",
        "company_name": f"G8 Scouted {uuid.uuid4().hex[:10]}",
        "company_domain": f"{prefix}-scout.invalid",
        "lead_title": "G8 scouted lead",
    })
    lead_id = owner_sql(f"SELECT id FROM leads WHERE idempotency_key='{prefix}-scout'")
    if not lead_id.isdigit():
        raise GateError(f"scouted lead was not persisted: {lead_id!r}")
    vcrun("evidence-record", {
        "idempotency_key": f"{prefix}-evidence",
        "lead_id": lead_id,
        "evidence_json": json.dumps({
            "claim": "G8 gate: ARR reached 1.2m EUR in H1 2026",
            "fact_type": "traction_adoption",
            "confidence": "high",
            "produced_by": "traction-analyst",
            "source": {"url": f"https://news-{prefix}.invalid/arr"},
        }),
    })
    counts = owner_sql(
        "SELECT count(*) FROM facts WHERE fact_status='submitted_claim'"
        " UNION ALL SELECT count(*) FROM sources UNION ALL SELECT count(*) FROM fact_sources"
    ).split()
    if len(counts) != 3 or any(value == "0" for value in counts):
        raise GateError(f"autonomous run left an empty knowledge base: facts/sources/links={counts}")
    return (
        "runtime-preflight, preference-observe, preference-forget, document-ingest, "
        "outbound-scout, evidence-record succeeded via real vcrun/Lobster; "
        f"knowledge base non-empty (facts/sources/links={'/'.join(counts)})"
    )


def owner_sql(sql: str) -> str:
    process = run(
        compose(
            "exec", "-T", "postgres", "psql", "-X", "-q", "-A", "-t",
            "-U", "openclaw_owner", "-d", "openclaw", "-c", sql,
        ),
        timeout=60,
    )
    return process.stdout.strip()


def teardown() -> None:
    if (PACKAGE / ".env").exists():
        subprocess.run(
            compose("--profile", "tools", "down", "--volumes", "--remove-orphans"),
            cwd=PACKAGE, text=True, capture_output=True, timeout=600,
        )
    leftovers = run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}"],
        timeout=60, check=False,
    ).stdout.split()
    if leftovers:
        run(["docker", "rm", "-f", *leftovers], timeout=120, check=False)
    existing = set(run(["docker", "volume", "ls", "-q"], timeout=60, check=False).stdout.split())
    stale = sorted(existing.intersection(PROJECT_VOLUMES))
    if stale:
        run(["docker", "volume", "rm", "-f", *stale], timeout=120, check=False)
    for relative in GENERATED_FILES:
        (PACKAGE / relative).unlink(missing_ok=True)
    if LIFECYCLE_LOCK.exists():
        shutil.rmtree(LIFECYCLE_LOCK, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-up", action="store_true", help="skip teardown to allow post-run inspection")
    args = parser.parse_args()
    checks: list[dict] = []
    secrets_map: dict[str, str] = {}
    try:
        precheck()
    except GateError as exc:
        print(json.dumps({"gate": "G8", "result": "FAIL", "checks": [
            {"name": "precheck", "result": "FAIL", "detail": str(exc)},
        ]}, indent=2, sort_keys=True))
        return 1
    try:
        checks.append(check("runtime-files", lambda: secrets_map.update(generate_runtime_files()) or "generated"))
        checks.append(check("bootstrap", lambda: run(
            ["./scripts/bootstrap.sh"], timeout=1800,
        ).stdout[-2000:] and "bootstrap.sh completed"))
        if all(item["result"] == "PASS" for item in checks):
            checks.append(check("negative-auth-proof", negative_auth_proof))
            checks.append(check("fixed-workflows-live", lambda: workflow_proofs(secrets_map)))
    finally:
        if not args.keep_up:
            checks.append(check("teardown", lambda: teardown() or "removed containers, volumes, runtime files"))
    passed = bool(checks) and all(item["result"] == "PASS" for item in checks)
    print(json.dumps({"gate": "G8", "result": "PASS" if passed else "FAIL", "checks": checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
