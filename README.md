# Nexus Spread Scanner

A self-hosted tool that watches crypto spot prices on several centralized exchanges, estimates the
**net** spread after fees, order-book slippage and transfer cost, and sends the opportunities to
**your own Telegram channel**. Every evaluation is stored in your own PostgreSQL database.

It is read-only: it never trades, never withdraws and never transfers funds.

Russian guide (step by step, with Telegram and exchange screenshots in words): [docs/guides/quickstart.md](docs/guides/quickstart.md).

## Example alert (numbers invented)

```text
🟢 ABC/USDT   +0.80 % net
Buy  Binance  100
Sell KuCoin  101
Net after fees/slippage: +0.80 % (≈ +$7.98 on $1,000)
Volume: up to $3,050 (≈ 30.5 ABC) by orderbooks
Transfer: BEP20 · fee 0.8 ABC (≈ $0.08) · ≈ 5 min (approx)
Withdraw Binance: ✅ open   Deposit KuCoin: ✅ open
Lifetime: just opened   ·   #7
```

Alerts are edited in place while a spread lives and get a "closed" summary when it ends. Alerts for
routes whose transfer is closed or unverified are marked as such.

## Requirements

- Docker with Compose v2 (Docker Desktop on Windows/macOS, Docker Engine on Linux)
- GNU make and a Unix-like shell (on Windows: WSL2)
- A Telegram account and a bot token from @BotFather
- Optional: read-only API keys from the exchanges

## Quickstart

```bash
cp .env.example .env && chmod 600 .env   # 1. create your settings file
# 2. edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, POSTGRES_PASSWORD (openssl rand -base64 32)
make up                                  # 3. check .env, build, migrate, start (scripts/start.sh)
make ps                                  # 4. all services should be healthy
make logs s=scanner                      # 5. watch the scanner; alerts appear in your Telegram
```

Step-by-step guide with the Telegram setup (bot, channel, channel id): [docs/guides/quickstart.md](docs/guides/quickstart.md).

Without any exchange key the tool runs in **public mode**: prices and order books work, but transfer
fees and deposit/withdrawal status are not read, so alerts are less precise.

## Configuration

Secrets go into `.env` only. Everything else lives in the committed file `config/nexus.toml`. Do not
copy setting lines into `.env`: an environment variable overrides the file. After editing
`config/nexus.toml`, run `make up` again (the settings are part of the image).

Owner overlay: a file `config/local.toml` (git-ignored, your private values over the committed defaults)
is planned. TODO(docs): describe it here once backend-lead's change has landed. The fixed text for the
channel's pinned message can be shown with a command; TODO(docs): add the exact command once it has
landed.

| Setting | Default | Meaning |
|---|---|---|
| `[alert] language` | `en` | Alert language: `en` or `ru` |
| `[alert] update_min_change_pct` | `25` | Edit an open alert only if the net profit changed by at least this % |
| `[alert] update_min_interval_s` | `60` | ...and at least this many seconds passed since the last edit |
| `[alert] max_per_hour` | `30` | Cap of new alert messages per hour; the rest become one "N more suppressed" message |
| `[spread] min_net_profit_pct` | `0.3` | Minimum net spread (%) to alert |
| `[spread] min_net_profit_usd` | `5` | Minimum net profit (USD) to alert |
| `[exchanges] enabled` | 5 venues | Venues to scan (binance, bybit, gateio, kucoin, okx) |
| `[watchdog] backup_check_enabled` | `false` | Alert when backups are stale; needs the backup mount, see the guide |

Keys in `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `POSTGRES_PASSWORD`, optional
`<VENUE>_API_KEY` / `_API_SECRET` / `_API_PASSPHRASE`, and `KEY_POLICY_STRICT` (see below).

## Read-only API keys (optional)

- Keys are optional. Each venue can run with or without a key.
- Create keys with **read permission only**. Withdrawals and trading must be disabled.
- Nexus checks the key at startup. A key that can withdraw or trade, or that the venue rejects, is
  **not used**: that venue runs in public mode and you get a warning in the startup check.
- `KEY_POLICY_STRICT=true` (optional) makes a rejected key stop the start, requires an IP whitelist,
  and refuses venues whose API cannot show the key's permissions.
- **Residual risk (KuCoin, Gate.io):** KuCoin: Nexus checks the key's permissions but cannot see its IP
  whitelist. Gate.io: Nexus cannot see the key's permissions; a Gate.io key with trade or withdraw
  rights would still be used for reading in default mode (Nexus never sends orders or withdrawals,
  but a leaked key would be dangerous). Check it by hand in the exchange settings, or use
  `KEY_POLICY_STRICT=true` to refuse it.

**Your keys stay with you.** API keys are optional and read-only. They are read from your local `.env`
file, used only to sign requests sent directly to the exchange's own API, and are never logged, stored
in the database, sent to Telegram or to the authors. Nexus has no telemetry. Create keys **without
trading and without withdrawal permission**; enable IP restriction where the exchange offers it. Alert
texts (prices, spreads) do go to Telegram, which you choose.

## Disclaimer

**Disclaimer.** Nexus is free software provided "as is", without warranty of any kind (see
[LICENSE](LICENSE)). It is an informational tool, **not financial, investment, legal or tax advice**,
and not a recommendation to buy or sell any asset. Spreads shown are estimates from public order
books and fee data; they can be wrong, stale or gone by the time you act. Transfers between exchanges
take time, can be delayed or frozen, and prices move meanwhile. You alone are responsible for your
decisions, for complying with each exchange's terms of service and with the laws of your country.
Nexus is **not affiliated with, endorsed by or sponsored by** Binance, Bybit, Gate.io, KuCoin, OKX or
Telegram; their names are used only to identify the services the tool connects to.

## Exchange data terms

**Exchange data terms.** Market data belongs to the exchanges. Their API terms allow personal use;
most of them forbid publishing, redistributing or monetising the data without a written licence
(e.g. OKX API Agreement s. 9.4 covers public endpoints too). Run Nexus for yourself and post to a
**private** channel. Do not make a public or paid channel out of it unless you hold the needed data
licences. Respect rate limits; do not use Nexus from a country an exchange does not serve. The
Nexus license covers the code only, not exchange data.

## Day-to-day commands

| Command | What it does |
|---|---|
| `make up` | Check `.env`, build, migrate, start (run again after any change) |
| `make ps` | Show service status |
| `make logs s=scanner` | Follow logs of one service (`worker-alerts`, `beat`, `postgres`, ...) |
| `make doctor` | Full check: settings, database, migrations (stack must be running) |
| `make doctor ARGS=--send-test` | Same, and send a test message to your chat |
| `make down` | Stop the stack; data is kept |
| `make reset-data` | **Deletes** the database and Redis data (asks you to type DELETE) |

## Troubleshooting

| Symptom | What to do |
|---|---|
| `make up` says `.env` is missing or a value is empty | Create `.env` from `.env.example` and fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` |
| "Telegram rejected the bot token (401)" | Get a new token from @BotFather (`/token`) |
| "Chat not found" | Send `/start` to your bot (private chat) or add the bot to the channel as administrator |
| "not an administrator" / "lacks rights" | Channel settings → Administrators → add the bot with "Post messages" and "Edit messages of others" |
| "Could not reach Telegram" | Check the internet; if Telegram is blocked where you live, use a VPN |
| "key rejected" / "KEY_POLICY" warning | Check the key, secret and passphrase; recreate it read-only if needed. The venue runs in public mode meanwhile |
| "database is not reachable" / "not migrated" | Run `make up`; if the password changed, it must match the one the database was created with |
| `make up` says "port is already allocated" (only if you enabled the optional database port) | Another PostgreSQL (or an old `nexus-local` stack: `docker compose -p nexus-local down`, keeps its data) holds 5432. Stop it or set `POSTGRES_HOST_PORT=15432` |
| Scanner not healthy after `make up` | `make logs s=scanner`, then `make doctor` |

SQL access from the host is off by default. To enable it (loopback `127.0.0.1` only, never public):
`COMPOSE_FILE=docker-compose.yml:docker-compose.postgres-port.yml make up`, port 5432 or
`POSTGRES_HOST_PORT`.

Full guide with more cases: [docs/guides/quickstart.md](docs/guides/quickstart.md).

## Update, stop, reset

- **Update:** `git pull` then `make up`. Schema changes are applied automatically by migrations on every
  `make up`, your data is kept. Only a database created before 2026-10-25 (the S1-tool schema squash)
  cannot be upgraded: back it up if you need it, then reset it once with `make reset-data` (this
  deletes data).
- **Stop:** `make down` (data kept).
- **Reset:** `make reset-data` deletes everything; it is irreversible.

## Development

```bash
uv sync
make check              # lint + mypy --strict + unit tests
make test-integration   # only against the nexus_test database (CI runs it)
```

Architecture, decisions and project status: [docs/decisions/0010-self-hosted-alert-tool.md](docs/decisions/0010-self-hosted-alert-tool.md),
[docs/pipeline/STATE.md](docs/pipeline/STATE.md), [CLAUDE.md](CLAUDE.md), [docs/conventions.md](docs/conventions.md).
Adding an exchange: a `CcxtExchangeAdapter` subclass in `src/nexus/adapters/cex/`.

## License

Apache License 2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). The license covers the code only.
Exchange data is governed by each exchange's terms (see above).
