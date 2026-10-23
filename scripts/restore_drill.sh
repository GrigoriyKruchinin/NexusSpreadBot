#!/usr/bin/env bash
# Restore drill: restore the latest dump into the scratch DB nexus_test ONLY, then compare row
# counts with the live DB. Refuses any other target. Prints counts only, never row data.
# Usage: restore_drill.sh [dump-file]   (default: latest in $BACKUP_DIR)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_backup_common.sh"

TARGET_DB="${TARGET_DB-nexus_test}"
TARGET_USER="${TARGET_USER:-nexus_test_owner}"
# Guard first, before anything touches Docker. Exact match only.
if [ "$TARGET_DB" != "nexus_test" ]; then
  die "refusing to restore into '$TARGET_DB': only 'nexus_test' is allowed"
fi
[ "$TARGET_DB" != "$SOURCE_DB" ] || die "target equals source DB"

dump="${1:-}"
[ -n "$dump" ] || dump="$(latest_dump "$BACKUP_DIR")"
[ -n "$dump" ] && [ -f "$dump" ] || die "no dump file found"
log "restoring $(basename "$dump") into $TARGET_DB as $TARGET_USER"

# --clean --if-exists drops objects inside nexus_test only; --no-owner keeps the test owner.
pg_run pg_restore -U "$TARGET_USER" -d "$TARGET_DB" --no-password \
  --clean --if-exists --no-owner --no-privileges --exit-on-error < "$dump"

tables_sql="select quote_ident(tablename) from pg_tables where schemaname='public' order by 1"
mapfile -t tables < <(pg_run psql -U "$BACKUP_USER" -d "$SOURCE_DB" -At -c "$tables_sql" | tr -d '\r')
status=0
printf '%-40s %12s %12s %s\n' table restored source verdict
for t in "${tables[@]}"; do
  src="$(pg_run psql -U "$BACKUP_USER" -d "$SOURCE_DB" -At -c "select count(*) from public.$t" | tr -d '\r')"
  dst="$(pg_run psql -U "$TARGET_USER" -d "$TARGET_DB" -At -c "select count(*) from public.$t" | tr -d '\r')"
  # The live DB keeps receiving rows after the dump snapshot, so restored <= source is expected.
  if [ "$dst" -le "$src" ] && { [ "$src" -eq 0 ] || [ "$dst" -gt 0 ]; }; then v=ok; else v=MISMATCH; status=1; fi
  printf '%-40s %12s %12s %s\n' "$t" "$dst" "$src" "$v"
done
[ "$status" -eq 0 ] && log "drill PASSED" || die "drill FAILED"
