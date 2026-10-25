#!/usr/bin/env bash
# Host-side dead-man + auto-recovery for the local soak stack (D-01b). Runs from user cron every 5 minutes.
#
# It lives OUTSIDE the stack: it keeps working when every app container (and the in-stack watchdog and
# Telegram worker) is down. What it does, in order:
#   1. Docker unreachable      -> alert (nothing can be recovered from here).
#   2. Expected service not running (exited/created/dead) -> `docker compose start <service>` (never
#      up/recreate/build, never down), then re-check after a short settle time.
#   3. A service unhealthy (the scanner healthcheck IS the sweep heartbeat: stale heartbeat -> unhealthy)
#      -> alert. No restart here: restarting a hung container is a human decision.
#   4. Alerts go straight to Telegram (token read at runtime from .env, never printed, never in argv).
#      First alert after WATCHDOG_FAIL_THRESHOLD consecutive bad runs, repeated every WATCHDOG_REPEAT_S,
#      one "recovered" message when it is healthy again.
#   5. When all is well, an optional external heartbeat is pinged (HEARTBEAT_URL_FILE, same rules as
#      backup.sh: owned by you, mode 0600, https only, fed to curl through stdin). A missing ping is what
#      alerts you when the whole PC is off, which no host script can detect.
# Pause (e.g. during a deploy): `touch ~/.nexus-watchdog-pause`; remove the file to resume.
# A pause file older than WATCHDOG_PAUSE_REMIND_S (12 h) triggers a Telegram reminder (once per that period).
# Read-only for data: no DB access, no `exec`, no `config`/`inspect`, no .env output.
# NEVER run this script with `bash -x` / `set -x`: the trace would print the Telegram token.
set -uo pipefail
set +x

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/docker-compose.yml}"
ENV_FILE="${WATCHDOG_ENV_FILE:-$REPO_ROOT/.env}"
STATE_DIR="${WATCHDOG_STATE_DIR:-$HOME/.local/state/nexus-host-watchdog}"
PAUSE_FILE="${WATCHDOG_PAUSE_FILE:-$HOME/.nexus-watchdog-pause}"
FAIL_THRESHOLD="${WATCHDOG_FAIL_THRESHOLD:-2}"
REPEAT_S="${WATCHDOG_REPEAT_S:-3600}"
SETTLE_S="${WATCHDOG_SETTLE_S:-45}"
START_TIMEOUT_S="${WATCHDOG_START_TIMEOUT_S:-240}"  # `start` honours depends_on health gates: a full stack takes 60-90 s
PAUSE_REMIND_S="${WATCHDOG_PAUSE_REMIND_S:-43200}"
LOG_FILE="${WATCHDOG_LOG_FILE:-$STATE_DIR/watchdog.log}"
LOG_MAX_BYTES="${WATCHDOG_LOG_MAX_BYTES:-1048576}"
EXPECTED=(postgres redis worker-alerts worker-maintenance beat scanner)

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2; }

mkdir -p -m 700 "$STATE_DIR" || { log "ERROR: cannot create state dir"; exit 1; }
chmod 700 "$STATE_DIR" 2>/dev/null || true  # also when it already existed with a looser mode
# The log (cron redirects stderr there) holds only status lines, still keep it private and bounded:
# one generation is kept as .1; cron's `>>` re-creates the file on the next run.
if [ -f "$LOG_FILE" ]; then
  if [ "$(stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$LOG_MAX_BYTES" ]; then
    mv -f "$LOG_FILE" "$LOG_FILE.1" 2>/dev/null || : > "$LOG_FILE"
  fi
  chmod 600 "$LOG_FILE" 2>/dev/null || true
fi
[ -f "$LOG_FILE.1" ] && chmod 600 "$LOG_FILE.1" 2>/dev/null
exec 9>"$STATE_DIR/lock"
flock -n 9 || { log "another run is active; skipped"; exit 0; }

dc() { timeout 60 docker compose -f "$COMPOSE_FILE" "$@"; }
dc_start() { timeout "$START_TIMEOUT_S" docker compose -f "$COMPOSE_FILE" start "$@"; }

# Value of KEY from the env file without sourcing it; prints nothing if absent. Never logs the value.
read_env() {
  local line v
  line="$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" 2>/dev/null | tail -n1)" || return 1
  v="${line#*=}"; v="${v%$'\r'}"
  v="${v#\"}"; v="${v%\"}"; v="${v#\'}"; v="${v%\'}"
  printf '%s' "$v"
}

# Send $1 to Telegram. Returns 0 only on HTTP 200. The URL (it carries the token) goes through curl's stdin
# config, so it never appears in argv/ps; curl's own stderr is discarded.
send_telegram() {
  local token chat code
  token="$(read_env TELEGRAM_BOT_TOKEN)" || token=""
  chat="$(read_env TELEGRAM_CHAT_ID)" || chat=""
  if ! [[ "$token" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]] || ! [[ "$chat" =~ ^(-?[0-9]+|@[A-Za-z0-9_]+)$ ]]; then
    log "WARNING: Telegram token/chat id missing or malformed in the env file; message NOT sent (values not shown)"
    return 1
  fi
  code="$(printf 'url = "https://api.telegram.org/bot%s/sendMessage"\n' "$token" |
    curl -q -sS --max-time 15 --retry 2 -o /dev/null -w '%{http_code}' --config - \
      --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" 2>/dev/null)" || code="000"
  if [ "$code" = "200" ]; then log "telegram message sent"; return 0; fi
  log "WARNING: telegram send failed (http $code)"
  return 1
}

# Optional external heartbeat (healthchecks.io style). The URL is a secret: stdin config only, never logged.
ping_heartbeat() {
  local url="" f="${HEARTBEAT_URL_FILE:-}"
  local url_re="^https://[A-Za-z0-9._~:/?#@!\$&'()*+,;=%-]+\$"
  [ -n "$f" ] || return 0
  if [ ! -f "$f" ] || [ ! -r "$f" ]; then
    log "WARNING: HEARTBEAT_URL_FILE is not a readable file; heartbeat skipped"; return 0
  fi
  if [ "$(stat -c %u "$f")" != "$(id -u)" ] || [ "$(stat -c %a "$f")" != "600" ]; then
    log "WARNING: heartbeat file must be owned by you with mode 0600; heartbeat skipped"; return 0
  fi
  url="$(tr -d '[:space:]' < "$f")"
  if ! [[ "$url" =~ $url_re ]]; then
    log "WARNING: heartbeat URL is not a plain https URL; skipped (value not shown)"; return 0
  fi
  if printf 'url = "%s"\n' "$url" | curl -q -fsS --max-time 10 --retry 2 -o /dev/null --config - 2>/dev/null; then
    log "external heartbeat sent"
  else
    log "WARNING: external heartbeat failed (details suppressed: URL is a secret)"
  fi
}

# Pause handling (after the helpers: it may send a reminder). A forgotten pause silently disables recovery.
if [ -e "$PAUSE_FILE" ]; then
  log "paused ($PAUSE_FILE exists); nothing done"
  pause_mtime="$(stat -c %Y "$PAUSE_FILE" 2>/dev/null || date +%s)"
  now_p="$(date +%s)"
  last_remind=0
  [ -f "$STATE_DIR/pause_reminded" ] && read -r last_remind < "$STATE_DIR/pause_reminded"
  [[ "$last_remind" =~ ^[0-9]+$ ]] || last_remind=0
  if [ $((now_p - pause_mtime)) -ge "$PAUSE_REMIND_S" ] && [ $((now_p - last_remind)) -ge "$PAUSE_REMIND_S" ]; then
    if send_telegram "host-watchdog is PAUSED for more than $((PAUSE_REMIND_S / 3600)) h (auto-recovery and alerts are off). Remove $PAUSE_FILE to resume."; then
      printf '%s\n' "$now_p" > "$STATE_DIR/pause_reminded"
    fi
  fi
  exit 0
fi
rm -f "$STATE_DIR/pause_reminded"

# Fills global PROBLEMS (array of short strings) and STOPPED (services that can be `start`ed).
evaluate() {
  PROBLEMS=(); STOPPED=()
  local out svc state health seen=" "
  if ! timeout 20 docker info >/dev/null 2>&1; then
    PROBLEMS+=("docker daemon unreachable")
    return
  fi
  if ! out="$(dc ps -a --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null)"; then
    PROBLEMS+=("docker compose ps failed")
    return
  fi
  while read -r svc state health; do
    [ -n "$svc" ] || continue
    seen+="$svc "
    case " ${EXPECTED[*]} " in *" $svc "*) ;; *) continue ;; esac
    if [ "$state" != "running" ]; then
      PROBLEMS+=("$svc: $state")
      case "$state" in exited | created | dead) STOPPED+=("$svc") ;; esac
    elif [ "$health" = "unhealthy" ]; then
      PROBLEMS+=("$svc: unhealthy")
    fi
  done <<< "$out"
  for svc in "${EXPECTED[@]}"; do
    case "$seen" in *" $svc "*) ;; *) PROBLEMS+=("$svc: missing (container does not exist)") ;; esac
  done
}

recovery_sent=0
evaluate
if [ "${#STOPPED[@]}" -gt 0 ]; then
  log "recovery: docker compose start ${STOPPED[*]} (no recreate)"
  dc_start "${STOPPED[@]}" >/dev/null 2>&1 || log "WARNING: docker compose start returned an error"
  sleep "$SETTLE_S"
  PREV_PROBLEMS=("${PROBLEMS[@]}")
  evaluate
  if [ "${#PROBLEMS[@]}" -eq 0 ]; then
    log "recovery succeeded after: ${PREV_PROBLEMS[*]}"
    send_telegram "host-watchdog: stack was down (${PREV_PROBLEMS[*]}), restarted with 'docker compose start', now healthy. Check for a soak data gap." && recovery_sent=1
  fi
fi

fails=0; alerted=0; last_alert=0
[ -f "$STATE_DIR/state" ] && read -r fails alerted last_alert < "$STATE_DIR/state"
[[ "$fails" =~ ^[0-9]+$ ]] || fails=0
[[ "$alerted" =~ ^[01]$ ]] || alerted=0
[[ "$last_alert" =~ ^[0-9]+$ ]] || last_alert=0
now="$(date +%s)"

if [ "${#PROBLEMS[@]}" -eq 0 ]; then
  log "ok"
  if [ "$alerted" = "1" ] && [ "$recovery_sent" = "0" ]; then  # one message: "restarted ... healthy" already says it
    send_telegram "host-watchdog: stack is healthy again." || true
  fi
  fails=0; alerted=0
  ping_heartbeat
else
  fails=$((fails + 1))
  log "problem (run $fails): ${PROBLEMS[*]}"
  if [ "$fails" -ge "$FAIL_THRESHOLD" ] && { [ "$alerted" = "0" ] || [ $((now - last_alert)) -ge "$REPEAT_S" ]; }; then
    if send_telegram "host-watchdog ALERT: ${PROBLEMS[*]} (bad for $fails consecutive checks)."; then
      alerted=1; last_alert="$now"
    fi
  fi
fi
printf '%s %s %s\n' "$fails" "$alerted" "$last_alert" > "$STATE_DIR/state"
exit 0
