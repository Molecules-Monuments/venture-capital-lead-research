#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify package inventory self-consistency against its embedded manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


PACKAGE = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PACKAGE / "manifest.json"
RUNTIME_ALLOWED = {
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
# Must equal build_release_manifest.EXCLUDED_PREFIXES; the manifest records the
# set and the contract check below refuses a manifest that disagrees. Every entry
# here is a directory --pristine stops reporting, so this set is kept to the one
# directory that genuinely cannot be declared. Developer tooling belongs beside
# the package, not inside it, precisely so it never needs to appear here.
REVIEW_ONLY_ROOTS = {"_internal"}
# Operator working directories. Their contents are deliberately undeclared —
# `inbox` is the documented document drop point (bind-mounted read-only into the
# gateway) and `quarantine` is a runtime quarantine placeholder (the deployed
# stack mounts the named volume `vc-quarantine` at `/quarantine`, so rejected
# uploads never land in this directory; it stays tolerated as an operator
# working area) — so a system that is actually processing documents would
# otherwise fail --pristine for doing its job. The directories themselves, and
# their tracked .gitkeep, stay declared; only the operator's own files inside
# them are tolerated.
OPERATOR_DATA_ROOTS = {"inbox", "quarantine"}


def tolerated_unreadable(relative: str, declared: set[str]) -> bool:
    """Whether a package path this gate cannot read hides anything it would name.

    Nothing under `_internal/` enters the declared inventory and --pristine never
    reports its contents; `inbox/` and `quarantine/` below their own root hold
    operator payload that is never declared. An unreadable path in either place
    therefore hides nothing this gate would have reported, so refusing on it
    costs the tolerance docs/RUNBOOK.md §9 documents: a deployment doing its job
    (operator payload under `inbox/`, with a directory there not readable by the
    invoking user) failed its own integrity gate while
    `build_release_manifest.py --check` went on passing — the two-checker
    disagreement that reads as tampering.

    There is one predicate because there are two syscalls that can fail. os.walk's
    onerror fires for a directory it cannot ENUMERATE (mode 0000); a directory
    that is readable but not SEARCHABLE (mode 0444, 0644, `chmod a-x`) raises
    nothing there and fails in the loop's own lstat instead. The first was
    classified and the second was not, so --pristine still failed on tolerated
    roots for the second shape. Both callers now ask this function.

    build_release_manifest.tolerated() applies the same rule to the same roots,
    and tests/g7/test_recovery_lifecycle.py runs both scripts over the same
    fixture for every (root, directory mode) pair so the two cannot drift.
    """
    root = relative.split("/", 1)[0]
    if root in REVIEW_ONLY_ROOTS:
        return True
    if root not in OPERATOR_DATA_ROOTS or relative == root:
        return False
    # Never tolerate a DECLARED path. `inbox/.gitkeep` and `quarantine/.gitkeep`
    # are declared package files sitting inside otherwise-tolerated roots, and
    # tolerating them let the sibling builder write a manifest without them
    # while this gate then passed over the reduced inventory.
    return relative not in declared


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def fail(message: str) -> None:
    print(json.dumps({"result": "FAIL", "errors": [message]}, indent=2), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pristine",
        action="store_true",
        help="also reject files not declared by the manifest or allowed runtime set",
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8"), object_pairs_hook=unique_object
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        fail(f"manifest is unavailable or invalid: {exc}")
    if manifest.get("manifest_version") != 1 or manifest.get("package_version") != "3.0.1":
        fail("unsupported manifest/package version")
    if manifest.get("excluded_review_directories") != sorted(REVIEW_ONLY_ROOTS):
        fail("manifest review-only directory contract is missing or unexpected")
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
        fail("manifest file inventory is malformed")
    # Fail closed on an empty inventory. A zero-file list is internally consistent,
    # so every check below would vacuously pass and the gate would report PASS while
    # verifying nothing — which is precisely what a manifest built from a package
    # whose path defeats the builder's exclusion rules looks like. Only zero is
    # rejected: a small package is a legitimate shape, an empty one never is.
    if not entries:
        fail("manifest declares no files; refusing to certify an empty inventory")

    declared: set[str] = set()
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest contains a non-object file entry")
            continue
        relative = entry.get("path")
        if not isinstance(relative, str) or relative.startswith("/") or ".." in Path(relative).parts:
            errors.append(f"unsafe manifest path: {relative!r}")
            continue
        if relative in declared:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        declared.add(relative)
        path = PACKAGE / relative
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise OSError("not a non-symlink regular file")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != entry.get("sha256"):
                errors.append(f"hash mismatch: {relative}")
            if info.st_size != entry.get("size"):
                errors.append(f"size mismatch: {relative}")
            # Git records the executable bit and discards the rest of the mode,
            # so only that bit is part of the release contract. Comparing full
            # permissions here would fail every clone taken under a umask other
            # than 022 while proving nothing about the package's integrity.
            if bool(info.st_mode & stat.S_IXUSR) != entry.get("executable"):
                errors.append(f"executable-bit mismatch: {relative}")
        except OSError as exc:
            errors.append(f"missing/invalid file {relative}: {exc}")

    if args.pristine:
        actual: set[str] = set()

        # os.walk with onerror, never Path.rglob: rglob silently swallows the
        # PermissionError it hits while descending, so a subtree this verifier
        # cannot read simply never appeared in the inventory and --pristine
        # reported PASS over it. An undeclared executable inside a mode-000
        # directory was invisible to this gate, to build_release_manifest.py
        # --check and to `git status` at the same time, which is precisely the
        # tamper signal docs/RUNBOOK.md §9 sends the operator here to read. A
        # directory this gate cannot enumerate is now a finding in its own right.
        def unreadable(exc: OSError) -> None:
            try:
                where = Path(exc.filename).relative_to(PACKAGE).as_posix()
            except (TypeError, ValueError):
                errors.append(f"cannot inspect package path {exc.filename}: {exc}")
                return
            if tolerated_unreadable(where, declared):
                return
            errors.append(f"cannot inspect package path {where}: {exc}")

        for directory, subdirectories, filenames in os.walk(PACKAGE, onerror=unreadable):
            base = Path(directory)
            # Version-control metadata is not part of the deployable package, so
            # prune it rather than walking it and discarding every entry.
            if base == PACKAGE and ".git" in subdirectories:
                subdirectories.remove(".git")
            for name in list(subdirectories) + filenames:
                path = base / name
                relative = path.relative_to(PACKAGE).as_posix()
                if relative == "manifest.json":
                    continue
                # `.git` is version-control metadata whatever its file type. The
                # prune above only removes it from the DIRECTORY list, and a
                # `git worktree` or submodule checkout writes `.git` as a regular
                # FILE — which os.walk hands back in `filenames`, so --pristine
                # reported it as an undeclared file while
                # build_release_manifest.py --check (whose EXCLUDED_PARTS matches
                # by path part, not by type) still passed. That two-checker
                # disagreement is the tamper signal docs/RUNBOOK.md §9 sends the
                # operator to read, raised here by an ordinary checkout layout.
                if relative == ".git" or relative.startswith(".git/"):
                    continue
                try:
                    info = path.lstat()
                except OSError as exc:
                    # Same question the onerror callback asks, because this is
                    # the other syscall that can fail: a directory that is
                    # readable but not searchable hands its names back through
                    # os.walk without error and fails here instead. Classifying
                    # in only one of the two places is what left --pristine
                    # failing on tolerated roots at mode 0444/0644.
                    if not tolerated_unreadable(relative, declared):
                        errors.append(f"cannot inspect package path {relative}: {exc}")
                    continue
                if relative in RUNTIME_ALLOWED:
                    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        errors.append(f"invalid runtime path type: {relative}")
                    continue
                root = relative.split("/", 1)[0]
                if root in REVIEW_ONLY_ROOTS:
                    if relative != root:
                        continue
                    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                        errors.append(f"invalid review-only root type: {relative}")
                    continue
                if root in OPERATOR_DATA_ROOTS and relative != root and relative not in declared:
                    # Operator-supplied payload, not a package file. A symlink here
                    # would still be a real finding: the gateway follows it out of
                    # the intended directory, so keep rejecting those.
                    if stat.S_ISLNK(info.st_mode):
                        errors.append(f"symlink in operator data directory: {relative}")
                    continue
                if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                    continue
                # Every undeclared regular file, symlink, FIFO, socket, device, cache,
                # or editor/OS artifact makes a pristine package fail.
                actual.add(relative)
        unexpected = sorted(actual - declared)
        if unexpected:
            errors.append(f"unexpected files: {unexpected}")

    report = {
        "result": "PASS" if not errors else "FAIL",
        "package_version": manifest.get("package_version"),
        "verified_files": len(declared) - sum(error.startswith("missing/invalid file") for error in errors),
        "declared_files": len(declared),
        "pristine": args.pristine,
        "errors": errors,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
