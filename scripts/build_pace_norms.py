# -*- coding: utf-8 -*-
"""
事前ペース予測の基準ノルム生成 — data/pace_norms.json を作る。
predict_pace_intensity() がライブで「前方TOP3のテン速力」を距離馬場内z化するために、
(馬場, 距離band) ごとの『前方TOP3テン速力の平均/標準偏差』を事前計算して保存する。

検証(scripts/pace_predict_backtest.py)で、この前方TOP3テン速力z(符号反転)が実前半ペースと
相関 r=0.226・オッズ層内で荒れ率を事後ペース天井並みに動かす(中層1.11倍)ことを確認済み。
ノルムはその z 化の母集団統計。出走馬の履歴計算(条件×直近加重・前k走)はノルム生成と
ライブ(fetch_jv_profilesのten_speed)で揃える。
"""
import os, sys, sqlite3, json, statistics
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core.pace_map import _parse_jv_time

DB = jj.JV_DB_PATH
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'pace_norms.json')
HIST_FROM = 2018
NORM_FROM = 2019   # ノルム母集団(履歴が2走以上たまる年から)
K = 5
TOPK = 3


def date_key(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def surf_norm(s):
    s = str(s or '')
    if 'ダ' in s:
        return 'ダ'
    if '障' in s:
        return '障'
    return '芝'


def main():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print('読み込み中...')
    rows = con.execute(
        "SELECT r.race_key, r.year, r.monthday, r.ketto_num, r.chakujun, r.ato3f, r.time, "
        "ra.kyori, ra.surface FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= ?", (HIST_FROM,)).fetchall()
    con.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    hist = defaultdict(list)   # ketto -> [(dk, ts, surf, kyori)]
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            if not r['chakujun'] or r['chakujun'] <= 0:
                continue
            t = _parse_jv_time(r['time'])
            if t is None or not r['ato3f'] or r['ato3f'] <= 0 or not r['kyori'] or r['kyori'] <= 700:
                continue
            ts = (t - r['ato3f'] / 10.0) / (r['kyori'] - 600) * 600.0
            if 25.0 < ts < 60.0:
                hist[r['ketto_num']].append((dk, ts, r['surface'], r['kyori']))
    for k in hist:
        hist[k].sort()

    def pre_ts(ketto, dk, surf, ky):
        h = hist.get(ketto)
        if not h:
            return None
        past = [(d, ts, s, k) for (d, ts, s, k) in h if d < dk]
        if len(past) < 2:
            return None
        past = past[-K:][::-1]
        num = den = 0.0
        for idx, (d, ts, s, k) in enumerate(past):
            cw = 1.0
            if surf and s:
                cw *= 1.6 if str(surf) == str(s) else 0.5
            if ky and k:
                cw *= 1.4 if abs(k - ky) <= 400 else 0.6
            w = cw * (0.82 ** idx)
            num += ts * w; den += w
        return num / den if den else None

    grp = defaultdict(list)
    for rk, rs in by_race.items():
        if int(rs[0]['year']) < NORM_FROM:
            continue
        surf = rs[0]['surface']; ky = rs[0]['kyori']
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        tsps = []
        for r in rs:
            v = pre_ts(r['ketto_num'], dk, surf, ky)
            if v is not None:
                tsps.append(v)
        if len(tsps) < TOPK + 2:
            continue
        tsps.sort()
        top = sum(tsps[:TOPK]) / TOPK
        grp[(surf_norm(surf), (ky or 0) // 400)].append(top)

    norms = {}
    for (sn, band), vals in grp.items():
        if len(vals) < 30:
            continue
        norms[f"{sn}|{band}"] = [round(statistics.mean(vals), 4),
                                  round(statistics.pstdev(vals) or 1.0, 4), len(vals)]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'k': K, 'topk': TOPK, 'norms': norms}, f, ensure_ascii=False, indent=1)
    print(f"保存: {OUT}  ({len(norms)} buckets)")
    for key in sorted(norms)[:12]:
        m, sd, n = norms[key]
        print(f"  {key:<8} mean={m:.2f} sd={sd:.2f} n={n}")


if __name__ == '__main__':
    main()
