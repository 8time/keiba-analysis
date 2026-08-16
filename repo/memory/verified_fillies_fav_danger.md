---
name: verified-fillies-fav-danger
description: 牝馬限定×1番人気はオッズ統制後も-4.9pp(z-2.94)。axis_confidence -1.0pp + danger_gate配線
metadata: 
  node_type: memory
  type: project
  originSessionId: 72da3c77-2988-4dbb-a040-fdbe604e0282
  modified: 2026-08-11T20:59:39.915Z
---

牝馬限定戦×1番人気は「同じオッズでも複勝率が低い」。

**オッズ統制した残差(20分位):**
- train: -1.1pp (z-1.54)
- holdout: -4.9pp (z-2.94) ★有意

2番人気以下は残差≈0（holdout z+0.19）で無効。1番人気限定の現象。
オッズ帯別では1.5-3.0倍の「普通の1番人気」で-2.0〜-2.6pp。圧倒的本命(1.5倍未満)は影響なし。

arareAターゲット(7番人気以下3着内)は非有意(z+1.75)。「大穴が来る」のではなく
「本命が飛んで2-5番人気が来る」中波乱パターン。

**Why:** trainのzが-1.54と弱いため、保守的に1.0ppの弱い補正として導入。
**How to apply:**
- axis_selector: `FILLIES_DEMERIT = 1.0`（1番人気×オッズ基準のみ適用）
- danger_gate: `fillies_race=True`で1番人気にseverity+1（理由表示用）
- arare_logit: 変更なし（fillies=0.032据え置き。残差z+0.26で適正）
- fav_check: 専用項目は不要（軸候補%に吸収）。danger_gate経由で①に理由表示
- app.py: `meta.get('is_fillies')` → axis_marks/axis_confidence/danger_vetoに配線

検証: scratchpad/axis_fillies_test.py + arare_fillies_residual.py
関連: [[verified_arare_conditions]], [[verified_danger_fav_audit]], [[project_axis_selection]]
