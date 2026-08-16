---
name: verified-vh-badge-selection
description: VH精鋭内でバッジ数(検証済みシグナル数)による選別は逆効果。VH1位が最良(+4pp)
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 72da3c77-2988-4dbb-a040-fdbe604e0282
  modified: 2026-08-10T18:21:33.530Z
---

VH候補の中でバッジ数(検証済みシグナル=補正T/末脚/33ラップ/騎手/血統/厩舎/血統回収の7種)が多い馬を選ぶのはVH1位を選ぶより-4pp劣る。

- train: VH1位24.1% vs バッジ最多19.8%
- holdout: VH1位22.1% vs バッジ最多18.0%
- 別馬のみ(holdout): VH1位22.3% vs バッジ最多14.1%(-8.2pp)

**Why:** VHスコア自体が補正T/末脚/血統を既に取り込んでいるため、バッジとして二重カウントするとオッズ順序で既に評価された馬を過大に拾う。精鋭内では🧬血統が-5.3pp(z-8.27)、👑騎手が-1.4pp(z-2.08)と逆に効く。

**How to apply:** 🏆マークはバッジ最多ではなくVHスコア1位（=各グループの1位表示馬）に付ける。バッジは判断参考として表示するが「多いほど良い」とは案内しない。scripts/vh_badge_backtest.py
