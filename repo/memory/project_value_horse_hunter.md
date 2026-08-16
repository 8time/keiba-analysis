---
name: project-value-horse-hunter
description: 穴馬ハンター改修。v2モデル(2026-07)でrecall70%目標達成=holdout73.5%@precision1.84x。combo方式は帯内オッズ順序を捨てていたのが壁の正体。scripts/value_hunter_recall_v2.py
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

ユーザー方針(2026-07): 「穴馬ハンターがほぼ当たらない→妙味のある馬発見ツールへ生まれ変わらせる」。
穴馬(人気薄)と妙味馬(過小評価3着内候補)は定義が違うが混ぜてよい。

**研究(scripts/value_longshot_research.py・7番人気以下・直近3ヶ月+train2.5年・リーク無し)**:
ベース3着内率 train7.7%/直近7.2%。単体リフト(直近3ヶ月でも全有意):
🔵補正T +6.9pp(z23)/直近+7.9pp最強・🧬血統+5.3pp・🔥末脚+2.8/直近+3.8・🏃位置3以内+2.4/直近+3.5・
👑騎手+1.4/直近+3.0・🧬血統回収+2.8・⚡33+1.0(最弱)。
**combo(6シグナル同時発火数)は完全単調**: 0=4.1%(基準の半分)→1=7.2→2=9.9→3=13.1→4=18.8→5=20.0%。
直近3ヶ月も同型(0=3.4→2=9.7→4=14.6)。combo2+ z18.6/直近z7.1・combo3+ z19/直近z6.5。
→**不的中の原因=combo0馬(基準の半分)を弱い参考シグナルで拾っていた。妙味馬=combo馬**。

**実施済**: pages/anabaka_hunter.py の header caption + docstring に妙味馬/comboの説明を追記(名前は据置)。

**今後の予定(未実施)**: この機能を最終的にSRA(app.py ~6787-6855)の
『💀消し推奨馬(予測スコア下位30%)』『🎯推奨穴馬(Top Dark Horse)』2セクションを削除して設置。
表示はTop Dark Horseの st.warning カード形式(🐴{馬番}{馬名}・人気・根拠・予測スコア)に寄せる。
妙味馬の選出=7番人気以下(pop_threshold)をcombo降順で。combo2+を『妙味』、combo0を消し寄りに。
既存のbuild_edge_sets([[project_consensus_view]])のcombo/edge_reasonsを流用可能。
関連: [[verified_arare_signal_check]](6シグナルholdout)・[[verified_spurt_index]]・[[project_value_scanner]]。

**v2再現率アップ検証済(2026-07-06・Fable案件①完了)**: scripts/value_hunter_recall_v2.py。
連続量特徴LGBM(leak-free・fit≤2023/しきい値=val2024固定/holdout2025/直近3ヶ月)で
recall70%目標達成: holdout 73.5%@14.30%(基準1.84x)/直近 72.7%@13.56%(1.89x)・残差z+7.8。
精度1.35xを守れる上限はrecall≈0.88。combo≥2は同予算でモデルに全敗(52.8%vs66.9%recall)。
**重要な学び**: ①combo壁の正体=7人気以下を同格に扱い帯内オッズ順序を破棄+二値top3の崖。
市場のみ(オッズ昇順)でもrecall0.70@14.2%が出る=改善の主成分は市場情報→**儲かるリストではない**
(単勝効率的と整合)。②能力特徴のみ(市場抜き)でも11.8%=1.52xで目標超え。フル-市場=+0.5〜0.9pp(holdout)。
③「combo0は予測不能」は誤り=v2が56〜63%捕捉。④補正T/末脚の連続量化(上位40%)はtop3二値より
残差z安定(仮説1実証)。⑤パドック台帳0件で仮説4検証不能。
成果物: data/vh2_model.lgb+value_hunter_recall_v2.json+repo/value_hunter_recall_v2_curve.png+
repo/fable_report_value_hunter_recall.md(実装提案=精鋭recall0.5/広域網recall0.7の2段+combo0誤切り救済)。

**配線済(2026-07-06・ユーザー指示「両方(軽量を主・LGBMは過去検証用)」)**: 重いLGBMはライブ推論に
特徴量パリティ&レイテンシの脆いサブシステムが必要→**モデル不要の透明7特徴ロジスティックを本線に採用**。
scripts/value_hunter_light.py(fit≤2024/holdout2025/直近3ヶ月)で **recall70%@precision16.3%(2.09x)**・
combo≥2(52%@12%)を全域で圧倒・LGBM(73.5%@14.3%)にも匹敵。**係数はneg_log_odds0.88(市場支配)+
ct_pct0.41(補正T)が主、末脚/血統/combo/elim/位置はほぼ0**=Fable分解と一致。パラメータ=
data/value_hunter_light.json(git -f追跡・必須)。
配線先: core/value_hunter.py(prob/tier/score_race)。consensus_view.build_edge_sets が
ctfig/spurt/血統/combo/elim/オッズからvh_score算出し返す→integrate で🎯精鋭はcombo0・消去多でも
切らない救済。pages/anabaka_hunter.py に🎯精鋭(recall0.5)/🕸️広域網(recall0.7)の2段リスト+
『網羅リストで+EVではない』注記+vh_score降順ソート。smoke40関数。
**単勝EVとは意図的に非連携**(主成分が市場情報=儲かるリストではない・単勝効率的)。用途は複勝/ワイド/3連複の絞り込み。

**SRAの💀消し推奨/🎯Top Dark Horse置換=完了(2026-07-12)**: app.py SRA下部の2セクションを検証済みロジックへ置換。
- 💀消し推奨(予測スコア下位30%・未検証)→「✖消し候補(統合ビュー合議)」=_cv_resのkeshiグループ(消去クロス重複3+強気カット・救済済み)をそのまま表示。
- 🎯推奨穴馬(Top Dark Horse=適性Y≥60・未検証)→「🎯妙味馬(穴馬ハンター)」=7番人気以下×🎯精鋭をvhスコア降順、筆頭はst.warningカード(人気/オッズ/妙味スコア/根拠edge_reasons)+次点3頭+「+EVではない」注記。build_edge_setsのセッションキャッシュ共有。
- 残タスク(全てデータ待ち): ①パドック台帳蓄積→仮説4検証 ②オッズ時系列(scheduled_odds_recorder)蓄積→隠れ本命特徴の前向き検証 ③(任意)NAR専用係数fit。実装系の残は無し。
