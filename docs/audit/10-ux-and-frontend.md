# 10 - UX and Frontend Audit

## No GUI exists
- No `src/nexus/dashboard/`, no FastAPI/Jinja/Chart.js in `pyproject.toml` (grep for dashboard/fastapi returned nothing), no static assets, no templates directory (`ls src/nexus` shows config, domain, engine, adapters, infra, interfaces, notifications, persistence, scanner, services, simulation, workers only). The dashboard is Stage 3 (todo.md:371-402, all unchecked) and no `docs/guides/stage-3-dashboard.md` exists. Severity: Info. Confidence: High.
- Only user interface is Telegram (push, one-way) plus `docker compose logs` and direct SQL on 127.0.0.1:5432. There are no interactive commands (no kill switch/pause; todo.md:386 plans them).

## Telegram message UX (code review only; no live messages seen)
Where: `src/nexus/notifications/formatting.py`, `digest.py`, `telegram.py`.
- UX-01 Positive: HTML parse mode with a central `esc()` (formatting.py:55) used for dynamic values; money/percent/price/duration formatters (`fmt_usd`, `fmt_pct`, `fmt_price` with significant digits, `fmt_duration`, lines 65-112); `truncate()` guard for the 4096 limit (line 115). Severity: n/a. Confidence: Medium.
- UX-02 Positive: messages are Russian (git log: "Russian alert, event and digest messages"), show gross vs net, fee/slippage/transfer breakdown, book age, and always label unverified transfer and estimated fees (todo.md:104). Snapshot tests exist (tests/unit/notifications).
- UX-03 Alert fatigue controls exist: one alert per episode, re-alert only on +50 % growth, "episode closed" summary, queue-age drop (`TELEGRAM_ALERT_MAX_AGE_S`), quarantine of flapping routes. First soak still produced 19 alerts on one route before the fix (todo.md:293-295), so thresholds are unproven. Severity: Low. Confidence: Medium.
- UX-04 Gap: alerts are read-only text with no action affordance (no inline keyboard, no link to exchange pair pages, no "mute route/exchange" command). Operators cannot silence a noisy route without editing `.env` blacklist and restarting. Severity: Low. Confidence: High.
- UX-05 Gap: no bot-down notification (see 07 INF-05); user learns about outages only by silence. Digest is once a day at 09:00 Europe/Moscow by default.
- UX-06 Risk: mixed-language sources: README, CLAUDE.md, code are English; messages Russian; if the chat is a group with non-Russian readers, nothing is configurable (no locale setting found). Severity: Info. Confidence: Low.
- UX-07 Not verified: rendering of long digests on mobile, emoji/blockquote look. Needs a live screenshot review.

## Dashboard code
None. Nothing to audit. Recommendation: do not start Stage 3 before the Stage 1.5 soak go/no-go; meanwhile a read-only SQL view or saved queries would cover analysis needs.
