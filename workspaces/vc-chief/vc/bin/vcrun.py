#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Fail-closed launcher for the package's reviewed Lobster workflows.

This is intentionally not a general Lobster wrapper.  It exposes no inline
pipeline, file-path, environment, working-directory, or command override.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from typing import Any


VERSION = "3.0.0"
LOBSTER_VERSION = "2026.6.11"
LOBSTER_BIN = Path("/usr/local/bin/openclaw-lobster")
EXPECTED_LOBSTER_TARGET = Path(
    "/opt/openclaw-runtime/node_modules/@clawdbot/lobster/bin/lobster.js"
)
LOBSTER_PACKAGE_JSON = Path(
    "/opt/openclaw-runtime/node_modules/@clawdbot/lobster/package.json"
)
WORKFLOW_ROOT = Path("/workspaces/vc-chief/vc/workflows")
WORKDIR = Path("/workspaces/vc-chief")
MAX_ARGS_BYTES = 32 * 1024
MAX_VALUE_CHARS = 16 * 1024
MAX_OUTPUT_BYTES = 512 * 1024
MAX_RECONCILIATION_BYTES = 64 * 1024
RUN_TIMEOUT_SECONDS = 360
CONTROL_TIMEOUT_SECONDS = 60

WORKFLOWS: dict[str, dict[str, Any]] = {
    "evaluate-lead": {
        "file": "evaluate-lead.lobster",
        "database_workflow": "evaluate-lead",
        "keys": {"idempotency_key", "lead_id", "criteria_json", "decision_context_json"},
        "json_object_keys": {"criteria_json", "decision_context_json"},
    },
    "inbound-intake": {
        "file": "inbound-intake.lobster",
        "database_workflow": "inbound-intake",
        "keys": {
            "idempotency_key", "lead_title", "company_name", "company_domain", "document_path",
            "channel_provider", "channel_account_id", "channel_event_id",
        },
        "json_object_keys": set(),
    },
    "outbound-scout": {
        "file": "outbound-scout.lobster",
        "database_workflow": "outbound-scout",
        "keys": {"idempotency_key", "company_name", "company_domain", "lead_title"},
        "json_object_keys": set(),
    },
    "runtime-preflight": {
        "file": "runtime-preflight.lobster",
        "database_workflow": "system.runtime-preflight",
        "keys": {"idempotency_key"},
        "json_object_keys": set(),
    },
    "preference-observe": {
        "file": "preference-observe.lobster",
        "database_workflow": "preference-observe",
        "keys": {"idempotency_key", "trusted_context", "preference_key", "preference_value", "observation_kind"},
        "json_object_keys": set(),
    },
    "preference-forget": {
        "file": "preference-forget.lobster",
        "database_workflow": "preference-forget",
        "keys": {"idempotency_key", "trusted_context", "preference_key"},
        "json_object_keys": set(),
    },
    "document-ingest": {
        "file": "document-ingest.lobster",
        "database_workflow": "document-ingest",
        "keys": {"idempotency_key", "document_path", "trusted_context"},
        "json_object_keys": set(),
    },
    "document-lead-intake": {
        "file": "document-lead-intake.lobster",
        "database_workflow": "document-lead-intake",
        "keys": {"idempotency_key", "trusted_context", "extraction_id", "lead_title", "company_name", "company_domain"},
        "json_object_keys": set(),
    },
    "evidence-record": {
        "file": "evidence-record.lobster",
        "database_workflow": "evidence-record",
        "keys": {"idempotency_key", "lead_id", "evidence_json"},
        "json_object_keys": {"evidence_json"},
    },
    "contradiction-record": {
        "file": "contradiction-record.lobster",
        "database_workflow": "contradiction-record",
        "keys": {"idempotency_key", "lead_id", "left_fact_id", "right_fact_id", "severity"},
        "json_object_keys": set(),
    },
    "trajectory-record": {
        "file": "trajectory-record.lobster",
        "database_workflow": "trajectory-record",
        "keys": {"idempotency_key", "lead_id", "left_fact_id", "right_fact_id"},
        "json_object_keys": set(),
    },
    "memo-record": {
        "file": "memo-record.lobster",
        "database_workflow": "memo-record",
        "keys": {
            "idempotency_key", "lead_id", "evaluation_id", "compiled_truth_id",
            "memo_title", "memo_markdown", "citations_json", "evidence_hash",
        },
        "json_object_keys": set(),
    },
    "source-watch": {
        "file": "source-watch.lobster",
        "database_workflow": "system.source-watch",
        "keys": {
            "idempotency_key", "source_name", "source_uri", "source_class",
            "cadence", "thesis_relevance", "expected_signal",
        },
        "json_object_keys": set(),
    },
    "source-unwatch": {
        "file": "source-unwatch.lobster",
        "database_workflow": "system.source-unwatch",
        "keys": {"idempotency_key", "source_uri"},
        "json_object_keys": set(),
    },
    "source-scan": {
        "file": "source-scan.lobster",
        "database_workflow": "system.source-scan",
        "keys": {"idempotency_key", "limit"},
        "json_object_keys": set(),
    },
    "inbound-text-intake": {
        "file": "inbound-text-intake.lobster",
        "database_workflow": "inbound-text-intake",
        "keys": {"idempotency_key", "lead_title", "company_name", "company_domain", "origin_subtype"},
        "json_object_keys": set(),
    },
    "orchestration-record": {
        "file": "orchestration-record.lobster",
        "database_workflow": "orchestration-record",
        "keys": {"idempotency_key", "lead_id", "record_kind", "specialist", "payload_json"},
        # Native Task Flow correlation handles are first-class but optional: a
        # chief that has them makes the audit row queryable by flow/task; one that
        # omits them still records a valid entry (the handles persist as NULL).
        "optional_keys": {"flow_id", "task_id", "flow_revision"},
        "json_object_keys": {"payload_json"},
    },
    "proposal-record": {
        "file": "proposal-record.lobster",
        "database_workflow": "system.proposal-record",
        "keys": {"idempotency_key", "proposal_kind", "title", "summary", "content_json"},
        "json_object_keys": {"content_json"},
    },
}

# Added to the Lobster argument payload by the runner after validation, and
# never accepted from the caller: `validate_workflow_args` has no such key in
# any contract, so a caller that supplies one is rejected as an extra field.
# Every fixed workflow declares it in its `args:` map and forwards it to
# `workflow-start`, which stores it as the run's immutable argument binding.
INJECTED_ARG_KEYS = frozenset({"input_digest"})

IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)

# PostgreSQL's `bigint` ceiling. The canonical shapes below admit up to
# nineteen digits — 9999999999999999999 — so the shape check is not the bound;
# the explicit comparison is.
BIGINT_MAX = 9_223_372_036_854_775_807
POSITIVE_BIGINT_RE = re.compile(r"[1-9][0-9]{0,18}")
NON_NEGATIVE_BIGINT_RE = re.compile(r"0|[1-9][0-9]{0,18}")

# Argument names that carry a PostgreSQL `bigint` key. Applied by intersection
# with the contract's own key set rather than per workflow, so a workflow that
# gains one of these arguments cannot gain it unvalidated.
BIGINT_ID_ARG_KEYS = frozenset({
    "lead_id", "left_fact_id", "right_fact_id",
    "extraction_id", "evaluation_id", "compiled_truth_id",
})
# Counters that legitimately start at zero, so they are bounded but not
# "positive": workflow_runs.flow_revision defaults to 0 and migration 014's
# orchestration_audit CHECK admits >= 0.
NON_NEGATIVE_BIGINT_ARG_KEYS = frozenset({"flow_revision"})
# Identifier-shaped arguments that are opaque text rather than numeric keys:
# orchestration_audit.flow_id/task_id and the channel handles are `text`
# columns, so a numeric bound here would refuse legitimate values.
OPAQUE_TEXT_ID_ARG_KEYS = frozenset({
    "channel_account_id", "channel_event_id", "flow_id", "task_id",
})
# Contract arguments that carry no database identifier: free text, JSON object
# strings, enumerations, URIs and digests, each validated by its own rule below.
# Listed so the classification underneath is a partition over EVERY contract
# key. It is not a description of the three sets above; it is the fourth cell.
NON_IDENTIFIER_ARG_KEYS = frozenset({
    "cadence", "channel_provider", "citations_json", "company_domain",
    "company_name", "content_json", "criteria_json", "decision_context_json",
    "document_path", "evidence_hash", "evidence_json", "expected_signal",
    "idempotency_key", "lead_title", "limit", "memo_markdown", "memo_title",
    "observation_kind", "origin_subtype", "payload_json", "preference_key",
    "preference_value", "proposal_kind", "record_kind", "severity",
    "source_class", "source_name", "source_uri", "specialist", "summary",
    "thesis_relevance", "title", "trusted_context",
})
# Contract arguments no set above classifies. The world is enumerated from
# WORKFLOWS rather than restated, so adding an argument without deciding how it
# is bounded leaves it here, and a call that carries it is refused instead of
# forwarding an unchecked value to the database. It is empty while every
# argument is classified.
#
# The derivation is over EVERY contract key, not over keys matching a suffix
# tuple. It used to filter WORKFLOWS through an IDENTIFIER_SHAPED_SUFFIXES
# tuple, which made the filter define the very world it was supposed to be
# checked against: narrowing that tuple back to ("_id",) and dropping
# `flow_revision` from the bounded set emptied this frozenset and let a 23-digit
# `flow_revision` through to orchestration_audit's bigint column with all 35 g5
# tests green -- the exact regression the tuple's own comment claimed it
# prevented. No tuple to narrow now: a new argument is unclassified until it is
# named in one of the four sets.
UNCLASSIFIED_ID_ARG_KEYS = frozenset(
    key
    for contract in WORKFLOWS.values()
    for key in (set(contract["keys"]) | set(contract.get("optional_keys", ())))
    if key not in BIGINT_ID_ARG_KEYS
    and key not in NON_NEGATIVE_BIGINT_ARG_KEYS
    and key not in OPAQUE_TEXT_ID_ARG_KEYS
    and key not in NON_IDENTIFIER_ARG_KEYS
)


class VCRunError(RuntimeError):
    """Expected, structured command failure."""


class _ProbeRefusal(Exception):
    """A typed helper refusal from the pre-flight replay probe.

    Carries the helper's own error object so a tampered replay and an
    operator-cancelled run stay distinguishable from a runner malfunction.
    """

    def __init__(self, error: dict[str, Any]):
        super().__init__(str(error.get("message", "workflow replay refused")))
        self.error = error


class _UsageError(Exception):
    """Command-line usage failure surfaced through the JSON error contract."""


class _JsonArgumentParser(argparse.ArgumentParser):
    # argparse would print plain usage text to stderr; vcrun's contract is one
    # JSON object per invocation, so usage errors are raised and rendered by
    # main() instead. Subparsers inherit this class via type(self).
    def error(self, message: str) -> Any:
        raise _UsageError(message)


def _wait_after_kill(process: subprocess.Popen[bytes]) -> None:
    # SIGKILL cannot be trapped, but wait() can still time out for a process
    # stuck in uninterruptible sleep. Swallow that instead of crashing the
    # JSON contract; the exit code is then reported as unknown (None).
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    # Drop the tracked PGID now that the group is killed (and normally reaped):
    # the failure paths still run an up-to-30s reconciliation subprocess before
    # returning, and a signal arriving in that window must not re-kill a PID
    # the kernel may have recycled after the reap.
    _CURRENT_CHILD_PGID.clear()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VCRunError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _emit(payload: dict[str, Any], *, stream: Any = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


# Track the currently-supervised Lobster child (its own session, pgid == pid) so
# a SIGINT/SIGTERM to vcrun never orphans it and never escapes as a raw Python
# traceback. Cleared at reap time on every path — the normal exit and, via
# _wait_after_kill, all three kill paths — because the failure paths run an
# up-to-30s reconciliation subprocess before returning and a stale entry would
# let the signal handler SIGKILL a recycled PID's process group.
_CURRENT_CHILD_PGID: list[int] = []


def _kill_current_child() -> None:
    for pgid in _CURRENT_CHILD_PGID:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    _CURRENT_CHILD_PGID.clear()


def _handle_termination_signal(signum: int, _frame: Any) -> None:
    # Kill the supervised child first, then honor the one-JSON-object contract on
    # stderr (matching _error) and exit non-zero. os._exit avoids re-entering the
    # interrupted supervision loop or emitting a second, partial payload.
    _kill_current_child()
    try:
        _emit(
            {"ok": False, "error": {"code": "interrupted",
             "message": f"vcrun terminated by signal {signum}", "details": None}},
            stream=sys.stderr,
        )
        sys.stderr.flush()
    except Exception:  # noqa: S110  # about to os._exit; a second payload would break the one-object contract
        pass
    os._exit(130)


def _install_signal_handlers() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_termination_signal)
        except (ValueError, OSError):
            # Not on the main thread (e.g. under a test runner): best-effort only.
            pass


def _error(code: str, message: str, *, details: Any = None) -> int:
    _emit(
        {"ok": False, "error": {"code": code, "message": message, "details": details}},
        stream=sys.stderr,
    )
    return 2


def _reject_non_standard_literal(name: str) -> None:
    """`json` accepts NaN/Infinity/-Infinity by default; strict JSON does not.

    Anything re-emitted here reaches Node's JSON.parse and PostgreSQL's jsonb
    parser, both of which reject those literals — so refuse them at ingest
    rather than shipping a payload the next hop cannot read.
    """
    raise VCRunError(f"JSON contains the non-standard literal {name}")


def _validate_json_object_string(name: str, value: str) -> str:
    try:
        parsed = json.loads(
            value, object_pairs_hook=_unique_object, parse_constant=_reject_non_standard_literal
        )
    except json.JSONDecodeError as exc:
        raise VCRunError(f"{name} must contain valid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise VCRunError(f"{name} must contain a JSON object")
    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _canonical_bigint(parsed: dict[str, Any], key: str, *, allow_zero: bool = False) -> None:
    """Refuse an identifier argument PostgreSQL's `bigint` cannot hold.

    The canonical shape alone admits nineteen digits, i.e. values above
    `BIGINT_MAX`. Such a value used to pass the runner and fail inside the
    database, after `workflow-start` had already committed the run row — which
    costs the caller a fresh idempotency key to correct. Both refusals are
    raised here, before any step runs.
    """
    value = parsed[key]
    if allow_zero:
        if not NON_NEGATIVE_BIGINT_RE.fullmatch(value):
            raise VCRunError(f"{key} must be a non-negative integer string")
    elif not POSITIVE_BIGINT_RE.fullmatch(value):
        raise VCRunError(f"{key} must be a canonical positive BIGINT string")
    if int(value) > BIGINT_MAX:
        raise VCRunError(f"{key} exceeds PostgreSQL BIGINT")


def validate_workflow_args(workflow: str, raw: str) -> str:
    if workflow not in WORKFLOWS:
        raise VCRunError("unknown fixed workflow selector")
    if len(raw.encode("utf-8")) > MAX_ARGS_BYTES:
        raise VCRunError(f"args JSON exceeds {MAX_ARGS_BYTES} bytes")
    try:
        parsed = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_non_standard_literal
        )
    except json.JSONDecodeError as exc:
        raise VCRunError(f"args JSON is invalid: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise VCRunError("args JSON must be an object")

    contract = WORKFLOWS[workflow]
    expected = contract["keys"]
    optional = contract.get("optional_keys", set())
    actual = set(parsed)
    missing = expected - actual
    extra = actual - expected - optional
    if missing or extra:
        raise VCRunError(
            "args JSON keys do not match the fixed workflow contract: "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )

    for key, value in parsed.items():
        if not isinstance(value, str):
            raise VCRunError(f"{key} must be a string")
        if not value:
            raise VCRunError(f"{key} must not be empty")
        if "\x00" in value:
            raise VCRunError(f"{key} contains a NUL byte")
        if len(value) > MAX_VALUE_CHARS:
            raise VCRunError(f"{key} exceeds {MAX_VALUE_CHARS} characters")

    if not IDEMPOTENCY_RE.fullmatch(parsed["idempotency_key"]):
        raise VCRunError("idempotency_key has an invalid format")

    # Identifier arguments are bounded by name, not per workflow: which ones
    # apply is read off the contract's own key set, so every workflow that
    # names one gets the same shape *and* the same ceiling.
    unclassified = UNCLASSIFIED_ID_ARG_KEYS & actual
    if unclassified:
        raise VCRunError(
            "arguments are not classified as bigint, opaque text or "
            f"non-identifier: {sorted(unclassified)}"
        )
    for key in sorted(BIGINT_ID_ARG_KEYS & actual):
        _canonical_bigint(parsed, key)
    for key in sorted(NON_NEGATIVE_BIGINT_ARG_KEYS & actual):
        _canonical_bigint(parsed, key, allow_zero=True)

    if workflow == "orchestration-record" and parsed["record_kind"] not in {
        "delegation_eval", "return_assessment", "chief_output",
    }:
        raise VCRunError("record_kind must be delegation_eval, return_assessment, or chief_output")
    if workflow == "proposal-record" and parsed["proposal_kind"] not in {
        "schema_change", "source_policy", "skill_candidate", "other",
    }:
        raise VCRunError("proposal_kind must be schema_change, source_policy, skill_candidate, or other")
    if workflow == "contradiction-record" and parsed["severity"] not in {"low", "medium", "high", "blocking"}:
        raise VCRunError("severity must be low, medium, high, or blocking")
    if workflow in {"source-watch", "source-unwatch"}:
        # Shape pre-check only, case preserved: vcops normalize_uri is the
        # normalization authority and lowercases just the scheme/authority, so
        # lowercasing the whole value here would corrupt case-sensitive paths
        # and queries and desynchronize the workflow lane from the operator lane.
        source_uri = parsed["source_uri"].strip()
        if not re.match(r"^https?://[^\s/]+", source_uri, re.IGNORECASE):
            raise VCRunError("source_uri must be an http(s) URL")
        parsed["source_uri"] = source_uri
    if workflow == "source-watch":
        if parsed["source_class"] not in {
            "company_blog", "vc_portfolio", "news_rss", "press_release",
            "research_report", "open_source", "job_board", "other",
        }:
            raise VCRunError("source_class is outside the reviewed watchlist taxonomy")
        if parsed["cadence"] not in {"daily", "weekly", "monthly"}:
            raise VCRunError("cadence must be daily, weekly, or monthly")
    if workflow == "source-scan":
        # Match the vcops source-scan bound (1..500) so an over-limit request
        # is refused here instead of failing mid-run after workflow-start.
        if not re.fullmatch(r"[1-9][0-9]{0,2}", parsed["limit"]) or int(parsed["limit"]) > 500:
            raise VCRunError("limit must be an integer between 1 and 500")
    if workflow == "memo-record":
        if not re.fullmatch(r"[0-9a-f]{64}", parsed["evidence_hash"]):
            raise VCRunError("evidence_hash must be a lowercase SHA-256 digest")
        try:
            citations = json.loads(parsed["citations_json"], object_pairs_hook=_unique_object)
        except json.JSONDecodeError as exc:
            raise VCRunError(f"citations_json must contain valid JSON: {exc.msg}") from exc
        if not isinstance(citations, list) or any(not isinstance(item, dict) for item in citations):
            raise VCRunError("citations_json must be a JSON array of citation objects")
        parsed["citations_json"] = json.dumps(citations, sort_keys=True, separators=(",", ":"))
    if workflow == "inbound-intake":
        document_path = PurePosixPath(parsed["document_path"])
        if not document_path.is_absolute() or ".." in document_path.parts:
            raise VCRunError("document_path must be an absolute normalized path")
        if document_path == PurePosixPath("/inbox") or PurePosixPath("/inbox") not in document_path.parents:
            raise VCRunError("document_path must be below /inbox")
        if parsed["channel_provider"] not in {"manual", "slack", "msteams", "discord", "telegram"}:
            raise VCRunError("channel_provider is not a reviewed intake provider")
        if parsed["channel_provider"] != "manual":
            raise VCRunError("/inbox intake is operator/manual only; channel attachments use document-ingest")
    if workflow == "document-ingest":
        document_path = PurePosixPath(parsed["document_path"])
        media_root = PurePosixPath("/home/node/.openclaw/media/inbound")
        if (
            not document_path.is_absolute()
            or ".." in document_path.parts
            or media_root not in document_path.parents
            or document_path.parent != media_root
        ):
            raise VCRunError("document_path must be a direct file below the OpenClaw inbound media root")
    if workflow == "preference-observe":
        if parsed["preference_key"] not in {
            "memo_length", "communication_tone", "research_depth", "citation_density", "output_structure"
        }:
            raise VCRunError("preference_key is outside the bounded schema")
        if parsed["observation_kind"] not in {"explicit", "inferred"}:
            raise VCRunError("observation_kind must be explicit or inferred")
    if workflow == "preference-forget" and parsed["preference_key"] not in {
        "memo_length", "communication_tone", "research_depth", "citation_density", "output_structure"
    }:
        raise VCRunError("preference_key is outside the bounded schema")
    if workflow in {"inbound-intake", "inbound-text-intake", "outbound-scout", "document-lead-intake"}:
        domain = parsed["company_domain"].strip().lower().rstrip(".")
        if not DOMAIN_RE.fullmatch(domain):
            raise VCRunError("company_domain must be a bare DNS domain")
        parsed["company_domain"] = domain
    if workflow == "inbound-text-intake" and parsed["origin_subtype"] not in {
        "direct_contact", "network_referral", "event_followup", "unknown",
    }:
        raise VCRunError("origin_subtype is outside the reviewed inbound taxonomy")

    for key in contract["json_object_keys"]:
        parsed[key] = _validate_json_object_string(key, parsed[key])

    return json.dumps(parsed, sort_keys=True, separators=(",", ":"))


def _validate_install() -> None:
    try:
        if not stat.S_ISLNK(LOBSTER_BIN.lstat().st_mode):
            raise VCRunError("pinned Lobster launcher must be the image-owned symlink")
        actual_target = LOBSTER_BIN.resolve(strict=True)
        expected_target = EXPECTED_LOBSTER_TARGET.resolve(strict=True)
        if actual_target != expected_target or not stat.S_ISREG(actual_target.stat().st_mode):
            raise VCRunError("pinned Lobster launcher resolves outside the reviewed image dependency")
        package = json.loads(
            LOBSTER_PACKAGE_JSON.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
        )
        if package.get("version") != LOBSTER_VERSION:
            raise VCRunError("installed Lobster version does not match the reviewed pin")
    except (OSError, json.JSONDecodeError) as exc:
        raise VCRunError("pinned Lobster installation is unavailable or invalid") from exc

    for directory in (
        Path("/workspaces"),
        Path("/workspaces/vc-chief"),
        Path("/workspaces/vc-chief/vc"),
        WORKFLOW_ROOT,
    ):
        try:
            info = directory.lstat()
        except OSError as exc:
            raise VCRunError(f"fixed workflow directory is unavailable: {directory}") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise VCRunError(f"fixed workflow directory must be a non-symlink directory: {directory}")
    for contract in WORKFLOWS.values():
        workflow_path = WORKFLOW_ROOT / contract["file"]
        try:
            info = workflow_path.lstat()
        except OSError as exc:
            raise VCRunError(f"reviewed workflow is missing: {workflow_path}") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise VCRunError(f"reviewed workflow must be a non-symlink regular file: {workflow_path}")


def _last_json_object(rendered: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for offset in (match.start() for match in reversed(list(re.finditer(r"\{", rendered)))):
        try:
            value, end = decoder.raw_decode(rendered[offset:])
        except json.JSONDecodeError:
            continue
        if not rendered[offset + end :].strip() and isinstance(value, dict):
            return value
    return None


def _redact_output(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _sensitive_output_key(key) else _redact_output(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_output(item) for item in value]
    return value


def _sensitive_output_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return any(
        marker in normalized
        for marker in ("password", "passwd", "secret", "token", "apikey", "dsn", "credential")
    )


def _normalize_lobster_output(
    return_code: int,
    rendered: str,
    *,
    runner_metadata: dict[str, Any] | None = None,
    expected_plain_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    metadata = dict(runner_metadata or {})
    if expected_plain_version is not None:
        expected_output = f"{expected_plain_version}\n"
        if return_code != 0 or rendered != expected_output:
            return (
                {
                    "ok": False,
                    "runner": "vcrun",
                    "exit_code": return_code,
                    "error": {
                        "code": "invalid_lobster_version",
                        "message": "pinned Lobster did not emit the exact reviewed plain version",
                    },
                    **metadata,
                },
                None,
            )
        lobster_version = {"ok": True, "version": expected_plain_version}
        return (
            {
                "ok": True,
                "runner": "vcrun",
                "exit_code": 0,
                "lobster": lobster_version,
                **metadata,
            },
            lobster_version,
        )

    lobster_envelope = _last_json_object(rendered)
    if lobster_envelope is None:
        return (
            {
                "ok": False,
                "runner": "vcrun",
                "exit_code": return_code,
                "error": {
                    "code": "invalid_lobster_output",
                    "message": "pinned Lobster did not emit a final JSON envelope",
                },
                **metadata,
            },
            None,
        )
    redacted = _redact_output(lobster_envelope)
    ok = return_code == 0 and redacted.get("ok") is True
    return (
        {
            "ok": ok,
            "runner": "vcrun",
            "exit_code": return_code,
            "lobster": redacted,
            **metadata,
        },
        redacted,
    )


def _run_helper(argv: list[str], *, label: str) -> tuple[int, dict[str, Any]]:
    """Run one bounded vcops-workflow command and return its JSON envelope.

    Shared by the pre-flight replay probe and the failure reconciliation: both
    are short, single-object helper calls made outside the Lobster child, with
    the same scrubbed environment and output bound.
    """
    try:
        helper = subprocess.run(
            ["/workspaces/vc-chief/vc/bin/vcops-workflow", *argv],
            env={"PATH": "/usr/bin:/bin"},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise VCRunError(f"Postgres {label} timed out") from exc
    if len(helper.stdout.encode("utf-8")) > MAX_RECONCILIATION_BYTES:
        raise VCRunError(f"Postgres {label} output exceeded its bound")
    try:
        result = json.loads(helper.stdout, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, VCRunError) as exc:
        raise VCRunError(f"Postgres {label} returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise VCRunError(f"Postgres {label} returned invalid JSON")
    return helper.returncode, result


def _probe_workflow_replay(
    *,
    workflow: str,
    idempotency_key: str,
    input_digest: str,
) -> dict[str, Any]:
    """Classify a reused idempotency key before any workflow step runs.

    This is what makes an unchanged retry of a completed operation the
    documented no-op instead of a second execution: several intake workflows
    create their company and lead rows before `workflow-start`, so the decision
    has to be taken here, ahead of Lobster, not inside the graph.
    """
    contract = WORKFLOWS.get(workflow)
    if contract is None:
        raise VCRunError("cannot probe an unknown fixed workflow")
    return_code, result = _run_helper(
        [
            "workflow-replay-probe",
            "--workflow",
            contract["database_workflow"],
            "--idempotency-key",
            idempotency_key,
            "--input-digest",
            input_digest,
        ],
        label="workflow replay probe",
    )
    if return_code != 0 or result.get("ok") is not True:
        error = result.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            # A typed refusal (tampered replay, cancelled/lost run) is the
            # answer, not a runner malfunction: surface it verbatim so the two
            # cases stay distinguishable.
            raise _ProbeRefusal(error)
        raise VCRunError("Postgres workflow replay probe failed")
    probe = result.get("workflow_replay_probe")
    if not isinstance(probe, dict) or probe.get("outcome") not in {
        "absent", "in_progress", "completed", "retried", "unverifiable",
    }:
        raise VCRunError("Postgres workflow replay probe returned an invalid outcome")
    return probe


def _reconcile_workflow_failure(
    *,
    workflow: str,
    idempotency_key: str,
    reason: str,
) -> dict[str, Any]:
    contract = WORKFLOWS.get(workflow)
    if contract is None:
        raise VCRunError("cannot reconcile failure for an unknown fixed workflow")
    return_code, result = _run_helper(
        [
            "workflow-reconcile-failure",
            "--workflow",
            contract["database_workflow"],
            "--idempotency-key",
            idempotency_key,
            "--reason",
            reason,
        ],
        label="workflow-failure reconciliation",
    )
    if return_code != 0 or result.get("ok") is not True:
        raise VCRunError("Postgres workflow-failure reconciliation failed")
    reconciliation = result.get("workflow_failure_reconciliation")
    if not isinstance(reconciliation, dict):
        raise VCRunError("Postgres workflow-failure reconciliation omitted its result")
    outcome = reconciliation.get("outcome")
    if outcome not in {"not_started", "already_failed", "transitioned_failed"}:
        raise VCRunError("Postgres workflow-failure reconciliation returned an invalid outcome")
    workflow_run = reconciliation.get("workflow_run")
    if outcome == "not_started":
        if workflow_run is not None:
            raise VCRunError("not-started failure reconciliation unexpectedly returned a workflow run")
    elif not isinstance(workflow_run, dict) or workflow_run.get("status") != "failed":
        raise VCRunError("Postgres workflow-failure reconciliation did not establish failed state")
    return result


def _attach_failure_reconciliation(
    payload: dict[str, Any],
    *,
    failure_hook: Any,
    reason: str,
) -> None:
    """Record the cleanup outcome on the failure payload without replacing it.

    A reconciliation that itself fails used to be raised as a VCRunError, which
    discarded `payload` — including the Lobster envelope carrying the failing
    step's error output (the step id itself is named only for timeouts; a
    command failure is identified by its helper error content) — and left the
    operator with only the second, downstream message. The original failure is
    the diagnostic one, so both are reported: the run still exits non-zero, and
    `postgres_reconciliation` says whether the database was left reconciled.
    """
    try:
        reconciliation = failure_hook(reason)
    except (OSError, subprocess.SubprocessError, VCRunError) as exc:
        payload["postgres_reconciliation"] = {
            "ok": False,
            "reason": reason,
            "error": {
                "code": "reconciliation_failed",
                "message": f"Postgres workflow-failure reconciliation did not complete: {exc}",
            },
        }
        return
    if not isinstance(reconciliation, dict) or reconciliation.get("ok") is not True:
        payload["postgres_reconciliation"] = {
            "ok": False,
            "reason": reason,
            "error": {
                "code": "reconciliation_invalid",
                "message": "Postgres workflow-failure reconciliation returned an invalid result",
            },
        }
        return
    payload["postgres_reconciliation"] = reconciliation


def _execute(
    argv: list[str],
    timeout: int,
    *,
    runner_metadata: dict[str, Any] | None = None,
    success_hook: Any = None,
    trusted_env: dict[str, str] | None = None,
    expected_plain_version: str | None = None,
    failure_hook: Any = None,
) -> int:
    _validate_install()
    safe_env = {
        "HOME": "/home/node",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/opt/vcops-venv/bin:/usr/local/bin:/usr/bin:/bin",
        "TZ": "Europe/Berlin",
        "OPENCLAW_STATE_DIR": "/home/node/.openclaw",
        "LOBSTER_STATE_DIR": "/home/node/.openclaw/lobster/state",
        "VCOPS_AGENT_MODE": "1",
        "VCOPS_INBOX_ROOT": "/inbox",
        "VCOPS_MEDIA_ROOT": "/home/node/.openclaw/media/inbound",
        "VCOPS_QUARANTINE_ROOT": "/quarantine",
        "VCOPS_STATE_ROOT": "/home/node/.openclaw/vcops",
        "VCOPS_WORKSPACE_ROOT": "/workspaces/vc-chief/vc",
    }
    if trusted_env:
        safe_env.update(trusted_env)
    process = subprocess.Popen(
        argv,
        cwd=WORKDIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=safe_env,
        start_new_session=True,
    )
    _CURRENT_CHILD_PGID[:] = [process.pid]
    assert process.stdout is not None
    captured = bytearray()
    deadline = time.monotonic() + timeout
    eof = False
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                os.killpg(process.pid, signal.SIGKILL)
                _wait_after_kill(process)
                payload = {
                    "ok": False,
                    "runner": "vcrun",
                    "exit_code": process.returncode,
                    "error": {
                        "code": "lobster_timeout",
                        "message": f"Lobster exceeded the fixed {timeout}s timeout",
                    },
                }
                if runner_metadata:
                    payload.update(runner_metadata)
                if failure_hook is not None:
                    _attach_failure_reconciliation(
                        payload,
                        failure_hook=failure_hook,
                        reason="lobster_timeout",
                    )
                _emit(payload)
                return 1
            for key, _mask in selector.select(timeout=min(0.1, remaining)):
                chunk = os.read(key.fd, 65_536)
                if not chunk:
                    selector.unregister(process.stdout)
                    eof = True
                    break
                captured.extend(chunk)
                if len(captured) > MAX_OUTPUT_BYTES:
                    os.killpg(process.pid, signal.SIGKILL)
                    _wait_after_kill(process)
                    payload = {
                        "ok": False,
                        "runner": "vcrun",
                        "exit_code": process.returncode,
                        "error": {
                            "code": "lobster_output_limit",
                            "message": (
                                f"Lobster output exceeded the fixed {MAX_OUTPUT_BYTES}-byte limit"
                            ),
                        },
                    }
                    if runner_metadata:
                        payload.update(runner_metadata)
                    if failure_hook is not None:
                        _attach_failure_reconciliation(
                            payload,
                            failure_hook=failure_hook,
                            reason="lobster_output_limit",
                        )
                    _emit(payload)
                    return 1
    try:
        return_code = process.wait(timeout=10)
        _CURRENT_CHILD_PGID.clear()
    except subprocess.TimeoutExpired:
        # Lobster closed stdout but did not exit: kill the process group and
        # fail through the structured error contract, never a raw traceback.
        # This is the same failure family as the timeout/output-limit kills, so
        # it must also reconcile the database workflow run to failed instead of
        # leaving it stranded in running.
        os.killpg(process.pid, signal.SIGKILL)
        _wait_after_kill(process)
        payload = {
            "ok": False,
            "runner": "vcrun",
            "exit_code": process.returncode,
            "error": {
                "code": "lobster_no_exit",
                "message": (
                    "Lobster closed its output but did not exit within the fixed bound"
                ),
            },
        }
        if runner_metadata:
            payload.update(runner_metadata)
        if failure_hook is not None:
            _attach_failure_reconciliation(
                payload,
                failure_hook=failure_hook,
                reason="lobster_no_exit",
            )
        _emit(payload)
        return 1
    rendered = captured.decode("utf-8", errors="replace")
    payload, lobster_envelope = _normalize_lobster_output(
        return_code,
        rendered,
        runner_metadata=runner_metadata,
        expected_plain_version=expected_plain_version,
    )
    ok = payload.get("ok") is True
    if not ok and failure_hook is not None:
        error = payload.get("error")
        reason = (
            "lobster_invalid_output"
            if isinstance(error, dict) and error.get("code") == "invalid_lobster_output"
            else "lobster_step_failure"
            if lobster_envelope is not None
            else "lobster_runner_failure"
        )
        _attach_failure_reconciliation(payload, failure_hook=failure_hook, reason=reason)
    if ok and success_hook is not None and lobster_envelope is not None:
        hook_result = success_hook(lobster_envelope)
        if hook_result:
            payload.update(hook_result)
    _emit(payload)
    return 0 if ok else (return_code or 1)


def _build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="vcrun", description="Fixed-workflow Lobster launcher"
    )
    parser.add_argument("--version", action="version", version=f"vcrun {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("run", "dry-run"):
        child = sub.add_parser(command)
        child.add_argument("workflow", choices=sorted(WORKFLOWS))
        child.add_argument("--args-json", required=True)

    sub.add_parser("doctor")
    sub.add_parser("version")
    return parser


def main(argv: list[str] | None = None) -> int:
    _install_signal_handlers()
    try:
        args = _build_parser().parse_args(argv)
    except _UsageError:
        # The parser raises instead of printing argparse usage text, so a
        # usage failure emits exactly one JSON object on stderr and nothing
        # else — the same contract as every other error path.
        return _error(
            "usage_error",
            "invalid vcrun command line; see 'vcrun --help' for the fixed surface",
        )
    except SystemExit as exc:
        # --help/--version print conventional text and exit 0; keep that.
        code = exc.code if isinstance(exc.code, int) else 2
        if code == 0:
            return 0
        return _error(
            "usage_error",
            "invalid vcrun command line; see 'vcrun --help' for the fixed surface",
        )
    try:
        if args.command in {"run", "dry-run"}:
            payload = validate_workflow_args(args.workflow, args.args_json)
            # The canonical argument digest binds the run row to exactly these
            # arguments. It is computed here, over the validated and normalized
            # payload, and injected rather than accepted: a caller-supplied
            # digest would be self-certifying.
            input_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            parsed_payload = json.loads(payload, object_pairs_hook=_unique_object)
            parsed_payload["input_digest"] = input_digest
            payload = json.dumps(parsed_payload, sort_keys=True, separators=(",", ":"))
            workflow_path = WORKFLOW_ROOT / WORKFLOWS[args.workflow]["file"]
            command = [
                str(LOBSTER_BIN),
                "run",
                "--mode",
                "tool",
            ]
            if args.command == "dry-run":
                command.append("--dry-run")
            command.extend(["--file", str(workflow_path), "--args-json", payload])
            failure_hook = None
            if args.command == "run":
                idempotency_key = parsed_payload["idempotency_key"]
                _validate_install()
                probe = _probe_workflow_replay(
                    workflow=args.workflow,
                    idempotency_key=idempotency_key,
                    input_digest=input_digest,
                )
                if probe["outcome"] == "completed":
                    # The documented idempotent replay: this exact operation
                    # already succeeded, so its records are the result and no
                    # step runs a second time.
                    _emit(
                        {
                            "ok": True,
                            "runner": "vcrun",
                            "exit_code": 0,
                            "workflow": args.workflow,
                            "idempotent_replay": probe,
                        }
                    )
                    return 0

                def failure_hook(reason: str) -> dict[str, Any]:
                    return _reconcile_workflow_failure(
                        workflow=args.workflow,
                        idempotency_key=idempotency_key,
                        reason=reason,
                    )

            return _execute(
                command,
                RUN_TIMEOUT_SECONDS,
                failure_hook=failure_hook,
            )

        if args.command == "doctor":
            return _execute([str(LOBSTER_BIN), "doctor"], CONTROL_TIMEOUT_SECONDS)
        if args.command == "version":
            return _execute(
                [str(LOBSTER_BIN), "version"],
                CONTROL_TIMEOUT_SECONDS,
                runner_metadata={
                    "vcrun_version": VERSION,
                    "required_lobster_version": LOBSTER_VERSION,
                },
                expected_plain_version=LOBSTER_VERSION,
            )
        raise VCRunError("unknown command")
    except KeyboardInterrupt:
        # Reached only if the signal handler could not be installed (non-main
        # thread); still honor the JSON contract and reap any supervised child.
        _kill_current_child()
        return _error("interrupted", "vcrun interrupted")
    except _ProbeRefusal as exc:
        return _error(
            str(exc.error.get("code") or "workflow_replay_refused"),
            str(exc.error.get("message") or "workflow replay refused"),
            details=exc.error.get("details"),
        )
    except VCRunError as exc:
        return _error("vcrun_error", str(exc))
    except OSError as exc:
        return _error("runtime_error", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
