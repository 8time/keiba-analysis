# Composer案件 的中率プランv2 新提案 N1〜N6 実装指示書

> このファイルをそのまま Composer に渡してよい。コールドスタート前提なので、
> 末尾の「共通コンテキスト」「禁止事項」「落とし穴」を最初に読むこと。
> **ステップA→B→C→Dの順に進め、各ステップの成果物をユーザーに見せて承認を得てから次へ。**
> 本番の既定買い目（D=人気1-2×3-4の3連複2点 / C=Rule B / BA=見送り）は**この案件では一切変えない**。

---

## 依頼の背景（人間の意図）
「的中率を上げる28案」を厳格監査した結果、多くが「投資額の増加を無視」「別戦略の数字を流用」
「券種の誤記」で落ちた。生き残った考え方を実装可能な形にしたのが N1〜N6。

- N1: 同点数・ROI下限つきで「的中率最大」の形を探す（オフライン）
- N2: C の 3連単2-4-7 を 3連複化したときの的中増分を着順データだけで数える（オフライン）
- N3: レース選択ゲートを「現行の券」に掛け直す（オフライン）
- N4: 「当たり優先」を予算固定で定義し、成績表示に損失/100円などを追加（表示のみ）
- N5: データ欠損による見送りを理由コードで記録・集計する（記録のみ・挙動不変）
- N6: 消去該当のRank7位をRank8位へ入れ替える案をペア検定で判定（オフライン）

## 大原則
1. **新しい予測エッジを作らない。** 既存の順位（人気・ability_score・vh2_score）と既存の券の組み方だけで比較する。
2. **本番の挙動を変えるのは N4/N5 の「キー追加・表示追加」だけ。** 券の中身・点数・見送り判定は不変。
3. **的中率は必ず「投資/レース」「損失/100円（=100−ROI）」「投資/1的中」「最大連敗」と併記。** 的中率単独の表は出力しない。
4. **train/holdout を固定。** train = day ≤ 20231231 / holdout = day ≥ 20240101（LTR/ability_score の学習が≤2023なので、2024以降だけが学習期間外）。
5. 「効く」と書くのは holdout で確認したときだけ。train で選んで holdout で評価、順位が入れ替わる候補は「不採用」と書く。
6. UIに出す言葉は平易に（`plain-label-check` 方針）。「Wilson」「McNemar」「ROI」を説明なしで出さない。

---

## ステップA（本番側・追加のみ）: N5 → N4

### N5. 欠損を「見送り理由」として数える

#### 目的
現在 `core/playbook_tickets.build_tickets` は見送り理由を `warning` 文字列でしか持たず、
「荒れで見送った」と「データが無くて券を組めなかった」が区別できない。
また VH/Projected が無いとき `cross_n` を暗黙に 0 にして C を3連単へ流している
（`core/playbook_tickets.py` 227–231行）。**この挙動は今回変えない**が、起きた事実を記録する。

#### 成果物
1. `core/playbook_tickets.py`
   - `build_tickets` の戻り `rec` に以下のキーを**追加**（既存キーの値・順序・シグネチャは不変）:
     - `skip_reason`: `None` | `'zone_ba'` | `'no_horses'` | `'ninki_missing'` | `'ltr_insufficient'`
     - `skip_detail`: 補足（例 `'missing ninki: [4]'`、`'ltr order 5 < 7'`）。無ければ `None`
     - `cross_n_source`: `'given'`（引数で渡された）| `'computed'`（vh+proj から算出）| `'unavailable'`（どちらも無く 0 を代入した）
     - `degraded`: `cross_n_source == 'unavailable'` かつ zone が `'C'` のとき `True`、それ以外 `False`
   - `_umaban_at_pop` で人気1〜4が揃わない場合、どの人気が欠けたか/重複したかを `skip_detail` に入れる
     （例: 人気3が2頭・人気4が0頭 → `'dup ninki: [3], missing ninki: [4]'`）。
   - `snapshot_payload` の `meta` に上記4キーを追加。
2. `core/newspaper.py` `persist_playbook` の `extra` dict に同4キーを追加（他は触らない）。
3. `core/playbook_ledger.py`
   - `entry_from_blob` の戻り row に `skip_reason`, `degraded` を追加。
   - `summarize` の戻りに `'skips_by_reason': {reason: count}` と `'degraded_n': int` を追加。
     既存キー（`D/C/BA/ALL`）は不変。
4. `pages/playbook_log.py`
   - B/A のキャプションの下に「見送りの内訳」を小さく表示。ラベルは平易に:
     - `zone_ba` → 「荒れそうなので見送り」
     - `ninki_missing` → 「人気1〜4番が取れなかった」
     - `ltr_insufficient` → 「能力順（検証AI）が足りなかった」
     - `no_horses` → 「出走表が無かった」
   - `degraded_n > 0` のとき「穴データが無いまま3連単を組んだレース: N件（今後の見直し対象）」を1行。
5. `scripts/skip_reason_audit.py`（新規・オフライン）
   - (a) `data/newspaper/*.bets.json` を `playbook_ledger.list_entries()` で読み、`skip_reason` 別・`degraded` 件数を印字。
   - (b) `data/export/horse_races.csv`（`scripts/csv_data.load_horses`）で、
     妙味度 D ゾーン相当のレースのうち **ninki 1〜4 が4頭ちょうど揃わない**レースの件数と割合を印字
     （同人気で順位が飛ぶケースの実測頻度）。vscore は `races.csv` の `vscore` 列、
     無ければ `core.value_scanner.race_value_score` で代用（`scripts/trifecta_formation_phase3.build_races` と同じ手順）。
   - 結果を `repo/memory/verified_skip_reason_audit.md` に書く（他の verified_*.md と同じ先頭 front-matter 形式）。

#### テスト（`tests/smoke.py` に追加）
- `build_tickets('R', 80, hs, None, ltr)` → `skip_reason == 'zone_ba'`
- 人気3が2頭・人気4が無い `hs` で D → `skip` かつ `skip_reason == 'ninki_missing'`、`skip_detail` に `4` を含む
- `build_tickets('R', 55, hs, None, ltr)`（vh/proj 無し）→ 券は従来どおり30点、`cross_n_source == 'unavailable'`、`degraded is True`
- `build_tickets('R', 55, hs, None, ltr, cross_n=2)` → `cross_n_source == 'given'`、`degraded is False`
- `persist_playbook` → `load_bets` で `extra['skip_reason']` が往復すること
- 既存 `tests/test_bettype_selector.py` と `tests/smoke.py` の全件が引き続き通ること

#### 合格条件
既存テスト全通過。券の内容・点数・skip 判定の真偽は1件も変わらない（差分は追加キーのみ）。

---

### N4. 「当たり優先」を予算固定で定義し、表示に反映する

#### 目的
「4点は2点の2倍の投資」問題は、**1レースの予算を固定**すれば
「400円を2点×200円で買うか、4点×100円で買うか」の比較になり、差は「損失/100円」と「的中率」だけになる。
この定義を成績表示に埋め込む。**モードの実装（券を変える）は今回やらない。**

#### 成果物
1. `core/bayes_stats.py` に追加（既存関数は不変）:
   ```python
   def wilson_interval(k, n, z=1.96):
       """Wilsonスコア区間 (lower, upper)。n=0 は (None, None)。標準mathのみ。"""
   ```
2. `core/playbook_ledger.py` `_zone_stats` の戻りに追加（既存キー不変）:
   - `loss_per_100`: `100 - roi`（roi が None なら None）
   - `cost_per_hit`: `investment / n_hit`（n_hit=0 なら None）
   - `hit_rate_lo`, `hit_rate_hi`: `wilson_interval(n_hit, n_settled)` を %表記（n_settled<1 なら None）
   - `max_losing_streak`: 精算済みを `race_date, race_id` 昇順に並べた連敗最大
   - `avg_investment`: `investment / n_settled`
   `summarize` に `'purchase_rate'`: 買ったレース数 ÷（買った＋見送り）を % で追加。
3. `pages/playbook_log.py` `_metric_box` を拡張（引数追加は末尾にデフォルト付きで）:
   - 「的中率 23.5%（確定30R・統計的なぶれ幅 12〜40%）」の形で Wilson 区間を併記。
     `n_settled < 30` のときは数値の代わりに「集計中（確定◯R・30Rで表示）」。
   - 「100円賭けるごとに平均◯円減る」（=loss_per_100）
   - 「1回当たるまでに平均◯円」（=cost_per_hit）
   - 「最長で◯回連続はずれ」（=max_losing_streak）
   - 上部キャプションに「買ったレースの割合 ◯%（見送りを含めた全レース比）」（=purchase_rate）
4. `repo/hitrate_mode_spec.md`（新規・仕様書のみ・コード無し）:
   - 「当たり優先モード」の定義: ゾーンごとに **1レース予算を固定**（D: 400円 / C: 3,000円）し、
     予算内で「ROI下限（既定85%）を満たす検証済み候補のうち的中率最大」の買い方を選ぶ。
   - 候補は `scripts/hitrate_menu_backtest.py`（ステップB）の出力から人手で確定する。
   - UI文言案: 「当たる回数は増えますが、当たったときの払戻は小さくなります。1レースに使う金額は同じです。」
   - **実装はこの案件の範囲外**と明記。

#### テスト
- `wilson_interval(7, 30)` の lower が 0.10〜0.13、upper が 0.40〜0.43。`wilson_interval(0, 0) == (None, None)`。
- `summarize` の各ゾーンに新キーが存在し、`n_settled == 0` のとき None で落ちないこと。
- 連敗計算: hit 列 `[1,0,0,0,1,0]` → 3。

#### 合格条件
📒プレイブック成績ページのスクリーンショット（またはテキスト）を提示。既存の的中率・回収率の値は変わらない。

**承認ゲートA**: N5/N4 の差分とテスト結果を提示 → 承認後にステップBへ。

---

## ステップB（オフライン・共通基盤）: 共通モジュール → N2 → N1

### 共通モジュール `scripts/hitrate_common.py`（新規）
以後の N1/N2/N3/N6 はすべてこれを使う。**ライブ側からは import しない。**

```python
TRAIN_END = 20231231
HOLDOUT_FROM = 20240101
UNIT = 100
MIN_HORSES = 8
ROI_FLOOR_DEFAULT = 85.0

def load_payouts(bet_type) -> dict[str, list[tuple[tuple[int,int,int], float]]]
    # jravan.db payouts。bet_type は '3連複' or '3連単'。3連複は tuple(sorted)。
    # scripts/trifecta_formation_phase3.load_payouts と同じ SQL。race_key は str。

def build_races(zones=('D','C')) -> list[dict]
    # scripts/trifecta_formation_phase3.build_races を全ゾーン対応にしたもの。
    # 各 dict: rk, day, year, period('train'/'holdout'/None), zone, vscore, cross_n,
    #   ninki_ord, rank_ord(ability_score 昇順), vh_ord(vh2_score 降順),
    #   ninki_map{umaban:ninki}, elim_map{umaban:elim_n}, top3(着順1-3の馬番 tuple),
    #   n_horses, gate 特徴(races.csv の mean_elim, n_elim3, odds_entropy, field_size, is_handi1)
    # chakujun が NaN/0 の馬は着順から除く。top3 が3頭揃わないレースは捨てる。
    # 2024-01-01 より前で period None になるものは無い（train/holdout の二値）。

def live_tickets(race, playbook_id) -> (kind, set_of_tickets)
    # 本番と同じ組み方を core.trio_engine.build_formation / build_trifecta_formation で再現:
    #  'd_ninki_trio_2'      : ninki1,2 固定 × ninki3 / ninki4 → 3連複2点
    #  'c_ltr_trio_236'      : rank 上位2 × 上位3 × 上位6 → 3連複
    #  'c_ltr_trifecta_247'  : rank 上位2 × 上位4 × 上位7 → 3連単
    # ninki1-4 が揃わない/rank が足りないときは (kind, set()) を返す（=見送り）。

def rule_b_playbook(race) -> playbook_id
    # zone D → d_ninki_trio_2 / zone C & cross_n>=3 → c_ltr_trio_236 / zone C & cross_n<3 → c_ltr_trifecta_247

def score(tickets, kind, payouts_for_race) -> dict(cost, ret, hit, tc)
def summarise(recs) -> dict(n, hits, hit_rate, roi, loss_per_100, cost_per_hit,
                            avg_pts, max_losing_streak, year_roi, year_hit, recs)
def block_ci_roi(recs, n_boot=2000, seed=42) -> (lo, hi)   # day 単位ブロック bootstrap
def wilson(k, n) -> (lo, hi)                                # core.bayes_stats.wilson_interval を呼ぶ
def mcnemar(base_hits, test_hits) -> dict(b, c, z, p)       # 標準mathのみ。b=baseのみ的中, c=testのみ的中
def write_memo(path, title, description, sections: list[str])  # verified_*.md 形式
```

- 点数は必ず `len(tickets)` で数える（棚卸し表の「~30」などのラベル値を使わない）。
- 出力表は常に列: `候補 | 券種 | 点 | n | 的中率 | ROI | 損失/100円 | 投資/1的中 | 最大連敗 | ROI 95%CI | 年別`。

### N2. 3連単→3連複化の的中増分を数える

#### 目的
同じ7頭・同じ入れ子で 3連単2-4-7（30点）を 3連複2-4-7（19点）にすると、
3連単が当たったレースは必ず当たる。増分＝「3頭は網に入ったが順序が違ったレース」で、
配当を引く前に着順だけで数えられる。

#### 成果物 `scripts/trio_conversion_backtest.py`
- 対象セル: zone C & cross_n < 3（現行 RRR セル）。train/holdout 別に出す。
- 各レースで `tri = live_tickets(race,'c_ltr_trifecta_247')`, `trio = build_formation(rank[:2], rank[:4], rank[:7])`。
- **assert**: 3連単が的中したレース集合 ⊆ 3連複が的中したレース集合（1件でも破れたら停止して原因を印字）。
- 出力: 両者の n・的中率・増分レース数・ROI（3連複は '3連複' 配当で採点）・損失/100円・投資/1的中・最大連敗・CI・年別。
- 参考として同セルで `c_ltr_trio_236`（7点）も並べる（Rule B の cross_n≥3 セルの券をこのセルに当てた場合）。
- 結論の書き方（自動生成・数値埋め込み）:
  「3連複化で的中は X%→Y%（+Zpp、増分 N レース）。ROI は A%→B%。損失/100円は a→b。
   ROI下限85%を満たす: はい/いいえ」。**「採用」とは書かない**（判断は人）。
- メモ出力: `repo/memory/verified_trio_conversion.md`

#### テスト
- 合成データ（8頭・順位固定・着順を与える）で「3連単的中 ⇒ 3連複的中」が成り立ち、逆は成り立たないケースを1件ずつ。
- `len(build_formation(r[:2], r[:4], r[:7])) == 19` を確認（7頭以上・重複なし）。

### N1. 同点数・ROI下限つきで「的中率最大」の形を探す

#### 目的
`trifecta_formation_phase3.py` の形探索は ROI 最大で 2-4-7 を選んだ。目的が的中率なら、
**点数上限と ROI 下限を制約にして的中率を最大化**する探索を別に行う。
現行の捕捉率は 1着 Rank top2=29% / 2着 top4=42% / 3着 top7=67% で、最も狭いのは1着列。

#### 成果物 `scripts/hitrate_shape_search.py`
- 引数: `--zone {D,C}` `--cell {trifecta,trio_c,d}` `--max-points N` `--roi-floor 85`（既定値は各セルの現行点数と85）。
- セルと探索空間:
  - `C & cross_n<3`（現行 3連単2-4-7・30点）: 券種 ∈ {3連単, 3連複}、a∈1..4, b∈a..6, c∈b..9、順位は Rank。
  - `C & cross_n>=3`（現行 3連複2-3-6・7点）: 券種 3連複、a∈1..3, b∈a..5, c∈b..8、順位は Rank。
  - `D`（現行 3連複2点）: 券種 3連複、軸は人気1・2固定、3頭目候補を {人気3..k (k=3..6)} ∪ {VH穴 上位 m (m=0..2, ninki≥6)} で列挙。`--max-points` 既定 4。
- 手順:
  1. train で全候補を評価し、`avg_pts ≤ max_points` かつ `roi_train ≥ roi_floor` を満たすものを的中率降順に並べる（上位10を印字）。
  2. その上位10を holdout で固定評価。holdout でも `roi ≥ roi_floor` を満たし、かつ holdout 的中率が現行より高いものだけ「候補」。
  3. train 1位が holdout でも上位3位以内に入らなければ「順位不安定・不採用」と自動で書く。
  4. 現行（2-4-7 / 2-3-6 / D 2点）は必ず基準行として同じ表に出す。
- 出力: 表（共通列）+ 各候補の 1着/2着/3着 捕捉率 + `data/hitrate_shape_search_<cell>.csv` + `repo/memory/verified_hitrate_shape_search.md`。
- 結論欄には「ROI下限◯%・点数上限◯点で、holdout 的中率最大は …（現行比 +◯pp、損失/100円 ◯→◯）」のみ。**採用可否は書かない。**

#### テスト
- 合成8頭・着順固定で、(1,1,3) 3連複（=1点: 1-2-3）と (3,3,3) 3連複（=1点: 同じ）で点数が一致し、
  (2,3,4) の点数が `len(build_formation)` と一致すること。
- `--roi-floor 200` で候補が0件になり、例外を出さず「該当なし」と印字すること。

**承認ゲートB**: N2/N1 の出力表とメモを提示 → 承認後にステップCへ。

---

## ステップC（オフライン）: N3. ゲートを現行の券に掛け直す

#### 目的
`verified_race_gate_frontier.md` の「mean_elim 上位10%で的中35→39%」は
**3連複10点＋3連単30点を全レース同時購入する40点戦略**の数字で、現行 playbook の券には当てはまらない。
同じゲートを「現行の券（Rule B）」に掛けたとき、的中率が上がるかを直接測る。

#### 成果物 `scripts/gate_on_live_playbook.py`
- 対象: holdout（2024+）。ゾーン D / C を分けて評価（ゲートで D と C の比率が変わると混ざるため）。
- 券: `rule_b_playbook(race)` → `live_tickets`。見送り（券が組めない）レースは分母から除き、件数を報告。
- ゲート特徴（`races.csv`）: `mean_elim`, `n_elim3`, `odds_entropy`, `field_size`, `vscore`（ゾーン内での位置）。
  各特徴について **降順・昇順の両方向**で s ∈ {100, 50, 30, 20, 10, 5}% を評価（方向が事前に不明なため）。
- 出力（ゾーン×特徴×方向×s の表）: 共通列 + 「s=100 との ROI 95%CI 重なり: あり/なし」+ 購入率。
- 結論の自動文: 「的中率が s=100 より上がり、かつ ROI が下限◯%以上のセル: N 件（一覧）。CI が s=100 と重ならないもの: M 件」。
  該当0件ならその旨を書く。
- メモ出力: `repo/memory/verified_gate_on_live_playbook.md`

#### テスト
- `eval_subset` 相当の関数で、n=10・s=30% が 3 レースを選ぶこと（ceil）。
- 昇順・降順で選ばれる集合が s=100 のとき一致すること。

**承認ゲートC**: 表とメモを提示 → 承認後にステップDへ。

---

## ステップD（オフライン）: N6. 消去入替をペア検定で判定

#### 目的
「Rank7位が消去該当ならRank8位に入れ替える」案の根拠に使われた 93.1% は、
8番人気以下を中心に切った別母集団の精度で、この入替の根拠にならない。
**同一レースで入替前後の的中を比べる McNemar 検定**で判定する。

#### 成果物 `scripts/elim_swap_paired_test.py`
- 対象セル: `C & cross_n<3`（3連単2-4-7 の3着列 Rank7位）と `C & cross_n>=3`（3連複2-3-6 の3列目 Rank6位）。
- 消去該当の定義（`core/consensus_view.integrate` の cut しきい値に合わせる）:
  `elim_n ≥ 3 かつ ninki ≥ 6` または `elim_n ≥ 5 かつ ninki ≤ 5`。`elim_n` は `horse_races.csv` の列。
- 入替規則: 末列の最後の1頭（Rank7位 / Rank6位）が該当なら、Rank8位以降で**最初の非該当馬**と入れ替える（Rank10位まで探し、無ければ入替なし）。
  他の列は触らない。点数は原則同じ（重複で変わる場合は `len(tickets)` で実測）。
- 出力: train/holdout 別に、基準 vs 入替 の共通列 + 「入替が発生したレース数と割合」+ McNemar の b, c, z, p。
- 判定文（自動）: 「holdout: 入替のみ的中 c=◯ / 基準のみ的中 b=◯、z=◯。train も同符号: はい/いいえ。ROI 差 ◯pp」。
  **「z≥1.96 かつ train 同符号 かつ ROI 差 ≥ −2pp」を満たすかどうかだけを書き、採用可否は書かない。**
- メモ出力: `repo/memory/verified_elim_swap_paired.md`

#### テスト
- `mcnemar(base=[1,1,0,0,0], test=[1,0,1,1,0])` → b=1, c=2、z の符号が正。
- 入替規則: rank8 も該当なら rank9 を採る合成ケース、rank8..10 全部該当なら入替なしの合成ケース。

**承認ゲートD**: 表とメモを提示して完了報告。

---

## 共通コンテキスト（コールドスタート用）
- 環境: Python 3.13 / Streamlit / Windows / UTF-8（BOMなし）。スクリプト先頭で
  `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`（`scripts/trifecta_formation_phase3.py` と同じ）を必ず入れる。
- 本番の買い目パス:
  - `core/formation_stats.py` `zone_code(vscore)`: D 0≤v<50 / C 50≤v<70 / BA v≥70
  - `core/bettype_selector.py` `select(zone, cross_n)`: Rule B（D→3連複 / C&cross_n≥3→3連複 / C&cross_n<3→3連単 / BA→見送り）
  - `core/playbook_tickets.py` `build_tickets(...)`: 券の生成。D は人気固定・C は LTR（ライブは高いほど強い）
  - `core/newspaper.py` `persist_playbook` → `data/newspaper/{race_id}.bets.json` の `playbook` キー
  - `core/playbook_ledger.py` `settle` / `summarize`、`pages/playbook_log.py` が表示
  - app.py の呼び出し: 7402行付近と 9417行付近（`vh_scores=_vh_for_pb or None` なので、空 dict は None として渡る）
- オフライン研究データ:
  - `scripts/csv_data.py` → `data/export/horse_races.csv`（53列: race_key, day, umaban, ninki, win_odds, chakujun, top3, ability_score, vh2_score, elim_n, combo …）と `races.csv`（vscore, mean_elim, n_elim3, odds_entropy, field_size, is_handi1, kigo …）。
    無ければ `python scripts/export_features_csv.py`（約6分）。gitignore 対象。
  - 配当: `data/jravan.db` の `payouts`（`race_key` 文字列, `bet_type` '3連複'/'3連単', `combo` 6桁, `payout` 円）。接続は `core.jockey_jv.JV_DB_PATH` を read-only で。
  - 再利用できる既存コード: `scripts/trifecta_formation_phase3.py`（build_races, summarise, block_ci）、
    `scripts/rank_vs_ninki_legs.py`（D の軸除外順位の取り方）、`scripts/race_gate_frontier_backtest.py`（eval_subset, block_bootstrap_roi, max_losing_streak）、
    `scripts/vscore_zone_formation.py`（trio_tickets / trifecta_tickets）、`core/trio_engine.py`（build_formation / build_trifecta_formation）、`core/bayes_stats.py`（wilson_lower）。
- 検証済みの前提（覆さない）:
  - 全券種・全形で holdout ROI < 100%（控除の壁）。的中率とROIはトレードオフ。
  - D は人気、C は Rank が有利。荒れ（BA）は買わない。
  - LTR ≈ 人気（top7 捕捉 81.3% vs 81.7%）。新スコア・再学習・頭数分割は棄却済み。
- 記録先: `repo/memory/verified_*.md`（先頭に `---\nname:\ndescription:\nmetadata:\n  node_type: memory\n  type: project\n---` の front-matter）。

## 禁止事項
- 既存関数のシグネチャ変更（CLAUDE.md）。**戻り dict へのキー追加は可**。引数追加は末尾・デフォルト付きのみ。
- `requirements.txt` に無いライブラリの追加（統計は標準 `math` / `numpy` / `pandas` の範囲。scipy 禁止）。
- 本番の券・点数・見送り判定を変えること（N5 で `cross_n` 欠損時に見送りへ変える案は**今回は実装せず**、`degraded` を数えるだけ）。
- `scripts/*` を Streamlit（app.py / pages）から import すること（stdout 差し替えで壊れる）。
- 確定オッズを「買える時点の情報」として特徴量・フィルタに使うこと（時点リーク）。本案件はオッズを条件に使わない。
- メモや出力に「採用」「効く」「改善した」と書くこと。数値と判定条件の充足だけを書く。
- 新しい `.md` ドキュメント（README 等）を勝手に増やすこと。作るのは本指示書が指定したファイルのみ。

## 落とし穴（過去に踏んだもの）
1. CSV の `race_key` は pandas が int64 で読む。payouts は文字列。**必ず `astype(str)`**。
2. **`ability_score` は小さいほど強い**（昇順）。ライブ LTR は高いほど強い（降順）。取り違えると的中率が 1/10 になる。
3. 点数はラベルでなく `len(tickets)` で実測（`mid 3-5-7` は「36」と書かれていたが実測60点）。
4. `chakujun` に 0/NaN（取消・除外）が混ざる。着順ソート前に除く。
5. 3連複の的中判定は `tuple(sorted(...))` で正規化、3連単は順序そのまま。
6. holdout だけ良くて train で負ける候補は採らない（RRV 2-4-7 の前例: holdout 112% / train 82%）。
7. 見送りレースを分母から外すと的中率が上がって見える。購入率を必ず横に出す。
8. Windows の cp932 で日本語印字が落ちる。stdout の UTF-8 ラップを忘れない。

## 成果物一覧（チェックリスト）
- [ ] A: `core/playbook_tickets.py` / `core/newspaper.py` / `core/playbook_ledger.py` / `pages/playbook_log.py` / `core/bayes_stats.py` の追加キー・表示、`scripts/skip_reason_audit.py`、`repo/hitrate_mode_spec.md`、`repo/memory/verified_skip_reason_audit.md`、smoke 追加
- [ ] B: `scripts/hitrate_common.py`、`scripts/trio_conversion_backtest.py`、`scripts/hitrate_shape_search.py`、`repo/memory/verified_trio_conversion.md`、`repo/memory/verified_hitrate_shape_search.md`
- [ ] C: `scripts/gate_on_live_playbook.py`、`repo/memory/verified_gate_on_live_playbook.md`
- [ ] D: `scripts/elim_swap_paired_test.py`、`repo/memory/verified_elim_swap_paired.md`
- [ ] 各ステップ後: `python tests/smoke.py` と `python -m unittest tests.test_bettype_selector` が通ること
