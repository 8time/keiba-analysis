---
name: project-bet-optimizer
description: ④買い方最適化(券種EV比較・配分)。core/bet_optimizer.py新設。EVは未検証モデル確率の目安
metadata: 
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

6段サイクル[[app-rebuild-pipeline]]の④「AI連携による買い方」を実装(2026-06-15)。🧹消去フィルターページの3連複フォーメーション直下に「🎰 買い方最適化（券種EV比較・配分）」追加。

**core/bet_optimizer.py(純粋関数)**:
- 勝率: Projected Score の softmax。calibrate_temp で『モデル本命勝率≈市場本命勝率』に温度自動較正(スケール暴発防止)。
- **blended_win_probs(scores, win_odds, alpha)**: 市場を事前分布にした幾何ブレンド p∝q^(1-α)·m^α。α=0純市場/α=1純モデル。**既定α=0.35(市場寄り)**。外れ馬のEV暴発を抑える肝。
- Harville連系確率: umaren_prob(1-2着)/trio_prob(3頭で表彰台独占)/wide_prob(2頭3着内=Σtrio)/place_prob(1頭3着内)。検算済(勝率Σ=1・複勝Σ=3・3連複全組Σ=1)。
- kelly_fraction=(p·odds-1)/(odds-1)×0.5(ハーフ・cap0.25)、ev=p·odds、enumerate_bets(券種別買い目EV降順)、allocate(kelly/払戻均等/均等＋合成オッズ＋トリガミ＋期待回収)。

**core/scraper.py**: fetch_combo_odds(race_id, kind='umaren'|'wide') 追加(type=4/5・JSONP・既存fetch_sanrenpuku_oddsと同型)。確定済レースはstatus=resultで空返し(UIはオッズ無でスキップ)。

**正直な限界(重要)**:
- EVは**未検証のProjected Scoreモデル確率による目安**。較正+市場ブレンドでも、モデルが人気薄を過大評価するとEVが膨らむ(例:宝塚記念で250倍馬をモデル3位評価→α0.5でEV8)。**人気薄の高EVはモデル過信の可能性大**とUIに明記。
- 実証エッジは✨Scanner側の妙味シグナル([[project-value-scanner]]単複乖離/断層/黄金ライン)にある。④は『信頼する選択に対する券種比較＋配分(合成オッズ/トリガミ/ケリー)の構造づくり』に使うのが安全、とcaption明記。
- 馬連/ワイドのライブ取得は当日(月曜)発売中レースが無く未検証。3連複と同一API/パースなので発売中なら取れる想定。要・実レースで疎通確認。

**🎯当てにいくフィルター(core/bet_filter.py annotate_bets)の精緻化(2026-06-23)**: ユーザー指摘「🎯つきすぎ・当たってない」を受け修正。原因=🎯が`in_band(価格帯)`だけで点いていた(本線帯10-150倍が広く大半が該当)＋app.pyで🎯当て度列と狙い目列の二重表示。価格帯は的中を予測しない([[verified_tansho_roi_efficient]])のが本質。修正: 🎯は『狙い目価格帯 AND 穴脚の検証エッジ(edge_ana)』合致時のみ／価格帯のみ=チップ"価格帯"・エッジのみ="🔵エッジ"に降格／重複"狙い目"列を廃止／列名"🎯当て度"→"🎯妙味度"。根拠も2→拡張: edge=🔵補正T上位/🔥末脚top/🏠厩舎当ｺｰｽ≥20%([[project_trainer_course]])/⭐黄金ライン/🟢道悪軸([[verified_baba_blood]])、danger=🌧️重不良×1番人気([[verified_heavy_track_bias]])/⚠瞬発系道悪(FADE)。annotate_betsにedge_reasons/danger_reasons(任意kwarg・後方互換)を追加し馬ごとの具体ラベルを根拠列へ。_aimは race単位でsession_stateキャッシュ。3連複/馬連/馬単の全表で共通適用。

push未(commit 1ca560cの後)。ユーザーが「push」と言ったら。
