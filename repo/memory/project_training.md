---
name: project-training
description: 調教(追い切り)分析。Single Race Analysisに調教セクション追加(展開マップと時系列オッズの間)。評価A-Dは既存scrape
metadata:
  node_type: memory
  type: project
  originSessionId: 5e89769b-3184-403b-8fde-01496f4cfa45
---

調教(追い切り)機能（2026-06-15開始）。ユーザー要望: 各馬の調教情報を表示→数値化→加算ボーナスで予測活用。

**⚠️ 2026-07-14 更新（下の「重要な前提」は古い）**:
- **Phase2のJV-Link取り込みは実行済みで、jravan.db に `training` テーブルが存在する（505,374行）**。
  列 = ketto_num / center(0=美浦,1=栗東) / cho_date / cho_time / t4f / lap_86 / t3f / lap_64 /
  t2f / lap_42 / lap_20（すべて1/10秒単位）。**加速ラップは計算できる**（lap_42 - lap_20）。
- **ただし現時点では検証不能**（`scripts/accel_lap_backtest.py`・全項目 |z|<1）。理由は3つ:
  ① 期間が **2025-06-10〜2026-06-14 の1年分だけ** → train/holdout の2窓検定ができない（trainがn=0）
  ② レースに紐づくのは全出走の **2.1%**(39,190行) しかない
  ③ **追い方(一杯/強め/馬なり)とコース種別(坂路/CW/W/ポリ)の列が無い**。ラスト1Fの中央値が
     15.4秒・8割が14秒以上＝大半が軽いキャンターで、「最終追い切りで一杯に追った時の加速」を
     切り出せない。効果が出なかった最大の原因はこれの可能性が高い。
- → **否定ではなく保留**。再挑戦の条件と手順は `saved_logic_notes.json` の
  「調教の加速ラップ（保留・データ待ち）」に格納済み。ウッドチップ(WOOD)は依然未取り込み。
- スピード指数は `core/corrected_time.py`（同日同コース偏差の較正タイム）が実質の自前指数で
  検証済み（[[verified_corrected_time]]）。新指数にPCI/展開ロスを混ぜてはいけない（両方エッジ無し）。

**（以下は2026-06-15時点の記録・①は上記のとおり解消済み）**
- ~~**jravan.db に調教データは無い**~~（テーブルは races/results/payouts/horses/odds/race_wind のみ）。JV-Data の坂路(SLOP)/ウッド(WOOD)調教 record は未取り込み。
- **netkeiba 調教ページは既にスクレイプ済**: utils/adv_fetch_helper.py の oikiri.html 取得で **調教評価A-D → TrainingEval/TrainingScore(A100/B70/C40/D10)** を df に格納。予測スコアの「⏱️調教%」(Trainingウェイト)ボーナスに既に連動。**ただし評価グレードのみ。時計・脚色・コース・短評・併せ馬は未取得**。
- **過去の調教蓄積が無い→調教ボーナスはバックテスト不可**（風・クッション・H2Hと同じ立場）。検証できないので「表示＋theory/advisory」止まり。

**Phase1 実装済(2026-06-15)**: app.py の展開マップと時系列オッズの間に「⏱️調教（追い切り）分析」expander追加。「🔄 調教を取得」ボタンで netkeiba oikiri を取得・session_stateにキャッシュ→表表示。
- type=3(全頭一発): 評価ランクA-D＋短評(キビキビ等)。core/oikiri.py の parse_oikiri_reviews/fetch_oikiri_reviews。
- type=1(タイムビュー): コース/馬場/乗り役/ラップ/分所/脚色。**netkeibaは無料で上位3頭しか時計を出さない**(残りは競馬ブック有料・JSスクロールでも増えない)。parse_oikiri_detail/fetch_oikiri_detail。

**【決着】調教評価A-Dは予測に効かない＝表示・参考用に降格(2026-06-15)**:
- scripts/oikiri_grade_backtest.py で中央重賞2021-2025・9,092頭をscrape→results結合→オッズ補正残差。
- 結果: **A=+0.009(z+0.55,有意でない)・B=−0.016(z−3.6***)・C=−0.023(z−3.3***)**。B/Cは有意に過剰人気。100Rで見えたA+0.029はノイズ(増やすと消失)。
- 対応: `.score_weights_main.json` の Training を 0.5→**0.0**(他ウェイト保持・可逆)。UIラベル「⏱️調教%(検証=予測力なし)」、A/B好評価successを「A参考(買い材料でない)」に変更。**[[feedback-catch-underrated-winners]] の方針=測ってから最適化に従い降格。** 風・H2H・調教時計と同じ「効かない」バケツ。

**Phase2 時計取得＝JV-Link坂路調教(HC)取り込みが最良ルート（2026-06-15実装）**:
- **JV-Data HC レコード = 坂路調教**。jvdata_layout.json に定義済(reclen60)。中身: トレセン区分・調教年月日・調教時刻・**血統登録番号(=results.ketto_num)**・4F合計(800-0M)・ラップ800-600・3F合計・ラップ600-400・2F合計・ラップ400-200・ラップ200-0(ラスト1F)。**全部0.1秒単位**。
- **過去分も取れる＝バックテスト可能**（netkeibaスクレイプ=現在のみ・評価グレードだけ、とは別格）。
- 実装: scripts/jvdata_parser.py に `parse_hc(buf)`、scripts/jvlink_ingest.py に `training`テーブル(PK: ketto_num,cho_date,cho_time)＋idx_training_ketto＋kind=='HC'ハンドラ追加。**32bit JV-Link環境で実行**: `python scripts/jvlink_ingest.py --dataspec SLOP --fromtime YYYYMMDDHHMMSS --option 1`（坂路の dataspec は研究/JV-Data仕様で "SLOP" の可能性大・--probeで確認。確定要）。
- **ウッドチップ調教は別レコードでjvdata_layout.jsonに無い→未対応**（レイアウト追加が要る。坂路から開始）。
- TARGET frontier JV: 独自ファイルは綺麗なAPI無し（読むのは脆い）。TARGETのデータ=JRA-VANデータなので、**JV-Link直結が正道**（既に稼働）。調教時計もJV-Data(HC)にあり自前取り込み可。CSVエクスポートは手動フォールバック。
- 次: ユーザーが32bitで一括ingest→jravan.dbにtraining蓄積→加速ラップ/偏差値化/終い評価＋調教セクションを実データで構築、ボーナスはバックテストして採用。
- スクリプト変更は未push（data/はgitignoreなのでDB自体は元からpush対象外）。app.pyの調教表示セクションはPhase1で追加済(展開マップと時系列オッズの間)。
