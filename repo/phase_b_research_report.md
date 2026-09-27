# Phase B research report — STOP A

Date: 2026-09-22

## 1. Baseline parity

**PARTIAL** (unchanged). Not FULL.

| Piece | Status |
|-------|--------|
| LTR | Rebuilt via `research/csv_ltr.py` + `ltr_model.lgb` |
| VH | CSV `vh2_score` |
| zone / bettype / playbook tickets | Production `formation_stats`, `bettype_selector`, `playbook_tickets` |
| Projected Score | **NOT_REPRODUCIBLE** — see `repo/phase_b_projected_score_audit.md` |
| cross_n | Production `consensus_view.compute_cross_n`, but proj missing so live path sets 0 |
| elim_keep | `elim_engine` without proj (`A_partial`) |
| C playbook | All C races stay `c_ltr_trifecta_247` until proj exists |

`research_baseline_partial` (100 yen/point, no Kelly), from Step 1, is **not** the production baseline:

- TRAIN ROI 81.8% (22,599 bets / 22,681 D+C races), max DD ¥6,588,430
- VALIDATION ROI 72.2% (2,897 bets / 2,915 races), max DD ¥1,106,240

## 2. Leak audit

Target-race finish, payout, and future races are not inputs to `_calc_pro_scores`.
They also must not be used to invent Projected Score.
ScoringSignal and scraper `PastRuns` are absent historically, so a batch was **not** implemented (no imputed features).

## 3–4. TRAIN / VALIDATION production baseline

Not remeasured. FULL parity was not reached.

## 5–12. Experiments

**Not run** (STOP A). Experiment count: 0. No EXP definitions were rewritten. HOLDOUT was not evaluated.

## 13. Next HOLDOUT candidates

**None.** Do not send a candidate to HOLDOUT until Projected Score parity is FULL.

## Required data before retry

1. Historical BattleScore or scraper-equivalent `PastRuns` for each starter, as-of race day.
2. Historical ScoringSignal maps, or an explicit product decision that live weight `ScoringSignal` is not part of the frozen baseline (that would be a strategy definition change, not a silent proxy).
3. Frozen weight file version.
4. A sample of saved live `score_cache` rows to check rank agreement.
