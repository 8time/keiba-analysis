# Fable案件① 妙味馬ハンターの再現率を50%→70%へ

> このファイルをそのままFableに渡してよい。Fableはコールドスタート前提なので、下の
> 「共通コンテキスト」を必ず最初に読み込むこと。

---

## 依頼（人間からの要望・原文の意図）
現在の妙味馬ハンターは「7番人気以下で3着内に来る馬」の**約半分（49〜54%）しか拾えない**。
だが**人間の予想家は実現できているはず**——言語化はできないが、視覚から大量の情報（パドック、
馬体、隊列、脚色、馬場の傷み方など）を読み取り、脳内で無意識に計算していると思われる。
**捕捉できない半分を捨てず、再現率7割を目指したい。** その「言語化されていない視覚情報」を
数値特徴として発掘・追加し、combo方式の天井を破ることがゴール。

## 現状（このアプリの到達点＝ベースライン）
- 対象母集団: JRA平地・7番人気以下。ベース3着内率 = **train 7.7% / 直近3ヶ月 7.2%**。
- 現行「combo」= 検証済み6シグナルの同時発火数。各シグナルは各レース内で相対上位を取る二値:
  `🔵補正T(field top3)` `🧬血統スコア(top3)` `🧬血統回収100%+` `🔥末脚指数(top3)`
  `⚡33ラップ適合` `👑騎手力(top3)`。
- comboは3着内率と完全に単調（リーク無し検証・`scripts/value_longshot_research.py`）:

  | combo | train 3着内 | 直近3ヶ月 | 母数(train) |
  |---|---|---|---|
  | 0 | 4.1%（基準の半分） | 3.4% | 16,348 |
  | 1 | 7.2% | 6.2% | 22,677 |
  | 2 | 9.9% | 9.7% | 13,936 |
  | 3 | 13.1% | 12.8% | 4,712 |
  | 4 | 18.8% | 14.6% | 1,038 |
  | 5 | 20.0% | 15.0% | 145 |

- **精度/再現率のトレードオフ（＝今回破りたい壁）**:
  - combo≥2: 再現率 **train49% / 直近54%**、精度 11.2%/10.7%（基準の約1.5倍）。
  - combo≥1: 再現率 85%/89% だが精度は基準とほぼ同じ（緩すぎてショートリストの意味なし）。
  - **combo=0の好走馬が train14.8% / 直近11.4%** 存在＝6シグナルが1つも発火しない好走。
    現方式では原理的に事前予測不能な層（純粋な展開のアヤ・馬場激変など）。

## ゴール（成功条件）
7番人気以下の3着内馬の**再現率 ≈ 70%** を、**精度を意味あるレベル（≥ 基準の1.35倍・目安10%以上）
に保ったまま**達成する特徴セット/モデルを提示する。単に緩めて再現率を上げる（＝combo≥1の轍）は不可。
recall@k と precision の両方を1本のカーブで示し、現行combo≥2から上振れしていることを証明する。

## 攻め筋の仮説（Fableは検証してから採否を決める＝verify-first）
「人間が視覚から読む＝現6シグナルに無い情報」を数値化する方向。候補（要leak-free検証）:
1. **二値top3を連続量/top5へ緩和**: 補正T・末脚・血統を「レース内順位比率」や「z」で連続特徴化し、
   top3の崖で落ちていた惜しい馬（combo1に埋もれる好走）を拾う。
2. **展開・位置取りの相性**: `core/pace_map.py`の隊列位置・差し切り限界ライン(sashikiri_table)・
   マクリ・テン速力zを特徴化。※過去検証で「展開恩恵の買い」はpriced-in（[[verified_tenkai_priced_in]]）
   なので、**残差が出るのは"末脚×展開が向く人気薄"等の交互作用**に限る想定。必ず残差で確認。
3. **クラス替わり/条件替わり**: 昇級/降級・距離延長短縮・初コース。単体はpriced-in報告が多いが
   （[[verified_folk_signals_overbet]]）、combo0好走の一部を説明するか交互作用で再検証。
4. **馬体/パドック台帳**: `core/paddock_ledger.py`の観察タグ（貯まっていれば）。
   定量馬体重は買い妙味ゼロ（[[verified_paddock_weight]]）だが視覚タグは未検証。
5. **ランキングモデル化**: 二値フラグの足し算(combo)でなく、7番人気以下×3着内を正例とする
   **recall@k最適化のLTR**を学習し既存LTRとブレンド。ハーネスは `scripts/auto_feature_search.py`
   （既存LTRを壊さず包み、recall@7でadd/drop探索・[[project_auto_feature_loop]]）を土台に、
   ターゲットを「7番人気以下の3着内」に差し替えて特徴探索する。
6. **交互作用項**: 補正T×位置取り、末脚×馬場、血統×距離替わり 等。単体priced-inでも交互作用に
   残差が残る例が既にある（[[verified_baba_blood]]の米国型×稍重ダ×人気上位など）。

## 制約・作法（厳守）
- **リーク厳禁**: すべて各レース時点`before_key`以前の履歴のみ。kyakushitsu(結果脚質)/
  通過順の当該レース値/win_odds確定後情報は特徴に使わない（位置取りは過去平均のみ）。
- **priced-in判定**: 「市場（人気）を超えるか」は人気別ベース3着内率からの**残差z**で見る。
  単に率が高いだけの特徴は人気の裏返しなので不採用。
- **検証窓**: train ≤2024 / holdout=2025 / 直近3ヶ月(2026-03-21〜2026-06-21)でも崩れないこと。
- **正直さ**: combo0の予測不能層（〜12-15%）は天井として明記。7割が無理なら「どこまで可能か」を
  精度とのトレードオフ曲線で正直に返す（過大約束しない＝有料販売を想定）。

## 成果物
1. `scripts/value_hunter_recall_v2.py`（新規・leak-free・上記母集団で precision-recall を出力）。
2. 推奨特徴セット（採用/不採用と各々の残差z・holdout安定性）。
3. recall/precision カーブ（現行combo≥2の点を重ねて上振れを図示）。
4. 実装提案（`pages/anabaka_hunter.py`のcombo算出をどう置換/拡張するか）。既存の
   `core/consensus_view.build_edge_sets()`のedge_reasons/comboを土台に増分する形が望ましい。

---

## 共通コンテキスト（Fableは必ず読む）
- **アプリ**: 競馬分析Streamlit（`app.py`・約13,000行）。Python 3.13 / Windows / UTF-8。
- **DB**: `data/jravan.db`（SQLite・JRA-VAN実データ）。パスは `core/jockey_jv.JV_DB_PATH`。
  **凍結中**（ライセンス都合で最新race_key = 2026-06-21が上限。派生モデル再構築で新規情報は増えない）。
  主要テーブル:
  - `races(race_key, year, monthday, jyo, hasso_time, kyori, surface, track_code, tenko,
    baba_shiba, baba_dirt, shusso_tosu, juryo(1=ハンデ), kigo, grade, race_name ...)`
  - `results(race_key, umaban, waku, ketto_num, chakujun, ninki, win_odds, futan(斤量0.1kg単位),
    bataiju(馬体重), zogen, age, jockey_name, trainer_code, kyakushitsu(結果脚質=リーク源),
    ato3f, corner1..corner4, blinker ...)`
  - `horses(ketto_num, sire, bms, sex, birth, dam ...)`
  - ※風速/風向・複勝オッズ・オッズ時系列・馬主列はDBに無い（[[verified_wind_no_effect]]で風はOpen-Meteo
    archiveから別取得しdata/wind_archive_cache.jsonにキャッシュ済み）。
- **検証規約**: race_key文字列を`before_key`として各馬の履歴を厳密に過去へ限定。train/holdout分割。
  効果は「人気/市場を統制した残差z」で判定（率の高低だけでは priced-in と区別不能）。
- **既存の検証済みエッジ（土台にできる）**: 補正T(`core/corrected_time.py`)・血統
  (`core/bloodline.py`)・末脚指数・33ラップ(`core/lap33.py`)・騎手力(`core/jockey_jv.py`)・
  消去クロス(`core/elim_cross.py`)・妙味スキャナ(`core/value_scanner.py`)・軸選定
  (`core/axis_selector.py`)・展開(`core/pace_map.py`)。関連バックテストは`scripts/*_backtest.py`。
- **参考スクリプト**: `scripts/value_longshot_research.py`（本案件の元になった7番人気研究）、
  `scripts/revival_backtest.py`（leak-freeなcombo/elim算出の機構）、`scripts/auto_feature_search.py`
  （recall@kの特徴探索ハーネス）。
- **哲学**: verify-first。ヒューリスティックは必ずバックテストしてから実装。priced-in/リークは正直に区別。
