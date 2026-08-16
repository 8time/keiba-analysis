---
name: verified_emp_bias_danger
description: 当日バイアス逆算は順張り妙味ゼロ(priced-in)。逆張り=外有利日×内枠人気馬の危険人気は弱いfade。pooled z-3.8は楽観的でholdout2025 z-1.77/2026崩落(カード2却下)
metadata:
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

Vマトリクス精度向上①=当日バイアス逆算(track_bias.empirical_bias)の妙味検証(scripts/tenkai_bias_backtest.py・2021-25・tosu>=8・n=221,454・枠umabanのみ事前確定で使用/corner4は集計側のみ=リーク無し)。

**順張り(バイアス合致馬を買う)=妙味ゼロ＝priced-in（再実装禁止）:**
- 内枠有利日×内枠馬: 残差+0.02pp(z+0.05)。confident日(n>=4)ではむしろ-0.82pp。
- 外枠有利日×外枠馬: +0.41pp(z+1.42)非有意。合致全体+0.25pp(z+1.13)。ROI全群71-75%=控除率負け。
- → Vエリア該当/有利な枠を「買い」シグナルにするのは死。[[verified_tenkai_priced_in]](展開恩恵)と枠軸でも同型確認。

**逆張り(消去)=危険人気馬(ただしout-of-sampleで減衰・弱いfade):**
- **はっきり外枠有利と判明した日(lane_label=='外有利',confident)に内枠を引いた1-3番人気馬**: 複勝率が期待を下回る。
- ⚠**当初のpooled(2021-25一括)z-3.8は楽観的な in-sample 値だった**(2026-07-02にtrain/holdout分割で再検証・scripts/intraday_bias_backtest.py)。train2021-24=fade全体z-2.31/confident z-3.09だが、**holdout2025=fade全体z-1.77(ゲート-2.0を外す)/confident z-2.44**、**confirm2026=全群z≈0(-0.57/-0.39)に崩落**。ROIは全区間65-75%(控除ライン割れ=過剰人気の傾向自体は一貫)。
- **結論: 弱いfade(消し寄り)ではあるが、新規に強化配線する水準ではない**。既存danger_popular_innerは相手不安の可視化として残すが、これを軸/穴の強シグナルにはしない。カード2(日内バイアス realtime版)は**採用ゲート不通過で却下**。
- 非対称は成立: 内有利日×外枠の人気馬は非有意。「外有利日×内枠人気馬」のみが弱く効く。

**実装(2026-06-18):** track_bias.`danger_popular_inner(emp_bias, umaban, tosu, ninki)` 追加(外有利日×内枠×1-3人気でフラグ)。app.py SRAエビデンス表で`_tb_emp_bias`がある時のみ表示。**ライブ制約**: 当日バイアスは対象レースがjravan.dbにある時だけ算出(同日前半R結果が必要)→当日取り込み時/教材検証時に機能、無ければNoneで非表示。

**How to apply**: 当日バイアスは「合致馬を買う」には使わない(priced-in)。使うなら逆張りの危険人気馬消去(外有利日×内枠人気馬)のみ。これは相手絞り/軸不安の可視化用で、単体で穴妙味は出ない。[[project_elimination_engine]][[project_trackbias]][[project_pace_map_rebuild]]。
