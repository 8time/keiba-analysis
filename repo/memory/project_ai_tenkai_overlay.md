---
name: project_ai_tenkai_overlay
description: netkeiba「AI展開予測」の4コーナー隊列位置を静的JSから抽出しアプリ展開MAPと照合(🏆/💀)。core/ai_tenkai.py。表示のみ・エッジ主張なし
metadata: 
  node_type: memory
  type: project
  originSessionId: ddc31c7d-ff26-4821-8a37-bdbceb363b6b
---

netkeiba出馬表(nar/race.netkeiba.com/race/shutuba.html)の「AI展開予測」隊列可視化の
4コーナー位置を取得し、当アプリ展開MAPの到達位置と前40%/後35%帯で照合して
両AI同帯なら🏆(前=有利)/💀(後=危険)を出す表示機能(2026-07-03, T4)。

**データ源の発見(重要):** 位置は「4コーナー〇クリックで動的描画」に見えるが、実体は
出馬表HTMLの`updateHorsePosition()`内の**静的JS**に埋込。ログイン/課金("マスター"バッジは
プロモ表示のみ)不要。requests素取得+正規表現でパース可(Playwright不要)。
- `<span class="HorseIcon" id="Horse{馬番}" style="left:X%">` が実描画アイコン(=真の出走頭数)。
- JS内 `case 'Corner01'(スタート後)/'Corner02'(3角)/'Corner03'(4角)` の
  `$("#Horse{馬番}").css({left:'X%'})` にコーナー別位置。テンプレ余剰スロット(実在しない馬番)や
  `//`コメント行が混在するので、①実描画アイコンの馬番集合で濾過 ②行コメント除去 が必須。
- **方向較正(大井7/3実査)**: 先行馬=低left%(#6先行=0%)/追込馬=高left%(#3追込=100%)。
  → **left%小=前・大=後**。アプリ側`pace_map.style_from_score`も低score=前(逃げ/先行)で同方向。

**実装 core/ai_tenkai.py(新規・既存不変):**
parse_tenkai_positions(html)→{馬番:{start,corner3,corner4}} / band_by_left(left_map,0.40,0.35)→前中後 /
agreement_icons(nk帯,app帯)→両前=🏆・両後=💀 / fetch_tenkai_positions / corner4_bands。
app.py 3266の🗺️展開MAP expander内にボタン起動で配線(JRA/NAR両対応・毎回スクレイプせずcache)。

**Why:** 展開恩恵はpriced-in([[verified_tenkai_priced_in]])なのでエッジ主張はしない。
「2つのAI(netkeiba×自作展開MAP)の合意点」の可視化のみ。[[project_pace_map_rebuild]]の補助表示。

**How to apply:** netkeiba隊列系の位置が要るときはHTML静的パースで足りる(動的と誤認しない)。
smoke=帯分類/合意アイコンのネットワーク非依存テストあり。[[project_nankan_scraper]]のNAR一連(T1-T5)の一部。
