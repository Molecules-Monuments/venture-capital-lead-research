#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Scaffold the reviewed customization profile, or re-pin its artifact hashes.

`check_customization.py` requires a SHA-256 for each of the twenty governed
artifacts. Computing those by hand is pure toil that says nothing about whether
anyone read the files, so this script fills them from the tree and leaves every
statement of review to the operator: the twenty review flags stay false, the
placeholders stay unreplaced, and `status` stays `CUSTOMIZE_REQUIRED`. The
profile therefore still FAILS validation until a human has actually reviewed
the artifacts and said so.

Use `--update-hashes` after deliberately editing a governed artifact (a changed
thesis, rubric, or source list) to re-pin only the hash map of an existing
profile, leaving every other field untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# Loading this module must not shed bytecode into scripts/__pycache__, which
# verify_release.py --pristine would then report as an undeclared file.
sys.dont_write_bytecode = True

PACKAGE = Path(__file__).resolve().parent.parent
EXAMPLE = PACKAGE / "config/customization-profile.example.json"
TARGET = PACKAGE / "config/customization-profile.json"
LOCK = PACKAGE / "deployment-lock.json"

REBUILD_STEP = (
    "A deployment is already recorded and its image predates this edit. The governed "
    "artifacts under workspaces/ are baked into the derived image read-only and are not "
    "bind-mounted, so this edit does not reach the running gateway until the image is "
    "rebuilt: run ./scripts/bootstrap.sh. Confirm with `python3 -B "
    "scripts/record_images.py --validate-baked-sources deployment-lock.json`."
)


def stale_deployment_step() -> str | None:
    """Return the rebuild instruction when a recorded deployment predates this edit.

    A tree that is ahead of its deployment is a normal intermediate state, so this
    is a required next step rather than a failure — but it must be stated, because
    no other gate in this package can see it (see record_images.py).
    """
    if not LOCK.is_file() or LOCK.is_symlink():
        return None
    try:
        # Imported here, not at module scope: keeps the scaffold usable when
        # record_images cannot be loaded.
        from record_images import baked_sources_digest

        recorded = json.loads(LOCK.read_text(encoding="utf-8")).get("baked_sources_sha256")
        if recorded == baked_sources_digest():
            return None
    except (OSError, ValueError, ImportError):
        # An unreadable or pre-3.0.0 lock cannot prove the image is current
        # either, so say the same thing rather than staying silent.
        pass
    return REBUILD_STEP


class DuplicateKeyError(ValueError):
    pass


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        seen[key] = value
    return seen


def digest(relative: str) -> str:
    path = PACKAGE / relative
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"governed artifact is missing or not a regular file: {relative}")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            value.update(block)
    return value.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise SystemExit(f"cannot read {path.name}: {exc}") from exc


def pin_hashes(profile: dict[str, Any]) -> list[str]:
    review = profile.get("review")
    if not isinstance(review, dict) or not isinstance(review.get("reviewed_artifacts"), dict):
        raise SystemExit("profile has no review.reviewed_artifacts object to pin")
    artifacts = review["reviewed_artifacts"]
    for relative in sorted(artifacts):
        artifacts[relative] = digest(relative)
    return sorted(artifacts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-hashes",
        action="store_true",
        help="re-pin the hash map of the existing profile instead of creating one",
    )
    arguments = parser.parse_args()

    if arguments.update_hashes:
        if not TARGET.is_file():
            raise SystemExit(f"{TARGET.name} does not exist; run without --update-hashes first")
        profile = load(TARGET)
        source = TARGET.name
    else:
        if TARGET.exists():
            raise SystemExit(
                f"{TARGET.name} already exists; refusing to overwrite a reviewed profile "
                "(use --update-hashes to re-pin its artifact hashes)"
            )
        profile = load(EXAMPLE)
        source = EXAMPLE.name

    pinned = pin_hashes(profile)
    rendered = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    # O_EXCL on create so a concurrent run cannot clobber a profile someone is
    # already editing; --update-hashes rewrites in place by design.
    if arguments.update_hashes:
        TARGET.write_text(rendered, encoding="utf-8")
    else:
        with TARGET.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    TARGET.chmod(0o600)

    rebuild_step = stale_deployment_step()
    print(
        json.dumps(
            {
                "result": "OK",
                "written": str(TARGET.relative_to(PACKAGE)),
                "source": source,
                "artifact_hashes_pinned": len(pinned),
                "next_steps": ([rebuild_step] if rebuild_step else [])
                + [
                    "Read every governed artifact listed in review.reviewed_artifacts; "
                    "the hashes only record which bytes you are attesting to.",
                    "Replace every <PLACEHOLDER> value, including organization, "
                    "approvers, channel and model selections.",
                    "Set the twenty review flags to true only for what was actually reviewed.",
                    "Set review.approved_by to a stable ID different from "
                    "organization.deployment_owner, and review.approved_at to an RFC3339 time.",
                    "Set status last, then validate the profile against the deployment "
                    "environment: python3 -B scripts/check_customization.py "
                    "config/customization-profile.json .env  (passing the .env path is "
                    "what binds the reviewed selections to it; the profile alone is not "
                    "the gate).",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
