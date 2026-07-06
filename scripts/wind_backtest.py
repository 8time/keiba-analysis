# -*- coding: utf-8 -*-
"""風の影響 再検証バックテスト (verified 再調査・改良版)。

旧版は2023-24芝・勝ち馬4角位置のみでr≈+0.049(ほぼ無効)と結論。標本が小さく閾値/交互作用未検証。
今回:
  - Open-Meteo archive(ERA5・無料) で 10場×2016-2025 の"発走時刻の"風速/風向を取得(JSONディスクキャッシュ)。
  - 各場の直線走行方位 _VENUE_STRAIGHT_BEARING から符号付き向かい風成分 comp を計算(+向かい風/-追い風)。
  - 閾値(|comp|≥4, ≥7 m/s)・向き × 脚質(DiD)・馬体重・斤量 で3着内率(人気統制の残差)/ROIを検証。

リーク方針:
  - 風/馬体重(bataiju)/斤量(futan)/人気(ninki)は事前確定=リーク無し。
  - kyakushitsu(脚質)は結果脚質=リーク源。脚質×風は「向かい風時の前有利 − 平穏時の前有利」の
    差分の差(DiD)で見る(定常リークは相殺)。加えて corner1(1角位置=リーク軽)でも front-bias を確認。
  - "市場を超えるか"は人気別ベース3着内率からの残差(z)で判定。
"""
import os
import sys
import json
import math
import time
import sqlite3
import statistics
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'wind_archive_cache.json')

# jyo -> (lat, lon, 直線走行方位deg)  ※方位は core/pace_map._VENUE_STRAIGHT_BEARING と同一
VENUE = {
    '01': (43.062, 141.351, 80),   '02': (41.778, 140.729, 250),
    '03': (37.752, 140.470, 200),  '04': (37.918, 139.049, 110),
    '05': (35.659, 139.483, 300),  '06': (35.725, 139.999, 340),
    '07': (35.063, 136.954, 40),   '08': (34.909, 135.713, 70),
    '09': (34.784, 135.362, 110),  '10': (33.860, 130.882, 250),
}
YEARS = list(range(2016, 2026))


def fetch_wind_cache():
    """(jyo,'YYYY-MM-DDTHH') -> (speed,dir)。開催時間帯(9-18時)のみJSONキャッシュ。"""
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            cache = json.load(f)
    import requests
    changed = False
    for jyo, (lat, lon, _) in VENUE.items():
        for yr in YEARS:
            ck = f"{jyo}:{yr}"
            if ck in cache:
                continue
            url = (f"https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
                   f"&hourly=wind_speed_10m,wind_direction_10m&wind_speed_unit=ms"
                   f"&timezone=Asia%2FTokyo&start_date={yr}-01-01&end_date={yr}-12-31")
            for attempt in range(4):
                try:
                    j = requests.get(url, timeout=60).json()
                    h = j.get('hourly', {})
                    ts = h.get('time', []); ws = h.get('wind_speed_10m', []); wd = h.get('wind_direction_10m', [])
                    d = {}
                    for i, t in enumerate(ts):
                        hh = int(t[11:13])
                        if 9 <= hh <= 18 and ws[i] is not None and wd[i] is not None:
                            d[t[:13]] = [ws[i], wd[i]]
                    cache[ck] = d
                    changed = True
                    print(f"  fetched {jyo} {yr} ({len(d)}h)", flush=True)
                    time.sleep(0.4)
                    break
                except Exception as e:
                    print(f"  retry {jyo} {yr}: {e}", flush=True)
                    time.sleep(3)
    if changed:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
    flat = {}
    for ck, d in cache.items():
        jyo = ck.split(':')[0]
        for key, (s, wdir) in d.items():
            flat[(jyo, key)] = (s, wdir)
    return flat


def head_component(speed, wdir, bearing):
    """符号付き向かい風成分 (m/s)。 +=向かい風, -=追い風。横風は~0。風は wdir『から』吹く。"""
    ang = math.radians(((wdir - bearing + 180) % 360) - 180)
    return speed * math.cos(ang)


def main():
    print("風アーカイブ取得(キャッシュ)...")
    wind = fetch_wind_cache()
    print(f"  風データ {len(wind):,}時間ぶん")

    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    print("レース読み込み...")
    races = con.execute(
        "SELECT race_key rk, year y, monthday md, jyo, hasso_time ht, surface, kyori "
        "FROM races WHERE jyo<='10' AND CAST(year AS INT)>=2016 AND CAST(year AS INT)<=2025 "
        "AND hasso_time!=''").fetchall()
    rmeta = {r['rk']: r for r in races}
    res = con.execute(
        "SELECT race_key rk, chakujun ch, ninki nk, win_odds wo, bataiju bw, futan fu, "
        "kyakushitsu ks, corner1 c1 FROM results WHERE jyo<='10' AND CAST(year AS INT)>=2016 "
        "AND CAST(year AS INT)<=2025 AND chakujun>0").fetchall()
    con.close()

    race_comp = {}
    for rk, r in rmeta.items():
        bearing = VENUE.get(r['jyo'], (0, 0, 0))[2]
        ht = str(r['ht']).zfill(4)
        try:
            hh = int(ht[:2])
        except Exception:
            continue
        md = str(r['md']).zfill(4)
        key = f"{r['y']}-{md[:2]}-{md[2:]}T{hh:02d}"
        w = wind.get((r['jyo'], key))
        if not w:
            continue
        race_comp[rk] = {'comp': head_component(w[0], w[1], bearing), 'speed': w[0],
                         'surface': r['surface'], 'kyori': r['kyori'], 'jyo': r['jyo']}
    print(f"  風結合 {len(race_comp):,}/{len(rmeta):,}レース")

    base_n = defaultdict(lambda: [0, 0])
    horses = []
    for x in res:
        rc = race_comp.get(x['rk'])
        if not rc or not x['nk'] or x['nk'] <= 0:
            continue
        t3 = 1 if x['ch'] <= 3 else 0
        base_n[x['nk']][0] += t3
        base_n[x['nk']][1] += 1
        horses.append({
            'comp': rc['comp'], 'speed': rc['speed'], 'surface': rc['surface'], 'jyo': rc['jyo'],
            'ch': x['ch'], 't3': t3, 'win': 1 if x['ch'] == 1 else 0,
            'nk': x['nk'], 'wo': x['wo'], 'bw': x['bw'], 'fu': x['fu'],
            'ks': str(x['ks']), 'c1': x['c1'],
        })
    base = {k: (v[0] / v[1] if v[1] else 0) for k, v in base_n.items()}
    print(f"  対象 {len(horses):,}頭")

    def resid_report(label, sub):
        n = len(sub)
        if n < 80:
            print(f"  {label:38s} n={n:5d} (小)")
            return
        t3 = sum(h['t3'] for h in sub) / n
        exp = sum(base.get(h['nk'], 0) for h in sub) / n
        se = (0.15 * 0.85 / n) ** 0.5
        z = (t3 - exp) / se if se else 0
        print(f"  {label:38s} n={n:6d} 複勝{t3:6.1%} 期待{exp:6.1%} 残差{(t3-exp)*100:+5.1f}pp z={z:+.2f}")

    # [0] 粗相関(旧版r再現)
    xs = [h['comp'] for h in horses]; ys = [-h['ch'] for h in horses]
    try:
        r = statistics.correlation(xs, ys)
    except Exception:
        r = float('nan')
    print(f"\n[0] 向かい風成分 vs 着順(良化方向) 相関 r={r:+.4f}  (旧版=+0.049 芝1479R)")

    # [1] 閾値別 全体残差
    print("\n[1] 向かい風成分の閾値別 全体残差(人気統制)")
    for lab, f in [("平穏 |comp|<4", lambda h: abs(h['comp']) < 4),
                   ("向かい風 comp>=4", lambda h: h['comp'] >= 4),
                   ("向かい風 強 comp>=7", lambda h: h['comp'] >= 7),
                   ("追い風 comp<=-4", lambda h: h['comp'] <= -4),
                   ("追い風 強 comp<=-7", lambda h: h['comp'] <= -7)]:
        resid_report(lab, [h for h in horses if f(h)])

    # [2] 脚質×風 前有利のDiD
    print("\n[2] 脚質×風 前有利DiD (前=逃1+先2, 後=差3+追4)  複勝率")
    def leg_rate(sub, front):
        g = [h for h in sub if (h['ks'] in ('1', '2')) == front]
        return (sum(h['t3'] for h in g) / len(g), len(g)) if g else (None, 0)
    calm = [h for h in horses if abs(h['comp']) < 4]
    cf, _ = leg_rate(calm, True); cb, _ = leg_rate(calm, False)
    calm_diff = (cf - cb) if (cf and cb) else 0
    for wlab, wf in [('平穏|comp|<4', lambda h: abs(h['comp']) < 4),
                     ('向かい風>=4', lambda h: h['comp'] >= 4),
                     ('向かい風>=7', lambda h: h['comp'] >= 7),
                     ('追い風<=-4', lambda h: h['comp'] <= -4),
                     ('追い風<=-7', lambda h: h['comp'] <= -7)]:
        sub = [h for h in horses if wf(h)]
        fr, fn = leg_rate(sub, True); br, bn = leg_rate(sub, False)
        if fr is None or br is None:
            continue
        did = (fr - br) - calm_diff
        tag = "" if wlab.startswith('平穏') else f"  DiD={did*100:+.1f}pp"
        print(f"  {wlab:12s} 前{fr:6.1%}(n{fn:5d}) 後{br:6.1%}(n{bn:5d}) 前-後={((fr-br)*100):+5.1f}pp{tag}")

    # [2b] corner1前列(リーク軽) front-bias
    print("\n[2b] 1角3番手以内(早め先頭・リーク軽)の残差 × 風")
    for wlab, wf in [('平穏|comp|<4', lambda h: abs(h['comp']) < 4),
                     ('向かい風>=4', lambda h: h['comp'] >= 4),
                     ('向かい風>=7', lambda h: h['comp'] >= 7),
                     ('追い風<=-4', lambda h: h['comp'] <= -4)]:
        g = [h for h in horses if wf(h) and h['c1'] and 1 <= h['c1'] <= 3]
        resid_report(f"1角先頭×{wlab}", g)

    # [3] 馬体重×強風 (事前確定=クリーン)
    print("\n[3] 馬体重×風 残差(人気統制)  大型>=500 / 小柄<460")
    for wlab, wf in [('平穏|comp|<4', lambda h: abs(h['comp']) < 4),
                     ('強風|comp|>=7', lambda h: abs(h['comp']) >= 7),
                     ('向かい風>=7', lambda h: h['comp'] >= 7)]:
        sub = [h for h in horses if wf(h) and h['bw']]
        resid_report(f"大型>=500 ×{wlab}", [h for h in sub if h['bw'] >= 500])
        resid_report(f"小柄<460  ×{wlab}", [h for h in sub if h['bw'] < 460])

    # [4] 斤量×強風 (futanは0.1kg単位=570→57.0kg)
    print("\n[4] 斤量×風 残差  重>=570(57.0kg) / 軽<540(54.0kg)")
    for wlab, wf in [('平穏|comp|<4', lambda h: abs(h['comp']) < 4),
                     ('強風|comp|>=7', lambda h: abs(h['comp']) >= 7)]:
        sub = [h for h in horses if wf(h) and h['fu']]
        resid_report(f"重>=57.0 ×{wlab}", [h for h in sub if h['fu'] >= 570])
        resid_report(f"軽<54.0  ×{wlab}", [h for h in sub if h['fu'] < 540])

    # [5] 単勝ROI(参考)
    print("\n[5] 単勝ROI(参考・win_odds欠損注意)")
    def roi(sub):
        v = [h for h in sub if h['wo'] and h['wo'] > 0]
        if len(v) < 80:
            return None
        return sum((h['wo'] if h['win'] else 0) for h in v) / len(v), len(v)
    for lab, wf in [('向かい風>=7 × 前(逃先)', lambda h: h['comp'] >= 7 and h['ks'] in ('1', '2')),
                    ('向かい風>=7 × 大型500+', lambda h: h['comp'] >= 7 and h['bw'] and h['bw'] >= 500),
                    ('追い風<=-7 × 後(差追)', lambda h: h['comp'] <= -7 and h['ks'] in ('3', '4'))]:
        rr = roi([h for h in horses if wf(h)])
        if rr:
            print(f"  {lab:26s} ROI {rr[0]*100:5.1f}% n={rr[1]}")

    print("\n[判定] 残差z>2かつDiDが明確なら実装価値。閾値でも残差≈0/ROI控除割れなら"
          "『表示のみ』の従来判断を維持。")


if __name__ == '__main__':
    main()
