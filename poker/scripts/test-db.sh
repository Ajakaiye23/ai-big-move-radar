#!/usr/bin/env bash
# Runs the migration and the schema smoke test against a throwaway local database.
#
#   npm run test:db
#
# Needs a Postgres you can reach with psql. Override with PGHOST/PGUSER/etc, or
# set PSQL_SUPERUSER to the command that gets you a superuser shell.
set -euo pipefail

cd "$(dirname "$0")/.."

DB_NAME="${DB_NAME:-chip_ledger_test}"
PSQL_SUPERUSER="${PSQL_SUPERUSER:-psql}"

run() { $PSQL_SUPERUSER -v ON_ERROR_STOP=1 -q "$@"; }

echo "→ recreating database $DB_NAME"
run -d postgres -c "drop database if exists $DB_NAME" >/dev/null
run -d postgres -c "create database $DB_NAME" >/dev/null

echo "→ installing Supabase stubs"
run -d "$DB_NAME" -f supabase/test/stubs.sql >/dev/null

echo "→ applying migrations"
for file in supabase/migrations/*.sql; do
  echo "   $file"
  run -d "$DB_NAME" -f "$file" >/dev/null
done

echo "→ running smoke test"
run -d "$DB_NAME" -f supabase/test/smoke.sql

echo "→ dropping $DB_NAME"
run -d postgres -c "drop database if exists $DB_NAME" >/dev/null
