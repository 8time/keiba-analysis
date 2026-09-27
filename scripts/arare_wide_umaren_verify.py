# -*- coding: utf-8 -*-
"""荒れ帯(BAゾーン)の馬連/ワイド保険券 — train→holdout 固定検証。

背景:
  netkeiba「ウマい馬券」360件(data/shapes_umai_baken_20260908_1002.jsonl)は
  全4レースが大荒れで、的中者の主武器は 馬連16/ワイド14/3連複10/単勝10/3連単8
  だった。ただし事後選択サンプルなのでエッジの証明にはならない。
  本スクリプトは「荒れ予報(BA)のレースで馬連/ワイド軸流しは、現行の見送り
  (ライブは ba_skip)や研究時代の最良形(3連複 人気3-5-8)よりマシか」を
  実配当ベースで検証する。

設計（事前固定）:
  - 対象: JRA中央・8頭以上・該当券種の配当あり
  - 分割: train <= 20241231 / holdout >= 20250101（bettype_selector系と同一）
  - 候補形は事前固定。train は参考表示、holdout が判定
  - 判定:
      A = holdout ROI >= 90% かつ 3連複3-5-8とのROI差CI下限 > -3pp かつ年別一貫
      B = baseline 以上だが条件一部未達
      C = baseline 未満 → 「荒れ=見送り」維持
  - 見送り(ROI100%相当)を覆すには ROI>=100% が必要（想定しない）

Usage: python scripts/arare_wide_umaren_verify.py
"""
import io
import os
import sqlite3
import sys
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import csv_data as cd
from core import formation_stats as fs
from core import jockey_jv as jj
from core import value_scanner as vs
from core.trio_engine import build_formation
from scripts.elim_cross_keep_top3_2026h1 import hunter_elite_top3
from scripts.elim_miss1_hunter import hunter_ranks
from scripts import hitrate_common as hc

MIN_HORSES = 8
TRAIN_END_DAY = 20241231
HOLDOUT_FROM_DAY = 20250101
UNIT = 100
BOOT_N = 2000
BOOT_SEED = 42

HORSE_COLS = [
    'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'chakujun',
    'ability_score', 'vh2_score',
    'h7_fig', 'spurt_idx', 'sire_surf_t3', 'combo', 'elim_n', 'avg_pos3',
]


def load_payouts_pair():
    """ワイド・馬連・3連複の配当。key=(kind, sorted tuple)。"""
    con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
    out = defaultdict(dict)
    for rk, bt, combo, pay in con.execute(
            "SELECT race_key, bet_type, combo, payout FROM payouts "
            "WHERE bet_type IN ('ワイド','馬連','3連複') AND payout>0"):
        c = str(combo).strip()
        if not c.isdigit():
            continue
        rk, pay = str(rk), float(pay)
        if bt in ('ワイド', '馬連') and len(c) == 4:
            out[rk][(bt, tuple(sorted((int(c[:2]), int(c[2:])))))] = pay
        elif bt == '3連複' and len(c) == 6:
            t = tuple(sorted((int(c[:2]), int(c[2:4]), int(c[4:6]))))
            out[rk][('3連複', t)] = pay
    con.close()
    return out


def v_legs(rows):
    """phase2と同一: 精鋭1,2 + 広域1 (pop>=6)。"""
    ninki = {int(r['umaban']): int(r['ninki']) for r in rows}
    _et3, scored = hunter_elite_top3(rows)
    _lab, elite, net = hunter_ranks(ninki, scored, pop_min=6)
    out = []
    for u in list(elite[:2]) + list(net[:1]):
        if u not in out:
            out.append(u)
    return out


def build_races(pall):
    h = cd.load_horses(cols=HORSE_COLS)
    r = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'vscore', 'field_size'])
    h['race_key'] = h['race_key'].astype(str)
    meta = {str(x.race_key): x for x in r.itertuples(index=False)}

    out = []
    for rk, g in h.groupby('race_key', sort=False):
        if len(g) < MIN_HORSES:
            continue
        try:
            jyo = int(float(g['jyo'].iloc[0]))
        except (TypeError, ValueError):
            continue
        if not (1 <= jyo <= 10):
            continue
        day_val = int(g['day'].iloc[0])
        m = meta.get(rk)
        vscore = float(m.vscore) if m is not None and pd.notna(m.vscore) else None
        odds_list = [float(x) for x in g['win_odds'] if float(x) > 0]
        if vscore is None:
            rv = vs.race_value_score(
                odds_list,
                {'is_handicap': bool(getattr(m, 'is_handi1', 0)),
                 'kigo': str(getattr(m, 'kigo', '') or '')},
                n_horses=len(g))
            if not rv:
                continue
            vscore = float(rv['score'])
        zone = fs.zone_code(vscore)
        if zone not in ('BA', 'C'):
            continue

        valid = g[g['chakujun'].notna() & (g['chakujun'] > 0)]
        fin = valid.sort_values('chakujun')
        top3 = tuple(int(x) for x in fin['umaban'].tolist()[:3])
        if len(top3) < 3:
            continue
        top3_set = set(top3)
        top2 = tuple(sorted(top3[:2]))
        win_trio = tuple(sorted(top3))

        ninki_ord = [int(x) for x in g.sort_values('ninki')['umaban']]
        rank_ord = [int(x) for x in g.sort_values('ability_score', ascending=True)['umaban']]
        if len(ninki_ord) < 8 or len(rank_ord) < 7:
            continue
        recs = g.to_dict('records')
        legs = v_legs(recs)

        pm = pall.get(rk)
        if not pm:
            continue

        # ---- 候補形の構築と採点 ----
        bets = {}

        def add_pair_bet(name, kind, axis, opps):
            tix = {tuple(sorted((axis, o))) for o in opps if o != axis}
            if not tix:
                return
            cost = len(tix) * UNIT
            ret = 0.0
            hit = 0
            for t in tix:
                if kind == 'ワイド':
                    won = t[0] in top3_set and t[1] in top3_set
                else:
                    won = t == top2
                if won:
                    p = pm.get((kind, t))
                    if p:
                        ret += p
                        hit = 1
            bets[name] = dict(cost=cost, ret=ret, hit=hit, tc=len(tix))

        rank1 = rank_ord[0]
        pop1 = ninki_ord[0]
        add_pair_bet('wide_rank1_rank26', 'ワイド', rank1, rank_ord[1:6])
        add_pair_bet('wide_pop1_pop26', 'ワイド', pop1, ninki_ord[1:6])
        add_pair_bet('umaren_rank1_rank26', '馬連', rank1, rank_ord[1:6])
        add_pair_bet('umaren_pop1_pop27', '馬連', pop1, ninki_ord[1:7])
        if legs:
            add_pair_bet('wide_vh1_pop15', 'ワイド', legs[0], ninki_ord[:5])
            add_pair_bet('umaren_vh1_pop15', '馬連', legs[0], ninki_ord[:5])
        if len(legs) >= 3:
            tix = {tuple(sorted(p)) for p in
                   ((legs[0], legs[1]), (legs[0], legs[2]), (legs[1], legs[2]))}
            cost = len(tix) * UNIT
            ret = sum(pm.get(('ワイド', t), 0.0)
                      for t in tix if t[0] in top3_set and t[1] in top3_set)
            bets['wide_vhbox3'] = dict(cost=cost, ret=ret, hit=int(ret > 0), tc=len(tix))

        # baseline: 3連複 人気3-5-8
        trio_tix = set(build_formation(ninki_ord[:3], ninki_ord[:5], ninki_ord[:8]))
        cost = len(trio_tix) * UNIT
        ret = pm.get(('3連複', win_trio), 0.0) if win_trio in trio_tix else 0.0
        bets['trio_pop358'] = dict(cost=cost, ret=ret, hit=int(ret > 0), tc=len(trio_tix))

        out.append(dict(
            rk=rk, day=day_val, year=day_val // 10000,
            period='train' if day_val <= TRAIN_END_DAY else 'holdout',
            zone=zone, vscore=vscore, n_horses=len(g),
            vh_n=len(legs), bets=bets,
        ))
    return out


def summarise_bet(rows, key):
    recs = []
    for r in rows:
        b = r['bets'].get(key)
        if not b or b['cost'] == 0:
            continue
        recs.append(dict(day=r['day'], year=r['year'], rk=r['rk'],
                         cost=b['cost'], ret=b['ret'], hit=b['hit'], tc=b['tc']))
    return hc.summarise(recs), recs


def block_roi_diff(recs_base, recs_cand):
    """同一レースペアでのROI差ブートストラップ（日ブロック）。"""
    bm = {r['rk']: r for r in recs_base}
    pairs = [(bm[r['rk']], r) for r in recs_cand if r['rk'] in bm]
    if len(pairs) < 30:
        return None, None, 0
    rng = np.random.default_rng(BOOT_SEED)
    cb = np.array([p[0]['cost'] for p in pairs], dtype=np.float64)
    rb = np.array([p[0]['ret'] for p in pairs], dtype=np.float64)
    cc = np.array([p[1]['cost'] for p in pairs], dtype=np.float64)
    rc = np.array([p[1]['ret'] for p in pairs], dtype=np.float64)
    days = np.array([p[1]['day'] for p in pairs])
    uniq, inv = np.unique(days, return_inverse=True)
    blocks = [np.where(inv == i)[0] for i in range(len(uniq))]
    diffs = []
    for _ in range(BOOT_N):
        picks = rng.integers(0, len(blocks), size=len(blocks))
        idx = np.concatenate([blocks[p] for p in picks])
        sb, sc = cb[idx].sum(), cc[idx].sum()
        roi_b = rb[idx].sum() / sb * 100 if sb else 0
        roi_c = rc[idx].sum() / sc * 100 if sc else 0
        diffs.append(roi_c - roi_b)
    d = np.array(diffs)
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)), len(pairs)


def year_consistent(s_cand, s_base, years=(2025, 2026), tol_pp=5.0):
    det = []
    ok_all = True
    for y in years:
        rc = s_cand['year_roi'].get(y)
        rb = s_base['year_roi'].get(y)
        if rc is None or rb is None:
            det.append((y, 'データなし', False))
            ok_all = False
            continue
        ok = rc >= rb - tol_pp
        det.append((y, f'候補{rc:.0f}% vs 基準{rb:.0f}%', ok))
        ok_all = ok_all and ok
    return ok_all, det


def classify(s_ho, s_base, diff_ci, y_ok):
    if s_ho['n'] == 0:
        return 'C', 'holdout 0R'
    roi_d = s_ho['roi'] - s_base['roi']
    if s_ho['roi'] >= 100.0:
        return 'A+', f"holdout ROI {s_ho['roi']:.1f}%（見送り覆し級・要再検証）"
    if roi_d < 0:
        return 'C', f'holdout ROI {roi_d:+.1f}pp（3連複3-5-8未満）→ 見送り維持'
    if s_ho['roi'] >= 90.0 and diff_ci[0] is not None and diff_ci[0] > -3.0 and y_ok:
        return 'A', f"holdout ROI {s_ho['roi']:.1f}%・対基準 {roi_d:+.1f}pp・年別一貫"
    return 'B', f"baseline以上だが条件一部未達（ROI {s_ho['roi']:.1f}%・差CI {diff_ci}）"


def print_line(name, s, base=None):
    if s['n'] == 0:
        print(f'  {name:22s}: 0R')
        return
    lo, hi = hc.block_ci_roi(s['recs'])
    d = f" (対基準{s['roi']-base['roi']:+.1f}pp)" if base else ''
    tri = sum(1 for r in s['recs'] if r['hit'] and r['ret'] < r['cost'])
    yrs = ' '.join(f"{y}:{v:.0f}%" for y, v in sorted(s['year_roi'].items()))
    print(f"  {name:22s} {s['n']:>5}R 的中{s['hit_rate']:5.1f}% ROI{s['roi']:6.1f}%{d}"
          f" CI[{lo:.0f}-{hi:.0f}] 連敗{s['max_losing_streak']:>3}"
          f" 平均{s['avg_pts']:.1f}点 トリガミ{tri} 年:{yrs}")


CANDIDATES = [
    'wide_rank1_rank26', 'wide_vh1_pop15', 'wide_vhbox3',
    'umaren_rank1_rank26', 'umaren_vh1_pop15', 'wide_pop1_pop26',
]
BASELINE = 'trio_pop358'
MARKET_CTRL = 'umaren_pop1_pop27'


def run_zone(rows_all, zone, pall):
    rows = [r for r in rows_all if r['zone'] == zone]
    train = [r for r in rows if r['period'] == 'train']
    hold = [r for r in rows if r['period'] == 'holdout']
    print('\n' + '=' * 80)
    print(f'■ ゾーン {zone}  train={len(train):,}R / holdout={len(hold):,}R')
    print('=' * 80)

    s_base_tr, r_base_tr = summarise_bet(train, BASELINE)
    s_base_ho, r_base_ho = summarise_bet(hold, BASELINE)

    print('--- train（参考・形状は事前固定）---')
    print_line(BASELINE + ' [基準]', s_base_tr)
    for k in CANDIDATES + [MARKET_CTRL]:
        s_tr, _ = summarise_bet(train, k)
        print_line(k, s_tr, s_base_tr)

    print('--- holdout（判定）---')
    print_line(BASELINE + ' [基準]', s_base_ho)
    results = {}
    for k in CANDIDATES + [MARKET_CTRL]:
        s_ho, r_ho = summarise_bet(hold, k)
        lo, hi, npair = block_roi_diff(r_base_ho, r_ho)
        y_ok, y_det = year_consistent(s_ho, s_base_ho)
        grade, reason = classify(s_ho, s_base_ho, (lo, hi), y_ok)
        results[k] = dict(grade=grade, reason=reason, s=s_ho,
                          diff_ci=(lo, hi), npair=npair, y_det=y_det)
        ci_txt = f'差CI[{lo:+.1f},{hi:+.1f}]' if lo is not None else '差CI n/a'
        print_line(k, s_ho, s_base_ho)
        print(f'      {ci_txt} (paired n={npair}) 年別一貫={y_ok} → 判定 {grade}: {reason}')
    return results, s_base_ho


def main():
    print('荒れ帯 馬連/ワイド保険券 — train→holdout 固定検証')
    print('候補形は事前固定（netkeiba360件の観察由来）。train=参考 / holdout=判定。')
    print('読込...', flush=True)
    pall = load_payouts_pair()
    rows = build_races(pall)
    print(f'対象 {len(rows):,}R（BA+C・8頭以上・配当あり）')

    res_ba, base_ba = run_zone(rows, 'BA', pall)
    res_c, base_c = run_zone(rows, 'C', pall)

    print('\n' + '=' * 80)
    print('■ 最終サマリ（holdout）')
    print('=' * 80)
    print(f"BA 基準 3連複3-5-8: ROI {base_ba['roi']:.1f}% / 的中 {base_ba['hit_rate']:.1f}%")
    for k, v in res_ba.items():
        print(f"  BA {k:22s} {v['grade']:2s} ROI {v['s']['roi']:6.1f}%  {v['reason']}")
    print(f"C 基準 3連複3-5-8: ROI {base_c['roi']:.1f}%（参考: Rule B は87.7%）")
    for k, v in res_c.items():
        print(f"  C  {k:22s} {v['grade']:2s} ROI {v['s']['roi']:6.1f}%  {v['reason']}")

    # ---- memo ----
    lines = [
        '## 背景',
        'netkeiba ウマい馬券360件（全4R大荒れ・的中ショーケース）で的中者の主武器は',
        '馬連16/ワイド14/3連複10/単勝10/3連単8 だった。事後選択サンプルのため',
        'エッジの証明にはならず、本検証で事前ルールとして実配当 holdout にかけた。',
        '',
        '## 設計',
        '- 対象: JRA中央 8頭以上 / zone BA(主)・C(副次)',
        '- 分割: train ≤20241231（参考）/ holdout ≥20250101（判定）',
        '- 候補: ワイド/馬連 × 軸(Rank1・VH穴1位・人気1) + VH穴3頭ボックス',
        '- 基準: 3連複 人気3-5-8（研究時代のBA最良形）/ 馬連 人気1×2-7（市場対照）',
        '- 判定: A=holdout ROI≥90% かつ対基準CI下限>-3pp かつ年別一貫',
        '',
        f"## BA holdout 基準: 3連複3-5-8 ROI {base_ba['roi']:.1f}% 的中 {base_ba['hit_rate']:.1f}%",
        '',
    ]
    for k, v in res_ba.items():
        s = v['s']
        lo, hi = v['diff_ci']
        ci = f'対基準CI[{lo:+.1f},{hi:+.1f}]' if lo is not None else '対基準CI n/a'
        lines.append(
            f"- **{k}** → {v['grade']}: holdout {s['n']}R 的中{s['hit_rate']:.1f}% "
            f"ROI{s['roi']:.1f}% {ci} 連敗{s['max_losing_streak']} — {v['reason']}")
    lines += ['', f"## C holdout 基準: 3連複3-5-8 ROI {base_c['roi']:.1f}%（参考）", '']
    for k, v in res_c.items():
        s = v['s']
        lines.append(
            f"- {k} → {v['grade']}: 的中{s['hit_rate']:.1f}% ROI{s['roi']:.1f}%")
    lines += ['', '## 再現', '```', 'python scripts/arare_wide_umaren_verify.py', '```']
    memo = os.path.join(ROOT, 'repo', 'memory', 'verified_arare_wide_umaren.md')
    hc.write_memo(memo, 'verified_arare_wide_umaren',
                  '荒れ帯(BA)の馬連/ワイド保険券 holdout 検証', lines)
    print(f'\n→ {memo}')


if __name__ == '__main__':
    main()
