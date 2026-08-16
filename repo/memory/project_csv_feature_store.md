---
name: project-csv-feature-store
description: CSV特徴ストア。data/export/horse_races.csv(25万行×53列・全leak-freeシグナル済)+races.csv(18k×82列)。scripts/csv_data.pyローダーでバックテストを分→秒(実証275倍)。オフライン研究専用
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

Fable案件②(CSV化)の副産物を恒久資産化(2026-07)。「DB→毎回leak-free再計算(分)」を「CSV→数秒」に置換。

**成果物(data/export/・gitignore・再生成 python scripts/export_features_csv.py 約6分)**:
- horse_races.csv: 251,629行×53列。1馬×1レース。全leak-freeシグナル(補正T h7_fig/h7_rank/h7_pct・
  末脚 spurt_idx/race_pct/mean3・血統 sire_surf_t3/sire_dist_t3/bms_surf_t3/blood_race_pct・
  33 h_lap33/course_l33/lap_fit_bin・騎手厩舎 jockey_form_t3/jockey_jyo_win/jockey_dist_win/
  trainer_form_t3・位置 avg_pos3/pos_ratio3・近走 prior_top3_rate/margin_best3/days_since・
  elim_n・combo(2024+×7番人気以下のみ付与)・ability_score・vh2_score)+事前属性+結果(chakujun/top3/win)。
- races.csv: 18,243行×82列。1レース1行。オッズ構造(odds_entropy/eff_n/fav1/r21/r31/live10/30/mid515)・
  実力拮抗度(各シグナルのstd/top2差)・combo穴馬数・展開型・現行スキャナー出力・荒れラベル5種。

**ローダー scripts/csv_data.py**: load_horses(pop_min/cols)/load_races/add_period(train≤2024/
holdout2025/recent≥20260321)/base_top3_by_ninki/resid_z。cols指定で列を絞ると更に速い。
各スクリプトが特徴を再実装しない=**パリティずれも構造的に消える**(過去のcombo再現キャッシュ問題や
is_handicapバグの再発防止)。新バックテストは `from scripts.csv_data import load_horses` の数行+数秒。

**実証 scripts/value_longshot_csv.py**: DB版value_longshot_research(~180秒)を0.65秒で再現(約275倍)。
ベース3着内率(train7.7%/recent7.2%)・combo単調(0=4→4=18%)がDB版と一致(recentはcombo完全付与でほぼ完全一致)。

**⚠限界**: オフライン研究・バックテスト専用(凍結DBスナップショット)。**ライブ推論には使わない**(当日は
アプリがスクレイプ+履歴からその場計算=[[project_value_horse_hunter]]の軽量式/value_scanner.arare_prob)。
53列に無い新特徴は再エクスポートかDB再計算が要る。用途拡大: 複数AIに配る集合知/AutoML/可視化/
auto_feature_search高速化。関連: [[project_auto_feature_loop]]・scanner_arare_logit(Fable案件②)。
