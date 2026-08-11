# SPDX-License-Identifier: 0BSD
"""The erasure-gap enumeration in data_retention.md is a closed-world claim.

`workspaces/vc-chief/vc/data_retention.md` tells the operator which stores
`vcops data-erase-lead` does **not** reach, and instructs them to rehearse
out-of-band steps against that list. A list like that is only trustworthy if
it is complete — and completeness cannot be spot-checked, only enumerated.
The thirteenth audit pass found the list missing its largest members after
twelve passes had verified every entry it *did* carry.

This suite enumerates the world: every table in docs/SCHEMA.sql must carry
exactly one disposition below, and every disposition that involves subject
data must be named in data_retention.md. A table added to docs/SCHEMA.sql
fails here until someone consciously categorizes it — and, if it can hold
subject data, names it in the operator-facing list. SCHEMA.sql currency
itself is proven by verify_offline's --with-schema-reference opt-in, so a
migration change must regenerate the schema reference for this net to close.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (ROOT / "docs/SCHEMA.sql").read_text(encoding="utf-8")
RETENTION = (ROOT / "workspaces/vc-chief/vc/data_retention.md").read_text(encoding="utf-8")

# What the erasure transaction actually writes (migration 017's
# consume_approval_and_erase_lead plus the consume_approval it calls): fact
# tombstones, leads.status, two audit_events rows (approval consumption and
# the erasure), and the consumed approvals row's bookkeeping columns. The
# approvals table is dispositioned under SUBJECT_BEARING because its value
# columns (scope, action_preview, decision_note) are never erased.
TOUCHED = {
    "facts",
    "leads",
    "audit_events",
}

# Stores that can hold a subject's data verbatim and that the erasure function
# does not reach. Each must be named in data_retention.md's enforcement
# section so the operator's out-of-band procedure covers it.
SUBJECT_BEARING = {
    "workflow_requests",            # request_payload: the canonical intake payload
    "compiled_truth",               # fact_history + current_view snapshots
    "memos",                        # rendered memo body + content_uri
    "memo_citations",
    "lead_artifacts",
    "evidence_artifacts",
    "document_extractions",
    "sources",                      # title/canonical_uri/publisher/metadata of uploads
    "evaluations",
    "evaluation_criteria",          # per-criterion rationale text
    "fact_sources",
    "contradictions",               # explanation text
    "trajectory_events",            # calculation jsonb
    "orchestration_audit",          # payload jsonb
    "notification_outbox",          # subject + payload
    "workflow_runs",                # result jsonb, error/cancellation text
    "proposals",                    # title/summary/content, lead-keyed
    "approvals",                    # scope/action_preview/decision_note
    "entity_resolution_runs",       # identity_query holds the submitted identity
    "entity_resolution_decisions",  # reasons + candidate lists
    "entity_resolution_consumptions",
    "companies",                    # the company identity rows themselves
    "company_domains",
    "company_aliases",
    "company_external_ids",
    # Child linkage/locator rows that follow their listed parents:
    "compiled_truth_facts",
    "contradiction_facts",
    "trajectory_points",
    "document_facts",
    "notification_attempts",
}

# Channel-user personal data: a separate lane scoped to channel principals,
# not leads. Its subject-request path is the preference forget workflow —
# which deletes nothing: it writes append-only marker/audit rows and NULLs
# only the current user_preferences value, while all six tables survive until
# an owner-run out-of-band step (four by append-only trigger; channel_principals
# and user_preferences by holding no DELETE grant for the runtime role, though
# the owner can still remove their rows). The retention document must name the
# lane, the workflow, and that caveat — all three are asserted below.
USER_LANE = {
    "channel_principals",
    "user_preferences",
    "preference_observations",
    "preference_forget_markers",
    "user_preference_audit",
    "trusted_context_uses",
}

# Operational registries with no subject data: the migration ledger, the
# reviewed fact-promotion policy row, and the operator-managed watched-source
# registry (its rows describe the operator's sources, not any lead).
OPERATIONAL = {
    "schema_migrations",
    "fact_promotion_policy",
    "signal_sources",
}


def schema_tables() -> set[str]:
    names = re.findall(r"^CREATE TABLE public\.([a-z0-9_]+) \(", SCHEMA, re.MULTILINE)
    statements = re.findall(r"^CREATE TABLE ", SCHEMA, re.MULTILINE)
    if len(names) != len(statements):
        raise AssertionError(
            f"{len(statements)} CREATE TABLE statements but only {len(names)} "
            "parseable names — the name pattern no longer fits docs/SCHEMA.sql"
        )
    return set(names)


class ErasureGapEnumerationTests(unittest.TestCase):
    def test_every_schema_table_has_exactly_one_disposition(self):
        world = schema_tables()
        self.assertGreaterEqual(len(world), 40, "SCHEMA.sql parse has rotted")
        categorized = TOUCHED | SUBJECT_BEARING | USER_LANE | OPERATIONAL
        self.assertEqual(
            len(categorized),
            len(TOUCHED) + len(SUBJECT_BEARING) + len(USER_LANE) + len(OPERATIONAL),
            "a table appears in more than one disposition set",
        )
        self.assertEqual(
            world, categorized,
            "docs/SCHEMA.sql and the disposition sets disagree. A new table must "
            "be consciously categorized here — and, if it can hold subject data, "
            "added to data_retention.md's erasure-gap list. A removed table must "
            "leave both.",
        )

    def test_every_subject_bearing_table_is_named_in_the_retention_doc(self):
        # Only the enforcement section counts, and only a deliberate backticked
        # naming: a table name used as ordinary prose elsewhere in the document
        # must not satisfy the completeness claim. Bound the slice at the next
        # same-level heading so a section appended after Enforcement cannot
        # satisfy the naming requirement (level-3 subsections stay in scope).
        enforcement = RETENTION.split("## Enforcement", 1)[1].split("\n## ", 1)[0]
        missing = sorted(
            name
            for name in TOUCHED | SUBJECT_BEARING | USER_LANE
            if not re.search(rf"`{name}\b", enforcement)
        )
        self.assertEqual(
            missing, [],
            "data_retention.md's enforcement section no longer names these "
            f"stores: {missing}. The erasure-gap list is a completeness claim; "
            "extend it rather than weakening this test.",
        )
        # Table names alone do not carry the user lane's correction: the
        # document must keep naming the workflow and keep saying it deletes
        # nothing, or the wording can regress with this gate green.
        self.assertIn(
            "`preference-forget`", enforcement,
            "the enforcement section no longer names the user lane's workflow",
        )
        self.assertRegex(
            enforcement, r"deletes nothing",
            "the enforcement section no longer states that the user-lane "
            "workflow deletes nothing — the correction it records can regress "
            "silently without this assertion",
        )


if __name__ == "__main__":
    unittest.main()
