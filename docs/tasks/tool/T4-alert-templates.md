# T4 - Alert message templates (new/update/closed) with i18n ru/en

- id: T4
- stage: S1-tool
- owner: backend-lead
- complexity: medium (formatting plus Telegram HTML limits)
- size: M
- depends_on: T3
- status: done

## Progress
Done: catalog (en/ru) in alert_catalog.py, `[alert] language`, NEW/UPDATE/CLOSED templates, golden + escaping tests. Pinned disclaimer text in catalog (README in T9). Edit-in-place left to T5.

## Goal
Define and implement the three Telegram message templates carrying the approved fields, in Russian and English chosen by a setting.

## Context docs
`src/nexus/notifications/formatting.py` (current Russian `OpportunityFormatter`), Telegram HTML subset rules

## Scope
1. Setting `[alert] language = "en"|"ru"` (default `en`; owner keeps `ru`). All user-facing strings via one small catalog, no scattered literals.
2. Template NEW (<= 1200 chars, no table in pre-blocks that breaks on mobile):
```
🟢 <b>COIN</b>/USDT   +1.12 % net
Buy  <b>Binance</b>  0.04210
Sell <b>KuCoin</b>   0.04290
Net after fees/slippage: <b>+1.12 %</b> (≈ $34.20 on $3,050)
Volume: <b>$3,050</b> (≈ 72,400 COIN) by orderbooks
Transfer: <b>BEP20</b> · fee 0.8 COIN (≈ $0.03) · ≈ 5 min (approx)
Withdraw Binance: ✅ open   Deposit KuCoin: ✅ open
Lifetime: just opened   ·   #id
```
3. Template UPDATE (edit-in-place or reply when edit impossible): same body with current numbers + `Lifetime: 4 m 20 s, peak +1.9 %`
4. Template CLOSED: first line replaced with `⚪ Closed` + `Lived 6 m 05 s, peak +1.9 %, last +0.7 %`; transfer/open flags kept as last seen
5. Unverified/closed flags shown as ⚠️/❌/❓ with a one-line hint; conditional-venue marker (B14) kept only if still configured
6. Disclaimer footer once in the channel pin text, not in every alert (documented in README, T9)

## Acceptance criteria
- Golden-string tests for NEW/UPDATE/CLOSED in ru and en, incl. unknown transfer, closed deposit, unverified network
- Every message <= 4096 chars after escaping (existing `truncate` still applies); HTML escaped (test with `<`, `&` in coin names)
- No secrets or internal ids beyond episode number in text

## Out of scope
Edit-in-place mechanics (T5).

## Files likely touched
src/nexus/notifications/formatting.py, new catalog module, config/nexus.toml, tests/unit/notifications/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
