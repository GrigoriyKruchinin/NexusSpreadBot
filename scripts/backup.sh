#!/usr/bin/env bash
# Daily logical backup of the live DB (read-only: pg_dump as the SELECT-only role nexus_ro).
# Output: $BACKUP_DIR/nexus-<UTC timestamp>.dump (custom format, mode 0600), outside the repo.
# Optional heartbeat: HEARTBEAT_URL_FILE (path to a file holding the ping URL) or HEARTBEAT_URL.
# The URL is a secret: it is fed to curl through stdin config, never argv, and never logged.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_backup_common.sh"
umask 077

ensure_backup_dir "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="$BACKUP_DIR/nexus-$stamp.dump"
partial="$final.partial"
trap 'rm -f -- "$partial"' EXIT

log "dumping $SOURCE_DB as $BACKUP_USER"
pg_run pg_dump -U "$BACKUP_USER" -d "$SOURCE_DB" --format=custom --no-password > "$partial"
[ -s "$partial" ] || die "dump is empty"
# Cheap integrity check: the archive table of contents must be readable.
pg_run pg_restore --list < "$partial" > /dev/null || die "dump failed pg_restore --list"
chmod 600 "$partial"
mv -- "$partial" "$final"
[ "$(stat -c %a "$final")" = "600" ] || die "dump file mode is not 0600"
log "wrote $(basename "$final") ($(stat -c %s "$final") bytes)"

"$(dirname "${BASH_SOURCE[0]}")/backup_prune.sh" "$BACKUP_DIR"

# Heartbeat: only after a verified dump. A ping failure is logged but does not fail the backup;
# a missed ping is what raises the alert on the external (free-tier) service.
url=""
if [ -n "${HEARTBEAT_URL_FILE:-}" ] && [ -r "$HEARTBEAT_URL_FILE" ]; then
  url="$(tr -d '[:space:]' < "$HEARTBEAT_URL_FILE")"
elif [ -n "${HEARTBEAT_URL:-}" ]; then
  url="$HEARTBEAT_URL"
fi
if [ -n "$url" ]; then
  if printf 'url = "%s"\n' "$url" | curl -fsS --max-time 10 --retry 2 -o /dev/null --config - 2>/dev/null; then
    log "heartbeat sent"
  else
    log "WARNING: heartbeat ping failed (details suppressed: URL is a secret)"
  fi
else
  log "heartbeat not configured (skipped)"
fi
