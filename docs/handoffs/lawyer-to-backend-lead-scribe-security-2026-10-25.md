# Handoff: lawyer -> backend-lead (T4), security (T9), scribe (T10) — 2026-10-25

- Why: T13 done; its texts and constraints feed T4 templates, T9 key statement and T10 README.
- Where: `docs/legal/tool-distribution.md` (s. 2 = what to do, s. 3 = texts, s. 4 = LICENSE).
- T4 (backend-lead): default/documented mode = operator's private channel; pinned text s. 3.2 (en/ru) via the catalog;
  no public-broadcast mode, no ads/referral placeholders, no exchange logos.
- T9 (security): confirm in code that keys go only to the venue's API host, are never logged/stored/sent to Telegram, and
  there is no telemetry. Only then may T10 publish statement s. 3.3; otherwise reword it.
- T10 (scribe): README sections Disclaimer (s. 3.1), Exchange data terms (s. 3.4), API keys (s. 3.3), License (after the
  user decides; recommendation Apache-2.0).
- Pitfalls: alerts carry raw prices = exchange Market Data; never describe Nexus as suitable for public or paid signal
  channels. Proxy/geo-bypass features conflict with OKX 9.4 and Gate 1.3(h).
