#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu

export LC_ALL=C

owner_password_file="/run/secrets/postgres_owner_password"
runtime_password_file="/run/secrets/openclaw_db_password"

read_password() {
  label="$1"
  path="$2"
  if [ ! -f "$path" ]; then
    echo "$label password secret is required" >&2
    exit 1
  fi
  value="$(cat "$path")"
  byte_count="$(wc -c < "$path" | tr -d '[:space:]')"
  if [ "${#value}" -ne "$byte_count" ] || [ "$byte_count" -lt 24 ] || [ "$byte_count" -gt 128 ]; then
    echo "$label password must be one 24-128 byte line without a trailing newline" >&2
    exit 1
  fi
  case "$value" in
    *[!A-Za-z0-9_-]*)
      echo "$label password must use only base64url-safe characters" >&2
      exit 1
      ;;
  esac
  REPLY="$value"
}

read_password "owner" "$owner_password_file"
owner_password="$REPLY"
read_password "runtime" "$runtime_password_file"
runtime_password="$REPLY"
unset REPLY

if [ "$owner_password" = "$runtime_password" ]; then
  echo "owner and runtime passwords must differ" >&2
  exit 1
fi

# Reconcile attributes and remove every inherited or SET ROLE path before
# changing credentials. ON_ERROR_STOP prevents a later verification query from
# masking an earlier failure.
psql -X -w --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'openclaw_runtime') THEN
    CREATE ROLE openclaw_runtime;
  END IF;
END
$do$;

ALTER ROLE openclaw_runtime WITH
  NOLOGIN
  NOSUPERUSER
  NOCREATEDB
  NOCREATEROLE
  NOINHERIT
  NOREPLICATION
  NOBYPASSRLS
  CONNECTION LIMIT 32
  VALID UNTIL 'infinity';

-- Block reconnects with the old credential, then evict every existing runtime
-- session. The role is re-enabled only after the new password is installed.
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE usename IN ('openclaw_runtime', 'openclaw_owner')
  AND pid <> pg_backend_pid();

ALTER ROLE openclaw_runtime RESET ALL;
ALTER ROLE openclaw_runtime IN DATABASE openclaw RESET ALL;

-- Bounded execution for every runtime-role session (re-applied after the
-- RESET above so a reconcile can never silently drop them). The fixed
-- workflows execute short parameterized statements; anything long-running
-- indicates a runaway or a lock pile-up and must fail rather than wedge the
-- deterministic lane. Idle-in-transaction is capped so an abandoned helper
-- cannot hold locks open indefinitely.
ALTER ROLE openclaw_runtime SET statement_timeout = '30s';
ALTER ROLE openclaw_runtime SET lock_timeout = '10s';
ALTER ROLE openclaw_runtime SET idle_in_transaction_session_timeout = '120s';

DO $do$
DECLARE
  granted_role name;
  member_role_name name;
BEGIN
  FOR granted_role IN
    SELECT parent.rolname
    FROM pg_auth_members AS membership
    JOIN pg_roles AS parent ON parent.oid = membership.roleid
    JOIN pg_roles AS member_role ON member_role.oid = membership.member
    WHERE member_role.rolname = 'openclaw_runtime'
  LOOP
    EXECUTE format('REVOKE %I FROM openclaw_runtime CASCADE', granted_role);
  END LOOP;
  FOR member_role_name IN
    SELECT member_role.rolname
    FROM pg_auth_members AS membership
    JOIN pg_roles AS parent ON parent.oid = membership.roleid
    JOIN pg_roles AS member_role ON member_role.oid = membership.member
    WHERE parent.rolname = 'openclaw_runtime'
  LOOP
    EXECUTE format('REVOKE openclaw_runtime FROM %I CASCADE', member_role_name);
  END LOOP;
END
$do$;
SQL

# PostgreSQL documents \password as the non-cleartext password-change path.
# With no TTY, psql reads the two prompt responses from this private pipe and
# sends only an encrypted verifier to the server.
printf '%s\n%s\n' "$runtime_password" "$runtime_password" \
  | psql -X -n -w --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      --command '\password openclaw_runtime'
printf '%s\n%s\n' "$owner_password" "$owner_password" \
  | psql -X -n -w --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      --command '\password openclaw_owner'

psql -X -w --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --command "ALTER ROLE openclaw_runtime LOGIN; SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename IN ('openclaw_runtime', 'openclaw_owner') AND pid <> pg_backend_pid()"

# The official image's temporary initialization server is socket-only. The
# post-health reconciler opts into TCP proof; first initialization defers it.
if [ "${OPENCLAW_VERIFY_TCP_AUTH:-0}" = "1" ]; then
  # A data directory initialized before --auth-host=scram-sha-256 was pinned
  # still carries initdb's loopback trust rules, which would make the negative
  # proof below observe an acceptance. Rewrite any host trust rule to
  # scram-sha-256 in place (preserving the file's ownership) and reload.
  hba_path="${PGDATA:-/var/lib/postgresql/data/pgdata}/pg_hba.conf"
  if [ -f "$hba_path" ] \
    && grep -Eq '^[[:space:]]*host[a-z]*[[:space:]].*[[:space:]]trust[[:space:]]*$' "$hba_path"; then
    sed -E 's/^([[:space:]]*host[a-z]*[[:space:]].*[[:space:]])trust[[:space:]]*$/\1scram-sha-256/' \
      "$hba_path" > "$hba_path.openclaw-reconcile"
    cat "$hba_path.openclaw-reconcile" > "$hba_path"
    rm -f "$hba_path.openclaw-reconcile"
    psql -X -w --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
      --tuples-only --no-align --command "SELECT pg_reload_conf()" >/dev/null
  fi
  # Local-socket trust is intentionally not accepted as rotation evidence.
  # Passwords live briefly in mode-0600 files and never enter argv or exports.
  runtime_passfile="$(mktemp /dev/shm/openclaw-runtime-pgpass.XXXXXX)"
  owner_passfile="$(mktemp /dev/shm/openclaw-owner-pgpass.XXXXXX)"
  invalid_passfile="$(mktemp /dev/shm/openclaw-invalid-pgpass.XXXXXX)"
  cleanup() {
    rm -f "$runtime_passfile" "$owner_passfile" "$invalid_passfile"
  }
  # QUIT belongs here with the rest: a handler that does not name it is not run
  # under SIGQUIT (measured under Debian dash: exit 131, handler never entered),
  # which left all three mode-0600 files -- holding the openclaw_runtime and
  # openclaw_owner passwords in cleartext -- behind in the container's /dev/shm,
  # contradicting the "live briefly" bound two lines above. cleanup is `rm -f`,
  # so running it for both QUIT and the following EXIT is harmless.
  trap cleanup EXIT HUP INT QUIT TERM
  chmod 0600 "$runtime_passfile" "$owner_passfile" "$invalid_passfile"
  printf '127.0.0.1:5432:openclaw:openclaw_runtime:%s\n' "$runtime_password" > "$runtime_passfile"
  printf '127.0.0.1:5432:openclaw:openclaw_owner:%s\n' "$owner_password" > "$owner_passfile"
  invalid_password="OpenClawInvalidCredentialProbe_0000000000000000"
  if [ "$invalid_password" = "$runtime_password" ] || [ "$invalid_password" = "$owner_password" ]; then
    invalid_password="OpenClawInvalidCredentialProbe_1111111111111111"
  fi
  printf '127.0.0.1:5432:openclaw:openclaw_runtime:%s\n' "$invalid_password" > "$invalid_passfile"
  printf '127.0.0.1:5432:openclaw:openclaw_owner:%s\n' "$invalid_password" >> "$invalid_passfile"
  unset runtime_password owner_password

  runtime_authenticated="$(PGPASSFILE="$runtime_passfile" psql -X -w --host=127.0.0.1 \
    --username openclaw_runtime --dbname openclaw --tuples-only --no-align \
    --command "SELECT current_user = 'openclaw_runtime'")"
  owner_authenticated="$(PGPASSFILE="$owner_passfile" psql -X -w --host=127.0.0.1 \
    --username openclaw_owner --dbname openclaw --tuples-only --no-align \
    --command "SELECT current_user = 'openclaw_owner'")"

  if [ "$(printf '%s' "$runtime_authenticated" | tr -d '[:space:]')" != "t" ] \
    || [ "$(printf '%s' "$owner_authenticated" | tr -d '[:space:]')" != "t" ]; then
    echo "database credential authentication proof failed" >&2
    exit 1
  fi
  if PGPASSFILE="$invalid_passfile" psql -X -w --host=127.0.0.1 \
      --username openclaw_runtime --dbname openclaw --command "SELECT 1" >/dev/null 2>&1 \
    || PGPASSFILE="$invalid_passfile" psql -X -w --host=127.0.0.1 \
      --username openclaw_owner --dbname openclaw --command "SELECT 1" >/dev/null 2>&1; then
    echo "database host authentication accepted an invalid password" >&2
    exit 1
  fi
  unset invalid_password
else
  unset runtime_password owner_password
fi
