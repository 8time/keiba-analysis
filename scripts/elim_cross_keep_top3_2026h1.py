# -*- coding: utf-8 -*-
"""消去クロステーブルで推奨頭数まで上から消し、敗者復活を足したあと
3着3頭が全部残るか。対象=2026年1〜6月。

再現(アプリの操作):
  1. フラグ数が多い順（同数なら人気が薄い順）に並べる
  2. 上から消して 推奨頭数 まで残す
  3. 消した馬のうち 🧩combo3+ または 🎯精鋭top3 を敗者復活
     ※復活はクロスで切った馬だけ。📊で切った馬は復活しない。

SRAその場の旗(調教C・戦闘力下位・展開MAP・Stress・netkeiba照合・騎手弱材料)は
CSVに無いので含めない。並びは完全一致ではない。

Usage: python scripts/elim_cross_keep_top3_2026h1.py
"""
import os
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import elim_cross as ec
from core import narrow_n as nn
from core import value_hunter as vh
from core import value_scanner as vs
from scripts import csv_data as cd

DAY0, DAY1 = 20260101, 20260630


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def flag_counts(rows):
    """レース内のフラグ数。CSVで再現できるものだけ。rows=dictのlist。"""
    n = len(rows)
    ninki = {int(r['umaban']): int(r['ninki']) for r in rows}

    horses_bc = [{'um': int(r['umaban']),
                  'spurt': _num(r.get('spurt_idx')),
                  'c4': _num(r.get('pos_ratio3'))} for r in rows]
    bc = ec.bottom_both_umabans(horses_bc)

    mw_in = []
    for r in rows:
        u = int(r['umaban'])
        sp = _num(r.get('spurt_idx'))
        pos = _num(r.get('pos_ratio3'))
        form = _num(r.get('avg_chaku5'))
        ct = _num(r.get('h7_fig'))
        mw_in.append({'um': u, 'cols': {
            'spurt': (-sp if sp is not None else None),
            'pos': pos,
            'form': form,
            'ctime': ct,
        }})
    mw = ec.multiweak_umabans(mw_in)

    pop_k = max(1, int(n * 0.34))
    pl = ec.worst_k_umabans(
        [{'um': int(r['umaban']), 'pop': int(r['ninki'])} for r in rows],
        'pop', k=pop_k, min_field=1)

    jl = ec.worst_k_umabans(
        [{'um': int(r['umaban']), 'j': _num(r.get('jockey_form_t3'))} for r in rows],
        'j', higher_worse=False)

    a3_k = max(1, int(n * 0.39))
    a3 = ec.worst_k_umabans(
        [{'um': int(r['umaban']), 'sp': _num(r.get('spurt_idx'))} for r in rows],
        'sp', k=a3_k, min_field=1, higher_worse=False)

    # ltr_low: 実力スコア下位50%(小さいほど強い → 大きい側が下位)
    ab = [(int(r['umaban']), _num(r.get('ability_score'))) for r in rows]
    ab_ok = [(u, v) for u, v in ab if v is not None]
    ltr_low = set()
    if len(ab_ok) >= 2:
        ab_ok.sort(key=lambda x: x[1])
        cut = max(1, len(ab_ok) // 2)
        ltr_low = {u for u, _ in ab_ok[cut:]}

    cnt = {}
    for r in rows:
        u = int(r['umaban'])
        n_flag = int(_num(r.get('elim_n')) or 0)
        # elim_n は slow3f(末脚≤0.30)を含むが、ライブのフラグ数は agari3f(相対下位)を使う
        sp = _num(r.get('spurt_idx'))
        if sp is not None and sp <= 0.30:
            n_flag = max(0, n_flag - 1)
        extra = 0
        if u in bc:
            extra += 1
        if u in mw:
            extra += 1
        if u in pl:
            extra += 1
        if u in jl:
            extra += 1
        if u in a3:
            extra += 1
        if u in ltr_low:
            extra += 1
        cnt[u] = n_flag + extra
    return cnt, ninki


def hunter_elite_top3(rows):
    odds, ct, sp, bl, combo, elim, front = {}, {}, {}, {}, {}, {}, set()
    for r in rows:
        u = int(r['umaban'])
        o = _num(r.get('win_odds'))
        if o and o > 0:
            odds[u] = o
        cf = _num(r.get('h7_fig'))
        if cf is not None:
            ct[u] = cf
        si = _num(r.get('spurt_idx'))
        if si is not None:
            sp[u] = si
        sf = _num(r.get('sire_surf_t3'))
        if sf is not None:
            bl[u] = sf
        combo[u] = int(_num(r.get('combo')) or 0)
        elim[u] = int(_num(r.get('elim_n')) or 0)
        ap = _num(r.get('avg_pos3'))
        if ap is not None and ap <= 3:
            front.add(u)
    scored = vh.score_race(ct, sp, bl, combo, elim, odds, front)
    elite = {u for u, d in scored.items() if d.get('tier') == '🎯精鋭'}
    if not elite:
        return set(), scored
    top3 = set(sorted(elite, key=lambda u: -scored[u]['score'])[:3])
    return top3, scored


def add_rklow_vh(flags, n, edf_rank, scored):
    """ライブと同じ: 📊スコア順の下位56% かつ ハンター圏外。"""
    if n < 6 or not edf_rank:
        return
    cut = n - max(1, int(n * 0.56))
    have = [(u, rk) for u, rk in edf_rank.items() if rk is not None]
    if len(have) < 6:
        return
    have.sort(key=lambda x: x[1])
    for i, (u, _) in enumerate(have):
        if i >= cut and not str((scored.get(u) or {}).get('tier') or '').strip():
            flags[u] = flags.get(u, 0) + 1


def edf_rank_and_surv(rows, border=3):
    """📊 score ≈ -人気 +1.5(末脚救出) -1.5(休み/距離/高齢)。
    半分残し＋ボーダー残し(既定3)。戻り: (rank_by_um 1=上位, survivor_set)
    """
    n = len(rows)
    sp_ok = [(int(r['umaban']), _num(r.get('spurt_idx'))) for r in rows]
    sp_ok = [(u, v) for u, v in sp_ok if v is not None]
    sp_ok.sort(key=lambda x: -x[1])
    spurt_top3 = {u for u, _ in sp_ok[:3]}

    scored = []
    for r in rows:
        u = int(r['umaban'])
        pop = int(r['ninki'])
        pos = 1.5 if (u in spurt_top3 and pop >= 6) else 0.0
        neg = 0.0
        ds = _num(r.get('days_since'))
        if ds is not None and ds >= 180:
            neg += 1.5
        dc = _num(r.get('dist_change'))
        if dc is not None and abs(dc) >= 400:
            neg += 1.5
        age = _num(r.get('age'))
        if age is not None and age >= 7:
            neg += 1.5
        # ライブは危険材料が1つでも -1.5。複数あっても同じ。上は足しているので
        # 1つ以上あれば -1.5 に揃える。
        neg = 1.5 if neg > 0 else 0.0
        score = -float(pop) + pos - neg
        scored.append((u, score, pop))
    scored.sort(key=lambda x: (-x[1], x[2], x[0]))
    rank = {u: i + 1 for i, (u, _, _) in enumerate(scored)}

    if n < 3:
        return rank, {u for u, _, _ in scored}
    half = (n + 1) // 2
    cut_zone = n - half
    bmax = max(0, min(3, cut_zone - 1)) if n >= 6 else 0
    b = min(border, bmax)
    surv = {u for u, _, _ in scored[:half + b]}
    return rank, surv


def recommend_n(rows, kigo, is_handi):
    odds = []
    for r in rows:
        v = _num(r.get('win_odds'))
        if v and v > 0:
            odds.append(v)
    ap = vs.arare_prob(odds, {'is_handicap': bool(is_handi), 'kigo': kigo or ''}, len(rows))
    rec = nn.recommend(ap, len(rows))
    if rec:
        return int(rec['n']), rec.get('arare_band', '')
    return 7, ''


def cut_to_n(order, n_keep):
    """order = 消す順（先頭が上=消す）。末尾 n_keep 頭を残す。"""
    n_keep = max(1, min(n_keep, len(order)))
    cut = set(order[:max(0, len(order) - n_keep)])
    keep = set(order[len(order) - n_keep:])
    return keep, cut


def revival(cut, rows, elite_top3):
    add = set()
    combo_of = {int(r['umaban']): int(_num(r.get('combo')) or 0) for r in rows}
    for u in cut:
        if combo_of.get(u, 0) >= 3 or u in elite_top3:
            add.add(u)
    return add


def apply_flow(order, tgt, rows, elite_top3, pool=None):
    """pool=Noneなら全頭から切る。指定ならその中だけ切る(📊残り)。"""
    if pool is not None:
        order = [u for u in order if u in pool]
    if len(order) > tgt:
        keep, cut = cut_to_n(order, tgt)
    else:
        keep, cut = set(order), set()
    add = revival(cut, rows, elite_top3)
    return keep | add, keep, add


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'day', 'jyo', 'umaban', 'ninki', 'win_odds', 'top3',
        'elim_n', 'combo', 'ability_score', 'spurt_idx', 'pos_ratio3', 'avg_pos3',
        'avg_chaku5', 'h7_fig', 'sire_surf_t3', 'jockey_form_t3', 'is_handi1',
        'days_since', 'dist_change', 'age',
    ])
    h = h[(h['day'] >= DAY0) & (h['day'] <= DAY1)]
    h['jyo'] = h['jyo'].astype(float)
    print(f'  2026/1-6 馬行 {len(h):,} / レース {h["race_key"].nunique():,}', flush=True)

    races = cd.load_races(cols=['race_key', 'kigo', 'is_handi1', 'field_size'])
    kigo_map = dict(zip(races['race_key'].astype(str), races['kigo'].fillna('').astype(str)))
    handi_map = dict(zip(races['race_key'].astype(str),
                         races['is_handi1'].fillna(0).astype(int)))

    stats = {
        'full': {'tot': 0, 'ok': 0, 'ok_norev': 0, 'miss': Counter(),
                 'keep': [], 'rev': [], 'tgt': [], 'plus': 0},
        'edf': {'tot': 0, 'ok': 0, 'ok_norev': 0, 'miss': Counter(),
                'keep': [], 'rev': [], 'tgt': [], 'plus': 0},
        'ninki': {'tot': 0, 'ok': 0, 'miss': Counter(), 'keep': []},
    }
    skipped = Counter()
    by_month = defaultdict(lambda: {'tot': 0, 'ok_full': 0, 'ok_edf': 0})
    jra_n = nar_n = 0

    for rk, g in h.groupby('race_key', sort=False):
        win = set(int(x) for x in g[g['top3'] == 1]['umaban'])
        if len(win) != 3:
            skipped['top3!=3'] += 1
            continue
        if len(g) < 5:
            skipped['field<5'] += 1
            continue
        rows = g.to_dict('records')
        jyo = int(g['jyo'].iloc[0])
        is_jra = 1 <= jyo <= 10
        if is_jra:
            jra_n += 1
        else:
            nar_n += 1
            # ユーザーのSRA想定は中央。地方は別集計に回す
            skipped['nar'] += 1
            continue

        flags, ninki = flag_counts(rows)
        elite_top3, scored = hunter_elite_top3(rows)
        rk_edf, surv = edf_rank_and_surv(rows, border=3)
        add_rklow_vh(flags, len(rows), rk_edf, scored)

        order = sorted(flags, key=lambda u: (-flags[u], -ninki.get(u, 0)))
        kigo = kigo_map.get(str(rk), '')
        is_handi = bool(handi_map.get(str(rk), int(_num(g['is_handi1'].iloc[0]) or 0)))
        tgt, _band = recommend_n(rows, kigo, is_handi)
        month = int(g['day'].iloc[0]) // 100

        # A: 全頭のクロスから推奨まで（ユーザー説明どおり）
        keep_a, keep_a0, add_a = apply_flow(order, tgt, rows, elite_top3, pool=None)
        sa = stats['full']
        sa['tot'] += 1
        sa['tgt'].append(tgt)
        sa['keep'].append(len(keep_a))
        sa['rev'].append(len(add_a))
        if len(keep_a) > tgt:
            sa['plus'] += 1
        miss_a = len(win - keep_a)
        sa['miss'][miss_a] += 1
        if miss_a == 0:
            sa['ok'] += 1
        if win <= keep_a0:
            sa['ok_norev'] += 1

        # B: 先に📊(半分+ボーダー3)→クロスで推奨まで（アプリの実画面）
        keep_b, keep_b0, add_b = apply_flow(order, tgt, rows, elite_top3, pool=surv)
        sb = stats['edf']
        sb['tot'] += 1
        sb['tgt'].append(tgt)
        sb['keep'].append(len(keep_b))
        sb['rev'].append(len(add_b))
        if len(keep_b) > tgt:
            sb['plus'] += 1
        miss_b = len(win - keep_b)
        sb['miss'][miss_b] += 1
        if miss_b == 0:
            sb['ok'] += 1
        if win <= keep_b0:
            sb['ok_norev'] += 1

        # 参考: 人気上位N頭（フラグ無視）
        pop_order = sorted(ninki, key=lambda u: ninki[u])  # 人気1が先頭=残す側
        keep_p = set(pop_order[:tgt])
        stats['ninki']['tot'] += 1
        stats['ninki']['keep'].append(len(keep_p))
        miss_p = len(win - keep_p)
        stats['ninki']['miss'][miss_p] += 1
        if miss_p == 0:
            stats['ninki']['ok'] += 1

        by_month[month]['tot'] += 1
        if miss_a == 0:
            by_month[month]['ok_full'] += 1
        if miss_b == 0:
            by_month[month]['ok_edf'] += 1

    def pct(a, b):
        return a / b * 100 if b else 0.0

    def report(title, s, with_rev=True):
        tot = s['tot']
        print(f'\n=== {title}  {tot:,}R ===')
        print(f'  3着3頭が全部残った:  {s["ok"]:,} / {tot:,}  ({pct(s["ok"], tot):.1f}%)')
        if with_rev and 'ok_norev' in s:
            print(f'  敗者復活なしだと:    {s["ok_norev"]:,} / {tot:,}  ({pct(s["ok_norev"], tot):.1f}%)')
        if s.get('tgt'):
            print(f'  平均 推奨頭数 {sum(s["tgt"])/len(s["tgt"]):.1f}'
                  f' / 送信頭数 {sum(s["keep"])/len(s["keep"]):.1f}', end='')
            if s.get('rev'):
                print(f'（復活平均 {sum(s["rev"])/len(s["rev"]):.2f}頭・'
                      f'推奨より多いレース {s.get("plus", 0):,}）')
            else:
                print()
        print('  3着の欠け:')
        for k in (0, 1, 2, 3):
            print(f'    {k}頭欠け: {s["miss"][k]:,}R  ({pct(s["miss"][k], tot):.1f}%)')
        if s.get('rev'):
            n1 = sum(1 for x in s['rev'] if x == 1)
            n2 = sum(1 for x in s['rev'] if x >= 2)
            print(f'  復活1頭: {n1:,}R  /  2頭以上: {n2:,}R')

    print(f'\nJRAのみ集計（地方は除外 {skipped["nar"]:,}R）。'
          f'3着確定以外のスキップ: top3!=3 {skipped["top3!=3"]:,} / 頭数<5 {skipped["field<5"]:,}')
    report('A 全頭クロス → 上から消して推奨頭数 → 敗者復活（説明どおり）', stats['full'])
    report('B 先に📊半分+ボーダー3 → クロスで推奨まで → 敗者復活（アプリ画面）', stats['edf'])
    report('参考 人気上位N頭だけ残す（フラグも復活もなし）', stats['ninki'], with_rev=False)

    print('\n=== 月別（全部残った件数） ===')
    for m in sorted(by_month):
        d = by_month[m]
        print(f'  {m}: {d["tot"]:,}R  A {d["ok_full"]:,} ({pct(d["ok_full"], d["tot"]):.1f}%)'
              f'  B {d["ok_edf"]:,} ({pct(d["ok_edf"], d["tot"]):.1f}%)')
    print('\nSRAその場の旗（調教C・戦闘力下位・展開MAP・Stress・騎手弱材料）は未使用。'
          '本番より消す順番が少し違う可能性がある。')


if __name__ == '__main__':
    main()
