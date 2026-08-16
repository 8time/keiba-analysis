---
name: verified_paddock_weight
description: パドック定量(馬体重/増減)は買い妙味ゼロ=fade側のみ。主観項目は履歴無しで検証不可。動画ML予測は時期尚早
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

「パドックで馬のここを見ろは回収率を上げるか」をユーザー規律(検証してから実装)で確認(2026-06-24・scripts/paddock_weight_backtest.py・2021-25 JRA平地 n≈28万・オッズ帯統制の複勝残差/z+単勝ROI)。

**結論=パドック定量(馬体重bataiju/増減zogen)で回収率は上げられない**:
- 増減: 大幅減≤-10 複勝残差-0.012(z-4.3)/大幅増≥+10 -0.008(z-3.2)/増+3〜9 -0.005(z-3.1)/維持-2〜+2 ≈0(+0.004 z3.0)。**正の妙味(z>+2)ゼロ・全部fade側か織込み済み**。
- 馬体重水準: 小型≤440 -0.012(z-6.9)・単ROI57.7%=強い負(危険)。中441-499≈0。大型≥500 残差≈0(織込み済・単ROI77.8%は控除なり)。
- 馬体重×増減: 小型×大幅減-0.031(z-5.4)/小型×大幅増-0.015(z-2.0)/大型×大幅減-0.020(z-2.6)=[[verified_stress_debuff]]の小柄×馬体減を再確認(消去向きfade)。
- 1-3番人気だけ複勝残差+(増減問わず+0.02前後)=人気馬の元々の過小評価であって増減そのものの差ではない(増減で住み分かない)。

**使い道**: 買い妙味でなく**消去/危険人気馬の補強**(小型・大幅増減のfade)のみ。これは既にstress_debuffで部分採用済み。

**パドック動画解析について(重要)**: 歩様/発汗/気配/毛艶/チャカつき等の主観項目は**履歴データが存在せずバックテスト不可能**=予測ロジックにできない(検証済みエッジのみの原則)。動画ML自動抽出も重いVision新ライブラリ要で[[CLAUDE.md]]の新lib禁止に抵触。**正しい順序=まず「パドック観察タグ台帳」(个人運用検証・lib不要・⑥回顧/[[project_elim_reasons_learning]]と同思想)で、自分のパドック観察タグ×結果のROIを蓄積→効くタグが実証できてから、そのcueだけ動画自動抽出**。upfrontの動画ML予測は時期尚早。関連:[[project_betsync_money]][[project_app_pipeline]]

**phase A 実装済(2026-06-24)**: 左メニュー「👁️ パドック解析」=core/paddock_ledger.py(lib不要JSON台帳 paddock_ledger.json・gitignore済)。**scene=paddock/training**でパドックと調教を同じ台帳に同居(調教動画も対応・検証はscene別に分離)。タグ=パドック24種(fade14/buy9/ctx2)＋調教20種(fade9/buy9/ctx2)＋自由メモ・source=manual/将来gemma。調教20種は調教資料(Elite_Training_Analytics・2026-06-24)の映像観察cueを反映=ゴール後余力t_after_goal/バテt_bate(資料の最重要)・加減速ラップt_accel_lap/t_decel_lap・併せ馬の勝負根性t_awase_strong・直進性t_yoroke・キックバックt_kickback・コース変更の罠t_course_switch。※資料の数値系(調教評価A-D=効かず[[project_training]]・外厩帰り/お帰り=織込み済み[[feedback_folk_signals_overbet]]・加速ラップ実数値=jravan.dbに調教ラップ無くBT不可)は実装せず、検証不能な主観cueのみ台帳化。各タグにTAG_HELP説明(「白い泡とは」等)。**画像/動画の任意添付**(save_media→data/paddock_media/・gitignore済)=手動タグの証拠＆phase BのGemma答え合わせ正解データ。記録→精算(着順+確定単勝オッズ)→tag_stats(scene別:複勝率/単ROI/平均人気/ベース比)＋verdict(極性は決め打ちせず実測判定:fade=複勝率-5pt以下で消しに機能/buy=単ROI≥100%で買い妙味/精算<MIN_SAMPLE20件はサンプル不足)。smoke 189件に組込。**phase B=Ollama/Gemma 4 12bの自動タグ抽出(source=gemma)を同台帳に入れ人の眼vsGemmaを比較**=台帳が貯まってから着手。Gemma 4 12B=2026-06-04リリース(私のカットオフ後・当初gemma3と誤記)・画像/音声/動画対応(encoder-free・16GB級ローカル)・Ollama対応(requestsのみでlib不要)・Apache2.0。動画解析の最終目標に動画対応が直結=phase Bはこれ一択。台帳は source='gemma' でモデル非依存=コード変更不要。
