# -*- coding: utf-8 -*-
"""使う馬プール固定(fixed_pool) vs 現行 人気1-4∪穴6-12 の3連複比較。

5番人気の常時追加ではない。各レースで『ユーザーがK頭残した』代理を作り、
そのK頭を recommend_trio に渡す:
  old  = 人気条件で再フィルター (fixed_pool=False)
  new  = 渡したK頭をプールに固定 (fixed_pool=True)

代理:
  ninkiK   = 人気1..K（5番を残した絞り＝今回の形）
  abilityK = 能力スコア上位K（5番を残すとは限らない）

Usage: python scripts/fixed_pool_trio_backtest.py
"""
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import trio_engine as te
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd


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


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(k, 'ninki') if len(sub) > k else sub


def keep_ability(g, k):
    return g.nlargest(min(k, len(g)), 'ability_score')


def to_horses(g):
    rows = []
    for r in g.itertuples(index=False):
        sc = r.ability_score
        if sc != sc:  # NaN
            sc = 0.0
        rows.append({
            'umaban': int(r.umaban),
            'name': str(int(r.umaban)),
            'score': float(sc),
            'pop': int(r.ninki),
            'alert': '',
        })
    return rows


def run_one(hs, win, n_points, fixed, pattern='本線'):
    r = te.recommend_trio(hs, pattern=pattern, n_points=n_points, fixed_pool=fixed)
    bets = r.get('bets') or []
    combos = [frozenset(b['combo']) for b in bets]
    hit = win in combos
    return hit, len(bets)


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'umaban', 'ninki', 'ability_score',
        'top3', 'chakujun', 'field_size',
    ])
    rmeta = cd.load_races(cols=['race_key', 'vscore', 'vlabel'])
    vscore = rmeta.drop_duplicates('race_key').set_index('race_key')['vscore'].to_dict()
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    grouped = {str(rk): g for rk, g in h.groupby('race_key', sort=False)}

    specs = []
    for k in (6, 7, 8, 9):
        specs.append((f'人気1-{k}', k, keep_ninki))
        specs.append((f'能力上位{k}', k, keep_ability))

    # cell[(spec, period, zone, n_points, mode)] = [n, hits, cost, ret, cond_n, cond_hits]
    cell = defaultdict(lambda: [0, 0, 0, 0, 0, 0])

    n_races = 0
    for rk, g in grouped.items():
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if pay is None:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay:
            continue
        win_fs, payout = pay
        if win_fs != win:
            # 配当comboは馬番。CSV馬番と一致しないレースはスキップ
            continue
        period = str(g['period'].iloc[0])
        vs = vscore.get(rk)
        if vs is None:
            try:
                vs = vscore.get(int(rk))
            except (TypeError, ValueError):
                vs = None
        if vs is None:
            vs = vscore.get(str(rk))
        try:
            vs = float(vs) if vs == vs else None
        except (TypeError, ValueError):
            vs = None
        # 見送り推奨 = 妙味度70以上 (formation_stats BA)
        skip = bool(vs is not None and vs >= 70)
        zones = ['all']
        if skip:
            zones.append('BA見送り')
        else:
            zones.append('D/C/B非見送り')
        n_races += 1
        for spec, k, fn in specs:
            kg = fn(g, k)
            if len(kg) < 3:
                continue
            keep = set(int(x) for x in kg['umaban'])
            in_keep = win <= keep
            hs = to_horses(kg)
            for mode, fixed in (('old', False), ('new', True)):
                r = te.recommend_trio(hs, pattern='本線', n_points=20, fixed_pool=fixed)
                bets = r.get('bets') or []
                combos = [frozenset(b['combo']) for b in bets]
                for n_points in (10, 20):
                    hit = win in combos[:n_points]
                    nbet = min(len(bets), n_points)
                    cost = nbet * 100
                    ret = payout if hit else 0.0
                    for z in zones:
                        for per in (period, 'ALL'):
                            key = (spec, per, z, n_points, mode)
                            c = cell[key]
                            c[0] += 1
                            c[1] += int(hit)
                            c[2] += cost
                            c[3] += ret
                            if in_keep:
                                c[4] += 1
                                c[5] += int(hit)
        if n_races % 4000 == 0:
            print(f'  {n_races:,}R...', flush=True)

    print(f'\n対象 {n_races:,}R（勝ち3頭と3連複配当が一致）')

    def row(spec, per, z, n_points, mode):
        n, hits, cost, ret, cn, ch = cell[(spec, per, z, n_points, mode)]
        if n == 0:
            return None
        hr = hits / n * 100
        roi = (ret / cost * 100) if cost else 0
        chr_ = (ch / cn * 100) if cn else 0
        return n, hr, roi, cn, chr_

    def block(per, z, title):
        print(f'\n=== {title} ===')
        print(f'{"絞り":<12}{"点":>4}{"old的中":>9}{"new的中":>9}{"差":>7}'
              f'{"oldROI":>9}{"newROI":>9}{"残し内old":>10}{"残し内new":>10}')
        for spec, k, _fn in specs:
            for n_points in (10, 20):
                a = row(spec, per, z, n_points, 'old')
                b = row(spec, per, z, n_points, 'new')
                if not a or not b:
                    continue
                dhr = b[1] - a[1]
                print(f'{spec:<12}{n_points:4d}{a[1]:8.1f}%{b[1]:8.1f}%{dhr:+6.1f}'
                      f'{a[2]:8.1f}%{b[2]:8.1f}%{a[4]:9.1f}%{b[4]:9.1f}%')

    block('holdout', 'all', 'holdout 全レース')
    block('holdout', 'BA見送り', 'holdout 見送り推奨(妙味度70+)')
    block('holdout', 'D/C/B非見送り', 'holdout 見送り以外')
    block('train', 'all', 'train 全レース（参考）')
    print('\n残し内=勝ち3頭が使う馬に入っていたレースだけ。ここが「評価して落としたか」の比較。')
    print('old=人気で再除外 / new=使う馬をプール固定。ROIは1点100円フラット。')


if __name__ == '__main__':
    main()
