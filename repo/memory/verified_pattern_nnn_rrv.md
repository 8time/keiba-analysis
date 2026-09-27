# verified_pattern_nnn_rrv

description: 鉄板 NNN/NNV と中庸 RRR/RRV の holdout 比較（3列目を N/R vs V）

## データ定義

### 妙味度ゾーン (formation_stats.ZONE_BOUNDS)
- **D 鉄板**: 0 ≤ vscore < 50
- **C 中庸**: 50 ≤ vscore < 70
- **B/A 荒れ**: vscore ≥ 70（本検証では対象外）
- vscore: `data/export/races.csv`（欠損時 `value_scanner.race_value_score`）

### 列の意味
- **N**: 人気順（`ninki` 昇順）
- **R**: Rank = `ability_score` 昇順（小さいほど強い。holdout の LTR 代理）
- **V**: VH = `vh2_score` 降順（穴馬ハンタースコア。app の「V=VH順位」）

### 4パターン（vh_leg3_verify と同一）
| パターン | ゾーン | 券種 | 形 | 1-2列 | 3列 |
|---------|--------|------|-----|-------|-----|
| NNN | D 鉄板 | 3連複 | 2-3-6 | 人気 | 人気 |
| NNV | D 鉄板 | 3連複 | 2-3-6 | 人気 | VH |
| RRR | C 中庸 | 3連単 | 2-4-7 | Rank | Rank |
| RRV | C 中庸 | 3連単 | 2-4-7 | Rank | VH |

holdout: day >= 20240101。配当: `data/jravan.db` payouts 実配当。

## holdout 成績

| パターン | レース数 | 的中率 | ROI | ROI 95%CI | 最大連敗 | 平均点数 |
|---------|---------|--------|-----|-----------|---------|---------|
| NNN | 3994 | 52.7% | 52.4% | 50.0-54.8% | 13 | 16.0 |
| NNV | 3994 | 52.9% | 52.2% | 50.0-54.5% | 11 | 16.1 |
| RRR | 3128 | 7.4% | 88.2% | 65.5-111.9% | 74 | 30.0 |
| RRV | 3128 | 8.4% | 82.8% | 61.2-107.4% | 58 | 32.0 |

## ペア比較（NNN vs NNV / RRR vs RRV）

### 鉄板 NNN vs NNV
- 的中率: NNN 52.7% vs NNV 52.9% (差 +0.1pp)
- ROI: 52.4% vs 52.2% (差 -0.2pp, bootstrap差95%CI -1.6〜+1.3pp)
- McNemar: baseのみ 70 / testのみ 75 (z=+0.42, 非有意)
- 判定: **差は小さい/非有意（的中 +0.1pp, ROI -0.2pp）**

### 中庸 RRR vs RRV
- 的中率: RRR 7.4% vs RRV 8.4% (差 +1.1pp)
- ROI: 88.2% vs 82.8% (差 -5.4pp, bootstrap差95%CI -34.0〜+22.9pp)
- McNemar: baseのみ 45 / testのみ 78 (z=+2.98, 有意)
- 判定: **的中率差は McNemar 有意 — RRV が優位（ROI差 -5.4pp は CI 跨ぎ）**

## 迷ったときの推奨

**鉄板: NNN と NNV の差は小さい（的中 0.1pp / ROI -0.2pp）— デフォルトは点数の少ない NNN でよい。**
**中庸: 差は統計的に明確でない — デフォルトは検証済み本線 RRR（点数・説明の単純さ優先）。**

## 再現
```
python scripts/pattern_nnn_rrv_backtest.py
```
