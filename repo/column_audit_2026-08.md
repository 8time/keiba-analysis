# 強適ランキングテーブル 列の棚卸し（2026-08-07）

40件超の検証を経て、**根拠が消えた列**が残っていないかを台帳と突き合わせた。
「何を足すか」ではなく「何を外すか」の棚卸し。列が多いほど画面は読みにくくなる。

## 🔴 撤去候補（検証で明確に否定された）

| 列 | 台帳 | 判定 |
|---|---|---|
| `PCILabel` | [[verified_pci_pricedin]] | **PCI完全終了**。乖離は消去妙味なし(残差-0.5pp)、想定RPCI乖離は逆効果、is_pci_fatal否定、コース形状との交互作用もz0.20で否定、弱因子stackingも否定。n=162,353。**再提案打ち切り**と明記 |
| `AvgPCI` | 同上 | 同上 |
| `PCIType` | 同上 | 同上 |
| `DensityScore` | [[verified_pace_congestion_weak]] | テン混雑→荒れは**実タイムで再挑戦しても超えず決着**(31,849R)。ten_top3_zはholdout z+1.70で2未達・recentで0.64に崩落。**再提案しない**と明記 |
| `DensityPenaltyLabel` | 同上 | 同上 |
| `TrainingEval` | [[verified_training_and_sire_popbucket]] [[verified_jrdb_kyi_fields]] [[verified_jrdb_cyb_training]] | 調教は**時計(4.4万頭)・矢印(96%同一値)・仕上り(CYB)の3方向すべてゼロ**。評価A-Dも根拠なし |

## 🟡 表示のみに格下げ済み（加点はゼロ化されているが列は残る）

| 列 | 台帳 | 現状 |
|---|---|---|
| `DeployScoreLabel` | [[verified_tenkai_priced_in]] | 好位妙味+2.4ppは小標本ノイズ。deploy_bonusは**加点ゼロ化済み**。展開マップ自体は読み物として価値があるので列は残す判断もあり |
| `FrontCollapseEffect` | 同上 | 展開由来。同上 |
| `AvgPosition` / `Pos600m` | [[verified_makuri_priced_in]] [[verified_legtype_axis]] | 位置・脚質は人気に織込み済み。ただし**展開マップの入力**として内部的に必要 |

## 🟢 検証済みで残すべき（根拠あり）

| 列 | 根拠 |
|---|---|
| `CorrectedT` | [[verified_arare_signal_check]] 荒れ予報時に最強(z10.4) |
| `LTR` | recall@7=0.936。ただし人気は超えない([[verified_top5_capture_ceiling]]) |
| `SpurtIdx` | [[verified_spurt_index]] 人気薄×末脚top3。[[verified_spurt_pace_quality]] スロー由来のみ信頼 |
| `Lap33` | [[verified_lap33_theory]] 人気薄で残差+0.9pp・両窓安定 |
| `JPower` | 騎手力。[[verified_weight_top3_bonus]]で唯一の両窓改善(+0.4/+0.6pp) |
| `OddsGap` | [[verified_odds_structure_hunt]] 断層直上・深さ勾配で ratio=2.0 が最強 |
| `Bloodline`/`BloodStats` | [[verified_arare_signal_check]] 荒れ時に有意。[[verified_baba_blood]] 道悪×POWER群 |
| `Stress` | [[verified_stress_debuff]] リーク除去後に残った3項目のみ(小柄×馬体減 等) |
| `AxisMark` | [[project_axis_selection]] [[verified_axis_ng_claims]] [[verified_front_runner_overbet]] |
| `Signal` | [[verified_arare_signal_check]] 🟣combo2+ |
| `EV` | 表示のみ。100倍超は⚠罠表示 |
| `RiskFlags`/`Alert` | [[verified_danger_fav_audit]] で材料を精査済み |

## ⚪ 判定保留（台帳に直接の検証が無い）
`SpeedIndex` / `AvgAgari` / `NIndex` / `Strength(X)` / `Suitability(Y)` /
`ボーナス詳細` / `WeightHistory` / `JockeyChange` / `Trainer`
→ 多くは他列の素材や表示補助。単独の検証は無いが害も無い。

## 撤去による効果の見積り
43列 → 撤去候補6列を外すと **37列**。
PCI系3列とDensity系2列は**スコアに寄与していない上に画面幅を食う**ので、
外して困る場面が想定しにくい。TrainingEvalは「調教はゼロ」が3方向で確定した今、
残すと誤った判断材料になる。
