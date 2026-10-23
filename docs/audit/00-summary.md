# Audit summary (2026-10-23)

Nexus Spread Scanner: async Python 3.12 scanner of net spreads between spot CEXs
(code has 7 adapters; CLAUDE.md lists 5). Net spread = after taker fees on both legs, orderbook
slippage at a $1,000 notional and transfer cost; alerts to Telegram; every evaluation stored in
PostgreSQL; paper trading exists. Docker Compose local stack (7 services) was healthy.

**Stage:** MVP / analysis (trajectory M). Code is mature, the hypothesis is NOT yet tested: only a
~10 h keyless soak and a 4 min smoke exist, and the paper data was wiped by an audit mishap (R-01).

**Strengths:** 481 unit tests green, 89 % branch coverage, ruff 0 / mypy --strict 0, Decimal money
math, hardened app image, GET-only guard on exchange REST clients, no withdraw/trade calls, no
secrets in code or history.

**Top risks:** see 13-risk-register.md. **First steps:** protect integration tests from touching the
live DB, add CI + coverage floor, fix sweep isolation and DB timeouts, bump certifi/protobuf, add
pg_dump backups, then run a multi-day keyed soak and the quant viability analysis.

**Plain words:** the tool works and is well tested, but nobody has yet proven that it can make
money after all costs. The next job is honest data collection and a math check, not new features.
