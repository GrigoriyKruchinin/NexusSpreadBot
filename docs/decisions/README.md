# Decisions (ADR index)

| # | Title | Status |
|---|---|---|
| 0001 | [No withdrawal/transfer in code](0001-no-withdrawal-in-code.md) | accepted (revised by 0010) |
| 0002 | [bitget/mexc adapters: extension only](0002-bitget-mexc-extension-only.md) | accepted |
| 0003 | [Modular-monolith scanner; Celery kept](0003-modular-monolith-scanner-keep-celery.md) | accepted |
| 0004 | [Source plug-in contract, DEX seam on paper](0004-source-plugin-contract.md) | accepted |
| 0005 | [Clock domains](0005-clock-domains.md) | accepted |
| 0006 | [U2: DEX seam only; risk-manager added](0006-u2-dex-seam-only-risk-manager.md) | accepted (amended by 0008, 0010) |
| 0007 | [Up to 5 iterations to find a profitable spread approach](0007-iteration-loop-find-profitable-approach.md) | superseded by 0010 |
| 0008 | [GO-HOLD state; DEX development allowed during HOLD](0008-go-hold-dex-during-hold.md) | superseded by 0010 |
| 0009 | [Public perp market-data port; hedged paper strategy as a PaperBook sibling](0009-perp-market-data-and-hedged-paper-strategy.md) | superseded by 0010 (never accepted) |
| 0010 | [Self-hosted spread-alert tool (after NO-GO)](0010-self-hosted-alert-tool.md) | accepted |

ADRs live here (`docs/decisions/`), not in `docs/adr/`.
Format for new ADRs (MADR-lite): Status/Date, Context, Decision drivers, Considered options,
Decision, Consequences (good/bad), Confirmation (how compliance is checked). Changing an accepted
ADR = a new ADR that supersedes it, or a dated "Revised" line for clarifications.
