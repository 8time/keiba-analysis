# P2-D1b — コース layout × 展開MAP最終直線 holdout 報告

> **実施日:** 2026-09-07  
> **脚本:** `scripts/vmatrix_p2_layout_check.py`  
> **出力:** `repo/analysis/vmatrix_p2_d/summary.json`  
> **本番変更:** なし（core/ app.py 未変更）

---

## スコープ確認（必須）

本検証は **展開MAPの既存最終直線 x** に対する layout 追加効果のみ。

| 対象外（変更禁止・未検証） |
|---------------------------|
| V 赤枠・V 座標・pos4 |
| `build_pace_context` / `build_v_matrix` |
| layout → V baba / pace / coords 接続 |
| 新規 layout 重み・閾値・ML・買い目・Rank/VH |

---

## 1. 対象母集団

| 項目 | 値 |
|------|-----|
| DB | `jockey_jv` SQLite（`core/jockey_jv.py`） |
| 期間 | **2024–2025**（holdout） |
| 抽出 | `races` テーブル、`CAST(year AS INTEGER) BETWEEN 2024 AND 2025` |
| 頭数 | `shusso_tosu >= 8` |
| サンプリング | `sample_every=1`（全件） |
| 結果行 | `results.chakujun > 0 AND umaban > 0` |
| プロファイル | `fetch_jv_profiles(..., before_key=race_key)`（リーク防止） |

| 母数 | 件数 |
|------|------|
| クエリ対象レース | 10,913 |
| paired 評価完了 | **10,803** |
| 頭数不足スキップ | 110 |
| 展開MAP生成失敗 | 0 |

**layout 表ヒット（first_corner 非 null）:** 3,612 / 10,913 = **33.4%**

---

## 2. A/B 定義

| 条件 | layout 引数 | 意味 |
|------|-------------|------|
| **A** | `{}` | layout なし（gate_w=0.45, straight_push=0.45 デフォルト） |
| **B** | `get_course_layout(venue, surf, kyori)` | 既存コース表（94エントリ拡充済み） |

`scripts/layout_effect_backtest.py` と同型。  
（原 BT はラベルが逆記載だが、比較内容は同一: with vs without layout）

---

## 3. 正解定義

| 項目 | 定義 |
|------|------|
| **予測** | `estimate_pace_map(...)` の **最終フェーズ** 各馬 `x`（大きい = 前方） |
| **正解** | 同レース `results.chakujun`（着順） |
| **相関方向** | Spearman ρ(`-x`, `chakujun`) — x を反転して着順と正相関 |

---

## 4. 欠損処理

| 欠損 | 処理（layout_effect_backtest 準拠） |
|------|-------------------------------------|
| ten 欠損 | `score = 0.5` フォールバック |
| ninki / agari / finish_hist | extras に載せるのみ（無ければ省略） |
| layout 表未ヒット | `first_corner=None`, `straight=None` → デフォルト係数 |
| chakujun 欠損馬 | `actual.get(u, 99)`（脚本同型） |
| 頭数 < 8 | レース除外 |

train で閾値・ルールの再調整は **行っていない**。

---

## 5. holdout 期間

- **2024–2025** を holdout として全件評価
- 再現確認: 2023–2025, `sample_every=5`, `limit=2000`（原 BT 同条件）

---

## 6. Spearman ρ

### holdout（2024–2025, n=10,803）

| 条件 | mean ρ | SD |
|------|--------|-----|
| A（layout なし） | **0.5273** | 0.2391 |
| B（layout あり） | **0.5273** | 0.2391 |

### 再現確認（2023–2025 sample, n=1,969）

| 条件 | mean ρ | SD |
|------|--------|-----|
| A | 0.5228 | 0.2361 |
| B | 0.5228 | 0.2361 |

原脚本 `layout_effect_backtest.py`（500R サンプル）でも **+0.0000** を確認。

---

## 7. paired 差（主比較）

| 指標 | holdout | repro |
|------|---------|-------|
| **mean(B − A)** | **0.0000** | 0.0000 |
| SD | 0.0000 | 0.0000 |
| median | 0.0000 | 0.0000 |
| paired t | 0.00 | 0.00 |
| 改善レース率 | 0.0% | 0.0% |
| 悪化レース率 | 0.0% | 0.0% |
| 不変レース率 | **100.0%** | 100.0% |

---

## 8. レース数

| | holdout | repro |
|--|---------|-------|
| paired n | 10,803 | 1,969 |
| fc ヒット率 | 33.4% | 37.0% |

---

## 9. 差分の分布

全レースで **B − A = 0.0000**（完全一致）。

| 分位 | holdout |
|------|---------|
| p10 | 0.0000 |
| p25 | 0.0000 |
| median | 0.0000 |
| p75 | 0.0000 |
| p90 | 0.0000 |

統計的安定性: 差分分散 = 0、t 検定 = 0。**layout 有無で Spearman が 1 レースも動いていない。**

---

## 10. 成功条件判定

| 事前条件 | 結果 |
|----------|------|
| B − A ≥ +0.02 ρ | **未達**（0.0000） |
| 悪化していないか | ✅ 悪化なし（ただし改善もゼロ） |
| 十分なレース数 | ✅ 10,803R |
| paired 分布 | ✅ 報告済（全件 0） |
| 統計的安定性 | ✅ 再現 BT でも同一 |

**判定: NO-GO** — 追加説明力なし（layout あり/なしで予測が同一）

---

## 11. 実装可否

| 項目 | 結論 |
|------|------|
| 展開MAP 最終直線への layout 追加 | **NO-GO** — 現行コードでは効果ゼロ |
| layout → V 接続 | **根拠なし**（本 holdout の対象外かつ効果なし） |
| describe_pace notes（D-2 caption） | 本 holdout 未検証（別トラック） |
| 次段階 | layout を **final x に効かせるコード変更** は D-3 相当のため **設計 GO 前に禁止** |

### ゼロ差分のコード上原因

`core/pace_map.py` `estimate_pace_map()`:

1. **最終フェーズ（直線）** の `base = finish[u]`（`predict_finish`）— layout **非参照**
2. `gate_w`（first_corner 由来）は **スタート** フェーズのみ使用
3. `straight_push`（straight 由来）は **計算されるが未使用**（dead code）
4. `build_pace_context` / `pos4` は layout 引数を **body で未参照**

→ layout on/off で **最終直線 x が bit 一致** → Spearman も完全一致。

---

## 結論

### 判定: **NO-GO**

既存 course layout を展開MAP最終直線 x の予測に入れても、**着順との Spearman ρ は 1 ビットも変わらない**（10,803 holdout + 原 BT 再現）。

### 分離報告（重要）

| 質問 | 回答 |
|------|------|
| layout を **V へ入れる根拠**になったか？ | **ならない。** V 未接続・効果ゼロ |
| **展開MAPだけ**の改善だったか？ | **改善自体がゼロ。** 最終直線 x は layout 非依存の実装 |
| 今後 layout を活かすには？ | `estimate_pace_map` の直線フェーズ等への配線変更が必要だが、それは **本 holdout スコープ外（D-3）** |

---

## 付録: 再現コマンド

```bash
# holdout 2024-25
python scripts/vmatrix_p2_layout_check.py

# + 原 BT 同条件 repro
python scripts/vmatrix_p2_layout_check.py --repro

# 原脚本（参考）
python scripts/layout_effect_backtest.py --from 2023 --to 2025 --sample-every 5 --limit 2000
```
