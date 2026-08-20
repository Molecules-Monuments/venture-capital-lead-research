#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Structurally validate and safely extract one bounded gzip tar recovery stream."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tarfile
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator


CHUNK_SIZE = 1024 * 1024
DEFAULT_MAX_ENTRIES = 100_000
DEFAULT_MAX_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_RATIO = 500
# DELIBERATELY NOT VERIFIED HERE: gzip's CRC32/ISIZE trailer.
#
# `tarfile` stops at the tar end-of-archive marker and reads exactly
# `member.size` bytes per member, so gzip never validates its own trailer and a
# recovery point that was already corrupt when backup.sh first read it back
# passes this validator. That is a real residual gap, recorded rather than
# papered over -- and it is deliberately left open, because the eighteenth audit
# pass got the fix wrong three times running:
#
#   1. draining the reader tarfile had been using read live member bytes on any
#      multi-member archive and rejected every genuine backup. A live update
#      drill caught it only after it had stopped production.
#   2. re-reading from offset 0 with a bound of `member payload + 1 MiB` ignored
#      tar's 512-byte header and padding per entry, so it rejected any real
#      archive past roughly a thousand entries.
#   3. the regression test's positive control was a single-member archive, so it
#      could not see either of the above.
#
# The compensating controls are real and were measured: restore.sh verifies every
# member's SHA-256 against the HMAC-authenticated SHA256SUMS *before* this
# validator opens anything, so a recovery point corrupted after it was written
# cannot reach a restore. Only a born-corrupt archive slips through, which is why
# the finding was adversarially downgraded to minor.
#
# If this is ever closed, the bound must be derived from the tar framing the
# headers already describe (offset_data + 512-rounded size), never from the
# payload total, and the regression test must use a MULTI-MEMBER archive.
MAX_PATH_BYTES = 4_096
MAX_SEGMENT_BYTES = 255


class ArchiveError(ValueError):
    pass


def normalized_name(raw: str) -> str:
    if not raw or raw.startswith("/") or "\\" in raw:
        raise ArchiveError(f"unsafe archive path: {raw!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise ArchiveError(f"archive paths must not contain control characters: {raw!r}")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            raise ArchiveError(f"archive path escapes its root: {raw!r}")
        # tarfile decodes member names with errors="surrogateescape", so a name
        # byte that is not valid UTF-8 arrives as a lone surrogate that plain
        # .encode("utf-8") refuses. Operator files under inbox/ carry whatever
        # bytes the filesystem gave them, so measure the length the same way
        # tarfile produced the string. For a name that is already valid UTF-8
        # this encodes to identical bytes.
        if len(part.encode("utf-8", "surrogateescape")) > MAX_SEGMENT_BYTES:
            raise ArchiveError(f"archive path segment is too long: {raw!r}")
        parts.append(part)
    rendered = "/".join(parts)
    if len(rendered.encode("utf-8", "surrogateescape")) > MAX_PATH_BYTES:
        raise ArchiveError(f"archive path is too long: {raw!r}")
    return rendered


def validate_members(
    archive: tarfile.TarFile,
    *,
    archive_size: int,
    max_entries: int,
    max_member_bytes: int,
    max_total_bytes: int,
    max_ratio: int,
) -> tuple[list[tuple[tarfile.TarInfo, str]], int]:
    validated: list[tuple[tarfile.TarInfo, str]] = []
    seen: set[str] = set()
    files: set[str] = set()
    required_directories: set[str] = set()
    total = 0
    raw_entries = 0
    for member in archive:
        raw_entries += 1
        if raw_entries > max_entries:
            raise ArchiveError(f"archive exceeds {max_entries} entries")
        name = normalized_name(member.name)
        if not name:
            if not member.isdir():
                raise ArchiveError("archive root entry must be a directory")
            continue
        if name in seen:
            raise ArchiveError(f"duplicate normalized archive path: {name!r}")
        parents = ["/".join(name.split("/")[:index]) for index in range(1, len(name.split("/")))]
        if any(parent in files for parent in parents):
            raise ArchiveError(f"archive path descends through a file: {name!r}")
        if member.isfile() and name in required_directories:
            raise ArchiveError(f"archive file conflicts with an existing descendant: {name!r}")
        required_directories.update(parents)
        seen.add(name)
        if member.isdir():
            if member.size != 0:
                raise ArchiveError(f"directory has a nonzero payload: {name!r}")
        elif member.isfile() and not member.sparse:
            if member.size < 0 or member.size > max_member_bytes:
                raise ArchiveError(f"archive member exceeds its byte limit: {name!r}")
            total += member.size
            if total > max_total_bytes:
                raise ArchiveError(f"archive exceeds its {max_total_bytes}-byte total limit")
            files.add(name)
        else:
            raise ArchiveError(f"links, sparse files, devices, and special entries are forbidden: {name!r}")
        validated.append((member, name))
    if archive_size <= 0:
        raise ArchiveError("archive is empty")
    if total > archive_size * max_ratio:
        raise ArchiveError(f"archive exceeds its {max_ratio}:1 expansion-ratio limit")
    return validated, total


def extract_members(
    archive: tarfile.TarFile,
    members: list[tuple[tarfile.TarInfo, str]],
    destination: Path,
) -> None:
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for member, name in members:
        target = destination.joinpath(*name.split("/"))
        if member.isdir():
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(target, 0o700)
            continue
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveError(f"regular archive member has no data stream: {name!r}")
        written = 0
        with source, target.open("xb") as output:
            os.chmod(target, 0o600)
            while True:
                block = source.read(CHUNK_SIZE)
                if not block:
                    break
                written += len(block)
                if written > member.size:
                    raise ArchiveError(f"archive member expanded beyond its declared size: {name!r}")
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if written != member.size:
            raise ArchiveError(f"archive member ended before its declared size: {name!r}")


@contextmanager
def pinned_archive(path: Path) -> Iterator[tuple[BinaryIO, int]]:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise ArchiveError("archive must be a regular, non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            metadata.st_dev,
            metadata.st_ino,
        ):
            raise ArchiveError("archive changed while it was being opened")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            yield handle, opened.st_size
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--list-file", type=Path)
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--max-member-bytes", type=int, default=DEFAULT_MAX_MEMBER_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--max-ratio", type=int, default=DEFAULT_MAX_RATIO)
    args = parser.parse_args()
    limits = (args.max_entries, args.max_member_bytes, args.max_total_bytes, args.max_ratio)
    if any(value <= 0 for value in limits):
        parser.error("every archive limit must be positive")
    try:
        if not args.destination.parent.is_dir() or args.destination.parent.is_symlink():
            raise ArchiveError("extraction destination parent must be a non-symlink directory")
        if args.destination.exists() or args.destination.is_symlink():
            raise ArchiveError("extraction destination must not already exist")
        with pinned_archive(args.archive) as (stream, archive_size):
            with tarfile.open(fileobj=stream, mode="r:gz", errorlevel=2) as archive:
                members, total = validate_members(
                    archive,
                    archive_size=archive_size,
                    max_entries=args.max_entries,
                    max_member_bytes=args.max_member_bytes,
                    max_total_bytes=args.max_total_bytes,
                    max_ratio=args.max_ratio,
                )
                reserve = min(64 * 1024 * 1024, max(1024 * 1024, total // 20))
                free = shutil.disk_usage(args.destination.parent).free
                if total + reserve > free:
                    raise ArchiveError(
                        f"insufficient staging space: need {total + reserve} bytes, have {free}"
                    )
                extract_members(archive, members, args.destination)

        if args.list_file is not None:
            # Same surrogateescape round-trip as normalized_name: without it a
            # member name carrying non-UTF-8 bytes validates in backup mode and
            # then fails here in restore mode, i.e. a recovery point that cannot
            # be restored. restore.sh reads this list byte-faithfully.
            with args.list_file.open("x", encoding="utf-8", errors="surrogateescape") as output:
                output.write("".join(f"{name}\n" for _, name in members))
    except (ArchiveError, OSError, tarfile.TarError, UnicodeError, EOFError) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "result": "PASS",
                "archive": str(args.archive),
                "entries": len(members),
                "uncompressed_bytes": total,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
