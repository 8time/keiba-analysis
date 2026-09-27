# Vエリア改善 — 既存資産マスター表

> 作成目的：Vエリア改修に使えるアプリ内データ・関数・検証済み機能の棚卸し。  
> **本ドキュメントは調査・整理のみ。ロジック変更は含まない。**  
> 現行V仕様（pos4縦・≫補助・赤枠維持）を前提に記載。

---

## G層：Vエリア本体への禁止事項

1. **V該当馬への加点禁止** — 合議・スコア・買い目・playbookへ接続しない
2. **V×人気薄を穴馬化しない** — 展開恩恵×人気薄は過剰人気（`verified_tenkai_priced_in`）
3. **PCIを使用しない** — 162,353R検証でpriced-in/不採用（`verified_pci_pricedin`）
4. **ten_speedを馬の縦座標に使用しない** — ten/corner habitの方が位置予測に優位（`scripts/vmatrix_pos_backtest.py`）
5. **Rank / VH / 戦闘力 / 人気をV本体へ混入しない** — 能力・買いレイヤーと分離
6. **predict_finishをVの縦座標そのものに使用しない** — ≫表示のみ（`finish_push_delta`）
7. **未検証のコース・含水・クッション等を勝手に数値化しない** — holdout前に赤枠へ入れない
8. **既存の赤枠ルール（`_V_COL` / `_V_ROW`）を変更しない** — 今回の調査でも触らない
9. **ten_speed / predict_pace_intensity を V へ単独接続しない** — ペース予測としては holdout で A より改善（Acc 41.8% vs 37.2%, `repo/vmatrix_pace_holdout.md`）だが、体系が `build_pace_context`（展開マップ）と異なり、接続すると 64% のレースで V 行と展開マップが乖離。Scanner・3連複ヒント等の既存配線に留める
10. **検証済み注記を V 座標・加点へ混ぜない** — 末脚/危険人気/ダート枠等は「馬点横の補助注記」のみ。V + 末脚 → 加点 禁止

---

## マスター表（列定義）

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|

以下、層ごとに行を記載。

---

### A層：馬の位置推定

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|
| A | **pos4** | `core/pace_map.py` → `build_pace_context()` | 展開マップ4角・新聞隊列図（finish欠損時）・V縦座標 | `{umaban: float}` 0=先頭, 1=最後方。forward+相互作用補正 | 馬ごと欠損→`resolve_v_pos`がten/scoreへ | **検証済み** spearman~0.46（`project_pace_map_rebuild.md`）; align holdout 2756R 帯一致100% | ○ | **Y座標正本（採用済）** | **P0** | 展開マップと整合。改修済み |
| A | **resolve_v_pos** | `core/pace_map.py` | V-matrix Y/X混ぜのpos解決 | `(pos, source)` source=`pos4`\|`ten`\|`score` | pos4キー int/str両対応 | **検証済み** `tests/test_vmatrix_pos4.py`, `scripts/vmatrix_pos4_align_check.py` | ○ | **V座標解決の唯一入口** | **P0** | ロジック二重化防止 |
| A | **ten** | `fetch_jv_profiles()` → `prof['ten']` | pos4欠損時のV縦・`_phase_frac`開始相 | 過去走最早コーナー相対位置 0–1 | JV DBなし/コーナー無→None | **検証済み** corner habit ρ+0.474 vs 実corner1（`vmatrix_pos_backtest.py` 2023–25） | △ | **Yフォールバックのみ** | **P0** | 習性位置。pos4欠損専用 |
| A | **score（脚質スコア）** | `calculator.analyze_pace_distribution()` / `score_from_pastruns()` | V縦最終FB・X混ぜ(0.35)・forwardブレンド | 0–1。PastRuns通過順位由来 | PastRuns無→0.5 | **一部検証** 脚質priced-in（`verified_legtype_axis`） | △ | **Y最終FB + X lane** | **P0** | 最弱フォールバック |
| A | **predict_finish / finish** | `core/pace_map.py` → `predict_finish()` | 展開マップ直線相・新聞隊列（優先表示）・V≫ | `{umaban: 0–1}` pos4+kick+apt+power+**pop**合成 | horses<2→pos4コピー | **検証済み** finish spearman 0.39–0.53 vs pos4 0.16（250–300R calib） | △ | **≫のみ（座標禁止）** | **P0** | 能力・人気混入。縦に使わない |
| A | **finish_push_delta / V_FINISH_PUSH_MIN** | `core/pace_map.py` | V-matrix黄色≫ | delta=pos−finish; push if ≥0.15 & source=pos4 | ten/score基準馬は≫なし | **検証済み** 単体テスト; align spec | ○ | **表示オーバーレイ** | **P0** | sashikiri y加算の代替 |
| A | **上がり3F / agari** | `fetch_jv_profiles()` → `agari`, `agari_time` | `predict_finish` kick・sashikiri・末脚妙味 | agari=場内相対順位0=最速; time=秒 | ato3f無→kick 0.5 | **検証済み** 末脚×人気薄 ROI~111%（`verified_spurt_index` 14,702R） | △ | **V本体不可。直下アラート** | **P1** | 検証済み注記はV近傍UI |
| A | **上がり順位（live）** | SRA `AvgAgari` → `_pm_extras['kick']` | `predict_finish` kick入力 | 出走表の上がり3F数値 | 列欠損→JV agari | **一部検証** finishモデル内 | × | **finish経由のみ** | — | V座標・赤枠不可 |
| A | **脚質ラベル / kyaku_pos** | `style_from_score`, JV kyakushitsu | V hover・展開チップ・forwardブレンド | 逃げ/先行/差し/追込; kyaku_pos 0–1 | 履歴無→不明/None | **検証済み** priced-in（`verified_legtype_axis`） | × | **表示ラベルのみ** | — | 位置はpos4/ten/score |
| A | **nige_rate / senko_rate** | `fetch_jv_profiles()` | ctx保存のみ（他未参照） | 過去走逃げ/先行率 | 履歴薄→0 | **未確認** V未使用 | × | **未接続** | P3 | forwardに未配線 |
| A | **ten_speed** | `fetch_jv_profiles()`, `predict_pace_intensity()` | pos4/forwardブレンド・Scanner・3連複ヒント | sec/600m 小=速い | time/ato3f無→None | **検証済み** 位置ρ+0.232<ten; pace Acc 41.8%（Phase2-1） | × | **V縦/V行とも禁止** | **禁止** | G層#4/#9。展開マップと体系不一致 |
| A | **tactics_forward（騎手/厩舎）** | `jockey_tactics.py`+`trainer_tactics.py` → `tactics_forward()` | `build_pace_context` forward 15% | 騎60%+厩40%の前受けprior 0–1 | 名前不明→None | **不採用/禁止** 荒れ選択二重計上（`verified_tenkai_priced_in` pace_pressure BT） | × | **pos4間接のみ** | 禁止 | 絵の精度のみ可、妙味不可 |
| A | **sashikiri_table** | `core/pace_map.py` | 展開MAP≫(margin≥1.5)・差し切り表UI | margin秒・rank4等 | leader agari無→[] | **検証済み** y加算廃止テスト | × | **引数互換・V未使用** | **P0** | finish≫に移行済 |
| A | **netkeiba AI展開4角** | `core/ai_tenkai.py` → `parse_tenkai_positions()` | SRA手動照合（**score**帯比較）・elim tenkai2 | `{umaban:{start,corner3,corner4}}` left% | HTML取得失敗→空 | **不採用/禁止** display only priced-in（`project_ai_tenkai_overlay`） | × | **V未接続** | 禁止 | pos4/finishと別系統 |
| A | **forward** | `build_pace_context()` 内部 | pos4生成の中間 | `{umaban: 0–1}` 多因子blend | — | **一部検証** pos4経由 | × | **pos4の上游** | P0 | Vはpos4スライスのみ消費 |
| A | **leader / contested / nige_umas** | `build_pace_context()` | 展開UI・describe_pace・pos4 cap | ハナ馬番号・争いフラグ等 | leader無→None | **一部検証** 表示・pos4生成 | × | **V未直接使用** | — | pace分類の入力 |

---

### B層：有利ゾーン・馬場バイアス

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|
| B | **_V_COL / V_BABA_PATTERNS** | `core/pace_map.py` 定数 | V赤枠**列**（内/中/外） | フラット/内2/内4 → 0/1/2 | — | **検証済み** V買い=priced-in（`verified_emp_bias_danger` 221,454R） | ○ | **赤枠列（現状維持）** | **P0** | 変更禁止 |
| B | **baba radio（馬場ラジオ）** | `app.py` ~L4940 | ユーザーがV列選択 | UI 3択 | — | 同上 | ○ | **赤枠入力** | **P0** | 手動上書き可 |
| B | **empirical_bias / baba_for_v** | `core/track_bias.py` → `empirical_bias()`, `empirical_bias_from_db()` | V baba**自動初期値**（最優先）・エビデンス | `{baba_for_v, lane_label, front_rate, inner_rate, …}` | 当日先行レース不足→None | **検証済み** 持続性 61% vs 50% front（`project_trackbias.md`）; V買いpriced-in | ○ | **赤枠自動initのみ** | **P0** | 既にV接続済 |
| B | **開催日数 holding_days + 馬場状態** | scraper `meta` | V baba自動init**第2候補** | 日数int; 良/稍重/重/不良 | meta欠損→フラット | **弱い検証** ヒューリスティック（`trackbias_integration_plan.md`） | ○ | **emp無時のFB init** | **P0** | 静的推定 |
| B | **nichi_bias** | `core/track_bias.py` | バイアスダッシュボード・エビデンス | 日目別 front/inner 期待値 | nichi不明→None | **弱い検証** 静的表2018–25; **P2-Aクローズ**（変換規則なし） | × | **V baba禁止** | **禁止** | `repo/vmatrix_nichi_mapping_review.md` |
| B | **course_empirical_bias** | `core/track_bias.py` | エビデンス・新聞・コースプロファイル | 10y JRavan front/inner率 | サンプル不足→None | **検証済み** 実測（`project_trackbias.md`） | △ | **エビデンスのみ** | P2 | V赤枠未接続 |
| B | **danger_popular_inner（危険人気）** | `core/track_bias.py` | エビデンス・`danger_gate` veto | 外有利×内枠人気 | 条件不合→None | **一部検証** fade -4.6pp; holdout2025 z-1.77弱体化（`verified_emp_bias_danger`） | ○ | **V近傍注記（veto）** | **P1** | 座標不可。表示整理 |
| B | **dirt_draw_signal** | `core/track_bias.py` | エビデンス・Race Scanner | boost/danger/caution | 芝→None | **検証済み** 176,723R dirt z±9.4/−6.0（`verified_dirt_draw_bias`） | ○ | **エビデンス注記** | **P1** | V座標不可 |
| B | **bias_dashboard / σ / 推移** | `core/track_bias.py` | SRAエビデンス表 | 当日σ・front/inner推移 | DB不足→空 | **検証済み** 表示・説明用 | △ | **キャプション/表** | P2 | 赤枠数式未接続 |
| B | **frame_eval / comeback_flag** | `core/track_bias.py` | エビデンス表示 | 枠評価・巻返し | — | comeback **不採用**（`verified_comeback_overbet`） | × | **未接続** | 禁止 | 穴信号として有害 |
| B | **クッション値 cushion** | `lookup_track_cond`, `jra_baba_scraper`, UI | エビデンス・血統フラグ | mm / 日次shift | 未取得→空 | **検証済み** 血統×shift（`verified_cushion_theory`）; **荒れ无效** | △ | **未検証→赤枠禁止** | **P2** | 存在≠投入可 |
| B | **含水率 moisture** | 同上 + `dirt_moisture_bloodtype` | エビデンス・血統 | % | 未取得→空 | **検証済み** sire×moisture（`verified_baba_blood`） | △ | **未検証→赤枠禁止** | **P2** | venue比較は見る用 |
| B | **track_cond_cache** | `core/track_cond_cache.py` | SRA 24hキャッシュ | cushion/moist | 期限切れ→None | インフラ | × | **V未使用** | — | データ供給のみ |

**B層まとめ — V赤枠に既接続：** `baba` radio ← `empirical_bias.baba_for_v` ← holding_days/馬場  
**存在するがV赤枠未接続：** nichi_bias, course_empirical, cushion, moisture, σ推移

---

### C層：ペース

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|
| C | **_V_ROW / V_PACE_PATTERNS** | `core/pace_map.py` 定数 | V赤枠**行**（前/中/後） | スロー/ミドル/ハイ → 0/1/2 | — | V買いpriced-in | ○ | **赤枠行（現状維持）** | **P0** | 変更禁止 |
| C | **pace radio** | `app.py` ~L4955 | ユーザーV行選択 | UI 3択 | — | 同上 | ○ | **赤枠入力** | **P0** | 手動上書き可 |
| C | **build_pace_context.pace** | `build_pace_context()` | V pace**自動初期値**・展開全体 | スロー/ミドル/ハイ | — | **検証済み** pos4/pace pipeline | ○ | **赤枠auto init** | **P0** | `_pm_ctx['pace']` |
| C | **front_ratio** | `build_pace_context()` | pace判定・UIチップ | 0–1 前向き率 | — | **弱い検証** arare residual z≤1.69（`verified_pace_congestion_weak` 30,767R） | △ | **pace行の入力（間接）** | P0 | 既にpace分類に使用 |
| C | **predict_pace_intensity** | `core/pace_map.py` | Scanner・3連複・session `_pace_int_*` | `{z, label, pred_pace, n}` | ten_speed不足→note | **検証済み** r+0.226（22,721R）; Phase2-1 Acc 41.8% | × | **V接続禁止** | **禁止** | G層#9。展開ctx.paceと64%不一致 |
| C | **estimate_pace_map / build_figure** | `core/pace_map.py` | 展開マップ可視化 | phase別 x,y | horses<2→空 | **検証済み** pace_backtest calib | × | **V別ウィジェット** | — | 同一pos4源 |
| C | **describe_pace** | `core/pace_map.py` | 展開1行コメント | 文字列 | — | 表示 | × | **V未使用** | — | |
| C | **wind / wind_effect** | `fetch_wind`, `wind_effect()` | 展開MAP微調整（任意） | 風速・方向 | API失敗→無 | **不採用** r≈0（`verified_wind_no_effect`） | × | **禁止** | 禁止 | |
| C | **legacy _pace.pace_label** | `calculator` 展開分析 | V pace auto**第2FB** | 文字列 | `_pace`無→スキップ | **未確認** | △ | **FB initのみ** | P0 | ctx.pace優先 |

**C層注意：** ペース確率化・9マス確率分散・Slow25%/Mid55%等は**P3（新規合成モデル）**で今回禁止。

---

### D層：コース・馬場条件

検証分類：**実測あり** / **弱い** / **未検証仮説**

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|
| D | **get_course_layout** | `core/pace_map.py` | 展開MAP gate/straight | `{first_corner, straight, straight_course, notes}` | 未知コース→デフォルト | **実測あり** layout BT（`scripts/layout_effect_backtest.py`） | △ | **展開のみ。V赤枠不可** | **P2** | 未検証→赤枠禁止 |
| D | **course_profile_label** | `core/pace_map.py` | 適性スコア・エビデンス | 直線長/小回り/標準 | — | **実測あり** straight bucket | △ | **表示・適性** | P2 | V未接続 |
| D | **1角距離 first_corner** | `_FIRST_CORNER`+layout | 展開開始gate重み | メートル | None可 | **弱い** 閾値ヒューリスティック | △ | **未検証候補** | P2 | holdout要 |
| D | **直線長 straight** | `_STRAIGHT_LEN`+layout | finish重み・notes | メートル | — | **実測あり** finish model | △ | **未検証候補** | P2 | 赤枠未接続 |
| D | **kyori（距離）** | DB/scraper | profile norm・bias filter | int m | — | **実測あり** 各種BTの層別キー | △ | **V未使用** | P2 | 頭数と同様 |
| D | **頭数 shusso_tosu** | DB/scraper | empirical_bias内側率・narrow-N | int | — | **実測あり** 多数BT | △ | **V未使用**（Vはumaban/max） | P2 | 存在≠V coords |
| D | **芝/ダート surface** | scraper | 全パイプライン分岐 | 芝/ダ | — | **実測あり** | △ | **間接（profile/bias）** | — | |
| D | **馬場状態 condition** | scraper meta | V baba FB（重/不良→内4）・danger | 良/稍重/重/不良 | 欠損→無視 | **実測あり** 485,017R（`verified_heavy_track_bias`） | ○ | **baba init FBのみ** | P0 | 稍重≈priced-in |
| D | **クッション・含水** | `track_bias`, JRA PDF | エビデンス・血統 | 数値 | 未取得多 | **実測あり** sire系; **荒れ无效** | △ | **未検証→赤枠禁止** | **P2** | brief明示ban |
| D | **大箱/小回り / fast_track** | layout+`course_bias_text` | エビデンス文言 | ラベル | — | **弱い** 叙述的 | △ | **未検証仮説** | P2 | |
| D | **PCI / RPCI** | `race_analysis_tools`, elim_cross | 消去弱フラグpcidev | PCI指数 | PastRuns無 | **不採用** 162,353R（`verified_pci_pricedin`） | × | **禁止** | 禁止 | G層#3 |

---

### E層：能力・別レイヤー情報

| 層 | 変数/機能 | 取得元 | 現在の用途 | データ内容 | 欠損/例外 | 既存検証 | V利用候補 | Vでの扱い | 優先度 | 理由 |
|----|-----------|--------|------------|------------|-----------|----------|-----------|-----------|--------|------|
| E | **V-matrix / V該当リスト** | `build_v_matrix()` | SRA可視化・新聞pace | plotly + `[{umaban,name,style}]` | horses<2→None | **検証済み** 地図のみ; V買いpriced-in; align 2756R | ○ | **表示本体** | **P0** | 買いシグナル化禁止 |
| E | **BattleScore / 戦闘力** | `calculator.calculate_battle_score()` | SRA列・Projected Score | float+icons | — | **一部検証** top3 bonus有害（`verified_weight_top3_bonus`） | × | **finish間接のみ** | 禁止 | G層#5 |
| E | **Suitability / Strength** | `calculate_strength_suitability()` | SRA Y/X適性 | 0–100 | JV薄→低 | BT: rank不変（pace rebuild） | × | **finish apt経由のみ** | 禁止 | |
| E | **Rank / Projected Score** | `app.py` sort | 合議・playbook・表示 | 1..N | — | **検証済み** Rank10↓ fade z-7.45（`verified_rank_fav_disagree`） | × | **V未接続** | 禁止 | 買いレイヤー |
| E | **LTR / 検証AI** | `core/ltr_ranker.py` | SRA列・監査 | `{umaban: score}` | model無→空 | holdout audits | × | **禁止** | 禁止 | |
| E | **VH / value_hunter** | `core/value_hunter.py` | 合議・C-zone | tier/score/prob | — | holdout2025; **not +EV**（`project_value_horse_hunter`） | × | **禁止** | 禁止 | |
| E | **人気 / オッズ** | scraper df | 全EV・finish pop | int/float | — | 最強単因子 ρ~0.55 | × | **finish≫文脈のみ** | 禁止 | V×人気薄禁止 |
| E | **末脚妙味アラート** | `app.py` ~L4986 | V**直下**UI | pop≥6 ∧ agari≤0.33 | 条件不合→空 | **検証済み** 単ROI~111%（360R alert BT） | ○ | **隣接レイヤー表示** | **P1** | V本体と分離済 |
| E | **SpurtIdx / 末脚指数** | `jockey_jv._spurt_index()` | SRA列 | float | runs不足→— | **検証済み** 14,702R | ○ | **アラート入力** | **P1** | |
| E | **33ラップ / lap33** | `core/lap33.py` | SRA列・value_scanner | fit mark | — | **検証済み** holdout2025（`verified_lap33_theory`） | × | **V未接続** | — | 別レイヤー |
| E | **venue_fav_note** | `core/blood_course.py` | 展開MAP caption | shift/z/flag | 1–3人気のみ | **検証済み** train21–24/holdout25（`verified_blood_course`） | ○ | **キャプション注記** | **P1** | 座標不可 |
| E | **danger_veto / vetos** | `core/danger_gate.py` | 軸警告・elim | reasons[] | — | 66R ledger warn-only | ○ | **合議/消去（V外）** | P1 | |
| E | **展開恩恵 deploy_bonus** | ~~trio_engine~~ | **撤去済** | — | — | **不採用** priced-in | × | **禁止** | 禁止 | |
| E | **combo / arare signals** | `consensus_view`, scanner | 荒れ・6シグナル | count 0–6 | — | **一部検証**（`verified_arare_signal_check`） | × | **V未接続** | — | |

---

## 検証スクリプト索引（V/展開関連）

| スクリプト | 層 | 内容 | 標本 |
|------------|-----|------|------|
| `scripts/vmatrix_pos4_align_check.py` | A | pos4 vs ten V-band | 2756R holdout≥20240101 |
| `scripts/vmatrix_pos_backtest.py` | A | ten vs ten_speed Y予測 | 2023–25 ~10,587R |
| `scripts/tenkai_bias_backtest.py` | B | empirical bias + V買い | 大標本 |
| `scripts/intraday_bias_backtest.py` | B | emp bias holdout | 未確認（要参照） |
| `scripts/deploy_filter_backtest.py` | C | 展開恩恵zone | 121R+ |
| `scripts/pace_predict_backtest.py` | C | ten_speed pace | 22,721R |
| `scripts/vmatrix_pace_holdout_check.py` | C | A ctx.pace vs B pint（V副作用） | 14,764R |
| `scripts/tenkai_alert_backtest.py` | E | 展開妙味→否定/末脚置換 | 360R |
| `scripts/layout_effect_backtest.py` | D | コースlayout | 未確認 |
| `scripts/spurt_index_backtest.py` | E | 末脚 | 14,702R |
| `scripts/dirt_blueprint_backtest.py` | B | ダート枠 | 176,723R |
| `tests/test_vmatrix_pos4.py` | A | 契約テスト | 単体 |
| `tests/smoke.py` | A | resolve_v_pos | 契約 |

---

## 改修候補 — 優先度区分

### P0：既に採用済み・変更不要

- pos4 → V縦座標（`resolve_v_pos` 経由）
- ten / score → 欠損フォールバックのみ
- predict_finish → ≫補助のみ（`finish_push_delta`）
- sashikiri y加算廃止
- 赤枠 `_V_COL` × `_V_ROW` + baba/pace radio
- empirical_bias → baba auto init
- build_pace_context.pace → pace auto init
- V該当の買いシグナル化禁止（caption明記済）

### P1：次フェーズ — V周辺注記の統一（**推奨・表示のみ**）

**方針：** Vを「予想エンジン」ではなく「展開可視化レイヤー」として完成。本体ロジック・赤枠・座標・買い目は**一切変更しない**。

```text
┌─────────────────────────┐
│      Vエリア MAP         │  ← 位置・有利度（pos4 / 馬場×ctx.pace / ≫）
│  ● = pos4  ≫ = finish   │
└─────────────────────────┘
6番 🔥末脚妙味  /  2番 ⚠危険人気  /  5番 ◆ダート枠  ← 補助注記（加点なし）
```

| 注記 | 既存ソース | 現状 | P1でやること |
|------|-----------|------|--------------|
| 🔥 末脚妙味 | `app.py` 末脚アラート + `profiles['agari']` | V**下**にリスト | 馬番単位でV近傍に統一表示 |
| ⚠ 危険人気 | `track_bias.danger_popular_inner()` | エビデンス表 | V近傍注記へ |
| ◆ ダート枠 | `track_bias.dirt_draw_signal()` | エビデンス/Scanner | V近傍注記へ |
| 🏟 venue_fav | `blood_course.venue_fav_note()` | 展開MAP caption | V近傍またはMAP下に統一 |

- Vキャプション・軸ラベル（pos4/≫）— **一部実施済**
- **禁止：** 注記をV座標・V該当判定・合議/買いへ接続しない

### P2：既存データだが holdout 検証が必要

- ~~ten_speed → V ペース行~~ → **Phase 2-1 で現行維持確定**（`repo/vmatrix_pace_holdout.md`）。G層#9参照
- nichi_bias → baba auto init 強化
- course_empirical_bias / bias_dashboard σ
- コース形状（1角/直線/大箱小回り）
- クッション値・含水率（血統エビデンスはあるが**赤枠投入は未検証**）
- 頭数・距離をV coordsへ（現状未使用）

### P3：新規合成モデル — 後回し

- 連続V Advantage スコア
- ペース確率化（Slow 25% / Mid 55% 等）
- 9マスの連続スコア化 / 確率分散
- nige_rate/senko_rate の新規blend
- netkeiba AI 4角の pos4 融合

### 禁止：採用しない

- V該当馬への加点・Rank/VH/戦闘力/人気のV coords混入
- V×人気薄の穴馬化
- PCI（全用途でV関連終了）
- ten_speed による馬の縦座標
- **predict_pace_intensity / ten_speed による V ペース行の単独差し替え**（展開マップと体系不一致）
- predict_finish をY座標に
- **末脚/危険人気等を V 加点・座標へ混ぜる**
- 展開恩恵 deploy_bonus / 好位妙味フィルター（撤去済）
- wind / comeback をBet信号に
- 未検証 cushion/moisture/形状の赤枠数値化

---

## 現行Vデータフロー（参照）

```text
SRA horses + jockey/trainer
  → fetch_jv_profiles (ten, ten_speed, agari, kyaku_pos, …)
  → build_pace_context → pos4, pace, leader, front_ratio
  → predict_finish(pos4 + kick/apt/power/pop) → finish
  → build_v_matrix(pos4, finish)
       Y = resolve_v_pos(pos4 → ten → score)
       X = 0.65×gate + 0.35×pos
       赤枠 = _V_COL[baba] × _V_ROW[pace]  ← empirical_bias / ctx.pace
       ≫  = finish_push_delta (pos4基準のみ)
```

---

## 調査メタ

- 棚卸し：2026-09-07
- Phase 2-1 pace holdout：2026-09-07 → **現行維持**（`repo/vmatrix_pace_holdout.md`）
- 次推奨：**P1 V周辺注記統一**（表示のみ）
- pos4 align：`repo/analysis/vmatrix_pos4_align/summary.json`（2756R）
- pace A/B：`repo/analysis/vmatrix_pace_holdout/summary.json`（14764R）
