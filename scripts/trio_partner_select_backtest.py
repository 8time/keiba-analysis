# -*- coding: utf-8 -*-
"""6-7番人気Xの『相手2頭』選び。

馬Xを3着候補にしたとき、どのペアと組むかをレース前特徴でスコアする。
ルールは「6-7番が3着だったレース」からは作らない。
脚質・位置の実測テーブルは train の全3連複正解（人気不問）から凍結。

見るもの:
  1) 実際の相手ペアが、X固定の15通りのうち何位か（中央値・top1/3/5）
  2) 鉄板8点 + 相手枠2点 の10点: 全体的中 / 中穴捕捉 / 通常的中 / ROI

Usage: python scripts/trio_partner_select_backtest.py
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd

KEEP_K = 7
N_POINTS = 10
N_IRON = 8
N_PARTNER = 2


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


def pos_band(pos):
    if pos is None:
        return '不明'
    if pos <= 0.28:
        return '前'
    if pos >= 0.55:
        return '後'
    return '中'


def triple_key(xs):
    return tuple(sorted(xs))


def prod3(fs, fk):
    p = 1.0
    for u in fs:
        p *= fk[u]
    return p


def median(xs):
    if not xs:
        return 0.0
    ys = sorted(xs)
    return float(ys[len(ys) // 2])


def add_feats(h):
    h = h.copy()
    g = h.groupby('race_key', sort=False)
    h['ab_rank'] = g['ability_score'].rank(method='min', ascending=True)
    h['blood_rk'] = g['sire_surf_t3'].rank(method='min', ascending=False)
    return h


def horse_map(kg):
    out = {}
    for rec in kg.to_dict('records'):
        u = int(rec['umaban'])
        pos = _num(rec.get('pos_ratio3'))
        ab = _num(rec.get('ability_score'))
        out[u] = {
            'nk': int(rec['ninki']),
            'fk': fuku_of(rec['ninki'], rec['win_odds']),
            'ab': ab if ab is not None else 0.7,
            'st': style_of(pos),
            'pb': pos_band(pos),
            'lap': 1.0 if (_num(rec.get('lap_fit_bin')) or 0) >= 1 else 0.0,
            'h33': _num(rec.get('h_lap33')),
            'blood': _num(rec.get('sire_surf_t3')) or 0.0,
            'br': _num(rec.get('blood_rk')) or 99.0,
            'waku': _num(rec.get('waku_n')) or 5.0,
        }
    return out


FRONT = {'逃', '先'}
BACK = {'差', '追'}


def scorers(emp_st, emp_pos):
    """相手ペアのスコア。高いほどXと組む。Xは3着役として固定。"""

    def fuku_pair(x, a, b, hs):
        return hs[a]['fk'] * hs[b]['fk']

    def ninki_pair(x, a, b, hs):
        return -hs[a]['nk'] - hs[b]['nk']

    def ability_pair(x, a, b, hs):
        # CSV ability_score は小さいほど強い
        return -(hs[a]['ab'] + hs[b]['ab'])

    def style_emp(x, a, b, hs):
        k = triple_key([hs[x]['st'], hs[a]['st'], hs[b]['st']])
        n, tot = emp_st.get(k, (0, 1))
        return (n + 1) / (tot + 20)

    def pos_emp(x, a, b, hs):
        k = triple_key([hs[x]['pb'], hs[a]['pb'], hs[b]['pb']])
        n, tot = emp_pos.get(k, (0, 1))
        return (n + 1) / (tot + 20)

    def style_rule(x, a, b, hs):
        sx, sa, sb = hs[x]['st'], hs[a]['st'], hs[b]['st']
        n_nige = sum(1 for s in (sx, sa, sb) if s == '逃')
        n_uni = len({sx, sa, sb} - {'不明'})
        x_back = sx in BACK
        pair_front = sa in FRONT or sb in FRONT
        if n_nige >= 2:
            return 0.15
        if x_back and pair_front:
            return 1.0
        if n_uni >= 3:
            return 0.75
        if n_uni >= 2:
            return 0.45
        return 0.20

    def lap_rel(x, a, b, hs):
        xf = hs[x]['lap']
        pf = hs[a]['lap'] + hs[b]['lap']
        return xf * (1.0 + 0.5 * pf) + 0.15 * pf

    def blood_rel(x, a, b, hs):
        # 血統上位ほど良い。Xと相手の平均
        return -(hs[x]['br'] + (hs[a]['br'] + hs[b]['br']) / 2.0)

    def strong_two(x, a, b, hs):
        # 強い2頭＋中穴: 相手は人気が前
        return ninki_pair(x, a, b, hs)

    def mix(x, a, b, hs):
        # 市場の相手強さ + 脚質ルール + 能力
        return (
            1.5 * fuku_pair(x, a, b, hs)
            + 0.4 * style_rule(x, a, b, hs)
            + 0.2 * ability_pair(x, a, b, hs)
        )

    return [
        ('相手=複勝積', fuku_pair),
        ('相手=人気前', ninki_pair),
        ('相手=能力上位', ability_pair),
        ('相手=脚質実測', style_emp),
        ('相手=位置実測', pos_emp),
        ('相手=脚質ルール', style_rule),
        ('相手=33関係', lap_rel),
        ('相手=血統関係', blood_rel),
        ('相手=複合', mix),
    ]


def pair_rank_of(x, win, others, score_fn, hs):
    """X固定の相手ペア一覧で、実際の相手が何位か。Xが勝ち3頭にいないなら None。"""
    if x not in win:
        return None
    pair = tuple(sorted(u for u in win if u != x))
    if len(pair) != 2:
        return None
    ranked = sorted(
        combinations(others, 2),
        key=lambda p: score_fn(x, p[0], p[1], hs),
        reverse=True,
    )
    ranked_fs = [tuple(sorted(p)) for p in ranked]
    try:
        return ranked_fs.index(pair) + 1
    except ValueError:
        return None


def ticket_partner(ordered_fuku, xs, others, hs, score_fn):
    """鉄板=複勝積上位8。残り2点は X+相手 を相手スコア順。"""
    iron = list(ordered_fuku[:N_IRON])
    used = set(iron)
    cands = []
    for x in xs:
        rest = [u for u in others if u != x]
        if len(rest) < 2:
            continue
        for a, b in combinations(rest, 2):
            fs = frozenset((x, a, b))
            if fs in used:
                continue
            cands.append((score_fn(x, a, b, hs), fs))
    cands.sort(key=lambda t: t[0], reverse=True)
    extra = []
    for _, fs in cands:
        if fs in used:
            continue
        extra.append(fs)
        used.add(fs)
        if len(extra) >= N_PARTNER:
            break
    if len(extra) < N_PARTNER:
        for fs in ordered_fuku:
            if fs not in used:
                extra.append(fs)
                used.add(fs)
            if len(extra) >= N_PARTNER:
                break
    return iron + extra[:N_PARTNER]


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'top3',
        'ability_score', 'pos_ratio3', 'lap_fit_bin', 'h_lap33',
        'sire_surf_t3', 'waku_n',
    ])
    h = add_feats(h)
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    # train の全正解3頭から脚質・位置の組を凍結（6-7番3着に限定しない）
    st_n, pos_n = Counter(), Counter()
    n_train_win = 0
    for rk, g in h[h['period'] == 'train'].groupby('race_key', sort=False):
        w = g[g['top3'] == 1]
        if len(w) != 3:
            continue
        sts, pbs = [], []
        for rec in w.to_dict('records'):
            pos = _num(rec.get('pos_ratio3'))
            sts.append(style_of(pos))
            pbs.append(pos_band(pos))
        st_n[triple_key(sts)] += 1
        pos_n[triple_key(pbs)] += 1
        n_train_win += 1
    emp_st = {k: (v, n_train_win) for k, v in st_n.items()}
    emp_pos = {k: (v, n_train_win) for k, v in pos_n.items()}
    print(f'  train 正解組から脚質テーブル {n_train_win:,}R', flush=True)

    sc_list = scorers(emp_st, emp_pos)
    sc_names = [n for n, _ in sc_list]

    # pair rank: (period, scorer) -> list of ranks
    pranks = defaultdict(list)
    # 実際の相手が人気1-2か
    partner_shape = Counter()
    # tickets
    cell = defaultdict(lambda: [0, 0, 0, 0])  # n, hit, cost, ret
    yellow_combo_rank = defaultdict(list)  # scorer -> overall rank in 35 if we ranked by... skip
    # fuku overall rank of winning combo on yellow (baseline)
    y_fuku_rank = []

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
        kg = keep_ninki(g, KEEP_K)
        if len(kg) < 3:
            continue
        hs = horse_map(kg)
        ums = list(hs.keys())
        keep = set(ums)
        fk = {u: hs[u]['fk'] for u in ums}
        in_keep = win <= keep
        third_nk = max(int(x) for x in win_rows['ninki'])
        if third_nk <= 5:
            zone = 'green'
        elif third_nk in (6, 7):
            zone = 'yellow'
        else:
            zone = 'red'

        xs = [u for u in ums if hs[u]['nk'] in (6, 7)]
        combos = [frozenset(c) for c in combinations(ums, 3)]
        ordered_fuku = sorted(combos, key=lambda fs: prod3(fs, fk), reverse=True)

        if in_keep and zone == 'yellow':
            # 実際の3着役X = 勝ち3頭のうち一番人気が薄い馬
            x_act = max(win, key=lambda u: hs[u]['nk'])
            others = [u for u in ums if u != x_act]
            if period == 'holdout':
                pair = tuple(sorted(u for u in win if u != x_act))
                partner_shape[tuple(sorted(hs[u]['nk'] for u in pair))] += 1
                try:
                    y_fuku_rank.append(ordered_fuku.index(win) + 1)
                except ValueError:
                    pass
            if x_act in keep and len(others) >= 2:
                for name, fn in sc_list:
                    rnk = pair_rank_of(x_act, win, others, fn, hs)
                    if rnk is not None:
                        pranks[(period, name)].append(rnk)

        # 10点
        jobs = [('複勝積10', None)]
        for name, fn in sc_list:
            jobs.append((name, fn))
        for name, fn in jobs:
            if name == '複勝積10':
                top = ordered_fuku[:N_POINTS]
            else:
                top = ticket_partner(ordered_fuku, xs, ums, hs, fn)
            hit = bool(in_keep and win in set(top))
            for per in (period, 'ALL'):
                for z in ('all', zone):
                    c = cell[(per, name, z)]
                    c[0] += 1
                    c[1] += int(hit)
                    c[2] += N_POINTS * 100
                    c[3] += payout if hit else 0.0

    def pct(a, b):
        return a / b * 100 if b else 0.0

    def pr_pair(period, title):
        print(f'\n=== {title}  X固定の相手15通りでの実際の相手順位 ===')
        print('1位=その方法が正解の相手2頭を一番に選べた。市場の複勝積が基準。')
        print(f'{"方法":<16}{"n":>6}{"中央":>6}{"平均":>6}{"1位":>7}{"3位内":>7}{"5位内":>7}')
        for name in sc_names:
            rs = pranks[(period, name)]
            if not rs:
                continue
            n = len(rs)
            top1 = sum(1 for r in rs if r == 1)
            top3 = sum(1 for r in rs if r <= 3)
            top5 = sum(1 for r in rs if r <= 5)
            mark = ' ←基準' if name == '相手=複勝積' else ''
            print(f'{name:<16}{n:6,d}{median(rs):6.0f}{sum(rs)/n:6.1f}'
                  f'{pct(top1, n):6.1f}%{pct(top3, n):6.1f}%{pct(top5, n):6.1f}%{mark}')

    def pr_tickets(period, title):
        print(f'\n=== {title}  鉄板8点+相手枠2点 ===')
        print(f'{"方法":<16}{"全体的中":>8}{"全体ROI":>8}{"通常的中":>8}{"中穴捕捉":>8}')
        names = ['複勝積10'] + sc_names
        for name in names:
            a = cell[(period, name, 'all')]
            g = cell[(period, name, 'green')]
            y = cell[(period, name, 'yellow')]
            if a[0] == 0:
                continue
            mark = ' ←基準' if name == '複勝積10' else ''
            print(f'{name:<16}{pct(a[1], a[0]):7.1f}%{(a[3]/a[2]*100 if a[2] else 0):7.1f}%'
                  f'{pct(g[1], g[0]):7.1f}%{pct(y[1], y[0]):7.1f}%{mark}')

    pr_pair('holdout', 'holdout ← 相手選びの判定')
    if y_fuku_rank:
        print(f'\n  中穴で複勝積の組全体順位 中央 {median(y_fuku_rank):.0f}  平均 {sum(y_fuku_rank)/len(y_fuku_rank):.1f}'
              f'  （n={len(y_fuku_rank):,}）')
        bins = [(1, 10, '1-10'), (11, 20, '11-20'), (21, 30, '21-30'), (31, 99, '31-')]
        for lo, hi, lab in bins:
            c = sum(1 for r in y_fuku_rank if lo <= r <= hi)
            print(f'    全体{lab}: {c:,}  ({c/len(y_fuku_rank)*100:.1f}%)')
    print('\n  holdout 実際の相手2頭の人気')
    tot = sum(partner_shape.values()) or 1
    for k, v in partner_shape.most_common(12):
        print(f'    人気{k[0]}-{k[1]}: {v:,}  ({v/tot*100:.1f}%)')

    pr_tickets('holdout', 'holdout ← 10点の採用判定')
    pr_pair('train', 'train 参考（脚質実測は同じtrainなので楽観）')
    pr_tickets('train', 'train 参考')
    print('\n相手選びが前進していれば、相手順位の中央が複勝積より小さくなる。')
    print('アプリは変更していない。')


if __name__ == '__main__':
    main()
