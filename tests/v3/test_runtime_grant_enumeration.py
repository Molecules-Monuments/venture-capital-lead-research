# SPDX-License-Identifier: Apache-2.0
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

# The append-only history tables, DERIVED from the same statements
# DATA_MODEL.md cites rather than copied from its prose. A hardcoded list is
# a second source of truth: an eighth table revoked in a later migration
# would pass a suite whose whole purpose is to enumerate them, and the
# document's "all seven" would go stale with nothing to catch it.
def _history_tables() -> set[str]:
    revoked: set[str] = set()
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        for match in re.finditer(
            r"REVOKE\s+UPDATE\s+ON\s+(?:TABLE\s+)?([\w\s,.]+?)\s+FROM\s+openclaw_runtime",
            path.read_text(encoding="utf-8"), re.S | re.I,
        ):
            for name in match.group(1).split(","):
                cleaned = name.strip().split(".")[-1]
                if cleaned:
                    revoked.add(cleaned)
    return revoked


HISTORY_TABLES = _history_tables()

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen",
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
        # Both halves are anchored to the grantee their failure messages name.
        # An unanchored `GRANT … ON FUNCTION public\.(\w+)` would also count a
        # grant to some other role as "the runtime may call it", and an
        # unanchored REVOKE would count `REVOKE ALL … FROM <owner>` — a line
        # pg_dump does emit — as "PUBLIC no longer holds EXECUTE".
        granted = set(
            re.findall(
                r"^GRANT (?:ALL|EXECUTE) ON FUNCTION public\.(\w+)\(.*?\) "
                r"TO openclaw_runtime;$",
                SCHEMA,
                re.M,
            )
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
            re.findall(
                r"^REVOKE ALL ON FUNCTION public\.(\w+)\(.*?\) FROM PUBLIC;$",
                SCHEMA,
                re.M,
            )
        )
        unrevoked = sorted(set(definers) - revoked)
        self.assertEqual(
            unrevoked, [],
            "these SECURITY DEFINER functions carry no explicit REVOKE ALL … "
            "FROM PUBLIC, so PostgreSQL's built-in PUBLIC EXECUTE default "
            f"still stands and any role can call them: {unrevoked}. Add the "
            "REVOKE half in the migration that creates the function.",
        )

    def test_data_model_security_definer_counts_match_the_schema(self):
        """DATA_MODEL.md's SECURITY DEFINER counts must equal what the schema yields.

        Compares three documented number-words against sets derived here: `the
        twelve non-trigger `SECURITY DEFINER` functions`, and its `eight created
        in `001`` / `four created after `002`` split, against a scan of
        docs/SCHEMA.sql and of the migrations that create each one. All three were
        unbound, so a thirteenth definer left the document asserting a number
        nothing measured. The history-table count is bound by
        test_history_tables_are_select_insert_only, which derives the same word.
        """
        words = NUMBER_WORDS
        document = DATA_MODEL

        blocks = re.split(r"(?=^CREATE FUNCTION public\.)", SCHEMA, flags=re.M)
        definers = [
            match.group(1)
            for block in blocks
            if (match := re.match(r"CREATE FUNCTION public\.(\w+)\(", block))
            and "SECURITY DEFINER" in block[:2000]
        ]
        self.assertTrue(
            f"the {words[len(definers)]} non-trigger `SECURITY DEFINER` functions"
            in document,
            f"docs/DATA_MODEL.md does not state {len(definers)} non-trigger "
            f"SECURITY DEFINER functions; docs/SCHEMA.sql defines {sorted(definers)}",
        )

        # The document also splits that total by the migration that created each
        # one. Derive the split so the two halves cannot drift apart from the sum.
        created_in_001 = set()
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            body = path.read_text(encoding="utf-8")
            for block in re.split(r"(?=CREATE (?:OR REPLACE )?FUNCTION )", body):
                match = re.match(r"CREATE (?:OR REPLACE )?FUNCTION\s+(?:public\.)?(\w+)\(", block)
                if match and "SECURITY DEFINER" in block[:2000] and path.name.startswith("001"):
                    created_in_001.add(match.group(1))
        early = len(created_in_001 & set(definers))
        late = len(definers) - early
        self.assertTrue(
            f"The {words[early]} created in `001`" in document,
            f"docs/DATA_MODEL.md does not say {words[early]} SECURITY DEFINER "
            f"functions were created in 001; the migrations define {early}",
        )
        self.assertTrue(
            f"The {words[late]} created after `002`" in document,
            f"docs/DATA_MODEL.md does not say {words[late]} SECURITY DEFINER "
            f"functions were created after 002; the migrations define {late}",
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
        # Everything above reads `runtime_grants()`, which filters on
        # `TO openclaw_runtime`, so a grant to a second grantee is invisible to
        # it — PUBLIC most of all: PUBLIC privileges are held by every role
        # directly rather than through membership, so `NOINHERIT` on
        # `openclaw_runtime` (migrations/000_roles.sh:60) does not withhold
        # them. Enumerate the grantee of every GRANT line so a second one has
        # to be reviewed into this set before the gate goes green again.
        grant_lines = re.findall(r"^GRANT .+;$", SCHEMA, re.M)
        grantees = re.findall(
            r"^GRANT .+? ON (?:TABLE|SEQUENCE|FUNCTION|SCHEMA) .+ TO (\S+);$",
            SCHEMA,
            re.M,
        )
        self.assertEqual(
            len(grantees), len(grant_lines),
            f"{len(grant_lines)} GRANT lines in docs/SCHEMA.sql but only "
            f"{len(grantees)} name a TABLE/SEQUENCE/FUNCTION/SCHEMA target with "
            "a parsable grantee, so this grantee scan would enumerate a partial "
            "world",
        )
        self.assertEqual(
            sorted(set(grantees)), ["openclaw_runtime"],
            "docs/SCHEMA.sql grants a privilege to a grantee other than "
            f"openclaw_runtime: {sorted(set(grantees) - {'openclaw_runtime'})}. "
            "Every other check in this suite reads only the openclaw_runtime "
            "grant lines, so such a grant would be invisible to them.",
        )
        # `GRANT …` is one of two spellings pg_dump emits for a privilege. The
        # other is `ALTER DEFAULT PRIVILEGES … GRANT … TO <role>`, which the
        # scan above cannot see because it does not begin with GRANT. Rather
        # than widen the detector, pin the world: docs/SCHEMA.sql carries no
        # such statement today (measured), because pg_dump emits one only when
        # `pg_default_acl` holds a row — and migration 002's three
        # `ALTER DEFAULT PRIVILEGES … REVOKE ALL … FROM PUBLIC` statements
        # create none, which is exactly why
        # `test_no_security_definer_function_relies_on_default_privileges`
        # above exists. A future migration that sets a default privilege lands
        # here verbatim and has to be reviewed in.
        self.assertEqual(
            re.findall(r"^ALTER DEFAULT PRIVILEGES.*$", SCHEMA, re.M), [],
            "docs/SCHEMA.sql now carries a default-privilege statement. pg_dump "
            "emits one only when the default ACL is non-default, and neither the "
            "grantee scan above nor any other check in this suite reads that "
            "spelling, so it must be reviewed into this suite before the gate "
            "goes green.",
        )

    def test_history_tables_are_select_insert_only(self):
        for table in sorted(HISTORY_TABLES):
            with self.subTest(table=table):
                self.assertEqual(
                    self.grants.get(table), frozenset({"SELECT", "INSERT"}),
                    f"docs/DATA_MODEL.md states the runtime holds SELECT/INSERT "
                    f"but no UPDATE on {table}",
                )
        # The prose names these as a closed set; keep it that way. The count
        # word is DERIVED, not pinned: a hardcoded "seven" here would fail a
        # document correctly updated to "eight" while passing a stale one.
        expected = f"all {NUMBER_WORDS[len(HISTORY_TABLES)]} of those history tables"
        self.assertTrue(
            expected in DATA_MODEL,
            f"docs/DATA_MODEL.md does not contain {expected!r}; the REVOKE "
            f"UPDATE statements yield {len(HISTORY_TABLES)}: {sorted(HISTORY_TABLES)}",
        )
        for table in sorted(HISTORY_TABLES):
            self.assertTrue(
                f"`{table}`" in DATA_MODEL,
                f"docs/DATA_MODEL.md never names the append-only table {table}",
            )


if __name__ == "__main__":
    unittest.main()
