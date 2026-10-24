# Shared helpers for backup scripts. Sourced, not executed. No secrets are handled here:
# pg tools run inside the postgres container over the local unix socket, so no password
# appears on any command line, in compose, or in logs.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.local.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/nexus-backups}"
BACKUP_USER="${BACKUP_USER:-nexus_ro}"
SOURCE_DB="${SOURCE_DB:-nexus}"
# Exact file-name formats written by backup.sh (single source of truth for prune/latest_dump).
DUMP_RE='^nexus-[0-9]{8}T[0-9]{6}Z\.dump$'

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Run a command inside the postgres container (stdin is forwarded).
pg_run() { docker compose -f "$COMPOSE_FILE" exec -T postgres "$@"; }

# Absolute physical path of $1 even if it does not exist yet (symlinks of the existing prefix resolved).
resolve_path() {
  local p="$1" rest="" base
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  case "/$p/" in */../*) die "path must not contain '..': $1" ;; esac
  while [ ! -e "$p" ]; do
    base="$(basename "$p")"; rest="/$base$rest"; p="$(dirname "$p")"
  done
  [ -d "$p" ] || die "not a directory: $p"
  (cd "$p" && printf '%s%s' "$(pwd -P)" "$rest")
}

# Validate the backup dir location BEFORE any mkdir/chmod, then create it (0700).
# Sets REAL_BACKUP_DIR. Refuses: inside the repo, $HOME itself or any parent of it, a foreign owner,
# an existing dir whose mode is not 0700 (never chmods an existing dir).
ensure_backup_dir() {
  local real home_real
  real="$(resolve_path "$1")" || exit 1
  home_real="$(cd "$HOME" && pwd -P)"
  case "$real/" in
    "$REPO_ROOT"/*) die "backup dir must be outside the repository: $real" ;;
  esac
  case "$home_real/" in
    "$real"/*) die "backup dir must not be \$HOME or a parent of it: $real" ;;
  esac
  if [ -e "$real" ]; then
    [ "$(stat -c %u "$real")" = "$(id -u)" ] || die "backup dir is not owned by the current user: $real"
    [ "$(stat -c %a "$real")" = "700" ] || die "existing backup dir mode is not 0700 (fix it yourself): $real"
  else
    mkdir -m 700 -p -- "$real"
    [ "$(stat -c %a "$real")" = "700" ] || die "backup dir mode is not 0700: $real"
  fi
  REAL_BACKUP_DIR="$real"
}

# Latest regular dump file in a dir (exact backup.sh name format; lexicographic == chronological).
latest_dump() {
  local name
  name="$(find "$1" -maxdepth 1 -type f -printf '%f\n' | grep -E "$DUMP_RE" | sort | tail -n 1 || true)"
  [ -z "$name" ] || printf '%s/%s\n' "$1" "$name"
}

# "table|rowcount" for every public table of DB $2 as role $1 (one psql call, counts only).
table_counts() {
  local sql
  sql="select tablename, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', schemaname, tablename), false, true, '')))[1]::text from pg_tables where schemaname='public' order by 1"
  pg_run psql -U "$1" -d "$2" -At -c "$sql" | tr -d '\r'
}

# ---------------------------------------------------------------- off-machine copy + status (S0a)
# Copy location (D-02). Default is the Windows side of WSL, outside OneDrive. Empty value disables the copy.
BACKUP_COPY_DIR="${BACKUP_COPY_DIR-/mnt/c/nexus-backups}"
# World-readable status dir (file names only, no secrets): BACKUP_DIR is 0700 and the container user
# (uid 10001) could not traverse it, so the maintenance worker gets this directory read-only at /backups.
BACKUP_STATUS_DIR="${BACKUP_STATUS_DIR:-$HOME/nexus-backup-status}"

# Write the status JSON atomically (same-dir temp file + rename) to $1 with mode $2.
# Fields: finished_at (UTC ISO), ok, dump (file name or ""), copied. $3=ok(true/false) $4=dump name $5=copied.
write_status_file() {
  local target="$1" mode="$2" tmp
  tmp="$(mktemp -- "$(dirname "$target")/.last_backup.XXXXXX")" || return 1
  printf '{"finished_at": "%s", "ok": %s, "dump": "%s", "copied": %s}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" "$4" "$5" > "$tmp" || { rm -f -- "$tmp"; return 1; }
  chmod "$mode" "$tmp" && mv -f -- "$tmp" "$target" || { rm -f -- "$tmp"; return 1; }
}

# Never fails the caller: a status problem is only logged.
write_status() {
  write_status_file "$BACKUP_DIR/last_backup.json" 600 "$1" "$2" "$3" || log "WARNING: could not write status file"
  if [ ! -d "$BACKUP_STATUS_DIR" ]; then
    mkdir -m 755 -p -- "$BACKUP_STATUS_DIR" 2>/dev/null || { log "WARNING: cannot create status dir"; return 0; }
  fi
  write_status_file "$BACKUP_STATUS_DIR/last_backup.json" 644 "$1" "$2" "$3" || log "WARNING: could not write public status file"
  return 0
}

# Copy dump $1 and its .counts sidecar to BACKUP_COPY_DIR, verify sha256, prune with the same retention.
# Returns 0 only if both files were copied and verified. Never dies: callers treat failure as a WARNING.
copy_offsite() {
  local dump="$1" counts="${1%.dump}.counts" dest parent real_src real_dst f name tmp
  dest="$BACKUP_COPY_DIR"
  if [ -z "$dest" ]; then log "WARNING: BACKUP_COPY_DIR is empty; off-machine copy disabled"; return 1; fi
  case "$dest" in /*) ;; *) log "WARNING: BACKUP_COPY_DIR must be an absolute path; copy skipped"; return 1 ;; esac
  case "/$dest/" in */../*) log "WARNING: BACKUP_COPY_DIR must not contain '..'; copy skipped"; return 1 ;; esac
  if [ ! -d "$dest" ]; then
    parent="$(dirname "$dest")"
    if [ ! -d "$parent" ]; then
      log "WARNING: $parent does not exist (drive not mounted?); off-machine copy skipped"; return 1
    fi
    case "$parent" in /mnt/?) mountpoint -q -- "$parent" || {
      log "WARNING: $parent is not mounted; off-machine copy skipped"; return 1; } ;; esac
    mkdir -p -- "$dest" 2>/dev/null || { log "WARNING: cannot create copy dir; copy skipped"; return 1; }
  fi
  real_dst="$(cd "$dest" && pwd -P)" || return 1
  real_src="$(cd "$(dirname "$dump")" && pwd -P)" || return 1
  if [ "$real_dst" = "$real_src" ]; then log "WARNING: BACKUP_COPY_DIR equals BACKUP_DIR; copy skipped"; return 1; fi
  case "$real_dst/" in "$REPO_ROOT"/*) log "WARNING: BACKUP_COPY_DIR is inside the repository; copy skipped"; return 1 ;; esac
  for f in "$dump" "$counts"; do
    name="$(basename "$f")"
    tmp="$real_dst/.$name.partial"
    if ! cp -- "$f" "$tmp" 2>/dev/null; then rm -f -- "$tmp"; log "WARNING: copy of $name failed"; return 1; fi
    if [ "$(sha256sum < "$f")" != "$(sha256sum < "$tmp")" ]; then
      rm -f -- "$tmp"; log "WARNING: checksum mismatch after copying $name"; return 1
    fi
    chmod 600 -- "$tmp" 2>/dev/null || true   # best effort: NTFS mounts ignore modes
    mv -f -- "$tmp" "$real_dst/$name" || { rm -f -- "$tmp"; log "WARNING: cannot finalize copy of $name"; return 1; }
  done
  log "copied $(basename "$dump") and sidecar to the off-machine dir (checksums verified)"
  "$(dirname "${BASH_SOURCE[0]}")/backup_prune.sh" "$real_dst" || log "WARNING: pruning the copy dir failed"
  return 0
}
