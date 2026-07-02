# -*- coding: utf-8 -*-
"""NAR在庫データでJRA検証済みシグナルを再検証(P1+P2バッチ)。

大井(nankan_backtest_rows.json) + 川崎(kawasaki_backtest_rows.json)を読み、
JRAで「検証済エッジ」として発火しているシグナルがNARでも有意かを一括検証。
venue別フィルタ + 統合(全NAR)の3パスで比較する。

検証項目:
  [D1] ダート枠順バイアス — 外枠×1-3人気 / 内枠×4-5人気(JRA: z+9.4/-6.0)
  [D2] 事前脚質(前型)×人気帯 — 先行有利は織り込み済みか
  [D3] PCI乖離 — レース内avg_pci偏差と複勝率の関係
  [D4] 少頭数/フルゲートの荒れ条件 — trio_leanの前提がNARで成立するか
  [D5] 川崎固有: 内枠×逃げ先行(超小回り×直線300m)

残差 = 人気帯別期待複勝率からの乖離。オッズ未保有のため人気帯ベースライン使用。
"""
import sys
import io
import json
import math
import os
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

OOI_PATH = 'scripts/debug/nankan_backtest_rows.json'
KAWASAKI_PATH = 'scripts/debug/kawasaki_backtest_rows.json'

POP_BANDS = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 9), (10, 99)]


def pop_band(p):
    if p is None:
        return None
    for lo, hi in POP_BANDS:
        if lo <= p <= hi:
            return (lo, hi)
    return None


def pop_band_label(b):
    if b is None:
        return '?'
    lo, hi = b
    return f'{lo}' if lo == hi else f'{lo}-{hi}'


def z_score(hits, n, expected_rate):
    if n < 20 or expected_rate <= 0 or expected_rate >= 1:
        return 0.0
    p_hat = hits / n
    se = math.sqrt(expected_rate * (1 - expected_rate) / n)
    return (p_hat - expected_rate) / se if se > 0 else 0.0


def is_top3(r):
    return r.get('rank') is not None and 1 <= r['rank'] <= 3


def positional_third(umaban, n_horses):
    cutoff_inner = math.ceil(n_horses / 3)
    cutoff_outer = math.floor(2 * n_horses / 3)
    if umaban <= cutoff_inner:
        return 'inner'
    if umaban > cutoff_outer:
        return 'outer'
    return 'middle'


def load_data():
    rows = []
    if os.path.exists(OOI_PATH):
        with open(OOI_PATH, encoding='utf-8') as f:
            ooi = json.load(f)
        for r in ooi:
            r.setdefault('venue', 'ooi')
        rows.extend(ooi)
    if os.path.exists(KAWASAKI_PATH):
        with open(KAWASAKI_PATH, encoding='utf-8') as f:
            kawa = json.load(f)
        for r in kawa:
            r.setdefault('venue', 'kawasaki')
        rows.extend(kawa)
    return rows


def run_analysis(rows, venue_label):
    n_races = len(set(r['race_id'] for r in rows))
    print(f'\n{"#"*70}')
    print(f'# {venue_label} ({n_races}R / {len(rows)}頭)')
    print(f'{"#"*70}')

    # ── 人気帯別ベースライン ──
    band_stats = defaultdict(lambda: {'n': 0, 'hits': 0})
    for r in rows:
        b = pop_band(r.get('popularity'))
        if b is None:
            continue
        band_stats[b]['n'] += 1
        if is_top3(r):
            band_stats[b]['hits'] += 1

    band_expected = {}
    print('\n[ベースライン] 人気帯別複勝率:')
    for b in POP_BANDS:
        s = band_stats[b]
        rate = s['hits'] / s['n'] if s['n'] > 0 else 0
        band_expected[b] = rate
        print(f'  {pop_band_label(b)}人気: {rate:.1%} (n={s["n"]})')

    def expected_rate(pop):
        b = pop_band(pop)
        return band_expected.get(b, 0.25) if b else 0.25

    def analyze_group(label, subset):
        n = len(subset)
        if n < 20:
            print(f'  {label}: n={n} (標本不足)')
            return None
        hits = sum(1 for r in subset if is_top3(r))
        rate = hits / n
        exp_sum = sum(expected_rate(r.get('popularity')) for r in subset)
        exp_rate = exp_sum / n
        residual = rate - exp_rate
        z = z_score(hits, n, exp_rate)
        sig = ' ***' if abs(z) >= 2.58 else ' **' if abs(z) >= 1.96 else ''
        print(f'  {label}: 複勝率={rate:.1%} 期待={exp_rate:.1%} 残差={residual:+.1%}pp z={z:+.2f} (n={n}){sig}')
        return {'rate': rate, 'exp': exp_rate, 'residual': residual, 'z': z, 'n': n}

    # ── 位置区分 ──
    for r in rows:
        r['_pos'] = positional_third(r['umaban'], r['n_horses'])

    # ════════════════════════════════════════════════
    # [D1] ダート枠順バイアス
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print('[D1] ダート枠順バイアス')
    print('='*60)

    print('\n[D1a] 外枠×1-3人気 (JRA: +4.5pp / z+9.4):')
    for pos in ['outer', 'middle', 'inner']:
        sub = [r for r in rows if r['_pos'] == pos and r.get('popularity') and r['popularity'] <= 3]
        analyze_group(f'{pos}×1-3人気', sub)

    print('\n[D1b] 内枠×4-5人気 (JRA: -3.9pp / z-6.0):')
    for pos in ['inner', 'middle', 'outer']:
        sub = [r for r in rows if r['_pos'] == pos and r.get('popularity') and 4 <= r['popularity'] <= 5]
        analyze_group(f'{pos}×4-5人気', sub)

    print('\n[D1c] 全人気帯・枠位置別:')
    for pos in ['inner', 'middle', 'outer']:
        sub = [r for r in rows if r['_pos'] == pos]
        analyze_group(f'{pos}(全人気)', sub)

    # ════════════════════════════════════════════════
    # [D2] 事前脚質×人気帯
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print('[D2] 事前脚質×人気帯')
    print('='*60)

    legs = ['逃げ', '先行', '差し', '追込']
    pop_groups = [(1, 3, '1-3人気'), (4, 5, '4-5人気'), (6, 99, '6+人気')]

    for plo, phi, plabel in pop_groups:
        print(f'\n[D2] {plabel}:')
        for leg in legs:
            sub = [r for r in rows if r.get('leg_type') == leg and r.get('popularity') and plo <= r['popularity'] <= phi]
            analyze_group(f'{leg}×{plabel}', sub)

    print('\n[D2b] 前型(逃げ+先行) vs 後型(差し+追込):')
    for plo, phi, plabel in pop_groups:
        front = [r for r in rows if r.get('leg_type') in ('逃げ', '先行') and r.get('popularity') and plo <= r['popularity'] <= phi]
        back = [r for r in rows if r.get('leg_type') in ('差し', '追込') and r.get('popularity') and plo <= r['popularity'] <= phi]
        analyze_group(f'前型×{plabel}', front)
        analyze_group(f'後型×{plabel}', back)

    # ════════════════════════════════════════════════
    # [D3] PCI乖離
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print('[D3] PCI乖離')
    print('='*60)

    race_pci = defaultdict(list)
    for r in rows:
        if r.get('avg_pci') is not None:
            race_pci[r['race_id']].append(r['avg_pci'])

    race_pci_mean = {}
    race_pci_std = {}
    for rid, vals in race_pci.items():
        if len(vals) >= 5:
            m = sum(vals) / len(vals)
            race_pci_mean[rid] = m
            race_pci_std[rid] = math.sqrt(sum((v - m)**2 for v in vals) / len(vals)) if len(vals) > 1 else 1.0

    for r in rows:
        r['_pci_dev'] = None
        if r.get('avg_pci') is not None and r['race_id'] in race_pci_mean:
            std = race_pci_std[r['race_id']]
            if std > 0.5:
                r['_pci_dev'] = (r['avg_pci'] - race_pci_mean[r['race_id']]) / std

    pci_rows = [r for r in rows if r.get('_pci_dev') is not None]
    print(f'\nPCI偏差算出可能: {len(pci_rows)}/{len(rows)}')

    print('\n[D3a] PCI偏差×人気帯:')
    for plo, phi, plabel in pop_groups:
        for dev_lo, dev_hi, dlabel in [(-99, -1.0, 'PCI低(≤-1σ)'), (-1.0, 1.0, 'PCI中(-1~+1σ)'), (1.0, 99, 'PCI高(≥+1σ)')]:
            sub = [r for r in pci_rows if dev_lo < r['_pci_dev'] <= dev_hi and r.get('popularity') and plo <= r['popularity'] <= phi]
            analyze_group(f'{dlabel}×{plabel}', sub)

    # ════════════════════════════════════════════════
    # [D4] 少頭数/フルゲートの荒れ条件
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print('[D4] 頭数別荒れ傾向')
    print('='*60)

    race_horses = defaultdict(list)
    for r in rows:
        race_horses[r['race_id']].append(r)

    for nlo, nhi, nlabel in [(5, 8, '少頭数(≤8)'), (9, 10, '中少(9-10)'), (11, 12, '中(11-12)'), (13, 14, '多(13-14)'), (15, 16, 'フル(15-16)')]:
        target_races = {rid: hs for rid, hs in race_horses.items() if nlo <= hs[0]['n_horses'] <= nhi}
        if not target_races:
            print(f'  {nlabel}: レース数=0')
            continue
        honsen = 0
        ana2 = 0
        n_races = len(target_races)
        for rid, hs in target_races.items():
            pop1_in = any(h['popularity'] == 1 and is_top3(h) for h in hs)
            pop2_in = any(h['popularity'] == 2 and is_top3(h) for h in hs)
            if pop1_in and pop2_in:
                honsen += 1
            top3 = [h for h in hs if is_top3(h)]
            ana_count = sum(1 for h in top3 if h.get('popularity') and h['popularity'] >= 5)
            if ana_count >= 2:
                ana2 += 1
        print(f'  {nlabel}: {n_races}R / ①本線={honsen}({honsen/n_races:.0%}) / ②穴2頭={ana2}({ana2/n_races:.0%})')

    print('\n[D4b] 頭数×人気帯別残差:')
    for nlo, nhi, nlabel in [(5, 10, '少(≤10)'), (11, 12, '中(11-12)'), (13, 16, '多(≥13)')]:
        for plo, phi, plabel in [(1, 3, '1-3人気'), (4, 5, '4-5人気'), (6, 99, '6+人気')]:
            sub = [r for r in rows if nlo <= r['n_horses'] <= nhi and r.get('popularity') and plo <= r['popularity'] <= phi]
            analyze_group(f'{nlabel}×{plabel}', sub)

    # ════════════════════════════════════════════════
    # [D5] 川崎固有: 内枠×前型(超小回り仮説)
    # ════════════════════════════════════════════════
    kawasaki_rows = [r for r in rows if r.get('venue') == 'kawasaki']
    if kawasaki_rows:
        print('\n' + '='*60)
        print('[D5] 川崎固有: 内枠×前型(超小回り×直線300m)')
        print('='*60)

        print('\n[D5a] 内枠×前型 vs 外枠×後型:')
        for plo, phi, plabel in pop_groups:
            inner_front = [r for r in kawasaki_rows if r['_pos'] == 'inner'
                           and r.get('leg_type') in ('逃げ', '先行')
                           and r.get('popularity') and plo <= r['popularity'] <= phi]
            outer_back = [r for r in kawasaki_rows if r['_pos'] == 'outer'
                          and r.get('leg_type') in ('差し', '追込')
                          and r.get('popularity') and plo <= r['popularity'] <= phi]
            analyze_group(f'川崎内枠×前型×{plabel}', inner_front)
            analyze_group(f'川崎外枠×後型×{plabel}', outer_back)

    # ════════════════════════════════════════════════
    # [D6] 末脚指数(既存検証との整合確認)
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print('[D6] 末脚指数top3×人気帯(既存検証の再確認)')
    print('='*60)

    for plo, phi, plabel in [(1, 3, '1-3人気'), (4, 5, '4-5人気'), (6, 99, '6+人気')]:
        spurt_yes = [r for r in rows if r.get('spurt_top3') and r.get('popularity') and plo <= r['popularity'] <= phi]
        spurt_no = [r for r in rows if not r.get('spurt_top3') and r.get('popularity') and plo <= r['popularity'] <= phi]
        analyze_group(f'末脚top3×{plabel}', spurt_yes)
        analyze_group(f'末脚非top3×{plabel}', spurt_no)

    # ════════════════════════════════════════════════
    # 総合サマリ
    # ════════════════════════════════════════════════
    print('\n' + '='*60)
    print(f'[総合サマリ] {venue_label}')
    print('='*60)

    outer_pop13 = [r for r in rows if r['_pos'] == 'outer' and r.get('popularity') and r['popularity'] <= 3]
    inner_pop45 = [r for r in rows if r['_pos'] == 'inner' and r.get('popularity') and 4 <= r['popularity'] <= 5]

    n_o = len(outer_pop13)
    h_o = sum(1 for r in outer_pop13 if is_top3(r))
    e_o = sum(expected_rate(r.get('popularity')) for r in outer_pop13) / n_o if n_o else 0
    z_o = z_score(h_o, n_o, e_o) if n_o >= 20 else 0

    n_i = len(inner_pop45)
    h_i = sum(1 for r in inner_pop45 if is_top3(r))
    e_i = sum(expected_rate(r.get('popularity')) for r in inner_pop45) / n_i if n_i else 0
    z_i = z_score(h_i, n_i, e_i) if n_i >= 20 else 0

    print(f'  D1 外枠×1-3人気: z={z_o:+.2f} (n={n_o})')
    print(f'  D1 内枠×4-5人気: z={z_i:+.2f} (n={n_i})')

    front_ana = [r for r in rows if r.get('leg_type') in ('逃げ', '先行') and r.get('popularity') and r['popularity'] >= 6]
    if len(front_ana) >= 20:
        h_f = sum(1 for r in front_ana if is_top3(r))
        e_f = sum(expected_rate(r.get('popularity')) for r in front_ana) / len(front_ana)
        z_f = z_score(h_f, len(front_ana), e_f)
        print(f'  D2 前型×6+人気: z={z_f:+.2f} (n={len(front_ana)})')

    small_pop13 = [r for r in rows if r['n_horses'] <= 10 and r.get('popularity') and r['popularity'] <= 3]
    if len(small_pop13) >= 20:
        h_s = sum(1 for r in small_pop13 if is_top3(r))
        e_s = sum(expected_rate(r.get('popularity')) for r in small_pop13) / len(small_pop13)
        z_s = z_score(h_s, len(small_pop13), e_s)
        print(f'  D4 少頭数×1-3人気: z={z_s:+.2f} (n={len(small_pop13)})')

    spurt_ana = [r for r in rows if r.get('spurt_top3') and r.get('popularity') and r['popularity'] >= 6]
    if len(spurt_ana) >= 20:
        h_sp = sum(1 for r in spurt_ana if is_top3(r))
        e_sp = sum(expected_rate(r.get('popularity')) for r in spurt_ana) / len(spurt_ana)
        z_sp = z_score(h_sp, len(spurt_ana), e_sp)
        print(f'  D6 末脚top3×6+人気: z={z_sp:+.2f} (n={len(spurt_ana)})')


def main():
    all_rows = load_data()
    if not all_rows:
        print('データファイルが見つかりません。')
        return

    ooi_rows = [r for r in all_rows if r.get('venue', 'ooi') == 'ooi']
    kawa_rows = [r for r in all_rows if r.get('venue') == 'kawasaki']

    # Pass 1: 大井のみ
    if ooi_rows:
        run_analysis(ooi_rows, '大井(Ooi)')

    # Pass 2: 川崎のみ
    if kawa_rows:
        run_analysis(kawa_rows, '川崎(Kawasaki)')

    # Pass 3: 統合
    if ooi_rows and kawa_rows:
        run_analysis(all_rows, '全NAR統合(大井+川崎)')

    # ── venue間差分サマリ ──
    if ooi_rows and kawa_rows:
        print('\n' + '#'*70)
        print('# venue間差分(大井 vs 川崎)')
        print('#'*70)
        print('\n構造の違い: 大井=大箱/直線386m/右回り vs 川崎=小回り/直線300m/左回り')
        print('大井は差しも届く。川崎は先行有利が定説。')


if __name__ == '__main__':
    main()
