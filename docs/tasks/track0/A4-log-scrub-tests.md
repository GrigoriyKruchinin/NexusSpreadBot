# A4 — Log scrubbing proven by tests (R-07, S-07)

- id: A4 (migration-plan §A; todo.md Track 0 R-07)
- stage: Track 0 (base)
- owner: backend-lead
- reviewers: security (leak scenarios), tech-lead
- complexity: low (code already sets httpx/httpcore/ccxt >= WARNING; the work is proof plus one pattern)
- depends_on: A2 (CI runs the new tests)
- status: todo

## Goal
Prove with unit tests that no secret reaches logs via httpx/httpcore/stdlib loggers, Celery
task logs or URL/DSN credentials, and close any gap found.

## Context docs
`docs/audit/security-review-architecture.md` (S-04, S-07), `docs/architecture/target.md` §10.2, §10.4,
`docs/audit/06-security-baseline.md`, `src/nexus/log.py`, `src/nexus/workers/app.py`.

## Acceptance criteria
1. Test: httpx INFO request log for `https://api.telegram.org/bot<fake-token>/sendMessage` either is
   not emitted (logger level >= WARNING) or its output, captured via `caplog`/handler through the
   real logging setup, contains no token.
2. Test: stdlib loggers (`httpx`, `httpcore`, `ccxt`, root, `celery.*`) routed through the scrubber;
   a record emitted by each with a fake token/API key in message and in `args` is scrubbed.
3. Scrubber covers URL credentials: `redis://user:pass@host:6379/1`, `redis://:pass@host`,
   `postgresql+asyncpg://u:p@h/db`, `amqp://...` -> `scheme://***@host...` (pattern
   `://[^:/@\s]*:[^@\s]+@`); tests incl. no false positive on URLs without credentials and on
   `host:port` text.
4. Test: Celery task-received style log line with payload args does not expose secret-like values;
   card/target note that payloads never carry secrets.
5. Test: formatted exception repr of a ccxt auth-style error containing a fake key is scrubbed
   when logged via the project logger (rule: never log raw ccxt auth `repr` without `scrub`).
6. All fake secrets are obviously synthetic; gitleaks allowlist updated only by exact value if needed.
7. `make check` not worse than baseline (>= 492 unit, coverage >= 89 %, ruff 0, mypy 0); todo R-07
   ticked in the same commit as verification.

## Out of scope
Log redesign, structured-logging migration, Redis auth itself (A5b), new log stack/metrics (D-track),
scrubbing of non-regex-detectable bare secrets (known limit INF-13; documented, not solved here).

## Files likely touched
`src/nexus/log.py`, `tests/unit/test_log.py` (and a new `tests/unit/test_log_leaks.py`),
`.gitleaks.toml` (only if new fakes), `todo.md`, this card.

## Risks
Regex over-scrubbing can hide useful diagnostics; keep the pattern narrow and test negatives.
