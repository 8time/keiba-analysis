# Forward collector

影の研究記録だけを集める。馬券の購入、入金、資金の減算はしない。

```
python scripts/forward_collector.py --status
python scripts/forward_collector.py --synthetic
python scripts/forward_collector.py --live --once
python scripts/forward_collector.py --live --dry-run
python scripts/forward_collector.py --live
```

`--live` は 60 秒おきに当日だけを見る。止めるときは Ctrl+C。タスクスケジューラには登録しない。`--dry-run` は 1 回だけ実行してデータベースへ書く。購入はしない。

スナップショットは発走 60 / 30 / 15 / 5 分前の前後 3 分。主判断は 5 分以上前のうち 15 分前に一番近いもの。発走 5 分を切ってから初めて見つけたレースは LATE_DISCOVERY で、判断は作らない。同じ目標時刻の再取得は足さない。再起動後は `forward.db` の取得済み時刻から続く。

`--status` は `data/research/forward/` の未完了レースを表示する。`--synthetic` は合成1レースを EVALUATED まで通す。

Windows のタスクスケジューラへはこのスクリプトから登録しない。開催日に人が `--status` を実行し、発走前のオッズを `ForwardStore.add_odds_snapshot` で足す。結果は `capture_result` だけが受け取る。判断側のファイルへ確定オッズは書かない。

スキーマ名は `FORWARD_V1`。仕様を変えるときは V2 として分け、V1 の行と混ぜない。Forward の行を Historical の学習データへ自動では足さない。
