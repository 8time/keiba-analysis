# Projected Score historical parity audit (2026-09-22)

## Verdict

**NOT_REPRODUCIBLE** for the live SRA score used by `cross_n` and `elim_engine`.

Phase B parity stays **PARTIAL**. STOP CONDITION A: no improvement experiments, no HOLDOUT metrics.

## Live canonical path

1. `calculator.calculate_battle_score(df)` — Ogura from `PastRuns` (rank, grade, date) plus agari/position bonuses.
2. `calculator.calculate_n_index(df)`
3. `calculator.calculate_strength_suitability(df, course_profile)` — writes a column `Projected Score` = BattleScore + (Strength X + Suitability Y) * 0.25. **This column is overwritten.**
4. `app.py` `_calc_pro_scores` (around the SRA block) replaces `Projected Score` with:

   `(BattleScore * weight.Base + sum(normalized bonuses * weights) )` minus stress, then optional TopBattleBonus and safety-net.

5. `score_cache.write_scores` stores that value. `consensus_view.compute_cross_n` and `elim_engine.compute_elim_rows` read `proj` from that cache.

## Current weights (`.score_weights_main.json`)

Non-zero:

| key | weight | input |
|-----|--------|--------|
| Base | 1.0 | BattleScore |
| Popularity | 1.5 | race popularity (pre-race) |
| ScoringSignal | 1.0 | same-day JRA scan marks |
| JPowerTop3 | 0.1 | `jockey_jv.jockey_power` top 3 in the race |

All other weights including Suitability, Stress, CorrectedT, Spurt, Lap33, Bloodline are 0 in the saved file. Dropping ScoringSignal would **not** match live.

## Input classification

| Input | Class | Notes |
|-------|--------|--------|
| Popularity / win odds / weight / post | AVAILABLE_PRE_RACE | In export or JV |
| BattleScore / PastRuns (rank, grade, agari, date, surface) | NOT_AVAILABLE_PRE_RACE as the live object | Export has rolling stats, not the scraper `PastRuns` list the function iterates |
| ScoringSignal / daily scan | NOT_AVAILABLE_PRE_RACE | `app.py` states forward ledger only; no 2016–2024 scan archive |
| JPower | UNCERTAIN for batch parity | Function supports `before_key`, but the SRA call does not pass it. Historical replay is not the live call |
| TimeIndex / Labo / Training | NOT_AVAILABLE_PRE_RACE | Weights are 0 today, so they do not move the score **if** weights stay frozen. They are still part of the function |
| chakujun / payout of the target race | Not an input to `_calc_pro_scores` | Must stay out of any future batch |

## Snapshots

`data/score_cache` has 506 plain score JSON files (proj + battle per umaban). Year prefixes:

- 2026: 500 (HOLDOUT window — not read for metrics)
- 2024: 3
- 2012: 1
- TRAIN 2016–2023: 0

Three validation races cannot certify a 22k-race baseline. Example shape (`202405020601.json`): `{umaban: {proj, battle}}` only, not the inputs that produced them. Rank parity vs a rebuilt score was not computed.

## What was not done

- No proxy (`ability_score`, odds rank, h7).
- No historical Projected Score cache.
- No `cross_n` distribution (would be all 0 without proj, which is the known partial baseline).
- No elim cache v2.
- No EXP-01..10.
- HOLDOUT rows were not scored.

## To reach FULL later

Need, per horse and race, stored **before post time**:

1. The same `PastRuns` records `calculate_ogura_index` / `calculate_battle_score` consume, or a bit-exact dump of BattleScore.
2. Archived ScoringSignal maps for every race (or a frozen decision that live weight ScoringSignal is 0 — that is a **strategy change**, not a reconstruction).
3. Frozen `.score_weights_main.json` version id.
4. JPower computed with an explicit as-of race key, then compared to a live snapshot sample.
