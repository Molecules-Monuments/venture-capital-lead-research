#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Build or verify the deterministic Version 3.0 deployment manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
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
# Top-level directories that live in the package directory but are never part
# of the distribution: internal review material, the machine-specific developer
# venv, and the live-testing harness that drives throwaway deployments. Keep in
# lockstep with verify_release.REVIEW_ONLY_ROOTS — that gate re-reads this set
# from the manifest and fails closed if the two disagree.
EXCLUDED_PREFIXES = {"_internal", "openclaw-v3-dev-venv", "v3-live-testing"}
# Operator payload, not package files. verify_release.py tolerates anything the
# operator drops here (its OPERATOR_DATA_ROOTS); without the same rule the two
# checkers disagree and an ordinary document drop makes this manifest look
# stale, which docs/RUNBOOK.md §9 would have the operator read as tampering.
# Only the tracked placeholder in each root is a declared package file.
OPERATOR_DATA_ROOTS = {"inbox", "quarantine"}


def inventory() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(PACKAGE.rglob("*")):
        relative = path.relative_to(PACKAGE).as_posix()
        if (
            not path.is_file()
            or path.is_symlink()
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
                and path.name != ".gitkeep"
            )
        ):
            continue
        info = path.stat()
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
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
        "package": "openclaw-lead-research",
        "package_version": "3.0.0",
        "created_on": "2026-07-20",
        "based_on": {
            "package_version": "2.0.0",
            "ground_source": "OpenClaw - Runbook Lead Research.md",
            "ground_source_revision": "2026-06-10"
        },
        "upstream": {
            "openclaw": {
                "version": "2026.7.1",
                "commit": "2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4",
                "image": (
                    "ghcr.io/openclaw/openclaw:2026.7.1@"
                    "sha256:6a31d44b2944e7adcd2b582bf6fb463111264ebca97a0201795b799135bd102c"
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


def manifest_differences(expected: dict[str, Any], limit: int = 20) -> list[str]:
    """Summarize how the declared manifest differs from the current tree."""
    try:
        declared = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ["manifest.json is missing or unreadable"]
    was = {entry["path"]: entry for entry in declared.get("files", [])}
    now = {entry["path"]: entry for entry in expected["files"]}
    lines = [f"added: {path}" for path in sorted(set(now) - set(was))]
    lines += [f"removed: {path}" for path in sorted(set(was) - set(now))]
    lines += [
        f"changed: {path}"
        for path in sorted(set(was) & set(now))
        if was[path] != now[path]
    ]
    if not lines:
        return ["file inventory matches; a manifest header field differs"]
    return lines[:limit] + ([f"... and {len(lines) - limit} more"] if len(lines) > limit else [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    expected = expected_manifest()
    rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != rendered:
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
    changes = (
        []
        if MANIFEST.is_file() and MANIFEST.read_text(encoding="utf-8") == rendered
        else manifest_differences(expected)
    )
    MANIFEST.write_text(rendered, encoding="utf-8")
    print(f"Manifest written: {expected['file_count']} files")
    if changes:
        print("Re-pinned against the current tree:", file=sys.stderr)
        for line in changes:
            print(f"  {line}", file=sys.stderr)
        print(
            "Each line above is now declared release content. If any of them is "
            "not a change you made deliberately, treat it as an integrity "
            "finding (docs/RUNBOOK.md §9) rather than a re-pin.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
