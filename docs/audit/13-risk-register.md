# Risk register

| ID | Risk | Sev | Source |
|---|---|---|---|
| R-01 | Integration tests TRUNCATE the DB named in env (localhost:5432/nexus); live paper/snapshot data was wiped on 2026-10-23, no backups exist | High (occurred) | 04, 05, 07 |
| R-02 | One non-ExchangeError in a fetch aborts whole sweep via asyncio.gather -> no heartbeat, unhealthy container | Med | 03 (service.py:795-808, 293-308) |
| R-03 | Net profit overstated in stored analytics: buy fee assumed in base currency; transfer fee 0 when UNKNOWN; USDT/USDC = 1 USD | Med | 03 M-section |
| R-04 | spread_evaluations growth (~60 cols, 4 indexes, est. 7-8M rows/30d, unverified); unbatched purges; no DB timeouts | Med | 08 |
| R-05 | No CI, no coverage floor: quality ratchet unenforced | Med | 05, 07 |
| R-06 | Vulnerable deps: certifi (PYSEC-2026-4320), protobuf 5.29.5 hard-pinned (PYSEC-2026-1805) | Med | 06 |
| R-07 | httpx INFO log may print Telegram URL with bot token | Med | 06 |
| R-08 | No clock-sync/NTP guard; cross-venue book skew uses exchange timestamps; cancellation swallowed in _until_stopped | Med | 03 |
| R-09 | No Postgres backups, no external bot-down signal; Redis without auth; one DB role for all services | Med | 07 |
| R-10 | Scope drift: 7 adapters vs 5 documented; transfer-status parsers unverified with real keys (todo.md:166); items 1.5.6/1.5.11 (R) have no recorded audit verdict | Low-Med | 09, 01 |
| R-11 | No LICENSE; exchange ToS and Argentina CNV/tax notes unverified (no sources consulted) | Med | 11 |
| R-12 | Bus factor 1; direct-to-main workflow | Low | 14 |
| R-13 | Alert claim at-most-once; crashed SENDING row never recovered | Low | 03 |
