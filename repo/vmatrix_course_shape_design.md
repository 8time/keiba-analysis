# V Matrix P2-D — コース形状 調査設計

> **段階:** 設計のみ。holdout 脚本・本番コード変更なし。  
> **目的:** コース形状が **V 座標・加点・赤枠** に入る価値ではなく、**既存展開情報への追加説明力**（D-1）および **V 近傍 caption 材料**（D-2）があるかを検証する設計を固定する。  
> **前提:** P0/P1 完了、`repo/vmatrix_improvement_scorecard.md` 固定。P2-A クローズ。

参照: `core/pace_map.py`, `scripts/layout_effect_backtest.py`, `core/pace_backtest.py`, `repo/vmatrix_p2_priority_research_design.md` § P2-D

---

## 0. 最終判定（先に）

| トラック | 状態 | 理由 |
|--------|:----:|------|
| **D-1（展開MAP・既存配線）** | **GO準備完了（限定）** | 既存 BT `layout_effect_backtest.py` に **正解・指標・比較** あり。holdout 2024–25 分割で再現可能 |
| **D-1（pos4 への layout 効果）** | **設計不足 → 停止** | `build_pace_context` は **layout を参照しない**。layout on/off で pos4 は不変。検証にはコード変更＝**D-3 禁止** |
| **D-2（V caption 説明力・定量）** | **設計不足 → 停止** | 「説明が正しい」の **既存正解定義・BT なし**。定性監査のみ可能 |
| **D-3** | **禁止** | 本設計のスコープ外（§10） |

**総合:** **条件付き GO準備完了** — 次に書ける holdout 脚本は **D-1b（展開MAP 直線フェーズ × layout on/off）のみ**。D-2 定量 holdout は **別 GO**（評価枠の合意）まで停止。

---

## 1. 対象となる既存コース変数

| 変数 | 型 | 意味（コード上） | 定義元 |
|------|-----|------------------|--------|
| `first_corner` | int m \| None | スタート→1角までの距離（目安） | `_FIRST_CORNER[(venue,surf,d)]` |
| `straight` | int m \| None | 最終直線長（目安）。芝内/外は **距離帯で近似** | `_STRAIGHT_LEN` + 京都/阪神/新潟分岐 |
| `straight_course` | bool | コーナーなし直線競馬（新潟芝1000） | `get_course_layout` 特例 |
| `notes` | list[str] | 人間向け説明文（閾値は fc/straight の **既存ハードコード**） | `get_course_layout` L138–156 |
| `course_profile_label` | str | 直線長 3 分類ラベル（≥400 / ≤335 / 標準） | `course_profile_label()` |
| `infer_turn` | '左'\|'右' | 開催場から回り方向 | `LEFT_TURN_VENUES` |
| `phases_for_distance` | list | 展開MAPフェーズ列（距離依存） | `pace_map.py` |

**表の性質:** すべて **静的目安値**（JV コース測量の live 取得ではない）。docstring にも「目安」と明記。

---

## 2. 各変数の取得元

| 入力 | 取得経路 |
|------|----------|
| `venue` | `race_id[4:6]` → `VENUE_CODES`（JRA 01–10） |
| `surface` | scraper / jravan `races.surface`（`'ダ' in surface` で芝ダ判定） |
| `distance` | `races.kyori` / scraper meta |

**関数入口:** `get_course_layout(venue, surface, distance)` → dict。  
**派生:** `course_profile_label(venue, surface, distance)` → 上記 dict の `straight` のみ使用。

---

## 3. 現在の利用箇所

### 3.1 展開パイプライン（D-1 関連）

| 箇所 | layout の使われ方 |
|------|-------------------|
| `estimate_pace_map()` | **使用あり:** `gate_w`（fc 閾値 200/350/550）、`straight_push`（straight 330/450）、`straight_course` でフェーズ短縮 |
| `build_pace_context()` | **使用なし** — `layout` 引数を受け取るが **body 内未参照**。`pos4` / `pace` / `forward` は layout 非依存 |
| `predict_finish()` | ctx 経由。layout 間接効果 **なし** |
| `describe_pace()` | `layout.get('notes')` を展開コメント末尾に **連結**（D-2 材料） |
| `app.py` ~L4587–4760 | `_pm_layout = get_course_layout(...)` → 展開MAP・describe_pace |

### 3.2 V エリア（D-3 禁止の確認）

| 箇所 | layout 接続 |
|------|-------------|
| `build_v_matrix()` | **なし** |
| V baba / pace radio | **静的 caption**（`app.py` L4946–4948）。layout 非参照 |
| P1 注記 | layout 非参照 |

### 3.3 エビデンス・適性

| 箇所 | 用途 |
|------|------|
| `app.py` | `course_profile_label` → エビデンス「コース特性(自動判定)」 |
| `calculate_strength_suitability` | ラベル文字列「直線が長い」「小回り」を **語句マッチ** |

### 3.4 既存バックテスト

| 脚本 | layout 関連 |
|------|-------------|
| `scripts/layout_effect_backtest.py` | **主 BT:** layout on/off × 展開MAP直線 vs 着順 |
| `core/pace_backtest.py` | layout を case に載せるが **pos4 評価は no-op** |
| `scripts/blood_course_backtest.py` | 直線長 **帯** × 血統（layout 関数とは別定義の近似表） |
| `scripts/course_arare_backtest.py` | 小回り場コード集合（layout 表とは別） |
| `scripts/pci_course_shape_backtest.py` | O/U 字 **場** 分類（PCI 交互作用・**却下済**） |

---

## 4. 欠損状況

| 項目 | 欠損パターン | 影響 |
|------|--------------|------|
| `first_corner` | `_FIRST_CORNER` に無い (venue,surf,d) → **None** | `gate_w=0.45` デフォルト（layout あり/なし差缩小） |
| `straight` | 表外 → **None** | `straight_push=0.45` デフォルト |
| `straight_course` | 新潟芝1000 のみ True | フェーズがスタート+直線のみ |
| `notes` | fc/straight 両方 None かつ特例なし → **空リスト** | describe_pace に追記なし |
| `course_profile_label` | straight None → **「標準」** | エビデンスは常に何かしら表示 |

**layout_effect_backtest の報告値（脚本内コメント）:** `first_corner` ヒット率を計測する設計。repo に **保存済み summary.json は無し**（再実行が必要）。

**母集団設計上:** `first_corner is None` かつ `straight is None` のレースは **D-1 効果が出にくい** → 主分析は **layout 表ヒットレース** に限定する候補（事後変更禁止で holdout 脚本に明記）。

---

## 5. 既存検証の有無

| 検証 | 対象 | 結果の所在 | layout 形状との関係 |
|------|------|------------|---------------------|
| **layout_effect_backtest.py** | 展開MAP **最終直線** x vs **chakujun** | 脚本 stdout のみ（analysis 未保存） | **直接**（layout on/off） |
| **pace_backtest.py** | **pos4** vs **corner4** | `project_pace_map_rebuild.md`（spearman ~0.46 等） | layout **無効**（no-op） |
| **vmatrix_pos4_align_check** | V 帯一致 pos4 vs ten | `repo/analysis/vmatrix_pos4_align/summary.json` | layout **無関係** |
| **course_arare_backtest** | 小回り場 × 荒れ | verified/priced-in 系 | 「小回り荒れ」は **オッズ織込み** |
| **blood_course_backtest T1** | 直線長帯 × 血統 | 脚本 | layout 表と **近似**だが別定義 |
| **pci_course_shape** | O/U × PCI | **却下**（holdout z 未達） | V/caption には **非推奨** |
| **layout.notes 文言** | 「短い→内先行有利」等 | **専用 BT なし** | 一般論の **数値裏付け未確認** |

---

## 6. D-1 — 正解・評価指標候補

### 6.1 既存正解定義（repo 内・採用可）

#### GT-D1a — 着順（layout_effect_backtest 準拠）

| 項目 | 定義 |
|------|------|
| **予測** | `estimate_pace_map(..., layout=A\|{})` の **最終フェーズ** 各馬 `x`（大きい=前方） |
| **正解** | 同レース `results.chakujun`（**事後・着順**） |
| **指標** | レース内 **Spearman ρ**（`-x` vs chakujun。脚本 L131 と同型） |
| **比較** | paired: ρ(layout=full) − ρ(layout={}) |
| **リーク** | 予測は `before_key=race_key` プロファイルのみ。正解は当該レース結果（評価専用） |

**根拠脚本:** `scripts/layout_effect_backtest.py` L7–8, L127–136, L168–174。

#### GT-D1b — 4角通過（pace_backtest 準拠）

| 項目 | 定義 |
|------|------|
| **予測** | `build_pace_context` → `pos4`（または `predict_corner_order`） |
| **正解** | `corner4`（欠損時 `corner3`）を頭数正規化 `actual_n` |
| **指標** | Spearman ρ、`leader_hit_rate`、`top3_overlap` |
| **根拠** | `core/pace_backtest.py` L9–12, L28–41, L122–157 |

**重要制約:** 現行コードでは **layout on/off で pos4 は同一**。  
→ GT-D1b は「展開 pos4 ベースライン」の参照値であり、**layout 追加説明力は測れない**。holdout 脚本に **含めない**（含めると D-3 改修を暗示する）。

#### GT-D1c — 直線到達（evaluate_finish 準拠）

| 項目 | 定義 |
|------|------|
| **正解** | `chakujun` 正規化 `finish_n` |
| **予測** | `predict_finish` 等 |
| **指標** | Spearman vs 着順 |

**layout 効果:** ctx 経由で **なし**（build_pace_context が layout 未使用）。D-1 主分析から **外す**。

### 6.2 D-1 holdout プロトコル（設計固定）

| 項目 | 規定 |
|------|------|
| DB | `data/jravan.db` |
| 期間 | train 2021–2023 / holdout **2024–2025**（`vmatrix_pace_holdout` 同型） |
| 母集団 | JRA jyo 01–10、`shusso_tosu≥8`、`fetch_jv_profiles` ≥40%、**layout 表ヒット**（fc または straight 非 None） |
| 比較 | A= `get_course_layout` / B= `{}` |
| 主指標 | holdout **mean(ρ_A − ρ_B)**（paired） |
| 成功条件（P2 設計書） | holdout で **+0.02 以上**（`vmatrix_p2_priority_research_design.md` L129） |
| 副指標 | first_corner ヒット率、straight 非 None 率、ρ_A 単独の絶対水準 |
| 禁止 | layout 閾値変更、pos4/build_pace_context 改修、新 ML |

### 6.3 D-1 で測れないもの（明示）

- **「layout が pos4 を改善するか」** — 未配線のため不可（§0）
- **「layout が V 赤枠該当を変えるか」** — D-3 禁止
- **corner4 を正解に layout を pos4 へ入れる実験** — コード変更必須 → 禁止

---

## 7. D-2 — 評価方法候補

### 7.1 現状の「説明」経路

| 出力 | 内容 | V との距離 |
|------|------|------------|
| `layout['notes']` | fc/straight 閾値に基づく日本語（**既存閾値のみ**） | `describe_pace` → 展開MAP下コメント。**V caption ではない** |
| `course_profile_label` | 3 分類ラベル | エビデンス表・適性スコア |
| V radio caption | 「開幕週・コース替り直後」等 | **layout 非連動・固定文** |

### 7.2 既存裏付けの調査結果

| 主張（notes / profile より） | 既存検証 | 結論 |
|------------------------------|----------|------|
| 直線短い → 内・先行有利 | 専用 BT **なし**。blood_course T1 は **血統×直線帯** | caption **定量未確認** |
| 直線長い → 差し不利小 | 同上 | 未確認 |
| 小回り → 先行有利 | course_arare: 小回り荒れは **priced-in** | **買い/caption 強調に不向き** |
| 1角まで短い → 内枠先行 | 専用 BT **なし** | 未確認 |
| O/U 字 × 脚質 | pci_course_shape | **却下** |

### 7.3 D-2 評価候補（設計段階）

| ID | 方法 | 既存正解 | 採用可否 |
|----|------|----------|----------|
| **D2-Q1** | `describe_pace` の notes 有/無で **文言が ctx.pace と矛盾しないか** ルール監査 | なし（定性） | 脚本不要・手動/checklist 可 |
| **D2-Q2** | notes の straight 帯別に **当日 empirical front_rate** と符号一致率 | empirical_bias（レース時点） | **副次**。baba/V とは別 |
| **D2-Q3** | V 直下に notes を **表示追加**した場合の UX | なし | 実装 GO 後。今回スコープ外 |

**定量 holdout 用 GT:** **存在しない**。新規「説明正解スコア」を invent しない（ユーザー指示）。

### 7.4 D-2 と V の関係（固定）

- D-2 成功しても **赤枠・座標は変えない**（D-3 禁止）
- 成功形: 展開 caption または V **近傍** の固定文改善（P1 注記の延長）
- 「短いから前有利」を **自動 baba/pace 初期値** にしない（P2-A 教訓）

---

## 8. リーク防止

| データ | 予測側 | 評価側 |
|--------|--------|--------|
| 過去走プロファイル | `fetch_jv_profiles(..., before_key=race_key)` | — |
| layout 表 | 静的（venue,surf,d のみ） | — |
| corner4 / chakujun | **使わない** | GT-D1a/b の正解のみ |
| 当日 empirical | D-2 副次のみ | 当該 R 以前の勝ち馬 |

**tenkai_bias / intraday と同型:** 馬の事前情報=枠・プロファイル。通過順は正解ラベルのみ。

---

## 9. 母集団候補

| 条件 | D-1 | D-2 |
|------|-----|-----|
| JRA 01–10 | ○ | ○ |
| shusso_tosu ≥ 8 | ○ | ○ |
| profile 40% 以上 | ○ | ○ |
| layout fc または straight ヒット | ○（推奨） | ○（notes 非空） |
| 芝/ダート | 両方（layout 表は芝ダ別） | 同左 |
| NAR | 除外（layout 表が JRA 中心） | 除外 |

**欠損:** 上記を満たさないレースは **補完せず除外**。

---

## 10. D-3 禁止事項（再掲）

以下は P2-D holdout・本番の **いずれも禁止**:

- pos4 / X / Y への layout 係数投入
- `build_pace_context` / `build_v_matrix` / `resolve_v_pos` の shape 改修
- V 該当加点・新 V スコア・赤枠直接変更
- layout 閾値（200/350/550、330/450 等）の **holdout 後調整**
- コース形状 × V の新規合成モデル・ML

**許可されるのは:** D-1 の **既存 estimate_pace_map 経路** の on/off 比較、D-2 の **既存 notes 文言** の表示監査のみ。

---

## 11. holdout へ進むための GO 条件

### 11.1 D-1b（展開MAP 直線 × layout）— **GO 可**

| # | 条件 | 状態 |
|---|------|:----:|
| 1 | 既存正解定義（chakujun） | ✅ layout_effect_backtest |
| 2 | 既存指標（Spearman ρ paired） | ✅ 同上 |
| 3 | 既存比較（layout full vs {}） | ✅ 同上 |
| 4 | リーク規約 | ✅ before_key |
| 5 | holdout 分割 | ✅ 2024–25（設計固定） |
| 6 | D-3 非抵触 | ✅ estimate_pace_map のみ |

**次成果物（別 GO 後）:** `scripts/vmatrix_p2_layout_check.py` + `repo/analysis/vmatrix_p2_d/summary.json`

### 11.2 D-1a（pos4 × layout）— **NO-GO**

| # | 条件 | 状態 |
|---|------|:----:|
| layout が pos4 を変える既存コード | ❌ 未配線 |

→ holdout 脚本を書いても **常に差分 0**。停止。

### 11.3 D-2（V caption 定量）— **NO-GO（設計不足）**

| # | 条件 | 状態 |
|---|------|:----:|
| 説明力の既存正解 | ❌ なし |
| notes 主張の専用 BT | ❌ なし |

→ 定性 checklist（D2-Q1）のみ先行可。**定量 holdout は停止**。

---

## 12. スコアカード連携（P2-D  pré）

`repo/vmatrix_improvement_scorecard.md` 更新は **holdout 実行後**。設計段階では:

| ID | 判定 |
|----|------|
| P2-D | **調査設計完了・holdout 未着手** |
| P2-D-1b | GO準備完了 |
| P2-D-1a / D-2 定量 | 設計不足 |

---

## 13. 参照ファイル

| パス | 役割 |
|------|------|
| `core/pace_map.py` L38–184, L669–781, L888–950, L1364–1425 | layout 定義・配線・未使用箇所 |
| `scripts/layout_effect_backtest.py` | D-1 既存 BT テンプレ |
| `core/pace_backtest.py` | pos4 GT 定義（layout no-op 注意） |
| `repo/vmatrix_p2_priority_research_design.md` | 成功条件 +0.02ρ |
| `repo/vmatrix_improvement_scorecard.md` | P0–P2-A 固定 |

---

*作成: 2026-09-07 / ステータス: **条件付き GO準備完了（D-1b のみ）***
