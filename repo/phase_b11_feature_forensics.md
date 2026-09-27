# B11 feature forensics

分類の正本は `research/historical/feature_classes.py` と `data/research/advanced/feature_registry.json`。

## モデルに入れてよいもの

`SAFE_PRE_RACE` のみ。馬の属性、単勝オッズ、人気、shift(1) の能力・騎手・厩舎・消去フラグ数、レースの vscore とオッズ構造。

## 入れないもの

- `LABEL_ONLY`: `chakujun`, `top3`, `win`、着順から作った `arareA/B`, `ana2`, `honsen`, `ninki_top3_logsum`
- `UNCERTAIN`: `combo` と combo 集計（2024年以降の人気薄キャッシュだけ）
- Projected Score / ScoringSignal / スクレイパ `PastRuns` は CSV に無い。代理は作っていない。

## オッズの時点

`win_odds` は JV の確定単勝オッズである。購入ボタンを押す時点のオッズだと確認していない。したがって Historical ROI は、発走前に同じ価格で買えたことの証明ではない。

## 市場の強さ（2016–2025、記述統計）

レース内で `1/odds` を合計 1 に正規化した確率は、オッズ帯の実勝率とほぼ一致する。その帯を単勝で買う ROI はおおよそ 59–83% で、短いオッズほど控除後も 80% 前後に張り付く。長いオッズ帯はさらに低い。
