#!/usr/bin/env bash
# Restore drill: restore a dump into the scratch DB nexus_test ONLY, then compare per-table row counts
# with the counts recorded at dump time (<dump>.counts: rows just before / just after the dump).
# A restored count must lie between those two numbers (inclusive). The dump is a consistent snapshot
# taken between the two counts, so for tables that only grow or only shrink the snapshot count is in
# that range; static tables must match exactly. Live counts are NOT used (the scanner keeps writing).
# A table that is missing after restore, or has no recorded counts, is a FAILED verdict.
# Refuses any other target DB; the restore role is pinned to nexus_test_owner and must not be superuser.
# Prints counts only, never row data. The table is also saved to $BACKUP_DIR/restore-drill-last.txt.
# Usage: restore_drill.sh [dump-file]   (default: latest in $BACKUP_DIR)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_backup_common.sh"

TARGET_DB="${TARGET_DB-nexus_test}"
readonly TARGET_USER=nexus_test_owner   # pinned on purpose: no environment override
# Guard first, before anything touches Docker. Exact match only.
if [ "$TARGET_DB" != "nexus_test" ]; then
  die "refusing to restore into '$TARGET_DB': only 'nexus_test' is allowed"
fi
[ "$TARGET_DB" != "$SOURCE_DB" ] || die "target equals source DB"

ensure_backup_dir "$BACKUP_DIR"
BACKUP_DIR="$REAL_BACKUP_DIR"
dump="${1:-}"
[ -n "$dump" ] || dump="$(latest_dump "$BACKUP_DIR")"
[ -n "$dump" ] && [ -f "$dump" ] || die "no dump file found"
counts_file="${dump%.dump}.counts"
[ -f "$counts_file" ] || die "drill FAILED: no counts sidecar ($(basename "$counts_file")); run 'make backup' and drill that dump"

# Defence in depth: the restore role must not be a superuser.
is_super="$(pg_run psql -U "$TARGET_USER" -d "$TARGET_DB" -At -c "select rolsuper from pg_roles where rolname=current_user" | tr -d '\r')"
[ "$is_super" = "f" ] || die "role $TARGET_USER is not a verified non-superuser (got '$is_super'); aborting"

log "restoring $(basename "$dump") into $TARGET_DB as $TARGET_USER"
# --clean --if-exists drops objects inside nexus_test only; --no-owner keeps the test owner.
pg_run pg_restore -U "$TARGET_USER" -d "$TARGET_DB" --no-password \
  --clean --if-exists --no-owner --no-privileges --exit-on-error < "$dump"

declare -A restored=()
while IFS='|' read -r t n; do
  [ -z "$t" ] || restored[$t]="$n"
done < <(table_counts "$TARGET_USER" "$TARGET_DB")

report="$BACKUP_DIR/restore-drill-last.txt"
status=0
{
  printf '%-40s %10s %10s %10s %s\n' table restored before after verdict
  while IFS='|' read -r t lo hi; do
    [ -n "$t" ] || continue
    dst="${restored[$t]:-}"
    if [ -z "$dst" ]; then
      v="MISSING"; status=1; dst="-"
    else
      a=$lo; b=$hi
      if [ "$a" -gt "$b" ]; then a=$hi; b=$lo; fi
      if [ "$dst" -ge "$a" ] && [ "$dst" -le "$b" ]; then v=ok; else v=MISMATCH; status=1; fi
    fi
    printf '%-40s %10s %10s %10s %s\n' "$t" "$dst" "$lo" "$hi" "$v"
  done < "$counts_file"
} | (umask 077; tee "$report") >&2 || true
# tee runs in a pipeline subshell: recompute status from the saved report.
grep -qE ' (MISSING|MISMATCH)$' "$report" && status=1
[ -s "$report" ] || status=1
[ "$status" -eq 0 ] && log "drill PASSED" || die "drill FAILED"
