#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build or verify the deterministic Version 3.0 deployment manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parent.parent
MANIFEST = PACKAGE / "manifest.json"
EXCLUDED_FILES = {
    "manifest.json",
    ".env",
    "config/customization-profile.json",
    "config/connectors.json",
    "config/runtime/openclaw.json",
    "config/runtime/secrets/postgres_owner_password",
    "config/runtime/secrets/openclaw_db_password",
    "config/runtime/secrets/vcops_approval_pepper",
    "config/runtime/secrets/vc_trusted_context_key",
    "deployment-lock.json",
}
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
# Keep in lockstep with verify_release.REVIEW_ONLY_ROOTS: that gate re-reads this
# set from the manifest and fails closed if the two disagree. Everything else in
# the package root is declared, so a stray directory is reported rather than
# silently tolerated — deliberately, since this set is the only blind spot the
# pristine inventory has. The developer venv and the live-testing harness are
# kept beside the package rather than inside it so they need no entry here.
EXCLUDED_PREFIXES = {"_internal"}
# Operator payload, not package files. verify_release.py tolerates anything the
# operator drops here (its OPERATOR_DATA_ROOTS); without the same rule the two
# checkers disagree and an ordinary document drop makes this manifest look
# stale, which docs/RUNBOOK.md §9 would have the operator read as tampering.
# Only the tracked placeholder in each root is a declared package file.
OPERATOR_DATA_ROOTS = {"inbox", "quarantine"}
# The one file inside each operator root that IS a declared package file. Named
# once and used by both inventory() and tolerated(): tolerating it as operator
# payload let an unreadable `inbox/` drop it from the written manifest (331 ->
# 330, exit 0), after which `verify_release.py --pristine` PASSED over the
# reduced inventory because the file it would have missed was no longer declared.
OPERATOR_DATA_DECLARED_NAME = ".gitkeep"
# The complete set of declared paths inside the operator roots. Written as paths,
# not as a basename rule: a `.gitkeep` an operator brings in with a checkout is
# THEIRS, and treating it as a package file is what made the two integrity
# checkers disagree.
DECLARED_OPERATOR_PLACEHOLDERS = frozenset(
    f"{root}/{OPERATOR_DATA_DECLARED_NAME}" for root in OPERATOR_DATA_ROOTS
)


def tolerated(relative: str) -> bool:
    """Whether a path this script cannot read is the operator's business, not tampering.

    A path is only an integrity finding if it could have contributed to the
    inventory: `_internal/` is excluded by contract and `inbox/`/`quarantine/`
    below their own root hold operator payload that is never declared, so an odd
    permission there is not a tamper signal. Refusing on those made an unreadable
    directory under `inbox/` block every re-pin — the step docs/MAINTAINING.md makes
    mandatory after any declared-file change — which is a worse failure than the
    blind spot the guard closes.

    verify_release.tolerated_unreadable() applies the same rule to the same
    roots, and tests/g7/test_recovery_lifecycle.py runs both scripts over the
    same fixture for every (root, directory mode) pair so the two cannot drift:
    a disagreement between the two checkers is the tamper signal
    docs/RUNBOOK.md §9 sends the operator to read.
    """
    root = relative.split("/", 1)[0]
    if root in EXCLUDED_PREFIXES:
        return True
    if root not in OPERATOR_DATA_ROOTS or relative == root:
        return False
    # The declared placeholder is `<root>/.gitkeep` and nothing else. Deciding by
    # BASENAME instead made this script refuse any `.gitkeep` at any depth, while
    # verify_release.py decided by manifest membership and tolerated the same
    # path — so an operator dropping a repo checkout into `inbox/` (one that
    # carries its own `.gitkeep`) made the two checkers disagree, which
    # docs/RUNBOOK.md §9 tells them to read as tampering. Measured on 06b307a.
    # inventory() below declares exactly these two paths, so the two scripts now
    # partition the same world.
    return relative not in DECLARED_OPERATOR_PLACEHOLDERS


def walk_package() -> list[tuple[Path, os.stat_result]]:
    """Every path under the package with its own lstat, refusing to guess about what it cannot read.

    os.walk with onerror, never Path.rglob: rglob swallows the PermissionError it
    hits while descending, so an unreadable subtree would be omitted from the
    inventory in silence — and a later `verify_release.py --pristine` would then
    agree with a manifest that never saw those files, so both integrity signals
    would pass over an undeclared payload. Omitting a subtree here is worse than
    failing, so this raises instead.

    The lstat is taken HERE rather than in inventory() so that exactly one place
    can fail to read a path. There are two syscalls that can fail and only one of
    them reaches os.walk's onerror: a directory that is readable but not
    SEARCHABLE (mode 0444, 0644, `chmod a-x`) raises nothing during the walk —
    it hands its names back in `filenames` — and inventory()'s former
    `Path.is_file()` filter turned the resulting stat-level PermissionError into
    a plain False, dropping the entry in silence. Measured: with `docs/` at mode
    0444 the write path exited 0 reporting "Manifest written: 321 files" having
    dropped all ten declared `docs/*` files from the release inventory, which is
    precisely the omission the refusal below claims to prevent.
    """
    unreadable: list[str] = []

    def record(filename: "str | os.PathLike[str] | None", exc: OSError) -> None:
        try:
            # `Path(filename)`, not `Path(str(filename))`: str() always succeeds,
            # so the TypeError arm below was unreachable here while the identical
            # arm in verify_release.py was live — two callbacks that read as
            # equivalent and were not. os.scandir sets exc.filename to None on
            # some errors, and Path(None) is what raises.
            # ty: ignore[invalid-argument-type] — passing the possibly-None
            # filename is the point: `Path(None)` is what raises the TypeError
            # the handler below catches, and narrowing it away here would make
            # that arm unreachable, which is the defect this replaced.
            where = Path(filename).relative_to(PACKAGE).as_posix()
        except (TypeError, ValueError):
            unreadable.append(f"{filename}: {exc}")
            return
        if tolerated(where):
            return
        unreadable.append(f"{where}: {exc}")

    def note(exc: OSError) -> None:
        record(exc.filename, exc)

    found: list[tuple[Path, os.stat_result]] = []
    for directory, subdirectories, filenames in os.walk(PACKAGE, onerror=note):
        base = Path(directory)
        if base == PACKAGE and ".git" in subdirectories:
            subdirectories.remove(".git")
        for name in list(subdirectories) + filenames:
            path = base / name
            try:
                found.append((path, path.lstat()))
            except OSError as exc:
                record(path, exc)
    if unreadable:
        raise SystemExit(
            "cannot enumerate the package: "
            + "; ".join(sorted(unreadable))
            + ". Refusing to write a manifest that omits a subtree it could not "
              "read — a silent omission here would make a later "
              "`verify_release.py --pristine` agree with an inventory that never "
              "saw those files (docs/RUNBOOK.md §9)."
        )
    return sorted(found, key=lambda pair: pair[0])


def inventory() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path, info in walk_package():
        relative = path.relative_to(PACKAGE).as_posix()
        if (
            # Shape-filter on the lstat walk_package() already took, never on
            # Path.is_file()/Path.is_symlink(): those re-stat the path and turn a
            # PermissionError into a plain False, which is how files this script
            # could not read were dropped from the inventory in silence.
            # `S_ISREG` on an lstat is exactly the old `is_file() and not
            # is_symlink()` — a symlink's own lstat is never S_ISREG — so
            # symlinks, directories, fifos, sockets and devices are all excluded
            # by this single test, and a path that could not be stat'd never
            # reaches here because walk_package() refused.
            not stat.S_ISREG(info.st_mode)
            or relative in EXCLUDED_FILES
            or relative.split("/", 1)[0] in EXCLUDED_PREFIXES
            # Match on the package-relative path. `path.parts` is absolute, so a
            # package that merely *lives* under a directory named .git,
            # __pycache__, .pytest_cache or .ruff_cache would exclude every file
            # and silently produce a 0-file manifest.
            or any(part in EXCLUDED_PARTS for part in Path(relative).parts)
            or path.suffix in EXCLUDED_SUFFIXES
            or path.name == ".DS_Store"
            or (
                relative.split("/", 1)[0] in OPERATOR_DATA_ROOTS
                and relative not in DECLARED_OPERATOR_PLACEHOLDERS
            )
        ):
            continue
        try:
            payload = path.read_bytes()
        except OSError as exc:
            # A regular file whose own mode denies the read stats perfectly well,
            # so walk_package()'s guard cannot see it. Refusing here keeps the
            # promise that no manifest is written over a path this script could
            # not read; before this, the read raised an uncaught traceback.
            raise SystemExit(
                f"cannot read package file {relative}: {exc}. Refusing to write a "
                "manifest that omits a file it could not read "
                "(docs/RUNBOOK.md §9)."
            ) from exc
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": info.st_size,
                # Only the executable bit is recorded. Git carries that bit and
                # nothing else, so a manifest that pinned full permissions would
                # make every clone taken under a umask other than 022 fail the
                # integrity gate for a reason that says nothing about integrity.
                # Content is bound by sha256; the exec bit is bound because it
                # is the one permission that changes how a file is treated.
                "executable": bool(info.st_mode & stat.S_IXUSR),
            }
        )
    return entries


def expected_manifest() -> dict[str, Any]:
    files = inventory()
    return {
        "manifest_version": 1,
        "package": "vc-lead-research",
        "package_version": "3.0.1",
        "created_on": "2026-07-20",
        "based_on": {
            "package_version": "2.0.0",
            "ground_source": "OpenClaw - Runbook Lead Research.md",
            "ground_source_revision": "2026-06-10"
        },
        "upstream": {
            "openclaw": {
                "version": "2026.8.1",
                "commit": "ea806575e6450e4d1efdfc72c19f04be982a1b9b",
                "image": (
                    "ghcr.io/openclaw/openclaw:2026.8.1@"
                    "sha256:e7849cb6c1ef1ead39ab4be7d85edb2df89611f486e283284c7cf35ce39a20d4"
                ),
            },
            "lobster": {
                "version": "2026.6.11",
                "commit": "86b8cc20a867f18c08ae8e3f4fec9ee7d52bf8c9",
            },
            "postgres_image": (
                "postgres:17.10-bookworm@"
                "sha256:4f736ae292687621d4dbe0d499ffd024a36bd2ee7d8ca6f2ccd4c800f047b394"
            ),
        },
        "release_state": {
            "package_readiness": "production-ready within the retained Version 3 release-gate scope",
            "deployment_exclusions": (
                "live provider/recovery exercises, jurisdiction-specific customization, "
                "and target-runtime capacity testing"
            ),
            "customization_profile": "required and excluded from distribution manifest",
            "default_primary_channel": "none",
            "optional_primary_channels": ["slack", "msteams", "discord", "telegram"],
        },
        "excluded_runtime_files": sorted(EXCLUDED_FILES - {"manifest.json"}),
        "excluded_review_directories": sorted(EXCLUDED_PREFIXES),
        "file_count": len(files),
        "files": files,
    }


def manifest_delta(expected: dict[str, Any]) -> dict[str, list[str]] | None:
    """Paths removed, added and changed against the declared manifest.

    Returns None when manifest.json is missing or unreadable — that is an
    informational state, not a delta, and callers must not read it as one.

    The delta is exposed separately from the printable summary because the
    summary is truncated: deciding anything from the printed lines makes
    truncation decide it too. That is exactly how the removal warning below was
    lost — see main().
    """
    try:
        declared = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    was = {entry["path"]: entry for entry in declared.get("files", [])}
    now = {entry["path"]: entry for entry in expected["files"]}
    return {
        "removed": sorted(set(was) - set(now)),
        "added": sorted(set(now) - set(was)),
        "changed": sorted(
            path for path in set(was) & set(now) if was[path] != now[path]
        ),
    }


def manifest_differences(expected: dict[str, Any], limit: int = 20) -> list[str]:
    """Summarize how the declared manifest differs from the current tree.

    Six line kinds can come back and only three of them are delta lines:
    `removed:`, `added:` and `changed:` paths, plus the informational
    "manifest.json is missing or unreadable" and "file inventory matches; a
    manifest header field differs", plus the "... and N more" truncation
    marker. A caller that captions this list has to caption the three delta
    kinds by name, not "each line above".
    """
    delta = manifest_delta(expected)
    if delta is None:
        return ["manifest.json is missing or unreadable"]
    # Removals sort first because this list is truncated at `limit`. Building
    # `added:` lines first meant any re-pin with 20 or more additions dropped
    # every `removed:` line, so a deleted hash-pinned reviewed artifact was
    # absorbed with nothing on screen naming it.
    lines = [f"removed: {path}" for path in delta["removed"]]
    lines += [f"added: {path}" for path in delta["added"]]
    lines += [f"changed: {path}" for path in delta["changed"]]
    if not lines:
        return ["file inventory matches; a manifest header field differs"]
    return lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else [])


def read_manifest_text() -> str | None:
    """The declared manifest's bytes, or None when it cannot be read.

    A present-but-unreadable `manifest.json` (root-owned 0600, or a mount the
    operator cannot read) raised an uncaught PermissionError out of both modes,
    on a script whose whole job is an operator-actionable integrity verdict —
    while `verify_release.py` reported the same state as a clean one-line error.
    `manifest_differences()` already enumerates "manifest.json is missing or
    unreadable"; this is what makes that line reachable rather than aspirational.
    """
    try:
        return MANIFEST.read_text(encoding="utf-8")
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    expected = expected_manifest()
    rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not MANIFEST.is_file() or read_manifest_text() != rendered:
            # Name what differs and what to do about it. A bare mismatch line
            # sends the operator to the runbook's tampering procedure even when
            # the cause is a customization they deliberately made.
            print("manifest does not match the current deployable package", file=sys.stderr)
            for line in manifest_differences(expected):
                print(f"  {line}", file=sys.stderr)
            print(
                "If these changes are deliberate (customized policy artifacts, a new "
                'file), re-pin the inventory with "python3 -B scripts/build_release_manifest.py". '
                "If they are not, treat it as an integrity finding (docs/RUNBOOK.md §9).",
                file=sys.stderr,
            )
            return 1
        print(f"Manifest verified: {expected['file_count']} files")
        return 0
    # Name what this write absorbs. docs/RUNBOOK.md §9 asks the operator to
    # re-pin only changes they can account for, and they cannot do that if the
    # write path reports a bare file count while silently promoting a stray
    # backup, note or editor artifact into declared release content — which is
    # exactly the debris `verify_release.py --pristine` rejected a moment
    # earlier. Compute the delta before overwriting the declared inventory.
    up_to_date = MANIFEST.is_file() and read_manifest_text() == rendered
    # Both are read before the write, which overwrites what they measure against.
    delta = None if up_to_date else manifest_delta(expected)
    changes = [] if up_to_date else manifest_differences(expected)
    try:
        MANIFEST.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        # An operator-actionable verdict, not a traceback. This script exists to
        # tell the operator what the integrity state is; a present-but-unwritable
        # manifest.json (root-owned, a read-only mount) is a state they can fix,
        # and the sibling verifier already reports its equivalent as one line.
        print(f"cannot write {MANIFEST.name}: {exc}", file=sys.stderr)
        return 1
    print(f"Manifest written: {expected['file_count']} files")
    if changes:
        print("Re-pinned against the current tree:", file=sys.stderr)
        for line in changes:
            print(f"  {line}", file=sys.stderr)
        # The caption names the three delta kinds instead of saying "each line".
        # "now declared release content" was wrong for `removed:` — a removed
        # path is precisely what is no longer declared — and "each line" is
        # wrong for the two informational lines manifest_differences can return
        # ("manifest.json is missing or unreadable" on a first build, "file
        # inventory matches; a manifest header field differs") and for the
        # "... and N more" marker, none of which is an absorbed change.
        print(
            "Each `removed:`, `added:` or `changed:` line above is a change this "
            "re-pin has just absorbed into the declared inventory. If any of them "
            "is not a change you made deliberately, treat it as an integrity "
            "finding (docs/RUNBOOK.md §9) rather than a re-pin.",
            file=sys.stderr,
        )
        # Derived from the untruncated delta, never from `changes`. Keyed off the
        # printed lines, this warning was suppressed by the very truncation it
        # was printed from: a re-pin that added twenty files dropped every
        # `removed:` line, so deleting a hash-pinned reviewed artifact — the
        # highest-signal case docs/MAINTAINING.md makes reading this delta a
        # binding step for — was absorbed in silence. Every removed path is
        # named, uncapped: for the one delta kind that takes content away,
        # completeness beats brevity.
        if delta and delta["removed"]:
            print(
                "These paths are no longer declared at all; confirm you deleted "
                "each one deliberately before trusting this manifest:",
                file=sys.stderr,
            )
            for path in delta["removed"]:
                print(f"  removed: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
