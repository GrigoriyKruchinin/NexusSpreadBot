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

## Status (as of delta audit 02, 2026-10-24, HEAD `1fb8d60`; details in `delta-02-S0.md`)

Rows above are the baseline (audit `0f596e3`); D-xx rows come from delta audits.

| ID | Status | Note |
|---|---|---|
| R-01 | Closed | `tests/db_guard.py`, CI asserts `nexus_test` (delta-track0-B14) |
| R-02 | Closed (code) | `gather_isolated`, S0b `110fb91`/`cb1c1af`; B3 failure counters still open |
| R-03 | Open | engine untouched; M2 |
| R-04 | Open | M2 (+ A5a N4) |
| R-05 | Closed | CI + floor 89 % |
| R-06 | Closed | f6b5abb, todo ticked |
| R-07 | Closed | 37de0fa |
| R-08 | Open | M2 / B4 |
| R-09 | Reduced | backups + copy + watchdog; Redis auth (A5b), roles (A5c), external heartbeat (A5d) open |
| R-10 | Reduced | parsers / 1.5.6, 1.5.11 verdict open |
| R-11 | Reduced | legal docs; LICENSE open |
| R-12 | Reduced | branch + CI; bus factor 1 |
| R-13 | Open | B12 |
| D-01 | Closed (config), live check pending | `unless-stopped` + park on exit 3; confirm on first soak restart |
| D-02 | Reduced | off-machine copy + status file + watchdog; same-host residual (D-09) |
| D-03 | Open | drill on first dump of the fresh DB |
| D-04 | Accepted | `nexus_test` holds live copy (A5c) |
| D-05 | Open | key attestation, before U3 |
| D-06 | Reduced | B15 part 1 per-set portfolios; valid only after soak + B15 part 2 |
| D-07 | Partly fixed | new drift list in delta-02 §5 |
| D-08 | New, Med | disabled paper set / paper failures are log-only, not watched |
| D-09 | New, Med | watchdog is single-host; PC/stack outage is silent |
| D-10 | New, Low | migration `b15a7c3e91d2` first applied on the fresh DB |
| D-11 | New, Low | watchdog state in unauthenticated Redis (A5b) |
| D-12 | New, Low | scanner-alive signal = `exchange_health`; stuck later phases look alive |
