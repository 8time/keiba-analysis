# -*- coding: utf-8 -*-
"""展開適合度 × 血統回収100%+ のAND検証。

ユーザー仮説(アパタイトテソーロ=展開84.7・父回収109%・12番人気・3着):
  「展開適合が高い AND 血統回収100%以上」の人気薄は、
  通常の穴馬より3着以内に来やすいか。

測る段階:
  1. 展開適合度が高い
  2. 血統回収率100%以上(父×条件の単勝回収。画面の『複xx%/回yy%』と同じ)
  3. 1 AND 2
  4. 3 AND 8番人気以下  → 穴としての着内率・単勝回収・人気統制残差

展開適合の区切り: >=70 / 75 / 80 / 85
  (画面の84.7★ は >=80 で星が付く閾値と同じ式)

展開適合度の再現:
  core.race_analysis_tools.calculate_all_deploy_scores と同じ加重
  (位置40% + PCIマッチ35% + 密集25%)。
  入力は当該レースより前の過去走のみ(リーク無し)。
  密集は予測位置の重なりから近似(ライブの通過記号は過去再現できない)。
  ライブの84.7と1点単位では一致しないが、同じ式・同じ閾値で切る。

train=2021-2024 / holdout=2025。JRA。採用ゲート=両窓 z>=+2 かつ残差>0 かつ n>=200。

実行: python scripts/deploy_blood_and_backtest.py
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bloodline as bl
from core import jockey_jv as jj
from core.lap33 import JV_DB_PATH
from core.race_analysis_tools import PCICalculator

import sqlite3
import math

THRESH = (70, 75, 80, 85)
TRAIN = (2021, 2024)
HOLD = (2025, 2025)
MIN_N = 200
Z_OK = 2.0
PAST_N = 5


def _con():
    return sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True, timeout=30)


def to_sec(v):
    """jravan time: 1132 → 73.2秒。"""
    try:
        s = str(int(v))
    except (TypeError, ValueError):
        return None
    if not s or s == '0':
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def to_agari(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x <= 0:
        return None
    # 372 → 37.2 / すでに37.2ならそのまま
    return x / 10.0 if x >= 80 else x


def deploy_score(pos_ratio, avg_pci, rpci, collapse, n_near):
    """calculate_all_deploy_scores と同じ加重。pos_ratio: 0=前, 1=後。"""
    if pos_ratio is None or avg_pci is None or rpci is None:
        return None
    if collapse >= 3.5:
        pos_pts = min(100.0, pos_ratio * 100.0)
    elif collapse <= 2.0:
        pos_pts = max(0.0, 100.0 - pos_ratio * 100.0)
    else:
        pos_pts = max(0.0, 100.0 - abs(pos_ratio - 0.5) * 200.0)

    is_fatal = False
    if rpci <= 49.5 and avg_pci > rpci + 1.5:
        is_fatal = True
    elif rpci >= 50.5 and avg_pci < rpci - 1.5:
        is_fatal = True
    elif 49.5 < rpci < 50.5 and abs(avg_pci - rpci) > 3.0:
        is_fatal = True
    if is_fatal:
        pci_match = 0.0
    else:
        pci_match = max(0.0, 100.0 - abs(avg_pci - rpci) * 5.0)

    density_score = max(0.0, float(n_near) - 1.0) * 0.8
    density_pts = max(0.0, min(100.0, 80.0 - density_score * 15.0))
    return round(pos_pts * 0.40 + pci_match * 0.35 + density_pts * 0.25, 1)


def z_resid(res_sum, n):
    if n <= 0:
        return 0.0
    se = math.sqrt(0.22 * 0.78 / n)
    return (res_sum / n) / se if se > 0 else 0.0


def main():
    print('読み込み中(JRA results)...')
    con = _con()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.time htime, r.ato3f ato, r.corner4 c4, "
        "ra.kyori kyori, ra.surface surface, ra.shusso_tosu tosu, ra.year y "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT) >= 2016 "
        "ORDER BY r.race_key"
    ).fetchall()
    hrows = con.execute("SELECT ketto_num, sire FROM horses").fetchall()
    con.close()
    horse_sire = {kt: sire for kt, sire in hrows}
    print(f'  {len(rows):,}行 / 父辞書 {len(horse_sire):,}頭')

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)
    race_keys = sorted(by_race)

    exp = jj.calibrate_odds_expectation()

    def e3(o):
        if not o or o <= 0:
            return 0.22
        e = exp.get(jj._odds_band(o))
        return e['top3'] if e else 0.22

    roi_cache = {}

    def sire_roi100(sire, surf, kyori):
        key = (sire, surf, kyori)
        if key not in roi_cache:
            st = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            roi_cache[key] = bool(st and st.get('win_roi', 0) >= 100)
        return roi_cache[key]

    hist = defaultdict(list)  # kt -> [(pos_ratio, pci)]
    # period -> slice_name -> [t3, n, res_sum, win_pay]
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0, 0.0]))

    n_eval = 0
    n_skip_hist = 0
    pci_fn = PCICalculator.calculate_pci

    for rk in race_keys:
        yr = int(str(rk)[:4])
        rs = by_race[rk]
        r0 = rs[0]
        kyori = r0['kyori']
        surf = '芝' if '芝' in str(r0['surface'] or '') else 'ダ'
        tosu = r0['tosu'] or len(rs)
        if tosu < 8:
            # 履歴だけ更新
            for r in rs:
                pos = None
                if r['c4'] and r['c4'] > 0 and tosu >= 2:
                    pos = min(1.0, (r['c4'] - 1) / max(tosu - 1, 1))
                tsec = to_sec(r['htime'])
                ag = to_agari(r['ato'])
                pci = None
                if tsec and ag and kyori:
                    pci = pci_fn(tsec, ag, kyori)
                    if not (20.0 <= pci <= 100.0):
                        pci = None
                if pos is not None or pci is not None:
                    hist[r['kt']].append((pos, pci))
                    if len(hist[r['kt']]) > 12:
                        hist[r['kt']] = hist[r['kt']][-12:]
            continue

        # 各馬の過去平均
        past = {}
        for r in rs:
            h = hist.get(r['kt']) or []
            last = h[-PAST_N:]
            prs = [p for p, _ in last if p is not None]
            pcs = [c for _, c in last if c is not None]
            if len(prs) < 2 or len(pcs) < 2:
                past[r['kt']] = None
                continue
            past[r['kt']] = (sum(prs) / len(prs), sum(pcs) / len(pcs))

        usable = [p for p in past.values() if p]
        if len(usable) < max(6, int(tosu * 0.5)):
            n_skip_hist += 1
        else:
            fronts = [pci for pos, pci in usable if pos <= 0.35]
            rpci = (sum(fronts) / len(fronts)) if fronts else (
                sum(pci for _, pci in usable) / len(usable))
            n_front = sum(1 for pos, _ in usable if pos <= 0.35)
            if n_front >= 5:
                collapse = 4.0
            elif n_front <= 2:
                collapse = 1.5
            else:
                collapse = 2.7
            # 予測位置の近傍数
            pos_list = [past[r['kt']][0] for r in rs if past.get(r['kt'])]

            if TRAIN[0] <= yr <= HOLD[1]:
                period = 'train' if yr <= TRAIN[1] else 'holdout'
                n_eval += 1
                for r in rs:
                    if not r['nk'] or not r['wo'] or r['wo'] <= 0:
                        continue
                    nk = int(r['nk'])
                    wo = float(r['wo'])
                    t3 = 1 if r['ch'] <= 3 else 0
                    win = 1 if r['ch'] == 1 else 0
                    res = t3 - e3(wo)
                    pay = wo if win else 0.0
                    pv = past.get(r['kt'])
                    ds = None
                    if pv:
                        my_pos, my_pci = pv
                        n_near = sum(1 for p in pos_list if abs(p - my_pos) < 0.08)
                        ds = deploy_score(my_pos, my_pci, rpci, collapse, n_near)
                    sire = horse_sire.get(r['kt'])
                    roi_ok = sire_roi100(sire, surf, kyori)

                    def add(name):
                        a = agg[period][name]
                        a[0] += t3
                        a[1] += 1
                        a[2] += res
                        a[3] += pay

                    add('ALL')
                    if nk >= 8:
                        add('POP8')
                    if roi_ok:
                        add('BLOOD')
                        if nk >= 8:
                            add('BLOOD_POP8')
                    if ds is not None:
                        for th in THRESH:
                            if ds >= th:
                                add(f'D{th}')
                                if roi_ok:
                                    add(f'D{th}_AND')
                                if nk >= 8:
                                    add(f'D{th}_POP8')
                                if roi_ok and nk >= 8:
                                    add(f'D{th}_AND_POP8')

        # 履歴更新(今走を未来に漏らさないよう最後に足す)
        for r in rs:
            pos = None
            if r['c4'] and r['c4'] > 0 and tosu >= 2:
                pos = min(1.0, (r['c4'] - 1) / max(tosu - 1, 1))
            tsec = to_sec(r['htime'])
            ag = to_agari(r['ato'])
            pci = None
            if tsec and ag and kyori:
                pci = pci_fn(tsec, ag, kyori)
                if not (20.0 <= pci <= 100.0):
                    pci = None
            if pos is not None or pci is not None:
                hist[r['kt']].append((pos, pci))
                if len(hist[r['kt']]) > 12:
                    hist[r['kt']] = hist[r['kt']][-12:]

    print(f'評価レース: {n_eval:,}  (履歴不足スキップ {n_skip_hist:,})')
    print('展開適合は過去走の位置+PCIで再現。ライブの84.7と1点単位では一致しない。')

    def show(period):
        print(f'\n=== {period} ===')
        print(f"{'条件':<28}{'n':>8}{'着内率':>8}{'残差':>8}{'z':>7}{'単ROI':>8}")

        def line(name, label):
            t3, n, res, pay = agg[period][name]
            if n == 0:
                print(f"{label:<28}{'n=0':>8}")
                return None
            hit = t3 / n
            resid = res / n
            z = z_resid(res, n)
            roi = pay / n
            mark = ''
            if n < MIN_N:
                mark = '  (n不足)'
            print(f"{label:<28}{n:8d}{hit:7.1%}{resid*100:+7.2f}pp{z:+7.2f}{roi:7.1%}{mark}")
            return {'n': n, 'hit': hit, 'resid': resid, 'z': z, 'roi': roi}

        alls = line('ALL', '全体')
        p8 = line('POP8', '8番人気以下(基準)')
        print('-- 単体 --')
        line('BLOOD', '血統回収100%+')
        line('BLOOD_POP8', '血統回収100%+ ×8番〜')
        for th in THRESH:
            line(f'D{th}', f'展開>={th}')
        print('-- AND --')
        for th in THRESH:
            line(f'D{th}_AND', f'展開>={th} AND 血統100%+')
        print('-- AND × 8番人気以下 --')
        rows_out = []
        for th in THRESH:
            s = line(f'D{th}_AND_POP8', f'展開>={th} AND 血統 ×8番〜')
            rows_out.append((th, s))
        return p8, rows_out

    tr_base, tr_and = show('train')
    ho_base, ho_and = show('holdout')

    print('\n=== 判定(穴馬AND: 両窓 z>=+2 かつ残差>0 かつ n>=200) ===')
    any_ok = False
    for (th, ts), (_, hs) in zip(tr_and, ho_and):
        ok = (ts and hs
              and ts['n'] >= MIN_N and hs['n'] >= MIN_N
              and ts['z'] >= Z_OK and hs['z'] >= Z_OK
              and ts['resid'] > 0 and hs['resid'] > 0)
        vs = ''
        if ts and hs and tr_base and ho_base:
            vs = (f"  vs穴基準 着内 {ts['hit']-tr_base['hit']:+.1%}/"
                  f"{hs['hit']-ho_base['hit']:+.1%}")
        print(f"  展開>={th} AND 血統100%+ ×8番〜 : "
              f"{'★採用' if ok else '未達'}{vs}")
        any_ok = any_ok or ok
    if not any_ok:
        print('→ どの区切りでもゲート未達。今回の1件は偶然側。エンジンには足さない。')
    else:
        print('→ 穴馬候補として見る価値あり(加点は別途、点数に入れるかは残差の大きさで判断)。')


if __name__ == '__main__':
    main()
