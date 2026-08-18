# SPDX-License-Identifier: 0BSD
"""Set or check the canonical re-execution dates across the evidence documents.

The four evidence documents state, in several phrasings each, (a) the date the
full gate matrix was last re-executed and (b) the date the derived image was
last rebuilt with ``docker build --no-cache --pull``. Two consecutive audit
passes each found one of these hand-edited dates left stale (one instance
missed out of eight), so hand-editing them is a demonstrated defect class:
this script is the only supported way to move them.

Two offline-gate suites read the patterns below and fail on the drift this tool
exists to prevent:

* ``tests/v3/test_evidence_doc_consistency.py`` — the stated dates diverge, a
  document's count of tool-managed mentions moves, or the hand-maintained
  retrieval-scale run-history list stops ending at the matrix date.
* ``tests/v3/test_snapshot_recipe_currency.py`` — the rebuild date quoted in
  the two copies of the snapshot.debian.org recovery recipe stops matching it,
  or that recipe's ``SNAPSHOT=`` timestamp falls behind the rebuild date.

``--check`` reproduces all of those, so this tool and the gate fail on the same
tree. They did not before: an eighteenth-pass finding moved the matrix date with
the documented command, got ``OK`` from the documented ``--check``, and then had
``tests/v3`` reject the tree over the run-history list the tool never mentioned.

Usage:
    python3 -B scripts/set_evidence_execution_date.py 2026-08-10
    python3 -B scripts/set_evidence_execution_date.py 2026-08-10 --rebuild-date 2026-08-09
    python3 -B scripts/set_evidence_execution_date.py --check

Setting rewrites every matrix-date mention to the given date and every
rebuild-date mention to ``--rebuild-date`` (default: the same date). The
matrix group includes the G8 re-run and retrieval-benchmark re-run mentions,
which move with every full matrix re-execution.

Three dates are deliberately *not* rewritten, because each is a history or a
provenance record that a blanket rewrite would destroy — but each is bound to a
managed date by the gate, so moving a managed date obliges a hand-edit and
``--check`` names the ones still outstanding:

* the retrieval-scale run-history *list* in V3_RELEASE_EVIDENCE — append the
  new matrix date to it; a rewrite would collapse the history to one entry.
  This append is due whenever the *matrix* date moves, not only when the scale
  gate is re-run on its own: the sibling "benchmark re-run <date>" mention is
  already in the managed set for exactly that reason.
* the ``V3_RELEASE_EVIDENCE.md records <date>`` quote in each copy of the
  snapshot.debian.org recovery recipe (``docs/RUNBOOK.md`` and
  ``Dockerfile.openclaw``) — set both to the new rebuild date.
* the recipe's ``SNAPSHOT=`` timestamp, which must not predate the rebuild it
  is supposed to reproduce.

Fully historical dates (the original 2026-07-23 execution and per-finding
re-check dates) are outside all of this: they are records of past events, not
statements about the current tree.
"""

import argparse
import datetime
import re
import sys
from collections import Counter
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent

EVIDENCE_DOCS = (
    "docs/V3_RELEASE_EVIDENCE.md",
    "docs/PRODUCTION_READINESS.md",
    "docs/OFFLINE_RELEASE_EVIDENCE.md",
    "evals/V3_EVAL_RESULTS.md",
)

DATE = r"(?P<date>\d{4}-\d{2}-\d{2})"

# Every phrasing the evidence documents use for "the full matrix was last
# re-executed on <date>". \s matches the newline of a wrapped sentence.
MATRIX_DATE_PATTERNS = tuple(
    re.compile(expression, re.IGNORECASE)
    for expression in (
        rf"last\s+(?:full\s+)?re-execut(?:ed|ion)\s*:?\s*(?:on\s+)?\**{DATE}",
        rf"count\s+re-verified\s+{DATE}",
        rf"measurement\s+of\s+a\s+\*\*{DATE}\*\*\s+re-execution",
        rf"G8\s+gate\s+\(re-run\s+{DATE}",
        rf"benchmark\s+re-run\s+{DATE}",
    )
)

# Every phrasing for "the derived image was rebuilt on <date>". The G6 re-run
# statement is bound to the same rebuild, so it moves with this group.
REBUILD_DATE_PATTERNS = tuple(
    re.compile(expression, re.IGNORECASE)
    for expression in (
        rf"--no-cache\s+--pull`\s+on\s+\**{DATE}",
        rf"G6\s+gate\s+was\s+re-run\s+on\s+{DATE}",
    )
)

# The hand-maintained dates the gate binds to the managed ones. The patterns
# are duplicated in tests/v3/test_evidence_doc_consistency.py and
# tests/v3/test_snapshot_recipe_currency.py, which own the gate-side assertions;
# the copies here exist so `--check` fails where those suites fail rather than
# printing OK on a tree they reject. Keep them identical, or import these.
RUN_HISTORY_PATTERN = re.compile(
    r"retrieval-scale\s+gate\s+was\s+re-run\s+on\s+"
    r"((?:\d{4}-\d{2}-\d{2}[,\s]+(?:and\s+)?)*\d{4}-\d{2}-\d{2})"
)
RECIPE_SOURCES = ("docs/RUNBOOK.md", "Dockerfile.openclaw")
QUOTED_REBUILD_DATE = re.compile(
    r"V3_RELEASE_EVIDENCE\.md`? records \*{0,2}(\d{4}-\d{2}-\d{2})"
)
# Groups 1-3 are the timestamp's year, month and day.
SNAPSHOT_ASSIGNMENT = re.compile(r"SNAPSHOT=(\d{4})(\d{2})(\d{2})T\d{6}Z")

# Measured mention inventory per document, taken from the shipped tree. These
# numbers move only when a phrasing is deliberately added to or removed from a
# document; a mention that merely stops matching a pattern above leaves the
# managed set in silence — the rewrite skips it, and without this comparison
# `--check` still prints OK while the document keeps a superseded date.
# docs/OFFLINE_RELEASE_EVIDENCE.md carries no managed mention and therefore no
# key, so one appearing there is a mismatch too.
# tests/v3/test_evidence_doc_consistency.py imports this constant and asserts it
# against fresh document text, so `--check` and the offline gate fail on the same
# drift; do not restate these numbers there or anywhere else.
MANAGED_MENTIONS = {
    "matrix re-execution": {
        "docs/V3_RELEASE_EVIDENCE.md": 3,
        "docs/PRODUCTION_READINESS.md": 3,
        "evals/V3_EVAL_RESULTS.md": 4,
    },
    "image rebuild": {
        "docs/V3_RELEASE_EVIDENCE.md": 2,
        "docs/PRODUCTION_READINESS.md": 1,
        "evals/V3_EVAL_RESULTS.md": 1,
    },
}


def parse_date(value: str) -> datetime.date:
    """Parse YYYY-MM-DD, rejecting shapes that are not real calendar days.

    The check this replaces was `re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}")`, which
    accepts 2026-02-30, 2026-13-45 and 0000-00-00. An eighteenth-pass finding
    ran the tool with 2026-02-30 and got fourteen managed mentions across four
    evidence documents asserting a re-execution on a day that does not exist,
    with `--check` and the offline gate both still reporting OK.

    The regex stays in front of `fromisoformat` on purpose: since 3.11 that
    parser also accepts basic-format and week-date spellings (`20260818`,
    `2026-W34-1`), which would round-trip into the documents in a form no
    pattern above matches and no reader expects.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"not a YYYY-MM-DD date: {value}")
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"not a real calendar date: {value}") from None


def future_horizon() -> datetime.date:
    """The latest date that may legitimately be called "already happened".

    Both managed groups record events in the past, so a date beyond today is an
    operator typo. One day of slack absorbs the timezone spread: UTC+14 is a
    real offset, so a run genuinely happening "today" can be tomorrow's date in
    UTC. Anything further out is not a clock question.
    """
    return datetime.datetime.now(tz=datetime.UTC).date() + datetime.timedelta(days=1)


def document_text(relative: str) -> str:
    return (PACKAGE / relative).read_text(encoding="utf-8")


def collect(patterns: tuple[re.Pattern[str], ...]) -> list[tuple[str, str]]:
    """Return every (document, date) the patterns match, in document order.

    Raises ValueError if a matched date is not a real calendar day. The
    validation lives here rather than in a new test method because both
    tests/v3 suites reach the documents through this function, so an impossible
    date already fails the offline gate — and adding a test method to
    tests/v3/test_evidence_doc_consistency.py would move the offline test total
    that those same four documents pin.
    """
    found: list[tuple[str, str]] = []
    for relative in EVIDENCE_DOCS:
        text = document_text(relative)
        for pattern in patterns:
            for match in pattern.finditer(text):
                value = match.group("date")
                try:
                    parse_date(value)
                except ValueError as error:
                    raise ValueError(f"{relative}: {error}") from None
                found.append((relative, value))
    return found


def rewrite(patterns: tuple[re.Pattern[str], ...], new_date: str) -> int:
    """Rewrite the date group of every match to new_date; return match count."""
    total = 0
    for relative in EVIDENCE_DOCS:
        path = PACKAGE / relative
        text = path.read_text(encoding="utf-8")
        spans: list[tuple[int, int]] = []
        for pattern in patterns:
            spans.extend(match.span("date") for match in pattern.finditer(text))
        if not spans:
            continue
        for start, end in sorted(spans, reverse=True):
            text = text[:start] + new_date + text[end:]
        path.write_text(text, encoding="utf-8")
        print(f"{relative}: {len(spans)} date(s) set")
        total += len(spans)
    return total


def outstanding_hand_edits(matrix_date: str, rebuild_date: str) -> list[str]:
    """The hand-maintained dates the gate binds to the two managed ones.

    Each is deliberately outside the rewrite set — a blanket rewrite would
    collapse a run history to one entry, and the recipe's snapshot timestamp is
    an archive coordinate, not a date this tool may invent. Each is nonetheless
    asserted against a managed date by a tests/v3 suite, so leaving them out of
    `--check` is what let the tool print OK on a tree the gate rejects.
    """
    problems: list[str] = []

    histories: list[tuple[str, list[str]]] = []
    for relative in EVIDENCE_DOCS:
        for match in RUN_HISTORY_PATTERN.finditer(document_text(relative)):
            histories.append(
                (relative, re.findall(r"\d{4}-\d{2}-\d{2}", match.group(1)))
            )
    if not histories:
        problems.append(
            "no retrieval-scale run-history list matched; the phrasing moved and "
            "tests/v3/test_evidence_doc_consistency.py reads it too"
        )
    for relative, dates in histories:
        if dates[-1] != matrix_date:
            problems.append(
                f"{relative}: append {matrix_date} to the retrieval-scale "
                f"run-history list, which still ends at {dates[-1]}. It is a "
                "history, so this tool leaves it alone; "
                "tests/v3/test_evidence_doc_consistency.py requires it to reach "
                "the day the matrix last ran"
            )
        if dates != sorted(dates):
            problems.append(
                f"{relative}: the retrieval-scale run-history list is not in "
                f"ascending order: {dates}"
            )

    for relative in RECIPE_SOURCES:
        text = document_text(relative)
        quoted = QUOTED_REBUILD_DATE.findall(text)
        if len(quoted) != 1:
            problems.append(
                f"{relative}: expected exactly one "
                '"V3_RELEASE_EVIDENCE.md records <date>" quote in the '
                f"snapshot.debian.org recovery recipe; found {len(quoted)}"
            )
        elif quoted[0] != rebuild_date:
            problems.append(
                f"{relative}: set the recovery recipe's "
                f'"V3_RELEASE_EVIDENCE.md records {quoted[0]}" quote to '
                f"{rebuild_date} by hand; tests/v3/test_snapshot_recipe_currency.py "
                "binds it to the recorded rebuild date"
            )
        for parts in SNAPSHOT_ASSIGNMENT.findall(text):
            if "".join(parts) < rebuild_date.replace("-", ""):
                problems.append(
                    f"{relative}: the recipe's SNAPSHOT={'-'.join(parts)} archive "
                    f"predates the {rebuild_date} rebuild, so a snapshot-only "
                    "install can resolve a package behind the reviewed image. "
                    "Choose a snapshot at or after the rebuild"
                )
    return problems


def check() -> int:
    status = 0
    resolved: dict[str, str] = {}
    horizon = future_horizon()
    for label, patterns in (
        ("matrix re-execution", MATRIX_DATE_PATTERNS),
        ("image rebuild", REBUILD_DATE_PATTERNS),
    ):
        try:
            found = collect(patterns)
        except ValueError as error:
            print(f"FAIL: {label}: {error}")
            status = 1
            continue
        measured = dict(Counter(relative for relative, _ in found))
        if measured != MANAGED_MENTIONS[label]:
            print(
                f"FAIL: {label} mention inventory moved: "
                f"{measured} != {MANAGED_MENTIONS[label]}"
            )
            status = 1
        dates = sorted({date for _, date in found})
        if not found:
            print(f"FAIL: no {label} dates matched; the patterns have rotted")
            status = 1
        elif len(dates) > 1:
            print(f"FAIL: {label} dates diverge: {dates}")
            for relative, date in found:
                print(f"  {relative}: {date}")
            status = 1
        else:
            print(f"OK: {label} date is {dates[0]} ({len(found)} mentions)")
            resolved[label] = dates[0]
            if parse_date(dates[0]) > horizon:
                print(
                    f"FAIL: the {label} date {dates[0]} is in the future; both "
                    "managed groups record events that have already happened"
                )
                status = 1
    if len(resolved) == 2:
        for problem in outstanding_hand_edits(
            resolved["matrix re-execution"], resolved["image rebuild"]
        ):
            print(f"FAIL: {problem}")
            status = 1
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", nargs="?", help="matrix re-execution date, YYYY-MM-DD")
    parser.add_argument("--rebuild-date", help="image rebuild date (default: same as date)")
    parser.add_argument("--check", action="store_true", help="verify consistency only")
    args = parser.parse_args()
    if args.check:
        if args.date or args.rebuild_date:
            parser.error("--check takes no dates")
        return check()
    if not args.date:
        parser.error("a date is required unless --check is given")
    horizon = future_horizon()
    for label, value in (
        ("date", args.date),
        ("--rebuild-date", args.rebuild_date or args.date),
    ):
        try:
            parsed = parse_date(value)
        except ValueError as error:
            parser.error(f"{label}: {error}")
        else:
            if parsed > horizon:
                parser.error(
                    f"{label}: {value} is in the future; both managed groups "
                    "record events that have already happened"
                )
    matrix = rewrite(MATRIX_DATE_PATTERNS, args.date)
    rebuild = rewrite(REBUILD_DATE_PATTERNS, args.rebuild_date or args.date)
    print(f"matrix mentions set: {matrix}; rebuild mentions set: {rebuild}")
    status = check()
    if status:
        print(
            "\nThe managed mentions above were written. Each FAIL is a hand-edit "
            "this tool deliberately does not make; the offline gate fails until "
            "they are done. Re-run with --check afterwards."
        )
    return status


if __name__ == "__main__":
    sys.exit(main())
