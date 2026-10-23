# Security review — target architecture and migration plan

Date: 2026-10-23. Author: security (critic, read-only). Status: for orchestrator / architect.
Reviewed: `docs/architecture/target.md`, `docs/architecture/migration-plan.md`,
`docs/product/vision.md`, ADR 0001-0007, `docs/audit/06`, `07`, `13` (R-05, R-06, R-07, R-09).
Spot-checked (read-only, no values printed): `docker-compose.local.yml`, `src/nexus/log.py`,
`src/nexus/workers/app.py`, `.pre-commit-config.yaml`. `.env` was not read.

## Verdict: ACCEPT WITH CHANGES

The topology is sound from a security view: secrets are split per container (Telegram token only
in `worker-alerts`, exchange keys only in `scanner`), ADR 0001 is reinforced by a GET-only
runtime guard, Stage 2 executor is a separate boundary. No blocker in the design itself.
Gaps are in what the architecture leaves *unspecified* (DB grants, Redis auth details, CI scan
scope, backup handling, U3 key model). Required changes below are additions to `target.md` /
`migration-plan.md`, not redesign.

## Answer: are 3 DB roles acceptable for Stage 1?

**Yes, with conditions.** For Stage 1 (paper data, public/read-only exchange access, single
local host) a per-service split adds little: the realistic threats are operator mistakes and
test runs (R-01), not lateral movement between our own containers. The 3-role cut is acceptable
**only if** the following hold; otherwise it is a High finding.

Minimum role set for Stage 1 (required):

| Role | Rights | Used by |
|---|---|---|
| bootstrap superuser (`POSTGRES_USER`) | everything | **only** postgres init / manual admin; never in any app service env |
| `nexus_migrator` | owner of schema `public` objects, DDL | `migrator` container only |
| `nexus_app` | `SELECT, INSERT, UPDATE, DELETE` on app tables, `USAGE` on sequences; **no** `TRUNCATE`, no DDL, no `CREATE` on schema, not owner, `NOSUPERUSER NOCREATEDB NOCREATEROLE` | scanner, worker-alerts, worker-maintenance |
| `nexus_ro` | `SELECT` only (+ `default privileges` for future tables) | analytics, dashboards, `pg_dump` backups |
| test role (e.g. `nexus_test_owner`) | owner of DB `nexus_test` only; `CONNECT` on `nexus` **revoked** | integration tests only |

The test role is the important addition: the R-01 guard checks the DB *name*; a separate role
without `CONNECT` on `nexus` makes a wipe of live data impossible even if the guard is bypassed
(defence in depth, same logic as ADR 0001). Plus `statement_timeout` / `lock_timeout` set per role
(`ALTER ROLE ... SET`) as the server-side half of B5.

Per-service split (`nexus_scanner`, `nexus_alerts`, `nexus_maint`) becomes **required** before any
of: VPS / non-local host, Stage 2 executor, or any role holding money-touching credentials.
Record this trigger in `target.md` §4.

## Findings

| # | Sev | Area | Finding | Required change |
|---|---|---|---|---|
| S-01 | High | DB roles | §4 lists 3 roles but no grants. Today all services use the image owner/superuser (INF-08); "nexus_app (DML)" without explicit "no TRUNCATE / not owner / no DDL" can be implemented as owner and change nothing. | Add the grant table above to `target.md` §4; A5 acceptance: test/SQL check that `nexus_app` cannot `TRUNCATE`/`DROP`/`CREATE`, superuser absent from app env. Migrations create grants + `ALTER DEFAULT PRIVILEGES`. |
| S-02 | High | Test isolation (R-01) | Name guard only; same server, same superuser credential reachable by tests. | Add dedicated test role without `CONNECT` on `nexus` (A1 follow-up, or part of A5). CI uses its own ephemeral Postgres service. |
| S-03 | High | Backups (R-09) | Plan says "pg_dump backups" only. Unspecified: credentials, storage location, encryption, retention, restore test. A dump is a full copy of the data and lives outside the DB's access control. | A5 must specify: dumps run as `nexus_ro` (or dedicated `nexus_backup`, SELECT only) with password via `.pgpass`/`_FILE` (never CLI arg); stored outside repo and outside the compose volume (`.gitignore` + `.dockerignore` entry for the backup dir); file mode 0600; retention (e.g. 7 daily + 4 weekly); if copied off-host -> encrypted (`age`/`gpg`); **restore drill into `nexus_test`** as acceptance; B7 (migration) waits for one verified restore, not just a dump. |
| S-04 | Medium | Redis auth | "auth on, R-09" without details. Pitfalls: password in `redis-cli -a` healthcheck shows in `ps`/`docker inspect`; password in `REDIS_URL`/broker URL appears in logs; scrubber has no `scheme://user:pass@` pattern (checked `log.py`). | Specify: `requirepass` (or ACL with one user for app, default user disabled) loaded from a file/secret; healthcheck uses `REDISCLI_AUTH` env; add URL-credential scrub pattern (`://[^:/@\s]*:[^@\s]+@` -> `://***@`) with unit test; `maxmemory` + eviction policy `noeviction` for db1 broker safety (INF-07); Redis stays unpublished. Per-service ACL users: not required in Stage 1, required at the same trigger as S-01. |
| S-05 | Medium | Celery | Celery is the trust boundary between scanner and Telegram (anyone who can write to Redis db1 can make the bot send messages). Serializer not pinned explicitly (default json in Celery 5). | Pin `task_serializer="json"`, `accept_content=["json"]`, `result_accept_content=["json"]` in `workers/app.py` (never pickle); validate payload incl. new `v` field (B12) and reject unknown versions with a log, not crash. HTML-escape stays mandatory in templates. |
| S-06 | Medium | CI secret scan (R-05) | A2 says "secret scan" without tool, scope or fail policy; pre-commit has only `detect-private-key` (does not catch API keys/Telegram tokens). | A2 acceptance: gitleaks (pinned version/action SHA) on full history on first run, then per-push; job fails on findings; allowlist for the synthetic test tokens by path+rule (not global regex); same hook in pre-commit. Also `pip-audit` on runtime **and** dev groups (A3), fail on known vulns. CI: `permissions: contents: read` default, third-party actions pinned by SHA, no repo secrets needed for Stage 1 (integration uses throwaway service creds defined in the workflow), no `pull_request_target`. |
| S-07 | Medium | Logging (R-07) | Code already sets `httpx/httpcore/ccxt` to >= WARNING and routes stdlib through the scrubber, but nothing proves it. Scrubber is regex-based (INF-13): raw secrets without a key name pass. | A4 acceptance changes from "silence httpx" to tests: (a) httpx INFO with `/bot<token>/` URL is not emitted / is scrubbed; (b) Celery task-received log does not print payload args containing secrets (no secrets should ever be in payloads - state that in §4 Celery row); (c) DSN/URL credential scrubbing (S-04). Add a rule to §5 contract: never log full exception `repr` of ccxt auth errors without `scrub`. |
| S-08 | Medium | Key model (U3) | Architecture says "exchange read-only keys" but does not define the permission model or how it is verified. | Add a short §"Key policy" to `target.md`: Stage 1 = one key per core venue, **read-only** scope only (no trade, no withdraw, no transfer/sub-account, no universal-transfer), IP whitelist to the host egress IP where the venue supports it, separate from any personal/trading key, rotated on suspicion and at Stage 2 start; passphrase venues (okx, kucoin) treat passphrase as a secret. Keys enter only via `.env`/Docker secrets, entered by the user from a `docs/guides/` file (U3), never through agents/chat. Startup check (where the venue exposes it, e.g. binance `apiRestrictions`): **refuse to start** if withdrawal or trading permission is detected. Keep GET-only guard + add unit test that the guard is installed on every authenticated client (06 §7). bitget/mexc key vars removed from scanner env while disabled (06 §8.5, aligns with B1). |
| S-09 | Medium | Secrets delivery | Secrets are plain env vars, visible in `docker inspect` (06 §3). `file_secret_settings` already supported. | Not required for local Stage 1. Make Docker/Compose secrets (`*_FILE`) **required** before VPS / soak on a shared host; note it in A5 or a new A6. |
| S-10 | Low | Docker hardening | App services good; infra images lack hardening; tags not digest-pinned; no resource limits. | Add to A5 (or devops card): `cap_drop: [ALL]` on app services; `no-new-privileges` + log limits on postgres/redis; `mem_limit`/`pids_limit`; digest pins + Trivy/grype image scan in CI before VPS. Postgres `127.0.0.1` publish is acceptable locally; must be removed on VPS. |
| S-11 | Low | Scanner lease / heartbeat (C10) | Redis keys are unauthenticated state; any Redis client can fake heartbeat or hold the lease. | Acceptable once S-04 is done (single trust domain). Lease value = random token, release/renew only if value matches (compare-and-set via Lua), so a stale instance cannot delete another's lease. |
| S-12 | Low | External heartbeat (R-09) | "External heartbeat" service unnamed; it receives a URL that is itself a secret (a ping URL). | Treat ping URL as a secret (`SecretStr`, scrubbed); free service only (user approval for any paid one). |
| S-13 | Low | Stage 2 boundary | §7 fine. | Add one line: executor gets its own DB role, own Redis ACL user, own trade-only key with IP whitelist; scanner never receives trade-capable keys. Security audit is a gate before Stage 2 code (already implied by vision §7). |
| S-14 | Info | Dependencies (R-06) | certifi / protobuf fixes are in A3. | A3 acceptance: protobuf pin bumped with documented reason; pip-audit 0 findings on runtime+dev. Any new dev dep (e.g. `import-linter` in C8) passes pip-audit; prefer AST test if equal. |

## Required edits (summary for architect / project-manager)

1. `target.md` §4: grant table and per-service-split trigger (S-01, S-02, S-13).
2. `target.md`: new short "Security model" section — key policy (S-08), Redis auth details (S-04),
   Celery json-only + payload validation (S-05), secrets delivery trigger (S-09).
3. `migration-plan.md` A2: gitleaks + pip-audit + CI hardening acceptance (S-06).
4. `migration-plan.md` A4: test-based acceptance incl. URL-credential scrubbing (S-07).
5. `migration-plan.md` A5: split into A5a backups (with restore drill, S-03), A5b Redis auth
   (S-04), A5c DB roles + test role (S-01/S-02), A5d Docker hardening (S-10). B7 depends on A5a
   restore drill.
6. B1 card: drop bitget/mexc key env from scanner while disabled (S-08).

## Out of scope / not verified
No code was run; no gitleaks/pip-audit run in this review (see `06-security-baseline.md`).
Exchange-specific permission-introspection endpoints need crypto-specialist confirmation per venue.

## Re-check 2026-10-23

Re-read: `target.md` §4, §7, §10; `migration-plan.md` (A5a-A5d, findings mapping);
`docs/reports/exchange-key-permissions.md`; `.github/workflows/ci.yml`, `.gitleaks.toml`.
Spot-checked: `.pre-commit-config.yaml`, `docker-compose.local.yml` (key names only, no values),
`pyproject.toml` pins. `.env` not read. Status is about the design/plan (code lands in the steps).

| # | Status | Evidence / gap |
|---|---|---|
| S-01 | addressed | Grant table §10.1; A5c acceptance (no TRUNCATE/DROP/CREATE, superuser absent from app env). |
| S-02 | addressed | `nexus_test_owner` without `CONNECT` on `nexus` (§10.1, A5c); CI uses ephemeral Postgres, DB-name assert + pytest guard. |
| S-03 | addressed | A5a: `nexus_ro`, `.pgpass`/`_FILE`, dir outside repo/volume, 0600, retention, off-host encryption, restore drill into `nexus_test`; B7/B8 depend on it. |
| S-04 | addressed | §10.2 + A5b (file secret, `REDISCLI_AUTH`, URL scrub + test, `noeviction`, unpublished). |
| S-05 | addressed | §10.3 + B12 acceptance (pickle not accepted, unknown `v` rejected). Not yet in code (`workers/app.py` has no serializer pin) - expected, B12 pending. |
| S-06 | partial | CI good: gitleaks pinned version+SHA256, full history each run, `--redact`, fails on finding; allowlist scoped rule+path+value; `permissions: contents: read`; actions SHA-pinned; `persist-credentials: false`; no repo secrets; no `pull_request_target`; pip-audit runtime+dev. **Gap G1:** no gitleaks hook in `.pre-commit-config.yaml` (only `detect-private-key`). **Gap G2:** A2 row text still says only "secret scan" (mapping line covers it; cosmetic). |
| S-07 | partial | Mapping line puts test-based acceptance on A4, and §10.4 has the ccxt-`repr` rule, but **G3:** A4 row itself still reads "silence httpx INFO, scrub tokens"; the A4 task card must carry the three tests (httpx `/bot<token>/`, Celery args, DSN/URL creds). |
| S-08 | partial | §10.4 key policy matches; crypto report gives per-venue checks. **G4:** no migration step owns the `KeyPolicyCheck` startup check + "GET-only guard on every authenticated client" test (mapped only to "U3 guide + B1"); §10.4 lacks the report's fail-closed rule (unparseable/missing field -> refuse), "log booleans only, never the response body", missing-IP-binding -> refuse, and the kucoin/gateio attestation fallback. **G5 (open in code):** B1 is done but `docker-compose.local.yml` still passes `MEXC_*`/`BITGET_*` key vars to the scanner; `.env.example` still lists them. |
| S-09 | addressed | §10.5 + A5d: `*_FILE` secrets required before VPS/shared host. |
| S-10 | addressed | §10.5 + A5d (digest pins, image scan, cap_drop, no-new-privileges, mem/pid limits, no published Postgres on VPS). Minor: log-size limits on postgres/redis not named. |
| S-11 | addressed | §10.2 + C10 (random token, compare-and-set renew/release, test). |
| S-12 | partial (minor) | Ping URL as secret in §10.5/A5a; "free service only, paid needs user approval" not stated. |
| S-13 | addressed | §7 last bullet (own DB role, Redis ACL user, trade-only IP-whitelisted key; security audit gates Stage 2). |
| S-14 | partial (minor) | CI pip-audit fails on any finding (runtime+dev). A3 row lacks "documented reason for protobuf pin" and the "new dev deps pass pip-audit" note (C8). |

Required before closing (small, no redesign):
1. G4 - add a step (e.g. A6 "key policy startup check", owner backend-lead + crypto-specialist,
   dep U3) and add fail-closed / booleans-only / IP-refuse / attestation lines to `target.md` §10.4.
2. G5 - remove `MEXC_*`/`BITGET_*` from the scanner env in compose (B1 follow-up card).
3. G1 - add pinned gitleaks pre-commit hook using `.gitleaks.toml`.
4. G3 - A4 task card lists the three scrub tests as acceptance.
Optional: G2, S-10 log limits, S-12 free-only, S-14 A3 wording.

### Verdict: ACCEPT (design), with 4 tracked follow-ups

No blocker remains in the architecture. Stage 1 may proceed; G4 must be done before U3 (first
real keys), G5 before any soak that loads keys, G1/G3 with A4. A first green CI run is still
pending (todo A2) and is not verified here.
