---
name: project_nar_recall_proportional
description: NAR用recall@N比例化。中央のBattleScore乖離セーフティネット(固定top3/top7)をNARは出走頭数比例に分岐
metadata: 
  node_type: memory
  type: project
  originSessionId: b85681ee-81a0-4031-a84d-ca3e3c82da92
---

app.py内「🛡️ BattleScore乖離セーフティネット」(強適Ranking Table直下、[[kyoteki-score-rebuild-goal]]の
「勝ち馬を上位7頭以内に」recall@7目標を実装した箇所)を、NAR(地方競馬)向けに出走頭数比例化した(2026-07-02)。

**背景**: [[kyoteki-score-rebuild-goal]]の目標=BattleScore上位3頭(≈JRA16-18頭立ての3/16〜3/18)が
予測スコアの上位7位圏外に落ちたら7位ラインまで引き上げる、というrecall漏れ防止ロジック。
これはJRA-VAN由来ではなくcalculator.py(BattleScore/Projected Score)ベースなのでNARでも動く前提だが、
出走頭数が少ないNAR(8〜12頭立てが多い)では固定「top3/top7」が相対的に緩すぎる
(7/10頭=70%はほぼ全頭を含めてしまい安全網として機能しない)。

**実装**: race_id(4-6桁目)がNAR(jyo>10)の場合のみ、
- seed(BattleScore上位何頭を監視するか) = round(出走頭数 × 3/16)
- line(引き上げ先の目標ランク) = min(出走頭数, max(seed+1, round(出走頭数 × 0.4)))
に切り替える。**中央(JRA)は`seed=3, line=7`固定のまま完全に不変**(ユーザー指示:
「中央の最適化データはいじりたくない」)。

**検証**: JRA側は全出走頭数(3〜18)で(3,7)が変わらないことを確認。NAR 10頭立てで
seed=2, line=4となり、ユーザー例示(「10頭ならランク4位内」)と一致。実データ(BattleScore/
Projected Scoreのdiff)でも該当馬が正しくランク4位ラインまで引き上げられることを確認済み。

**Why:** [[kyoteki-score-rebuild-goal]]の中核目標(勝ち馬を上位N位以内に汎化)をNARにも
適用する際、固定順位でなく出走頭数比例が本質的に正しいスケーリング。JRA側の既存挙動・
最適化済み数値には一切手を入れない設計。

**How to apply:** 将来NAR側でLTRモデル的な独立最適化をやる場合も、この「頭数比例の
recallターゲット」という考え方が再利用できる(ただしjravan.dbにNARの学習データが
無いため、build_ltr_model.py同様のLTR再学習は別課題)。

**🛟ボーダー残し(消去エンジン)のNAR検証(2026-07-02)**: 「半分カット」(`_keep=(n+1)//2`)は
既に頭数比例(50%上限丸め)で中央/地方の区別不要。固定なのは戻す頭数の上限「+3」のみで、
これは中央のscripts/keepmore_backtest.py(jravan.db・JRA限定)で「+1〜+3は人気補正残差が
プラス(z=1.97/3.19/1.84=過小評価)」と検証した数字。NARで同じ検証をscripts/nankan_keepmore_backtest.py
(大井261レース・人気番号別実測率を基準の代理指標=オッズデータがnankankeibaに無いため)で
実施したところ、**+1〜+4いずれも残差z≈0(+0.12/-0.15/+0.24/-0.27)**で中央のような
過小評価(妙味)は確認できなかった(ただし負でもない=単純な取りこぼし防止としては機能)。
→ **数値(上限3)は変更せず維持**(cut_zone-1で頭数に応じ自動的に絞られる既存ロジックで十分)、
**UI文言のみ変更**: NAR時は「妙味」でなく「recall安全網」という位置づけに修正(app.pyの
🛟ボーダー残しslider help/summaryキャプションを`_kf_is_nar_sn`で分岐)。

**Why:** JRAで検証されたエッジ(ボーダー残しの過小評価)をNARにそのまま謳うのは誤り
(このセッション全体を通じた教訓=JRA検証済みシグナルはNARで別途検証しないと信用できない)。
今回は実際にNARデータで検証し、エッジは無いが安全網としては害もないと確認した点が価値。
