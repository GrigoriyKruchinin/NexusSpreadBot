# Nexus Spread Scanner

`nexus-spread-bot` is an asynchronous multi-exchange spread scanner. It monitors spot order books
across centralized exchanges, estimates the **net** arbitrage spread after taker fees on both
legs, order-book slippage, and network transfer costs, and sends formatted Telegram alerts
for opportunities above a configured threshold.

> **Safety:** the bot never withdraws or transfers funds. Version 1 is read-only.

Status: **Stage 1 (MVP) in progress** — see [todo.md](todo.md).

## Quickstart (local)

See the setup guide (Russian): [docs/guides/stage-1-local-setup.md](docs/guides/stage-1-local-setup.md).

```bash
cp .env.example .env    # fill in Telegram token/chat id and optional read-only API keys
make up-local
```

## Development

```bash
uv sync
make check   # ruff + mypy --strict + unit tests
```
