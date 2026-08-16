---
name: verified-rotation-weight-demerit
description: 人気馬×中9週+ローテ=軸信頼度減点(z-5.6・ROIフラット)を検証しdanger_gateソフト理由に配線。13番人気以下の低EVも数値化。斤量±3kg変動は対称で弱い。layoff未配線バグも修正
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

NotebookLM資料「捨てる技術」の主張検証(2026-07-11・CSV基盤+実配当)。

**Why(実測)**:
- 人気馬(1-4番人気)×休養63日+: 複勝率残差 63-179日=-1.6pp(z-5.6)/180日+=-6.2pp(z-7.5)。
  **複勝ROIは81%台でフラット=市場織込み済み→fade(儲け)不可・軸信頼度の減点のみ**。
- 13番人気以下: 単勝ROI 13-15位=57%/16+=45%(7-9位は76%)=大穴の過剰人気は本物。
  エンジンは元からana_hi=12で対応済み(閾値13は妥当・追加作業なし)。
- 斤量±3kg変動×人気馬: 増も減も同じz-2.4/-2.5(対称)=「負担」でなく「条件替わり不確実性」。
  弱いので不採用。減量騎手乗替はDBに減量データ無く検証不能。
- 資料の他の主張はすべて既知: EV>1(単勝効率的で実務不成立)/黄金比46.8%(実測46%一致)/
  人気薄頭全削除(荒れ帯では逆効果=検証済と食い違い)/純能力AI(市場に勝てないと実測済)。

**How to apply**:
- danger_gate.pyに『中9週+ローテ』(63-179日)ソフト理由を追加済み(半年休み明けと排他・
  単独では非表示、硬い危険と重なるとseverity算入)。
- **重要バグ修正**: danger_vetoの呼び出し3か所すべてlayoff_days未指定で、半年休み明け
  ソフト理由は主要パスで一度も発火していなかった。consensus_view.build_edge_setsに
  PastRuns[0].Date→race_dateの日数計算を追加して配線(エンジン/統合ビュー/危険警告に波及)。
  app.py側の残り2か所(軸マーク降格5337/軸フロア10752)は未配線のまま(prev date非保持)。

関連: [[verified-arare-signal-check]] [[project-elimination-engine]] [[feedback-folk-signals-overbet]]
