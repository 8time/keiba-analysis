# -*- coding: utf-8 -*-
"""敗者復活フィルターの検証: 消去クロスで『切る』と判定された人気薄馬のうち、
検証済みシグナルの合議(combo)が強い馬は実際に3着内に来るか。

ユーザー案(強い条件): 切る帯(消去クロス重複≥3)に落ちた人気薄(6+)でも、荒れ予報6シグナルが
複数(combo2/3+)一致した馬は復活させる価値があるか。ベース(切る帯全体)の複勝率を明確に
上回るなら『敗者復活』機能に根拠あり。上回らなければ、切る=切るで復活は妙味なし。

対象=JRA平地・人気薄(6番人気以下)。elim=消去クロスの検証済みフラグ重複数(compute_flags/
verified_count)。combo=荒れ予報6シグナル(補正T/血統スコア/血統回収/33ラップ/末脚/騎手力)の
同時発火数(各レース内top3等・リーク無し=各レース時点以前の履歴のみ)。
train2018-24 / holdout2025。
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


def main():
    print("読み込み中(JRA 2021-2025)...")
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.ato3f h_ato3f, r.jockey_name jockey_name, r.bataiju bw, r.zogen zg, "
        "r.age age, r.corner1 c1, r.corner2 c2, r.corner3 c3, r.corner4 c4, "
        "ra.juryo juryo, ra.shusso_tosu tosu, ra.kyori kyori, ra.surface surface, ra.monthday md "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT)>=2021 "
        "ORDER BY r.race_key").fetchall()
    hrows = con.execute("SELECT ketto_num, sire, bms FROM horses").fetchall()
    con.close()
    horse_sire = {k: (s, b) for k, s, b in hrows}
    print(f"  {len(rows):,}行")

    # 騎手力を騎手ごとに1回だけ事前計算(before_key無し=career・stable statなのでリーク極小)。
    # レースごとのDB照会(遅すぎた原因)を排除。
    jp_by_jockey = {}
    _jns = {r['jockey_name'] for r in rows if r['jockey_name']}
    for _jn in _jns:
        try:
            jp_by_jockey[_jn] = jj.jockey_power(_jn).get('jpower')
        except Exception:
            jp_by_jockey[_jn] = None
    print(f"  騎手力 {len(jp_by_jockey)}名 事前計算")
    # 補正Tも(kt,surf)ごとに1回キャッシュ
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

    # 末脚(agari順位比率)履歴・通過順履歴・着順履歴(リーク遮断)
    hist_ag = defaultdict(list)   # kt -> [(rk, agari_rank_ratio)]
    hist_c4 = defaultdict(list)   # kt -> [(rk, c4ratio)]
    hist_t3 = defaultdict(list)   # kt -> [(rk, top3 0/1)]
    hist_dt = defaultdict(list)   # kt -> [(rk, monthday, kyori)]
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
                hist_c4[x['kt']].append((rk, (sum(cs) / len(cs)) / tosu))
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
        if len(past) < minr:
            return None
        return 1.0 - sum(past) / len(past)

    def past_c4(kt, rk, n=3):
        h = hist_c4.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk][-n:]
        return (sum(past) / len(past)) if past else None

    def past_last5(kt, rk):
        h = hist_t3.get(kt)
        if not h:
            return []
        return [v for (k, v) in h if k < rk][-5:][::-1]

    def prev_run(kt, rk):
        h = hist_dt.get(kt)
        if not h:
            return None, None
        past = [(md, ky) for (k, md, ky) in h if k < rk]
        return past[-1] if past else (None, None)

    def elim_count(r):
        kt = r['kt']
        rk = r['rk']
        pmd, pdist = prev_run(kt, rk)
        prev_date = (str(r['y']) + str(pmd)) if pmd else None
        race_date = str(r['y']) + str(r['md']) if r['md'] else None
        fl = ec.compute_flags(
            last5_top3=past_last5(kt, rk),
            spurt_index=past_spurt(kt, rk), spurt_runs=len([1 for (k, v) in hist_ag.get(kt, []) if k < rk][-5:]),
            avg_c4ratio=past_c4(kt, rk),
            prev_date=prev_date, race_date=race_date,
            prev_dist=pdist, cur_dist=r['kyori'],
            zogen=r['zg'], age=r['age'],
            is_handicap=(str(r['juryo']) == '1'))
        return ec.verified_count(fl)

    base_train = {'2021-24': [0, 0], '2025': [0, 0]}

    # 集計: period -> bucket -> [t3, n]
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    _races = list(by_race.items())
    for _ri, (rk, rs) in enumerate(_races):
        if _ri % 3000 == 0:
            print(f"  ...{_ri}/{len(_races)}races", flush=True)
        yr = int(str(rk)[:4])
        if yr < 2021:
            continue
        period = 'holdout' if yr == 2025 else 'train'
        r0 = rs[0]
        surf = '芝' if '芝' in str(r0['surface']) else 'ダ'
        kyori = r0['kyori']
        jyo = str(rk)[8:10] if len(str(rk)) >= 10 else '05'
        # 33ラップ course avg
        try:
            course_v = l3.course_avg33(surf, kyori, jyo=jyo)
        except Exception:
            course_v = None

        # レース内top3(全馬): 補正T/末脚/血統/騎手(すべて事前キャッシュ利用)
        ct_vals = {}
        for r in rs:
            v = ct_fig(r['kt'], surf)
            if v is not None:
                ct_vals[r['kt']] = v
        ct_top3 = {k for k, _ in sorted(ct_vals.items(), key=lambda x: x[1])[:3]}
        sp_vals = {r['kt']: past_spurt(r['kt'], rk) for r in rs}
        sp_valid = {k: v for k, v in sp_vals.items() if v is not None}
        sp_top3 = {k for k, _ in sorted(sp_valid.items(), key=lambda x: -x[1])[:3]}
        bl_vals = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            if sire or bms:
                bl_vals[r['kt']] = bl.blood_score(sire, bms, surf, kyori)
        bl_top3 = {k for k, _ in sorted(bl_vals.items(), key=lambda x: -x[1])[:3]}
        jp_vals = {}
        for r in rs:
            jpv = jp_by_jockey.get(r['jockey_name'])
            if jpv is not None:
                jp_vals[r['kt']] = jpv
        jp_top3 = {k for k, _ in sorted(jp_vals.items(), key=lambda x: -x[1])[:3]}

        for r in rs:
            if not r['nk'] or int(r['nk']) < 6:   # 人気薄(6+)のみ
                continue
            kt = r['kt']
            t3 = 1 if r['ch'] <= 3 else 0
            # combo(6シグナル同時発火数)
            sire, bms = horse_sire.get(kt, (None, None))
            bs = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            bb = bl.lookup_bms_stats(bms, surf, kyori) if bms else None
            roi100 = bool((bs and bs.get('win_roi', 0) >= 100) or (bb and bb.get('win_roi', 0) >= 100))
            lap_fit = False
            if course_v:
                hf = l3.horse_fit33(kt, before_key=rk)
                lap_fit = l3.fit_match(hf.get('avg_lap33'), course_v['avg']) is True
            combo = sum([kt in ct_top3, kt in sp_top3, kt in bl_top3, kt in jp_top3,
                         roi100, lap_fit])
            en = elim_count(r)

            base = base_train[('2025' if period == 'holdout' else '2021-24')]
            base[0] += t3; base[1] += 1
            a = agg[period]
            a['人気薄(6+)全体'][0] += t3; a['人気薄(6+)全体'][1] += 1
            cut = en >= ec.SLOW3F_MIN_RUNS and en >= 3  # elim>=3=切る帯
            if en >= 3:
                a['切る帯(消去3+)'][0] += t3; a['切る帯(消去3+)'][1] += 1
                if combo >= 2:
                    a['★復活combo2+ (切る×combo2+)'][0] += t3; a['★復活combo2+ (切る×combo2+)'][1] += 1
                if combo >= 3:
                    a['★復活combo3+ (切る×combo3+)'][0] += t3; a['★復活combo3+ (切る×combo3+)'][1] += 1
            # 参考: 切られていない人気薄でcombo3+(本来の穴)
            if en < 3 and combo >= 3:
                a['参考:非切る×combo3+'][0] += t3; a['参考:非切る×combo3+'][1] += 1

    def show(period):
        a = agg[period]
        b = base_train['2025' if period == 'holdout' else '2021-24']
        base_rate = b[0] / b[1] if b[1] else 0
        print(f"\n=== {period} (人気薄6+ ベース複勝率 {base_rate:.1%} n={b[1]:,}) ===")
        for k in ['人気薄(6+)全体', '切る帯(消去3+)', '★復活combo2+ (切る×combo2+)',
                  '★復活combo3+ (切る×combo3+)', '参考:非切る×combo3+']:
            t3, n = a[k]
            if n < 20:
                print(f"  {k:32s} n={n:5d} (小)")
                continue
            rate = t3 / n
            se = (0.15 * 0.85 / n) ** 0.5
            z = (rate - base_rate) / se if se else 0
            print(f"  {k:32s} n={n:6d} 複勝{rate:6.1%} 基準比{(rate-base_rate)*100:+5.1f}pp z={z:+.2f}")

    show('train')
    show('holdout')
    print("\n[判定] ★復活combo3+の複勝率が『切る帯(消去3+)』を明確に上回り、かつ人気薄ベースに"
          "近い/超えるなら敗者復活の根拠あり。切る帯と大差なければ復活は妙味なし(切る=切る)。")


if __name__ == '__main__':
    main()
