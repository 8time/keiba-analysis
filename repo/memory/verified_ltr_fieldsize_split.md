---
name: verified-ltr-fieldsize-split
description: 頭数でLTRモデルを分割する案は棄却(全体-0.04pp)。帯別の上乗せムラは分割では回収できない
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-08-02T19:57:08.337Z
---

「少頭数/多頭数でモデルを分けろ」(NotebookLM資料・帆楼氏記事)を検証 → **棄却**。

診断では帯間にムラが実在した(勝ち馬recall@7の人気superiority):
- 少頭数(〜9頭) 1,102R: +0.27pp
- 中間(10-12頭) 2,236R: **+1.52pp**
- 多頭数(13頭〜) 3,714R: +0.54pp
- 帯間差 1.25pp

しかし帯別に学習した専用モデルと単一モデルを同じholdoutで比較すると改善しない:
- 少頭数 0.9909 → 0.9909 (+0.00pp)
- 中間   0.9732 → 0.9705 (**-0.27pp**)
- 多頭数 0.8953 → 0.8961 (+0.08pp)
- **全体加重 0.9349 → 0.9345 (-0.04pp)**

解釈: ムラは「帯ごとに別の重みが要る」のではなく**帯ごとの難易度差**。
分割すると各モデルの学習データが減るぶん悪化し、相殺してマイナス。
`field_size` は既にFEATURESに入っており、単一モデルが内部で帯を扱えている。

運用コスト(モデル2倍・推論分岐)に見合わないので**単一モデル維持**。再提案しない。
scripts/ltr_fieldsize_split_backtest.py (--train で再現可)

関連: [[verified_ltr_refresh_rejected]] [[project_kyoteki_score_rebuild]]
