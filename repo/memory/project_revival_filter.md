---
name: project-revival-filter
description: 敗者復活フィルター検証・実装。切る帯(消去3+)の人気薄でもcombo3+なら複勝がベース超え(holdout12.3%vs切る帯5.9%・z+2.21)。combo2ではダメ。統合ビューに🔥敗者復活配線
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

ユーザー案(2026-07)「敗者復活フィルター作るか。作るならかなり厳しい条件にしないと」を検証してから実装。
scripts/revival_backtest.py(JRA平地2021-2026/6・人気薄6+・elim=消去クロス verified_count/
combo=荒れ予報6シグナル同時発火数・リーク無し・train2021-24/holdout2025)。

**検証結果(人気薄6+ ベース複勝率9.3%)**:
| バケット | train複勝 | holdout複勝 |
|---|---|---|
| 切る帯(消去3+) | 6.0%(z-14.7) | 5.9%(z-7.5) |
| 復活combo2+ | 8.0%(-1.3pp) | 9.4%(±0) |
| **★復活combo3+** | **10.4%(+1.1pp)** | **12.3%(+3.0pp・z+2.21)** |
| 参考:非切る×combo3+ | 16.6% | 19.4% |

**結論**: 切る帯に落ちてもcombo3+なら複勝10-12%=人気薄ベース(9.3%)を超えて復活(holdout有意)。
**combo2ではベース届かず=復活せず**(ユーザーの「かなり厳しく」が正解)。ただし切る帯×combo3(10-12%)は
非切る×combo3(16-19%)より弱い=復活は「基準超えの過小評価穴」であって強軸ではない。

**実装(core/consensus_view.integrate)**: 切るループでcombo3+はcontinue(切らない)→穴ループで
elim≥3×combo3+を『🔥敗者復活(combo{N}/消去{N})』ロールに。app.py統合ビュー: 役割列に🔥敗者復活の
色付け(#ff6b00)＋③穴カードに🔥敗者復活[馬番]表示。smoke=integrate(穴/切る/敗者復活)。

**How to apply**: 「切られた馬を救う」系は必ず激辛(combo3+等)にしてから配線。緩い条件(combo2)は
ベースに届かず妙味なし。[[project_consensus_view]]の切る=消去3+/[[verified_arare_signal_check]]の
combo=6シグナル同時発火が前提。
