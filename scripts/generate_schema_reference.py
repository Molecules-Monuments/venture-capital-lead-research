#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate (or verify) docs/SCHEMA.sql from the migration set.

docs/SCHEMA.sql is documentation, not a migration, but it is published as a
single-file view of the schema and is therefore only useful if it is provably
the schema the migrations actually produce. This script is how it is produced:
it applies every numbered forward migration to a throwaway cluster (reusing
run_g4.py's disposable-Postgres harness, which creates an openclaw_runtime
role inline for the grants the migrations reference — 000_roles.sh itself is a
deployment-lifecycle script and is not run here) and dumps the result.

Two things are stripped from the raw pg_dump output so that regenerating on an
unchanged tree is byte-stable and reviewable:

  * `\\restrict` / `\\unrestrict` — psql meta-commands carrying a per-run random
    token. They are not schema, and leaving them in would make every run differ.
  * `-- Dumped from database version ...` / `-- Dumped by pg_dump version ...`
    — the generating host's build, which says nothing about the schema.

Everything else is verbatim pg_dump output.

Use the PostgreSQL version this package pins for its container
(postgres:17.10-bookworm). A different major version emits different dump
directives and will produce a spurious diff; `--check` will tell you.

  python3 -B scripts/generate_schema_reference.py            # rewrite
  python3 -B scripts/generate_schema_reference.py --check    # verify only
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# load_harness() loads scripts/run_g4.py (and through it scripts/check_env.py)
# by path, which would byte-compile both into scripts/__pycache__ and make
# `verify_release.py --pristine` report undeclared files. Suppress it so this
# generator stays safe to run even when someone omits `-B`.
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent.parent
TARGET = PACKAGE / "docs/SCHEMA.sql"
HEADER = """-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 3.0 — consolidated schema reference (DOCUMENTATION)
--
-- This file is NOT a migration and is applied by nothing: migrate.sh only reads
-- migrations/NNN_*.sql, and this file lives under docs/. It is a schema-only
-- snapshot of the database after the {migration_span} are
-- applied in order (against a cluster with the openclaw_runtime role the
-- migrations' grants reference), provided as a single-file view so the whole
-- schema can be read and audited in one place.
--
-- The authoritative, reviewed source of the schema is the migrations/ directory.
-- This snapshot is generated from it and can lag if the migrations change; it is
-- documentation, not the source of truth.
--
-- Ownership note: objects are dumped with --no-owner. In a real deployment the
-- owner is openclaw_owner and the least-privilege application role is
-- openclaw_runtime (see migrations/000_roles.sh and docs/DATA_MODEL.md); the
-- GRANT/REVOKE statements below show that runtime privilege model.
--
-- GENERATED FILE — do not hand-edit. Regenerate from the package directory with
-- PostgreSQL 17 client tools on PATH:
--   python3 -B scripts/generate_schema_reference.py
-- Verify without rewriting:
--   python3 -B scripts/generate_schema_reference.py --check
--
"""
# psql meta-commands whose payload is a per-run random token.
RESTRICT = re.compile(r"^\\(un)?restrict .*\n", re.MULTILINE)
# Host build provenance, not schema.
DUMP_VERSION = re.compile(r"^-- Dumped (from database|by pg_dump) version.*\n", re.MULTILINE)


def load_harness():
    spec = importlib.util.spec_from_file_location("run_g4", PACKAGE / "scripts/run_g4.py")
    # spec_from_file_location returns None for an unreadable or non-module path,
    # and a spec built without a loader has loader=None. Assert both rather than
    # dereferencing them: a missing run_g4.py should say so here, not surface as
    # an AttributeError on None two lines later.
    if spec is None or spec.loader is None:
        raise SystemExit("scripts/run_g4.py could not be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render() -> str:
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        raise SystemExit("pg_dump is not on PATH; install the PostgreSQL 17 client tools")
    harness = load_harness()
    with harness.disposable_postgres() as database_url:
        dumped = subprocess.run(
            [pg_dump, "--schema-only", "--no-owner", database_url],
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
            capture_output=True,
            text=True,
            timeout=300,
        )
    if dumped.returncode:
        raise SystemExit(f"pg_dump failed: {dumped.stderr}")
    body = DUMP_VERSION.sub("", RESTRICT.sub("", dumped.stdout))
    # Derived, not hardcoded: a generated file must not carry a migration count
    # that silently goes stale the moment the next migration lands.
    stems = sorted(
        path.name.split("_", 1)[0]
        for path in (PACKAGE / "migrations").glob("[0-9][0-9][0-9]_*.sql")
    )
    span = f"{len(stems)} forward migrations {stems[0]}-{stems[-1]}" if stems else "no forward migrations"
    return HEADER.format(migration_span=span) + body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    expected = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != expected:
            print(
                "docs/SCHEMA.sql does not match the schema the migrations produce; "
                "regenerate it with `python3 -B scripts/generate_schema_reference.py` "
                "using PostgreSQL 17 client tools",
                file=sys.stderr,
            )
            return 1
        print(f"Schema reference verified: {len(expected.splitlines())} lines")
        return 0
    TARGET.write_text(expected, encoding="utf-8")
    print(f"Schema reference written: {len(expected.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
