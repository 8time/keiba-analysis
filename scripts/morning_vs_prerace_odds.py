# -*- coding: utf-8 -*-
"""朝一スナップ ↔ 直前スナップの変動と3着。

時系列は data/odds_history.db。結果は CSV（凍結〜2026-06-21）と接合できるレースだけ。
Usage: python scripts/morning_vs_prerace_odds.py
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import csv_data as cd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'odds_history.db')
GAP_MIN, GAP_MAX = 30.0, 36 * 60.0  # 30分〜36時間（前日夜〜当日）


def parse_ts(s):
    s = str(s).replace(' ', 'T')[:19]
    return datetime.fromisoformat(s)


def rank_of(odds_map):
    valid = [(u, o) for u, o in odds_map.items() if o and o > 0]
    valid.sort(key=lambda x: x[1])
    return {u: i + 1 for i, (u, _) in enumerate(valid)}


def load_snaps(con):
    rows = con.execute(
        "SELECT race_id, umaban, odds_value, timestamp FROM odds_logs "
        "WHERE odds_type='win' AND odds_value>0 ORDER BY race_id, timestamp"
    ).fetchall()
    # race -> ts -> {um: odds}
    raw = defaultdict(lambda: defaultdict(dict))
    for rid, um, od, ts in rows:
        try:
            raw[str(rid)][str(ts)][int(um)] = float(od)
        except (TypeError, ValueError):
            continue
    out = []
    for rid, by_ts in raw.items():
        times = sorted(by_ts.keys(), key=parse_ts)
        if len(times) < 2:
            continue
        t0, t1 = times[0], times[-1]
        gap = (parse_ts(t1) - parse_ts(t0)).total_seconds() / 60.0
        first, last = by_ts[t0], by_ts[t1]
        common = set(first) & set(last)
        out.append({
            'rid': rid, 't0': t0, 't1': t1, 'gap': gap, 'n_snap': len(times),
            'first': first, 'last': last, 'common': common,
            'h0': parse_ts(t0).hour, 'h1': parse_ts(t1).hour,
        })
    return out


def bucket_hour(h):
    if h < 6:
        return '深夜〜早朝'
    if h < 11:
        return '朝(〜10時)'
    if h < 14:
        return '昼'
    return '午後〜直前帯'


def main():
    if not os.path.exists(DB):
        print('odds_history.db なし')
        return
    con = sqlite3.connect(DB)
    snaps = load_snaps(con)
    con.close()
    print(f'2時点以上 {len(snaps)}R')
    usable = [s for s in snaps if GAP_MIN <= s['gap'] <= GAP_MAX and len(s['common']) >= 6]
    print(f'間隔30分〜36時間かつ6頭以上 {len(usable)}R')
    print('  最初の記録の時間帯:',
          dict(Counter(bucket_hour(s['h0']) for s in usable)))
    print('  最後の記録の時間帯:',
          dict(Counter(bucket_hour(s['h1']) for s in usable)))
    print(f'  間隔 中央 {sorted(s["gap"] for s in usable)[len(usable)//2]:.0f}分')

    # 変動の大きさ（結果なしでも分かる）
    d_rank = []
    ratio = []
    fav_change = 0
    n_r = 0
    for s in usable:
        rf, rl = rank_of(s['first']), rank_of(s['last'])
        n_r += 1
        fav_f = min(rf, key=rf.get)
        fav_l = min(rl, key=rl.get)
        if fav_f != fav_l:
            fav_change += 1
        for u in s['common']:
            if u in rf and u in rl:
                d_rank.append(rl[u] - rf[u])
                a, b = s['first'][u], s['last'][u]
                if a > 0:
                    ratio.append(b / a)
    absr = sorted(abs(x) for x in d_rank)
    print(f'\n=== 記録されている動き（結果はまだ見ない） 馬 {len(d_rank)}頭 / {n_r}R ===')
    print(f'  人気が2以上動いた馬: {sum(1 for x in d_rank if abs(x)>=2)}'
          f' ({sum(1 for x in d_rank if abs(x)>=2)/len(d_rank)*100:.1f}%)')
    print(f'  人気変動の中央 |差| {absr[len(absr)//2]}')
    print(f'  1番人気が朝と直前で別人: {fav_change}/{n_r}'
          f' ({fav_change/n_r*100:.1f}%)')
    print(f'  単勝が15%以上短縮: {sum(1 for x in ratio if x<=0.85)}'
          f' / 15%以上延長: {sum(1 for x in ratio if x>=1.15)}')

    h = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win_odds', 'top3', 'chakujun'])
    h['nk'] = h['race_key'].astype(str).str[0:4] + h['race_key'].astype(str).str[8:16]
    by = {}
    for rk, g in h.groupby('nk', sort=False):
        by[str(rk)] = {int(r.umaban): r for r in g.itertuples(index=False)}

    joined = [s for s in usable if s['rid'] in by]
    print(f'\n=== 結果と接合できたレース {len(joined)}R（CSVは〜2026/6/21） ===')
    if not joined:
        print('  接合ゼロ。夏開催の記録が凍結DBの外。')
        return

    def last_odds_exp(od, horses):
        """同じ直前オッズ帯の期待3着内率（接合レース内）。粗い。"""
        return None

    # 直前オッズ帯ごとのベース（接合分）
    band_t3 = defaultdict(list)
    rows = []
    for s in joined:
        res = by[s['rid']]
        rf, rl = rank_of(s['first']), rank_of(s['last'])
        for u in s['common']:
            if u not in res or u not in rf or u not in rl:
                continue
            r = res[u]
            top3 = int(r.top3)
            od1, od0 = s['last'][u], s['first'][u]
            rows.append({
                'rid': s['rid'], 'um': u, 'top3': top3,
                'rf': rf[u], 'rl': rl[u], 'dr': rl[u] - rf[u],
                'od0': od0, 'od1': od1, 'ratio': od1 / od0 if od0 else 1.0,
                'ninki': int(r.ninki),
            })
            if od1 < 5:
                b = '〜5倍'
            elif od1 < 10:
                b = '5-10'
            elif od1 < 20:
                b = '10-20'
            else:
                b = '20倍〜'
            band_t3[b].append(top3)

    exp = {b: (sum(v) / len(v) if v else 0) for b, v in band_t3.items()}

    def band_of(od):
        if od < 5:
            return '〜5倍'
        if od < 10:
            return '5-10'
        if od < 20:
            return '10-20'
        return '20倍〜'

    def show(title, pred):
        sub = [x for x in rows if pred(x)]
        if not sub:
            print(f'  {title}: 0頭')
            return
        t3 = sum(x['top3'] for x in sub)
        e = sum(exp.get(band_of(x['od1']), 0.2) for x in sub)
        rate = t3 / len(sub) * 100
        print(f'  {title}: {t3}/{len(sub)}  3着内 {rate:.1f}%  '
              f'(直前倍率帯の目安 {e/len(sub)*100:.1f}%)')

    print(f'  馬 {len(rows)}頭')
    show('全体', lambda x: True)
    show('人気2以上上昇（売れた）', lambda x: x['dr'] <= -2)
    show('人気2以上下降（沈んだ）', lambda x: x['dr'] >= 2)
    show('単勝15%以上短縮', lambda x: x['ratio'] <= 0.85)
    show('単勝15%以上延長', lambda x: x['ratio'] >= 1.15)
    show('書籍:隠れた本命(朝top3→3以上下降)',
         lambda x: x['rf'] <= 3 and x['rl'] - x['rf'] >= 3)
    show('書籍:直前だけ売れた(朝6+→直前3以内)',
         lambda x: x['rf'] >= 6 and x['rl'] <= 3 and x['rf'] - x['rl'] >= 4)
    show('直前1番人気・朝も1番', lambda x: x['rl'] == 1 and x['rf'] == 1)
    show('直前1番人気・朝は3番以下', lambda x: x['rl'] == 1 and x['rf'] >= 3)
    show('直前6-10番で短縮', lambda x: 6 <= x['rl'] <= 10 and x['ratio'] <= 0.85)
    show('直前6-10番で延長', lambda x: 6 <= x['rl'] <= 10 and x['ratio'] >= 1.15)

    # レース単位: 3着馬の動き
    print('\n  各レースの3着馬（朝人気→直前人気）')
    for s in joined:
        res = by[s['rid']]
        rf, rl = rank_of(s['first']), rank_of(s['last'])
        t3 = sorted(
            [int(r.umaban) for r in res.values() if int(r.top3) == 1],
            key=lambda u: int(res[u].chakujun) if res[u].chakujun == res[u].chakujun else 99,
        )
        bits = []
        for u in t3:
            a = rf.get(u, '?')
            b = rl.get(u, '?')
            bits.append(f'{u}番 {a}→{b}')
        print(f'    {s["rid"]}  {s["t0"][11:16]}→{s["t1"][11:16]}  '
              f'{int(s["gap"])}分  ' + ' / '.join(bits))


if __name__ == '__main__':
    main()
