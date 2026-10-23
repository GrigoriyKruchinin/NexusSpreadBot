#!/usr/bin/env bash
# Retention: keep the newest KEEP_DAILY dumps (default 7) plus the newest dump of each of the
# KEEP_WEEKLY (default 4) most recent ISO weeks among the older ones. Deletes the rest.
# Usage: backup_prune.sh <dir>     File names: nexus-YYYYMMDDTHHMMSSZ.dump
set -euo pipefail
dir="${1:?usage: backup_prune.sh <dir>}"
keep_daily="${KEEP_DAILY:-7}"
keep_weekly="${KEEP_WEEKLY:-4}"
[ -d "$dir" ] || { echo "not a directory: $dir" >&2; exit 1; }

mapfile -t files < <(find "$dir" -maxdepth 1 -type f -name 'nexus-????????T??????Z.dump' | sort -r)
declare -A week_seen=()
weeks=0
i=0
for f in "${files[@]}"; do
  i=$((i + 1))
  if [ "$i" -le "$keep_daily" ]; then
    continue
  fi
  base="$(basename "$f")"
  day="${base#nexus-}"; day="${day:0:8}"
  week="$(date -u -d "$day" +%G-W%V)"
  if [ -z "${week_seen[$week]:-}" ] && [ "$weeks" -lt "$keep_weekly" ]; then
    week_seen[$week]=1
    weeks=$((weeks + 1))
    continue
  fi
  rm -f -- "$f"
  echo "pruned $base" >&2
done
