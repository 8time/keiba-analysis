# JRA-VAN 契約再開時のTODO ＋ データ鮮度の現状

最終更新: 2026-08-15

このファイルは「JRA-VANの契約を再開したとき、何を・どの順で・どのコマンドでやるか」を
1箇所にまとめたもの。契約が切れている間に発生した劣化と、その回避策も記録する。

---

## 0. まず現状（2026-08-15 時点の実測）

### データの鮮度

| テーブル/ファイル | 中身 | 収録範囲 | 状態 |
|---|---|---|---|
| `jravan.db` races / results | レース・出走結果 | 1954-10-23 〜 **2026-06-21** | 🔴 **55日前で停止** |
| `jravan.db` horses | 血統(父/母/母父) | birth 〜 **2021-06-19** | 🔴 **2023年から劣化** |
| `jravan.db` training | 調教時計 | 2025-06-10 〜 2026-06-14 | 🟡 1年分のみ |
| `jravan.db` track_cond | クッション値/含水率 | 2018-07 〜 2026-06 | 🟡 2,346件と疎 |
| `jravan.db` race_wind | 風向風速 | — | 🟡 1,500件のみ |
| `data/corrected_time.db` | 補正タイム(H7図) | 〜 2026-06-14 | 🔴 DBに追随して停止 |
| `data/export/*.csv` | LTR/vh2の学習元 | 2026-07-07 生成 | 🔴 中身は2026-06まで |

### 血統(horses)の劣化 — デビュー年別の母名取得率

| デビュー年 | 頭数 | 母名あり | 父名あり |
|---|---|---|---|
| 〜2022 | 各4,600〜4,900 | **100%** | **100%** |
| 2023 | 4,797 | 76.7% | 83.3% |
| 2024 | 4,910 | **8.5%** | 43.5% |
| 2025 | 4,983 | **0.2%** | 70.9% |
| 2026 | 1,696 | **0%** | 100% |

**影響**: ライブ表示は 2026-08-15 に `core/scraper.py` を修正して netkeiba から
直接取るようにしたので**影響なし**(実測 0% → 100%)。
残る影響は**バックテストのみ**(過去分の血統は jravan.db を見るため)。

---

## 1. 契約再開したら、この順でやる

### ① 差分取り込み（最優先・数分）

```
C:\Users\kimnhaty\pythonx86-312\tools\python.exe scripts\jvlink_ingest.py --from 20260621000000 --option 1
```

- `--option 1` は差分のみ。`--option 4`(全件)は数時間かかるので普段使わない
- **32bit版Pythonでないと JV-Link が動かない**(上のパスがそれ)
- 取り込み後: `python -c "from core import db_freshness as d; print(d.status())"` で🟢を確認

### ② 補正タイムの再構築（①の後・必須）

```
python scripts\build_corrected_time.py
```

補正タイムは検証済みシグナルの中で最強クラス(荒れ時 z+10.4)。DBを更新したら必ず作り直す。
放置すると `data/corrected_time.db` が古いままで、静かに精度が落ちる。

### ③ CSVフィーチャーストアの再生成（②の後）

```
python scripts\export_features_csv.py
```

LTR(`ability_score`)と vh2 の学習元。バックテストの土台なので、
検証をやり直す前に必ず更新する。

### ④ 血統の穴埋め（②③と独立・JRDBで代替可）

JRA-VANを再開すれば `horses` も自動で埋まるはずだが、埋まらない場合はJRDBのUKCを使う。
→ 「2. JRDB UKC で血統を埋める」参照。

### ⑤ モデルの再学習（任意・データが1年ぶん増えてから）

```
python scripts\build_ltr_model.py          # ability_score
python scripts\value_hunter_light.py       # vh2(妙味馬)
```

⚠ [[verified_ltr_refresh_rejected]] で「窓を前に進めても改善しない(+0.11pp=誤差)」と
検証済み。**データが増えたからといって自動で再学習しない**。やるなら必ず holdout で比較。

---

## 2. JRDB UKC で血統を埋める（JRA-VAN不要）

JRDBの **UKC(馬基本データ)** に血統がフル装備されている。JRA-VANが無くてもこれで埋まる。

```
父馬名 / 母馬名 / 母父馬名 / 父馬生年 / 母馬生年 / 母父馬生年
父系統コード / 母父系統コード（12系統の大系統分類・netkeibaには無い）
```

### 手順

1. JRDB会員ページ **年度パックコーナー** から `UKC_2025.zip` を取得
   （保険で `UKC_2024.zip` `UKC_2023.zip` も。**2018-2022は jravan.db が100%なので不要**）
2. `data/jrdb/raw/` に置く（解凍不要・`.gitignore`済み）
3. 確認: `python scripts\jrdb_ukc_ingest.py --dry-run`
4. 取り込み: `python scripts\jrdb_ukc_ingest.py`
   → `jravan.db` に **`horses_jrdb`** テーブルを新規作成（既存 `horses` は触らない）
   → 参照側は `horses` と `horses_jrdb` を COALESCE する

### ⚠ JRDBのアクセス制限

**レース当日 08:00〜19:00 は過去データのDLが制限される**（サーバ負荷対策）。
土日の日中は取れない。**平日、または土日なら19時以降**に行うこと。
`scripts/jrdb_fetch.py` にも同じガードが実装済み。

### 規約の注意

- 個人利用限定。複製・頒布・第三者提供は禁止（`data/jrdb/` は `.gitignore` 済み）
- 機械的な一括取得は規約第8条11項に抵触のおそれ。**過去分は必ず年度パックを使う**
  （日別に大量リクエストしない）

---

## 3. 契約が切れている間の回避策（実施済み）

| 問題 | 回避策 | 状態 |
|---|---|---|
| 血統がライブで取れない | `core/scraper.py` で netkeiba の `Horse01`(父)/`Horse03`(母)/`Horse04`(母父) を直接パース | ✅ 実施済(0%→100%) |
| バックテストの血統が2023年以降欠損 | train/holdout の分割を前倒しして検証（例: 兄姉検証は 2017/2018-2023 で分割） | ✅ 運用で対応 |
| 3着馬との差・レース正式名称 | netkeiba の結果ページから取得（`fetch_comprehensive_result`） | ✅ 実施済 |
| 東西所属(tozai) | netkeiba の調教師欄「栗東・」「美浦・」からパース | ✅ 実施済(0%→100%) |

**教訓**: netkeibaのHTMLには使っていない情報がまだ眠っている可能性がある。
「jravan.dbに無い」＝「取れない」ではない。まずHTMLを見ること。

---

## 4. 契約再開後にやり直す価値がある検証

契約停止のせいで**データ不足で判定保留**になっているもの。

| 項目 | なぜ保留か | 再開後にできること |
|---|---|---|
| **母の出産年齢16歳超** | 母馬生年がどこにも無い | UKC取り込みで即検証可能（JRDBで足りる） |
| 調教の加速ラップ | `training` が1年分のみ | 数年たまれば検証可能。ただし調教時計自体は[効果ゼロ](verified_training_and_sire_popbucket)確定 |
| クッション値×種牡馬 | `track_cond` が2,346件と疎 | 件数が増えれば再検証 |
| 重賞でのRank優位 | holdout n=975 で標本不足 | データが増えれば[判定可能](verified_class_rank_gradient) |

---

## 5. 定期メンテのチェックリスト

DB更新のたびに、この順で確認する。

```
1. python -c "from core import db_freshness as d; print(d.status()['msg'])"   # 🟢か
2. python scripts\build_corrected_time.py                                    # 補正T再構築
3. python scripts\export_features_csv.py                                     # CSV再生成
4. python tests\smoke.py                                                     # 全緑か
```

`db_freshness` のしきい値（実測ベース）:
- 14日: 🟢 まだ大丈夫 / 21日: 🟡 そろそろ / 28日: 🟠 更新時期 / 49日: 🔴 要更新
- 「DBがN日古いとき直近走が欠ける馬の割合」は 21日で29%、28日で42%、49日で60%
