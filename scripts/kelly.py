# -*- coding: utf-8 -*-
"""
② 資金管理: 多肢選択ケリー基準 ＋ 破産確率（デモ）

数理の正本は core/money.py に移管済み。本ファイルは CLI デモ＋後方互換の薄いラッパ。
  from scripts.kelly import kelly_multi, ruin_probability  # = core.money のもの
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.money import kelly_multi, ruin_probability  # noqa: E402


def main():
    print("=" * 68)
    print("② 多肢選択ケリー基準 ＋ 破産確率 デモ")
    print("=" * 68)

    horses = [
        {'umaban': 7,  'p': 0.40, 'odds': 3.0},   # EV=1.20 妙味◎
        {'umaban': 3,  'p': 0.20, 'odds': 6.0},   # EV=1.20 妙味○
        {'umaban': 12, 'p': 0.15, 'odds': 5.0},   # EV=0.75 妙味なし
        {'umaban': 1,  'p': 0.10, 'odds': 2.0},   # EV=0.20 過剰人気
    ]
    print("\n■ 入力（AI勝率 × 現在オッズ）")
    for h in horses:
        print(f"  {h['umaban']:>2}番  勝率{h['p']*100:4.0f}%  オッズ{h['odds']:.1f}倍  EV={h['p']*h['odds']:.2f}")

    for kf, name in [(1.0, 'フルケリー'), (0.25, '1/4ケリー(推奨)')]:
        res = kelly_multi(horses, kelly_fraction=kf)
        print(f"\n■ {name}  留保レートR={res['reserve_rate']:.3f}")
        for b in res['bets']:
            if b['frac'] > 0:
                print(f"  {b['umaban']:>2}番(EV{b['ev']}): 資金の {b['frac']*100:5.2f}% を投資")
        print(f"  現金留保: {res['cash']*100:.1f}%  / 賭け総額: {res['sum_bet']*100:.1f}%")
        print(f"  → EVプラス馬({len([b for b in res['bets'] if b['frac']>0])}頭)だけに配分、EVマイナス馬は自動除外")

    print("\n■ 破産確率（穴狙いの非対称リスク）")
    for p, odds, label in [(0.40, 3.0, '本命型(勝率40%/3倍)'), (0.10, 12.0, '穴型(勝率10%/12倍)')]:
        for kf in (1.0, 0.25):
            r = ruin_probability(p, odds, kelly_fraction=kf, n_bets=500, ruin_level=0.5)
            kn = 'フル' if kf == 1.0 else '1/4'
            print(f"  {label} {kn}ケリー: 賭け率{r['bet_fraction']*100:.1f}%  "
                  f"500戦で資金半減する確率={r['ruin_prob']*100:.1f}%  中央値={r['median_final']}")


if __name__ == '__main__':
    main()
