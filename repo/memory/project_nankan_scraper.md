---
name: project_nankan_scraper
description: nankankeiba.com(南関東4場)スクレイパー＋NAR分析パイプライン修復。PastRunsブリッジでPCI/展開マップ/脚質分類をNARで有効化・大井/川崎深掘りプロファイル
metadata: 
  node_type: memory
  type: project
  originSessionId: b85681ee-81a0-4031-a84d-ca3e3c82da92
---

core/nankan_scraper.py新設。nankankeiba.com(Shift_JIS)から南関東4場のデータを取得。

**netkeiba場コード(jyo_code)の正しい対応(2026.07に誤りを発見・修正):**
42=浦和／43=船橋／44=大井／45=川崎。core/track_bias.py `_NAR_VENUE_PROFILES` は
一度このマッピングを取り違えて実装しており(大井=42等)、全部ズレていたバグを発見・修正済み。
nankan_scraper.py内の`NANKAN_VENUES`(nankankeiba.com内部コード用、42/43/44/45だが意味が別)
とは体系が異なるので混同注意。

**根本バグ: NAR races always had empty PastRuns → PCI/展開マップ/脚質分類が全馬50.0/不明で死んでいた**
netkeiba地方競馬版(nar.netkeiba.com/race/shutuba.html)には過去走の詳細(タイム/上がり3F/通過順)を
含む`td class="Past*"`セルが構造上存在しない(JRAのshutuba_past.htmlのみに存在)。
core/scraper.pyのget_race_data()はJRA/NAR共通コードパスでこのセルを探すため、
NAR馬は常に`PastRuns=[]`になり、race_analysis_tools.get_pci_summary()・
calculator.analyze_pace_profile()が全馬デフォルト値(AvgPCI=50.0/不明/展開適合率0%)を返していた。

**修正: nankankeiba.comの過去走をPastRuns互換dictに変換するブリッジを追加**
- `nankan_scraper.runs_to_pastruns(runs)`: nankan runの(time/agari3f/distance/passing等)を
  scraper.pyのPastRuns dictスキーマ(Time/Agari/Distance/Passing/Margin等)に変換。
  既存のPCI計算式(race_analysis_tools.calculate_pci)・脚質分類(calculator.analyze_pace_profile
  の_label_from_score、過去走のPassing文字列から通過順比率で判定)をそのまま流用でき、
  NAR専用の新ロジックを一切書かずにJRA版と同じ分析パイプラインが動く。
- `enrich_with_nankan()`の戻り値に`pastruns`キーを追加。
- app.py: 🏠Single Race Analysisタブで、NAR(jyo 42-45)なら「nankankeiba.comレースID」入力欄が
  出現(main_nankan_id)。must_fetchブロック内でdf['PastRuns']にブリッジ結果を埋め込んでから
  calculate_battle_score以降の計算に入る。
- 展開スコア(DeployScore)は表示専用の評価軸に留め、予測スコアへの直接加点はしない
  ([[verified_tenkai_priced_in]]で「展開恩恵は織込み済み」と検証済みのため、NARでも同じ扱いが正しい)。

**実機検証(Playwright, 2026-07-01):** 202644063001(大井2歳戦, 2026-06-30 R1)を
nankan_race_id=2026063020050201で補完 → 12/12頭マッチ。補完前は全馬PCI50.0/展開適合率0%、
補完後はAvgPCI 38-48で分散・展開適合率54%・RPCI42.1・波乱確率40%と正しく差別化された。
nankan_race_idは日付/venue/R番号を含む16桁。

**【2026-07-03 完了】nankan race_id自動導出(T1・手入力不要化):**
`/calendar/{YYYYMM}.do` がその月の全開催の`program_id`(14桁=date8+venue2+kaiji2+day2)を列挙する。
これでdate+venueからkaiji/dayをブルートフォースせず決定的に導出できる。
- nankankeiba内部venue(16桁の[8:10]): **18浦和/19船橋/20大井/21川崎**(2026-07カレンダー実査確定)。
  netkeiba jyo(42-45)とは別体系。`nankan_scraper.NETKEIBA_TO_NANKAN_VENUE`={'42':'18','43':'19','44':'20','45':'21'}。
- `nankan_scraper.derive_nankan_race_id(netkeiba_race_id, date_yyyymmdd)`: カレンダーから
  program_idを引きR番号を付す。`fetch_month_programs`(月キャッシュ)/`fetch_program_races`も追加。
- app.py SRA+消去エンジン両導線で、手入力(main_nankan_id/kf_nankan_id)が空なら
  metadata.date_valから自動導出。手入力で上書き可。実査=大井7/1 R1・7/3 R11で全馬PastRuns充足。
- uma_search(馬名検索)フォールバックはJS駆動(doSubmit)でrequests静的GET不可→不採用。
  純地方馬は自レースのnankan出走表に必ず載るので、正しいrace_id導出だけで名前照合で解決する。

**fetch_entriesの列パースバグ2件を修正(2026.07):**
1. 同枠2頭ペアの2頭目は枠番セルがrowspanで省略され11セル行になる→枠番/馬番/馬名が全部
   1列ズレて壊れていた(waku値が実は前馬のumaban、nameが実はsex_age等)。セル数で
   オフセットを動的判定し前行の枠番を引き継ぐロジックに修正。
2. 馬名末尾に"(中同名)"等の注記が付くと生年月日パース正規表現が失敗→注記を許容する正規表現に修正。
sire/dam分割(カタカナ境界ヒューリスティック)は依然不正確(参考値どまり)。ただし
match_horses_by_nameは馬名のみで照合するため実害なし。fetch_horse_history側の父/母/母父
(ラベル付き行から取得)は正確。

**大井/川崎 深掘りプロファイル(NotebookLM資料ベース、jyo正: 大井=44/川崎=45):**
core/track_bias.pyの`_NAR_VENUE_PROFILES`に距離別枠順バイアス・砂質・雨天バイアス・
リーディング騎手・重賞傾向を追加。船橋(43)/浦和(42)にも一般的なコース構造知識ベースで
distance_biasを追加(こちらは大井/川崎ほどの実証データ無し・定性的記述に留める)。
`nar_evidence_rows(jyo_code, surface, distance, race_name)`にdistance/race_name引数を追加し、
SRAエビデンス表で距離別バイアス・重賞傾向行を動的生成。

**Why:** [[feedback_catch_underrated_winners]]同様、NARは JRA-VANデータが無く
分析パイプライン全体が死んでいた。データ取得層(前回)に続き、分析ロジック層の
PCI/脚質/展開マップをJRAと同じ検証済みロジックへ橋渡しすることでNAR分析精度をJRA並みに引き上げた。

**How to apply:** NAR race_idを解析する際は、対応するnankankeiba.com race_idを
`/program/{日付+venue+kai+day}.do`か出馬表ページから見つけて`main_nankan_id`に入力する。
入力が無い場合は従来通りPastRunsが空のままフォールバック動作(エラーにはならない)。

**横展開(2026.07): 🧹消去フィルターにも同じブリッジを配線**
🏠Single Race Analysisだけでなく🧹消去フィルターにも`kf_nankan_id`入力+PastRunsブリッジを追加。
併せて`_nk_spurt_map`(馬名→nankan末脚指数)を作り、jockey_jv(JRA-VAN)ベースの
spurt_indexがNone(NAR専業馬でjravan.db未収録)の場合のフォールバックとして
①末脚救出ロジック(強適消去エンジン)②compute_flags(消去クロステーブル)双方に配線。
pcidev(事前平均PCI乖離)は`race_analysis_tools.PCICalculator`がdf['PastRuns']を直接見るため
ブリッジのみで自動的に機能する。実機検証(Playwright, 202644063001+nankan 2026063020050201)で
12/12頭マッチ・危険人気馬フラグ(大幅距離変更/半年休み明け)が個別馬で正しく発火することを確認済み。

**🔍Race Scanner(Batch)のNAR対応(2026-07-03完了):** 実は既にNAR対応済だった
(単複乖離/オッズ断層/荒れ度=オッズ系は元々動作。末脚救出/初ダート等はvalue_scanner.
horse_value_factorsが`jj.horse_recent_context(ketto)`=jravan参照で、NAR馬もketto解決10/10)。
**重要**: scannerはdf['PastRuns']でなくjravan ctxを見るため、バッチにnankan PastRuns一括補完を
足しても無意味かつスクレイプ過大→非採用。代わりに騎手名の名寄せ(下記)を配線し黄金ラインを有効化。

**騎手名の略記→完全名 名寄せ(NAR共通の落とし穴):** netkeiba/NAR出馬表は騎手名を短縮表示
(中山遥/和田譲/安藤洋)し、jravanの完全名(中山遥人/和田譲治/安藤洋一)と一致せず成績0になる。
`jockey_jv.resolve_jockey_name(略記)`=DB騎手名一覧をキャッシュし前方一致で最頻の完全名へ解決。
One-Push(騎手Pro)のレース単位騎手指標のNAR未取込フォールバック(ライブ出馬表+jravan履歴)と
value_scanner.horse_value_factorsの黄金ラインで使用。**別バグ**: jockey_jv._venue_nameがJRA(01-10)
のみで、NARで''を返し当該場成績が全走混入していた→NAR会場(42浦和/43船橋/44大井/45川崎等)を追加。

**【2026-07-03】T2/T5/T3も完了(nar_support_project.mdのタスク):**
- **T2 One-Push(騎手Pro)NAR対応**: 根本原因=NAR出馬表は騎手/厩舎が`<a>`でなくプレーンテキスト
  → `jockey_analyzer.extract_jockey_ids_from_race`の`td.Jockey a`セレクタが空。NAR時は
  `get_race_data`(NAR対応済)で騎手/厩舎/馬名/人気/オッズを馬番照合補完。fetch_race_metaもNARドメイン化。
  **重要バグ修正**: `scraper.VENUE_NAMES`の南関場コードが誤り(42大井/43川崎/44船橋/45浦和)で
  会場別騎手成績照合を破壊していた→正(42浦和/43船橋/44大井/45川崎)。smokeに回帰ガード追加。
- **T5(シグナル/展開適合度)/T3(順位妥当性)はT1連動でコード変更なしで解決**。
  補正Tは**jravan在籍NAR馬(大半)で機能**(resolve_horse→ketto→corrected_time.db)。
  純地方新馬(jravan未収録・例ゴッドバーグ)のみ補正T='-'(検証済NAR補正T無しのため捏造せずfield-rank整合を保つ)。
  T1前=空PastRunsでBattleScore全馬0.0一律→T1後=差別化(大井7/3 R11 std0.00→5.31)。
- **T4 netkeiba AI展開予測(4コーナー)照合**は[[project_ai_tenkai_overlay]]参照(core/ai_tenkai.py新設)。
