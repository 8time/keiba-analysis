# Track A automation audit

## もともとあったもの

`research/forward/snapshot.py` が判断 JSONL と結果 JSONL を分けて追記する。結果キーが判断に入ると拒否する。`shadow_baseline.py` は `purchased: false` の影記録。`quality.py` が欠測オッズと確定オッズの混入を分ける。`tests/test_forward_pipeline.py` は合成の判断→影→結果。実レースの完走は無い。

## 今回足したもの

`research/forward/automation.py` と `scripts/forward_collector.py`。

状態は OBSERVED → DECISION_CAPTURED → SHADOW_CREATED → RESULT_CAPTURED → SETTLED → EVALUATED。失敗は FAILED_RETRYABLE（最大5回）か INVALID。

生ログは `raw_events.jsonl` と `odds_snapshots.jsonl`。索引は `forward.db`。同じ event id は二重に足さない。別時刻のオッズは別イベント。

主判断は、発走5分以上前のスナップショットのうち、15分前に一番近いもの。過去の収支から時刻は選んでいない。

単勝の払戻信頼は VERIFIED。複勝・馬連・ワイド・3連複・3連単は PARTIAL のまま。PARTIAL は公式ROIにしない。実購入金額は 0。

## まだ無いもの

開催日の自動スクレイプ、Task Scheduler 登録、実レースの decision → 公式結果 → 精算の完走。能力指数、H7、末脚平均、過去3着内率、騎手・調教師の場別成績は判断時点の必須項目になっていない（欠測は 0 にしない）。
