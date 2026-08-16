---
name: project-jravan-data-gap
description: JRA-VAN契約停止でjravan.dbが2026-06-21停止・血統は2023年から劣化。netkeibaパースで回避済み。TODOはrepo/jravan_todo.md
metadata: 
  node_type: memory
  type: project
  originSessionId: d55c28a0-3521-494c-8d35-19b459b44417
  modified: 2026-08-15T06:01:50.026Z
---

2026-08-15 に jravan.db を全テーブル棚卸しした結果と、契約停止中の回避策。
**契約再開時の手順書は `repo/jravan_todo.md`**(コマンド付き)。

## 実測した劣化
| 対象 | 収録範囲 | 状態 |
|---|---|---|
| races/results | 〜**2026-06-21** | 55日前で停止 |
| horses(血統) | birth 〜2021-06-19 | **2023年から劣化** |
| corrected_time.db | 〜2026-06-14 | DBに追随して停止 |
| data/export/*.csv | 2026-07-07生成(中身は6月まで) | 同上 |
| training | 2025-06〜2026-06の1年分 | 元から薄い |
| track_cond | 2,346件 / race_wind 1,500件 | 元から疎 |

**血統のデビュー年別 母名取得率**: 〜2022年100% → 2023年76.7% → 2024年**8.5%** →
2025年**0.2%** → 2026年**0%**。

## 回避策(すべて実施済み・netkeibaから直接取る)
| 欠けたもの | どこから取ったか | 効果 |
|---|---|---|
| 血統(父/母/母父) | shutuba_pastの `div.Horse01`/`Horse03`/`Horse04` | **0% → 100%** |
| 東西所属(tozai) | 調教師欄「栗東・」「美浦・」(括弧形式ではない) | **0% → 100%** |
| 3着馬との差・正式レース名 | 結果ページ(`fetch_comprehensive_result`) | 新規取得 |

⚠ 血統は `Bloodline='-'` のハードコードで、**HTMLにあるのにパースしていなかった**。
tozaiも `[東]`形式だけを想定し実データの「栗東・」形式を取れていなかった。
**「jravan.dbに無い」＝「取れない」ではない。まずHTMLを見ること。**

## バックテストへの影響と対処
ライブ表示は上記で解決したが、**過去分の血統は jravan.db を見るため穴が残る**。
→ train/holdout の分割を前倒しして対応する
   (例: [[verified_sibling_debut_rejected]]は 2017/2018-2023 で分割し直した)。

## JRDB UKC で血統を埋められる(JRA-VAN不要)
UKC(馬基本データ)に 父/母/母父馬名 + **母馬生年** + 父系統/母父系統コード がある。
仕様書は `data/jrdb/spec/ukc_doc.txt` に取得済み。
取り込みは **`scripts/jrdb_ukc_ingest.py`**(作成済・`horses_jrdb`テーブルに書き、既存hordesは無変更)。
必要なのは `UKC_2025.zip`(保険で2024/2023)。**2018-2022はjravan.dbが100%なので不要**。
⚠ JRDBは**レース当日08:00〜19:00はDL制限**。平日か19時以降に。

**How to apply:** DB更新後は必ず ①差分ingest → ②build_corrected_time → ③export_features_csv
→ ④smoke の順。補正Tの再構築を飛ばすと最強シグナル(荒れ時z+10.4)が古いまま静かに劣化する。
[[project_db_freshness]] [[verified_corrected_time]]
