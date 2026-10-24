#!/usr/bin/env bash
# Daily logical backup of the live DB (read-only: pg_dump as the SELECT-only role nexus_ro).
# Output (outside the repo, mode 0600):
#   $BACKUP_DIR/nexus-<UTC timestamp>.dump    custom-format dump
#   $BACKUP_DIR/last_backup.json              status {finished_at, ok, dump, copied}, atomic; a public copy
#                                             goes to $BACKUP_STATUS_DIR (default ~/nexus-backup-status)
#   $BACKUP_COPY_DIR                          copy of dump + .counts (default /mnt/c/nexus-backups; skipped
#                                             with a WARNING if not mounted; empty value disables)
#   $BACKUP_DIR/nexus-<UTC timestamp>.counts  "table|rows_before|rows_after" (row counts taken just
#                                             before and just after the dump; used by the restore drill)
# Optional heartbeat: HEARTBEAT_URL_FILE (file, owned by you, mode 0600, holding the ping URL) or
# HEARTBEAT_URL. The URL is a secret: fed to curl through stdin config, never argv, never logged.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_backup_common.sh"
umask 077

# BACKUP_ARCHIVE=1 (make backup-archive): a one-off archive dump (e.g. of the old DB before a fresh stack)
# written to $BACKUP_DIR/archive/nexus-archive-<stamp>.dump. The name does not match the daily format and
# the dir is a subdir, so backup_prune.sh never deletes it. No status file, no heartbeat; the off-machine
# copy is still made (also never pruned). Set SOURCE_DB to archive another database.
archive="${BACKUP_ARCHIVE:-0}"
ensure_backup_dir "$BACKUP_DIR"
BACKUP_DIR="$REAL_BACKUP_DIR"
prefix="nexus"
if [ "$archive" = "1" ]; then
  ensure_backup_dir "$BACKUP_DIR/archive"
  BACKUP_DIR="$REAL_BACKUP_DIR"
  prefix="nexus-archive"
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/$prefix-$stamp.dump"
partial="$final.partial"
counts_final="$BACKUP_DIR/$prefix-$stamp.counts"
counts_partial="$counts_final.partial"
dump_name=""
copied=false
on_exit() {
  local rc=$?
  rm -f -- "$partial" "$counts_partial"
  # Status for the liveness watchdog (S0b): written on success AND on failure; never changes the exit code.
  if [ "$archive" = "1" ]; then :
  elif [ "$rc" -eq 0 ]; then write_status true "$dump_name" "$copied"; else write_status false "$dump_name" false; fi
  exit "$rc"
}
trap on_exit EXIT

log "dumping $SOURCE_DB as $BACKUP_USER"
before="$(table_counts "$BACKUP_USER" "$SOURCE_DB")"
pg_run pg_dump -U "$BACKUP_USER" -d "$SOURCE_DB" --format=custom --no-password > "$partial"
after="$(table_counts "$BACKUP_USER" "$SOURCE_DB")"
[ -s "$partial" ] || die "dump is empty"
[ -n "$before" ] || die "no tables found in $SOURCE_DB"
# Cheap integrity check: the archive table of contents must be readable.
pg_run pg_restore --list < "$partial" > /dev/null || die "dump failed pg_restore --list"
# Sidecar: join before/after by table name.
export LC_ALL=C
join -t '|' <(printf '%s\n' "$before" | sort -t '|' -k1,1) <(printf '%s\n' "$after" | sort -t '|' -k1,1) > "$counts_partial"
chmod 600 "$partial" "$counts_partial"
mv -- "$partial" "$final"
mv -- "$counts_partial" "$counts_final"
[ "$(stat -c %a "$final")" = "600" ] || die "dump file mode is not 0600"
log "wrote $(basename "$final") ($(stat -c %s "$final") bytes)"

dump_name="$(basename "$final")"
if [ "$archive" = "1" ]; then
  copy_offsite "$final" || log "WARNING: off-machine copy of the archive NOT made"
  log "archive dump written (never pruned): $final"
  exit 0
fi
"$(dirname "${BASH_SOURCE[0]}")/backup_prune.sh" "$BACKUP_DIR"

# Off-machine copy (D-02): a problem here is a WARNING, never a failed backup; the status file records it.
if copy_offsite "$final"; then copied=true; else log "WARNING: off-machine copy NOT made (status copied=false)"; fi

# Heartbeat: only after a verified dump. Problems are logged (never the URL) but do not fail the backup;
# a missed ping is what raises the alert on the external service.
url=""
url_re="^https://[A-Za-z0-9._~:/?#@!\$&'()*+,;=%-]+\$"
if [ -n "${HEARTBEAT_URL_FILE:-}" ]; then
  if [ ! -f "$HEARTBEAT_URL_FILE" ] || [ ! -r "$HEARTBEAT_URL_FILE" ]; then
    log "WARNING: HEARTBEAT_URL_FILE is set but not a readable file; heartbeat skipped"
  elif [ "$(stat -c %u "$HEARTBEAT_URL_FILE")" != "$(id -u)" ] || [ "$(stat -c %a "$HEARTBEAT_URL_FILE")" != "600" ]; then
    log "WARNING: heartbeat file must be owned by you with mode 0600 (chmod 600); heartbeat skipped"
  else
    url="$(tr -d '[:space:]' < "$HEARTBEAT_URL_FILE")"
  fi
elif [ -n "${HEARTBEAT_URL:-}" ]; then
  url="$HEARTBEAT_URL"
fi
if [ -n "$url" ] && ! [[ "$url" =~ $url_re ]]; then
  log "WARNING: heartbeat URL is not a plain https URL; heartbeat skipped (value not shown)"
  url=""
fi
if [ -n "$url" ]; then
  if printf 'url = "%s"\n' "$url" | curl -q -fsS --max-time 10 --retry 2 -o /dev/null --config - 2>/dev/null; then
    log "heartbeat sent"
  else
    log "WARNING: heartbeat ping failed (details suppressed: URL is a secret)"
  fi
else
  log "heartbeat not configured or skipped"
fi
