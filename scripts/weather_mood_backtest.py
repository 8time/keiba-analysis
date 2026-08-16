# -*- coding: utf-8 -*-
"""②天候×大衆心理の歪みは日本競馬にあるか — 英国EC/SADモデルの日本版検証

仮説(英国 2002-2016年87,402レース):
  天候そのものが馬に効くのではなく、**天候がベッターの気分に影響してオッズを歪める**。
  英国では雨の日-18.65%ROI/冬のSAD期間-9.78%ROI vs 低風速日+20.21%ROIと報告。

⚠ このアプリでは既に [[verified_wind_no_effect]] で『風は着順に効かない(477k頭・残差≈0)』
  と否定済み。ただしあれは **物理チャネル(天候→馬の走り→着順)** の検証。
  本検証は別チャネル＝**心理チャネル(天候→買う人の気分→オッズの歪み)** を見る。
  残差の当て先が「着順」ではなく「オッズ(人気)からの乖離」である点が違う。

設計(リーク無し):
  ベース = 人気 × 馬場状態 を train(〜2023)で凍結。
    馬場状態を入れるのは、天候の**物理的な影響を差し引く**ため。
    実データで天候と馬場は一対一でない(晴でも稍重13%/雨でも良13%)ので分離可能。
  → 残った天候別の残差 = 物理では説明できない分 = 心理チャネルの候補。
  月(季節)はSAD(季節性感情障害)の代理指標として別途見る。

データ監査済(scripts実行前に確認):
  tenko 取得率99.73%(欠損93件は除外) / コード体系は2016-2026で安定
  1=晴 2=曇 3=雨 4=小雨 5=雪 6=小雪 / 馬場は surface に応じ baba_shiba|baba_dirt

使い方: python scripts/weather_mood_backtest.py
"""
import os
import sys
import math
import random
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN_END = 2023
TENKO = {'1': '晴', '2': '曇', '3': '雨', '4': '小雨', '5': '雪', '6': '小雪'}
BABA = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}
ORDER = ['晴', '曇', '小雨', '雨', '雪', '小雪']


def zof(m, n, sd):
    return m / (sd / math.sqrt(n)) if n else 0.0


def main():
    print('DB読込(天候・馬場)...')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rmeta = {}
    for rk, tk, bs, bd, sf, jyo, md, ky in con.execute(
            """SELECT race_key, tenko, baba_shiba, baba_dirt, surface, jyo, monthday, kyori
               FROM races WHERE jyo BETWEEN '01' AND '10' AND shubetsu NOT IN ('18','19')
                 AND surface IN ('芝','ダート')"""):
        t = TENKO.get(str(tk))
        b = BABA.get(str(bs if str(sf) == '芝' else bd))
        if not t or not b:          # 欠損(93件)は除外
            continue
        rmeta[str(rk)] = (t, b, str(sf), str(jyo), int(str(md)[:2]), int(ky or 0))
    fuku = {}
    for rk, cb, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'"):
        c = str(cb).strip()
        if c.isdigit():
            fuku[(str(rk), int(c))] = float(pay)
    con.close()
    print(f'  レースmeta {len(rmeta):,}件 / 複勝配当 {len(fuku):,}件')

    df = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win', 'top3', 'win_odds'])
    df = df[df['ninki'].notna()]
    S = []
    for r in df.itertuples(index=False):
        rk = str(int(r.race_key))
        m = rmeta.get(rk)
        if not m:
            continue
        S.append(dict(y=int(rk[:4]), nk=int(r.ninki), tenko=m[0], baba=m[1],
                      surf=m[2], jyo=m[3], mo=m[4], ky=m[5],
                      w=int(r.win), t3=int(r.top3),
                      od=(float(r.win_odds) if r.win_odds == r.win_odds else None),
                      pay=fuku.get((rk, int(r.umaban)), 0.0)))
    print(f'  結合サンプル {len(S):,}頭\n')

    # ベース: 人気×馬場状態(train凍結) ＝ 天候の物理チャネルを差し引く
    bw = defaultdict(lambda: [0, 0]); bt = defaultdict(lambda: [0, 0])
    for s in S:
        if s['y'] > TRAIN_END:
            continue
        k = (s['nk'], s['baba'])
        bw[k][0] += s['w']; bw[k][1] += 1
        bt[k][0] += s['t3']; bt[k][1] += 1
    WB = {k: v[0] / v[1] for k, v in bw.items() if v[1] >= 30}
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 30}
    print(f'  ベース凍結: 人気×馬場状態 / train〜{TRAIN_END} ({len(WB)}セル)\n')

    def rs_of(keep):
        out = []
        for s in S:
            if not keep(s):
                continue
            k = (s['nk'], s['baba'])
            if k not in TB:
                continue
            out.append((s['w'] - WB[k], s['t3'] - TB[k], s['pay'], s['t3'],
                        s['od'], s['w']))
        return out

    def stat(rs):
        n = len(rs)
        if n < 200:
            return None
        mw = sum(x[0] for x in rs) / n
        mt = sum(x[1] for x in rs) / n
        froi = sum(x[2] for x in rs) / (n * 100) * 100
        od = [x for x in rs if x[4]]
        wroi = (sum((x[4] * 100 if x[5] else 0) for x in od) / (len(od) * 100) * 100
                if od else 0)
        return (n, mw, zof(mw, n, 0.28), mt, zof(mt, n, 0.42), wroi, froi)

    def table(title, groups, keep):
        print(f'  === {title} ===')
        print(f"  {'区分':<10}{'n':>9}{'勝利残差':>10}{'z':>7}{'複勝残差':>10}{'z':>7}"
              f"{'単ROI':>7}{'複ROI':>7}")
        for lbl, g in groups:
            r = stat(rs_of(lambda s, gg=g: keep(s) and gg(s)))
            if r is None:
                print(f'  {lbl:<10}{"標本不足":>9}')
                continue
            print(f'  {lbl:<10}{r[0]:>9,}{r[1]:>+10.4f}{r[2]:>+7.2f}'
                  f'{r[3]:>+10.4f}{r[4]:>+7.2f}{r[5]:>6.1f}%{r[6]:>6.1f}%')
        print()

    TG = [(t, (lambda s, tt=t: s['tenko'] == tt)) for t in ORDER]

    print('=' * 84)
    print('■ 1. 単純な全体効果（天候別・全人気帯）')
    print('=' * 84)
    table('全期間', TG, lambda s: True)

    print('=' * 84)
    print('■ 2. 人気帯別')
    print('=' * 84)
    for bl, bf in (('1-3人気', lambda s: s['nk'] <= 3),
                   ('4-6人気', lambda s: 4 <= s['nk'] <= 6),
                   ('7人気以下', lambda s: s['nk'] >= 7)):
        table(f'全期間 / {bl}', TG, bf)

    print('=' * 84)
    print('■ 3. train / holdout')
    print('=' * 84)
    for pl, pf in ((f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024', lambda s: s['y'] == 2024),
                   ('2025+', lambda s: s['y'] >= 2025)):
        table(f'{pl} / 全人気', TG, pf)
    for pl, pf in ((f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024+', lambda s: s['y'] >= 2024)):
        table(f'{pl} / 1-3人気', TG, lambda s, p=pf: p(s) and s['nk'] <= 3)

    print('=' * 84)
    print('■ 4. 月別（SAD＝季節性の代理指標・1-3人気）')
    print('=' * 84)
    table('全期間 / 1-3人気',
          [(f'{m}月', (lambda s, mm=m: s['mo'] == mm)) for m in range(1, 13)],
          lambda s: s['nk'] <= 3)
    table('holdout2024+ / 1-3人気',
          [(f'{m}月', (lambda s, mm=m: s['mo'] == mm)) for m in range(1, 13)],
          lambda s: s['nk'] <= 3 and s['y'] >= 2024)

    print('=' * 84)
    print('■ 5. 年別（雨系 vs 晴・1-3人気の複勝残差）')
    print('=' * 84)
    print(f"  {'年':>6}{'晴 n':>9}{'晴 残差':>10}{'z':>7}{'雨系 n':>9}{'雨系 残差':>10}{'z':>7}")
    for y in range(2016, 2027):
        a = stat(rs_of(lambda s, yy=y: s['y'] == yy and s['nk'] <= 3 and s['tenko'] == '晴'))
        b = stat(rs_of(lambda s, yy=y: s['y'] == yy and s['nk'] <= 3
                       and s['tenko'] in ('雨', '小雨')))
        if a and b:
            print(f'  {y:>6}{a[0]:>9,}{a[3]:>+10.4f}{a[4]:>+7.2f}'
                  f'{b[0]:>9,}{b[3]:>+10.4f}{b[4]:>+7.2f}')
        elif a:
            print(f'  {y:>6}{a[0]:>9,}{a[3]:>+10.4f}{a[4]:>+7.2f}{"(雨系不足)":>26}')
    print()

    print('=' * 84)
    print('■ 6. 頑健性（雨系×1-3人気 を場/芝ダ/距離で分割）')
    print('=' * 84)
    RAIN = lambda s: s['tenko'] in ('雨', '小雨') and s['nk'] <= 3
    JN = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
    table('場別', [(JN[j], (lambda s, jj=j: s['jyo'] == jj)) for j in sorted(JN)], RAIN)
    table('芝ダ別', [('芝', lambda s: s['surf'] == '芝'),
                  ('ダート', lambda s: s['surf'] == 'ダート')], RAIN)
    table('距離別', [('〜1400', lambda s: s['ky'] <= 1400),
                  ('1401-1800', lambda s: 1400 < s['ky'] <= 1800),
                  ('1801〜', lambda s: s['ky'] > 1800)], RAIN)

    print('=' * 84)
    print('■ 7. bootstrap 95%CI（主要セル・複勝残差）')
    print('=' * 84)
    random.seed(42)
    CELLS = [
        ('雨系×1-3人気(全期間)', lambda s: s['tenko'] in ('雨', '小雨') and s['nk'] <= 3),
        ('雨系×1-3人気(2024+)', lambda s: s['tenko'] in ('雨', '小雨') and s['nk'] <= 3
         and s['y'] >= 2024),
        ('晴×1-3人気(全期間)', lambda s: s['tenko'] == '晴' and s['nk'] <= 3),
        ('曇×1-3人気(全期間)', lambda s: s['tenko'] == '曇' and s['nk'] <= 3),
    ]
    for lbl, kp in CELLS:
        rs = rs_of(kp)
        n = len(rs)
        if n < 200:
            print(f'  {lbl:<24} 標本不足({n})')
            continue
        bs = []
        for _ in range(2000):
            bs.append(sum(rs[random.randrange(n)][1] for _ in range(n)) / n)
        bs.sort()
        pt = sum(x[1] for x in rs) / n
        lo, hi = bs[50], bs[1949]
        cross = (lo < 0 < hi)
        print(f'  {lbl:<24} n={n:>7,}  {pt*100:+.2f}pp  '
              f'95%CI[{lo*100:+.2f}, {hi*100:+.2f}]  '
              f'{"CIが0を跨ぐ=有意でない" if cross else "★CIが0を跨がない"}')

    print()
    print('判定基準: train と holdout(2024+) の両方で同符号かつ |z|>=2、')
    print('  さらに場/芝ダ/年で符号が一貫し bootstrap CI が0を跨がない場合のみ採用。')
    print('  一部の条件だけ強い場合は後付け抽出(selection bias)を疑い棄却する。')


if __name__ == '__main__':
    main()
