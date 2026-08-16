# -*- coding: utf-8 -*-
"""④クラス別 Rank vs 人気 — 英国『上級クラスほどAIが効く』の日本版検証

⚠ この検証の主眼(ここを外すと無意味):
  測るのは「Rankが当たるか」ではなく
  **「市場の人気順位を超える情報をRankが持っているか」がクラスで変わるか**。
  生の的中率で比べると「上級クラスほど強い馬が揃っている」だけの話になるため、
  必ず『人気を統制した残差』で見る。

主指標(3つとも同じ問いを別角度から):
  A. 人気統制後のRank残差 … ベース=クラス×人気別top3率(train凍結)。
     同じクラス・同じ人気の中でRank上位が上振れするなら、Rankは市場超えの情報を持つ。
  B. 乖離ケースの勝敗 … RankとNinkiが食い違う馬で、どちらの言い分が当たるか。
  C. 順位相関 … Spearman(Rank,着順) と Spearman(人気,着順) の差。

クラスの復元(jravan.dbに条件カラムが無いため):
  JRAのクラスは累積勝利数で決まる。results履歴から各馬の『そのレース時点の
  勝利数/出走数』(リーク無し)を作り、出走馬の中央値でクラスを判定。
  重賞/Lはgrade列(A/B/C/D/L)が正本。
  → netkeibaのRaceData02実表記と照合し **14/14(100%)** で一致を確認済み。
  復元分布: 新馬7.9% 未勝利36.8% 1勝30.3% 2勝8.8% 3勝6.0% OP/L6.6% 重賞3.6%
  (実際のJRA番組構成と整合)

使い方: python scripts/class_rank_vs_ninki.py
"""
import os
import sys
import math
import random
import sqlite3
import statistics as st
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
CLASSES = ['新馬', '未勝利', '1勝', '2勝', '3勝', 'OP/L', '重賞']


def build_class_map():
    """race_key -> クラス。リーク無し(そのレース時点までの成績のみ使用)。"""
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
    rows = con.execute(
        """SELECT r.race_key, r.ketto_num, r.chakujun, ra.year, ra.monthday, ra.grade
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19')""").fetchall()
    con.close()
    by_horse = defaultdict(list)
    grade = {}
    for rk, kt, ch, y, md, g in rows:
        if not kt:
            continue
        by_horse[kt].append((int(str(y) + str(md).zfill(4)), str(rk), int(ch or 0)))
        grade[str(rk)] = str(g or '')
    prior = {}
    for kt, lst in by_horse.items():
        lst.sort(key=lambda z: (z[0], z[1]))
        w = s = 0
        for _, rk, ch in lst:
            prior[(rk, kt)] = (w, s)
            s += 1
            if ch == 1:
                w += 1
    agg = defaultdict(list)
    for rk, kt, ch, y, md, g in rows:
        p = prior.get((str(rk), kt))
        if p is not None:
            agg[str(rk)].append(p)
    out = {}
    for rk, lst in agg.items():
        g = grade.get(rk, '')
        if g in ('A', 'B', 'C', 'D'):
            out[rk] = '重賞'; continue
        if g == 'L':
            out[rk] = 'OP/L'; continue
        if st.median([s for _, s in lst]) == 0:
            out[rk] = '新馬'; continue
        mw = st.median([w for w, _ in lst])
        out[rk] = ('未勝利' if mw == 0 else '1勝' if mw == 1 else
                   '2勝' if mw == 2 else '3勝' if mw == 3 else 'OP/L')
    return out


def zof(m, n, sd):
    return m / (sd / math.sqrt(n)) if n else 0.0


def spearman(xs, ys):
    n = len(xs)
    if n < 30:
        return None
    def rk(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            a = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                r[order[k]] = a
            i = j + 1
        return r
    rx, ry = rk(xs), rk(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    dx = sum((rx[i] - mx) ** 2 for i in range(n)) ** 0.5
    dy = sum((ry[i] - my) ** 2 for i in range(n)) ** 0.5
    return num / (dx * dy) if dx and dy else None


def main():
    print('クラス復元中...')
    cls_map = build_class_map()
    print(f'  {len(cls_map):,}レース\n')

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    fuku = {}
    for rk, cb, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'"):
        c = str(cb).strip()
        if c.isdigit():
            fuku[(str(rk), int(c))] = float(pay)
    con.close()

    df = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win_odds',
                              'chakujun', 'top3', 'win', 'ability_score'])
    df = df[df['ninki'].notna() & df['ability_score'].notna()]

    # レース単位に人気順位/Rank順位を振り直す(欠損を詰めた実効順位)
    races = defaultdict(list)
    for r in df.itertuples(index=False):
        rk = str(int(r.race_key))
        races[rk].append(r)

    S = []
    for rk, lst in races.items():
        cl = cls_map.get(rk)
        if not cl or len(lst) < 5:
            continue
        yr = int(rk[:4])
        by_nk = sorted(lst, key=lambda r: r.ninki)
        by_ab = sorted(lst, key=lambda r: r.ability_score)   # 小さいほど強い
        npos = {int(r.umaban): i + 1 for i, r in enumerate(by_nk)}
        rpos = {int(r.umaban): i + 1 for i, r in enumerate(by_ab)}
        for r in lst:
            um = int(r.umaban)
            S.append(dict(y=yr, cls=cl, n=len(lst), um=um,
                          npos=npos[um], rpos=rpos[um],
                          nk=int(r.ninki), ch=int(r.chakujun),
                          t3=int(r.top3), w=int(r.win),
                          od=(float(r.win_odds) if r.win_odds == r.win_odds else None),
                          pay=fuku.get((rk, um), 0.0)))
    print(f'サンプル {len(S):,}頭 / {len(races):,}レース\n')

    print('=' * 88)
    print('■ 0. クラス別サンプル数（train/holdout）')
    print('=' * 88)
    print(f"  {'クラス':<8}{'train〜2023':>13}{'holdout2024+':>14}{'計':>11}")
    for c in CLASSES:
        a = sum(1 for s in S if s['cls'] == c and s['y'] <= TRAIN_END)
        b = sum(1 for s in S if s['cls'] == c and s['y'] > TRAIN_END)
        print(f'  {c:<8}{a:>13,}{b:>14,}{a+b:>11,}')

    # ── ベース: クラス×人気 の top3率(train凍結) ──
    bt = defaultdict(lambda: [0, 0])
    bw = defaultdict(lambda: [0, 0])
    for s in S:
        if s['y'] > TRAIN_END:
            continue
        k = (s['cls'], s['npos'])
        bt[k][0] += s['t3']; bt[k][1] += 1
        bw[k][0] += s['w']; bw[k][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 50}
    WB = {k: v[0] / v[1] for k, v in bw.items() if v[1] >= 50}

    def resid(keep):
        rs = []
        for s in S:
            if not keep(s):
                continue
            k = (s['cls'], s['npos'])
            if k not in TB:
                continue
            rs.append((s['t3'] - TB[k], s['w'] - WB[k], s['pay'], s['t3'],
                       s['od'], s['w']))
        return rs

    def stat(rs, minn=150):
        n = len(rs)
        if n < minn:
            return None
        mt = sum(x[0] for x in rs) / n
        mw = sum(x[1] for x in rs) / n
        froi = sum(x[2] for x in rs) / (n * 100) * 100
        od = [x for x in rs if x[4]]
        wroi = (sum((x[4] * 100 if x[5] else 0) for x in od) / (len(od) * 100) * 100) if od else 0
        return (n, mt, zof(mt, n, 0.42), mw, zof(mw, n, 0.28), froi, wroi)

    print()
    print('=' * 88)
    print('■ 1.【主指標A】人気を統制した後の Rank上位3頭 の残差')
    print('=' * 88)
    print('  同じクラス・同じ人気順位の馬と比べて、Rank上位だと上振れするか。')
    print('  >0 かつ z>=2 なら「Rankは人気を超える情報を持つ」。')
    for pl, pf in ((f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024+', lambda s: s['y'] > TRAIN_END)):
        print(f'\n  === {pl} ===')
        print(f"  {'クラス':<8}{'n':>8}{'複勝残差':>10}{'z':>7}{'勝利残差':>10}{'z':>7}"
              f"{'単ROI':>8}{'複ROI':>8}")
        for c in CLASSES:
            r = stat(resid(lambda s, cc=c, p=pf: p(s) and s['cls'] == cc and s['rpos'] <= 3))
            if r is None:
                print(f'  {c:<8}{"標本不足":>8}')
                continue
            print(f'  {c:<8}{r[0]:>8,}{r[1]:>+10.4f}{r[2]:>+7.2f}'
                  f'{r[3]:>+10.4f}{r[4]:>+7.2f}{r[6]:>7.1f}%{r[5]:>7.1f}%')

    print()
    print('=' * 88)
    print('■ 2.【主指標B】RankとNinkiが食い違う馬 — どちらの言い分が当たるか')
    print('=' * 88)
    print('  Rank昇格 = Rank順位が人気順位より3つ以上上位（市場より高評価）')
    print('  Rank降格 = その逆（市場より低評価）。残差>0ならRankの主張が正しい。')
    for pl, pf in ((f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024+', lambda s: s['y'] > TRAIN_END)):
        print(f'\n  === {pl} ===')
        print(f"  {'クラス':<8}{'昇格n':>8}{'昇格残差':>10}{'z':>7}"
              f"{'降格n':>8}{'降格残差':>10}{'z':>7}{'差':>9}")
        for c in CLASSES:
            up = stat(resid(lambda s, cc=c, p=pf: p(s) and s['cls'] == cc
                            and s['npos'] - s['rpos'] >= 3))
            dn = stat(resid(lambda s, cc=c, p=pf: p(s) and s['cls'] == cc
                            and s['rpos'] - s['npos'] >= 3))
            if not up or not dn:
                print(f'  {c:<8}{"標本不足":>8}')
                continue
            print(f'  {c:<8}{up[0]:>8,}{up[1]:>+10.4f}{up[2]:>+7.2f}'
                  f'{dn[0]:>8,}{dn[1]:>+10.4f}{dn[2]:>+7.2f}{up[1]-dn[1]:>+9.4f}')

    print()
    print('=' * 88)
    print('■ 3.【主指標C】順位相関 Spearman(順位, 着順) — 小さいほど識別力が高い')
    print('=' * 88)
    print(f"  {'クラス':<8}{'期間':<14}{'n':>9}{'Rank-着順':>11}{'人気-着順':>11}"
          f"{'差(Rank-人気)':>14}")
    for c in CLASSES:
        for pl, pf in ((f'train', lambda s: s['y'] <= TRAIN_END),
                       ('holdout', lambda s: s['y'] > TRAIN_END)):
            sub = [s for s in S if s['cls'] == c and pf(s)]
            if len(sub) < 500:
                continue
            rr = spearman([s['rpos'] for s in sub], [s['ch'] for s in sub])
            rn = spearman([s['npos'] for s in sub], [s['ch'] for s in sub])
            if rr is None or rn is None:
                continue
            print(f'  {c:<8}{pl:<14}{len(sub):>9,}{rr:>11.4f}{rn:>11.4f}'
                  f'{rr-rn:>+14.4f}')
    print('  ※差が負ならRankのほうが着順をよく説明している(=識別力が高い)')

    print()
    print('=' * 88)
    print('■ 4. bootstrap 95%CI（主指標A・holdout・Rank上位3頭の複勝残差）')
    print('=' * 88)
    random.seed(42)
    for c in CLASSES:
        rs = resid(lambda s, cc=c: s['y'] > TRAIN_END and s['cls'] == cc and s['rpos'] <= 3)
        n = len(rs)
        if n < 150:
            print(f'  {c:<8} 標本不足({n})')
            continue
        bs = []
        for _ in range(2000):
            bs.append(sum(rs[random.randrange(n)][0] for _ in range(n)) / n)
        bs.sort()
        pt = sum(x[0] for x in rs) / n
        lo, hi = bs[50], bs[1949]
        print(f'  {c:<8} n={n:>7,}  {pt*100:+.2f}pp  95%CI[{lo*100:+.2f}, {hi*100:+.2f}]'
              f'  {"CIが0を跨ぐ" if lo < 0 < hi else "★0を跨がない"}')

    print()
    print('判定: train と holdout の両方で 残差>0 かつ z>=2、bootstrapのCIが0を跨がない')
    print('  クラスのみ「そのクラスではRankが市場を超える情報を持つ」と言える。')
    print('  一部クラスだけ強い場合は、事後に切り出したselection biasを疑うこと。')


if __name__ == '__main__':
    main()
