# -*- coding: utf-8 -*-
"""🟡中穴3着型: 6-7番人気を3着役として、複勝積の11-20位から10点へ繰り上げる。

通常レース（3着が5番以内）は、条件が点火しなければ複勝積のまま。
条件は「6-7番が実際に3着だったレース」から作らない。
6-7番人気の馬すべてにレース前の条件を掛け、
満たす馬が3着の組だけ 11-20位から最大N点入れ替える。

Usage: python scripts/trio_yellow_promote_backtest.py
"""
import os
import sqlite3
import sys
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd

KEEP_K = 7
N_POINTS = 10
SWAPS = (0, 1, 2)


def load_pays():
    con = sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT race_key, combo, payout FROM payouts "
        "WHERE bet_type='3連複' AND payout>0"
    ).fetchall()
    con.close()
    out = {}
    for rk, combo, p in rows:
        try:
            fs = frozenset(int(combo[i:i + 2]) for i in range(0, 6, 2))
            if len(fs) == 3:
                out[str(rk)] = (fs, float(p))
        except Exception:
            continue
    return out


def fuku_of(ninki, odds):
    v = fuku_rate(ninki, odds)
    if v is None:
        v = fuku_rate(ninki, None)
    return max(1.0, float(v or 8.0)) / 100.0


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(min(k, len(sub)), 'ninki')


def prod(fs, fk):
    p = 1.0
    for u in fs:
        p *= fk[u]
    return p


def third_of(fs, nk):
    return max(fs, key=lambda u: nk[u])


def add_feats(h):
    h = h.copy()
    g = h.groupby('race_key', sort=False)
    h['ab_rank'] = g['ability_score'].rank(method='min', ascending=True)
    h['vh_pct'] = g['vh2_score'].rank(method='min', ascending=True, pct=True)
    h['spurt_rk'] = g['spurt_idx'].rank(method='min', ascending=False)
    h['blood_rk'] = g['sire_surf_t3'].rank(method='min', ascending=False)
    h['pt3_rk'] = g['prior_top3_rate'].rank(method='min', ascending=False)
    h['gap'] = (h['ninki'] - h['ab_rank']).fillna(0)
    h['vh_pct'] = h['vh_pct'].fillna(0.0)
    return h


def flags_of(rec, race):
    spurt = _num(rec.get('spurt_rk')) is not None and rec['spurt_rk'] <= 3
    vh_hi = float(rec.get('vh_pct') or 0) >= 0.67
    lap = (_num(rec.get('lap_fit_bin')) or 0) >= 1
    myomi = float(rec.get('gap') or 0) >= 2
    back = (_num(rec.get('pos_ratio3')) or 0.5) >= 0.55
    combo = (_num(rec.get('combo')) or 0) >= 2
    inner = (_num(rec.get('waku_n')) or 9) <= 3
    dist_ok = abs(_num(rec.get('dist_change')) or 0) < 200
    pt3_hi = _num(rec.get('pt3_rk')) is not None and rec['pt3_rk'] <= 3
    blood_hi = _num(rec.get('blood_rk')) is not None and rec['blood_rk'] <= 3
    n_front = race.get('n_front')
    closer_hi = back and n_front is not None and n_front >= 5
    return {
        '末脚top3': bool(spurt),
        'VH上位1/3': bool(vh_hi),
        '33適合': bool(lap),
        '妙味(能力>人気)': bool(myomi),
        '後方脚質': bool(back),
        'ハンターcombo2+': bool(combo),
        '内枠1-3': bool(inner),
        '距離ほぼ据置': bool(dist_ok),
        '前走3着上位': bool(pt3_hi),
        '血統上位': bool(blood_hi),
        '先行多×後方': bool(closer_hi),
        '末脚orVH': bool(spurt or vh_hi),
        '末脚andVH': bool(spurt and vh_hi),
        '無条件': True,
    }


def promote(ordered, nk, flag_map, n_swap):
    if n_swap <= 0:
        return list(ordered[:N_POINTS]), 0
    base = list(ordered[:N_POINTS])
    band = list(ordered[N_POINTS:20])
    take = []
    for fs in band:
        if len(take) >= n_swap:
            break
        t = third_of(fs, nk)
        if nk[t] in (6, 7) and flag_map.get(t):
            take.append(fs)
    if not take:
        return base, 0
    kept = base[:N_POINTS - len(take)]
    return kept + take, len(take)


def median(xs):
    if not xs:
        return 0.0
    ys = sorted(xs)
    return float(ys[len(ys) // 2])


FLAG_NAMES = [
    '複勝積', '無条件', '末脚top3', 'VH上位1/3', '33適合', '妙味(能力>人気)',
    '後方脚質', 'ハンターcombo2+', '内枠1-3', '距離ほぼ据置',
    '前走3着上位', '血統上位', '先行多×後方', '末脚orVH', '末脚andVH',
]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'top3',
        'ability_score', 'vh2_score', 'spurt_idx', 'lap_fit_bin',
        'pos_ratio3', 'combo', 'waku_n', 'dist_change',
        'prior_top3_rate', 'sire_surf_t3',
    ])
    h = add_feats(h)
    rmeta = cd.load_races(cols=['race_key', 'n_front', 'vscore'])
    rmeta = rmeta.drop_duplicates('race_key')
    rmap = {}
    for r in rmeta.itertuples(index=False):
        rec = {'n_front': _num(r.n_front), 'vscore': _num(r.vscore)}
        rmap[str(r.race_key)] = rec
        try:
            rmap[str(int(r.race_key))] = rec
        except (TypeError, ValueError):
            pass
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    horse_n = defaultdict(lambda: [0, 0])
    cell = defaultdict(lambda: [0, 0, 0, 0, [], 0])
    yellow_rank = defaultdict(int)

    data_flags = [n for n in FLAG_NAMES if n != '複勝積']

    for rk, g in h.groupby('race_key', sort=False):
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay or pay[0] != win:
            continue
        payout = pay[1]
        period = str(g['period'].iloc[0])
        race = rmap.get(str(rk)) or {}
        try:
            race = race or rmap.get(str(int(rk)), {})
        except (TypeError, ValueError):
            pass
        kg = keep_ninki(g, KEEP_K)
        if len(kg) < 3:
            continue

        ums = [int(x) for x in kg['umaban']]
        keep = set(ums)
        nk = {int(r.umaban): int(r.ninki) for r in kg.itertuples(index=False)}
        fk = {int(r.umaban): fuku_of(r.ninki, r.win_odds)
              for r in kg.itertuples(index=False)}
        flag_by_name = {name: {} for name in data_flags}

        for rec in kg.to_dict('records'):
            u = int(rec['umaban'])
            fl = flags_of(rec, race)
            for name in data_flags:
                flag_by_name[name][u] = fl[name]
            if int(rec['ninki']) in (6, 7):
                t3 = int(rec['top3']) == 1
                horse_n[(period, '6-7全体', True)][0] += 1
                horse_n[(period, '6-7全体', True)][1] += int(t3)
                for name in data_flags:
                    if name == '無条件':
                        continue
                    on = bool(fl[name])
                    horse_n[(period, name, on)][0] += 1
                    horse_n[(period, name, on)][1] += int(t3)

        in_keep = win <= keep
        third_nk = max(int(x) for x in win_rows['ninki'])
        if third_nk <= 5:
            zone = 'green'
        elif third_nk in (6, 7):
            zone = 'yellow'
        else:
            zone = 'red'

        combos = [frozenset(c) for c in combinations(ums, 3)]
        ordered = sorted(combos, key=lambda fs: prod(fs, fk), reverse=True)

        if period == 'holdout' and zone == 'yellow' and in_keep:
            try:
                rnk = ordered.index(win) + 1
            except ValueError:
                rnk = 99
            if rnk <= 10:
                yellow_rank['1-10 既に入'] += 1
            elif rnk <= 20:
                yellow_rank['11-20 繰上げ対象'] += 1
            elif rnk <= 30:
                yellow_rank['21-30'] += 1
            else:
                yellow_rank['31-35'] += 1

        jobs = [('複勝積', {u: False for u in ums})]
        for name in data_flags:
            jobs.append((name, flag_by_name[name]))

        for name, fmap in jobs:
            for n_swap in SWAPS:
                if name == '複勝積' and n_swap != 0:
                    continue
                if name != '複勝積' and n_swap == 0:
                    continue
                top, n_did = promote(ordered, nk, fmap, n_swap)
                hit = bool(in_keep and win in set(top))
                for per in (period, 'ALL'):
                    for z in ('all', zone):
                        c = cell[(per, name, n_swap, z)]
                        c[0] += 1
                        c[1] += int(hit)
                        c[2] += N_POINTS * 100
                        c[3] += payout if hit else 0.0
                        if hit:
                            c[4].append(payout)
                        c[5] += int(n_did > 0)

    def pr_horse(period):
        print(f'\n=== {period}  6-7番人気の馬そのもの（3着内率） ===')
        print('「この条件の6-7番は3着に来やすいか」。結果の3着レースだけは見ていない。')
        print(f'{"条件":<16}{"あり頭":>8}{"あり3着内":>10}{"なし頭":>8}{"なし3着内":>10}{"差":>8}')
        tot = horse_n[(period, '6-7全体', True)]
        print(f'{"6-7全体":<16}{tot[0]:8,d}{tot[1] / tot[0] * 100 if tot[0] else 0:9.1f}%')
        for name in data_flags:
            if name == '無条件':
                continue
            on = horse_n[(period, name, True)]
            off = horse_n[(period, name, False)]
            r_on = on[1] / on[0] * 100 if on[0] else 0
            r_off = off[1] / off[0] * 100 if off[0] else 0
            mark = ''
            if on[0] >= 80 and (r_on - r_off) >= 3:
                mark = ' ←差あり'
            print(f'{name:<16}{on[0]:8,d}{r_on:9.1f}%{off[0]:8,d}{r_off:9.1f}%'
                  f'{r_on - r_off:7.1f}pp{mark}')

    def line(label, a, mark=''):
        n, hit, cost, ret, pays, nsw = a
        if n == 0:
            return
        htr = hit / n * 100
        roi = ret / cost * 100 if cost else 0
        med = median(pays)
        avg = (sum(pays) / len(pays)) if pays else 0
        sw = nsw / n * 100 if n else 0
        print(f'{label:<16}{n:6,d}{htr:7.1f}%{roi:7.1f}%{med:8.0f}{avg:8.0f}'
              f'{sw:7.1f}%{mark}')

    def pr_tickets(period, title):
        print(f'\n=== {title} ===')
        hdr = f'{"条件":<16}{"R":>6}{"10点的中":>8}{"ROI":>8}{"中央配当":>8}{"平均配当":>8}{"入替率":>8}'
        for n_swap, lab in ((0, '基準・入れ替えなし'), (1, '入れ替え1点'), (2, '入れ替え2点')):
            print(f'\n-- {lab} --')
            for z, zname in (
                ('all', '全体'),
                ('green', '通常 3着が5番以内'),
                ('yellow', '中穴 3着が6-7番'),
            ):
                print(f'\n  [{zname}]')
                print(hdr)
                names = ['複勝積'] if n_swap == 0 else data_flags
                for name in names:
                    ns = 0 if name == '複勝積' else n_swap
                    a = cell[(period, name, ns, z)]
                    mark = ''
                    if name == '複勝積':
                        mark = ' ←基準'
                    line(name, a, mark)

    pr_horse('holdout')
    print('\n=== holdout  中穴3着レースで、複勝積の正解順位 ===')
    tot_y = sum(yellow_rank.values()) or 1
    for k in ('1-10 既に入', '11-20 繰上げ対象', '21-30', '31-35'):
        print(f'  {k}: {yellow_rank[k]:,}  ({yellow_rank[k] / tot_y * 100:.1f}%)')
    print(f'  残し内の中穴3着 {tot_y:,}R（候補外の中穴3着はこの表に含まない）')

    pr_tickets('holdout', 'holdout ← 採用判定')
    pr_horse('train')
    pr_tickets('train', 'train 参考')
    print('\n採用: 中穴の捕捉が上がり、通常の的中がほぼ落ちず、全体ROIが基準以上。')
    print('アプリは変更していない。')


if __name__ == '__main__':
    main()
