---
name: project-consensus-view
description: 強適シートに検証済みエッジの合議ビューを追加。_aim計算をcore/consensus_viewへ抽出しtrio/trifectaと共有。荒れレジーム別に本命/相手/穴/消しへ再編
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
  modified: 2026-08-12T10:22:31.988Z
---

ユーザー要望(2026-07-05)「📊強適シート(Strength×Suitability)を全然さわってなかった。全機能で連携
できるものを全て連携させてレース結果に近づけて」。強適シートは散布図＋消し/穴提案だけで、この
セッションで検証・配線した🟣6シグナル/軸候補/消去/荒れ予報と完全分離していた。

**設計判断**: 検証済みエッジの全馬セット(旧`_aim`インライン145行)は買い目エンジン(6587行)で構築され
強適シート(6392行)より後。しかも強適シートが読める`view_df`はユーザーの列選択で絞られ空にもなる=
信頼不可。→ `_aim`計算を**core/consensus_view.build_edge_sets()に抽出**し、①強適シート直前で呼び
キャッシュ ②既存6587行のインラインも同関数呼び出しに置換(DRY・145行削除)。同一session_stateキー
`_aimsets2_{rid}`を共有。

**consensus_view.integrate(rows, aim, regime)**: 荒れ予報レジーム(trio_lean)別に独立エッジを合議:
- 軸候補◎〇▲(オッズ別実複勝率=最直接の3着内根拠)＋市場エッジ(黄金ライン/厩舎当コース/道悪軸)
- 荒れ予報6シグナルは**人気薄(6+)限定**でvalue票に算入(holdout検証はその母集団=[[verified_arare_signal_check]])
- 🧩combo2+ボーナス(z+9.2>単独最強)、危険veto=fade減点
- 役割グルーピング(優先順位方式): 危険→本命(統合最上位)→穴(人気薄×検証シグナルは順位に関わらず拾う)
  →相手(残り上位3)→残り。荒れで過小評価の勝ち馬を穴グループから落とさない設計([[feedback_catch_underrated_winners]])

**正直な枠**: 合議一致は複勝率を単調UP(scripts/consensus_backtest.py: votes=3で複27% vs ベース9.4%・
ROI最大96%)だが**フラット単勝で黒字化せず=市場を出し抜く予測器ではない**。UIに明記「本命の信頼度＋
相手/穴の絞り込みの道具」。[[project_magi_consensus]]の検証知見(独立エッジの合議は本物)を強適シートへ再配線。

**実査検証(202608020211・大荒れ18頭1200m・1着16人気フィオライア)**: レジームを正しく②穴妙味と判定、
実際の3着内全馬(14フィオライア16人気/17レイピア6人気/6ヤマニンアルリフラ9人気)が🎯穴グループに入った=
「過小評価の勝ち馬を落とさない」は達成。ただし**1200mは⚡33ラップが全馬適合で穴グループが11頭に膨張**
(既知の弱点=33ラップは短距離で識別力低・holdout z+2.6と6シグナル中最弱)。16人気をピンポイントで
本命化は大荒れゆえ不能(ユーザーも承知)。combo3で絞ると6頭(勝ち馬含む)。

**R×V クロス列追加(2026-08-12)**: integrate()にrank_pos(LTR降順)とvh_pos(vh2_score降順)を計算。
両方≤5なら🔵(cross_rv)。app.pyの強適テーブルにR/V/R×V列を表示。
VH×人気はρ=0.94だがtop-5内ではρ=0.16=独立した再順位付け情報([[verified-cross-table-structure]])。

**smoke**: consensus_view.integrate(荒れレジーム穴拾い)追加・CORE import一覧にconsensus_view追加。426/426緑。

**How to apply**: 33ラップの短距離希釈は検証済みの既知特性のため触らない(verify-first)。合議の重み付けを
signal強度(z値)比例にする案は未検証=やるならbacktestしてから。展開系はpriced-in([[verified_tenkai_priced_in]])
なので合議に足さない。
