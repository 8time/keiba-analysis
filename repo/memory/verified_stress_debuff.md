---
name: verified_stress_debuff
description: 🐎Stress Analystはリーク無し再検証で小さな馬体重デバフのみ採用。逃げ+13pp/ダ×後方-5.6ppは結果脚質リークで幻
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

🐎 Stress Analyst（🧪テストタブ・乗算デバフ）の検証。scripts/stress_debuff_backtest.py 他。**重大教訓: results.kyakushitsu は『そのレースで実際に見せた脚質＝結果』であり事前情報ではない。** これでバックテストすると in-race リークで巨大な偽エッジが出る。

**リークで否定された偽エッジ（再実装禁止）:**
- 「逃げ+13.2pp/単回収190%」: kyakushitsu=1(実際に逃げ切れた馬)条件のため。**事前habitual位置(過去走平均relを使用)では前型×芝-0.2pp(z=-0.4)/前型×ダ-0.7pp(z=-1.9)＝ほぼ0**。[[verified_legtype_axis]]の「事前脚質は動かさない(前型+0.9pp)」を再確認。**逃げボーナスは撤去**。
- 「ダ×後方-5.6pp」「大型520+×追込-7.7pp」: 同じく結果脚質リーク。事前では 大型520+単独-0.6pp(z=-1.4)/大型×habit後型+0.5pp(非有意)＝消える。撤去。

**リーク無し(事前確定データのみ)で生き残った実デバフ＝採用:**
- 🟧小柄馬(<440kg)×馬体減6kg超: 複勝残差**-2.0pp(z=-3.0)**。馬体重/増減は事前確定でクリーン。係数-0.04。
- 🟨習性後方ぐせ(過去平均rel≧0.65)×芝: **-1.5pp(z=-3.0)**。ダートは非有意。係数-0.03。
- 🟨馬体増+8kg超: **-1.0pp(z=-3.1)**軽微。係数-0.02。

**実装(2026-06-18)**: app.py 🧪テスト。multiplier∈[0.85,1.00]の小さい減点のみ。ボーナス無し。係数<0.92=危険人気候補だが効果±1〜2ppと明記し「軸消しでなく相手の優先度下げ」用途に。脚質はAvgPosition(習性)を代理。

**重要(2026-06-18追加)**: 🐎Analystとは別に、📊強適 Ranking Tableの`Stress`列が旧条件A/B/C/Dの**独立コピー**で残っており、しかも`Projected Score`(final_score=raw_potential-weighted_loss・app.py~3635)に効いていた=メイン予測が否定済み俗説で歪んでいた。ユーザー承認で🧪と同一の検証版(小柄×馬体減-0.04/芝×後方ぐせ-0.03/馬体増-0.02、floor0.85)に同期済み。両者は別コードなので片方修正時はもう片方も要同期。

**How to apply**: デバフ/エッジ条件を足す前に必ず『その変数が事前に入手可能か』を確認。corner/kyakushitsu/今回通過順は結果でリーク源。事前=馬体重/増減/枠/距離/馬場/習性(過去走平均)/前走情報のみ。[[feedback_folk_signals_overbet]][[verified_legtype_axis]]。
