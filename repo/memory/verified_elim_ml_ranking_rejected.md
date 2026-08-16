---
name: verified_elim_ml_ranking_rejected
description: 消去順を人気→ML(市場なし)に置換する案は不採用。Eの-1.3ppはcomboのカバレッジ差とvh2_score(=市場込み)の産物だった
metadata: 
  node_type: memory
  type: project
  originSessionId: 423e3727-3223-4cca-9421-07a73ee06686
  modified: 2026-07-21T22:31:44.671Z
---

repo/opus_brief_elim_ml_ranking.md（強適消去エンジン①の消去順を「人気」→「ML(市場なし)」に差し替える案件）を Phase 0 で停止・**不採用**（2026-07-22）。ゲート未達のため app.py は一切変更していない。検証は `scripts/elim_ml_ranking_backtest.py --phase0` / `--coverage`。

**指示書の前提が誤っていた**。指示書は「E: ML(市場なし)= holdout こぼし率10.9%（現行12.2%に対し-1.3pp）」を再検証不要の既定事実としていたが、列グループのアブレーションで内訳を割ると:

| 変種 | 標準分割(train≤2024→2025+) | 代替分割(train≤2022→2023-24) |
|---|---|---|
| A: 人気(現行) | 12.15% | 12.16% |
| E: 全43列 | 10.92% (-1.23pp) | 11.19% (-0.97pp) |
| E1: live列のみ(combo/vh2抜き) | 16.42% (**+4.27pp**) | 17.81% (+5.65pp) |
| E4: live + vh2_score | 11.53% (-0.63pp) | 11.08% (-1.08pp) |
| E6: **vh2_score 単独** | 11.57% (-0.58pp) | 10.97% (-1.19pp) |

- **combo はカバレッジ差の幻**: data/vh2_combo_cache.json は2024年以降・7番人気以下しか作っていない → 学習期6.1% / 評価期57.1%。単独では +2.54pp(無価値)なのに vh2 と組むと標準分割で0.6pp稼ぎ、別分割では逆に0.11pp悪化＝符号反転。両窓一貫の原則に落ちる。
- **「市場なし」は元から成立していない**: 唯一効いている vh2_score は data/vh2_model.lgb の出力で内部に ninki/log_odds を含む。しかも fit≤2023/val2024 なので代替分割(eval2023-24)は vh2 にとって in-sample＝甘い。正味は標準分割だけを読む。
- **残り41列は上乗せゼロ**: E4(42列) ≒ E6(vh2_score 1列)。ライブ特徴パリティ（h7_fig の較正表、血統ローリング、33ラップ、騎手厩舎ローリング…）を実装する労力に対して得るものが無い。
- 結論: ライブ実装可能な最良版は標準分割 -0.63pp で採用ゲート(-1.0pp)未達 → **消去順は現行の `-人気 + 1.5*妙味 - 1.5*危険`(app.py の強適消去エンジン)のまま**。

**救済案2件も棄却**（`scripts/elim_vh2_oof_backtest.py`・train2018-2024→eval2025+）。自作vh2入力の再現度は凍結vh2_scoreとspearman 0.9900＝入力再構成は正しい。

| 変種 | こぼし率 | 対現行 |
|---|---|---|
| F1: live+vh2(凍結) | 11.28% | -0.88pp |
| F2: live+**vh2_oof** | 11.40% | -0.75pp |
| F3: vh2_oof 単独 | 11.46% | -0.69pp |
| F4: live+vh2_oof+**combo_lf** | 11.28% | -0.88pp |
| F5: live+combo_lf(vh2抜き) | 16.78% | +4.63pp |
| F6: live+vh2_oof+combo(リーク版) | 11.15% | **-1.00pp ✅** |

- ① **OOF化しても改善しない**（-0.75pp、凍結版-0.88ppより僅かに悪い）。「in-sample歪みが足を引っ張っている」という仮説は棄却。年ごとexpanding window（target年Yは year<Y のみで学習・round数は凍結モデルのbest_iteration=112固定）で作成。
- ② **キャッシュ済みcomboは6成分中4つがリーク**（`ct.get_figure`=現在時点のH7図 / `bl.lookup_sire_stats`=blood_dict.dbの全期間集計 / `jj.jockey_power`=全期間 / ROI100%判定を過去レースに適用）。CSVのleak-free列だけで作り直した combo_lf は上乗せ+0.13ppのみ、単体では+4.63pp（live列の連続量と情報が重複）。
- **ゲート(-1.0pp)に到達する唯一の変種がリーク版combo入り** ＝ 元の-1.23ppが本物でなかったことの決定的裏付け。

**How to apply**: 「消去順をMLに置き換えれば取りこぼしが減る」は再提案しない。「vh2をOOFにすれば」「comboをバックフィルすれば」も検証済みで否定。ボーダー3頭が正しい設計であることは変わらない([[verified_keepone_border]])。**教訓＝CSV特徴ストアの列は全部が同じ品質ではない**: combo のように後付けで一部期間だけ埋めた列、vh2_score のように別モデル出力（学習窓つき・市場情報入り）の列がある。バックテストで「全数値列を突っ込む」時は必ず列グループのアブレーションと train/eval カバレッジ(`--coverage`)を見ること。[[project_csv_feature_store]] / [[project_elimination_engine]] / [[project_value_horse_hunter]] 参照。
