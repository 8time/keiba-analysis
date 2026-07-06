# Fable案件② 全データCSV化 → レーススキャナー（荒れ予報）の精度改善

> このファイルをそのままFableに渡してよい。Fableはコールドスタート前提なので、下の
> 「共通コンテキスト」を必ず最初に読み込むこと。

---

## 依頼（人間からの要望・原文の意図）
このアプリのデータを**全てCSV化**し、それを使って**レーススキャナー（荒れ予報）の精度を改善**する。
**約1年間**の期間でテスト。我々人間には「ただの数字」にしか見えないが、**全てを数値化して比較すれば、
荒れるレースと荒れないレースの違い**が見えてくるかもしれない。レース単位で全特徴を並べ、
荒れ/非荒れの分布を突き合わせて、現行スキャナーが取りこぼしている判別軸を探す。

## レーススキャナーとは（改善対象）
`core/value_scanner.py`:
- `race_value_score(odds_list, meta, jyo, surface, dist, n_horses, ...)` → **妙味度 0〜100 と
  ラベル S/A/B/C/D**（荒れ期待度）。
- `trio_lean(meta, n_horses, fav_odds, pace_z, ...)` → **`②穴妙味向き` / `本線向き` / `中立`**
  のレジーム判定。アプリ全体（強適テーブル・買い目・統合ビュー）の分岐に使われる。
- `no_favorite_flag(odds_list)` → オッズ本命不在（●大穴）判定。
これらが「このレースは荒れる/堅い」を事前に当てられているか、が改善対象。

## 現状（既に検証済みの荒れ条件＝土台）
`scripts/condition_arare_backtest.py` / `scripts/roi_pattern_backtest.py` 等で検証済み。
オッズを超える独立エッジとして生き残っているのは:
- **ハンデ戦**（juryo=1）: ②型荒れ +7.9pp（z5.2）。
- **フルゲート16頭**: z5.9。
- **オッズ本命不在（大谷等価）**: 荒れ83% / z5.5(2025) z5.2(2026)。ハンデ/16頭と独立
  （[[verified_arare_entropy]]）。`no_favorite_flag`= fav1オッズ≥3.0 & odds3/odds1≤2.0 & 30倍未満≥10頭。
- **少頭数8-10頭**: 本線堅（+8.4pp）。
- 牝馬限定/ダートは荒れやすいが**人気に織込み済み**（検索絞りのみ・買い妙味なし）。
- **単勝ROIは全条件・全オッズ帯で控除割れ**（[[verified_tansho_roi_efficient]]）。
  →スキャナーは「ROIで勝つ予測器」ではなく**レース選択器/レジーム判定器**。ここは死守。

## 仮説（今回掘りたいところ＝人間に見えない数値差）
現行は主に「オッズ構造＋頭数＋ハンデ」で荒れを判定している。**出走馬の実力/適性の"ばらつき"を
レース単位に集計した特徴**が、荒れ/非荒れをさらに分けるのではないか。候補（要leak-free検証）:
- **オッズ・エントロピー / 上位人気の断層**（1〜3番人気の信頼オッズ差、実効頭数）。
- **フィールド内スプレッド**: 補正T・血統スコア・末脚指数・騎手力・強適スコアの**標準偏差/レンジ/
  上位2頭差**。実力が拮抗（低スプレッド）＝荒れ、突出馬あり（高スプレッド）＝堅、という仮説。
- **combo馬の頭数**: 7番人気以下でcombo≥2の人気薄が何頭いるか（案件①の産物）。多い＝荒れ余地。
- **展開の型**: 逃げ候補数・前向き率（`pace_map.build_pace_context`）・ハイ/スロー。多頭数のハナ争い
  ＝ハイ＝差し台頭＝荒れ、等。
- **クラス/距離/馬場/コース形状**との交互作用。
これらを1レース=1行に集約し、**荒れ/非荒れの2群で分布を比較 → 判別に効く軸を残差/AUCで特定**。

## 「荒れ」の定義（Fableが選び、根拠を明記）
候補（複数を並行評価してよい）:
- (A) 3着内に7番人気以下が1頭以上入る（＝妙味馬が絡む＝案件①と直結）。
- (B) 勝ち馬が6番人気以下。
- (C) 3連単配当が上位xパーセンタイル（配当列がDBに無ければ着順×人気から近似、または要注記）。
まず(A)を主指標に。市場（人気）が既に織り込む分を超えて当てられるかを見るため、
**「人気だけで作った荒れ確率のベースライン」からの上振れ（残差/z・AUCゲイン）**で評価する。

## 進め方
1. **CSV書き出しスクリプト** `scripts/export_features_csv.py` を新規作成:
   - **馬行CSV** `data/export/horse_races.csv`: 1行=1馬×1レース。全シグナル（補正T/血統/末脚/33/
     騎手/消去/位置取り/combo）＋事前確定属性（ninki, win_odds, 馬体重, 斤量, 枠, 齢, 性）＋
     結果（chakujun, top3, win）。すべてleak-free（before_key履歴）。
   - **レース行CSV** `data/export/races.csv`: 1行=1レース。上記の**フィールド集約**（各シグナルの
     mean/std/max/top2差、オッズエントロピー、combo馬数、頭数、ハンデ、頭数、距離、馬場、コース、
     展開型）＋荒れラベル(A/B/C)。
   - 期間は約1年（例 2025-06-22〜2026-06-21）をholdout、それ以前をtrainに。CSVは`data/export/`へ
     （`data/`はgitignoreなので巨大でも安全）。
2. **レース単位の荒れ判別バックテスト** `scripts/scanner_arare_v2.py`:
   - races.csvで、現行`race_value_score`/`trio_lean`のラベルと実荒れの一致（confusion/AUC）をまず測定。
   - 次に上記フィールド特徴を足したモデル（ロジスティック/GBTでよい）で**AUC/precision@kが
     人気ベースライン＋現行スキャナーを上回るか**を1年holdoutで検証。
3. 効いた特徴だけを`value_scanner`へ配線する提案（率の改善幅とz付き）。効かなければ「現行維持が正解」
   と正直に結論（[[verified_pci_pricedin]]のような打ち切り前例あり）。

## 制約・作法（厳守）
- **リーク厳禁**（before_key履歴のみ・結果脚質/通過順/確定オッズ後情報は不可）。
- **priced-in判定**: 人気だけで作った荒れ確率を必ずベースラインに置き、その上振れで評価。
- **1年holdout**（直近1年）で崩れないこと。train期間で過学習した特徴は不採用。
- **正直さ**: 多くはpriced-inの可能性が高い（市場は荒れやすさもある程度織り込む）。「フィールド構造が
  市場を超えて荒れを当てる」ことを示せた分だけ採用。過大約束しない（有料販売を想定）。
- スキャナーの位置づけ（ROI予測器ではなくレース選択/レジーム判定器）を変えない。

## 成果物
1. `scripts/export_features_csv.py`（馬行＋レース行CSV書き出し・leak-free）。
2. `scripts/scanner_arare_v2.py`（現行スキャナー vs +フィールド特徴の荒れ判別・1年holdout・AUC/precision）。
3. 効いた特徴の一覧（残差z・holdout安定性）と`value_scanner`への配線提案、または現行維持の結論。

---

## 共通コンテキスト（Fableは必ず読む）
- **アプリ**: 競馬分析Streamlit（`app.py`・約13,000行）。Python 3.13 / Windows / UTF-8。
- **DB**: `data/jravan.db`（SQLite・JRA-VAN実データ）。パスは `core/jockey_jv.JV_DB_PATH`。
  **凍結中**（最新race_key = 2026-06-21が上限）。主要テーブル:
  - `races(race_key, year, monthday, jyo, hasso_time, kyori, surface, track_code, tenko,
    baba_shiba, baba_dirt, shusso_tosu, juryo(1=ハンデ), kigo(牝馬限定=kigo[1]='2'), grade, race_name ...)`
  - `results(race_key, umaban, waku, ketto_num, chakujun, ninki, win_odds, futan(斤量0.1kg),
    bataiju, zogen, age, jockey_name, trainer_code, kyakushitsu(結果脚質=リーク源), ato3f,
    corner1..corner4, blinker ...)`
  - `horses(ketto_num, sire, bms, sex, birth, dam ...)`
  - ※複勝オッズ・オッズ時系列・馬主列・風速はDBに無い（配当列も無い→荒れ(C)は着順×人気で近似）。
- **検証規約**: race_key文字列を`before_key`として履歴を過去へ限定。train/holdout分割。効果は
  「人気/市場を統制した残差z・AUCゲイン」で判定。
- **既存モジュール**: `core/value_scanner.py`（本案件の対象）、`core/corrected_time.py`・
  `core/bloodline.py`・`core/lap33.py`・`core/jockey_jv.py`・`core/elim_cross.py`・
  `core/pace_map.py`（フィールド特徴の材料）。
- **参考スクリプト**: `scripts/condition_arare_backtest.py`（荒れ条件検証）、
  `scripts/roi_pattern_backtest.py`（単勝ROIは効率的と確認）、`scripts/revival_backtest.py`
  （leak-freeなシグナル算出機構）、`scripts/value_longshot_research.py`（combo研究）。
- **哲学**: verify-first。効かない仮説は打ち切って正直に報告する（PCI/風の打ち切り前例あり）。
