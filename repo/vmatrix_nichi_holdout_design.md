# V Matrix P2-A — nichi_bias holdout 設計書

> **段階:** 設計確定のみ。**holdout 脚本はまだ書かない。**  
> **目的:** `empirical_bias` が使えないレースにおいて、現行フォールバック（`holding_days + condition`）より `nichi_bias` が優れているかを、**同一 holdout・固定ルール**で検証する。  
> **非目的:** nichi_bias の本番配線、閾値最適化、V 買い接続。

参照: `app.py`（V baba init）、`core/track_bias.py`、`core/pace_map.py`、`repo/vmatrix_p2_priority_research_design.md`

---

## 1. 本番 baba 生成経路

### 1.1 フロー

```text
解析開始
  ├─ jravan.db → empirical_bias_from_db → st.session_state['_tb_emp_bias']
  ├─ scraper meta → holding_days, condition
  └─ jravan.db → nichi_bias（エビデンス表のみ・V未接続）

Vエリア UI
  _vm_baba_auto_idx 決定 → st.radio('vm_baba') → build_v_matrix(baba=...)
  → _V_COL[baba] で赤枠列（0=内 / 1=中 / 2=外）
```

### 1.2 優先順位（本番・確定）

| 順位 | 経路 | ソース | 発火条件 |
|:---:|------|--------|----------|
| **①** | `empirical_bias.baba_for_v` | `empirical_bias_from_db(year, monthday, jyo, surface, race_num)` | 同日・同場・同馬場で **当該 R より前** の勝ち馬 **n≥2** |
| **②** | `holding_days + condition` | scraper `meta` | ①が None |
| — | `nichi_bias` | jravan `races.nichi` | **V baba には未接続**（エビデンス表「開催日目」のみ） |

### 1.3 ① empirical → baba（既存・唯一の正式 mapping）

```409:414:core/track_bias.py
    if inner >= 0.50:
        lane_label, baba_for_v = '内有利', 'フラット'
    elif inner <= 0.20:
        lane_label, baba_for_v = '外有利', '内4頭目まで荒れ'
    else:
        lane_label, baba_for_v = '中庸〜やや内', '内2頭目まで荒れ'
```

- `inner_rate` = 勝ち馬の `umaban ≤ tosu/3` の比率（`empirical_bias` 内で定義）
- `lane_label`（内有利 / 中庸〜やや内 / 外有利）と `baba_for_v`（`V_BABA_PATTERNS` 3値）は **1:1 対応**

### 1.4 ② holding_days + condition → baba（本番フォールバック A）

```4919:4928:app.py
                                else:
                                    ...
                                        _vm_hd_n = int(_vm_re.search(r'\d+', str(meta.get('holding_days', '') or '')).group()) ...
                                        _vm_cond = str(meta.get('condition', '') or '')
                                        if _vm_cond in ('重', '不良') or _vm_hd_n >= 7:
                                            _vm_baba_auto_idx = 2   # 外有利 → 内4頭目まで荒れ
                                        elif _vm_hd_n >= 5:
                                            _vm_baba_auto_idx = 1   # 中有利 → 内2頭目まで荒れ
                                    # else: 0 = フラット
```

| 条件 | index | `V_BABA_PATTERNS` | UI 表示 |
|------|:-----:|-------------------|---------|
| デフォルト / 1–4日目 | 0 | フラット | 内有利 |
| 5–6日目 | 1 | 内2頭目まで荒れ | 中有利 |
| 7日目以上 **or** 重/不良 | 2 | 内4頭目まで荒れ | 外有利 |

- `holding_days`: scraper が RaceData02 の「N日目」から取得（`core/scraper.py` L1714–1722）
- `condition`: scraper が「馬場:良/稍重/…」から取得
- 根拠: `repo/trackbias_integration_plan.md` §0（**弱い検証**のヒューリスティック）

### 1.5 holdout 再現時のデータ源差（要固定）

| 入力 | 本番 | jravan 离线再現 |
|------|------|-----------------|
| ① empirical | `empirical_bias_from_db` | 同一 SQL・同一 `empirical_bias()` |
| ② 日数 | `meta.holding_days`（ページ） | **`races.nichi`**（JV 開催日目。意味は同じだが取得経路が異なる） |
| ② 馬場 | `meta.condition` | **`baba_shiba` / `baba_dirt`**（芝/ダで切替） |
| B nichi | （未接続） | `races.nichi` → `nichi_bias(nichi, surface)` |

**原則:** 离线では scraper meta が無いため、A の再現は **`nichi + baba_*`** で行う。本番との差は設計上明示し、結果解釈時に混同しない。

---

## 2. A/B 比較対象

### A — 現行フォールバック（本番 ② の再現）

- 入力: 開催日目（离线=`nichi`）+ 馬場状態（重/不良）
- 出力: `V_BABA_PATTERNS` 3分類（§1.4 の表）
- **既存コードそのまま**（`app.py` L4919–4928 相当）

### B — nichi_bias 候補

- 入力: `nichi_bias(nichi, surface)` の戻り値
- 出力: `V_BABA_PATTERNS` 3分類
- **前提:** ① `empirical_bias` が None のレースのみで A と比較（本番と同じ優先順位）

### 比較の問い（固定）

> empirical が使えないレースで、V baba 自動初期値として **A（現行②）** と **B（nichi_bias）** のどちらが、当日の内外バイアス（正解代理）に近いか。

---

## 3. holdout 母集団

### 3.1 含める条件（すべて必須）

| # | 条件 | 根拠 |
|---|------|------|
| 1 | JRA 平地（`jyo` 01–10） | 既存 BT 慣行（`tenkai_bias_backtest.py` 等） |
| 2 | `shusso_tosu ≥ 8` | V / バイアス BT 共通 |
| 3 | **レース時点で `empirical_bias_from_db` = None**（prior 勝ち馬 n&lt;2） | 本番で ② vs B が競合する唯一の母集団 |
| 4 | A が再現可能（`nichi` 取得可、`baba_*` 取得可） | 欠損は除外 |
| 5 | B が再現可能（芝: `nichi_bias` ≠ None） | ダートは `nichi_bias` が None のため **主分析から除外** |
| 6 | 正解代理が定義可能（§5 採用後） | 評価不能は除外 |

### 3.2 除外（勝手に補完しない）

- `nichi` 欠損 / 0 / 範囲外
- ダート（`nichi_bias` 非対応）
- レース時点で empirical が存在する行（**混ぜない**）
- V 副次分析用の profile 不足（主分析=baba 一致率には不要。V Jaccard 副次集団のみ別途フィルタ）

### 3.3 時系列分割（固定・事後変更禁止）

| 区分 | 期間 | 用途 |
|------|------|------|
| train | 2021–2023 | 参考集計のみ（**閾値凍結・チューニング禁止**） |
| holdout | 2024–2025 | **採用判定の唯一の判断面** |

`race_key` または `year+monthday` 昇順。`vmatrix_pace_holdout` / `vmatrix_p2_priority_research_design.md` と整合。

---

## 4. 時系列リーク防止

### 4.1 予測側（A/B 入力）

| 入力 | 許可 | 禁止 |
|------|------|------|
| ① empirical | 当該 R **より前** の勝ち馬のみ | 当該 R 以降の結果 |
| A: nichi / condition | レース前に確定の情報 | 事後馬場変化の上書き |
| B: nichi_bias | `nichi` + `surface` のみ（静的表 `_NICHI_*`） | 当日勝ち馬を nichi 推定に使用 |

母集団は **empirical=None** に限定するため、①は常に None。A/B は静的入力のみ。

### 4.2 評価側（正解代理）

- 正解作成に **当該日・当該 R 以降の結果を使うことは可**（事後ラベル）
- ただし予測入力へ **逆流させない**（ラベル生成パイプラインと A/B パイプラインを分離）

### 4.3 既存 BT のリーク規約（踏襲）

`tenkai_bias_backtest.py` / `intraday_bias_backtest.py` 冒頭:

> 対象馬の事前確定情報 = umaban(枠) のみ。corner4 は **当日バイアス集計（prior 勝ち馬）** にのみ使用。

holdout でも同型: prior 勝ち馬の corner4/umaban は **正解代理・empirical 集計** にのみ使用。

---

## 5. 正解代理（既存定義の調査結果）

### 5.1 既存 track_bias 関連脚本一覧

| 脚本 | 正解 / ラベルの使い方 | baba init 精度評価向き |
|------|----------------------|------------------------|
| `scripts/tenkai_bias_backtest.py` | レース時点 `empirical_bias(priors)` の `lane_label` で **買い群分け** | ×（妙味検証。n&lt;2 は skip） |
| `scripts/intraday_bias_backtest.py` | 同上 + train/holdout 分割 | × |
| `scripts/comeback_backtest.py` | レース時点 `empirical_bias(priors)`（confident 必須） | × |
| `core/track_bias.py` `bias_dashboard()` | **当日全終了 R** の勝ち馬で `empirical_bias` + σ | △（事後・全日） |
| `repo/vmatrix_p2_priority_research_design.md` P2-A | 「事後 lane ラベル = `empirical_bias_from_db` の lane_label」 | △（文言のみ。 cold start では from_db=None） |

**結論:** baba init の **Accuracy 評価専用** の既存脚本は **存在しない**。

### 5.2 既存の `baba_for_v` / `lane_label` 定義（コード上）

| ID | 定義 | 意味 | リーク |
|----|------|------|--------|
| **GT-1** | レース時点 `empirical_bias(prior_winners).baba_for_v` | 本番 ① と同型の「その時点のベスト推定」 | なし |
| **GT-2** | 事後 `empirical_bias(当日全勝ち馬).baba_for_v` | その日の **最終的な** 内外バイアス | 事後のみ（評価ラベル可） |
| **GT-3** | GT-2 の `inner_rate` vs `nichi_bias.inner_expected` の MAE / 符号一致 | 連続値一致（3分類ではない） | 事後 |
| **GT-4** | `bias_dashboard.summary` の `sigma_inner` 符号（±0.5σ） | 内外の強度・方向（3分類ではない） | レース時点で prior 全日 |

### 5.3 採用方針 — **保留（脚本着手前に要決定）**

| 第一目的（baba 3分類一致） | 推奨候補 | 理由 |
|---------------------------|----------|------|
| 主正解 | **GT-2** | cold start では GT-1 は定義不能（= None）。`baba_for_v` の **唯一の既存 3分類 mapping** は `empirical_bias()` 内のみ |
| 副正解 | **GT-3** | P2 設計書の「主指標」原文。ただし **baba 一致率とは別物** |

**保留事項:**

1. GT-2 を主正解とするか（事後 oracle として明示同意）
2. GT-3 を副報告に添えるか（3分類 Accuracy とは混同しない）
3. GT-4 / `bias_dashboard` は P2-C 領域のため **P2-A では使わない**

> **脚本は GT-1 を主正解にできない**（母集団が empirical=None のため常に未定義）。  
> GT-2 以外を主正解にする場合は **新規正解定義** となり、本設計の原則に反する → **採用不可**。

**暫定結論（設計上）:** 第一目的の主正解 = **GT-2**（`empirical_bias(当日全勝ち馬).baba_for_v`）。§5.3 の明示承認後に脚本へ反映。

---

## 6. nichi_bias → baba の変換規則

### 6.1 調査結果 — **変換規則未定義（実験停止条件）**

コード・repo 全体を探索した結果:

| 所在 | nichi → baba 変換 | 状態 |
|------|-------------------|------|
| `core/track_bias.py` `nichi_bias()` | `front_expected`, `inner_expected`, `wear_label`, `note` を返す。**`baba_for_v` なし** | 表示用のみ |
| `app.py` V baba init | `nichi_bias` **未使用** | — |
| `empirical_bias()` | `inner_rate` → `baba_for_v`（0.50 / 0.20） | **nichi とは無関係** |
| `app.py` holding_days fallback | 日数 5/7 + 重/不良 | **nichi_bias 関数とは別経路** |
| `repo/vmatrix_p2_priority_research_design.md` | 「`inner_expected` で `_V_COL` を推定（`_NICHI_INNER` 閾値のみ）」 | **研究提案のみ。関数・閾値未実装** |
| `scripts/` | nichi → baba の BT **なし** | — |

### 6.2 `_NICHI_INNER` の性質

- 日目 1–10 ごとの **期待 inner 率** 静的表（2018–25 芝、docstring「バックテスト済み」）
- 値域 **0.264–0.337**（いずれも `empirical_bias` の 0.50/0.20 閾値の **中間帯**）
- **`empirical_bias` と同じ 0.50/0.20 を `inner_expected` に適用すると、全 day が「内2」1クラスに潰れる** → 実質的な 3分類にならない

### 6.3 設計上の判定

```
┌─────────────────────────────────────────────────────────┐
│  B（nichi_bias → V_BABA 3分類）の変換規則は              │
│  既存コード・既存検証脚本・repo に存在しない。             │
│                                                         │
│  → holdout 脚本は書かない。                              │
│  → 新閾値・新 mapping を設計段階で創作しない。          │
│  → 変換規則が core/ または verified 文档で定義される     │
│     まで P2-A は「設計保留」。                           │
└─────────────────────────────────────────────────────────┘
```

**B を実装可能にするための先行 GO（本設計のスコープ外）:**

- 例: `nichi_bias` の `wear_label` 段階と `holding_days` 5/7 規則の **既存対応関係を文書化して採用**（ただし現状は **別ロジック** で同一変換ではない）
- 例: `inner_expected` を **別の既存 verified 閾値** に接続する根拠の提示

---

## 7. 評価指標（変換規則確定後に有効）

### 7.1 第一目的 — baba 分類 vs 正解代理（GT-2 暫定）

| 指標 | 定義 |
|------|------|
| baba 一致率 | A/B 各々の 3分類 == GT-2 `baba_for_v` |
| 内/中/外 precision | クラス別（UI: 内有利/中有利/外有利） |
| 内/中/外 recall | 同上 |
| macro F1 | 3クラス macro 平均 |
| A/B disagreement 率 | A の baba ≠ B の baba |

**報告:** holdout のみで採用判定。train は参考。

### 7.2 第二目的 — V 赤枠への影響（副次）

| 指標 | 備考 |
|------|------|
| V 赤枠 Jaccard | A vs B の `build_v_matrix` 該当 umaban 集合（**pace は本番同型 `build_pace_context.pace` 固定**） |
| V 該当頭数 | 平均 / 分布 |
| V 該当馬 複勝率 | **補助のみ** |
| V 該当馬 単 ROI | **補助のみ** |

V 成績は採用判断に **使わない**（`verified_emp_bias_danger` / G層: V 買い = priced-in）。

### 7.3 副正解（GT-3・任意）

- 日単位: `|inner_expected − 当日実測 inner_rate|` の MAE
- 符号一致率（nichi 期待 vs 実測が同方向か）
- **baba 一致率とは別表で報告**

---

## 8. 欠損処理

| 欠損 | 処理 |
|------|------|
| `empirical_bias` あり | **母集団から除外**（比較対象外） |
| `nichi` 欠損 | 除外 |
| ダート | 除外（`nichi_bias` = None） |
| `baba_shiba` / `baba_dirt` 欠損 | A の 重/不良 判定不能 → **除外**（フラット仮定しない） |
| GT-2 不能（当日勝ち馬 n&lt;2） | 除外 |
| V 副次: profile 不足 | V 指標サブセットから除外（主分析は継続） |

**原則:** 欠損の補完・デフォルト代入・mean imputation **禁止**。

---

## 9. 採用判定ルール（固定・事後変更禁止）

`repo/vmatrix_p2_priority_research_design.md` P2-A より:

| 条件 | 判定 |
|------|------|
| holdout cold start で A 比 **lane/baba 一致 +3pp 以上** かつ **V Jaccard ≥ 0.85** | **実装候補**（本番配線は別 GO） |
| 改善 &lt; +1pp | **クローズ** |
| その他 | **保留** |
| empirical あり日への上書き | **評価母集団に含めない**（設計上発生しない） |

**前提:** §6 変換規則が確定し B が定義可能であること。未定義のままでは判定不能。

**禁止（再掲）:**

- holdout 結果を見てから母集団・閾値・正解定義を変更
- V ROI を採用理由にする
- 新 ML / 連続バイアス化 / pace・pos4 変更

---

## 10. 脚本着手ゲート（現在地）

```text
[✓] 本番 baba 経路確認
[✓] A/B 比較対象定義
[✓] 母集団・リーク規約
[✓] 既存正解定義調査
[✗] nichi_bias → baba 変換規則（未定義 → 停止）
[△] 正解代理 GT-2 の明示承認（§5.3 保留）
[ ] scripts/vmatrix_p2_nichi_baba_check.py
[ ] repo/analysis/vmatrix_p2_a/summary.json
```

**次にユーザー GO が必要なもの（順）:**

1. **B の変換規則** — 既存コード or verified 文档での定義（新閾値なし）
2. **GT-2（事後 `empirical_bias` 全日）** を主正解とする承認
3. 上記確定後 → holdout 脚本作成

---

## 11. 関連ファイル

| ファイル | 役割 |
|----------|------|
| `app.py` L3216–3231, L4912–4952 | empirical 供給・V baba init |
| `core/track_bias.py` | `empirical_bias`, `nichi_bias`, `_NICHI_*` |
| `core/pace_map.py` | `V_BABA_PATTERNS`, `_V_COL`, `build_v_matrix` |
| `core/scraper.py` L1714–1722 | `holding_days` |
| `scripts/tenkai_bias_backtest.py` | empirical リーク規約の参照実装 |
| `repo/vmatrix_p2_priority_research_design.md` | P2-A 成功条件（採用判定） |
| `repo/trackbias_integration_plan.md` | holding_days ヒューリスティックの出所 |

---

*作成: 2026-09-07 / ステータス: **設計確定・脚本未着手**（§6 変換規則未定義により B 側は保留）*
