#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Operator-only Lobster pause controller; never add this path to exec approvals."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


# The fixed implementation below is loaded by path, which would byte-compile it
# into workspaces/vc-chief/vc/bin/__pycache__ and make `verify_release.py
# --pristine` report an undeclared file. The image wrappers already pass `-B`;
# suppress it here too so a direct operator invocation is equally safe.
sys.dont_write_bytecode = True

_IMAGE_IMPL_PATH = Path("/workspaces/vc-chief/vc/bin/vcrun.py")
_IMPL_PATH = _IMAGE_IMPL_PATH if _IMAGE_IMPL_PATH.is_file() else Path(__file__).with_name("vcrun.py")
_SPEC = importlib.util.spec_from_file_location("vcrun_fixed_impl", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise SystemExit("unable to load fixed vcrun implementation")
_IMPL = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _IMPL
_SPEC.loader.exec_module(_IMPL)


OPERATOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,199}$")
APPROVAL_ID_RE = re.compile(r"^[0-9a-f]{8}$")
MAX_RECONCILIATION_BYTES = 64 * 1024


def _reconcile_postgres_cancellation(
    *,
    run_id: str,
    expected_revision: int,
    operator_id: str,
) -> dict[str, object]:
    try:
        helper = subprocess.run(
            [
                "/workspaces/vc-chief/vc/bin/vcops-operator",
                "workflow-cancel",
                "--run-id",
                run_id,
                "--expected-revision",
                str(expected_revision),
                "--reason",
                "operator rejected or cancelled the Lobster persistence checkpoint",
                "--terminal",
                # evaluate-lead is the only workflow with an approval pause; a
                # mistyped-but-valid run_id for any other workflow must never
                # be terminally cancelled by this reconciliation.
                "--expected-workflow",
                "evaluate-lead",
            ],
            env={"PATH": "/usr/bin:/bin", "VCOPS_OPERATOR_ID": operator_id},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise _IMPL.VCRunError("Postgres cancellation reconciliation timed out") from exc
    if len(helper.stdout.encode("utf-8")) > MAX_RECONCILIATION_BYTES:
        raise _IMPL.VCRunError("Postgres cancellation reconciliation output exceeded its bound")
    try:
        result = json.loads(helper.stdout, object_pairs_hook=_IMPL._unique_object)
    except json.JSONDecodeError as exc:
        raise _IMPL.VCRunError("Postgres cancellation reconciliation returned invalid JSON") from exc
    if helper.returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
        # Surface the helper's structured error (e.g. revision_conflict with
        # current_revision) so the operator can correct the retry instead of
        # guessing.
        detail = ""
        if isinstance(result, dict) and isinstance(result.get("error"), dict):
            detail = ": " + json.dumps(result["error"], sort_keys=True, separators=(",", ":"))
        raise _IMPL.VCRunError(f"Postgres cancellation reconciliation failed{detail}")
    workflow_run = result.get("workflow_run")
    status = workflow_run.get("status") if isinstance(workflow_run, dict) else None
    if status != "cancelled":
        raise _IMPL.VCRunError(
            "Postgres cancellation reconciliation did not establish the required cancelled state"
        )
    return result


def main() -> int:
    _IMPL._install_signal_handlers()
    parser = argparse.ArgumentParser(
        prog="vcrun-control",
        description="Operator-only control for paused fixed Lobster workflows",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--id", required=True, dest="approval_id")
    resume.add_argument("--run-id")
    resume.add_argument("--expected-revision", type=int)
    decision = resume.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", choices=("yes", "no"))
    decision.add_argument("--cancel", action="store_true")
    args = parser.parse_args()

    postgres_reconciliation: dict[str, object] | None = None
    try:
        operator_id = os.environ.get("VCOPS_OPERATOR_ID", "")
        if not OPERATOR_ID_RE.fullmatch(operator_id):
            raise _IMPL.VCRunError("operator-id must be a stable operator identifier")
        if not APPROVAL_ID_RE.fullmatch(args.approval_id):
            raise _IMPL.VCRunError("approval ID must be exactly eight lowercase hexadecimal characters")
        rejecting = args.cancel or args.approve == "no"
        if rejecting and (not args.run_id or args.expected_revision is None or args.expected_revision < 1):
            raise _IMPL.VCRunError("rejection/cancel requires Postgres --run-id and positive --expected-revision")
        if not rejecting and (args.run_id is not None or args.expected_revision is not None):
            raise _IMPL.VCRunError("Postgres reconciliation arguments are only valid for rejection/cancel")
        command = [str(_IMPL.LOBSTER_BIN), "resume", "--id", args.approval_id]
        if args.cancel:
            command.append("--cancel")
        else:
            command.extend(["--approve", args.approve])
        _IMPL._emit(
            {
                "ok": True,
                "event": "operator_lobster_control",
                "operator_id": operator_id,
                "decision": "cancel" if args.cancel else f"approve:{args.approve}",
            },
            stream=sys.stderr,
        )
        if rejecting:
            postgres_reconciliation = _reconcile_postgres_cancellation(
                run_id=args.run_id,
                expected_revision=args.expected_revision,
                operator_id=operator_id,
            )

        # An approved resume continues the paused workflow through its
        # post-approval persistence steps (compiled truth, evaluation save,
        # terminal transition — a larger budget than any control action), so it
        # gets the full run timeout; killing it mid-persistence would strand
        # the run. Rejection/cancel resumes terminate immediately and keep the
        # short control bound.
        timeout = (
            _IMPL.RUN_TIMEOUT_SECONDS if args.approve == "yes" else _IMPL.CONTROL_TIMEOUT_SECONDS
        )
        return _IMPL._execute(
            command,
            timeout,
            runner_metadata=(
                {"postgres_reconciliation": postgres_reconciliation}
                if postgres_reconciliation is not None
                else None
            ),
            trusted_env={"LOBSTER_APPROVAL_APPROVED_BY": operator_id},
        )
    except KeyboardInterrupt:
        _IMPL._kill_current_child()
        return _IMPL._error(
            "interrupted",
            "vcrun-control interrupted",
            details=(
                {"postgres_reconciliation": postgres_reconciliation}
                if postgres_reconciliation is not None
                else None
            ),
        )
    except _IMPL.VCRunError as exc:
        return _IMPL._error(
            "vcrun_control_error",
            str(exc),
            details=(
                {"postgres_reconciliation": postgres_reconciliation}
                if postgres_reconciliation is not None
                else None
            ),
        )
    except OSError as exc:
        return _IMPL._error(
            "runtime_error",
            str(exc),
            details=(
                {"postgres_reconciliation": postgres_reconciliation}
                if postgres_reconciliation is not None
                else None
            ),
        )


if __name__ == "__main__":
    raise SystemExit(main())
