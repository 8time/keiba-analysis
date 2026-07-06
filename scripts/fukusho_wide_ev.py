# -*- coding: utf-8 -*-
"""複勝/ワイド EV最適化 — scripts/fukusho_wide_ev.py (Fable案件③)

fukusho_combo_backtest.py で見つかった『人気薄×combo≥4の複勝+EV(2024-26)』を、
①長い履歴(2016+) ②ワイド ③オッズ帯 ④他エッジ合成 まで広げて厳密検証する。

comboの長期化: 元combo(vh2_combo_cache)は2024+のみ、かつ構成モジュール(補正T get_figure/
血統 blood_score/騎手 jockey_power)は全期間の静的統計=2016-2023に遡ると未来情報を含む。
→ 本スクリプトは **combo6p**(CSVのleak-free連続量シグナルから同じ6本をレース内top3化した
   厳密リーク無し版)を定義して全期間で使う:
   🔵h7_rank≤3(補正T) / 🔥spurt_idx top3(末脚) / 🧬sire_surf_t3 top3(血統) /
   🧬sire_winroi≥1.0(血統回収) / ⚡lap_fit_bin=1(33ラップ) / 👑jockey_form_t3 top3(騎手)
   2024+では元comboとの対応を実測して読み替え表を示す。

検証規約: 配当は実データ(payouts・網羅率99.9%)。bootstrapは**レース単位クラスタ**(同一レース内の
相関を保守的に扱う)。era split: 2016-2023(仮説発見前=真のout-of-sample) / 2024-2026(発見期) / 年別。
+EV判定 = 90%CI下限>100% が複数年・両eraで維持。

Usage: python scripts/fukusho_wide_ev.py
Output: data/fukusho_wide_ev.json + 標準出力レポート
"""
import os
import sys
import json
import sqlite3
import time as _time

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, 'data', 'jravan.db')
OUT = os.path.join(ROOT, 'data', 'fukusho_wide_ev.json')

POP_MIN = 7          # 主母集団(案件①/元検証と同じ7番人気以下)
N_BOOT = 2000
RNG = np.random.default_rng(42)

report = {'ts': _time.strftime('%Y-%m-%d %H:%M:%S'), 'sections': {}}


# ───────────────────────── 配当ロード ─────────────────────────

def load_payouts():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    fuku, wide = {}, {}
    for rk, cb, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts "
            "WHERE bet_type='複勝' AND race_key>='2016'"):
        c = str(cb)
        if c.isdigit():
            fuku[(rk, int(c))] = float(pay)
    for rk, cb, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts "
            "WHERE bet_type='ワイド' AND race_key>='2016'"):
        c = str(cb)
        if len(c) == 4 and c.isdigit():
            a, b = int(c[:2]), int(c[2:])
            wide[(rk, (min(a, b), max(a, b)))] = float(pay)
    con.close()
    print(f'配当: 複勝{len(fuku):,} / ワイド{len(wide):,} (2016+)', file=sys.stderr)
    return fuku, wide


def load_place_odds():
    """事前複勝オッズ(odds表 bet_type='place'・単一スナップショット)。(rk,umaban)->odds"""
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    po = {}
    for rk, cb, od in con.execute(
            "SELECT race_key, combo, odds FROM odds "
            "WHERE bet_type='place' AND race_key>='2016'"):
        c = str(cb)
        if c.isdigit() and od and od > 0:
            po[(rk, int(c))] = float(od)
    con.close()
    print(f'事前複勝オッズ: {len(po):,}頭 (2016+)', file=sys.stderr)
    return po


# ───────────────────────── bootstrap(レース単位クラスタ) ─────────────────────────

def boot_roi(bets, label, min_bets=50, store=None):
    """bets: DataFrame[race_key, cost, ret]。レース単位クラスタbootstrapのROI 90%CI。"""
    m = len(bets)
    if m < min_bets:
        print(f'  {label:34s} n={m}(小標本・判定不可)')
        return None
    g = bets.groupby('race_key', sort=False).agg(c=('cost', 'sum'), r=('ret', 'sum'))
    cost, ret = g['c'].values, g['r'].values
    n = len(cost)
    idx = RNG.integers(0, n, size=(N_BOOT, n))
    rois = ret[idx].sum(axis=1) / cost[idx].sum(axis=1)
    rois.sort()
    lo, mid, hi = rois[int(N_BOOT*0.05)], rois[N_BOOT//2], rois[int(N_BOOT*0.95)]
    hit = (bets['ret'] > 0).mean()
    v = '★★+EV(CI下限>100%)' if lo > 1.0 else ('floor超' if lo > 0.75 else '未達')
    print(f'  {label:34s} n={m:6d}({n:5d}R) 的中{hit:5.1%} ROI{mid:6.1%} '
          f'90%CI[{lo:5.1%},{hi:6.1%}] {v}')
    res = {'n': m, 'races': n, 'hit': float(hit), 'roi': float(mid),
           'lo': float(lo), 'hi': float(hi)}
    if store is not None:
        store[label] = res
    return res


# ───────────────────────── combo6p(leak-free長期combo) ─────────────────────────

def build_combo6p(df):
    """CSVのleak-free連続量から元comboと同じ6シグナルのレース内top3化を再構成。"""
    for src, out in (('spurt_idx', '_r_sp'), ('sire_surf_t3', '_r_bl'),
                     ('jockey_form_t3', '_r_jk')):
        df[out] = df.groupby('race_key')[src].rank(method='min', ascending=False,
                                                   na_option='bottom')
    df['s_h7'] = (df['h7_rank'] <= 3).astype(int)
    df['s_sp'] = (df['_r_sp'] <= 3).astype(int)
    df['s_bl'] = (df['_r_bl'] <= 3).astype(int)
    df['s_jk'] = (df['_r_jk'] <= 3).astype(int)
    df['s_lap'] = (df['lap_fit_bin'] == 1).astype(int)
    df['s_roi'] = (df['sire_winroi'] >= 1.0).astype(int)
    df['combo6p'] = df[['s_h7', 's_sp', 's_bl', 's_jk', 's_lap', 's_roi']].sum(axis=1)
    df.drop(columns=['_r_sp', '_r_bl', '_r_jk'], inplace=True)
    return df


def main():
    t0 = _time.time()
    fuku, wide = load_payouts()
    place = load_place_odds()

    cols = ['race_key', 'day', 'umaban', 'ninki', 'win_odds', 'chakujun', 'top3',
            'h7_rank', 'spurt_idx', 'sire_surf_t3', 'jockey_form_t3', 'lap_fit_bin',
            'sire_winroi', 'combo', 'field_size']
    df = cd.load_horses(cols=cols, with_period=False)
    df = build_combo6p(df)
    df['year'] = df['day'] // 10000
    df['era'] = np.where(df['year'] <= 2023, '2016-23(out-of-sample)', '2024-26(発見期)')
    df['fpay'] = [fuku.get((str(r), int(u)), 0.0)
                  for r, u in zip(df['race_key'].astype(str), df['umaban'])]
    df['pod'] = [place.get((str(r), int(u)), np.nan)
                 for r, u in zip(df['race_key'].astype(str), df['umaban'])]
    t3 = df[df['top3'] == 1]
    cov = (t3['fpay'] > 0).mean()
    print(f'馬行 {len(df):,} (2016+)  複勝配当網羅率(3着内馬)={cov:.1%}  '
          f'事前複勝オッズ網羅率={df["pod"].notna().mean():.1%}', file=sys.stderr)

    pop = df[df['ninki'] >= POP_MIN].copy()
    pop['cost'] = 100.0
    pop['ret'] = np.where(pop['top3'] == 1, pop['fpay'], 0.0)

    # ══ ① combo6p の妥当性: 元combo(2024+)との対応 ══
    print('\n' + '=' * 84)
    print('【① combo6p(leak-free長期版) vs 元combo(モジュール版・2024+のみ)の対応】')
    both = pop[pop['combo'].notna()]
    ct = pd.crosstab(both['combo'].astype(int), both['combo6p'])
    print('  クロス表(行=元combo/列=combo6p):')
    print('  ' + ct.to_string().replace('\n', '\n  '))
    corr = both['combo'].corr(both['combo6p'])
    print(f'  相関={corr:.3f}')
    sec1 = {'corr': float(corr)}
    print('  [2024+ 複勝ROI 再現比較(レースクラスタbootstrap)]')
    for th in (3, 4):
        boot_roi(both[both['combo'] >= th], f'元combo>={th} (2024+)', store=sec1)
        boot_roi(both[both['combo6p'] >= th], f'combo6p>={th} (2024+)', store=sec1)
    report['sections']['1_agreement'] = sec1

    # ══ ② 長期履歴での複勝EV(最重要) ══
    print('\n【② 複勝ROI×combo6p (人気薄7+・実配当・レースクラスタbootstrap 90%CI)】')
    sec2 = {}
    for era, sub in pop.groupby('era'):
        print(f'  --- {era}  base(全人気薄)複勝率{(sub["ret"]>0).mean():.1%} ---')
        for c in range(0, 6):
            boot_roi(sub[sub['combo6p'] == c], f'combo6p={c} [{era[:7]}]', store=sec2)
        for th in (2, 3, 4):
            boot_roi(sub[sub['combo6p'] >= th], f'combo6p>={th} [{era[:7]}]', store=sec2)
    print('  --- 年別(combo6p>=3 / >=4) ---')
    for y in range(2016, 2027):
        boot_roi(pop[(pop['combo6p'] >= 3) & (pop['year'] == y)], f'combo6p>=3 {y}',
                 min_bets=80, store=sec2)
    for y in range(2016, 2027):
        boot_roi(pop[(pop['combo6p'] >= 4) & (pop['year'] == y)], f'combo6p>=4 {y}',
                 min_bets=80, store=sec2)
    report['sections']['2_fukusho_long'] = sec2

    # ══ ③ オッズ帯最適化 ══
    print('\n【③ オッズ帯別 複勝ROI(combo6p>=3・人気薄7+・全期間2016+)】')
    sec3 = {}
    hi = pop[pop['combo6p'] >= 3]
    wb = [(5, 10), (10, 20), (20, 30), (30, 50), (50, 100), (100, 9999)]
    print('  [単勝オッズ帯]')
    for a, b in wb:
        boot_roi(hi[(hi['win_odds'] >= a) & (hi['win_odds'] < b)],
                 f'combo6p>=3 単勝{a}-{b}倍', store=sec3)
    print('  [事前複勝オッズ帯]')
    pb = [(1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 8.0), (8.0, 15.0), (15.0, 999.0)]
    for a, b in pb:
        boot_roi(hi[(hi['pod'] >= a) & (hi['pod'] < b)],
                 f'combo6p>=3 複勝{a}-{b}倍', store=sec3)
    print('  [単複乖離接続: 単勝≥10倍×事前複勝≤3倍]')
    boot_roi(hi[(hi['win_odds'] >= 10) & (hi['pod'] <= 3.0)],
             'combo6p>=3 × 単複乖離', store=sec3)
    boot_roi(pop[(pop['win_odds'] >= 10) & (pop['pod'] <= 3.0)],
             '単複乖離のみ(combo不問)', store=sec3)
    report['sections']['3_odds_band'] = sec3

    # ══ ④ ワイド ══
    print('\n【④ ワイド(実配当)・combo6p馬絡み(レースクラスタbootstrap)】')
    sec4 = {}
    pop_idx = df.set_index(['race_key'])
    by_race = df.groupby('race_key')
    uma_top3 = {rk: set(g.loc[g['top3'] == 1, 'umaban'].astype(int))
                for rk, g in by_race}

    def wide_bets(th, mode):
        rows = []
        anchors_all = df[(df['ninki'] >= POP_MIN) & (df['combo6p'] >= th)]
        fav_all = df[df['ninki'] <= 4]
        favs = fav_all.groupby('race_key')['umaban'].apply(list)
        alls = by_race['umaban'].apply(list)
        for rk, g in anchors_all.groupby('race_key'):
            aus = [int(u) for u in g['umaban']]
            if mode == 'a':  # combo×combo
                pairs = [(a, b) for i, a in enumerate(aus) for b in aus[i+1:]]
            elif mode == 'b':  # combo×人気1-4
                fv = [int(u) for u in favs.get(rk, [])]
                pairs = [(a, f) for a in aus for f in fv]
            else:            # combo×全馬
                al = [int(u) for u in alls.get(rk, [])]
                pairs = [(a, o) for a in aus for o in al if o != a]
                pairs = list({(min(a, b), max(a, b)) for a, b in pairs})
            for a, b in pairs:
                key = (str(rk), (min(a, b), max(a, b)))
                pay = wide.get(key)
                hit3 = uma_top3.get(rk, set())
                ret = pay if (pay and a in hit3 and b in hit3) else 0.0
                rows.append((rk, 100.0, ret or 0.0))
        return pd.DataFrame(rows, columns=['race_key', 'cost', 'ret'])

    for th in (3, 4):
        for mode, lbl in (('a', 'combo×combo'), ('b', 'combo×人気1-4'), ('c', 'combo×全馬')):
            bets = wide_bets(th, mode)
            boot_roi(bets, f'ワイド combo6p>={th} {lbl}', store=sec4)
    # era別(本線候補のみ)
    print('  [era別: combo6p>=4 × 人気1-4]')
    bets = wide_bets(4, 'b')
    bets['year'] = bets['race_key'].astype(str).str[:4].astype(int)
    boot_roi(bets[bets['year'] <= 2023], 'ワイド>=4×人気 2016-23', store=sec4)
    boot_roi(bets[bets['year'] >= 2024], 'ワイド>=4×人気 2024-26', store=sec4)
    report['sections']['4_wide'] = sec4

    # ══ ⑤ 他エッジ単体・合成の複勝EV ══
    print('\n【⑤ 他エッジの複勝EV再評価(人気薄7+・全期間)】')
    sec5 = {}
    singles = {'🔵補正T top3': pop['s_h7'] == 1, '🔥末脚 top3': pop['s_sp'] == 1,
               '🧬血統 top3': pop['s_bl'] == 1, '🧬回収≥100%': pop['s_roi'] == 1,
               '⚡33適合': pop['s_lap'] == 1, '👑騎手 top3': pop['s_jk'] == 1}
    for lbl, m in singles.items():
        boot_roi(pop[m], f'{lbl} 単体', store=sec5)
    report['sections']['5_singles'] = sec5

    # ══ ⑥ リーク署名(元combo+EVの正体判定) ══
    # 元combo構成モジュールは凍結DB全期間の静的統計(get_figure=馬の未来走含むベスト補正T/
    # jockey_power before_key無し/血統静的辞書)=歴史レース評価ではlook-ahead。
    # 本物のエッジなら「leak-free版とも一致する群」が良いはず。リークなら
    # 「未来情報でのみ上位に見える群」に利益が集中するはず。
    print('\n【⑥ リーク署名: 元combo(2024+)の+EVはどこに住んでいるか】')
    sec6 = {}
    hi4 = both[both['combo'] >= 4]
    boot_roi(hi4[hi4['combo6p'] >= 3], '元combo>=4 ∧ combo6p>=3(一致)', store=sec6)
    boot_roi(hi4[hi4['combo6p'] <= 2], '元combo>=4 ∧ combo6p<=2(未来情報のみ)', store=sec6)
    hi3 = both[both['combo'] >= 3]
    boot_roi(hi3[hi3['combo6p'] >= 3], '元combo>=3 ∧ combo6p>=3(一致)', store=sec6)
    boot_roi(hi3[hi3['combo6p'] <= 2], '元combo>=3 ∧ combo6p<=2(未来情報のみ)', store=sec6)
    for y in (2024, 2025, 2026):
        boot_roi(hi4[hi4['year'] == y], f'元combo>=4 {y}(未来情報は24>25>26)',
                 min_bets=60, store=sec6)
    report['sections']['6_leak_signature'] = sec6
    print('  → +EVが不一致(未来情報のみ)群に集中し、未来情報最少の2026で消える場合、'
          '元combo+EVはリークの幻と判定。')

    with open(OUT, 'w', encoding='utf-8') as fp:
        json.dump(report, fp, ensure_ascii=False, indent=1)
    print(f'\njson → {OUT}\ndone in {_time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
