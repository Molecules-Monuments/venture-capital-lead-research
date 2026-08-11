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

UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty",
        7: "seventy", 8: "eighty", 9: "ninety"}


def number_word(value: int) -> str:
    """English word for 0-99, hyphenated ('thirty-three') like the docs."""
    if 0 <= value < 20:
        return UNITS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        return f"{TENS[tens]}-{UNITS[unit]}" if unit else TENS[tens]
    raise AssertionError(f"no English number-word mapping for {value}")


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


    def test_run_history_lists_end_at_the_tool_managed_matrix_date(self):
        """A hand-maintained date list beside a tool-managed one drifts.

        `scripts/set_evidence_execution_date.py` rewrites every match of its
        patterns to one date, so a *history* enumeration deliberately sits
        outside it — otherwise the tool would collapse the history. The
        fourteenth pass then moved the tool-managed rebuild date to 2026-08-11
        in the same sentence that lists the retrieval-scale run history, and
        left that list ending at 2026-08-10: the sentence read as if the scale
        gate had not run on the day the matrix did.

        The list cannot be generated, but its terminal entry is checkable: a
        run history of the matrix's own gates must reach the day the matrix
        last ran.
        """
        matrix = {date for _, date in evidence_dates.collect(evidence_dates.MATRIX_DATE_PATTERNS)}
        self.assertEqual(len(matrix), 1, "matrix date is not singular; the sibling test covers this")
        current = matrix.pop()
        # Anchor to the retrieval-scale clause and tolerate any wrapping: the
        # same sentence carries a G6 "gate was re-run on <single date>" clause,
        # and hardcoded single spaces made both which-clause-matches and
        # whether-it-matches-at-all depend on where the line happened to wrap.
        history = re.compile(
            r"retrieval-scale\s+gate\s+was\s+re-run\s+on\s+"
            r"((?:\d{4}-\d{2}-\d{2}[,\s]+(?:and\s+)?)*\d{4}-\d{2}-\d{2})"
        )
        found = []
        for relative, text in EVIDENCE_TEXT.items():
            for match in history.finditer(text):
                dates = re.findall(r"\d{4}-\d{2}-\d{2}", match.group(1))
                found.append((relative, dates))
        self.assertTrue(
            found,
            "no 'gate was re-run on <date list>' history was found; the "
            "pattern no longer fits the evidence documents",
        )
        for relative, dates in found:
            self.assertEqual(
                dates[-1], current,
                f"{relative}: the run-history list ends at {dates[-1]} while the "
                f"tool-managed matrix re-execution date is {current}. Append the "
                "current date by hand — this list is deliberately outside "
                "set_evidence_execution_date.py, which would collapse the history.",
            )
            self.assertEqual(
                dates, sorted(dates),
                f"{relative}: the run-history list is not in ascending order: {dates}",
            )

    def test_rebuild_provenance_clause_is_identical_across_the_documents(self):
        """PRODUCTION_READINESS claims its two siblings "carry the same note".

        The fourteenth pass updated the clause in one document and left the
        other two describing a different set of edited files, which falsified
        that cross-claim. The dates in this sentence are tool-managed; the
        file list beside them was not bound to anything, so bind it here.
        """
        # The three documents terminate the sentence differently (an em-dash
        # continuation in two, a full stop in the third), so stop at either.
        clause = re.compile(
            r"after that day's edits to\s+(.+?)(?:\s+—|\.\s)", re.S
        )
        found = []
        for relative, text in EVIDENCE_TEXT.items():
            for match in clause.finditer(text):
                found.append((relative, " ".join(match.group(1).split())))
        self.assertEqual(
            {relative for relative, _ in found},
            {
                "docs/V3_RELEASE_EVIDENCE.md",
                "docs/PRODUCTION_READINESS.md",
                "evals/V3_EVAL_RESULTS.md",
            },
            "PRODUCTION_READINESS asserts all three documents carry this note, "
            f"but the clause was found only in {sorted({r for r, _ in found})}. "
            "A count check would pass while one document dropped it and "
            "another carried it twice.",
        )
        variants = {phrase for _, phrase in found}
        self.assertEqual(
            len(variants), 1,
            f"the rebuild-provenance clause differs across documents: {found}. "
            "All three describe one rebuild, so the file list must be "
            "identical in each.",
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
        g5_g7 = all_claims(r"G5 (\d+)/(\d+); G7 (\d+)/(\d+)")
        self.assertGreaterEqual(len(g5_g7), 1, "the G5/G7 phrasing has rotted")
        for relative, groups in g5_g7:
            for stated, suite in zip(groups, ("g5", "g5", "g7", "g7")):
                self.assertEqual(
                    int(stated), self.suite_counts[suite],
                    f"{relative} states G5/G7 counts {groups}; discovery counts "
                    f"{self.suite_counts['g5']}/{self.suite_counts['g7']}",
                )

    def test_growth_bridge_arithmetic_matches_discovery(self):
        # The narrative sentence bridging the pre-rewrite baseline to the
        # current aggregate has gone stale twice (once as "fourteen", once as
        # "twenty-five"), because no pattern above matches it. The baseline is
        # a historical measurement at a named commit that discovery cannot
        # re-derive, so it is taken as stated and only the delta arithmetic is
        # enforced.
        claims = all_claims(
            r"measures (\d+) offline tests[\s\S]{0,200}?added ([a-z-]+) in total"
        )
        self.assertGreaterEqual(len(claims), 1, "the growth-bridge phrasing has rotted")
        for relative, (baseline, delta_word) in claims:
            expected = number_word(self.offline_tests - int(baseline))
            self.assertEqual(
                delta_word, expected,
                f"{relative} bridges {baseline} tests to the current aggregate "
                f"with '{delta_word}'; discovery makes that delta {expected}",
            )

    def test_per_suite_evidence_table_matches_discovery(self):
        rows = all_claims(
            r"\| (\d+)/(\d+) \| `(?:[A-Z_]+=\S+ )?python3 -B -m unittest discover"
            r" -s (tests/[a-z0-9]+) -p '([^']+)'"
        )
        pairs = {(directory, pattern) for _, (_, _, directory, pattern) in rows}
        self.assertGreaterEqual(len(rows), 7, "the per-suite evidence table has rotted")
        for relative, (passed, total, directory, pattern) in rows:
            measured = discovered_count(directory, pattern)
            for stated in (passed, total):
                self.assertEqual(
                    int(stated), measured,
                    f"{relative} table row states {passed}/{total} for {directory} "
                    f"{pattern}; discovery counts {measured}",
                )
        # Key on (directory, pattern), not directory alone: the two
        # env-prefixed G4 rows share tests/g4, and one of them rotting away
        # must fail here even while the other keeps the directory covered.
        for name, directory, pattern in verify_offline.SUITES:
            if (directory, pattern) not in pairs:
                self.fail(
                    f"suite {name} ({directory} {pattern}) has no row in the "
                    "evidence table"
                )

    def test_g4_claims_match_discovery(self):
        g4_files = sorted((ROOT / "tests/g4").glob("test_*.py"))
        g4_total = discovered_count("tests/g4", "test_*.py")
        claims = (
            all_claims(r"G4 \((\d+)/(\d+)\)")
            + all_claims(r"(\d+)/(\d+)\*\* across \w+ suites")
            + all_claims(r"\*\*(\d+)/(\d+)\*\* \| `python3 -B scripts/run_g4\.py`")
            + all_claims(r"G4 (\d+)/(\d+) across")
            + all_claims(r"Disposable PostgreSQL G4 \| (\d+)/(\d+) across")
        )
        self.assertGreaterEqual(len(claims), 7, "the G4 count phrasings have rotted")
        for relative, groups in claims:
            for stated in groups:
                self.assertEqual(
                    int(stated), g4_total,
                    f"{relative} states G4 {groups[0]}/{groups[1]}; discovery over "
                    f"tests/g4 counts {g4_total}",
                )
        across = all_claims(r"/\d+\*{0,2} across (\w+) suites")
        self.assertGreaterEqual(
            len(across), 5, "the G4 across-suites phrasings have rotted"
        )
        word = number_word(len(g4_files))
        for relative, (stated_word,) in across:
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
