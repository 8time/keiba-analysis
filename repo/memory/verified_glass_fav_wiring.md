---
name: verified-glass-fav-wiring
description: ガラス人気馬(検証済z-8.5)が軸マークとスキャナーで未配線だった件と、NARで単勝を複勝と誤認していたバグ
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-08-02T20:35:54.038Z
---

検証済み(z-8.5・3窓一貫 [[verified_odds_theory_signals]])の🥃ガラス人気馬が
実際には正しく機能していなかった。2件の問題を修正。

**① 配線漏れ** — danger_veto は win_odds/place_mid を渡さないと発火しない。
- core/consensus_view.py:123 … 渡していた ✅
- app.py 🎯軸馬候補(6009付近) … **渡していない** → 軸マークで一度も発火せず
- app.py 🔍Race Scanner(12544付近) … **渡していない**（place_map は取得済みなのに未使用）
→ 両方に win_odds/place_mid を配線。SRA側はレース単位で1回だけ取得しsession_stateにキャッシュ。

**② NARで単勝オッズを複勝オッズと誤認(より深刻)**
netkeibaのNAR API は type=1/2/b1 の**どれでも** `{'Odds':'5.6','Ninki':3}` ＝単勝を返す。
fetch_place_odds_api の parse が `val.get('Odds')` を Min/Max のフォールバックにしていたため、
単勝オッズを複勝オッズとして採用していた。結果、単複乖離が「単勝 vs 単勝」の無意味な比較になり
NARで大量に誤発火（川崎6Rで上位3頭すべてに🥃が付き、実際は8番1着9番2着）。

判別法: 複勝オッズは必ず Min/Max のレンジで来る。単一 `Odds` しか無ければ複勝ではない。
→ `Odds` フォールバックを削除。NARは空dictを返す（＝発火しない）のが正しい挙動。
JRAは元から OddsMin/OddsMax を返しており正常だった（札幌11R 1番 7.0-10.4）。

**現状**: 🥃ガラス人気馬はJRAでのみ機能する。NARは複勝オッズの供給源が無いので
別ソース(nankankeiba等)を見つけない限り使えない。
Min==Max が全頭で揃っていたら複勝ではないと疑うこと。
