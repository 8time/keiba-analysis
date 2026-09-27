# Forward research readiness

**FORWARD_AUTOMATION_READY_FOR_LIVE_TEST**

判断スナップショットには Gate、LTR/VH の点数と順位、`decision_time_odds`（出典は `core.scraper` の出馬表／API。確定オッズのコピーではない）を入れられる。実レースを decision → shadow → 公式結果まで通した記録はまだ無い。複勝以下の同着・返還は引き続き PARTIAL なので、券種研究の準備完了とは呼ばない。

Historical 結論 `NO_ADVANCED_HISTORICAL_EDGE_FOUND` は変更していない。新しい候補は作っていない。

## PAYOUT STATUS

| 券種 | 状態 |
|--|--|
| 単勝 | VERIFIED（400レースで DB 払戻 = win_odds×100） |
| 複勝 | PARTIAL |
| 馬連 | PARTIAL |
| ワイド | PARTIAL |
| 3連複 | PARTIAL |
| 3連単 | PARTIAL |

桁長（馬番2桁連結）は券種と一致する。払戻0円の行は無い。研究パーサーは一致した最初の正の払戻だけを返す。同着の合算、返還、取消、特払を券に対応づける列は `payouts` に無い。本番精算は未変更。問題はここまでの未照合であり、コードは直していない。

## TRACK A

判断 JSONL と結果 JSONL は別ファイル。判断レコードに着順・払戻キーがあると `invalid`。

保存できるもの: `race_id`、判断時刻、馬番・馬名、人気、`decision_time_odds`、`PastRuns`、`BattleScore`、予測スコア、シグナル、LTR 値、消去残馬、重みのハッシュ。プレイブック生成後に、ゾーン・券種・フォーメーション・チケット・見送り理由を **SHADOW**（`purchased: false`）で追記する。

まだ判断時点に必ず入るとは限らないもの: Gate、VH 順位、LTR 順位、`cross_n` の入力一式、購入ボタン時点と確定オッズの両方。`final_odds` は結果側だけ。

## ODDS TIMING

判断側は `decision_time_odds` と `odds_snapshot_timestamp`。結果側は `final_odds`。同じレコードには入れない。ライブの `Odds` 列が発走前の最終表示かは、保存時刻と突合するまで未証明。

## RESULT CAPTURE

`append_result` が着順、払戻、確定オッズ、返還ステータスを `results.jsonl` に書く。判断ファイルは上書きしない。

## DATA QUALITY

`research/forward/quality.py` が decision を `valid` / `partial` / `invalid` に分ける。結果の混入と、全馬オッズ欠測は通常サンプルにしない。

## FORWARD PIPELINE TEST

`tests/test_forward_pipeline.py`: 判断 → SHADOW 記録 → 結果 → 100円差引の確認。2件成功。本番の購入処理は通していない。

## 変更

Research の forward / payout 監査と、`app.py` の観測追記だけ。Phase A は未変更。買い目の計算は未変更。実購入は増やしていない。

## 残る不足

1. 複勝・馬連・ワイド・三連複・三連単の同着と返還が VERIFIED ではない。
2. Gate と順位が、毎回の判断スナップショットに必須化されていない。
3. まだ実レースの Forward 台帳は溜まっていない。パイプライン試験は合成レースだけ。
