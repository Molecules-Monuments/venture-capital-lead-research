# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PACKAGE = Path(__file__).resolve().parents[2]
SCRIPTS = PACKAGE / "scripts"

# The review-only directory contract is asserted in three places that must agree
# (.gitignore, build_release_manifest.EXCLUDED_PREFIXES,
# verify_release.REVIEW_ONLY_ROOTS). Read it from the verifier under test rather
# than restating the literal here: these fixtures previously hard-coded
# ["_internal"] and silently became wrong the moment the contract was widened.
_REVIEW_SPEC = importlib.util.spec_from_file_location(
    "verify_release_contract", SCRIPTS / "verify_release.py"
)
assert _REVIEW_SPEC is not None and _REVIEW_SPEC.loader is not None
_verify_release = importlib.util.module_from_spec(_REVIEW_SPEC)
_REVIEW_SPEC.loader.exec_module(_verify_release)
EXCLUDED_REVIEW_DIRECTORIES = sorted(_verify_release.REVIEW_ONLY_ROOTS)


AUTH_SPEC = importlib.util.spec_from_file_location(
    "backup_authentication_contract", SCRIPTS / "authenticate_backup.py"
)
assert AUTH_SPEC is not None and AUTH_SPEC.loader is not None
backup_authentication = importlib.util.module_from_spec(AUTH_SPEC)
AUTH_SPEC.loader.exec_module(backup_authentication)


def body(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


class RecoveryLifecycleContractTests(unittest.TestCase):
    def test_lifecycle_scripts_are_executable_and_parse_as_posix_shell(self) -> None:
        for name in (
            "backup.sh",
            "restore.sh",
            "migrate.sh",
            "rotate_runtime_role.sh",
            "bootstrap.sh",
            "update.sh",
        ):
            path = SCRIPTS / name
            with self.subTest(script=name):
                self.assertTrue(os.access(path, os.X_OK), f"{name} is not executable")
                subprocess.run(["sh", "-n", str(path)], check=True, timeout=10)

    def test_all_touched_scripts_pin_compose_file_and_project(self) -> None:
        for name in (
            "backup.sh",
            "restore.sh",
            "migrate.sh",
            "rotate_runtime_role.sh",
            "bootstrap.sh",
            "update.sh",
        ):
            script = body(name)
            with self.subTest(script=name):
                self.assertIn('COMPOSE_PROJECT="openclaw-lead-research-v3"', script)
                self.assertIn('docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT"', script)

    def test_postgres_init_mounts_only_the_role_reconciler(self) -> None:
        compose = (PACKAGE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn(
            "./migrations/000_roles.sh:/docker-entrypoint-initdb.d/000_roles.sh:ro",
            compose,
        )
        self.assertNotIn("./migrations:/docker-entrypoint-initdb.d", compose)

    def test_migration_and_ledger_registration_share_one_transaction(self) -> None:
        script = body("migrate.sh")
        self.assertIn("begin_count=", script)
        self.assertIn("commit_count=", script)
        self.assertIn("migration must contain exactly one standalone outer BEGIN and COMMIT", script)
        self.assertIn("pg_advisory_xact_lock(2026071801::bigint)", script)
        self.assertIn("\\if :ledger_exists", script)
        self.assertIn("\\if :migration_applied", script)
        self.assertIn("RAISE EXCEPTION 'migration checksum/name mismatch'", script)
        self.assertIn("SELECT register_schema_migration(:'version', :'name', :'checksum');", script)
        pipeline = script.index("  {\n    echo 'BEGIN;'")
        advisory_lock = script.index("pg_advisory_xact_lock", pipeline)
        under_lock_check = script.index("to_regclass", advisory_lock)
        registration = script.index("SELECT register_schema_migration", pipeline)
        psql = script.index("} | compose exec -T postgres", registration)
        self.assertLess(advisory_lock, under_lock_check)
        self.assertLess(under_lock_check, registration)
        self.assertLess(pipeline, registration)
        self.assertLess(registration, psql)
        self.assertNotIn("--command \"SELECT register_schema_migration", script)
        self.assertNotIn('stored="$(compose exec', script)
        self.assertIn("database contains an unexpected or incompatible migration ledger row", script)
        self.assertIn("database migration ledger does not exactly match this release", script)
        inventory = script.index("Construct the complete reviewed ledger")
        preflight_snapshot = script.index('snapshot_ledger "$ACTUAL_LEDGER"', inventory)
        apply = script.index("  {\n    echo 'BEGIN;'", preflight_snapshot)
        final_snapshot = script.index('snapshot_ledger "$ACTUAL_LEDGER"', apply)
        self.assertLess(inventory, preflight_snapshot)
        self.assertLess(preflight_snapshot, apply)
        self.assertLess(apply, final_snapshot)

    def test_generated_migration_stream_rechecks_after_advisory_lock(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g7-migrate-") as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            captures = root / "captures"
            fake_bin.mkdir()
            captures.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "count=0\n"
                "if [ -f \"$FAKE_CAPTURE/count\" ]; then count=$(cat \"$FAKE_CAPTURE/count\"); fi\n"
                "count=$((count + 1))\n"
                "printf '%s\\n' \"$count\" >\"$FAKE_CAPTURE/count\"\n"
                "capture=\"$FAKE_CAPTURE/call.$count.sql\"\n"
                "cat >\"$capture\"\n"
                "if grep -q 'SELECT version,name,checksum_sha256' \"$capture\"; then\n"
                "  cat \"$FAKE_LEDGER_OUTPUT\"\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            environment_file = root / "deployment.env"
            environment_file.write_text("fixture=true\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            environment["FAKE_CAPTURE"] = str(captures)
            ledger_output = root / "ledger.tsv"
            migrations = sorted((PACKAGE / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
            ledger_output.write_text(
                "".join(
                    f"{path.name.split('_', 1)[0]}\t{path.stem}\t"
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}\n"
                    for path in migrations
                ),
                encoding="utf-8",
            )
            environment["FAKE_LEDGER_OUTPUT"] = str(ledger_output)
            subprocess.run(
                [str(SCRIPTS / "migrate.sh"), str(environment_file)],
                cwd=PACKAGE,
                env=environment,
                check=True,
                text=True,
                capture_output=True,
                timeout=30,
            )
            streams = [
                path
                for path in captures.glob("call.*.sql")
                if "SELECT register_schema_migration" in path.read_text(encoding="utf-8")
            ]
            streams.sort(key=lambda path: int(path.name.split(".")[1]))
            self.assertEqual(len(migrations), len(streams))
            first = streams[0].read_text(encoding="utf-8")
            lock = first.index("pg_advisory_xact_lock")
            ledger = first.index("to_regclass", lock)
            condition = first.index("\\if :migration_applied", ledger)
            schema = first.index("CREATE TABLE IF NOT EXISTS schema_migrations", condition)
            register = first.index("SELECT register_schema_migration", schema)
            self.assertIn(
                "DO $migration_guard$ BEGIN RAISE EXCEPTION 'migration checksum/name mismatch'; "
                "END $migration_guard$;",
                first,
            )
            self.assertLess(lock, ledger)
            self.assertLess(ledger, condition)
            self.assertLess(condition, schema)
            self.assertLess(schema, register)
            self.assertTrue(first.rstrip().endswith("COMMIT;"))

    def test_migrator_rejects_unknown_ledger_before_application(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g7-newer-ledger-") as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            captures = root / "captures"
            fake_bin.mkdir()
            captures.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                "capture=\"$FAKE_CAPTURE/call.$$.sql\"\n"
                "cat >\"$capture\"\n"
                "if grep -q 'SELECT version,name,checksum_sha256' \"$capture\"; then\n"
                "  printf '%s\\t%s\\t%s\\n' 999 999_future aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
                "fi\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            environment_file = root / "deployment.env"
            environment_file.write_text("fixture=true\n", encoding="utf-8")
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            environment["FAKE_CAPTURE"] = str(captures)
            result = subprocess.run(
                [str(SCRIPTS / "migrate.sh"), str(environment_file)],
                cwd=PACKAGE,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("unexpected or incompatible migration ledger row: 999", result.stderr)
            captured_sql = "\n".join(
                path.read_text(encoding="utf-8") for path in captures.glob("call.*.sql")
            )
            self.assertNotIn("SELECT register_schema_migration", captured_sql)

    def test_backup_is_quiesced_complete_and_destination_new(self) -> None:
        script = body("backup.sh")
        stop = script.index("compose --profile tools stop openclaw-cli openclaw-gateway")
        dump = script.index("pg_dump", stop)
        state_archive = script.index("/home/node/.openclaw", dump)
        self.assertLess(stop, dump)
        self.assertLess(dump, state_archive)
        self.assertIn("backup destination already exists; refusing to mix recovery points", script)
        # Publication must never overwrite an existing recovery point. The
        # no-clobber guarantee comes from mkdir failing on an existing path
        # (portable) rather than GNU-only `mv -T -n`, which is unavailable on
        # the BSD userland this script otherwise tolerates.
        self.assertIn('if [ -e "$DESTINATION" ]; then', script)
        self.assertIn('if ! mkdir "$DESTINATION"; then', script)
        self.assertIn("backup destination appeared during publication; refusing to overwrite it", script)
        # No executed `mv -T`; the only permitted occurrence is the comment
        # explaining why it was replaced.
        self.assertFalse(
            [
                line
                for line in script.splitlines()
                if "mv -T" in line and not line.lstrip().startswith("#")
            ]
        )
        self.assertIn("--exclude=./openclaw.json", script)
        self.assertIn("--exclude=./exec-approvals.json", script)
        self.assertIn("--exclude=./exec-approvals.sock", script)
        # Those tar excludes are top-level-only, so restore.sh's contamination
        # check must anchor on the same depth: a nested archive member that
        # merely shares one of these names is legitimate backup payload.
        self.assertIn(
            r"grep -Eq '^(openclaw\.json|exec-approvals\.(json|sock))$'",
            body("restore.sh"),
        )
        self.assertIn("-C /inbox -czf - .", script)
        self.assertIn("-C /quarantine -czf - .", script)
        self.assertIn("LOCAL_ARTIFACTS.tsv", script)
        self.assertIn("verify_local_artifacts", script)
        self.assertIn("local_artifact_inventory=LOCAL_ARTIFACTS.tsv", script)
        self.assertIn("deployment-lock.json is required before backup", script)
        self.assertIn("--validate-live", script)
        self.assertIn("--validate-live-structure", script)
        self.assertIn("--lock-package-version", script)
        self.assertIn('printf \'%s\\n\' "$BACKUP_PACKAGE_VERSION" >"$STAGING/VERSION"', script)
        self.assertIn('echo "package_version=$BACKUP_PACKAGE_VERSION"', script)
        self.assertNotIn('cp "$PACKAGE_DIR/VERSION" "$STAGING/VERSION"', script)
        checksums = script.index("sha256sum $checksum_files >SHA256SUMS")
        authenticate = script.index("scripts/authenticate_backup.py create", checksums)
        # The recovery point becomes visible at its destination only after its
        # checksum manifest is written and HMAC-authenticated, so a reader can
        # never observe a published-but-unauthenticated backup.
        publish = script.index('if ! mkdir "$DESTINATION"; then', authenticate)
        self.assertLess(checksums, authenticate)
        self.assertLess(authenticate, publish)
        self.assertIn('echo "format_version=3"', script)

    def test_backup_rejects_inbox_path_overlap_before_quiescence(self) -> None:
        script = body("backup.sh")
        canonical_inbox = script.index(
            'PACKAGE_INBOX="$(CDPATH= cd -- "$PACKAGE_DIR/inbox" && pwd -P)"'
        )
        overlap = script.index('paths_overlap "$DESTINATION" "$PACKAGE_INBOX"')
        staging = script.index('mkdir -m 0700 "$STAGING"')
        quiesce = script.index(
            "compose --profile tools stop openclaw-cli openclaw-gateway"
        )
        self.assertIn("paths_overlap()", script)
        self.assertIn("backup destination must not overlap the package inbox", script)
        self.assertLess(canonical_inbox, overlap)
        self.assertLess(overlap, staging)
        self.assertLess(overlap, quiesce)

    def test_runtime_role_reconcile_pins_session_time_bounds(self) -> None:
        # The role initializer RESETs all settings on every reconcile, so the
        # bounded-execution settings must be re-applied right after — a
        # reconcile may never silently drop them.
        script = (PACKAGE / "migrations" / "000_roles.sh").read_text(encoding="utf-8")
        reset = script.index("ALTER ROLE openclaw_runtime RESET ALL;")
        for setting in (
            "ALTER ROLE openclaw_runtime SET statement_timeout = '30s';",
            "ALTER ROLE openclaw_runtime SET lock_timeout = '10s';",
            "ALTER ROLE openclaw_runtime SET idle_in_transaction_session_timeout = '120s';",
        ):
            self.assertIn(setting, script)
            self.assertGreater(script.index(setting), reset)

    def test_restore_validates_every_component_before_mutation(self) -> None:
        script = body("restore.sh")
        authenticity = script.index("scripts/authenticate_backup.py verify")
        checksum = script.index("validate_checksum_manifest\n", authenticity)
        state_validation = script.index(
            'validate_archive "$VALIDATION_DIR/openclaw-state.tar.gz" state'
        )
        staged_database = script.index('VALIDATION_DB="openclaw_restore_validate_$$"')
        inventory_compare = script.index(
            'cmp "$VALIDATION_DIR/LOCAL_ARTIFACTS.tsv" "$VALIDATION_DIR/database-artifacts.tsv"'
        )
        mutation = script.index("MUTATION_STARTED=1")
        # Every backup member is staged with a single read BEFORE the HMAC
        # authenticity proof, which then runs against the staged manifest; from
        # the staging call onward the operator-writable backup directory is
        # never read again, closing every verify-then-reread window.
        staging_call = script.index("\nstage_backup\n")
        self.assertLess(staging_call, authenticity)
        self.assertLess(staging_call, mutation)
        self.assertIn(
            '"$VALIDATION_DIR/SHA256SUMS" "$VALIDATION_DIR/BACKUP_AUTHENTICATION"',
            script,
        )
        self.assertNotIn('"$BACKUP_DIR/', script[staging_call:])
        self.assertNotIn('<"$BACKUP_DIR/postgres.dump"', script)
        self.assertIn('<"$VALIDATION_DIR/postgres.dump"', script)
        self.assertNotIn('verify_local_artifacts "$BACKUP_DIR/LOCAL_ARTIFACTS.tsv"', script)
        render = script.index("python3 scripts/render_channel_config.py")
        destructive_drop = script.index("--force openclaw", mutation)
        for prior in (
            authenticity,
            checksum,
            state_validation,
            staged_database,
            inventory_compare,
        ):
            self.assertLess(prior, mutation)
        self.assertLess(authenticity, checksum)
        self.assertLess(mutation, destructive_drop)
        self.assertLess(checksum, render)
        self.assertLess(state_validation, render)
        self.assertIn("consumers remain stopped", script)
        self.assertIn("/quarantine -mindepth 1", script)
        self.assertIn("! -name exec-approvals.json", script)
        self.assertIn("up -d --wait --force-recreate --no-deps openclaw-gateway", script)
        self.assertIn("run --rm --no-deps openclaw-state-init", script)
        self.assertGreaterEqual(script.count("/vcops"), 2)
        self.assertGreaterEqual(script.count("db-check"), 2)
        self.assertIn(
            'required_files="BACKUP_AUTHENTICATION BACKUP_MANIFEST '
            'LOCAL_ARTIFACTS.tsv SHA256SUMS VERSION deployment-lock.json',
            script,
        )
        self.assertIn('--validate-live "$PACKAGE_DIR/deployment-lock.json"', script)
        self.assertIn('--validate-lock "$VALIDATION_DIR/deployment-lock.json"', script)
        self.assertIn("BACKUP_AUTHENTICATION", script)
        self.assertIn("format_version=3", script)

    def test_backup_authentication_rejects_manifest_and_mac_tampering(self) -> None:
        key = bytes.fromhex("ab" * 32)
        manifest = b"a" * 64 + b"  BACKUP_MANIFEST\n"
        authentication = backup_authentication.build_authentication(key, manifest)
        encoded = (json.dumps(authentication) + "\n").encode("utf-8")
        backup_authentication.verify_authentication(key, manifest, encoded)
        with self.assertRaisesRegex(ValueError, "manifest_sha256 mismatch"):
            backup_authentication.verify_authentication(key, manifest + b"x", encoded)
        authentication["mac"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "MAC mismatch"):
            backup_authentication.verify_authentication(
                key, manifest, json.dumps(authentication).encode("utf-8")
            )

    def test_backup_authentication_cli_is_fail_closed_and_private(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g7-backup-auth-") as temporary:
            root = Path(temporary)
            environment = root / "deployment.env"
            environment.write_text(f"BACKUP_HMAC_KEY={'ab' * 32}\n", encoding="utf-8")
            environment.chmod(0o600)
            manifest = root / "SHA256SUMS"
            manifest.write_text(f"{'1' * 64}  BACKUP_MANIFEST\n", encoding="utf-8")
            authentication = root / "BACKUP_AUTHENTICATION"
            command = [
                sys.executable,
                str(SCRIPTS / "authenticate_backup.py"),
                "create",
                str(environment),
                str(manifest),
                str(authentication),
            ]
            created = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertEqual(0, created.returncode, created.stderr)
            self.assertEqual(0o600, authentication.stat().st_mode & 0o777)
            verified = subprocess.run(
                [*command[:2], "verify", *command[3:]],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(0, verified.returncode, verified.stderr)
            manifest.write_text(f"{'2' * 64}  BACKUP_MANIFEST\n", encoding="utf-8")
            rejected = subprocess.run(
                [*command[:2], "verify", *command[3:]],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("mismatch", rejected.stderr)

    def test_recovery_archive_validator_is_structural_and_bounded(self) -> None:
        validator = SCRIPTS / "validate_recovery_archive.py"
        with tempfile.TemporaryDirectory(prefix="g7-archive-") as temporary:
            root = Path(temporary)

            def write_archive(path: Path, members: list[tuple[str, bytes, bytes | None]]) -> None:
                with tarfile.open(path, "w:gz") as archive:
                    for name, payload, link_target in members:
                        info = tarfile.TarInfo(name)
                        if link_target is not None:
                            info.type = tarfile.SYMTYPE
                            info.linkname = link_target.decode()
                            archive.addfile(info)
                        else:
                            info.size = len(payload)
                            archive.addfile(info, io.BytesIO(payload))

            valid = root / "valid.tar.gz"
            write_archive(valid, [("nested/evidence.txt", b"reviewed", None)])
            destination = root / "valid-output"
            result = subprocess.run(
                [sys.executable, str(validator), str(valid), str(destination)],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(b"reviewed", (destination / "nested/evidence.txt").read_bytes())

            attacks: dict[str, list[tuple[str, bytes, bytes | None]]] = {
                "traversal": [("../escape", b"x", None)],
                "link": [("pivot", b"", b"../outside")],
                "duplicate": [("same", b"one", None), ("./same", b"two", None)],
                "control": [("bad\nname", b"x", None)],
                "oversized": [("large", b"12345", None)],
            }
            for name, members in attacks.items():
                with self.subTest(attack=name):
                    archive_path = root / f"{name}.tar.gz"
                    write_archive(archive_path, members)
                    output = root / f"{name}-output"
                    command = [sys.executable, str(validator), str(archive_path), str(output)]
                    if name == "oversized":
                        command.extend(["--max-member-bytes", "4", "--max-total-bytes", "4"])
                    rejected = subprocess.run(
                        command,
                        text=True,
                        capture_output=True,
                        timeout=10,
                    )
                    self.assertNotEqual(0, rejected.returncode)
                    self.assertFalse(output.exists())

    def test_pristine_verifier_rejects_cache_and_special_junk(self) -> None:
        verifier = (SCRIPTS / "verify_release.py").read_text(encoding="utf-8")
        self.assertNotIn("IGNORED_NAMES", verifier)
        self.assertNotIn("IGNORED_SUFFIXES", verifier)
        self.assertIn("Every undeclared regular file, symlink, FIFO, socket, device, cache", verifier)
        self.assertIn("actual.add(relative)", verifier)
        with tempfile.TemporaryDirectory(prefix="g7-release-inventory-") as temporary:
            package = Path(temporary)
            scripts = package / "scripts"
            scripts.mkdir()
            verifier_path = scripts / "verify_release.py"
            shutil.copy2(SCRIPTS / "verify_release.py", verifier_path)
            declared = package / "declared.txt"
            declared.write_text("reviewed\n", encoding="utf-8")

            def entry(path: Path) -> dict[str, object]:
                return {
                    "path": path.relative_to(package).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                    "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                }

            files = [entry(verifier_path), entry(declared)]
            (package / "manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": 1,
                        "package_version": "3.0.0",
                        "excluded_review_directories": EXCLUDED_REVIEW_DIRECTORIES,
                        "file_count": len(files),
                        "files": files,
                    }
                ),
                encoding="utf-8",
            )
            clean = subprocess.run(
                [sys.executable, str(verifier_path), "--pristine"],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(0, clean.returncode, clean.stderr or clean.stdout)
            helpers = package / "_internal"
            helpers.mkdir()
            (helpers / "review.md").write_text("temporary evidence\n", encoding="utf-8")
            helper_clean = subprocess.run(
                [sys.executable, str(verifier_path), "--pristine"],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(0, helper_clean.returncode, helper_clean.stderr or helper_clean.stdout)
            helper_link = helpers / "escape"
            helper_link.symlink_to(declared)
            helper_dirty = subprocess.run(
                [sys.executable, str(verifier_path), "--pristine"],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(
                0, helper_dirty.returncode, helper_dirty.stderr or helper_dirty.stdout
            )
            helper_link.unlink()
            cache = package / "__pycache__"
            cache.mkdir()
            (cache / "junk.pyc").write_bytes(b"junk")
            dirty = subprocess.run(
                [sys.executable, str(verifier_path), "--pristine"],
                text=True,
                capture_output=True,
                timeout=10,
            )
            self.assertNotEqual(0, dirty.returncode)
            self.assertIn("__pycache__/junk.pyc", dirty.stdout)

    def test_pristine_tolerates_operator_payload_but_not_symlinks_in_it(self) -> None:
        """`--pristine` must stay usable on a system that is doing its job.

        `inbox/` is the documented document drop point and `quarantine/` is a
        runtime quarantine placeholder (the deployed stack quarantines rejected
        uploads into the `vc-quarantine` named volume, not this directory); both
        are operator working directories whose payload is deliberately
        undeclared. If those files failed the check, the RUNBOOK's pre-deployment
        verification would report a false integrity failure on every running
        deployment. A symlink is different: the gateway bind-mounts `inbox` and
        would follow the link out of the intended tree, so it stays a finding.
        """
        verifier = (SCRIPTS / "verify_release.py").read_text(encoding="utf-8")
        self.assertIn("OPERATOR_DATA_ROOTS", verifier)
        with tempfile.TemporaryDirectory(prefix="g7-operator-data-") as temporary:
            package = Path(temporary)
            scripts = package / "scripts"
            scripts.mkdir()
            verifier_path = scripts / "verify_release.py"
            shutil.copy2(SCRIPTS / "verify_release.py", verifier_path)
            declared = package / "declared.txt"
            declared.write_text("reviewed\n", encoding="utf-8")

            def entry(path: Path) -> dict[str, object]:
                return {
                    "path": path.relative_to(package).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size": path.stat().st_size,
                    "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                }

            files = [entry(verifier_path), entry(declared)]
            (package / "manifest.json").write_text(
                json.dumps(
                    {
                        "manifest_version": 1,
                        "package_version": "3.0.0",
                        "excluded_review_directories": EXCLUDED_REVIEW_DIRECTORIES,
                        "file_count": len(files),
                        "files": files,
                    }
                ),
                encoding="utf-8",
            )

            def run_pristine() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(verifier_path), "--pristine"],
                    text=True,
                    capture_output=True,
                    timeout=10,
                )

            self.assertEqual(0, run_pristine().returncode)

            for root_name in ("inbox", "quarantine"):
                with self.subTest(directory=root_name):
                    root = package / root_name
                    root.mkdir()
                    payload = root / "operator-document.csv"
                    payload.write_text("metric,value\ncustomers,7\n", encoding="utf-8")
                    tolerated = run_pristine()
                    self.assertEqual(
                        0, tolerated.returncode, tolerated.stdout or tolerated.stderr
                    )

                    escape = root / "escape.csv"
                    escape.symlink_to(declared)
                    rejected = run_pristine()
                    self.assertNotEqual(0, rejected.returncode)
                    self.assertIn(
                        f"symlink in operator data directory: {root_name}/escape.csv",
                        rejected.stdout,
                    )
                    escape.unlink()
                    payload.unlink()
                    root.rmdir()

    def test_deployment_lock_binds_release_and_migrations(self) -> None:
        recorder = body("record_images.py")
        for contract_field in (
            "release_manifest_sha256",
            "expected_images",
            "migrations",
            "package_version",
            "upstream",
        ):
            self.assertIn(contract_field, recorder)
        self.assertIn("deployment lock does not match this exact package/upstream/migration contract", recorder)
        spec = importlib.util.spec_from_file_location(
            "g7_record_images_contract", SCRIPTS / "record_images.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.release_contract()
        images = [
            {
                "role": role,
                "reference": reference.split("@", 1)[0],
                "id": "sha256:" + (str(index) * 64),
                "repo_digests": (
                    [module._role_required_repo_digest(role, reference)]
                    if module._role_required_repo_digest(role, reference)
                    else []
                ),
            }
            for index, (role, reference) in enumerate(
                contract["expected_images"].items(), start=1
            )
        ]
        payload = {
            "lock_version": 1,
            "baked_sources_sha256": module.baked_sources_digest(),
            "created_at": "2026-07-18T00:00:00+00:00",
            "release_contract": contract,
            "images": images,
        }
        with tempfile.TemporaryDirectory(prefix="g7-deployment-lock-") as temporary:
            lock = Path(temporary) / "deployment-lock.json"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(payload, module.validate_lock(lock))

            missing_digest = json.loads(json.dumps(payload))
            next(
                image for image in missing_digest["images"] if image["role"] == "postgres"
            )["repo_digests"] = []
            lock.write_text(json.dumps(missing_digest), encoding="utf-8")
            with self.assertRaisesRegex(
                module.LockError, "missing the pinned repository digest for postgres"
            ):
                module.validate_lock(lock)

            lock.write_text(json.dumps(payload), encoding="utf-8")

            def inspect_live(
                role: str, image: str, *, required_repo_digest: str | None = None
            ) -> dict[str, object]:
                stored = next(item for item in images if item["role"] == role)
                self.assertEqual(stored["reference"], image)
                if required_repo_digest:
                    self.assertIn(required_repo_digest, stored["repo_digests"])
                return dict(stored)

            with mock.patch.object(module, "inspect", side_effect=inspect_live):
                self.assertEqual(payload, module.validate_live(lock))

            def inspect_wrong_id(
                role: str, image: str, *, required_repo_digest: str | None = None
            ) -> dict[str, object]:
                current = inspect_live(
                    role, image, required_repo_digest=required_repo_digest
                )
                if role == "derived":
                    current["id"] = "sha256:" + ("e" * 64)
                return current

            with mock.patch.object(module, "inspect", side_effect=inspect_wrong_id):
                with self.assertRaisesRegex(
                    module.LockError, "live image ID differs from deployment lock for derived"
                ):
                    module.validate_live(lock)

            payload["release_contract"]["migrations"].append(
                {"path": "migrations/999_future.sql", "sha256": "f" * 64}
            )
            lock.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                module.LockError, "does not match this exact package/upstream/migration contract"
            ):
                module.validate_lock(lock)

    def test_compatible_update_backup_uses_preserved_lock_version(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "g7_record_images_prior_version", SCRIPTS / "record_images.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.release_contract()
        prior_contract = json.loads(json.dumps(contract))
        prior_contract["package_version"] = "1.9.0"
        prior_contract["expected_images"]["derived"] = "openclaw-lead-research:1.9.0"
        images = []
        for index, (role, reference) in enumerate(
            prior_contract["expected_images"].items(), start=1
        ):
            required = module._role_required_repo_digest(role, reference)
            images.append(
                {
                    "role": role,
                    "reference": reference.split("@", 1)[0],
                    "id": "sha256:" + (str(index) * 64),
                    "repo_digests": [required] if required else [],
                }
            )
        payload = {
            "lock_version": 1,
            "baked_sources_sha256": module.baked_sources_digest(),
            "created_at": "2026-07-18T00:00:00+00:00",
            "release_contract": prior_contract,
            "images": images,
        }
        with tempfile.TemporaryDirectory(prefix="g7-prior-version-lock-") as temporary:
            lock = Path(temporary) / "deployment-lock.json"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual("1.9.0", module.lock_package_version(lock))
            current_version = (PACKAGE / "VERSION").read_text(encoding="utf-8").strip()
            self.assertNotEqual(current_version, module.lock_package_version(lock))
            with self.assertRaisesRegex(
                module.LockError,
                "does not match this exact package/upstream/migration contract",
            ):
                module.validate_lock(lock)
            # This is the old package side of restore's exact-lock gate: when
            # the matching old package supplies this release contract, the
            # preserved lock and lock-derived VERSION validate together.
            with mock.patch.object(
                module, "release_contract", return_value=prior_contract
            ):
                self.assertEqual(payload, module.validate_lock(lock))

        backup = body("backup.sh")
        self.assertIn('COMPATIBLE_BACKUP="${OPENCLAW_BACKUP_COMPATIBLE_LOCK:-0}"', backup)
        self.assertIn('if [ "$COMPATIBLE_BACKUP" -eq 1 ]; then', backup)
        self.assertIn("--validate-live-structure", backup)
        self.assertIn("--lock-package-version", backup)
        self.assertIn('printf \'%s\\n\' "$BACKUP_PACKAGE_VERSION" >"$STAGING/VERSION"', backup)
        self.assertNotIn('cp "$PACKAGE_DIR/VERSION" "$STAGING/VERSION"', backup)

    def test_clean_restore_prerequisites_are_explicit(self) -> None:
        operations = (PACKAGE / "docs/OPERATIONS.md").read_text(encoding="utf-8")
        runbook = (PACKAGE / "docs/RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("run `scripts/bootstrap.sh`", operations)
        self.assertIn("healthy package Postgres service", operations)
        self.assertIn("run `./scripts/bootstrap.sh`", runbook)
        self.assertIn("local `deployment-lock.json`", runbook)

    def test_restore_rejects_source_and_staging_overlap_before_mutation(self) -> None:
        script = body("restore.sh")
        source_overlap = script.index('paths_overlap "$BACKUP_DIR" "$PACKAGE_INBOX"')
        staging_overlap = script.index(
            'paths_overlap "$VALIDATION_DIR" "$PACKAGE_INBOX"'
        )
        mutation = script.index("MUTATION_STARTED=1")
        inbox_replace = script.index(
            'restore_host_tree "$VALIDATION_DIR/inbox" "$PACKAGE_DIR/inbox"'
        )
        self.assertIn("paths_overlap()", script)
        self.assertIn("backup source must not overlap the package inbox", script)
        self.assertIn("restore validation staging must not overlap the package inbox", script)
        self.assertLess(source_overlap, staging_overlap)
        self.assertLess(staging_overlap, mutation)
        self.assertLess(mutation, inbox_replace)

    def test_update_holds_lock_and_keeps_backup_quiesced(self) -> None:
        script = body("update.sh")
        self.assertIn('LOCK_TOKEN="update:$$"', script)
        self.assertIn('OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN"', script)
        self.assertNotIn("OPENCLAW_LIFECYCLE_LOCK_HELD", script)
        self.assertIn("OPENCLAW_BACKUP_LEAVE_QUIESCED=1", script)
        self.assertIn("OPENCLAW_BACKUP_COMPATIBLE_LOCK=1", script)
        backup = script.index('./scripts/backup.sh "$BACKUP_DESTINATION"')
        build = script.index("compose build --pull openclaw-gateway")
        # The lock-structure precondition invokes record_images.py earlier (and
        # deliberately before the quiesce); the post-build lock write is the
        # bare invocation on its own line.
        record = script.index("python3 scripts/record_images.py\n")
        precheck = script.index("python3 scripts/record_images.py --validate-live-structure")
        self.assertLess(precheck, backup)
        self.assertLess(backup, build)
        self.assertLess(build, record)
        self.assertIn("consumers remain stopped", script)

    def test_rotation_seeds_approval_state_before_no_dependency_gateway_start(self) -> None:
        script = body("rotate_runtime_role.sh")
        seed = script.index("compose run --rm --no-deps openclaw-state-init")
        gateway = script.index(
            "compose up -d --wait --force-recreate --no-deps openclaw-gateway"
        )
        self.assertLess(seed, gateway)
        self.assertNotIn("docker compose --env-file", script)


class LifecycleScriptRefusalExecutionTests(unittest.TestCase):
    """Execute the destructive lifecycle scripts against invalid invocations and
    assert they REFUSE at runtime (non-zero exit + message), rather than only
    grepping their source for guard strings. These argument-contract refusals run
    before any lock acquisition, docker call, or state mutation, so they are safe
    to execute in a unit test; the full destructive round-trip stays the G8 /
    live-commissioning exercise.
    """

    def _run(self, script: str, args: list[str]):
        return subprocess.run(
            [str(SCRIPTS / script), *args],
            cwd=str(PACKAGE), capture_output=True, text=True, timeout=30,
        )

    def test_backup_refuses_without_a_destination(self) -> None:
        result = self._run("backup.sh", [])
        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)

    def test_restore_refuses_without_destructive_confirmation(self) -> None:
        # A backup directory with no explicit --confirm-destructive-restore must
        # be refused before anything is touched.
        result = self._run("restore.sh", ["/nonexistent-openclaw-backup"])
        self.assertEqual(2, result.returncode)
        self.assertIn("confirm-destructive-restore", result.stderr)

    def test_update_refuses_without_a_backup_destination(self) -> None:
        result = self._run("update.sh", [])
        self.assertEqual(2, result.returncode)
        self.assertIn("usage:", result.stderr)

    def test_baked_source_digest_covers_every_image_baked_artifact(self) -> None:
        # The derived image is a build-time snapshot of these paths and nothing
        # bind-mounts them, so this digest is the only thing in the package that
        # can tell an operator their policy edit has not reached the gateway.
        module = self._record_images()
        with tempfile.TemporaryDirectory(prefix="g7-baked-sources-") as temporary:
            root = Path(temporary) / "package"
            for tree in module.BAKED_SOURCE_TREES:
                shutil.copytree(PACKAGE / tree, root / tree, symlinks=True)
            for name in module.BAKED_SOURCE_FILES:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PACKAGE / name, root / name)
            baseline = module.baked_sources_digest(root)
            self.assertEqual(baseline, module.baked_sources_digest(root))

            # Every governed policy artifact the operator is told to customize
            # must move the digest, including the reviewed prompt files and the
            # helper entry points the exec allowlist names.
            for relative in (
                "workspaces/vc-chief/vc/thesis.md",
                "workspaces/vc-chief/vc/exclusion_criteria.md",
                "workspaces/vc-chief/vc/scoring-rubric.v3.json",
                "workspaces/vc-chief/vc/primary_sources.md",
                "workspaces/vc-chief/USER.md",
                "workspaces/vc-chief/SOUL.md",
                "workspaces/vc-chief/vc/bin/vcops.py",
                "workspaces/shared-skills/evidence-scoring/SKILL.md",
                "runtime-extensions/vc-trusted-context/index.js",
                "config/exec-approvals.json",
                "requirements.lock",
                "Dockerfile.openclaw",
            ):
                target = root / relative
                original = target.read_bytes()
                target.write_bytes(original + b"\n")
                self.assertNotEqual(
                    baseline,
                    module.baked_sources_digest(root),
                    f"editing {relative} must change the image-baked source digest",
                )
                target.write_bytes(original)
                self.assertEqual(baseline, module.baked_sources_digest(root))

            # Losing the executable bit on a helper the exec allowlist names
            # changes the image, so it changes the digest.
            helper = root / "workspaces/vc-chief/vc/bin/agent/vcops"
            mode = helper.stat().st_mode
            helper.chmod(mode & ~stat.S_IXUSR)
            self.assertNotEqual(baseline, module.baked_sources_digest(root))
            helper.chmod(mode)

            # Host-generated workspace state is excluded from the build context,
            # so it must not be able to report a false drift.
            (root / "workspaces/vc-chief/memory").mkdir(exist_ok=True)
            (root / "workspaces/vc-chief/memory/session.md").write_text("x", encoding="utf-8")
            (root / "workspaces/vc-chief/.openclaw").mkdir(exist_ok=True)
            (root / "workspaces/vc-chief/.openclaw/state.json").write_text("{}", encoding="utf-8")
            (root / "workspaces/vc-chief/vc/logs/scan.log").write_text("x", encoding="utf-8")
            (root / "workspaces/vc-chief/vc/bin/__pycache__").mkdir(exist_ok=True)
            (root / "workspaces/vc-chief/vc/bin/__pycache__/vcops.pyc").write_bytes(b"\x00")
            self.assertEqual(baseline, module.baked_sources_digest(root))

    def test_stale_deployment_is_reported_but_never_blocks_recovery(self) -> None:
        module = self._record_images()
        contract = module.release_contract()
        images = [
            {
                "role": role,
                "reference": reference.split("@", 1)[0],
                "id": "sha256:" + (str(index) * 64),
                "repo_digests": (
                    [module._role_required_repo_digest(role, reference)]
                    if module._role_required_repo_digest(role, reference)
                    else []
                ),
            }
            for index, (role, reference) in enumerate(contract["expected_images"].items(), start=1)
        ]
        payload = {
            "lock_version": 1,
            "baked_sources_sha256": module.baked_sources_digest(),
            "created_at": "2026-07-30T00:00:00+00:00",
            "release_contract": contract,
            "images": images,
        }
        with tempfile.TemporaryDirectory(prefix="g7-stale-deployment-") as temporary:
            lock = Path(temporary) / "deployment-lock.json"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(payload, module.validate_baked_sources(lock))

            stale = json.loads(json.dumps(payload))
            stale["baked_sources_sha256"] = "a" * 64
            lock.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(module.LockError, "Re-run ./scripts/bootstrap.sh"):
                module.validate_baked_sources(lock)
            # A recovery point legitimately predates a policy edit, so the
            # staleness check must stay out of the comparisons restore.sh and
            # backup.sh depend on: those still validate this lock.
            self.assertEqual(stale, module.validate_lock(lock, require_manifest_digest=False))
            with mock.patch.object(module, "inspect", side_effect=lambda role, image, **_: dict(
                next(item for item in images if item["role"] == role)
            )):
                self.assertEqual(stale, module.validate_live(lock))

            malformed = json.loads(json.dumps(payload))
            del malformed["baked_sources_sha256"]
            lock.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaisesRegex(
                module.LockError, "image-baked source digest is invalid"
            ):
                module.validate_lock(lock, structure_only=True)

    def test_stale_deployment_notice_is_surfaced_to_the_operator(self) -> None:
        # The defect this closes was silence: the edit re-pinned cleanly and
        # every gate passed. Both commands the customization loop runs after an
        # edit must name the rebuild.
        module = self._record_images()
        self.assertIn("bootstrap.sh", module.STALE_DEPLOYMENT_MESSAGE)
        checker = (SCRIPTS / "check_customization.py").read_text(encoding="utf-8")
        self.assertIn("STALE_DEPLOYMENT_MESSAGE", checker)
        self.assertIn('"notices": stale_deployment_notices()', checker)
        initializer = (SCRIPTS / "init_customization.py").read_text(encoding="utf-8")
        self.assertIn("stale_deployment_step", initializer)
        self.assertIn("--validate-baked-sources", initializer)
        self.assertIn("--validate-baked-sources", body("record_images.py"))
        # The diagnostic must reach the operator even from the lifecycle scripts
        # that discard this script's stdout.
        self.assertIn("file=sys.stderr", body("record_images.py"))

    def _record_images(self):
        spec = importlib.util.spec_from_file_location(
            "g7_record_images_baked", SCRIPTS / "record_images.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_backup_refuses_an_invalid_quiesce_flag(self) -> None:
        # A malformed control env var is rejected at parse time, before any lock
        # or consumer is touched.
        result = subprocess.run(
            [str(SCRIPTS / "backup.sh"), "/tmp/openclaw-nonexistent-dest"],
            cwd=str(PACKAGE), capture_output=True, text=True, timeout=30,
            env={**os.environ, "OPENCLAW_BACKUP_LEAVE_QUIESCED": "maybe"},
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("OPENCLAW_BACKUP_LEAVE_QUIESCED must be 0 or 1", result.stderr)


if __name__ == "__main__":
    unittest.main()
