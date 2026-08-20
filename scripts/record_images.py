#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Record and validate the release/image contract for one deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PACKAGE / "manifest.json"
VERSION_PATH = PACKAGE / "VERSION"
LOCK_PATH = PACKAGE / "deployment-lock.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REPO_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
MIGRATION_RE = re.compile(r"^[0-9]{3}_.+\.sql$")

# Dockerfile.openclaw COPYs the reviewed workspaces, the trusted-context
# extension, the exec-approvals seed and the dependency locks into the derived
# image and makes them read-only (`chmod -R a-w`). docker-compose.yml
# bind-mounts none of them, deliberately: a model lane must not be able to
# rewrite its own agent contracts, skills or helper entry points, and the exact
# image gate (G6) can only prove image content it owns.
#
# The consequence for the operator is that these artifacts are a build-time
# snapshot. Editing workspaces/vc-chief/vc/thesis.md on the host re-pins
# cleanly and passes every package gate, yet changes nothing about a running
# deployment until the image is rebuilt and the gateway recreated
# (./scripts/bootstrap.sh does both). Every other gate here is deliberately
# deployment-agnostic, so none of them can see that drift. Recording a digest
# of exactly these inputs in the deployment lock is what makes it detectable
# instead of silent.
#
# This is exactly the build context .dockerignore admits, including its
# host-generated-state exclusions; tests/infrastructure pins the two together
# so the build context and this contract cannot drift apart.
#
# config/exec-approvals.json is digested because it is image content, but note
# that a rebuild alone does not apply a change to it: the initializer seeds it
# into the state volume only when absent (it stays writable for OpenClaw's own
# socket token). It is not customizable — tests/infrastructure pins its exact
# allowlist, so an edit fails the offline gate rather than reaching a
# deployment. STALE_DEPLOYMENT_MESSAGE states the exception.
BAKED_SOURCE_FILES = (
    "Dockerfile.openclaw",
    "config/exec-approvals.json",
    "requirements.lock",
)
BAKED_SOURCE_TREES = (
    "runtime-extensions/vc-trusted-context",
    "runtime-packages",
    "workspaces",
)


class LockError(ValueError):
    """The deployment lock is missing, malformed, or release-incompatible."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise LockError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise LockError(f"must be a regular, non-symlink file: {path}")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    # UnicodeError covers UnicodeDecodeError: a lock file that is not valid UTF-8
    # must surface as LockError, not as a traceback.
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LockError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LockError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migration_inventory() -> list[dict[str, str]]:
    paths = [PACKAGE / "migrations/000_roles.sh"]
    paths.extend(
        path
        for path in sorted((PACKAGE / "migrations").glob("*.sql"))
        if MIGRATION_RE.fullmatch(path.name)
    )
    inventory: list[dict[str, str]] = []
    for path in paths:
        try:
            info = path.lstat()
        except OSError as exc:
            raise LockError(f"migration inventory is unavailable: {path}") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise LockError(f"migration must be a regular, non-symlink file: {path}")
        inventory.append({"path": path.relative_to(PACKAGE).as_posix(), "sha256": _sha256(path)})
    return inventory


def _is_host_generated(relative: str) -> bool:
    """Mirror .dockerignore's exclusions for host-generated workspace state."""
    if relative.endswith((".pyc", ".log")):
        return True
    parts = relative.split("/")
    if "__pycache__" in parts:
        return True
    # workspaces/<agent>/.openclaw/** and workspaces/<agent>/memory/**
    return len(parts) > 3 and parts[0] == "workspaces" and parts[2] in {".openclaw", "memory"}


def baked_sources_digest(root: Path = PACKAGE) -> str:
    """Digest the exact host artifacts that become read-only derived-image content."""
    entries: list[str] = []

    def add(path: Path, relative: str) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise LockError(f"image-baked artifact is unavailable: {relative}") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise LockError(
                f"image-baked artifact must be a regular, non-symlink file: {relative}"
            )
        # Git and the Docker build context both carry only the executable bit,
        # so the rest of the mode is not part of this contract.
        executable = "x" if info.st_mode & stat.S_IXUSR else "-"
        entries.append(f"{relative}\0{executable}\0{_sha256(path)}")

    for name in BAKED_SOURCE_FILES:
        add(root / name, name)
    for tree in BAKED_SOURCE_TREES:
        base = root / tree
        if not base.is_dir():
            raise LockError(f"image-baked source tree is unavailable: {tree}")
        for path in base.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if _is_host_generated(relative):
                continue
            try:
                info = path.lstat()
            except OSError as exc:
                raise LockError(f"image-baked artifact is unavailable: {relative}") from exc
            if stat.S_ISDIR(info.st_mode):
                continue
            add(path, relative)
    digest = hashlib.sha256()
    for entry in sorted(entries):
        digest.update(entry.encode("utf-8") + b"\n")
    return digest.hexdigest()


def _expected_images(upstream: dict[str, Any], package_version: str) -> dict[str, str]:
    try:
        return {
            "openclaw-base": upstream["openclaw"]["image"],
            "postgres": upstream["postgres_image"],
            "derived": f"vc-lead-research:{package_version}",
        }
    except (KeyError, TypeError) as exc:
        raise LockError("release manifest has an incomplete upstream image contract") from exc


def release_contract() -> dict[str, Any]:
    manifest = _load_json(MANIFEST_PATH)
    try:
        package_version = VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LockError("VERSION is unavailable") from exc
    if not package_version or manifest.get("package_version") != package_version:
        raise LockError("VERSION and release manifest package version differ")
    upstream = manifest.get("upstream")
    if not isinstance(upstream, dict):
        raise LockError("release manifest upstream contract is missing")
    return {
        "package_version": package_version,
        "release_manifest_sha256": _sha256(MANIFEST_PATH),
        "upstream": upstream,
        "expected_images": _expected_images(upstream, package_version),
        "migrations": _migration_inventory(),
    }


def _validate_contract_shape(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise LockError("deployment lock release_contract must be an object")
    if not isinstance(contract.get("package_version"), str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._+-]*", contract["package_version"]
    ):
        raise LockError("deployment lock package_version is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(contract.get("release_manifest_sha256", ""))):
        raise LockError("deployment lock release manifest digest is invalid")
    upstream = contract.get("upstream")
    if not isinstance(upstream, dict):
        raise LockError("deployment lock upstream contract is invalid")
    expected = contract.get("expected_images")
    if not isinstance(expected, dict) or set(expected) != {"openclaw-base", "postgres", "derived"}:
        raise LockError("deployment lock expected image inventory is invalid")
    if any(not isinstance(value, str) or not value for value in expected.values()):
        raise LockError("deployment lock contains an invalid expected image reference")
    migrations = contract.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        raise LockError("deployment lock migration inventory is invalid")
    seen: set[str] = set()
    for item in migrations:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise LockError("deployment lock contains a malformed migration entry")
        path = item.get("path")
        digest = item.get("sha256")
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or ".." in Path(path).parts
            or path in seen
            or not re.fullmatch(r"[0-9a-f]{64}", str(digest or ""))
        ):
            raise LockError("deployment lock contains an unsafe migration inventory")
        seen.add(path)
    return contract


def _local_reference(pinned_reference: str) -> str:
    return pinned_reference.split("@", 1)[0]


def _required_repo_digest(reference: str) -> str | None:
    if "@" not in reference:
        return None
    image_name, digest = reference.rsplit("@", 1)
    if not SHA256_RE.fullmatch(digest):
        raise LockError(f"image reference has an invalid pinned digest: {reference}")
    # Docker RepoDigests omit a tag even when the pull/build reference contains
    # both a tag and a digest. Preserve registry ports by stripping only a colon
    # in the final path component.
    slash = image_name.rfind("/")
    colon = image_name.rfind(":")
    if colon > slash:
        image_name = image_name[:colon]
    return f"{image_name}@{digest}"


def _role_required_repo_digest(role: str, reference: str) -> str | None:
    required = _required_repo_digest(reference)
    if role in {"openclaw-base", "postgres"} and required is None:
        raise LockError(f"upstream image reference is not digest-pinned for {role}")
    return required


def inspect(role: str, image: str, *, required_repo_digest: str | None = None) -> dict[str, object]:
    # Bounded like every other subprocess in this package: backup.sh and
    # update.sh call this while consumers are stopped, so an unresponsive
    # Docker daemon must fail the lifecycle script rather than leave the
    # deployment quiesced indefinitely.
    raw = subprocess.check_output(["docker", "image", "inspect", image], text=True, timeout=60)
    data = json.loads(raw, object_pairs_hook=_unique_object)[0]
    record = {
        "role": role,
        "reference": image,
        "id": data["Id"],
        "repo_digests": sorted(data.get("RepoDigests") or []),
    }
    if required_repo_digest and required_repo_digest not in record["repo_digests"]:
        raise LockError(
            f"live image for {role} does not expose required digest {required_repo_digest}"
        )
    return record


def validate_lock(
    path: Path, *, structure_only: bool = False, require_manifest_digest: bool = True
) -> dict[str, Any]:
    payload = _load_json(path)
    if payload.get("lock_version") != 1:
        raise LockError("deployment lock version is unsupported")
    created_at = payload.get("created_at")
    if not isinstance(created_at, str):
        raise LockError("deployment lock timestamp is missing")
    try:
        parsed_time = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise LockError("deployment lock timestamp is invalid") from exc
    if parsed_time.tzinfo is None:
        raise LockError("deployment lock timestamp must include a timezone")
    if not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("baked_sources_sha256", ""))):
        raise LockError("deployment lock image-baked source digest is invalid")

    contract = _validate_contract_shape(payload.get("release_contract"))
    if not structure_only:
        current = release_contract()
        # The manifest digest also covers documentation and the operator's own
        # policy artifacts, which the customization procedure requires them to
        # edit and re-pin. Holding a recovery point to it would make every
        # backup taken before such an edit permanently unrestorable, so a
        # backup's own lock is compared on the fields that decide whether its
        # contents can be safely restored: package version, upstream images,
        # and the migration set. The live package's lock is still compared in
        # full, so a deployment must always match its own manifest.
        if not require_manifest_digest:
            contract = {k: v for k, v in contract.items() if k != "release_manifest_sha256"}
            current = {k: v for k, v in current.items() if k != "release_manifest_sha256"}
        if contract != current:
            differing = sorted(k for k in current if contract.get(k) != current.get(k))
            raise LockError(
                "deployment lock does not match this exact package/upstream/migration contract"
                + (f" (differing: {', '.join(differing)})" if differing else "")
            )
        contract = _validate_contract_shape(payload.get("release_contract"))

    expected = contract["expected_images"]
    images = payload.get("images")
    if not isinstance(images, list) or len(images) != 3:
        raise LockError("deployment lock must contain exactly three image records")
    seen_roles: set[str] = set()
    for item in images:
        if not isinstance(item, dict):
            raise LockError("deployment lock contains a malformed image record")
        role = item.get("role")
        if not isinstance(role, str) or role not in expected or role in seen_roles:
            raise LockError("deployment lock contains an unknown or duplicate image role")
        seen_roles.add(role)
        if item.get("reference") != _local_reference(expected[role]):
            raise LockError(f"deployment lock image reference differs for {role}")
        if not SHA256_RE.fullmatch(str(item.get("id", ""))):
            raise LockError(f"deployment lock image ID is invalid for {role}")
        repo_digests = item.get("repo_digests")
        if (
            not isinstance(repo_digests, list)
            or any(not isinstance(value, str) or not REPO_DIGEST_RE.fullmatch(value) for value in repo_digests)
            or len(repo_digests) != len(set(repo_digests))
        ):
            raise LockError(f"deployment lock repository digests are invalid for {role}")
        required_digest = _role_required_repo_digest(role, expected[role])
        if required_digest and required_digest not in repo_digests:
            raise LockError(f"deployment lock is missing the pinned repository digest for {role}")
    if seen_roles != set(expected):
        raise LockError("deployment lock image inventory is incomplete")
    return payload


def validate_live(path: Path, *, structure_only: bool = False) -> dict[str, Any]:
    """Validate a lock and prove its recorded image IDs still name live images."""
    payload = validate_lock(path, structure_only=structure_only)
    contract = payload["release_contract"]
    stored_images = {item["role"]: item for item in payload["images"]}
    for role, expected_reference in contract["expected_images"].items():
        live = inspect(
            role,
            _local_reference(expected_reference),
            required_repo_digest=_role_required_repo_digest(role, expected_reference),
        )
        if live["id"] != stored_images[role]["id"]:
            raise LockError(f"live image ID differs from deployment lock for {role}")
    return payload


STALE_DEPLOYMENT_MESSAGE = (
    "the recorded deployment was built from different image-baked artifacts than this package "
    "tree now contains. This compares Dockerfile.openclaw itself together with what it bakes "
    "into the derived image read-only — workspaces/, runtime-extensions/vc-trusted-context/, "
    "config/exec-approvals.json, runtime-packages/ and requirements.lock — and nothing "
    "bind-mounts those, so the running gateway was built before your change to one of them. "
    "Re-run ./scripts/bootstrap.sh: it rebuilds the image, recreates the gateway, and re-records "
    "this lock. One exception a rebuild does not resolve: config/exec-approvals.json is seeded "
    "into the state volume only when absent and is not customizable — see CUSTOMIZATION.md, "
    "DO_NOT_CUSTOMIZE_DIRECTLY"
)


def validate_baked_sources(path: Path) -> dict[str, Any]:
    """Prove the running deployment's image was built from the current package tree.

    Deliberately structure-only and separate from validate_lock/validate_live: a
    recovery point legitimately predates a policy edit, so this staleness check
    must never be folded into the comparisons restore.sh and backup.sh depend on.
    """
    payload = validate_lock(path, structure_only=True)
    if payload["baked_sources_sha256"] != baked_sources_digest():
        raise LockError(STALE_DEPLOYMENT_MESSAGE)
    return payload


def lock_package_version(path: Path) -> str:
    """Return the package version from a structurally valid prior lock."""
    payload = validate_lock(path, structure_only=True)
    return payload["release_contract"]["package_version"]


def validate_applied_migrations(path: Path, ledger: str) -> None:
    """Refuse a lock that predates the schema the deployment actually carries.

    An update applies migrations inside its nested rotation and records the
    new lock only after several further fallible steps. A failure in that
    window leaves the database at the new schema while deployment-lock.json
    still describes the old contract — and the documented "repair the release"
    retry then takes another pre-update recovery point, stamping the *old*
    package version onto a dump of the *new* schema. Restoring that recovery
    point is only rejected by migrate.sh, long after the production database
    has been dropped. Compare the live ledger to the lock before the stamp so
    the operator is stopped while everything is still recoverable.

    One-directional by design: a lock entry with no ledger row is normal (the
    role reconciler is a shell script, and a not-yet-applied migration is the
    ordinary pre-update state). Only a ledger row the lock cannot account for
    proves the schema has moved past it.
    """
    contract = validate_lock(path, structure_only=True)["release_contract"]
    recorded = {item["path"]: item["sha256"] for item in contract["migrations"]}
    for line in ledger.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise LockError(f"malformed schema_migrations ledger row: {line!r}")
        version, name, checksum = (field.strip() for field in fields)
        expected = recorded.get(f"migrations/{name}.sql")
        if expected is None:
            raise LockError(
                f"the deployment's schema is ahead of {path}: applied migration "
                f"{version} ({name}) is not in the recorded release contract. "
                "Migrations were applied without a new lock being recorded — by "
                "an update or bootstrap that failed after migrate.sh, or by a "
                "direct scripts/rotate_runtime_role.sh run. Complete or roll "
                "back that operation, or re-record the lock with "
                "scripts/record_images.py, before taking a recovery point: the "
                "version stamped on it would not describe the schema inside it."
            )
        if expected != checksum:
            raise LockError(
                f"applied migration {version} ({name}) has checksum {checksum}, "
                f"but {path} records {expected} — the deployment's schema does "
                "not match the recorded release contract"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-lock", type=Path)
    modes.add_argument("--validate-structure", type=Path)
    modes.add_argument("--validate-live", type=Path)
    modes.add_argument("--validate-live-structure", type=Path)
    modes.add_argument("--validate-baked-sources", type=Path)
    modes.add_argument("--lock-package-version", type=Path)
    modes.add_argument(
        "--validate-applied-migrations",
        type=Path,
        help="compare the schema_migrations ledger on stdin (version/name/checksum TSV) "
        "against the lock's recorded migration inventory",
    )
    args = parser.parse_args()
    try:
        if args.validate_applied_migrations:
            validate_applied_migrations(
                args.validate_applied_migrations, sys.stdin.read()
            )
            print(
                json.dumps(
                    {
                        "result": "PASS",
                        "deployment_lock": str(args.validate_applied_migrations),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.lock_package_version:
            print(lock_package_version(args.lock_package_version))
            return 0
        if args.validate_baked_sources:
            validate_baked_sources(args.validate_baked_sources)
            print(
                json.dumps(
                    {"result": "PASS", "deployment_lock": str(args.validate_baked_sources)},
                    sort_keys=True,
                )
            )
            return 0
        if args.validate_live or args.validate_live_structure:
            path = args.validate_live or args.validate_live_structure
            validate_live(path, structure_only=bool(args.validate_live_structure))
            print(json.dumps({"result": "PASS", "deployment_lock": str(path)}, sort_keys=True))
            return 0
        if args.validate_lock or args.validate_structure:
            path = args.validate_lock or args.validate_structure
            # --validate-lock is how restore.sh checks a recovery point's own
            # lock, which may predate a manifest re-pin. --validate-live keeps
            # the full comparison for the package being run right now.
            validate_lock(
                path,
                structure_only=bool(args.validate_structure),
                require_manifest_digest=False,
            )
            print(json.dumps({"result": "PASS", "deployment_lock": str(path)}, sort_keys=True))
            return 0

        contract = release_contract()
        images = [
            inspect(
                role,
                _local_reference(reference),
                required_repo_digest=_role_required_repo_digest(role, reference),
            )
            for role, reference in contract["expected_images"].items()
        ]
        payload = {
            "lock_version": 1,
            # Recorded at the end of bootstrap/update, immediately after
            # `compose build`, so this is the digest the running image was
            # actually built from.
            "baked_sources_sha256": baked_sources_digest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "release_contract": contract,
            "images": images,
        }
        LOCK_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(LOCK_PATH)
        return 0
    except (LockError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        # stderr, like every sibling validator (authenticate_backup.py,
        # validate_recovery_archive.py, verify_release.py): restore.sh and
        # update.sh send this script's stdout to /dev/null, which used to
        # discard the one diagnostic naming what actually differed.
        print(json.dumps({"result": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
