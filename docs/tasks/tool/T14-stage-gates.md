# T14 - Stage gates: tech-lead, tester, security, delta audit, close

- id: T14
- stage: S1-tool
- owner: orchestrator
- complexity: medium (process card; reviews are done by critics)
- size: M
- depends_on: T1a-T13
- status: todo

## Goal
Close S1-tool per `close-stage`.

## Context docs
skill `close-stage`, `docs/audit/`

## Scope
1. tech-lead review of the whole diff (max 3 fix rounds); focus: alert state machine (T5), startup validation (T7), removed-code leftovers
2. tester: full regression + manual E2E with a real test bot/channel by the user
3. security review: secret handling in startup messages and logs, Telegram token scope, key permission checks, compose exposure of ports (Postgres/Redis not published), default passwords absent
4. delta audit `docs/audit/delta-03-S1-tool.md`; tag proposal; summary to the user (Russian)

## Acceptance criteria
- tech-lead ACCEPT, security ACCEPT, delta audit committed, STATE/todo current, ratchet baseline updated

## Out of scope
Merge to main (only with user consent).

## Files likely touched
docs/audit/

DoD: `make check` green and not worse than baseline, new tests, no secrets in diff, todo.md + card updated, committed (Conventional Commits).

## Progress note: fix round 1 (backend-lead, 2026-10-25)
Tech-lead review points handled (see `docs/audit/tech-lead-review-S1-tool.md`):
- 1, 2, 9, 10, 11: `services/alerts.py` (a close without a stored message is silent; an UPDATE without a stored message is dropped; a NEW that finds a stored message edits it), `DeliveryReceipt.message_id` may be `None`, `truncate()` keeps HTML valid, docstring fixed.
- 3: system events and digest are rendered from `alert_catalog` (`sys_*`, `dg_*`, `wd_*` keys) in `[alert] language`; `SystemEventFormatter(language)` / `DigestFormatter(language)` wired in `container.py`.
- 7, 12: placeholder regex matches the whole value; key check retries transient errors 3x (1 s, 2 s backoff) before the public fallback; auth errors are not retried.
- 8, 13, R2: `nexus pin-text [--lang en|ru]` prints the pinned disclaimer (devops: reference it in README); `nexus check` calls `configure_logging` (WARNING, redaction on); DB probe covered by unit tests with a fake engine; `fmt_time` removed.
- 16 (owner language ru): optional untracked `config/local.toml` next to `config/nexus.toml`, merged per key over it (same guard as the main file, settings only, secrets stay in `.env`), gitignored, copied into the image by `COPY config/nexus.toml config/local.tom[l] ./config/`. Owner setup: create `config/local.toml` with `[alert]` / `language = "ru"`, then `make up` (rebuild). The Dockerfile glob is verified by test only, not by a real `docker build`: tester should confirm the build with and without the file.
- Not mine: 4, 5, 6, 14, 15 (docs/compose/guard rails).

## Progress note: fix round 2 (backend-lead, 2026-10-30)
- R2-1: `tests/unit/config/test_config_file.py` repo-file tests (`test_repo_toml_equals_code_defaults`, `test_merged_db_name_is_what_the_integration_guard_checks`) now load a copy of `config/nexus.toml` from an empty tmp dir (`_hermetic_repo_toml`), so an owner's `config/local.toml` cannot change them. Regression test `test_owner_local_toml_next_to_the_repo_file_does_not_leak_into_repo_tests` (fake config dir in tmp_path; the real `config/` is never written). Runtime loader unchanged.
- N-1: docstring line in `services/alerts.py::_deliver` (dropped UPDATE is not replayed; growth announced at next threshold).
