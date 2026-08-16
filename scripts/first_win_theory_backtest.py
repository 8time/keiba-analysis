# -*- coding: utf-8 -*-
"""『初勝利理論』の検証 — 初勝利時の"上がり差"は将来の走りを予告するか

主張(プレミアム予想の動画):
  G1/重賞を勝つ馬は初勝利時(新馬/未勝利の勝ち上がり)に共通点がある。
    ① 上がり最速であること
    ② 上がり2位の馬に対して大きな差(芝なら0.6秒以上)をつけていること
  着順差でなく『上がりタイムの差』を見るので馬場状態に左右されない、というのが売り。

⚠ 似て非なる既存検証:
  [[verified_prior_margin_debunk]] は『1着馬との着差0.6秒/0.8秒』の否定。今回は
  『上がり2位との上がり差』なので**別物**として測り直す。
  [[verified_spurt_index]](末脚は人気薄限定)・[[verified_spurt_pace_quality]]
  (上がりはスロー由来か否かで質が変わる)とも指標の作り方が違う。

2つの問いを分けて測る:
  (a) 主張は事実か  … 該当馬が後に重賞/OPを勝つ率が、非該当より高いか
  (b) 馬券に使えるか … 該当馬の"その後の全レース"で人気を統制した残差が出るか
      → (a)がYESでも(b)がゼロなら「本当だが市場が既に知っている」＝使えない

データ監査済: results.ato3f 取得率100%(486,002件)・1/10秒単位
  (芝の勝ち馬の上がり中央値34.7秒で妥当性確認)

使い方: python scripts/first_win_theory_backtest.py
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
GAP_MAIN = 0.6          # 主張どおりの閾値(秒)


def zof(m, n, sd):
    return m / (sd / math.sqrt(n)) if n else 0.0


def main():
    print('DB読込...')
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
    rows = con.execute(
        """SELECT r.race_key, r.ketto_num, r.chakujun, r.ato3f, r.ninki,
                  ra.year, ra.monthday, ra.surface, ra.grade
           FROM results r JOIN races ra ON ra.race_key=r.race_key
           WHERE ra.jyo BETWEEN '01' AND '10' AND ra.surface IN ('芝','ダート')
             AND ra.shubetsu NOT IN ('18','19') AND r.chakujun>0
             AND CAST(ra.year AS INT)>=2016""").fetchall()
    con.close()
    print(f'  {len(rows):,}行')

    # レース単位に上がりを集約 → 上がり順位と2位との差
    race_ato = defaultdict(list)
    for rk, kt, ch, a3, nk, y, md, sf, g in rows:
        if a3 and int(a3) > 0:
            race_ato[str(rk)].append((str(kt), int(a3)))
    fastest = {}    # race_key -> (最速のato3f, 2番目のato3f)
    for rk, lst in race_ato.items():
        vs = sorted(v for _, v in lst)
        if len(vs) >= 2:
            fastest[rk] = (vs[0], vs[1])

    # 馬ごとに時系列
    by_horse = defaultdict(list)
    for rk, kt, ch, a3, nk, y, md, sf, g in rows:
        if not kt:
            continue
        day = int(str(y) + str(md).zfill(4))
        by_horse[str(kt)].append(dict(day=day, rk=str(rk), ch=int(ch),
                                      a3=int(a3 or 0), nk=(int(nk) if nk else None),
                                      y=int(y), sf=str(sf), g=str(g or '')))
    for lst in by_horse.values():
        lst.sort(key=lambda z: (z['day'], z['rk']))

    # 初勝利レースを特定し、上がり最速か/2位との差を算出
    horses = {}
    for kt, lst in by_horse.items():
        fw = next((r for r in lst if r['ch'] == 1), None)
        if not fw or fw['a3'] <= 0:
            continue
        f = fastest.get(fw['rk'])
        if not f:
            continue
        is_fastest = (fw['a3'] == f[0])
        gap = (f[1] - fw['a3']) / 10.0 if is_fastest else 0.0   # 秒
        horses[kt] = dict(fw_day=fw['day'], fw_year=fw['y'], fw_surf=fw['sf'],
                          is_fastest=is_fastest, gap=gap,
                          after=[r for r in lst if r['day'] > fw['day']])
    print(f'  初勝利を特定できた馬: {len(horses):,}頭\n')

    def sig(h, gap_th=GAP_MAIN, surf=None):
        if surf and h['fw_surf'] != surf:
            return False
        return h['is_fastest'] and h['gap'] >= gap_th

    print('=' * 80)
    print('■ 0. 該当率（どれくらい珍しい条件か）')
    print('=' * 80)
    for sf in ('芝', 'ダート'):
        sub = [h for h in horses.values() if h['fw_surf'] == sf]
        f1 = sum(1 for h in sub if h['is_fastest'])
        print(f'  {sf}で初勝利 {len(sub):>7,}頭 / 上がり最速 {f1:>6,} ({f1/len(sub)*100:4.1f}%)')
        for th in (0.3, 0.4, 0.5, 0.6, 0.8):
            c = sum(1 for h in sub if h['is_fastest'] and h['gap'] >= th)
            print(f'      上がり最速×2位と{th}秒差以上: {c:>5,} ({c/len(sub)*100:4.2f}%)')

    print()
    print('=' * 80)
    print('■ (a) 主張は事実か — その後 重賞/OP を勝つ率')
    print('=' * 80)

    def later_win(h, grades):
        return any(r['ch'] == 1 and r['g'] in grades for r in h['after'])

    for sf in ('芝', 'ダート'):
        print(f'\n  === {sf}で初勝利した馬 ===')
        print(f"  {'区分':<26}{'n':>8}{'重賞勝ち':>10}{'率':>8}{'OP+重賞':>10}{'率':>8}")
        sub = [h for h in horses.values() if h['fw_surf'] == sf]
        groups = [('非該当(全体)', lambda h: True),
                  ('上がり最速のみ', lambda h: h['is_fastest']),
                  (f'最速×{GAP_MAIN}秒差以上★主張', lambda h: sig(h))]
        for lbl, gf in groups:
            g = [h for h in sub if gf(h)]
            if len(g) < 50:
                continue
            jg = sum(1 for h in g if later_win(h, ('A', 'B', 'C', 'D')))
            op = sum(1 for h in g if later_win(h, ('A', 'B', 'C', 'D', 'L')))
            print(f'  {lbl:<26}{len(g):>8,}{jg:>10,}{jg/len(g)*100:>7.2f}%'
                  f'{op:>10,}{op/len(g)*100:>7.2f}%')

    # ── (b) 馬券に使えるか: 人気統制後の残差 ──
    print()
    print('=' * 80)
    print('■ (b) 馬券に使えるか — その後の全レースで人気を統制した残差')
    print('=' * 80)
    print('  ベース=人気別top3率(train〜2023凍結)。残差>0かつz>=2が両窓で一貫なら市場超え。')

    bt = defaultdict(lambda: [0, 0])
    samples = []     # (year, ninki, top3, is_sig, surf)
    for kt, h in horses.items():
        s = sig(h)
        for r in h['after']:
            if r['nk'] is None:
                continue
            t3 = 1 if r['ch'] <= 3 else 0
            samples.append((r['y'], r['nk'], t3, s, h['fw_surf']))
            if r['y'] <= TRAIN_END:
                bt[r['nk']][0] += t3
                bt[r['nk']][1] += 1
    TB = {k: v[0] / v[1] for k, v in bt.items() if v[1] >= 50}
    print(f'  対象(初勝利後の出走) {len(samples):,}頭\n')

    def resid(keep):
        out = []
        for (y, nk, t3, s, sf) in samples:
            if not keep(y, nk, t3, s, sf):
                continue
            if nk not in TB:
                continue
            out.append(t3 - TB[nk])
        return out

    print(f"  {'区分':<22}{'期間':<16}{'n':>8}{'複勝残差':>10}{'z':>8}")
    for sf in ('芝', 'ダート'):
        for pl, pf in ((f'train〜{TRAIN_END}', lambda y: y <= TRAIN_END),
                       ('holdout 2024+', lambda y: y > TRAIN_END)):
            rs = resid(lambda y, nk, t3, s, ss, p=pf, f=sf: p(y) and s and ss == f)
            if len(rs) < 100:
                print(f'  {sf+"・該当馬":<22}{pl:<16}{len(rs):>8,}  標本不足')
                continue
            m = sum(rs) / len(rs)
            print(f'  {sf+"・該当馬":<22}{pl:<16}{len(rs):>8,}{m:>+10.4f}'
                  f'{zof(m, len(rs), 0.42):>+8.2f}')

    print()
    print('  参考: 閾値を変えた場合(芝・holdout 2024+)')
    print(f"  {'閾値':<22}{'n':>8}{'複勝残差':>10}{'z':>8}")
    for th in (0.3, 0.4, 0.5, 0.6, 0.8):
        sig_set = {kt for kt, h in horses.items()
                   if h['fw_surf'] == '芝' and h['is_fastest'] and h['gap'] >= th}
        rs = []
        for kt in sig_set:
            for r in horses[kt]['after']:
                if r['y'] > TRAIN_END and r['nk'] in TB:
                    rs.append((1 if r['ch'] <= 3 else 0) - TB[r['nk']])
        if len(rs) < 100:
            print(f'  {"最速×"+str(th)+"秒差以上":<22}{len(rs):>8,}  標本不足')
            continue
        m = sum(rs) / len(rs)
        print(f'  {"最速×"+str(th)+"秒差以上":<22}{len(rs):>8,}{m:>+10.4f}'
              f'{zof(m, len(rs), 0.42):>+8.2f}')

    print()
    print('=' * 80)
    print('■ bootstrap 95%CI（芝・該当馬・holdout）')
    print('=' * 80)
    rs = resid(lambda y, nk, t3, s, ss: y > TRAIN_END and s and ss == '芝')
    n = len(rs)
    if n >= 100:
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
    print('読み方: (a)で差が出ても(b)がゼロなら「主張は事実だが市場が織込み済み」＝馬券には使えない。')


if __name__ == '__main__':
    main()
