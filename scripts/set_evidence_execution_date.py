# SPDX-License-Identifier: 0BSD
"""Set or check the canonical re-execution dates across the evidence documents.

The four evidence documents state, in several phrasings each, (a) the date the
full gate matrix was last re-executed and (b) the date the derived image was
last rebuilt with ``docker build --no-cache --pull``. Two consecutive audit
passes each found one of these hand-edited dates left stale (one instance
missed out of eight), so hand-editing them is a demonstrated defect class:
this script is the only supported way to move them.
``tests/v3/test_evidence_doc_consistency.py`` imports the patterns below and
fails the offline gate whenever the stated dates diverge.

Usage:
    python3 -B scripts/set_evidence_execution_date.py 2026-08-10
    python3 -B scripts/set_evidence_execution_date.py 2026-08-10 --rebuild-date 2026-08-09
    python3 -B scripts/set_evidence_execution_date.py --check

Setting rewrites every matrix-date mention to the given date and every
rebuild-date mention to ``--rebuild-date`` (default: the same date). The
matrix group includes the G8 re-run and retrieval-benchmark re-run mentions,
which move with every full matrix re-execution. ``--check`` verifies that
each group is internally consistent and prints both dates. Historical dates
(the original 2026-07-23 execution, the retrieval-gate run-history *list* in
V3_RELEASE_EVIDENCE — append today's date there by hand when the scale gate
re-runs — and per-finding re-check dates) are deliberately not managed here:
they are records of past events, not statements about the current tree.
"""

import argparse
import re
import sys
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


def collect(patterns: tuple[re.Pattern[str], ...]) -> list[tuple[str, str]]:
    """Return every (document, date) the patterns match, in document order."""
    found: list[tuple[str, str]] = []
    for relative in EVIDENCE_DOCS:
        text = (PACKAGE / relative).read_text(encoding="utf-8")
        for pattern in patterns:
            found.extend((relative, match.group("date")) for match in pattern.finditer(text))
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


def check() -> int:
    status = 0
    for label, patterns in (
        ("matrix re-execution", MATRIX_DATE_PATTERNS),
        ("image rebuild", REBUILD_DATE_PATTERNS),
    ):
        found = collect(patterns)
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
    for value in (args.date, args.rebuild_date or args.date):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            parser.error(f"not a YYYY-MM-DD date: {value}")
    matrix = rewrite(MATRIX_DATE_PATTERNS, args.date)
    rebuild = rewrite(REBUILD_DATE_PATTERNS, args.rebuild_date or args.date)
    print(f"matrix mentions set: {matrix}; rebuild mentions set: {rebuild}")
    return 0 if check() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
