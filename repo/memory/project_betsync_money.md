---
name: project_betsync_money
description: 資金管理⑤ BetSyncブラッシュアップ。core/money.pyを正本に、ガードレール/ケリー/台帳を配線
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

⑤「資金管理で長期回収率を上げる」を💰BetSyncページ(app.py:380〜)に実装した。

**設計思想**: ユーザーが昔ルーレットで作った添付ツール(THREE D BET法/betsync.pdf)は全てマーチンゲール系の追い上げ表＝控除率下では数学的に破産が約束された型。既存BetSyncの進行系(6連法/3Dリカバリ/ジワ上げ/ウィナーズ)もその移植。だからブラッシュアップの本質は「追い上げ＝感情の自動化を残しつつ、その上に破産を止める防護柵を被せる」。

**正本**: `core/money.py` に数理を集約 = kelly_multi / ruin_probability / bankroll_cap / cap_check / session_guard / Ledger(data/ledger.db)。scripts/kelly.py と scripts/betting_ledger.py は core.money を import する薄いデモに変更済み(単一の真実)。これらのscriptはimport時に sys.stdout を差し替えるためStreamlitへ直接importしてはいけない→だからcore/money.pyを作った。

**app.py BetSyncに追加した4ブロック**(操作パネルとKaggleチャットの間):
- 🛡️ バンクロール・ガードレール(B): 1R上限=残高1〜5%スライダー / セッション損切り(-%)・利確(+%) / 進行系の次回ベット`_nd_bet`が上限超なら赤警告
- 🎯 EV配分・多肢ケリー(A): data_editorで馬番/勝率%/オッズ→kelly_multiで配分円+破産確率
- 📈 回収率・残高推移(C): 既存computed[]から累積ROI/残高をst.line_chart
- 📒 収支台帳・Brier較正(C/D): money.Ledgerを配線。report/settled_rows/reflection表示+記録/精算フォーム+全消去

**予測モデル自動連携(済)**: 🎰買い方最適化(blended_win_probs)は実は🧹消去フィルターページ(app.py:5250〜)のSingle Race Analysisではなく消去フィルター内)にある。そこで`st.session_state['bs_ev_feed']={'race_id','rows':[{umaban,bamei,p,odds}],'alpha','ts'}`を書き出す。💰BetSyncの🎯EV配分は「⬇️予測を取込」で、📒台帳は「📥予測を一括記録」(全頭=Brier較正データ・race_idで重複防止)でこのfeedを読む。

**追い上げ実証(2026-06-23・scripts/toto_escalation_backtest.py)**: ユーザー提示の「mini toto風36倍固定10段エスカレーション(累積42,000円・10連敗で全損)」を3連複10点(1番人気軸5頭流し2-6番)に適用し2021-25実データで検証。結果=**完全に破産する**: 的中率37.7%だが≥36倍(プラス条件)は5.25%(平均19R/1回)→10連敗確率(1-0.0525)^10=58%→破産1,185回・最終-4,370万円。レースサーチ(trio_lean ②穴妙味に絞る)で≥36倍率5.25→6.04%に改善するが10連敗54%でマーチンは救えない(破産10%未満には≥36倍率20.6%が必要・現実5-6%で埋まらない差)。教訓=資金配分はEVを変えず追い上げは損失を激増。正しい道=フラット掛けでEV>1の選択を探す。THREE D BET/betsync.pdfと同型の再確認。

関連: [[project_bet_optimizer]](④単発ケリーはこの多肢ケリーで置換する方針) / [[project_app_pipeline]] / [[project_value_scanner]] / [[project_elimination_engine]] / [[verified_tansho_roi_efficient]]
