# -*- coding: utf-8 -*-
"""CHA(調教本追切)で既存U俗説をholdout検証。新規条件の発掘はしない。

対象:
  skip_wood 「美浦ウッド11.3秒以下／栗東坂路52.7-12.2は上位争い」
      → 02(美浦ウッド系)&終いＦ<=11.3 / 11(栗東坂路)&推定4F<=52.7&終いＦ<=12.2
      ※CHAの時計は区間が2F以上だと平均ペース。4F合計はjravan trainingのt4fで
        2つの合成式(テン2F説/中間2F説)を較正してから全年に適用
  tr_ippai 「追い切りは一杯だから良く、馬なりだから悪い」
      → 追切種類(1:一杯/2:強目/3:馬なり)別の複勝残差

設計: train=2021-2024基準率 / holdout=2025(JRA平地)。上半期/下半期で符号確認。
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
OUT_JSON = os.path.join(ROOT, 'data', 'cha_wood_ippai_summary.json')
Z_SE_P = 15.4
TRAIN = (2021, 2024)

CODE_WOOD_MIHO = '02'   # 美浦ウッド系 (6F本流・終い12.0)
CODE_SAKA_RITTO = '11'  # 栗東坂路 (4F・t4f照合済)

CHA_COLS = ['場コード', 'Ｒ', '馬番', '調教年月日', '調教コースコード', '追切種類',
            '調教Ｆ', 'テンＦ', '中間Ｆ', '終いＦ']


def load_cha():
    layout, reclen, _ = jrdb_read.build_layout('CHA')
    lay = [f for f in layout if f[0] in CHA_COLS]
    frames = []
    path = os.path.join(ROOT, 'data', 'jrdb', 'raw', 'CHA_2025.zip')
    with zipfile.ZipFile(path) as z:
        for n in sorted(x for x in z.namelist() if x.upper().endswith('.TXT')):
            frames.append(jrdb_read.parse_buf(z.read(n), lay, reclen,
                                              jrdb_read._day_from_name(n)))
    df = pd.concat(frames, ignore_index=True)
    for c in ('テンＦ', '中間Ｆ', '終いＦ', '調教Ｆ', '追切種類'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['day'] = df['day'].astype(int)
    df['jyo_i'] = df['場コード'].astype(int)
    df['R'] = df['Ｒ'].astype(int)
    df['umaban'] = df['馬番'].astype(int)
    return df


def load_jravan():
    con = sqlite3.connect(DB)
    df = pd.read_sql(
        "SELECT r.race_key, r.year, r.monthday, r.jyo, r.race_num,"
        " t.ketto_num, t.umaban, t.chakujun, t.ninki, t.ijo"
        " FROM races r JOIN results t ON r.race_key = t.race_key"
        " WHERE r.jyo IN ('01','02','03','04','05','06','07','08','09','10')"
        "   AND r.surface IN ('芝','ダート')", con)
    tr = pd.read_sql("SELECT ketto_num, cho_date, t4f FROM training", con)
    con.close()
    tr['cho_date'] = pd.to_numeric(tr['cho_date'], errors='coerce')
    df['day'] = (df['year'].astype(int) * 10000
                 + pd.to_numeric(df['monthday'], errors='coerce')).astype(int)
    df['chakujun'] = pd.to_numeric(df['chakujun'], errors='coerce')
    df['ninki'] = pd.to_numeric(df['ninki'], errors='coerce')
    df['valid'] = (df['ijo'].astype(str) == '0') & df['chakujun'].between(1, 30)
    df['year_i'] = df['year'].astype(int)
    return df, tr


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


def show(name, r, res, key=None):
    print(f'  {name:38s} n={r.get("n",0):>6,} 複勝{r.get("top3","-")}% '
          f'(基準{r.get("exp","-")}%) 残差{r.get("resid","-")}pp z={r.get("z","-")}')
    res[key or name] = r
    return r


def main():
    print('CHA/jravan読み込み...')
    cha = load_cha()
    df, tr = load_jravan()
    trn = df[df['valid'] & df['year_i'].between(*TRAIN) & df['ninki'].between(1, 18)]
    base = trn.assign(t3=trn['chakujun'] <= 3).groupby('ninki')['t3'].mean()

    ev = df[df['year_i'] == 2025].copy()
    ev['jyo_i'] = ev['jyo'].astype(int)
    ev['R'] = ev['race_num'].astype(int)
    ev = ev.merge(cha[['day', 'jyo_i', 'R', 'umaban', '調教年月日', '調教コースコード',
                       '追切種類', '調教Ｆ', 'テンＦ', '中間Ｆ', '終いＦ']],
                  on=['day', 'jyo_i', 'R', 'umaban'], how='left')
    hit = ev['調教コースコード'].astype(str).str.strip() != ''
    print(f'  2025出走行 {len(ev):,} → CHA結合 {hit.sum():,} ({hit.mean()*100:.1f}%)')
    ev['h1'] = (ev['day'] % 10000) <= 630
    res = {}

    # ---- 4F合計の較正 (栗東坂路コード11 × jravan t4f) ----
    print('\n== 4F合成式の較正 (コード11, jravan t4f結合行) ==')
    saka = ev[(ev['調教コースコード'] == CODE_SAKA_RITTO) & (ev['調教Ｆ'] == 4)].copy()
    saka = saka.merge(tr, left_on=['ketto_num', '調教年月日'],
                      right_on=['ketto_num', 'cho_date'], how='left')
    cal = saka[saka['t4f'].notna() & (saka['t4f'] > 0)]
    f1 = cal['テンＦ'] * 2 + cal['中間Ｆ'] + cal['終いＦ']  # テン=最初の2F
    f2 = cal['テンＦ'] + cal['中間Ｆ'] * 2 + cal['終いＦ']  # 中間=2F
    mae1 = (f1 - cal['t4f']).abs().median()
    mae2 = (f2 - cal['t4f']).abs().median()
    print(f'  n={len(cal):,}  式A(テンx2+中間+終い) 中央誤差={mae1:.1f}  '
          f'式B(テン+中間x2+終い) 中央誤差={mae2:.1f}')
    use_a = mae1 <= mae2
    print(f'  → 式{"A" if use_a else "B"}を採用')
    if use_a:
        ev['est4f'] = ev['テンＦ'] * 2 + ev['中間Ｆ'] + ev['終いＦ']
    else:
        ev['est4f'] = ev['テンＦ'] + ev['中間Ｆ'] * 2 + ev['終いＦ']

    # ---- skip_wood ----
    print('\n===== skip_wood =====')
    m_a = (ev['調教コースコード'] == CODE_WOOD_MIHO) & (ev['終いＦ'] <= 113)
    show('美浦ウッド系(02) 終い1F<=11.3', resid_stats(ev[m_a], base), res, 'wood:美浦W11.3以下')
    show('  うち上半期', resid_stats(ev[m_a & ev['h1']], base), res, 'wood:美浦W11.3以下:1H')
    show('  うち下半期', resid_stats(ev[m_a & ~ev['h1']], base), res, 'wood:美浦W11.3以下:2H')

    m_b = ((ev['調教コースコード'] == CODE_SAKA_RITTO) & (ev['調教Ｆ'] == 4)
           & (ev['est4f'] <= 527) & (ev['終いＦ'] <= 122))
    show('栗東坂路(11) 推定4F<=52.7 & 終い<=12.2', resid_stats(ev[m_b], base), res,
         'wood:栗坂52.7-12.2')
    show('  うち上半期', resid_stats(ev[m_b & ev['h1']], base), res, 'wood:栗坂:1H')
    show('  うち下半期', resid_stats(ev[m_b & ~ev['h1']], base), res, 'wood:栗坂:2H')
    # 参考: 正確なt4fでの再現（6月以降サブセット）
    saka_ev = ev[(ev['調教コースコード'] == CODE_SAKA_RITTO) & (ev['調教Ｆ'] == 4)].copy()
    saka_ev = saka_ev.merge(tr, left_on=['ketto_num', '調教年月日'],
                            right_on=['ketto_num', 'cho_date'], how='left')
    exact = ((saka_ev['t4f'] > 0) & (saka_ev['t4f'] <= 527) & (saka_ev['終いＦ'] <= 122))
    show('参考: 正確なt4f<=52.7 & 終い<=12.2 (6-12月のみ)',
         resid_stats(saka_ev[exact], base), res, 'wood:栗坂:正確t4f')

    # ---- tr_ippai ----
    print('\n===== tr_ippai: 追切種類(一杯/強目/馬なり) =====')
    for code, lab in [(1, '一杯'), (2, '強目'), (3, '馬なり')]:
        m = ev['追切種類'] == code
        show(f'追切種類={lab}', resid_stats(ev[m], base), res, f'ippai:{lab}')
    for code, lab in [(1, '一杯'), (3, '馬なり')]:
        m = ev['追切種類'] == code
        show(f'  {lab} 上半期', resid_stats(ev[m & ev['h1']], base), res, f'ippai:{lab}:1H')
        show(f'  {lab} 下半期', resid_stats(ev[m & ~ev['h1']], base), res, f'ippai:{lab}:2H')

    with open(OUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(f'\n保存: {OUT_JSON}')


if __name__ == '__main__':
    main()
