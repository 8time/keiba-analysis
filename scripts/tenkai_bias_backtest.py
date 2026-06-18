# -*- coding: utf-8 -*-
"""
当日バイアス逆算(empirical_bias)の妙味エッジ検証。

問い: 「同日同場同馬場の前半レースから内枠有利/外枠有利/前残り/差しと判明した日に、
       その傾向に合致する馬(枠は事前確定)は人気を超えて好走するか?」
- 描画(傾向の持続)は検証済(track_bias.py docstring)。ここでは"妙味=人気を超えるか"を測る。
- リーク厳守: 馬の事前確定情報=umaban(枠)のみ使用。corner4(通過順)は当日バイアスの"集計"側
  (前半レースの勝ち馬)にのみ使い、対象馬の好走判定には使わない。
- 指標: 母集団のオッズ帯別期待複勝率に対する残差(z) と 単勝ROI。
"""
import os
import sys
import sqlite3
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.track_bias import empirical_bias  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')

# 細かいオッズ帯（人気補正の精度を上げる）
_EDGES = [1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50, 100, 1e9]


def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES) - 1


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    yf = " OR ".join(["ra.year=?"] * len(YEARS))
    print("loading...", file=sys.stderr)
    rows = con.execute(
        f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.race_num, ra.shusso_tosu,
                   r.umaban, r.chakujun, r.corner4, r.win_odds, r.ninki
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.shusso_tosu>=8 AND r.chakujun>0""",
        YEARS).fetchall()
    con.close()
    print(f"rows={len(rows)}", file=sys.stderr)

    # group by (day,venue,surface) -> race_num -> list of horse dicts
    days = {}
    for (y, md, jyo, surf, rnum, tosu, um, chaku, c4, wo, nin) in rows:
        surf2 = 'ダ' if 'ダ' in str(surf) else '芝'
        key = (y, md, jyo, surf2)
        days.setdefault(key, {}).setdefault(rnum, []).append(
            {'umaban': um, 'chakujun': chaku, 'corner4': c4 or 0,
             'win_odds': wo or 0, 'tosu': tosu, 'ninki': nin or 99})

    # population odds-band expectation (top3 & win)
    pop = {}
    for r in rows:
        chaku, wo = r[7], r[9]
        if not wo or wo <= 0:
            continue
        b = oband(wo)
        d = pop.setdefault(b, [0, 0, 0, 0.0])
        d[0] += 1
        d[1] += 1 if chaku <= 3 else 0
        d[2] += 1 if chaku == 1 else 0
        d[3] += wo if chaku == 1 else 0  # gross return per 1
    exp_top3 = {b: d[1] / d[0] for b, d in pop.items() if d[0]}

    # accumulators
    def newacc():
        return {'n': 0, 'top3': 0, 'win': 0, 'ret': 0.0, 'exp': 0.0}

    groups = {
        '内枠有利日×内枠馬': newacc(),
        '内枠有利日×内枠馬(confident n>=4)': newacc(),
        '外枠有利日×外枠馬': newacc(),
        '前残り日×前走前々(habitual先行)': newacc(),
        '差し日×habitual後方': newacc(),
        '当日バイアス合致(枠)全体': newacc(),
        # 逆張り=消去妙味: バイアス不利な枠を引いた人気馬(1-3番人気)は過剰人気か
        '内有利日×外枠の人気馬(1-3人気)': newacc(),
        '外有利日×内枠の人気馬(1-3人気)': newacc(),
        '外有利日×内枠の人気馬(confident n>=4)': newacc(),
        '外有利日×内枠の1番人気のみ': newacc(),
        '当日バイアス不利×人気馬 全体': newacc(),
    }
    # habitual position needs each horse's prior run; we approximate with its
    # corner4 IN PRIOR same-day races? No—use horse identity across days would
    # need ketto. Skip pace-habitual here (枠 version is the clean pre-race test).

    def add(acc, h):
        if not h['win_odds'] or h['win_odds'] <= 0:
            return
        acc['n'] += 1
        t3 = 1 if h['chakujun'] <= 3 else 0
        acc['top3'] += t3
        acc['win'] += 1 if h['chakujun'] == 1 else 0
        acc['ret'] += h['win_odds'] if h['chakujun'] == 1 else 0
        acc['exp'] += exp_top3.get(oband(h['win_odds']), 0.22)

    for key, byrace in days.items():
        rnums = sorted(byrace.keys())
        for i, rnum in enumerate(rnums):
            # prior winners (same day/venue/surface, earlier race_num)
            priors = []
            for pr in rnums:
                if pr >= rnum:
                    break
                for h in byrace[pr]:
                    if h['chakujun'] == 1 and h['corner4'] > 0:
                        priors.append({'corner4': h['corner4'], 'umaban': h['umaban'],
                                       'tosu': h['tosu']})
            bias = empirical_bias(priors)
            if not bias:
                continue
            inner_day = bias['lane_label'] == '内有利'
            outer_day = bias['lane_label'] == '外有利'
            conf = bias['confident']
            for h in byrace[rnum]:
                tosu = h['tosu'] or 0
                if tosu < 8:
                    continue
                inner_drawn = h['umaban'] <= max(1, tosu / 3)
                outer_drawn = h['umaban'] > tosu * 2 / 3
                if inner_day and inner_drawn:
                    add(groups['内枠有利日×内枠馬'], h)
                    add(groups['当日バイアス合致(枠)全体'], h)
                    if conf:
                        add(groups['内枠有利日×内枠馬(confident n>=4)'], h)
                if outer_day and outer_drawn:
                    add(groups['外枠有利日×外枠馬'], h)
                    add(groups['当日バイアス合致(枠)全体'], h)
                # 逆張り消去: バイアス不利な枠の人気馬
                pop_horse = h['ninki'] <= 3
                if pop_horse and inner_day and outer_drawn:
                    add(groups['内有利日×外枠の人気馬(1-3人気)'], h)
                    add(groups['当日バイアス不利×人気馬 全体'], h)
                if pop_horse and outer_day and inner_drawn:
                    add(groups['外有利日×内枠の人気馬(1-3人気)'], h)
                    add(groups['当日バイアス不利×人気馬 全体'], h)
                    if conf:
                        add(groups['外有利日×内枠の人気馬(confident n>=4)'], h)
                    if h['ninki'] == 1:
                        add(groups['外有利日×内枠の1番人気のみ'], h)

    # population baseline
    base_n = sum(d[0] for d in pop.values())
    base_top3 = sum(d[1] for d in pop.values()) / base_n
    base_win = sum(d[2] for d in pop.values()) / base_n
    base_roi = sum(d[3] for d in pop.values()) / base_n

    print("=" * 78)
    print(f"母集団(2021-25, tosu>=8): n={base_n:,} 複勝率{base_top3*100:.1f}% "
          f"勝率{base_win*100:.1f}% 単ROI{base_roi*100:.1f}%")
    print("=" * 78)
    print(f"{'グループ':<34} {'n':>7} {'複勝%':>6} {'残差pp':>7} {'z':>6} {'勝%':>5} {'単ROI%':>7}")
    print("-" * 78)
    for name, a in groups.items():
        if a['n'] < 30:
            print(f"{name:<34} {a['n']:>7} (sample<30)")
            continue
        t3 = a['top3'] / a['n']
        exprate = a['exp'] / a['n']
        resid = (t3 - exprate) * 100
        # z: sum(actual-exp)/sqrt(sum p(1-p)); approximate var with exprate
        var = a['n'] * exprate * (1 - exprate)
        z = (a['top3'] - a['exp']) / math.sqrt(var) if var > 0 else 0
        win = a['win'] / a['n']
        roi = a['ret'] / a['n'] * 100
        print(f"{name:<34} {a['n']:>7} {t3*100:>6.1f} {resid:>+7.2f} {z:>+6.2f} "
              f"{win*100:>5.1f} {roi:>7.1f}")
    print("-" * 78)
    print("残差pp=複勝率−オッズ帯期待 / z>+2かつROI>~75%(控除後黒字目安)で妙味。")


if __name__ == '__main__':
    main()
