#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Run the fail-closed Version 3 data/helper gate on disposable PostgreSQL.

The gate applies every numbered SQL migration twice, runs every G4 suite with
zero skips permitted, and tears the temporary cluster down even on failure.
It never targets a configured production database.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


# pinned_postgres_major() loads scripts/check_env.py by path, which would
# byte-compile it into scripts/__pycache__ and make `verify_release.py
# --pristine` report an undeclared file. Suppress it so the gate stays safe to
# run even when someone omits `-B`.
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent.parent
MIGRATIONS = PACKAGE / "migrations"
TESTS = PACKAGE / "tests/g4"
HELPER = PACKAGE / "workspaces/vc-chief/vc/bin/vcops.py"


class GateError(RuntimeError):
    pass


def run(command: list[str | Path], *, env: dict[str, str] | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(item) for item in command],
        cwd=PACKAGE,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def apply_migration(
    psql: str,
    database_url: str,
    migration: Path,
    pass_number: int,
    env: dict[str, str] | None = None,
) -> None:
    checksum = hashlib.sha256(migration.read_bytes()).hexdigest()
    applied = run(
        [
            psql, "-X", "-v", "ON_ERROR_STOP=1",
            database_url, "-f", migration,
        ],
        env=env,
        timeout=120,
    )
    if applied.returncode:
        raise GateError(
            f"migration {migration.name} failed on idempotence pass {pass_number}: "
            f"{applied.stderr or applied.stdout}"
        )
    # Register exactly the row a real deployment writes. scripts/migrate.sh uses
    # name="${migration_file%.sql}" — the full stem, version prefix included —
    # and register_schema_migration() compares the stored name verbatim, so a
    # second, divergent copy of that rule here would mean this gate validates a
    # ledger no deployment ever produces.
    version = migration.stem.split("_", 1)[0]
    name = migration.stem
    registered = run(
        [
            psql, "-X", "-v", "ON_ERROR_STOP=1", database_url, "-c",
            f"SELECT register_schema_migration('{version}', '{name}', '{checksum}')",
        ],
        env=env,
        timeout=30,
    )
    if registered.returncode:
        raise GateError(
            f"migration {migration.name} registration failed on pass {pass_number}: "
            f"{registered.stderr or registered.stdout}"
        )


def pinned_postgres_major() -> int:
    """Major PostgreSQL version this package actually deploys.

    Read from check_env.py's POSTGRES_IMAGE so the pinned image stays the one
    source of truth; nothing here should carry a second copy of the version.
    """
    spec = importlib.util.spec_from_file_location("g4_check_env", PACKAGE / "scripts/check_env.py")
    if spec is None or spec.loader is None:
        raise GateError("cannot load scripts/check_env.py to read the pinned image")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    matched = re.match(r"postgres:(\d+)\.", module.POSTGRES_IMAGE)
    if not matched:
        raise GateError(f"cannot read a pinned PostgreSQL major from {module.POSTGRES_IMAGE!r}")
    return int(matched.group(1))


def require_pinned_postgres(initdb: str) -> None:
    """Refuse to run the gate against a PostgreSQL major the package never ships.

    The harness finds its tools on PATH, so on a host with several PostgreSQL
    installations it will silently pick whichever is linked. A gate that
    validates the migration set against a different major than the deployment
    runs is worse than no gate: it reports PASS while proving nothing about the
    version operators will actually use. Fail loudly and say how to fix it.
    """
    expected = pinned_postgres_major()
    probe = run([initdb, "--version"], timeout=30)
    rendered = (probe.stdout or "") + (probe.stderr or "")
    found = re.search(r"\b(\d+)\.\d+", rendered)
    if not found:
        raise GateError(f"cannot determine the local PostgreSQL version: {rendered.strip()!r}")
    actual = int(found.group(1))
    if actual != expected:
        raise GateError(
            f"local PostgreSQL major {actual} does not match the pinned deployment major "
            f"{expected} (POSTGRES_IMAGE in scripts/check_env.py). This gate would validate "
            f"the migration set against a version this package never deploys. Put the "
            f"PostgreSQL {expected} client tools first on PATH, for example "
            f"PATH=/usr/lib/postgresql/{expected}/bin:$PATH on Debian/Ubuntu, or "
            f"PATH=\"$(brew --prefix postgresql@{expected})/bin:$PATH\" on macOS."
        )


@contextmanager
def disposable_postgres() -> Iterator[str]:
    tools = {name: shutil.which(name) for name in ("initdb", "pg_ctl", "psql")}
    missing = [name for name, path in tools.items() if not path]
    if missing:
        raise GateError(f"required PostgreSQL tools are missing: {', '.join(missing)}")
    require_pinned_postgres(tools["initdb"])
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise GateError("refusing to initialize PostgreSQL as root")
    with tempfile.TemporaryDirectory(prefix="openclaw-v3-g4-") as directory:
        base = Path(directory)
        data = base / "data"
        socket = base / "socket"
        socket.mkdir()
        port = 45_000 + secrets.randbelow(15_000)
        # Pin the disposable cluster and its tool processes to the C locale:
        # --no-locale fixes the cluster catalog, and LC_ALL/LANG=C keep initdb
        # and the postmaster deterministic on hosts with unset or broken
        # LANG/LC_* (unset locale can abort server startup on macOS).
        cluster_env = {**os.environ, "LC_ALL": "C", "LANG": "C"}
        initialized = run(
            [
                tools["initdb"], "-A", "trust", "-U", "postgres",
                "--no-locale", "--encoding=UTF8", "-D", data,
            ],
            env=cluster_env,
            timeout=120,
        )
        if initialized.returncode:
            raise GateError(f"initdb failed: {initialized.stderr or initialized.stdout}")
        started = run(
            [
                tools["pg_ctl"], "-D", data, "-l", base / "postgres.log", "-o",
                f"-F -p {port} -k {socket} -c listen_addresses=''", "-w", "start",
            ],
            env=cluster_env,
            timeout=120,
        )
        if started.returncode:
            raise GateError(f"pg_ctl start failed: {started.stderr or started.stdout}")
        try:
            database_url = f"host={socket} port={port} dbname=postgres user=postgres"
            role = run(
                [
                    tools["psql"], "-X", "-v", "ON_ERROR_STOP=1", database_url, "-c",
                    "CREATE ROLE openclaw_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD 'g4-runtime-only'",
                ],
                env=cluster_env,
                timeout=30,
            )
            if role.returncode:
                raise GateError(f"runtime-role creation failed: {role.stderr or role.stdout}")
            migrations = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
            if not migrations:
                raise GateError("no numbered migrations found")
            for pass_number in (1, 2):
                for migration in migrations:
                    apply_migration(
                        tools["psql"], database_url, migration, pass_number,
                        env=cluster_env,
                    )
            yield database_url
        finally:
            run(
                [tools["pg_ctl"], "-D", data, "-m", "immediate", "-w", "stop"],
                env=cluster_env,
                timeout=30,
            )


def run_suite(name: str, pattern: str, env: dict[str, str], timeout: int) -> dict[str, object]:
    process = run(
        [sys.executable, "-m", "unittest", "discover", "-s", TESTS, "-p", pattern, "-v"],
        env=env,
        timeout=timeout,
    )
    rendered = process.stderr + process.stdout
    match = re.search(r"Ran\s+(\d+)\s+tests?", rendered)
    count = int(match.group(1)) if match else 0
    skipped = bool(re.search(r"skipped=|\.\.\. skipped", rendered, re.IGNORECASE))
    ok = process.returncode == 0 and count > 0 and not skipped
    return {
        "name": name,
        "ok": ok,
        "tests": count,
        "skipped": skipped,
        "error_tail": None if ok else rendered[-20_000:],
    }


def main() -> int:
    try:
        import psycopg  # noqa: F401
        import openpyxl  # noqa: F401
        import pypdf  # noqa: F401
        import yaml  # noqa: F401
    except ImportError as exc:
        print(json.dumps({"gate": "G4", "result": "FAIL", "errors": [f"locked dependency missing: {exc}"]}, indent=2))
        return 1

    checks: list[dict[str, object]] = []
    try:
        with disposable_postgres() as owner_url:
            runtime_url = re.sub(r"\buser=\S+", "user=openclaw_runtime", owner_url)
            migration_files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
            checksums = {
                path.name.split("_", 1)[0]: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in migration_files
            }
            # Keyed by the 3-digit prefix, so two migrations sharing one would
            # collapse into a single entry while both are still applied.
            if len(checksums) != len(migration_files):
                raise GateError(
                    "migration filenames must have unique 3-digit prefixes; "
                    f"{len(migration_files)} files produced {len(checksums)} keys"
                )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    # Force UTF-8 mode in the suite processes and every helper
                    # subprocess they spawn: with LANG/LC_* unset, macOS Python
                    # would otherwise default text I/O to ASCII and the gate
                    # would fail on encoding, not on the contract under test.
                    "PYTHONUTF8": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "VCOPS_HELPER": str(HELPER),
                    "DATABASE_URL": owner_url,
                    "G4_RUNTIME_DATABASE_URL": runtime_url,
                    "G4_MIGRATION_CHECKSUMS": json.dumps(checksums, sort_keys=True),
                }
            )
            checks.extend(
                [
                    run_suite("semantics", "test_semantics.py", environment, 120),
                    run_suite("document_security", "test_document_security.py", environment, 240),
                    run_suite("database_contract", "test_database_contract.py", environment, 240),
                    run_suite("helper_cli_database", "test_helper_cli_database.py", environment, 300),
                    run_suite("workflow_execution", "test_workflow_execution.py", environment, 300),
                    run_suite("research_intelligence", "test_research_intelligence.py", environment, 300),
                    run_suite("source_surveillance", "test_source_surveillance.py", environment, 300),
                ]
            )
    except Exception as exc:
        checks.append({"name": "disposable_postgres", "ok": False, "tests": 0, "skipped": False, "error_tail": str(exc)})
    passed = bool(checks) and all(check["ok"] for check in checks)
    report = {
        "gate": "G4",
        "result": "PASS" if passed else "FAIL",
        "migrations_applied_twice": passed,
        "checks": checks,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
