# -*- coding: utf-8 -*-
"""『兄姉の新馬戦実績』は使えるか — デビュー戦の予想ファクター検証

主張(PDF新聞の資料):
  情報の少ない若駒戦では、種牡馬(父)以上に **兄姉の新馬戦実績** を重視すべき。
  兄弟が1着・2着でデビューしているなら、その馬は『Ready-to-Fire(準備万端)』。

⚠ 既存台帳との関係:
  血統本体は [[verified_blood_course]](血統×コースは織込み済み)・
  [[verified_training_and_sire_popbucket]](人気薄×父は全区分|z|<1.7)で否定済み。
  ただし『兄姉の**デビュー戦**成績』は切り口が違うので別途測る。
  なお [[verified_class_rank_gradient]] で新馬はRankが効く(+2.87pp z+3.08)と判明しており
  「新馬戦は市場が読み切れていない」領域である傍証はある。

設計(リーク無し):
  対象 = 各馬の初出走(デビュー戦)。
  シグナル = 同じ母から生まれ、**対象レースより前に**デビュー済みの兄姉のうち
             デビュー戦で1着または2着だった馬がいる。
  比較群 = ①兄姉のデビューが3着以下のみ ②兄姉が特定できない
  評価 = 人気別top3率をtrainで凍結した残差(市場が織込み済みなら残差≈0)。

使い方: python scripts/sibling_debut_backtest.py
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
TRAIN_END = 2017   # 血統データ(horses.dam)が2020年代でほぼ欠損のため分割を前倒し(実測: 2024年デビュー馬の母名取得率8.5%)


def zof(m, n, sd=0.42):
    return m / (sd / math.sqrt(n)) if n else 0.0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)

    print('=' * 84)
    print('■ データ監査')
    print('=' * 84)
    # 母(dam)の取得率
    r = con.execute("SELECT COUNT(*), SUM(CASE WHEN dam IS NULL OR TRIM(dam)='' "
                    "THEN 1 ELSE 0 END) FROM horses").fetchone()
    print(f'  horses {r[0]:,}頭 / 母名の欠損 {r[1]:,} '
          f'→ 取得率 {(r[0]-r[1])/r[0]*100:.1f}%')

    dam_of = {}
    for kt, dam in con.execute(
            "SELECT ketto_num, dam FROM horses WHERE dam IS NOT NULL AND TRIM(dam)<>''"):
        dam_of[str(kt)] = str(dam).strip()
    print(f'  母名を持つ馬 {len(dam_of):,}頭')

    rows = con.execute(
        """SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, ra.year, ra.monthday
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0""").fetchall()
    con.close()
    print(f'  出走レコード {len(rows):,}件')

    # 馬ごと時系列 → デビュー戦を特定
    by_horse = defaultdict(list)
    for rk, kt, ch, nk, y, md in rows:
        if not kt:
            continue
        by_horse[str(kt)].append((int(str(y) + str(md).zfill(4)), str(rk),
                                  int(ch), (int(nk) if nk else None), int(y)))
    debut = {}
    for kt, lst in by_horse.items():
        lst.sort()
        d = lst[0]
        debut[kt] = dict(day=d[0], rk=d[1], ch=d[2], nk=d[3], y=d[4])
    print(f'  デビュー戦を特定できた馬 {len(debut):,}頭')

    # 母 → 産駒(デビュー日順)
    by_dam = defaultdict(list)
    for kt, d in debut.items():
        dm = dam_of.get(kt)
        if dm:
            by_dam[dm].append((d['day'], kt))
    for l in by_dam.values():
        l.sort()
    n_multi = sum(1 for l in by_dam.values() if len(l) >= 2)
    print(f'  産駒を2頭以上持つ母 {n_multi:,}頭')

    # 各馬について「自分より前にデビュー済みの兄姉」を集める
    samples = []
    n_with_sib = 0
    for dm, lst in by_dam.items():
        for i, (day, kt) in enumerate(lst):
            d = debut[kt]
            if d['nk'] is None:
                continue
            elders = [k for (dd, k) in lst[:i] if dd < day]     # リーク遮断
            if elders:
                n_with_sib += 1
            best = None
            for e in elders:
                ec = debut[e]['ch']
                best = ec if best is None else min(best, ec)
            samples.append(dict(y=d['y'], nk=d['nk'], ch=d['ch'],
                                n_sib=len(elders), best_sib=best))
    print(f'  デビュー戦サンプル {len(samples):,}頭 '
          f'/ うち先にデビューした兄姉あり {n_with_sib:,} '
          f'({n_with_sib/len(samples)*100:.1f}%)')

    # ── ベース: 人気別top3率(train凍結) ──
    bt = defaultdict(lambda: [0, 0])
    for s in samples:
        if s['y'] <= TRAIN_END:
            bt[s['nk']][0] += 1 if s['ch'] <= 3 else 0
            bt[s['nk']][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 50}

    GROUPS = [
        ('兄姉なし(初仔等)', lambda s: s['n_sib'] == 0),
        ('兄姉あり・デビュー3着以下', lambda s: s['n_sib'] > 0 and s['best_sib'] is not None
         and s['best_sib'] >= 3),
        ('兄姉あり・デビュー2着', lambda s: s['best_sib'] == 2),
        ('★兄姉あり・デビュー1着', lambda s: s['best_sib'] == 1),
        ('★兄姉あり・デビュー1-2着', lambda s: s['best_sib'] is not None and s['best_sib'] <= 2),
    ]

    def stat(keep):
        rs = []
        hit = 0
        for s in samples:
            if not keep(s) or s['nk'] not in TB:
                continue
            t3 = 1 if s['ch'] <= 3 else 0
            rs.append(t3 - TB[s['nk']])
            hit += t3
        n = len(rs)
        if n < 200:
            return None
        m = sum(rs) / n
        return (n, m, zof(m, n), hit / n * 100)

    print()
    print('=' * 84)
    print('■ 1. 兄姉のデビュー成績別 — 対象馬のデビュー戦(人気統制後の残差)')
    print('=' * 84)
    for pl, pf in (('全期間', lambda s: True),
                   (f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2018-2023', lambda s: TRAIN_END < s['y'] <= 2023)):
        print(f'\n  === {pl} ===')
        print(f"  {'区分':<26}{'n':>8}{'複勝率':>8}{'複勝残差':>10}{'z':>8}")
        for lbl, gf in GROUPS:
            r = stat(lambda s, g=gf, p=pf: p(s) and g(s))
            if r is None:
                print(f'  {lbl:<26}{"標本不足":>8}')
                continue
            print(f'  {lbl:<26}{r[0]:>8,}{r[3]:>7.1f}%{r[1]:>+10.4f}{r[2]:>+8.2f}')

    print()
    print('=' * 84)
    print('■ 2. bootstrap 95%CI（★兄姉デビュー1-2着・holdout 2018-2023）')
    print('=' * 84)
    rs = []
    for s in samples:
        if TRAIN_END < s['y'] <= 2023 and s['best_sib'] is not None and s['best_sib'] <= 2 \
                and s['nk'] in TB:
            rs.append((1 if s['ch'] <= 3 else 0) - TB[s['nk']])
    n = len(rs)
    if n >= 200:
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
    print('判定: 残差>0かつz>=2がtrain/holdout両方で一貫し、bootstrapのCIが0を跨がない')
    print('  場合のみ採用。z≈0なら「兄姉が走れば市場も期待する」＝priced-in。')


if __name__ == '__main__':
    main()
