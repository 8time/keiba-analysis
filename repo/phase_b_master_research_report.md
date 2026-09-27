# Phase B master research report

更新: B5 完了時点。

## 現在

- **Phase:** B5 終了
- **停止:** `NO_HISTORICAL_EDGE_FOUND`（STOP 4）
- **B6–B10 / Phase C–E:** 未着手。生存 signal が 0 のため進めない。
- **Forward:** `WAITING` ではない。Historical finalist が無いので Forward 評価対象も無い。
- **本番・Phase A:** 未変更。

## 完了しているもの

- Phase A: CLOSED
- 本番 Projected Score の historical FULL parity: NOT_REPRODUCIBLE（proxy は作っていない）
- Track A: `research/forward/` の判断スナップショットと結果ファイルの分離
- historical_research_v1: `VH_TOP2_POP6_WIN_V1` は HOLDOUT **FAILED**。救済しない。
- B5 walk-forward: 21 ルール × 6 fold = **126** experiment（append-only）

## B5 プロトコル

各 fold は TRAIN だけで閾値（エントロピーと平均消去の 75 パーセンタイル）を固定し、翌年 TEST を 1 回だけ採点する。2026 は選択に使わない。

| Fold | TRAIN | TEST |
|------|--------|------|
| WF1 | 2016–2019 | 2020 |
| WF2 | 2016–2020 | 2021 |
| WF3 | 2016–2021 | 2022 |
| WF4 | 2016–2022 | 2023 |
| WF5 | 2016–2023 | 2024 |
| WF6 | 2016–2024 | 2025 |

券種は単勝 100 円。入力は SAFE_PRE_RACE のみ。`combo` は不確実なので未使用。着順ラベルは採点だけ。

促進条件（事前固定）: TEST が 4 年以上、そのうち ROI>100 が 4 年、最悪年 ROI≥80、かつ「ROI≤100」の片側 bootstrap p を Benjamini-Hochberg q=0.10 で棄却。FAILED reference `vh_rank2_ninki_ge6` は促進禁止。

## 結果

促進 **0**。20 本の中央 TEST ROI はおおよそ 74–83%。ROI>100 の TEST 年は **0**。bootstrap p はすべて 1.0（resample しても ROI は 100 を超えない側）。BH 棄却なし。

例（6 年の中央 / 最悪 TEST ROI）:

- 1番人気 `fav`: 79.7 / 77.9
- VH1位: 83.3 / 79.0
- ability 1位: 80.0 / 74.6
- 騎手1位: 76.6 / 71.1
- 高エントロピーの本命: 74.3 / 71.8

`vh_rank2_ninki_ge6` は台帳に残るが、B6 へは送っていない。

## 解釈

このカタログの範囲では、購入前の安全特徴による単勝ルールは、年をまたいでも市場（控除後）を安定して超えていない。ROI を後から盛る探索はしていない。

B7 の券種比較は、馬・レースの edge が確認された後、という停止条件に当たるため未実施。パーサー未検証の券種で ROI を作らない。

## 成果物

- `research/walkforward/catalog.py`
- `research/walkforward/run_b5.py`
- `data/research/walkforward/b5_summary.json`
- `data/research/checkpoints/phase_b5.json`
- `data/research/experiments.jsonl`（追記）
- `tests/test_phase_b5_walkforward.py`（OK）

## DOMAIN_POSITION_TICKET_TRACK（B26–B29）

B5 / B11–B25 は変更していない。複勝・ワイド・D帯3連複2点は 2020–2025 で ROI 100% 未満。cross_n 系の 236/247/248 は NOT_REPRODUCIBLE。生存候補 0。詳細は advanced final report。

## Advanced（B11–B25）

単純ルール失敗のあとに、市場確率とロジスティック回帰を walk-forward した。結論は `NO_ADVANCED_HISTORICAL_EDGE_FOUND`。詳細は `repo/phase_b_advanced_final_report.md`。B5 の結論は残す。

オッズ込みモデルは logloss を年あたり 0.0002 未満しか改善せず、TRAIN 内 90 パーセンタイルの edge で買った単勝は 2020–2025 のすべてで ROI 84–88%。三連系は払戻照合が済んでいないので未評価。

## 次にやらないこと

TEST 年や 2026 を見て閾値を動かさない。FAILED 単勝穴を人気帯や VH2 だけで復活させない。本番への反映はしない。
