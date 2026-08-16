---
name: project-elimination-engine
description: 🧹消去フィルターに強適消去エンジン追加(半分消去＋穴1頭救出＋危険人気馬検知)。検証済み
metadata: 
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

🧹消去フィルター刷新(2026-06-15)。ゴール=出走数を半分に減らし、消した中から妙味の穴1頭、別に危険な人気馬を検出。ユーザー方針=予測スコア/BattleScore下位馬ベース。俗説条件(前走着順/年齢/ローテ/血統)は[[feedback-folk-signals-overbet]]で過剰人気=非採用とした。

**検証(scripts/elimination_backtest.py, test2023-2025・JRA平地, train〜2022で黄金ライン/厩舎当コース構築)**:
- ① 人気ランクで下位半分を消す → 勝ち馬取りこぼし10.0%/3着内17.4%。半分narrowingは安全(9割の勝ち馬は残る)。
- ② 人気薄(≥8番)×検証+ファクター(黄金ライン連対≥40%(rides≥10) or 厩舎当コース勝率≥20%(runs≥10)) → **単勝回収率108.8%(プラス)** vs 無印63.7%。n=453/3年。穴救出ルール有効。
- ③ 人気上位(≤3番)×検証-ファクター(牝×冬春/大幅距離変更≥400m/初ダート/前走フロック=前走人気薄≥6で着順≤3) → 3着内残差+0.0145 vs 健全人気馬+0.0409(両者有意)。危険人気馬は他の人気馬比 約-2.6pp。検知有効(相対的危険・絶対消しではない)。

**実装(app.py 🧹ページ上部「🎯 強適消去エンジン(検証済み)」ボタン)**:
- 強適消去スコア = -人気 + (＋ファクター1.5) - (−ファクター1.5)。降順ソート、上位半分=✅残し/下位半分=🧹消し(色分け)。
- 妙味の穴: 消去ゾーン×人気薄(≥8)×＋ファクター の最長オッズ1頭をsuccess表示。
- 危険人気馬: 人気≤3×−ファクター をerror表示(馬名＋危険材料)。
- 注: **予測スコア/BattleScoreはライブ生成でDBに無い**ため消去スコアは「市場順位±検証ファクター」で自己完結。完全に予測スコアで切るならSingle Race Analysisの採点済dfを連携する追加実装が要る。
- core/jockey_jv.py: horse_recent_context() 追加。黄金ライン=jockey_trainer_combo(top2)、厩舎当コース=trainer_course_winrate([[project-trainer-course]])を再利用。
- push済(commit 3aab55f)。

**追加検証＆実装(2026-06-15・PDF/資料「危険な人気馬の解体新書」「2026 Playbook」NHKマイルC資料の取り込み)**:
- scripts/dangerfav_backtest.py で資料の危険シグナルを検証(人気≤3・残差)。基準(健全人気馬3着内残差)≈+0.032。
  採用4つ: **トップ騎手乗替**(残差+0.009・単勝72%)/**斤量比≥12.6%(小型439kg以下)**(勝利残差−0.006・単勝70%)/**半年休み明け**(残差−0.020 z−1.7)/**前走逃げ**(残差+0.005)。→③危険検知の−ファクターに追加。
  非採用: 押し出し1番人気≥4倍(中立・資料外れ。真に危険は1人気2-3倍−0.05だが帯artifact)/ローカル/長距離。
- core/jockey_jv.py: horse_recent_context に prev_jockey/prev_date/prev_kyaku 追加、jockey_is_top() 追加。netkeiba騎手名は略称のため前方一致で乗替判定。斤量比は馬体重が発走前未公開だと不発(公開後点灯)。
- **3連複フォーメーション連携(その2)**: core/trio_engine.py build_formation(col1,col2,col3)=各列1頭ずつ相異なる3連複(順不同重複排除)。app🧹ページに「3連複フォーメーション」UI追加=✅残し上位→軸/対抗、🎯穴→押さえに自動配置。2-4-7型/1-3-5型/カスタム、点数×単価表示。買い目構造は予測エッジでなく点数最適化([[project-trio-engine]])。小サンプル0-0-0-10型(資料)は罠で非実装。

**🧹消去クロステーブル(2026-06-17・ユーザー観測「調教C以下は3着内に来にくい→下位指標を重ねれば消去強化できるのでは」起点)**:
- 検証(scripts/elim_cross_backtest.py, test2021-25 n=330,818, 過去走のみ=hindsight漏れ防止)。8フラグ=近3走着外/5走複勝0/末脚下位/後方脚質/半年休み/距離±400m/体重±16k/8歳上。
- **結論(重要)**: 各フラグ単体の複勝率は**人気に織込み済(人気補正残差 -0.1〜-1.5pp)＝妙味ではない**(圧勝/脚質/僅差負けと同じ教訓)。ただし**重複数→絶対複勝率は強い単調低下: 0個31.5/1個27.1/2個19.1/3個14.9/4個13.7/5個13.6/6個13.1/7個10.3%**。人気1-5番でも6個以上で残差-1.8〜-5.5pp(小n=過剰人気の兆候)。
- **用途は『妙味発見』ではなく『来にくさの可視化』**=3連複フォーメーションの相手から外す点数削減＋軸の不安可視化。人気とほぼ相関する点を明記して使う。
- 実装: `core/elim_cross.py`(FLAG_DEFS/compute_flags/band_fukusho=重複数→推定複勝率)＋`core/jockey_jv.py: horse_elim_stats()`(直近5走top3/直近3走4角比率)。app🧹ページ上部に「消去クロステーブル」ボタンUI(重複数降順・色分け・4個以上=消去推奨/人気≤5×4個以上=過剰人気警告)。
- **調教評価(A〜D)はjravan.dbに過去データ無く検証不可**([[project-training]])。ユーザー実観測が強いため『調教C以下』は手動multiselectで重複数に+1できる『検証不可フラグ(train)』として別扱い。
- **総合戦闘力/予測スコア下位の加味(2026-06-17・ユーザー要望)**: 🏠Single Race Analysisの採点df(`st.session_state['current_bonus_df']`>`['df']`、列=BattleScore/Projected Score)を🧹ページが取得し、下位30%(quantile0.30以下)に`battle`/`proj`フラグ追加。馬番集合の60%以上一致で同一レース判定(別レース採点の誤適用防止)、不一致時はチェックボックス非表示+案内。**これらは人気/オッズ内包かつライブ生成で再構築不可=検証不可**のため`UNVERIFIED={train,battle,proj}`に追加し、`verified_count()`(検証8フラグのみ)で**推定複勝率(BAND)を算定**。表は『フラグ数(総重複)』と『検証数』を分離表示、推定複勝率は検証数ベース。消去候補=総重複≥4、過剰人気警告=検証数≥4(残差発見は検証フラグ由来のため)。
- 未commit(elim_cross.py+jockey_jv.py+app.py消去クロステーブル一式)。

**🐞重大バグ修正＋列追加(2026-06-21):**
- **連携バグの根因=左メニュー新タブ化([[project_magi_oshaberi]]と同時期の変更)**。各ページが別Streamlitセッション→st.session_stateは**タブ間で共有されない**ため🧹消去クロスが🏠の`current_bonus_df`(戦闘力/予測スコア)を読めず連携断。**横断したいデータはsession_stateでなくディスク**。教訓として今後のクロスページ連携も同様。
- 修正: **core/score_cache.py 新設**。🏠採点時(app.py 3813付近)に`write_scores(race_id, df)`で`data/score_cache/{race_id}.json`へ保存→🧹側が`read_scores(race_id)`で読み戻し(race_id一致で誤適用なし)。消去クロスの`battle`/`proj`フラグ復活＋強適消去エンジンのEV列にも流用。
- **強適消去エンジンに4列追加**: 🔵補正T(過去走ベスト補正タイム偏差・フィールドtop3に🔵=[[verified_corrected_time]])＋単勝EV/複勝率/連対率(core/bet_optimizer: blended_win_probs→ev/place_prob/自作top2。**Projected Score必要=未採点なら'-'と案内**)。EV/複勝/連対は**モデル目安(未検証)**=下の「📊jravan実測オッズ帯」とは別物と明記。
- **「後方馬を消去クロスに条件追加」は既存`back`フラグ(後方脚質=直近3走4角位置比≥0.78)で対応済**(horse_elim_statsのavg_c4ratioで点灯)。展開MAPの相対後方5-8頭とは定義違い(habitual vs this-race)だが、展開position自体priced-in([[verified_tenkai_priced_in]][[verified_legtype_axis]])なので重複カウント用として既存flagで足りる。
- 展開MAP(core/pace_map.build_figure): 後方5〜8頭(出馬数依存:≤12→5/13-14→6/15→7/16+→8)の境界に**オレンジ破線**を局面ごとに描画(frames traces=[0,4,5])。

**勝ちワークフローの緑枠常掲＋将来の統合プラン(2026-06-23)**: ユーザー運用知見=「最初の消去で3着内はだいたい残る。回収率上位×補正T上位の重なりで絞るのはダメだった(回収率は市場効率的[[verified_tansho_roi_efficient]]・補正Tは本命寄りで人気と重複[[verified_corrected_time]]=織込み同士の重なりは無効)。強適ランキング(🤖検証AI=recall@7最適化)主軸の方がうまくいく」。→app.py 🧹消去フィルターページ最上部(st.header直後)に緑枠HTMLボックスで常掲: ①消去=母集団づくり(recall) ②強適ランキング主軸 ③絞りは回収率でなく検証エッジ(🚫危険人気消し[[verified_emp_bias_danger]]/🔵補正T=本命補強/🔥穴=末脚偏差[[verified_spurt_index]]/🟢道悪=血統[[verified_baba_blood]])。⚠回収率は馬選別でなく見送り・点数・券種で守る。**将来プラン**: 🧹消去フィルターは最終的に🏠Single Race Analysisへ移設予定(上下スクロールで情報を見ながら絞るため)。ただし同ページの馬券系機能が未完成のため当面は移さない([[project_app_pipeline]])。

**危険人気馬Veto共通化 P0(2026-06-23・Codexブラッシュ案の最優先を実装)**: 散在していた検証済み危険シグナルを `core/danger_gate.py` の `danger_veto(...)` 1本に集約(全引数optional・人気1-3番限定発火・severity=該当理由数)。集約=重不良×1番([[verified_heavy_track_bias]])/道悪×瞬発系FADE([[verified_baba_blood]])/外有利×内枠人気([[verified_emp_bias_danger]])/牝×冬春fade/トップ騎手乗替・斤量比≥12.6%・半年休み・前走逃げ(dangerfav)/Stressはリーク無し3つのみ([[verified_stress_debuff]])。**方針=相対de-rank(完全消しでない)**: severity0=通常/1=軸降格注意(⚠付記・相手まで残す)/2以上=軸不可(veto)。`axis_demote()`でAxisMark表示を降格。配線済=🏠SRAの🎯軸馬候補◎〇▲(人気上位のマーク付き馬を降格)。**残り(次の増分)**: 3連複2軸の自動選定/馬連軸/馬単頭固定にも同Gateを配線(各サイトで危険コンテキストを渡す)。tests/smoke.pyにdanger_gateチェック追加(174/174)。関連:[[project_qa_harness]][[project_axis_selection]]

**両列最下位(botcross)フラグ追加(2026-07-03・ユーザー要望「もっと多くの項目でふるいたい・ボーダー3で3頭戻すなら3頭以上消したい」)**:
- 検証(scripts/elim_column_rank_backtest.py, test2021-25・JRA10頭以上・全部pre-race leak-free)。強適表の**上り3F(末脚)/平均位置**の"列内下位"を検証。
- **単独列の下位は弱い(priced-in)**: 上り3Fワースト1頭=複勝8.5%(人気期待9.1・残差-0.6pp)/平均位置ワースト1頭=11.4%(-1.0pp)。ワースト3頭を消すと3着内馬を30-38%のレースで誤消去=単独では消しすぎ。
- **両列の交差(上り3F下位∩平均位置下位)は強い**: 両列ワースト1=複勝**2.1%**(残差-2.0pp)/ワースト3群=4.6%。**ワースト3交差を消しても3着内馬を含むのは2.5%のレースのみ=97.5%安全**。holdout2025でも2.2%/2.3%誤消去で安定。
- 実装: `elim_cross.bottom_both_umabans(horses,k=3,min_field=8)`=spurt_index最小k ∩ avg_c4ratio最大k。FLAG_DEFSに`botcross`('両列最下位')追加。**BAND較正(元8フラグ)外**なのでUNVERIFIEDに入れverified_count/推定複勝率には算入しない(slow3f/backの相対版で二重計上回避)が、独立検証済のため表示は△を付けない。フラグ数(重複)には+1し降順ソートで消去候補上位に浮く。app.py消去クロス生成ループの後段でレース全馬をランクして点灯。
- **教訓**: 「列の下位=来ない」は単独では人気織込み(既存のslow3f/back単体がpriced-inなのと同じ[[verified_spurt_index]][[verified_legtype_axis]])。**複数の弱点列の"交差"にすると初めて強い消去**になる=消去クロスの本質(stacking)をユーザーの直感どおり定量化できた。

**多列弱点(multiweak)フラグ追加＋4列拡張(2026-07-03・ユーザー「他の列も同じ枠組みで」)**:
- scripts/elim_multicol_backtest.py で4列{末脚/平均位置/近走着順/補正T}を検証(補正Tはbaseline=同(馬場,距離)中央値→当日馬場補正→過去ベスト、leak-free自前計算。corrected_time.dbのfigは全キャリアで漏れるため不使用)。
- **単独列は全部priced-in**(残差-0.4〜-1.5pp、ワースト3消しは誤消去27-38%)。
- **2列交差(ワースト3∩)**: 末脚×平均位置=誤消去2.5%(最安全・botcross)/末脚×補正T=7.6%/平均位置×補正T=9.8%/近走×補正T=10.7%。安全さは末脚×位置が突出。
- **≥3列でワースト3(multiweak)**: 複勝6.7%・残差-1.5pp・誤消去**6.0%(94%安全)・約0.9頭/R**=botcross(0.28頭)より広く消せる中安全消去。
- **重要な限界**: 単一条件で安全に3頭消すのは無理。~1頭/Rが安全上限(それ以上は誤消去10-20%)。「ボーダーで戻す分を全部相殺」はbotcross+multiweak+既存countのstackingで達成する設計。
- 実装: elim_cross.multiweak_umabans(4列を『大きいほど下位』に揃え、need列以上でワーストK)＋jockey_jv.horse_elim_stats に avg_chaku_ratio(近走着順/頭数)追加。app消去クロス後段で末脚(-spurt_index)/位置(avg_c4ratio)/近走(avg_chaku_ratio)/補正T(corrected_time.get_figure.fig)をランクして点灯。botcross/multiweakともBAND較正外(UNVERIFIED)だが検証済のため表示△なし・重複数+1。

**残り列の追加検証=却下(2026-07-03・再提案しない)**: scripts/elim_multicol_backtest.pyを7列に拡張(+テン位置=過去1角比率/馬体重小/体重減)。full+holdout2025両方で:
- **テン位置(テン速力の遅さ)=残差+0.1〜+0.2pp=シグナル無し**。テンが遅い=差し追込で3着内に来るため消去材料にならない(むしろ僅か正)。**却下**。
- **体重減(当日マイナス)単独=残差-0.1〜+0.2pp=priced-in**。**却下**(小柄×馬体減の交互作用は[[verified_stress_debuff]]で既にstress1フラグ化済=クロス配線済のため二重計上回避で単独列は足さない)。
- **馬体重小=残差-0.6〜-0.8pp**は弱シグナルだがstress1(小柄×馬体減)と重複=二重計上のため**却下**。
- 結論: クロスの検証済み列は{末脚/平均位置/近走着順/補正T}(＋既存form/layoff/distbig/zogen±16k/age/pci/handi/stress)が正解セット。**弱い/priced-inな列を重複countに混ぜるとcount自体が鈍る**(7列重複≥2は誤消去46%に悪化)ため足さない。物理属性(テン/体重)は消去の物差しにならないと確定。

**『過信しない列』ヘッダ強調＋PCI乖離の扱い(2026-07-03・ユーザー要望)**: 消去クロス表を
st.dataframe(canvas gridはヘッダ着色不可)からpandas StylerのHTML描画(th.col_heading.col{n}で
列ヘッダ着色)に変更し、**総合力下位/予測下位/展開後方/PCI乖離のヘッダを赤背景×黄文字**に。
意図=これらは『重複には数えるが過信しない列』で、高重複でも3着内に来た馬(例:大井202644070112
グルナルーフス2着)がこの4列主因なら"消さない"判断を可視化。**PCI乖離をこの過信しない群に入れた
根拠=[[verified_pci_pricedin]](残差-0.5pp・人気織込みで実質エッジ無し)**。battle/proj/pmbackは
検証不可(人気内包)、pcidevは検証済だが実質priced-in。失敗時st.dataframeにフォールバック。

**人気下位・騎手実績下位フラグ追加(2026-07-03・ユーザー要望)**: 両方とも『過信しない列』(CAUTION_KEYS・赤×黄ヘッダ・UNVERIFIED=BAND較正外・重複には数えるが検証数/推定複勝率には非算入)。
- **人気下位(poplow)**: レース内人気最下位側3頭。複勝率3.2%=全列で最低(=最も安全に切れる実務軸)だが**残差-0.64pp=市場評価そのもの**(独立エッジ皆無・当然)。人気は基準なので重複countに入れると重複が人気を追うだけ→BAND非算入で正解。
- **騎手実績下位(jlow)**: 騎手の**通算複勝率**が低い側3頭。複勝率11.5%/残差-0.48pp/誤消去31.8%。
  **騎手指標の検証(within-race worst3・leak-free・2021-25)**: 通算複勝率(残差-0.48pp)＞USM人気比(-0.81ppだが複勝14.7%と高く誤消去39.5%で消しに不向き)＞**直近30走複勝率(-0.22pp≈ほぼ0=priced-in)**。→**騎手は通算複勝率で見るのが最適。直近成績/連敗ストリークは予測に効かない**([[project_jockey_jv]]の連敗誤謬と一致)。ユーザーの「直近レースの成績で判断?」への答え=NO。
- 実装: elim_cross.worst_k_umabans(単一指標ワーストK)＋CAUTION_KEYS定数。app cross loopで人気(r['人気'])と騎手通算複勝率(jockey_base_stats.overall.top3・50騎乗以上・resolve_jockey_nameで名寄せ)をランク。

**危険人気馬の精度改善=半年休み明けをソフト理由化(2026-07-03・ユーザー「危険人気馬がだいたい休み明けで好走してる=精度低い」)**:
- 検証(jravan 2021-25 JRA 1-3人気): 休み明け≥180は**複勝45.0%/期待52.2%/残差-7.28pp z-5.43**=統計的には有効なfade。だが**絶対複勝率が高く単独では"来る"**(1番人気×休明=**複勝59.7%**/2-3番=38.8%)。前走1着/休み明け実績あり/年齢/重賞平場…どの部分集合も残差負で「安全な部分集合」は無い。
- 結論=信号は本物だが**精度が低い**(絶対45-60%来る)＋NAR/直近はjravan収録が疎で休養日数を過大算出し**誤爆**(ユーザーが見ていた大井202644070112がNAR)。
- 対策: **danger_gate.danger_veto で半年休み明けを『ソフト理由』化**=他に硬い危険理由がある時のみseverityに算入(単独ではseverity0=危険表示しない)。'だいたい休み明けが表示される'ノイズを消し、重なった時だけ有効fadeとして残す。severity≥2=vetoは不変。**教訓: 残差有意でも絶対率が高い(=来る)信号は"単独で危険表示"すると体感精度が下がる→stacking gate化が正解**。elim_cross側のlayoffフラグ(重複用・priced-in前提)は別機能で不変。前走逃げ(dangerfav残差+0.005≈0)も本来弱いので将来同様に見直す候補。

**🔥+F(＋ファクター)を強適テーブルAlert列に常設(2026-07-12・ユーザー「なんで強適テーブルに出さないんだっけ」)**:
- ②の検証済み『人気薄8+×+ファクター=単勝ROI108.8%』は消去エンジン実行時にしか出なかった(実装経緯のみ・原理的理由なし)→SRA強適テーブルのAlert列に **🔥+F** バッジとして配線。判定は統合ビューと同じ build_edge_sets の市場エッジ(⭐黄金ライン rides≥10×連対≥40%/🏠厩舎当ｺｰｽ勝率≥20%/🟢道悪軸/🔥末脚top3)×人気≥8。セッションキャッシュ`_aimsets2_{rid}`共有で重複計算なし(Alert列フラグ段で未計算なら先行計算)。新聞にもAlert列経由で自動掲載。凡例(display_icon_legend)に説明追加。
- **✨EV>1は意図的に非掲載と確認**: オッズ帯平均勝率×自分のオッズ=帯上端で機械的に100%超えする帯量子化アーティファクト。[[verified_tansho_roi_efficient]](単勝は全帯+ROIポケット無し)と整合。ランキング表に出すと「買えるサイン」に誤読されるため消去フィルター内の注意書き付き参考のまま。再提案しない。

**消去クロス「📤SRAに送る」ボタン＋🔥敗者復活表示(2026-07-12・ユーザー要望)**: クロステーブル最終候補の下に📤ボタン。①押すと🚫stage2で切った馬(_x2ums)を統合ビューと同じ救済ルール(🧩combo3+ or 🎯精鋭)で照合→該当は残しに自動追加+🧹ページにst.warning表示。②combo/vh_tierは新聞スナップショット{rid}.cv.jsonのaimをディスク経由で読む(別タブ=別セッションのため。SRA未解析なら判定スキップの案内)。③既存の毎リラン自動write_keepは復活馬をunion保持に変更(ボタン後のリランで復活馬が上書き消失するバグを予防)。session_state key=kf_sent_sra_{rid}。

**Gate検証BT群＋severity校正(2026-06-24・Codexブラッシュ#3-8)**: ①**#5 danger_stack_backtest=severity校正**: 人気1-3の複勝残差 severity0:+0.039(z17.3)/1:±0/2:**-0.054(z-2.10)**/3+:小標本(n21)。**severity≥2=軸不可は妥当・severity1は±0で完全消し不要**と確定(cheap-field=重不良1番/道悪FADE/牝冬春。単独はどれもz<2、stackで効く)。②#6 pair_gate_backtest=馬連/馬単の軸Veto前後ROIほぼ不変(79.6→79.8/77.6→77.4)。severity≥2の危険1番が稀(~0.6%)で軸入替頻度低→Vetoは稀な明確危険馬の安全装置でROIは動かさない(馬連馬単は控除を抜けない参考ツール)。③#3 trio_gate_ticket_backtest=決着タイプtier別実3連複: 本線向き的中54.9%/ROI81.2%/トリガミ46.7%/連敗7、中立41.3%/79.2%/連敗17、②16.5%/83.5%/平均5063/連敗44。ROI全<100%(控除)だがtierで的中/配当/トリガミ/連敗が住み分け=資金設計根拠。④scanner_priority_backtest --ablate(axis/danger/value/lean)でGate要素分解可(lean無効で買いtierのfav信頼度↑②型率↓=leanが②荒れを買いに広げる)。⑤#8 money.Ledgerにgate_status/lean/severity列+roi_by_gate()、BetSyncにGate別ROI表+記録タグ。⑥馬場コードoff-by-one(Codex BTの0=良ズレ)を value_scanner.baba_code_to_label()共通化で修正(smokeで1→良/4→不良)。**未整合(要対応)**: ③Gateがapp.py inline(_play_score)とcore(scanner_priority)で二重化→app.pyをcore呼び出しに一本化すべき(canonical drift)。
