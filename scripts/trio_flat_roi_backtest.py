# -*- coding: utf-8 -*-
"""3連複フラット掛けROI検証(追い上げ無し)。
toto_escalation(追い上げ)で破産確定を示した後の本筋: 『選択そのものに正味の価値があるか』を
フラット掛けROIで評価する。3連複の平均回収率は控除率で約75-80%。これを超える
(できれば100%超)選択×レースフィルターがあるかを正直に測る。

軸=1番人気固定(再現性)。相手構成3種 × レースフィルター(trio_lean)4種 の総当り。
1レース=10点×100円=1000円投資。的中=勝ち3連複が{軸}+相手2頭に含まれる。
回収=その3連複の実払戻(円/100円)。ROI=総回収/総投資。2021-25 平地 tosu>=8。"""
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
from core import value_scanner as vs

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')

# 相手構成(1番人気軸への相手5頭・人気順位で指定)。C(5,2)=10点。
PARTNER_SETS = {
    '本命型(相手2-6番)':   [2, 3, 4, 5, 6],
    '中穴型(2,3+6,7,8番)': [2, 3, 6, 7, 8],
    '穴厚型(2,3+8,10,12番)': [2, 3, 8, 10, 12],
}


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    rrows = con.execute(
        f"""SELECT ra.race_id, ra.race_key, ra.shusso_tosu, ra.juryo, ra.kyori,
                   ra.surface, ra.baba_shiba, ra.baba_dirt, r.umaban, r.ninki, r.win_odds
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
              AND ra.shusso_tosu>=8 AND r.chakujun>0""", YEARS).fetchall()
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
    for (rid, rk, tosu, juryo, kyori, surf, bsh, bdt, um, ninki, wo) in rrows:
        d = races.setdefault(rid, {'tosu': tosu, 'juryo': juryo or '', 'kyori': kyori or 0,
                                   'baba': str((bsh if (surf or '') == '芝' else bdt) or ''),
                                   'horses': []})
        d['horses'].append({'um': um, 'ninki': ninki or 99, 'wo': wo or 0})

    _BABA = {'3': '重', '4': '不良'}
    # cell[(pset, filt)] = [invested, returned, n, hits]
    cell = defaultdict(lambda: [0, 0, 0, 0])
    FILTERS = ['全レース', '本線向き', '中立', '②穴妙味向き', '②+中立']

    for rid in races:
        d = races[rid]
        if rid not in pay:
            continue
        win_tri, pp = pay[rid]
        by_ninki = {h['ninki']: h['um'] for h in d['horses']}
        if 1 not in by_ninki:
            continue
        axis = by_ninki[1]
        odds = [h['wo'] for h in d['horses'] if h['wo'] > 0]
        lean = vs.trio_lean(meta={'is_handicap': d['juryo'] == '1'}, n_horses=d['tosu'],
                            fav_odds=min(odds) if odds else None, dist=d['kyori'],
                            baba=_BABA.get(d['baba']), odds_list=odds)['lean']
        filt_tags = ['全レース', lean]
        if lean in ('②穴妙味向き', '中立'):
            filt_tags.append('②+中立')
        for pname, plist in PARTNER_SETS.items():
            partners = [by_ninki[n] for n in plist if n in by_ninki]
            if len(partners) < 5:
                continue
            pts = list(combinations(partners, 2))   # 10点(相手2頭ずつ)
            won = (axis in win_tri) and ((win_tri - {axis}) in [frozenset(c) for c in pts])
            for ft in filt_tags:
                c = cell[(pname, ft)]
                c[0] += 1000          # 10点×100円
                c[2] += 1
                if won:
                    c[1] += pp        # 当たり点の払戻(100円→pp円)
                    c[3] += 1

    print("=" * 88)
    print("3連複フラット掛けROI (軸=1番人気・10点×100円/R・2021-25 平地 tosu>=8)")
    print("控除前提: 3連複の平均回収率≒75-80%。これを超えるセルがあれば妙味の候補。")
    print("=" * 88)
    print(f"{'相手構成':<22}{'フィルター':<12}{'n':>7}{'的中%':>8}{'平均配当':>9}{'ROI%':>8}")
    print("-" * 88)
    for pname in PARTNER_SETS:
        for ft in FILTERS:
            c = cell[(pname, ft)]
            if c[2] < 100:
                continue
            roi = c[1] / c[0] * 100 if c[0] else 0
            hitr = c[3] / c[2] * 100 if c[2] else 0
            avgp = c[1] / c[3] if c[3] else 0
            mark = ' ★100%超' if roi >= 100 else (' ◎80%超' if roi >= 80 else '')
            print(f"{pname:<22}{ft:<12}{c[2]:>7}{hitr:>8.1f}{avgp:>9.0f}{roi:>8.1f}{mark}")
        print()
    print("-" * 88)
    print("※ROIは実払戻ベース(追い上げ無し)。100%超=理論上プラス。80%前後=平均的(控除なり)。")
    print("  人気薄相手はhit率が落ちるが平均配当が上がる→ROIで相殺されるか否かが論点。")


if __name__ == '__main__':
    main()
