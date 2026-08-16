# -*- coding: utf-8 -*-
"""動画『荒れやすいレースの条件』の未検証3項目 ―― コース/距離/馬場は独立エッジか。

【結論(2026-07-23)】3つとも不採用。全窓(2021-25)では②型残差 z2〜3で効くが、
**副窓(2025単年)で全て z<2 に崩落**＝両窓一貫の基準を満たさない。priced-in寄り。

  条件                全窓②型z   2025②型z
  小回り(中/小/福/函)    +2.87      +0.31   ← 崩落
    └ 小倉のみ          +3.24      +1.23   (単体で最強だが副窓で未達)
  短距離(≤1200m)       +2.35      -0.11   ← 崩落(符号も逆)
  重・不良馬場          +2.24      +1.65   ← 崩落(惜しいが未達)
  小回り×短距離         +2.47      -0.22   ← 崩落(符号も逆)

  全窓のz2〜3は5年分(n=数千)の検出力で拾えているだけで、単年に割ると消える。
  「小回り/短距離/道悪は荒れる」は事実だが、その荒れは1番人気オッズが既に
  織り込んでいる(統制後の上乗せが年をまたいで安定しない)。
  → 既検証のハンデ/フルゲート(z5前後で両窓一貫)とは検出力が一桁違う。
    レース選別のtrio_leanに足す価値なし。動画の条件は"検索の目安"どまり。


動画5条件のうち、ハンデ戦・フルゲート・牝馬限定・少頭数は検証済み
([[verified_arare_conditions]])。残る3つを同じ枠組みで検証する:
  ① 小回りコース(中山/小倉/福島/函館) … 前残りで荒れる?
  ② 短距離(1200m以下) … 挽回時間が無く紛れる?
  ③ 重・不良馬場 … 時計がかかり格差が縮む?

検証の肝(condition_arare_backtest.py と同じ):
  **1番人気オッズ帯で統制**する。「小回りは荒れる」だけなら市場が既にオッズで
  そう言っている可能性がある(priced-in)。オッズの堅さを揃えた上で、なお
  ②型決着(人気-穴-穴)が増える/本線決着(1・2番人気が両方3着内)が減るかを残差zで見る。

指標:
  honsen = 1・2番人気が両方3着内(鉄板・母集団≈31%)
  ana2   = 3着内に5番人気以下が2頭以上(②型・母集団≈28%)
リーク無し: コース/距離/馬場/1番人気オッズは全て事前確定(発走前に判る)。

採用ゲート: ②型残差 z>=2(または本線残差 z<=-2)。オッズを超える独立エッジの基準。

Usage: python scripts/course_arare_backtest.py
"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  'data', 'jravan.db')
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

YEARS = ('2021', '2022', '2023', '2024', '2025')
HOLD = ('2025',)                      # 副窓(近年だけで符号が保たれるか)
_EDGES = [1.5, 2, 2.5, 3, 4, 5, 7, 10, 1e9]

# 小回りコース(動画: 馬群が密集し前残りしやすい)
SMALL = {'06', '10', '03', '02'}      # 中山/小倉/福島/函館
BIG = {'05', '04'}                    # 東京/新潟(直線長い=堅い、と動画)


def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES) - 1


def fetch():
    for _ in range(8):
        try:
            con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
            break
        except sqlite3.OperationalError:
            import time
            time.sleep(3)
    else:
        raise SystemExit('DB busy')
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    rows = con.execute(
        f"""SELECT ra.race_key, ra.year, ra.jyo, ra.kyori, ra.surface,
                   ra.baba_shiba, ra.baba_dirt, ra.shusso_tosu,
                   r.chakujun, r.ninki, r.win_odds
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.jyo<='10' AND ra.shubetsu IN ('11','12','13','14')
              AND ra.shusso_tosu>=8 AND r.chakujun>0 AND r.ninki>0""",
        list(YEARS)).fetchall()
    con.close()
    return rows


def build(rows):
    """レース単位に畳む。各レースに条件フラグと決着ラベルを付ける。"""
    R = defaultdict(list)
    meta = {}
    for rk, yr, jyo, kyori, surf, bs, bd, tosu, chaku, ninki, odds in rows:
        R[rk].append((int(chaku), int(ninki), odds))
        if rk not in meta:
            surf_s = '芝' if '芝' in str(surf) else 'ダ'
            baba = bs if surf_s == '芝' else bd
            meta[rk] = {'year': str(yr), 'jyo': str(jyo), 'kyori': int(kyori),
                        'surf': surf_s, 'baba': str(baba)}
    out = []
    for rk, horses in R.items():
        m = meta[rk]
        t3 = [n for c, n, _ in horses if c <= 3]
        if len(t3) < 3:
            continue
        fav_odds = min((o for c, n, o in horses if n == 1 and o), default=None)
        honsen = int(sum(1 for c, n, o in horses if c <= 3 and n <= 2) >= 2)
        ana2 = int(sum(1 for c, n, o in horses if c <= 3 and n >= 5) >= 2)
        m2 = dict(m)
        m2.update({'race_key': rk, 'band': oband(fav_odds),
                   'honsen': honsen, 'ana2': ana2})
        out.append(m2)
    return out


def resid(sub, base, key):
    n = len(sub)
    if n < 100:
        return None
    obs = sum(r[key] for r in sub)
    exp = sum(base[r['band']][key] for r in sub)
    var = sum(base[r['band']][key] * (1 - base[r['band']][key]) for r in sub)
    if var <= 0:
        return None
    return {'rate': obs / n, 'exp': exp / n, 'resid': (obs - exp) / n,
            'z': (obs - exp) / math.sqrt(var), 'n': n}


def base_rates(races):
    b = defaultdict(lambda: {'honsen': [0, 0], 'ana2': [0, 0]})
    for r in races:
        for k in ('honsen', 'ana2'):
            b[r['band']][k][0] += r[k]
            b[r['band']][k][1] += 1
    return {band: {k: (v[k][0] / v[k][1] if v[k][1] else 0.3) for k in v}
            for band, v in b.items()}


def report(races, label):
    base = base_rates(races)
    print(f'\n{"=" * 82}\n{label}  (全{len(races):,}レース・1番人気オッズ帯で統制)\n{"=" * 82}')
    print(f'{"条件":28s} {"該当":>7s} {"本線率":>7s} {"本線残差":>9s} '
          f'{"②型率":>7s} {"②型残差":>9s} {"z(②)":>7s}')

    def line(name, sub):
        rh = resid(sub, base, 'honsen')
        ra = resid(sub, base, 'ana2')
        if not rh or not ra:
            print(f'{name:28s}  n<100')
            return
        print(f'{name:28s} {len(sub):>7,} {rh["rate"]:>6.1%} '
              f'{rh["resid"] * 100:>+7.2f}pp {ra["rate"]:>6.1%} '
              f'{ra["resid"] * 100:>+7.2f}pp {ra["z"]:>+7.2f}')

    line('① 小回り(中山/小倉/福島/函館)', [r for r in races if r['jyo'] in SMALL])
    line('   ├ 中山', [r for r in races if r['jyo'] == '06'])
    line('   ├ 小倉', [r for r in races if r['jyo'] == '10'])
    line('   └ 福島', [r for r in races if r['jyo'] == '03'])
    line('  (対照)広い(東京/新潟)', [r for r in races if r['jyo'] in BIG])
    line('② 短距離(≤1200m)', [r for r in races if r['kyori'] <= 1200])
    line('   1300-1600m', [r for r in races if 1300 <= r['kyori'] <= 1600])
    line('  (対照)長距離(≥2200m)', [r for r in races if r['kyori'] >= 2200])
    line('③ 重・不良馬場', [r for r in races if r['baba'] in ('3', '4')])
    line('   稍重', [r for r in races if r['baba'] == '2'])
    line('  (対照)良馬場', [r for r in races if r['baba'] == '1'])
    # 小回り×短距離の相乗(動画の複合)
    line('④ 小回り×短距離', [r for r in races
                          if r['jyo'] in SMALL and r['kyori'] <= 1200])


def main():
    rows = fetch()
    races = build(rows)
    report(races, '【全窓】2021-2025')
    report([r for r in races if r['year'] in HOLD], '【副窓】2025のみ')
    print(f'\n{"=" * 82}')
    print('読み方: ②型残差 z>=2 が全窓と副窓で一貫すればオッズを超える独立エッジ。')
    print('  z<2 なら「小回りは荒れるが、それは1番人気オッズが既に織り込んでいる」＝priced-in。')
    print('  既検証: ハンデ/フルゲートは独立エッジ・少頭数は堅い([[verified_arare_conditions]])。')


if __name__ == '__main__':
    main()
