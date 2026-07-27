#!/usr/bin/env python3
"""Record and validate the release/image contract for one deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
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
    except (OSError, json.JSONDecodeError) as exc:
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


def _expected_images(upstream: dict[str, Any], package_version: str) -> dict[str, str]:
    try:
        return {
            "openclaw-base": upstream["openclaw"]["image"],
            "postgres": upstream["postgres_image"],
            "derived": f"openclaw-lead-research:{package_version}",
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
    raw = subprocess.check_output(["docker", "image", "inspect", image], text=True)
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


def validate_lock(path: Path, *, structure_only: bool = False) -> dict[str, Any]:
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

    contract = _validate_contract_shape(payload.get("release_contract"))
    if not structure_only and contract != release_contract():
        raise LockError("deployment lock does not match this exact package/upstream/migration contract")

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


def lock_package_version(path: Path) -> str:
    """Return the package version from a structurally valid prior lock."""
    payload = validate_lock(path, structure_only=True)
    return payload["release_contract"]["package_version"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--validate-lock", type=Path)
    modes.add_argument("--validate-structure", type=Path)
    modes.add_argument("--validate-live", type=Path)
    modes.add_argument("--validate-live-structure", type=Path)
    modes.add_argument("--lock-package-version", type=Path)
    args = parser.parse_args()
    try:
        if args.lock_package_version:
            print(lock_package_version(args.lock_package_version))
            return 0
        if args.validate_live or args.validate_live_structure:
            path = args.validate_live or args.validate_live_structure
            validate_live(path, structure_only=bool(args.validate_live_structure))
            print(json.dumps({"result": "PASS", "deployment_lock": str(path)}, sort_keys=True))
            return 0
        if args.validate_lock or args.validate_structure:
            path = args.validate_lock or args.validate_structure
            validate_lock(path, structure_only=bool(args.validate_structure))
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
            "created_at": datetime.now(timezone.utc).isoformat(),
            "release_contract": contract,
            "images": images,
        }
        LOCK_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(LOCK_PATH)
        return 0
    except (LockError, OSError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
