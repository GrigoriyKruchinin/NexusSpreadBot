# STATE (updated 2026-10-24)

## Where we are
- **Stage S1-tool planned** (b018cdb; cards `docs/tasks/tool/`, T0..T14). User answers 2026-10-25: T2 squash migrations into
  one initial schema; alerts `[alert] language = en|ru` (default en, user ru); retire quant-analyst, risk-manager,
  creative-ceo, observability-engineer (T12); T9 drop human KEY_POLICY attestations for third parties, optional
  KEY_POLICY_STRICT; LICENSE after T13 lawyer input. Started: T0 (architect), T13 (lawyer), T1a (backend-lead).
- **2026-10-25 after NO-GO (user answers):** stack STOPPED (`docker compose stop`). User OK to delete ALL data: backups
  (~/nexus-backups, C:\nexus-backups), old + soak1 volumes. Agent deletion was denied by permission settings -> commands
  given to the user to run himself. HT1 code removal: backend-lead running. Product direction: tool that posts spreads on
  venues (with and without keys) with key data to a Telegram channel and writes to the DB (as now). Next: project-manager
  cards for the reshaped scope after user confirms details (paper portfolios removal, channel, alert fields).
- **UF 2026-10-25: NO-GO (user decision).** Report `docs/reports/go-no-go.md`. Project = analytical spread-finder only.
  HT1 frozen after S12 (disabled). DB wipe planned for HT deploy is NOT done (no HT deploy). Open user questions: what the
  analytical tool must deliver; keep/stop old spot paper runs; keep/remove HT1 code; DB wipe; merge branch to `main`.
- **2026-10-25 hedge-method comparison** (`docs/quant/hedge-method-comparison.md`, 40 episodes): PERP okx+kucoin passes 0 after
  basis check (sell venue B falls back ~1.1 % during transfer); MARGIN short on B locks the spread but okx/kucoin lend 0 of
  the alerted coins, only binance (7/40, +$47.6) and gate; UNHEDGED -$848 on 40. No method passes in the GO set today.
  HT1 S13 ON HOLD pending user answer: margin on binance and/or gate (needs legal + G1.1a) or NO-GO -> analytical tool.
- **User OK 2026-10-25 (U4): wipe all old DB data**, start HT from zero. Orchestrator plan: do it at HT deploy (S15) in
  one go via a fresh DB volume per `docs/guides/soak-fresh-stack.md` (no `down -v`), so the old spot paper code does not
  write new data in between; quick archive dump first as a safety net.
- **User decision 2026-10-25 (tax): GO/HT verdict is judged PRE-TAX** (supersedes "2 %/month after 35 % tax" for HT);
  after-tax shown as reference only. Bonferroni: PRELIMINARY-GO uses the 2.5th-percentile lower bound (option b).
- **User decision 2026-10-25 (option a): finish HT and test it on paper.** Test length MAX ~1 week (not 3), with gaps
  (PC sometimes off); verdict by extrapolation from active hours. Quant to define a short-window, gap-aware preliminary
  verdict (params pre-registered before deploy => whole week is out-of-sample; label confidence honestly). HT1 progress:
  S0-S3 committed (a7ba759..1b29e02); S4 binance adapter partial, uncommitted in the worktree.
- **User decision 2026-10-25 (later): HT is THE strategy; current spot-inventory soak data is not needed.** Old paper
  sets need not be kept or resumed (AC5 golden-hash coexistence no longer required; tell architect/backend-lead). Project is
  reshaped around HT; GO candidate = HT with hedge on okx+kucoin (binance separate until G1.1a). If HT is not viable ->
  project stays an analytical spread-finder tool. Orchestrator plan: keep stack running (scanner alert data still useful) until
  HT is ready; then at deploy: archive dump, fresh DB, start HT only (each data step needs explicit U4 OK).
- **User decision 2026-10-25: NEW STRATEGY "hedged transfer"** (no coin inventory, no directional exposure): buy spot on A +
  short perp, transfer A->B, sell on B + close short. Entry only after pre-checks: perp exists and can be opened (depth,
  funding), withdraw A / deposit B open on a common network, spot depth on B, net profit > threshold. Running:
  quant-analyst spec (`docs/quant/hedged-transfer-spec.md`, card HT1) and lawyer (`docs/legal/futures-access.md`).
  Then backend-lead implements as paper only (ADR 0001). Existing soak keeps running.
- **2026-10-25 12:50Z preview (go_report, read-only):** soak gap from a full disk (user fixed; 894G free); 13 of 33 h
  without a sweep; stack up again ~12:40Z. All 4 sets: hedged P&L (realized - rebalance) +58..+72 USD in 1.4 d, but MTM on
  coin inventory -471..-669 USD -> total -405..-597 USD. Loss = price drop of held small-cap inventory (T, ORDER, ANIME), not
  the spread trades. Sample far too short; paper fill realism unverified. User asked about hedging (short perp) - candidate
  task for quant-analyst (paper hedge-cost model: funding, perp fees, margin), no real trading (ADR 0001).
- **User decision 2026-10-24 ~15:45Z: WAIT MODE.** No more work on reboot auto-recovery for now. User keeps the PC on and
  restarts containers himself (or asks the orchestrator: `docker compose start`, no recreate) if they are down. Gaps in
  soak data are acceptable; analysis uses whatever data exists. D-01 re-check and the auto-recovery guide steps are
  OPTIONAL (not blocking). User returns in ~1 week (~2026-10-31) to request the soak analysis.
  On return: check `docker ps`, count gaps (downtime) in scanner data, D-08 digests, then soak analysis (B15 GO report,
  4 venue sets). Retention fix (paper snapshots thinned to 1/day, not deleted) is deployed in all app containers.
- Trajectory M. Branch `chore/agent-pipeline-adoption` (pushed; CI with 7 jobs, green on the last recorded run).
  Not merged to `main` (only with user consent).
- Quality ratchet: 1041 unit tests, branch coverage 91.5 %, ruff 0, mypy --strict 0 (floor 89 %).
- Fresh stack UP since 2026-10-24 13:32Z on volumes `nexus-local_*-soak1` (old volumes kept; archive dump
  `nexus-archive-20261024T132431Z` in ~/nexus-backups/archive + C:). Migrations at head b15a7c3e91d2, roles bootstrapped.
  SOAK RUNNING since 2026-10-24 14:05Z (scanner healthy, 4 paper runs started). Keys: binance/okx/kucoin pass
  with IP-binding waiver (KP-W); bybit and gateio public mode (gateio key rejected with auth error twice; user
  commented it out; Gate support question stays in go-gates-checklist). D-03 first dump + restore drill PASSED
  14:06Z. Pending: D-01 live restart check (restart Docker/WSL once), first digest check (D-08), 24 h checkpoint.

## D-01 live restart check 2026-10-24: FAILED (auto-recovery) -> fix D-01b deployed, re-check pending
- User ran `wsl --shutdown` ~15:09Z; Docker Desktop reconnected. postgres/redis came back; scanner, beat, worker-alerts,
  worker-maintenance Exited (127) at start with no app log output. Hypothesis (unconfirmed; `docker inspect` is denied):
  bind mount `./config/nexus.toml` from the Ubuntu distro was not available when Docker Desktop restarted them.
- 15:11Z orchestrator ran `docker compose start` (no recreate): all healthy, migrator exit 0, key policy pass, 4x
  `paper_resumed` (same runs, no reset). Soak data gap ~15:08:32Z-15:11:50Z (~3.5 min). No Telegram alert (workers down too).
- D-01b (devops, 2026-10-24): root cause confirmed from Docker Desktop logs (WSL bind mount not ready when the engine restarts
  containers). Fix committed: config baked into image, no bind mounts except backup-status, `scripts/host_watchdog.sh` (cron,
  `docker compose start` + Telegram + optional external heartbeat). NOT deployed (needs rebuild + recreate of all app containers,
  user OK). Handoff `docs/handoffs/D01b-auto-recovery.md`, user guide `docs/guides/soak-auto-recovery.md`.
- Risk for the soak: a Windows reboot/update leaves the stack down SILENTLY. Fix needed (devops): e.g. bake config into
  the image or start the stack from WSL boot, plus an external dead-man alert.
- D-01b (devops): config baked into image, bind mount removed, backup-status bind long syntax create_host_path=false,
  host watchdog `scripts/host_watchdog.sh` (cron, compose start + Telegram dead-man). Security ACCEPT (24f491a), tech-lead r2
  ACCEPT (05cc8c4; deploy-list fixes D-1/D-2 applied by orchestrator at deploy). CI green on 05cc8c4.
- DEPLOYED 2026-10-24 15:35Z (user OK): `make up-local`, all 5 app services recreated healthy, postgres/redis untouched,
  paper run ids 1-4 resumed (no new runs), key policy pass, 0 errors. Soak gap ~15:35-15:37Z.
- NEXT: user does guide `docs/guides/soak-auto-recovery.md` steps (Docker Desktop autostart, Task Scheduler keeps Ubuntu up,
  crontab watchdog line), then re-run D-01 (`wsl --shutdown`, wait 3-5 min, `ps -a`). Follow-up: handoff deploy list still
  has D-1/D-2 text to correct; Makefile `up-local` does `mkdir -p ~/nexus-backup-status` (conflicts with D-2 intent).
- User decision 2026-10-24: external heartbeat (whole PC off) DEFERRED to the server; rely on the morning digest.

## Stage S0 (pre-soak gates) closed
- Accepted: B15 part 1 (TL r3), A7 (security r1, TL r2), S0 (TL r2 `343df63`, security r2 `1fb8d60`), tester regression,
  D-08 per-set watchdog (`fba9dd4` + r1 fixes `4d1a990`; tech-lead r2 ACCEPT, `docs/audit/tech-lead-review-D08.md`).
- Delta audit 02: `docs/audit/delta-02-S0.md`. Hygiene: `docs/audit/hygiene-S0.md` (applied `0e7175b`).
- Open check: D-01 live restart check (security S-8) on the first Docker/WSL restart of the soak.

## Next (in order) - resume here
1. (done) D-08 accepted. Stage summary given to the user in chat 2026-10-24.
2. Fresh stack per `docs/guides/soak-fresh-stack.md`: each data step (archive dump, new empty DB volume, migrations
   from zero, stack up) needs explicit U4 OK from the user. No `down -v`; the old volume stays until the soak is verified.
3. First-day checks: D-03 (manual dump + restore drill on `nexus_test`), D-10 (migrator exit 0, `alembic current` = head),
   D-01 (scanner back `Up` after a restart), D-08 (all 4 sets in the first digest; a 100 % idle set is reported).
4. 24 h soak checkpoint (card B15): union/cap p95 > 1.3, sweep duration +25 %, any 429 ban -> NEEDS_USER.
5. B15 part 2 ACCEPTED by tech-lead r2 (10925ab; quant r1 point 1 verified by TL). Fixes d571f8b, 756dba7, b9aa8ba, 8534fa6,
   73a9a5f; CI green on 73a9a5f incl. integration. Follow-ups before UF: card section "Part 2 follow-ups (before UF)".
   Retention fix safe to deploy (TL r2). NOTE: retention runs in `worker-maintenance` (celery task nexus.maintenance.purge),
   NOT in the scanner; scanner code unchanged since soak start -> deploy = rebuild image + recreate worker-maintenance only.
   DEPLOYED 2026-10-24 14:55Z (user OK: worker-maintenance only): image rebuilt at 4d9bfe5, worker-maintenance recreated,
   healthy, task nexus.maintenance.purge registered; scanner NOT restarted (no soak data gap). D-01 stays open until a real
   Docker/WSL restart. Other containers (beat, worker-alerts, scanner) still run the pre-change image; behaviour identical.
   Original item: B15 part 2 GO report generator (`docs/quant/b15-review-and-report-spec.md`, incl. F2 fee
   disclosure). Quant pre-soak condition C1 (strategy params in run hash) is DONE in 8ffb9c3 (tech-lead B15 r3).
6. Then: B16 public probe, A5b Redis auth, A5c DB roles, A6/A7 follow-ups, A5d at VPS.
7. Stage summary to the user for S0 (`docs/reports/stage-S0-summary.md`) if not yet written.

## User decisions (2026-10-23)
- 2026-10-24: rebuild + restart the scanner with retention fix d81811b BEFORE 2026-10-31 14:05Z (day 8 of soak, old 7-day
  retention would delete paper snapshots), only AFTER tech-lead accepts d81811b. The restart doubles as the D-01 live check.
- 2026-10-24: IP whitelist on exchange keys NOT required for the local soak (keys read-only, no withdrawals). Mandatory again
  on server/VPS (A5d) and before any trading permission. Implemented as explicit env-only waiver flag (task KP-W).
- Soak runs on this PC (WSL; Windows sleep disabled). Off-machine dump copy: `C:\nexus-backups` (outside OneDrive).
- Soak on a FRESH stack + clean `nexus` DB; old data/logs/backups are obsolete; old volume removed only after the soak is verified, with user OK.
- Soak runs 4 venue sets: all, excl_conditional, excl_bybit, excl_gateio (`[paper] venue_sets` in `config/nexus.toml`); $10,000 fixed each.
- Settings in committed `config/nexus.toml`; `.env` = secrets only (A7).
- GO bar: 2 %/month **after** income tax; GO judged on 35 % (15 % shown too; accountant to confirm).
- B15 concentration rule (strict): >= 2 %/month after tax without the top-2 routes AND without the top-2 coins.
- Bybit and gateio: GO numbers with and without; judged without them if not resolved by UF.
- GO-HOLD = analytical GO but gates unmet -> keep developing without money (DEX allowed). Real legal penalties -> NO-GO/stop.
- Integration tests run only in CI. Push of the working branch is allowed.
- Proxy per exchange: backlog idea; lawyer ToS check first; design with the user when a server is chosen.
- Expand venues (up to ~20): public-data probe first; user registers only where worth it.

## User facts / open items for the user
- RF citizen (passport), resident in Argentina, DNI pending. Keys for binance/gateio/kucoin/okx are in `.env`
  (never read it). Bybit: 1.6 ETH transfer frozen, compliance ticket ~1.5 months. Binance account opened as RF resident:
  change residence on the existing account, do NOT open a second one. Gate ToS 2.5 lists Argentina and Russia as
  restricted (user to ask Gate support in writing).
- User actions list: `docs/legal/go-gates-checklist.md`.
- Branch protection on `main`: user configuring (checks: lint, typecheck, unit, integration, secret-scan,
  dependency-audit, docker-build; 0 required approvals).
- `uv run pre-commit install` once (gitleaks hook). KEY_POLICY_* attestation flags default false.
- LICENSE decision. Optional: CLAUDE.md quality ratchet text (481 / 89 %) to be updated by the user (user-owned file).

## Lessons
- INCIDENT 2026-10-23: `docker compose config` expanded `.env` and printed live keys into a transcript. User rotated all 4
  keys. Fix: deny rules, CLAUDE.md rule 4. Agent prompts must list implicit `.env` readers explicitly.
- Devops tried a write probe on live `nexus` despite a ban (blocked). For live-DB tasks: give exact commands and review them.
- Earlier integration run truncated live `nexus` (R-01). Integration tests now refuse anything but `nexus_test`.
- Concurrent agents + pre-commit: commit may fail with "files were modified"; just retry.
- Session can die mid-run: after restart check `git status` for partial agent output before relaunching.
