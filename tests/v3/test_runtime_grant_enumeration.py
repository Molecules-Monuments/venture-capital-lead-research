# SPDX-License-Identifier: 0BSD
"""The runtime grant matrix in DATA_MODEL.md is a closed-world claim.

`docs/DATA_MODEL.md` tells the reader the runtime role "holds `SELECT`/`INSERT`
but no `UPDATE` on all seven of those history tables", "receives no grant
outside that reviewed migration series", and is granted no `DELETE` or
`TRUNCATE` anywhere. Those are universal claims over 42 tables, and until the
fourteenth pass nothing enumerated that world: the G4 privilege test
spot-checks ten table/schema/database privileges, so a future migration
granting `UPDATE` or `DELETE` on a history table would leave the documentation
silently false.

This suite enumerates the world the same way the erasure-gap suite does, from
`docs/SCHEMA.sql` — the generated reference whose currency `verify_offline.py
--with-schema-reference` already proves. It reads the pg_dump-normalized
one-grant-per-line form rather than migrations/, where the grants wrap across
lines.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "docs/SCHEMA.sql").read_text(encoding="utf-8")
DATA_MODEL = (ROOT / "docs/DATA_MODEL.md").read_text(encoding="utf-8")

# The seven append-only history tables DATA_MODEL.md names: migration 004
# revokes UPDATE on the first five, 017 completes the contract for the last
# two, so the runtime must hold exactly SELECT+INSERT on each.
HISTORY_TABLES = {
    "facts",
    "fact_sources",
    "document_facts",
    "compiled_truth_facts",
    "evaluation_criteria",
    "contradiction_facts",
    "trajectory_points",
}


def append_only_tables() -> set[str]:
    """Tables whose UPDATE is refused by the shared append-only trigger.

    Derived from the generated schema rather than restated, so a migration
    that adds or drops such a trigger moves this world automatically. Matches
    every `prevent_*_mutation` guard, not one named function: `audit_events`
    uses `prevent_audit_mutation` FOR EACH STATEMENT, and an earlier version
    of this pattern skipped it — leaving a grant of UPDATE on the audit log
    invisible to the whole suite.
    """
    found = {
        table
        for _name, events, table in re.findall(
            r"^CREATE TRIGGER (\w+) BEFORE ([A-Z OR]+?) ON public\.(\w+)\s+"
            r"FOR EACH (?:ROW|STATEMENT) EXECUTE FUNCTION public\.prevent_\w+_mutation\(\);",
            SCHEMA,
            re.M,
        )
        if "UPDATE" in events
    }
    if len(found) < 19:
        raise AssertionError(
            f"only {len(found)} append-only UPDATE triggers parsed out of "
            "docs/SCHEMA.sql — the trigger pattern has rotted, so this check "
            "would enumerate a partial world"
        )
    return found


def runtime_grants() -> dict[str, frozenset[str]]:
    granted = re.findall(
        r"^GRANT (\S+) ON TABLE public\.(\w+) TO openclaw_runtime;", SCHEMA, re.M
    )
    tables = re.findall(r"^CREATE TABLE public\.(\w+) \(", SCHEMA, re.M)
    if len(granted) != len(tables):
        raise AssertionError(
            f"{len(tables)} tables but {len(granted)} runtime grant lines — the "
            "pg_dump grant form no longer fits docs/SCHEMA.sql, so this suite "
            "would enumerate an empty or partial world"
        )
    return {table: frozenset(privileges.split(",")) for privileges, table in granted}


class RuntimeGrantEnumerationTests(unittest.TestCase):
    def setUp(self):
        self.grants = runtime_grants()

    def test_every_table_carries_exactly_one_reviewed_grant(self):
        self.assertGreaterEqual(len(self.grants), 40, "SCHEMA.sql grant parse has rotted")
        tables = set(re.findall(r"^CREATE TABLE public\.(\w+) \(", SCHEMA, re.M))
        self.assertEqual(
            set(self.grants), tables,
            "every table must carry exactly one runtime grant line; a new "
            "migration must grant consciously and update docs/DATA_MODEL.md",
        )
        allowed = {
            frozenset({"SELECT"}),
            frozenset({"SELECT", "INSERT"}),
            frozenset({"SELECT", "INSERT", "UPDATE"}),
        }
        unexpected = sorted(
            f"{table}={sorted(privileges)}"
            for table, privileges in self.grants.items()
            if privileges not in allowed
        )
        self.assertEqual(
            unexpected, [],
            "the runtime role holds a privilege shape docs/DATA_MODEL.md does "
            f"not describe: {unexpected}",
        )
        # A shape check alone is table-agnostic: it would let a read-only
        # table gain INSERT, or an append-only one gain UPDATE, and stay
        # green. Bind the two families to their own sources of truth.
        self.assertEqual(
            sorted(t for t, p in self.grants.items() if p == frozenset({"SELECT"})),
            ["fact_promotion_policy", "notification_attempts", "schema_migrations"],
            "the read-only table set moved; docs/DATA_MODEL.md describes these "
            "three as SELECT-only for the runtime role",
        )
        offenders = sorted(
            table for table in append_only_tables() if "UPDATE" in self.grants.get(table, ())
        )
        self.assertEqual(
            offenders, [],
            "these tables carry an append-only UPDATE trigger yet grant the "
            f"runtime UPDATE, so the grant contradicts the trigger: {offenders}",
        )

    def test_no_security_definer_function_relies_on_default_privileges(self):
        """`ALTER DEFAULT PRIVILEGES … REVOKE ALL ON FUNCTIONS` is a no-op.

        migration 002 ends with that statement and the comment "A later
        migration is not implicitly exposed to the runtime. Its installer must
        add deliberate grants after review." For TABLES and SEQUENCES that
        holds. For FUNCTIONS it does not: PostgreSQL's `EXECUTE TO PUBLIC` on
        a new function is a built-in default, not a `pg_default_acl` entry, so
        revoking from an empty default ACL changes nothing and every function
        created after 002 carries PUBLIC EXECUTE.

        Nothing is exposed today — the 21 unGRANTed functions are trigger
        functions, which need trigger context, and `register_schema_migration`
        is SECURITY INVOKER, so the runtime's SELECT-only grant on
        `schema_migrations` still refuses its INSERT. The forward risk is a
        future SECURITY DEFINER function added without an explicit grant,
        which would run as owner and be callable by the runtime through that
        PUBLIC default. Pin the invariant instead of relying on the statement
        that does not enforce it.
        """
        blocks = re.split(r"(?=^CREATE FUNCTION public\.)", SCHEMA, flags=re.M)
        definers = []
        for block in blocks:
            match = re.match(r"CREATE FUNCTION public\.(\w+)\(", block)
            if match and "SECURITY DEFINER" in block[:2000]:
                definers.append(match.group(1))
        self.assertGreaterEqual(
            len(definers), 12, "the SECURITY DEFINER function scan has rotted"
        )
        granted = set(
            re.findall(r"GRANT (?:ALL|EXECUTE) ON FUNCTION public\.(\w+)", SCHEMA)
        )
        ungranted = sorted(set(definers) - granted)
        self.assertEqual(
            ungranted, [],
            "these SECURITY DEFINER functions carry no explicit grant, so the "
            "only thing standing between the runtime and owner-privileged "
            f"execution is PostgreSQL's PUBLIC default: {ungranted}. Migration "
            "002's ALTER DEFAULT PRIVILEGES on FUNCTIONS does not revoke it. "
            "Add an explicit REVOKE/GRANT pair in the migration that creates "
            "the function.",
        )
        # The GRANT half alone is not the invariant docs/DATA_MODEL.md states.
        # A definer that is GRANTed to openclaw_runtime but never REVOKEd from
        # PUBLIC is still reachable by every role, because the PUBLIC EXECUTE
        # default described above is what the migration failed to withhold.
        # Both halves or the pair is not a pair.
        revoked = set(
            re.findall(r"REVOKE ALL ON FUNCTION public\.(\w+)", SCHEMA)
        )
        unrevoked = sorted(set(definers) - revoked)
        self.assertEqual(
            unrevoked, [],
            "these SECURITY DEFINER functions carry no explicit REVOKE ALL … "
            "FROM PUBLIC, so PostgreSQL's built-in PUBLIC EXECUTE default "
            f"still stands and any role can call them: {unrevoked}. Add the "
            "REVOKE half in the migration that creates the function.",
        )

    def test_no_table_grants_delete_or_truncate(self):
        """docs/DATA_MODEL.md states the runtime "grants no `DELETE`, `TRUNCATE`"."""
        offenders = sorted(
            table
            for table, privileges in self.grants.items()
            if privileges & {"DELETE", "TRUNCATE"}
        )
        self.assertEqual(
            offenders, [],
            f"docs/DATA_MODEL.md says the runtime holds no DELETE or TRUNCATE; "
            f"these tables now grant one: {offenders}",
        )
        self.assertIn("grants no `DELETE`, `TRUNCATE`", DATA_MODEL)

    def test_history_tables_are_select_insert_only(self):
        for table in sorted(HISTORY_TABLES):
            with self.subTest(table=table):
                self.assertEqual(
                    self.grants.get(table), frozenset({"SELECT", "INSERT"}),
                    f"docs/DATA_MODEL.md states the runtime holds SELECT/INSERT "
                    f"but no UPDATE on {table}",
                )
        # The prose names these seven as a closed set; keep it that way.
        self.assertIn("all seven of those history tables", DATA_MODEL)
        for table in sorted(HISTORY_TABLES):
            self.assertIn(f"`{table}`", DATA_MODEL)


if __name__ == "__main__":
    unittest.main()
