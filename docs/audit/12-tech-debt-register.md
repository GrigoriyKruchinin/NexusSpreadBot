# 12 - Tech Debt Register

TODO/FIXME/XXX/HACK markers: a grep across `src`, `tests`, `Makefile`, `Dockerfile*`, `docker-compose*` found **none**. Debt is tracked in prose inside todo.md instead. `# type: ignore` / `noqa`: 1 occurrence in src. `except Exception`: 25 occurrences in src (not individually reviewed; see TD-07).

Scale: severity L/M/H; fix cost S (<0.5 d), M (1-3 d), L (>3 d).

| ID | Problem | Where | Sev | Cost | Depends on |
|---|---|---|---|---|---|
| TD-01 | No CI pipeline; gates run only locally | `.github/` absent; see 07 INF-01 | H | S-M | none |
| TD-02 | No DB backup/restore procedure | compose volumes; 07 INF-04 | M | S | off-host target |
| TD-03 | Single owner DB credential for all services | docker-compose.local.yml:23-28; todo.md:339 | M | M | prod compose, Alembic role grants |
| TD-04 | Quarantine recurrence history held in memory only | todo.md:305; `scanner/quarantine.py` | M | S-M | persist spans in DB/Redis |
| TD-05 | `scanner/service.py` is 1048 lines (orchestrator doing sweeps, WS, episodes, paper, health, events) | `src/nexus/scanner/service.py` | M | M-L | tests already cover; split by responsibility (SRP) |
| TD-06 | Key-based transfer-status parsers unverified against live exchanges | todo.md:166; `adapters/cex/*` | M | M | real read-only keys |
| TD-07 | 25 broad `except Exception` handlers, risk of swallowed errors vs CLAUDE.md "never swallow" | `grep -rn "except Exception" src` | M | M | review each for logging/re-raise |
| TD-08 | (R) items 1.5.6 and 1.5.11 ticked without recorded audit verdict | todo.md:218, 293 | M | S | run `/audit-risks` |
| TD-09 | Dead scaffolding: `BaseDEXProvider` unused | `src/nexus/interfaces/dex.py` | L | S | decide keep/remove |
| TD-10 | Doc drift: CLAUDE.md lists 5 V1 exchanges, code has 7; todo.md Stage 3 lists MEXC/Bitget as future | CLAUDE.md "V1 Product Decisions"; todo.md:395 | L | S | none |
| TD-11 | Duplicate/superseded roadmap items still open | todo.md:117, 349, 395 | L | S | none |
| TD-12 | Dual alert-dedup mechanisms (route cooldown + episode keys) | `SPREAD_ALERT_COOLDOWN_S`, todo.md:213 | L | S | soak data |
| TD-13 | Base image not digest-pinned; no image HEALTHCHECK; no vuln scan | `Dockerfile:3,21` | L | S | CI |
| TD-14 | Redis without auth/maxmemory; shared by cache and Celery broker | docker-compose.local.yml:137-147 | M | S | none |
| TD-15 | No resource limits / crash-loop backoff cap | `x-image` anchor | L | S | none |
| TD-16 | Scanner start gated on alerts-worker health | docker-compose.local.yml:165-167 | L | S | none |
| TD-17 | Healthcheck CLI supports only `scanner`; workers/beat use shell one-liners | `cli.py:61`, compose:186,203,219 | L | S | none |
| TD-18 | Integration tests not wired to a Makefile target/compose DB; no CI run | Makefile:35-36; README:92 | L | S | TD-01 |
| TD-19 | `make revision` runs on host, not in container | Makefile:56-58 | L | S | none |
| TD-20 | Redundant migrations/README COPY in Dockerfile | Dockerfile:16, 22-27 | Info | S | none |
| TD-21 | Pre-commit runs whole-project mypy on each commit; weak secret detection | .pre-commit-config.yaml:12-27 | L | S | TD-01 (gitleaks) |
| TD-22 | `SCANNER_MIN_QUOTE_VOLUME_USD=50000` is a placeholder pending soak | todo.md:290-291 | L | S | soak |
| TD-23 | No metrics/tracing; observability is logs + digest only | src (no prometheus/sentry) | M | M | prod monitoring design |
| TD-24 | Logging secret scrubbing is pattern-based | `log.py:20-60` | L | S-M | add key-name-independent tests with real-format fixtures |
| TD-25 | Telegram UX lacks interactive controls (mute route, pause) | notifications/*; todo.md:386 | L | M | aiogram decision (CLAUDE.md) |
| TD-26 | Untracked `nexus-adoption-instructions.md` in repo root | git status | Info | S | none |
| TD-27 | Stage 1 exit checkbox: user real-Telegram check never ticked | todo.md:112 | L | S | user |

Confidence: High for TD-01..04, 08, 10, 11, 13, 14, 26 (direct evidence); Medium for TD-05, 07, 15, 24 (inferred from size/grep, not reviewed line by line).

## Suggested sequencing
1. TD-01 + TD-18 + TD-21 (CI with integration services and secret scan).
2. TD-02, TD-14, TD-15 before any unattended multi-day soak.
3. TD-08 and TD-06 to close process/verification debt in the signal path.
4. TD-04, TD-05, TD-07 as a refactor pass before Stage 2 execution code builds on the scanner.
5. TD-03 as the first step of Stage 2.
