#!/usr/bin/env bash
# Retention (all dates are UTC, taken from the file name nexus-YYYYMMDDTHHMMSSZ.dump):
#  * daily : the newest dump of each of the KEEP_DAILY (default 7) most recent calendar days that have
#            a dump (days without any dump do not use up the window, so a stopped machine loses nothing).
#  * weekly: among older dumps, the newest dump of each of the KEEP_WEEKLY (default 4) most recent ISO
#            weeks that the daily window does not already cover.
#  Other dumps are deleted, together with their .counts sidecar. Malformed names are never touched.
#  The newest dump is never deleted. KEEP_* must be integers 1..9999, otherwise nothing is deleted.
# Usage: backup_prune.sh <dir>
set -euo pipefail
dir="${1:?usage: backup_prune.sh <dir>}"
keep_daily="${KEEP_DAILY:-7}"
keep_weekly="${KEEP_WEEKLY:-4}"
for v in "$keep_daily" "$keep_weekly"; do
  [[ "$v" =~ ^[1-9][0-9]{0,3}$ ]] || { echo "ERROR: KEEP_DAILY/KEEP_WEEKLY must be integers 1..9999 (got '$v')" >&2; exit 2; }
done
[ -d "$dir" ] || { echo "not a directory: $dir" >&2; exit 1; }

dump_re='^nexus-[0-9]{8}T[0-9]{6}Z\.dump$'
mapfile -t files < <(find "$dir" -maxdepth 1 -type f -printf '%f\n' | grep -E "$dump_re" | sort -r || true)
declare -A day_seen=() week_seen=()
days=0
weeks=0
newest="${files[0]:-}"   # unconditional guard: never deleted, whatever the arithmetic says
remove() {
  [ "$1" != "$newest" ] || return 0
  rm -f -- "$dir/$1" "$dir/${1%.dump}.counts"
  echo "pruned $1" >&2
}
for base in "${files[@]}"; do
  day="${base#nexus-}"; day="${day:0:8}"
  if ! week="$(date -u -d "$day" +%G-W%V 2>/dev/null)"; then
    echo "WARNING: unparsable date in $base, kept" >&2
    continue
  fi
  if [ -n "${day_seen[$day]:-}" ]; then
    remove "$base"                      # older dump of an already kept day
  elif [ "$days" -lt "$keep_daily" ]; then
    day_seen[$day]=1; week_seen[$week]=1; days=$((days + 1))
  elif [ -z "${week_seen[$week]:-}" ] && [ "$weeks" -lt "$keep_weekly" ]; then
    week_seen[$week]=1; weeks=$((weeks + 1))
  else
    remove "$base"
  fi
done
# Orphan sidecars (dump already gone).
while IFS= read -r c; do
  [ -f "$dir/${c%.counts}.dump" ] || { rm -f -- "$dir/$c"; echo "pruned orphan $c" >&2; }
done < <(find "$dir" -maxdepth 1 -type f -printf '%f\n' | grep -E '^nexus-[0-9]{8}T[0-9]{6}Z\.counts$' || true)
