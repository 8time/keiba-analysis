# -*- coding: utf-8 -*-
"""3連複10点: 馬の点数ではなく『3頭セット』を評価する。

加点対象は馬ではなく組み合わせ。
  ① 人気合計
  ② 複勝率の積
  ③ 積 × 展開相性（レースの先行数に対して、組の前後が噛むか）
  ④ 積 × 脚質相性（3頭の脚質がバラけているか。逃げ重複は減点）
  ⑤ 積 × 3着適性（一番薄い馬が『3着役』として成立するか）
  ⑥ ③～⑤の平均
  ⑦ 市場5点 + 2強1点5点（セットの残し方そのものを変える）

主指標 = holdout の全体捕捉（選定率 × 10点）。41%の壁。
45%なら大きい。候補内66%→68%だけでは不十分。

Usage: python scripts/trio_combo_set_backtest.py
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

W = 1.5
N_POINTS = 10
FRONT = {'逃', '先'}
BACK = {'差', '追'}


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


def style_of(pos):
    if pos is None:
        return '不明'
    if pos <= 0.20:
        return '逃'
    if pos <= 0.40:
        return '先'
    if pos <= 0.65:
        return '差'
    return '追'


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(min(k, len(sub)), 'ninki')


def fuku_prod(fs, fk):
    p = 1.0
    for u in fs:
        p *= fk[u]
    return p


def feat_pace(fs, hs, race):
    """先行が多いレースは組に差し・追込、少ないレースは組に前が欲しい。"""
    n_front = race.get('n_front')
    n_hana = race.get('n_hana')
    styles = [hs[u]['st'] for u in fs]
    n_back = sum(1 for s in styles if s in BACK)
    n_fr = sum(1 for s in styles if s in FRONT)
    high = (n_front is not None and n_front >= 5) or (n_hana is not None and n_hana >= 2)
    low = (n_hana == 0 and n_front is not None and n_front <= 2)
    if high:
        return min(1.0, n_back / 2.0)
    if low:
        return min(1.0, n_fr / 2.0)
    return 0.5


def feat_style(fs, hs):
    """3頭の脚質が噛み合うか。逃げが2頭以上は組み合わせとして弱い。"""
    styles = [hs[u]['st'] for u in fs]
    known = [s for s in styles if s != '不明']
    if len(known) < 2:
        return 0.5
    n_nige = sum(1 for s in known if s == '逃')
    n_uni = len(set(known))
    has_f = any(s in FRONT for s in known)
    has_b = any(s in BACK for s in known)
    if n_nige >= 2:
        return 0.15
    if has_f and has_b and n_uni >= 2:
        return 1.0
    if n_uni >= 2:
        return 0.55
    return 0.20


def feat_third(fs, hs):
    """一番薄い馬が3着役か。鉄板3頭は市場に任せる（ここでは押し上げない）。"""
    third = max(fs, key=lambda u: hs[u]['nk'])
    nk = hs[third]['nk']
    if nk <= 4:
        return 0.35
    st = hs[third]['st']
    n_nige = sum(1 for u in fs if hs[u]['st'] == '逃')
    score = 0.40
    if st in BACK:
        score = 0.85
    elif st == '先':
        score = 0.50
    elif st == '逃' and n_nige >= 2:
        score = 0.10
    if hs[third]['spurt']:
        score = min(1.0, score + 0.25)
    return score


def feat_mean(fs, hs, race):
    return (feat_pace(fs, hs, race) + feat_style(fs, hs) + feat_third(fs, hs)) / 3.0


def rank_by(combos, key_fn, n):
    return sorted(combos, key=key_fn, reverse=True)[:n]


def hybrid_sets(ums, fk, hs, race, n=N_POINTS):
    """市場の強い組5点 + 残りから『2強＋1』を相性順に5点。"""
    combos = [frozenset(c) for c in combinations(ums, 3)]
    by_mkt = rank_by(combos, lambda fs: fuku_prod(fs, fk), n)
    first = by_mkt[: min(5, n)]
    used = set(first)
    two_plus_one = []
    for fs in combos:
        if fs in used:
            continue
        n_out = sum(1 for u in fs if hs[u]['nk'] >= 5)
        if n_out == 1:
            two_plus_one.append(fs)
    two_plus_one.sort(
        key=lambda fs: fuku_prod(fs, fk) * (1.0 + W * feat_mean(fs, hs, race)),
        reverse=True,
    )
    out = list(first)
    for fs in two_plus_one:
        if len(out) >= n:
            break
        out.append(fs)
    if len(out) < n:
        for fs in by_mkt:
            if fs not in used and fs not in out:
                out.append(fs)
            if len(out) >= n:
                break
    return out[:n]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'top3',
        'pos_ratio3', 'spurt_idx',
    ])
    rmeta = cd.load_races(cols=['race_key', 'n_front', 'n_hana', 'mean_posr', 'field_size'])
    rmeta = rmeta.drop_duplicates('race_key')
    rmap = {}
    for r in rmeta.itertuples(index=False):
        rmap[str(r.race_key)] = {
            'n_front': _num(r.n_front),
            'n_hana': _num(r.n_hana),
            'mean_posr': _num(r.mean_posr),
        }
        try:
            rmap[str(int(r.race_key))] = rmap[str(r.race_key)]
        except (TypeError, ValueError):
            pass
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)
    print(f'  セットブースト W={W}', flush=True)

    h = h.copy()
    h['spurt_rk'] = h.groupby('race_key')['spurt_idx'].rank(method='min', ascending=False)
    h['spurt_flag'] = ((h['spurt_rk'] <= 3) & (h['ninki'] >= 6)).astype(float)

    names = [
        '①人気合計', '②複勝積', '③積×展開', '④積×脚質',
        '⑤積×3着役', '⑥複合', '⑦市場5+2強1',
    ]
    cell = defaultdict(lambda: [0, 0, 0, 0, 0])  # n_all, n_sel, n_hit, cost, ret

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

        hs_all = {}
        for r in g.itertuples(index=False):
            u = int(r.umaban)
            pos = _num(r.pos_ratio3)
            hs_all[u] = {
                'nk': int(r.ninki),
                'fk': fuku_of(r.ninki, r.win_odds),
                'st': style_of(pos),
                'spurt': bool(r.spurt_flag == 1),
            }

        for k in (6, 7, 8, 9):
            kg = keep_ninki(g, k)
            if len(kg) < 3:
                continue
            ums = [int(x) for x in kg['umaban']]
            keep = set(ums)
            hs = {u: hs_all[u] for u in ums}
            fk = {u: hs[u]['fk'] for u in ums}
            nk = {u: hs[u]['nk'] for u in ums}
            sel = win <= keep
            combos = [frozenset(c) for c in combinations(ums, 3)]

            def k_ninki(fs):
                return -sum(nk[u] for u in fs)

            def k_fuku(fs):
                return fuku_prod(fs, fk)

            def k_pace(fs):
                return k_fuku(fs) * (1.0 + W * feat_pace(fs, hs, race))

            def k_style(fs):
                return k_fuku(fs) * (1.0 + W * feat_style(fs, hs))

            def k_third(fs):
                return k_fuku(fs) * (1.0 + W * feat_third(fs, hs))

            def k_mix(fs):
                return k_fuku(fs) * (1.0 + W * feat_mean(fs, hs, race))

            tops = {
                '①人気合計': rank_by(combos, k_ninki, N_POINTS),
                '②複勝積': rank_by(combos, k_fuku, N_POINTS),
                '③積×展開': rank_by(combos, k_pace, N_POINTS),
                '④積×脚質': rank_by(combos, k_style, N_POINTS),
                '⑤積×3着役': rank_by(combos, k_third, N_POINTS),
                '⑥複合': rank_by(combos, k_mix, N_POINTS),
                '⑦市場5+2強1': hybrid_sets(ums, fk, hs, race, N_POINTS),
            }
            for name in names:
                hit = bool(sel and win in set(tops[name]))
                for per in (period, 'ALL'):
                    c = cell[(per, k, name)]
                    c[0] += 1
                    c[1] += int(sel)
                    c[2] += int(hit)
                    c[3] += N_POINTS * 100
                    c[4] += payout if hit else 0.0

    def pct(a, b):
        return a / b * 100 if b else 0.0

    def pr_period(period, title):
        print(f'\n=== {title} ===')
        for k in (6, 7, 8, 9):
            n_all = cell[(period, k, names[0])][0]
            if n_all == 0:
                continue
            n_sel = cell[(period, k, names[0])][1]
            print(f'\n-- 人気1-{k}  全{n_all:,}R / 残し内{n_sel:,}R  '
                  f'選定 {pct(n_sel, n_all):.1f}% --')
            print(f'{"モデル":<14}{"残し内10点":>10}{"全体捕捉":>10}{"10点ROI":>10}')
            for name in names:
                a = cell[(period, k, name)]
                cond = pct(a[2], a[1])
                overall = pct(a[2], a[0])
                roi = a[4] / a[3] * 100 if a[3] else 0.0
                mark = ''
                if name.startswith('①') or name.startswith('②'):
                    mark = ' ←基準'
                print(f'{name:<14}{cond:9.1f}%{overall:9.1f}%{roi:9.1f}%{mark}')

    pr_period('holdout', 'holdout ← 採用判定・主指標は全体捕捉')
    pr_period('train', 'train 参考')
    print('\n41%の壁。45%なら大きい。候補内だけの微増は不採用。')
    print('アプリは変更していない。展開は馬の加点ではなく組の前後バランス。')


if __name__ == '__main__':
    main()
