# -*- coding: utf-8 -*-
"""『母の出産年齢が16歳を超えると回収率が下がる』は本当か

主張(PDF新聞の資料・若駒戦のリスク管理):
  母の出産年齢が16歳を超えている高齢出産馬は、統計的に回収率が低下する傾向にある。

データ: JRDB UKC(scripts/jrdb_ukc_ingest.py で取り込んだ horses_jrdb)。
  母馬生年 は jravan.db の horses には無く、UKCにしか無い項目。
  出産年齢 = その馬の生年 − 母馬生年。

⚠ 既存台帳との関係: 単発の血統ファクターは軒並み否定されている
  ([[verified_blood_course]] 血統×コースは織込み済み /
   [[verified_training_and_sire_popbucket]] 人気薄×父は全区分|z|<1.7 /
   [[verified_sibling_debut_rejected]] 兄姉のデビュー実績もpriced-in)。
  期待値は低いが、母馬生年という**市場が見ていない可能性のある項目**なので測る。

設計(リーク無し): 出産年齢は生まれた時点で確定＝レース前情報。
  評価は人気別top3率をtrainで凍結した残差(市場が織込み済みなら残差≈0)。
  デビュー戦だけでなく全出走を対象にする(主張が「回収率」なので単勝ROIも併記)。

使い方: python scripts/dam_age_backtest.py
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


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
    try:
        n_j = con.execute('SELECT COUNT(*) FROM horses_jrdb').fetchone()[0]
    except sqlite3.OperationalError:
        print('❌ horses_jrdb がありません。先に scripts/jrdb_ukc_ingest.py を実行してください。')
        return 1
    print(f'horses_jrdb: {n_j:,}頭')

    # 出産年齢 = 産駒の生年 − 母馬生年
    dam_age = {}
    for kt, dbirth in con.execute(
            "SELECT ketto_num, dam_birth FROM horses_jrdb "
            "WHERE dam_birth IS NOT NULL AND LENGTH(dam_birth)=4"):
        try:
            foal_y = int(str(kt)[:4])       # 血統登録番号の先頭4桁が生年
            dy = int(dbirth)
            age = foal_y - dy
            if 2 <= age <= 30:              # 異常値を除外
                dam_age[str(kt)] = age
        except (TypeError, ValueError):
            continue
    print(f'出産年齢を計算できた馬: {len(dam_age):,}頭')

    rows = con.execute(
        """SELECT r.ketto_num, r.chakujun, r.ninki, r.win_odds, ra.year
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0 AND r.ninki>0""").fetchall()
    con.close()

    S = []
    for kt, ch, nk, od, y in rows:
        a = dam_age.get(str(kt))
        if a is None:
            continue
        S.append(dict(y=int(y), nk=int(nk), ch=int(ch), age=a,
                      od=(float(od) if od and od > 0 else None)))
    print(f'照合できた出走 {len(S):,}件\n')
    if len(S) < 2000:
        print('❌ 標本が少なすぎます。')
        return 1

    print('=' * 74)
    print('■ 0. 出産年齢の分布')
    print('=' * 74)
    cnt = defaultdict(int)
    for s in S:
        cnt[s['age']] += 1
    tot = len(S)
    for a in sorted(cnt):
        if cnt[a] >= 200:
            bar = '#' * int(cnt[a] / tot * 200)
            print(f'  {a:>2}歳: {cnt[a]:>7,} ({cnt[a]/tot*100:4.1f}%) {bar}')
    n16 = sum(v for a, v in cnt.items() if a >= 16)
    print(f'\n  16歳以上での出産: {n16:,}件 ({n16/tot*100:.1f}%)')

    # ベース: 人気×年 のtop3率。
    # ⚠ train凍結だと成立しない。UKCは『最近走っている馬』のマスタなので、
    #   この標本の train(≤2023) 部分は「2024年以降も走り続けた馬」に偏る(生存バイアス)。
    #   実際 train凍結でやると 〜10歳 まで含む**全帯**が holdout で -2.3〜-3.2pp と
    #   一律にマイナスへ振れ、年齢の効果ではなく標本構成のズレを測ってしまう。
    #   → 同じ年・同じ人気の馬と比べる形にして期間効果を打ち消す。
    bt = defaultdict(lambda: [0, 0])
    for s in S:
        k = (s['y'], s['nk'])
        bt[k][0] += 1 if s['ch'] <= 3 else 0
        bt[k][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 30}

    def stat(keep):
        rs = []
        wret = 0.0
        wn = 0
        hit = 0
        for s in S:
            _k = (s['y'], s['nk'])
            if not keep(s) or _k not in TB:
                continue
            t3 = 1 if s['ch'] <= 3 else 0
            rs.append(t3 - TB[_k])
            hit += t3
            if s['od']:
                wn += 1
                if s['ch'] == 1:
                    wret += s['od'] * 100
        n = len(rs)
        if n < 300:
            return None
        m = sum(rs) / n
        return (n, m, zof(m, n), hit / n * 100,
                (wret / (wn * 100) * 100) if wn else 0)

    BANDS = [('〜10歳', lambda a: a <= 10), ('11-13歳', lambda a: 11 <= a <= 13),
             ('14-15歳', lambda a: 14 <= a <= 15),
             ('★16-17歳', lambda a: 16 <= a <= 17),
             ('★18歳〜', lambda a: a >= 18),
             ('★16歳以上(主張)', lambda a: a >= 16)]

    print()
    print('=' * 74)
    print('■ 1. 出産年齢別 — 人気統制後の残差と単勝ROI')
    print('=' * 74)
    for pl, pf in (('全期間', lambda s: True),
                   (f'train〜{TRAIN_END}', lambda s: s['y'] <= TRAIN_END),
                   ('holdout 2024+', lambda s: s['y'] > TRAIN_END)):
        print(f'\n  === {pl} ===')
        print(f"  {'区分':<18}{'n':>9}{'複勝率':>8}{'複勝残差':>10}{'z':>8}{'単勝ROI':>9}")
        for lbl, af in BANDS:
            r = stat(lambda s, a=af, p=pf: p(s) and a(s['age']))
            if r is None:
                print(f'  {lbl:<18}{"標本不足":>9}')
                continue
            print(f'  {lbl:<18}{r[0]:>9,}{r[3]:>7.1f}%{r[1]:>+10.4f}{r[2]:>+8.2f}{r[4]:>8.1f}%')

    print()
    print('=' * 74)
    print('■ 2. bootstrap 95%CI（★16歳以上・全期間）')
    print('=' * 74)
    rs = []
    for s in S:
        if s['age'] >= 16 and (s['y'], s['nk']) in TB:
            rs.append((1 if s['ch'] <= 3 else 0) - TB[(s['y'], s['nk'])])
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
    print('判定: 主張どおりなら16歳以上で残差<0かつ|z|>=2がtrain/holdout両方で一貫するはず。')
    print('  z≈0なら「高齢出産は不利」は市場が織込み済み、または元から効果なし。')


if __name__ == '__main__':
    main()
