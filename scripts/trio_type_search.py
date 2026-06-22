# -*- coding: utf-8 -*-
"""3連複 決着タイプ判別子の探索(trio_lean精度向上)。
既存trio_lean=ハンデ/フルゲート/頭数/fav_odds/pace。新候補を1番人気オッズ帯で統制して
②型(荒れ)/本線(堅)への独立寄与(z)を測り、採用すべき判別子を洗い出す。
本線=1・2番人気が両方3着内 / ②型=3着内に5番人気以下2頭以上(condition_arare_backtestと同義)。
全て事前確定でリーク無し。z②>+2&z本<-2=②独立エッジ / z本>+2&z②<-2=堅い独立シグナル。"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')
_EDGES = [1.5, 2, 2.5, 3, 4, 5, 7, 10, 1e9]
_LOCAL = {'01', '02', '03', '04', '07', '10'}  # 札幌函館福島新潟中京小倉


def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES) - 1


def dist_band(k):
    k = k or 0
    if k <= 1400:
        return '短'
    if k <= 1800:
        return 'マ'
    if k <= 2200:
        return '中'
    return '長'


con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
yf = " OR ".join(["ra.year=?"] * len(YEARS))
rows = con.execute(
    f"""SELECT ra.race_key, ra.shusso_tosu, ra.juryo, ra.kyori, ra.grade, ra.jyo,
               ra.surface, ra.baba_shiba, ra.baba_dirt, ra.race_name,
               r.chakujun, r.ninki, r.win_odds
        FROM races ra JOIN results r ON r.race_key=ra.race_key
        WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
          AND ra.shusso_tosu>=8 AND r.chakujun>0""", YEARS).fetchall()
con.close()

races = {}
for (rk, tosu, juryo, kyori, grade, jyo, surf, bsh, bdt, rname,
     chaku, ninki, wo) in rows:
    d = races.setdefault(rk, {
        'tosu': tosu, 'juryo': juryo or '', 'kyori': kyori or 0, 'grade': grade or '',
        'jyo': str(jyo or ''), 'surf': surf or '', 'rname': rname or '',
        'baba': str((bsh if (surf or '') == '芝' else bdt) or ''), 'horses': []})
    d['horses'].append({'chaku': chaku, 'ninki': ninki or 99, 'wo': wo or 0})

recs = []
for rk, d in races.items():
    hs = d['horses']
    odds = sorted(h['wo'] for h in hs if h['wo'] and h['wo'] > 0)
    if len(odds) < 3:
        continue
    fav = odds[0]
    band = oband(fav)
    top3 = [h for h in hs if h['chaku'] <= 3]
    n1 = any(h['ninki'] == 1 and h['chaku'] <= 3 for h in hs)
    n2 = any(h['ninki'] == 2 and h['chaku'] <= 3 for h in hs)
    honsen = 1 if (n1 and n2) else 0
    ana2 = 1 if sum(1 for h in top3 if h['ninki'] >= 5) >= 2 else 0
    # 候補特徴
    feats = set()
    feats.add('距離' + dist_band(d['kyori']))
    if d['grade'] in ('A', 'B', 'C'):
        feats.add('重賞(G1-3)')
    if '新馬' in d['rname']:
        feats.add('新馬')
    if '未勝利' in d['rname']:
        feats.add('未勝利')
    t = d['tosu']
    if 11 <= t <= 13:
        feats.add('中頭数11-13')
    if 14 <= t <= 15:
        feats.add('多頭数14-15')
    feats.add('ローカル場' if d['jyo'] in _LOCAL else '中央4場')
    if d['baba'] in ('3', '4'):
        feats.add('道悪(重不良)')
    # オッズ断層: 2番人気/1番人気 比
    r21 = odds[1] / fav if fav else 1
    if r21 >= 1.8:
        feats.add('1番人気抜け(2/1比≥1.8)')
    elif r21 <= 1.25:
        feats.add('上位拮抗(2/1比≤1.25)')
    # 上位3頭の単勝集中度(合成オッズ=3/Σ(1/o)) 低いほど堅い
    inv3 = sum(1.0 / o for o in odds[:3])
    syn3 = 3.0 / inv3 if inv3 else 99
    if syn3 <= 2.2:
        feats.add('上位3頭堅(合成≤2.2)')
    elif syn3 >= 4.0:
        feats.add('上位3頭割れ(合成≥4.0)')
    recs.append((band, honsen, ana2, feats, t))

band_tot = defaultdict(int); band_hon = defaultdict(int); band_ana = defaultdict(int)
for (band, hon, ana, feats, t) in recs:
    band_tot[band] += 1; band_hon[band] += hon; band_ana[band] += ana
exp_hon = {b: band_hon[b] / band_tot[b] for b in band_tot}
exp_ana = {b: band_ana[b] / band_tot[b] for b in band_tot}


def stat(sub):
    n = len(sub)
    if n == 0:
        return None
    hon = sum(r[1] for r in sub); ana = sum(r[2] for r in sub)
    e_hon = sum(exp_hon[r[0]] for r in sub); e_ana = sum(exp_ana[r[0]] for r in sub)
    var_a = sum(exp_ana[r[0]] * (1 - exp_ana[r[0]]) for r in sub)
    var_h = sum(exp_hon[r[0]] * (1 - exp_hon[r[0]]) for r in sub)
    z_ana = (ana - e_ana) / math.sqrt(var_a) if var_a > 0 else 0
    z_hon = (hon - e_hon) / math.sqrt(var_h) if var_h > 0 else 0
    return {'n': n, 'hon': hon / n * 100, 'hr': (hon - e_hon) / n * 100, 'zh': z_hon,
            'ana': ana / n * 100, 'ar': (ana - e_ana) / n * 100, 'za': z_ana}


base = {'n': len(recs), 'hon': sum(r[1] for r in recs) / len(recs) * 100,
        'ana': sum(r[2] for r in recs) / len(recs) * 100}
print("=" * 96)
print(f"母集団(2021-25 平地 tosu>=8): n={base['n']:,}  本線{base['hon']:.1f}%  ②型{base['ana']:.1f}%  "
      "(1番人気オッズ帯で統制)")
print("=" * 96)
print(f"{'判別子候補':<24}{'n':>7}{'本線%':>7}{'本線残差':>9}{'z本':>7}{'②型%':>7}{'②残差':>8}{'z②':>7}")
print("-" * 96)
cands = ['距離短', '距離マ', '距離中', '距離長', '重賞(G1-3)', '新馬', '未勝利',
         '中頭数11-13', '多頭数14-15', 'ローカル場', '中央4場', '道悪(重不良)',
         '1番人気抜け(2/1比≥1.8)', '上位拮抗(2/1比≤1.25)', '上位3頭堅(合成≤2.2)', '上位3頭割れ(合成≥4.0)']
for c in cands:
    s = stat([r for r in recs if c in r[3]])
    if not s or s['n'] < 150:
        print(f"{c:<24}{(s['n'] if s else 0):>7} (sample<150)")
        continue
    flag = ''
    if s['za'] > 2 and s['zh'] < -2:
        flag = ' ★②独立'
    elif s['zh'] > 2 and s['za'] < -2:
        flag = ' ◆堅独立'
    print(f"{c:<24}{s['n']:>7}{s['hon']:>7.1f}{s['hr']:>+9.2f}{s['zh']:>+7.2f}"
          f"{s['ana']:>7.1f}{s['ar']:>+8.2f}{s['za']:>+7.2f}{flag}")
print("-" * 96)
print("★②独立=z②>+2&z本<-2(オッズ超で荒れる) / ◆堅独立=z本>+2&z②<-2(オッズ超で堅い)。")
print("残差≈0=織込み済み(タイプ選択の足しにならない)。")
