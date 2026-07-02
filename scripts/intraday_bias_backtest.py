# -*- coding: utf-8 -*-
"""日内バイアス逆張り(危険人気馬)の train/holdout 検証 ―― カード2の第1タスク。

既存 tenkai_bias_backtest.py はpooled(2021-25 一括)で
「外有利日(confident)×内枠×1-3人気=複勝残差-4.6pp/z-3.8」を出した。
本スクリプトは同じ逐次集計(リーク無し=前レース勝ち馬からのみ当日バイアス推定)を
train2021-24で凍結→2025 holdout→2026 confirm に分割し、fade側エッジが
out-of-sample で生き残るかを判定する。

採用ゲート(カード2): 2025 holdout の fade群 複勝残差 z <= -2.0。
リーク厳守: 対象馬の事前確定情報=umaban(枠)/ninki(人気)のみ。corner4(通過順)は
当日バイアス"集計"側(前レース勝ち馬)にのみ使用し、対象馬の好走判定には使わない。
odds帯期待は train(2021-24) で凍結。

追加: カード記載の「前半1-6R推定→後半7-12Rのみ評価」の厳格cut も併記
(逐次版=live関数と同型が主・厳格cut=実運用デプロイ可能形の確認)。
"""
import os
import sys
import sqlite3
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.track_bias import empirical_bias, danger_popular_inner  # noqa: E402

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
TRAIN = ('2021', '2022', '2023', '2024')
HOLD = ('2025',)
CONF = ('2026',)
_EDGES = [1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50, 100, 1e9]


def oband(o):
    o = o or 1e9
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES) - 1


def load(con, years):
    yf = " OR ".join(["ra.year=?"] * len(years))
    rows = con.execute(
        f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.race_num, ra.shusso_tosu,
                   r.umaban, r.chakujun, r.corner4, r.win_odds, r.ninki
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.jyo BETWEEN '01' AND '10'
              AND ra.shusso_tosu>=8 AND r.chakujun>0""", years).fetchall()
    days = {}
    for (y, md, jyo, surf, rnum, tosu, um, chaku, c4, wo, nin) in rows:
        surf2 = 'ダ' if 'ダ' in str(surf) else '芝'
        days.setdefault((y, md, jyo, surf2), {}).setdefault(rnum, []).append(
            {'umaban': um, 'chakujun': chaku, 'corner4': c4 or 0,
             'win_odds': wo or 0, 'tosu': tosu, 'ninki': nin or 99})
    return rows, days


def build_exp(train_rows):
    """train(2021-24)のオッズ帯→複勝率で期待値を凍結"""
    pop = {}
    for r in train_rows:
        chaku, wo = r[7], r[9]
        if not wo or wo <= 0:
            continue
        d = pop.setdefault(oband(wo), [0, 0])
        d[0] += 1
        d[1] += 1 if chaku <= 3 else 0
    return {b: d[1] / d[0] for b, d in pop.items() if d[0]}


def newacc():
    return {'n': 0, 'top3': 0, 'win': 0, 'ret': 0.0, 'exp': 0.0}


def add(acc, h, exp_top3):
    if not h['win_odds'] or h['win_odds'] <= 0:
        return
    acc['n'] += 1
    acc['top3'] += 1 if h['chakujun'] <= 3 else 0
    acc['win'] += 1 if h['chakujun'] == 1 else 0
    acc['ret'] += h['win_odds'] if h['chakujun'] == 1 else 0
    acc['exp'] += exp_top3.get(oband(h['win_odds']), 0.22)


def evaluate(days, exp_top3, strict_second_half=False):
    """逐次集計で fade群を蓄積。strict=前半1-6R推定→後半7-12Rのみ評価。"""
    g = {'fade全体(外有利×内枠×1-3人気)': newacc(),
         'fade(confident)': newacc(),
         'fade(1番人気のみ)': newacc()}
    for key, byrace in days.items():
        rnums = sorted(byrace.keys())
        for rnum in rnums:
            if strict_second_half and rnum < 7:
                continue
            priors = []
            for pr in rnums:
                if pr >= rnum:
                    break
                if strict_second_half and pr > 6:
                    continue  # 推定は前半1-6Rのみ
                for h in byrace[pr]:
                    if h['chakujun'] == 1 and h['corner4'] > 0:
                        priors.append({'corner4': h['corner4'], 'umaban': h['umaban'],
                                       'tosu': h['tosu']})
            bias = empirical_bias(priors)
            if not bias:
                continue
            for h in byrace[rnum]:
                if (h['tosu'] or 0) < 8:
                    continue
                dp = danger_popular_inner(bias, h['umaban'], h['tosu'], h['ninki'])
                if not dp:
                    continue
                add(g['fade全体(外有利×内枠×1-3人気)'], h, exp_top3)
                if bias.get('confident'):
                    add(g['fade(confident)'], h, exp_top3)
                if h['ninki'] == 1:
                    add(g['fade(1番人気のみ)'], h, exp_top3)
    return g


def report(title, g):
    print(f"\n=== {title} ===")
    print(f"{'群':<30} {'n':>6} {'複勝%':>6} {'残差pp':>7} {'z':>7} {'単ROI%':>7}")
    print("-" * 66)
    out = {}
    for name, a in g.items():
        if a['n'] < 20:
            print(f"{name:<30} {a['n']:>6} (n<20)")
            out[name] = None
            continue
        t3 = a['top3'] / a['n']
        exprate = a['exp'] / a['n']
        resid = (t3 - exprate) * 100
        var = a['n'] * exprate * (1 - exprate)
        z = (a['top3'] - a['exp']) / math.sqrt(var) if var > 0 else 0
        roi = a['ret'] / a['n'] * 100
        print(f"{name:<30} {a['n']:>6} {t3*100:>6.1f} {resid:>+7.2f} {z:>+7.2f} {roi:>7.1f}")
        out[name] = {'n': a['n'], 'resid': resid, 'z': z, 'roi': roi}
    return out


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    train_rows, train_days = load(con, TRAIN)
    _, hold_days = load(con, HOLD)
    _, conf_days = load(con, CONF)
    con.close()
    exp_top3 = build_exp(train_rows)
    print(f"exp帯(train2021-24)凍結: {len(train_rows):,}行から{len(exp_top3)}帯")

    print("\n########## 逐次版(live danger_popular_inner と同型) ##########")
    gt = report("train 2021-24", evaluate(train_days, exp_top3))
    gh = report("holdout 2025", evaluate(hold_days, exp_top3))
    gc = report("confirm 2026", evaluate(conf_days, exp_top3))

    print("\n########## 厳格cut(前半1-6R推定→後半7-12Rのみ) ##########")
    report("holdout 2025 (strict)", evaluate(hold_days, exp_top3, strict_second_half=True))

    print("\n" + "=" * 66)
    print("採用ゲート(カード2): 2025 holdout fade全体 z <= -2.0")
    z_hold = (gh.get('fade全体(外有利×内枠×1-3人気)') or {}).get('z')
    if z_hold is None:
        print("判定: ⚠ holdoutのn不足で評価不能 → 却下(データ薄)")
    elif z_hold <= -2.0:
        print(f"判定: ✅ 採用 (2025 z={z_hold:+.2f} <= -2.0) → 配線可")
    else:
        print(f"判定: ❌ 却下 (2025 z={z_hold:+.2f} > -2.0)。pooled z-3.8はout-of-sampleで減衰")


if __name__ == '__main__':
    main()
