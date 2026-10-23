# Security review — B14 conditional venues reporting

- Reviewer: security (read-only)
- Date: 2026-10-23
- Scope: commits `5ba4f07`, `e23024d`; card `docs/tasks/m2/B14-conditional-venues-reporting.md`
- `.env` not read.

## Verdict: ACCEPT (no blocking points)

## Checks

| # | Area | Result |
|---|------|--------|
| 1 | Secrets / connection strings / account ids in Telegram text | OK. Digest block and alert marker carry only venue display names, counts and USD totals. No DSN, key, chat id or account id is touched. |
| 2 | Secrets in logs | OK. `digest_sent` adds `conditional_venues` (lowercase ids), `total_all` / `total_excl_conditional` (episode count + P&L as string). `conditional_venues_defaulted` logs default/effective lists and `EXCHANGES_ENABLED` names only. |
| 3 | Startup logs | OK. `scanner_starting.conditional_venues` and `alerts_worker_starting.conditional_venues` carry venue names only. |
| 4 | HTML escaping | OK. Venue names pass `esc(exchange_name(...))` in digest and alert marker; symbol still `esc`. Static `P&amp;L` is a literal entity. Defence in depth: venue names are additionally constrained by `^[a-z][a-z0-9_]*$`, so no markup characters can reach the message even before escaping. |
| 5 | Config validation abuse | OK. Strip + lowercase, regex, duplicate check; explicit list must be subset of `EXCHANGES_ENABLED` (fail-fast). Error messages echo only the offending venue name (`!r`) — not secret-bearing. Empty env falls back to default (`env_ignore_empty=True`); `[]` = none. The setting only affects read-side reporting, cannot enable collection, trading or transfers (ADR 0001 intact). |
| 6 | SQL construction | OK. `trade_free_clause` / `rebalance_free_clause` use SQLAlchemy `column.in_(tuple)` with bound parameters; no string interpolation/`text()`. Empty tuple renders SQLAlchemy's empty-IN expression (safe). Python-side episode filter uses `touches_conditional` on ORM attributes. |
| 7 | Docker / env | OK. New `x-conditional-env` anchor adds only `CONDITIONAL_VENUES` to scanner and alerts worker; no secret groups added to new services. `.env.example` value is non-secret. |
| 8 | Secret scan of diff | OK. Only hits are pre-existing test placeholders (`DB_PASSWORD`, `VALID_TOKEN`, `"k"`/`"s"`, chat id `"42"`) in unit-test fixtures. |

## Non-blocking notes

- N1 (info): `_init_logging` for the alerts role re-instantiates `ConditionalVenuesSettings()`; an invalid value would raise a pydantic `ValidationError` there, whose text includes the raw input. The input is a venue list (not secret), so no leak; just a second failure point beside `_validate_role_settings`.
- N2 (info): alerts worker has no subset check (no `EXCHANGES_ENABLED`); a non-enabled name never matches a route, so no security impact.
- N3 (carry): tech-lead point 6 (validate names against adapter registry) remains deferred; not a security issue given the regex.
