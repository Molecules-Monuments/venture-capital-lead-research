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


def run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment.setdefault(
        "VCOPS_HELPER", str(PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py")
    )
    return subprocess.run(
        command,
        cwd=PACKAGE,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def test_suite(name: str, directory: str, pattern: str) -> dict[str, object]:
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


def command_check(name: str, command: list[str], timeout: int = 300) -> dict[str, object]:
    process = run(command, timeout=timeout)
    rendered = process.stderr + process.stdout
    return {
        "name": name,
        "result": "PASS" if process.returncode == 0 else "FAIL",
        "detail": None if process.returncode == 0 else rendered[-20_000:],
    }


def syntax_checks() -> list[dict[str, object]]:
    python_errors: list[str] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if "_internal" in path.parts:
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            python_errors.append(f"{path.relative_to(PACKAGE)}: {exc}")
    checks: list[dict[str, object]] = [
        {
            "name": "python-syntax",
            "result": "PASS" if not python_errors else "FAIL",
            "detail": python_errors or None,
        }
    ]
    shell_paths = sorted(PACKAGE.glob("scripts/*.sh")) + sorted(PACKAGE.glob("migrations/*.sh"))
    for path in shell_paths:
        checks.append(command_check(f"shell-syntax:{path.name}", ["sh", "-n", str(path)]))
    return checks


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
    checks = [test_suite(*suite) for suite in SUITES]
    checks.extend(syntax_checks())
    ruff = Path(sys.executable).with_name("ruff")
    if not ruff.is_file():
        discovered_ruff = shutil.which("ruff")
        ruff = Path(discovered_ruff) if discovered_ruff else ruff
    checks.append(
        command_check(
            "ruff", [str(ruff), "check", ".", "--exclude", "_internal", "--no-cache"]
        )
        if ruff.is_file()
        else {
            "name": "ruff",
            "result": "FAIL",
            "detail": "Ruff is missing; install the complete hash-locked requirements-dev.lock",
        }
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
