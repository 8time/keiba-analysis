---
name: project-jockey-jv
description: 騎手分析ProをJRA-VAN(jravan.db)直集計で強化。core/jockey_jv.py新設。連敗ストリークは予測に効かない(検証済)
metadata:
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

騎手分析Pro強化（2026-06-14）。既存は core/jockey_analyzer.py(netkeibaスクレイピング・直近3ページ)＋utils/jockey_stats_db.py(別DB data/keiba.db・要インポート)。新たに **core/jockey_jv.py** を新設し jravan.db(30年283万走) を直接集計。

**重要な検証結果（scripts/jockey_backtest.py）**: 騎手の**連敗ストリーク・due比(そろそろ勝つ)は次走を全く予測しない**＝ギャンブラーの誤謬。オッズ期待値で馬質補正した残差が連敗0/1-2/3-5/6-9/10+で全て±0.001の平坦。調子(直近20複勝率)もhotで+0.0013とごく僅か。→ ストリークは「正直なラベル付き参考表示」に留め、予測には skill/相性(コース・黄金ライン・USM)を使う。

**core/jockey_jv.py（jockey_nameで名寄せ・before_keyでリーク遮断）**:
- J1 `jockey_base_stats`(全体/場/距離/オッズ帯の勝率連対複勝・単回収)
- J2 `jockey_horse_combo`(騎手×馬,ketto_num) `jockey_trainer_combo`(騎手×調教師=黄金ライン,trainer_code) `jockey_change_signal`(乗替・鞍上強化)
- J3 `calibrate_odds_expectation`(オッズ帯別実勝率) `usm_calibrated`/`jockey_usm`(人気以上に走らせる実力=USM)
- 調子 `momentum`(連敗/圏外連続/勝ち間隔/due比/hot/固め打ち) `losing_streak_leaders`(連敗中の騎手ピックアップ)
- J5 `jockey_factor`(場相性・実力・調子→馬スコアへ掛ける暫定係数mult。強さはJ4で較正前提)

**app.py**: 騎手分析Proに新タブ「🔥JRA-VAN版」追加(既存タブは温存)。連敗ピックアップ表(誤謬の警告付き)＋レースID入力でフィールドの騎手指標テーブル(全体/場/黄金ライン/コンビ/USM/騎手係数/調子)。レースは jravan.db に race_id があれば entries(jockey_name/bamei/trainer_code/ketto_num)を直接取得しbefore_key=race_keyで算出。未取り込みレースは案内表示。

jravan.db: results に jockey_name/trainer_code/ketto_num 100%充足。idx_results_jockey/ketto 既存で高速。データは2026/6/7まで。
オッズ帯別実勝率: ~3.0倍=37.9% / 3-10=14.6% / 10-30=5.0% / 30~=0.9%。
[[catch-underrated-winners]]の「人気より好走=実力」はUSMで数値化済み。

**J4検証(scripts/jockey_skill_backtest.py・各騎乗直前の状態で層別・オッズ補正残差)**:
- **黄金ライン(騎手×調教師 連対率)が最強**: 40%以上で 勝ち残差+0.020/連対残差+0.027(n=3196)＝明確に人気以上。30-40%でも連対+0.008。→ jockey_factor で40%+:×1.07/30-40%:×1.035。表示は🥇🥇(40%+)/🥇(30-40%)。
- **USM(複勝)は弱いが一貫**: <90で複勝残差-0.011(沈む)、110-120で+0.007(上振れ)。→ factorに (USM-100)/100*0.12 を±[-0.05,+0.04]で反映。
- **連敗/due/調子hotは残差ほぼ平坦=予測力ゼロ→jockey_factorに不採用**（表示のみ）。
- jockey_factor は USM＋場相性＋黄金ラインのみで構成（証拠ベース）に改修済み。trainer_code と expected(=calibrate_odds_expectation) を渡して使う。

**J5統合（2026-06-14・馬スコア×騎手係数）**:
- `resolve_horse(bamei)`（馬名→最新ketto_num/trainer_code）と `jockey_factor_by_name(jockey,horse,...)` を追加＝ライブ(netkeiba名)から黄金ライン/コンビを引ける橋渡し。
- app.py 主強適テーブル直後(≈3749行)に新expander「🏇騎手係数込み 総合スコア(J5)」を追加（既存テーブルは非破壊）。騎手影響率スライダー(0-150%,既定100)で `騎手込みスコア = Projected Score × (1+w*(mult-1))`。順位変動・黄金ライン🥇🥇表示。騎手係数はレース単位でsession_stateキャッシュ(スライダー高速化)。期待値表は '_jj_expected' 共有。
- 較正方針: 強適スコアはnetkeiba由来でオフライン再現不可のため「強適×騎手の比率」は厳密バックテスト不可。代わりに**構成要素(黄金ライン/USM)を残差で実測**し、その測定エッジに合わせて係数multを保守的設定→影響率100%が既定、ユーザーがスライダーで調整。
- scripts/jockey_factor_calib.py は合成mult帯別の残差検証（重く時間かかる）。

**trainer_code='00000'プレースホルダーバグ修正(2026-07-02)**: jravan.db全2,880,928行中
1,012,764行(35%・142,667頭)が`trainer_code='00000'`(調教師情報未記録の穴埋め値)を共有。
`resolve_horse()`がこれをそのまま返していたため、全く違う馬・違う調教師同士が
`trainer_course_winrate`/`trainer_overall_winrate`で同一の無意味な集計(例: n=6777走/勝率8%)
にヒットし、強適Ranking Tableの「厩舎(ランク-当コース勝率)」列で複数の異なる調教師が
同一の"?-8%(6777)"を表示するバグとして発覚(ユーザー報告のスクリーンショットで発見)。
`resolve_horse()`内でtrainer_code='00000'をNoneに丸めるよう修正(ketto_numは有効なので残す)。
NAR馬でJRA交流重賞に出走歴がある場合(帝王賞出走馬等)に特に頻発(NAR所属馬のJRA側
trainer_codeが未記録のケースが多いため)。

**騎手力(JPower)偏差値の新設(2026-07-03・ユーザー「騎手のみの力をそのレース時点で数値化したい」)**:
- 考え方: オッズ=馬の質＋市場の騎手評価を織込むため、**オッズ期待値に対する複勝上振れ(USM)が『騎手のみの寄与』に最も近い**。
- 検証(scripts/jockey_power_backtest.py・時系列ストリーム・リーク無し): 直近500騎乗の縮小USM(疑似100騎乗を期待値通りで追加)五分位→ train2021-24で単調(-1.02pp→+0.78pp・z-4.5〜+3.5)、**holdout2025でも方向維持(Q4+0.75pp z+2.0/Q1-0.72pp)=実力として持続**。ただし広がり~1.8ppと効果量小=大半は織込み済み→**予測器でなくレース内の騎手比較表示**。
- 実装: `jockey_jv.jockey_power(name, before_key)` → {'jpower':偏差値50=平均, 'usm', 'rides'}。較正定数 JPOWER_MEAN=99.63/SD=8.71(2021-24騎乗重み)・期待値2016-20較正をハードコード。実測=ルメール59.5/戸崎53.0/武豊50.2/横山武49.6。
- 配線: 騎手Proのレース単位表(before_key=そのレース時点)・NARフォールバック表・One-Pushランキング表(resolve_jockey_nameで名寄せ)に『騎手力』列。**限界: NAR専業騎手はjravanのNARオッズ全nullでUSM計算不可→'-'**。
- **強適テーブルにも配線(2026-07-03)**: SRA強適Rankingに『🏇騎手力(乗替)』列=今走JPower＋前走騎手(horse_recent_context.prev_jockey)との差分表示 `60(▲+9)`(▲≥+3強化/▽≤-3弱化/→同等)。**差分自体のエッジは未検証=表示のみ**とhelpに明記。session_stateでレース単位キャッシュ(jpower_col_{race_id})。

**resolve_horse同名馬誤マッチバグ修正(2026-07-02)**: `bamei`だけの一致検索だったため、
2歳新馬などデビュー馬が同名の引退済み別馬にマッチしていた(例: 2026年デビュー「イントゥザライト」が
2009年最終出走の同名馬のketto_numを誤取得、「スカイビーンズ」も2005年の別馬)。競走馬名は
引退後に再利用されるため名前だけでは別馬と区別できない。
修正: `before_key`未指定(=ライブ/現在レース用途)の場合のみ、マッチした最終出走の年が
DB内最新年から4年以上前なら「別馬」とみなし(None,None)を返すガードを追加。
バックテスト用途(before_key指定)はガード対象外(その時点で有効だった対応関係のため)。
現役馬(帝王賞出走馬等)への影響なし(回帰確認済)。
