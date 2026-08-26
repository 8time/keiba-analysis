---
name: verified-folklore-effectiveness
description: 俗説有効度0〜100は作らない。俗説は生の的中ではなく残差で読む。少頭数×先行の1セルも市場を超えない
metadata:
  node_type: memory
  type: reference
---

俗説ハンターは「世間の話を数える」実験場で、予想スコアには足していない。
次にやりたかったのは「今回のレースで信用してよい俗説」を一本の有効度にする案。
先に数字を作り、holdout で単調なら画面、という順にした。

## 有効度は凍結

`scripts/folklore_effectiveness_backtest.py`（指示書 `repo/brief_folklore_effectiveness.md`）。

- 類似度は train で S3 freeze（S2 とほぼ同点）
- holdout の五分位は単調に見えるが、レース単位 Spearman は **+0.078**
- 俗説別 Spearman はすべて ≈0。並んで見えたのは「どの俗説か」で、レース環境ではない
- Q5 の実現残差は **+0.22pp**。0〜100 の「有効度78」を出す坂がない
- 同日前トラックバイアス（D）は C を上回らない（同一母集団 Spearman 差 −0.0001）。機能化しない

**Why:** 謎の78点を作るより、妙味度・穴馬ハンターに計算資源を使う。
失敗しても、俗説の生データが市場評価と混ざっている、という発見は残る。

**How to apply:** 有効度UIは作らない。Rank / 穴馬 / 3連単に足さない。

## 読むときの主指標は残差

例（holdout 2025・先行）:

- 生の3着以内の差 **+8.3pt**
- 人気をならしたあと **−0.23pt** → 市場以上の優位性なし

逃げも同じ型（生 +9.5pt / 残差 −0.89pt）。休み明けは生も残差もマイナス。

画面（`pages/folklore_hunter.py`）は、この読み方を出すだけ。新しい得点ではない。
既存の [[verified_front_runner_overbet]] / [[verified_weight_video_claims]] と同じ見方。

## 1セル（少頭数×先行）も打ち切り

条件探しを続けるかの最後の1本。セルは先に固定（`repo/brief_senko_small_field.md`）。

| 固定 | 値 |
|---|---|
| 先行 | `pos_ratio3 <= 0.28` |
| 少頭数 | `field_size <= 11` |
| 採否 | 少頭数の中の人気ベース（B_cell）で +3.0pp |

覗き見あり: 探索表示では holdout の B_global が **+5.55pp** だった。
少頭数は 3/N で全馬の複勝が上がる。B_global のプラスはインフレ。

| | train | holdout | recent |
|---|---:|---:|---:|
| CELL B_cell | +0.04pp | **+1.60pp** | −0.80pp |
| CELL−COMP | +0.04pp | **+1.53pp** | −0.95pp |
| train年プラス | 4/9 | — | — |

採否4条件のうち、holdout +3.0pp と CELL−COMP +3.0pp が未達。**打ち切り。**

**Why:** 「少頭数なら先行が効く」は、頭数の底上げを除くと残らない。
recent は符号すら逆。2セル目を探さない。

**How to apply:** 条件付き俗説の研究は一旦止める。`small_field_closer` もこの結果では触らない。
計算資源は妙味・穴馬へ。
