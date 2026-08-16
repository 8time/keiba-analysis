---
name: jravan-jvlink-setup
description: JRA-VAN JV-Link取り込み環境の構築状態（32bit Python開通済・利用キー待ち）
metadata: 
  node_type: memory
  type: project
  originSessionId: 167390d6-2f22-4f41-bcc2-f3e605727fd4
---

keiba_analysisにJRA-VAN Data Lab（JV-Link）を統合中。**解約前提で1ヶ月の無料体験中に全履歴を吸い出しローカル較正資産を作る**戦略（[[jravan-brushup-plan]]）。

**構築済み環境（2026-06時点）:**
- JV-Link Data Lab インストール済み: `C:\Program Files (x86)\JRA-VAN\Data Lab`（JV-Link設定.exe / JVLinkAgent.exe）。COM登録済み（32bit専用）。
- 64bit PythonからはCOM不可。**32bit Pythonをzip版で導入**: `C:\Users\kimnhaty\pythonx86-312\tools\python.exe`（NuGet pythonx86 3.12.8を展開。インストーラ版はAVが反応するので不使用）。pywin32導入済み・win32com OK。
- 接続テスト: `keiba_analysis/scripts/jvlink_test.py`。**完全開通済み**（2026-06）。COM Dispatch✅ / JVInit("UNKNOWN") rc=0✅ / **JVOpen("RACE","YYYYMMDD...",1) rc=0✅** で実データ取得成功（H1/H6/HR/O1/O2 等）。
- **重要: 無料体験中は利用キー空(m_ServiceKey空)でOK**。当初-301が出たのは私が`option=4`を使ったミス。**option=1（通常データ）が正解**。「体験中はキー不要」はユーザーが正しかった。
- **pywin32は動的ディスパッチ必須**: `win32com.client.dynamic.Dispatch("JVDTLab.JVLink")`。`EnsureDispatch`で生成されるgen_py型付きラッパーだとJVOpenが「パラメータはオプションではない」で失敗する。gen_pyキャッシュ(`%LOCALAPPDATA%\Temp\gen_py`)は削除しておく。
- JV-Link COMメソッド: JVInit/JVOpen/JVRead/JVClose/JVStatus/JVSetSavePath/JVSetServiceKey/JVRTOpen/JVSkip 等。JVReadは(rc, buff, filename)を返す。rc>0=バイト数, 0=EOF, -1=ファイル切替, -3=DL中(待機)。

**取り込みパイプライン完成（2026-06・実データ取得検証済み）:**
- `scripts/jvdata_spec_extract.py`: JV-Data2311.xls(`%TEMP%`)の「フォーマット」シート(index2)から全31レコード型の項目レイアウトを`scripts/jvdata_layout.json`に自動抽出。
- `scripts/jvdata_parser.py`: RA/SE/HRを**1始まりバイトオフセット**で切り出し（数値=ascii、馬名等=cp932）。race_key=年4+月日4+場2+回2+日2+R2(16桁)、netkeiba_id=年4+場2+回2+日2+R2(12桁)。
- `scripts/jvlink_ingest.py`: JV-Link→SQLite(`data/jravan.db`)。テーブル races/results/payouts。`--test`で直近少量、`--from --option`で範囲指定。

**JVGetsの正しい呼び方（重要・ハマりどころ）:**
- **JVReadはNG**（BSTR経由でCP_ACP変換され日本語バイトが不可逆破損、mbcs/cp932再エンコードもズレる）。
- **型付きラッパー必須**: `jv = win32com.client.gencache.EnsureDispatch("JVDTLab.JVLink")`（動的Dispatchだと JVGets のVT_BYREF|VT_VARIANTがマーシャリングできずヒープ破損でクラッシュ）。
- `jv.JVOpen(dataspec, fromtime, option, 0, 0)` ← readcount/downloadcountのプレースホルダ必須（in/out）。返り=(rc, readcount, dlcount, timestamp)。
- `jv.JVGets(b'', 120000)` → (rc, buff, filename)。buff=バイト配列。`bytes(bytearray(buff))`で正規化。rc=0:EOF, -1:ファイル切替, -3:DL中(待機), >0:バイト長。
- 検証OK: 馬名「ヴォルスター」騎手「黒岩悠」単勝3.4等すべて正しくデコード。

**全履歴取込:** `--from 19860101000000 --option 4`をBG実行（5011ファイル・37レコ/秒・約25h、JVOpen-301は自動リトライ実装済み）。RACEデータ種別=RA/SE/HR＋地方/海外の馬柱参照も含む（地方/海外は払戻なし→分析時はjyo IN('01'..'10')で中央のみに絞る）。`year=1954`等のstrayが少数（要クレンジング）。**JV-Linkは同時1セッションのみ**＝RACE取込中はUM等の別取得不可、完走後に実行。

**実装済み分析モジュール（4機能・64bitでDB読むだけ）:**
- ① `scripts/backtest.py` — 時系列バックテスト。人気別/年代別ドリフト・オッズ帯別・ドローダウン・`simulate(strategy)`汎用API。検証済(1番人気単勝ROI76.8%等・教科書通り)。
- ② `scripts/kelly.py` — Whelan多肢選択ケリー`kelly_multi()`＋破産確率`ruin_probability()`(モンテカルロ)。EVプラス馬だけ配分・1/4ケリー推奨を実証。
- ③ `scripts/build_blood_dict.py` — 種牡馬/母父×芝ダ×距離帯の複勝率・回収率を`data/blood_dict.db`に。**要UM取込**（RACE完走後 `jvlink_ingest.py --dataspec DIFF --option 4`）。parse_um追加済・horsesテーブルもDDL済。

**⚠UM(血統)取込が未完=最近の馬の血統が欠損(2026-06-23確認)**: horses総数198,212頭(ほぼ全頭sire有)だが、results出走馬とのカバー率が年々低下=2023:75%/2024:52%/2025:32%/**2026:21%**。原因=RACE(レース結果)は継続取込だがUM(競走馬マスタ=血統)の`--dataspec DIFF`取込が未実施のまま(過去の一括分で止まっている)。症状=🩸血統SPで最近レースの父/母父が「-」・道悪×血統シグナル([[verified_baba_blood]])が最近レースで発火しない。**対処=`python scripts/jvlink_ingest.py --dataspec DIFF --option 4`(全件・JV-Link単一セッション時)→その後build_blood_dict.py再実行**。UMはkind=='UM'でparse_um(3代血統pos205・父1/母2/母父5)→horsesにupsert。RACE dataspecにUMは含まれない。体験版でDIFF配信不可なら--probeが0件→正式キー要。

**実行結果(2026-06-23)=DIFF option=4はマスタが2023-07で停止していた**: 32bit python(C:\Users\kimnhaty\pythonx86-312\tools\python.exe)で`--dataspec DIFF --option 4`実行→UM 198,212件処理もhorses件数は198,212のまま不変(1頭も増えず)。診断: ①JRA中央のみでもカバー率2024:53%/2025:28%/2026:20%(地方海外でなくJRA若駒が欠損) ②horses.birthが2021頭打ち(2022以降ゼロ) ③欠損馬のketto=2023xxxxxx(2023年生まれの若駒) ④JVOpen返りtimestamp='20230731144210'＋DL=0ファイル＝2023-07-31時点のキャッシュ済セットアップを読み直しただけ。option=4は古いローカルキャッシュを再読込しただけで新規DLなし。**次手=通常差分でキャッチアップ: `jvlink_ingest.py --dataspec DIFF --option 1 --from 20230731000000`。DLファイル≥1かつhorses>198,212なら成功。DL=0/UM増えずなら体験版の蓄積系が2023-07で打切り=最新血統に正式キー(有料)必要**。

**結論=JRA-VAN血統マスタはこのライセンスで2023-07凍結・コードでは解決不可(2026-06-23確定)**: ①RACEはoption=1で2026まで取れる(ライブDL有効・results 2,880,461→2,880,928で確認) ②DIFF option=1 from2023-07はrc=-1(通常データ提供期間外・古すぎ) ③DIFF option=4を--savepathで新規空フォルダに向けてもDL=0/UM198,212/horses不変=サーバがこのアカウントに2023-07超のセットアップを出していない。births≤2021頭打ち・2022以降生まれ(2024-26デビュー馬)は永遠に埋まらない。**JRA-VANのデータ契約問題でJV-Link追求は打止め**。

**回避策=netkeibaスクレイプ血統を血統シグナルに優先利用(実装済2026-06-23)**: ライブ単レース解析はnetkeibaスクレイプ時に既にdf['sire']/['broodmareSire']を取得済(app.py:4145・Bloodline列の出所)。問題は道悪×血統(heavy_fav_blood_mod)と消去エンジン(_babafav)がjravan.db horsesを見ていた点のみ。app.pyの2箇所(_aimループ・消去エンジン)を「スクレイプ済みdf['sire']優先→無ければtb.sire_of_ketto(jravan)フォールバック」に変更。これで賭ける場面(ライブ)では血統欠損が解消・道悪×血統が最近レースで発火する。血統SPの過去レースIDタブは依然jravan依存(2023以前のみ・過去検証用で影響小)。
- ④ `scripts/betting_ledger.py` — 予測→結果→反省→学習ループ。Brier score＋ROIで自己採点、予測勝率帯の較正ズレから次回ルール生成（GEPA的）。検証済(過大評価グセを自己検知)。

研究的裏付け: 多肢ケリー=Whelan(2025,Wiley boer.12474実在)、LTR競馬=Korean J Applied Stat 2024(CatBoost Ranker最良・実在)。「40年=特徴量辞書／直近5-7年=学習」の使い分けが過学習対策の結論。次: LTR(XGBoost/LightGBM rank:ndcg)で3着内ランク学習、ウォークフォワード検証。
