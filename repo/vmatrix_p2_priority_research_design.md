# Vエリア P2候補 — 優先順位比較の研究設計

> **目的：** P2候補どれを次に調査／実装検討するかを、**同一ルーブリック**で比較するための設計書。  
> **本書は研究設計のみ。** 実装・閾値調整・本番配線は含まない。  
> **前提：** P0（pos4・ctx.pace・赤枠）と P1（注記統一）は完了／進行中。Phase 2-1 で **ten_speed→Vペース行は現行維持（調査クローズ）**。

---

## 1. 比較の問い

```text
「V地図を賢くする」ためではなく、
既存データのうち“Vの表示・初期値”に安全に載せられるものはどれか？
```

優先順位の決め方（**固定。事後変更禁止**）：

| 順位 | 判断軸 | 意味 |
|:---:|--------|------|
| 1 | **整合性** | 展開マップ（`build_pace_context`）・pos4・同一 `_pm_ctx` と矛盾しないか |
| 2 | **予測／説明の改善** | 対象シグナル自体が holdout で現行より改善するか（買い成績ではない） |
| 3 | **副作用の小ささ** | V赤枠・該当頭数・Jaccard が Phase 2-1 級の大崩れを起こさないか |
| 4 | **実装リスク** | 変更面積・欠損・ライブデータ依存・回帰テスト容易性 |
| 5 | **買い成績** | **参考のみ**。V該当ROI等で採用判断しない（`verified_tenkai_priced_in`） |

---

## 2. P2候補一覧（比較対象）

Phase 2-1 以降、**ten_speed / predict_pace_intensity の V 接続は P2 から除外**（G層#9・`repo/vmatrix_pace_holdout.md`）。

| ID | 候補 | 既存資産 | 想定接続面 | 検証分類 |
|----|------|----------|------------|----------|
| **P2-A** | `nichi_bias` → baba 自動初期値の第3候補 | `track_bias.nichi_bias()` | V **baba radio** init | 弱い（静的表2018–25） |
| **P2-B** | `course_empirical_bias` → baba / 説明 | `track_bias.course_empirical_bias()` | エビデンス or baba ヒント | 実測あり（10y静的） |
| **P2-C** | `bias_dashboard` σ・推移 | `track_bias.bias_dashboard()` | baba init または caption | 実測あり（当日） |
| **P2-D** | コース形状（1角/直線/大箱） | `get_course_layout`, `course_profile_label` | 展開MAP精度 or V caption | 実測あり（layout BT） |
| **P2-E** | クッション値・含水率 | `lookup_track_cond`, `cushion_day_shift` | **赤枠** or 注記 | 血統×shift 実測／**荒れ无效** |
| **P2-F** | 頭数・距離 | `shusso_tosu`, `kyori` | V **座標**（lane 等） | 各種BTの層別キー／**V未接続** |

**P3（本比較の対象外）：** 連続V Advantage、ペース確率化、9マススコア化、ML。

---

## 3. 共通 holdout プロトコル

Phase 2-1（`scripts/vmatrix_pace_holdout_check.py`）と揃える。

| 項目 | 規定 |
|------|------|
| DB | `data/jravan.db` |
| 期間 | train: 2021–2023 / holdout: **2024–2025**（レースキー先頭8桁） |
| 母集団 | JRA 場01–10、`shusso_tosu≥8`、`fetch_jv_profiles` 40%以上（ pace 系と同型） |
| リーク | 各レース `before_key=race_key`（既存関数どおり） |
| 禁止 | holdout 結果を見てから閾値再調整・新特徴量・新ML |
| V座標 | **常に現行** pos4→ten→score（候補は baba/pace init または caption のみ） |
| 副次指標 | V該当 Jaccard（現行 vs 候補）、該当頭数/レース、複勝率・単ROI（**参考**） |

各候補スクリプトの出力先：`repo/analysis/vmatrix_p2_<id>/summary.json` + 1ページ Markdown。

---

## 4. 候補別研究設計

### P2-A：`nichi_bias` → baba init 強化

**現行：** baba init = ① `empirical_bias.baba_for_v` → ② `holding_days`+馬場状態 → フラット。

**候補：** ①が None のとき ③ `nichi_bias(holding_days, 芝)` の `inner_expected` で `_V_COL` インデックスを推定（**既存 `_NICHI_INNER` 閾値のみ。新閾値禁止**）。

| 項目 | 内容 |
|------|------|
| 主指標 | 当日実測 **内枠勝率**（or corner4 内側率）と nichi 期待の一致（MAE / 符号一致率） |
| 副指標 | baba 3択の Accuracy vs 現行②のみ（正解=事後 lane ラベル：`empirical_bias_from_db` の lane_label を正解代理） |
| V副作用 | baba 変更率、V Jaccard（baba×現行pace vs 候補baba×現行pace） |
| 既存根拠 | 静的表、`project_trackbias.md`（当日逆算の方が強い） |
| 成功条件 | holdout で現行②より **lane 一致 +3pp以上** かつ V Jaccard≥0.85 |
| 失敗条件 | 改善<1pp、または empirical_bias がある日に逆方向へ上書き |
| リスク | **低**（init のみ・手動上書き可） |
| 既存脚本拡張 | `scripts/intraday_bias_backtest.py` 参照、新規 `scripts/vmatrix_p2_nichi_baba_check.py` |

---

### P2-B：`course_empirical_bias` → baba / 説明

**候補：** コース静的 front/inner 率から baba ヒント、または V/展開 caption のみ（**赤枠自動変更はオプション分岐**）。

| 項目 | 内容 |
|------|------|
| 主指標 | コース別 **front_rate** と当日 front_rate の相関（Spearman） |
| 副指標 | baba init Accuracy（正解=当日 empirical または事後 lane） |
| V副作用 | 同上 |
| 既存根拠 | `course_empirical_bias` 10y、`project_trackbias.md` |
| 成功条件 | 説明用途：**整合性問題なし**で採用可（数値改善不要）。baba init 用途：P2-A より優位なら A より優先 |
| 失敗条件 | コース静的と当日逆算が holdout で符号逆転が多い（>40%） |
| リスク | **低〜中**（静的 vs 当日の混同注意） |
| 脚本 | `scripts/vmatrix_p2_course_empirical_check.py` |

---

### P2-C：`bias_dashboard` σ → baba init

**候補：** `sigma_inner` / `sigma_front` が閾値超えのとき baba を 1段シフト（**既存 `bias_stars` / dashboard 文言の閾値のみ**）。

| 項目 | 内容 |
|------|------|
| 主指標 | σ 高の日の lane 方向予測 Accuracy vs 現行 |
| 副指標 | confident 日に限った precision |
| 既存根拠 | 当日推移は `project_trackbias.md` で実装済み |
| 成功条件 | empirical_bias 欠損日（コールドスタート）でのみ +5pp 改善 |
| 失敗条件 | empirical_bias あり日で上書きして悪化 |
| リスク | **中**（empirical との優先順位設計が必須） |
| 脚本 | `scripts/vmatrix_p2_bias_sigma_check.py` |

---

### P2-D：コース形状（1角/直線/大箱）

**接続面の分岐（2トラックで別採点）：**

| トラック | 接続先 | 主指標 |
|----------|--------|--------|
| D-1 | **展開MAP**（`estimate_pace_map`） | 直線相と着順 ρ（`layout_effect_backtest.py` 再現） |
| D-2 | **V caption のみ** | ユーザー向け説明整合（定量不要） |
| D-3 | V **座標**（gate/straight 係数） | **原則禁止**（P2-F と合わせて別枠） |

| 項目 | 内容 |
|------|------|
| 成功条件 D-1 | layout あり vs なしで holdout ρ **+0.02以上**（layout BT 再確認） |
| V副作用 | D-1 は V 非変更。D-3 は Phase 2-1 並みの Jaccard 調査必須 |
| リスク | D-1 **低**、D-3 **高** |
| 脚本 | 既存 `scripts/layout_effect_backtest.py` + holdout 2024–25 分割 |

**優先示唆（設計時点）：** D-1（展開MAP）> D-2（caption）>> D-3（V coords）。

---

### P2-E：クッション・含水 → 赤枠

**警告：** `project_pace_map_rebuild.md` — 荒れ予測无效。血統×shift は **注記（P1類似）** 向き。

| 項目 | 内容 |
|------|------|
| 主指標 | cushion shift 帯と **当日 inner/front 実測** の関連（単調性） |
| 副指標 | baba 3択 Accuracy（赤枠接続案のみ） |
| 既存根拠 | `verified_cushion_theory`, `verified_baba_blood` / 荒れ无效 |
| 成功条件 | baba 接続は **holdout lane Accuracy +2pp** かつ 単調性確認 |
| 失敗条件 | 荒れ・lane とも単調性なし（再現）→ **赤枠接続は永久保留**、P1注記のみ |
| リスク | **高**（ライブ track_cond 欠損・場間絶対値比較禁止） |
| 脚本 | `scripts/baba_moisture_split.py` 拡張 or `vmatrix_p2_cushion_baba_check.py` |

---

### P2-F：頭数・距離 → V 座標

**現行：** X = `0.65*gate + 0.35*pos`（gate は `umaban/max` のみ。頭数は未使用）。

| 項目 | 内容 |
|------|------|
| 主指標 | pos4 帯一致率（Phase pos4 align と同型）— 座標変更後も **≥0.98** 維持必須 |
| 副指標 | V Jaccard vs 現行、該当頭数変化 |
| 既存根拠 | 頭数は empirical 内側率等で使用済み。V coords 未検証 |
| 成功条件 | **設計上ほぼ unreachable** — 座標変更は G層「赤枠・座標変更禁止」に抵触しやすい |
| 推奨 | **調査優先度：最低**。caption（「多頭数レース」）のみなら P2-D-2 相当 |
| 脚本 | 必要なら `vmatrix_p2_fieldsize_x_check.py`（オフラインのみ） |

---

## 5. 優先順位スコアカード（調査後に記入）

調査完了後、各 ID を 1–5 点で採点（**事前の順位付けではない**）。

| 次元 | 1点 | 3点 | 5点 |
|------|-----|-----|-----|
| 整合性 | 展開ctxと64%乖離級 | 部分一致 | 完全同期（init/captionのみ） |
| 予測改善 | holdout 悪化 | ±1pp | +3pp以上 |
| V副作用 | Jaccard<0.5 | 0.5–0.85 | ≥0.85 |
| 実装リスク | 座標/買い触り | baba init | 注記/caption のみ |
| データ可用性 | ライブ欠損多 | 部分 | jravan+既存UIで常時 |

**総合優先度 = 整合性×2 + 予測改善×2 + V副作用×1.5 + 実装リスク×1 + データ×0.5**（最大25点）

記入テンプレ：

| ID | 整合 | 予測 | 副作用 | リスク | データ | 合計 | 判定 |
|----|:---:|:---:|:---:|:---:|:---:|:---:|------|
| P2-A | — | — | — | — | 3 | — | **クローズ**（変換/GT不足・holdout前停止） |
| P2-B | | | | | | | 未調査 |
| P2-C | | | | | | | |
| P2-D | — | — | — | — | — | — | **設計完了**（D-1b holdout GO可） |
| P2-E | | | | | | | |
| P2-F | | | | | | | |

**判定ラベル（固定）：**

- **実装候補** — 総合≥18 かつ 整合≥4 かつ 副作用≥4
- **注記のみ** — 予測は弱いが整合≥4（→ P1 拡張）
- **保留** — 整合<3 または 副作用<3
- **クローズ** — holdout 悪化 or G層抵触

---

## 6. 推奨調査順（設計時点の仮説順）

実施順の提案。**スコア確定前の作業順**であり、採用順ではない。

```text
1. P2-A (nichi_bias)     … 変更小・empirical 欠損日の穴埋め
2. P2-C (bias σ)         … 同上・当日データと相性良
3. P2-B (course static)  … caption / 弱い baba ヒント
4. P2-D-1 (layout→MAP)   … V非変更・展開精度のみ
5. P2-E (cushion)        … 赤枠は最後。ダメなら注記固定
6. P2-F (頭数/距離 coords) … 原則スキップ可
```

**並行可：** A / B / C は同一 holdout 母集団で独立脚本を並走可能。

---

## 7. 各研究の成果物

| 成果物 | 内容 |
|--------|------|
| `scripts/vmatrix_p2_<id>_check.py` | オフライン holdout（本番非接続） |
| `repo/analysis/vmatrix_p2_<id>/summary.json` | 数値 |
| `repo/vmatrix_p2_<id>_report.md` | 1–2ページ（主指標・副作用・判定ラベル） |
| スコアカード更新 | 本書 §5 表を埋める |
| **やらないこと** | app.py / pace_map.py の本番配線（別 Phase でユーザー承認後） |

---

## 8. 禁止事項（全 P2 共通）

1. V該当馬への加点・買い接続  
2. ten_speed / predict_pace_intensity の V 再接続  
3. pos4 / ≫ / ctx.pace の変更  
4. holdout 後の閾値チューニング  
5. 「V ROI が良いから採用」の論理  
6. PCI / Rank / VH / 人気 の V 混入  
7. 未検証の連続スコア化・確率化  

---

## 9. 設計時点の予備所見（採用判断ではない）

| ID | 所見 |
|----|------|
| P2-A/C | baba **init** 限定なら整合性リスク低。empirical 優先は維持 |
| P2-B | **caption / 注記**向き。自動 baba は A/C 次点 |
| P2-D | 展開MAP改善と V は分離評価。V coords への形状投入は非推奨 |
| P2-E | 血統フラグは P1 注記で足りる可能性大。赤枠は期待薄 |
| P2-F | Phase 2-1 と同型の「地図をいじるリスク」— 最優先しない |

**Phase 2-1 の教訓：** 予測は改善しても **展開体系と乖離する接続は保留**（`repo/vmatrix_pace_holdout.md`）。P2 でも「整合性→予測→副作用」の順を崩さない。

---

## 10. 次アクション（実装前）

1. 本設計書のレビュー（候補 ID・holdout 分割・成功条件）  
2. P2-A 脚本作成 → holdout 実行 → §5 スコアカード初回記入  
3. 結果を見て P2-C / B の順で繰り返し  
4. 全候補スコア確定後、`repo/vmatrix_p2_priority_ranking.md` に**ランキングのみ**記載（本番配線は別 GO）

---

*作成：2026-09-07 / 参照：`repo/vmatrix_existing_assets_master.md`, `repo/vmatrix_pace_holdout.md`, `repo/memory/project_trackbias.md`*
