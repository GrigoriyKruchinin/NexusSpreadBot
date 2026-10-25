# T5 - Anti-spam: dedupe, cooldown, edit-in-place, close message

- id: T5
- stage: S1-tool
- owner: backend-lead
- complexity: high (concurrency between scanner, outbox and Telegram API; idempotency)
- size: L
- depends_on: T3, T4
- status: todo

## Goal
One episode = one Telegram message that is edited while the spread lives and marked closed at the end, with strict anti-spam limits.

## Context docs
`services/alerts.py`, `scanner/episodes.py`, `domain/episodes.py`, `infra/redis_store.py`, `notifications/telegram.py`, `[alert]`/`alert_cooldown_s` in config

## Scope
1. INotifier gets `edit(message_id, message)` (Telegram `editMessageText`); `DeliveryReceipt.message_id` is stored with the episode (column on episodes or alert outbox row).
2. Rules: (a) dedupe key = episode id (route + base) so one open episode never produces a second NEW message; (b) UPDATE only if net grew/fell by >= `alert.update_min_change_pct` (default 25 % relative) AND >= `alert.update_min_interval_s` (default 60 s) since the last edit; (c) cooldown per route after CLOSED: `alert_cooldown_s` before a NEW message for the same route (flapping); (d) global cap `alert.max_per_hour` (default 30), overflow collapsed into one 'N more spreads suppressed' message; (e) CLOSED: edit the message to the closed template, silent (`disable_notification`)
3. Fallbacks: edit fails with 'message not found'/'cannot be edited' -> send a new message once and store the new id; 'message is not modified' -> ignore; 429 -> honour `retry_after`, never loop
4. Telegram rate limits: <= 1 msg/s per chat, <= 20 msg/min to a channel; a small token bucket in the sender
5. Stale `SENDING` rows reaper (B12) folded in here

## Acceptance criteria
- Unit tests with a fake notifier: new/update/close sequence produces 1 send + N edits + 1 close edit; flapping route obeys cooldown; cap overflow produces one summary
- Failure tests: edit error -> single resend; 429 -> delayed retry; duplicate worker delivery does not double-send (idempotency key)
- Integration test on `nexus_test` for the outbox/episode message_id persistence (CI only)
- Restart mid-episode does not spam: open episodes reload their message_id

## Out of scope
Digest content; changing spread math.

## Files likely touched
src/nexus/services/alerts.py, notifications/, interfaces/notifications.py, persistence, tests/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).
