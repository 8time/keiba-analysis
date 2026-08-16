---
name: project_auto_feature_loop
description: 自己改善ループをLTRに限定して安全実装。scripts/auto_feature_search.py。recall@7で特徴量探索・自動デプロイしない
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
  modified: 2026-07-21T23:43:38.890Z
---

「自己改善ループ」(戦略→BT→採点→弱点→並列別案→最良選択→絞り込み)を中核目標(過小評価の勝ち馬=recall@7)に限定して安全実装(2026-06-22)。流行のagentic loop。LLMは賢い部分でなく提案/批評役、頭脳はオッズ残差/recall@7のPython。ローカルLLM([[project_pre_agi_local_llm]])でも可。

**scripts/auto_feature_search.py**: build_ltr_model.py/ltr_ranker.pyを**一切変更せずimport再利用**して包む。固定2025+テストの**recall@7のみ**で評価(ROI最適化はしない=過学習/俗説製造を回避)。候補特徴量は『リークしない×推論時(ltr_ranker)でも計算できる』ものだけ。多重検定の罠の防護柵=①固定seed決定論化 ②val(2024)とtest(2025+)両方で改善した案だけ採用候補 ③マージン閾値(--margin既定+0.15pp) ④**自動デプロイしない**(人がレビューしてFEATURES+encode+ltr_rankerの両方に配線→`python scripts/build_ltr_model.py`再訓練)。--ablation(drop-one=有害特徴量検出)/--quick(2019+軽量)。出力=data/feature_search_log.json。

**初回結果(--quick 2019+, 264s)**: 候補6本(weight_ratio/zogen_abs/draw_rel/age_sq/bataiju_dev/futan_dev)**全て採用基準未達**=簡単な派生は織込み済み。防護柵が機能=健全。

**第2イテレーション結果(全データ, 257s, 2026-06-22)**: ベースtest win@7=0.9295/val=0.9436。強候補4本=add_strong_candidates(前走着差/騎手直近勝率win80/騎手複勝t3_50/厩舎複勝t3_30。jockey_code/trainer_codeはresultsから自前merge、フィルタ前全履歴でshift(1).rolling)。結果: **cand_prior_margin却下(test-0.19/val-0.24=[[verified_prior_margin_debunk]]通り織込み済み、生着差はランキング悪化)**。騎手/厩舎"全体"成績3本は**両ホールドアウトで僅かプラスだが全部ノイズ範囲内(test6982でse≈±0.3pp、jockey_win最大でも+0.13pp<1SE)・マージン未達で不採用**。→ループが独自に「全体の騎手/厩舎成績は織込み済み」を再発見=[[project_trainer_course]]の検証結論(全体勝率は織込み済み・🔴当コース勝率≥20%だけ妙味)と一致。

**第3イテレーション結果(条件特化, 全データ, 271s, 2026-06-22)**: build_candidates(candset='cond')で当馬場/当コース成績を追加(jockey×surface/jockey×jyo/trainer×jyo/trainer×surface、複勝t3のrolling)。**初の採用候補=cand_trainer_jyo_t3(厩舎の当コース複勝率, roll20 min5): Δtest+0.19pp/Δval+0.05pp で防護柵通過**。jockey_jyo_t3はtest+0.19だがval-0.05で却下、jockey_surfは両正だがマージン未達、trainer_surfは却下。→**[[project_trainer_course]]の検証結論(全体勝率は織込み済み・当コースだけ妙味)と完全一致**。前回の方向予測(全体→条件特化)が的中。⚠️ただしtest+0.19ppは6982レースのse≈±0.3ppに対し1SE未満でval+0.05ppも僅少=確定エッジでなく「防護柵通過の最有力候補」。検証済trainer_courseの事前知識が方向を支持する点が他候補と違う。

**✅採用・配線完了(2026-06-22)**: seed頑健性(scripts/seed_robustness_check.py・5seed)= Δtest mean+0.25pp/std0.14・5/5正、Δval mean+0.19pp・5/5正 → GO。配線=build_ltr_model.py(load_dataにr.trainer_code追加・compute_trainer_course新設=厩舎×jyoのshift(1).rolling20min5複勝率・FEATURESに'trainer_jyo_t3') + core/ltr_ranker.py(_trainer_jyo_t3=馬の最新厩舎→当jyo直近20走複勝率をDB query・推論時付与) + app.py(_ltr_riにjyo/race_num追加。**これが無くB6のjyo_code/race_num/cushion/dirt_moistureが推論時ずっと0だった潜在バグも同時修正**)。本番再訓練結果: **Win recall@7 0.9297→0.9307(vs Ninki+0.36pp)・Top3 recall@7 0.8802→0.8835(vs Ninki+0.37pp/旧比+0.33pp)**。trainer_jyo_t3は特徴量重要度4位(gain24995)。

**第4イテレーション(cond2, 2026-06-22)**: build_candidates候補=血統×馬場(sire_surf)/枠×コース(draw_course・レース単位集約でリーク無)/騎手当場勝率(jockey_jyo_win)/騎手×場×馬場(surfjyo)。baselineはtrainer_jyo_t3入り。**採用=cand_jockey_jyo_win(騎手の当場"勝率"): Δtest+0.16/Δval+0.58pp**。前回jockey_jyo_t3(複勝率)はval負で却下だったが**勝率フレームで復活**(recall@7=勝ち馬なので勝率が素直に効く)。血統×馬場✗(blood_dict.dbで織込み済み)・枠×コース✗(win recallに効かず)。seed頑健性(--feat cand_jockey_jyo_win --candset cond2)=Δtest mean+0.26/5/5正・Δval mean+0.62/5/5正→GO。配線=build_ltr_model(jockey_code取込+compute_jockey_course=騎手×jyoのshift1.rolling60勝率+FEATURES) + ltr_ranker(_jockey_jyo_win=**その馬のレースの騎手名で照合**・当jyo直近60勝率。騎手はレース毎可変なので最新騎手でなく当該騎手) + app.py(_ltr_hsにjockey名追加)。**本番再訓練: Win recall@7 0.9307→0.9347(vs Ninki+0.76pp/前比+0.40pp)・Top3 0.8835→0.8822(微減-0.13pp=勝率特化のトレードオフ)**。jockey_jyo_winは重要度3位。中核=勝ち馬recall@7なのでネット+。

**第5イテレーション(cond3, 2026-06-22)**: 候補=騎手×距離帯(勝率/複勝)・厩舎×距離帯複勝・昇級代理(前走勝ち/通算勝利数)。**前走クラス昇降はDBに条件クラスコード無し&race_name空で不可**→通算勝利数/前走勝ちで代理(両方弱く不採用=クラスはオッズ/過去成績に織込み済み)。防御柵通過=jockey_dist_win(+0.30pp/seed42)とtrainer_dist_t3(+0.17)。**重要:combo同時投入(+0.14pp)<jockey_dist_win単体(+0.30pp)=2つは冗長(距離適性で重複・既存jyo系とも相関)→両方採らず最強1本**。採用=cand_jockey_dist_win。seed頑健性=Δtest mean+0.17/5/5正・Δval mean+0.12/**4/5**(seed1のみval負)=これまでで最弱だが防御柵通過。配線(build_ltr_model compute_jockey_dist=騎手×距離帯S/M/L/Xのshift1.rolling50勝率 + ltr_ranker _jockey_dist_win=騎手名で当該距離帯BETWEEN照合・直近50勝率)。**本番再訓練: Win recall@7 0.9347→0.9363(vs Ninki+0.92pp/前比+0.16pp)・Top3 0.8822→0.8813(微減)**。jockey_dist_win重要度3位。弱seedでも本番で明確改善=採用。距離帯バケツ:S<=1400/M1401-1800/L1801-2200/X2201+。app.pyは変更不要(jockey名/kyoriは既に渡している)。

**第6イテレーション(cond4, 2026-06-22)=頭打ち**: 候補=厩舎×騎手相性(trainer_jockey_t3)・騎手×馬場×距離(jockey_surf_dist_win)・枠×距離(waku_dist_t3・レース単位集約)。baseline=3特徴量入り(test0.9360/val0.9513)。**3本とも採用ゼロ=「valは正(+0.12〜0.24)だがtestは負(-0.03〜-0.07)」**=既存の騎手/厩舎適性3本と冗長＆val片側はノイズ/2024過学習。防護柵が val片側改善を正しく却下。**結論:騎手/厩舎の条件特化ファミリーはやり尽くしプラトー。同系統をこれ以上切ってもtest伸びず。** 次に伸ばすなら別ファミリー(母父bms×条件/馬体重トレンド/フィールド相対オッズ/既存強特徴の相互作用など)が要る。cond4のsearchコードはauto_feature_search.pyに残置(本番FEATURES変更無し)。

**第7イテレーション(cond5=USM, 2026-06-23)=採用ゼロ**: USM(馬力絞り出しメーター=オッズ帯人口平均に対する騎手の過去実績比・trailing250騎乗shift1)を単/連/複で候補化(cand_usm_win/t2/t3)。baseline=jockey_jyo_win+jockey_dist_win入り。**3本ともtest微減(-0.04〜-0.11)val横ばい(+0.00〜+0.10)で却下**=全体USMは既採用の条件版(当場勝率/当距離帯勝率)に吸収済み・織込み済み。「全体✗→条件特化◎」の再確認。**意義: USMはバックテスト可能で、実際に検証して『単体全体USMはLTRに上乗せしない』と確定**。db-keiba等の単勝回収率しきい値条件(全体騎手スライス)も同family＝予測器でなく参考枠が妥当([[verified_tansho_roi_efficient]])。

**第8イテレーション(cond6=血統系, 2026-06-23)=採用ゼロ**: 母父(BMS)×馬場/距離・ニックス(父×母父)を産駒成績(shift1.rolling)で候補化。**4本ともフラット〜負(bms_surf+0.00/bms_dist-0.01/nick_surf-0.03/nick-0.10)**。cond2で父×馬場却下に続き、**母父・配合(隠れた角度の期待)まで含め血統は完全に織込み済み**=馬の血統評判はオッズが先に織込む。→血統はLTR予測器に上乗せ無し確定。🩸血統SPページは表示/探索ラボとしては可だが予測器にはならない。NotebookLM血統キーワードはモデル用には低価値(表示用なら可)。次に伸ばすなら非血統角度(ペース/トラックバイアス/condition-change)。

**第9イテレーション(Glickoレーティング, 2026-07-02)=却下**: 資料p6「レーティング系(絶対能力)」の検証。チェス式Glicko-1を過去レースから逐次計算(リーク無し=事前レーティングのみ・強い馬を負かした馬は強い・scripts/glicko_feature_test.py)。cand_glicko+cand_glicko_rankを26特徴に追加。**win_r@7: VAL+0.06pp/TEST-0.02pp、top3: VAL-0.02pp/TEST-0.07pp=ほぼゼロで却下**。馬の絶対能力も人気に織込み済み(過去の通算勝利数/前走成績と同型)。→レーティング系はLTR上乗せ無し確定。

**NAR専用モデル(資料p5セグメント, 2026-07-02)=採用**: これはauto_feature_loop(特徴追加)でなくモデル分割。JRA学習LTRは地方で分布外→南関42-45だけで別LightGBM学習(scripts/build_ltr_nar.py・NAR特徴=log_odds/cushion/surface_code除外)。**holdout2025 win recall@7=モデル98.4% vs 人気96.0%=+2.38pp(JRA版+0.9ppより大・地方は騎手が効く=jockey_jyo_win/dist_win重要度2-3位)**。ltr_ranker._load_nar+get_scoresが会場コード(jyo>10)でモデル自動切替。今日のNAR抑制を専用モデルに置換。→特徴追加は頭打ちでも「条件でモデルを分ける」は効く余地あり(特に分布外のNAR)。

**第10イテレーション(cond7=減点方式資料, 2026-07-22)=採用ゼロ**: NotebookLM資料「The Sculptor's Funnel(減点方式)」の消し条件のうち**台帳に検証記録が無い4項目だけ**を候補化(既検証のものは投入しない: 前走着差/距離適性/中3週/斤量3kg増/大型馬は再投入禁止)。cand_minarai_lost(前走が減量騎手→今回通常=実質斤量増・results.minarai使用)/cand_futan_diff(今回−前走斤量)/cand_prev_futan(前走の斤量=57.5kg以上の過酷さ)/cand_runs_since_rest(前走間隔90日以上を起点に数え直す使い詰め戦数)。ベースtest win@7=0.9366。**結果: prev_futan -0.07 / minarai_lost -0.16 / futan_diff -0.24 / runs_since_rest -0.26pp で全滅**。⚠**4本中3本が val では改善(+0.07〜+0.12)しているのに test は全滅** ＝ 片窓だけ見ていたら3本採用していた。両窓ゲートが過学習を捕まえた明確な実例。斤量・ローテ系は織込み済みで確定。詳細=[[verified_genten_method_material]]。

**ループ実績まとめ**: 簡易6✗→全体騎手厩舎4✗→trainer_jyo_t3◎→jockey_jyo_win◎→jockey_dist_win◎→cond4(条件特化)✗→cond5(USM全体)✗→cond6(血統)✗→Glickoレーティング✗。別軸=NAR専用モデル◎(+2.38pp)。Win recall@7=0.9295→0.9307→0.9347→**0.9363**。採用3=全部「騎手厩舎の条件特化」。织込み済み確定=血統全般/全体騎手厩舎/USM/前走着差/枠/PCI/展開/巻き返し/圧勝/単勝ROI。知見:「全体✗→条件特化◎」「複勝率✗→勝率◎(recall@7=勝ち馬)」「冗長候補はcomboで検出し最強1本のみ」「弱seedでも本番retrainが最終審判」。prepareはcompute_trainer_course+jockey_course+jockey_distを呼ぶ(baseline本番一致・KeyError防止)。build_candidatesのjtマージはdfに無い列のみ(load_dataにjockey/trainer_code入った後の衝突回避)。次候補=騎手×馬場×距離/厩舎×騎手相性/枠×距離など(クラス系は打止め)。関連:[[project_trainer_course]]/[[project_kyoteki_score_rebuild]]/[[feedback_catch_underrated_winners]]
