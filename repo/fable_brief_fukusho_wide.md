# Fable案件③ 複勝/ワイド EV最適化 — 買い方研究で初の+EVを深掘りする

> このファイルをそのままFableに渡してよい。Fableはコールドスタート前提なので、下の
> 「共通コンテキスト」を必ず最初に読み込むこと。

---

## 依頼（背景と狙い）
買い方研究をずっと3連単で行っていたが、実配当ROIは全帯で控除率floor(75%)は超えるものの**利益(100%)には届かない**
（市場効率的・verified_formation_roi）。原因が判明した: **我々の検証済みエッジ(末脚/combo/荒れ)は全て
『3着内率』の話で人気薄に集中しており、3連単(勝ち"順序"=市場が最も賢い券種)とはミスマッチ**だった。

3着内エッジに正しく対応する券種＝**複勝/ワイド**。しかも複勝/ワイドの投票プールは単勝/3連単より資金が薄い＝
**市場効率が低い(歪みが残る)**。そこで試したら——**買い方研究で初めて統計的に+EVな結果**が出た。

これは利益化の本命筋。**この複勝/ワイドのエッジを、長い履歴・ワイド・オッズ帯まで広げて厳密に検証し、
"実運用できる複勝/ワイド選択ルール"に仕上げること**が本案件のゴール。

## 現状（速攻検証で判明した+EV・ここが出発点）
`scripts/fukusho_combo_backtest.py`（payouts複勝実配当・網羅率99.9%・bootstrap 90%CI・**2024-2026のみ**）:

| 人気薄(6番人気以下) | 複勝ROI中央 | 90%CI | 判定 |
|---|---|---|---|
| 全体(基準) | 65.9% | — | -EV(市場は人気薄を過剰にfade) |
| combo≥2 | 86.0% | [82.7, 89.7] | floor超だが-EV |
| combo≥3 | 103.4% | [96.8, 110.5] | 損益分岐±(2025は+有意/2024・2026は跨ぐ) |
| **combo≥4** | **123.5%** | **[109.8, 138.2]** | **★★統計的に+EV(CI下限>100%)** |

- combo = 荒れ予報6シグナル(🔵補正T/🧬血統上位/🧬血統回収100%+/🔥末脚/⚡33ラップ/👑騎手力 のレース内同時発火数)。
- メカニズム(健全): 複勝ROIがcomboで単調上昇(combo0=42%→4=125%)。市場は人気薄を平均的に過剰fade(基準66%)するが、
  **comboが『死んだ人気薄』と『過小評価の生きた人気薄』を判別**=後者が複勝で+EV。3連単の壁と別物。
- **最大の限界**: comboはCSV(horse_races.csv)で**2024年以降のみ**付与(vh2_combo_cache由来)＝2.5年しかない。
  combo≥4は少量(n=1321)。**長い履歴での再確認が必須**（これがタスク①）。

## ゴール（成功条件）
1. **combo≥4/≥3の複勝+EVが、2016年以降の長い履歴でも堅いか**をbootstrap CI＋年別で確認（in/out-of-sample分離）。
2. **ワイド**（複勝より更に非効率＝もっと+EVの可能性）で、combo馬絡みの買い目が+EVか。
3. **複勝オッズ帯の最適化**（どのオッズ帯で+EVが最大化するか）。
4. combo以外の3着内エッジ(末脚/補正T/血統・単体/連続量)も複勝EVで再評価し、**最強の複勝選択ルール**を1本にまとめる。
5. **利益化を主張できるライン**を正直に確定（CI下限>100%が複数年・out-of-sampleで維持されるか）。

## タスク詳細
1. **combo履歴の拡張(最重要)**: comboを2016年以降の全レースで**leak-freeに再計算**（各レース時点`before_key`以前の履歴のみ）。
   機構は既存の `scripts/revival_backtest.py` / `scripts/value_longshot_research.py` が持つ（補正T=corrected_time / 末脚=
   ato3f順位のrolling / 血統=bloodline / 33=lap33 / 騎手=jockey_power のレース内top3を数える）。これを複勝配当に結合。
2. **複勝+EVの厳密検証**: 人気薄6+×combo≥3/≥4 の複勝ROIをbootstrap 90%CI。train(≤2023)/holdout(2024-25)/直近で分離し、
   holdoutでもCI下限>100%が出るか。combo=4の少量問題は長期で緩和されるはず。
3. **ワイド検証**: payoutsのワイド実配当(combo=2頭・4桁)で、(a) combo馬×combo馬、(b) combo馬×人気馬(1-4)、
   (c) combo馬の全ワイド の各ROIをbootstrap。人気2+穴1=49.9%(検証済)を踏まえると combo馬×人気馬 が本線候補。
4. **オッズ帯最適化**: 複勝はodds表(bet_type='place')の事前オッズ or win_oddsから複勝妙味を推定。combo×複勝オッズ帯で
   +EVが最大/最小になる帯を特定(単複乖離=単長い複短い の既検証エッジとも接続)。
5. **他エッジの複勝EV再評価**: 末脚指数top/補正Ttop/血統top を単体・連続量で複勝EV評価し、comboと重ねて最強ルール化。
6. **実装提案**: value_hunter/穴馬ハンターの妙味馬(combo≥2〜)を『**複勝の買い目**』として提案する配線案
   (3連単でなく)。combo≥4=厚張り/combo≥3=標準/combo≥2=様子見、等の閾値と資金配分(ケリー)。

## 制約・作法（厳守）
- **リーク厳禁**: combo等は各レース`before_key`以前の履歴のみ(kyakushitsu=結果脚質/当該レース通過順は不使用)。
- **配当は実データ**: payouts表(複勝/ワイド/馬連…網羅率99.9%)。架空odds推定は使わない(ROIは実払戻で)。
- **3連単の轍を踏まない**: 3連単は分散巨大で単年小標本の>100%は変動の幻だった。**必ずbootstrap 90%CI＋年別＋
  train/holdout分離**で「CI下限>100%が複数年維持」を利益化の条件に。¥200k capの頑健版も併記。
- **正直さ(有料販売想定)**: +EVは本物なら本物、変動なら変動と峻別。「複勝は市場効率が低いから歪みが残る」という
  メカニズムが崩れる帯(効率的な帯)も明示。combo≥2(-EV)を+EVと混同しない。
- verify-first。効かない仮説は打ち切って正直に報告(PCI/風/3連単の打ち切り前例あり)。

## 成果物
1. `scripts/fukusho_wide_ev.py`（combo履歴拡張＋複勝/ワイドEVをbootstrap CI・train/holdout・オッズ帯別で出力）。
2. 最強の複勝/ワイド選択ルール（閾値・オッズ帯・エッジ合成）と、各の+EV有意性(CI下限)・年別安定性。
3. 配線提案（value_hunter/穴馬ハンター→複勝買い目・combo別の資金配分）。または「+EVは維持されない」の正直な結論。

---

## 共通コンテキスト（Fableは必ず読む）
- **アプリ**: 競馬分析Streamlit（`app.py`・約13,000行）。Python 3.13 / Windows / UTF-8。verify-first哲学。
- **DB**: `data/jravan.db`（SQLite・JRA-VAN実データ）。パス=`core/jockey_jv.JV_DB_PATH`。**凍結**(最新race_key=2026-06-21)。
  - `results(race_key, umaban, ketto_num, chakujun, ninki, win_odds, futan, bataiju, zogen, age, jockey_name,
    trainer_code, kyakushitsu(結果脚質=リーク源), ato3f, corner1..4 ...)`
  - `races(race_key, year, monthday, jyo, hasso_time, kyori, surface, tenko, baba_shiba, baba_dirt, shusso_tosu,
    juryo(1=ハンデ), kigo(牝限定=kigo[1]='2') ...)`
  - `horses(ketto_num, sire, bms ...)`
  - **`payouts(race_key, race_id, bet_type, combo, payout, pop)`** ★本案件の核。bet_type∈{単勝,複勝,枠連,馬連,ワイド,
    馬単,3連複,3連単}。payout=100円あたりの払戻。combo表記: 複勝='06'(単馬番2桁)/ワイド='0203'(2頭4桁)/
    馬連='0208'/3連単='120304'(3頭6桁・着順)。網羅率99.9%。
  - **`odds(race_key, bet_type, combo, odds, ninki)`** bet_type∈{win,place,quinella,exacta,trio,wide,bracket_q}=事前オッズ(77M行)。
- **CSV特徴ストア(高速化)**: `data/export/horse_races.csv`(25万行×53列・全leak-freeシグナル計算済・**combo/vh2は2024+のみ**)
  + `races.csv`。ローダー=`scripts/csv_data.py`(load_horses/load_races/標準分割train≤2024/holdout2025/recent≥20260321)。
  DB再計算(分)をCSV(秒)に置換。ただし**combo履歴拡張(2016-2023)はCSVに無いのでDBからleak-free再計算が必要**。
- **既存の検証済みエッジ(3着内型・人気薄)**: 末脚指数(人気薄6+×末脚top3・verified_spurt_index)、combo(荒れ6シグナル・
  verified_arare_signal_check)、単複乖離(単≥10×複≤3で勝率2.5→7%・value_scanner)、ダート枠順(track_bias)。
  関連モジュール: corrected_time/bloodline/lap33/jockey_jv/elim_cross/value_scanner。
- **参考スクリプト**: `scripts/fukusho_combo_backtest.py`(本案件の元・複勝combo検証)、`scripts/revival_backtest.py`と
  `scripts/value_longshot_research.py`(leak-freeなcombo/シグナル再計算の機構=combo履歴拡張に流用)、
  `scripts/formation_backtest.py`(3連単・bootstrap CIの作法)。
- **重要な文脈**: 3連単は市場効率で利益化不能だった(buy-methodは損失縮小止まり)。複勝/ワイドは**プールが薄く歪みが残る
  唯一の+EV候補**。ここが利益化の本丸。本物Rank(純LTR)/更なる3連単絞りは壁で優先度低=やらない。
