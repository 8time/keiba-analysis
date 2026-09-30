# Prediction Time Machine 実装進捗

## Phase 1: 現状調査・設計（完了）

- 完了: `scraper.get_race_data` から SRA、監査イベント、推奨までの経路を確認。取得完了時刻を各値の fetched_at に転用しない。
- 決定: 独立した追記専用SQLite。時刻不明は UNKNOWN。結果は別テーブル。

## Phase 2: 保存・Replay・研究抽出（完了）

- 変更: snapshot、品質、Replay、時刻制約付き dataset、監査イベントの写し。
- 決定: 未保存の工程は null。研究 Stage 1 確率は本番未生成のため null。

## Phase 3: 検証（完了）

- fixture の保存、未来・時刻不明の除外、不変、Outcome分離、補完の区別。
- この環境では lightgbm と LTR モデルがあり、Phase B の該当1件は PASS。

## Phase 4: 取得時刻と工程値の接続（完了）

- 完了: 出馬表、オッズ、人気、リアルタイムAPI、result.html、予想オッズの受領時刻を、実際に書き込んだセルへだけ結び付けた。
- 完了: 位置、4角、ゴール、VH、穴馬、消去、推奨を観測として組み立てる。LIVE/JV混在は GREEN にしない。
- 完了: 手組み GREEN は Replay と Dataset まで通る。保存失敗はスコアを変えず `SNAPSHOT_SAVE_FAILED` を残す。

## Phase 5: 実運用経路の GREEN 条件（2026-09-30 更新）

判定は **C（REAL_GREEN_READY）**。実レース `capture_origin=production` かつ `quality=GREEN` は **0 件**（品質は緩めていない）。

### 実 DB の blocker 分解（production 2 件・割合は出さない）

| blocker | 件数 | 意味 |
| --- | ---: | --- |
| POST_RACE_SNAPSHOT | 2 | finalize / capture が **2026-09-30**、レース発走 **2026-02-01 15:30** より後 |
| POST_RACE_SOURCE | 2 | 同上（時系列整合） |
| IMPUTED_POSITION | 2 | 過去走 Passing/Agari の Imputed が残存 |
| NOT_EXECUTED_POSITION | 1 | 初回 `capture_sra` のみ（finalize 前の中間 snapshot） |

2 件目は `capture_scope=assembled recorded run`・`workflow_profile=MAIN_PAGE` まで到達。**経路は動いているが、発走後タイムスタンプのため RED**。

### 今回のコード変更（予測式・買い目は不変）

- SRA `capture_sra` 成功直後に、同一 `analysis_run_id` で **finalize**（既存 observation の組み立てのみ）。
- `position_stage` 記録時に **analysis_run_id を明示**（Streamlit session の run と一致）。
- `blockers` CLI に **snapshot 単位の entries / fixable_hints** を追加。
- E2E: `test_real_green_ready_production_origin_sra_core` … **production origin + pre-race → GREEN + production-only Dataset 投入**（隔離 DB）。

### 実レースで GREEN にする操作条件

1. 発走 **前** に「SRA分析」を実行（`readiness` が ready）。
2. 同一 run で `position_stage` が記録される（分析ボタン経路）。
3. 推奨・消去で MAIN_PAGE / FULL へ上げる場合は、それも **発走前** に実行。
4. 古いキャッシュは `CACHE_SOURCE_TIME_UNKNOWN` のまま（時刻を埋めない）。

## Phase 5（旧メモ）

判定は C。実レース production GREEN は 0 件。品質は緩めていない。

- 原因: 以前は穴馬・消去・推奨を、実行していない SRA 経路でも GREEN 必須にしていた。本番関数だけの薄い HTML は、それに加えて騎手欠落と調教師抽出失敗で YELLOW だった。
- 変更: `workflow_profile` を導入した。`SRA_CORE` は position、BattleScore、Projected Score。`MAIN_PAGE` はそれにペース、ゴール、VH、推奨を足す。`FULL_PREDICTION` は穴馬と消去も必須。未実行は `NOT_EXECUTED`。Stage 1 は `NOT_APPLICABLE`。
- 変更: `capture_origin` を分けた。アプリの SRA 保存は `production`。研究 Dataset は `--production-only` で fixture GREEN を除外できる。
- 変更: 新規キャッシュは `source_fetched_at` を sidecar に残し、読込時に復元する。古いキャッシュは UNKNOWN_TIME。
- 変更: JV は path、size、mtime、schema hash、最新 race key を残す。mtime は内容証明ではない。
- 変更: `readiness` と `blockers` を追加した。予測式は実行しない。
- 検証: 騎手と受領時刻が揃った入力を本番の BattleScore と強適計算に通すと、`SRA_CORE` の fixture GREEN になる。production-only Dataset には入らない。
- 検証: 薄い fixture HTML は `UNKNOWN_TIME`、`CRITICAL_INPUT_MISSING`（Jockey 3）、`NOT_EXECUTED_POSITION` で YELLOW のまま。
- 未完了: 実レースを取得して `capture_origin=production` の GREEN を1件残すこと。画面を開いていない穴馬・消去は実行しない。
