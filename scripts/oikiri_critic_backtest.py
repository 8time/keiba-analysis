# -*- coding: utf-8 -*-
"""netkeiba調教短評が、人気帯ごとに好走とつながるか。

短評は決まった一言（気配上々／平行線 等）。見た目のプラス語が、
同じ人気の馬よりよく来るか（複勝残差）を測る。
見る期間=〜2024 / 確認=2025。残差z>=+2 かつ確認n>=80 だけ採用。
スコアには入れない。

キャッシュ: scratch/oikiri_critic_cache.json
  python scripts/oikiri_critic_backtest.py           # 取得済みを集計
  python scripts/oikiri_critic_backtest.py --fetch    # 足りないレースを取得
"""
import os
import sys
import json
import time
import argparse
import sqlite3
from collections import Counter, defaultdict

import requests

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import jockey_jv as jj
from core import oikiri
from core.scraper import _get_headers, _is_blocked, _decode_content

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANK_CACHE = os.path.join(ROOT, 'scratch', 'oikiri_grade_cache.json')
CRIT_CACHE = os.path.join(ROOT, 'scratch', 'oikiri_critic_cache.json')

from core.oikiri import critic_tone


def polarity(txt):
    t = critic_tone(txt)
    if t.startswith('－'):
        return '心配'
    if t.startswith('＋'):
        return '良さそう'
    return '普通'


def ninki_band(n):
    if n <= 3:
        return '1-3人気'
    if n <= 5:
        return '4-5人気'
    return '6番人気以下'


def load_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)


def is_jra_rid(rid):
    s = str(rid)
    if len(s) != 12 or not s.isdigit():
        return False
    return 1 <= int(s[4:6]) <= 10


def fetch_one(sess, rid):
    url = f'https://race.netkeiba.com/race/oikiri.html?race_id={rid}&type=3'
    try:
        resp = sess.get(url, timeout=15)
        resp.raise_for_status()
        html = _decode_content(resp.content)
    except Exception:
        return None
    if not html or _is_blocked(html):
        return None
    rev = oikiri.parse_oikiri_reviews(html)
    out = {}
    for um, d in rev.items():
        c = (d.get('critic') or '').strip()
        r = (d.get('rank') or '').strip()
        if c or r:
            out[str(um)] = {'critic': c, 'rank': r}
    return out


def do_fetch(limit=0):
    rank_ids = [rid for rid in load_json(RANK_CACHE) if is_jra_rid(rid)]
    cache = load_json(CRIT_CACHE)
    todo = [rid for rid in rank_ids if rid not in cache]
    if limit:
        todo = todo[:limit]
    print(f'取得対象 {len(todo)} / 既に {len(cache)} (JRA {len(rank_ids)})', flush=True)
    sess = requests.Session()
    sess.headers.update(_get_headers(referer='https://race.netkeiba.com/'))
    n_ok = 0
    for i, rid in enumerate(todo, 1):
        got = fetch_one(sess, rid)
        cache[rid] = got or {}
        if got:
            n_ok += 1
        if i % 10 == 0:
            save_json(CRIT_CACHE, cache)
            print(f'  {i}/{len(todo)} 短評あり{n_ok}', flush=True)
        time.sleep(0.28)
    save_json(CRIT_CACHE, cache)
    print(f'完了 今回OK {n_ok}  キャッシュ {len(cache)}', flush=True)


def stats_add(bucket, t3, win, odds, e3):
    bucket['n'] += 1
    bucket['t3'] += t3
    bucket['w'] += win
    bucket['pay'] += odds if win else 0.0
    bucket['r3'] += t3 - e3


def stats_rep(name, d, min_n=40):
    n = d['n']
    if n < min_n:
        print(f'  {name:18s} n={n:5d} (少)')
        return None
    hit = d['t3'] / n
    se = (0.22 * 0.78 / n) ** 0.5
    z = (d['r3'] / n) / se if se else 0.0
    roi = d['pay'] / n
    line = (f'  {name:18s} n={n:5d} 複的中{hit:5.1%} 勝{d["w"]/n:5.1%} '
            f'単ROI{roi:6.1%} 複残差{d["r3"]/n:+.3f}(z={z:+.2f})')
    star = z >= 2.0 and n >= 80
    print(line + (' ★' if star else ''))
    return {'n': n, 'hit': hit, 'z': z, 'roi': roi, 'star': star}


def empty():
    return {'n': 0, 't3': 0, 'w': 0, 'pay': 0.0, 'r3': 0.0}


def analyze():
    cache = load_json(CRIT_CACHE)
    if not cache:
        print('キャッシュが空。先に --fetch')
        return
    exp = jj.calibrate_odds_expectation()

    def e3(o):
        e = exp.get(jj._odds_band(o))
        return e['top3'] if e else 0.22

    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    by_phrase = defaultdict(lambda: defaultdict(empty))  # phrase -> period -> stats
    by_pol = defaultdict(lambda: defaultdict(lambda: defaultdict(empty)))  # pol -> band -> period
    by_cross = defaultdict(lambda: defaultdict(empty))  # (pol, band) -> period
    phrase_n = Counter()
    n_join = 0
    for rid, horses in cache.items():
        if not horses or not is_jra_rid(rid):
            continue
        rows = con.execute(
            """SELECT r.umaban, r.ninki, r.chakujun, r.win_odds, ra.year
               FROM results r JOIN races ra ON ra.race_key=r.race_key
               WHERE ra.race_id=? AND r.chakujun>0 AND r.win_odds>0 AND r.ninki>0""",
            (rid,)).fetchall()
        if not rows:
            continue
        year = int(rows[0][4])
        period = '見る(〜2024)' if year <= 2024 else ('確認(2025)' if year == 2025 else '直近(2026)')
        rmap = {str(int(um)): (int(nk), int(ch), float(od))
                for um, nk, ch, od, _y in rows}
        for um, d in horses.items():
            if um not in rmap:
                continue
            nk, ch, od = rmap[um]
            critic = (d.get('critic') or '').strip()
            if not critic:
                continue
            t3 = 1 if ch <= 3 else 0
            win = 1 if ch == 1 else 0
            ev = e3(od)
            band = ninki_band(nk)
            pol = polarity(critic)
            stats_add(by_phrase[critic][period], t3, win, od, ev)
            stats_add(by_phrase[critic]['全体'], t3, win, od, ev)
            stats_add(by_pol[pol][band][period], t3, win, od, ev)
            stats_add(by_cross[(pol, band)][period], t3, win, od, ev)
            stats_add(by_cross[(pol, band)]['全体'], t3, win, od, ev)
            phrase_n[critic] += 1
            n_join += 1
    con.close()
    print(f'結合 {n_join}頭 / 短評の種類 {len(phrase_n)}', flush=True)

    print('\n======== 言葉の印象 × 人気帯 ========')
    print('良さそう/心配は短評の言葉から。残差＋＝同じ人気よりよく来た')
    for pol in ('良さそう', '普通', '心配'):
        print(f'\n--- {pol} ---')
        for band in ('1-3人気', '4-5人気', '6番人気以下'):
            print(f'  [{band}]')
            for per in ('見る(〜2024)', '確認(2025)', '直近(2026)', '全体'):
                stats_rep(per, by_cross[(pol, band)][per], min_n=30)

    print('\n======== よく出る短評（全体・多い順） ========')
    for ph, _n in phrase_n.most_common(40):
        print(f'\n・{ph}  [{polarity(ph)}]')
        for per in ('見る(〜2024)', '確認(2025)', '全体'):
            stats_rep(per, by_phrase[ph][per], min_n=25)

    print('\n======== 確認期間で残差が目立つ短評（n>=80） ========')
    rows = []
    for ph, pers in by_phrase.items():
        d = pers.get('確認(2025)', empty())
        n = d['n']
        if n < 80:
            continue
        se = (0.22 * 0.78 / n) ** 0.5
        z = (d['r3'] / n) / se if se else 0.0
        rows.append((z, ph, d, polarity(ph)))
    rows.sort(key=lambda x: -abs(x[0]))
    if not rows:
        print('  なし')
    for z, ph, d, pol in rows[:15]:
        hit = d['t3'] / d['n']
        print(f'  {ph:10s} {pol:6s} n={d["n"]:4d} 複{hit:5.1%} '
              f'残差{d["r3"]/d["n"]:+.3f} z={z:+.2f}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    if args.fetch:
        do_fetch(limit=args.limit)
    analyze()


if __name__ == '__main__':
    main()
