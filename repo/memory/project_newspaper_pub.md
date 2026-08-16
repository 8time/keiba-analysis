---
name: project-newspaper-pub
description: 📰新聞発行ページ — SRA解析をPDF競馬新聞化+全情報CSV。データ源はviewスナップショット
metadata: 
  node_type: memory
  type: project
  originSessionId: cc3efc74-957d-40d6-bb8c-d63a99809eb5
---

📰新聞発行(2026-07-11実装)。core/newspaper.py + pages/newspaper_pub.py。

- データ源: SRAが強適Ranking Table確定時に data/newspaper/{rid}.view.json(表示列フォーマット済み+列順+ラベル)、合議確定時に {rid}.cv.json(groups/horses+aim=build_edge_sets全セット+荒れ予報forecast)、展開MAP={rid}.pace.json、4券種おすすめ買い目={rid}.bets.json を保存(app.pyフック7ヶ所)。左メニューは新タブ=別セッションなのでsession_stateは跨げず、ディスク経由が必須(score_cacheと同じ設計)。
- 紙面セクション: 予想ヘッダー(荒れ予報/妙味度/軸候補+複勝信頼度/危険人気馬)・合議5カード・買い目4券種・展開隊列(AI照合💀はscore_cache.read_tenkai_danger)・消去フィルター(aim.elim+read_keep)・穴馬ハンター(aim.vh_tier×人気薄6+上位6頭に制限=実レースで全馬精鋭になる対策)・オッズ動向(odds_history.db+odds_move紙面時算出)・エビデンス表/PCI&展開適合/展開分析&波乱確率/Stress Analyst({rid}.analysis.jsonにwrite_analysis_snapshotでキー別マージ保存)・🚨条件アラート集約(荒れ予報lean/危険veto=cv.jsonから再構成+末脚妙味/枠順エッジ={rid}.alerts.json write_alert=空書きクリア方式)。
- 列選択: カスタム(チェック式)で非表示列含む全項目から選択・チェック順=紙面順(SRA⚙列順設定と同パターン)。
- CSV強化=LLM実験の学び(2026-07-12): ユーザーが全情報CSVを外部LLM会議に渡して七夕賞を予想させた実験→1/3的中(人気ベースライン並み)。原因診断=①CSVに合議の結論(役割/危険材料/荒れ予報)が無く生特徴量のみ ②Projected Score/LTRは人気内包でLLMが実質人気に依存 ③正解シグナル(6末脚🔥/9補正T🔵)はCSV内で光っていたが使い方の説明が無い。対策=build_csv_bytesに結論列(合議役割/検証シグナル根拠/🧩重複/妙味tier/危険材料+R荒れ予報%/R妙味度/R決着タイプ)を同梱+csv_data_dictionary()(検証済み/帯限定/市場内包/否定済み俗説を説明するLLM向けデータ辞書md)を📖ボタンで配布。**外部LLMに渡す時はCSV+辞書セットが必須**。LLM反省会の改善提案は大半が検証済み却下項目(斤量/展開/4角位置/コース適性)=俗説再生産に注意。
- 改ページ設計(2026-07-12・「PDFが変な切れ方」対応): ①レース区切りはpage-break-AFTER→BEFORE(2R目以降)=末尾空白ページ根絶 ②表紙は3R以上のみ独立ページ+目次付き、1-2Rは題字帯のみに縮小(白紙ページの主因だった) ③extras欄はflex→inline-block(flexは入りきらない行が箱群ごと次ページへジャンプし大空白を作る=印刷fragmentationに弱い) ④table.ktにpage-break-inside:avoid(keep_tableオプション既定ON)=表が入らなければ次ページ頭から丸ごと・1ページ超は自動分割+tr単位avoid。pdf.js(CDN)でPDF各ページをPNG化する検証スクリプトあり(scratchpad/render_pdf_pages.py方式)。
- 🐞既定フィルタの罠を修正(2026-07-12): 旧既定『最新日のみ』は前日に翌日レースを1つ解析すると該当1Rに縮み、紙面が1レース分しか出ない(ユーザー報告「PDFがおかしい・一番上のレースしか出ない」の正体。バックエンドは正常だった)。既定を『解析が新しい順(推奨)』=ts降順の上位12Rに変更+「↻既定を選び直す」ボタン(np_racesをpopしてから再生成)。
- 🔍スキャン新聞(2026-07-12): Scannerスキャン完了時に結果+Gateをdata/newspaper/scan_digest.json(最新1回)へ保存→A4縦2列カードの一覧PDF。フィルタ=②穴妙味のみ/本線のみ(荒れ回避)/荒れ予報%レンジ/見送り除外/最大R数/並び。UI=pages/newspaper_pub.render_scan_digest_ui(Scannerページと新聞ページで共用・key_prefix分離)。leanはセッション=dict/保存後=strの両対応(_lean_of)。
- 色分け継承: 強適テーブルStylerの計算済みセルCSS(styler._compute()→ctx・冪等)を表示直前に{rid}.styles.jsonへ保存→紙面がtd inline styleで完全継承(ルール二重実装なし・アプリの色変更に自動追従)。行キー=表示行順のpos(view recordsと同順)。🧹行グレーアウトは適用前に取る。モノクロ/行数不一致はスキップ。
- スナップショット未保存の過去レースは data/score_cache/{rid}.full.json から代表列(_FB_COLS)で再構成(📄代表列マーク)。
- PDF化は既存Playwright chromium page.pdf(A4横/縦・scale)。requirements追加なし。Streamlitスレッドとのasyncioループ衝突回避で別スレッド実行。
- CSVエクスポート: view表示列+full.json全列をUmabanでマージ、PastRuns等ネストはJSON文字列化。
- 発行メニュー設定は user_prefs.json の 'newspaper' キーに永続化。
- smoke.py に newspaper往復チェックあり。FEATURE_STATUS.md 登録済み。

関連: [[project_qa_harness]] [[project_consensus_view]]

## 配布物(紙面)に載せてよいデータの線引き(2026-07-23確定)

**方針: 紙面には自前の計算結果だけを載せる。他社の"加工物"は載せない。** アプリ内で自分が見る分は私的利用なので従来どおり。

- ✅ **出走表の事実**(馬番/枠/人気/オッズ/馬名/騎手/斤量/馬体重/調教師/血統) … 著作権法10条2項「事実の伝達にすぎない雑報」で**そもそも著作物でない**。出所を問わず自由。実測で紙面42列中28列は自前計算、残りもこの事実列。
- ❌ **他社が作った予測・指数** … netkeibaのAI展開予測、他社の予想印など。事実ではなく創作的な加工物。
- ⚠️ **契約で縛られたデータ**(JRA-VANの生データ) … 著作物でなくても**契約**で再配布制限。加工済みの予想・指数の公表は一般に可だが規約は要確認。
- ⚠️ **CSV同梱時** … `build_csv_bytes()` は full.json全列(108列)＝スクレイプ済み過去走(PastRuns)を含む。読者に配るなら加工済み列だけに絞る。

**⚠ 誤った線引き(却下)**: 「複数サイトに載っている数字は出所が特定できないから自由」——**成り立たない**。義務の源は「バレるか」ではなく**自分が同意した契約**。JRA-VANと契約している以上、同じ数字が他所にあっても規約に縛られる。正しい理由は「公表された事実はそもそも誰のものでもない」の方。理由を間違えると、他社の予想印まで載せる方向に流れる。

**実施した対応**: `core/newspaper._pace_html()` から netkeiba AI展開照合の分岐を削除し、後方グループは**常に自前の展開MAP**を使うようにした。以前は 🤝照合を実行済みのレースだけ「💀AI展開照合=両AIが後方帯で合意」に差し替わっていた(保存済み100件中12件が該当)。展開恩恵は[[verified_tenkai_priced_in]]で紙面価値への寄与も乏しく、リスクだけ残る機能だったため。app.py側の🤝表示は**変更なし**(私的利用)。
