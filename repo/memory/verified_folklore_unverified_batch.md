---
name: verified-folklore-unverified-batch
description: 俗説ハンター「未検証だが検証可能」39項目を一括バックテスト。採用方向3件(全てfade側)・否決12・未達18・標本不足4
metadata:
  node_type: memory
  type: project
  originSessionId: 0dfa50b3-f3ba-4580-bc53-02d70a45391f
---

俗説ハンター(core/folklore_lib.py)で verdict=unverified のうち出馬表系データで検証可能な
39項目（パドック/調教タグ依存の_tag_m系18件と _always_skip 系を除く）を一括検証。
2026-08-26。スクリプト: `scripts/folklore_unverified_backtest.py`、要約: `data/folklore_unverified_summary.json`。

## 方法
- jravan.db 2014-2026・**JRA平地のみ**（同DBの地方行はgrade体系が別物で混入厳禁）。
- 条件戦は race_name が空なので **クラス階級は出走メンバーのキャリアから導出**
  （全馬初出走→新馬 / 最大勝数0→未勝利 / 1→1勝 … 4+→OP。grade A/B/C/L はG1/G2/G3/Lを直接使用。
  未勝利は2歳6-12月・3歳1-3月にしか存在しない事実で誤判定補正。2025分布:
  新馬304/未勝利619/1勝1474/2勝469/3勝217/OP123/G3・68/G2・38/G1・24 = 実態と整合）。
- 残差 = 複勝(3着内)率 − 同人気のtrain(2021-2024)基準率。holdout=2025が本番、recent(2026-03-21〜)は符号確認。
- 騎手統計（トップ騎手=500騎乗&勝率15%+、コース巧者=30騎乗&勝率15%+）はtrain窓で凍結（リーク防止）。
- 判定: holdout n>=200 かつ 主張方向に z>=2 かつ recent同符号 → 採用方向。39件の多重検定考慮で2窓符号一致を要求。

## 結果

### 採用方向（3件・いずれも消し/fade側の俗説が真。効果は小さくROI<80%＝買い妙味ではない）
| 項目 | holdout | recent | 解釈 |
|---|---|---|---|
| first_dist 初めての距離は不安 | n=10,736 残差-1.08pp z-2.84 | -1.11pp z-1.62 | 初距離は人気より1pp弱過剰評価 |
| closer_overbet 追い込み馬は売れやすい | n=1,808 残差-2.89pp z-2.51 | -2.69pp z-1.31 | 5人気以内の追込馬は過剰人気（[[feedback_folk_signals_overbet]]と整合） |
| dirt_layoff ダートの休み明けは割引 | n=7,249 残差-1.07pp z-2.31 | -1.12pp z-1.29 | ダート休明は人気より1pp過剰評価 |

### holdoutのみ有意（recentが未確認/不一致 → 採用は保留が無難）
- maiden_fav1 新馬の1番人気: holdout +5.80pp z+2.12 / recent は n=23 で+4.64pp（同符号だが標本小）。要観察。
- dirt_class_up ダート昇級は危険: holdout -1.45pp z-2.32 だが recent +0.04ppで符号不一致。

### 否決（効果なし・織込み済み確定: holdoutで主張方向の効果ゼロ）
blinker_on / age4 / short_rest / ninki1_solid(1人気は残差ゼロ=市場正確) / colt_winter /
maiden_up / wet_to_good / dirt_out_to_in / fav_slow_agari / dirt_front / dirt_closer_miss / closer_blinker

### 未達（方向は一貫するが |z|<2。採用するほどではない）
top_jockey(+2.00境界) / course_jockey(+1.93、jockey_jvの既知「弱プラス有意未満」と一致) /
filly_fav1_any(-2.6ppで3窓一貫するが有意未満) / first_venue / stay_jockey / jockey_up /
prev_close / prev_stakes / prev_fluke / inner_to_outer / nige_win_up / stakes_nige /
open_nakaana / dirt_small / dirt_2yo_power / filly_wear / gelding_summer / local_rensen /
small_field_closer（[[folklore_small_field_context]]の「打つ手なし」と整合）

### 標本不足（holdout n<200。JRDBでも増やせない＝実世界で稀な条件）
weight_minus20(n=134) / open_cond_win_fav(n=37) / turf_2yo_small(n=28)

## JRDBで補えるか（残る未検証スキップ項への回答）
- **gray_summer（毛色）→ 可能**: KTA位置148/UKC位置46に毛色コード。未取得なので取れば検証可能。
- **skip_nf_layoff（外厩）→ 可能**: KYI位置573 放牧先 / 623 放牧先ランク(A-E)。
- **skip_kikyo（帰厩日）→ 概ね可能**: KYI位置562 入厩年月日 / 570 入厩何日前。ラスト1Fはjravan trainingかCYBと組合せ。
- **skip_oikiri_score（調教採点50点）→ 近似のみ**: CYB位置86 調教評価(◎○△3段階)。「50点」そのものではない。
- **skip_wood（調教時計）→ JRDB不要・決着済み**: [[verified_training_and_sire_popbucket]]で時計は全ゼロ。
- **C群（パドック自分の目）→ JRDB非推奨**: [[verified_jrdb_paddock_codes]]で公開馬体/気配コードは全ゼロ確定。paddock_ledgerの台帳が本筋。
- **発情/逆手前/体型/他社印 → JRDBにも無し**。skip_odds_crash/skip_morning_dropの時系列オッズは
  JRDB基準オッズ(OZ系)が参照点になりうるが、基準オッズ自体のエッジは検証済みゼロ。odds_history.dbの蓄積が本筋。

## 注意
- カタログ(core/folklore_lib.py)の verdict は **まだ更新していない**（ユーザー判断待ち）。
- 「採用方向」の3件も効果1-3ppのfade側知識であり、新しい買いシグナルではない。
  verified_folklore_effectiveness.md の「条件付き俗説研究は一旦停止」方針とも整合させること。
