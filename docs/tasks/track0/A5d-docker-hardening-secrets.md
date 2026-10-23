# A5d — Docker hardening and secrets files (S-09, S-10)

- id: A5d (migration-plan §A)
- stage: Track 0 (base)
- owner: devops
- reviewers: security
- complexity: medium (many compose edits, risk of startup regressions)
- depends_on: A5b, A5c (secret-file conventions and roles); required before any VPS / shared-host soak, NOT for local Stage 1
- status: todo (deferred until a VPS or shared host is planned)
- Note: changes the Docker stack; ask before `make up-local` restarts.

## Goal
Make the container stack safe to run off the local machine: secrets via files, minimal
privileges, resource limits, pinned and scanned images.

## Context docs
`docs/architecture/target.md` §10.5, `docs/audit/security-review-architecture.md` (S-09, S-10),
`docs/audit/06-security-baseline.md` (§3).

## Acceptance criteria
1. Compose secrets (`*_FILE`) used for DB passwords, Redis password, Telegram token, exchange keys,
   heartbeat URL; no secret in `environment:` and none visible in `docker inspect` of app containers
   (checked by script, values never printed).
2. App services: `cap_drop: [ALL]`, `security_opt: no-new-privileges:true`, `read_only` root fs where
   feasible, `mem_limit`, `pids_limit`; postgres/redis: `no-new-privileges`, log size limits.
3. Postgres port not published in the VPS/prod compose profile (local profile may keep `127.0.0.1`).
4. Base images pinned by digest; image scan (Trivy or grype) added to CI, fails on High/Critical
   with a documented allowlist.
5. Stack starts healthy under the new constraints (local smoke after user OK); `make check` and CI green.
6. Russian guide `docs/guides/` note on creating secret files (U3 style, user enters values).

## Out of scope
VPS provisioning, TLS/reverse proxy, per-service DB/Redis users (separate trigger), CD, Stage 2 executor isolation.

## Files likely touched
`docker-compose*.yml`, `Dockerfile`, `.github/workflows/ci.yml`, `src/nexus/config.py`
(`*_FILE` support check), `docs/guides/secrets-files.md`, `todo.md`.

## Risks
`read_only`/`cap_drop` can break ccxt or Celery temp-file usage; apply incrementally per service.
Digest pins need a refresh routine (note in card at close).

## Follow-ups from A5a review (carried)
- S-A5a-5(c): `HEARTBEAT_URL` as a plain env var is acceptable for local Stage 1 only; on the VPS use
  `HEARTBEAT_URL_FILE` (0600, owner-checked by `backup.sh`) or a Docker secret.
- S-A5a-6: on the VPS no published Postgres port (target.md §10.5); re-verify that `nexus_ro` cannot log in over TCP.
- Heartbeat service is deferred here by user decision 2026-10-23; the daily cron entry also moves to the VPS host.
