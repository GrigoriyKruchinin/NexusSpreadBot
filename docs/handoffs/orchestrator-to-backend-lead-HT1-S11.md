# Handoff: orchestrator -> backend-lead, HT1 S11+ (2026-10-25)

Read before S11-S15 of `docs/tasks/HT1-hedged-transfer-paper.md`.

1. **Coverage counters (quant spec section 16.2, required by the short-window verdict).** The HT runtime must
   persist, per UTC hour and per HT set: minutes with a complete sweep, and minutes with a fresh perp feed per
   hedge venue. Without them active hours cannot be computed. If S10 is already committed, add them as a
   follow-up additive migration (new table or columns on `paper_hedged_*` only). Wire the writes in S13.
2. **S14 GO report fields:** quant spec section 16.6 (labels PRELIMINARY-GO / PRELIMINARY-NO-GO / INCONCLUSIVE,
   bootstrap bounds, flags `prereg_mismatch`, `day_concentrated`, `hod_bias`, `bonferroni_fail`, `single_regime`).
3. **Pre-registration:** after S11, report the HT run hash per set; the quant writes
   `docs/quant/ht-preregistration.md` with it before deploy.
4. HT-only (user decision 2026-10-25): `[paper]` spot sets switched off at deploy, fresh DB; no golden pins.
