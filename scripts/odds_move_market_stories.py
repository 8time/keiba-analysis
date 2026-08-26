# -*- coding: utf-8 -*-
"""朝のオッズ→後場のオッズで、軸の補強／弱い馬の押し上げが見えるか。

3着は使わない。市場自身の『朝の評価』と『後の評価』の差だけを見る。
最後の記録は昼12時が多い（発走10分前ではない）点は本文で明示する。

Usage: python scripts/odds_move_market_stories.py
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from statistics import median

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.morning_vs_prerace_odds import (
    DB, GAP_MIN, GAP_MAX, load_snaps, rank_of, bucket_hour,
)


def pct(a, b):
    return a / b * 100 if b else 0.0


def med(xs):
    return median(xs) if xs else 0


def main():
    if not os.path.exists(DB):
        print('odds_history.db なし')
        return
    con = sqlite3.connect(DB)
    snaps = load_snaps(con)
    con.close()
    usable = [s for s in snaps if GAP_MIN <= s['gap'] <= GAP_MAX and len(s['common']) >= 6]
    print(f'対象 {len(usable)}R（2時点・間隔30分〜36時間）')
    print('  最初:', dict(Counter(bucket_hour(s['h0']) for s in usable)))
    print('  最後:', dict(Counter(bucket_hour(s['h1']) for s in usable)))
    print('  ※最後は昼12時が多く、発走直前ではない。朝の評価 vs 後場の評価、として読む。')

    fav_kind = Counter()  # solid / from2 / fake(3+)
    morning_fav_last = Counter()
    late_into_top3 = []   # (rf, rl, od0, od1)
    late_into_fav = []
    hidden = []           # morning top3 that dropped
    collapse = []         # ratio od1/od0 for horses that entered top3 from 6+
    n_danger_race = 0
    n_hidden_race = 0
    n_solid = n_fake = n_mid = 0

    for s in usable:
        rf, rl = rank_of(s['first']), rank_of(s['last'])
        common = s['common']
        fav = min((u for u in common if u in rl), key=lambda u: rl[u])
        ef = rf.get(fav)
        if ef == 1:
            fav_kind['朝から1番（軸補強）'] += 1
            n_solid += 1
        elif ef == 2:
            fav_kind['朝は2番→1番'] += 1
            n_mid += 1
        else:
            fav_kind['朝は3番以下→1番（押し上げ）'] += 1
            n_fake += 1
            late_into_fav.append((ef, s['first'].get(fav), s['last'].get(fav)))

        mf = min((u for u in common if u in rf), key=lambda u: rf[u])
        morning_fav_last[rl.get(mf, 99)] += 1

        hit_danger = hit_hidden = False
        for u in common:
            if u not in rf or u not in rl:
                continue
            a, b = rf[u], rl[u]
            od0, od1 = s['first'][u], s['last'][u]
            # 朝6+ が後で3以内
            if a >= 6 and b <= 3:
                late_into_top3.append((a, b, od0, od1))
                hit_danger = True
                if od0 > 0:
                    collapse.append(od1 / od0)
            if a <= 3 and (b - a) >= 3:
                hidden.append((a, b, od0, od1))
                hit_hidden = True
        if hit_danger:
            n_danger_race += 1
        if hit_hidden:
            n_hidden_race += 1

    n = len(usable)
    print('\n=== 後場の1番人気は、朝から支持されていたか（軸の補強） ===')
    for k in ('朝から1番（軸補強）', '朝は2番→1番', '朝は3番以下→1番（押し上げ）'):
        print(f'  {k}: {fav_kind[k]}R  ({pct(fav_kind[k], n):.1f}%)')
    print(f'  → 1番人気の約{pct(n_solid, n):.0f}%は朝から1番。'
          f'{pct(n_fake, n):.0f}%は朝3番以下からの浮上。')

    print('\n=== 朝の1番人気は、後場でどこにいるか ===')
    held = morning_fav_last[1]
    still_top3 = sum(morning_fav_last[i] for i in (1, 2, 3))
    out4 = sum(v for k, v in morning_fav_last.items() if k >= 4)
    print(f'  後も1番: {held}R ({pct(held, n):.1f}%)')
    print(f'  後も3番以内: {still_top3}R ({pct(still_top3, n):.1f}%)')
    print(f'  4番以下に沈む: {out4}R ({pct(out4, n):.1f}%)')
    print('  内訳 後場人気:',
          ' '.join(f'{k}番{morning_fav_last[k]}' for k in range(1, 9) if morning_fav_last[k]))

    print('\n=== 朝は弱かったのに、後場で上位へ売られた馬 ===')
    print(f'  朝6番以下 → 後場3番以内: {len(late_into_top3)}頭 / {n_danger_race}R'
          f'（{pct(n_danger_race, n):.1f}%のレースで発生）')
    if late_into_top3:
        print(f'    朝の単勝 中央 {med([x[2] for x in late_into_top3]):.1f}倍'
              f' → 後 {med([x[3] for x in late_into_top3]):.1f}倍'
              f'（倍率 {med(collapse):.2f}倍に縮小）')
        print(f'    朝人気の中央 {med([x[0] for x in late_into_top3]):.0f}番'
              f' → 後 {med([x[1] for x in late_into_top3]):.0f}番')
        to_fav = [x for x in late_into_top3 if x[1] == 1]
        print(f'    そのうち後場1番まで行った: {len(to_fav)}頭')
        from_bin = Counter(x[0] for x in late_into_top3)
        print('    朝の人気:',
              ' '.join(f'{k}番{from_bin[k]}' for k in sorted(from_bin)[:10]))

    print('\n=== 朝は売れていたのに、後場で沈んだ馬 ===')
    print(f'  朝3番以内 → 3つ以上下降: {len(hidden)}頭 / {n_hidden_race}R'
          f'（{pct(n_hidden_race, n):.1f}%のレース）')
    if hidden:
        print(f'    朝の単勝 中央 {med([x[2] for x in hidden]):.1f}倍'
              f' → 後 {med([x[3] for x in hidden]):.1f}倍')
        print(f'    朝人気の中央 {med([x[0] for x in hidden]):.0f}番'
              f' → 後 {med([x[1] for x in hidden]):.0f}番')
        was1 = [x for x in hidden if x[0] == 1]
        print(f'    朝1番が沈んだ: {len(was1)}頭')

    print('\n読み方（結果は見ていない）')
    print('  軸補強 = 後場1番が朝から1番。市場が一度も揺らしていない。')
    print('  押し上げ = 朝は6番以下なのに後場3番以内。朝の市場は弱者と見ていた。')
    print('  沈み = 朝の上位が後で人気を失う。賢い金が先に降りた可能性（未検証）。')


if __name__ == '__main__':
    main()
