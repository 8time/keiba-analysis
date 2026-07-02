# 地方競馬(NAR)対応プロジェクト ―― 新セッション用ブリーフ

このファイルをそのまま新セッションに貼る。目的は「地方(特に南関42-45)を中央と同等に扱える道具にする」。
根本原因は1つ ―― **地方データがjravan.dbに無い/薄い**。以下は今セッションで実査済みの事実。

---

## 0. 実査で判明した根本事実（新セッションは再調査不要）

- **jravan.dbの地方カバレッジが大幅遅延**: 大井(jyo=44)2026は monthday 0521 まで・**13レースのみ**。直近NARレース(例 202644070112, 202644063008/09)は**未取込(0件)**。
- **純地方馬はjravanに存在しない**: 例「ゴッドバーグ」は表記ゆれ含め**jravanに1走も無い** → アプリから見えない → 評価不能(強適/LTR/末脚/補正T/騎手成績すべて空)。
- **jravanはNAR結果を100万走持つ**(jyo 30-55・ketto_num/ninki/corner/ato3f/time付・オッズは全null)が、上記の通り**最近ぶんが欠落**＆**JV-Link未収録の純地方馬は最初から無い**。
- **nankankeiba.com ブリッジ**(`core/nankan_scraper.py`)が地方の唯一の万能ソース(純地方馬もカバー)。venue: 42浦和/43船橋/44大井/45川崎。`fetch_horse_history(horse_id)` あり。SRAはこのブリッジでPastRuns→PCI/末脚/展開を復旧している([[project_nankan_scraper]])。
- **jockey_pro One-Push** は `jockey_analyzer.analyze_race()` でライブscrape(jravan非依存)だが**JRA向け** → NARで騎手/厩舎/馬名が空/?。
- **jockey_pro「レース単位騎手指標」**(pages/jockey_pro.py:167〜)は jravanをrace_idで引く → NAR未取込レースで「未取り込みです」。
- **🧬血統適性**(app.py:2647)は blood_dict.db(JRA血統) → 純地方馬は父/母父が'-'・馬名が?(今セッションでNameフォールバックは追加済)。
- 既に地方で効いているもの(今セッション実装): 軸較正POP_FUKU_NAR(1番人気78.7%)/NAR専用LTRモデル(build_ltr_nar.py・人気+2.38pp)/🔬シグナル列のNAR会場スキャン/補正タイムはNAR転移(本命補強+5.84pp)/dirt_draw NARゲート。
- **地方の展開適合度/PCIの数値が弱い**のは、ブリッジのPastRunsが薄い馬が多いため(データ量問題)。

---

## 1. タスク（優先順）

### T1【最優先】nankanブリッジを「全出走馬の過去走を確実に取る」まで強化
- 目的: ゴッドバーグのような**JV-Linkゼロ馬**でも過去走を得て、末脚/補正T/展開/PCI/脚質を地方で機能させる。
- やること: SRAの地方処理で、出走各馬の nankankeiba horse_id を確実に解決 →`fetch_horse_history`でPastRunsを埋める。取れない馬のフォールバック(名前照合・ID総当たり `scripts/debug/nankan_id_bruteforce*.py`)を頑健化。
- 受け入れ: 直近の大井レース(未取込)を1本分析して、全馬(純地方馬含む)にPastRuns/末脚/補正Tが入る。
- 検証: 大井の既検証標本([[verified_nankan_pci_spurt_backtest]] 263R/3197頭)でリグレッションが無いこと。

### T2 jockey_pro One-Push のNARスクレイプ対応（元#3）
- `core/jockey_analyzer.py` の analyze_race を NAR(nar.netkeiba)ドメイン対応に。騎手/厩舎/馬名/オッズを南関で取得。
- 「レース単位騎手指標」(jravan依存)は、NAR未取込レースで**jravan騎手成績(過去はある)＋ライブ出走表**にフォールバック。
- 受け入れ: 大井レースでOne-Pushに騎手データ・馬名が出る(?でない)。

### T3 フェスティヴルディ等「順位が変」を再確認（元#4/#6）
- T1完了後、フェスティヴルディ(jravanにketto 2021106899で存在)や純地方馬の強適順位が妥当になるか確認。
- 受け入れ: 過去走が埋まった状態で、来た馬が極端に下位に沈まない(データ起因の誤評価が消える)。

### T4 展開MAP × netkeiba AI展開予測 の照合アイコン（新機能）
- netkeibaのshutubaページにある「AI展開予測」(4コーナー位置。**4コーナー〇をクリックで位置確定**する動的描画)をスクレイプ。
- 当アプリの展開MAP(直線=到達位置)と**同じ位置の馬**にアイコン: 有利位置一致=🏆 / 危険位置一致=💀。
- 帯: **前40% / 後35%**(ユーザー指定)。両者(netkeiba 4コーナー vs アプリ 直線)が同帯なら点灯。
- 注意: netkeiba側の位置データは動的(クリック後)なので、埋め込みJSON/APIエンドポイントを探す(HTMLの静的パースでは出ない可能性大)。
- 位置づけ: **表示のみ・エッジ主張なし**(展開恩恵はpriced-in [[verified_tenkai_priced_in]])。「AI同士の合意点」の可視化。

### T5 地方シグナル列・展開適合度の最終確認
- 🔬シグナル列(J◎/T●)は会場スキャン済だが、scrape_raceがNAR shutubaで騎手/厩舎を取れているか確認(T1/T2と連動)。
- 展開適合度の数値はT1(PastRuns充足)で改善するはず。改善後に地方で妥当か確認。

---

## 2. 関連ファイル・関数マップ

| 対象 | 場所 |
|---|---|
| NARブリッジ本体 | `core/nankan_scraper.py`(fetch_horse_history/compute_spurt_index/runs_to_pastruns) |
| SRAのNAR処理(PastRunsブリッジ) | app.py 2057〜(「NAR(南関東)補完」) |
| One-Push | `pages/jockey_pro.py`(render・analyze_race呼び出し 358) |
| ライブ集計 | `core/jockey_analyzer.py`(analyze_race・NARドメイン化が要) |
| レース単位騎手指標(jravan) | pages/jockey_pro.py 167〜 |
| 血統適性 | app.py 2647・`core/bloodline.py`・data/blood_dict.db(JRA血統) |
| 展開MAP | `core/pace_map.py`(build_pace_context/estimate_pace_map) |
| シグナル列スキャン | app.py `_fetch_daily_signals`(184・NAR会場対応済) |
| NAR会場コード | 42浦和/43船橋/44大井/45川崎。他NAR=30/35/36/47/48/50/51/54/55 |
| NAR軸/LTR/補正T(実装済) | axis_selector.POP_FUKU_NAR / scripts/build_ltr_nar.py / ltr_ranker._load_nar |

---

## 3. 規約・防護柵（厳守）

- Python3.13/Streamlit/Windows・**UTF-8(BOMなし)**。既存関数シグネチャは変えず**追加関数で**。requirements.txt外のライブラリ禁止。
- **スクレイピングは `core/scraper.py: fetch_robust_html`**(requests直はボット検知)。地方は `nar.netkeiba.com`。アクセス配慮(0.5s間隔・キャッシュ・resume。前例=scripts/kawasaki_backtest_phase2.py)。
- **検証優先**: エッジ主張は必ず jravan.db holdout(2025)で複勝残差z or recall@7 val+test両改善。**結果リーク禁止**(kyakushitsu/通過順/上がり順位は事後情報)。ただしT1〜T4は多くが**表示/データ補完**でエッジ主張なし(展開/シグナルはpriced-in既確定)。
- 変更後 `python tests/smoke.py`(終了コード0)・`FEATURE_STATUS.md`更新。まず新規ファイル、既存への配線は最小diff・1コミットで戻せる形。
- **却下済み(再提案しない)**: 展開恩恵/ペース圧力の荒れ予測(⑧と重複)/PCI/馬主/当日バイアスz-3.8/Glicko等 = すべてpriced-in。地方作業は「エッジ発掘」でなく「地方を中央と同じ土俵に乗せるデータ補完＋表示」が本質。

---

## 4. 進め方の推奨

**T1(ブリッジ強化)が全ての土台**。これが出来ればT3(順位)・T5(展開適合度/シグナル)は連動改善する。T2(One-Push NAR)とT4(netkeiba照合)は独立機能。
順序: T1 → T5確認 → T3確認 → T2 → T4。各タスク完了ごとにコミット・smoke緑。

まず新セッションで「T1から。まずnankan_scraperと現状のNAR SRA処理を読んで、純地方馬(ゴッドバーグ 例:大井202644070112)でPastRunsが取れない原因を特定して」と指示するとよい。
