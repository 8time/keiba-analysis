# -*- coding: utf-8 -*-
"""アプリは変えない。NNV/RRV 3連単の仮想収支だけ出す。

鉄板 NNV: 1着=人気1-2 / 2着=人気1-4 / 3着=精鋭1・2 + 広域網1
中庸 RRV: 1着=Rank1-2 / 2着=Rank1-4 / 3着=同じ穴3頭
荒れ: 見送り
1点=100円。CSV凍結・実配当。
"""
import os
import sys
import sqlite3
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

sys.stdout.reconfigure(encoding='utf-8')

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs
from core.trio_engine import build_trifecta_formation
from scripts.elim_cross_keep_top3_2026h1 import hunter_elite_top3
from scripts.elim_miss1_hunter import hunter_ranks

UNIT = 100
MIN_HORSES = 8
BANKROLL0 = 100000


def zone_of(v):
    if v < 50:
        return 'D'
    if v < 70:
        return 'C'
    return 'BA'


def load_pays(kind):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?",
            (kind,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit() and pay and float(pay) > 0:
            out[str(rk)] = (
                (int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def v_legs(rows):
    ninki = {int(r['umaban']): int(r['ninki']) for r in rows}
    _et3, scored = hunter_elite_top3(rows)
    _lab, elite, net = hunter_ranks(ninki, scored, pop_min=6)
    out = []
    for u in list(elite[:2]) + list(net[:1]):
        if u not in out:
            out.append(u)
    return out


def settle_tri(tickets, win, pay):
    if not tickets or not win:
        return False, 0.0
    if win in tickets:
        return True, float(pay)
    return False, 0.0


def settle_trio(tickets, win, pay):
    if not tickets or not win:
        return False, 0.0
    w = tuple(sorted(win))
    if w in tickets:
        return True, float(pay)
    return False, 0.0


def fmt_yen(n):
    return f'{int(n):+,}円'


def summarize(rows, title):
    print(f'\n=== {title} ===')
    if not rows:
        print('  (0R)')
        return
    n = len(rows)
    hits = [r for r in rows if r['hit']]
    cost = sum(r['cost'] for r in rows)
    ret = sum(r['ret'] for r in rows)
    pts = sum(r['n'] for r in rows)
    print(f'  レース {n}  的中 {len(hits)} ({100 * len(hits) / n:.1f}%)'
          f'  平均点数 {pts / n:.1f}')
    print(f'  投資 {cost:,.0f}円  払戻 {ret:,.0f}円  '
          f'収支 {fmt_yen(ret - cost)}  回収 {100 * ret / cost:.1f}%'
          if cost else '  投資0')
    if hits:
        pays = sorted(r['ret'] for r in hits)
        pnls = sorted(r['ret'] - r['cost'] for r in hits)
        print(f'  当たったときの払戻  最小{pays[0]:,.0f} / '
              f'中央{pays[len(pays)//2]:,.0f} / 平均{sum(pays)/len(pays):,.0f} / '
              f'最大{pays[-1]:,.0f}')
        print(f'  当たったときのそのレース収支  最小{fmt_yen(pnls[0])} / '
              f'中央{fmt_yen(pnls[len(pnls)//2])} / 平均{fmt_yen(sum(pnls)/len(pnls))} / '
              f'最大{fmt_yen(pnls[-1])}')
        top = sorted(hits, key=lambda r: -r['ret'])[:5]
        print('  大きい当たり:')
        for r in top:
            print(f'    {r["day"]} {r["rk"]}  {r["n"]}点  払戻{r["ret"]:,.0f}円'
                  f'  そのR {fmt_yen(r["ret"]-r["cost"])}')


def walk_bank(rows, title, also_c=True):
    bal = float(BANKROLL0)
    peak = bal
    trough = bal
    bust = None
    bought = 0
    skipped = 0
    for r in rows:
        if r['zone'] == 'C' and not also_c:
            continue
        if r['zone'] not in ('D', 'C'):
            continue
        if bal < r['cost']:
            skipped += 1
            if bust is None:
                bust = r
            continue
        bal += (r['ret'] - r['cost'])
        bought += 1
        peak = max(peak, bal)
        trough = min(trough, bal)
    print(f'\n--- 10万円 {title} ---')
    print(f'  終値 {fmt_yen(bal - BANKROLL0)}（残高 {bal:,.0f}円）'
          f'  買えた{bought}R / 資金不足で見送り{skipped}R')
    print(f'  途中最高 {peak:,.0f}円 / 途中最低 {trough:,.0f}円')
    if bust:
        print(f'  初めて足りなくなった: {bust["day"]} {bust["rk"]}'
              f'  zone={bust["zone"]} 必要{bust["cost"]:,}円 当時残高は直前')
    else:
        print('  資金不足は起きなかった')


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'chakujun',
        'ability_score', 'h7_fig', 'spurt_idx', 'sire_surf_t3', 'combo',
        'elim_n', 'avg_pos3',
    ])
    h = h[(h['day'] >= 20250101) & (h['day'] <= 20260621)]
    rmeta = cd.load_races(cols=['race_key', 'kigo', 'is_handi1'])
    meta = {str(x.race_key): x for x in rmeta.itertuples(index=False)}
    pay_t = load_pays('3連単')
    pay_o = load_pays('3連複')
    print(f'  馬行 {len(h):,} / 3連単配当 {len(pay_t):,} / 3連複配当 {len(pay_o):,}',
          flush=True)

    races = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        try:
            jyo = int(float(g['jyo'].iloc[0]))
        except (TypeError, ValueError):
            jyo = 0
        if not (1 <= jyo <= 10):
            continue
        day = int(g['day'].iloc[0])
        odds_list = [float(x) for x in g['win_odds'] if float(x) > 0]
        m = meta.get(str(rk))
        rv = vs.race_value_score(
            odds_list,
            {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
             'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g))
        if not rv:
            continue
        z = zone_of(float(rv['score']))
        g2 = g.sort_values('ninki')
        ninki_ord = [int(x) for x in g2['umaban']]
        g3 = g.sort_values('ability_score', ascending=True, na_position='last')
        rank_ord = [int(x) for x in g3['umaban']]
        fin = g.sort_values('chakujun')
        top3 = [int(x) for x in fin['umaban'][:3]]
        if len(top3) < 3:
            continue
        win = tuple(top3)
        rows = g.to_dict('records')
        v = v_legs(rows)
        pt = pay_t.get(str(rk))
        po = pay_o.get(str(rk))
        races.append(dict(
            rk=str(rk), day=day, zone=z, vscore=float(rv['score']),
            ninki=ninki_ord, rank=rank_ord, v=v, win=win, pt=pt, po=po,
        ))
    races.sort(key=lambda x: (x['day'], x['rk']))
    print(f'  対象レース {len(races):,}', flush=True)

    def eval_period(lo, hi, label):
        sel = [x for x in races if lo <= x['day'] <= hi]
        d_nnv, c_rrv = [], []
        d_old, c_old = [], []
        skipped_v = 0
        for x in sel:
            if x['zone'] == 'BA':
                continue
            v = x['v']
            win, pt, po = x['win'], x['pt'], x['po']
            if x['zone'] == 'D':
                a, b = x['ninki'][:2], x['ninki'][:4]
                if len(a) < 2 or len(b) < 4 or not v:
                    skipped_v += 1
                    continue
                tix = set(build_trifecta_formation(a, b, v))
                if not tix or not pt:
                    continue
                hit, ret = settle_tri(tix, win, pt[1])
                d_nnv.append(dict(
                    day=x['day'], rk=x['rk'], zone='D', n=len(tix),
                    cost=len(tix) * UNIT, hit=hit, ret=ret if hit else 0.0))
                # 旧プレイブック 3連複2点
                p1, p2, p3, p4 = x['ninki'][:4]
                old = {tuple(sorted((p1, p2, p3))), tuple(sorted((p1, p2, p4)))}
                if po:
                    oh, oret = settle_trio(old, win, po[1])
                    d_old.append(dict(
                        day=x['day'], rk=x['rk'], zone='D', n=2,
                        cost=200, hit=oh, ret=oret if oh else 0.0))
            else:
                a, b = x['rank'][:2], x['rank'][:4]
                if len(a) < 2 or len(b) < 4 or not v:
                    skipped_v += 1
                    continue
                tix = set(build_trifecta_formation(a, b, v))
                if not tix or not pt:
                    continue
                hit, ret = settle_tri(tix, win, pt[1])
                c_rrv.append(dict(
                    day=x['day'], rk=x['rk'], zone='C', n=len(tix),
                    cost=len(tix) * UNIT, hit=hit, ret=ret if hit else 0.0))
                tix_rrr = set(build_trifecta_formation(
                    x['rank'][:2], x['rank'][:4], x['rank'][:7]))
                if pt and tix_rrr:
                    oh, oret = settle_tri(tix_rrr, win, pt[1])
                    c_old.append(dict(
                        day=x['day'], rk=x['rk'], zone='C', n=len(tix_rrr),
                        cost=len(tix_rrr) * UNIT, hit=oh,
                        ret=oret if oh else 0.0))

        print(f'\n########## {label}  {lo}-{hi}  '
              f'対象{len(sel)}R  穴0頭でスキップ{skipped_v} ##########')
        summarize(d_nnv, f'{label} 鉄板 NNV 3連単（人気2×4×穴3）')
        summarize(c_rrv, f'{label} 中庸 RRV 3連単（Rank2×4×穴3）')
        summarize(d_nnv + c_rrv, f'{label} NNV+RRV 合計（荒れは見送り）')
        summarize(d_old, f'{label} 参考: 今のアプリ 鉄板 3連複2点')
        summarize(c_old, f'{label} 参考: 今のアプリ 中庸 Rank2-4-7 30点')

        both = sorted(d_nnv + c_rrv, key=lambda r: (r['day'], r['rk']))
        walk_bank(both, f'{label} NNVだけ（中庸は買わない）', also_c=False)
        walk_bank(both, f'{label} NNV+RRV', also_c=True)

    eval_period(20260101, 20260131, '2026年1月')
    eval_period(20250101, 20251231, '2025年')
    eval_period(20260101, 20260621, '2026年1-6月')


if __name__ == '__main__':
    main()
