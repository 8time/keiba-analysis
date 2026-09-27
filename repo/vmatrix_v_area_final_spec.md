# Vエリア現行仕様 — 最終凍結書

> **凍結日:** 2026-09-07  
> **根拠調査:** P0 / P1 / P2-1 / P2-A / P2-D（D-1b holdout 含む）  
> **ステータス:** **現行本番仕様として凍結** — 以降の V 改修は本書＋G層に従う  
> **コード変更:** 本書作成時点で追加変更なし（調査結果の文書化のみ）

関連: `repo/vmatrix_improvement_scorecard.md`（数値スコアカード）、`repo/vmatrix_existing_assets_master.md`（資産表・G層）

---

## 0. 一文定義

```text
V = 展開マップと同じ pos4 隊列 × ユーザー調整可能な baba/pace 赤枠 × 検証済み注記。
     単体予測精度が高い資産でも、展開 ctx と体系が違えば V へ入れない。
     cold start の baba は holding_days まで。nichi_bias / ten_speed / layout は V 外。
```

**V の役割:** SRA 上の **展開地図**（どの馬場×ペース組み合わせでどの位置が恵まれるかの可視化）。  
**V の非役割:** 買い目・加点・Rank/VH 代替・能力スコア。

---

## 1. 調査アークと判定（P0 → P2-D）

| ID | 内容 | 判定 | holdout / 根拠 | 本番への影響 |
|----|------|:----:|----------------|--------------|
| **P0** | pos4 整合（Y=pos4→ten→score、≫=finish_push） | **採用済み** | 2,756R（2024–25）帯一致 pos4 **100%** vs ten 76% | 座標正本確定 |
| **P1** | 検証済み注記の V 直下統一（表示のみ） | **採用済み** | `core/vmatrix_annotations.py` | caption のみ |
| **P2-1** | ten_speed / predict_pace_intensity → V **ペース行** | **NO-GO** | 14,764R；Acc B 41.8% > A 37.2% も **64% 乖離**、Jaccard **0.38** | pace 行は ctx.pace 維持 |
| **P2-A** | nichi_bias → V **baba init** | **NO-GO** | holdout **未実施**（設計ゲート不通過） | baba ①② 維持 |
| **P2-D** | course layout → 展開MAP最終直線 x（D-1b） | **NO-GO** | 10,803R（2024–25）；B−A **0.0000 ρ**、不変 **100%** | layout → V 根拠なし |

**P2-D の位置づけ:** 展開MAP（V とは別ウィジェット）の最終直線 x に対する検証。**V 赤枠・座標・pos4 には触れていない。** layout を V へ接続する根拠は **ゼロ**（効果自体が現行コードでゼロ）。

---

## 2. 凍結仕様 — 座標

### 2.1 縦軸（Y）— P0 確定

| 項目 | 仕様 |
|------|------|
| **正本** | `build_pace_context()` → `pos4`（0=先頭、1=最後方） |
| **解決入口** | `resolve_v_pos(umaban, name, score, profiles, pos4)` のみ |
| **優先順** | `pos4` → `profiles['ten']` → `h['score']`（0.5 FB） |
| **変換** | `y = (1.0 - pos) * 3.0`（0..3、後→前） |
| **禁止** | `predict_finish` を Y に使用、`ten_speed` を Y に使用、sashikiri による y 加算 |

**根拠:** `repo/brief_vmatrix_pos4_align.md`、`tests/test_vmatrix_pos4.py`（9件）、`scripts/vmatrix_pos4_align_check.py`

### 2.2 横軸（X）— 変更なし

| 項目 | 仕様 |
|------|------|
| **式** | `lane = 0.65 × gate + 0.35 × pos` |
| **gate** | `(umaban - 1) / (max_uma - 1)` |
| **pos** | `resolve_v_pos` と同一 |
| **表示** | `x = lane × 3.0` |

係数・枠正規化の変更は **禁止**（P0 不変条件）。

### 2.3 ≫ 表示 — P0 確定

| 項目 | 仕様 |
|------|------|
| **意味** | 4角想定位置より **直線到達（finish）が前** に出る想定 |
| **判定** | `finish_push_delta(pos, finish, source)` ≥ `V_FINISH_PUSH_MIN`（**0.15**） |
| **条件** | `source == 'pos4'` の馬のみ（ten/score 基準馬は ≫ なし） |
| **finish 源** | `predict_finish()`（能力・人気混入あり → **座標禁止・表示のみ**） |

### 2.4 赤枠（V エリアハイライト）— 変更禁止

| 定数 | 値 |
|------|-----|
| `V_BABA_PATTERNS` | フラット / 内2頭目まで荒れ / 内4頭目まで荒れ |
| `V_PACE_PATTERNS` | スロー / ミドル / ハイ |
| `_V_COL` | フラット→0, 内2→1, 内4→2 |
| `_V_ROW` | スロー→0, ミドル→1, ハイ→2 |

**該当判定:** ユーザー選択（または自動初期値）の `(baba, pace)` が指す **1 マス**。  
**禁止:** 9 マス確率化、連続スコア化、layout/含水/クッションによる赤枠自動変更。

---

## 3. 凍結仕様 — 自動初期値

### 3.1 baba（赤枠列）— P2-A 後も不変

```text
優先 ① empirical_bias.baba_for_v（当日 JRavan 先行レース実測）
     ② holding_days + condition（scraper meta の静的ヒューリスティック）
     ③ ユーザー手動（vm_baba radio）
```

| 経路 | 状態 |
|------|------|
| `empirical_bias` / `empirical_bias_from_db` | **接続済み・維持** |
| `holding_days` + 馬場状態 | **接続済み・維持** |
| `nichi_bias` → baba | **禁止**（P2-A クローズ：変換規則不存在、GT 未承認） |

### 3.2 pace（赤枠行）— P2-1 後も不変

```text
優先 ① build_pace_context().pace（展開マップと同一 ctx）
     ② legacy _pace.pace_label（第2 FB）
     ③ ユーザー手動（vm_pace radio）
```

| 経路 | 状態 |
|------|------|
| `build_pace_context.pace` | **接続済み・維持**（front_ratio / nige_umas ルール） |
| `predict_pace_intensity` / ten_speed | **V 禁止**（Scanner・3連複ヒント等は V 外で既存利用可） |

**P2-1 根拠:** B はペース Acc +4.6pp だが、V 行を B にすると展開マップと **64% のレースで矛盾**（Jaccard 0.38）。体系整合 > 単体 Acc。

---

## 4. 凍結仕様 — 注記（P1）

V チャート直下の **表示専用** caption。座標・赤枠・買い・Rank/VH には接続しない。

| 表示 | ソース | モジュール |
|------|--------|------------|
| 🔥 末脚 | agari≤0.33 & pop≥6 | app 既存条件 |
| ⚠ 危険 | 外有利×内枠人気 | `track_bias.danger_popular_inner` |
| ◆ 枠 | ダート枠シグナル | `track_bias.dirt_draw_signal` |
| ◇ 場 | 場別血統傾向 | `blood_course.venue_fav_note` |

**実装:** `core/vmatrix_annotations.py` → `app.py` V 直下 HTML。  
**原則:** G層#10 — 検証済み注記は馬点横の補助表示。V + 末脚 → 加点 **禁止**。

---

## 5. データフロー（凍結）

```text
fetch_jv_profiles(before_key=race_key)
        │
        ▼
build_pace_context(horses, profiles, distance, surface, layout*, wind)
        │                    * layout は引数のみ・body 未参照（pos4/pace 非依存）
        ├── pos4 ──────────────────────────────┐
        ├── pace ──→ vm_pace auto init ────────┤
        └── forward / leader / …（展開 UI）     │
                                               ▼
predict_finish(ctx, extras) ──→ finish ──→ ≫ のみ
                                               │
                                               ▼
build_v_matrix(horses, profiles, pace, baba, pos4=, finish=)
        │
        ├── Y = resolve_v_pos(pos4 → ten → score)
        ├── X = 0.65×gate + 0.35×pos
        ├── 赤枠 = _V_COL[baba] × _V_ROW[pace]
        └── 戻り: (plotly Figure, V該当馬リスト)

empirical_bias ──→ baba auto init ①
holding_days+condition ──→ baba auto init ②

vmatrix_annotations ──→ V 直下 caption（P1）
```

**展開MAP（別ウィジェット）:** `estimate_pace_map(..., layout=)` — layout は gate_w（スタートのみ）等に影響するが、**最終直線 x は layout 非依存**（P2-D D-1b 確定）。

---

## 6. 検証済み — V に入れているもの

| 機能 | 接続面 | フェーズ | 変更可否 |
|------|--------|:--------:|:--------:|
| pos4 → Y | 座標 | P0 | 凍結 |
| finish → ≫ | 表示 | P0 | 凍結 |
| ctx.pace → pace radio init | 赤枠行 | P0 | 凍結 |
| empirical → baba init ① | 赤枠列 | P0 | 凍結 |
| holding_days+condition → baba init ② | 赤枠列 | P0 | 凍結 |
| vmatrix_annotations 4種 | caption | P1 | 凍結 |
| danger / dirt_draw / venue_fav | 注記 | P1 | 凍結 |

---

## 7. 検証済み — V に入れないもの（拒否リスト）

Composer・今後の改修で **差し戻し対象**。

### 7.1 座標・赤枠（構造）

| 項目 | 理由 | 調査 |
|------|------|------|
| `_V_COL` / `_V_ROW` ルール変更 | 赤枠定義の破壊 | G#8, P0 |
| pos4 / ctx.pace / finish_push 再定義 | P0 確定 | P0 |
| ten_speed → V 縦 or V 行 | ρ 劣位 + 体系不一致 | G#4, P2-1 |
| predict_pace_intensity → V ペース行 | Acc↑ も 64% 乖離、Jaccard 0.38 | P2-1 |
| predict_finish → Y | 能力・人気混入 | G#6, P0 |
| PCI / Rank / VH / 人気 → V 本体 | priced-in / レイヤー混同 | G#3,#5 |
| layout → V baba/pace/coords | D-1b で追加説明力ゼロ | P2-D |
| get_course_layout → 赤枠自動 | 未検証 + D-1b NO-GO | P2-D |

### 7.2 baba cold start

| 項目 | 理由 | 調査 |
|------|------|------|
| nichi_bias → baba | 変換規則なし、GT 未承認 | P2-A |
| empirical 閾値を inner_expected に流用 | 既存規則なし・3 分類潰れ | P2-A review |

### 7.3 買い・加点

| 項目 | 理由 |
|------|------|
| V 該当馬への加点 | priced-in（221,454R） |
| V × 人気薄を穴馬化 | 展開恩恵 overbet |
| 検証済み注記 → V 座標・スコア | P1 で表示に限定 |

### 7.4 V 外で既存利用可

| 項目 | V での扱い | 既存配線 |
|------|------------|----------|
| ten_speed / predict_pace_intensity | V 禁止 | Scanner・3連複ヒント |
| get_course_layout notes | V 禁止 | describe_pace 文言 |
| wind_effect | 禁止（r≈0） | 展開MAP 任意 |

---

## 8. holdout 数値記録（凍結時点）

### P0 — pos4 align（2024–25, 2,756R）

| 指標 | ten 基準 | pos4 基準 |
|------|----------|-----------|
| 帯一致率 | 76.1% | **100%** |
| V Jaccard（参考） | — | 0.59 mean |

出典: `repo/analysis/vmatrix_pos4_align/summary.json`

### P2-1 — pace holdout（2021–25, 14,764R）

| 指標 | A: ctx.pace | B: predict_pace_intensity |
|------|-------------|---------------------------|
| Accuracy | 37.2% | **41.8%** |
| A/B pace 一致 | — | **36%** |
| V Jaccard（baba 固定） | — | **0.38** |

出典: `repo/vmatrix_pace_holdout.md`, `repo/analysis/vmatrix_pace_holdout/summary.json`

### P2-A — nichi（holdout 未実施）

| ゲート | 結果 |
|--------|------|
| nichi → V_BABA 変換規則 | **不存在** |
| GT-2 正解代理 | **未承認** |

出典: `repo/vmatrix_nichi_mapping_review.md`

### P2-D — layout D-1b（2024–25, 10,803R paired）

| 指標 | A: layout={} | B: layout=full | B−A |
|------|--------------|----------------|-----|
| mean Spearman ρ | 0.5273 | 0.5273 | **0.0000** |
| 不変レース率 | — | — | **100%** |
| layout → V 根拠 | — | — | **なし** |

出典: `repo/vmatrix_p2_layout_holdout.md`, `repo/analysis/vmatrix_p2_d/summary.json`

---

## 9. G層（V 本体禁止事項 — 凍結）

`repo/vmatrix_existing_assets_master.md` §G層 を **V 改修の上位規約** として再掲:

1. V 該当馬への加点禁止  
2. V×人気薄を穴馬化しない  
3. PCI 使用禁止  
4. ten_speed を馬の縦座標に使用しない  
5. Rank / VH / 戦闘力 / 人気を V 本体へ混入しない  
6. predict_finish を V 縦座標に使用しない（≫ のみ）  
7. 未検証のコース・含水・クッション等を holdout 前に赤枠へ入れない  
8. `_V_COL` / `_V_ROW` を変更しない  
9. ten_speed / predict_pace_intensity を V へ単独接続しない  
10. 検証済み注記を V 座標・加点へ混ぜない  

---

## 10. 実装者向けルール（Composer / 改修共通）

### やってよい

- V 直下 caption の文言・レイアウト改善（座標非接続）
- `vmatrix_annotations` の表示条件を **既存関数委譲のまま** 整理
- P0/P1 のテスト・smoke 維持
- V 外（Scanner、エビデンス表、展開MAP UI）の独立改善

### やってはいけない

- `build_v_matrix` / `resolve_v_pos` の座標契約変更
- 赤枠ルール・閾値の事後最適化
- holdout なしでの新資産 V 接続
- 「Acc が高いから」ten_speed / layout / nichi を V へ入れる
- V 該当を playbook / 買い目 / Rank に接続

### 変更前チェックリスト

1. 本書 §6（入れてよい）に該当するか？  
2. §7 拒否リストに触れないか？  
3. G層 #1–10 を侵害しないか？  
4. 展開マップ（`build_pace_context`）と体系が一致するか？  
5. holdout または既存 verified 文档の根拠があるか？

---

## 11. スコープ外（本凍結後の候補 — 未着手）

| ID | 内容 | 状態 |
|----|------|------|
| P2-B | course_empirical → baba | 未調査 |
| P2-C | bias_dashboard σ → baba | 未調査 |
| P2-E | クッション・含水 → 赤枠 or 注記 | 未調査 |
| P2-F | 頭数・距離 → lane | 未調査 |
| P2-D2 | layout notes → V caption 定量 | 未検証（D-1b NO-GO 後も別 GO 要） |

**原則:** 上記は **別 GO + holdout + 本書更新** まで本番 V へ接続しない。

---

## 12. 参照索引

| ドキュメント | 内容 |
|--------------|------|
| `repo/brief_vmatrix_pos4_align.md` | P0 実装 brief |
| `repo/brief_vmatrix_p1_annotations.md` | P1 実装 brief |
| `repo/vmatrix_pace_holdout.md` | P2-1 holdout |
| `repo/vmatrix_nichi_mapping_review.md` | P2-A 設計ゲート |
| `repo/vmatrix_p2_layout_holdout.md` | P2-D D-1b holdout |
| `repo/vmatrix_course_shape_design.md` | P2-D 設計 |
| `repo/vmatrix_improvement_scorecard.md` | 数値スコアカード |
| `repo/vmatrix_existing_assets_master.md` | 資産表・G層 |
| `core/pace_map.py` | `build_v_matrix`, `resolve_v_pos`, 赤枠定数 |
| `core/vmatrix_annotations.py` | P1 注記 |
| `tests/test_vmatrix_pos4.py` | P0 単体テスト |
| `tests/test_vmatrix_annotations.py` | P1 単体テスト |

---

## 13. 凍結宣言

```text
2026-09-07 時点で、Vエリアの座標・赤枠・自動初期値・注記について、
P0/P1 で採用した仕様と、P2-1/P2-A/P2-D で NO-GO と確定した拒否事項を
本書に統合し、現行本番仕様として凍結する。

以降、Vエリアへの新規接続・座標変更・赤枠変更は、
本書 §10 チェックリストと holdout 結果の追記なしには行わない。
```

---

*最終凍結: 2026-09-07 / 次回改訂: 別 GO の holdout 完了時のみ（事後改変禁止）*
