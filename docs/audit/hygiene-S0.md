# Repo hygiene — stage S0 (B15 part 1, A7, S0)

- Date: 2026-10-24. Author: analyzer (list only). Applies: scribe (+ orchestrator for agent/skill files and
  for `git rm`/commit, see H-1). Skill: `.claude/skills/repo-hygiene/SKILL.md`.
- Basis: `docs/audit/delta-02-S0.md` §5, `docs/pipeline/STATE.md`, HEAD `b835c59`, grep of paths/facts.
- Scope: `CLAUDE.md`, `.claude/agents/*` (16), `.claude/skills/*` (57), `.claude/settings.json`, `docs/**` (107),
  `todo.md`, plus `README.md` (requested by orchestrator). 184 files.
- **Counts: KEEP 148 · UPDATE 29 · DELETE 7 · NEW 1** (soak guide).
- Concurrency: backend-lead is editing `src/`, `tests/`, `config/nexus.toml`, the S0 card and the `todo.md`
  D-08 line (uncommitted at the time of this list). Scribe applies S0-card and `todo.md` edits **after**
  backend-lead commits, and does not touch the D-08 line.

## H-1. Blocking process finding (fix first)

| Item | Problem | Fix |
|---|---|---|
| `.claude/agents/scribe.md` vs skill `repo-hygiene` | Skill says scribe applies DELETE via `git rm` and commits `chore(docs): stage <X> hygiene`, but scribe has `tools: Read, Write, Edit, Glob, Grep` (no Bash): it cannot `git rm` or commit. | Either orchestrator runs `git rm` + commit after scribe edits (recommended, no tool widening), or add `Bash` to scribe. Reword the skill "Who" line to match. |

## 1. Root files

| File | Verdict | What is wrong -> corrected fact |
|---|---|---|
| `CLAUDE.md` | KEEP | Ratchet already 1009 / 91.4 %. Optional (user-owned): add `make backup`, `make backup-archive`, `make restore-drill`, `make check-env-settings` to "Commands" with "(ask first, U4)" for the first three. |
| `todo.md` | UPDATE | (a) M2 "R-02 Isolate exchange failures ..." unchecked -> tick: "done in S0b (`110fb91` + r2 `cb1c1af`, `gather_isolated`); per-route counters remain in B3". (b) M2 "Split `scanner/service.py` (1048 lines); review 25 `except Exception`" -> "1169 lines; 20 `except Exception` in it, 35 in `src/` (2026-10-24)". (c) M3 "Multi-day keyed soak" line: drop "Pre-soak gates ... D-01 `on-failure:5` + no alert ..., D-02 ..., R-02" (closed in S0) -> "Remaining before/at soak start: fresh stack (U4 each data step), D-03 restore drill on the first dump of the new DB, D-10 migrator exit 0 + `alembic current` = head, D-01 live restart check (security S-8), D-08 per-set freshness (own line)". Also "depends on B15" -> "B15 part 1 done; part 2 report runs in parallel". (d) M2 R-03 cites `docs/reports/math-review.md`, which never existed in git -> drop the reference or point to the future quant formula review (`docs/quant/formula-review.md`, M3 quant item). (e) B15 line "config `PAPER_VENUE_SETS`, default `all` + `excl_conditional`" -> "`[paper] venue_sets` in `config/nexus.toml` (env `PAPER_VENUE_SETS` overrides); soak runs 4 sets: all, excl_conditional, excl_bybit, excl_gateio". Do NOT touch the D-08 line (backend-lead). |
| `README.md` | UPDATE | `README.md:107-140`: (a) add one bullet "Shadow paper portfolios per venue set (`[paper] venue_sets`, fixed capital each; GO numbers per set)"; (b) one bullet "Liveness watchdog (maintenance worker): Telegram alert on stale scanner data, missing/failed/uncopied backup"; (c) dev/ops commands: `make backup`, `make backup-archive`, `make restore-drill`, `make check-env-settings` (link `docs/guides/backups.md`); (d) line 136 `make test-integration   # repositories against PostgreSQL (POSTGRES_* env)` -> "... only against the `nexus_test` DB (refuses otherwise); normally runs in CI". |

## 2. `.claude/`

| File | Verdict | What is wrong -> corrected fact |
|---|---|---|
| `.claude/settings.json` | KEEP (review only) | Deny list covers the 2026-10-23 incident variants. No loosening proposed. Optional tightening for the user to decide (user-owned config, agents may not change it): deny `Bash(docker compose down -v:*)` (only the `-f docker-compose.local.yml` form is denied now), `Bash(docker volume rm:*)`, `Bash(git push origin HEAD:main:*)`; put `make backup*`/`make restore-drill` under `ask` explicitly (today they fall to the default prompt). |
| `.claude/agents/orchestrator.md` | UPDATE | "You do NOT" line is the generic subagent text: "never call other agents ... never talk to the user directly ... return NEEDS_USER" — contradicts its role (it calls agents and talks to the user). Replace with: "Does NOT write product code or design the product; never edits `.env`/settings without the user." Add skill `close-stage` (stage-end workflow uses it; today only project-manager lists it) and `repo-hygiene`. |
| `.claude/agents/scribe.md` | UPDATE | See H-1. Also add skill `repo-hygiene`; description mentions CHANGELOG, which does not exist (see `update-changelog`). |
| `.claude/agents/analyzer.md` | UPDATE | Add skill `repo-hygiene` (analyzer writes the list; no agent lists the skill today). |
| other 13 agents | KEEP | Roster matches CLAUDE.md (16). Future output dirs (`docs/risk/`, `docs/crypto/`, `docs/quant/*`) are fine as targets. |
| skill `delta-audit` | UPDATE | Writes `docs/reports/delta-<stage>.md`; real practice and links use `docs/audit/delta-<stage>.md` (`delta-track0-B14.md`, `delta-02-S0.md`). Also add "diff vs the previous delta and the CLAUDE.md ratchet", not only 05/06. |
| skill `security-audit` | UPDATE | "Done when: docs/reports/security-*.md" -> `docs/audit/security-review-<task>.md` (all 7 reviews live there). |
| skill `write-adr` | UPDATE | Path `docs/adr/NNNN-slug.md` does not exist -> `docs/decisions/NNNN-slug.md`, MADR-lite per `docs/decisions/README.md`; it duplicates `log-decision` — keep both only if write-adr = MADR-lite for architect and log-decision = short record. |
| skill `repo-hygiene` | UPDATE | "Who" line vs scribe tools (H-1). Add: "reviews/audits referencing deleted handoffs are not edited; history is in git". |
| skill `update-changelog` | UPDATE | No `CHANGELOG*` in the repo; never produced. Orchestrator decides: create `CHANGELOG.md` at the next stage close, or drop the skill from scribe and say "history lives in git" (also in repo-hygiene "STATE.md" rule). Recommendation: drop. |
| other 52 skills | KEEP | All referenced by at least one agent. Future outputs (`docs/reports/stage-<n>-summary.md`, `docs/ops/ops-log.md`, `docs/crypto/dex-cost-model.md`) are targets, not drift. |

## 3. `docs/`

### 3.1 Handoffs — all accepted -> DELETE (results live in cards, reviews, commits)

| File | Verdict | Why / what replaces it |
|---|---|---|
| `docs/handoffs/A7-to-review.md` | DELETE | A7 accepted (security r1, TL r2; `c6e35b8`). Replaced by card A7 + `tech-lead-review-A7.md`, `security-review-A7.md`. |
| `docs/handoffs/B15-part1-to-review.md` | DELETE | Part 1 accepted (TL r3 + F1/F3). Still-useful facts already elsewhere: Soak checkpoint (card B15:89-94), F2 (card B15:97), run-hash/recycle details (`tech-lead-review-B15.md`, quant spec). Before deleting, scribe adds one line to card B15 "Part 1 commits: f9ac581, c61b060, 2854904, 8ffb9c3 (+F1/F3)". |
| `docs/handoffs/S0a-to-review.md` | DELETE | S0 accepted (TL r2 `343df63`, security r2 `1fb8d60`). Also stale: says `restart: on-failure`; code is `unless-stopped` + park on exit 3. |
| `docs/handoffs/S0b-to-review.md` | DELETE | Same; replaced by card S0 + `tech-lead-review-S0.md` + `security-review-S0.md`. |
| `docs/handoffs/architect-to-project-manager-2026-10-23.md` | DELETE | Cards were cut (B1..B16, A-track); plan lives in `docs/architecture/migration-plan.md`. |
| `docs/handoffs/architect-to-project-manager-2026-10-23-adr-accept.md` | DELETE | ADR 0003-0005 accepted; ADR index records it. |

Links to deleted handoffs: fix only in living docs — card A7 (line 9), card B15 (line 9), `docs/quant/b15-review-and-report-spec.md:4,216` (-> commit hashes above). Do NOT edit reviews (`tech-lead-review-{A7,B15,S0}.md`, `security-review-A7.md`); their links resolve via git history.

### 3.2 Task cards (never delete; statuses)

| File | Verdict | Corrected fact (line 9 unless noted) |
|---|---|---|
| `docs/tasks/m3/S0-pre-soak-gates.md` | UPDATE | `status: todo` -> `done (S0a 3bb5746 + r2 2c528c6, 8b1e81d; S0b up to 21897bf + r2 cb1c1af; TL r2 ACCEPT 343df63, security r2 ACCEPT 1fb8d60). Open: D-01 live restart check (S-8), D-08 follow-up`. Apply after backend-lead commits (concurrent edit). |
| `docs/tasks/track0/A7-config-file.md` | UPDATE | `review (implemented; see docs/handoffs/A7-to-review.md)` -> `done (security r1, tech-lead r2 ACCEPT; c6e35b8). Follow-ups: todo A7 line`. |
| `docs/tasks/track0/A6-key-policy-startup-check.md` | UPDATE | `review ... awaiting re-review` -> `done (6766bfd + ee38592; TL r2 + security ACCEPT). Follow-ups F-1..F-5 in todo`. Line 17 `docs/adr/0001*` -> `docs/decisions/0001-no-withdrawal-in-code.md`. |
| `docs/tasks/m2/B14-conditional-venues-reporting.md` | UPDATE | `review (round 2 fixes applied, not committed). 656 unit tests` -> `done (5ba4f07 + e23024d; TL r2 ACCEPT)`. |
| `docs/tasks/m2/B1-core-exchanges-default.md` | UPDATE | `done (uncommitted, awaiting tech-lead review)` -> `done (2862593; accepted)`. |
| `docs/tasks/m2/B15-shadow-paper-portfolios.md` | UPDATE | Line 9 handoff link -> commit list (see 3.1); keep "part 2 pending". Venue-set default text (if any) -> 4 sets in TOML. |
| `docs/tasks/track0/A4-log-scrub-tests.md` | UPDATE | "todo R-07 tick pending orchestrator" -> drop (R-07 is ticked). |
| A2, A2a, A5a, A5b, A5c, A5d, B1a, B16 cards | KEEP | Statuses match todo (A5a "Open: re-run drill" = D-03, still true; A2 branch protection pending user, still true). |

### 3.3 Pipeline

| File | Verdict | What is wrong -> corrected fact |
|---|---|---|
| `docs/pipeline/STATE.md` | UPDATE | Says "Unit tests 999, 91.3 %" -> 1009 / 91.4 %. Item "Next 1" (stage end) about to be done. 70 lines; skill `update-state` limit ~60. Trimmed outline in §5. |
| `docs/pipeline/context-plan.md` | UPDATE | Lists `docs/adr/` (does not exist) -> `docs/decisions/`; add `docs/audit/` (reviews, deltas). |
| `docs/pipeline/task-format.md` | UPDATE | Filename `docs/tasks/<stage>/<NNN>-<slug>.md` -> real pattern `docs/tasks/<stage>/<ID>-<slug>.md` (e.g. `m3/S0-pre-soak-gates.md`); status list fine. |
| `docs/pipeline/team-proposal.md` | DELETE | One-off U1 proposal ("13 agents"); U1 done, real roster (16) lives in CLAUDE.md + `.claude/agents/`; no references. History in git (`0f596e3`). |
| `docs/pipeline/intake.md`, `nexus-appendix.md` | KEEP | Source documents (intake answers, GO criteria P6/P7 cited by todo). |

### 3.4 Guides (Russian, user-facing)

| File | Verdict | What is wrong -> corrected fact |
|---|---|---|
| `docs/guides/stage-1-local-setup.md` | UPDATE | (a) Table line 366 `PAPER_VENUE_SETS` value `all;excl_conditional` -> TOML `[paper] venue_sets = "all;excl_conditional;excl_bybit=-bybit;excl_gateio=-gateio"` (4 sets). (b) Lines 273, 485 "уберите ... из `EXCHANGES_ENABLED`" -> "из `[exchanges] enabled` в `config/nexus.toml`". (c) Digest section (445-460): add per-set paper lines, "all vs без условных бирж" totals (B14), per-set downtime/coverage line (S0b), "Набор X перезапущен" line; drop "см. `todo.md`, 1.5.10" (no such item; -> "решение GO/NO-GO по отчёту B15 part 2"). (d) Add short "Сторож (watchdog)" subsection: which Telegram alerts exist (scanner silent, backup missing/failed/not copied, recovery) and that silence of the whole PC is NOT alerted (D-09) -> link soak guide. (e) Section 6 "Ноутбук уснул": link `backups.md` soak section. |
| `docs/guides/backups.md` | UPDATE | Line ~86 "(после этапа S0b) придёт оповещение" -> S0b done: "придёт оповещение в Telegram". Heartbeat status (~line 77) "пропущенный бэкап вы заметите только по журналу" -> stale: watchdog alerts if `last_backup.json` is missing, `ok=false`, `copied=false` or older than 26 h; external heartbeat still deferred (whole-PC outage stays silent). |
| `docs/guides/free-hosting.md` | UPDATE | Line 147 `EXCHANGES_ENABLED` -> `[exchanges] enabled` in `config/nexus.toml`; "Код и секреты": copy `.env` (secrets only) + note `config/nexus.toml` comes with git. |
| `docs/guides/ci-branch-protection.md`, `gate-0-how-to-continue.md` | KEEP | Still accurate (`scripts/run-pipeline.sh` exists). |
| **NEW** `docs/guides/soak-fresh-stack.md` | NEW (scribe) | See §4. |

### 3.5 Architecture, audit, quant, other

| File | Verdict | What is wrong -> corrected fact |
|---|---|---|
| `docs/architecture/target.md` | UPDATE (low) | Line 80 "`Scanner` (1048 lines ...)" -> "1169 lines as of 2026-10-24"; line 173-174 add "`[exchanges] enabled` in `config/nexus.toml` (A7)". |
| `docs/architecture/migration-plan.md` | UPDATE (low) | Line 5 baseline "481 tests, 89 %" -> "the CLAUDE.md quality ratchet (currently 1009, 91.4 %)". |
| `docs/audit/04-build-run-test.md` | UPDATE | Line 15 records running `docker compose ... config`. Add note: "Since 2026-10-23 this command is denied (it expands `.env`; key-leak incident, CLAUDE.md rule 4). Do not re-run; compose is checked by YAML parsing (`tests/unit/test_compose.py`)." Keep the evidence file. |
| `docs/audit/12-tech-debt-register.md` | UPDATE | No status column. Add "Status 2026-10-24" section (like 13): TD-01 closed (CI 7 jobs), TD-02 reduced (A5a + S0a copy/status/watchdog), TD-05 1169 lines, TD-07 35 in `src/` (20 in service.py), TD-15 partly (unless-stopped + park on exit 3; no resource limits), TD-18 closed (CI integration on `nexus_test`), TD-21 gitleaks done (A2a), TD-26 file gone. |
| `docs/audit/00-03, 05-11, 13-16` | KEEP | Dated baseline snapshot; 13 already has the status section (delta-02). |
| reviews/deltas: `architect-review-B15`, `delta-02-S0`, `delta-track0-B14`, `security-config-split-A7`, `security-review-{A5a,A6,A7,B14,S0,architecture}`, `tech-lead-review-{A5a,A7,B14,B15,S0,track0}`, `tester-regression-S0` | KEEP | Back GO/NO-GO or stage acceptance; never delete. |
| `docs/audit/evidence/*` (16) | KEEP | Evidence for audits (incl. empty `compose-config-stderr.txt`, cited by 04:15). |
| `docs/conventions.md` | UPDATE | "Config: pydantic-settings, each container loads only its own subset; `.env.example` in sync" -> "settings in committed `config/nexus.toml` (env overrides, startup guard rejects secrets/unknown keys); `.env` / `.env.example` hold only secrets + ENV-ONLY (A7)". |
| `docs/quant/b15-review-and-report-spec.md` | UPDATE | Lines 4, 216 handoff link -> commits; lines 96, 110 `PAPER_VENUE_SETS=...` -> add "`[paper] venue_sets` in `config/nexus.toml`". No content change. |
| `docs/quant/b14-conditional-totals-review.md`, `docs/decisions/*` (9), `docs/legal/*` (3), `docs/reports/*` (4), `docs/product/*` (2), `docs/assets/nexus-logo.jpg` | KEEP | ADR 0003 "1048-line" is dated context, ADRs are not edited. |

## 4. Soak guide check

Result: **missing.** `docs/guides/backups.md` has "Тест на неделю (soak): чтобы Windows не уснул" and
"Перезапуски сканера", but there is no Russian guide for the fresh-stack steps, the first checks, the daily
routine, or the rule "no daily digest = outage" (D-09). -> **NEW `docs/guides/soak-fresh-stack.md`** (scribe;
Russian, plain words; commands are run by the agent team with the user's OK, the user only confirms/observes).
Required content:
1. Что это и зачем: 7-14 дней работы на чистой базе, 4 набора бирж, цифры для GO.
2. Перед стартом (уже сделано 2026-10-24): ключи заменены, `make check-env-settings` пусто, сон Windows выключен (ссылка на `backups.md`).
3. Шаги свежего стека, каждый с вашим OK (U4): архивный дамп старой базы (`make backup-archive`, не удаляется) ->
   новый пустой том БД (старый том НЕ удаляем, никакого `down -v`) -> миграции с нуля (migrator завершился с кодом 0,
   версия = head, D-10) -> `make up-local`, все сервисы healthy, сообщение о старте в Telegram.
4. Первые проверки: ручной `make backup` + `make restore-drill` (D-03); `last_backup.json`: `ok=true`, `copied=true`;
   копия в `C:\nexus-backups` (+ необязательный `icacls`); проверка перезапуска Docker/WSL один раз (сканер сам `Up`,
   максимум одно оповещение о простое и одно о восстановлении; D-01/S-8).
5. Первый дайджест: все 4 набора видны; набор с простоем 100 % = выключенный набор -> сообщить (D-08).
6. Каждый день: дайджест в 09:00 (Europe/Moscow, `[digest]` в `config/nexus.toml`). **Нет дайджеста к ~09:30 = авария**
   (сторож работает на том же ПК и при падении ПК/WSL/всего стека молчит; D-09): проверить, включён ли ПК, `make ps-local`, написать «статус».
7. Какие оповещения сторожа бывают и что делать (сканер молчит; бэкап нет/упал/не скопирован; восстановление).
8. Контрольная точка 24 ч (карточка B15): union/cap p95 > 1.3, длительность прохода +25 %, бан по лимиту запросов -> вопрос пользователю.
9. Чего не делать: `docker compose down -v`, `wsl --shutdown`, интеграционные тесты на рабочей базе, правка `.env` с настройками.
10. После подтверждённого soak: удаление старого тома только с вашего OK.

## 5. STATE.md trimmed outline (target <= 60 lines)

1. **Where we are** (4 lines): trajectory M; branch + CI green; ratchet 1009 / 91.4 % / ruff 0 / mypy 0; stack stopped on purpose.
2. **Stage S0 closed** (3 lines): B15 part 1, A7, S0 accepted; stage end done (regression, delta-02, hygiene-S0); link `docs/audit/delta-02-S0.md`. Drop per-commit detail (lives in cards/git).
3. **Next (in order)** (8 lines): D-08 follow-up (backend-lead, in progress) -> fresh stack per `docs/guides/soak-fresh-stack.md` (U4 each data step) -> first-day checks (D-03, D-10, D-01, D-08) -> 24 h checkpoint -> B15 part 2 in parallel -> B16, A5b/A5c, A6/A7 follow-ups.
4. **User decisions** (keep, compress to one line each; drop ones fully implemented: "Digest/Telegram conditional list (done in B14)", "4 venue sets" -> merge into one "soak setup" line).
5. **User facts / open items** (keep as is; drop "user steps before fresh stack: DONE").
6. **Lessons** (keep incident + live-DB lesson + concurrent commit + session restart; 1-2 lines each).
Remove: "Done 2026-10-23" block (history in git/cards), item "Stage end for S0 can run now", item 2 "User steps ... DONE".
