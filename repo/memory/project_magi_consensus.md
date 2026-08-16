---
name: project-magi-consensus
description: MAGIを予測器→合議ゲート(妙味/見送り判定)に転生。core/magi_consensus.py。3機を独立した検証済みエッジに差替
metadata:
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

🧠MAGIシステム転生(2026-06-16)。旧MAGI(core/magi_system.py)が精度ダメだった根因＝**偽アンサンブル**: 3機(MELCHIOR/BALTHASAR/CASPER)が全部同じ BattleScore/Projected Score を見ており相関≒1。同じ数字を3回見て多数決＝BattleScore追認装置。さらに WinProb=score/sum(score) の偽EV、magi_trainer.pyの学習土台が「人気の逆数(95-(人気-1)×5.5)」＝人気を人気で予測、で頭打ち。「勝ち馬TOP3当て」自体が最難でプロジェクト中核(recall@7/過小評価救出)と不一致。→ [[feedback_folk_signals_overbet]]の俗説の罠と同型。

**転生方針**: 予測器をやめ、合議の本来価値=「独立した別視点が一致するか」のメタ信号にする。新ヒューリスティクスは作らず3機を**互いに独立した検証済みエッジ**に差替: MELCHIOR=強適消去スコア上位(実力で残る・[[project_elimination_engine]]) / BALTHASAR=単複乖離(検証2.5→7%)・オッズ断層・黄金ライン・厩舎当コース([[project_value_scanner]]) / CASPER=🔥末脚救出([[verified_spurt_index]])・展開好位妙味(検証+2.4pp・[[project_pace_map_rebuild]])。

**実装(core/magi_consensus.py)**: `evaluate_consensus(rows, vs, jj, jyo,surface,dist,month,min_year, place_map, pace_pos, date_val, gap_anchors)`。value_scanner.horse_value_factorsを1頭ずつ呼び、posを末脚有無でBAL系/CAS系に分類(`_classify_pos`)。MELは消去スコア(-人気+1.5×pos-1.5×neg)上位半分。焦点候補=人気薄(≥6)の最多得票馬。承認数3=🟢GO/2=🟡条件付き/≤1=⚪見送り。危険人気馬=人気≤3×−ファクター×市場妙味なし。**自信度は作り物の数字を使わず、回顧台帳consensus_ledger.json(`log_consensus_outcome`/`calibration_summary`)に合議状態別の実測勝率/複勝率/ROIを蓄積して与える設計**。

**配線(app.py 🧠MAGIシステムpage)**: 波乱度表示の直後・モード選択の前に「🧩CONSENSUS GATE」パネル追加(st.session_state['df']を使用)。エヴァ風承認/否定UI(3カラム緑承認/赤否定)＋RESULT OF THE DELIBERATIONバナー＋合議妙味馬テーブル＋危険人気馬＋回顧キャリブレーションexpander。事前複勝オッズ取得はcheckbox任意(scraper.fetch_place_odds_api)。展開好位ゾーンはsession_state[`_pace_ctx_{rid}`]→trio_engine.deploy_bonus_from_ctxからbest-effort。

**合議バックテスト完了(2026-06-16, scripts/consensus_backtest.py)**: jravan.dbで計算可能な3独立軸(末脚=ato3f偏差/フォーム=chakujun偏差/オッズ断層=odds_gap_anchors)を2021-25・人気薄6番人気以下127,550点で再構築し承認数別に実測。**結論=「合議の一致は的中率を単調に上げる(本物)が、ROIを生むのは"市場軸(BALTHASAR)の票"が混ざったときだけ」**。数値: ベース複9.4%/単ROI66% → 末脚13.6%/66% → フォーム14.6%/67% → 断層24.1%/77% → votes=2は16%/59〜68% → **votes=3=複27%/ROI96%, 末脚×断層=複27%/ROI94%(別格)**。実力軸どうし(末脚+フォーム)のANDは的中上がるがROI≈ベース([[verified_spurt_index]]step2「AND併用は悪化」と整合)。フラット単勝で黒字化はせず(最大96%)＝複勝/組合せ向き。→ evaluate_consensusの判定を改訂: 承認数を対称に扱わず**人気薄2票は市場軸(candidate['bal'])が有ればCONDITIONAL(別軸合意)/無ければSKIP推奨(実力軸の重複＝妙味薄)**に格下げ。3票はGO据置。app.pyはverdict_label表示なので自動反映。注:断層はwin_odds確定値で代理・本来BALTHASARの主力は単複乖離(place odds=1993-96/2026のみで広域窓不可)。

**未了/次**: 回顧学習ページ(app.py:10329〜)を「LLM反省文」から「合議判定→実結果をlog_consensus_outcomeで台帳記録」に繋ぎ替えるとキャリブレーションが回り始める。旧magi_system.py/magi_trainer.pyは温存(削除せず)。

**⚠️ 2026-06-22 UI削除**: ユーザー指示で🧠MAGIシステムページから🧩CONSENSUS GATE(合議ゲート)と🎓MAGIトレーニングのUIブロックをapp.pyから丸ごと削除。SRA依存(st.stop)も撤去。ページは[[project_magi_oshaberi]]の「おしゃべり回顧」を主役に再構成(レースID直接入力・SRA不要)。**core/magi_consensus.py / consensus_ledger.json / consensus_backtest.py のロジックは残存**(検証知見は有効)が、UIからは呼ばれない。再びUI化するなら新ページに。検証結論(votes=3=複27%/ROI96%・市場軸が混ざると黒字寄り)は引き続き正しい。
