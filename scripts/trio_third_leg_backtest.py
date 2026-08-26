# -*- coding: utf-8 -*-
"""3連複10点: 3着候補だけにデータを足して、人気/複勝の基準を超えられるか。

アプリの順位付けは変えない。holdout・10点的中が採用判定。
目標: 人気1-7・残し内10点が 65.8% → 70%台。67%では複雑化の価値が怪しい。
ROIが大きく崩れないこと。全体捕捉 = 候補選定率 × 残し内10点。

3着 = 組の中で一番人気が薄い馬（能力で最弱を選ぶ④は使わない）。

ベースA  人気合計
ベースB  複勝率の積
実験C    B × 穴馬ハンター(vh2。comboは7番以下のみなので5番穴が抜けない)
実験D    B × 妙味（能力順位より人気が薄い＝市場が嫌っている）
実験E    B × 33ラップ適合（検証どおり人気6+限定）
実験F    B × 血統（sire_surf レース内順位）
実験G    B × 穴VH＋妙味＋展開(後方寄り)

Usage: python scripts/trio_third_leg_backtest.py
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

# 3着特徴の掛け算ブースト。feat=1 のときスコアは (1+W) 倍。
W_BOOST = 1.5


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


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(min(k, len(sub)), 'ninki')


def all_combos(ums):
    return [frozenset(c) for c in combinations(ums, 3)]


def rank_top(combos, score_fn, n):
    return sorted(combos, key=score_fn, reverse=True)[:n]


def _num(x, default=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if v != v:
        return default
    return v


def race_pct_map(g, col, higher_better):
    """レース全頭で 1=最良, 0=最悪。欠損は入れない。"""
    rows = []
    for r in g.itertuples(index=False):
        v = _num(getattr(r, col, None))
        if v is None:
            continue
        rows.append((int(r.umaban), v))
    if len(rows) < 2:
        return {}
    rev = higher_better
    rows.sort(key=lambda kv: kv[1], reverse=rev)
    n = len(rows)
    return {u: 1.0 - i / (n - 1) for i, (u, _) in enumerate(rows)}


def feats_for_race(g):
    """馬番 -> 0..1 特徴。3着（組内で一番人気薄）にだけ掛ける。"""
    nk, ab = {}, {}
    spurt_vals = []
    for r in g.itertuples(index=False):
        u = int(r.umaban)
        nk[u] = int(r.ninki)
        av = _num(r.ability_score)
        if av is not None:
            ab[u] = av
        sv = _num(r.spurt_idx)
        if sv is not None:
            spurt_vals.append((u, sv))

    # 能力: CSVは小さいほど強い
    ab_rank = {}
    if ab:
        ordered = sorted(ab, key=lambda u: ab[u])
        for i, u in enumerate(ordered, start=1):
            ab_rank[u] = i

    vh = race_pct_map(g, 'vh2_score', True)
    blood = race_pct_map(g, 'sire_surf_t3', True)
    # blood_race_pct は小さいほど良い（rank/頭数）
    blood_pct = race_pct_map(g, 'blood_race_pct', False)

    spurt_top = set()
    if spurt_vals:
        spurt_vals.sort(key=lambda kv: -kv[1])
        spurt_top = {u for u, _ in spurt_vals[:3]}

    hunter, myomi, lap, blood_f, pace, combo_f, spurt_f = {}, {}, {}, {}, {}, {}, {}
    for r in g.itertuples(index=False):
        u = int(r.umaban)
        nki = nk[u]
        combo = _num(r.combo, 0.0) or 0.0
        combo_n = max(0.0, min(combo, 3.0)) / 3.0
        vh_p = vh.get(u, 0.0)
        # 穴ハンター: vh2は全馬、comboは7番以下のみ。5番を落とさないようvh2主。
        hunter[u] = 0.7 * vh_p + 0.3 * combo_n
        combo_f[u] = combo_n

        gap = 0.0
        if u in ab_rank:
            gap = max(0.0, nki - ab_rank[u]) / 6.0
        myomi[u] = min(1.0, gap)

        fit = _num(r.lap_fit_bin, 0.0) or 0.0
        lap[u] = 1.0 if (fit >= 1.0 and nki >= 6) else 0.0

        bf = blood.get(u)
        if bf is None:
            bf = blood_pct.get(u, 0.0)
        blood_f[u] = bf

        pr = _num(r.pos_ratio3)
        pace[u] = pr if pr is not None else 0.0

        spurt_f[u] = 1.0 if (u in spurt_top and nki >= 6) else 0.0

        hunter[u] = max(0.0, min(1.0, hunter[u]))
        myomi[u] = max(0.0, min(1.0, myomi[u]))
        blood_f[u] = max(0.0, min(1.0, blood_f[u]))
        pace[u] = max(0.0, min(1.0, pace[u]))

    return {
        'nk': nk,
        'hunter': hunter,
        'myomi': myomi,
        'lap': lap,
        'blood': blood_f,
        'pace': pace,
        'combo': combo_f,
        'spurt': spurt_f,
    }


def third_of(fs, nk):
    return max(fs, key=lambda u: nk[u])


def models_for(fk, nk, ft):
    hunter, myomi, lap, blood, pace = (
        ft['hunter'], ft['myomi'], ft['lap'], ft['blood'], ft['pace'])

    def fuku_prod(fs):
        p = 1.0
        for u in fs:
            p *= fk[u]
        return p

    def ninki_sum(fs):
        return -sum(nk[u] for u in fs)

    def boosted(feat):
        def score(fs):
            t = third_of(fs, nk)
            return fuku_prod(fs) * (1.0 + W_BOOST * feat.get(t, 0.0))
        return score

    def mix3(fs):
        t = third_of(fs, nk)
        m = (hunter.get(t, 0.0) + myomi.get(t, 0.0) + pace.get(t, 0.0)) / 3.0
        return fuku_prod(fs) * (1.0 + W_BOOST * m)

    return [
        ('A 人気合計', ninki_sum),
        ('B 複勝積', fuku_prod),
        ('C 積×穴VH', boosted(hunter)),
        ('D 積×妙味', boosted(myomi)),
        ('E 積×33', boosted(lap)),
        ('F 積×血統', boosted(blood)),
        ('G 積×複合', mix3),
    ]


MODEL_NAMES = [m[0] for m in models_for({}, {}, {
    'hunter': {}, 'myomi': {}, 'lap': {}, 'blood': {}, 'pace': {},
})]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'ability_score', 'top3',
        'vh2_score', 'combo', 'lap_fit_bin', 'sire_surf_t3', 'blood_race_pct',
        'spurt_idx', 'pos_ratio3',
    ])
    rmeta = cd.load_races(cols=['race_key', 'vscore'])
    vsmap = rmeta.drop_duplicates('race_key').set_index('race_key')['vscore'].to_dict()
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)
    print(f'  3着ブースト W={W_BOOST}（feat=1で {1 + W_BOOST:.1f} 倍）', flush=True)

    # cell[key] = [n, hits, cost, ret]
    cell = defaultdict(lambda: [0, 0, 0, 0])
    keep_n = defaultdict(int)
    all_n = defaultdict(int)
    miss_third = defaultdict(int)
    miss_n = 0

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
        vs = vsmap.get(rk)
        if vs is None:
            try:
                vs = vsmap.get(int(rk))
            except (TypeError, ValueError):
                vs = None
        try:
            vs = float(vs) if vs == vs else None
        except (TypeError, ValueError):
            vs = None
        skip = bool(vs is not None and vs >= 70)
        zones = ['all', 'BA見送り' if skip else '非見送り']

        ft = feats_for_race(g)
        nk_all = ft['nk']

        for k in (6, 7, 8, 9):
            kg = keep_ninki(g, k)
            if len(kg) < 3:
                continue
            ums = [int(x) for x in kg['umaban']]
            keep = set(ums)
            in_keep = win <= keep
            ab_fk, nk = {}, {}
            for r in kg.itertuples(index=False):
                u = int(r.umaban)
                nk[u] = int(r.ninki)
                ab_fk[u] = fuku_of(r.ninki, r.win_odds)
            mdls = models_for(ab_fk, nk, ft)
            for z in zones:
                all_n[(period, z, k)] += 1
                if in_keep:
                    keep_n[(period, z, k)] += 1
            ranked = {}
            if in_keep:
                combos = all_combos(ums)
                for name, fn in mdls:
                    ranked[name] = {
                        10: rank_top(combos, fn, 10),
                        20: rank_top(combos, fn, 20),
                    }
                if period == 'holdout' and k == 7:
                    if win not in ranked['B 複勝積'][10]:
                        t = third_of(win, nk_all)
                        miss_n += 1
                        miss_third[nk_all.get(t, 0)] += 1
            for name, _fn in mdls:
                for n_points in (10, 20):
                    hit = bool(in_keep and win in ranked[name][n_points])
                    cost = n_points * 100
                    for z in zones:
                        for per in (period, 'ALL'):
                            if in_keep:
                                c = cell[(per, z, k, name, n_points, 'cond')]
                                c[0] += 1
                                c[1] += int(hit)
                                c[2] += cost
                                c[3] += payout if hit else 0.0
                            a = cell[(per, z, k, name, n_points, 'all')]
                            a[0] += 1
                            a[1] += int(hit)
                            a[2] += cost
                            a[3] += payout if hit else 0.0

    def line(name, a, b, keep_rate, mark=''):
        if a[0] == 0:
            return
        h10 = a[1] / a[0] * 100
        h20 = b[1] / b[0] * 100 if b[0] else 0
        r10 = a[3] / a[2] * 100 if a[2] else 0
        r20 = b[3] / b[2] * 100 if b[2] else 0
        overall = keep_rate * (a[1] / a[0]) * 100
        print(f'{name:<12}{h10:9.1f}%{h20:9.1f}%{r10:9.1f}%{overall:9.1f}%{mark}')

    def pr_block(period, zone, title):
        print(f'\n=== {title} ===')
        for k in (6, 7, 8, 9):
            n_all = cell[(period, zone, k, MODEL_NAMES[0], 10, 'all')][0]
            n_cond = cell[(period, zone, k, MODEL_NAMES[0], 10, 'cond')][0]
            if n_all == 0:
                continue
            keep_rate = n_cond / n_all if n_all else 0
            print(f'\n-- 人気1-{k}  全{n_all:,}R / 残し内{n_cond:,}R  '
                  f'候補選定率 {keep_rate * 100:.1f}% --')
            print(f'{"モデル":<12}{"残し内10点":>10}{"残し内20点":>10}'
                  f'{"10点ROI":>10}{"全体捕捉":>10}')
            for name in MODEL_NAMES:
                a = cell[(period, zone, k, name, 10, 'cond')]
                b = cell[(period, zone, k, name, 20, 'cond')]
                mark = ''
                if name == 'B 複勝積':
                    mark = ' ←基準'
                elif name == 'A 人気合計':
                    mark = ' ←基準'
                line(name, a, b, keep_rate, mark)
            print('  全体捕捉 = 候補選定率 × 残し内10点。ROIは残し内・1点100円。')

    pr_block('holdout', 'all', 'holdout 全 ← 採用判定')
    pr_block('holdout', '非見送り', 'holdout 見送り以外')
    pr_block('holdout', 'BA見送り', 'holdout 見送り推奨(妙味度70+)')
    pr_block('train', 'all', 'train 参考')

    print('\n=== holdout・人気1-7・複勝積が10点で外した組の3着人気 ===')
    if miss_n:
        for nki in sorted(miss_third):
            print(f'  3着が{nki}番人気: {miss_third[nki]:,}  ({miss_third[nki] / miss_n * 100:.1f}%)')
        print(f'  外れ合計 {miss_n:,}')
    else:
        print('  (なし)')
    print('\n主指標は残し内10点。65.8%→67%では不十分、70%台なら面白い。')
    print('20点で勝って10点で負ける方式は不採用。アプリは変更していない。')


if __name__ == '__main__':
    main()
