# -*- coding: utf-8 -*-
"""KYI(外厩/帰厩)データを使った2俗説の追加検証。

対象:
  skip_nf_layoff  「ノーザンファーム外厩の中9週以上・1番人気は買い」
  skip_kikyo      「レース11〜13日前の最短帰厩でラスト1Fが速い馬は勝負」

設計:
  - KYI_2025.zip (2025年109開催日) を必要列だけ高速パース
  - jravan.db の JRA平地 (全年=間隔計算用 / 2021-24=train基準 / 2025=評価) と結合
  - 評価は従来どおり「複勝率残差(実績-人気別基準)」+ z値。2025を上半期/下半期に割って符号安定性も見る
  - NF俗説は生の勝率主張(36.6% vs 29.9%)なので勝率も併記
"""
import os
import re
import sys
import json
import sqlite3
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd

from scripts import jrdb_read

DB = os.path.join(ROOT, 'data', 'jravan.db')
KYI_ZIP = os.path.join(ROOT, 'data', 'jrdb', 'raw', 'KYI_2025.zip')
OUT_JSON = os.path.join(ROOT, 'data', 'kyi_layoff_kikyo_summary.json')

Z_SE_P = 15.4  # folklore_effectiveness_backtest と同じ (複勝SEは人気に弱依存するが一貫性優先)
TRAIN = (2021, 2024)
NF_PAT = re.compile(r'ノーザン|ＮＦ|NF')

KYI_COLS = ['場コード', 'Ｒ', '馬番', '血統登録番号', '馬名',
            '入厩何走目', '入厩年月日', '入厩何日前', '放牧先', '放牧先ランク']


def load_kyi_fast():
    """必要列だけのレイアウトで KYI zip をパース"""
    layout, reclen, spec = jrdb_read.build_layout('KYI')
    lay = [f for f in layout if f[0] in KYI_COLS]
    frames = []
    with zipfile.ZipFile(KYI_ZIP) as z:
        names = sorted(n for n in z.namelist() if n.upper().endswith('.TXT'))
        for n in names:
            frames.append(jrdb_read.parse_buf(z.read(n), lay, reclen,
                                              jrdb_read._day_from_name(n)))
    df = pd.concat(frames, ignore_index=True)
    return df


def load_jravan():
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT r.race_key, r.year, r.monthday, r.jyo, r.race_num, r.surface,"
        " t.ketto_num, t.umaban, t.chakujun, t.ninki, t.ijo"
        " FROM races r JOIN results t ON r.race_key = t.race_key"
        " WHERE r.jyo IN ('01','02','03','04','05','06','07','08','09','10')"
        "   AND r.surface IN ('芝','ダート')", con)
    tr = pd.read_sql(
        "SELECT ketto_num, cho_date, lap_20 FROM training", con)
    con.close()
    df['day'] = (df['year'].astype(int) * 10000
                 + pd.to_numeric(df['monthday'], errors='coerce')).astype('Int64')
    df['dt'] = pd.to_datetime(df['day'], format='%Y%m%d', errors='coerce')
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)
    df['year_i'] = df['year'].astype(int)
    return df, tr


def add_gap(df):
    """有効走のみで前走日をシフト → gap_days"""
    v = df[df['valid']].sort_values(['ketto_num', 'day', 'race_key'])
    v = v.copy()
    v['p_dt'] = v.groupby('ketto_num', sort=False)['dt'].shift(1)
    v['gap_days'] = (v['dt'] - v['p_dt']).dt.days
    return df.merge(v[['race_key', 'umaban', 'ketto_num', 'gap_days']],
                    on=['race_key', 'umaban', 'ketto_num'], how='left')


def resid_stats(sub, base):
    """複勝率残差(実績-人気別train基準)と z"""
    sub = sub[sub['valid'] & sub['ninki'].between(1, 18)]
    n = len(sub)
    if n == 0:
        return dict(n=0)
    top3 = (sub['chakujun'] <= 3).mean() * 100
    exp = sub['ninki'].map(base).mean() * 100
    resid = top3 - exp
    z = resid / (Z_SE_P / np.sqrt(n))
    win = (sub['chakujun'] == 1).mean() * 100
    return dict(n=int(n), top3=round(top3, 1), exp=round(exp, 1),
                resid=round(resid, 1), z=round(z, 1), win=round(win, 1))


def main():
    print('KYI読み込み...')
    kyi = load_kyi_fast()
    print(f'  {len(kyi):,}行  day={kyi["day"].min()}〜{kyi["day"].max()} ({kyi["day"].nunique()}日)')

    print('jravan読み込み...')
    df, tr = load_jravan()
    df = add_gap(df)

    # train基準(2021-24 JRA平地, 有効走)
    trn = df[df['valid'] & df['year_i'].between(*TRAIN) & df['ninki'].between(1, 18)]
    base = trn.assign(t3=trn['chakujun'] <= 3).groupby('ninki')['t3'].mean()
    print(f'  train {TRAIN[0]}-{TRAIN[1]}: {len(trn):,}行')

    # 2025評価行 + KYI結合 (day, 場コード, R, 馬番)
    ev = df[df['year_i'] == 2025].copy()
    ev['jyo_i'] = ev['jyo'].astype(int)
    ev['day'] = ev['day'].astype(int)
    ev['umaban'] = ev['umaban'].astype(int)
    kyi['jyo_i'] = kyi['場コード'].astype(int)
    kyi['R'] = kyi['Ｒ'].astype(int)
    kyi['day'] = kyi['day'].astype(int)
    kyi['馬番'] = kyi['馬番'].astype(int)
    ev['R'] = ev['race_num'].astype(int)
    kcols = ['day', 'jyo_i', 'R', '馬番', '入厩何走目', '入厩年月日', '入厩何日前',
             '放牧先', '放牧先ランク']
    ev = ev.merge(kyi[kcols], left_on=['day', 'jyo_i', 'R', 'umaban'],
                  right_on=['day', 'jyo_i', 'R', '馬番'], how='left')
    hit = ev['放牧先'].notna() & (ev['放牧先'].astype(str).str.strip() != '')
    print(f'  2025出走行 {len(ev):,} → KYI結合 {hit.sum():,} ({hit.mean()*100:.1f}%)')

    ev['is_nf'] = ev['放牧先'].astype(str).str.contains(NF_PAT)
    ev['entry_dt'] = pd.to_datetime(ev['入厩年月日'], format='%Y%m%d', errors='coerce')
    ev['days_since_entry'] = (ev['dt'] - ev['entry_dt']).dt.days
    # 入厩何日前(公式値)との整合チェック
    chk = ev[['days_since_entry', '入厩何日前']].dropna()
    agree = (chk['days_since_entry'] == chk['入厩何日前']).mean()
    print(f'  入厩何日前 vs (レース日-入厩年月日): 一致率 {agree*100:.1f}% (n={len(chk):,})')

    ev['h1'] = (ev['day'] % 10000) <= 630  # 上半期/下半期
    res = {}

    print('\n===== skip_nf_layoff: NF外厩・中9週以上・1番人気 =====')
    lay = ev['gap_days'] >= 63
    fav = ev['ninki'] == 1
    tests = {
        'NF外厩&中9週&1番人気': lay & ev['is_nf'] & fav,
        '非NF外厩&中9週&1番人気(対照)': lay & ~ev['is_nf'] & fav,
        'NF外厩&中9週&人気1-3': lay & ev['is_nf'] & ev['ninki'].between(1, 3),
        'NF外厩&中9週&全人気': lay & ev['is_nf'],
        '中9週&1番人気(全体)': lay & fav,
    }
    for name, m in tests.items():
        r = resid_stats(ev[m], base)
        res['nf:' + name] = r
        print(f'  {name:24s} n={r.get("n",0):>6,} 勝率{r.get("win","-")}% '
              f'複勝{r.get("top3","-")}% (基準{r.get("exp","-")}%) '
              f'残差{r.get("resid","-")}pp z={r.get("z","-")}')
    # 符号安定性(上下半期)
    for name, m in {'NF&fav1': tests['NF外厩&中9週&1番人気'],
                    '非NF&fav1': tests['非NF外厩&中9週&1番人気(対照)']}.items():
        for half, lab in [(True, '1H'), (False, '2H')]:
            r = resid_stats(ev[m & (ev['h1'] == half)], base)
            res[f'nf:{name}:{lab}'] = r
            print(f'    {name} {lab}: n={r.get("n",0):>5,} 残差{r.get("resid","-")}pp')

    print('\n===== skip_kikyo: 帰厩日(入厩からの日数) =====')
    fresh = ev['入厩何走目'] == 1
    dse = ev['days_since_entry']
    print('  [入厩何走目==1(前走後に帰厩した馬)の日数別 複勝残差]')
    buckets = [(1, 6), (7, 10), (11, 13), (14, 17), (18, 21), (22, 28), (29, 45), (46, 400)]
    for lo, hi in buckets:
        m = fresh & dse.between(lo, hi)
        r = resid_stats(ev[m], base)
        res[f'kikyo:帰厩{lo}-{hi}日'] = r
        print(f'    {lo:>3}-{hi:<3}日 n={r.get("n",0):>6,} 残差{r.get("resid","-")}pp z={r.get("z","-")}')

    m_kikyo = fresh & dse.between(11, 13)
    r = resid_stats(ev[m_kikyo], base)
    res['kikyo:11-13日(入厩何走目1)'] = r
    print(f'  → 11-13日帰厩: n={r.get("n",0):,} 残差{r.get("resid","-")}pp z={r.get("z","-")}')

    # ラスト1F条件: jravan training (2025-06以降) の直近追い lap_20 がレース内上位半分
    print('\n  [ラスト1F条件を追加 (trainingは2025-06〜のみ → 下半期限定)]')
    trv = tr[tr['lap_20'] > 0].copy()
    trv['lap1f'] = trv['lap_20'] / 10.0
    trv = trv.sort_values(['ketto_num', 'cho_date'])
    trv['cho_dt'] = pd.to_datetime(trv['cho_date'], format='%Y%m%d', errors='coerce')
    ev2 = ev[m_kikyo & ~ev['h1']].copy()
    mrg = pd.merge_asof(ev2.sort_values('dt'),
                        trv[['ketto_num', 'cho_dt', 'lap1f']].sort_values('cho_dt'),
                        left_on='dt', right_on='cho_dt', by='ketto_num',
                        direction='backward', tolerance=pd.Timedelta('7D'))
    have = mrg['lap1f'].notna()
    print(f'    11-13日帰厩・下半期 {len(ev2):,}行のうち直近7日内の追切あり: {have.sum():,}')
    if have.sum() >= 50:
        med = mrg.groupby('race_key')['lap1f'].transform('median')
        mrg['lap_fast'] = mrg['lap1f'] <= med
        for lab, mm in [('ラスト1F上位半分', mrg['lap_fast']),
                        ('ラスト1F下位半分', ~mrg['lap_fast'])]:
            r = resid_stats(mrg[have & mm], base)
            res[f'kikyo:11-13日+{lab}'] = r
            print(f'    {lab}: n={r.get("n",0):,} 残差{r.get("resid","-")}pp z={r.get("z","-")}')

    print('\n===== 参考: 放牧先ランク × 中9週(全人気) =====')
    for rk in ['A', 'B', 'C', 'D', 'E']:
        m = lay & (ev['放牧先ランク'] == rk)
        r = resid_stats(ev[m], base)
        res[f'rank{rk}:中9週'] = r
        print(f'    ランク{rk}: n={r.get("n",0):>6,} 残差{r.get("resid","-")}pp z={r.get("z","-")}')

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {OUT_JSON}')


if __name__ == '__main__':
    main()
