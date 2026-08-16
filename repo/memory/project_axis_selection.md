---
name: project_axis_selection
description: 軸馬候補◎〇▲を強適Ranking Tableに表示。core/axis_selector.py。検証済み2要素(人気複勝率+前走圧勝)で構成
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

軸馬選定タスク([[project_trio_engine]]の固定軸「人気上位2頭」を超える狙い)。Single Raceの📊強適 Ranking Tableに **🎯軸馬候補 列(◎〇▲・最大3頭)** を実装。

**実装**:
- `core/axis_selector.py`: `axis_marks(horses)` / `axis_confidence(pop, odds, prev_win_margin)`。軸=3着内信頼度(複勝率)が高い人気馬。
  - **base = 単勝オッズ別 実複勝率**(jravan.db 2021-25, ODDS_FUKU): 1.0-1.2倍94.9/1.8-2.2倍74.5/2.6-3.0倍64.3/4.5-6.0倍45.2%…。オッズは人気順位より細かい軸指標(#3検証)。オッズ欠損(約37%)時のみ人気別複勝率(POP_FUKU)で代替。
  - 前走圧勝(🔨)は**加点ではない**: オッズ統制で-5〜11pp([[verified_ohtani_trap]])＝過剰人気注意フラグ＋オッズ基準時 -5pp の軽い減点。オッズ欠損時のみ人気ベースで+15.7加点。
  - 信頼度フロア(◎≥50/〇≥42/▲≥35%)未満は印を付けない=波乱レースはマークが減る(「迷わない・少なく」)。MAX_CAND_POP=6。
  - 不採用: 脚質([[verified_legtype_axis]])、前走僅差負け(#4=人気馬で+0.5pp)、オッズ2.5倍の崖(#3=崖は存在せず滑らか)。
- `core/jockey_jv.py`: `horse_prev_win_margin` / `_parse_time_msst` 追加。
- `app.py`: kettoループでawm算出→_trc_map['awm']。Alert直後に AxisMark列をUmabanキーで生成(odds=df['Odds']も渡す)。cols/label/column_config(tooltip)に追加。表示=例「◎ 92%」「▲ 59%🔨」。

**検証状況(全て検証済)**: #3=オッズベース採用(崖は無いがオッズは強い軸指標)。#4=不採用。
**head-to-head結論(scripts/axis_h2h_backtest.py, 26042R)**: ◎〇ルール軸 vs 固定軸(人気1+2位)で軸2頭ダブル複勝率=同一playレースで **37.5% vs 37.7%(-0.2pp)**、ペア相違は7.2%のみ。**固定軸が既に最適＝trio_engineの軸ロジックは変更しない**。オッズ(人気)が軸信頼度を効率的に織込み済で、選び直しの余地ほぼゼロ。
**この列の価値**: 軸の「選び直し」ではなく**信頼度の可視化**(◎91%か◎52%か＝張る/見送りの判断材料、混戦はフロアで印が減る)＋過剰人気🔨注意。trio_engine本体は無改変。
