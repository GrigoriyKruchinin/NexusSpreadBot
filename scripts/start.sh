#!/usr/bin/env bash
# One-command start (T8): checks .env, builds, runs migrations (migrator service), starts the stack.
#   scripts/start.sh        (same as `make up`)
#
# Secrets: this script never prints values from .env, only variable NAMES. A missing POSTGRES_PASSWORD
# is generated and written into .env (mode kept 0600) without being echoed; do not run with `bash -x`.
# It never expands the environment of containers or the compose file.
set -euo pipefail
set +x

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ENV_FILE=".env"
PROJECT_VOLUME="nexus_postgres-data"
WAIT_S="${START_WAIT_S:-300}"

fail() { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "docker not found / docker не найден (install Docker Desktop or Docker Engine)"
docker info >/dev/null 2>&1 || fail "Docker daemon is not running / Docker не запущен"
docker compose version >/dev/null 2>&1 || fail "'docker compose' (v2) is required / нужен docker compose v2"

[ -f "$ENV_FILE" ] || fail ".env not found / файл .env не найден. Run: cp .env.example .env  and fill it in (see comments inside)"

# Presence checks by NAME only (the value is matched, never stored or printed).
is_empty() { grep -Eq "^[[:space:]]*$1[[:space:]]*=[[:space:]]*(\"\"|'')?[[:space:]]*(#.*)?\$" "$ENV_FILE"; }
is_set() { grep -Eq "^[[:space:]]*$1[[:space:]]*=" "$ENV_FILE"; }

missing=()
for name in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  if ! is_set "$name" || is_empty "$name"; then missing+=("$name"); fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  fail "fill in .env first / заполните .env: ${missing[*]}"
fi

if ! is_set POSTGRES_PASSWORD || is_empty POSTGRES_PASSWORD; then
  # Safe only while no database volume exists yet: an existing volume keeps its old password.
  if [ -n "$(docker volume ls -q --filter "name=^${PROJECT_VOLUME}\$")" ]; then
    fail "POSTGRES_PASSWORD is empty but a database volume already exists / пароль пустой, а база уже создана: set the password you used before"
  fi
  command -v openssl >/dev/null 2>&1 || fail "openssl not found: set POSTGRES_PASSWORD in .env manually (min 12 chars)"
  tmp="$(umask 077 && mktemp "${ENV_FILE}.XXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  NEW_PG_PASSWORD="$(openssl rand -base64 36 | tr -d '/+=\n' | cut -c1-32)" \
    awk 'BEGIN { done = 0 }
         /^[[:space:]]*POSTGRES_PASSWORD[[:space:]]*=/ { print "POSTGRES_PASSWORD=" ENVIRON["NEW_PG_PASSWORD"]; done = 1; next }
         { print }
         END { if (!done) print "POSTGRES_PASSWORD=" ENVIRON["NEW_PG_PASSWORD"] }' "$ENV_FILE" >"$tmp"
  chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
  trap - EXIT
  echo "POSTGRES_PASSWORD was empty: generated and saved to .env (value not shown) / пароль БД сгенерирован и записан в .env"
fi

# T7 hook: once `nexus check` exists, run it here (inside the built image) to fail fast on bad settings.

echo "Building and starting (first run takes a few minutes)... / сборка и запуск, первый раз несколько минут..."
docker compose up -d --build

echo "Waiting for the scanner to become healthy (up to ${WAIT_S}s)... / ждём готовности сканера..."
deadline=$((SECONDS + WAIT_S))
while [ "$SECONDS" -lt "$deadline" ]; do
  migrator_exit="$(docker compose ps -a migrator --format '{{.State}} {{.ExitCode}}' 2>/dev/null || true)"
  case "$migrator_exit" in
    exited\ [1-9]*) docker compose logs --tail=40 migrator >&2 || true
                    fail "database migration failed (log above) / миграция БД не прошла" ;;
  esac
  health="$(docker compose ps scanner --format '{{.Health}}' 2>/dev/null || true)"
  if [ "$health" = "healthy" ]; then
    docker compose ps
    echo "OK: stack is up. Alerts go to your Telegram chat. Logs: make logs s=scanner / Stop: make down"
    exit 0
  fi
  sleep 5
done
docker compose ps || true
fail "not healthy after ${WAIT_S}s / не готово за ${WAIT_S}с. See: make logs s=scanner (the scanner may be parked after a key-policy refusal)"
