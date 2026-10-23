# 07 - Infrastructure and Delivery Audit

Scope: Dockerfile, docker-compose.local.yml, Makefile, .pre-commit-config.yaml, CI/CD, deploy, rollback, backup, monitoring, logging. Read-only audit; `.env` was not read. Date: 2026-10-23. Branch `chore/agent-pipeline-adoption`.

Format: ID - what - where - evidence - severity / confidence.

## Summary

Local development stack is solid (non-root, read-only rootfs, per-service env scoping, healthchecks, log rotation). Everything past "laptop" is absent: no CI, no prod compose, no backups, no external monitoring, no deploy or rollback path. This matches todo.md Stage 2.5/2.6 (all unchecked), so these are known gaps, but the bot is expected to run multi-day soaks now (todo.md:310) with zero safety net.

## Findings

### INF-01 No CI at all
- Where: `.github/` missing (`ls .github` -> No such file); `.dockerignore:2` still lists `.github`.
- Evidence: quality gates (ruff, mypy --strict, pytest, test_safety AST check) run only on the developer machine, enforced by agent convention (CLAUDE.md "Autonomous Delivery Loop") and pre-commit. Pushes go straight to `main` (`.claude/settings.json` allows `git push origin main`). No secret scanning, no dependency audit, no integration tests in a pipeline.
- Severity: High. Confidence: High.

### INF-02 Pre-commit is local-only and bypassable; hook set incomplete
- Where: `.pre-commit-config.yaml:1-28`.
- Evidence: hooks are `language: system` calling `uv run ...` (needs local env); `mypy src tests` runs on every commit (slow, discourages use). No pytest hook, no secret scanner beyond `detect-private-key` (does not detect API keys/Telegram tokens), no `check-merge-conflict`. Whether `pre-commit install` was ever run cannot be verified from the repo (no `.git/hooks/pre-commit` check performed; the agent flow forbids `--no-verify` only by settings deny list).
- Severity: Medium. Confidence: Medium.

### INF-03 No production compose, deploy, or rollback
- Where: only `docker-compose.local.yml` exists; todo.md:352-362 unchecked.
- Evidence: image is tagged `nexus-spread-bot:local` (docker-compose.local.yml:10), built in place. No registry push, no SHA tags, so no rollback target. `make migrate` only exists for local compose (Makefile:50-51). Migrations are forward-only in practice; no documented downgrade/rollback procedure. `migrator` runs `alembic upgrade head` automatically on every `up` (compose:149-156) - a bad migration blocks all services (they depend on `service_completed_successfully`).
- Severity: High for any non-laptop run; Medium today. Confidence: High.

### INF-04 No backups of PostgreSQL or Redis
- Where: compose volumes `postgres-data`, `redis-data` (docker-compose.local.yml:225-227); no `pg_dump` anywhere (grep for backup/pg_dump finds only docs/guides/free-hosting.md).
- Evidence: all evaluations, episodes, quarantine and paper-trading state (portfolio totals are "kept", todo.md:278) live in a single named volume. `docker compose down -v` or disk loss wipes the soak data that drives the Stage 2 go/no-go. Paper P&L cannot be recomputed from retained data (snapshots are purged by retention).
- Severity: Medium (data is paper, not funds). Confidence: High.

### INF-05 No external monitoring or dead-man switch
- Where: healthchecks docker-compose.local.yml:168-174, 185-190, 202-207, 218-223; `src/nexus/cli.py:40-53,61`.
- Evidence: health is visible only through `docker compose ps`. If the host sleeps, Docker stops, or all containers die, no Telegram "bot is down" message can be sent (alerts come from the same stack). `nexus healthcheck` accepts only target `scanner` (cli.py:61); workers use `celery inspect ping`, beat uses a pidfile check (compose:219) which proves the process exists, not that it schedules. No metrics endpoint (no Prometheus/Sentry anywhere in src). todo.md:310 already notes "laptop must not sleep".
- Severity: Medium. Confidence: High.

### INF-06 Scanner start is coupled to alerts worker health
- Where: docker-compose.local.yml:165-167.
- Evidence: `scanner` depends on `worker-alerts: service_healthy`. A Telegram or broker problem that fails `celery inspect ping` (timeout 5 s, compose:186) blocks scanner start, so data collection stops because the notification path is down. Also `inspect ping -d alerts@$$HOSTNAME` depends on hostname-based node naming (`-n alerts@%h`), fragile on recreate.
- Severity: Low-Medium. Confidence: Medium.

### INF-07 Redis has no auth and holds the alert/dedup/quarantine state; broker shares instance
- Where: docker-compose.local.yml:137-147; broker `redis://redis:6379/1`, cache `redis://redis:6379/0` (compose:31, 50).
- Evidence: no `requirepass`; any container on the compose network (including a compromised dependency in any service) can enqueue Celery tasks that render Telegram messages. Port is not published (good). Redis persistence `--save 60 1000` + AOF; no `maxmemory` or eviction policy, so unbounded growth is possible with orderbook cache keys.
- Severity: Medium (local), High on a shared VPS. Confidence: Medium.

### INF-08 Single shared Postgres credential for all services
- Where: `x-db-env` anchor (docker-compose.local.yml:23-28) used by migrator, scanner, worker-alerts, worker-maintenance.
- Evidence: every service uses the owner user created by the postgres image (`POSTGRES_USER`). Scanner holds DDL-capable rights. Contradicts CLAUDE.md "each container loads only its own settings subset" in spirit; planned in todo.md:339 (Stage 2.2), not done. Postgres port is published on 127.0.0.1:5432 (compose:129-130), acceptable but reachable by any local process/WSL user.
- Severity: Medium. Confidence: High.

### INF-09 Exchange API keys injected into the scanner container (V1)
- Where: docker-compose.local.yml:53-69 (all 7 exchanges' key/secret/passphrase).
- Evidence: intended (read-only keys), mitigated by `install_read_only_guard` (src/nexus/adapters/cex/ccxt_base.py:76-102, blocks non-GET) and `tests/unit/test_safety.py`. Residual: the guard patches `client.fetch` on instances; any code path bypassing `fetch` is not covered; the ccxt.pro WebSocket client is built with `authenticated=False` (ccxt_base.py:523), so it carries no keys. Nothing verifies at startup that a key lacks withdrawal permission (CLAUDE.md rule 2 is only required for trading mode, but the guard is the sole V1 defense).
- Severity: Low (V1). Confidence: Medium.

### INF-10 Dockerfile: unpinned base, no image HEALTHCHECK, no vuln scanning
- Where: `Dockerfile:3-6, 21`.
- Evidence: `python:3.12-slim` floats (not digest-pinned); uv image is pinned `0.9.8` (good). No `HEALTHCHECK` in the image (health defined only in compose, so `docker run` has none). `CMD ["nexus","--help"]` default. No build-time SBOM/scan. Positives: multi-stage, `--frozen` lockfile, non-root uid 10001, cache mounts, no dev deps, `.dockerignore` excludes `.env`, tests, docs.
- Severity: Low. Confidence: High.

### INF-11 Dockerfile copies migrations twice and README into builder
- Where: `Dockerfile:16, 22-27`.
- Evidence: `COPY README.md` needed only for the hatch build; migrations come both inside the installed package (non-editable install) and a second copy at `./src/nexus/persistence/migrations` for alembic.ini. Redundant, risk of drift if `alembic.ini` script_location and package path diverge. Not a bug today.
- Severity: Info. Confidence: Medium.

### INF-12 No resource limits in compose
- Where: `x-image` anchor, docker-compose.local.yml:9-21.
- Evidence: no `mem_limit`/`cpus`/`pids_limit`; `restart: unless-stopped` with no backoff cap means a crash-looping scanner restarts forever. A leaking scanner (7 exchanges x loaded markets) can exhaust the laptop/WSL VM. Log rotation is configured (10m x 5) - good.
- Severity: Low-Medium. Confidence: Medium.

### INF-13 Logging: good structure, no aggregation, scrubbing is regex-based
- Where: `src/nexus/log.py:1-60`; compose `x-log-env`.
- Evidence: structlog with key redaction and regex scrubbing of Telegram tokens, signatures, exchange headers (log.py:20-60). Gaps: regex coverage is heuristic (a secret not matching the patterns, e.g. a raw hex API secret in an exception string without a key name, passes through); logs live only in per-container json-file (rotation 50 MB total), no shipping, so history older than rotation is lost. Celery logs use `--loglevel INFO` with `worker_hijack_root_logger=False` (workers/app.py), hence they go through the same chain only if stdlib handler is configured - not verified at runtime.
- Severity: Low-Medium. Confidence: Medium.

### INF-14 Makefile gaps
- Where: `Makefile`.
- Evidence: no `make backup`, `make restore`, `make psql`, `make build`; `make revision` runs alembic on the host (Makefile:56-58) requiring local env and DB; `test-integration` needs `POSTGRES_*` env set manually (README:92 mentions it; no target wires it to the compose DB). `SRC := src tests` is fine. `logs` with empty `s` follows all services. No `make down-local -v`/`clean`.
- Severity: Low. Confidence: High.

### INF-15 Process: direct push to main, agent-owned release
- Where: CLAUDE.md "Ship"; `.claude/settings.json` allows `git push origin main`; current branch is `chore/agent-pipeline-adoption`.
- Evidence: no branch protection can be verified; no PR review, no required status checks (see INF-01). 38 commits, all by one author.
- Severity: Medium. Confidence: Medium.

### INF-16 Untracked file in working tree
- Where: `nexus-adoption-instructions.md` (untracked per git status).
- Evidence: not in `.gitignore`; risk of accidental `git add .`. Content not reviewed here.
- Severity: Info. Confidence: High.

## What is good (keep)
- `.env` and `.coverage` are git-ignored (verified with `git check-ignore`).
- Compose enforces `POSTGRES_PASSWORD`, `TELEGRAM_*` as required (`:?`), read-only rootfs, `no-new-privileges`, tmpfs `/tmp`, `init: true`, graceful stop 30 s for scanner.
- `tests/unit/test_compose.py` enforces per-service env scoping.
- Beat schedule fixed to use picklable `LocalNow` (workers/app.py:28-36).

## Recommended order
1. GitHub Actions: lint, mypy, unit tests, integration with service containers, gitleaks, `uv`/pip-audit (INF-01).
2. Scheduled `pg_dump` + off-host copy and a restore drill (INF-04).
3. External heartbeat (healthchecks.io-style ping or second Telegram sender) before the multi-day soak (INF-05).
4. Pin base image digest; add resource limits; Redis `requirepass` (INF-07, INF-10, INF-12).
5. Separate DB roles (INF-08) before Stage 2.
