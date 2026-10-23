# 14 - Git History

Evidence: `evidence/git-log.txt` (full log), `evidence/hot-files.txt` (top 40 files by touches).

## Activity
- 38 commits on HEAD, 2026-10-18 to 2026-10-23 (6 days): 19 on 10-18, 12 on 10-19, 7 on 10-23; none on 10-20..22. 0 merge commits.
- Authors: GrigoriyKruchinin 37 (gkruchinin75@gmail.com), Grigorii Kruchinin (GitHub noreply) 1 - likely the same person (the initial commit), not verified.
- Remote: `origin git@github.com:GrigoriyKruchinin/NexusSpreadBot.git`.

## Branches / tags
- Local: `main`, `chore/agent-pipeline-adoption` (current). Remote: `origin/main`. Whether the current branch is pushed: not verified.
- Tag `pre-agents-baseline` -> 589a291 (2026-10-23, "docs(guides): add free hosting guide and sync message names") - lightweight, no message.
- Working tree: only `nexus-adoption-instructions.md` and `docs/audit/` untracked.

## Conventions
Conventional Commits, scoped, English: feat 20, docs 11, fix 3, build 2, chore 1, plus "Initial commit". Matches CLAUDE.md. One commit per todo item with todo.md tick (todo.md is the most-touched file, 27 times). Linear history on a single branch; commits go directly to main (per CLAUDE.md /ship), no PR/merge evidence.

## Big changes (lines changed, insertions+deletions)
| Lines | Commit |
|---|---|
| 2895 | e8680d3 feat(transfer): public Binance status fallback, stricter network matching |
| 2765 | 865113a feat(adapters): read-only ccxt adapters for 5 CEXes |
| 2115 | 0ca3891 feat(scanner): orchestrator, Celery workers, Redis coordination |
| 1733 | e0f1b3f feat(simulation): paper inventory, trades, virtual rebalancing |
| 1645 | 05881c6 build: uv skeleton and quality tooling |
| 1421 | 6785d1f feat(engine): depth-aware net spread estimator |

(Fixture and lock files probably inflate some counts.)

## Hot files (touches)
todo.md 27; docs/guides/stage-1-local-setup.md 16; scanner/service.py 12; tests/unit/scanner/test_scanner.py 12; config/groups.py 12; .env.example 12; docker-compose.local.yml 10; container.py 9. Churn in `scanner/service.py` and `config/groups.py` marks them as central/complex.

## Risks
- Very young, single-author repo; bus factor 1.
- Commits land straight on main without review; the risk-critic gate is process-only (not verified as enforced).
- Adapters for bitget/mexc exist though CLAUDE.md lists five V1 exchanges - check whether scope drift is intentional.
- No secrets scan of history performed (not verified); `.env` is git-ignored and absent from `git ls-files`.
