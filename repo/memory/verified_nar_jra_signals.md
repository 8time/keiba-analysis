---
name: verified-nar-jra-signals
description: 大井3197頭+川崎2020頭でJRA検証済みシグナル再検証。枠順はpriced-in(大井)/逆転(川崎内枠有利z+2.55)。少頭数×本命z+2.14有意
metadata: 
  node_type: memory
  type: project
  originSessionId: 2e1ab573-9c8a-4994-96f3-d38f0566d06f
---

## NAR在庫データ再検証(大井263R+川崎180R = 443R/5217頭)

scripts/nar_jra_signal_backtest.py で venue 別3パス(大井/川崎/統合)実行。

### venue間比較サマリ

| シグナル | 大井(263R) | 川崎(180R) | 統合(443R) | 判定 |
|---|---|---|---|---|
| D1 外枠×1-3人気 | z+0.32 | z-1.14 | z-0.51 | priced-in |
| **D1 内枠×1-3人気** | z-0.60 | **z+2.55★** | z+1.24 | **川崎のみ有意** |
| D1c 内枠(全人気) | z-1.48 | **z+2.22★** | z+0.28 | **川崎のみ有意** |
| D2 脚質 | priced-in | priced-in | priced-in | 全場織込み済み |
| D3 PCI | priced-in | priced-in | priced-in | 全場織込み済み |
| **D4 少頭数×本命** | z+2.00★ | z+1.00 | **z+2.14★** | NAR統合で強化 |
| D5 川崎内枠×前型×6+人気 | — | z+1.99★(n=48) | — | 小標本・追跡候補 |
| **D6 末脚top3×1-3人気** | z+1.71 | z+1.42 | **z+2.18★** | NAR統合で有意化 |

### 重大な発見: 川崎の内枠バイアス
- 川崎=超小回り(1周1200m/直線300m)で**JRAの外枠優位が完全に逆転**
- 内枠×1-3人気: 複勝率64.7% vs 期待56.2% = +8.5pp(z+2.55)
- 外枠×1-3人気: 複勝率52.4% vs 期待56.5% = -4.1pp(z-1.14)
- 大井(大箱/直線386m)では枠順差は消滅→場の構造が枠順バイアスの有無を決定

### 実施した修正
1. core/track_bias.py: dirt_draw_signal()にNARゲート([[project_nankan_scraper]]の場コード利用)
2. core/track_bias.py: nar_evidence_rows()に川崎内枠バイアスのエビデンス行追加

### データ資産
- scripts/debug/nankan_backtest_rows.json — 大井3197頭(venue=ooi)
- scripts/debug/kawasaki_backtest_rows.json — 川崎2020頭(venue=kawasaki)
- scripts/debug/kawasaki_races_phase1.json — 川崎180R生結果
- scripts/nar_jra_signal_backtest.py — venue別3パスバックテスト

**Why:** JRAダート枠順エッジ(z+9.4)がNARでそのまま表示されていた誤表示を実測で解消。かつ川崎固有の内枠エッジを新規発見。

**How to apply:** NAR分析では場の構造(直線長/回り)によりエッジの方向が変わる。場コード別にゲートするのが正解。新場を追加する際は必ず再検証。
