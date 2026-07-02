# -*- coding: utf-8 -*-
"""消去フロンティア検証 ―― カード3(ボーダー3廃止の是非)。

現行の消去は『人気で下位半分カット』(支配項=-人気)＋『ボーダーで1頭戻す』。
ボーダーは半分カットが3着内馬をこぼす(≈15%)のを≈10%に戻す後始末。
問い: 弱点フラグ数(elim_cross)を消去順に織り込めば、ボーダー無しでも
      こぼし率≤10% かつ 平均消去頭数≥現行(ボーダーON) を両立できるか?

方式(リーク無し):
  - 各馬の弱点フラグ数を過去走から構築(elim_cross_backtest.pyと同じ8フラグ)。
  - 消去スコア = 人気rank + W×フラグ数 (大きいほど消す)。W=0が現行(人気のみ)。
  - Wは train(2021-24)で『ボーダーON同数消去時のこぼし最小』を選び凍結。
  - holdout2025/confirm2026 で こぼし率・平均消去頭数を現行3方式と比較。
採用ゲート(カード3): holdout2025 で フロンティア こぼし率≤10% かつ 平均消去頭数≥ボーダーON。
両立しなければ却下(=ボーダー3は正しい設計と決着)。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
LOAD_FROM = 2019  # 履歴用(testは2021-)
MIN_FIELD = 8


def dk(y, md):
    return int(y) * 10000 + int(md)


def build():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.monthday md, r.ketto_num kt, r.chakujun ch, "
        "r.ninki nk, r.win_odds wo, r.ato3f a3, r.corner4 c4, r.zogen zg, r.age ag, "
        "ra.kyori ki, ra.shusso_tosu st, ra.jyo jyo "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= ? AND ra.jyo BETWEEN '01' AND '10'",
        (LOAD_FROM,)).fetchall()
    con.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        d = dk(rs[0]['y'], rs[0]['md'])
        n = rs[0]['st'] or len(rs)
        a3 = sorted([(x['a3'], x) for x in rs if x['a3'] and x['a3'] > 0], key=lambda t: t[0])
        rank = {x['kt']: (i + 1) / len(a3) for i, (_, x) in enumerate(a3)} if a3 else {}
        for x in rs:
            if not x['ch'] or x['ch'] <= 0:
                continue
            c4r = (x['c4'] / n) if (x['c4'] and n) else None
            hist[x['kt']].append({'dk': d, 'dist': x['ki'], 'top3': 1 if x['ch'] <= 3 else 0,
                                  'a3rank': rank.get(x['kt']), 'c4r': c4r})
    for k in hist:
        hist[k].sort(key=lambda z: z['dk'])
    return by_race, hist


def flag_count(r, d, hist):
    h = hist.get(r['kt'], [])
    p5 = [x for x in h if x['dk'] < d][-5:]
    p3 = p5[-3:]
    c = 0
    if len(p3) >= 3 and all(x['top3'] == 0 for x in p3):
        c += 1  # form3
    if len(p5) >= 3 and all(x['top3'] == 0 for x in p5):
        c += 1  # nofuku5
    ar = [x['a3rank'] for x in p3 if x['a3rank'] is not None]
    if len(ar) >= 2 and sum(ar) / len(ar) >= 0.70:
        c += 1  # slow3f
    cr = [x['c4r'] for x in p3 if x['c4r'] is not None]
    if len(cr) >= 2 and sum(cr) / len(cr) >= 0.78:
        c += 1  # back
    if p5 and (d - p5[-1]['dk']) >= 180:
        c += 1  # layoff (概算)
    if p5 and p5[-1]['dist'] and r['ki'] and abs(r['ki'] - p5[-1]['dist']) >= 400:
        c += 1  # distbig
    if r['zg'] is not None and abs(r['zg']) >= 16:
        c += 1  # zogen
    if r['ag'] is not None and r['ag'] >= 8:
        c += 1  # age8
    return c


def eval_period(by_race, hist, y_from, y_to, W):
    """各方式の こぼし数/3着内総数/消去頭数を集計。
    方式: off(半分カット) / on(+1ボーダー) / frontier(人気+W×フラグ, on同数消去)"""
    tot3 = 0
    miss = {'off': 0, 'on': 0, 'front': 0}
    misw = {'off': 0, 'on': 0, 'front': 0}
    totw = 0
    cut = {'off': 0, 'on': 0, 'front': 0}
    nrace = 0
    for rk, rs in by_race.items():
        y = int(rs[0]['y'])
        if not (y_from <= y <= y_to):
            continue
        horses = [x for x in rs if x['ch'] and x['ch'] > 0 and x['nk'] and x['nk'] > 0]
        n = len(horses)
        if n < MIN_FIELD:
            continue
        nrace += 1
        d = dk(rs[0]['y'], rs[0]['md'])
        keep_base = (n + 1) // 2
        keep_plus = keep_base + 1
        k_off = n - keep_base    # off消去頭数
        k_on = n - keep_plus     # on消去頭数(=フロンティアも同数)
        cut['off'] += k_off
        cut['on'] += k_on
        cut['front'] += k_on
        # pop rank(1=最人気)
        fcmap = {id(h): flag_count(h, d, hist) for h in horses}
        pop_sorted = sorted(horses, key=lambda x: x['nk'])
        pop_rank = {id(h): i + 1 for i, h in enumerate(pop_sorted)}
        # off/on: 人気下位を消す
        elim_off = {id(h) for h in horses if pop_rank[id(h)] > keep_base}
        elim_on = {id(h) for h in horses if pop_rank[id(h)] > keep_plus}
        # frontier: score=人気rank + W×フラグ数, 上位k_on頭を消す
        scored = sorted(horses, key=lambda h: (pop_rank[id(h)] + W * fcmap[id(h)]), reverse=True)
        elim_front = {id(h) for h in scored[:k_on]}
        for h in horses:
            t3 = 1 if h['ch'] <= 3 else 0
            w = 1 if h['ch'] == 1 else 0
            tot3 += t3
            totw += w
            for name, elim in (('off', elim_off), ('on', elim_on), ('front', elim_front)):
                if id(h) in elim:
                    miss[name] += t3
                    misw[name] += w
    return {'tot3': tot3, 'totw': totw, 'miss': miss, 'misw': misw,
            'cut': cut, 'nrace': nrace}


def show(tag, r):
    print(f"\n=== {tag} ({r['nrace']}R, 3着内総数{r['tot3']}) ===")
    print(f"{'方式':<26}{'平均消去頭数':>10}{'こぼし率(3着内)':>14}{'勝ち馬こぼし':>12}")
    print("-" * 64)
    for name, lbl in (('off', '現行ボーダーOFF(半分)'), ('on', '現行ボーダーON(+1戻し)'),
                      ('front', 'フロンティア(人気+フラグ)')):
        avgcut = r['cut'][name] / max(r['nrace'], 1)
        cob = r['miss'][name] / max(r['tot3'], 1)
        cobw = r['misw'][name] / max(r['totw'], 1)
        print(f"{lbl:<26}{avgcut:>10.2f}{cob*100:>13.1f}%{cobw*100:>11.1f}%")
    return r


def main():
    print("読み込み・履歴構築中...")
    by_race, hist = build()

    # W選択: train2021-24で on同数消去時の frontier こぼし最小
    print("\n########## W選択(train 2021-24) ##########")
    best_w, best_cob = 0, 1.0
    for W in (0, 1, 2, 3, 5):
        r = eval_period(by_race, hist, 2021, 2024, W)
        cob = r['miss']['front'] / max(r['tot3'], 1)
        mark = ''
        if cob < best_cob:
            best_cob, best_w = cob, W
            mark = ' ←best'
        print(f"  W={W}: frontier こぼし率 {cob*100:.2f}% (on={r['miss']['on']/max(r['tot3'],1)*100:.2f}%){mark}")
    print(f"凍結 W={best_w}")

    show("train 2021-24", eval_period(by_race, hist, 2021, 2024, best_w))
    rh = show("holdout 2025", eval_period(by_race, hist, 2025, 2025, best_w))
    show("confirm 2026", eval_period(by_race, hist, 2026, 2026, best_w))

    print("\n" + "=" * 64)
    print("採用ゲート(カード3): holdout2025 フロンティア こぼし率≤10% かつ 平均消去頭数≥ボーダーON")
    cob_f = rh['miss']['front'] / max(rh['tot3'], 1)
    cob_on = rh['miss']['on'] / max(rh['tot3'], 1)
    cut_f = rh['cut']['front'] / max(rh['nrace'], 1)
    cut_on = rh['cut']['on'] / max(rh['nrace'], 1)
    print(f"  フロンティア: こぼし{cob_f*100:.1f}% / 消去{cut_f:.2f}頭")
    print(f"  ボーダーON  : こぼし{cob_on*100:.1f}% / 消去{cut_on:.2f}頭")
    ok_cob = cob_f <= 0.10
    ok_cut = cut_f >= cut_on - 1e-9
    better = cob_f <= cob_on + 1e-9
    if ok_cob and ok_cut and better:
        print(f"  判定: ✅ 採用 (こぼし≤10%かつ消去≥ON かつ ON以下のこぼし) → トグル配線可")
    else:
        why = []
        if not ok_cob:
            why.append(f"こぼし{cob_f*100:.1f}%>10%")
        if not better:
            why.append(f"こぼしがON({cob_on*100:.1f}%)より悪化({cob_f*100:.1f}%)")
        if not ok_cut:
            why.append("消去頭数がON未満")
        print(f"  判定: ❌ 却下 ({' / '.join(why)}) → ボーダー3は正しい設計")


if __name__ == '__main__':
    main()
