# 高entropy混戦研究 — データ棚卸し（STEP 1）

主キーは JV の `race_key`（`export_features_csv` / `scripts/high_entropy_upset_research.py` と同一）。

| 項目 | 区分 | 取得元 |
| --- | --- | --- |
| race_id / race_key | A | `jravan.db` results / races |
| 日付 | A | `races.monthday` → `day` |
| 競馬場 | A | `races.jyo` |
| 芝/ダ | A | `races.surface` |
| 距離 | A | `races.kyori` |
| 馬場状態 | A | `baba_shiba` / `baba_dirt` → `baba_code` |
| 出走頭数 | A | `shusso_tosu` / 集計 `n_run` |
| 単勝オッズ・人気 | A | `results.win_odds`, `ninki`（発走前確定オッズ・JV収録） |
| 1番人気オッズ | B | レース内最小 odds → `fav1` |
| odds entropy / eff_n | B | 正規化インプライド確率（`value_scanner` / export 同一） |
| 荒れ予測確率 | B | `arare_prob` / `vscore`（凍結ロジット・export 再現） |
| 妙味ゾーン | B | `race_value_score` の label / `trio_lean`（export `races.csv`） |
| 逃げ・先行・前方候補数 | B | export 集約 `n_hana`, `n_front`（過去走 position 由来・要 export） |
| ペース予測 | C | ライブ `pace_map` / テン速力 z（TM GREEN または session のみ・CSV 未一括） |
| 4角位置予測 | C | 本番 pace_map（研究 CSV には未標準搭載） |
| 各馬能力・Rank・VH | B | export `horse_races.csv` + vh2 スコア（要 `export_features_csv.py`） |
| 上位馬能力差 | B | export `h7_top2gap`, `vh2_top2gap`, `mkt_ability_corr` |
| 1〜3着・人気 | A | `results.chakujun`, `ninki` |
| 1番人気着順 | B | 事後ラベル `fav1_chakujun` |
| 配当（単勝〜3連単） | A | `jravan.db` `payouts`（券種別） |
| 取得時刻・TM snapshot | C | `prediction_time_machine.db`（実レース GREEN 0 件・未一括 JOIN） |

**区分:** A=保存済み B=計算で再現 C=未整備またはライブ専用

**リーク:** オッズ・人気は JV のレース結果行に載る「そのレースの事前オッズ」。結果ページの result オッズは使わない。TM の UNKNOWN_TIME は発走前扱いしない。

**既存ラベル（変更しない）:** `export_features_csv.py` — `arareA`=7番人気以下が3着内、`arareB`=勝ち馬6番人気以下、`ana2`=5番人気以下が3着内2頭以上、`honsen`=1・2番人気両方3着内。
