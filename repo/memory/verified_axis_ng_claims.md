---
name: verified-axis-ng-claims
description: 資料「NGな軸馬の選び方」4主張の検証。前走1着=過剰人気のみ本物で軸信頼度に配線、距離延長/短間隔ローテは否定
metadata: 
  node_type: memory
  type: reference
  originSessionId: 9ae897bd-d954-4ace-a024-a2d4254e1de5
---

NotebookLM資料『データ駆動型・競馬予想の極意 / 絶対にNGな軸馬の選び方』の主張を、
1〜5番人気(軸候補帯)・オッズ20分位で統制した複勝率残差で検定（`scripts/axis_ng_backtest.py`）。

**本物（採用・配線済み）:**
- **🔨前走1着（勝ち上がり直後）は過剰人気** — train -1.28pp(z-7.18) / holdout -2.28pp(z-2.62)。
  **圧勝かどうかを問わない**のが肝（勝ち幅0.3〜1.0秒の普通の勝ちも holdout z-2.66）。
  既存の🔨圧勝(ATSU・勝ち幅1.0秒以上)は前走1着のごく一部しかカバーしておらず、しかも
  統合ビュー経路では prev_win_margin が渡っておらず**発火していなかった**。
  → `axis_selector.PREV_WIN_DEMERIT = 1.5pp`（ATSUと二重計上しない）。app.pyの軸マーク3経路に配線。
  複勝率の絶対値は高い(44.5%)ので**軸から外さない**＝信頼度の割引のみ（[[verified_ohtani_trap]]と同じ運用）。
  俗に言う「昇級初戦・連勝馬の過剰人気」の正体。クラス列がDBに無いため前走1着で近似。

**否定（実装しない）:**
- **距離延長**（+200m以上 z-1.1/-0.2、+400m以上はむしろ正）＝効果なし。
- **短間隔ローテ（中1〜2週）**＝**逆**に残差わずかに正(+0.65/+0.96pp)。疲労説は誤り。
- **成績のムラ（直近5走の着順のばらつき上位25%）** = train -1.69pp(z-5.85)だが holdout z-1.99 で
  基準割れ。符号は一貫するが**保留**（採用しない）。再検証するなら標本を増やしてから。

**データ無しで検定不能:** スピード指数113ライン / 調教の加速ラップ（[[project_training]]）。
**既に答えが出ていて再検証しない:** 逃げ先行を軸([[verified_legtype_axis]]) / EV>100で買い
([[verified_tansho_roi_efficient]]) / 長期休養([[verified_rotation_weight_demerit]]) /
枠順([[verified_dirt_draw_bias]]) / 指数1位の過剰人気([[verified_odds_theory_signals]]のガラス人気馬)。

**Why:** 「複勝率が高い＝良い軸」ではない。オッズ統制後の残差で見ないと市場の織込みと区別できない。
前走1着馬はまさに「絶対値は高いが、オッズがそれ以上に高い」典型。
