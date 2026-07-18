# -*- coding: utf-8 -*-
"""3連単エンジンの『穴の人気上限 ana_hi=12』を実配当で検証する。

発端(実査 202603020611・荒れ確率78%・●大穴): 結果11-6-9。3連複エンジンは2軸[11,9]で的中
(14点中6位/combo流しなら7点中4位)。しかし3連単は全336点を生成しても11-6-9が301位で圏外。
原因の1つが **ana_hi=12**: 「穴」とみなす人気の上限が12番人気で固定されており、
実3着の9番(15番人気・🧩combo2・🔵補正T上位)が穴として一切扱われない(ボーナス0・himo優先度0)。
同レースでは1番(14番人気・🧩combo4・🎯精鋭)・8番(13番人気・combo2)も同様に穴から漏れていた。
荒れ確率78%・本命不在(●大穴)判定のレースなのに、である。

★この検証がクリーンな理由: ana_hi を広げても **3着列の頭数(n_third)は変わらない**。
  「9枠に誰が入るか」が入れ替わるだけで **点数=コストは完全に同一**。
  よって『的中率とROIの純粋な比較』ができる(点数が増えて当たりやすくなった、という交絡がない)。

再現するもの(core/trio_engine.recommend_trifecta のプール構築と同一):
  first  = Rank上位 n_first ＋ put_ana_head(荒れ帯のみ: combo最大の穴を1頭だけ1着に許容)
  second = first ∪ Rank順で n_second まで
  third  = second ∪ himo_ranked(穴のcombo優先→シグナル有→スコア順) で n_third まで
  荒れ帯(_BAND_FORMATION['arare']) = (n_first=3, n_second=5, n_third=9)

比較: ana_hi=12(現行) vs 16 vs 出走頭数(=上限なし)。
評価: 実際の3連単配当(payouts表)で 的中率 / 回収率 / ¥200k頭打ちの頑健ROI。
      train(≤2024) / holdout(2025) の両方で改善しなければ採用しない。
"""
import os
import random
import sqlite3
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import csv_data as cd
from core import jockey_jv as jj
from core import trio_engine as te
from core import value_scanner as vs

MIN_HORSES = 8
CAP = 200000.0
ANA_LO = 6
ARARE_TH = 0.60            # 荒れ帯(_BAND_FORMATIONのarare相当)
N_FIRST, N_SECOND, N_THIRD, _SUGG, PUT_ANA_HEAD = te._BAND_FORMATION['arare']
ANA_HI_VARIANTS = ('12(現行)', '16', '無制限')


def load_trifecta_payouts():
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = {}
    for rk, combo, pay in con.execute(
            "SELECT race_key, combo, payout FROM payouts WHERE bet_type='3連単'"):
        c = str(combo)
        if len(c) == 6 and c.isdigit():
            out[rk] = ((int(c[:2]), int(c[2:4]), int(c[4:6])), float(pay))
    con.close()
    return out


def _fill(pool, source, limit):
    for u in source:
        if len(pool) >= limit:
            break
        if u not in pool:
            pool.append(u)
    return pool


def build_pools(rank_umas, combo_of, ninki_of, ana_hi):
    """エンジンと同一のプール構築。ana_hi だけを可変にする。"""
    ana_set = {u for u in rank_umas
               if ninki_of.get(u) and ANA_LO <= ninki_of[u] <= ana_hi}
    first = _fill([], rank_umas, N_FIRST)
    if PUT_ANA_HEAD:
        # 荒れ帯: combo最大の穴を1頭だけ1着に許容(エンジンと同じく1頭)
        for u in sorted(ana_set, key=lambda x: -combo_of.get(x, 0))[:1]:
            if u not in first:
                first.append(u)
    second = _fill(list(first), rank_umas, N_SECOND)
    # ヒモ順: 穴のcombo優先 → 穴かどうか → Rank順(エンジンのhimo_rankedと同型)
    himo = sorted(rank_umas,
                  key=lambda u: (-(combo_of.get(u, 0) if u in ana_set else 0),
                                 -(1 if u in ana_set else 0),
                                 rank_umas.index(u)))
    third = _fill(list(second), himo, N_THIRD)
    return first, second, third


def points(c1, c2, c3):
    n = 0
    for a in c1:
        for b in c2:
            if b == a:
                continue
            for c in c3:
                if c not in (a, b):
                    n += 1
    return n


def main():
    print('3連単 実配当を読み込み...')
    payout = load_trifecta_payouts()
    print(f'  {len(payout):,}レース')
    df = cd.load_horses(cols=['race_key', 'day', 'ninki', 'win_odds', 'ability_score',
                              'combo', 'umaban', 'is_handi1'])
    df = df[df['umaban'].notna() & df['ninki'].notna()]
    by_race = defaultdict(list)
    for r in df.itertuples(index=False):
        by_race[str(r.race_key)].append(r)

    # agg[period][ranksrc][ana_hi] = [cost, ret, hits, pts, n, ret_capped]
    agg = {p: {rs: {v: [0.0, 0.0, 0, 0, 0, 0.0] for v in ANA_HI_VARIANTS}
               for rs in ('ninki', 'ability')}
           for p in ('train', 'holdout')}
    boot = defaultdict(list)
    n_races = {'train': 0, 'holdout': 0}

    for rk, rows in by_race.items():
        if rk not in payout or len(rows) < MIN_HORSES:
            continue
        y = rows[0].day // 10000
        period = 'train' if y <= cd.TRAIN_END else ('holdout' if y == cd.HOLDOUT_YEAR else None)
        if period is None:
            continue
        odds_list = [r.win_odds for r in rows if r.win_odds and r.win_odds > 0]
        if len(odds_list) < 3:
            continue
        ap = vs.arare_prob(odds_list, {'is_handicap': bool(rows[0].is_handi1)}, len(rows))
        if ap is None or ap < ARARE_TH:      # ★荒れ帯のみ(ana_hiが効くのはここ)
            continue
        n_races[period] += 1
        win, pay = payout[rk]
        field = len(rows)
        def _i(v, d=0):
            try:
                f = float(v)
                return d if f != f else int(f)     # NaN → d
            except (TypeError, ValueError):
                return d
        combo_of = {int(r.umaban): _i(r.combo) for r in rows}
        ninki_of = {int(r.umaban): _i(r.ninki) for r in rows}

        for rs in ('ninki', 'ability'):
            if rs == 'ninki':
                ranked = sorted(rows, key=lambda x: x.ninki)
            else:
                ranked = sorted(rows, key=lambda x: (x.ability_score
                                                     if x.ability_score is not None else 1e9))
            rank_umas = [int(r.umaban) for r in ranked]
            for v in ANA_HI_VARIANTS:
                ah = 12 if v.startswith('12') else (16 if v == '16' else field)
                c1, c2, c3 = build_pools(rank_umas, combo_of, ninki_of, ah)
                pts = points(c1, c2, c3)
                if pts <= 0:
                    continue
                h = (win[0] in c1) and (win[1] in c2) and (win[2] in c3)
                a = agg[period][rs][v]
                a[0] += pts * 100
                a[1] += pay if h else 0.0
                a[2] += 1 if h else 0
                a[3] += pts
                a[4] += 1
                a[5] += min(pay, CAP) if h else 0.0
                if rs == 'ninki':
                    boot[v].append((pts * 100, pay if h else 0.0))

    print(f"\n荒れ帯(荒れ確率≥{ARARE_TH:.0%})のレース数: "
          f"train {n_races['train']:,} / holdout {n_races['holdout']:,}")
    print(f"フォーメーション: 1着{N_FIRST}頭(+穴頭1) / 2着{N_SECOND}頭 / 3着{N_THIRD}頭"
          f"  ※ana_hiを変えても頭数=点数は不変")

    for period in ('train', 'holdout'):
        print(f"\n{'='*76}\n=== {period} ===")
        print(f"  {'Rank源':8s} {'穴の人気上限':12s} {'参加':>6s} {'的中率':>7s} {'点数':>5s} "
              f"{'回収率':>8s} {'頑健ROI':>8s}")
        for rs in ('ninki', 'ability'):
            for v in ANA_HI_VARIANTS:
                cost, ret, hits, pts, n, retc = agg[period][rs][v]
                if n < 30:
                    continue
                print(f"  {rs:8s} {v:12s} {n:6d} {hits/n:6.2%} {pts/n:5.1f} "
                      f"{ret/cost if cost else 0:7.1%} {retc/cost if cost else 0:7.1%}")

    # bootstrap: 現行(12) vs 無制限 の raw ROI 分布(全年プール・ninki軸)
    random.seed(42)
    print(f"\n{'='*76}\n=== bootstrap(1000回・ninki軸・荒れ帯) raw ROI ===")
    print("  点数=コストは同一なので、差はそのまま『どの馬を3着列に入れたか』の差。")
    for v in ANA_HI_VARIANTS:
        recs = boot.get(v) or []
        if len(recs) < 100:
            continue
        rois = []
        m = len(recs)
        for _ in range(1000):
            samp = [recs[random.randrange(m)] for _ in range(m)]
            c = sum(x[0] for x in samp)
            r = sum(x[1] for x in samp)
            rois.append(r / c if c else 0)
        rois.sort()
        print(f"  穴の人気上限 {v:8s} n={m:5d}  ROI中央 {rois[500]:6.1%}  "
              f"90%CI [{rois[50]:6.1%}, {rois[950]:6.1%}]")

    print("\n[判定] train/holdoutの両方で的中率・ROIが改善して初めて採用。"
          "点数は不変なので、改善すれば純粋に『3着列の馬選びが良くなった』ことを意味する。")


if __name__ == '__main__':
    main()
