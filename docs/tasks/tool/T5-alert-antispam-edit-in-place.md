# T5 - Anti-spam: dedupe, cooldown, edit-in-place, close message

- id: T5
- stage: S1-tool
- owner: backend-lead
- complexity: high (concurrency between scanner, outbox and Telegram API; idempotency)
- size: L
- depends_on: T3, T4
- status: done (integration tests run in CI only)

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

## Result
- Update rule: `OpportunityEpisode.alert_kind` - relative change up OR down >= `[alert] update_min_change_pct` (25) and >= `update_min_interval_s` (60) since the last alert; replaces `realert_growth_pct`. Dedupe key = episode id (Redis `alert:episode:<id>:<n>`, unchanged). Route cooldown restarts at the CLOSE of an alerted episode.
- Delivery (`services/alerts.py`): NEW sends and stores `message_id` + last evaluation id + AlertContext payload (so volume/transfer blocks survive, the T3 risk) in new columns of `opportunity_episodes` (revision `b7d2c4e6a1f3`, written by the alerts worker only). UPDATE edits it; MessageGoneError -> one re-send, new id stored; "not modified" is success in `TelegramNotifier.edit`. `EpisodeClosed` carries `episode_id` + times; the worker edits the message to CLOSED (silent, lifetime until the last qualifying evaluation, never expired); no message -> the old closed event message.
- Cap: `[alert] max_per_hour` (30) NEW messages per clock hour (table `alert_hour_budget`, atomic upsert); overflow -> `SUPPRESSED` log row + ONE silent "N more spreads suppressed" message edited as it grows. Updates/closes do not consume the budget; a failed send refunds its slot.
- Rate limits: `notifications/rate_limit.py` sliding window (`send_min_interval_s` 1.0, `send_max_per_minute` 20), 429 `retry_after` blocks the limiter and goes to the Celery retry countdown; a slot further than 20 s away is handed back to the task retry. The limiter is per process: alerts worker is now `--concurrency 1` in `docker-compose.local.yml`.
- B12 reaper: `RetentionRepository.purge(alerts_sending_before=...)` marks `sending` rows older than `[alert] sending_stale_s` (600) as `failed` (hourly maintenance task).
- Known limits: the cap uses clock-hour buckets (a burst across :59/:01 is bounded by the 20/min limiter); with several alerts workers the limiter and ordering guarantees are per process.
