# -*- coding: utf-8 -*-
"""ユーザーの3仮説を「とある1日・3会場」だけでラフに試算する(本格検証の前の当たり感チェック)。
2026-06-21(函館02/東京05/阪神09・各12R=36R)。jravan.dbの実データ+netkeiba archived shutubaページ。

仮説①: 展開MAP(アプリ側の習性)×netkeiba AI展開予測の重複馬(🏆)だけを3連複BOXで買う
仮説②: 消去エンジン残り馬を単勝期待値(オッズ帯実測)順に、軸馬を含めた6頭で軸から馬連流し
仮説③: ①と②の重複馬でBOX買い

注意: これは1日36レースの試算に過ぎず、統計的に意味のある検証ではない(本格検証はjravan.db
の複数年データで行うべき)。アプリの実際の消去フィルター(半分消去+穴1頭救出+危険人気馬検知)は
簡略化して代用(verified_countの中央値以下を残す)。展開MAPのアプリ側も簡略化
(習性4角位置比率をfront_frac/back_frac=0.40/0.35で前/中/後に分類)。
"""
import os
import sys
import sqlite3
from collections import defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core import elim_cross as ec
from core import axis_selector as axs
from core import ai_tenkai as at

DB = jj.JV_DB_PATH
DATE = '20260621'
JYOS = ('02', '05', '09')


def market_ev_table(con):
    """オッズ帯別 実測 勝率(2022-2025)。app.pyの📊残った馬の期待値と同じ較正。"""
    edges = [1.5, 2.5, 4.0, 7.0, 15.0, 30.0, 60.0]

    def band(o):
        for i, e in enumerate(edges):
            if o <= e:
                return i
        return len(edges)
    bk = {}
    for o, c in con.execute(
        "SELECT win_odds, chakujun FROM results "
        "WHERE year IN ('2022','2023','2024','2025') AND chakujun>0 AND win_odds>0"):
        b = band(o / 10.0)
        d = bk.setdefault(b, [0, 0])
        d[0] += 1
        d[1] += 1 if c == 1 else 0
    return {b: (d[1] / d[0]) for b, d in bk.items()}, edges


def ev_band_of(o, edges):
    for i, e in enumerate(edges):
        if o <= e:
            return i
    return len(edges)


def combo_str(nums):
    return ''.join(f"{n:02d}" for n in sorted(nums))


def payout_lookup(payouts, bet_type, nums):
    key = combo_str(nums)
    return payouts.get((bet_type, key))


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()

    ev_table, edges = market_ev_table(con)

    race_keys = [r[0] for r in cur.execute(
        f"SELECT DISTINCT race_key FROM results WHERE substr(race_key,1,8)=? "
        f"AND jyo IN ({','.join('?'*len(JYOS))}) ORDER BY race_key", (DATE,) + JYOS)]
    print(f"対象: {DATE} 3会場 {len(race_keys)}レース\n")

    rows = cur.execute(
        f"SELECT r.race_key, r.umaban, r.ketto_num, r.chakujun, r.ninki, r.win_odds, "
        f"r.zogen, r.age, r.futan, r.corner1,r.corner2,r.corner3,r.corner4, "
        f"ra.surface, ra.kyori, ra.juryo, ra.shusso_tosu, r.jyo, r.bamei "
        f"FROM results r JOIN races ra ON ra.race_key=r.race_key "
        f"WHERE r.race_key IN ({','.join('?'*len(race_keys))})", race_keys).fetchall()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r[0]].append(r)

    payouts = {}
    for rk, bt, combo, pay, pop in cur.execute(
        f"SELECT race_key, bet_type, combo, payout, pop FROM payouts "
        f"WHERE race_key IN ({','.join('?'*len(race_keys))})", race_keys):
        payouts.setdefault(rk, {})[(bt, combo)] = pay
    con.close()

    # 集計用
    res1 = {'cost': 0, 'ret': 0, 'hit': 0, 'races': 0, 'skip': 0}
    res2 = {'cost': 0, 'ret': 0, 'hit': 0, 'races': 0, 'skip': 0}
    res3 = {'cost': 0, 'ret': 0, 'hit': 0, 'races': 0, 'skip': 0}

    for rk in race_keys:
        rs = by_race.get(rk, [])
        if len(rs) < 5:
            continue
        surf = str(rs[0][13])
        kyori = rs[0][14]
        juryo = str(rs[0][15])
        is_handi = (juryo == '4')
        jyo = rs[0][17]
        netkeiba_id = rk[:4] + rk[8:]  # 年4+場2+回2+日2+R2

        horses = []
        for (rk2, um, kt, ch, nk, wo, zg, age, futan, c1, c2, c3, c4, s, ky, jy, tosu, jyo2, bamei) in rs:
            if not wo or wo <= 0 or not nk:
                continue
            odds = wo / 10.0
            es = jj.horse_elim_stats(kt, before_key=rk)
            ctx = jj.horse_recent_context(kt, before_key=rk)
            pwm = jj.horse_prev_win_margin(kt, before_key=rk)
            flags = ec.compute_flags(
                last5_top3=es.get('last5_top3'), spurt_index=(ctx or {}).get('spurt_index'),
                spurt_runs=(ctx or {}).get('spurt_runs', 0), avg_c4ratio=es.get('avg_c4ratio'),
                prev_date=(ctx or {}).get('prev_date'), race_date=rk[:8],
                prev_dist=(ctx or {}).get('prev_dist'), cur_dist=kyori,
                zogen=zg, age=age, is_handicap=is_handi, futan=futan)
            vc = ec.verified_count(flags)
            cs = [c for c in (c1, c2, c3, c4) if c and c > 0]
            habit_c4 = (sum(cs) / len(cs)) / tosu if (cs and tosu) else None  # 0-1比率(高=後方)
            horses.append({
                'um': um, 'kt': kt, 'ch': ch, 'nk': nk, 'odds': odds, 'vc': vc,
                'habit_c4': habit_c4,
                'ev_win': odds * ev_table.get(ev_band_of(odds, edges), 0.06),
                'name': bamei,
            })
        if len(horses) < 5:
            continue

        # 軸候補(◎〇▲・最大3頭)
        is_nar = int(jyo) > 10
        ax_horses = [{'name': h['name'], 'pop': h['nk'], 'odds': h['odds']} for h in horses]
        axm = (axs.axis_marks_nar(ax_horses) if is_nar else axs.axis_marks(ax_horses))
        axis_um = None
        for h in horses:
            if (axm.get(h['name']) or {}).get('mark') == '◎':
                axis_um = h['um']
                break

        actual_top3 = {h['um'] for h in horses if h['ch'] and h['ch'] <= 3}

        # ── 仮説① 展開一致🏆 ──
        app_band = {}
        vals = [(h['um'], h['habit_c4']) for h in horses if h['habit_c4'] is not None]
        if vals:
            vals.sort(key=lambda t: t[1])  # 昇順=前方(比率小)→後方
            n = len(vals)
            nf, nb = max(1, round(n * 0.40)), max(1, round(n * 0.35))
            for i, (u, _) in enumerate(vals):
                app_band[u] = '前' if i < nf else ('後' if i >= n - nb else '中')
        try:
            nk_band = at.corner4_bands(netkeiba_id)
        except Exception:
            nk_band = {}
        icons = at.agreement_icons(nk_band, app_band) if nk_band else {}
        trophy_set = {u for u, ic in icons.items() if ic == '🏆'}

        res1['races'] += 1
        if len(trophy_set) >= 3:
            combos = list(combinations(sorted(trophy_set), 3))
            cost = len(combos) * 100
            ret = 0
            for c in combos:
                p = payout_lookup(payouts.get(rk, {}), '3連複', list(c))
                if p:
                    ret += p
            res1['cost'] += cost; res1['ret'] += ret
            if ret > 0:
                res1['hit'] += 1
        else:
            res1['skip'] += 1

        # ── 仮説② 消去残り馬EV順6頭・軸流し ──
        med = sorted(h['vc'] for h in horses)[len(horses) // 2]
        survivors = [h for h in horses if h['vc'] <= med]
        survivors_sorted = sorted(survivors, key=lambda h: -h['ev_win'])
        six = []
        if axis_um is not None:
            six.append(axis_um)
        for h in survivors_sorted:
            if h['um'] in six:
                continue
            six.append(h['um'])
            if len(six) >= 6:
                break
        res2['races'] += 1
        if axis_um is not None and len(six) >= 2:
            others = [u for u in six if u != axis_um]
            cost = len(others) * 100
            ret = 0
            for o in others:
                p = payout_lookup(payouts.get(rk, {}), '馬連', [axis_um, o])
                if p:
                    ret += p
            res2['cost'] += cost; res2['ret'] += ret
            if ret > 0:
                res2['hit'] += 1
        else:
            res2['skip'] += 1

        # ── 仮説③ ①∩②の重複 ──
        overlap = trophy_set & set(six)
        res3['races'] += 1
        if len(overlap) >= 3:
            combos = list(combinations(sorted(overlap), 3))
            cost = len(combos) * 100
            ret = 0
            for c in combos:
                p = payout_lookup(payouts.get(rk, {}), '3連複', list(c))
                if p:
                    ret += p
            res3['cost'] += cost; res3['ret'] += ret
            if ret > 0:
                res3['hit'] += 1
        else:
            res3['skip'] += 1

    def report(name, r):
        n = r['races'] - r['skip']
        roi = (r['ret'] / r['cost'] * 100) if r['cost'] else 0
        print(f"【{name}】対象{r['races']}R中 賭けた{n}R(見送り{r['skip']}R) "
              f"的中{r['hit']}R 投資{r['cost']}円 回収{r['ret']}円 回収率{roi:.1f}%")

    report('①展開一致🏆 3連複BOX', res1)
    report('②消去残りEV6頭 軸流し馬連', res2)
    report('③①∩②の重複 3連複BOX', res3)
    print("\n※1日36レースの試算。統計的な結論には使えない(本格検証はjravan.db複数年で別途実施)。")


if __name__ == '__main__':
    main()
