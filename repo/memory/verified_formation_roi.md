---
name: verified-formation-roi
description: 3連単フォーメーション実配当ROI検証。可変(regime-matched)+荒れ選択で控除率floor(75%)は有意に超える(bootstrap 90%CI下限>75%)がROI中央83-90%<100%で利益化には未到達。scripts/formation_backtest.py
metadata: 
  node_type: memory
  type: reference
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

買い方研究 第1弾(2026-07)。ユーザー方針「Rank固定+人気で点数削減・可変フォーメーション+見送り」。
**重要な資産発見**: jravan.dbに `payouts`表(3連単/3連複の実配当・2016+で3連単36,411R・中央¥26,170/最大¥5,836万)
と `odds`表(win/place/trio等の事前オッズ・77M行)がある=**架空でなく実配当でROI検証可能**。

**検証(scripts/formation_backtest.py・CSV特徴ストア+payouts・2021-2026)**:
買い方=tight(Rank1軸堅)/jai(広角)/arare(妙味馬1着)/variable(arare_probでregime切替)/variable_skip(中庸見送り)。
Rank源=人気(ninki) vs ability_score(=4pct平均・低い=強・強適RankでもLTRでもない crude proxy)。
参加フィルタ=全レース/検証荒れ(ハンデ/16頭/●大穴)/荒れ確率≥62%。判定=bootstrap 90%CI(3連単は分散巨大)。

**結論(全年プール5k-18kレース・raw ROI bootstrap)**:
- 可変(regime-matched)は全フィルタで**90%CI下限>75%=控除率floorを有意に超える**(選択にスキル有)。
- ただし**ROI中央 83-90% < 100% = 長期では負け**(利益化には未到達)。荒れ確率≥62%が最良(中央90%・CI上限107%)。
- **堅いtight(favorite-only狭い)は63-71%でfloor未達→狭いより広い可変の方が良い**(市場は広げた中rangeのcomboを過小評価?)。
- 単年holdout+¥200k capだと72-77%に見えるが=小標本+過剰capの錯覚。**大標本rawが真**(capは荒れの大穴を切りすぎ=保守的すぎ)。
- 人気>ability crude proxy(win slotで tight的中 人気9.2% vs ability3.2%)=強適Rank(実物)は別途要検証。

**第3弾: ブック型点数最適化 帯別(scripts/formation_pointopt.py・人気2+穴1・pop=R1-3/ana=妙味穴top2)**:
- 堅(ap<42%): **book 74.1% > wide 68.9%** =点数絞り(36点)が効く帯(動画/書籍の土俵・正しい)。
- 中(42-60%): **wide 85.5%(★floor超・最良) > book 81.7%** =最も損益分岐に近い。
- 荒れ(≥62%): **wide 80.8% >> book 70.4%** =荒れは広く/穴頭カットは逆効果(動画の但し書き「荒れに弱い」を実証)。
→ 帯別formation(堅→book絞る/中荒れ→wide)は正しい。**だがどの帯・買い方も100%のCI下限を出さない**=
3連単は買い方だけでは利益化不能。買い方最適化=損失縮小(naive tight63%→中波乱wide85%)であって利益化ではない。

**pop_th=5→4に変更(trio_engine)**: 人気馬=1-4で決着『人気2+穴1』が49.9%最頻に最大化(1-6だと人気3頭50.8%に化ける)。
穴ana_lo=6不変(妙味検出は6番人気以下)。5番人気=中間。**フォーメーション分類の境界(4/5)と妙味検出ゾーン(6+)は別の仕事**。

**How to apply**: 荒れレース選択(妙味度/arare_prob/検証荒れ条件)は控除率floorを有意に超える買い方選択スキルを生むが、
利益化(100%)には届かない。利益化の主戦場は**見送り+資金管理(BetSync/ケリー)**であって買い方の妙技ではない。
帯別に買い方を変える(堅→少点book/中荒れ→wide)のは損失縮小として正しい。有料販売では「買い方で市場並より賢くなるが長期プラスの保証はない」と正直に。
**それ自体では利益(100%)に届かない**。利益化には更なる絞り(EV/点数最適化/軸精度)が要る。有料販売では
「floor超=市場並より賢いが、長期プラスの保証ではない」と正直に。単年少標本の>100%はほぼ変動の幻(要bootstrap)。
関連: [[verified_tansho_roi_efficient]](単勝効率)・[[verified_arare_conditions]]/[[verified_arare_entropy]](荒れ条件)・
[[project_csv_feature_store]](高速検証基盤)・[[project_trio_engine]]。次段=本物Rank(LTRで全馬scoring)/EVフィルタ/点数最適化。
