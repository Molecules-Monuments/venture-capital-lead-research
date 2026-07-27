#!/usr/bin/env python3
"""Create or verify the authenticated checksum envelope for a recovery point."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_env import parse_dotenv  # noqa: E402


MAX_MANIFEST_BYTES = 1024 * 1024
MAX_AUTHENTICATION_BYTES = 4096
AUTHENTICATION_KEYS = {
    "format_version",
    "algorithm",
    "key_id",
    "manifest_sha256",
    "mac",
}


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def read_regular(path: Path, maximum: int) -> bytes:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{path}: must be a non-symlink regular file")
    if metadata.st_size > maximum:
        raise ValueError(f"{path}: exceeds {maximum} bytes")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise ValueError(f"{path}: changed to a non-regular file")
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError(f"{path}: changed while opening")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            content = handle.read(maximum + 1)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(content) > maximum:
        raise ValueError(f"{path}: grew beyond {maximum} bytes")
    return content


def authentication_key(env_path: Path) -> bytes:
    value = parse_dotenv(env_path).get("BACKUP_HMAC_KEY", "")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("BACKUP_HMAC_KEY must be exactly 64 hexadecimal characters")
    return bytes.fromhex(value)


def build_authentication(key: bytes, manifest: bytes) -> dict[str, Any]:
    return {
        "format_version": 1,
        "algorithm": "hmac-sha256",
        "key_id": hashlib.sha256(key).hexdigest()[:16],
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "mac": hmac.new(key, manifest, hashlib.sha256).hexdigest(),
    }


def verify_authentication(key: bytes, manifest: bytes, authentication: bytes) -> None:
    parsed = json.loads(authentication, object_pairs_hook=unique_object)
    if not isinstance(parsed, dict) or set(parsed) != AUTHENTICATION_KEYS:
        raise ValueError("backup authentication envelope has an invalid field inventory")
    expected = build_authentication(key, manifest)
    for field in ("format_version", "algorithm", "key_id", "manifest_sha256"):
        if parsed.get(field) != expected[field]:
            raise ValueError(f"backup authentication {field} mismatch")
    mac = parsed.get("mac")
    if not isinstance(mac, str) or not hmac.compare_digest(mac, expected["mac"]):
        raise ValueError("backup authentication MAC mismatch")


def write_new(path: Path, payload: bytes) -> None:
    parent = path.parent
    metadata = parent.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{parent}: output parent must be a non-symlink directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "verify"):
        child = subparsers.add_parser(name)
        child.add_argument("env_file", type=Path)
        child.add_argument("checksum_manifest", type=Path)
        child.add_argument("authentication_file", type=Path)
    args = parser.parse_args()
    try:
        key = authentication_key(args.env_file)
        manifest = read_regular(args.checksum_manifest, MAX_MANIFEST_BYTES)
        if args.command == "create":
            payload = (
                json.dumps(build_authentication(key, manifest), sort_keys=True) + "\n"
            ).encode("utf-8")
            write_new(args.authentication_file, payload)
        else:
            authentication = read_regular(
                args.authentication_file, MAX_AUTHENTICATION_BYTES
            )
            verify_authentication(key, manifest, authentication)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"result": "FAIL", "errors": [str(exc)]}), file=sys.stderr)
        return 1
    print(json.dumps({"result": "PASS", "operation": args.command}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
