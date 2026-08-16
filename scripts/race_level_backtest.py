# -*- coding: utf-8 -*-
"""『前走のレースレベル』は使えるか — PDF新聞『ハイレベル戦』の検証

主張(資料):
  「ハイレベル戦(オレンジ表記)で1.5秒差以内に走っていた馬の次走は
    単回収率93% / 複回収率92%。逆に低レベル戦上がりは単回収率62%まで落ちる」

⚠ 主張の数字自体が100%未満＝資料どおりでも儲からない。
  ただし93% vs 62%の**差**は大きいので、軸の信頼度としては意味があるかもしれない。
  よって「儲かるか」ではなく「人気を超える情報か」を残差で測る。

『ハイレベル戦』の再現可能な定義(資料は新聞独自の判定なので、こちらで作る):
  前走P(日付Dp)の出走馬のうち、**Dpより後・今走Dより前に**勝ち上がった馬の割合。
  → 「あのレースに居た馬が、その後どんどん勝っている」＝結果的にレベルが高かった。
  ⚠ リーク厳守: 使うのは今走Dより前の情報のみ。D以降の結果は一切見ない。

設計: ベース=人気×年 のtop3率(期間効果を打ち消す。[[verified_dam_age_rejected]]の教訓)。
  自分自身は分母から除外(自分が勝ち上がった事実で自分を評価しない)。

使い方: python scripts/race_level_backtest.py
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

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN_END = 2023


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def parse_time(s):
    s = str(s).strip()
    if not s.isdigit() or int(s) == 0:
        return None
    return int(s[:-3] or 0) * 60 + int(s[-3:-1] or 0) + int(s[-1]) / 10.0


def main():
    print('DB読込...')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
    rows = con.execute(
        """SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.time, r.win_odds,
                  ra.year, ra.monthday
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0
             AND CAST(ra.year AS INT)>=2015""").fetchall()
    con.close()
    print(f'  {len(rows):,}行')

    # レース単位: 出走馬リストと勝ちタイム
    race_members = defaultdict(list)
    race_day = {}
    win_time = {}
    for rk, kt, ch, nk, tm, od, y, md in rows:
        if not kt:
            continue
        day = int(str(y) + str(md).zfill(4))
        race_day[str(rk)] = day
        race_members[str(rk)].append(str(kt))
        if int(ch) == 1:
            t = parse_time(tm)
            if t:
                win_time[str(rk)] = t

    # 馬ごと時系列
    by_horse = defaultdict(list)
    for rk, kt, ch, nk, tm, od, y, md in rows:
        if not kt:
            continue
        by_horse[str(kt)].append(dict(
            day=int(str(y) + str(md).zfill(4)), rk=str(rk), ch=int(ch),
            nk=(int(nk) if nk else None), t=parse_time(tm),
            od=(float(od) if od and od > 0 else None), y=int(y)))
    for l in by_horse.values():
        l.sort(key=lambda z: (z['day'], z['rk']))

    # 各馬の「勝った日」リスト(レベル算定用)
    win_days = defaultdict(list)
    for kt, l in by_horse.items():
        for r in l:
            if r['ch'] == 1:
                win_days[kt].append(r['day'])

    print('レースレベルを算定中(リーク遮断)...')
    S = []
    for kt, l in by_horse.items():
        for i in range(1, len(l)):
            cur, prev = l[i], l[i - 1]
            if cur['nk'] is None:
                continue
            mem = race_members.get(prev['rk']) or []
            if len(mem) < 6:
                continue
            # 前走の同走馬のうち、前走の後〜今走の前 に勝ち上がった割合(自分は除く)
            n_o = n_up = 0
            for o in mem:
                if o == kt:
                    continue
                n_o += 1
                if any(prev['day'] < d < cur['day'] for d in win_days.get(o, ())):
                    n_up += 1
            if n_o < 5:
                continue
            level = n_up / n_o
            # 前走の着差(勝ち馬との秒差)
            wt = win_time.get(prev['rk'])
            margin = (prev['t'] - wt) if (wt and prev['t']) else None
            S.append(dict(y=cur['y'], nk=cur['nk'], ch=cur['ch'], od=cur['od'],
                          level=level, margin=margin, prev_ch=prev['ch']))
    print(f'  評価対象 {len(S):,}走\n')

    # ベース: 人気×年
    bt = defaultdict(lambda: [0, 0])
    for s in S:
        k = (s['y'], s['nk'])
        bt[k][0] += 1 if s['ch'] <= 3 else 0
        bt[k][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 30}

    def stat(keep):
        rs = []
        wret = 0.0
        wn = hit = 0
        for s in S:
            k = (s['y'], s['nk'])
            if k not in TB or not keep(s):
                continue
            t3 = 1 if s['ch'] <= 3 else 0
            rs.append(t3 - TB[k])
            hit += t3
            if s['od']:
                wn += 1
                if s['ch'] == 1:
                    wret += s['od'] * 100
        n = len(rs)
        if n < 300:
            return None
        m = sum(rs) / n
        return (n, m, zof(m, n), hit / n * 100, (wret / (wn * 100) * 100) if wn else 0)

    # レベルの分布から4分位を決める
    lv = sorted(s['level'] for s in S)
    q1, q2, q3 = lv[len(lv)//4], lv[len(lv)//2], lv[len(lv)*3//4]
    print('=' * 76)
    print(f'■ 0. レースレベルの分布  四分位: {q1:.2f} / {q2:.2f} / {q3:.2f}')
    print('=' * 76)
    BANDS = [('低(下位25%)', lambda s: s['level'] <= q1),
             ('中低', lambda s: q1 < s['level'] <= q2),
             ('中高', lambda s: q2 < s['level'] <= q3),
             ('★高(上位25%)', lambda s: s['level'] > q3)]

    print()
    print('=' * 76)
    print('■ 1. 前走レースレベル別 — 人気統制後の残差')
    print('=' * 76)
    for pl, pf in (('全期間', lambda s: True),
                   (f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024+', lambda s: s['y'] > TRAIN_END)):
        print(f'\n  === {pl} ===')
        print(f"  {'区分':<16}{'n':>9}{'複勝率':>8}{'複勝残差':>10}{'z':>8}{'単勝ROI':>9}")
        for lbl, bf in BANDS:
            r = stat(lambda s, b=bf, p=pf: p(s) and b(s))
            if r is None:
                print(f'  {lbl:<16}{"標本不足":>9}')
                continue
            print(f'  {lbl:<16}{r[0]:>9,}{r[3]:>7.1f}%{r[1]:>+10.4f}{r[2]:>+8.2f}{r[4]:>8.1f}%')

    print()
    print('=' * 76)
    print('■ 2.【主張の再現】ハイレベル戦×1.5秒差以内 vs 低レベル戦')
    print('=' * 76)
    CLAIM = [
        ('★高レベル×1.5秒差以内', lambda s: s['level'] > q3 and s['margin'] is not None
         and s['margin'] <= 1.5),
        ('高レベル×1.5秒超', lambda s: s['level'] > q3 and s['margin'] is not None
         and s['margin'] > 1.5),
        ('低レベル×1.5秒差以内', lambda s: s['level'] <= q1 and s['margin'] is not None
         and s['margin'] <= 1.5),
        ('低レベル×1.5秒超', lambda s: s['level'] <= q1 and s['margin'] is not None
         and s['margin'] > 1.5),
    ]
    for pl, pf in (('全期間', lambda s: True),
                   ('holdout 2024+', lambda s: s['y'] > TRAIN_END)):
        print(f'\n  === {pl} ===')
        print(f"  {'区分':<22}{'n':>9}{'複勝率':>8}{'複勝残差':>10}{'z':>8}{'単勝ROI':>9}")
        for lbl, cf in CLAIM:
            r = stat(lambda s, c=cf, p=pf: p(s) and c(s))
            if r is None:
                print(f'  {lbl:<22}{"標本不足":>9}')
                continue
            print(f'  {lbl:<22}{r[0]:>9,}{r[3]:>7.1f}%{r[1]:>+10.4f}{r[2]:>+8.2f}{r[4]:>8.1f}%')

    print()
    print('=' * 76)
    print('■ 3. bootstrap 95%CI（高レベル×1.5秒差以内・全期間）')
    print('=' * 76)
    rs = []
    for s in S:
        k = (s['y'], s['nk'])
        if k in TB and s['level'] > q3 and s['margin'] is not None and s['margin'] <= 1.5:
            rs.append((1 if s['ch'] <= 3 else 0) - TB[k])
    n = len(rs)
    if n >= 300:
        random.seed(42)
        bs = []
        for _ in range(2000):
            bs.append(sum(rs[random.randrange(n)] for _ in range(n)) / n)
        bs.sort()
        pt = sum(rs) / n
        lo, hi = bs[50], bs[1949]
        print(f'  n={n:,}  {pt*100:+.2f}pp  95%CI[{lo*100:+.2f}, {hi*100:+.2f}]  '
              f'{"CIが0を跨ぐ=有意でない" if lo < 0 < hi else "★0を跨がない"}')
    else:
        print(f'  標本不足({n})')

    print()
    print('判定: 残差>0かつz>=2がtrain/holdout両方で一貫し、CIが0を跨がない場合のみ採用。')
    print('  対照群(低レベル)が0近辺にあることも必ず確認する。')


if __name__ == '__main__':
    main()
