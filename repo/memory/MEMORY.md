## ユーザー・フィードバック
- [過小評価の勝ち馬を拾う](feedback_catch_underrated_winners.md) — 中核目標
- [俗説5案は過剰人気](feedback_folk_signals_overbet.md) — 初ブリ/距離短縮等→正の妙味ゼロ。再実装防止
- [負けた日の思いつきは1日試算→判断](feedback_single_day_hunch_check.md) — まず1日サンプルで様子見る運用
- [VHバッジ選別は逆効果](verified_vh_badge_selection.md) — VH1位が最良(+4pp)。🏆はVH1位に付ける

## プロジェクト状態
- [アプリ再構築パイプライン](project_app_pipeline.md) — 妙味レース→強適→消去→券種の4段
- [CSV特徴ストア](project_csv_feature_store.md) — horse_races.csv 25万×53列。研究高速化用
- [穴馬ハンター](project_value_horse_hunter.md) — recall70%達成。主成分=市場情報。vh2_model.lgb
- [妙味スキャナ](project_value_scanner.md) — 単複乖離(単≥10×複≤3)検証済。core/value_scanner.py
- [強適消去エンジン](project_elimination_engine.md) — 半分消去+穴救出+危険人気馬+消去クロス22フラグ
- [強適シート統合ビュー](project_consensus_view.md) — 検証済みエッジ合議。core/consensus_view.py
- [軸馬候補◎〇▲](project_axis_selection.md) — 固定軸(人気1+2)が最適
- [MAGI合議ゲート転生](project_magi_consensus.md) — 予測器→妙味/見送り判定器へ
- [MAGIおしゃべりルーム](project_magi_oshaberi.md) — インタビュー型回顧学習。core/magi_chat.py
- [3連複エンジン統合](project_trio_engine.md) — 人気-人気-穴が最頻46%・ROI最高
- [買い方最適化④](project_bet_optimizer.md) — core/bet_optimizer.py(Harville+ケリー)
- [資金管理⑤ BetSync](project_betsync_money.md) — ガードレール/破産確率/台帳。core/money.py
- [展開マップ再構築](project_pace_map_rebuild.md) — テン速力実タイム化。事実上完了
- [トラックバイアス統合](project_trackbias.md) — クッション値/含水率/ABCコースはDB未収録
- [騎手分析JRA-VAN版](project_jockey_jv.md) — core/jockey_jv.py(J1〜J5)
- [nankanスクレイパー+NAR修復](project_nankan_scraper.md) — 南関東4場(42浦和/43船橋/44大井/45川崎)
- [NAR recall比例化](project_nar_recall_proportional.md) — 出走頭数比例に分岐。中央は不変
- [Gemini 3.x移行](project_gemini3_migration.md) — budget→level移行。gemini_compat.pyで世代振分
- [新聞発行(PDF+CSV)](project_newspaper_pub.md) — 自前計算+出走表事実のみ。他社加工物は載せない
- [新聞AIコメント欄](project_newspaper_ai_commentary.md) — 5人格×検証済みシグナル担当。約4円/R
- [netkeiba AI展開照合](project_ai_tenkai_overlay.md) — 表示のみ・エッジ主張なし
- [消去理由ラーニング](project_elim_reasons_learning.md) — 条件タグ3回で自動残し。個人実観測台帳
- [競馬AI思考法エンジン](project_philosophy_engine.md) — 検証済み台帳の編纂。LLM不使用ルールエンジン
- [📝買い目ノート](project_bet_note.md) — 検証済みルールで診断(LLM不使用)。core/bet_note.py
- [推奨絞り頭数](project_narrow_n.md) — 荒れ予報×頭数で実測。堅い6頭〜大荒れ9頭
- [買い方の分布統計](project_formation_stats.md) — 配当/連敗/必要資金を3箇所に配線
- [QA基盤](project_qa_harness.md) — tests/smoke.py(pytest不要)
- [DB鮮度アラート](project_db_freshness.md) — core/db_freshness.pyで🟡🟠🔴表示
- [JRA-VAN欠損と回避策](project_jravan_data_gap.md) — 血統2023年から劣化→netkeibaパースで0%→100%。手順書=repo/jravan_todo.md
- [強適テーブル列の棚卸し](project_column_audit.md) — 🔴6列否定済み→除外。repo/column_audit_2026-08.md
- [JRA-VAN JV-Link環境](project_jravan_setup.md) — 32bit Pythonで開通済
- [LTR特徴量探索](project_auto_feature_loop.md) — 採用3件=騎手厩舎条件特化。斤量ローテは織込み済み確定
- [db-keiba騎手J-combo](project_dbkeiba_jcombo.md) — 検証済み=不採用(out-of-sample崩落)
- [JRDB仕様書駆動読込](project_jrdb_ingest.md) — jrdb_spec.py+jrdb_read.py。バイト位置注意
- [SkyOffice AIボット](project_skyoffice_bots.md) — 凍結
- [pre_agi ローカルLLM](project_pre_agi_local_llm.md) — AUTOMATA新プロジェクト
- [「この1番人気は買えるか」ビュー](project_fav_check.md) — 検証済み部品を集約。新主張ゼロ
- [BetSync癖発見](project_betsync_habits.md) — 感情/見送り/逸脱の自己申告台帳

## 検証済み(採用・配線済み)
- [荒れ条件](verified_arare_conditions.md) — ハンデ+7.9pp/フルゲート16頭のみ独立エッジ
- [荒れ判別ロジット](verified_arare_field_pricedin.md) — エントロピー主軸AUC0.69
- [オッズ本命不在(荒れ)](verified_arare_entropy.md) — 大谷等価=荒れ83%。ハンデ/16頭と独立
- [荒れ予報時に見る列](verified_arare_signal_check.md) — 補正T最強z10.4。6項目有意→🟣マーカー
- [オッズ理論(ガラス人気馬)](verified_odds_theory_signals.md) — 単複逆転fade z-8.5→danger_gate
- [オッズ構造(断層深度)](verified_odds_structure_hunt.md) — ratio=2.0が最強。心理節目等は効果なし
- [人気馬×中9週+減点](verified_rotation_weight_demerit.md) — z-5.6→danger_gate配線済
- [危険人気馬の材料再監査](verified_danger_fav_audit.md) — 10.8万頭。斤量比/前走5着以下→削除
- [ガラス人気馬の配線漏れ修正](verified_glass_fav_wiring.md) — win_odds/place_mid未渡し→修正
- [軸馬NG(前走1着)](verified_axis_ng_claims.md) — -2pp両窓有意。距離延長/短間隔は否定
- [先行は軸として過剰人気](verified_front_runner_overbet.md) — 位置比率<0.28で-1.6pp
- [末脚偏差は人気薄限定](verified_spurt_index.md) — 6人気以下×top3で効く
- [上がり3Fはスロー由来だけ](verified_spurt_pace_quality.md) — 🐢信頼/⚡バテ差し注意
- [33ラップは人気薄で本物](verified_lap33_theory.md) — 人気薄×適合=+0.9pp安定
- [補正タイム](verified_corrected_time.md) — 穴+1pp(弱)/本命+5pp(強)。軸寄り
- [道悪×血統](verified_baba_blood.md) — POWER群維持。人気薄逆張りは織込み済み
- [ダート枠順エッジ](verified_dirt_draw_bias.md) — 外枠×1-3人気+4.5pp/内枠×4-5人気-3.9pp
- [黄金ラインは35-40%](verified_golden_line_bands.md) — 40%+は織込み済み。係数は据え置き
- [クッション値×種牡馬4頭](verified_cushion_theory.md) — 名指し12頭は崩落
- [Stress Analystデバフ](verified_stress_debuff.md) — リーク無し=小柄×馬体減-2.0pp等のみ
- [消去クロス スト2閾値](verified_stress2_bottomk.md) — K=2が最強
- [末脚救出+ボーダー残し](verified_keepone_border.md) — 取りこぼし15→10%
- [末脚下位は短距離でも有効](verified_slow3f_distance.md) — 距離ゲート不要
- [アンチ市場の消し2件](verified_antimarket_elim.md) — 脆い本命-6.5pp/断層直下-5.1pp
- [人気1-3がRank下位=fade材料](verified_rank_fav_disagree.md) — Rank10位以下z-7.45。fav_checkに配線
- [消去クロスに実力下位×VH圏外](verified_elim_ranklow_vhout.md) — 該当29%・top3率3.1%
- [厩舎の当コース勝率](project_trainer_course.md) — 🔴≥20%のみ妙味
- [補正T×人気重複は軸信頼度](verified_time_pop_overlap.md) — 重複0→3で複勝55→74%
- [騎手名略記バグ修正](verified_jockey_shortname_bug.md) — 係数1.0固定の原因=名寄せ未通過
- [NAR逃げは複勝52%](verified_nar_draw_style.md) — 中枠逃げ最強。内枠×逃げ加点は棄却
- [NAR大型馬500kg+穴帯限定](verified_nar_weight_bias.md) — 7人気+で+8.3pp
- [NAR JRAシグナル](verified_nar_jra_signals.md) — 川崎内枠z+2.55。少頭数×本命z+2.14
- [NAR末脚指数](verified_nankan_pci_spurt_backtest.md) — 6人気以下×top3=12.3%vs8.2%
- [牝馬限定×1番人気fade](verified_fillies_fav_danger.md) — top3率-5.7pp(z-3.04)。danger_gate+fav_check配線

## 荒れ俗説(否定/保留)
- [荒れ4件検証](verified_arare_4claims.md) — 開催後半/短距離=否定、新潟芝/福島ダ=保留、牝馬限定=採用

## 検証済み(否定・priced-in)
- [パドック定量](verified_paddock_weight.md) — fade側のみ。買い妙味ゼロ
- [堅いレース逆転](verified_solid_race_inverse.md) — 既存ロジットに含まれ済み
- [複勝combo+EV](verified_fukusho_combo_leak.md) — リークの幻。leak-free版は-EV
- [PCI完全終了](verified_pci_pricedin.md) — 軸/相手/消去いずれもエッジ無し
- [圧勝の罠は軸では誤り](verified_ohtani_trap.md) — 前走圧勝=最良の軸(複勝72.3%)
- [脚質は織込み済み](verified_legtype_axis.md) — 事前習性は複勝率をほぼ動かさず
- [巻き返しは過剰人気](verified_comeback_overbet.md) — 穴帯残差≈0〜負
- [展開恩恵は織込み済み](verified_tenkai_priced_in.md) — 展開向く×人気薄=むしろ過剰
- [当日バイアスは順張り死](verified_emp_bias_danger.md) — 逆張りfadeのみ弱い
- [単勝は市場効率的](verified_tansho_roi_efficient.md) — 全条件で+ROI無し
- [風は着順に効かない](verified_wind_no_effect.md) — 477k頭で残差≈0
- [天候×心理の歪みも無い](verified_weather_mood_rejected.md) — 英国EC/SADは日本で非再現。trainの雨マイナスはholdoutで符号反転
- [距離適性はpriced-in](verified_distance_affinity_pricedin.md) — 残差≈0
- [マクリ指数は織込み済み](verified_makuri_priced_in.md) — 全帯z<2
- [血統×コースは織込み済み](verified_blood_course.md) — 副産物=場×人気軸信頼度のみ
- [テン混雑→荒れは超えず](verified_pace_congestion_weak.md) — 実タイムでもpriced-in確定
- [トラック変更は過剰人気](verified_track_change_overbet.md) — 芝→ダz-3.9〜-5.5
- [ショッカー理論はリーク](verified_shocker_leak.md) — 事前部分にするとエッジ消滅
- [前走着差0.6秒/0.8秒は俗説](verified_prior_margin_debunk.md) — 小標本ノイズ/リーク
- [兄姉のデビュー実績もpriced-in](verified_sibling_debut_rejected.md) — 複勝率9pp差は全て人気で説明。CIが0を跨ぐ
- [前走レースレベルは効かない](verified_race_level_rejected.md) — 効いているのは着差1.5秒だけ。低レベル戦の方がむしろ良い
- [母の出産年齢16歳超は効果なし](verified_dam_age_rejected.md) — ベースを期間内で取ると消滅。14-15歳の方が悪い
- [初勝利理論はpriced-in](verified_first_win_theory.md) — 重賞勝ち率2.1倍は事実だが馬券残差ゼロ。タイム指数95%は数字のマジック
- [補正タイム俗説](verified_5run_theory_debunk.md) — 5走前理論等は織込み済み
- [馬主は織込み済み](verified_owner_pricedin.md) — 単体/×厩舎ともpriced-in
- [消去ML置換は不採用](verified_elim_ml_ranking_rejected.md) — holdout-0.63ppでゲート未達
- [減点方式資料は9割既知](verified_genten_method_material.md) — 未検証4項目もLTRで全不採用
- [LTR窓前進は改善せず](verified_ltr_refresh_rejected.md) — 2026で+0.11pp=誤差
- [頭数モデル分割は不採用](verified_ltr_fieldsize_split.md) — 帯別学習で全体-0.04pp
- [上位3頭加点は悪化](verified_weight_top3_bonus.md) — priced-in領域を歪める
- [NAR庭騎手はエッジなし](verified_nar_home_jockey.md) — z-0.51
- [NAR出走間隔は効かない](verified_nar_interval_no_effect.md) — z-0.66
- [卍氏ファクター(重体重棄却)](verified_manji_two_factors.md) — 遠征は[[verified_ensei_east_to_west]]で決着
- [東→西遠征×1-6人気は過剰人気](verified_ensei_east_to_west.md) — 複勝-4pp(z-3.1〜-5.3)。関西馬の東征はpriced-in
- [調教時計と人気薄×父は両方ゼロ](verified_training_and_sire_popbucket.md) — 全区分|z|<1.7
- [JRDB: パドック/基準オッズ/KYI/C分類/CYB全ゼロ](verified_jrdb_paddock_codes.md) — 新エッジ無し確定
- [r40複勝EVは時点リーク](verified_r40_place_ev.md) — 確定オッズ118%→直前86%。締切前で追試必須

## クロス・フォーメーション構造検証
- [クロステーブル構造](verified_cross_table_structure.md) — VH×人気ρ=0.94二重計上/top-5内ρ=0.16独立。4軸<3軸。R×V列実装済
- [RRVファミリー不安定](verified_rrv_structure_unstable.md) — Rank系>人気系は安定。個別ファミリー順位は期間で入替

## 買い方・資金管理の検証
- [フォーメーションROI](verified_formation_roi.md) — 控除率超えだがROI83-90%<100%
- [妙味度較正とゾーン別形](verified_vscore_zone_formation.md) — 全形でROI100%未満
- [点数スイープholdout](verified_formation_sweep_holdout.md) — 選抜バイアス-32pp
- [◎〇+VH精鋭1位](verified_axis_vh_trio.md) — D鉄板ROI89%が最良。荒れは使用不可
- [どちらの軸が飛ぶかは予測不能](verified_which_axis_flies.md) — 「常に人気2」62.2%が最良
- [3頭目もRankより人気](verified_rank_vs_ninki_legs.md) — D鉄板で人気+7〜9pp
- [Rankが効くのは下級クラス](verified_class_rank_gradient.md) — 未勝利+4.4pp z+9.9。英国『上級ほどAI』は非再現
- [荒れゾーンに勝ち筋は無い](verified_arare_zone_buy.md) — 見送りが正解
- [3連単穴上限ana_hi=12](verified_ana_hi_cap.md) — 13番人気以下は的中率-1.3pp
- [カジノ進行法は全滅](verified_staking_systems.md) — フラットベット一択
- [日内の流れは無い](verified_hot_hand_selective.md) — ここぞ=選別のこと
- [3連単人気パターンは幻](verified_popularity_patterns.md) — 選抜バイアス-98pp
- [公開回収率の信憑性](verified_roi_claim_credibility.md) — 券種×回数が無い数字は評価不能
- [買い方の総まとめ](repo/buying_playbook_2026-08.md) — D鉄板=人気形/C中庸=Rank形/荒れ=見送り
- [3着内2頭上位+1頭伏兵は23%](verified_top5_longshot_seasonality.md) — 季節性否定
- [戦闘力天井は市場](verified_top5_capture_ceiling.md) — LTRは人気81.7%を超えない

## リファレンス
- [JRDB導入で何が解けるか](reference_jrdb_potential.md) — 最有望=不利(映像由来)。加工済み指数は価値薄
