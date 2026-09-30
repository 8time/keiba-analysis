# Prediction Time Machine（実運用待ち）

発走前にアプリが実際に持っていた入力と、その場で計算した値を、追記専用SQLiteへ残す。予測式、重み、消去、買い目は変えていない。研究用の Stage 1 確率は本番経路で生成されないため、新しく計算して埋めていない。

判定は **C（REAL_GREEN_READY）**。実レースの production GREEN は **0 件**（既存 DB 2 件はいずれも **発走後 capture → RED**）。品質基準は緩めていない。

隔離 DB の E2E では **`capture_origin=production`・pre-race・finalize 後 SRA_CORE GREEN** と **`--production-only` Dataset 投入**まで PASS。残 blocker は **発走前に本番 UI で同経路を走らせること** のみ（GREEN 捏造はしない）。

## 完成条件の再監査

| 条件 | 判定 | 根拠 |
| --- | --- | --- |
| 1. 取得時刻 | PARTIAL | 出馬表HTML、単勝、人気、HTML枠、リアルタイムAPI、result.html、予想オッズは受領地点で時刻を付ける。新規キャッシュは sidecar に `source_fetched_at` を残す。古いキャッシュと抽出失敗セルは UNKNOWN_TIME |
| 2. Provenance伝播 | PARTIAL | 値が一致したセルだけ由来を付ける。後段で時刻は推測しない |
| 3. 工程一覧 | PASS | 本書の工程表と `UI_STAGE_TRIGGERS` |
| 4. 全工程フック | PARTIAL | 実行された工程だけ保存する。穴馬は別画面、消去はボタン。未実行を実行済みにはしない |
| 5. Stage 1 | PARTIAL | 本番は `position_score_map`。研究 Stage 1 確率は `NOT_APPLICABLE` で、GREEN 条件に入れない |
| 6. 4角 | PARTIAL | 保存済み `pos4` の安定ソート。別モデルは走らせない |
| 7. BattleScore | PARTIAL | 最終値と計算済み成分。市場オッズは入力ではない |
| 8. VH・穴馬 | PARTIAL | 生成された戻り値を記録。穴馬画面の実レース操作は未実施 |
| 9. ゴール | PARTIAL | `predict_finish` の戻り値と diagnostics |
| 10. Timeline | PASS | `replay_race` が snapshot と observation を時刻順に返す |
| 11. Completeness | PASS | workflow ごとの必要工程を再計算する |
| 12. GREENを厳格に | PASS | 時刻不明、発走後、補完、予想オッズ、確定結果オッズ、LIVE/JV混在、その workflow で欠ける工程は GREEN にしない |
| 13. Dataset Builder | PASS | `--quality` `--minutes-before-start` `--from-date` `--to-date` `--production-only` `--workflow` |
| 14. 発走N分前 | PASS | snapshot 時刻に加え、各 source の fetched_at と派生値の derived_at を見る |
| 15. Replay | PARTIAL | summary に workflow、origin、blockers、freshness、版、各工程を出す。専用画面はない |
| 16. Provenance確認 | PARTIAL | `explain --umaban` とセル provenance |
| 17. LIVE/JV混在 | PARTIAL | 警告を残し GREEN にしない。予測式は未変更 |
| 18. Imputed | PARTIAL | `PassingType/AgariType=Imputed`、予想オッズ、result.html を区別。8-8の既存利用は未変更 |
| 19. Outcome分離 | PASS | Outcome は別テーブル。追加後も prediction fingerprint は変わらない |
| 20. append-only / hash | PASS | UPDATE/DELETE拒否と fingerprint 不一致検出 |
| 21. lightgbm | PASS | この環境で `test_ltr_differs_from_ability_order` は PASS |
| 22. Regression | PASS | BattleScore、着順スコア、Phase B の買い目 golden、LTR 順序は既存テストのまま |
| 23. Leakage | PASS | 発走後、未来 source、時刻不明、予想オッズ、result オッズ、fixture origin を本番抽出から除外 |
| 24. 実経路E2E | PARTIAL | スクレイパーから SRA・展開・VH・Replay まで通る。実レース取得は BLOCKED |
| 25. GREEN 1件 | PARTIAL | fixture の SRA_CORE GREEN は成立。実レース production GREEN は 0 |
| 26. 容量・速度 | PASS | 下記の fixture 実測 |
| 27. 保存失敗 | PASS | スコアは変わらず `SNAPSHOT_SAVE_FAILED` |
| 28. 再監査 | PASS | 本表。条件は削っていない |
| 29. 完成宣言 | FAIL | 実レース GREEN が無いため完成とは宣言しない。状態は実運用待ち |

## 工程と、実行される操作

| 工程 | いつ実行されるか | GREEN での扱い |
| --- | --- | --- |
| position / BattleScore / Projected Score | SRA分析の計算中 | `SRA_CORE` の必須 |
| ペース / ゴール | メイン画面の展開マップ描画（折りたたみでもスクリプトは実行される） | `MAIN_PAGE` 以上で必須 |
| VH / 推奨 | メイン画面の統合ビュー。推奨は買い目を組んだとき | `MAIN_PAGE` 以上で必須 |
| 穴馬 | 穴馬ハンター画面を開いたとき | `FULL_PREDICTION` と、profile 無しの厳密 snapshot で必須 |
| 消去 | 「強適消去エンジンを実行」を押したとき | `FULL_PREDICTION` で必須 |
| Stage 1 確率 | 本番画面では実行されない | `NOT_APPLICABLE`。欠落にはしない |

未実行は `NOT_EXECUTED`、その workflow の対象外は `NOT_APPLICABLE`、計算したのに値が無いのは `MISSING`、失敗は `FAILED`。画面を開いていない工程を、こちらから実行して埋めない。

`SRA_CORE` の必要工程がすべて揃うと、確定時に `MAIN_PAGE` へ上げることがある。`FULL_PREDICTION` へは自動では上げない。

## 品質と由来

`capture_origin` は `production` / `fixture` / `test` / `manual` / `unspecified`。アプリの SRA 保存だけが `production`。`evidence_class=production_capture` は `capture_sra` 関数を通ったという意味で、実レースとは別。

- RED: 発走以降の snapshot または source、未来の source、result.html のオッズ。
- YELLOW: いずれかの blocker。時刻不明、予想オッズ、補完、LIVE/JV混在、重要入力の不足、その workflow で未達の工程。
- GREEN: blocker が無く、その `workflow_profile` について発走前と検証できたとき。

研究 Dataset の既定は GREEN のみ。`--production-only` は `capture_origin=production` だけを残す。fixture GREEN はここに入らない。

## キャッシュと JV

新規の `race_history.csv` 保存時、`data/cache_provenance/{race_id}.json` に `source`、`source_fetched_at`、`cached_at` を書く。読込時は `source_fetched_at` だけを復元する。sidecar が無い古いキャッシュは `UNKNOWN_TIME` のまま。`cached_at` を取得時刻にしない。

JV は `data/jravan.db` の path、size、mtime、schema hash、`PRAGMA user_version`、`MAX(race_key)` を残す。DB 全体はコピーしない。mtime は内容の同一性を保証しない。`latest_race_key` は収録の先端だけで、途中行の改変は size と mtime が変わらなければ検出できない。

準備確認は予測を実行しない。

```text
python -m core.prediction_time_machine readiness
python -m core.prediction_time_machine blockers
python -m core.prediction_time_machine replay --snapshot-id <UUID>
python -m core.prediction_time_machine dataset --cutoff <ISO> --production-only --workflow SRA_CORE
```

## なぜ本番関数の薄い fixture は YELLOW か

3頭の fixture HTML をスクレイパー、`calculate_battle_score`、`calculate_strength_suitability`、展開、VH、保存、Replay まで通した snapshot の blocker は次のとおり。件数は 1 で、割合にはしない。

| blocker | 内容 | コードで GREEN にできるか |
| --- | --- | --- |
| `CRITICAL_INPUT_MISSING` | Jockey が 3 頭とも無い | できない。HTML に騎手が無い |
| `UNKNOWN_TIME` | 調教師抽出に失敗した Tozai / Trainer / TrainerID に受領時刻が無い | できない。失敗セルへ現在時刻を入れない |
| `NOT_EXECUTED_POSITION` | `position_stage` をこの snapshot に載せていない | 位置を記録すれば消える。記録していないものを存在したことにはしない |

同じ計算関数に、騎手・斤量・馬体重・実測の過去走・受領時刻を渡した fixture は `SRA_CORE` で GREEN になる。`capture_origin` は `fixture` のままなので、実レース GREEN には数えない。本番 DB `data/prediction_time_machine.db` の snapshot は 0 件。

## 検証

- Time Machine 19 件、production path 2 件、展開 14 件、Phase B parity 5 件。合計 40 件 PASS。LTR 1 件を含む。
- 手組み GREEN は Replay と既定 Dataset に入る。`--production-only` では入らない。
- 薄い fixture は YELLOW のまま、production-only Dataset に入らない。
- 予想オッズは非 GREEN。result.html オッズは RED。
- Outcome 追加後も prediction fingerprint は不変。
- BattleScore は強適計算の前後で不変。diagnostics の有無で着順スコアは不変。
- readiness はこの環境で ready。JV は schema hash と最新 race key まで取れている。

容量（16頭、過去走8、追加100列、snapshot 10件）:

- 保存の中央値 0.129秒、最大 0.161秒。
- 1件あたり約 138KB。1レース3件で約 0.41MB。3,600レース/年で約 1.5GB/年。観測と WAL は含まない。

## 厳密な研究利用を開始できる条件

`TIME_MACHINE_V1_START` は最初の保存成功であり、研究開始日ではない。開始条件は、実レースの発走前にアプリが保存した snapshot で、`capture_origin=production` かつ `quality=GREEN` かつ対象の `workflow_profile` が明示されていること。その件数は現在 0。recorder の準備はできている。
