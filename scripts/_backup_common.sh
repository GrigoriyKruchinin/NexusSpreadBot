# Shared helpers for backup scripts. Sourced, not executed. No secrets are handled here:
# pg tools run inside the postgres container over the local unix socket, so no password
# appears on any command line, in compose, or in logs.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.local.yml}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/nexus-backups}"
BACKUP_USER="${BACKUP_USER:-nexus_ro}"
SOURCE_DB="${SOURCE_DB:-nexus}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# Run a command inside the postgres container (stdin is forwarded).
pg_run() { docker compose -f "$COMPOSE_FILE" exec -T postgres "$@"; }

# Create the backup dir (0700) and refuse unsafe locations.
ensure_backup_dir() {
  local dir="$1" real
  mkdir -p "$dir"
  chmod 700 "$dir"
  real="$(cd "$dir" && pwd -P)"
  case "$real/" in
    "$REPO_ROOT"/*) die "backup dir must be outside the repository: $real" ;;
  esac
  [ "$(stat -c %a "$real")" = "700" ] || die "backup dir mode is not 0700: $real"
}

# Latest regular dump file in a dir (lexicographic == chronological by name).
latest_dump() {
  find "$1" -maxdepth 1 -type f -name 'nexus-*.dump' | sort | tail -n 1
}
