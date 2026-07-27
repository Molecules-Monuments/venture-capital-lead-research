#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Verify package inventory self-consistency against its embedded manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
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
REVIEW_ONLY_ROOTS = {"_internal"}


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
    if manifest.get("manifest_version") != 1 or manifest.get("package_version") != "3.0.0":
        fail("unsupported manifest/package version")
    if manifest.get("excluded_review_directories") != sorted(REVIEW_ONLY_ROOTS):
        fail("manifest review-only directory contract is missing or unexpected")
    entries = manifest.get("files")
    if not isinstance(entries, list) or manifest.get("file_count") != len(entries):
        fail("manifest file inventory is malformed")

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
            if format(stat.S_IMODE(info.st_mode), "04o") != entry.get("mode"):
                errors.append(f"mode mismatch: {relative}")
        except OSError as exc:
            errors.append(f"missing/invalid file {relative}: {exc}")

    if args.pristine:
        actual: set[str] = set()
        for path in PACKAGE.rglob("*"):
            relative = path.relative_to(PACKAGE).as_posix()
            if relative == "manifest.json":
                continue
            # Version-control metadata is not part of the deployable package.
            if relative == ".git" or relative.startswith(".git/"):
                continue
            try:
                info = path.lstat()
            except OSError as exc:
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
