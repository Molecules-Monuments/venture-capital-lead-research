# SPDX-License-Identifier: Apache-2.0
"""The snapshot.debian.org rebuild recipe must stay current, and stay one recipe.

`Dockerfile.openclaw` pins ten Debian package versions. The other 38 packages
its `apt-get install` step adds to the base image carry no pin at all, so what
actually reproduces them is the `snapshot.debian.org` timestamp in the recovery
recipe — and that recipe is written twice, in `docs/RUNBOOK.md` §11 and in the
`RECOVERY` comment of `Dockerfile.openclaw`.

Two failures were measured against the shipped release and are what this suite
pins:

* The documented timestamp was derived from the last apt-pin change rather than
  from the date the reviewed image was built. At `20260805T000000Z` a
  snapshot-only install resolved `libnss3` to `2:3.87.1-1+deb12u3`, one
  bookworm-security revision behind the `2:3.87.1-1+deb12u4` the reviewed image
  carries. The rebuild date recorded at the time of that measurement
  (`20260811T000000Z`) did supply it; the current recorded date is read from
  the evidence documents rather than restated here.
* The recipe added its snapshot archives without displacing the base image's own
  `/etc/apt/sources.list.d/debian.sources`. Both then sit at priority 500 and
  apt takes the higher version, so the snapshot decided nothing — measured: with
  that file present, `libnss3` resolved from `deb.debian.org`.

The rebuild date is not restated here. It is read from the evidence documents
through the same patterns `scripts/set_evidence_execution_date.py` maintains, so
moving the date with the mandated tool moves this test's expectation with it.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import set_evidence_execution_date as evidence_dates  # noqa: E402

# The two places the recovery recipe is written. Both are read as text; neither
# is executed here.
RECIPE_SOURCES = ("docs/RUNBOOK.md", "Dockerfile.openclaw")

# Only the assignment form is matched, so the RUNBOOK's prose counter-example
# (a bare `20260805T000000Z` naming the timestamp that resolves one revision
# behind) is not mistaken for a second recipe.
# Group 1 is the whole literal, groups 2-4 its date. The agreement test needs
# the literal: two copies naming the same day at different times point at two
# different snapshot archives, and so at two different sets of installed bytes.
SNAPSHOT_ASSIGNMENT = re.compile(r"SNAPSHOT=((\d{4})(\d{2})(\d{2})T\d{6}Z)")

# The line that makes the snapshot authoritative rather than merely present.
DISPLACE_BASE_SOURCES = "rm -f /etc/apt/sources.list.d/debian.sources"

# Both copies of the recipe quote the recorded rebuild date in prose, with and
# without Markdown emphasis.
QUOTED_REBUILD_DATE = re.compile(r"V3_RELEASE_EVIDENCE\.md`? records \*{0,2}(\d{4}-\d{2}-\d{2})")


def recipe_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class SnapshotRecipeCurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshots = {
            relative: SNAPSHOT_ASSIGNMENT.findall(recipe_text(relative))
            for relative in RECIPE_SOURCES
        }
        # collect() returns every (document, date) the rebuild-date patterns
        # match across the four evidence documents. Its own --check mode is what
        # proves they agree; this suite takes the most recent one so a snapshot
        # can never sit behind the newest recorded rebuild.
        cls.rebuild_dates = [date for _, date in evidence_dates.collect(
            evidence_dates.REBUILD_DATE_PATTERNS
        )]

    def test_each_recipe_source_carries_exactly_one_snapshot_timestamp(self) -> None:
        counts = {relative: len(found) for relative, found in self.snapshots.items()}
        self.assertEqual(
            counts,
            dict.fromkeys(RECIPE_SOURCES, 1),
            "the recovery recipe must appear exactly once in each source, as a "
            f"`SNAPSHOT=<timestamp>` assignment; found {counts}. A zero means "
            "the recipe moved or was reworded and this suite is no longer "
            "reading it; a two means there are now two timestamps to keep "
            "current.",
        )

    def test_both_recipe_sources_agree_on_the_snapshot_timestamp(self) -> None:
        stated = {relative: found for relative, found in self.snapshots.items() if found}
        distinct = {found[0][0] for found in stated.values()}
        self.assertEqual(
            len(distinct),
            1,
            "docs/RUNBOOK.md and Dockerfile.openclaw give different "
            f"snapshot.debian.org timestamps: {stated}. They document one "
            "rebuild recipe, so an operator following either must point apt at "
            "the same archive.",
        )

    def test_snapshot_timestamp_is_not_earlier_than_the_recorded_image_rebuild(self) -> None:
        self.assertTrue(
            self.rebuild_dates,
            "no image-rebuild date was found in the evidence documents through "
            "scripts/set_evidence_execution_date.py's REBUILD_DATE_PATTERNS, so "
            "the snapshot timestamp cannot be checked against anything",
        )
        latest_rebuild = max(self.rebuild_dates).replace("-", "")
        for relative, found in self.snapshots.items():
            for parts in found:
                self.assertGreaterEqual(
                    "".join(parts[1:4]),
                    latest_rebuild,
                    f"{relative} points apt at snapshot {'-'.join(parts[1:4])}, which "
                    f"predates the {max(self.rebuild_dates)} rebuild the evidence "
                    "documents record. A snapshot taken before the reviewed image "
                    "was built can resolve a package to an older revision than the "
                    "image actually carries.",
                )

    def test_both_recipe_sources_displace_the_base_image_source_list(self) -> None:
        missing = [
            relative
            for relative in RECIPE_SOURCES
            if DISPLACE_BASE_SOURCES not in recipe_text(relative)
        ]
        self.assertEqual(
            missing,
            [],
            f"the recovery recipe in {missing} no longer contains "
            f"`{DISPLACE_BASE_SOURCES}`. Without it the base image's "
            "deb.debian.org source list stays enabled at the same priority as "
            "the snapshot archives and apt takes the higher version, so the "
            "pinned timestamp stops deciding which bytes get installed.",
        )

    def test_recipe_prose_quotes_the_recorded_rebuild_date(self) -> None:
        quoted = {
            relative: QUOTED_REBUILD_DATE.findall(recipe_text(relative))
            for relative in RECIPE_SOURCES
        }
        self.assertEqual(
            {relative: len(found) for relative, found in quoted.items()},
            dict.fromkeys(RECIPE_SOURCES, 1),
            "each recipe source must quote the recorded rebuild date exactly "
            f"once, as \"V3_RELEASE_EVIDENCE.md records <date>\"; found {quoted}",
        )
        latest_rebuild = max(self.rebuild_dates)
        for relative, found in quoted.items():
            for date in found:
                self.assertEqual(
                    date,
                    latest_rebuild,
                    f"{relative} tells the operator the reviewed image was built "
                    f"on {date}, but the evidence documents record "
                    f"{latest_rebuild}. This date is hand-written prose, not "
                    "managed by scripts/set_evidence_execution_date.py, so it "
                    "goes stale on the next rebuild unless it is corrected here.",
                )


    def test_every_timestamp_literal_is_the_recipe_or_a_named_counter_example(self) -> None:
        """No third restatement of the recipe's timestamp may go unbound.

        The five checks above read only the `SNAPSHOT=` assignment form, so a
        bare timestamp in prose is invisible to them. One such restatement was
        written five lines below the recipe block and survived a simulated
        rebuild with the whole suite green, while naming a pre-build timestamp —
        the exact trap the surrounding paragraph warns about. Pin the world
        instead of the instance: every `<8 digits>T<6 digits>Z` literal in a
        recipe source must be either that file's own recipe timestamp or one of
        the counter-examples this section deliberately quotes.
        """
        allowed_counter_examples = {
            # Resolves all ten pins and still installs libnss3 one
            # bookworm-security revision behind: the silent-failure case.
            "20260805T000000Z",
            # Before libpoppler126=22.12.0-2+deb12u3 entered the archive: the
            # loud-failure case.
            "20260731T000000Z",
        }
        for relative in RECIPE_SOURCES:
            with self.subTest(source=relative):
                text = recipe_text(relative)
                recipe = {found[0] for found in SNAPSHOT_ASSIGNMENT.findall(text)}
                unbound = sorted(
                    {
                        literal
                        for literal in re.findall(r"\d{8}T\d{6}Z", text)
                        if literal not in recipe and literal not in allowed_counter_examples
                    }
                )
                self.assertEqual(
                    unbound, [],
                    f"{relative} states timestamp(s) {unbound} that are neither its "
                    f"`SNAPSHOT=` recipe value {sorted(recipe)} nor a counter-example "
                    "this test names. A bare timestamp in prose is not read by the "
                    "other checks here, so it silently goes stale on the next image "
                    "rebuild — and a stale one is a pre-build timestamp. Refer to the "
                    "recipe's own value rather than restating it, or add the literal "
                    "here with the reason it is quoted.",
                )


if __name__ == "__main__":
    unittest.main()
