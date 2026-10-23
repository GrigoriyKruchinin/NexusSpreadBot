# Stage-end regression: Track 0 (B1, A2, A2a, A4, B1a, A6, A5a) + B14

Date: 2026-10-23. Branch `chore/agent-pipeline-adoption`, head `4c7fd70`. Author: tester.

## Numbers
| Metric | Baseline (docs/audit/05) | Now |
|---|---|---|
| Unit tests | 481 | 720 (721 with the safety net below) |
| Branch coverage | 89 % | 90.55 % (gate 89 %) |
| ruff / mypy --strict | 0 / 0 | 0 / 0 (137 source files) |
| Unit suite runtime | - | 16-23 s |

Flaky signs: unit suite run three times (`make check`, `make test-cov`, `--durations`),
720 passed every time, no reruns, no order dependence seen. Slowest test:
`test_ccxt_adapters.py::test_timeout_maps_to_unavailable` (2.0 s, real timeout path); next
ones are 0.26-0.28 s (client construction, runtime guard). No concern.

## Integration (CI only, user decision)
Not run locally. Latest CI run on the branch head `4c7fd70` (run 40040083013): success, all 7 jobs
green: unit, lint, typecheck, integration, secret-scan, dependency-audit, docker-build.
The previous run (on `1674089`) was cancelled by the newer push; the run before it is green.

## Gap check: acceptance criteria vs tests
Result: all criteria that are testable in unit scope have tests, except one gap that was closed.
- B1: default == CORE_EXCHANGES, explicit extension list, empty env fallback (`test_settings.py`),
  `.env.example` sync (`test_env_example.py`). Covered.
- A2 (CI): verified by CI runs, not unit tests. Negative checks are recorded in the card. Covered by process.
- A2a (gitleaks hook): config-only (`.pre-commit-config.yaml` pins gitleaks with `.gitleaks.toml`,
  `--redact`); block-demo is a one-off manual check. No unit test (not unit-testable).
- A4: URL credentials, no false positives, httpx/stdlib loggers, Celery line, ccxt repr
  (`test_log_leaks.py`). Covered.
- A6: per-venue pass/refuse/malformed/missing, logs without body, GET-only guard on every client,
  attestation for kucoin/gateio, no-key skip, scanner-start ordering, CLI non-zero exit
  (`test_key_policy.py`). Covered. Not checked here: target.md section 10.4 text (docs).
- B1a: criteria 1-2 (no MEXC_/BITGET_ in compose and `.env.example`) had NO test. ADDED
  `test_extension_venue_keys_not_wired_by_default` in `tests/unit/test_compose.py`.
  Criterion 3 (docs mention) is present in README and `docs/guides/stage-1-local-setup.md`
  (grep only); criterion 4 (`docker compose config`) not run per rules (no docker).
- A5a: retention/prune, path refusals, modes, restore target guard, role pin, count checks,
  heartbeat, bootstrap SQL (`test_backup_scripts.py`, fake docker sandbox). Covered. Not unit-
  testable: real dump, `.gitignore`/`.dockerignore` entries, age/gpg encryption docs, restore-drill
  report (`docs/reports/restore-drill.md` is the evidence), cron install.
- B14: touches_conditional, aggregation totals, config default/override/invalid/empty/subset,
  golden digest incl. empty list, alert marker, escaping, length < 4096, log fields
  (`test_conditional.py`, `test_digest_conditional.py`, `test_settings.py`, `test_digest.py`,
  `test_formatting.py`). Covered. `.env.example` sync test exists; compose wiring is covered by the
  generic documented-variable test.

## Findings
No production bug found. Residual, non-blocking: no unit test for gitleaks hook presence
(consider a trivial yaml assertion if desired); compose `config` validity is only checked indirectly
by YAML parsing in `test_compose.py`.
