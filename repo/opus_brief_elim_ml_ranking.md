# Opus案件 消去エンジン高度化 ―― 消去順を「人気」から「MLランキング(市場なし)」へ

> # 🔴 確定版の結論（2026-07-22）: **本案件は不採用。この指示書は実行しないこと。**
>
> Phase 0 の特徴パリティ検証で停止した。**下の「検証済みの事実」節に書かれた
> 「E: ML(市場なし) = -1.3pp ★採用」は誤りであり、無効。** 根拠は下記。
> app.py / core/ は一切変更していない（消去順は現行の `-人気 + 1.5*妙味 - 1.5*危険` のまま）。
>
> | 案 | holdout(2025+) こぼし率 | 対現行 | ゲート(-1.0pp) |
> |---|---|---|---|
> | 現行: 人気順 | 12.15% | — | — |
> | 当初主張 E(全43列) | 10.92% | -1.23pp | ✅ だが**無効**(下記) |
> | ライブ実装可能な最良 E4 | 11.53% | -0.63pp | ❌ |
> | ① vh2をout-of-fold化 | 11.40% | -0.75pp | ❌ |
> | ② comboをリークフリー再構築 | 11.28% | -0.88pp | ❌ |
> | 参考: リーク版combo入り | 11.15% | -1.00pp | ✅（リーク列があって初めて到達） |
>
> **なぜ当初の -1.3pp が無効か（2点）**
> 1. **combo のカバレッジ差**: `data/vh2_combo_cache.json` は2024年以降・7番人気以下しか
>    作っていない。学習期6.1% / 評価期57.1% という欠損率の断崖があり、モデルは
>    「combo欠損=学習期」を学習してしまう。単独では +2.54pp(無価値)なのに vh2 と組むと
>    標準分割で0.6pp稼ぎ、別分割では逆に0.11pp悪化＝**符号反転**（両窓一貫の原則に落ちる）。
>    さらに中身も6成分中4つがリーク（`ct.get_figure`=現在時点のH7図 /
>    `bl.lookup_sire_stats`=blood_dict.dbの全期間集計 / `jj.jockey_power`=全期間 /
>    ROI100%判定 を過去レースに適用）。
> 2. **「市場なし」が成立していない**: 唯一エッジを出している `vh2_score` は
>    `data/vh2_model.lgb` の出力で、内部に `ninki`/`log_odds` を含む。つまり本案の
>    実体は「市場情報の再表現」であり、市場非依存の新情報ではない。
>
> **決定的な事実**: ゲート(-1.0pp)に到達する変種は**リーク列を含むものだけ**だった。
> 残り41列(補正T/末脚/血統/33ラップ/騎手厩舎…)の上乗せはゼロ（E4 ≒ vh2_score単独 E6）。
>
> **再提案の禁止**: 「vh2をOOF化すれば」「comboをバックフィルすれば」は両方とも検証済みで否定。
> 検証: `scripts/elim_ml_ranking_backtest.py --phase0 / --coverage`,
> `scripts/elim_vh2_oof_backtest.py`。台帳: memory `verified_elim_ml_ranking_rejected`。
>
> 以下は当時の指示内容であり、**歴史的記録として残す**（実行対象ではない）。

> このファイルをそのままOpusに渡してよい。Opusはコールドスタート前提なので、
> 末尾の「共通コンテキスト」と「禁止事項」を必ず最初に読むこと。
> **Phase順(0→1→2→3)に進め、各Phaseの採用ゲートを通ってから次へ。
> ゲートを落ちたらそこで停止し、結果を正直に報告して指示を待つ（無理に通さない）。**

---

## 依頼の背景（人間からの要望・原文の意図）

左メニュー「🧹 消去フィルター」は2段階で頭数を絞る:
①🎯強適消去エンジン(下位半分カット+ボーダー3頭戻し) → ②🧹消去クロステーブル。

ユーザーの要望は「あまり考えずとも、過去のデータから来ない馬を自動で消してほしい」。
ボーダー3頭はカットラインの際に3着内馬が混ざるための苦肉の策と認識している。

## ~~検証済みの事実（2026-07・この指示書の根拠。再検証不要）~~ ← ⚠ **この節は誤り。無効**

> ⚠ 下表の「E: ML(市場なし) -1.3pp ★採用」は 2026-07-22 の再検証で棄却された（冒頭参照）。
> **『再検証不要』と書いたこと自体が誤りだった**: 全数値列を一括投入した結果で、
> 列ごとのカバレッジ・リーク・ライブ再現性を確認していなかった。

`scripts/elim_ml_ranking_backtest.py`（CSV特徴ストア・リークフリー）で消去順5種を比較済み:

| 消去順 | holdoutこぼし率(2025-26) | 対現行 |
|---|---|---|
| A: 人気(現行の支配項) | 12.2% | — |
| B: 能力スコア単独 | 26.9% | +14.7pp(論外) |
| C: vh2スコア | 11.6% | -0.7pp |
| D: ML(市場込み) | 11.9% | -0.3pp |
| **E: ML(市場なし)** | **10.9%** | **-1.3pp ★採用** |

- Eは別分割(train≤2022→2023-24評価)でも **-0.97pp** と再現。両窓で採用ゲート(-1pp)を満たす。
- 「同じこぼし率でもっと多く消す」は**不可能と確定**(+1頭で17.7%へ跳ねる)。
  → ボーダー3頭は正しい設計。**消去頭数もボーダー3もUIも変えない**。変えるのは並び順だけ。
- 市場込み(D)が負ける理由: オッズを特徴に入れると下位帯で人気順序をなぞる。
  下位人気帯は市場の値付けが最も雑な領域なので、オッズ非依存の特徴が効く。
- 現行の消去スコアは `app.py:10013` の
  `_score = -人気 + 1.5*(妙味材料あり) - 1.5*(危険材料あり)`。

## 成果物の全体像

LTRモデルと同じ「学習スクリプト → 凍結モデル+meta → coreモジュール → app配線」のパターン:

```
scripts/build_elim_model.py     # 学習+凍結(新規)
data/elim_model.lgb             # 凍結モデル(生成物)
data/elim_meta.json             # features/学習期間/ゲート成績(生成物)
core/elim_ranker.py             # ライブ推論(新規)。get_elim_scores(...)
app.py                          # 消去エンジンの_scoreをML優先+フォールバックに
tests/smoke.py                  # 契約テスト追加
```

---

## Phase 0: 特徴パリティの設計（最重要・ここで失敗すると全部無駄）

バックテストのEはCSVストアの**市場列(ninki/win_odds)以外の全数値列(約43列)**を使った。
しかしライブ(消去フィルターのページ)はCSVを読まず、スクレイプしたdfと
jravan.dbからその場で特徴を計算する。**オフラインと同じ値をライブで作れる列だけ**が使える。

手順:
1. `data/export/horse_races.csv` の列と `scripts/export_features_csv.py` の各列の計算式を読む。
2. 各列を3分類する:
   - **live-easy**: スクレイプ済みdf/metadataから直接取れる
     (waku_n, futan, bataiju, zogen, sex_code, age, field_size, kyori_int, surface_code, is_handi1, dist_change…)
   - **live-db**: jravan.dbから馬/騎手/厩舎キーで計算できる。消去フィルターのページが
     既に類似計算をしている列も多い(h7_fig系=corrected_time, spurt_idx系, blood_race_pct,
     jockey/trainer系, prior_top3_rate, avg_pos3, h_lap33系…)。`core/ltr_ranker.py` の
     `_prior_spurt/_prior_record/_trainer_jyo_t3` 等が流用可能な実装例。
   - **live-hard**: ライブ再現が難しい/コストが高い列(あれば除外)
3. **live-easy + live-db のみ**を最終特徴セットとして確定する。
   ⚠ `vh2_score` はvh2モデル出力で内部に市場情報を含む。ライブでは
   `core/value_hunter.score_race()` が既に動いているので使えるが、
   「市場なし」の建前が崩れる点をmetaに明記した上で採用可(Eの成績はこれ込み)。
4. `ability_score` はレース内percentile平均(h7_pct/spurt_race_pct/blood_race_pct/jk_race_pct)。
   レース内rank正規化はライブでも同じ定義で計算できる(全馬分を先に計算してからrank)。

### Phase 0 採用ゲート
確定した特徴セットで `scripts/elim_ml_ranking_backtest.py` を再実行
(_EXCLUDEに落とした列を追加するだけ)し、**holdoutこぼし率が現行比-1.0pp以上を維持**すること。
維持できなければ列を戻して原因を特定し、それでも無理なら**ここで停止して報告**
(全43列のEは-1.3ppなので、削りすぎなければ通るはず)。

---

## Phase 1: 学習スクリプトと凍結

`scripts/build_elim_model.py` を新規作成。`scripts/build_ltr_model.py` の流儀に合わせる:

- データ: CSV特徴ストア(`scripts/csv_data.load_horses()`)。**train=day≤2024のみで学習**
  (holdout 2025+は評価専用に残す。全期間学習にしない=将来の再検証可能性を守る)。
- モデル: LightGBM binary(label=top3)。パラメータはバックテストと同一:
  `objective=binary, learning_rate=0.05, num_leaves=63, min_data_in_leaf=200,
   feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, seed=7, num_boost_round=400`
- 出力: `data/elim_model.lgb` + `data/elim_meta.json`。metaには
  `features`(順序込み), `train_end`, `built_at`, `holdout_miss_rate`, `baseline_miss_rate`,
  `gate_passed` を記録。
- スクリプト末尾でholdout評価を自動実行し、ゲート成績を標準出力とmetaに残す。

### Phase 1 採用ゲート
生成したモデル+metaで、バックテストと同じholdoutこぼし率が再現すること(±0.1pp)。

---

## Phase 2: ライブ推論モジュール `core/elim_ranker.py`

`core/ltr_ranker.py` を実装例として新規作成:

```python
def available() -> bool            # モデル+meta存在チェック
def get_elim_scores(horses, race_info, precomputed=None) -> dict[int, float] | None
    # horses: 消去フィルターページが持つ per-horse dict のリスト
    # precomputed: ページが既に計算済みの値(補正T/末脚/血統/騎手系)を渡して再計算を避ける
    # 戻り値: {umaban: P(3着内)} 。特徴が作れない馬は他馬のrace内中央値で埋める
    # 例外時は None(呼び元がフォールバック)
```

設計上の注意:
- **JRA専用**。NAR(race_idの5-6桁目>10)は分布外なので `None` を返し現行ロジック継続
  (LTRがNAR別モデルにしたのと同じ理由。NAR版は将来の別案件)。
- 消去フィルターのページは既に馬ごとに補正T(_ctbest)/末脚/血統/黄金ライン等を
  計算している。**同じ値を二重計算しない**: ページの計算結果をprecomputed経由で受け取り、
  足りない特徴だけelim_ranker内でDBから引く。
- 特徴ベクトルは**必ずmeta['features']の順序**で組む(LTRと同じ流儀)。
- 欠損はNaNのままLightGBMに渡してよい(学習時もNaN含み)。

### Phase 2 採用ゲート（特徴パリティテスト）
`scripts/debug/test_elim_parity.py` を作り、CSVストアに存在する過去レース3件以上で
「オフライン特徴ベクトル vs ライブ計算の特徴ベクトル」を突き合わせる。
- 各特徴の一致率(数値は相対誤差1%以内)を列別に表示。
- **予測値の順位相関(spearman) ≥ 0.95** を合格ラインとする。
- 落ちた列は原因を直すか特徴から外す(外したらPhase 0のゲートを再確認)。

---

## Phase 3: app.py 配線と表示

`app.py` の消去エンジン(約10013行 `_score = -人気 + 1.5*_pos - 1.5*_neg`)を変更:

1. エンジン実行時に `elim_ranker.get_elim_scores()` を呼ぶ。
   - 成功時: `_score = ML予測のレース内順位を反転した値 + 1.5*_pos - 1.5*_neg`
     ※ **±1.5の検証済みファクター補正は残す**(黄金ライン/厩舎当コース等の妙味材料と
     危険材料。バックテストEは純ML順位だが、これらは独立検証済みのため保持。
     ただし後述の(2)でこの設計自体を検証すること)。
     ※ MLの生予測値でなく**レース内順位**を使う理由: ±1.5補正と足すため尺度を揃える。
     順位は `-(rank)` で「良い馬ほど大きい」に合わせる(現行の-人気と同じ向き)。
   - 失敗/NAR/モデル無し時: 現行の `-人気` にフォールバック(挙動完全維持)。
2. **配線前に必ず**「ML順位+±1.5補正」の合成が「純ML順位」より悪くないかを
   バックテストで確認する(elim_ml_ranking_backtest.pyに合成variantを1本追加)。
   ±補正で-1ppゲートを割るなら補正は捨てて純MLにする(データが決める)。
3. UI表示:
   - エンジン見出し直下のcaptionに「消去順: 🤖ML(検証済・こぼし12.2→10.9%)」or
     「消去順: 人気(MLフォールバック)」を明示。ユーザーがどちらで動いたか分かること。
   - 表に「ML順位」列を追加(既存列は変更しない)。
   - ボーダー3頭・穴1頭救出・危険人気馬検知・消去クロステーブル(②)は**一切変更しない**。
4. `write_elim_verdict_snapshot`(新聞連携)は判定列をそのまま使うので変更不要のはず。
   変わらないことをテストで確認。

### Phase 3 採用ゲート
- `tests/smoke.py` 全合格(既存を1件も壊さない)。
- 追加するsmokeテスト:
  - `elim_ranker.available()` False時のフォールバック(モデルファイルをリネームして確認)
  - NAR race_idでNoneを返すこと
  - meta['features']の順序で組んだダミー入力で予測が返ること
  - `gate_passed` がmetaでTrueであること(モデルの鮮度契約)
- 実レース1件(スナップショットのある202609011010等)でUIを実際に開き、
  ML順位列とcaptionが表示されることをスクショで目視確認。

---

## 採用ゲートまとめ（どれか落ちたら停止・報告）

| Phase | ゲート |
|---|---|
| 0 | live化可能な特徴だけでholdoutこぼし率 現行比-1.0pp以上 |
| 1 | 凍結モデルでバックテスト成績が再現(±0.1pp) |
| 2 | 特徴パリティ: 予測の順位相関≥0.95 |
| 3 | smoke全合格+フォールバック動作+UI目視 |

## 禁止事項

- **消去頭数・ボーダー3頭・穴1頭救出・消去クロステーブル(②)のロジック変更**。
  今回変えるのは①の並び順だけ。「もっと多く消す」は検証済みで不可能と確定している。
- 学習にholdout(2025+)を混ぜること。全期間学習も禁止(再検証可能性が消える)。
- requirements.txtにないライブラリの追加(LightGBMは既存)。
- 特徴にリーク(当該レースの結果・当日以降の情報)を混ぜること。CSVストアの列は
  leak-free保証済みだが、**ライブ側で自作する特徴は必ずbefore_key/日付フィルタを掛ける**
  (`core/jockey_jv.py`の`before_key`パターン参照)。
- ゲートを落ちたのに「概ね動く」として配線すること。落ちたら停止して報告。
- Projected Score / LTR / 買い目 / 合議など消去フィルター以外への影響。
  elim_rankerの出力は消去フィルターページ内で完結させる。

## 共通コンテキスト（コールドスタート用）

- 環境: Python 3.13 / Streamlit / Windows / UTF-8(BOMなし)。DBは data/jravan.db(SQLite・読み取りは `file:...?mode=ro`)。
- CSV特徴ストア: `data/export/horse_races.csv`(25万行×53列・全列leak-free)。
  ローダー `scripts/csv_data.py`。**オフライン研究専用・ライブ推論には使わない**。
  再生成は `python scripts/export_features_csv.py`(約6分)。
- 期間の慣例: train=≤2024 / holdout=2025 / recent=2026-03-21以降。
- 検証の慣例: 両窓(train系とholdout)で符号一致+有意のみ採用。1レースの観察から
  閾値を動かさない。落ちた検証も「やった証拠」としてスクリプトを残す。
- 参考実装: `core/ltr_ranker.py`(ライブ推論の型), `scripts/build_ltr_model.py`(学習の型),
  `scripts/elim_ml_ranking_backtest.py`(今回の検証・変種の追加はここに),
  `app.py` 9738行付近〜(消去エンジン本体。`_ekey`/`_erows`/`_edf`)。
- 検証台帳(メモリ):
  `C:\Users\kimnhaty\.claude\projects\c--Users-kimnhaty--gemini-antigravity-scratch-keiba-analysis\memory\`
  (索引=MEMORY.md)。関連: verified_keepone_border(ボーダー3は代替不能),
  elim_frontier(フラグ加重は却下), verified_elimination_engine系。
- 完了したらメモリに `project_elim_ml_ranking.md` を書き、MEMORY.mdに1行追加すること
  (採用ゲートの実測値・フォールバック設計・NARは対象外である旨を含める)。
