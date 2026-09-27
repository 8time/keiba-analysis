# Vエリア改善 — スコアカード（初回固定）

> **固定日:** 2026-09-07  
> **目的:** P0/P1/P2 調査の結果を Composer 改修の参照用に凍結する。  
> **原則:** 「弱いから何でも足す」→ **検証で入れていい／入れないを選別**。

関連: `repo/vmatrix_existing_assets_master.md`（G層・資産表）、`repo/vmatrix_p2_priority_research_design.md`（P2 ルーブリック）

---

## 1. フェーズ別サマリ

| ID | 内容 | 状態 | 判定 | 根拠ドキュメント |
|----|------|:----:|------|------------------|
| **P0** | pos4 整合（Y=pos4→ten→score、≫=finish_push） | ✅ 完了 | **採用済み** | `repo/brief_vmatrix_pos4_align.md`, `tests/test_vmatrix_pos4.py` |
| **P1** | 検証済み注記の V 直下統一（表示のみ） | ✅ 完了 | **採用済み** | `repo/brief_vmatrix_p1_annotations.md`, `core/vmatrix_annotations.py` |
| **P2-1** | ten_speed / predict_pace_intensity → V **ペース行** | ✅ 調査完了 | **NO-GO（V接続）** | `repo/vmatrix_pace_holdout.md`, `repo/analysis/vmatrix_pace_holdout/summary.json` |
| **P2-A** | nichi_bias → V **baba init** | ✅ 調査完了 | **NO-GO（設計ゲート）** | `repo/vmatrix_nichi_mapping_review.md`, `repo/vmatrix_nichi_holdout_design.md` |
| **P2-D** | コース形状 → 展開説明力（D-1b/D-2） | ✅ 設計完了 | **holdout 未着手**（D-1b GO可） | `repo/vmatrix_course_shape_design.md` |
| P2-B/C/E/F | 未着手 | — | — | `repo/vmatrix_p2_priority_research_design.md` |

**次の推奨（本スコアカード固定後）:** P2-D コース形状 — **新規ルール化せず、追加説明力（D-2 caption / D-1 展開MAP）のみ**を検証設計

---

## 2. 完了項目の記録

### P0 — pos4 整合 ✅

| 項目 | 結果 |
|------|------|
| 変更面 | `resolve_v_pos`, `build_v_matrix(pos4=, finish=)`, `app.py` 配線 |
| 不変 | 赤枠 `_V_COL`/`_V_ROW`, baba/pace radio, 買い/playbook |
| holdout | 2756R（2024–25）帯一致 pos4=**100%** vs ten=76%（`scripts/vmatrix_pos4_align_check.py`） |
| テスト | `tests/test_vmatrix_pos4.py` 9件 |

**確定した V 座標規約:**

```text
Y = pos4 → ten → score
≫ = finish_push_delta（pos4 基準・V_FINISH_PUSH_MIN=0.15）
X = 0.65×gate + 0.35×pos（変更なし）
赤枠 = baba × pace（変更なし）
```

---

### P1 — 注記統一 ✅

| 項目 | 結果 |
|------|------|
| 変更面 | `core/vmatrix_annotations.py`, V チャート直下 HTML |
| 4注記 | 🔥末脚 / ⚠危険 / ◆枠 / ◇場（既存関数委譲） |
| 不変 | V 座標・赤枠・ctx.pace・買い・Rank/VH |

**原則:** 検証済みシグナルは **馬点横の補助表示**。座標・加点・買い接続禁止（G層#10）。

---

### P2-1 — ten_speed → V ペース行 ✅ NO-GO

| 指標 | A: ctx.pace（現行） | B: predict_pace_intensity |
|------|---------------------|---------------------------|
| 3択 Accuracy（14,764R） | **37.2%** | **41.8%** |
| A/B pace 一致率 | 36% | — |
| V Jaccard（baba固定・pace差分時） | — | **0.38** |
| 展開 ctx との乖離 | 基準 | **64%** のレースで V 行 ≠ 展開マップ |

**判定:** ペース予測単体では B 優位だが、**展開体系（`build_pace_context`）と不一致** → V ペース行は **現行維持**。B は Scanner・3連複ヒント等の既存配線に留める（G層#9）。

**V に入れない（確定）:** `ten_speed` / `predict_pace_intensity` による V 赤枠行の自動切替。

---

### P2-A — nichi_bias → baba init ✅ NO-GO

| ゲート | 結果 |
|--------|------|
| nichi → V_BABA 既存変換規則 | **不存在**（`nichi_bias` はエビデンス表示専用） |
| GT-2 正解代理の既存採用 | **未承認**（baba Accuracy 用 BT なし） |
| holdout | **未実施**（設計ゲートで停止） |

**判定:** 変換規則・正解代理のいずれも repo 上未確定のため、holdout 以前に **クローズ**。本番 baba は ① empirical → ② holding_days+condition のまま。

**V に入れない（確定）:** `nichi_bias` による baba 自動初期値（`_NICHI_INNER` の表値を baba 閾値として流用する既存規則もなし）。

---

## 3. V に入れないもの — 確認済みリスト

Composer 改修時の **拒否リスト**（検証または G 層で固定）。

### 座標・赤枠（構造変更禁止）

| 項目 | 理由 | 参照 |
|------|------|------|
| `_V_COL` / `_V_ROW` ルール変更 | P0 確定。赤枠定義の破壊 | G#8 |
| pos4 / ctx.pace / finish_push の再定義 | P0 確定 | brief_pos4 |
| ten_speed → V 縦 or V 行 | ρ 劣位 + G#4 | pos_backtest |
| predict_pace_intensity → V ペース行 | Acc↑ も整合性 NG、Jaccard 0.38 | P2-1 |
| predict_finish → Y 座標 | 能力・人気混入 | G#6 |
| PCI / Rank / VH / 人気 → V 本体 | priced-in / レイヤー混同 | G#3,#5 |
| 頭数・距離 → lane 係数（未検証 coords） | G 層抵触リスク | P2-F 設計 |

### baba init（cold start 候補）

| 項目 | 理由 | 参照 |
|------|------|------|
| nichi_bias → baba | 変換規則なし + GT 未承認 | P2-A review |
| empirical 0.50/0.20 を inner_expected に流用 | 既存規則なし・3 分類潰れ | mapping review |

### 買い・加点

| 項目 | 理由 | 参照 |
|------|------|------|
| V 該当馬への加点 | priced-in（221,454R） | verified_emp_bias_danger |
| V × 人気薄を穴馬化 | 展開恩恵 overbet | verified_tenkai_priced_in |
| 検証済み注記 → V 座標・スコア | P1 で表示に限定 | G#10 |

### ペース・展開（V 外で既存利用可）

| 項目 | V での扱い | 参照 |
|------|------------|------|
| ten_speed / predict_pace_intensity | Scanner・ヒントのみ | P2-1 |
| wind_effect | 禁止（r≈0） | verified_wind_no_effect |
| tactics_forward 単体 | pos4 間接のみ | verified_tenkai_priced_in |

### 未検証 → 赤枠禁止（holdout 前）

| 項目 | 状態 |
|------|------|
| クッション・含水 → 赤枠 | 荒れ无效。注記候補のみ（P2-E） |
| course_empirical → 赤枠自動 | 未検証（P2-B） |
| bias_dashboard σ → baba 自動 | 未検証（P2-C） |
| コース形状 → V 座標（D-3） | **原則禁止**（P2-D 設計） |

---

## 4. V に入れているもの — 確認済みリスト

| 機能 | 接続面 | フェーズ |
|------|--------|:--------:|
| pos4 → Y | 座標 | P0 |
| finish → ≫ のみ | 表示 | P0 |
| build_pace_context.pace → pace radio init | 赤枠行 | P0 |
| empirical_bias.baba_for_v → baba init ① | 赤枠列 | P0 |
| holding_days + condition → baba init ② | 赤枠列 | P0 |
| vmatrix_annotations 4種 | V 直下 caption | P1 |
| danger / dirt_draw / venue_fav（P1 経由） | 注記 | P1 |

**触らない:** 上記以外を「賢くする」名目で V 座標・赤枠・買いへ足さない。

---

## 5. P2 候補スコアカード（初回記入）

ルーブリック: `vmatrix_p2_priority_research_design.md` §5（1–5 点、最大 25 点）。

| ID | 整合 | 予測 | 副作用 | リスク | データ | 合計 | 判定 |
|----|:---:|:---:|:---:|:---:|:---:|:---:|------|
| **P2-A** | — | — | — | — | 3 | — | **クローズ**（holdout 前停止） |
| P2-B | | | | | | | 未調査 |
| P2-C | | | | | | | 未調査 |
| P2-D | — | — | — | — | — | — | **設計完了**（D-1b GO可 / D-2定量停止） |
| P2-E | | | | | | | 未調査 |
| P2-F | | | | | | | 未調査 |

**P2-A 記入メモ:**

- **整合 / 予測 / 副作用:** holdout 未実施のため点数なし（「—」）
- **データ:** 3 — jravan `nichi` + 芝で取得可。ただし scraper `holding_days` との経路差あり
- **判定:** **クローズ** — 変換規則不存在 + GT-2 未承認（G 層抵触ではなく **設計ゲート不通過**）

**P2-1（参考・表外）:** V 接続 **クローズ**。ペース Acc は B 優位だが整合性失敗（64% 乖離、Jaccard 0.38）。

---

## 6. 現行 V の設計姿勢（Composer 向け一文）

```text
V = 展開マップと同じ pos4 隊列 × ユーザー調整可能な baba/pace 赤枠 × 検証済み注記。
     予測精度が単体で高い資産も、展開 ctx と体系が違えば V へ入れない。
     cold start の baba は holding_days まで。nichi_bias / ten_speed は V 外。
```

---

## 7. 次アクション（合意案）

| 順 | 作業 | 備考 |
|:--:|------|------|
| 1 | **本スコアカード固定** | 本ファイル（今回） |
| 2 | P2-D 調査設計 ✅ | `repo/vmatrix_course_shape_design.md` — D-1b holdout のみ次 GO |
| 3 | P2-B / C | baba 系。A クローズ後も empirical 優先は維持 |
| 4 | P2-E | 赤枠は最後。ダメなら P1 注記固定 |

**本番配線（app.py 変更）** は各候補で **別 GO**。holdout + スコアカード更新後のみ。

---

*初回固定: 2026-09-07 / 次回更新: P2 候補の holdout 完了時のみ（事後改変禁止）*
