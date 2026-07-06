# -*- coding: utf-8 -*-
"""妙味馬(7番人気以下で3着内に来る馬)の傾向研究。

穴馬ハンターを『妙味のある馬発見ツール』へ作り替えるための地固め。
ユーザー依頼(2026-07): 直近3ヶ月の7番人気以下で3着内に来る馬が、このアプリの検証済み数値
(補正T/血統スコア/血統回収/末脚指数/33ラップ/騎手力/位置取り/消去クロス)のどれを持つかを数値化。

リーク無し: 各シグナルは各レース時点『以前』の履歴のみで計算(revival_backtest.pyと同じ機構)。
bataiju/futan/ninki/win_oddsは事前確定。kyakushitsuは結果脚質なので使わず、過去平均通過順(位置取り)を使う。
train=2024-01〜2026-06(統計力) / recent=直近3ヶ月(2026-03-21〜, ユーザー指定)。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import corrected_time as ct
from core import bloodline as bl
from core import lap33 as l3
from core import elim_cross as ec

DB = jj.JV_DB_PATH
POP_MIN = 7                 # 7番人気以下
RECENT_KEY = '2026032100000000'


def main():
    print("読み込み(JRA 2023-2026/6)...")
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.ato3f h_ato3f, r.jockey_name jockey_name, r.bataiju bw, r.zogen zg, "
        "r.age age, r.corner1 c1, r.corner2 c2, r.corner3 c3, r.corner4 c4, "
        "ra.juryo juryo, ra.shusso_tosu tosu, ra.kyori kyori, ra.surface surface, ra.monthday md, ra.jyo jyo "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT)>=2023 "
        "ORDER BY r.race_key").fetchall()
    hrows = con.execute("SELECT ketto_num, sire, bms FROM horses").fetchall()
    con.close()
    horse_sire = {k: (s, b) for k, s, b in hrows}
    print(f"  {len(rows):,}行")

    jp_by_jockey = {}
    for _jn in {r['jockey_name'] for r in rows if r['jockey_name']}:
        try:
            jp_by_jockey[_jn] = jj.jockey_power(_jn).get('jpower')
        except Exception:
            jp_by_jockey[_jn] = None
    _ct_cache = {}

    def ct_fig(kt, surf):
        key = (kt, surf)
        if key not in _ct_cache:
            fig = ct.get_figure(kt, surf) or ct.get_figure(kt, None)
            _ct_cache[key] = fig.get('fig') if fig and fig.get('fig') is not None else None
        return _ct_cache[key]

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    hist_ag = defaultdict(list); hist_c4 = defaultdict(list)
    hist_t3 = defaultdict(list); hist_dt = defaultdict(list)
    for rk, rs in by_race.items():
        a3 = [(x['h_ato3f'], x['kt']) for x in rs if x['h_ato3f'] and x['h_ato3f'] > 0]
        a3.sort(key=lambda t: t[0])
        arank = {kt: (i + 1) / len(a3) for i, (_, kt) in enumerate(a3)} if a3 else {}
        tosu = rs[0]['tosu'] or len(rs)
        for x in rs:
            if x['kt'] in arank:
                hist_ag[x['kt']].append((rk, arank[x['kt']]))
            cs = [c for c in (x['c1'], x['c2'], x['c3'], x['c4']) if c and c > 0]
            if cs and tosu:
                hist_c4[x['kt']].append((rk, (sum(cs) / len(cs)) / tosu, sum(cs) / len(cs)))
            hist_t3[x['kt']].append((rk, 1 if x['ch'] <= 3 else 0))
            hist_dt[x['kt']].append((rk, x['md'], x['kyori']))
    for d in (hist_ag, hist_c4, hist_t3, hist_dt):
        for k in d:
            d[k].sort(key=lambda z: z[0])

    def past_spurt(kt, rk, n=5, minr=2):
        h = hist_ag.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk][-n:]
        return (1.0 - sum(past) / len(past)) if len(past) >= minr else None

    def past_c4ratio(kt, rk, n=3):
        h = hist_c4.get(kt)
        if not h:
            return None
        past = [v for (k, v, _a) in h if k < rk][-n:]
        return (sum(past) / len(past)) if past else None

    def past_avg_pos(kt, rk, n=3):
        h = hist_c4.get(kt)
        if not h:
            return None
        past = [a for (k, _v, a) in h if k < rk][-n:]
        return (sum(past) / len(past)) if past else None

    def past_last5(kt, rk):
        h = hist_t3.get(kt)
        return [v for (k, v) in h if k < rk][-5:][::-1] if h else []

    def prev_run(kt, rk):
        h = hist_dt.get(kt)
        if not h:
            return None, None
        past = [(md, ky) for (k, md, ky) in h if k < rk]
        return past[-1] if past else (None, None)

    # period -> signal -> [top3_with, n_with]; base -> [top3, n]
    SIGS = ['🔵補正T', '🧬血統', '🧬回収', '🔥末脚', '⚡33', '👑騎手', '🏃位置3以内', '🧹低消去(≤1)']
    agg = {p: {'_base': [0, 0]} for p in ('train', 'recent')}
    for p in agg:
        for s in SIGS:
            agg[p][s] = [0, 0]
    combo_agg = {p: defaultdict(lambda: [0, 0]) for p in ('train', 'recent')}
    # 妙味レシピ候補: combo>=2 の precision
    recipe = {p: {'combo2+': [0, 0], 'combo3+': [0, 0]} for p in ('train', 'recent')}

    races = list(by_race.items())
    for ri, (rk, rs) in enumerate(races):
        if ri % 3000 == 0:
            print(f"  ...{ri}/{len(races)}", flush=True)
        yr = int(str(rk)[:4])
        if yr < 2024:
            continue
        r0 = rs[0]
        surf = '芝' if '芝' in str(r0['surface']) else 'ダ'
        kyori = r0['kyori']; jyo = str(rk)[8:10] if len(str(rk)) >= 10 else '05'
        try:
            course_v = l3.course_avg33(surf, kyori, jyo=jyo)
        except Exception:
            course_v = None
        # レース内top3(全馬)
        ct_vals = {r['kt']: ct_fig(r['kt'], surf) for r in rs}
        ct_vals = {k: v for k, v in ct_vals.items() if v is not None}
        ct_top3 = {k for k, _ in sorted(ct_vals.items(), key=lambda x: x[1])[:3]}
        sp_vals = {r['kt']: past_spurt(r['kt'], rk) for r in rs}
        sp_top3 = {k for k, v in sorted(((k, v) for k, v in sp_vals.items() if v is not None),
                                        key=lambda x: -x[1])[:3]}
        bl_vals = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            if sire or bms:
                bl_vals[r['kt']] = bl.blood_score(sire, bms, surf, kyori)
        bl_top3 = {k for k, _ in sorted(bl_vals.items(), key=lambda x: -x[1])[:3]}
        jp_vals = {r['kt']: jp_by_jockey.get(r['jockey_name']) for r in rs}
        jp_top3 = {k for k, v in sorted(((k, v) for k, v in jp_vals.items() if v is not None),
                                        key=lambda x: -x[1])[:3]}
        period = 'recent' if rk >= RECENT_KEY else 'train'

        for r in rs:
            if not r['nk'] or int(r['nk']) < POP_MIN:
                continue
            kt = r['kt']; t3 = 1 if r['ch'] <= 3 else 0
            sire, bms = horse_sire.get(kt, (None, None))
            ss = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            roi100 = bool(ss and ss.get('win_roi', 0) >= 100)
            lap_fit = False
            if course_v:
                hf = l3.horse_fit33(kt, before_key=rk)
                lap_fit = l3.fit_match(hf.get('avg_lap33'), course_v['avg']) is True
            avg_pos = past_avg_pos(kt, rk)
            front = (avg_pos is not None and avg_pos <= 3.0)
            # 消去クロス
            pmd, pdist = prev_run(kt, rk)
            fl = ec.compute_flags(
                last5_top3=past_last5(kt, rk), spurt_index=sp_vals.get(kt),
                spurt_runs=len([1 for (k, v) in hist_ag.get(kt, []) if k < rk][-5:]),
                avg_c4ratio=past_c4ratio(kt, rk),
                prev_date=(str(r['y']) + str(pmd)) if pmd else None,
                race_date=(str(r['y']) + str(r['md'])) if r['md'] else None,
                prev_dist=pdist, cur_dist=kyori, zogen=r['zg'], age=r['age'],
                is_handicap=(str(r['juryo']) == '1'))
            elim_n = ec.verified_count(fl)

            sig_on = {
                '🔵補正T': kt in ct_top3, '🧬血統': kt in bl_top3, '🧬回収': roi100,
                '🔥末脚': kt in sp_top3, '⚡33': lap_fit, '👑騎手': kt in jp_top3,
                '🏃位置3以内': front, '🧹低消去(≤1)': elim_n <= 1,
            }
            a = agg[period]
            a['_base'][0] += t3; a['_base'][1] += 1
            for s, on in sig_on.items():
                if on:
                    a[s][0] += t3; a[s][1] += 1
            combo6 = sum(sig_on[s] for s in ('🔵補正T', '🧬血統', '🧬回収', '🔥末脚', '⚡33', '👑騎手'))
            combo_agg[period][combo6][0] += t3; combo_agg[period][combo6][1] += 1
            if combo6 >= 2:
                recipe[period]['combo2+'][0] += t3; recipe[period]['combo2+'][1] += 1
            if combo6 >= 3:
                recipe[period]['combo3+'][0] += t3; recipe[period]['combo3+'][1] += 1

    def z_of(t3, n, base):
        if n < 20:
            return None
        rate = t3 / n
        se = (base * (1 - base) / n) ** 0.5
        return rate, (rate - base) / se if se else 0

    for period in ('train', 'recent'):
        a = agg[period]
        b0, bn = a['_base']
        base = b0 / bn if bn else 0
        print(f"\n{'='*66}\n=== {period}  7番人気以下 ベース3着内率 {base:.1%} (n={bn:,}) ===")
        print("[各シグナル単体の3着内率リフト]")
        for s in SIGS:
            t3, n = a[s]
            rz = z_of(t3, n, base)
            if rz is None:
                print(f"  {s:16s} n={n:5d} (小)")
            else:
                rate, z = rz
                print(f"  {s:16s} n={n:6d} 3着内{rate:6.1%} 基準比{(rate-base)*100:+5.1f}pp z={z:+.2f}")
        print("[combo(荒れ6シグナル同時発火数)別 3着内率]")
        for c in sorted(combo_agg[period]):
            t3, n = combo_agg[period][c]
            if n >= 20:
                print(f"  combo={c}  n={n:6d} 3着内{t3/n:6.1%}  (基準比{(t3/n-base)*100:+.1f}pp)")
        print("[妙味レシピ candidate]")
        for k, (t3, n) in recipe[period].items():
            if n >= 20:
                rz = z_of(t3, n, base)
                print(f"  {k:8s} n={n:6d} 3着内{t3/n:6.1%} 基準比{(t3/n-base)*100:+.1f}pp z={rz[1]:+.2f}"
                      f"  ※捕捉={t3}頭(全3着内穴の一部)")

    print("\n[判定] 単体z>2かつcomboで単調上昇なら『妙味馬=combo馬』として穴馬ハンターを再構築する根拠。")


if __name__ == '__main__':
    main()
