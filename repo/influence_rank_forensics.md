# 影響率の実装（コード追跡）

## 場所

`app.py` の SRA ブロック。スライダーは `score_weights_main` に入り、`.score_weights_main.json` に保存される。

## 式

各指標をそのレースの最小・最大で 0–100 に伸ばす。小さいほど良い列（人気、上がり、補正T、斤量、位置）は向きを反転する。欠測は 0 扱いになりうる（`_safe_float`）。

`final = (BattleScore * Base + 各正規化値 * weight) ` からストレス減点を引く。その後、`TopBattleBonus` とセーフティネットが予測スコアをさらに動かす。

Rank は予測スコアの降順。同点の扱いは pandas のソート依存で、専用のタイブレークは無い。

## 今のファイル上のウェイト

ゼロでないのは `Base=1.0`、`Popularity=1.5`、`ScoringSignal=1.0`、`JPowerTop3=0.1`。他は 0。範囲は UI 上おおよそ 0–300（ボーナス）で、負のウェイトも JSON には書けるが、現行値は非負。

## 本番 Rank への経路

この合成が `Projected Score` を上書きし、`score_cache` の `proj` になる。券面の C ランクは別系統の LTR で、このウェイトそのものではない。

## Historical で使えないもの

`ScoringSignal`、`NIndex`、`LaboIndex`、調教、`JPower`、`Lap33`、`PastRuns` 由来の BattleScore は出馬表スクレイプ依存。CSV に同じ列は無い。代理では置換しない。
