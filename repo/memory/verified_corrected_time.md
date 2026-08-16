---
name: verified_corrected_time
description: 自前補正タイム(スピード指数)の検証。穴には弱く(+1pp)本命補強に強い(+5pp)。JRA-VANに補正タイムは無く生タイムから自作
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

**JRA-VANに補正タイム/基準タイム/数値馬場差は無い**(生の走破タイム＋馬場状態コード4段階のみ)。TARGET frontier JVの補正タイム(補/補9/前補)はTARGET独自ブラックボックス計算でJV配信には含まれない→外部依存より自前計算が筋。

**自前補正タイムの作り方(馬場コード非依存・リーク無し)**: scripts/corrected_time_backtest.py。
`sec`=走破タイム秒('1543'→114.3) → `baseline`=(surface,距離)中央値 → `raw_dev`=sec−baseline → `track_bias`=(開催日,競馬場,surface)のraw_dev中央値 → **`corrected`=raw_dev−track_bias**(負=速い)。馬場差を同日同コース偏差で吸収するので良/重コードの当否に依存しない。予測には各馬の過去走corrected(min=最速)のみ使用。

**検証結果(n=509,406馬・2019-25・芝ダ・人気順位ninkiで統制した残差pp/z):**
- 補正図トップ3(全人気): +2.67pp / z+22.8
- **1-2番人気×図トップ3: +5.36pp / z+19.3 ← 最強(本命の複勝信頼度UP・複勝69.3%)**
- 3-5番人気×図トップ3: +3.10pp / z+11.9
- **6番人気以下×図トップ3: +1.02pp / z+7.9 ← 有意だが小**(複勝11.9% vs 図外9.1%だが大半はninkiに織込み済)
- 9番人気以下×図トップ3: +0.64pp / z+4.7
- 6番人気以下(図トップ外)−0.19pp / 過去図なし−0.58pp(対照)

**How to apply**: 補正タイムは検証済みの**小エッジ**。①単体の穴アラームにはしない(穴超過分+1ppのみ・[[verified_spurt_index]]末脚の方が穴に効く) ②一番効くのは**本命補強**=軸の複勝信頼度([[verified_ohtani_trap]][[verified_comeback_overbet]]と同系統) ③LTR特徴量/人気薄の相手絞り込みフィルタとして末脚と併用。中核目標[[feedback_catch_underrated_winners]]の穴拾いには弱い点に注意。

**ライブ配線(2026-06-21・ユーザー選択=本命補強/強適Ranking Table)**: `scripts/build_corrected_time.py`が補正タイムを馬(ketto)ごとに集計→`data/corrected_time.db`(230,864頭・要再実行で更新)。`core/corrected_time.py`(get_figure/field_ranks/fmt)がread-onlyで引く。**🏠強適Ranking Table**と**🧹強適消去エンジン**に🔵補正T列(フィールドtop3に🔵・負=速い)。Name→ketto=jockey_jv.resolve_horse。※ホームは保存済み列順があると新列は既定非表示(⚙列順設定で要有効化)。EV/複勝/連対率列も消去エンジンに追加([[project_elimination_engine]])。

**図定義をH7化(2026-06-21・検証 scripts/h7_refine_backtest.py)**: 当初「過去全走・芝ダ混在の最小corrected」→**「直近7走 × 今走と同一芝ダ の最小corrected」**に変更(資料のH7指数定義)。比較(2019-25 図トップ3):best_all 全top3残差+2.67/穴+1.02/勝馬top3率38.6% → **h7_surf +3.11/穴+1.62/勝馬top3率44.6%**(本命補強は5.36→4.80と僅減だがz18.6で十分)。recallと穴で明確に改善=採用。horse_fig新スキーマ=ketto/fig_shiba/fig_dirt/runs_shiba/runs_dirt/last_day。`get_figure(ketto, surface)`が芝ダ別に返す(同一馬場の図が無い=初ダート等はNone)。

**NAR(南関)にも転移=抑制しない(2026-07-02・scripts/corrected_time_nar_check.py)**: 補正タイムは同日同コース偏差で自己較正なので会場非依存。南関42-45 holdout2025で**本命帯(1-3人気)×補正上位=複勝64.1%/残差+5.84pp/z≈2.0**、対照(補正上位でない本命)は+1.20pp/z0.77できれいに分離。JRA本命補強+5ppがそのまま転移。→NARでは[[verified_owner_pricedin]]文脈のLTR抑制と違い**補正タイムは残す(本命補強に活かす)**。穴帯は+1.34pp/z0.98で弱い(JRA同様priced-in)。教訓=当て推量で"NAR=JRA専用スコア全部抑制"は誤り。自己較正系(補正T)は転移・学習系(LTR)は分布外、と切り分ける。

**未了/改良余地**: ①図=過去全走のminは出走数多いほど有利になる微バイアス→直近平均orベスト3に改良すべき。②JRA-VANのマイニング予想走破タイム(SEレコードpos538/len5に存在・現DB未抽出)は別物の事前ML予測で、取込にはJV-Link再取得(SE再パースで列追加)が必要・歴史的カバレッジ未確認([[project_pace_map_rebuild]]と統合)。③単勝ROIはwin_odds欠損問題で未算出。
