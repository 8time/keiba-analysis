# Phase B historical research v1（HOLD OUT 未実行）

本番の Projected Score / Rule B 再現ではない。`historical_research_v1`。

## Track A

`research/forward/` が判断 JSONL（`data/research/forward/decisions.jsonl`）と結果 JSONL（`results.jsonl`）を分離する。着順・払戻キーは判断側で拒否。SRA 完了後に `app.py` から観測だけ呼ぶ。買い目・閾値・Phase A ledger は変えない。

## SAFE / 除外

分類は `research/historical/feature_classes.py` と `data/research/historical_v1/feature_registry.json`。

- **SAFE_PRE_RACE:** 出馬属性、単勝オッズ・人気、shift(1) 系（h7, 末脚, 騎手, 厩舎, elim_n, ability_score, vh2）、レース側の vscore・オッズ構造・頭数。
- **LABEL_ONLY:** `chakujun`, `top3`, `win`、レースの `arareA/B`, `ana2`, `honsen`, `ninki_top3_logsum`。入力に未使用。
- **UNCERTAIN（未使用）:** `combo` と combo 集計。export は 2024+ の人気薄のみ。
- **Projected Score:** 不使用（NOT_REPRODUCIBLE）。

評価は `day < 20250101` のみ。単勝・100円/点。Kelly なし。券種は払戻フォーマットを誤らないよう **単勝だけ**。複勝・ワイド・馬連・三連系は DB にあるが、この版では未結合。

## 事前ルール（18本、TRAIN で凍結）

画面条件（コード固定）: 点数 ≥ 500、年次 ROI≥90 が 4 年以上、かつ ROI≥100 または bootstrap 下限≥95。

合格は **1本だけ**: `vh_rank2_ninki_ge6`（VH 順位 1–2 かつ 6番人気以下を単勝）。

他（1番人気、VH1位、ability1位、h7、末脚、騎手、厩舎、低 elim、オッズ≥3 の本命、少頭数、牝馬、芝/ダ、vscore<50、C帯のVH1位、高エントロピー、高 mean_elim）は TRAIN で画面落ち。失敗も `experiments.jsonl` に `fail_screen` で残してある。

### TRAIN `vh_rank2_ninki_ge6`

| | |
|--|--|
| n | 2,487 |
| 的中率 | 9.7% |
| ROI | 110.1% |
| profit | +24,990円 |
| max DD | 18,770円 |
| ROI 95% CI | 94.8 – 124.4 |
| ROI≥90 の年 | 7 |

CI 下限は 100 を下回る。1番人気単勝の TRAIN ROI は 79.0%（n=26,578、CI 77.6–80.5）。

### VALIDATION 2024（定義は変更していない）

| | |
|--|--|
| n | 308 |
| 的中率 | 10.1% |
| ROI | 107.2% |
| profit | +2,230円 |
| max DD | 6,270円 |
| ROI 95% CI | **74.3 – 149.3** |

方向は TRAIN と同じだが、区間が広く、利益は小さい。組合せ探索は生存が 1 本のため未実施。

## 候補の切り分け

- **的中率:** 1番人気（TRAIN 33%）の方が高い。このルールは的中率改善ではない。
- **ROI:** TRAIN/VAL とも 100% 超だが CI が 100 をまたぐ。
- **DD:** 点数が少ないため DD の絶対額は本命全買いより小さい。同じ賭け金規模での優位ではない。

## HOLDOUT 候補（最大3、実行しない）

1件だけ。送る前に「区間が 100 をまたぐ単勝穴」と扱うこと。

- **ルール:** 各レースで `vh2_score` のレース内順位が 1 または 2、かつ `ninki >= 6` の馬を単勝 100 円。それ以外は買わない。
- **formation:** 1点/該当馬（平均点数は該当頭数。TRAIN はレースあたり約 0.1 点規模ではなく、該当馬 2,487 点 / 約 2.7 万レース）。
- **TRAIN:** n=2487, hit 9.7%, ROI 110.1%, profit +24990, DD 18770
- **VALIDATION:** n=308, hit 10.1%, ROI 107.2%, profit +2230, DD 6270
- **不確実性:** VAL CI 74–149
- **リスク:** 穴の少数的中、2024 の n が小さい、Projected 無しの VH 定義、三連系は未検証

2件目・3件目は無い。

## HOLDOUT 1回（ルール凍結後）

`candidate_id`: **VH_TOP2_POP6_WIN_V1**  
凍結: `data/research/historical_v1/holdout_freeze.json`（集計前、2026-09-21T22:32:57Z）  
期間: 2025-01-01 ～ 2026-06-21。2026 は 6月21日までの途中年度。  
判定: **FAILED**。見たあとで閾値・人気帯・VH順位・券種は変えていない。

全体: 対象 4,927 レース、購入 470 レース / 486 点（購入率 9.5%）、的中 41（8.4%）、stake 48,600、payout 47,990、profit **-610**、ROI **98.7%**、的中配当 平均 1,170 / 中央 1,130、max DD 6,120、最大連敗 38、ROI CI **70.1–128.7**。

- 2025: n=327、的中率 7.6%、ROI 93.9%、profit -2,010、max DD 6,120
- 2026（～06-21）: n=159、的中率 10.1%、ROI 108.8%、profit +1,400、max DD 4,520

最大払戻は 2,050 円。除外後 ROI は 94.7%（1件）/ 88.3%（上位3件）。全体利益がマイナスのため「利益寄与率」は正のプールに対する割合ではない。巨大配当依存ではない。

人気別・VH1/2・月次は診断のみ（`holdout_result.json`）。VH1 は ROI 72.6%、VH2 は 124.9% だが、分割して新ルールにはしない。月次の累積は 2026-06 末で -610。

## 実行

`python -m research.historical.run_v1`（約 29 秒）。出力は `data/research/historical_v1/`。HOLDOUT 集計なし。本番閾値は未更新。
