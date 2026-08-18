# SPDX-License-Identifier: 0BSD
"""The citation-prefix rule in TASKFLOW_LOBSTER_COMPATIBILITY.md is a closed rule.

That document's header tells the reader that `upstream_openclaw/` and
`upstream_lobster/` mark paths in the two upstream repositories, which are not
files in this package. The reader's inverse inference — an unprefixed path is a
file in the release — is one the document itself invites, because it also cites
genuinely in-package paths such as `runtime-packages/package-lock.json` in
exactly the same bare form.

Six citations broke that rule by naming upstream repository paths
(`src/tasks/...`, `extensions/lobster/...`) with no prefix, sending a reader to
search the release for files that were never in it. Restating the rule in prose
is what let them drift; this suite enumerates the world instead. Every
backticked `<path>:<lines>` citation in the document must land in exactly one of
four categories, and a citation that lands in none fails here.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/TASKFLOW_LOBSTER_COMPATIBILITY.md"
TEXT = DOC.read_text(encoding="utf-8")

UPSTREAM_PREFIXES = ("upstream_openclaw/", "upstream_lobster/")
# One constant for both methods. The classifier accepted any "@clawdbot/"
# path while the header rule and the sibling test sanctioned only the
# "@clawdbot/lobster/" subtree, so a citation into a different @clawdbot
# package was silently classified as shipped-in-the-image.
IMAGE_PACKAGE_PREFIX = "@clawdbot/lobster/"

# A citation is a backticked path followed by one or more line ranges:
# `upstream_lobster/src/workflows/file.ts:57-87,592-602,1261-1271`. The path
# part rejects backticks and whitespace, so a prose sentence spanning a backtick
# pair cannot be read as a path. The document's third short form — a line range
# with no path at all, continuing the file cited just before it — carries no
# path to classify and is therefore outside this pattern by construction.
CITATION_RE = re.compile(r"`([^`\s]+):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)`")


def citations() -> list[tuple[int, str, str]]:
    """Every citation in the document as (line number, path, full text)."""
    found = []
    for number, line in enumerate(TEXT.splitlines(), 1):
        for match in CITATION_RE.finditer(line):
            found.append((number, match.group(1), match.group(0)))
    return found


def upstream_paths_on(line_number: int) -> list[str]:
    """The prefixed citation paths sharing a line with `line_number`.

    Markdown paragraphs in this document are single physical lines, so the line
    is the paragraph: the locality the header promises for a bare file name.
    """
    line = TEXT.splitlines()[line_number - 1]
    return [
        match.group(1)
        for match in CITATION_RE.finditer(line)
        if match.group(1).startswith(UPSTREAM_PREFIXES)
    ]


class TaskflowCitationPathTests(unittest.TestCase):
    def test_every_citation_lands_in_a_declared_category(self):
        found = citations()
        # Non-vacuity: a pattern that stopped matching would otherwise report a
        # clean sweep of nothing.
        self.assertGreater(
            len(found), 40,
            f"CITATION_RE matched only {len(found)} citations in {DOC.name}; the "
            "pattern no longer fits the document",
        )
        unclassified = []
        for number, path, text in found:
            if path.startswith(UPSTREAM_PREFIXES):
                continue                       # 1. an upstream repository path
            if (ROOT / path).is_file():
                continue                       # 2. a file in this package
            if "/" not in path and upstream_paths_on(number):
                continue                       # 3. bare name, repository named alongside
            if path.startswith(IMAGE_PACKAGE_PREFIX):
                continue                       # 4. installed in the pinned image
            unclassified.append(f"{DOC.name}:{number} {text}")
        self.assertEqual(
            unclassified, [],
            "these citations are none of: prefixed with "
            f"{' or '.join(UPSTREAM_PREFIXES)}; an existing file in this package; "
            "a bare file name in a paragraph that also carries a prefixed "
            "citation; a path installed in the pinned image. A reader will "
            "search the release for them and find nothing. Prefix the upstream "
            f"ones rather than relaxing this rule: {unclassified}",
        )

    def test_the_header_states_the_rule_the_categories_enforce(self):
        # Without this the prose the categories above encode could be deleted
        # while the enumeration stayed green, leaving the rule enforced but
        # unexplained to the reader it exists for.
        # Pin the anchor before using it. `str.split` on an absent separator
        # returns the whole document, so a renamed heading silently widened
        # this check from the header to the entire file -- passing for the
        # wrong reason instead of failing.
        # `assertTrue(x in TEXT, ...)` rather than `assertIn(x, TEXT, ...)`:
        # unittest's standard message renders the container, and TEXT is the
        # whole 39 KB document. That failure measured 40,717 bytes against
        # 1,023 for this form, and verify_offline.py keeps only the last
        # 20,000 characters of the run as the operator-facing detail -- one
        # renamed heading would have evicted every other failure from the
        # gate's report.
        anchor = "## Release verdict"
        self.assertTrue(
            anchor in TEXT,
            f"{DOC.name} no longer contains {anchor!r}, so this test can no "
            "longer tell the header from the body; restore the heading or "
            "update the anchor",
        )
        header = TEXT.split(anchor, 1)[0]
        # Same reason as above, at 1.5 KB a shot: the header is a document
        # slice, and three subTests plus the closing check could spend 6 KB of
        # the gate's 20,000-character detail budget re-printing it.
        for required in (*UPSTREAM_PREFIXES, IMAGE_PACKAGE_PREFIX):
            with self.subTest(required=required):
                self.assertTrue(
                    f"`{required}`" in header,
                    f"the header no longer names {required}, but "
                    f"{Path(__file__).name} still admits citations on that basis",
                )
        self.assertTrue(
            Path(__file__).name in header,
            "the header no longer points the reader at the suite that enforces "
            "its citation rule",
        )

    def test_the_upstream_repository_subtrees_are_cited_consistently(self):
        # The six repaired citations were repo-relative paths under subtrees the
        # document elsewhere cites with a prefix, which is what identified them.
        # Assert that same-basename pairs never disagree about their prefix, so a
        # future half-prefixed pair is caught by measurement rather than by
        # someone noticing.
        by_basename: dict[str, set[str]] = {}
        for _number, path, _text in citations():
            if "/" not in path:
                continue
            by_basename.setdefault(path.rsplit("/", 1)[1], set()).add(path)
        split = {
            name: sorted(paths)
            for name, paths in by_basename.items()
            if len({p.startswith(UPSTREAM_PREFIXES) for p in paths}) > 1
        }
        self.assertEqual(
            {}, split,
            "the same file name is cited both with and without an upstream "
            f"prefix: {split}. One of the two spellings is wrong.",
        )


if __name__ == "__main__":
    unittest.main()
