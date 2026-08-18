#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Run the complete deterministic Version 3 offline verification matrix."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parent.parent
SUITES = (
    ("contracts", "tests/contracts", "test*.py"),
    ("v3", "tests/v3", "test*.py"),
    ("retrieval", "tests/retrieval", "test*.py"),
    ("infrastructure", "tests/infrastructure", "test*.py"),
    ("g6", "tests/g6", "test*.py"),
    ("g5", "tests/g5", "test*.py"),
    ("g7", "tests/g7", "test*.py"),
    ("g4-semantics", "tests/g4", "test_semantics.py"),
    ("g4-document-security", "tests/g4", "test_document_security.py"),
)

# First line of a shipped file that hands it to a POSIX shell. The same
# expression selects the world tests/g7/test_recovery_lifecycle.py scans for
# dash-mangled escapes; that module imports shell_paths() rather than keeping a
# second copy of the rule.
SHELL_SHEBANG = re.compile(r"^#!\s*/(usr/)?bin/(env\s+)?(sh|bash|dash)\b")

# Measured floor for the enumeration below (the shipped tree yields 14). It is
# not a target for growth: it exists so that an enumeration which silently
# empties — an unreadable manifest, a shebang expression that stops matching —
# fails the gate instead of reporting PASS with nothing parsed.
SHELL_SCRIPT_FLOOR = 14


def run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Unconditional pin: an inherited VCOPS_HELPER (e.g. a stale export from a
    # documented per-suite invocation or another checkout) would silently point
    # the g4 semantics/document-security suites at foreign helper code and let
    # this gate certify a helper it never ran.
    environment["VCOPS_HELPER"] = str(
        PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"
    )
    return subprocess.run(
        command,
        cwd=PACKAGE,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def test_suite(name: str, directory: str, pattern: str) -> dict[str, Any]:
    process = run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            directory,
            "-p",
            pattern,
        ]
    )
    rendered = process.stderr + process.stdout
    match = re.search(r"Ran\s+(\d+)\s+tests?", rendered)
    count = int(match.group(1)) if match else 0
    skipped = bool(re.search(r"skipped=|\.\.\. skipped", rendered, re.IGNORECASE))
    passed = process.returncode == 0 and count > 0 and not skipped
    return {
        "name": name,
        "result": "PASS" if passed else "FAIL",
        "tests": count,
        "skipped": skipped,
        "detail": None if passed else rendered[-20_000:],
    }


def declared_suite_directories() -> set[str]:
    """The tests/<name> directories the SUITES table above actually discovers."""
    return {Path(directory).name for _, directory, _ in SUITES}


def present_suite_directories() -> set[str]:
    """The tests/<name> directories holding at least one discoverable module.

    `test*.py` is the discovery pattern every SUITES entry hands to unittest,
    so it is also the key for "is this a suite": a directory carrying only
    fixtures is not one and does not appear here. tests/g3 ships a README and
    two .jsonl case files consumed by other suites, and drops out on that key
    rather than on a name this function would have to keep in step.
    """
    try:
        return {
            path.name
            for path in (PACKAGE / "tests").iterdir()
            if path.is_dir() and any(path.glob("test*.py"))
        }
    except OSError as exc:
        raise SystemExit(
            f"suite-inventory: cannot enumerate {PACKAGE / 'tests'}: {exc}"
        ) from exc


def require_complete_suite_inventory() -> None:
    """Refuse to report on a matrix whose suite inventory has drifted.

    SUITES is declared rather than globbed because each entry carries its own
    discovery pattern: tests/g4 is deliberately split, with its two
    database-free modules named there and the other five left to
    scripts/run_g4.py, which needs a disposable PostgreSQL. That is why the
    comparison is at directory granularity and not at file granularity.

    A declared inventory stops covering a suite the moment someone adds one:
    nothing fails, the reported test total moves by zero, and this gate still
    prints PASS over a directory it never discovered. scripts/run_g4.py already
    applies this guard one level down; this is the same fail-closed check for
    the tests/ tree as a whole.
    """
    declared = declared_suite_directories()
    present = present_suite_directories()
    if declared != present:
        absent = sorted(declared - present)
        unrun = sorted(present - declared)
        raise SystemExit(
            "suite-inventory: the tests/ tree does not match this gate's declared "
            f"SUITES; declared-but-absent={absent}, present-but-never-run={unrun}. "
            "Add the new suite to SUITES with its discovery pattern, or drop the "
            "stale entry."
        )


def command_check(name: str, command: list[str], timeout: int = 300) -> dict[str, Any]:
    process = run(command, timeout=timeout)
    rendered = process.stderr + process.stdout
    return {
        "name": name,
        "result": "PASS" if process.returncode == 0 else "FAIL",
        "detail": None if process.returncode == 0 else rendered[-20_000:],
    }


def shell_paths() -> list[Path]:
    """Every file declared in manifest.json whose shebang selects a POSIX shell.

    Enumerated from the manifest rather than from a `scripts/*.sh` +
    `migrations/*.sh` glob: the five launchers under
    workspaces/vc-chief/vc/bin/ (`vcops-workflow`, `vcops-operator`,
    `vcrun-control`, `agent/vcops`, `agent/vcrun`) carry no suffix, so both
    globs missed them and no step of this matrix parsed them at all.
    """
    # Fail closed rather than raising. This runs inside syntax_checks(), which
    # the matrix reaches only after nine suites have executed, so an unreadable
    # manifest destroyed the whole report instead of producing one FAIL -- and
    # the shell-inventory detail text below already names exactly this cause,
    # describing a path the code could not reach. Returning no paths trips the
    # SHELL_SCRIPT_FLOOR guard, which is that FAIL.
    try:
        manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest["files"]
    except (OSError, ValueError, KeyError):
        return []
    found: list[Path] = []
    for entry in entries:
        path = PACKAGE / entry["path"]
        try:
            first = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        except (OSError, IndexError):
            continue
        if SHELL_SHEBANG.match(first):
            found.append(path)
    return sorted(found)


def syntax_checks() -> list[dict[str, Any]]:
    python_errors: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "_internal" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            python_errors.append(f"{path.relative_to(PACKAGE)}: {exc}")
    checks: list[dict[str, Any]] = [
        {
            "name": "python-syntax",
            "result": "PASS" if not python_errors else "FAIL",
            "detail": python_errors or None,
        }
    ]
    paths = shell_paths()
    if len(paths) < SHELL_SCRIPT_FLOOR:
        # Emitted only when the enumeration has shrunk below the measured
        # floor, so a healthy tree carries exactly one check per shipped shell
        # script and no permanent placeholder in the documented check count.
        checks.append(
            {
                "name": "shell-inventory",
                "result": "FAIL",
                "detail": (
                    f"manifest.json declares {len(paths)} files with a POSIX-shell "
                    f"shebang; at least {SHELL_SCRIPT_FLOOR} are expected. The "
                    "shell-syntax enumeration reads the manifest, so a stale or "
                    "unreadable manifest silently empties it."
                ),
            }
        )
    # One `sh -n` per shipped shell script. This parses each file with whichever
    # /bin/sh the machine running the gate provides, so it catches parse errors
    # under that shell. It is not by itself a proof of dash-parseability, which
    # is what the deployment needs: on the macOS gate host /bin/sh is GNU bash
    # 3.2, which accepts `ARR=(a b c)`, `function f { }` and here-strings that
    # Debian's dash rejects with rc=2 (measured 2026-08-15).
    for path in paths:
        checks.append(
            command_check(
                f"shell-syntax:{path.relative_to(PACKAGE).as_posix()}",
                ["sh", "-n", str(path)],
            )
        )
    return checks


def locked_tool(name: str) -> Path:
    """Resolve a checker from this gate's own virtualenv, then from PATH.

    The virtualenv is tried first on purpose: both checkers are pinned with
    hashes in requirements-dev.lock, and a PATH copy of a different version
    would silently decide what this gate reports.
    """
    tool = Path(sys.executable).with_name(name)
    if tool.is_file():
        return tool
    discovered = shutil.which(name)
    return Path(discovered) if discovered else tool


def missing_tool(name: str, label: str) -> dict[str, Any]:
    return {
        "name": name,
        "result": "FAIL",
        "detail": f"{label} is missing; install the complete hash-locked requirements-dev.lock",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--with-g4-database",
        action="store_true",
        help="also run the disposable-PostgreSQL G4 gate (requires local PostgreSQL tools)",
    )
    parser.add_argument(
        "--with-g6-image",
        metavar="IMAGE",
        help="run the offline pinned-image/channel schema gate against IMAGE",
    )
    parser.add_argument(
        "--with-retrieval-scale",
        action="store_true",
        help="run the disposable 100k-company/1m-fact retrieval scale gate",
    )
    parser.add_argument(
        "--with-schema-reference",
        action="store_true",
        help=(
            "verify docs/SCHEMA.sql still matches the schema the migrations produce "
            "(requires PostgreSQL 17 client tools)"
        ),
    )
    parser.add_argument(
        "--with-deployment",
        action="store_true",
        help="run the real bootstrap/vcrun deployment gate (requires Docker and a clean package)",
    )
    args = parser.parse_args()
    # Before the first suite runs, not after: if SUITES no longer describes the
    # tests/ tree, the matrix below is not the matrix this report would claim to
    # be, and an hour of gate time would end in a PASS that means less than it
    # says. --help still works, because argparse has already handled it.
    require_complete_suite_inventory()
    checks = [test_suite(*suite) for suite in SUITES]
    checks.extend(syntax_checks())
    ruff = locked_tool("ruff")
    checks.append(
        command_check(
            "ruff", [str(ruff), "check", ".", "--exclude", "_internal", "--no-cache"]
        )
        if ruff.is_file()
        else missing_tool("ruff", "Ruff")
    )
    # ty resolves third-party imports from the interpreter it is given, so it is
    # pointed at this gate's own interpreter — the locked virtualenv — rather
    # than at whatever is on PATH. --python-version pins the deployed floor
    # (Debian Python 3.11 in the derived image) instead of inferring it from the
    # host, and --extra-search-path mirrors the sys.path insert several suites
    # perform before importing check_env as a first-party module.
    ty = locked_tool("ty")
    checks.append(
        command_check(
            "ty",
            [
                str(ty), "check", ".",
                "--python", sys.executable,
                "--python-version", "3.11",
                "--extra-search-path", "scripts",
            ],
        )
        if ty.is_file()
        else missing_tool("ty", "ty")
    )
    checks.extend(
        (
            command_check("skill-agent-system", [sys.executable, "-B", "scripts/validate_skill_system.py"]),
            command_check("fixed-workflows", [sys.executable, "-B", "scripts/validate_workflows.py"]),
            command_check("manifest-current", [sys.executable, "-B", "scripts/build_release_manifest.py", "--check"]),
            command_check("release-pristine", [sys.executable, "-B", "scripts/verify_release.py", "--pristine"]),
        )
    )
    if args.with_g4_database:
        checks.append(command_check("g4-database", [sys.executable, "-B", "scripts/run_g4.py"], timeout=900))
    if args.with_schema_reference:
        # Kept out of the default matrix on purpose: this one needs a local
        # PostgreSQL, and the default gate is deliberately database-free.
        checks.append(
            command_check(
                "schema-reference-current",
                [sys.executable, "-B", "scripts/generate_schema_reference.py", "--check"],
                timeout=900,
            )
        )
    if args.with_g6_image:
        checks.append(
            command_check(
                "g6-pinned-image",
                [
                    sys.executable,
                    "-B",
                    "scripts/run_g6_image.py",
                    "--image",
                    args.with_g6_image,
                ],
                timeout=900,
            )
        )
    if args.with_retrieval_scale:
        checks.append(
            command_check(
                "retrieval-scale",
                [sys.executable, "-B", "scripts/run_retrieval_scale.py"],
                timeout=1200,
            )
        )
    if args.with_deployment:
        # Outer timeout must exceed the gate's own worst-case internal budget
        # (bootstrap + six vcrun executions + teardown) so a slow-but-progressing
        # run is never SIGKILLed mid-flight, which would skip the gate's teardown
        # and orphan the throwaway deployment.
        checks.append(
            command_check(
                "g8-deployment",
                [sys.executable, "-B", "scripts/run_g8_deployment.py"],
                timeout=7200,
            )
        )
    total = sum(int(check.get("tests", 0)) for check in checks)
    failed = [check for check in checks if check["result"] != "PASS"]
    report = {
        "gate": "Version 3 deterministic offline verification",
        "result": "FAIL" if failed else "PASS",
        "tests": total,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
