---
name: verified_legtype_axis
description: 脚質は人気に織り込み済み。事前の習性脚質は軸選定でほぼ無効(後型-2pp)。資料の追込27vs5%は事後の幻影
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

「追い込みは罠・先行馬を軸に(複勝率27.4% vs 11番手以下5.2%)」(Racing Quant p4)の検証。scripts/legtype_axis_backtest.py, test 2021-2025, 軸候補=1〜3番人気。

- **[A] 事後(hindsight)**: 今回の脚質コード別 複勝率 = 逃げ73.3%/先行67.5%/差し40.4%/追込24.8%。4角1-5番手66.3% vs 11番手以下22.6%。→ 資料を強く再現。
- **[B] 事前(pre-race, 過去5走の平均kyakushitsu=習性脚質)**: 1〜3番人気内で 前型(<=2.0)57.7%(+0.9pp) / 中型57.2%(+0.3pp) / 後型(>3.0,追込寄り)54.9%(**-2.0pp**)。ベース56.9%。

**結論**: 資料の「追込避けろ」は **事後の幻影**。4角位置はレース後にしか分からず、人気がその馬の脚質を既に織り込んでいる([[project_trainer_course]]の全体勝率織込みと同型)。レース前に使える習性脚質は軸の複勝率をほぼ動かさない。

**How to apply**: 軸選定で脚質を強いルールにしない。使うなら「習性追込(後型)の人気馬を軸にするとき -2pp 程度の弱い減点」止まり。先行加点は無効(+0.9pp)。[[verified_ohtani_trap]]と同じく『的中率と回収率/人気の混同』に注意。

**マクリ地力指数も人気織込み済(2026-06-17・🧪新ロジックテストFEW+マクリ削除)**: 「前走マクリ(前走 max通過順位−着順≥7=後方から押し上げ)馬は穴の地力あり」を検証→該当n=23,250 複勝率30.4% vs 人気期待30.1% = **残差+0.4pp=ノイズ(priced-in)**。FEW(枠順flat+3/-2・馬体重flat±2/±10)も既知priced-in([[feedback_folk_signals_overbet]])。この採点器はBattleScore(人気を既に重み付け)に加点する設計で穴でなく人気馬を浮かせるだけ。穴狙いは検証済の[[verified_spurt_index]](末脚偏差・人気薄限定)/[[project_value_scanner]](単複乖離)/[[project_elimination_engine]](穴1頭救出・人気薄×+ファクター単勝108.8%)に集約。→ メニュー削除済(app.py nav+ブロック907行)。再実装しない。
