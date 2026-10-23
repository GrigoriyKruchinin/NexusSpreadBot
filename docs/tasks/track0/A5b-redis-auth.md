# A5b — Redis authentication and limits (R-09, S-04)

- id: A5b (migration-plan §A)
- stage: Track 0 (base)
- owner: devops (compose/Redis config) + backend-lead (URL handling, scrub test)
- reviewers: security
- complexity: low (config plus one scrub test; risk is breaking broker connectivity)
- depends_on: A4 (URL-credential scrub pattern and its unit test; A5b only verifies the wiring)
- status: todo
- Note: changes the local Docker stack; ask before `make up-local` / restart (CLAUDE.md "ask first").

## Goal
Redis requires authentication with the secret loaded from a file, healthcheck leaks nothing, and
the broker cannot silently evict data.

## Context docs
`docs/architecture/target.md` §10.2, `docs/audit/security-review-architecture.md` (S-04, S-11),
`docs/audit/07*` (INF-07).

## Acceptance criteria
1. `requirepass` (or one ACL app user, default user disabled) read from a secret file, not inline in
   compose or committed files; `.env.example` documents the variable name only.
2. Healthcheck uses `REDISCLI_AUTH`, not `redis-cli -a`; password absent from `ps` and the
   compose healthcheck definition.
3. `REDIS_URL` / Celery broker URLs carry credentials; scanner, worker-alerts, worker-maintenance
   connect successfully (smoke test on the local stack after user OK).
4. Credential-bearing URLs are scrubbed in logs: unit test exists (shared with A4 criterion 3);
   a startup log line printing the broker URL shows `***`.
5. `maxmemory` set with `maxmemory-policy noeviction`; Redis port is not published to the host
   (verified in compose config).
6. Unauthenticated `PING` is rejected (`NOAUTH`), authenticated `PING` passes; recorded in card.
7. `make check` not worse than baseline.

## Out of scope
Per-service ACL users (required at the VPS/Stage 2 trigger, A5d/target.md §10.1), scanner lease
token (C10), Celery serializer pinning (B12), TLS.

## Files likely touched
`docker-compose.local.yml` (and base compose), `.env.example`, `src/nexus/config.py` (settings for
secret file), `tests/unit/` (config/scrub), `docs/guides/` note for user if a new secret is needed, `todo.md`.

## Risks
Wrong password wiring takes down alerts silently (broker down); keep a rollback note in the card.
