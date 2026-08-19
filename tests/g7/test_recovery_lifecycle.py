# SPDX-License-Identifier: 0BSD
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
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


# The shipped-shell world is enumerated once, by the offline gate, and read
# from there. Two copies of the shebang rule is exactly how the gate and this
# module came to disagree: the gate globbed `*.sh` and missed the five
# suffix-less launchers this module already scanned.
_OFFLINE_SPEC = importlib.util.spec_from_file_location(
    "verify_offline_shell_inventory", SCRIPTS / "verify_offline.py"
)
assert _OFFLINE_SPEC is not None and _OFFLINE_SPEC.loader is not None
_verify_offline = importlib.util.module_from_spec(_OFFLINE_SPEC)
_OFFLINE_SPEC.loader.exec_module(_verify_offline)


AUTH_SPEC = importlib.util.spec_from_file_location(
    "backup_authentication_contract", SCRIPTS / "authenticate_backup.py"
)
assert AUTH_SPEC is not None and AUTH_SPEC.loader is not None
backup_authentication = importlib.util.module_from_spec(AUTH_SPEC)
AUTH_SPEC.loader.exec_module(backup_authentication)


def body(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


SHELL_COMMAND_PREFIXES = frozenset({
    "then", "else", "elif", "do", "eval", "command", "exec", "time", "!",
})


def shell_code_only(line: str) -> str:
    """One shell line with quoted text and any trailing comment blanked out.

    The trap inventory counts `trap` WORDS to keep its world closed. Counting the
    raw line makes an operator message the gate's business: `echo "this looks like
    a trap"` or a trailing `# not a trap` both raise the count, and the release
    gate then fails claiming a handler is hidden from trap_commands() when none
    exists. Blank rather than delete, so nothing shifts position.
    """
    out = []
    quote = ""
    for index, character in enumerate(line):
        if quote:
            out.append(" ")
            if character == quote:
                quote = ""
            continue
        if character in "'\"":
            quote = character
            out.append(" ")
            continue
        if character == "#" and (index == 0 or line[index - 1].isspace()):
            out.append(" " * (len(line) - index))
            break
        out.append(character)
    return "".join(out)


def echo_arguments(line: str) -> list[str]:
    """Every `echo` command's argument text on one shell line.

    Written as a quote-aware scan rather than a regex: two regex versions of
    this guard each missed a spelling (leading indentation, and a `;` inside
    a quoted argument terminating the match early). Walk the line tracking
    quote state, start collecting after an `echo` token wherever a command
    may begin, and stop at an unquoted command terminator.
    """
    found: list[str] = []
    index = 0
    at_command_start = True
    quote = ""
    while index < len(line):
        character = line[index]
        if quote:
            if character == quote:
                quote = ""
            index += 1
            continue
        if character in "'\"":
            quote = character
            at_command_start = False
            index += 1
            continue
        if character == "#":
            break
        if character in ";&|(){}`":
            at_command_start = True
            index += 1
            continue
        if character.isspace():
            index += 1
            continue
        word = re.match(r"[A-Za-z_!][A-Za-z_0-9-]*", line[index:])
        if at_command_start and word and word.group(0) in SHELL_COMMAND_PREFIXES:
            # `then echo …`, `do echo …`, `eval echo …`: a reserved word or
            # modifier still leaves the next token in command position.
            index += len(word.group(0))
            continue
        if at_command_start and line.startswith("echo", index):
            after = index + 4
            if after >= len(line) or line[after].isspace():
                collected = []
                cursor = after
                inner = ""
                while cursor < len(line):
                    current = line[cursor]
                    if inner:
                        if current == inner:
                            inner = ""
                    elif current in "'\"":
                        inner = current
                    elif current in ";&|)}":
                        break
                    collected.append(current)
                    cursor += 1
                found.append("".join(collected))
                index = cursor
                continue
        at_command_start = False
        index += 1
    return found


def shipped_shell_scripts() -> list[Path]:
    """Every declared release file whose shebang selects a POSIX shell.

    Enumerated from manifest.json rather than a `*.sh` glob: the agent and
    workflow launchers under workspaces/vc-chief/vc/bin/ carry no suffix and
    run under the same dash inside the derived image. The enumeration itself
    lives in scripts/verify_offline.py, which builds its per-file `sh -n`
    checks from the same list.
    """
    return _verify_offline.shell_paths()


# The four fatal signals every shipped cleanup handler must cover. A handler
# that omits one is simply not run when that signal arrives: measured under
# Debian dash, `trap cleanup EXIT HUP INT TERM` + SIGQUIT exits 131 with the
# handler never entered, while the same trap naming QUIT does run it. EXIT is
# deliberately not in this set -- it is not a signal, and a `trap ... EXIT`
# alone is a legitimate shape as long as the fatal four are armed somewhere.
FATAL_TRAP_SIGNALS = frozenset({"HUP", "INT", "QUIT", "TERM"})

# Shipped scripts that install a `trap` today. A floor, not an inventory: a new
# script may add one and the assertions below govern it, but a script that
# LOSES its handler stops cleaning up after itself silently, and this names it.
TRAP_BEARING_SCRIPTS = (
    "migrations/000_roles.sh",
    "scripts/backup.sh",
    "scripts/bootstrap.sh",
    "scripts/migrate.sh",
    "scripts/restore.sh",
    "scripts/rotate_runtime_role.sh",
    "scripts/update.sh",
)


def trap_commands(path: Path) -> list[tuple[int, str, str, frozenset[str]]]:
    """Each line-initial `trap` command in a shipped shell script.

    Returns (line number, line, action word, signal names). The action is `-`
    for a disarm and the handler otherwise; signal names are upper-cased with
    any `SIG` prefix removed so `TERM` and `SIGTERM` compare equal.

    Line-initial is the only form the package uses; a `trap` written after a
    `;` on a shared line would not be seen here, so keep them on their own
    line, as every shipped script does today.
    """
    found: list[tuple[int, str, str, frozenset[str]]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not re.match(r"^trap\s", stripped):
            continue
        try:
            words = shlex.split(stripped, comments=True)
        except ValueError:
            # An unbalanced quote is a shell syntax error the `sh -n` step
            # already reports; fall back so this check still names the line.
            words = stripped.split()
        action = words[1] if len(words) > 1 else ""
        signals = frozenset(word.upper().removeprefix("SIG") for word in words[2:])
        found.append((number, stripped, action, signals))
    return found


def shell_bearing_non_shebang_files() -> list[Path]:
    """Shipped files that run shell without carrying a shebang of their own.

    `shipped_shell_scripts()` enumerates by shebang, which is right for the
    printf/echo scanner (it parses shell) but leaves two shipped files that
    execute dash outside every guard: docker-compose.yml's `openclaw-state-init`
    service declares `entrypoint: ["/bin/sh", "-eu", "-c"]` over an inline
    command block and carries two CMD-SHELL healthchecks, and every
    Dockerfile.openclaw `RUN` line runs under the base image's `/bin/sh`, which
    is dash. Neither can be fed to the shell parser, but both are covered by
    the pinned line inventory below, which parses nothing.
    """
    return [PACKAGE / "docker-compose.yml", PACKAGE / "Dockerfile.openclaw"]


# The exact backslash-bearing lines in shipped shell, pinned as a SET rather
# than a count. A count is defeated by any net-zero edit: adding a mangling
# `echo` while deleting a reviewed `printf` in the same file leaves the total
# unchanged, which is precisely the evasion this backstop exists to stop.
# Identity fails on both halves of that edit and names them.
#
# When a legitimate change moves an entry, read the new line first and confirm
# the backslash is either a reviewed printf FORMAT or sits inside a `%s`
# argument, then regenerate this block in the same commit.
BACKSLASH_BEARING_LINES: dict[str, tuple[str, ...]] = {
    'migrations/000_roles.sh': (
        '# PostgreSQL documents \\password as the non-cleartext password-change path.',
        'printf \'%s\\n%s\\n\' "$runtime_password" "$runtime_password" \\',
        "--command '\\password openclaw_runtime'",
        'printf \'%s\\n%s\\n\' "$owner_password" "$owner_password" \\',
        "--command '\\password openclaw_owner'",
        "sed -E 's/^([[:space:]]*host[a-z]*[[:space:]].*[[:space:]])trust[[:space:]]*$/\\1scram-sha-256/' \\",
        'printf \'127.0.0.1:5432:openclaw:openclaw_runtime:%s\\n\' "$runtime_password" > "$runtime_passfile"',
        'printf \'127.0.0.1:5432:openclaw:openclaw_owner:%s\\n\' "$owner_password" > "$owner_passfile"',
        'printf \'127.0.0.1:5432:openclaw:openclaw_runtime:%s\\n\' "$invalid_password" > "$invalid_passfile"',
        'printf \'127.0.0.1:5432:openclaw:openclaw_owner:%s\\n\' "$invalid_password" >> "$invalid_passfile"',
    ),
    'scripts/backup.sh': (
        # Reviewed: the backslashes are inside a SINGLE-QUOTED `tr` argument,
        # so the shell never touches them and `tr` performs its own octal
        # expansion. This is not an `echo` argument, which is the dash-escape
        # class this pin exists for. The explicit ranges are what make the
        # check locale-proof; `[[:cntrl:]]` in a `case` is not.
        'package_inbox_stripped="$(printf \'%s\' "$PACKAGE_INBOX" | LC_ALL=C tr -d \'\\001-\\037\\177\')"',
        'tab="$(printf \'\\t\')"',
        'printf \'%s\\n\' "$CHECK_ENV_REPORT" >&2',
        'printf \'%s\\n\' "$LOCK_TOKEN" >"$LOCK_DIR/owner"',
        "printf '%s\\n' '\\set ON_ERROR_STOP on'",
        'printf \'%s\\n\' "SELECT (to_regclass(\'public.schema_migrations\') IS NOT NULL) AS ledger_exists \\\\gset"',
        "printf '%s\\n' '\\if :ledger_exists'",
        "printf '%s\\n' 'SELECT version,name,checksum_sha256 FROM schema_migrations ORDER BY version;'",
        "printf '%s\\n' '\\endif'",
        '--tuples-only --no-align --field-separator="$(printf \'\\t\')" \\',
        'BACKUP_PACKAGE_VERSION="$(tr -d \'\\r\\n\' < "$PACKAGE_DIR/VERSION")"',
        '*\\\\*) inbox_reject="$entry (backslash in path)" ; break ;;',
        'if printf \'%s\\n\' "$running_services" | grep -Fxq openclaw-gateway; then',
        'printf \'%s\\n\' "package inbox holds an entry a recovery archive cannot represent: $inbox_reject" >&2',
        'if printf \'%s\\n\' "$still_running" | grep -Fxq "$service"; then',
        '--command "SELECT count(*) FROM evidence_artifacts WHERE storage_tier IN (\'workspace_file\',\'quarantine\') AND (storage_uri IS NULL OR storage_uri ~ E\'[\\\\t\\\\r\\\\n]\')")"',
        'tab="$(printf \'\\t\')"',
        'printf \'%s\\n\' "$BACKUP_PACKAGE_VERSION" >"$STAGING/VERSION"',
        'printf \'%s\\n\' "$DB_CHECK_REPORT" >&2',
    ),
    'scripts/bootstrap.sh': (
        'printf \'%s\\n\' "$LOCK_TOKEN" >"$LOCK_DIR/owner"',
        'printf \'%s\\n\' "$DB_CHECK_REPORT" >&2',
    ),
    'scripts/migrate.sh': (
        'tab="$(printf \'\\t\')"',
        'printf \'%s\\t%s\\t%s\\n\' "$version" "$name" "$checksum" >>"$EXPECTED_LEDGER"',
        "printf '%s\\n' '\\set ON_ERROR_STOP on'",
        "printf '%s\\n' 'BEGIN;'",
        "printf '%s\\n' 'SELECT pg_advisory_xact_lock(2026071801::bigint) \\g /dev/null'",
        "printf '%s\\n' '\\set ledger_exists false'",
        'printf \'%s\\n\' "SELECT (to_regclass(\'public.schema_migrations\') IS NOT NULL) AS ledger_exists \\\\gset"',
        "printf '%s\\n' '\\if :ledger_exists'",
        "printf '%s\\n' 'SELECT version,name,checksum_sha256 FROM schema_migrations ORDER BY version;'",
        "printf '%s\\n' '\\endif'",
        "printf '%s\\n' 'COMMIT;'",
        'expected_row="$(printf \'%s\\t%s\\t%s\' "$stored_version" "$stored_name" "$stored_checksum")"',
        "printf '%s\\n' 'BEGIN;'",
        "printf '%s\\n' 'SELECT pg_advisory_xact_lock(2026071801::bigint);'",
        "printf '%s\\n' '\\set ledger_exists false'",
        "printf '%s\\n' '\\set migration_applied false'",
        'printf \'%s\\n\' "SELECT (to_regclass(\'public.schema_migrations\') IS NOT NULL) AS ledger_exists \\\\gset"',
        "printf '%s\\n' '\\if :ledger_exists'",
        'printf \'%s\\n\' "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = :\'version\') AS migration_applied \\\\gset"',
        'printf \'%s\\n\' "SELECT (NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = :\'version\') OR EXISTS (SELECT 1 FROM schema_migrations WHERE version = :\'version\' AND name = :\'name\' AND checksum_sha256 = :\'checksum\')) AS migration_valid \\\\gset"',
        "printf '%s\\n' '\\if :migration_valid'",
        "printf '%s\\n' '\\else'",
        'printf \'%s\\n\' "\\\\warn \'migration checksum/name mismatch for \' :\'name\'"',
        'printf \'%s\\n\' "DO \\$migration_guard\\$ BEGIN RAISE EXCEPTION \'migration checksum/name mismatch\'; END \\$migration_guard\\$;"',
        "printf '%s\\n' '\\endif'",
        "printf '%s\\n' '\\endif'",
        "printf '%s\\n' '\\if :migration_applied'",
        "printf '%s\\n' '\\else'",
        "printf '\\n'",
        'printf \'%s\\n\' "SELECT register_schema_migration(:\'version\', :\'name\', :\'checksum\');"',
        "printf '%s\\n' '\\endif'",
        "printf '%s\\n' 'COMMIT;'",
    ),
    'scripts/restore.sh': (
        '--command "SELECT count(*) FROM evidence_artifacts WHERE storage_tier IN (\'workspace_file\',\'quarantine\') AND (storage_uri IS NULL OR storage_uri ~ E\'[\\\\t\\\\r\\\\n]\')")"',
        'tab="$(printf \'\\t\')"',
        'tab="$(printf \'\\t\')"',
        '\\**) member="${member#\\*}" ;;',
        'printf \'%s\\n\' "$CHECK_ENV_REPORT" >&2',
        'printf \'%s\\n\' "$LOCK_TOKEN" >"$LOCK_DIR/owner"',
        'if [ "$(tr -d \'\\r\\n\' < "$VALIDATION_DIR/VERSION")" != "$(tr -d \'\\r\\n\' < "$PACKAGE_DIR/VERSION")" ]; then',
        'if grep -Eq \'^(openclaw\\.json|exec-approvals\\.(json|sock))$\' "$VALIDATION_DIR/state.list"; then',
        'if printf \'%s\\n\' "$running_services" | grep -Fxq openclaw-cli; then',
    ),
    'scripts/rotate_runtime_role.sh': (
        'printf \'%s\\n\' "$LIFECYCLE_LOCK_TOKEN" >"$LIFECYCLE_LOCK_DIR/owner"',
    ),
    'scripts/update.sh': (
        # Reviewed: the backslashes are inside a SINGLE-QUOTED `tr` argument,
        # so the shell never touches them and `tr` performs its own octal
        # expansion. This is not an `echo` argument, which is the dash-escape
        # class this pin exists for. The explicit ranges are what make the
        # check locale-proof; `[[:cntrl:]]` in a `case` is not.
        'package_inbox_stripped="$(printf \'%s\' "$PACKAGE_INBOX" | LC_ALL=C tr -d \'\\001-\\037\\177\')"',
        'printf \'%s\\n\' "$LOCK_TOKEN" >"$LOCK_DIR/owner"',
        "printf '%s\\n' '\\set ON_ERROR_STOP on'",
        'printf \'%s\\n\' "SELECT (to_regclass(\'public.schema_migrations\') IS NOT NULL) AS ledger_exists \\\\gset"',
        "printf '%s\\n' '\\if :ledger_exists'",
        "printf '%s\\n' 'SELECT version,name,checksum_sha256 FROM schema_migrations ORDER BY version;'",
        "printf '%s\\n' '\\endif'",
        '--tuples-only --no-align --field-separator="$(printf \'\\t\')" \\',
        'if printf \'%s\\n\' "$running_services" | grep -Fxq openclaw-cli; then',
        # Reviewed: this is the backslash CLASS PATTERN of the inbox guard, not an
        # escape in a message. It is `*\\*)` in the script, matching a literal
        # backslash in an inbox-relative path, and it is character-identical to
        # backup.sh's entry above because update.sh mirrors that guard verbatim.
        '*\\\\*) inbox_reject="$entry (backslash in path)" ; break ;;',
        'printf \'%s\\n\' "package inbox holds an entry a recovery archive cannot represent: $inbox_reject" >&2',
        'printf \'%s\\n\' "$DB_CHECK_REPORT" >&2',
    ),
    'Dockerfile.openclaw': (
        '#   { printf \'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ bookworm main\\n\' "$SNAPSHOT"',
        '#     printf \'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s/ bookworm-security main\\n\' "$SNAPSHOT"',
    ),
}


class RecoveryLifecycleContractTests(unittest.TestCase):
    def test_lifecycle_scripts_are_executable_and_parse_under_the_gate_host_shell(
        self,
    ) -> None:
        """`sh` here is the gate host's `/bin/sh`, which is not always dash.

        Measured on 2026-08-15: the macOS gate host resolves `/bin/sh` to GNU
        bash 3.2.57, which parses `ARR=(a b c)`, `function f { echo hi; }` and
        `cat <<<"here"` with rc=0, while `dash` in debian:bookworm-slim rejects
        each with rc=2 ('"(" unexpected', '"}" unexpected', 'redirection
        unexpected'). So a green run here proves the six scripts parse under
        the host's shell, not that they parse under the deployed one; proving
        that needs a host whose /bin/sh is dash. The escape guard below records
        the same host asymmetry for its own half of this class.
        """
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

    def test_no_shipped_shell_emits_a_backslash_literal_through_an_escape(self) -> None:
        """A backslash literal must never ride in an escape-interpreting slot.

        dash — the documented Linux host's /bin/sh — expands backslash escapes
        in echo arguments AND in a printf FORMAT string, whatever the quoting:
        `echo '\\endif'`, `echo "a;\\endif"`, `printf '\\endif\\n'` and
        `printf "\\endif\\n"` all emit ESC + "ndif", so psql never closes the
        \\if block and exits 3. Only printf's `%s` argument slot is literal.
        The gate host's /bin/sh is bash, where the two halves differ: bash's
        echo emits the literal, so the echo half of this class is invisible
        here, while bash's printf mangles the FORMAT string exactly as dash
        does. That asymmetry is why this guard is static — `sh -n` only
        parses, and no gate executes these paths under the deployed shell.

        Two earlier versions of this guard each covered only the spelling that
        had actually shipped, and a reviewer bypassed both. So do not match
        spellings: flag every echo argument containing a backslash anywhere,
        in any quoting, at any position on the line, and every printf whose
        FORMAT operand is not a reviewed literal — including an unquoted or
        variable format, which is equally unreviewable.
        """
        # Measured against the shipped tree; each is escape-free or uses only
        # \n / \t, which dash expands to exactly what the scripts intend.
        safe_formats = frozenset({
            r"%s", r"%s\n", r"\n", r"\t", r"%s\n%s\n",
            r"%s\t%s\t%s", r"%s\t%s\t%s\n",
            r"127.0.0.1:5432:openclaw:openclaw_owner:%s\n",
            r"127.0.0.1:5432:openclaw:openclaw_runtime:%s\n",
        })
        # printf's FORMAT operand in any of its three spellings.
        printf_pattern = re.compile(
            r"\bprintf\s+(?:--\s+)?(?:'([^']*)'|\"([^\"]*)\"|(\S+))"
        )
        offenders = []
        # The world is every shipped script with a shell shebang, not a *.sh
        # glob: five launchers under workspaces/vc-chief/vc/bin/ carry no
        # suffix and run under the same dash inside the derived image.
        shell_scripts = shipped_shell_scripts()
        self.assertGreaterEqual(
            len(shell_scripts), 14, "the shipped-shell enumeration has rotted"
        )
        for path in shell_scripts:
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                where = f"{path.relative_to(PACKAGE)}:{number}"
                for arguments in echo_arguments(line):
                    if "\\" in arguments:
                        offenders.append(
                            f"{where}: echo argument contains a backslash: {line.strip()}"
                        )
                for single, double, bare in printf_pattern.findall(line):
                    fmt = single or double or bare
                    if not single or "$" in fmt or "`" in fmt:
                        # Only a single-quoted literal can be reviewed: a
                        # double-quoted or bare format may interpolate, and a
                        # variable can carry escapes this file never shows.
                        offenders.append(
                            f"{where}: printf FORMAT is not a single-quoted "
                            f"literal ({fmt!r}), so its escapes cannot be reviewed"
                        )
                    elif "\\" in fmt and fmt not in safe_formats:
                        offenders.append(f"{where}: unreviewed printf format {fmt!r}")
        self.assertEqual(
            offenders, [],
            "dash expands backslash escapes in echo arguments and in printf "
            f"FORMAT strings, mangling these on the deployed host: {offenders}. "
            "Put the literal in a %s argument instead.",
        )

    def test_backslash_bearing_shell_lines_are_a_pinned_inventory(self) -> None:
        """The evasion-proof backstop for the dash-escape class.

        Four successive versions of the semantic guard were each bypassed by a
        spelling nobody had tried — a printf FORMAT in double quotes, an `echo`
        after `then`, a format held in a variable. Any detector that tries to
        understand shell keeps losing that race.

        This check parses no shell. Every dash-escape defect must put a backslash
        somewhere in a shipped script, so pinning those lines catches a new one
        however it is spelled. Line continuations are excluded: ubiquitous, carry
        no escape, and would swamp the signal.

        The pin is the SET of lines, not their count. A count is defeated by any
        net-zero edit — add a mangling `echo`, delete a reviewed `printf` in the
        same file, total unchanged — which is exactly the evasion this exists to
        stop. Comparing identity fails on both halves and names them.
        """
        measured: dict[str, tuple[str, ...]] = {}
        for path in shipped_shell_scripts() + shell_bearing_non_shebang_files():
            found = []
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.rstrip()
                body_text = stripped[:-1] if stripped.endswith("\\") else stripped
                if "\\" in body_text:
                    found.append(stripped.strip())
            if found:
                measured[path.relative_to(PACKAGE).as_posix()] = tuple(found)

        self.assertEqual(
            set(measured), set(BACKSLASH_BEARING_LINES),
            "the set of shipped files carrying backslashes moved: "
            f"gone {sorted(set(BACKSLASH_BEARING_LINES) - set(measured))}, "
            f"new {sorted(set(measured) - set(BACKSLASH_BEARING_LINES))}",
        )
        for relative, pinned in sorted(BACKSLASH_BEARING_LINES.items()):
            with self.subTest(file=relative):
                current = measured[relative]
                added = [line for line in current if line not in pinned]
                removed = [line for line in pinned if line not in current]
                self.assertEqual(
                    (added, removed), ([], []),
                    f"{relative}: the backslash-bearing lines moved.\n"
                    f"  new: {added}\n  gone: {removed}\n"
                    "Review each new line before regenerating this pin: the "
                    "backslash must be a reviewed printf format or sit inside a "
                    "%s argument. dash expands escapes in `echo` arguments, so an "
                    "`echo` here is the defect class this guard exists for.",
                )

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
        pipeline = script.index("  {\n    printf '%s\\n' 'BEGIN;'")
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
        apply = script.index("  {\n    printf '%s\\n' 'BEGIN;'", preflight_snapshot)
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

    def test_restore_compares_recorded_state_bound_before_archive_validation(self) -> None:
        # A recovery point written under a raised OPENCLAW_STATE_ARCHIVE_MAX_BYTES
        # must fail on a smaller-bound target with a message naming the
        # variable, before archive validation aborts with a byte-limit message
        # that names neither — and long before mutation. Backups record the
        # bound; manifests predating the field fall through unchanged.
        backup = body("backup.sh")
        restore = body("restore.sh")
        self.assertIn(
            'echo "state_archive_max_bytes=$STATE_ARCHIVE_MAX_BYTES"', backup
        )
        recorded_read = restore.index("sed -n 's/^state_archive_max_bytes=//p'")
        named_remedy = restore.index(
            "set OPENCLAW_STATE_ARCHIVE_MAX_BYTES in .env to at least"
        )
        malformed = restore.index("malformed state_archive_max_bytes")
        authenticity = restore.index("scripts/authenticate_backup.py verify")
        first_archive_validation = restore.index(
            'validate_archive "$VALIDATION_DIR/openclaw-state.tar.gz" state'
        )
        mutation = restore.index("MUTATION_STARTED=1")
        self.assertLess(authenticity, recorded_read)
        self.assertLess(recorded_read, first_archive_validation)
        self.assertLess(named_remedy, first_archive_validation)
        # Conservative by construction: bound <= host implies total <= host, so
        # the pre-check can reject an archive that would in fact have validated.
        # That is the intended trade — it never false-accepts, and the remedy
        # (raise the target's bound) is always reachable.
        self.assertLess(malformed, first_archive_validation)
        self.assertLess(first_archive_validation, mutation)

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

            def envelope(stream: str, label: str) -> dict:
                """Parse the validator's JSON envelope, or fail naming the leak.

                A traceback exits non-zero just like a rejection does, so every
                assertion below reads the envelope rather than the exit status.
                """
                sentinel = object()
                parsed: object = sentinel
                try:
                    parsed = json.loads(stream)
                except ValueError:
                    pass
                if parsed is sentinel or not isinstance(parsed, dict):
                    self.fail(
                        f"{label}: validate_recovery_archive.py emitted no JSON envelope. "
                        f"backup.sh runs it under `set -eu` and update.sh runs backup.sh "
                        f"after arming MUTATION_STARTED, so an unhandled exception here "
                        f"stops the deployment with this as the only diagnostic:\n{stream}"
                    )
                return parsed

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
                    # A traceback also exits non-zero, so assert the envelope the
                    # operator is promised rather than only the exit status.
                    self.assertEqual(
                        "FAIL",
                        envelope(rejected.stderr, name)["result"],
                        f"{name}: validator must reject with its FAIL envelope on stderr",
                    )

            # backup.sh runs this validator under `set -eu` on its own freshly
            # created archives, and update.sh runs backup.sh after arming
            # MUTATION_STARTED. An input that escapes the envelope therefore
            # aborts the backup and, on the update path, leaves the deployment
            # stopped with a Python traceback as the only diagnostic. Both inputs
            # below produced exactly that before the surrogateescape handling and
            # the widened except tuple.
            escapes: dict[str, Path] = {}

            non_utf8 = root / "non-utf8-name.tar.gz"
            with tarfile.open(non_utf8, "w:gz", encoding="utf-8", errors="surrogateescape") as archive:
                payload = b"deck"
                # An operator file dropped into inbox/ off a legacy share: the
                # name is a byte string the filesystem accepted, and tarfile
                # hands it back with errors="surrogateescape".
                info = tarfile.TarInfo("nested/Rapport_ann\udce9e.pdf")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            escapes["non-utf8-name"] = non_utf8

            truncated = root / "truncated.tar.gz"
            whole = root / "whole.tar.gz"
            write_archive(whole, [("nested/evidence.txt", b"x" * 4096, None)])
            raw = whole.read_bytes()
            truncated.write_bytes(raw[: len(raw) // 2])
            escapes["truncated"] = truncated

            for name, archive_path in escapes.items():
                with self.subTest(envelope=name):
                    output = root / f"{name}-output"
                    completed = subprocess.run(
                        [sys.executable, str(validator), str(archive_path), str(output)],
                        text=True,
                        capture_output=True,
                        timeout=10,
                    )
                    # Whether the host filesystem accepts the name decides
                    # PASS vs FAIL — APFS and a C-locale mount return EILSEQ,
                    # a UTF-8 Linux filesystem takes the bytes. Either is
                    # correct; a traceback is not, so assert only that one of
                    # the two envelopes was emitted.
                    stream = completed.stdout if completed.returncode == 0 else completed.stderr
                    self.assertIn(
                        envelope(stream, name)["result"],
                        {"PASS", "FAIL"},
                        f"{name}: validator emitted a JSON object without a PASS/FAIL result",
                    )
                    if name == "non-utf8-name":
                        # The envelope assertion above is satisfied by a clean
                        # FAIL, which is what a filesystem that refuses the name
                        # produces — so on macOS it would pass even if the name
                        # measurement went back to plain .encode("utf-8"). Pin
                        # that directly, independently of any filesystem.
                        spec = importlib.util.spec_from_file_location(
                            "g7_archive_validator", validator
                        )
                        assert spec is not None and spec.loader is not None
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        surrogate = "nested/Rapport_ann\udce9e.pdf"
                        try:
                            measured = module.normalized_name(surrogate)
                        except UnicodeError as exc:
                            self.fail(
                                "normalized_name raised on a surrogateescaped member "
                                f"name ({exc!r}). tarfile decodes non-UTF-8 name bytes "
                                "that way, and backup.sh runs this validator under "
                                "`set -eu`, so this escapes as a traceback and aborts "
                                "the backup — on the update path, with the deployment "
                                "already stopped."
                            )
                        self.assertEqual(surrogate, measured)
                    if name == "non-utf8-name" and completed.returncode == 0:
                        # Where the extraction succeeded it must be byte-faithful:
                        # restore.sh matches on these names.
                        self.assertIn(
                            b"Rapport_ann\xe9e.pdf",
                            os.listdir(os.fsencode(output / "nested")),
                        )

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

    def pristine_fixture(self, package: Path) -> Path:
        """A minimal declared package: the real verifier plus one declared file.

        Same shape the two tests above build inline. Returns the path of the
        copied verifier, which is what `--pristine` must be run from so it
        resolves PACKAGE to the throwaway tree rather than to this repository.
        """
        scripts = package / "scripts"
        scripts.mkdir()
        verifier_path = scripts / "verify_release.py"
        shutil.copy2(SCRIPTS / "verify_release.py", verifier_path)
        declared = package / "declared.txt"
        declared.write_text("reviewed\n", encoding="utf-8")
        files = [
            {
                "path": path.relative_to(package).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
                "executable": bool(path.stat().st_mode & stat.S_IXUSR),
            }
            for path in (verifier_path, declared)
        ]
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
        return verifier_path

    def test_pristine_ignores_git_metadata_whatever_its_file_type(self) -> None:
        """`.git` is version-control metadata as a directory AND as a file.

        `git worktree add` and a submodule checkout both write `.git` as a
        regular file holding `gitdir: ...`. The eighteenth pass replaced this
        verifier's rglob loop -- whose `.git` rule matched by path, so it caught
        both shapes -- with an os.walk that prunes `.git` only out of the
        DIRECTORY list, so the file shape fell through and was reported as an
        undeclared file. build_release_manifest.py excludes `.git` by path part
        and kept passing, and a disagreement between those two checkers is the
        tamper signal docs/RUNBOOK.md §9 sends the operator to read.
        """
        with tempfile.TemporaryDirectory(prefix="g7-git-metadata-") as temporary:
            package = Path(temporary)
            verifier_path = self.pristine_fixture(package)

            def run_pristine() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-B", str(verifier_path), "--pristine"],
                    text=True,
                    capture_output=True,
                    timeout=30,
                )

            self.assertEqual(0, run_pristine().returncode)

            metadata = package / ".git"
            metadata.write_text("gitdir: /elsewhere/.git/worktrees/audit\n", encoding="utf-8")
            as_file = run_pristine()
            self.assertEqual(
                0, as_file.returncode,
                "a `.git` regular file (git worktree / submodule checkout) was "
                f"reported as package content: {as_file.stdout or as_file.stderr}",
            )
            metadata.unlink()

            objects = package / ".git/objects"
            objects.mkdir(parents=True)
            (objects / "loose").write_bytes(b"object")
            (package / ".git/HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            as_directory = run_pristine()
            self.assertEqual(
                0, as_directory.returncode,
                "a `.git` directory was reported as package content: "
                f"{as_directory.stdout or as_directory.stderr}",
            )

    def test_pristine_reports_an_unenumerable_directory_only_where_it_hides_something(self) -> None:
        """A directory the verifier cannot read is a finding -- except where it
        could not have reported anything inside it anyway.

        rglob swallowed the PermissionError it hit while descending, so an
        undeclared payload inside a mode-000 directory was invisible here, to
        build_release_manifest.py --check and to `git status` at once; the
        os.walk rewrite makes that a finding. But the first version of the new
        error callback recorded every unreadable path unconditionally, including
        ones under `_internal` (never declared) and inside `inbox`/`quarantine`
        (operator payload, deliberately tolerated) -- so a deployment doing its
        job failed its own integrity gate for a subtree whose contents this gate
        never reports, and `--check` went on passing.
        """
        # Never skipTest here: verify_offline.py scores a suite FAIL the moment
        # any test in it skips, so a guard would turn a root-owned run of the
        # gate into a red g7. Mode 000 does not deny root, so under root the
        # fixture proves the undeclared-payload path instead; `denied` below
        # records which of the two it actually exercised.
        with tempfile.TemporaryDirectory(prefix="g7-unreadable-") as temporary:
            package = Path(temporary)
            verifier_path = self.pristine_fixture(package)

            def run_pristine() -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, "-B", str(verifier_path), "--pristine"],
                    text=True,
                    capture_output=True,
                    timeout=30,
                )

            self.assertEqual(0, run_pristine().returncode)

            # Two syscalls can fail, and only one of them reaches os.walk's
            # onerror. Mode 0o000 (and 0o111, searchable but not readable) fails
            # the directory ENUMERATION, so onerror fires. Mode 0o444/0o644 --
            # what `chmod a-x` and `chmod -R 644` produce -- is readable but not
            # SEARCHABLE: os.walk raises nothing and hands the names back in
            # `filenames`, and the loop's own lstat fails instead. Round 1
            # classified the first shape and not the second, so --pristine went
            # on failing on tolerated roots for every directory an operator had
            # left non-executable. Both shapes are rows here.
            for parent, tolerated in (
                ("_internal", True),
                ("inbox", True),
                ("quarantine", True),
                ("scripts", False),
            ):
                for mode in (0o000, 0o111, 0o444, 0o644):
                    with self.subTest(parent=parent, tolerated=tolerated, mode=oct(mode)):
                        locked = package / parent / "locked"
                        locked.mkdir(parents=True, exist_ok=True)
                        (locked / "payload").write_text("undeclared\n", encoding="utf-8")
                        locked.chmod(mode)
                        try:
                            done = run_pristine()
                        finally:
                            locked.chmod(0o755)
                        if tolerated:
                            self.assertEqual(
                                0, done.returncode,
                                f"an unreadable directory under {parent}/ at mode "
                                f"{oct(mode)} was reported, but nothing there can "
                                f"enter the declared inventory, so it hides nothing "
                                f"this gate would have named: "
                                f"{done.stdout or done.stderr}",
                            )
                        else:
                            self.assertNotEqual(
                                0, done.returncode,
                                f"an unreadable directory under {parent}/ at mode "
                                f"{oct(mode)} passed, so an undeclared payload "
                                f"inside it is invisible to every integrity signal "
                                f"at once: {done.stdout or done.stderr}",
                            )
                            # Which path is named depends on which syscall failed,
                            # and mode bits do not deny root at all -- under root
                            # the payload is simply an undeclared file. All three
                            # shapes name the offending directory, which is what
                            # the operator needs; asserting the exact sentence
                            # would pin the shape rather than the property.
                            self.assertIn(
                                f"{parent}/locked", done.stdout,
                                f"the failure at mode {oct(mode)} did not name "
                                f"`{parent}/locked`, so the operator cannot act on "
                                f"it: {done.stdout or done.stderr}",
                            )
                        shutil.rmtree(locked)

    def both_checkers_fixture(self, package: Path) -> tuple[Path, Path]:
        """A minimal declared package carrying BOTH integrity checkers.

        The manifest is generated by the shipped builder instead of hand-written
        as `pristine_fixture` does: `build_release_manifest.py --check` compares
        its own header fields as well as the file list, so a hand-written
        manifest differs in the header and `--check` would fail on every row for
        a reason that has nothing to do with permissions.
        """
        scripts = package / "scripts"
        scripts.mkdir()
        for name in ("verify_release.py", "build_release_manifest.py"):
            shutil.copy2(SCRIPTS / name, scripts / name)
        (package / "declared.txt").write_text("reviewed\n", encoding="utf-8")
        # A DECLARED file inside each operator root, exactly as the real package
        # carries `inbox/.gitkeep` and `quarantine/.gitkeep`. Without these the
        # fixture cannot construct the case where a tolerated root hides a
        # declared package file, which is where the tolerance was wrong.
        for root in ("inbox", "quarantine"):
            (package / root).mkdir()
            (package / root / ".gitkeep").write_text("", encoding="utf-8")
        built = subprocess.run(
            [sys.executable, "-B", str(scripts / "build_release_manifest.py")],
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(
            0, built.returncode,
            f"the fixture's baseline manifest build failed: {built.stdout}{built.stderr}",
        )
        return scripts / "verify_release.py", scripts / "build_release_manifest.py"

    def test_both_integrity_checkers_tolerate_exactly_the_same_unreadable_paths(self) -> None:
        """The two checkers must agree, because a disagreement IS the tamper signal.

        docs/RUNBOOK.md §9 sends the operator to `--pristine` when they suspect
        tampering, and one checker passing while the other fails is what that
        section teaches them to distrust. Each script decides tolerance in its own
        copy of the same rule, so nothing but this test binds the two copies.

        Before the eighteenth pass's round-3 repair the disagreement was real and
        measured on an export: with a directory under `inbox/` at mode 0o444,
        `verify_release.py --pristine` exited 1 with "cannot inspect package path
        inbox/locked/doc.pdf" while `build_release_manifest.py --check` exited 0.
        In the other direction, `build_release_manifest.py`'s own tolerance was
        exercised by NOTHING: deleting its classification left the whole offline
        gate green while making every manifest re-pin -- the step CLAUDE.md
        requires after any declared-file change -- impossible.

        Asserted as equality of outcome rather than as two independent
        expectations, so the test fails when they diverge in either direction.
        """
        # Never skipTest: verify_offline.py scores any skip as a suite failure.
        # Mode bits do not deny root, so under root every row exercises the
        # readable-undeclared-payload path instead; the agreement property is the
        # subject either way, and it holds for both shapes.
        with tempfile.TemporaryDirectory(prefix="g7-two-checkers-") as temporary:
            package = Path(temporary)
            verifier, builder = self.both_checkers_fixture(package)

            def rc(script: Path, *args: str) -> int:
                return subprocess.run(
                    [sys.executable, "-B", str(script), *args],
                    text=True, capture_output=True, timeout=60,
                ).returncode

            self.assertEqual(0, rc(verifier, "--pristine"), "baseline --pristine must pass")
            self.assertEqual(0, rc(builder, "--check"), "baseline --check must pass")

            for parent, tolerated in (
                ("_internal", True),
                ("inbox", True),
                ("quarantine", True),
                ("scripts", False),
            ):
                for mode in (0o000, 0o111, 0o444, 0o644):
                    with self.subTest(parent=parent, tolerated=tolerated, mode=oct(mode)):
                        locked = package / parent / "locked"
                        locked.mkdir(parents=True, exist_ok=True)
                        (locked / "payload.sh").write_text("undeclared\n", encoding="utf-8")
                        locked.chmod(mode)
                        try:
                            verified = rc(verifier, "--pristine")
                            checked = rc(builder, "--check")
                        finally:
                            locked.chmod(0o755)
                            shutil.rmtree(locked)
                        self.assertEqual(
                            verified == 0, checked == 0,
                            f"the two integrity checkers disagree about "
                            f"{parent}/locked at mode {oct(mode)}: "
                            f"verify_release --pristine returned {verified}, "
                            f"build_release_manifest --check returned {checked}. "
                            f"That disagreement is exactly what docs/RUNBOOK.md §9 "
                            f"tells the operator to read as tampering.",
                        )
                        self.assertEqual(
                            tolerated, verified == 0,
                            f"{parent}/locked at mode {oct(mode)} should be "
                            f"{'tolerated' if tolerated else 'refused'} and was not",
                        )

            # The cell neither test occupied: an operator root that is itself
            # unreadable HIDES A DECLARED FILE. Tolerating it let the builder's
            # write path drop `inbox/.gitkeep` and exit 0 (331 -> 330 declared
            # files), after which --pristine PASSED, because the file it would
            # have missed was no longer declared. Assert the inventory, not just
            # the exit status: a successful exit with a reduced manifest is the
            # defect.
            manifest = package / "manifest.json"
            before = json.loads(manifest.read_text(encoding="utf-8"))
            for root in ("inbox", "quarantine"):
                for mode in (0o000, 0o444, 0o644):
                    with self.subTest(declared_under=root, mode=oct(mode)):
                        (package / root).chmod(mode)
                        try:
                            # Mode bits do not deny root. Under uid 0 the builder
                            # reads the .gitkeep perfectly well and SHOULD succeed
                            # with the file still declared, so probe what this
                            # process can actually do rather than assuming the
                            # chmod denied it — asserting a refusal unconditionally
                            # made this block fail as root, and verify_offline.py
                            # scores any failure as a suite failure.
                            try:
                                (package / root / ".gitkeep").read_bytes()
                                denied = False
                            except OSError:
                                denied = True
                            written = subprocess.run(
                                [sys.executable, "-B", str(builder)],
                                text=True, capture_output=True, timeout=60,
                            )
                        finally:
                            (package / root).chmod(0o755)
                        after = json.loads(manifest.read_text(encoding="utf-8"))
                        if denied:
                            self.assertNotEqual(
                                0, written.returncode,
                                f"the builder reported success over {root}/ at mode "
                                f"{oct(mode)}, which hides the declared "
                                f"{root}/.gitkeep: {written.stdout}{written.stderr}",
                            )
                        else:
                            self.assertEqual(
                                0, written.returncode,
                                f"the builder refused {root}/ at mode {oct(mode)} "
                                f"even though this process can still read the "
                                f"declared file there: "
                                f"{written.stdout}{written.stderr}",
                            )
                        # Either way the declared file must survive: refused, or
                        # read and kept. What must never happen is a manifest
                        # written without it.
                        self.assertEqual(
                            before["files"], after["files"],
                            f"the manifest changed while {root}/ was at mode "
                            f"{oct(mode)} (this process "
                            f"{'could not' if denied else 'could'} read the "
                            f"declared file). A declared path is a package file "
                            f"wherever it lives; dropping it and exiting 0 makes "
                            f"--pristine agree with an inventory that never saw it.",
                        )

            # The cell that distinguishes the two rules by NAME rather than by
            # permission: an operator drops a repository checkout into `inbox/`
            # and it carries its own `.gitkeep`. `verify_release.py` asks whether
            # the path is DECLARED; `build_release_manifest.py` cannot (it is
            # writing the declaration), so it carries the equivalent set
            # explicitly. Round 5 replaced its BASENAME rule with the exact
            # relative paths -- and nothing failed when that was reverted, because
            # every existing row here plants at depth 1, where the two rules agree.
            # Depth 2 is the only input that separates them.
            checkout = package / "inbox" / "repo"
            checkout.mkdir()
            (checkout / ".gitkeep").write_text("", encoding="utf-8")
            (checkout / "README.md").write_text("operator's own checkout\n", encoding="utf-8")
            baseline = json.loads(manifest.read_text(encoding="utf-8"))
            verified = rc(verifier, "--pristine")
            checked = rc(builder, "--check")
            self.assertEqual(
                verified == 0, checked == 0,
                f"the two integrity checkers disagree about an operator checkout "
                f"carrying inbox/repo/.gitkeep: --pristine returned {verified}, "
                f"--check returned {checked}. docs/RUNBOOK.md §9 tells the "
                f"operator to read that disagreement as tampering, and this is a "
                f"deployment doing exactly what inbox/ is for.",
            )
            self.assertEqual(
                0, verified,
                "an operator checkout under inbox/ carrying its own .gitkeep "
                "raised the RUNBOOK §9 tamper signal; inbox/ holds operator data "
                "whose names are THEIRS to choose",
            )
            rebuilt = subprocess.run(
                [sys.executable, "-B", str(builder)],
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(
                0, rebuilt.returncode,
                f"a re-pin failed over an operator checkout under inbox/: "
                f"{rebuilt.stdout}{rebuilt.stderr}",
            )
            repinned = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                baseline["files"], repinned["files"],
                "a re-pin absorbed the operator's own inbox/repo/.gitkeep into "
                "the declared inventory. The next operator to add or remove a "
                "file there fails --pristine, and CLAUDE.md's re-pin step becomes "
                "a way to certify operator payload as package content.",
            )
            self.assertIn(
                "inbox/.gitkeep", [entry["path"] for entry in repinned["files"]],
                "the root placeholder inbox/.gitkeep left the inventory; the "
                "tolerance widened from 'this exact path' to 'anything named "
                "\'.gitkeep\'' in the other direction",
            )

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

    def test_compatible_backup_refuses_a_schema_ahead_of_its_lock(self) -> None:
        """A retried update must not stamp the old version onto the new schema.

        update.sh applies migrations inside its nested rotation and records the
        new lock only after several further fallible steps. A failure in that
        window leaves the database migrated while deployment-lock.json still
        describes the old contract; the documented "repair the release" retry
        then re-enters compatible-lock backup, which stamps the recovery point
        from that stale lock. Restoring the result is rejected only by
        migrate.sh — after the production database has already been dropped.
        backup.sh must therefore compare the live ledger to the lock before it
        stamps anything. The comparison runs in both modes, not just this one:
        a direct backup taken in the same drifted state would stamp the
        package VERSION onto the same mismatched dump.
        """
        script = body("backup.sh")
        ledger = script.index("SELECT version,name,checksum_sha256 FROM schema_migrations")
        guard = script.index("--validate-applied-migrations")
        stamp = script.index("--lock-package-version")
        quiesce = script.index("compose --profile tools stop openclaw-cli openclaw-gateway")
        self.assertLess(ledger, guard)
        self.assertLess(guard, stamp)
        self.assertLess(guard, quiesce)
        # The guard must be unconditional. Nested inside the compatible-lock
        # branch it would leave a direct backup stamping the package VERSION
        # onto a schema-ahead dump — the same defect in the other mode — so
        # pin that it precedes the branch and is not indented into it.
        branch = script.index('if [ "$COMPATIBLE_BACKUP" -eq 1 ]; then')
        self.assertLess(
            guard, branch,
            "the schema-ahead guard moved inside the compatible-lock branch; a "
            "direct backup.sh would no longer be checked",
        )
        guard_line = script[script.rindex("\n", 0, guard) + 1:guard]
        self.assertEqual(
            guard_line, "python3 scripts/record_images.py ",
            "the schema-ahead guard is indented, which means it was nested "
            f"back into a conditional: {guard_line!r}",
        )

        # update.sh must mirror it before it arms its own post-mutation
        # handler. backup.sh runs the guard pre-quiesce precisely so it fires
        # on a healthy running deployment, but update.sh sets MUTATION_STARTED
        # before invoking the pre-update backup, and that flag is what makes
        # the cleanup trap stop the gateway and CLI. Without the mirror, a
        # guard whose whole purpose is to stop the operator while everything is
        # still recoverable instead takes production down on its way to
        # reporting.
        update = body("update.sh")
        update_guard = update.index("--validate-applied-migrations")
        update_flag = update.index("MUTATION_STARTED=1")
        self.assertLess(
            update_guard, update_flag,
            "update.sh arms MUTATION_STARTED before mirroring backup.sh's "
            "schema-ahead ledger guard, so that guard now fails with consumers "
            "stopped instead of on a healthy running deployment",
        )

        spec = importlib.util.spec_from_file_location(
            "g7_record_images_ledger", SCRIPTS / "record_images.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        contract = module.release_contract()
        images = []
        for index, (role, reference) in enumerate(
            contract["expected_images"].items(), start=1
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
            "created_at": "2026-08-10T00:00:00+00:00",
            "release_contract": contract,
            "images": images,
        }
        applied = "\n".join(
            f"{entry['path'][len('migrations/'):len('migrations/') + 3]}\t"
            f"{Path(entry['path']).stem}\t{entry['sha256']}"
            for entry in contract["migrations"]
            if entry["path"].endswith(".sql")
        )
        with tempfile.TemporaryDirectory(prefix="g7-ledger-lock-") as temporary:
            lock = Path(temporary) / "deployment-lock.json"
            lock.write_text(json.dumps(payload), encoding="utf-8")
            # The ordinary pre-update state: every applied migration is in the
            # recorded contract. A lock entry with no ledger row (000_roles.sh,
            # or a migration this release adds) is normal and must not fail.
            module.validate_applied_migrations(lock, applied)
            module.validate_applied_migrations(
                lock, "\n".join(applied.splitlines()[:-1])
            )
            # The failed-update retry: the database carries a migration the
            # lock has never heard of.
            with self.assertRaisesRegex(module.LockError, "schema is ahead of"):
                module.validate_applied_migrations(
                    lock, applied + f"\n999\t999_from_a_newer_release\t{'a' * 64}"
                )
            # An applied migration whose file content no longer matches the
            # recorded digest is the same class of drift.
            drifted = applied.splitlines()
            head, name, _ = drifted[-1].split("\t")
            drifted[-1] = f"{head}\t{name}\t{'b' * 64}"
            with self.assertRaisesRegex(module.LockError, "does not match the recorded"):
                module.validate_applied_migrations(lock, "\n".join(drifted))
            with self.assertRaisesRegex(module.LockError, "malformed schema_migrations"):
                module.validate_applied_migrations(lock, "001\tonly-two-fields")

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
        # The lifecycle render writes config/runtime/secrets/, which every
        # container-creating Compose call bind-mounts. A freshly exported package
        # has none of those files, so a render placed after backup.sh lets the
        # pre-update backup quiesce the gateway and then die on a missing bind
        # source: production down, no recovery point. Keep it ahead of both the
        # mutation flag and the backup.
        render = script.index('python3 scripts/render_channel_config.py "$ENV_FILE"')
        mutation = script.index("MUTATION_STARTED=1")
        self.assertLess(
            render, mutation,
            "update.sh renders config/runtime/secrets/ after arming MUTATION_STARTED; "
            "a fresh package directory would quiesce the deployment and then fail on "
            "the missing secrets bind source",
        )
        self.assertLess(
            render, backup,
            "update.sh renders config/runtime/secrets/ after backup.sh, whose first "
            "container-creating Compose call needs those files to exist",
        )

    def test_quiesce_is_verified_against_the_services_it_stops(self) -> None:
        # `compose stop <service>` does not reach a `docker compose run` one-off,
        # which is how every CLI turn executes, so the stop alone cannot justify
        # backup.sh's constant `state_quiesced=true`. Derive the guarded names
        # from each script's own stop line rather than restating them here, so a
        # service added to the stop is either guarded or fails this test.
        backup = body("backup.sh")
        stop_line = next(
            line for line in backup.splitlines()
            if "compose --profile tools stop" in line
        )
        stopped = [
            word for word in stop_line.split()
            if word.startswith("openclaw-")
        ]
        self.assertEqual(["openclaw-cli", "openclaw-gateway"], stopped, stop_line)
        guard = next(
            (line for line in backup.splitlines() if line.startswith("for service in ")),
            "",
        )
        guarded = [
            word.rstrip(";") for word in guard.split()
            if word.startswith("openclaw-")
        ]
        self.assertEqual(
            stopped, guarded,
            "backup.sh must re-read the running set for exactly the services it "
            f"stops; stop={stopped} guard={guarded}",
        )
        self.assertLess(
            backup.index("compose --profile tools stop"),
            backup.index("for service in "),
            "the quiesce verification must run after the stop it verifies",
        )

        # `ps --status running` alone omits `docker compose run` one-offs on
        # Compose 2.20-2.23, and docs/RUNBOOK.md's documented floor is 2.20 —
        # measured across pinned plugin builds: 2.20.0/2.21.0/2.22.0/2.23.3 hide
        # the one-off, 2.24.7 and later list it. Every gate host runs a newer
        # Compose, so a guard written without `--all` is inert exactly on the
        # oldest supported host and no gate can see it. Pin the flag on every
        # such call rather than only the guard's position.
        # Tokenise rather than match a substring: `ps --services --status running`
        # is the same invocation with the flags reordered, and a substring pin
        # silently stops covering it.
        for name in ("backup.sh", "restore.sh", "update.sh"):
            joined = body(name).replace("\\\n", " ")
            for line in joined.splitlines():
                tokens = line.split()
                if "ps" not in tokens or "--status" not in " ".join(tokens):
                    continue
                if not any(token.startswith("--status") for token in tokens):
                    continue
                self.assertTrue(
                    {"--all", "-a"} & set(tokens),
                    f"{name}: a `compose ps --status ...` invocation without --all "
                    f"does not list a `docker compose run` one-off on Compose "
                    f"2.20-2.23, the documented floor, so the quiesce check it feeds "
                    f"is inert exactly on the oldest supported host: {line.strip()}",
                )

        # restore.sh and update.sh check pre-mutation instead, where the gateway
        # is still legitimately running, so only the CLI one-off is a valid
        # signal there. backup.sh's post-stop loop remains the backstop for a
        # one-off that starts during the stop itself.
        # The two blocks are near-identical and were introduced together, so a
        # refactor breaks both at once: run them as subTests and assert the
        # guard is present before ordering it, or one script's regression is
        # masked by the other's failure and a deleted guard raises a bare
        # ValueError from `.index()` that names no script at all.
        for name in ("restore.sh", "update.sh"):
            with self.subTest(script=name):
                script = body(name)
                self.assertEqual(
                    script.count("| grep -Fxq openclaw-cli"), 1,
                    f"{name} must carry exactly one refusal of a live "
                    f"'docker compose run' CLI turn; the ordering assertion below "
                    f"reads the first occurrence, so a missing or duplicated guard "
                    f"makes it meaningless",
                )
                self.assertEqual(
                    script.count("MUTATION_STARTED=1"), 1,
                    f"{name} must arm MUTATION_STARTED exactly once; the ordering "
                    f"assertion below has nothing to order the CLI refusal against "
                    f"otherwise",
                )
                self.assertLess(
                    script.index("| grep -Fxq openclaw-cli"),
                    script.index("MUTATION_STARTED=1"),
                    f"{name} must refuse a live 'docker compose run' CLI turn before "
                    f"it starts mutating; refusing afterwards leaves the deployment "
                    f"stopped with no recovery point",
                )

    def test_every_mutation_flag_is_armed_before_the_command_it_guards(self) -> None:
        # `trap '...' HUP INT QUIT TERM` runs between commands, so a signal delivered
        # during the guarded command is handled with the flag still at its old
        # value. A flag armed on the line after its command therefore leaves the
        # cleanup handler blind: measured on backup.sh, one SIGTERM during
        # `compose stop` left the gateway down, skipped the restore branch and
        # printed nothing at all, and the next backup reported success while
        # production was still offline. Each pair below is (flag assignment,
        # the command whose failure the flag makes recoverable).
        # Each command is anchored with its exact redirection: the bare form also
        # appears inside restore.sh's and update.sh's cleanup handlers, where it
        # is `>/dev/null 2>&1 || true`, and matching that occurrence would
        # compare the flag against the wrong line.
        guarded = {
            "backup.sh": (
                "QUIESCED=1",
                "compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null\n",
            ),
            "bootstrap.sh": (
                "MUTATION_STARTED=1",
                'OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" ./scripts/rotate_runtime_role.sh',
            ),
            "restore.sh": (
                "MUTATION_STARTED=1",
                "compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null\n",
            ),
            "rotate_runtime_role.sh": (
                "ROTATION_STARTED=1",
                "compose --profile tools stop openclaw-cli openclaw-gateway\n",
            ),
            "update.sh": ("MUTATION_STARTED=1", './scripts/backup.sh "$BACKUP_DESTINATION"'),
        }
        # The map above is a hand-written world, and a hand-written world is how
        # this test came to be named "every mutation flag" while covering three of
        # the four scripts that arm one. bootstrap.sh was the omission: it arms
        # MUTATION_STARTED and guards the runtime-role rotation with it, and
        # moving its flag to the wrong side of the rotation -- the exact defect
        # its own comment forbids, and a state this wave reached once -- left all
        # of g7 green. Derive the world from the shipped scripts and require an
        # entry for every member, so the next script to grow a flag cannot be
        # silently excluded the way bootstrap.sh was.
        # Derive the FLAG NAMES too, not just the scripts. Filtering on the two
        # literals "MUTATION_STARTED=1" and "QUIESCED=1" was itself a hand-written
        # world one level up: rotate_runtime_role.sh arms ROTATION_STARTED, whose
        # cleanup branch runs the identical `compose --profile tools stop
        # openclaw-cli openclaw-gateway`, and it was silently excluded exactly the
        # way bootstrap.sh had been. Measured: moving that flag below the stop it
        # guards left all of g7, the offline gate, ruff and ty green.
        #
        # The property, not the spelling: a mutation flag is a variable assigned
        # `=1` on its own line whose name is tested `-eq 1` inside the cleanup
        # handler, in a branch that stops the consumers.
        arming: dict[str, str] = {}
        for path in shipped_shell_scripts():
            lines = path.read_text(encoding="utf-8").split("\n")
            armed = set(
                re.findall(r"^([A-Z][A-Z0-9_]*)=1$", "\n".join(lines), re.M)
            )
            if not armed:
                continue
            starts = [i for i, line in enumerate(lines) if line.startswith("cleanup()")]
            if not starts:
                continue
            start = starts[0]
            end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
            # Join shell line continuations first. backup.sh's guard is
            # `[ "$status" -ne 0 ] && [ "$QUIESCED" -eq 1 ] && \` continued onto
            # the next line, and scanning raw lines upward finds the continuation
            # before the head — which names only GATEWAY_WAS_RUNNING and so lost
            # QUIESCED entirely.
            logical: list[str] = []
            pending = ""
            for line in lines[start:end]:
                stripped = line.strip()
                pending = f"{pending} {stripped}" if pending else stripped
                if pending.endswith("\\"):
                    pending = pending[:-1].rstrip()
                    continue
                logical.append(pending)
                pending = ""
            if pending:
                logical.append(pending)
            for i, statement in enumerate(logical):
                if "compose" not in statement:
                    continue
                if not any(c in statement for c in ("openclaw-gateway", "openclaw-cli")):
                    continue
                # The flag gating this consumer action is the one named by the
                # NEAREST enclosing `if`, not an outer one: rotate's consumer stop
                # sits inside `if [ "$ROTATION_LOCK_OWNED" -eq 1 ]`, and it is
                # ROTATION_STARTED that decides whether it runs.
                for j in range(i, -1, -1):
                    named = re.findall(r'\[ "\$([A-Z][A-Z0-9_]*)" -eq 1 \]', logical[j])
                    if not named:
                        continue
                    # A flag armed at top level arms recovery; one armed indented
                    # (backup.sh's GATEWAY_WAS_RUNNING) merely records observed
                    # state, and is not a mutation flag.
                    for name in named:
                        if name in armed:
                            arming[path.name] = f"{name}=1"
                    break
                break
        self.assertEqual(
            arming, {name: flag for name, (flag, _) in guarded.items()},
            "every shipped script that arms a flag gating the consumer stop needs "
            f"an entry here. Derived {arming}; listed "
            f"{ {name: flag for name, (flag, _) in guarded.items()} }.",
        )
        for name, (flag, command) in guarded.items():
            with self.subTest(script=name):
                script = body(name)
                self.assertEqual(
                    1, script.count(flag),
                    f"{name} must arm {flag} exactly once for this ordering to be unambiguous",
                )
                self.assertEqual(
                    1, script.count(command),
                    f"{name}: `{command.strip()}` is no longer unique, so this ordering "
                    f"check may be comparing against the wrong occurrence",
                )
                self.assertLess(
                    script.index(flag), script.index(command),
                    f"{name} arms {flag} after `{command}`. A signal during that "
                    f"command is handled with the flag still unset, so cleanup skips "
                    f"the branch that would report or undo the half-finished state",
                )

    def test_the_two_inbox_guards_refuse_exactly_the_same_classes(self) -> None:
        """backup.sh and update.sh each carry a copy of the inbox guard. Pin them together.

        update.sh reaches backup.sh's guard only AFTER arming MUTATION_STARTED, so
        mirroring the check in one place is not enough: a refusal that lands there
        stops openclaw-cli and openclaw-gateway and points the operator at a
        pre-update recovery point backup.sh refused before writing. update.sh
        therefore carries its own copy ahead of its quiesce, and both scripts say
        in prose that the two class lists must stay identical.

        They drifted. Measured under Debian dash on fixture inboxes, before the
        eighteenth pass's round-3 repair: update.sh carried three of backup.sh's
        five classes, so a backslash-named or hard-linked inbox entry was ACCEPTED
        pre-quiesce and refused only afterwards. The same copy matched the
        ABSOLUTE entry rather than the inbox-relative path, which is the spelling
        backup.sh's own comment warns against -- a package installed under a
        directory whose own name carries a control character had every clean inbox
        refused, also measured.

        A duplicated list cannot enforce itself and a comment saying "keep these
        identical" is not a check. Extracting a shared sourced helper was
        considered and rejected: it puts a new file into manifest.json and into
        `shipped_shell_scripts()`, and gives two lifecycle scripts a
        missing-file failure mode. This test is the enforcement instead. Both
        sides are derived from the scripts, so the test holds no third copy of
        the class list that could drift on its own.
        """
        def guard(name: str) -> tuple[frozenset[str], frozenset[str], bool, bool]:
            text = body(name)
            block = re.search(
                r'inbox_relative="\$\{entry#"\$PACKAGE_INBOX"/\}"\s*\n'
                r'(?:\s*#[^\n]*\n)*'
                r'\s*case "\$inbox_relative" in\n(.*?)\n\s*esac',
                text, re.S,
            )
            self.assertIsNotNone(
                block,
                f"{name}: could not find the inbox guard's `case` over the "
                f"inbox-relative path. Either the guard was removed, or it went "
                f"back to matching the absolute `$entry` -- the spelling that "
                f"refuses every run on a package installed under a directory "
                f"whose own name carries one of these characters.",
            )
            assert block is not None
            patterns = frozenset(
                re.findall(r'^\s*(\*[^)]*\))\s*inbox_reject=', block.group(1), re.M)
            )
            reasons = frozenset(
                re.findall(r'inbox_reject="\$entry \(([^)]*)\)"', text)
            )
            hardlink = bool(re.search(
                r'find "\$PACKAGE_INBOX" -mindepth 1 -type f -links \+1', text
            ))
            refuses = "inbox holds an entry a recovery archive cannot represent" in text
            return patterns, reasons, hardlink, refuses

        # The class LABELS are not the guard. Extracting the `case` patterns, the
        # reject reason strings and the hard-link `find` covers three of the five
        # predicates: the symlink test `[ -L "$entry" ]` and the not-a-regular-file
        # test `[ ! -f ... ] && [ ! -d ... ]` are ordinary `if`s whose labels stay
        # put when the predicate is neutered. Measured: appending `&& false` to
        # either one in update.sh left ALL of g7 green while that class stopped
        # refusing anything. So compare the two guard BODIES first — every code
        # line, in order — and treat the class-set checks below as the friendlier
        # message for the common case rather than as the enforcement.
        def code_lines(name: str, remedy: str) -> list[str]:
            text = body(name)
            start = text.index('inbox_reject=""')
            end = text.index(remedy)
            end = text.index("\n", text.index("\n", end) + 1) + 1
            return [
                line.rstrip()
                for line in text[start:end].split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]

        authority_body = code_lines("backup.sh", "remove or relocate it before backing up")
        mirror_body = [
            line.replace("before updating", "before backing up")
            for line in code_lines("update.sh", "remove or relocate it before updating")
        ]
        if authority_body != mirror_body:
            difference = "\n".join(
                difflib.unified_diff(
                    authority_body, mirror_body,
                    "scripts/backup.sh", "scripts/update.sh", lineterm="", n=1,
                )
            )
            self.fail(
                "the two inbox guards have diverged. Every code line must be "
                "identical apart from the remedy's last two words, because the "
                "list cannot enforce itself and a comment saying 'keep these "
                "identical' is not a check:\n" + difference
            )

        authority = guard("backup.sh")
        mirror = guard("update.sh")
        self.assertEqual(
            authority[0], mirror[0],
            "backup.sh and update.sh must refuse the same `case` patterns on the "
            f"inbox-relative path. backup.sh has {sorted(authority[0])}, "
            f"update.sh has {sorted(mirror[0])}. A class present in only one copy "
            f"is refused on the wrong side of update.sh's quiesce.",
        )
        self.assertEqual(
            authority[1], mirror[1],
            "backup.sh and update.sh must refuse the same inbox entry classes. "
            f"backup.sh refuses {sorted(authority[1])}, update.sh refuses "
            f"{sorted(mirror[1])}.",
        )
        self.assertTrue(
            authority[2] and mirror[2],
            "both scripts must carry the `-links +1` hard-link scan: a hard-linked "
            "regular file passes every per-entry test, but tar emits the second "
            "name as a link member and validate_recovery_archive.py then refuses "
            "the whole archive. backup.sh has it: "
            f"{authority[2]}; update.sh has it: {mirror[2]}",
        )
        self.assertTrue(authority[3] and mirror[3], "both guards must refuse, not just classify")
        update = body("update.sh")
        self.assertLess(
            update.index("inbox holds an entry"), update.index("MUTATION_STARTED=1\n"),
            "update.sh must refuse an unarchivable inbox entry BEFORE arming "
            "MUTATION_STARTED. Refusing afterwards runs the cleanup that stops "
            "both consumers, for an entry that could have been named while the "
            "gateway was still serving.",
        )

    def test_both_inbox_guards_refuse_every_class_when_actually_executed(self) -> None:
        """Run the guards. Parity alone cannot see a symmetric mistake.

        `test_the_two_inbox_guards_refuse_exactly_the_same_classes` compares the
        two copies to each other, so an edit applied to BOTH is invisible to it.
        Measured: deleting the control-character probe from both scripts, and
        separately neutering the symlink test in both with `&& false`, each left
        every offline suite green while reopening the escape that stops production
        after the quiesce.

        So execute the shipped block. Each guard is lifted verbatim, given a
        fixture inbox, and run under EVERY POSIX shell present on the host --
        `/bin/sh` plus whichever of `dash` and `bash` is installed. A single shell
        would not do: `/bin/sh` is dash on the Debian deployment and bash-in-sh-mode
        on the macOS gate host, so a bashism in both copies passes every gate here
        and kills every backup and every update there, and `sh -n` does not catch
        one (it parses `[[ ]]` under bash). An earlier draft of this docstring
        claimed "the dash matrix in the release evidence covers the other shell";
        no such artifact exists -- docs/V3_RELEASE_EVIDENCE.md does not contain the
        word. A refusal must name its class
        and say nothing has been stopped; a legal inbox must be accepted, because
        a guard that over-refuses blocks every backup and every update on that
        deployment.
        """
        def guard_source(name: str, remedy: str) -> str:
            """The guard verbatim, INCLUDING the `fi` that closes its reporter.

            `code_lines()` above stops one line earlier because it only compares
            the two copies to each other and the omission is symmetric. Executing
            the block needs the terminator, or `sh` reports "unexpected end of
            file" and the run says nothing about the guard.
            """
            text = body(name)
            start = text.index('inbox_reject=""')
            cursor = text.index(remedy)
            for _ in range(3):                    # remedy line, `exit 1`, `fi`
                cursor = text.index("\n", cursor) + 1
            return text[start:cursor]

        guards = {
            "backup.sh": guard_source("backup.sh", "remove or relocate it before backing up"),
            "update.sh": guard_source("update.sh", "remove or relocate it before updating"),
        }
        for name, source in guards.items():
            self.assertIn("[[:cntrl:]]", source, f"{name}: the guard lost its control-character probe")
            self.assertIn("-links +1", source, f"{name}: the guard lost its hard-link scan")

            # Every control-character classification must be locale-independent.
            # `[[:cntrl:]]` is resolved against the caller's LC_CTYPE, and the
            # UTF-8 bytes of an ordinary CJK filename include 0x97, 0x9C and
            # 0x9E -- all C1 controls in ISO-8859-15. Measured on Debian under
            # LC_ALL=en_US.ISO-8859-15: the guard refused a clean inbox, which
            # blocks EVERY backup and EVERY update on that deployment. Under
            # LC_ALL=C the class is exactly 0x00-0x1F and 0x7F, which is what
            # scripts/validate_recovery_archive.py refuses -- so the guard and
            # the validator agree on every host.
            #
            # Pin the enumerable world rather than widening a detector: a `case`
            # pattern cannot be scoped to a locale, so the ONLY admissible
            # spelling is inside a command prefixed with LC_ALL=C. Every
            # occurrence is checked, so a second one added later is caught.
            # The WHOLE script, not just the extracted guard. The first version
            # of this pin scanned `source` -- the lifted inbox-guard block -- and
            # so could not see the package-path guard near the top of the file,
            # which was written as a bare `case ... *[[:cntrl:]]*)` and carried
            # exactly the defect this pin exists to prevent. A pin that covers
            # less than the file it is about is the round's recurring defect.
            for line in body(name).split("\n"):
                if "[[:cntrl:]]" not in line or line.lstrip().startswith("#"):
                    continue
                with self.subTest(script=name, line=line.strip()[:70]):
                    self.assertIn(
                        "LC_ALL=C", line,
                        f"{name} classifies control characters without LC_ALL=C: "
                        f"{line.strip()!r}. The verdict then depends on the "
                        f"operator's LANG -- under ISO-8859-15 the UTF-8 bytes of "
                        f"a CJK filename read as C1 controls and the guard "
                        f"refuses a clean inbox, stopping every backup and every "
                        f"update on that deployment.",
                    )

        # (label, builder, must_refuse, expected fragment of the reason)
        def plant_clean(inbox: Path) -> None:
            (inbox / "deck.pdf").write_text("x\n", encoding="utf-8")
            (inbox / "two words.pdf").write_text("x\n", encoding="utf-8")
            # Through BYTES paths. `write_text`'s encoding= governs the CONTENT;
            # the FILENAME goes through sys.getfilesystemencoding(), which follows
            # the locale. Measured on the deployed floor (python:3.11-slim,
            # LC_ALL=en_US.ISO-8859-15 -> fsencoding iso8859-15): the str form
            # raises UnicodeEncodeError and this test errors, so the release gate
            # fails on a legal host. The guards read bytes from `find`, so what
            # matters is the bytes on disk, not the locale that named them.
            for raw_name in ("M\u00fcller.pdf", "\u65e5\u672c\u8a9e.pdf"):
                with open(os.path.join(os.fsencode(inbox), raw_name.encode("utf-8")), "wb") as handle:
                    handle.write(b"x\n")
            nested = inbox / "sub"
            nested.mkdir()
            (nested / "deck.pdf").write_text("x\n", encoding="utf-8")

        def plant_empty(inbox: Path) -> None:
            return None

        def plant_control(inbox: Path) -> None:
            (inbox / "a\x01b.pdf").write_text("x\n", encoding="utf-8")

        def plant_leading_newline(inbox: Path) -> None:
            (inbox / "\nscripts").symlink_to(inbox.parent / "VERSION")

        def plant_embedded_newline(inbox: Path) -> None:
            (inbox / "Q3 pitch\ndeck.pdf").write_text("x\n", encoding="utf-8")

        def plant_backslash(inbox: Path) -> None:
            (inbox / "back\\slash.pdf").write_text("x\n", encoding="utf-8")

        def plant_symlink(inbox: Path) -> None:
            (inbox / "link.pdf").symlink_to(inbox.parent / "VERSION")

        def plant_fifo(inbox: Path) -> None:
            os.mkfifo(inbox / "pipe")

        def plant_hardlink(inbox: Path) -> None:
            first = inbox / "orig.pdf"
            first.write_text("x\n", encoding="utf-8")
            os.link(first, inbox / "second.pdf")

        cases = (
            ("a clean inbox", plant_clean, False, ""),
            ("an empty inbox", plant_empty, False, ""),
            ("a control character", plant_control, True, "control character"),
            ("a leading newline", plant_leading_newline, True, "control character"),
            ("an embedded newline", plant_embedded_newline, True, "control character"),
            ("a backslash", plant_backslash, True, "backslash in path"),
            ("a symlink", plant_symlink, True, "symlink"),
            ("a fifo", plant_fifo, True, "not a regular file or directory"),
            ("a hard link", plant_hardlink, True, "hard link"),
        )

        # The nine cases below are hand-written; the guard's class set is not. If
        # a class is added to the scripts and no case exercises it, this test goes
        # on passing under a name that says "every class". So derive the world
        # from the guard text and require each class to be claimed by a case.
        for name, source in sorted(guards.items()):
            # Derive from EVERY `inbox_reject=` message, not from those matching a
            # particular shape. The first version keyed on a trailing "(...)"
            # group, so a class whose message parenthesises mid-sentence -- the
            # unreadable-inbox refusal below -- was silently outside the derived
            # world and needed no case. A derivation that quietly covers less is
            # the exact defect this whole round was about.
            classes = set(re.findall(r'inbox_reject="([^"]+)"', source))
            self.assertTrue(classes, f"{name}: no refusal class found; the derivation has rotted")
            self.assertGreaterEqual(
                len(classes), 6,
                f"{name}: only {len(classes)} refusal messages found {sorted(classes)}; "
                f"the guard has lost a class or the derivation has rotted",
            )
            expected_fragments = {expected for _, _, must, expected in cases if must}
            expected_fragments.add("could not be fully enumerated")
            unexercised = sorted(
                refusal for refusal in classes
                if not any(fragment in refusal for fragment in expected_fragments)
            )
            self.assertEqual(
                [], unexercised,
                f"{name} refuses {unexercised}, and no case below exercises that "
                f"class. This test is named ..._refuse_every_class_..., so a class "
                f"the scripts have and the fixtures do not is exactly the gap the "
                f"name denies. Add a case per class.",
            )

        # Differential: the guard exists to refuse, BEFORE the quiesce, exactly
        # what scripts/validate_recovery_archive.py would refuse after it. Ask
        # the validator rather than restating its rule a fifth time, and compare
        # verdicts name by name. This is what proves LC_ALL=C is the right
        # classification and not merely a different one: the C locale's cntrl
        # class is 0x00-0x1F and 0x7F, and so is the validator's.
        spec = importlib.util.spec_from_file_location(
            "g7_archive_validator", SCRIPTS / "validate_recovery_archive.py"
        )
        assert spec is not None and spec.loader is not None
        archive_validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(archive_validator)

        differential = (
            "plain.pdf",
            "two words.pdf",
            "M\u00fcller.pdf",
            "\u65e5\u672c\u8a9e.pdf",   # UTF-8 bytes include 0x97/0x9C/0x9E
            "a\u0085b.pdf",              # C1 NEL: accepted by BOTH, and the
            "a\u0097b.pdf",              # locale-dependent guard refused these
            "a\x01b.pdf",
            "a\x7fb.pdf",
        )
        validator_refuses = {}
        for candidate in differential:
            try:
                archive_validator.normalized_name(f"inbox/{candidate}")
                validator_refuses[candidate] = False
            except archive_validator.ArchiveError:
                validator_refuses[candidate] = True
        self.assertTrue(
            any(validator_refuses.values()) and not all(validator_refuses.values()),
            f"the differential set no longer separates the two verdicts: "
            f"{validator_refuses}",
        )

        shells = [
            candidate
            for candidate in ("/bin/sh", shutil.which("dash"), shutil.which("bash"))
            if candidate and Path(candidate).exists()
        ]
        # De-duplicate by resolved target: /bin/sh is frequently a link to one of
        # the others, and running the same binary twice is not a matrix.
        seen_shells: dict[str, str] = {}
        for candidate in shells:
            seen_shells.setdefault(str(Path(candidate).resolve()), candidate)
        shells = sorted(seen_shells.values())
        self.assertTrue(
            shells,
            "no POSIX shell found to execute the guards with; this test would "
            "otherwise pass without running anything",
        )

        for shell in shells:
            for name, source in sorted(guards.items()):
                for label, plant, must_refuse, expected in cases:
                    with self.subTest(shell=shell, script=name, case=label):
                        with tempfile.TemporaryDirectory(prefix="g7-guard-exec-") as raw:
                            package = Path(raw)
                            # A `scripts` directory and a VERSION file, so a fragment
                            # of a split name can resolve against the package the way
                            # it does on a real deployment.
                            (package / "scripts").mkdir()
                            (package / "VERSION").write_text("3.0.0\n", encoding="utf-8")
                            inbox = package / "inbox"
                            inbox.mkdir()
                            plant(inbox)
                            runner = package / "guard.sh"
                            runner.write_text(
                                # Invoked as `<shell> guard.sh`, so this line is inert;
                            # the matrix above decides the interpreter.
                            "set -eu\n"
                                f'PACKAGE_INBOX="{inbox}"\n'
                                f"{source}"
                                'echo "GUARD ACCEPTED"\n',
                                encoding="utf-8",
                            )
                            done = subprocess.run(
                                [shell, str(runner)],
                                cwd=package, text=True, capture_output=True, timeout=60,
                            )
                            output = done.stdout + done.stderr
                            if must_refuse:
                                self.assertNotEqual(
                                    0, done.returncode,
                                    f"{name} ACCEPTED {label}. That entry reaches "
                                    f"validate_recovery_archive.py, which refuses it "
                                    f"after the quiesce with production stopped and no "
                                    f"recovery point written: {output}",
                                )
                                self.assertIn(
                                    "a recovery archive cannot represent", output,
                                    f"{name} refused {label} without the operator-facing "
                                    f"message: {output}",
                                )
                                self.assertIn(
                                    expected, output,
                                    f"{name} refused {label} but named the wrong class; "
                                    f"the operator is sent after the wrong entry: {output}",
                                )
                                self.assertIn(
                                    "nothing has been stopped", output,
                                    f"{name} refused {label} without telling the operator "
                                    f"the deployment is untouched: {output}",
                                )
                            else:
                                self.assertEqual(
                                    0, done.returncode,
                                    f"{name} REFUSED {label}. A guard that over-refuses "
                                    f"blocks every backup and every update on that "
                                    f"deployment: {output}",
                                )

        # The unreadable-inbox class, which no fixture above can plant: it is a
        # permission state, not a name. Mode bits do not deny root, so probe what
        # this process can actually do rather than assuming the chmod denied it.
        for shell in shells:
            for name, source in sorted(guards.items()):
                with self.subTest(shell=shell, script=name, case="an unreadable subtree"):
                    with tempfile.TemporaryDirectory(prefix="g7-guard-unreadable-") as raw:
                        package = Path(raw)
                        (package / "scripts").mkdir()
                        (package / "VERSION").write_text("3.0.0\n", encoding="utf-8")
                        inbox = package / "inbox"
                        inbox.mkdir()
                        (inbox / "ok.pdf").write_text("x\n", encoding="utf-8")
                        locked = inbox / "locked"
                        locked.mkdir()
                        (locked / "payload.pdf").write_text("x\n", encoding="utf-8")
                        locked.chmod(0o000)
                        try:
                            try:
                                os.listdir(locked)
                                denied = False
                            except OSError:
                                denied = True
                            runner = package / "guard.sh"
                            runner.write_text(
                                "set -eu\n"
                                f'PACKAGE_INBOX="{inbox}"\n'
                                f"{source}"
                                'echo "GUARD ACCEPTED"\n',
                                encoding="utf-8",
                            )
                            done = subprocess.run(
                                [shell, str(runner)],
                                cwd=package, text=True, capture_output=True, timeout=60,
                            )
                        finally:
                            locked.chmod(0o755)
                    output = done.stdout + done.stderr
                    if denied:
                        self.assertNotEqual(
                            0, done.returncode,
                            f"{name} accepted an inbox holding a subtree it cannot "
                            f"read. It tars that inbox into the recovery point, so "
                            f"the archive would silently omit it: {output}",
                        )
                        self.assertIn(
                            "could not be fully enumerated", output,
                            f"{name} stopped on an unreadable subtree without naming "
                            f"the class. Written as a bare assignment this died under "
                            f"`set -e` with nothing but find's stderr, and an "
                            f"unreadable directory under the inbox is a state the two "
                            f"integrity checkers deliberately tolerate, so it is "
                            f"reachable on a healthy deployment: {output}",
                        )
                        self.assertIn(
                            "nothing has been stopped", output,
                            f"{name} refused an unreadable subtree without telling the "
                            f"operator the deployment is untouched: {output}",
                        )
                    else:
                        self.assertEqual(
                            0, done.returncode,
                            f"{name} refused an inbox this process can read perfectly "
                            f"well (running as root, where mode bits do not deny): "
                            f"{output}",
                        )

        for shell in shells:
            for name, source in sorted(guards.items()):
                for candidate, refused in sorted(validator_refuses.items()):
                    with self.subTest(shell=shell, script=name, differential=candidate):
                        with tempfile.TemporaryDirectory(prefix="g7-guard-diff-") as raw:
                            package = Path(raw)
                            (package / "scripts").mkdir()
                            (package / "VERSION").write_text("3.0.0\n", encoding="utf-8")
                            inbox = package / "inbox"
                            inbox.mkdir()
                            # Bytes path: the name must land on disk as these
                            # exact bytes whatever the locale is.
                            target = os.path.join(
                                os.fsencode(inbox), candidate.encode("utf-8")
                            )
                            with open(target, "wb") as handle:
                                handle.write(b"x\n")
                            runner = package / "guard.sh"
                            runner.write_text(
                                "set -eu\n"
                                f'PACKAGE_INBOX="{inbox}"\n'
                                f"{source}"
                                'echo "GUARD ACCEPTED"\n',
                                encoding="utf-8",
                            )
                            done = subprocess.run(
                                [shell, str(runner)],
                                cwd=package, text=True, capture_output=True, timeout=60,
                            )
                        self.assertEqual(
                            refused, done.returncode != 0,
                            f"{name} and validate_recovery_archive.py DISAGREE about "
                            f"{candidate!r}: the validator "
                            f"{'refuses' if refused else 'accepts'} it, the guard "
                            f"{'refused' if done.returncode else 'accepted'} it. The "
                            f"guard exists to refuse before the quiesce exactly what "
                            f"the validator refuses after it. Refusing more blocks "
                            f"every backup and every update on a legal deployment; "
                            f"refusing less lets the failure land after "
                            f"MUTATION_STARTED, with production stopped and no "
                            f"recovery point written. Output: "
                            f"{done.stdout}{done.stderr}",
                        )

    def test_both_scripts_refuse_a_package_path_holding_a_control_character(self) -> None:
        """A newline in the PACKAGE path must be named as such, not blamed on the inbox.

        Both guards enumerate entries from newline-delimited `find` output. If the
        package directory's own path holds a newline, every entry splits into
        fragments: the inbox check then refuses every backup and every update,
        names paths that do not exist, and reports "control character in path"
        against an entry whose name is clean. The operator is sent to correct the
        inbox, which is not where the problem is.

        The guard is at the top of each script, outside the block the executing
        test lifts, so it needs its own cover.
        """
        for name in ("backup.sh", "update.sh"):
            source = body(name)
            with self.subTest(script=name):
                self.assertIn(
                    "package_inbox_stripped=", source,
                    f"{name} no longer checks its own package path before "
                    f"enumerating entries under it",
                )
                # Non-comment lines only: the guard's own comment names the
                # construct it deliberately avoids, and matching that would make
                # this assertion forbid its own explanation.
                code_lines = "\n".join(
                    line for line in source.split("\n")
                    if not line.lstrip().startswith("#")
                )
                self.assertNotIn(
                    'case "$PACKAGE_INBOX" in', code_lines,
                    f"{name} checks its own path with a `case` pattern again. A "
                    f"case is matched in the script's own locale and cannot be "
                    f"scoped to C, so the verdict varies by locale and platform: "
                    f"measured, a raw 0x97 is refused under en_US.UTF-8 and "
                    f"accepted under ca_FR.ISO8859-15 on the same host.",
                )

        extracted = {}
        for name in ("backup.sh", "update.sh"):
            text = body(name)
            start = text.index("package_inbox_stripped=")
            end = text.index("\nfi\n", start) + len("\nfi\n")
            extracted[name] = text[start:end]

        for name, source in sorted(extracted.items()):
            for label, package_dir, must_refuse in (
                ("a clean package path", "/srv/openclaw", False),
                ("a newline in the package path", "/srv/open\nclaw", True),
                ("a tab in the package path", "/srv/open\tclaw", True),
                # Must be ACCEPTED: these are ordinary paths, and the earlier
                # `case` form refused them on some locale/platform pairs, which
                # blocks every backup and every update on that deployment.
                ("a CJK package path", "/srv/\u65e5\u672c\u8a9e/openclaw", False),
                ("an accented package path", "/srv/M\u00fcller/openclaw", False),
                ("a raw C1 byte in the package path", "/srv/a\u0097b/openclaw", False),
            ):
                with self.subTest(script=name, case=label):
                    runner = (
                        "set -eu\n"
                        f'PACKAGE_DIR="{package_dir}"\n'
                        f'PACKAGE_INBOX="{package_dir}/inbox"\n'
                        f'{source}'
                        'echo "PATH ACCEPTED"\n'
                    )
                    with tempfile.TemporaryDirectory(prefix="g7-pkgpath-") as raw:
                        script = Path(raw) / "probe.sh"
                        script.write_text(runner, encoding="utf-8")
                        done = subprocess.run(
                            ["/bin/sh", str(script)],
                            text=True, capture_output=True, timeout=60,
                        )
                    output = done.stdout + done.stderr
                    if must_refuse:
                        self.assertNotEqual(
                            0, done.returncode,
                            f"{name} accepted {label}; every entry it enumerates "
                            f"will be a fragment: {output}",
                        )
                        self.assertIn(
                            "package directory's own path", output,
                            f"{name} refused {label} but did not say the PACKAGE "
                            f"path is the problem, sending the operator to the "
                            f"inbox instead: {output}",
                        )
                        self.assertIn(
                            "Nothing has been stopped", output,
                            f"{name} refused {label} without telling the operator "
                            f"the deployment is untouched: {output}",
                        )
                    else:
                        self.assertEqual(
                            0, done.returncode,
                            f"{name} refused {label}; an ordinary package path "
                            f"must pass: {output}",
                        )

    def test_every_caller_of_the_rotation_checks_its_lock_before_arming(self) -> None:
        """A refusal that touched nothing must not stop a healthy deployment.

        rotate_runtime_role.sh acquires /tmp/openclaw-lead-research-v3-rotation.lock
        as its first act in that lane, and a crash-left lock is a state
        docs/OPERATIONS.md documents as an expected leftover -- it says the copy
        "can outlive an interrupted bootstrap or update". At that point the
        rotation has changed nothing and its own cleanup stops nothing, because
        ROTATION_STARTED is still 0. But its CALLERS arm their mutation flag
        before invoking it (deliberately: `trap ... HUP INT QUIT TERM` runs
        between commands, so a signal during the rotation must be handled with
        the flag already set), so the caller's cleanup runs
        `compose --profile tools stop openclaw-cli openclaw-gateway`.

        Measured under Debian dash with a stub rotation refusing at lock
        acquisition: without a pre-check, bootstrap.sh printed "openclaw-gateway
        and openclaw-cli are stopped" and ran that stop against a deployment
        nothing had touched. update.sh gained the pre-check in this wave;
        bootstrap.sh did not, and reached the identical refusal through the
        identical call. Both now carry it, and CLAUDE.md instructs re-running
        bootstrap.sh on an already-bootstrapped deployment, so this is a live
        path rather than first-install-only.

        The caller set is derived, so a third caller cannot be added without
        either carrying the check or failing here.
        """
        callers = sorted(
            path.name
            for path in shipped_shell_scripts()
            if "./scripts/rotate_runtime_role.sh" in path.read_text(encoding="utf-8")
            and "MUTATION_STARTED=1" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            ["bootstrap.sh", "update.sh"], callers,
            "the set of scripts that arm a mutation flag and then invoke the "
            "runtime-role rotation has changed; a new one needs the same "
            "pre-check, and one that stopped doing so needs this list updated",
        )
        for name in callers:
            with self.subTest(script=name):
                script = body(name)
                # assertTrue, not assertIn: assertIn appends an untruncated repr
                # of the container, and these scripts are 10-25 KB. The script text
                # is not what a reader needs to see.
                self.assertTrue(
                    'ROTATION_LOCK_DIR="/tmp/openclaw-lead-research-v3-rotation.lock"'
                    in script,
                    f"{name} invokes the rotation after arming a mutation flag, so "
                    f"it must refuse a crash-left rotation lock itself, while "
                    f"production is still running",
                )
                # Order the REFUSAL, not the assignment. Pinning
                # `index("ROTATION_LOCK_DIR=")` ordered only the variable
                # definition: moving the `if` block twelve lines below it, down
                # past the flag, left every assertion here true while restoring
                # the blocker in both callers. Measured.
                # Derive the path from the rotation itself. It existed as four
                # independent literals — rotate_runtime_role.sh's own LOCK_DIR,
                # the two mirrors, and this test — with nothing binding them, so
                # renaming rotate's lock left both mirrors checking a path
                # nothing creates: two dead guards with this test still green.
                rotation = body("rotate_runtime_role.sh")
                lock_path = re.search(r'^LOCK_DIR="([^"]+)"$', rotation, re.M)
                self.assertIsNotNone(
                    lock_path,
                    "rotate_runtime_role.sh no longer declares LOCK_DIR on its own "
                    "line, so the callers' mirrors cannot be checked against it",
                )
                assert lock_path is not None
                self.assertIn(
                    f'ROTATION_LOCK_DIR="{lock_path.group(1)}"', script,
                    f"{name} pre-checks a different path than the rotation "
                    f"actually locks ({lock_path.group(1)}), so its guard can "
                    f"never fire",
                )
                refusal = 'if [ -e "$ROTATION_LOCK_DIR" ]; then'
                self.assertIn(
                    refusal, script,
                    f"{name} no longer refuses on the rotation lock; the variable "
                    f"alone is not the guard",
                )
                self.assertLess(
                    script.index(refusal),
                    script.index("MUTATION_STARTED=1\n"),
                    f"{name} refuses on the rotation lock after arming its mutation "
                    f"flag, which is the same failure as not checking it: the "
                    f"cleanup stops both consumers for a refusal that changed "
                    f"nothing",
                )
                self.assertLess(
                    script.index(refusal),
                    script.index("./scripts/rotate_runtime_role.sh"),
                    f"{name} must refuse on the lock before invoking the rotation",
                )
                # The exit must be inside that block, not merely somewhere after
                # it: a refusal that reports and continues is not a refusal.
                self.assertIn(
                    "exit 1", script[script.index(refusal):script.index(refusal) + 500],
                    f"{name}'s rotation-lock branch does not exit",
                )
                self.assertTrue(
                    "nothing has been changed" in script,
                    f"{name}'s rotation-lock refusal must tell the operator "
                    f"nothing was changed; the cleanup message they would "
                    f"otherwise see says the opposite",
                )

    def test_no_shipped_trap_hides_behind_a_shared_line(self) -> None:
        """The trap inventory reads line-initial `trap` only; prove that is the world.

        `trap_commands()` matches `^trap\\s`, and its own docstring concedes that a
        `trap` written after a `;` on a shared line "would not be seen here, so
        keep them on their own line, as every shipped script does today". Nothing
        asserted the "as every shipped script does today" half, so a handler added
        mid-line was invisible to every assertion built on that inventory —
        including the fatal-signal-set check below. Measured: inserting
        `STAGING_GUARD=1 ; trap 'rm -rf "$STAGING"' HUP INT` into backup.sh left
        all of g7 green.
        """
        # Pin the enumerable world, do not widen a detector. The first version of
        # this check listed the lead-in characters it knew about (`;`, `&`, `|`,
        # `do`, `then`, `else`) and so missed `{`, `(` and `)`: a trap wrapped in
        # a function body — `stage_guard() { trap '...' HUP INT ; }` — passed
        # `sh -n` and `dash -n` and left all seven offline suites green while being
        # invisible to trap_commands(). Counting instead makes the world closed:
        # every `trap` word in the shipped text must be one trap_commands() sees.
        word = re.compile(r"(?<![\w./-])trap(?=\s)")
        mismatched = []
        for path in shipped_shell_scripts():
            # Quote-aware, not "drop whole-line comments": a `trap` inside a
            # quoted operator message or a trailing comment is not a command, and
            # counting it failed the release gate blaming a handler that is not
            # there. Blanking keeps both counters looking at command text only.
            code = "\n".join(
                shell_code_only(line)
                for line in path.read_text(encoding="utf-8").split("\n")
            )
            written = len(word.findall(code))
            # Blanking quotes would hide `eval "trap ... HUP"`, which IS a live
            # handler and which trap_commands() cannot see either. Nothing ships
            # like that; assert it rather than assume it.
            self.assertNotIn(
                "eval", "\n".join(
                    line for line in path.read_text(encoding="utf-8").split("\n")
                    if "trap" in line and "eval" in shell_code_only(line)
                ),
                f"{path.name} passes a trap through eval, where neither "
                f"trap_commands() nor this counter can see it",
            )
            seen = len(trap_commands(path))
            if written != seen:
                mismatched.append(
                    f"{path.name}: {written} `trap` word(s) in the script, "
                    f"{seen} seen by trap_commands()"
                )
        self.assertEqual(
            [], mismatched,
            "a `trap` in a shipped script is not visible to trap_commands(), which "
            "reads line-initial `trap` only — so every assertion built on that "
            "inventory, including the fatal-signal-set check, silently skips it. "
            "Put each trap on its own line, as the first word: " + "; ".join(mismatched),
        )

    def test_every_shipped_trap_names_the_whole_fatal_signal_set(self) -> None:
        """Enumerate the signal sets instead of reviewing twelve trap lines by eye.

        A handler that omits a signal is not run when that signal arrives.
        Measured under Debian dash: `trap cleanup EXIT HUP INT TERM` plus
        SIGQUIT exits 131 with the handler never entered, while the same trap
        naming QUIT runs it. The eighteenth pass added QUIT to all twelve trap
        lines in scripts/ and missed `migrations/000_roles.sh`, whose handler is
        the one that erases the three mode-0600 /dev/shm files holding the
        openclaw_runtime and openclaw_owner passwords -- so a SIGQUIT during the
        credential proof left both passwords in cleartext in the container's
        /dev/shm. Nothing in the package enumerated the sets, so nothing caught
        it; reviewing them by eye is exactly what failed.

        Three rules, each of which that omission breaks:
          1. no trap line may name a proper non-empty subset of the fatal four;
          2. a script that installs any trap must arm all four somewhere;
          3. a `trap -` disarm must name exactly what that script armed, so an
             arm and its disarm cannot drift apart.
        """
        measured: dict[str, list[tuple[int, str, str, frozenset[str]]]] = {}
        for path in shipped_shell_scripts():
            commands = trap_commands(path)
            if commands:
                measured[path.relative_to(PACKAGE).as_posix()] = commands

        missing = [name for name in TRAP_BEARING_SCRIPTS if name not in measured]
        self.assertEqual(
            [], missing,
            f"these shipped scripts no longer install any trap: {missing}. A "
            f"script that loses its handler stops cleaning up its staging, its "
            f"lock or its credential files on interrupt. If a handler was "
            f"deliberately removed, drop the path from TRAP_BEARING_SCRIPTS in "
            f"the same commit and say why.",
        )

        for relative, commands in sorted(measured.items()):
            with self.subTest(script=relative):
                armed: set[str] = set()
                installs = 0
                for number, line, action, signals in commands:
                    fatal = signals & FATAL_TRAP_SIGNALS
                    self.assertIn(
                        fatal, (frozenset(), FATAL_TRAP_SIGNALS),
                        f"{relative}:{number}: `{line}` names only "
                        f"{sorted(fatal)} of {sorted(FATAL_TRAP_SIGNALS)}. dash "
                        f"does not run a handler for a signal it was not armed "
                        f"for, so the omitted signal leaks whatever this handler "
                        f"cleans up.",
                    )
                    if action != "-":
                        installs += 1
                        armed |= signals
                if installs:
                    self.assertEqual(
                        FATAL_TRAP_SIGNALS, armed & FATAL_TRAP_SIGNALS,
                        f"{relative} installs a trap but never arms "
                        f"{sorted(FATAL_TRAP_SIGNALS - armed)}; a signal it does "
                        f"not name kills the script with its handler unrun.",
                    )
                for number, line, action, signals in commands:
                    if action != "-":
                        continue
                    self.assertEqual(
                        armed, signals,
                        f"{relative}:{number}: `{line}` disarms {sorted(signals)} "
                        f"but the script arms {sorted(armed)}. A disarm that "
                        f"misses a signal leaves the handler live while cleanup "
                        f"runs; one that names an extra signal is a sign the two "
                        f"halves were edited apart.",
                    )

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
        # Take the message's subject set from the digest inputs themselves
        # rather than spot-checking a name or two. Any of these paths can be
        # the one that raised the notice, so an operator who is told the
        # deployment is stale needs the notice to name all of them; a path
        # silently dropped from the sentence leaves them guessing. Substring
        # matching suffices because the message writes the trees with a
        # trailing slash.
        for name in (*module.BAKED_SOURCE_FILES, *module.BAKED_SOURCE_TREES):
            with self.subTest(name=name):
                self.assertIn(
                    name,
                    module.STALE_DEPLOYMENT_MESSAGE,
                    f"{name} is digested into baked_sources_sha256, so changing it is "
                    "one of the things that raises this notice — but the notice never "
                    "names it, so the operator cannot tell what went stale",
                )
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
