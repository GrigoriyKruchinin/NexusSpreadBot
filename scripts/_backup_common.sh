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
