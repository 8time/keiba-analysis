---
name: verified_pace_congestion_weak
description: 前傾/先行混雑→展開崩壊→荒れ は実テン3Fタイムで再挑戦しても超えず=priced-inで決着(2026-07-22)。再提案しない
metadata: 
  node_type: memory
  type: project
  originSessionId: ae626662-ddf7-4948-bcf9-cdf9f6a2e414
  modified: 2026-07-21T23:35:48.465Z
---

ロジック置き場「レース予測難易度高精度化(前半＝テン3F混雑で展開崩壊)」の検証(2026-07-19)。scripts/pace_congestion_arare_backtest.py・races.csv(31,849レース)。

**設計(リーク無し・オッズ超えを厳密化)**: 前傾混雑度(export_features_csv既算・過去走脚質ベース)= n_front(avg_pos3<=3の先行数)/n_hana(pos_ratio3<=0.20の逃げ数)/mean_posr/front_ratio。ベース=凍結荒れロジット arare_prob(オッズ12特徴・AUC0.69)の予測。残差=実荒れ(arareA)−予測。train凍結三分位→holdout/2025で「高混雑群残差−低混雑群残差」= D と z。

**結果=弱・方向一貫**: 全4特徴・両期間で **D>0(符号一貫)**。ただし z は holdout 0.65〜1.03 / 2025 1.27〜1.69 で**採用ゲート z>=2 に未達**。最良=front_ratio(先行率) holdout z+1.03/2025 z+1.53。→ PCI/距離([[verified_pci_pricedin]]/[[verified_distance_affinity_pricedin]])が符号逆転で死んだのと違い、**方向は本物っぽいが弱い**。今そのまま荒れ予報に足すのは早い。

**【決着】実テン3Fタイムで再挑戦→やはり超えず(2026-07-22・scripts/pace_tenspeed_arare_backtest.py)**: 上記の「再挑戦候補筆頭」を実行した結果、**priced-inで確定**。ten_speed =(走破タイム−上がり3F)/(距離−600)×600 [秒/600m・小=速い] を core/pace_map.py / build_pace_norms.py と同一定義(直近5走・条件重み1.6/0.5×距離1.4/0.6×直近0.82^idx・当日厳格除外)で leak-free に再現し、レース単位に集約(30,767レース)。z化ノルムはtrainのみで凍結。結果(D=混雑↑群残差−混雑↓群残差):

| 指標 | holdout(2025) | recent(2026) |
|---|---|---|
| ten_top3(前方3頭の実テン) | z+0.41 | z+0.24 |
| **ten_top3_z(距離馬場正規化)** | **z+1.70** | z+0.64 |
| ten_pack_r(±0.3秒の同速率) | z-0.30 | z-0.27 |
| ten_std / ten_gap14 | z-1.40 / -1.43 | z+1.95 / -0.36 |
| 旧n_front(順位代理・参考) | z+0.62 | z+0.02 |

実タイム化でten_top3_zはholdout z+1.70まで上がり旧代理(z+0.62)を上回ったが**2に届かず、recentで0.64へ崩落**。D>0の符号一貫は維持=「効いてはいるがオッズが既に織り込んでいる」。**再提案しない**。

**展開マップ側も伸びしろ無し(scripts/pace_map_tenweight_sweep.py)**: テン速力の残る使い道=表示精度(4角隊列)。_PACE_TUNE の w_ten/ch_ten を掃引(較正窓2024/検証窓2025-26・各1200R)→ w_ten=0.5/1.0 が両窓でspearman微増(+0.0022/+0.0012)だが**n=300→1200で伸びが縮み(+0.0032→+0.0012)、先頭的中とtop3被りは検証窓で悪化**。**現行 w_ten=0.25 が最良・変更しない**。ch_ten(コーナー履歴にテンを混ぜる)は全設定で悪化。

**How to apply**: テン速力は既に core/pace_map.py に w_ten=0.25 で実装・較正済みで、そこから先の上積みは荒れ予測にも表示精度にも無い。[[project_pace_map_rebuild]]は事実上完了扱い。位置取り代理も実タイムも結論は同じ＝展開はpriced-in([[verified_tenkai_priced_in]]/[[verified_makuri_priced_in]]と同型)。
