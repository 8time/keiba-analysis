---
name: verified_comeback_overbet
description: 🔄バイアス巻き返し候補は「次走穴妙味」としては誤り(検証済)。穴帯で残差≈0〜負・ROI66-68%。妙味は1-3番人気のみ
metadata: 
  node_type: memory
  type: project
  originSessionId: c3fa42fa-de5c-41c4-9911-b6156b6e7b9d
---

🔄バイアス巻き返し候補(core/track_bias.comeback_flag=直近走で当日バイアスに逆らって好走)を初検証(scripts/comeback_backtest.py・2023-25・JRA平地・jravan.db)。ユーザー報告「全く当たらない」を裏付け。**実装時バックテストされていなかった未検証フラグだった**。

- **フラグ発火馬(n=5514)全体**: 勝率10.1%/複勝率29.5%(母集団7.3%/21.8%より高く見える)が、単ROI70.9%(母集団71.0%と同じ=控除負け)、人気補正残差は複勝-0.4pp(z=-0.76)/勝-0.4pp(z=-1.14)で**負**。=生の好走率は『事後の幻影』で完全に人気に織込み済み。[[verified_legtype_axis]][[verified_pci_pricedin]][[feedback_folk_signals_overbet]]と同型。
- **人気帯別が決定的**: 1-3番人気で発火=複勝残差**+2.1pp(z=+2.24)**=唯一の正(ただし単ROI75.3%で単勝エッジでなく複勝/相手の信頼度。[[verified_ohtani_trap]]と同じ軸補強型)。4-5番人気=複勝残差**-3.8pp(z=-2.99)・勝残差z=-2.92**=明確な**過剰人気の罠**(危険人気側のネタ)。6-9番人気=残差-1.3pp/ROI68%。10番人気〜=複勝率6.7%/ROI66.6%。
- **結論**: 企画の謳い文句「巻き返し穴=次走妙味」は**穴帯(6番人気〜)で妙味ゼロ〜負**=誤り。正しい使い方は(1)1-3番人気で発火→軸の複勝信頼度UP、(2)4-5番人気で発火→危険人気の注意([[project_elimination_engine]]/危険人気馬シグナル連携)、(3)6番人気以下は非表示(エッジなし)。

**How to apply**: 中核目標=過小評価の勝ち馬を拾う[[feedback_catch_underrated_winners]]に対し本フラグは逆機能だった。穴妙味としての再実装禁止。**2026-06-18にapp.pyの🔄セクションを人気帯リフレームで実装済み**(ユーザー選択): 1-3番人気発火=緑カード「軸の複勝信頼度UP」/4-5番人気発火=赤カード「危険人気の罠」/6番人気以下・人気未取得=非表示(captionで件数のみ)。comeback_flag(track_bias)のロジック自体は不変、表示時にdf['Popularity']で振り分け。未commit(push待ち)。
