# -*- coding: utf-8 -*-
"""
荒れ条件(牝馬限定/新馬/ハンデ)の妙味検証。

問い: インフォグラフィックの「牝馬限定/新馬/ハンデ=荒れる」は、
      1番人気オッズ(=市場の堅さ)を統制してもなお
      『本線決着(①型:1・2番人気が両方3着内=鉄板)』を減らし
      『②型決着(人気-穴-穴:3着内に5番人気以下が2頭以上)』を増やすか?
      = オッズに織込み済みか、事前条件として独立エッジか。

統制: 1番人気オッズ帯(fav_odds band)ごとに母集団期待率を作り、各条件群の残差(z)で測る。
リーク無し: 条件(kigo/juryo/race_name)・1番人気オッズ・頭数はすべて事前確定。
分類: 牝馬限定=substr(kigo,2,1)='2' / ハンデ=juryo='1' / 新馬=race_name LIKE '%新馬%'
"""
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
_EDGES = [1.5, 2, 2.5, 3, 4, 5, 7, 10, 1e9]  # 1番人気オッズ帯


def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES) - 1


def main():
    for attempt in range(8):
        try:
            con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
            yf = " OR ".join(["ra.year=?"] * len(YEARS))
            rows = con.execute(
                f"""SELECT ra.race_key, ra.shusso_tosu, ra.kigo, ra.juryo, ra.race_name,
                           ra.surface, r.chakujun, r.ninki, r.win_odds
                    FROM races ra JOIN results r ON r.race_key=ra.race_key
                    WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
                      AND ra.shusso_tosu>=8 AND r.chakujun>0""",
                YEARS).fetchall()
            con.close()
            break
        except sqlite3.OperationalError:
            import time
            time.sleep(4)
    else:
        print("DB locked", file=sys.stderr)
        return
    print(f"rows={len(rows)}", file=sys.stderr)

    # group into races
    races = {}
    for (rk, tosu, kigo, juryo, rname, surf, chaku, ninki, wo) in rows:
        d = races.setdefault(rk, {'tosu': tosu, 'kigo': kigo or '', 'juryo': juryo or '',
                                  'rname': rname or '', 'surf': surf or '', 'horses': []})
        d['horses'].append({'chaku': chaku, 'ninki': ninki or 99, 'wo': wo or 0})

    # per-race metrics
    recs = []  # (band, honsen, ana2, conds set)
    for rk, d in races.items():
        hs = d['horses']
        odds = [h['wo'] for h in hs if h['wo'] and h['wo'] > 0]
        if not odds:
            continue
        fav = min(odds)
        band = oband(fav)
        top3 = [h for h in hs if h['chaku'] <= 3]
        n1_in = any(h['ninki'] == 1 and h['chaku'] <= 3 for h in hs)
        n2_in = any(h['ninki'] == 2 and h['chaku'] <= 3 for h in hs)
        honsen = 1 if (n1_in and n2_in) else 0
        ana2 = 1 if sum(1 for h in top3 if h['ninki'] >= 5) >= 2 else 0
        conds = set()
        if len(d['kigo']) >= 2 and d['kigo'][1] == '2':
            conds.add('牝馬限定')
        if d['juryo'] == '1':
            conds.add('ハンデ')
        if '新馬' in d['rname']:
            conds.add('新馬')
        if 'ダ' in str(d['surf']):
            conds.add('ダート')
        else:
            conds.add('芝')
        recs.append((band, honsen, ana2, conds, d['tosu']))

    # baseline expectation per band
    band_tot = defaultdict(int)
    band_hon = defaultdict(int)
    band_ana = defaultdict(int)
    for (band, hon, ana, conds, tosu) in recs:
        band_tot[band] += 1
        band_hon[band] += hon
        band_ana[band] += ana
    exp_hon = {b: band_hon[b] / band_tot[b] for b in band_tot}
    exp_ana = {b: band_ana[b] / band_tot[b] for b in band_tot}

    def stat(subset):
        n = len(subset)
        if n == 0:
            return None
        hon = sum(r[1] for r in subset)
        ana = sum(r[2] for r in subset)
        e_hon = sum(exp_hon[r[0]] for r in subset)
        e_ana = sum(exp_ana[r[0]] for r in subset)
        # z for ana (荒れ): positive = more 荒れ than odds predicts
        var_a = sum(exp_ana[r[0]] * (1 - exp_ana[r[0]]) for r in subset)
        z_ana = (ana - e_ana) / math.sqrt(var_a) if var_a > 0 else 0
        var_h = sum(exp_hon[r[0]] * (1 - exp_hon[r[0]]) for r in subset)
        z_hon = (hon - e_hon) / math.sqrt(var_h) if var_h > 0 else 0
        return {
            'n': n,
            'hon': hon / n * 100, 'hon_resid': (hon - e_hon) / n * 100, 'z_hon': z_hon,
            'ana': ana / n * 100, 'ana_resid': (ana - e_ana) / n * 100, 'z_ana': z_ana,
        }

    base = {'n': len(recs),
            'hon': sum(r[1] for r in recs) / len(recs) * 100,
            'ana': sum(r[2] for r in recs) / len(recs) * 100}

    print("=" * 92)
    print(f"母集団(2021-25 平地 tosu>=8): n={base['n']:,}  "
          f"本線決着率{base['hon']:.1f}%  ②型(穴2頭)決着率{base['ana']:.1f}%")
    print("  本線=1・2番人気が両方3着内 / ②型=3着内に5番人気以下が2頭以上")
    print("=" * 92)
    hdr = f"{'群':<26}{'n':>7}{'本線%':>7}{'本線残差':>9}{'z本':>7}{'②型%':>7}{'②残差':>8}{'z②':>7}"
    print(hdr)
    print("-" * 92)

    groups = [
        ('牝馬限定', lambda c, t: '牝馬限定' in c),
        ('ハンデ', lambda c, t: 'ハンデ' in c),
        ('新馬', lambda c, t: '新馬' in c),
        ('ダート戦', lambda c, t: 'ダート' in c),
        ('芝戦', lambda c, t: '芝' in c),
        ('--- 頭数別(条件無関係) ---', None),
        ('フルゲート(16頭以上)', lambda c, t: t >= 16),
        ('少頭数(8-10頭)', lambda c, t: 8 <= t <= 10),
        ('--- 荒れ条件×フルゲート ---', None),
        ('牝馬限定×16頭以上', lambda c, t: '牝馬限定' in c and t >= 16),
        ('ハンデ×16頭以上', lambda c, t: 'ハンデ' in c and t >= 16),
    ]
    for name, fn in groups:
        if fn is None:
            print(name)
            continue
        sub = [r for r in recs if fn(r[3], r[4])]
        s = stat(sub)
        if not s or s['n'] < 100:
            print(f"{name:<26}{(s['n'] if s else 0):>7} (sample<100)")
            continue
        print(f"{name:<26}{s['n']:>7}{s['hon']:>7.1f}{s['hon_resid']:>+9.2f}"
              f"{s['z_hon']:>+7.2f}{s['ana']:>7.1f}{s['ana_resid']:>+8.2f}{s['z_ana']:>+7.2f}")
    print("-" * 92)
    print("残差=オッズ帯期待からの乖離pp。z②>+2かつz本<-2なら『オッズを超えて荒れる』独立エッジ。")
    print("残差≈0なら織込み済み(=②穴妙味の根拠にできない・フォーク)。")


if __name__ == '__main__':
    main()
