# -*- coding: utf-8 -*-
"""CYB(調教分析)で既存U俗説の検証可能性を確認し、該当するものだけholdout検証。

対象(カタログ既存U項目のみ。新規条件の発掘はしない):
  skip_oikiri_score 「調教採点50点未満は馬券に絡まない」
      → CYBに100点満点の採点は無い。調教評価(◎○△)の△を「低評価」代理として検証
  skip_kikyo        「11〜13日前帰厩+ラスト1F速い」
      → KYI帰厩日 × CYB追切指数(レース内上位=速い代理)で全年検証
        (jravan training版は2025-06〜のみ n=417 で標本不足だった)

設計: train=2021-2024基準率 / holdout=2025(JRA平地)。複勝残差+z。CHＡは使わない。
"""
import os
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
OUT_JSON = os.path.join(ROOT, 'data', 'cyb_training_eval_summary.json')
Z_SE_P = 15.4
TRAIN = (2021, 2024)

CYB_COLS = ['場コード', 'Ｒ', '馬番', '調教評価', '追切指数', '一週前追切指数',
            '仕上指数', '調教量評価', '調教重点', '調教コース種別']
KYI_COLS = ['場コード', 'Ｒ', '馬番', '入厩何走目', '入厩年月日']


def load_zip_fast(prefix, cols):
    layout, reclen, _ = jrdb_read.build_layout(prefix)
    lay = [f for f in layout if f[0] in cols]
    frames = []
    path = os.path.join(ROOT, 'data', 'jrdb', 'raw', f'{prefix}_2025.zip')
    with zipfile.ZipFile(path) as z:
        for n in sorted(x for x in z.namelist() if x.upper().endswith('.TXT')):
            frames.append(jrdb_read.parse_buf(z.read(n), lay, reclen,
                                              jrdb_read._day_from_name(n)))
    df = pd.concat(frames, ignore_index=True)
    df['day'] = df['day'].astype(int)
    df['jyo_i'] = df['場コード'].astype(int)
    df['R'] = df['Ｒ'].astype(int)
    df['馬番'] = df['馬番'].astype(int)
    return df


def load_jravan():
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT r.race_key, r.year, r.monthday, r.jyo, r.race_num,"
        " t.ketto_num, t.umaban, t.chakujun, t.ninki, t.ijo"
        " FROM races r JOIN results t ON r.race_key = t.race_key"
        " WHERE r.jyo IN ('01','02','03','04','05','06','07','08','09','10')"
        "   AND r.surface IN ('芝','ダート')", con)
    con.close()
    df['day'] = (df['year'].astype(int) * 10000
                 + pd.to_numeric(df['monthday'], errors='coerce')).astype(int)
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)
    df['year_i'] = df['year'].astype(int)
    return df


def resid_stats(sub, base):
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


def show(name, r):
    print(f'  {name:34s} n={r.get("n",0):>6,} 複勝{r.get("top3","-")}% '
          f'(基準{r.get("exp","-")}%) 残差{r.get("resid","-")}pp z={r.get("z","-")}')
    return r


def main():
    print('CYB読み込み...')
    cyb = load_zip_fast('CYB', CYB_COLS)
    print(f'  {len(cyb):,}行')

    print('\n== CYBフィールド充足・分布 ==')
    for c in CYB_COLS[3:]:
        s = cyb[c]
        if s.dtype == object:
            fill = (s.astype(str).str.strip() != '').mean()
        else:
            fill = s.notna().mean()
        vc = s.value_counts().head(6).to_dict()
        print(f'  {c:12s} 充足{fill*100:6.1f}%  分布={vc}')

    print('\njravan読み込み...')
    df = load_jravan()
    trn = df[df['valid'] & df['year_i'].between(*TRAIN) & df['ninki'].between(1, 18)]
    base = trn.assign(t3=trn['chakujun'] <= 3).groupby('ninki')['t3'].mean()

    ev = df[df['year_i'] == 2025].copy()
    ev['jyo_i'] = ev['jyo'].astype(int)
    ev['R'] = ev['race_num'].astype(int)
    ev = ev.rename(columns={'umaban': '馬番'})
    ev = ev.merge(cyb[['day', 'jyo_i', 'R', '馬番', '調教評価', '追切指数',
                       '一週前追切指数', '仕上指数', '調教量評価']],
                  on=['day', 'jyo_i', 'R', '馬番'], how='left')
    hit = ev['調教評価'].astype(str).str.strip().isin(['1', '2', '3'])
    print(f'  2025出走行 {len(ev):,} → CYB調教評価あり {hit.sum():,} ({hit.mean()*100:.1f}%)')

    ev['h1'] = (ev['day'] % 10000) <= 630
    res = {}

    print('\n===== skip_oikiri_score: 調教評価(◎○△) × 複勝残差 =====')
    for code, lab in [('1', '◎'), ('2', '○'), ('3', '△(低評価=50点未満の代理)')]:
        m = ev['調教評価'].astype(str).str.strip() == code
        r = show(f'調教評価{lab}', resid_stats(ev[m], base))
        res[f'oikiri:評価{lab}'] = r
    # 下半期の符号確認用
    m = ev['調教評価'].astype(str).str.strip() == '3'
    for half, lab in [(True, '1H'), (False, '2H')]:
        r = show(f'  △ {lab}', resid_stats(ev[m & (ev['h1'] == half)], base))
        res[f'oikiri:△:{lab}'] = r
    # 人気薄に限定(「馬券に絡まない」は穴側の文脈でも読まれるので両方)
    r = show('△ & 4番人気以下', resid_stats(ev[m & (ev['ninki'] >= 4)], base))
    res['oikiri:△:4人気以下'] = r
    r = show('△ & 3番人気以内', resid_stats(ev[m & (ev['ninki'] <= 3)], base))
    res['oikiri:△:3人気以内'] = r

    print('\n===== skip_kikyo: KYI 11-13日帰厭 × CYB追切指数 =====')
    kyi = load_zip_fast('KYI', KYI_COLS)
    ev = ev.merge(kyi[['day', 'jyo_i', 'R', '馬番', '入厩何走目', '入厩年月日']],
                  on=['day', 'jyo_i', 'R', '馬番'], how='left')
    ev['entry_dt'] = pd.to_datetime(ev['入厩年月日'], format='%Y%m%d', errors='coerce')
    ev['dt'] = pd.to_datetime(ev['day'], format='%Y%m%d', errors='coerce')
    ev['days_since_entry'] = (ev['dt'] - ev['entry_dt']).dt.days
    ev['追切指数'] = pd.to_numeric(ev['追切指数'], errors='coerce')
    # レース内で追切指数の中央値以上を「速い」(上位半分)
    med = ev.groupby('race_key')['追切指数'].transform('median')
    ev['oik_fast'] = ev['追切指数'].notna() & (ev['追切指数'] >= med)

    kikyo = (ev['入厩何走目'] == 1) & ev['days_since_entry'].between(11, 13)
    r = show('11-13日帰厭 全体', resid_stats(ev[kikyo], base))
    res['kikyo:11-13日'] = r
    r = show('11-13日 & 追切指数上位半分', resid_stats(ev[kikyo & ev['oik_fast']], base))
    res['kikyo:11-13日+追切上位'] = r
    r = show('11-13日 & 追切指数下位半分',
             resid_stats(ev[kikyo & ev['追切指数'].notna() & ~ev['oik_fast']], base))
    res['kikyo:11-13日+追切下位'] = r
    for half, lab in [(True, '1H'), (False, '2H')]:
        r = show(f'  11-13日+追切上位 {lab}',
                 resid_stats(ev[kikyo & ev['oik_fast'] & (ev['h1'] == half)], base))
        res[f'kikyo:11-13日+追切上位:{lab}'] = r

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {OUT_JSON}')


if __name__ == '__main__':
    main()
