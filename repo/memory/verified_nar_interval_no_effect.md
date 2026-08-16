---
name: verified-nar-interval-no-effect
description: NAR出走間隔(連闘/中1週)検証→有意な不利なし棄却(z-0.66・短間隔20.9%vs通常25.5%・510頭)
metadata: 
  node_type: memory
  type: project
  originSessionId: 8193f2c8-eae5-432d-9103-99a37077d415
  modified: 2026-07-28T20:16:18.832Z
---

プレイブック主張「連闘・中1週は疲労で不利」をキャッシュ結果+出馬表前走日で検証→**棄却**。

## 検証結果
- **短間隔(≤13日) vs 通常(14日+)**: 複勝20.9% vs 25.5%(-4.6pp) だが z=-0.66 → 有意差なし
- **1-7日**: わずか4頭で標本不足(全滅だが偶然)
- **8-13日**: 39頭 複勝23.1% → 通常と大差なし
- **人気帯別**: 全帯z<2・4-6人気では短間隔がむしろ+9.6pp
- 短間隔馬は平均人気が悪い(6.9-11.2 vs 通常5.3-6.8) = 弱い馬が使い詰めされてるだけ
- JRA側でも「短間隔ローテは否定」(verified_axis_ng_claims)と一致

## 対応
- スコア減点(-3/-1) → **削除**
- 合議コメント「連闘級」「疲労注意」→ **削除**
- Interval列(中間日) → 情報表示として残留、色分けを中立化(赤バッジ→太字のみ)
- newspaper.pyの「適度な間隔」緑色 → 削除

**Why:** 短間隔の不利は弱い馬の使い詰めバイアスで、間隔そのものは成績に影響しない。[[verified_axis_ng_claims]]
**How to apply:** NARで間隔ペナルティを再提案しない。表示は情報として残す。

scripts/nar_interval_backtest.py / data/nar_interval_cache.json
