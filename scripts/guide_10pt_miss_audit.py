# -*- coding: utf-8 -*-
"""買い方ガイドの10点『取りこぼし』監査（オフライン研究専用・本番の買い目は変えない）。

問い
  1) 使う馬に3着内の3頭が全部いたのに、10点に的中の組が入らないのはどこで起きるか
     （軸が3着を外した / 穴(B群)が1頭も来ていない / 候補にはあったが10点の外）
  2) 10点を『穴入り8点＋穴なし2点』などに分けると的中率は上がるか

近似（オフラインで再現できない部分の代理）
  使う馬   = 人気上位 narrow_n 推奨頭数（消去クロス後6〜8頭の代理）
  軸       = 1番人気
  B群(穴)  = 6番人気以下の vh2_score 上位3頭（精鋭1・2位＋広域網1位の代理）
  来やすさ = 単勝オッズから Harville で出した3連複確率（3連複オッズの代理）
  配当帯   = trio_engine.band_from_value_label（🌀可変帯ONの現行設定）。推定オッズ=0.75/確率
評価窓   2025-01-01 以降（vh2・能力スコアの学習期間外）。配当は jravan.db の3連複実配当。

Usage: python scripts/guide_10pt_miss_audit.py [--pool elim]
  --pool elim: 使う馬を『消去フラグ数(elim_n)の少ない順→人気順』で取る（軸は必ず含める）
"""
import os
import sys
from collections import defaultdict
from itertools import combinations, permutations

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import narrow_n
from core import trio_engine as te
from scripts import csv_data as cd
from scripts import hitrate_common as hc

EVAL_FROM = 20250101
N_POINTS = 10
UNIT = 100
PAYBACK = 0.75
ANA_POP = 6
B_SIZE = 3
POP_TOP = 5


def harville_trio(p, trio):
    tot = 0.0
    for a, b, c in permutations(trio):
        d1 = 1.0 - p[a]
        d2 = d1 - p[b]
        if d1 <= 0 or d2 <= 0:
            continue
        tot += p[a] * (p[b] / d1) * (p[c] / d2)
    return tot


def band_bonus(prob, band):
    lo, hi = band
    o = PAYBACK / prob if prob > 0 else 1e9
    if lo <= o <= hi:
        return 15.0
    if o < lo:
        return -10.0
    return -6.0


def take(ordered, n, already=()):
    out = list(already)
    for c in ordered:
        if len(out) >= n:
            break
        if c not in out:
            out.append(c)
    return out


def build_races(pool_mode='ninki'):
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'ability_score', 'vh2_score', 'elim_n'])
    h = h[h['day'] >= EVAL_FROM]
    r = cd.load_races(cols=['race_key', 'day', 'vscore', 'vlabel', 'field_size'])
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}
    pays = hc.load_payouts('3連複')
    races = []
    for rk, g in h.groupby('race_key', sort=False):
        rk = str(rk)
        m = meta.get(rk)
        if m is None or pd.isna(m.vscore):
            continue
        lab = str(m.vlabel or '')[:1]
        kind = '堅い' if lab in ('C', 'D') else ('中庸' if lab == 'B' else None)
        if kind is None:
            continue
        g = g[pd.to_numeric(g['win_odds'], errors='coerce') > 0]
        if len(g) < 8:
            continue
        wins = {frozenset(c): float(p) for c, p in pays.get(rk, [])}
        if not wins:
            continue
        g = g.sort_values(['ninki', 'win_odds'])
        ums = [int(u) for u in g['umaban']]
        inv = {int(u): 1.0 / float(o) for u, o in zip(g['umaban'], g['win_odds'])}
        s = sum(inv.values())
        p = {u: v / s for u, v in inv.items()}
        nk = {int(u): int(n) for u, n in zip(g['umaban'], g['ninki'])}
        ab = {int(u): (float(a) if pd.notna(a) else 1.0)
              for u, a in zip(g['umaban'], g['ability_score'])}
        rec = narrow_n.recommend(float(m.vscore) / 100.0, len(g))
        n_pool = int(rec['n']) if rec else 7
        if pool_mode == 'elim':
            ge = g.assign(_e=pd.to_numeric(g['elim_n'], errors='coerce').fillna(0))
            order = [int(u) for u in ge.sort_values(['_e', 'ninki'])['umaban']]
            pool = [ums[0]] + [u for u in order if u != ums[0]][:n_pool - 1]
        else:
            pool = ums[:n_pool]
        ana = g[(g['ninki'] >= ANA_POP) & g['vh2_score'].notna()]
        b_set = [int(u) for u in ana.sort_values('vh2_score', ascending=False)['umaban'][:B_SIZE]]
        races.append(dict(
            rk=rk, day=int(g['day'].iloc[0]), kind=kind, label=lab,
            band=te.band_from_value_label(lab), ums=ums, p=p, nk=nk, ab=ab,
            axis=ums[0], pool=pool, b_set=b_set, wins=wins,
        ))
    return races


# ── 10点の組み方 ──────────────────────────────────────────────
def _prob_sorted(race, cands):
    p = race['p']
    return sorted(cands, key=lambda c: -harville_trio(p, tuple(c)))


def _band_sorted(race, cands):
    p, band = race['p'], race['band']

    def key(c):
        pr = harville_trio(p, tuple(c))
        return (-band_bonus(pr, band), -pr)
    return sorted(cands, key=key)


def _ability_sorted(race, cands):
    ab = race['ab']
    return sorted(cands, key=lambda c: sum(ab[u] for u in c))


def _axis_cands(race, horses):
    a = race['axis']
    rest = [u for u in horses if u != a]
    return [frozenset((a, x, y)) for x, y in combinations(rest, 2)]


def _form_cands(race):
    a = race['axis']
    b_set = [u for u in race['b_set'] if u != a]
    horses = list(dict.fromkeys(race['pool'] + b_set))
    out = set()
    for b in b_set:
        for x in horses:
            if x not in (a, b):
                out.add(frozenset((a, b, x)))
    return list(out), horses, set(b_set)


def _no_ana_axis_cands(race, horses, b_set):
    a = race['axis']
    rest = [u for u in horses if u != a and u not in b_set]
    return [frozenset((a, x, y)) for x, y in combinations(rest, 2)]


def rules_kata(race):
    pool = race['pool']
    ax = _axis_cands(race, pool)
    band_ord = _band_sorted(race, ax)
    nnn = [c for c in _prob_sorted(race, ax)
           if all(race['nk'][u] <= POP_TOP for u in c)]
    top5 = race['ums'][:5]
    return {
        '現行型: 1軸・能力順': (pool, _ability_sorted(race, ax)[:N_POINTS]),
        '現行型: 1軸・配当帯優先': (pool, band_ord[:N_POINTS]),
        '提案: 1軸・配当帯8＋人気だけ2': (pool, take(band_ord, N_POINTS,
                                              take(nnn, N_POINTS, band_ord[:8]))),
        '提案: 1軸・来やすい順': (pool, _prob_sorted(race, ax)[:N_POINTS]),
        '提案: 軸なし・来やすい順': (pool, _prob_sorted(
            race, [frozenset(c) for c in combinations(pool, 3)])[:N_POINTS]),
        '参考: 人気上位5頭BOX': (top5, [frozenset(c) for c in combinations(top5, 3)]),
    }


def rules_chuyo(race):
    form, horses, b_set = _form_cands(race)
    if not form:
        return {}
    band_ord = _band_sorted(race, form)
    no_ana = _prob_sorted(race, _no_ana_axis_cands(race, horses, b_set))
    ax_all = _axis_cands(race, horses)
    return {
        '現行型: 穴必須・配当帯優先': (horses, band_ord[:N_POINTS]),
        '現行型: 穴必須・来やすい順': (horses, _prob_sorted(race, form)[:N_POINTS]),
        '提案: 穴入り8＋穴なし2': (horses, take(band_ord, N_POINTS,
                                        take(no_ana, N_POINTS, band_ord[:8]))),
        '提案: 穴入り6＋穴なし4': (horses, take(band_ord, N_POINTS,
                                        take(no_ana, N_POINTS, band_ord[:6]))),
        '提案: 穴入り6＋穴なし4(両方来やすい順)': (horses, take(
            _prob_sorted(race, form), N_POINTS,
            take(no_ana, N_POINTS, _prob_sorted(race, form)[:6]))),
        '提案: 1軸・来やすい順(穴は任意)': (horses, _prob_sorted(race, ax_all)[:N_POINTS]),
        '提案: 軸なし・来やすい順': (horses, _prob_sorted(
            race, [frozenset(c) for c in combinations(horses, 3)])[:N_POINTS]),
    }


# ── 集計 ─────────────────────────────────────────────────────
def score(race, horses, tickets):
    tix = set(tickets)
    hit_pay = sum(pay for c, pay in race['wins'].items() if c in tix)
    in_pool = any(c <= set(horses) for c in race['wins'])
    cost = len(tix) * UNIT
    return dict(hit=int(hit_pay > 0), ret=hit_pay, cost=cost, in_pool=int(in_pool),
                toriga=int(0 < hit_pay < cost), year=race['day'] // 10000, day=race['day'])


def summarize(rows):
    n = len(rows)
    hits = sum(r['hit'] for r in rows)
    cost = sum(r['cost'] for r in rows)
    ret = sum(r['ret'] for r in rows)
    inp = [r for r in rows if r['in_pool']]
    conv = sum(r['hit'] for r in inp) / len(inp) * 100 if inp else 0.0
    tor = sum(r['toriga'] for r in rows)
    yh = defaultdict(lambda: [0, 0])
    for r in rows:
        yh[r['year']][0] += r['hit']
        yh[r['year']][1] += 1
    lo, hi = hc.block_ci_roi(rows, n_boot=500)
    return dict(n=n, hit=hits / n * 100 if n else 0.0, roi=ret / cost * 100 if cost else 0.0,
                roi_ci=(lo, hi),
                in_pool=len(inp) / n * 100 if n else 0.0, conv=conv,
                toriga=tor / hits * 100 if hits else 0.0,
                years={y: v[0] / v[1] * 100 for y, v in sorted(yh.items())})


def miss_breakdown(races, kind, rule_name, rules_fn):
    """使う馬に3着内3頭がそろったレースだけで、外れた理由を分ける。"""
    cnt = defaultdict(int)
    for race in races:
        if race['kind'] != kind:
            continue
        rs = rules_fn(race)
        if rule_name not in rs:
            continue
        horses, tix = rs[rule_name]
        hs = set(horses)
        wins_in = [c for c in race['wins'] if c <= hs]
        if not wins_in:
            continue
        cnt['そろった'] += 1
        if any(c in set(tix) for c in wins_in):
            cnt['的中'] += 1
        elif not any(race['axis'] in c for c in wins_in):
            cnt['軸が3着外'] += 1
        elif kind == '中庸' and not any(set(race['b_set']) & c for c in wins_in):
            cnt['穴(B群)が来ていない'] += 1
        else:
            cnt['候補にはあったが10点の外'] += 1
    return cnt


def outcome_mix(races, kind):
    mix = defaultdict(int)
    n = 0
    for race in races:
        if race['kind'] != kind:
            continue
        for c in race['wins']:
            n_ana = sum(1 for u in c if race['nk'].get(u, 99) >= ANA_POP)
            key = {0: '穴なし(3頭とも1-5番人気)', 1: '穴1頭(6番人気以下が1頭)'}.get(n_ana, '穴2頭以上')
            mix[key] += 1
            n += 1
            break
    return mix, n


def main():
    pool_mode = 'elim' if '--pool' in sys.argv and 'elim' in sys.argv else 'ninki'
    print(f'読込...（使う馬の代理: {pool_mode}）', flush=True)
    races = build_races(pool_mode)
    print(f'評価レース {len(races):,}（{EVAL_FROM}以降・堅い=C/D・中庸=B）\n')
    for kind, fn in (('堅い', rules_kata), ('中庸', rules_chuyo)):
        sub = [r for r in races if r['kind'] == kind]
        mix, n = outcome_mix(races, kind)
        print(f'==== {kind} {len(sub):,}R ====')
        print('決着の形: ' + ' / '.join(f'{k} {v / n * 100:.1f}%' for k, v in sorted(mix.items())))
        pool_n = sum(len(r['pool']) for r in sub) / len(sub)
        print(f'使う馬(代理)の平均頭数 {pool_n:.1f}頭')
        per_rule = defaultdict(list)
        hits_by_rule = defaultdict(list)
        for race in sub:
            for name, (horses, tix) in fn(race).items():
                sc = score(race, horses, tix)
                per_rule[name].append(sc)
                hits_by_rule[name].append(sc['hit'])
        base = next(iter(per_rule))
        print(f'{"組み方":<28}{"的中率":>7}{"回収率":>7}{"回収95%CI":>12}{"3頭そろい":>9}'
              f'{"そろい時的中":>10}{"トリガミ":>7}  年別的中  vs現行McNemar')
        for name, rows in per_rule.items():
            s = summarize(rows)
            yrs = ' '.join(f'{y}:{v:.1f}' for y, v in s['years'].items())
            mc = hc.mcnemar(hits_by_rule[base], hits_by_rule[name]) if name != base else None
            mct = (f"+{mc['c']}/-{mc['b']} p={mc['p']:.3f}" if mc else '(基準)')
            ci = f'[{s["roi_ci"][0]:.0f}-{s["roi_ci"][1]:.0f}]'
            print(f'{name:<28}{s["hit"]:6.1f}%{s["roi"]:6.1f}%{ci:>12}{s["in_pool"]:8.1f}%'
                  f'{s["conv"]:9.1f}%{s["toriga"]:6.1f}%  {yrs}  {mct}')
        for rn in list(per_rule)[:2]:
            cnt = miss_breakdown(races, kind, rn, fn)
            tot = cnt.pop('そろった', 0)
            if tot:
                print(f'  [{rn}] 3頭そろった{tot}Rの内訳: '
                      + ' / '.join(f'{k} {v / tot * 100:.1f}%' for k, v in cnt.items()))
        print()


if __name__ == '__main__':
    main()
