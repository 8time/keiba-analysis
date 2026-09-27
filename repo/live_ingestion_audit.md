# Live ingestion audit

## 再利用した取得

開催一覧は `core.scraper.get_race_list_for_date`。戻り値は race_id、場、レース名で、発走時刻は入っていない。時刻は同じサイトの race_list HTML から `race_id` の近くの `HH:MM` を探す。見つからなければ欠測で、推測しない。

発走前の単勝は `fetch_realtime_odds_api`。結果の着順は `fetch_race_result`。払戻の信頼区分は既存のまま（単勝だけ VERIFIED）。券面は `core.playbook_tickets.build_tickets`。購入関数は呼ばない。

UmaConn / JRA-VAN の live 接続は、この collector の必須依存にしていない。`jravan.db` は過去結果であり、判断時点のオッズではない。

## 分類

当日の race_id、馬番、人気、単勝オッズは、API が値を返したときだけ LIVE_AVAILABLE。発走時刻はページに時刻が無いと UNCERTAIN。PastRuns、BattleScore、予測スコア、VH、LTR、能力指数、H7、末脚、過去3着内率、騎手・調教師の場別成績は、この収集では取らず MISSING。確定オッズと着順は RESULT_ONLY。

## まだ実開催で確認していないこと

この実装時点では、今日の一覧を取りにいっても発走前レースが無ければスナップショットは増えない。合成時計のテストは通過している。
