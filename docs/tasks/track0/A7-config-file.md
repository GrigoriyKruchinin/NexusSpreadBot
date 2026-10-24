# A7 — Non-secret settings move to a committed config file

- id: A7
- stage: Track 0 (do after B15 part 1 is accepted, before the soak)
- owner: backend-lead; security pre-check of the secret/setting split
- reviewers: security (split + startup guard), tech-lead (diff)
- complexity: medium
- depends_on: B15 part 1 accepted (it touches the same config modules and `.env.example`)
- status: todo

## Goal
User decision 2026-10-23: `.env` keeps only secrets (exchange keys, Telegram, DB/Redis credentials).
Every other tunable lives in a committed, reviewable file `config/nexus.toml`, so each run's settings are
versioned (needed for GO report reproducibility) and agents can read/edit settings without touching secrets.

## Scope
1. Security first classifies every variable in `.env.example` as secret / setting (table in
   `docs/audit/security-config-split-A7.md`). Connection strings carrying passwords stay secret; host/port/db
   name may be settings.
2. Load `config/nexus.toml` via pydantic-settings `TomlConfigSettingsSource`. Priority: env var > TOML >
   code default (env override keeps CI/docker-compose working). Path overridable by `NEXUS_CONFIG_FILE`.
3. Startup guard, fail closed: a secret-classified field found in the TOML file -> refuse to start, naming
   the key (never its value).
4. Move settings into `config/nexus.toml` with comments; shrink `.env.example` to secrets; update
   `docker-compose.local.yml`, `docs/guides/stage-1-local-setup.md` (Russian), CI.
5. Run settings snapshot: log/persist a hash of the effective non-secret config at startup (GO report links to it).

## Acceptance criteria
- Tests: TOML load, env overrides TOML, defaults, missing file behaviour (documented), secret-in-TOML refusal,
  unknown key handling (fail closed).
- Behaviour unchanged with current local stack; `make check` not worse than baseline; no secrets in diff;
  `.env` never read by agents. Card and `todo.md` updated.

## Out of scope
Secret managers/vaults (Stage 2 VPS), changing any default values.
