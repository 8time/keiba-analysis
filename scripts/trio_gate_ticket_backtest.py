# -*- coding: utf-8 -*-
"""#3 3連複Gate チケット実ROIバックテスト。
Scanner/3連複Gateの「決着タイプtier × 可変点数」で、実際に買い目を組んで3連複配当に当てる。
tier別に 点数/的中率/ROI/トリガミ率/最大連敗 を出す(回収率ゴール直撃の現実評価)。

tier(trio_lean) と 可変点数(アプリのlean連動と同じ思想):
  見送り = 少頭数<8 / 新馬・未勝利            → 買わない
  本線向き = 軸1番人気 × 相手2-6番(本命型10点)  (堅め・的中重視)
  ②穴妙味向き = 軸1番人気 × 相手2,3番+穴7,8,9番(穴型10点)
  中立 = 本命型10点
※スコアはライブ専用で履歴に無いため、軸/相手は人気で近似(エンジンのauto相当)。
※3連複の平均回収率は控除で約75-80%。tier間の優劣/トリガミ/連敗の比較が目的(>100%は出ない前提)。
2021-25 平地 tosu>=8。"""
import os
import sys
import sqlite3
from itertools import combinations
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import value_scanner as vs

DB = jj.JV_DB_PATH
YEARS = ('2021', '2022', '2023', '2024', '2025')


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    rrows = con.execute(
        f"""SELECT ra.race_id, ra.race_key, ra.shusso_tosu, ra.juryo, ra.kyori, ra.surface,
                   ra.baba_shiba, ra.baba_dirt, ra.race_name, r.umaban, r.ninki, r.win_odds
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14') AND r.chakujun>0""", YEARS).fetchall()
    prows = con.execute(
        """SELECT race_id, combo, payout FROM payouts WHERE bet_type='3連複'
           AND (race_id LIKE '2021%' OR race_id LIKE '2022%' OR race_id LIKE '2023%'
                OR race_id LIKE '2024%' OR race_id LIKE '2025%')""").fetchall()
    con.close()

    pay = {}
    for rid, combo, p in prows:
        try:
            pay[rid] = (frozenset(int(combo[i:i+2]) for i in range(0, 6, 2)), p)
        except Exception:
            pass

    races = {}
    for (rid, rk, tosu, juryo, kyori, surf, bsh, bdt, rname, um, ninki, wo) in rrows:
        d = races.setdefault(rid, {'tosu': tosu, 'juryo': juryo or '', 'kyori': kyori or 0,
                                   'surf': surf, 'bsh': bsh, 'bdt': bdt, 'rname': rname or '',
                                   'h': {}})
        d['h'][ninki] = um
        d.setdefault('odds', []).append(wo)

    tiers = defaultdict(lambda: {'inv': 0, 'ret': 0, 'hit': 0, 'n': 0, 'tori': 0,
                                 'streak': 0, 'maxstreak': 0})

    for rid in sorted(races):
        d = races[rid]
        if rid not in pay:
            continue
        h = d['h']; tosu = d['tosu']
        # 見送り
        if tosu < 8 or '新馬' in d['rname'] or '未勝利' in d['rname']:
            continue
        if not all(n in h for n in (1, 2, 3)):
            continue
        odds = [o for o in d['odds'] if o and o > 0]
        baba = vs.baba_code_to_label(d['bsh'] if d['surf'] == '芝' else d['bdt'])
        lean = vs.trio_lean(meta={'is_handicap': d['juryo'] == '1'}, n_horses=tosu,
                            fav_odds=min(odds) if odds else None, dist=d['kyori'],
                            baba=baba, odds_list=odds)['lean']
        axis = h[1]
        if lean == '②穴妙味向き':
            parts = [h[n] for n in (2, 3, 7, 8, 9) if n in h]
        else:
            parts = [h[n] for n in (2, 3, 4, 5, 6) if n in h]
        if len(set(parts)) < 5 or axis in parts:
            continue
        pts = [frozenset((axis, a, b)) for a, b in combinations(parts[:5], 2)]  # 10点
        win_tri, pp = pay[rid]
        c = tiers[lean]; c['n'] += 1; c['inv'] += len(pts) * 100
        if win_tri in pts:
            c['hit'] += 1; c['ret'] += pp
            if pp < len(pts) * 100:
                c['tori'] += 1
            c['streak'] = 0
        else:
            c['streak'] += 1
            c['maxstreak'] = max(c['maxstreak'], c['streak'])

    print("=== #3 3連複Gate チケット実ROI (軸1番人気×相手5頭10点・2021-25・見送り除外) ===")
    print(f"{'tier(trio_lean)':<16}{'R数':>7}{'的中%':>8}{'ROI':>8}{'平均配当':>9}{'トリガミ%':>9}{'最大連敗':>8}")
    print("-" * 70)
    for lean in ('本線向き', '中立', '②穴妙味向き'):
        c = tiers[lean]
        if not c['n']:
            continue
        roi = c['ret'] / c['inv'] * 100 if c['inv'] else 0
        hitr = c['hit'] / c['n'] * 100
        avgp = c['ret'] / c['hit'] if c['hit'] else 0
        torir = c['tori'] / c['hit'] * 100 if c['hit'] else 0
        print(f"{lean:<16}{c['n']:>7}{hitr:>8.1f}{roi:>8.1f}{avgp:>9.0f}{torir:>9.1f}{c['maxstreak']:>8}")
    print("-" * 70)
    print("→ tier別の的中/ROI/トリガミ/連敗の比較。控除でROI<100%だが、本線向き=高的中/低配当、"
          "②=低的中/高配当の住み分けと、トリガミ率・連敗(資金設計)を確認。")


if __name__ == '__main__':
    main()
