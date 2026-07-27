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
EXCLUDED_PREFIXES = {"_internal"}


def inventory() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(PACKAGE.rglob("*")):
        relative = path.relative_to(PACKAGE).as_posix()
        if (
            not path.is_file()
            or path.is_symlink()
            or relative in EXCLUDED_FILES
            or relative.split("/", 1)[0] in EXCLUDED_PREFIXES
            or any(part in EXCLUDED_PARTS for part in path.parts)
            or path.suffix in EXCLUDED_SUFFIXES
            or path.name == ".DS_Store"
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


def expected_manifest() -> dict[str, object]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()
    expected = expected_manifest()
    rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != rendered:
            print("manifest does not match the current deployable package", file=sys.stderr)
            return 1
        print(f"Manifest verified: {expected['file_count']} files")
        return 0
    MANIFEST.write_text(rendered, encoding="utf-8")
    print(f"Manifest written: {expected['file_count']} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
