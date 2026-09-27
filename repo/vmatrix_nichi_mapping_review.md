# P2-A nichi_bias マッピング調査レビュー

> **段階:** 調査のみ。holdout・実装・コード変更なし。  
> **日付:** 2026-09-07  
> 参照: `core/track_bias.py`, `app.py`, `repo/vmatrix_nichi_holdout_design.md`

---

## 1. nichi_bias の実際の意味

### 1.1 関数の位置づけ

`nichi_bias(nichi, surface='芝')` は **Phase 5: 開催日目バイアス**（`core/track_bias.py` L824–871）。

- **入力:** JV の開催日目 `nichi`（1–12）、馬場 `surface`
- **ダート:** `'ダ' in surface` → **即 None**（芝専用）
- **出力:** 静的ルックアップ表 + 人間向けラベル。**確率推定・学習・V 座標には未接続**

docstring:

> 開催日目から**芝の傷み傾向**を返す。

### 1.2 定数 `_NICHI_FRONT` / `_NICHI_INNER`

```827:836:core/track_bias.py
# jravan.db 2018-25 芝の開催日目別平均(バックテスト済み):
#   day1=front56.0%/inner33.7% → day7=front52.2%/inner26.4%
_NICHI_FRONT = { 1: 0.560, 2: 0.537, ... }
_NICHI_INNER = { 1: 0.337, 2: 0.326, ... 7: 0.264, ... }
```

| 定数 | 意味（コード上の定義） | スケール |
|------|------------------------|----------|
| `_NICHI_FRONT[d]` | 開催 **d 日目** の芝レースにおける、**勝ち馬の前残り率の人口平均** | 0–1（率） |
| `_NICHI_INNER[d]` | 開催 **d 日目** の芝レースにおける、**勝ち馬の内枠勝率の人口平均** | 0–1（率） |

**「前残り率」「内枠勝率」の operational 定義**は `empirical_bias()` と同型（`track_bias.py` L400–401）:

- **front:** 勝ち馬の `corner4 ≤ 3` の比率
- **inner:** 勝ち馬の `umaban ≤ max(1, tosu/3)` の比率

つまり `front_expected` / `inner_expected` は **「その日目の典型的な当日バイアス方向の期待値（2018–25 芝・JRA 全体平均）」** であり、

- 個別レースの予測値ではない
- `baba_for_v` の 3 分類閾値（0.50 / 0.20）ではない
- 連続の **記述統計**（日目ごとの長期平均）

**表の検証脚本:** docstring に「バックテスト済み」とあるが、repo 内に `_NICHI_*` を再計算・検証する `scripts/*.py` は **見つからない**（表値の出所は docstring のみ）。

### 1.3 返却フィールド

| フィールド | 型 | 意味 |
|------------|-----|------|
| `nichi` | int | 入力日目（1–12） |
| `front_expected` | float | `_NICHI_FRONT[nichi]`（無ければ 0.52） |
| `inner_expected` | float | `_NICHI_INNER[nichi]`（無ければ 0.31） |
| `wear_label` | str | 芝傷み **フェーズ** の離散ラベル（下表） |
| `note` | str | エビデンス表用の **説明文**（人間向け） |

**`wear_label` の段階**（日目レンジは関数内ハードコード、L853–867）:

| 日目 | wear_label | note の要旨 |
|------|------------|-------------|
| 1–2 | 開幕週 | 芝新鮮 → 内枠・先行有利 |
| 3–4 | 序盤 | 内傷み始め → まだ先行有利 |
| 5–6 | 中盤 | 内傷み進行 → 外差し台頭 |
| 7–8 | 終盤(仮柵移動期) | 内ラチ荒れ → 外枠・差し有利増 |
| 9+ | 最終盤 | 日目だけでは判断困難 |

**重要:** `wear_label` / `note` は **表示・説明専用**。どのコードもこれを baba  index や `lane_label` に変換していない。

### 1.4 nichi_bias が「意味しない」こと

- 当日そのレースの実測バイアス（→ それは `empirical_bias`）
- V 赤枠の列選択（→ `baba_for_v` / `V_BABA_PATTERNS`）
- 買い・消去シグナル（→ `danger_popular_inner` 等は empirical 専用）

---

## 2. 既存利用箇所

### 2.1 コード（実行経路）

| ファイル | 行 | 使い方 | 判定への利用 |
|----------|-----|--------|--------------|
| `app.py` | L3238–3244 | jravan `races.nichi` → `nichi_bias()` | エビデンス行生成のみ |
| `app.py` | L3443–3447 | `wear_label`, `front_expected`, `inner_expected`, `note` を **「開催日目」行** に表示 | **なし**（表示） |
| `core/track_bias.py` | L829–871 | 定義元 | — |

**`nichi_bias` を import / 呼び出しているのは `app.py` のみ**（repo 全体 grep 結果）。

### 2.2 文書・設計（非実行）

| ファイル | 内容 | 判定への利用 |
|----------|------|--------------|
| `repo/vmatrix_existing_assets_master.md` | B 層資産。「V未配線」「弱い検証」 | 候補メモ |
| `repo/vmatrix_p2_priority_research_design.md` | P2-A 候補。`inner_expected` → `_V_COL` **提案** | **未実装** |
| `repo/vmatrix_nichi_holdout_design.md` | holdout 設計（脚本未着手） | 設計のみ |
| `repo/trackbias_integration_plan.md` | 開幕週=内有利等の **概念説明** | nichi_bias 関数とは未リンク |

### 2.3 関連だが別経路の UI

本番 V baba と混同しやすい **別表示**:

| UI 項目 | ソース | 閾値 | V baba との関係 |
|---------|--------|------|-----------------|
| エビデンス「**開催日数**」 | scraper `meta.holding_days` | ≥7 → 🚩外差し警告（L3059–3060） | **別ロジック**（警告文のみ） |
| V baba 自動 init ② | 同上 `holding_days` + `condition` | ≥7 or 重/不良 → 内4; ≥5 → 内2 | **V 接続あり** |
| エビデンス「**開催日目**」 | `nichi_bias` | なし（率を % 表示） | **V 未接続** |

`holding_days`（ページ）と `races.nichi`（JV）は **同じ「開催日目」の別取得経路**。`nichi_bias` は JV 日目 + 静的表を使うが、V baba は scraper 日数ヒューリスティックを使う。

### 2.4 `_NICHI_INNER` / `inner_expected` / `front_expected` の利用

| 利用箇所 | 用途 |
|----------|------|
| `nichi_bias()` 内部 | ルックアップ → 返却 |
| `app.py` L3447 | エビデンス表 `%` 表示 |
| その他 repo | **なし** |

**いずれも「3 分類判定」「baba 選択」「lane 符号」には使われていない。**

---

## 3. nichi_bias → V_BABA 既存変換の有無

### 結論: **存在しない**

| 候補 mapping | repo 内の状態 |
|--------------|---------------|
| `nichi_bias` → `baba_for_v` 関数 | **なし** |
| `inner_expected` → `_V_COL` / `V_BABA_PATTERNS` | **なし**（P2 設計書の提案のみ） |
| `wear_label` → baba index | **なし** |
| `nichi_bias` ≡ `holding_days` fallback | **なし**（別閾値体系: 5/7+重不良 vs 日目表+説明） |
| `empirical_bias` 閾値を `inner_expected` に流用 | **コード上なし**（調査上も全 day が中帯 1 クラスに潰れる） |

`baba_for_v` への **唯一の既存 mapping** は `empirical_bias()` 内のみ（`inner_rate` に 0.50 / 0.20）。

---

## 4. 変換規則が無い理由（事実ベース）

1. **設計意図が「説明」止まり**  
   Phase 5 はエビデンス表に「典型的な日目傾向」を載せる機能。V baba init（Phase 1）とは別フェーズ。

2. **数値スケールが empirical 閾値と非整合**  
   `_NICHI_INNER` は 0.26–0.34（**人口平均**）。`empirical_bias` の 3 分類閾値 0.50 / 0.20 は **当日勝ち馬サンプルの inner_rate** 用。同一尺度の閾値ではない。

3. **holding_days フォールバックが別体系で既に存在**  
   V cold start は日数 **5 / 7 + 馬場** の離散規則（`app.py`）。`nichi_bias` の連続期待値・5 段 `wear_label` とは **対応付けコードなし**。

4. **検証が表の存在確認止まり**  
   `_NICHI_*` は docstring で「2018–25 平均」と記載されるが、baba init 精度や lane 一致を測った verified / script は repo に **ない**。

5. **研究提案が未実装**  
   `vmatrix_p2_priority_research_design.md` の「`_NICHI_INNER` 閾値のみ」は **関数・閾値・テストのいずれも未存在**。

---

## 5. GT-1 / GT-2 の定義

### GT-1 — レース時点 empirical（事前）

**定義:** 対象レース R の **直前まで** の同日・同場・同馬場勝ち馬だけで `empirical_bias(priors)` → `baba_for_v` / `lane_label`。

- 実装: `empirical_bias_from_db(..., before_race_num=R)`（L448–469）
- 条件: prior 勝ち馬 **n ≥ 2**、否则 None
- **cold start 母集団では GT-1 は常に None → baba 正解として定義不能**

### GT-2 — 事後・当日全日 empirical（Oracle）

**定義（P2 設計上の候補）:** 対象日・同場・同馬場の **全勝ち馬**（R 終了後のレースを含む）で `empirical_bias(all_day_winners)` → `baba_for_v` / `lane_label`。

- **予測境界:** 評価ラベル専用。A/B 入力には使わない（事後情報）
- **既存関数:** `empirical_bias()` をそのまま呼べばよいが、**この呼び方を「正解代理」と明記した採用例は repo にない**

### 混同注意 — `bias_dashboard` は GT-2 ではない

`bias_dashboard(..., before_race_num)` は SQL で **`race_num < before_race_num`**（L721）。  
→ **GT-1 と同型のレース時点累積**。全日 oracle ではない。

---

## 6. GT-2 の既存採用実績

### 6.1 track_bias 関連脚本

| 脚本 | empirical の使い方 | GT-2 相当か |
|------|-------------------|-------------|
| `scripts/tenkai_bias_backtest.py` | prior winners のみ（L112–121） | **否** = GT-1。n&lt;2 skip |
| `scripts/intraday_bias_backtest.py` | 同上 | **否** |
| `scripts/comeback_backtest.py` | prior winners のみ（L51–52） | **否** |
| `core/track_bias.py` `bias_dashboard()` | `race_num < before` | **否** = GT-1 |

**いずれも「baba init の Accuracy 正解」用途ではない。**  
主用途 = 順張り/逆張り **買い群** の残差・z（`verified_emp_bias_danger.md`）。

### 6.2 verified / memory 文書

| 文書 | 内容 | GT-2 |
|------|------|------|
| `verified_emp_bias_danger.md` | レース時点 `lane_label` で fade 群評価 | **否**（GT-1・買い検証） |
| `project_trackbias.md` | 前半傾向の後半持続（61% vs 50%） | **否**（持続性。正解代理定義なし） |
| `vmatrix_p2_priority_research_design.md` | 「事後 lane ラベル」を **副指標として提案** | **提案のみ・採用実績なし** |

### 6.3 結論 — GT-2

| 項目 | 状態 |
|------|------|
| GT-2 を正解代理として使った既存 BT | **なし** |
| GT-2 の妥当性を示す verified 文書 | **なし** |
| 情報境界の既存先例 | GT-1 系のみ（prior のみ・リーク規約明文化） |

**→ GT-2 は「未承認」**（設計候補に留まる。採用には別途 GO と定義固定が必要）。

---

## 7. 現時点の GO / NO-GO

### 判定基準（ユーザー指定）

| 条件 | 結果 |
|------|------|
| A. 既存の nichi → V_BABA **変換規則**が見つかる | **✗ 見つからず** |
| A. GT-2 に **既存の妥当性根拠**がある | **✗ なし（未承認）** |
| B. どちらか未確認 → P2-A 停止継続 | **該当** |

### 最終判定: **NO-GO — P2-A 停止継続**

```text
┌────────────────────────────────────────────────────────────┐
│  P2-A holdout には進めない。                                │
│                                                            │
│  ブロッカー 1: nichi_bias → V_BABA 3分類の既存規則なし      │
│  ブロッカー 2: GT-2 正解代理の既存採用実績・承認なし        │
│                                                            │
│  今回: holdout 脚本作成禁止 / 既存コード変更禁止            │
└────────────────────────────────────────────────────────────┘
```

### P2-A を再開するために必要な GO（本調査のスコープ外）

1. **変換規則:** `core/` または verified 文档で、**新閾値なし**で `nichi_bias` → `baba_for_v` が定義されること  
2. **正解代理:** GT-2（または別の既存 GT）の **明示承認** と情報境界の文書化  
3. 上記確定後 → `repo/vmatrix_nichi_holdout_design.md` のゲート更新 → holdout 脚本

### 参考 — 停止中も確定している事実（再掲）

- 本番 V baba: ① empirical → ② holding_days+condition のみ
- `nichi_bias` はエビデンス表示専用
- cold start 評価の GT-1 は定義不能
- `empirical` 0.50/0.20 を `inner_expected` に流用する既存規則はない（かつ 3 分類として機能しない）

---

*調査方法: repo 全体 grep（`nichi_bias`, `inner_expected`, `front_expected`, `_NICHI_*`, `baba_for_v`, `lane_label`, `empirical_bias`）、`scripts/` BT 一覧、`verified_*` / `project_trackbias.md` 精読。コード・文書の変更なし。*
