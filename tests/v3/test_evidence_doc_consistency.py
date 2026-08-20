# SPDX-License-Identifier: Apache-2.0
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

import contextlib
import io
import json
import os
import importlib.util
import re
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

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

# The per-document inventory of tool-managed date mentions is
# evidence_dates.MANAGED_MENTIONS, imported above rather than restated here:
# the tool's `--check` and this suite have to fail on the same drift, and a
# second copy of the numbers could disagree with the first. Why the inventory
# exists at all is documented beside the constant in
# scripts/set_evidence_execution_date.py.

# The phrasings that state the offline totals, each tagged so the sites can be
# pinned rather than counted. A bare floor let one phrasing be reworded away
# while its document's stated test/check counts stopped being checked at all.
OFFLINE_TOTAL_PATTERNS = (
    ("base-checks", r"\*\*(\d+) tests, (\d+)/(\d+)\*\* base checks"),
    ("pass-line", r"PASS — (\d+) tests, (\d+)/(\d+) checks"),
    ("passed-failed-skipped",
     r"(\d+) tests passed; 0 failed; 0 skipped; (\d+)/(\d+) offline checks"),
    ("unittest-cases",
     r"(\d+) offline unittest cases pass, 0 fail, 0 skip; (\d+)/(\d+) offline checks"),
    ("suites-pass", r"suites pass (\d+) tests"),
)

# Every (document, phrasing) pair the four evidence documents currently carry.
OFFLINE_TOTAL_CLAIM_SITES = frozenset({
    ("docs/V3_RELEASE_EVIDENCE.md", "base-checks"),
    ("docs/V3_RELEASE_EVIDENCE.md", "pass-line"),
    ("docs/V3_RELEASE_EVIDENCE.md", "suites-pass"),
    ("docs/PRODUCTION_READINESS.md", "passed-failed-skipped"),
    ("evals/V3_EVAL_RESULTS.md", "unittest-cases"),
})

UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = {2: "twenty", 3: "thirty", 4: "forty", 5: "fifty", 6: "sixty",
        7: "seventy", 8: "eighty", 9: "ninety"}


def number_word(value: int) -> str:
    """English word for 0-999, hyphenated ('thirty-three') like the docs.

    Hundreds are spelled 'one hundred and four'. The growth-bridge delta this
    serves crossed 100 during the pre-publication audit remediation, so the
    range is not decorative.
    """
    if 0 <= value < 20:
        return UNITS[value]
    if value < 100:
        tens, unit = divmod(value, 10)
        return f"{TENS[tens]}-{UNITS[unit]}" if unit else TENS[tens]
    if value < 1000:
        hundreds, rest = divmod(value, 100)
        head = f"{UNITS[hundreds]} hundred"
        return f"{head} and {number_word(rest)}" if rest else head
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


def measured_gate_checks() -> list[str]:
    """The offline gate's own check inventory, taken by running it stubbed.

    scripts/verify_offline.py calls subprocess in exactly one place — its
    module-level `run` — so replacing that with a zero-exit "Ran 1 test / OK"
    result makes main() assemble its complete check list in about a second
    without executing a suite, a linter or a shell parse. Counting the names it
    emits replaces a hand-maintained constant that restated the gate's fixed
    steps: with the number measured, a step added to or removed from the gate
    moves the figure the evidence documents have to state.
    """
    def stub(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "Ran 1 test\nOK\n", "")

    buffer = io.StringIO()
    with (
        mock.patch.object(verify_offline, "run", stub),
        mock.patch.object(sys, "argv", ["verify_offline.py"]),
        contextlib.redirect_stdout(buffer),
    ):
        verify_offline.main()
    return [check["name"] for check in json.loads(buffer.getvalue())["checks"]]


def all_claims(pattern: str) -> list[tuple[str, tuple[str, ...]]]:
    """Every match of pattern across the evidence documents, with its source."""
    claims = []
    for relative, text in EVIDENCE_TEXT.items():
        for match in re.finditer(pattern, text):
            claims.append((relative, match.groups()))
    return claims


class EvidenceDateConsistencyTests(unittest.TestCase):
    def test_matrix_and_rebuild_dates_are_each_a_single_date(self):
        for label, patterns in (
            ("matrix re-execution", evidence_dates.MATRIX_DATE_PATTERNS),
            ("image rebuild", evidence_dates.REBUILD_DATE_PATTERNS),
        ):
            found = evidence_dates.collect(patterns)
            self.assertEqual(
                dict(Counter(document for document, _ in found)),
                evidence_dates.MANAGED_MENTIONS[label],
                f"{label}: the per-document inventory of tool-managed date "
                "mentions moved. A mention that stops matching a pattern in "
                "scripts/set_evidence_execution_date.py leaves the managed set "
                "in silence — the tool skips it, --check still prints OK, and "
                "the document keeps a superseded date. Restore the phrasing, or "
                "update MANAGED_MENTIONS if the mention was deliberately added "
                "or removed — the inventory lives in "
                "scripts/set_evidence_execution_date.py, so `--check` and this "
                "gate read one source of truth.",
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
        # Measured from the gate rather than restated: the previous arithmetic
        # here reconstructed the inventory (suites + a *.sh glob + a hardcoded
        # count of fixed steps), so deleting a fixed step from verify_offline.py
        # left this figure — and the checks total the documents print —
        # unchanged and green.
        cls.offline_check_names = measured_gate_checks()
        cls.offline_checks = len(cls.offline_check_names)

    def test_offline_totals_match_every_documented_claim(self):
        # Folded in rather than given a test of its own: a new test method here
        # would move the offline total the four evidence documents pin. The
        # check count is measured, so this pins identity, not arithmetic — a
        # fixed step renamed or dropped fails naming itself, where a count
        # alone stays green whenever something else moves the other way.
        for step in (
            "python-syntax",
            "ruff",
            "ty",
            "skill-agent-system",
            "fixed-workflows",
            "manifest-current",
            "release-pristine",
        ):
            self.assertIn(
                step, self.offline_check_names,
                f"scripts/verify_offline.py no longer emits a '{step}' check; "
                "the offline gate's fixed step set changed",
            )
        claims = []
        sites = []
        for identifier, pattern in OFFLINE_TOTAL_PATTERNS:
            for relative, groups in all_claims(pattern):
                claims.append((relative, groups))
                sites.append((relative, identifier))
        self.assertEqual(
            set(sites), set(OFFLINE_TOTAL_CLAIM_SITES),
            "the offline-count phrasings moved: "
            f"gone {sorted(set(OFFLINE_TOTAL_CLAIM_SITES) - set(sites))}, "
            f"new {sorted(set(sites) - set(OFFLINE_TOTAL_CLAIM_SITES))}. A "
            "reworded phrasing stops being matched here, which leaves that "
            "document's stated test and check counts bound to nothing.",
        )
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
            # The delta word may now be a multi-word hundreds form
            # ("one hundred and four"), so spaces are part of the capture.
            r"measures (\d+) offline tests[\s\S]{0,200}?added ([a-z][a-z\- ]*?) in total"
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

    def test_readiness_growth_chain_is_arithmetically_consistent(self):
        """Every growth chain in every evidence document must add up, step by step.

        The chain narrates how the offline total reached its current value: a
        baseline, then a sequence of "added <word> more ... moving it to N".
        Only the LEADING figure was bound by a pattern, so the narrative could
        say anything; the first version of this test then bound only the last two
        of seven steps.

        Two gaps survived that repair, and both are closed here.

        First, the test read ONE hard-coded document while
        `set_evidence_execution_date.EVIDENCE_DOCS` lists four, and
        docs/V3_RELEASE_EVIDENCE.md already restates the same total — a chain
        planted there whose every step was wrong left the suite green.

        Second, the step/waypoint count equality only fires for a claim that
        matches one of the two patterns. A claim matching NEITHER changed neither
        count, so "the sixteenth pass added ninety-nine more;" with no waypoint
        was unbound. So the world is now the SEGMENTS of the chain: every
        semicolon-delimited segment that makes a chain claim at all must parse as
        exactly one step, which is a property of the text rather than of the
        patterns that read it.
        """
        claimish = re.compile(
            r"added [a-z][a-z\- ]*? more|mov(?:ed|ing) it to \d+|the baseline was \d+"
        )
        step_pattern = re.compile(
            r"added ([a-z][a-z\- ]*?) more[^;]*?mov(?:ed|ing) it to (\d+)"
        )
        baseline_pattern = re.compile(r"the baseline was (\d+)")
        word_to_int = {number_word(value): value for value in range(1000)}

        chains = 0
        for relative, text in EVIDENCE_TEXT.items():
            for line in text.split("\n"):
                if not baseline_pattern.search(line) or not step_pattern.search(line):
                    continue
                chains += 1
                segments = line.split(";")
                steps: list[tuple[str, str]] = []
                for index, segment in enumerate(segments):
                    if not claimish.search(segment):
                        continue
                    found = step_pattern.findall(segment)
                    if not found and baseline_pattern.search(segment) and not re.search(
                        r"added [a-z][a-z\- ]*? more|mov(?:ed|ing) it to \d+", segment
                    ):
                        continue  # a segment that only states the baseline
                    with self.subTest(document=relative, segment=index):
                        self.assertEqual(
                            1, len(found),
                            f"{relative}: this segment of the growth chain makes a "
                            f"claim but does not parse as exactly one step "
                            f"(found {found}): {' '.join(segment.split())[:160]!r}. "
                            f"Every step must read 'added <word> more ... moving "
                            f"it to N'; a claim in any other shape is unbound, "
                            f"which is how a chain with a delta and no waypoint "
                            f"passed.",
                        )
                    steps.extend(found)

                waypoints = [int(v) for v in re.findall(r"mov(?:ed|ing) it to (\d+)", line)]
                self.assertEqual(
                    len(waypoints), len(steps),
                    f"{relative}: {len(waypoints)} waypoints but {len(steps)} "
                    f"readable steps {steps}",
                )
                unknown = [word for word, _ in steps if word not in word_to_int]
                self.assertEqual(
                    [], unknown,
                    f"{relative}: delta word(s) {unknown} are not English "
                    f"number-words this module can read",
                )
                self.assertEqual(
                    sorted(waypoints), waypoints,
                    f"{relative}: the growth chain's waypoints are not increasing: "
                    f"{waypoints}",
                )
                self.assertEqual(
                    len(set(waypoints)), len(waypoints),
                    f"{relative}: the growth chain repeats a waypoint: {waypoints}",
                )

                baseline = baseline_pattern.search(line)
                assert baseline is not None  # guarded by the loop condition above
                running = int(baseline.group(1))
                for word, stated in steps:
                    after = int(stated)
                    with self.subTest(document=relative, step=f"{running} + {word}"):
                        self.assertEqual(
                            running + word_to_int[word], after,
                            f"{relative} says {running} plus '{word}' "
                            f"({word_to_int[word]}) reaches {after}; that is "
                            f"{running + word_to_int[word]}. The chain is the "
                            f"document's own account of how the total was "
                            f"reached, so an operator reconciling it finds "
                            f"arithmetic that does not close.",
                        )
                    running = after

                self.assertEqual(
                    self.offline_tests, waypoints[-1],
                    f"{relative}: the growth chain ends at {waypoints[-1]} but "
                    f"discovery counts {self.offline_tests}",
                )

        self.assertTrue(
            chains,
            "no evidence document carries a growth chain any more; this binding "
            "is blind. It must find at least the offline-suites cell.",
        )

    def test_opt_in_gate_figures_are_derived_not_asserted(self):
        """The opt-in gates' own check counts must match what the documents claim.

        The offline totals are bound to discovery, but the figures for the gates
        that need Docker or a database were bound by nothing: measured, the full
        offline gate PASSED with G6 restated as 9/9, G8 as "six checks", and the
        retrieval-scale total as any number at all. Every one of them happens to
        be correct today, which is exactly when an unbound figure is cheapest to
        pin and most likely to rot later.

        Each is derivable from a constant in the script that produces it, so read
        it from there rather than re-stating it.
        """
        # IMPORT run_g6_image rather than parse it: EXPECTED_CHECK_NAMES
        # star-unpacks a generator over PROFILES, so counting quoted literals in
        # the source sees 3 of the 8 names. The module imports cleanly (it needs
        # no database driver), so ask it.
        def load(name: str):
            spec = importlib.util.spec_from_file_location(
                f"evidence_probe_{name}", ROOT / "scripts" / f"{name}.py"
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        g6_checks = len(load("run_g6_image").EXPECTED_CHECK_NAMES)

        # G8 declares no constant; its checks are appended one call at a time,
        # and importing it is not free of side effects, so count the call sites.
        g8_source = (ROOT / "scripts" / "run_g8_deployment.py").read_text(encoding="utf-8")
        g8_checks = len(re.findall(r'checks\.append\(check\("[a-z-]+"', g8_source))

        # Parsed, not imported: run_retrieval_scale imports psycopg at module
        # level, which the offline suites deliberately do not require.
        scale_source = (ROOT / "scripts" / "run_retrieval_scale.py").read_text(encoding="utf-8")
        fuzzy = re.search(r"^FUZZY_CASES = (\d+)", scale_source, re.M)
        exact = re.search(r"^EXACT_CASES = (\d+)", scale_source, re.M)
        self.assertIsNotNone(fuzzy, "run_retrieval_scale.py no longer declares FUZZY_CASES")
        self.assertIsNotNone(exact, "run_retrieval_scale.py no longer declares EXACT_CASES")
        assert fuzzy is not None and exact is not None
        scale_cases = int(fuzzy.group(1)) + int(exact.group(1))

        for label, measured, patterns in (
            ("G6 image gate", g6_checks, (r"\*\*(\d+)/\d+\*\*.{0,80}?image rebuilt",
                                          r"run_g6_image\.py` \(\*\*(\d+)/\d+\*\*",
                                          r"gate \(G6\) passes (\d+)/\d+")),
            ("G8 deployment gate", g8_checks, (r"run_g8_deployment\.py` \(\*\*PASS\*\* — (\w+) checks",)),
            ("retrieval-scale gate", scale_cases, (r"run_retrieval_scale\.py` \(\*\*(\d+)/\d+\*\*",
                                                   r"retrieval-scale gate passes (\d+)/\d+")),
        ):
            found = 0
            for relative, text in EVIDENCE_TEXT.items():
                for pattern in patterns:
                    for match in re.finditer(pattern, text, re.S):
                        raw = match.group(1)
                        stated = int(raw) if raw.isdigit() else {
                            "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                        }.get(raw.lower())
                        found += 1
                        with self.subTest(gate=label, document=relative):
                            self.assertEqual(
                                measured, stated,
                                f"{relative} states {raw} for the {label}; the "
                                f"script itself declares {measured}",
                            )
            with self.subTest(gate=label):
                self.assertTrue(
                    found,
                    f"no evidence document states a figure for the {label} in a "
                    f"shape this test can read; the binding is blind",
                )

    def test_manifest_count_is_internally_coherent(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["file_count"], len(manifest["files"]))


if __name__ == "__main__":
    unittest.main()
