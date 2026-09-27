# verified_bettype_selector_phase2

description: live score版馬連・馬単 + zone+cross_n 簡略ルール holdout 検証

## STEP 1 定義

| 項目 | 定義 | コード |
|------|------|--------|
| **live score / Rank** | `ability_score` 昇順（小=強）。ライブ LTR は高いほど強い（符号反転） | `playbook_tickets._ltr_order` |
| **ninki** | 人気昇順 | CSV `ninki` |
| **cross_n** | Rank上位4 ∩ VH上位4 の共通馬数 | `consensus_view.py` L433-435 |
| **zone** | D: vscore 0-49 / C: 50-69 | `formation_stats.ZONE_BOUNDS` |
| **VH穴** | 精鋭1,2 + 広域1 (pop≥6) | `elim_miss1_hunter.hunter_ranks` |
| **馬連/馬単** | 軸1 × 相手6 (recommend_quinella 構造) | `trio_engine.recommend_quinella_exacta` |
| **3連複** | D: 人気1-2×3-4 (2点) / C: Rank2-3-6 | `playbook_tickets` |
| **3連単 NNV** | 人気2×4×VH穴3 | `_nnv_rrv_whatif.py`（playbook未配線） |
| **3連単 RRR** | Rank2-4-7 (30点) | `playbook_tickets` C zone ライブ |

train: day≤20241231 / holdout: day≥20250101

---

## Q1: 馬連・馬単は live score で券種選択候補として価値があるか？

### holdout 比較（軸×相手6点）

| 券種 | 軸 | 的中率 | ROI | vs 人気軸 |
|------|-----|--------|-----|-----------|
| 馬連 | 人気1 | 47.3% | 78.8% | — |
| 馬連 | **Rank1** | 30.2% | 72.3% | 的中-17pp / ROI-6pp |
| 馬単 | 人気1 | 29.2% | 76.3% | — |
| 馬単 | **Rank1** | 17.6% | 78.0% | 的中-12pp / ROI+2pp |

**結論: いいえ（主役にはならない）。**
- Rank軸は的中率が大幅に下がる。馬連は ROI も悪化。
- 馬単 Rank は ROI が僅差（+1.6pp）だが的中率半減。資金効率・安定性で不利。
- D鉄板でも Rank軸馬連 ROI 71% < 人気軸 78%。
- **券種選択の第1候補は引き続き 3連複 / 3連単 NNV。馬連・馬単は補助以下。**

---

## Q2: `zone + cross_n` 簡略ルールは holdout で優位か？

### Rule B（train 決定: C & cross_n≥3 → 3連複、else NNV）

| ルール | holdout ROI | 95%CI | 最大連敗 | 2025 | 2026 |
|--------|------------|-------|---------|------|------|
| 常に3連複 | 75.6% | 63-90 | 46 | 74% | 79% |
| 常にNNV | 78.2% | 67-91 | 101 | 87% | 60% |
| ゾーン既定 (Rule A) | 80.3% | 66-95 | 45 | 85% | 71% |
| **Rule B** | **87.7%** | **72-106** | 40 | **89%** | **85%** |
| Rule C (+D 1強→馬単Rank) | 86.5% | 72-104 | 33 | 88% | 84% |

**結論: はい。**
- Rule B は第1フェーズの複雑ルール（83.5%）を上回り、過学習を減らした形で holdout 87.7%。
- 条件は **たった1つ**: C zone で cross_n≥3 なら 3連複、それ以外 C→NNV。
- 2025/2026 両年で Rule B ≥ ゾーン既定。

---

## Q3: D=3連複 / C=NNV は再現性があるか？

| zone | 3連複 ROI | NNV ROI | 相対優位 |
|------|----------|---------|---------|
| **D 鉄板** | **91%** | 77% | 3連複 |
| **C 中庸** | 72% | **79%** | NNV |

- ゾーン既定 (Rule A) holdout ROI 80.3%、年別 2025:85% / 2026:71%。
- **方向性は再現**: D→3連複、C→NNV の単純ルールは holdout でも成立。
- Rule B の cross_n 例外で C 内の改善余地あり。

---

## Q4: NNV 2-4-7 を live playbook へ配線する価値があるか？

### C zone holdout のみ

| 戦略 | 的中率 | ROI | 平均点 | 2025 | 2026 |
|------|--------|-----|--------|------|------|
| NNV 2-4-7 (VH穴) | 6.1% | 78.7% | 16 | 84% | 67% |
| **RRR 2-4-7 (live)** | **7.7%** | **92.3%** | 30 | **102%** | 71% |

**結論: 現時点では配線不要。**
- 既存 playbook の Rank 3連単30点 (RRR) が NNV を holdout で上回る。
- NNV は D zone 向け研究ロジックとしては有効だが、C zone live 置換には不適。
- D zone ではそもそも 3連複2点 (91% ROI) が NNV (77%) を大きく上回る。

---

## Q5: 第1段階ルールはどこまで単純化できるか？

### 推奨（検証済み・最小）

```text
if zone == D:
    券種 = 3連複（playbook 2点）
elif zone == C:
    if cross_n >= 3:   # train で決定、holdout 固定
        券種 = 3連複
    else:
        券種 = 3連単 NNV 2-4-7
else:
    見送り
```

### 第2段階（フォーメーション）— 今回は未接続

- 3連複 → playbook 2点 (D) / Rank2-3-6 (C)
- 3連単 → NNV 2-4-7（研究）/ RRR 2-4-7（live C 既定）

### やらない方がよいこと

- 馬連・馬単を第1段階に入れる（Rule C 系は ROI 87%→85% に低下）
- NNV を live playbook C に配線（RRR が優位）
- pop_struct / fav1 等を大量追加（Rule B で十分）

---

## F. 実装判断

| 項目 | 判断 |
|------|------|
| 推奨券種 UI | **まだ作らない**（全券種 ROI<100%） |
| 第1段階ルール | Rule B をバックエンドに保持する価値 **あり** |
| live playbook 変更 | **不要**（RRR 維持、NNV 配線見送り） |
| 次の接続 | 券種決定後のフォーメーション選択（第2段階） |

## 再現

```
python scripts/bettype_selector_phase2.py
```
