# -*- coding: utf-8 -*-
"""妙味度の的中検証 ＋ 妙味度ゾーン別の最適フォーメーション探索(3連複/3連単)。

ユーザー依頼:
  ① アプリの妙味度(vscore)がどれくらい当たっているか
  ② 妙味度を3ゾーン(1-49 / 50-69 / 70-)に分け、各ゾーンで最適な買い方を探す
     ・順位は人気でなく**アプリのランク**(ability_score=LTR代理)を使う
     ・3連複と3連単の両方
     ・目安 3連複10点 / 3連単30点(あくまで目安)

妙味度の定義: core/value_scanner.race_value_score が返す score。
  荒れ確率ロジットが引ければ arare_prob*100 がそのまま vscore になる。
  よって「妙味度が当たっているか」＝「荒れ予報の較正が合っているか」を測る。

フォーメーション表記: (a,b,c) = 1着候補Rank1..a / 2着Rank1..b / 3着Rank1..c
  3連複は順不同なので「Rank上位a頭から3頭」等でなく、同じ(a,b,c)の集合版として扱う
  (1着列/2着列/3着列に入る馬の集合から3頭を選ぶ組合せ・重複除去)。

ROIは payouts の実配当を使う。控除率25%が壁なのでROI100%超はまず出ない前提で、
「同じ点数ならどの形が一番マシか」を比べる。

Usage:
  python scripts/vscore_zone_formation.py
"""
import os
import sys
import io
import sqlite3
from itertools import combinations, permutations
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import jockey_jv as jj
from core import value_scanner as vs

MIN_HORSES = 8
ZONES = [('D 鉄板 (1-49)', 0, 50), ('C 中庸 (50-69)', 50, 70), ('B/A 荒れ (70-)', 70, 201)]

# 探索するフォーメーション形 (1着列, 2着列, 3着列) = Rank上位何頭までを入れるか
TRIFECTA_SHAPES = [
    (1, 3, 5), (1, 3, 6), (1, 3, 7), (1, 4, 6), (1, 4, 7), (1, 4, 8),
    (2, 3, 5), (2, 4, 6), (2, 4, 7), (2, 5, 7), (2, 5, 8), (3, 5, 7),
    (3, 5, 8), (3, 6, 8), (1, 5, 9), (2, 6, 9), (3, 6, 9), (4, 6, 8),
]
TRIO_SHAPES = [
    (1, 3, 5), (1, 3, 6), (1, 4, 6), (1, 4, 7), (1, 5, 7), (1, 5, 8),
    (2, 4, 6), (2, 4, 7), (2, 5, 7), (2, 5, 8), (3, 5, 7), (3, 5, 8),
    (1, 6, 9), (2, 6, 9), (3, 6, 9), (1, 3, 8), (2, 3, 6), (4, 6, 9),
]


def load_payouts(bet_type):
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(list)
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type=?", (bet_type,)):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[rk].append(((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay)))
    con.close()
    return out


def build_races():
    """レース単位に: 妙味度・アプリRank順の馬番・実着順・頭数 をまとめる。"""
    h = cd.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'win_odds',
                             'chakujun', 'ability_score'])
    r = cd.load_races(cols=['race_key', 'field_size', 'kigo', 'is_handi1'])
    # race_key は全桁が数字なので pandas が int64 として読む。DBのpayoutsは文字列
    # なので、そのままだと .get() が全て外れて「該当なし」になる(実際に踏んだ)。
    h['race_key'] = h['race_key'].astype(str)
    r['race_key'] = r['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}
    out = {}
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        odds = g['win_odds'].tolist()
        m = meta.get(rk)
        rv = vs.race_value_score(
            odds, {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                   'kigo': str(getattr(m, 'kigo', '') or '')},
            n_horses=len(g))
        if not rv:
            continue
        # ⚠ability_scoreは**小さいほど強い**(1着の平均0.380 / 10着以下0.562)。
        # 降順に並べると最弱の馬から選ぶことになる(実際に踏んで的中率が1/10になった)。
        gg = g.sort_values('ability_score', ascending=True)
        ranks = gg['umaban'].astype(int).tolist()          # アプリRank順(強い順)の馬番
        fin = g.sort_values('chakujun')
        top3 = fin['umaban'].astype(int).tolist()[:3]
        if len(top3) < 3:
            continue
        out[rk] = {'vscore': rv['score'], 'ranks': ranks, 'top3': tuple(top3),
                   'day': int(g['day'].iloc[0]), 'n': len(g),
                   'ninki_top3': fin['ninki'].tolist()[:3]}
    return out


def trifecta_tickets(ranks, a, b, c):
    A, B, C = set(ranks[:a]), set(ranks[:b]), set(ranks[:c])
    return {(x, y, z) for x in A for y in B for z in C
            if len({x, y, z}) == 3}


def trio_tickets(ranks, a, b, c):
    """3連複は順不同。(a,b,c)の各列から1頭ずつ取った集合を重複除去。"""
    A, B, C = set(ranks[:a]), set(ranks[:b]), set(ranks[:c])
    out = set()
    for x in A:
        for y in B:
            for z in C:
                if len({x, y, z}) == 3:
                    out.add(tuple(sorted((x, y, z))))
    return out


def evaluate(races, pay_map, shapes, kind, zone_lo, zone_hi):
    rows = []
    sel = [d for d in races.values() if zone_lo <= d['vscore'] < zone_hi]
    for (a, b, c) in shapes:
        hit, spend, ret, pts, n = 0, 0, 0.0, [], 0
        for d in sel:
            rk_top3 = d['top3']
            tk = (trifecta_tickets(d['ranks'], a, b, c) if kind == 'trifecta'
                  else trio_tickets(d['ranks'], a, b, c))
            if not tk:
                continue
            pl = pay_map.get(d['_rk'])
            if not pl:
                continue
            n += 1
            pts.append(len(tk))
            spend += len(tk) * 100
            for combo, pay in pl:
                key = combo if kind == 'trifecta' else tuple(sorted(combo))
                if key in tk:
                    hit += 1
                    ret += pay
                    break
        if n < 50:
            continue
        rows.append({'形': f'{a}-{b}-{c}', '平均点数': np.mean(pts), 'R数': n,
                     '的中率': hit / n * 100, 'ROI': ret / spend * 100 if spend else 0,
                     '回収': ret, '投資': spend})
    return pd.DataFrame(rows)


def main():
    print('読込中...', file=sys.stderr)
    races = build_races()
    for rk in races:
        races[rk]['_rk'] = rk
    df_all = pd.DataFrame([{'vscore': d['vscore'], 'day': d['day'],
                            'arare': int(any(p >= 7 for p in d['ninki_top3']))}
                           for d in races.values()])
    print(f'対象 {len(races):,}レース（{df_all["day"].min()}〜{df_all["day"].max()}）\n')

    # ── ① 妙味度は当たっているか（較正チェック） ──
    print('■ ① 妙味度の的中度：予報どおり荒れているか')
    print('   (荒れ＝3着以内に7番人気以下が1頭でも入った)')
    print(f'{"妙味度帯":16s}{"R数":>8}{"実際の荒れ率":>12}{"予報値との差":>12}')
    print('-' * 50)
    for lo in range(0, 100, 10):
        s = df_all[(df_all['vscore'] >= lo) & (df_all['vscore'] < lo + 10)]
        if len(s) < 100:
            continue
        act = s['arare'].mean() * 100
        pred = s['vscore'].mean()
        print(f'{lo:>3}-{lo+9:<12}{len(s):>8,}{act:>11.1f}%{act-pred:>+11.1f}pp')
    _c = df_all['vscore'].corr(df_all['arare'])
    print(f'\n   妙味度と実際の荒れの相関: {_c:+.3f}')

    print(f'\n{"ゾーン":18s}{"R数":>8}{"実際の荒れ率":>12}')
    print('-' * 40)
    for lbl, lo, hi in ZONES:
        s = df_all[(df_all['vscore'] >= lo) & (df_all['vscore'] < hi)]
        if len(s):
            print(f'{lbl:18s}{len(s):>8,}{s["arare"].mean()*100:>11.1f}%')

    # ── ② ゾーン別 最適フォーメーション ──
    for kind, lbl_k, pay_key, target in (('trio', '3連複', '3連複', 10),
                                          ('trifecta', '3連単', '3連単', 30)):
        pm = load_payouts(pay_key)
        shapes = TRIO_SHAPES if kind == 'trio' else TRIFECTA_SHAPES
        print(f'\n\n{"="*74}\n■ ② {lbl_k}：妙味度ゾーン別の買い方（目安{target}点）\n{"="*74}')
        for zlbl, lo, hi in ZONES:
            d = evaluate(races, pm, shapes, kind, lo, hi)
            if d.empty:
                print(f'\n[{zlbl}] 該当なし')
                continue
            d = d.sort_values('ROI', ascending=False)
            print(f'\n[{zlbl}]  ※Rankはアプリの実力順(人気ではない)')
            print(f'{"形":>10}{"平均点":>8}{"R数":>8}{"的中率":>9}{"ROI":>8}')
            print('-' * 45)
            for _, x in d.head(6).iterrows():
                print(f'{x["形"]:>10}{x["平均点数"]:>8.1f}{x["R数"]:>8,}'
                      f'{x["的中率"]:>8.1f}%{x["ROI"]:>7.0f}%')
            near = d[(d['平均点数'] >= target * 0.6) & (d['平均点数'] <= target * 1.6)]
            if not near.empty:
                b = near.iloc[0]
                print(f'   → 目安{target}点前後で最良: **{b["形"]}** '
                      f'({b["平均点数"]:.0f}点 / 的中{b["的中率"]:.1f}% / ROI{b["ROI"]:.0f}%)')

    print('\n※控除率25%が壁。ROI100%超はまず出ない前提で「同点数ならどれがマシか」を見る。')


if __name__ == '__main__':
    main()
