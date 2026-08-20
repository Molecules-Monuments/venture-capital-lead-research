# SPDX-License-Identifier: Apache-2.0
"""Execute the restored source-surveillance workflows end-to-end against the live DB.

Drives the real source-watch / source-scan / source-unwatch .lobster files so the
watchlist registry, the cadence-gated due computation, and the atomic per-cycle
scan claim are proven — the runtime that Version 3.0 was missing. The research
and persistence that follow a scan reuse the already-tested outbound-scout /
evidence-record workflows and are covered by test_research_intelligence.py.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg

from test_workflow_execution import LobsterStepRunner

OWNER_DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_URL = os.environ.get("G4_RUNTIME_DATABASE_URL", "")
HELPER = os.environ.get("VCOPS_HELPER", "")
PYTHON = os.environ.get("G4_PYTHON", sys.executable)


class SourceSurveillanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DATABASE_URL or not OWNER_DATABASE_URL:
            raise AssertionError("G4 database URLs are required; database tests may not skip")
        cls.prefix = "g4ss-" + uuid.uuid4().hex[:10]
        cls.tmp = tempfile.TemporaryDirectory(prefix="openclaw-g4-surveillance-")
        base = Path(cls.tmp.name)
        roots = {name: base / name for name in ("inbox", "media", "quarantine", "state")}
        for path in roots.values():
            path.mkdir()
        cls.env_base = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "DATABASE_URL": DATABASE_URL,
            "VCOPS_WORKFLOW_MODE": "1",
            "VCOPS_INBOX_ROOT": str(roots["inbox"]),
            "VCOPS_MEDIA_ROOT": str(roots["media"]),
            "VCOPS_QUARANTINE_ROOT": str(roots["quarantine"]),
            "VCOPS_STATE_ROOT": str(roots["state"]),
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def query(cls, sql, parameters=(), *, owner=False):
        with psycopg.connect(OWNER_DATABASE_URL if owner else DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(sql, parameters)
            row = cur.fetchone() if cur.description is not None else None
            return row[0] if row else None

    def execute(self, workflow_file, args):
        return LobsterStepRunner(workflow_file, args, self.env_base).run()

    @classmethod
    def invoke(cls, arguments, expect_ok=True, env_extra=None):
        env = os.environ.copy()
        env.update({k: v for k, v in cls.env_base.items() if k != "VCOPS_WORKFLOW_MODE"})
        if env_extra:
            env.update(env_extra)
        process = subprocess.run(
            [PYTHON, HELPER, *arguments, "--json"], env=env, text=True, capture_output=True, timeout=30,
        )
        payload = json.loads(process.stdout)
        if expect_ok and (process.returncode != 0 or not payload.get("ok")):
            raise AssertionError(f"helper failed: args={arguments} payload={payload}")
        if not expect_ok and process.returncode == 0:
            raise AssertionError(f"helper unexpectedly succeeded: args={arguments} payload={payload}")
        return payload

    def uri(self, tag):
        return f"https://{tag}-{self.prefix}.invalid/feed"

    def test_01_watch_registers_and_rewatch_upserts(self):
        state = self.execute("source-watch.lobster", {
            "idempotency_key": self.prefix + "-watch",
            "source_name": "G4SS TechNews",
            "source_uri": self.uri("news"),
            "source_class": "news_rss",
            "cadence": "daily",
            "thesis_relevance": "AI infrastructure launches",
            "expected_signal": "funding and launch signals",
        })
        self.assertEqual(state["workflow_start"]["json"]["workflow_run"]["status"], "queued")
        source = state["source_watch"]["json"]["source"]
        self.assertTrue(source["enabled"])
        self.assertEqual(source["cadence"], "daily")
        # Through the real workflow the lane sees back only what it submitted:
        # no row id, classification, owner or scan history. The surrogate id
        # would otherwise let a caller tell a fresh registration from a
        # re-watch of a source it is not cleared to know about.
        self.assertEqual(
            sorted(source),
            ["cadence", "canonical_uri", "enabled", "source_class", "source_name"],
        )
        self.assertEqual(
            self.query("SELECT count(*) FROM signal_sources WHERE canonical_uri=%s", (self.uri("news"),)), 1,
        )
        # Re-watch the same URI with a new cadence upserts in place (no duplicate).
        state = self.execute("source-watch.lobster", {
            "idempotency_key": self.prefix + "-rewatch",
            "source_name": "G4SS TechNews",
            "source_uri": self.uri("news"),
            "source_class": "news_rss",
            "cadence": "weekly",
            "thesis_relevance": "AI infrastructure launches",
            "expected_signal": "funding and launch signals",
        })
        self.assertEqual(state["source_watch"]["json"]["source"]["cadence"], "weekly")
        self.assertEqual(
            self.query("SELECT count(*) FROM signal_sources WHERE canonical_uri=%s", (self.uri("news"),)), 1,
        )

    def test_01b_watch_accepts_a_meaningful_uppercase_path(self):
        """A URL path is case-sensitive, so an uppercase segment is ordinary.

        The registry's normalization rule lowercases only scheme and authority
        (matching normalize_uri and sources.canonical_uri); an earlier
        whole-URI-lowercase rule rejected every such URL at the constraint.
        """
        cased = f"https://Cased-{self.prefix}.INVALID/Feed/Latest"
        state = self.execute("source-watch.lobster", {
            "idempotency_key": self.prefix + "-cased",
            "source_name": "G4SS Cased",
            "source_uri": cased,
            "source_class": "news_rss",
            "cadence": "daily",
            "thesis_relevance": "case handling",
            "expected_signal": "launch signals",
        })
        stored = state["source_watch"]["json"]["source"]["canonical_uri"]
        self.assertEqual(f"https://cased-{self.prefix}.invalid/Feed/Latest", stored)
        self.assertEqual(
            self.query("SELECT count(*) FROM signal_sources WHERE canonical_uri=%s", (stored,)), 1,
        )

    def test_02_scan_claims_due_sources_and_cadence_gates_reclaim(self):
        # A second daily source is due now.
        self.execute("source-watch.lobster", {
            "idempotency_key": self.prefix + "-watch-blog",
            "source_name": "G4SS Blog",
            "source_uri": self.uri("blog"),
            "source_class": "company_blog",
            "cadence": "daily",
            "thesis_relevance": "product depth",
            "expected_signal": "launch posts",
        })
        # Both never-scanned sources are due on the first scan (NULL last_scanned_at).
        state = self.execute("source-scan.lobster", {"idempotency_key": self.prefix + "-scan1", "limit": "50"})
        claimed = {s["canonical_uri"] for s in state["source_scan"]["json"]["worklist"]}
        self.assertIn(self.uri("blog"), claimed)
        self.assertIn(self.uri("news"), claimed)
        # The claim stamps 'claimed' (outcome pending), never 'succeeded': the
        # downstream screening has not run at claim time.
        self.assertEqual(
            self.query(
                "SELECT last_scan_status FROM signal_sources WHERE canonical_uri=%s", (self.uri("blog"),),
            ),
            "claimed",
        )
        # Immediate re-scan does not re-claim a source scanned this cycle (cadence gate).
        state = self.execute("source-scan.lobster", {"idempotency_key": self.prefix + "-scan2", "limit": "50"})
        reclaimed = {s["canonical_uri"] for s in state["source_scan"]["json"]["worklist"]}
        self.assertNotIn(self.uri("blog"), reclaimed)
        self.assertNotIn(self.uri("news"), reclaimed)

    def test_03_due_again_after_cadence_elapses(self):
        self.query(
            "UPDATE signal_sources SET last_scanned_at = clock_timestamp() - interval '2 days' "
            "WHERE canonical_uri=%s",
            (self.uri("blog"),), owner=True,
        )
        state = self.execute("source-scan.lobster", {"idempotency_key": self.prefix + "-scan3", "limit": "50"})
        claimed = {s["canonical_uri"] for s in state["source_scan"]["json"]["worklist"]}
        self.assertIn(self.uri("blog"), claimed)

    def test_04_unwatch_removes_from_scan_worklist(self):
        state = self.execute("source-unwatch.lobster", {
            "idempotency_key": self.prefix + "-unwatch", "source_uri": self.uri("blog"),
        })
        self.assertFalse(state["source_unwatch"]["json"]["source"]["enabled"])
        self.query(
            "UPDATE signal_sources SET last_scanned_at = clock_timestamp() - interval '2 days' "
            "WHERE canonical_uri=%s",
            (self.uri("blog"),), owner=True,
        )
        state = self.execute("source-scan.lobster", {"idempotency_key": self.prefix + "-scan4", "limit": "50"})
        claimed = {s["canonical_uri"] for s in state["source_scan"]["json"]["worklist"]}
        self.assertNotIn(self.uri("blog"), claimed)

    def test_05_source_list_is_confidentiality_gated_for_model_lanes(self):
        self.execute("source-watch.lobster", {
            "idempotency_key": self.prefix + "-watch-restricted",
            "source_name": "G4SS Restricted",
            "source_uri": self.uri("restricted"),
            "source_class": "other",
            "cadence": "monthly",
            "thesis_relevance": "confidential source",
            "expected_signal": "n/a",
        })
        self.query(
            "UPDATE signal_sources SET confidentiality='restricted' WHERE canonical_uri=%s",
            (self.uri("restricted"),), owner=True,
        )
        model_view = self.invoke(["source-list"], env_extra={"VCOPS_AGENT_MODE": "1"})
        uris = {s["canonical_uri"] for s in model_view["sources"]}
        self.assertNotIn(self.uri("restricted"), uris)
        self.assertIn(self.uri("news"), uris)
        operator_view = self.invoke(["source-list"])
        self.assertIn(self.uri("restricted"), {s["canonical_uri"] for s in operator_view["sources"]})

    def test_09_is_due_evaluates_cadence_and_fails_loud_on_unknown(self):
        # A never-scanned source is always due; the cadence CHECK keeps stored
        # rows in {daily,weekly,monthly}, but a direct call with an out-of-enum
        # cadence must RAISE rather than silently return NULL (which a due-filter
        # would read as "not due" and quietly skip the source).
        for cadence in ("daily", "weekly", "monthly"):
            self.assertIs(self.query("SELECT signal_source_is_due(%s, NULL)", (cadence,)), True)
        # A just-scanned daily source is not yet due.
        self.assertIs(self.query("SELECT signal_source_is_due('daily', now())"), False)
        # The boundary is a strict `<` against transaction-start now(), which is
        # what CUSTOMIZATION.md states verbatim ("at exactly one interval the
        # source is not yet due") and what passive_sourcing.md's skip-a-cycle
        # warning rests on. The caller's now() and the function's own now() are
        # the same transaction start, so both comparisons below are exact rather
        # than timing-dependent.
        self.assertIs(
            self.query("SELECT signal_source_is_due('daily', now() - interval '1 day')"),
            False,
            "signal_source_is_due no longer uses a strict `<`: a source scanned "
            "exactly one cadence interval ago came back due, contradicting the "
            "boundary CUSTOMIZATION.md states",
        )
        self.assertIs(
            self.query(
                "SELECT signal_source_is_due('daily', now() - interval '1 day' - interval '1 second')"
            ),
            True,
            "a daily source scanned one second past its cadence interval was not "
            "due; the cadence window has widened beyond the documented interval",
        )
        with self.assertRaises(psycopg.errors.InvalidParameterValue):
            self.query("SELECT signal_source_is_due('hourly', now())")

    def test_06_workflow_rewatch_cannot_undo_operator_boundaries(self):
        uri = self.uri("guarded")
        self.invoke([
            "source-watch", "--name", "G4SS Guarded", "--uri", uri,
            "--source-class", "news_rss", "--cadence", "daily",
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})
        # An operator restricts and disables the entry.
        self.query(
            "UPDATE signal_sources SET confidentiality='confidential', enabled=FALSE"
            " WHERE canonical_uri=%s",
            (uri,), owner=True,
        )
        # The workflow lane must not resurrect an operator-disabled source.
        refused = self.invoke([
            "source-watch", "--name", "G4SS Guarded", "--uri", uri,
            "--source-class", "news_rss", "--cadence", "daily",
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"}, expect_ok=False)
        self.assertEqual(refused["error"]["code"], "source_watch_disabled")
        self.assertFalse(self.query(
            "SELECT enabled FROM signal_sources WHERE canonical_uri=%s", (uri,),
        ))
        self.assertEqual(self.query(
            "SELECT confidentiality FROM signal_sources WHERE canonical_uri=%s", (uri,), owner=True,
        ), "confidential")
        # Once re-enabled, a workflow re-watch refreshes descriptive fields but
        # cannot lower confidentiality or seize ownership.
        self.query(
            "UPDATE signal_sources SET enabled=TRUE WHERE canonical_uri=%s", (uri,), owner=True,
        )
        updated = self.invoke([
            "source-watch", "--name", "G4SS Guarded", "--uri", uri,
            "--source-class", "news_rss", "--cadence", "weekly",
            "--owner", "rogue-agent", "--confidentiality", "internal",
        ], env_extra={"VCOPS_WORKFLOW_MODE": "1"})["source"]
        self.assertEqual(updated["cadence"], "weekly")
        # The descriptive write lands, but the response carries only values the
        # lane itself submitted. Echoing the stored row would disclose an
        # above-ceiling entry's classification, owner and scan history, and
        # make any caller-supplied URI a probe for whether it is watched.
        self.assertEqual(
            sorted(updated),
            ["cadence", "canonical_uri", "enabled", "source_class", "source_name"],
        )
        # The withheld operator state is still intact in the row itself.
        self.assertEqual(self.query(
            "SELECT confidentiality FROM signal_sources WHERE canonical_uri=%s", (uri,), owner=True,
        ), "confidential")
        self.assertEqual(self.query(
            "SELECT owner FROM signal_sources WHERE canonical_uri=%s", (uri,), owner=True,
        ), "operator")
        self.assertEqual(self.query(
            "SELECT cadence FROM signal_sources WHERE canonical_uri=%s", (uri,), owner=True,
        ), "weekly")
        # The operator lane may deliberately reclassify and reassign.
        reclassified = self.invoke([
            "source-watch", "--name", "G4SS Guarded", "--uri", uri,
            "--source-class", "news_rss", "--cadence", "weekly",
            "--owner", "surveillance-team", "--confidentiality", "internal",
        ], env_extra={"VCOPS_OPERATOR_MODE": "1", "VCOPS_OPERATOR_ID": "g4-operator"})["source"]
        self.assertEqual(reclassified["confidentiality"], "internal")
        self.assertEqual(reclassified["owner"], "surveillance-team")


if __name__ == "__main__":
    unittest.main(verbosity=2)
