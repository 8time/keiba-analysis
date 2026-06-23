# -*- coding: utf-8 -*-
"""#6 馬連/馬単 軸Veto バックテスト。
P0危険人気Vetoを馬連/馬単の自動軸に入れた効果を検証。FEATURE_STATUSで🟡だった両券種を、
危険軸を避けた時に的中率/ROI/トリガミがどう動くかで評価(ダメならUIは参考表示に降格)。

戦略: 軸1頭流し(相手=2-6番人気5頭・フラット5点)。
  baseline: 軸=1番人気固定。
  veto    : 1番人気が danger_veto severity>=2 なら軸を次点の非危険人気へ降格。
馬連=軸と相手2頭の組、馬単=軸→相手(頭固定)。実払戻(payouts)でROI。2021-25 平地。"""
import os
import sys
import sqlite3
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import danger_gate as dg
from core import value_scanner as vs

DB = jj.JV_DB_PATH
YEARS = ('2021', '2022', '2023', '2024', '2025')
_SEX = {'1': '牡', '2': '牝', '3': 'セ'}


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
    sire_of = {str(k): s for k, s in con.execute("SELECT ketto_num, sire FROM horses").fetchall()}
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    rrows = con.execute(
        f"""SELECT ra.race_id, ra.race_key, ra.surface, ra.baba_shiba, ra.baba_dirt, ra.monthday,
                   r.umaban, r.ninki, r.win_odds, r.ketto_num, r.sex, r.age
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14') AND ra.shusso_tosu>=8
              AND r.chakujun>0""", YEARS).fetchall()
    prows = con.execute(
        """SELECT race_id, bet_type, combo, payout FROM payouts
           WHERE bet_type IN ('馬連','馬単') AND (race_id LIKE '2021%' OR race_id LIKE '2022%'
             OR race_id LIKE '2023%' OR race_id LIKE '2024%' OR race_id LIKE '2025%')""").fetchall()
    con.close()

    qpay, epay = {}, {}
    for rid, bt, combo, p in prows:
        try:
            if bt == '馬連':
                qpay[rid] = (frozenset(int(combo[i:i+2]) for i in range(0, 4, 2)), p)
            else:
                epay[rid] = (tuple(int(combo[i:i+2]) for i in range(0, 4, 2)), p)
        except Exception:
            pass

    races = defaultdict(dict)
    for (rid, rk, surf, bsh, bdt, md, um, ninki, wo, ket, sex, age) in rrows:
        d = races[rid]
        d.setdefault('meta', (surf, bsh, bdt, md))
        d.setdefault('h', {})[ninki] = {'um': um, 'wo': wo, 'ket': ket, 'sex': sex, 'age': age}

    cell = defaultdict(lambda: {'q_inv': 0, 'q_ret': 0, 'q_hit': 0,
                                'e_inv': 0, 'e_ret': 0, 'e_hit': 0, 'n': 0})

    for rid, d in races.items():
        h = d['h']
        if not all(n in h for n in (1, 2, 3, 4, 5, 6)):
            continue
        surf, bsh, bdt, md = d['meta']
        baba = vs.baba_code_to_label(bsh if surf == '芝' else bdt)
        month = int(str(md)[:2]) if md and str(md)[:2].isdigit() else None
        # 1番人気の危険判定
        fav = h[1]
        vr = dg.danger_veto(ninki=1, surface=surf, baba=baba,
                            sire=sire_of.get(str(fav['ket'])),
                            sex_age=_SEX.get(str(fav['sex']), '') + str(fav['age'] or ''),
                            month=month)
        partners = [h[n]['um'] for n in (2, 3, 4, 5, 6)]
        axis_base = h[1]['um']
        axis_veto = h[2]['um'] if vr['veto'] else h[1]['um']  # vetoなら2番人気へ
        # veto時は相手も入れ替え(軸が2番人気なら相手は1,3,4,5,6番)
        partners_veto = ([h[1]['um']] + [h[n]['um'] for n in (3, 4, 5, 6)]) if vr['veto'] else partners

        for tag, axis, parts in (('baseline', axis_base, partners),
                                 ('veto', axis_veto, partners_veto)):
            c = cell[tag]; c['n'] += 1
            # 馬連: 軸×相手 5点
            if rid in qpay:
                win_q, qp = qpay[rid]
                c['q_inv'] += 500
                for pu in parts:
                    if frozenset((axis, pu)) == win_q:
                        c['q_ret'] += qp; c['q_hit'] += 1
                        break
            # 馬単: 軸→相手(頭固定) 5点
            if rid in epay:
                win_e, ep = epay[rid]
                c['e_inv'] += 500
                for pu in parts:
                    if (axis, pu) == win_e:
                        c['e_ret'] += ep; c['e_hit'] += 1
                        break

    print("=== #6 馬連/馬単 軸Veto バックテスト (軸1頭×相手2-6番5点・2021-25) ===")
    print(f"{'戦略':<10}{'n':>7}{'馬連的中%':>10}{'馬連ROI':>9}{'馬単的中%':>10}{'馬単ROI':>9}")
    print("-" * 60)
    for tag in ('baseline', 'veto'):
        c = cell[tag]
        n = max(c['n'], 1)
        qroi = c['q_ret'] / c['q_inv'] * 100 if c['q_inv'] else 0
        eroi = c['e_ret'] / c['e_inv'] * 100 if c['e_inv'] else 0
        print(f"{tag:<10}{c['n']:>7}{c['q_hit']/n*100:>10.1f}{qroi:>9.1f}{c['e_hit']/n*100:>10.1f}{eroi:>9.1f}")
    print("-" * 60)
    print("→ veto(危険1番人気を軸から外す)でROI/的中が改善すれば馬連/馬単のVetoは有効。"
          "悪化/不変ならUIは参考表示に降格(控除は抜けない前提)。")


if __name__ == '__main__':
    main()
