---
name: verified-odds-theory-signals
description: しまちゃん/NotebookLMオッズ理論5法則を検証。ガラス人気馬(単複逆転fade)のみ新規本物z-8.5→danger_gate配線。ヘソ指数/断層/30倍頭数/倍率比は全て織込み済みor実装済み
metadata: 
  node_type: memory
  type: project
  originSessionId: 64a070b3-be5e-4051-a8b3-047fbb5b0c0c
---

「AI×オッズ理論5黄金法則」動画+NotebookLM資料を検証(2026-07-11・CSV基盤+odds表place)。

**Why(検証結果)**:
- **ガラスの人気馬=新規で本物・配線した**: 上位人気(1-5)×単勝10倍未満で、実複勝オッズが
  『単勝帯ごとの複勝中央値』の1.20倍以上高い(=複勝が相対的に売れてない)馬の複勝率残差
  z-8.5(train-23 z-11.2/2024-25 z-4.2/2026 z-2.8=3窓方向一貫)。tanpuku_divergence
  (単長い×複短い=買い)の裏=fade側。複勝オッズは事前市場値でリーク無し。
- **ヘソ指数=織込み済み**: 基準オッズ(人気順平均)÷実オッズ の最大馬が中穴大穴(7+人気)に
  ある時レース荒れ率67.9%(+16.7pp)=生効果は本物だが、既存エントロピーロジット
  ([[verified-arare-field-pricedin]])へのAUCゲイン+0.15pp=priced-in。配線せず。
- 断層(実装済 track_bias/odds_gap_anchors=z+12.3)・30倍未満頭数(live30)・倍率比r21・
  合成オッズ/トリガミ(実装済)・券種ねじれ(歪みスキャナー実装済)は全て既知。
- 時系列オッズ/朝一比較/インサイダー検知はDBにオッズ時系列無く検証不能(実査)。
  電通大論文の焼きなまし最適解3670%は障害競走偏り+単年で信頼薄。

**How to apply(実装済)**:
- core/value_scanner.glass_favorite_fade(win_odds,place_mid,ninki)=凍結表
  data/glass_favorite_bands.json(train2016-23の単勝8帯×複勝中央値)で判定。
- danger_gate.danger_veto に win_odds/place_mid 引数追加=ガラス人気馬を硬い危険理由
  '🥃ガラス人気馬'として算入(単独severity1=軸降格注意・他と重なりveto)。
- consensus_view.build_edge_sets が fetch_place_odds_api で複勝Mid取得しdanger_vetoへ配線
  (セッションキャッシュで1レース1回)。強適エンジン/統合ビュー/危険警告に波及。

関連: [[verified-arare-entropy]] [[verified-dirt-draw-bias]](断層) [[project-value-scanner]]
[[verified-rotation-weight-demerit]](同時期のdanger_gate拡張)
