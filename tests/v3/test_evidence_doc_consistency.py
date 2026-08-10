# SPDX-License-Identifier: 0BSD
"""The evidence documents must agree with the gates and with each other.

Three audit findings established the defect class this suite closes: a prose
test count regressed while the gate emitted another number (F-27, and F-12
before it), and two consecutive passes each left one hand-edited re-execution
date stale while updating its seven siblings. Nothing bound the evidence
prose to the gate inventory; this suite is that binding. Every count below is
measured the same way the offline gate measures it (fresh-interpreter unittest
discovery per suite), so a drifted document fails the gate rather than waiting
for the next audit's reviewers to notice.

Discovery over tests/g4 imports psycopg and yaml at module scope, so this
suite requires the documented dev interpreter (requirements-dev.lock), not a
bare host python3 — the same requirement the offline gate already carries.
"""

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import set_evidence_execution_date as evidence_dates  # noqa: E402
import verify_offline  # noqa: E402

SUITE_COUNT_SNIPPET = """
import sys
import unittest

def flatten(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from flatten(entry)
        else:
            yield entry

found = unittest.defaultTestLoader.discover(sys.argv[1], sys.argv[2])
cases = list(flatten(found))
broken = [case for case in cases if type(case).__name__ == "_FailedTest"]
if broken:
    print("LOAD-ERROR: " + "; ".join(str(case) for case in broken))
    raise SystemExit(2)
print(len(cases))
"""

EVIDENCE_TEXT = {
    relative: (ROOT / relative).read_text(encoding="utf-8")
    for relative in evidence_dates.EVIDENCE_DOCS
}

NUMBER_WORDS = {
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


def discovered_count(directory: str, pattern: str) -> int:
    """Count a suite exactly as verify_offline does: fresh-interpreter discovery."""
    process = subprocess.run(
        [sys.executable, "-B", "-c", SUITE_COUNT_SNIPPET, directory, pattern],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if process.returncode:
        raise AssertionError(
            f"discovery failed for {directory} {pattern}: {process.stdout}{process.stderr}"
        )
    return int(process.stdout.strip())


def all_claims(pattern: str) -> list[tuple[str, tuple[str, ...]]]:
    """Every match of pattern across the evidence documents, with its source."""
    claims = []
    for relative, text in EVIDENCE_TEXT.items():
        for match in re.finditer(pattern, text):
            claims.append((relative, match.groups()))
    return claims


class EvidenceDateConsistencyTests(unittest.TestCase):
    def test_matrix_and_rebuild_dates_are_each_a_single_date(self):
        for label, patterns, minimum in (
            ("matrix re-execution", evidence_dates.MATRIX_DATE_PATTERNS, 6),
            ("image rebuild", evidence_dates.REBUILD_DATE_PATTERNS, 3),
        ):
            found = evidence_dates.collect(patterns)
            self.assertGreaterEqual(
                len(found), minimum,
                f"{label}: only {len(found)} mentions matched; the patterns in "
                "scripts/set_evidence_execution_date.py no longer fit the documents",
            )
            dates = {date for _, date in found}
            self.assertEqual(
                len(dates), 1,
                f"{label} dates diverge across the evidence documents: {found}. "
                "Move them with scripts/set_evidence_execution_date.py, never by hand.",
            )


class EvidenceCountConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite_counts = {
            name: discovered_count(directory, pattern)
            for name, directory, pattern in verify_offline.SUITES
        }
        cls.offline_tests = sum(cls.suite_counts.values())
        shell_paths = sorted(ROOT.glob("scripts/*.sh")) + sorted(ROOT.glob("migrations/*.sh"))
        # python-syntax, ruff, ty, skill-agent-system, fixed-workflows,
        # manifest-current, release-pristine: the gate's fixed non-suite,
        # non-shell steps. Moving that set means updating this constant, the
        # evidence documents, and verify_offline together.
        fixed_steps = 7
        cls.offline_checks = len(verify_offline.SUITES) + len(shell_paths) + fixed_steps

    def test_offline_totals_match_every_documented_claim(self):
        claims = (
            all_claims(r"\*\*(\d+) tests, (\d+)/(\d+)\*\* base checks")
            + all_claims(r"PASS — (\d+) tests, (\d+)/(\d+) checks")
            + all_claims(r"(\d+) tests passed; 0 failed; 0 skipped; (\d+)/(\d+) offline checks")
            + all_claims(r"(\d+) offline unittest cases pass, 0 fail, 0 skip; (\d+)/(\d+) offline checks")
            + all_claims(r"suites pass (\d+) tests")
        )
        self.assertGreaterEqual(len(claims), 4, "the offline-count phrasings have rotted")
        for relative, groups in claims:
            self.assertEqual(
                int(groups[0]), self.offline_tests,
                f"{relative} states {groups[0]} offline tests; discovery counts "
                f"{self.offline_tests}",
            )
            for stated in groups[1:]:
                self.assertEqual(
                    int(stated), self.offline_checks,
                    f"{relative} states {stated} offline checks; the gate inventory "
                    f"counts {self.offline_checks}",
                )
        checks_only = all_claims(r"\((\d+)/(\d+) offline checks\)")
        self.assertGreaterEqual(len(checks_only), 1, "the bare checks phrasing has rotted")
        for relative, groups in checks_only:
            for stated in groups:
                self.assertEqual(
                    int(stated), self.offline_checks,
                    f"{relative} states {stated} offline checks; the gate inventory "
                    f"counts {self.offline_checks}",
                )
        for relative, groups in all_claims(r"G5 (\d+)/(\d+); G7 (\d+)/(\d+)"):
            for stated, suite in zip(groups, ("g5", "g5", "g7", "g7")):
                self.assertEqual(
                    int(stated), self.suite_counts[suite],
                    f"{relative} states G5/G7 counts {groups}; discovery counts "
                    f"{self.suite_counts['g5']}/{self.suite_counts['g7']}",
                )

    def test_per_suite_evidence_table_matches_discovery(self):
        rows = all_claims(
            r"\| (\d+)/(\d+) \| `(?:[A-Z_]+=\S+ )?python3 -B -m unittest discover"
            r" -s (tests/[a-z0-9]+) -p '([^']+)'"
        )
        directories = {directory for _, (_, _, directory, _) in rows}
        self.assertGreaterEqual(len(rows), 7, "the per-suite evidence table has rotted")
        for relative, (passed, total, directory, pattern) in rows:
            measured = discovered_count(directory, pattern)
            for stated in (passed, total):
                self.assertEqual(
                    int(stated), measured,
                    f"{relative} table row states {passed}/{total} for {directory} "
                    f"{pattern}; discovery counts {measured}",
                )
        for name, directory, _pattern in verify_offline.SUITES:
            if directory not in directories:
                self.fail(f"suite {name} ({directory}) has no row in the evidence table")

    def test_g4_claims_match_discovery(self):
        g4_files = sorted((ROOT / "tests/g4").glob("test_*.py"))
        g4_total = discovered_count("tests/g4", "test_*.py")
        for relative, groups in (
            all_claims(r"G4 \((\d+)/(\d+)\)")
            + all_claims(r"(\d+)/(\d+)\*\* across \w+ suites")
            + all_claims(r"\*\*(\d+)/(\d+)\*\* \| `python3 -B scripts/run_g4\.py`")
            + all_claims(r"G4 (\d+)/(\d+) across")
            + all_claims(r"Disposable PostgreSQL G4 \| (\d+)/(\d+) across")
        ):
            for stated in groups:
                self.assertEqual(
                    int(stated), g4_total,
                    f"{relative} states G4 {groups[0]}/{groups[1]}; discovery over "
                    f"tests/g4 counts {g4_total}",
                )
        word = NUMBER_WORDS[len(g4_files)]
        for relative, (stated_word,) in all_claims(r"/\d+\*{0,2} across (\w+) suites"):
            self.assertEqual(
                stated_word, word,
                f"{relative} says 'across {stated_word} suites'; tests/g4 holds "
                f"{len(g4_files)} suite files",
            )

    def test_g4_per_suite_parenthetical_matches_discovery(self):
        labels = {
            "semantics": "test_semantics.py",
            "document security": "test_document_security.py",
            "database contract": "test_database_contract.py",
            "helper CLI": "test_helper_cli_database.py",
            "workflow execution": "test_workflow_execution.py",
            "research intelligence": "test_research_intelligence.py",
            "source surveillance": "test_source_surveillance.py",
        }
        text = EVIDENCE_TEXT["docs/PRODUCTION_READINESS.md"]
        for label, filename in labels.items():
            match = re.search(rf"{label} (\d+)[,)]", text)
            if match is None:
                self.fail(f"per-suite figure for '{label}' has rotted")
            measured = discovered_count("tests/g4", filename)
            self.assertEqual(
                int(match.group(1)), measured,
                f"PRODUCTION_READINESS states '{label} {match.group(1)}'; discovery "
                f"over {filename} counts {measured}",
            )

    def test_manifest_count_is_internally_coherent(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["file_count"], len(manifest["files"]))


if __name__ == "__main__":
    unittest.main()
