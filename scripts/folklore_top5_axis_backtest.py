# -*- coding: utf-8 -*-
"""俗説総合TOP5 × 1〜3番人気は軸か — 実装しない。

定義は repo/brief_folklore_top5_axis.md。
画面の evaluate_horse と同じ差し引き。CSV に無い前走通過・パドックは当てない。

Usage: python scripts/folklore_top5_axis_backtest.py
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import folklore_lib as fl
from scripts import csv_data as cd

MIN_N = 200
MIN_R = 80
ADOPT_A_PP = 0.03
ADOPT_B_PP = 0.02
ADOPT_C_PP = 0.02
Z_OK = 2.0
Z_SE_P = 0.22
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_JSON = os.path.join(ROOT, 'data', 'folklore_top5_axis_summary.json')

SEX = {1: '牡', 2: '牝', 3: 'セ'}
BABA = {1: '良', 2: '稍重', 3: '重', 4: '不良'}


def stats_from(resid, top3, win, odds):
    n = len(resid)
    if n == 0:
        return None
    r = np.asarray(resid, dtype=float)
    t3 = np.asarray(top3, dtype=float)
    w = np.asarray(win, dtype=float)
    o = np.asarray(odds, dtype=float)
    se = (Z_SE_P * (1 - Z_SE_P) / n) ** 0.5
    pay = np.where(w == 1, np.nan_to_num(o, nan=0.0), 0.0).sum()
    mean = float(r.mean())
    return {
        'n': int(n),
        'hit': float(t3.mean()),
        'win': float(w.mean()),
        'roi': float(pay / n) if n else 0.0,
        'resid': mean,
        'z': float(mean / se) if se > 0 else 0.0,
    }


def fmt(s):
    if s is None:
        return 'n=0'
    if s['n'] < MIN_N:
        return f"n={s['n']:6d}  (標本不足)"
    return (f"n={s['n']:6d} 複{s['hit']:5.1%} 勝{s['win']:5.1%} "
            f"単ROI{s['roi']:6.1%} 複残差{s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def fmt_r(s, min_n=MIN_R):
    if s is None:
        return 'n=0'
    if s['n'] < min_n:
        return f"R={s['n']:5d}  (標本不足)"
    return (f"R={s['n']:5d} 両方3着内{s['hit']:5.1%} "
            f"差 {s['resid']*100:+5.2f}pp z={s['z']:+5.2f}")


def _num(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def slim_score(horse):
    n_pos = n_neg = 0
    for rule in fl.CATALOG:
        m = fl.match_one(rule, horse)
        if not m or m.get('skip'):
            continue
        if m.get('sign', fl.SIGN_POS) > 0:
            n_pos += 1
        else:
            n_neg += 1
    return n_pos - n_neg, n_pos, n_neg


def make_snap(r, race):
    ninki = int(r.ninki)
    dist = int(r.kyori_int) if pd.notna(r.kyori_int) else None
    jyo = str(int(r.jyo)).zfill(2) if pd.notna(r.jyo) else ''
    day = int(r.day)
    month = (day // 100) % 100
    sex_c = int(r.sex_code) if pd.notna(r.sex_code) else 0
    futan = _num(r.futan)
    if futan is not None and futan > 80:
        futan = futan / 10.0
    baba_c = race.get('baba_code')
    try:
        baba = BABA.get(int(baba_c), '')
    except (TypeError, ValueError):
        baba = ''
    name = str(race.get('race_name') or '')
    grade = str(race.get('grade') or '')
    maiden, is_open, _cr = fl.race_kind({'RaceName': name, 'class': grade})
    if race.get('open_cls'):
        is_open = True
        if maiden:
            is_open = False
    delta = _num(r.zogen)
    if delta is not None:
        delta = int(round(delta))
    body = _num(r.bataiju)
    if body is not None:
        body = int(round(body))
    gap = _num(r.days_since)
    if gap is not None:
        gap = int(round(gap))
    ddiff = _num(r.dist_change)
    if ddiff is not None:
        ddiff = int(round(ddiff))
    return {
        'umaban': int(r.umaban),
        'ninki': ninki,
        'odds': _num(r.win_odds),
        'waku': int(r.waku_n) if pd.notna(r.waku_n) else None,
        'sex': SEX.get(sex_c),
        'age': int(r.age) if pd.notna(r.age) else None,
        'body_kg': body,
        'delta_kg': delta,
        'futan': futan,
        'sire': str(r.sire or ''),
        'bms': str(r.bms or ''),
        'dist': dist,
        'is_dirt': int(r.surface_code) == 1,
        'jyo': jyo,
        'n_horses': int(r.field_size) if pd.notna(r.field_size) else None,
        'month': month,
        'season': fl.season_of(month),
        'baba': baba,
        'is_fillies': bool(race.get('fillies')),
        'is_handicap': bool(r.is_handi1) or bool(race.get('is_handi1')),
        'is_maiden': maiden,
        'is_open': is_open,
        'gap_days': gap,
        'dist_diff': ddiff,
        'prev': None,
        'prev2': None,
        'past_n': 0,
        'paddock_tags': None,
        'training_tags': None,
    }


def score_all(horses, races):
    race_map = races.set_index('race_key').to_dict('index')
    scores = np.empty(len(horses), dtype=np.int16)
    npos = np.empty(len(horses), dtype=np.int16)
    nneg = np.empty(len(horses), dtype=np.int16)
    t0 = time.time()
    last = t0
    for i, r in enumerate(horses.itertuples(index=False)):
        race = race_map.get(r.race_key) or {}
        sc, p, n = slim_score(make_snap(r, race))
        scores[i] = sc
        npos[i] = p
        nneg[i] = n
        if (i + 1) % 20000 == 0:
            now = time.time()
            print(f"  総合 {i+1}/{len(horses)}  {now-last:.1f}s", flush=True)
            last = now
    print(f"  総合 完了 {len(horses)}頭  {time.time()-t0:.1f}s", flush=True)
    out = horses.copy()
    out['folk_score'] = scores
    out['n_pos'] = npos
    out['n_neg'] = nneg
    return out


def mark_top5(df):
    """レース内で画面と同じ順。上位5頭。"""
    df = df.copy()
    df['folk_rank'] = (
        df.sort_values(
            ['race_key', 'folk_score', 'n_neg', 'n_pos', 'umaban'],
            ascending=[True, False, True, False, True],
        )
        .groupby('race_key', sort=False)
        .cumcount() + 1
    )
    df['in_top5'] = df['folk_rank'] <= 5
    return df


def ninki_base(train):
    g = train.groupby(train['ninki'].astype(int))['top3'].mean()
    return g.to_dict()


def add_resid(df, base):
    exp = df['ninki'].astype(int).map(base).astype(float)
    df = df.copy()
    df['resid'] = df['top3'] - exp
    return df


def slice_stats(df, mask):
    sub = df.loc[mask]
    if sub.empty:
        return None
    return stats_from(sub['resid'], sub['top3'], sub['win'], sub['win_odds'])


def period_block(df, label, base):
    d = add_resid(df, base)
    p13 = d['ninki'].astype(int) <= 3
    inn = p13 & d['in_top5']
    out = p13 & ~d['in_top5']
    a_in = slice_stats(d, inn)
    a_out = slice_stats(d, out)
    a_all = slice_stats(d, p13)
    mix_in = d.loc[inn, 'ninki'].astype(int).value_counts(normalize=True).to_dict()
    mix_all = d.loc[p13, 'ninki'].astype(int).value_counts(normalize=True).to_dict()

    # B: レースで IN が2頭以上。総合1位 vs 人気1位（違う馬だけ）
    inn_df = d.loc[inn, ['race_key', 'umaban', 'ninki', 'folk_rank', 'top3',
                         'win', 'win_odds', 'resid']].copy()
    cnt = inn_df.groupby('race_key').size()
    multi_keys = set(cnt[cnt >= 2].index)
    multi = inn_df[inn_df['race_key'].isin(multi_keys)]
    folk_first = []
    ninki_first = []
    differ_f = []
    differ_n = []
    for rk, g in multi.groupby('race_key', sort=False):
        g = g.sort_values(['folk_rank', 'ninki', 'umaban'])
        ff = g.iloc[0]
        g2 = g.sort_values(['ninki', 'folk_rank', 'umaban'])
        nf = g2.iloc[0]
        folk_first.append(ff)
        ninki_first.append(nf)
        if int(ff['umaban']) != int(nf['umaban']):
            differ_f.append(ff)
            differ_n.append(nf)

    def rows_stats(rows):
        if not rows:
            return None
        t = pd.DataFrame(rows)
        return stats_from(t['resid'], t['top3'], t['win'], t['win_odds'])

    b_folk = rows_stats(folk_first)
    b_nk = rows_stats(ninki_first)
    b_df = rows_stats(differ_f)
    b_dn = rows_stats(differ_n)
    b_gap = None
    if differ_f and differ_n:
        tf = pd.DataFrame(differ_f)['top3'].to_numpy(dtype=float)
        tn = pd.DataFrame(differ_n)['top3'].to_numpy(dtype=float)
        diff = tf - tn
        n = len(diff)
        se = (0.5 * 0.5 / n) ** 0.5
        b_gap = {
            'n': n,
            'hit': float(tf.mean()),
            'win': float('nan'),
            'roi': float('nan'),
            'resid': float(diff.mean()),
            'z': float(diff.mean() / se) if se > 0 else 0.0,
        }

    # C: 同じ multi レースで、IN上位2頭 vs 人気1+2
    d2 = d.copy()
    d2['_nk'] = d2['ninki'].astype(int)
    pair_rows = []
    for rk, g in d2[d2['race_key'].isin(multi_keys)].groupby('race_key', sort=False):
        inn_g = g[g['in_top5'] & (g['_nk'] <= 3)].sort_values(
            ['folk_rank', 'ninki', 'umaban'])
        if len(inn_g) < 2:
            continue
        f1, f2 = inn_g.iloc[0], inn_g.iloc[1]
        nk = g[g['_nk'].isin((1, 2))]
        if len(nk) < 2:
            continue
        n1 = nk[nk['_nk'] == 1]
        n2 = nk[nk['_nk'] == 2]
        if n1.empty or n2.empty:
            continue
        n1, n2 = n1.iloc[0], n2.iloc[0]
        folk_both = int(f1['top3'] == 1 and f2['top3'] == 1)
        nk_both = int(n1['top3'] == 1 and n2['top3'] == 1)
        pair_rows.append({
            'folk_both': folk_both,
            'nk_both': nk_both,
            'diff': folk_both - nk_both,
        })
    c = None
    if pair_rows:
        pr = pd.DataFrame(pair_rows)
        n = len(pr)
        diff = pr['diff'].to_numpy(dtype=float)
        se = (0.5 * 0.5 / n) ** 0.5
        c = {
            'n': n,
            'hit': float(pr['folk_both'].mean()),
            'win': float(pr['nk_both'].mean()),
            'roi': float('nan'),
            'resid': float(diff.mean()),
            'z': float(diff.mean() / se) if se > 0 else 0.0,
            'folk_hit': float(pr['folk_both'].mean()),
            'nk_hit': float(pr['nk_both'].mean()),
        }

    print(f"\n=== {label} ===")
    print(f"1-3番人気 全体     {fmt(a_all)}")
    print(f"  TOP5に入った     {fmt(a_in)}")
    print(f"  TOP5に入らない   {fmt(a_out)}")
    def mix_s(m):
        return "  ".join(f"{int(k)}番{m.get(k,0)*100:.0f}%" for k in (1, 2, 3))
    print(f"  INの人気内訳     {mix_s(mix_in)}")
    print(f"  1-3の人気内訳    {mix_s(mix_all)}")
    print(f"複数INの総合1位    {fmt(b_folk)}")
    print(f"複数INの人気1位    {fmt(b_nk)}")
    print(f"違う馬のとき 総合  {fmt(b_df)}")
    print(f"違う馬のとき 人気  {fmt(b_dn)}")
    if b_gap:
        print(f"違う馬 総合−人気   n={b_gap['n']}  差{b_gap['resid']*100:+.2f}pp z={b_gap['z']:+.2f}")
    if c:
        print(f"軸2頭 総合IN上位2  両方3着内 {c['folk_hit']:.1%}  / 人気1+2 {c['nk_hit']:.1%}  "
              f"差{c['resid']*100:+.2f}pp  R={c['n']} z={c['z']:+.2f}")
    else:
        print("軸2頭 比較なし")

    return {
        'a_in': a_in, 'a_out': a_out, 'a_all': a_all,
        'mix_in': {str(int(k)): float(v) for k, v in mix_in.items()},
        'mix_all': {str(int(k)): float(v) for k, v in mix_all.items()},
        'b_folk': b_folk, 'b_nk': b_nk, 'b_df': b_df, 'b_dn': b_dn, 'b_gap': b_gap,
        'c': c,
        'n_p13': int(p13.sum()),
        'n_in': int(inn.sum()),
        'n_multi_r': int(len(multi_keys)),
    }


def pack(s):
    if not s:
        return None
    out = {}
    for k, v in s.items():
        if isinstance(v, (float, np.floating)):
            if v != v:
                out[k] = None
            else:
                out[k] = float(v)
        elif isinstance(v, (int, np.integer)):
            out[k] = int(v)
        else:
            out[k] = v
    return out


def adopt_a(train_in, hold_in):
    if not train_in or not hold_in:
        return False, '標本不足'
    if hold_in['n'] < MIN_N or train_in['n'] < MIN_N:
        return False, '標本不足'
    if train_in['resid'] <= 0:
        return False, 'train残差がプラスでない'
    if hold_in['resid'] < ADOPT_A_PP:
        return False, f"holdout残差 {hold_in['resid']*100:.2f}pp < +3.0pp"
    if hold_in['z'] < Z_OK:
        return False, f"holdout z {hold_in['z']:.2f} < +2.0"
    return True, 'A 到達'


def main():
    if not cd.available():
        raise SystemExit('data/export/horse_races.csv が無い')
    print('馬行を読みます…')
    cols = [
        'race_key', 'day', 'jyo', 'surface_code', 'kyori_int', 'field_size',
        'umaban', 'waku_n', 'ninki', 'win_odds', 'futan', 'bataiju', 'zogen',
        'sex_code', 'age', 'is_handi1', 'days_since', 'dist_change',
        'sire', 'bms', 'top3', 'win',
    ]
    horses = cd.load_horses(cols=cols)
    races = cd.load_races(cols=[
        'race_key', 'baba_code', 'race_name', 'grade', 'fillies', 'open_cls',
        'is_handi1', 'is_2yo',
    ])
    print(f"馬 {len(horses):,} / レース {races['race_key'].nunique():,}")
    scored = score_all(horses, races)
    scored = mark_top5(scored)
    train = scored[scored['period'] == 'train']
    hold = scored[scored['period'] == 'holdout']
    recent = scored[scored['period'] == 'recent']
    base = ninki_base(train)
    print('\n人気別ベース複勝 (train)')
    for k in sorted(base):
        if k <= 8:
            print(f"  {k}番 {base[k]:.1%}")

    tr = period_block(train, 'train', base)
    ho = period_block(hold, 'holdout', base)
    re = period_block(recent, 'recent', base)

    ok, why = adopt_a(tr['a_in'], ho['a_in'])
    b_ok = False
    c_ok = False
    if ok:
        bg = ho.get('b_gap')
        if bg and bg['n'] >= MIN_N and bg['resid'] >= ADOPT_B_PP and bg['z'] >= Z_OK:
            b_ok = True
        c = ho.get('c')
        if c and c['n'] >= MIN_R and c['resid'] >= ADOPT_C_PP and c['z'] >= Z_OK:
            c_ok = True

    print('\n=== 採否 ===')
    print(f"A TOP5×1-3番人気の残差: {'採用候補' if ok else '不採用'}  ({why})")
    if not ok:
        print('B/C は A 未達なので見ない（数字は上に出している）')
        print('軸信頼度・俗説ハンターの表示は変えない')
    else:
        print(f"B 複数INで総合上位: {'到達' if b_ok else '未達'}")
        print(f"C 軸2頭: {'到達' if c_ok else '未達'}")
        if ok and b_ok and c_ok:
            print('※ それでもこの工程ではエンジンに足さない。画面案は別工程。')
        else:
            print('A だけでも、軸の組み方は変えない（B/C 未達）')

    summary = {
        'adopt_a': ok,
        'adopt_b': b_ok,
        'adopt_c': c_ok,
        'why_a': why,
        'train': {k: pack(v) if k in (
            'a_in', 'a_out', 'a_all', 'b_folk', 'b_nk', 'b_df', 'b_dn', 'b_gap', 'c'
        ) else v for k, v in tr.items()},
        'holdout': {k: pack(v) if k in (
            'a_in', 'a_out', 'a_all', 'b_folk', 'b_nk', 'b_df', 'b_dn', 'b_gap', 'c'
        ) else v for k, v in ho.items()},
        'recent': {k: pack(v) if k in (
            'a_in', 'a_out', 'a_all', 'b_folk', 'b_nk', 'b_df', 'b_dn', 'b_gap', 'c'
        ) else v for k, v in re.items()},
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\n書いた {OUT_JSON}")


if __name__ == '__main__':
    main()
