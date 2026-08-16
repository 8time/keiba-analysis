# -*- coding: utf-8 -*-
"""33ラップ『符号一致』vs『距離±0.5秒ルール』の比較 — 該当馬が多すぎる問題の検証

ユーザーの懸念: 現行の33ラップ適合は該当馬が多すぎて使い方が合っているか不安。

原因(コード確認済): core/lap33.fit_match() は **符号が一致するかだけ** を見ている
(threshold=0.0)。コース平均は1コース1つの符号に固定されるので、瞬発力型コースなら
瞬発力型の馬が全員該当する。構造上おおよそ半数が引っかかる。

新資料(PDF新聞の『±0.5秒ルール』)が提案するのは **距離ベース** の判定:
  |馬の好走時33ラップ − 今回の想定33ラップ| <= 0.5 なら○ / <= 1.0 なら△
これなら該当馬を絞れる。エッジが保たれる(または上がる)なら現行を置き換える価値がある。

検証: [[verified_lap33_theory]] のT1(人気薄6+×適合→複勝残差+0.9pp)と同じ土俵で
  ①符号一致(現行) ②距離<=1.0 ③距離<=0.5 ④距離<=0.3 を比較する。
  ベース=人気別複勝率をtrainで凍結。リーク無し(コース平均は2010-2020で凍結、
  馬の33ラップは各レース時点より前の履歴のみ)。

使い方: python scripts/lap33_distance_backtest.py
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

from core import lap33 as l3

DB = l3.JV_DB_PATH
TRAIN_Y = (2021, 2024)
HOLD_Y = (2025, 2026)
BASE_Y = (2010, 2020)     # コース平均の凍結期間


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)

    # ── コース平均33ラップ(2010-2020で凍結) ──
    print('コース平均33ラップを構築(2010-2020で凍結)...')
    cavg = defaultdict(list)
    for surf, kyori, jyo, mae3f, rato3f, wtime in con.execute(
            f"""SELECT ra.surface, ra.kyori, ra.jyo, ra.mae3f, ra.ato3f, rw.time
                FROM races ra JOIN results rw ON rw.race_key=ra.race_key AND rw.chakujun=1
                WHERE ra.jyo<='10' AND ra.surface IN ('芝','ダート')
                  AND ra.mae3f>0 AND ra.ato3f>0
                  AND CAST(ra.year AS INT) BETWEEN {BASE_Y[0]} AND {BASE_Y[1]}"""):
        v = l3.race_lap33(kyori, mae3f, rato3f, wtime)
        if v is not None:
            cavg[(str(surf), int(kyori), str(jyo))].append(v)
    COURSE = {k: sum(v) / len(v) for k, v in cavg.items() if len(v) >= 30}
    print(f'  {len(COURSE):,}コース\n')

    # ── 全出走の33ラップ(馬個別) ──
    print('馬ごとの33ラップ履歴を構築...')
    rows = con.execute(
        """SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.ato3f,
                  ra.surface, ra.kyori, ra.jyo, ra.mae3f, ra.ato3f, rw.time,
                  CAST(ra.year AS INT)
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           JOIN results rw ON rw.race_key=ra.race_key AND rw.chakujun=1
           WHERE ra.jyo<='10' AND ra.surface IN ('芝','ダート') AND r.chakujun>0
             AND r.ninki>0 AND r.ato3f>0 AND ra.mae3f>0 AND ra.ato3f>0
             AND CAST(ra.year AS INT)>=2010""").fetchall()
    con.close()
    print(f'  {len(rows):,}行')

    hist = defaultdict(list)      # ketto -> [(race_key, chakujun, lap33)]
    recs = []
    for rk, kt, ch, nk, h_ato, surf, kyori, jyo, mae3f, rato3f, wtime, yr in rows:
        mid = l3.race_mid3f_rate(kyori, mae3f, rato3f, wtime)
        v = l3.lap33(mid, h_ato / 10.0 if h_ato else None)
        if v is None or not kt:
            continue
        hist[str(kt)].append((str(rk), int(ch), v))
        recs.append(dict(rk=str(rk), kt=str(kt), ch=int(ch), nk=int(nk), y=yr,
                         key=(str(surf), int(kyori), str(jyo))))
    for l in hist.values():
        l.sort(key=lambda z: z[0])
    print(f'  馬 {len(hist):,}頭 / 評価対象 {len(recs):,}走\n')

    # ── 各走時点での『過去の33ラップ』(全走平均 と 好走時平均) ──
    def prior_stats(kt, rk, n=10, min_runs=3):
        past = [(c, v) for (r, c, v) in hist[kt] if r < rk][-n:]
        if len(past) < min_runs:
            return None, None
        allv = [v for _, v in past]
        pl = [v for c, v in past if c <= 3]
        return (sum(allv) / len(allv),
                (sum(pl) / len(pl)) if pl else None)

    # ── 人気別ベース(train凍結) ──
    bt = defaultdict(lambda: [0, 0])
    for r in recs:
        if TRAIN_Y[0] <= r['y'] <= TRAIN_Y[1]:
            bt[r['nk']][0] += 1 if r['ch'] <= 3 else 0
            bt[r['nk']][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 50}

    # ── 判定方式ごとに残差を集計 ──
    METHODS = [
        ('①符号一致(現行)', 'sign', None),
        ('②距離<=1.0秒', 'dist', 1.0),
        ('③距離<=0.5秒★資料', 'dist', 0.5),
        ('④距離<=0.3秒', 'dist', 0.3),
    ]

    def evaluate(band_lo, band_hi, y0, y1, use_placed):
        """(方式 -> (n, 残差, z, 該当率))"""
        out = {m[0]: [0.0, 0, 0] for m in METHODS}   # sum_res, n_hit, n_eligible
        for r in recs:
            if not (y0 <= r['y'] <= y1) or not (band_lo <= r['nk'] <= band_hi):
                continue
            cv = COURSE.get(r['key'])
            if cv is None or r['nk'] not in TB:
                continue
            av, pv = prior_stats(r['kt'], r['rk'])
            base = pv if use_placed else av
            if base is None:
                continue
            res = (1 if r['ch'] <= 3 else 0) - TB[r['nk']]
            for lbl, kind, th in METHODS:
                out[lbl][2] += 1
                if kind == 'sign':
                    hit = (base > 0) == (cv > 0)
                else:
                    hit = abs(base - cv) <= th
                if hit:
                    out[lbl][0] += res
                    out[lbl][1] += 1
        return out

    for use_placed, plbl in ((False, '全走平均(現行の avg_lap33)'),
                             (True, '好走時平均(資料の考え方)')):
        print('=' * 86)
        print(f'■ 馬の33ラップの取り方: {plbl}')
        print('=' * 86)
        for band, bjp in (((6, 18), '人気薄(6番人気以下)'), ((1, 3), '人気上位(1-3番人気)')):
            print(f'\n  --- {bjp} ---')
            print(f"  {'判定方式':<22}{'期間':<10}{'該当n':>8}{'該当率':>8}"
                  f"{'複勝残差':>10}{'z':>8}")
            for ylbl, (y0, y1) in (('train', TRAIN_Y), ('holdout', HOLD_Y)):
                ev = evaluate(band[0], band[1], y0, y1, use_placed)
                for lbl, _, _ in METHODS:
                    s, nh, ne = ev[lbl]
                    if nh < 200:
                        print(f'  {lbl:<22}{ylbl:<10}{nh:>8,}  標本不足')
                        continue
                    m = s / nh
                    print(f'  {lbl:<22}{ylbl:<10}{nh:>8,}{nh/ne*100:>7.1f}%'
                          f'{m:>+10.4f}{zof(m, nh):>+8.2f}')
            print()

    # ── bootstrap: 最有力2方式(人気薄・holdout・好走時平均) ──
    print('=' * 86)
    print('■ bootstrap 95%CI（人気薄・holdout・好走時平均）')
    print('=' * 86)
    random.seed(42)
    for lbl, kind, th in METHODS:
        rs = []
        for r in recs:
            if not (HOLD_Y[0] <= r['y'] <= HOLD_Y[1]) or not (6 <= r['nk'] <= 18):
                continue
            cv = COURSE.get(r['key'])
            if cv is None or r['nk'] not in TB:
                continue
            _, pv = prior_stats(r['kt'], r['rk'])
            if pv is None:
                continue
            hit = ((pv > 0) == (cv > 0)) if kind == 'sign' else (abs(pv - cv) <= th)
            if hit:
                rs.append((1 if r['ch'] <= 3 else 0) - TB[r['nk']])
        n = len(rs)
        if n < 200:
            print(f'  {lbl:<22} 標本不足({n})')
            continue
        bs = []
        for _ in range(1500):
            bs.append(sum(rs[random.randrange(n)] for _ in range(n)) / n)
        bs.sort()
        pt = sum(rs) / n
        lo, hi = bs[37], bs[1462]
        print(f'  {lbl:<22} n={n:>7,}  {pt*100:+.2f}pp  '
              f'95%CI[{lo*100:+.2f}, {hi*100:+.2f}]  '
              f'{"CIが0を跨ぐ" if lo < 0 < hi else "★0を跨がない"}')

    print()
    print('判定: 該当率が下がり、かつ残差が現行(①)以上・train/holdout両方でz>=2なら置換の価値あり。')
    print('  該当率だけ下がって残差も落ちるなら「絞れているが精度は上がっていない」＝据え置き。')


if __name__ == '__main__':
    main()
