#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
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
import os
import secrets
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent
COMPOSE_PROJECT = "vc-lead-research-v3"
PROJECT_VOLUMES = (
    f"{COMPOSE_PROJECT}_postgres-data",
    f"{COMPOSE_PROJECT}_openclaw-state",
    f"{COMPOSE_PROJECT}_runtime-config",
    f"{COMPOSE_PROJECT}_vc-quarantine",
)
LIFECYCLE_LOCK = Path("/tmp/vc-lead-research-v3-lifecycle.lock")
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
    "workspaces/outbound-scout/USER.md",
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


def project_containers() -> list[str]:
    """Container IDs labelled with this gate's compose project.

    check defaults to True on purpose: a failing `docker ps` writes nothing to
    stdout, and a caller that read that as "no containers" would certify a
    teardown it never measured. precheck() and teardown() share this
    enumeration so the entry and exit conditions cannot describe different
    worlds.
    """
    return run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}"],
        timeout=60,
    ).stdout.split()


def project_volumes() -> list[str]:
    """This gate's volumes that exist. Raises on a failing enumeration."""
    existing = set(run(["docker", "volume", "ls", "-q"], timeout=60).stdout.split())
    return sorted(existing.intersection(PROJECT_VOLUMES))


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
    if project_containers():
        raise GateError(f"compose project {COMPOSE_PROJECT} already has containers; refusing")
    collisions = project_volumes()
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
    # Create at 0600 rather than write-then-chmod: this file carries six live
    # credentials, and a caller umask of 022 would leave it world-readable for
    # the window between the two calls. O_EXCL matches the gate's own
    # precondition that no .env exists (preflight refuses otherwise).
    descriptor = os.open(PACKAGE / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")

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


def vcrun(workflow: str, arguments: dict[str, str], *, expect_ok: bool = True) -> dict:
    process = run(
        compose(
            "exec", "-T", "openclaw-gateway", "/workspaces/vc-chief/vc/bin/agent/vcrun",
            "run", workflow, "--args-json", json.dumps(arguments),
        ),
        timeout=420,
        check=False,
    )
    # vcrun routes its usage_error/vcrun_error/runtime_error/interrupted
    # envelopes exclusively to stderr; scan it as well so those failures
    # surface as themselves instead of as "no JSON object found in output: ''".
    try:
        payload = last_json_object(process.stdout)
    except GateError:
        try:
            payload = last_json_object(process.stderr)
        except GateError:
            raise GateError(
                f"vcrun {workflow} produced no JSON envelope: rc={process.returncode} "
                f"stderr tail={process.stderr[-2000:]!r}"
            ) from None
    succeeded = process.returncode == 0 and payload.get("ok") is True
    if expect_ok and not succeeded:
        raise GateError(
            f"vcrun {workflow} failed: rc={process.returncode} payload={json.dumps(payload)[:4000]} "
            f"stderr tail={process.stderr[-1000:]!r}"
        )
    if not expect_ok and succeeded:
        raise GateError(
            f"vcrun {workflow} unexpectedly succeeded: payload={json.dumps(payload)[:4000]}"
        )
    return payload


def check(name: str, action) -> dict:
    try:
        detail = action()
        return {"name": name, "result": "PASS", "detail": detail if isinstance(detail, str) else None}
    except Exception as exc:  # the gate reports every failure rather than raising
        return {"name": name, "result": "FAIL", "detail": str(exc)}


def negative_auth_proof() -> str:
    probe = (
        "set -eu; passfile=$(mktemp /dev/shm/g8-invalid-pgpass.XXXXXX); chmod 0600 \"$passfile\"; "
        "printf '127.0.0.1:5432:openclaw:openclaw_owner:%s\\n' 'G8InvalidCredentialProbe_0000000000000000' > \"$passfile\"; "
        "if err=$(PGPASSFILE=\"$passfile\" psql -X -w --host=127.0.0.1 --username openclaw_owner "
        "--dbname openclaw --command 'SELECT 1' 2>&1); then rm -f \"$passfile\"; "
        "echo INVALID_PASSWORD_ACCEPTED; exit 1; fi; rm -f \"$passfile\"; "
        "printf 'invalid-password-rejected %s\\n' \"$err\""
    )
    process = run(compose("exec", "-T", "postgres", "sh", "-c", probe), timeout=60)
    if "invalid-password-rejected" not in process.stdout:
        raise GateError(f"negative proof did not observe a rejection: {process.stdout!r}")
    # A refused password and an unreachable server both make psql exit
    # non-zero; only the first proves anything about authentication.
    if "authentication failed" not in process.stdout:
        raise GateError(
            "negative proof did not observe an authentication failure — the server may "
            f"simply have been unreachable: {process.stdout!r}"
        )
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
    # Bound once, not inline: the replay assertions below re-send exactly these
    # arguments, and a freshly generated name would be a *changed* payload.
    scout_company = f"G8 Scouted {uuid.uuid4().hex[:10]}"
    vcrun("outbound-scout", {
        "idempotency_key": f"{prefix}-scout",
        "company_name": scout_company,
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

    # Replay semantics through the real runner, against the run the scout above
    # committed. The step-interpreter suites cover the helper contract; only this
    # gate proves what an operator actually sees from `vcrun run`.
    scout_arguments = {
        "idempotency_key": f"{prefix}-scout",
        "company_name": scout_company,
        "company_domain": f"{prefix}-scout.invalid",
        "lead_title": "G8 scouted lead",
    }
    replay = vcrun("outbound-scout", scout_arguments)
    if replay.get("idempotent_replay", {}).get("outcome") != "completed":
        raise GateError(
            "an unchanged retry of a succeeded workflow must report an idempotent "
            f"replay, not re-execute: payload={json.dumps(replay)[:2000]}"
        )
    leads_after_replay = owner_sql(f"SELECT count(*) FROM leads WHERE idempotency_key='{prefix}-scout'")
    if leads_after_replay != "1":
        raise GateError(f"idempotent replay duplicated business rows: leads={leads_after_replay}")

    # Same key, different arguments: refused, distinctly from the replay above,
    # and without mutating anything.
    tampered = vcrun(
        "outbound-scout",
        {**scout_arguments, "lead_title": "G8 tampered replay"},
        expect_ok=False,
    )
    if tampered.get("error", {}).get("code") != "idempotency_payload_mismatch":
        raise GateError(
            "a reused key with changed arguments must fail closed as "
            f"idempotency_payload_mismatch: payload={json.dumps(tampered)[:2000]}"
        )
    runs_after_tamper = owner_sql(
        f"SELECT count(*) FROM workflow_runs WHERE idempotency_key='{prefix}-scout'"
    )
    if runs_after_tamper != "1":
        raise GateError(f"a refused replay created workflow rows: runs={runs_after_tamper}")

    return (
        "runtime-preflight, preference-observe, preference-forget, document-ingest, "
        "outbound-scout, evidence-record succeeded via real vcrun/Lobster; "
        "unchanged retry returned an idempotent replay and a changed-argument "
        "retry failed closed without mutation; "
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


def release_our_lifecycle_lock() -> tuple[str, bool]:
    """Clear the lifecycle lock iff this gate's own bootstrap.sh left it.

    precheck() proved the lock absent at start, so anything here appeared
    during the run. Only a lock this gate's own bootstrap.sh could have left
    is ours to clear: a backup/restore/update/rotate token belongs to a real
    operator lifecycle operation and removing it would defeat the mutual
    exclusion the lock exists to provide.

    Returns (note for the check detail, stuck) where stuck is True only for a
    lock that is ours and survived removal — which would make precheck() refuse
    the next run.
    """
    if not LIFECYCLE_LOCK.exists():
        return "absent", False
    try:
        owner = (LIFECYCLE_LOCK / "owner").read_text(encoding="utf-8").strip()
    except OSError:
        owner = ""
    if not owner.startswith("bootstrap:"):
        held_by = owner or "an unidentified owner"
        print(f"leaving lifecycle lock {LIFECYCLE_LOCK} held by {held_by}", file=sys.stderr)
        return f"left held by {held_by}", False
    shutil.rmtree(LIFECYCLE_LOCK, ignore_errors=True)
    # ignore_errors discards the failure, so re-check instead of assuming.
    if LIFECYCLE_LOCK.exists():
        return "ours and NOT removed", True
    return "removed", False


def teardown() -> str:
    """Remove the deployment, re-verify that it is gone, and report what was measured.

    Through the seventeenth pass every removal here ran with check=False and
    nothing re-listed afterwards, so teardown() returned normally whatever
    happened: `docker rm` / `docker volume rm` exiting 1 — or `docker ps` /
    `docker volume ls` failing, whose empty stdout read as "nothing to
    remove" — still produced result=PASS with the fixed detail string "removed
    containers, volumes, runtime files". The gate would have certified a clean
    teardown while leaving a populated postgres-data volume (throwaway
    credentials, leads, approval rows) on the host, and both evidence
    documents cite this check for exactly that claim. The detail is now a
    measurement taken after the removals, not an assertion written before them.
    """
    down = "skipped (no .env)"
    if (PACKAGE / ".env").exists():
        # Deliberately not fatal on its own: the leftover sweep below is the
        # compensating path for a partial `compose down`, and the re-listing at
        # the end is what decides PASS/FAIL. The return code is reported rather
        # than discarded so a non-zero one is visible in the gate's evidence.
        completed = subprocess.run(
            compose("--profile", "tools", "down", "--volumes", "--remove-orphans"),
            cwd=PACKAGE, text=True, capture_output=True, timeout=600,
        )
        down = f"rc={completed.returncode}"
    leftovers = project_containers()
    if leftovers:
        # check=False on the removals only: a container can legitimately vanish
        # between the listing and the rm. Survival is the failure, not the exit
        # status, and the re-listing below is what detects survival.
        run(["docker", "rm", "-f", *leftovers], timeout=120, check=False)
    stale = project_volumes()
    if stale:
        run(["docker", "volume", "rm", "-f", *stale], timeout=120, check=False)
    for relative in GENERATED_FILES:
        (PACKAGE / relative).unlink(missing_ok=True)
    lock_note, lock_stuck = release_our_lifecycle_lock()

    surviving = []
    surviving_containers = project_containers()
    if surviving_containers:
        surviving.append(f"containers={surviving_containers}")
    surviving_volumes = project_volumes()
    if surviving_volumes:
        surviving.append(f"volumes={surviving_volumes}")
    surviving_files = [relative for relative in GENERATED_FILES if (PACKAGE / relative).exists()]
    if surviving_files:
        surviving.append(f"runtime files={surviving_files}")
    if lock_stuck:
        surviving.append(f"lifecycle lock {LIFECYCLE_LOCK}")
    if surviving:
        raise GateError(
            "teardown left state behind: " + "; ".join(surviving)
            + f" (compose down {down}). Remove it by hand before re-running the "
            "gate; precheck() refuses to start over an existing deployment."
        )
    return (
        f"compose down {down}; swept {len(leftovers)} leftover container(s) and "
        f"{len(stale)} stale volume(s); lifecycle lock {lock_note}; re-listed after "
        "removal: no project containers, no project volumes, no runtime files"
    )


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
            # teardown() returns its own detail: the string must describe what
            # the post-removal re-listing measured, not what was attempted.
            checks.append(check("teardown", teardown))
    passed = bool(checks) and all(item["result"] == "PASS" for item in checks)
    print(json.dumps({"gate": "G8", "result": "PASS" if passed else "FAIL", "checks": checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
