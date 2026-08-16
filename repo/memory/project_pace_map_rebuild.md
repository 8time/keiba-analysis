---
name: pace-map-rebuild
description: 展開マップ（core/pace_map.py）をテン速力＋バックテストで再構築済み（Phase0-5完了）。最大の効きはコーナー履歴の条件・直近・8走加重
metadata:
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

展開マップ（core/pace_map.py）はユーザー評価「かすりもしない」だった。2026-06-13にPhase0-5を一括実装・較正完了。

**バックテストで判明した最重要事実（再チューニング時に必須）**:
- 4角順位の最有力シグナルは「**条件類似度（同馬場・距離±400m）×直近重み(0.82^i)×過去8走**のコーナー履歴加重平均」。これがベース予測力を spearman 0.436→0.46、先頭的中 0.23→0.29前後へ底上げ（最大の効き）。
- テン速力z-score・脚質コード・相互作用（ハナ確定/番手争い/スロー前残り）は4角"ランキング"へはノイズ範囲（seed平均でbaselineと互角）。ただし先頭(ハナ)予測の小改善＋マップ表示/ハナ確定/ペース判定の明瞭化に有効なため軽め(w_ten0.25等)に採用。
- → **コーナー履歴の重みを薄めると即劣化する**。相互作用を強めても精度は上がらない。

**実装(core/pace_map.py)**: `_parse_jv_time`・拡張`fetch_jv_profiles`(ten_speed/nige_rate/kyaku_pos/front3_rate追加, surface/distance/before_key引数)・`build_pace_context`(forward度・pos4・leader・pace分類)・`predict_corner_order`・`estimate_pace_map`(surface/wind引数, フェーズ進行をpos4へ寄せる)・Phase5風(`wind_effect`/`wind_weight_bonus`/`fetch_wind`Open-Meteo)。チューニング定数=`_PACE_TUNE`。
**バックテスト基盤(core/pace_backtest.py)**: `collect_cases`(DB重処理1回)→`evaluate(tune)`でsweep。`idx_results_bamei`インデックスを自動作成（恒久・fetch高速化）。

**風(Phase5)の検証結果＝ほぼ無効（2026-06-14）**: Open-Meteo過去アーカイブ(ERA5・無料)で発走時刻の風を取得し race_key に結合（scripts/wind_backtest.py、data/jravan.db の race_wind テーブルにキャッシュ・1500R分）。直線方位へ投影した直線風成分(straight_tail)と勝ち馬4角位置の**相関 r=+0.049＝ほぼゼロ**、バケツ比較も追い風/向かい風で前残り率に有意差なし。→ wind_effect の位置補正magを0.10→0.03に縮小し「統計的根拠は弱い」と明記。風UI/情報表示は無料で便利なので維持するが、予測には効かせない。ERA5は10mグリッド値でスタンド遮蔽等の実地風とは差がある点は留保。
**app.py**: 展開マップexpander内でmax_runs=8・surface/distance渡し、風UI(selectbox+number_input)、ペース文脈サマリ(st.info)、describe_paceにpace_ctx。

**DB事実(jravan.db)**: 1996〜236,574レース・283万走。time='1330'→93.0秒(MSSt)。ato3f=334→33.4秒。kyakushitsu 1逃2先3差4追。1600m等はcorner1/2=0でcorner3/4のみ。race_keyは年先頭で辞書順=時系列順（before_keyリーク遮断に利用可）。

**直線=着順モデル（2026-06-13 追加・スプリングS で勝ち馬が直線最後方に出た不具合の修正）**:
- 旧来の「直線フェーズ=4角位置(pos4)」は実着順との相関わずか0.16で最悪。これが後方差し勝ち馬を最後方に描いた原因。
- `predict_finish(horses,profiles,ctx,extras)` を新設。直線=到達(着順)位置を **w_pos4(0.5)・w_kick(0.6 上がり3F決め手)・w_apt(0.5 適性)・w_power(1.0 総合力)** の合成＋「4角離れすぎ&決め手平凡なら届かない」reach補正で算出。`estimate_pace_map(extras=)` の直線で使用。チューニング定数=`_FINISH_TUNE`。
- 着順バックテスト(evaluate_finish, 250R): spearman vs実着順 pos4のみ0.16 / 能力のみ0.38 / **finish 0.39**、勝ち馬的中 0.21→0.28。後方差し勝ち40Rで勝ち馬の直線描画順位 平均9.35→5.20番手、前方5頭以内描画率18%→55%。
- `fetch_jv_profiles` に `finish_hist`(過去相対着順=能力proxy・条件直近重み)追加。
- **app.py が extras を渡す**: 強適Ranking Table の AvgAgari(決め手)・Suitability(Y)(適性)・BattleScore(総合戦闘力)を符号調整して {umaban:{kick,apt,power}} に。これら生データ列は展開マップ描画(1927行)時点で calculate_battle_score/calculate_n_index 由来で既に df 上にある（`Projected Score` は後段算出のため未存在）。
- apt(適性)weight は JV単独では検証不可（均一=定数オフセットでランキング不変）。ライブの Suitability で効く想定で保持。

**人気/単勝オッズの導入（2026-06-13・フェブラリーSで人気3の2着馬14番が直線後方すぎた件）**:
- 着順バックテスト(300R)で **人気(ninki)単独が最強の単一指標**: spearman 0.55・勝ち馬的中0.36（能力のみ0.38、4角のみ0.16を圧倒）。「みんなが見る指標」はやはり当たる。
- `predict_finish` に `w_pop`(人気項)追加。`extras['pop']`（app=Popularity/Odds, BT=ninki。小さいほど上位人気）。`_FINISH_TUNE` 既定 w_pop=1.4（全体の約40%）。
- **ジレンマ**: w_popを上げるほど精度↑だが「人気のみ」に漸近し穴馬(アウダーシア人気8で1着)を前に出せなくなる。適性・決め手で穴を拾う余地を残すため40%に抑制。w_pop=1.4で finish spearman 0.526（人気のみ0.55に肉薄）。
- 効果実証: 後方差し勝ち馬の直線描画 平均9.33→3.85番手・前方5頭率17%→75%。人気1-3かつ3着内の馬は平均2.41番手・前方5頭率95%。
- app.py `_pm_extras` に Popularity(なければOdds)を pop として追加済み。

**展開妙味アラート（2026-06-14・ジューンSでタシット12人気2着を取りこぼした件→[[catch-underrated-winners]]直結）**:
- タシットは実は先行馬（過去通過順ほぼ2-3・脚質コード2）。展開マップ直線で後方なのは finish モデルが「12人気＋近走凡走＋平凡な上がり」で消したから。Vエリア・マトリクスでは正しく内×前で勝ち馬カネラフィーナと共に該当していた。
- 検証(400R): スローは pos4(4角位置)の対着順相関0.21（ミドル0.11）で前残り実在。前にいた馬の3着内率はスロー38%>ミドル/ハイ30%。だが**「スロー＋前＋人気薄(下位半分)」の3着内率は約9%**（穴の本質＝市場が約1%評価の馬）。人気は全ペースで相関0.54-0.57と最強。
- 実装: app.py Vエリア表示直後に「🔍展開妙味アラート」（金縁・グラデの目立つHTMLボックス）。条件=**Vエリア該当 ∧（predict_finishの着順予想が後ろ半分 or 5番人気以下）**。predict_finishの順位＋df Popularity で判定。9%バケツである旨を明記し複勝・ワイド向き穴印として提示。
- **Cコース替わりの内有利バイアス/クッション値は jravan.db に無い**（東京芝track_code全'11'）。日替わりバイアスはVエリアの馬場バイアス手入力で対応する設計。
- track_code は A/B/Cコースを区別しない。

既存実装: 差し切り限界(sashikiri_table・4角pos4ベースで整合)・Vエリア3×3(build_v_matrix)・コース諸元(get_course_layout)。[[kyoteki-score-rebuild]]と同じ「測ってから最適化」。sweepスクリプトは scratch/sweep_pace*.py / sweep_finish.py / test_finish_demo.py。

**荒れ予測の検証(2026-06-17, scripts/chaos_predictor_backtest.py + chaos_prerace_backtest.py, 27,594R/2021-25)**: ユーザー要望=「トラックバイアス/ペースチェンジ指数で荒れ(勝ち馬ninki≥6)を予測→荒れレースをサーチ→②で賭ける」。ベース荒れ率13.4%。**結論=安価な事前ペース予測ではエッジにならない**。
- ✅ **事後ペース(ato3f-mae3f, 後半-前半)は荒れと本物の相関**: 超スロー11.5%→超ハイ21.9%、しかもオッズ層固定でも効く(堅層 ハイ14.6% vs スロー9.6%=層内1.27)。ハイペース→荒れはオッズに織り込まれていない真の情報。**だが事後情報で予測に使えない**。
- ❌ **習性脚質(過去走最頻kyakushitsu)からの事前ペース予測はシグナル消失**: 想定前づけ比率(逃げ+先行/判明馬)はリフト0.89〜1.10で単調性なし。想定逃げ馬数も効くのは堅層のみ(逃3+で1.23)、**②を賭けたい中/荒層では1.06〜1.09の横ばい**=既にオッズに入っている。
- ❌ **トラックバイアス(クッション値/含水率)は荒れにフラット**: やわ18.9/標準16.8/かた18.8%=単調性なし。荒れ予測子として無効。※クッション値/含水率は実は track_cond テーブルに2021〜収録済み([[trackbias]]の「未収録」は誤り)。収録されていても荒れには効かない。
- ❌ ★サーチ候補[中/荒層×14頭+×前づけ多]=23.9%(1.78倍)に見えるが、寄与はほぼ全部"1番人気が薄い"オッズ要因(荒層単体で24.3%)。前づけフィルタ寄与≒0。[[project-trio-engine]]の trio_selector「②は最荒層でも22%止まり」の再発見で②を黒字化しない。
- **判断(初版)**: crude版はライブ非配線。ペース自体は本物→ボトルネックは予測精度→テン速力で精密化を次段(Path1)へ。

**Path1=テン速力ベース事前ペース予測 検証成功＆配線(2026-06-17, scripts/pace_predict_backtest.py, 22,721R/2021-25)**: 脚質"コード"でなく テン速力=実時計((走破タイム-上がり3F)/(距離-600)*600・小=テン速い)で各馬の前進力を測り、出走馬の前方TOP3の事前テン速力(条件×直近0.82^i加重・前5走)を距離馬場内z化(符号反転=高いほどハイ想定)。**2段検証クリア**:
- STEP1(当たるか): 予測ペースz vs 実前半ペース(mae3f)z 相関 **r=+0.226**・単調(超スロー予想→実-0.28/ハイ予想→実+0.31)。crude脚質版のフラットと違い実ペースを当てている。
- STEP2(効くか): 1番人気オッズ層を固定しても荒れ率を動かす。ハイ予想の層内リフト=**堅1.13/中1.11/荒1.03**で、**事後(完璧)ペースの天井 堅1.12/中1.15/荒1.06 にほぼ肉薄**。crude版(中/荒で横ばい1.06-1.09)を明確に超えた。topk=3が最良(topk2は中1.09で劣化)。
- **限界(正直に)**: 事後ペースの天井自体が中程度(中層リフト~1.15)＝ペースはオッズを超えるが大きくはない。荒れ率を中層17→19%程度押す中程度エッジ。②の的中を保証はしない=②サーチを"少し賢く"する軟フィルタ。荒層では弱い(既に荒れてる)。
- **成果物**: `core/pace_map.predict_pace_intensity(profiles, distance, surface)`→{z(高=ハイ想定),label(ハイ想定/ややハイ/標準/スロー想定),pred_pace,n}。基準ノルム=`scripts/build_pace_norms.py`が`data/pace_norms.json`生成(13バケット・(馬場,距離band)別の前方TOP3テン速力mean/sd・2019+)。profilesはfetch_jv_profilesにsurface/distance/before_key渡しで履歴条件を揃えること。
- **配線(app.py)**: 展開マップ節(2491付近)で予測し`st.session_state['_pace_int_{race_id}']`保存(プロファイル既取得で実質無料)。🎯3連複エンジン節(4718付近)で読み、**ハイ想定→「②穴妙味狙い向き」/スロー想定→「本線向き」**のヒントst.info表示。本線vs②妙味の選択を補助する位置づけ。穴選別自体は引き続き🔥末脚シグナル([[project-trio-engine]]②妙味)。
- **Scanner配線完了(2026-06-17)**: `core/pace_map.fetch_ten_speed_profiles(names, surface, distance, max_runs=5, before_key=None)`新設=複数馬のテン速力を**1クエリ(bamei IN)で一括取得**({name:{'ten_speed'}}・fetch_jv_profilesの馬ごとSQLを回避・履歴加重はノルムと一致)。app.py Race Scannerループ(6383付近)で各レース予測→`value_scanner.race_value_score(...,pace_z=)`に渡す。race_value_scoreに**pace_z引数追加**(ハイ想定z≥0.7=+9/ややハイ≥0.2=+4/スロー≤-0.5=-6・フルゲート+12等と同オーダーの中程度)。Scanner各レースヘッダに**🌀ハイペース想定バッジ**、中/荒オッズ層(fav≥2.5)×ハイ想定で**「②穴妙味向き」**表示=ユーザーの「荒れレースをサーチ→②」を実装。穴選別は🔥末脚([[project-trio-engine]])。
- **リーク注意**: fetch_ten_speed_profilesはbamei一致の全過去走を使う。ライブ(未来レース=DB未収録)はリークなし。jravan.db収録済みの過去レース再スキャン時は当該race_keyを履歴に含むため`before_key`指定で除外(スモークで-0.06↔-0.2と整合確認)。DB surfaceは正UTF-8('芝'/'ダート'/'障害'・mojibakeは表示のみ)。
- **Single Race配線も完了**: 展開マップ節でfetch_jv_profiles由来の_pm_profilesから予測しsession保存→3連複エンジンでヒント表示(履歴深度がノルムのk=5とややズレるがtop3平均は0.82^idx減衰で安定・許容)。

**強適テーブルの🚦展開フィルター 改修(2026-06-14)**: 旧版(core/race_analysis_tools.py DeployScore=位置取り×PCIマッチ×密集、前崩れ理論)は『当たらない』。原因=未検証・予測の掛け算でノイズ・PCI致命的ミスマッチ0点の崖。バックテスト(scripts/deploy_filter_backtest.py・121R)で判明: build_pace_context の pace+pos4 から定義した展開恩恵スコアでも、**ペース有利な極端ポジ(前残り馬等)は複勝残差マイナス(高0.6-0.75=-0.031)＝既に人気で買われ妙味なし**。唯一プラスは**好位〜中団(恩恵0.4-0.6)=複勝残差+0.024**。→ app.py フィルターを検証済みエンジン版に置換(≈3331行)。`_pm_ctx`(pace+pos4)から恩恵算出し「🎯好位妙味ゾーン(0.40-0.62)」「人気先行ゾーン除外」を提供。旧理論オプションは廃止。
**教訓**: 「ペースに恵まれる馬」≠「妙味」。市場は展開有利を織り込み済み。エッジは過小評価の好位ゾーンにある(raw勝率と回収のズレ)。

**Vマトリクス精度監査(2026-06-18・ユーザー「Vマトリクスも精度上げたい」①→④順)**: build_v_matrix(core/pace_map.py:1061)の3軸を検証し『描画は既に最良の検証済み指標で組まれている／買い妙味は無い』と確定。
- **②Y軸(隊列)=変更しない**: 現状Y=`prof['ten']`(過去走の最初の有効コーナー位置平均)。「実タイムten_speedに替えれば精度UP」は誤り。scripts/vmatrix_pos_backtest.py(2023-25・10,587R)で今走corner1相対位置との**レース内ρ: 習性コーナー位置+0.474 > ten_speed+0.232 > ブレンド+0.440**。座る位置の予測はコーナー位置(=実現位置そのもの)が最良で、ten_speedはペース予測専用([[pace-map-rebuild]]Path1)。プラウシブルな改悪を未然回避。
- **③ペース(v_row)=既に検証済み源**: _vm_pace_autoは`_pm_ctx['pace']`=predict_pace_intensity(検証済テン速力版)から供給済み。変更不要。
- **①X軸/④馬券**: X軸baba初期値は当日逆算バイアス(`_tb_emp_bias`)優先。だが[[verified_emp_bias_danger]]で『有利ゾーンの馬を買う=priced-in(残差≈0)』を確認。逆張り(外有利日×内枠人気馬=危険人気馬)のみ検証済エッジでSRAエビデンス表に配線済(track_bias.danger_popular_inner)。
- **④実装(2026-06-18)**: 🏆Vエリア該当馬の直下に『Vエリアは"地図"であって"買い"ではない／妙味は🔍末脚アラート(人気薄×末脚・検証済ROI111%)と⚠危険人気馬で拾う』旨のキャプション追加(app.py ~2773)。Vエリア×人気薄も検証で過剰人気(-1.96pp)のため買い機能は足さない。
