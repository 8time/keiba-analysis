---
name: verified_track_change_overbet
description: トラック変更(前走→今走の芝/ダ)は軸エッジでない。ダ→芝88%は生ROIの見かけ(FLB)で人気補正すると負残差。芝→ダは強く過剰人気(fade)
metadata: 
  node_type: memory
  type: project
  originSessionId: ae626662-ddf7-4948-bcf9-cdf9f6a2e414
---

動画「回収率20%上がる軸馬の選び方」のトラック変更主張(特に「ダート→芝は単勝回収88%」)を検証(2026-07-20・ユーザー要望)。scripts/track_change_backtest.py・DB surface履歴×CSV(ninki/win/top3)結合436,594サンプル・train凍結ninki別ベース→holdout(2024)/2025残差。

**結果=軸エッジでない**(人気補正残差):
- **ダ→芝**(動画88%主張): 勝利残差 z-1.07/-0.43・複勝残差 **z-1.84/-1.87**(両期間マイナス)。低勝率(6.5%)でオッズ長い→生ROIが高く見えるだけのfavorite-longshot bias。人気補正すると負。
- **芝→ダ**: 複勝残差 **z-3.93/-5.53** 強く過剰人気。「ダート替わり一変」期待で買われるが来ない=**fade候補**。
- 芝→芝/ダ→ダ(同surface継続): 複勝残差 z+1.5〜1.8 わずか正(priced-inレベル)。

**降級(前走クラス)は未検証**: DBに級別(未勝利/1勝/2勝/3勝/OP)の明確フィールド無し(shubetsu=年齢区分/grade=G1-G3のみ)、race_name parseは特別レースで級不明→不正確なので実施せず。生ROI84%<100%+小標本+他前走系priced-inからエッジ薄と推定。

**動画全体の総括(この馬選び動画は全否定)**: ①ダート外枠=唯一本物だが[[verified_dirt_draw_bias]]で実装済 ②距離短縮=[[feedback_folk_signals_overbet]]で妙味ゼロ ③高齢=danger_gateから削除済(1-3人気で効かず) ④前走着順6-9着=[[verified_prior_margin_debunk]]priced-in ⑤トラック変更=本メモで否定 ⑥降級=未検証だが薄い ⑦「stackで117%」=生ROI全て<100%を組合せ探索で100%超に見せる多重検定の過学習(標本激減・oosで控除率80%へ回帰。[[verified_pci_pricedin]]の弱因子stacking否定・[[verified_formation_roi]]の単年>100%は変動の幻と同型)。How to apply: この動画由来の再提案は「検証済み・織込み/過学習」で即返す。
