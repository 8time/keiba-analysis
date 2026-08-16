# -*- coding: utf-8 -*-
"""🛟ボーダー残しを『レース条件で可変』にすると得か ―― 実装前の漏れ率確認。

現行(app.py 強適消去エンジン): 下位半分カット → ボーダー3頭を相手に戻す(固定3)。
案: 荒れ予報(core/value_scanner.trio_lean の lean)で戻す頭数を変える。
    ②穴妙味向き = top7圏外に3着馬が入りやすい → 多めに戻す
    本線向き     = 堅い → 少なめに戻して消去を稼ぐ

⚠ 評価の注意: 漏れ率(こぼし率)は「戻す頭数を増やせば必ず下がる」ので単独で見ても意味が無い。
   ボーダーを増やす=消す頭数が減る、というトレードオフなので、**平均消去頭数を揃えて**
   比較しないと『たくさん残したから漏れなかった』を改善と誤認する。
   ここでは固定ボーダー0〜5のフロンティア(平均消去頭数 → 漏れ率)を引き、
   可変ポリシーがそのフロンティアより下(=同じ消去数でより漏れない)かを見る。
   これが正味の『レース条件を見る価値』になる。

消去順は現行の支配項である人気順(scripts/elim_ml_ranking_backtest.py の A と同じ)を使う。
±1.5の検証済みファクター補正はCSVストアで完全再現できないため入れていない
(補正は全ポリシーに等しく効くので、ポリシー間の比較には影響しない)。

採用ゲート(このプロジェクトの慣例): train(≤2024)/holdout(2025+)の両窓で
  フロンティア比 -0.5pp 以上の改善が同符号で出ること。片窓だけなら不採用。

Usage: python scripts/elim_border_regime_backtest.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data  # noqa: E402

MIN_FIELD = 8       # scripts/elim_ml_ranking_backtest.py と同一
FIXED_RANGE = range(0, 6)


def build_races():
    """1レース=1レコードに畳む。以降のポリシー評価はこの上を回すだけ(高速化)。

    order: 消される順(人気が無い順)に並べた馬番。top3: 3着内の馬番。
    """
    print('Loading CSV store...', file=sys.stderr)
    h = csv_data.load_horses(cols=['race_key', 'day', 'umaban', 'ninki', 'chakujun', 'top3'])
    h['umaban'] = pd.to_numeric(h['umaban'], errors='coerce')
    h['chakujun'] = pd.to_numeric(h['chakujun'], errors='coerce')
    h = h[h['umaban'].notna() & h['chakujun'].notna()]
    r = csv_data.load_races(cols=['race_key', 'lean_label', 'lean_score'], with_period=False)
    lean = r.set_index('race_key')[['lean_label', 'lean_score']].to_dict('index')

    # 人気が無い順(=消される順)に並べる。同人気は馬番で決定的に。
    h = h.sort_values(['race_key', 'ninki', 'umaban'], ascending=[True, False, True])
    recs = []
    for rk, g in h.groupby('race_key', sort=False):
        n = len(g)
        if n < MIN_FIELD:
            continue
        top3 = frozenset(g.loc[g['chakujun'] <= 3, 'umaban'])
        if not top3:
            continue
        lv = lean.get(rk) or {}
        recs.append({
            'day': int(g['day'].iloc[0]),
            'n': n, 'order': tuple(g['umaban'].tolist()), 'top3': top3,
            'lean': str(lv.get('lean_label') or ''),
            'lean_score': float(lv.get('lean_score') or 0.0),
        })
    print(f'  races: {len(recs):,}', file=sys.stderr)
    return recs


def evaluate(recs, border_fn):
    """border_fn(rec)->戻す頭数。app.pyと同じガード(最低1頭は消しに残す/n>=6)を掛ける。"""
    miss = lost = cut_sum = 0
    tot = 0
    for rec in recs:
        n = rec['n']
        keep = (n + 1) // 2
        cut_zone = n - keep
        b = border_fn(rec)
        b_eff = max(0, min(int(b), cut_zone - 1)) if n >= 6 else 0
        eff = max(0, cut_zone - b_eff)
        if eff <= 0:
            tot += 1
            continue
        cut = set(rec['order'][:eff])
        hit = rec['top3'] & cut
        miss += int(bool(hit))
        lost += len(hit) / len(rec['top3'])
        cut_sum += eff
        tot += 1
    if not tot:
        return None
    return {'miss': miss / tot, 'lost3': lost / tot, 'cut': cut_sum / tot, 'races': tot}


# ── 可変ポリシー(荒れ予報 lean で戻す頭数を変える) ──
POLICIES = [
    ('V1: ②→4 / 本線→2 / 中立→3',
     lambda r: 4 if r['lean'] == '②穴妙味向き' else (2 if r['lean'] == '本線向き' else 3)),
    ('V2: ②→4 / それ以外3(荒れだけ広げる)',
     lambda r: 4 if r['lean'] == '②穴妙味向き' else 3),
    ('V3: 本線→2 / それ以外3(堅いだけ絞る)',
     lambda r: 2 if r['lean'] == '本線向き' else 3),
    ('V4: ②→5 / 本線→1 / 中立→3(強め)',
     lambda r: 5 if r['lean'] == '②穴妙味向き' else (1 if r['lean'] == '本線向き' else 3)),
    ('V5: lean_score連続(≥+1→4 / ≤-1→2)',
     lambda r: 4 if r['lean_score'] >= 1 else (2 if r['lean_score'] <= -1 else 3)),
]


def frontier_miss(fixed_pts, cut):
    """固定ボーダーの(平均消去数→漏れ率)フロンティア上で、平均消去数cutでの漏れ率を線形補間。"""
    xs = np.array([p['cut'] for p in fixed_pts])
    ys = np.array([p['miss'] for p in fixed_pts])
    o = np.argsort(xs)
    return float(np.interp(cut, xs[o], ys[o]))


def report(recs, label):
    print(f'\n--- {label}  {len(recs):,}レース ---')
    dist = pd.Series([r['lean'] or '(空)' for r in recs]).value_counts(normalize=True)
    print('  荒れ予報の分布: ' + ' / '.join(f'{k}{v:.1%}' for k, v in dist.items()))

    fixed = []
    print(f"\n  {'固定ボーダー':28s} {'平均消去':>8s} {'漏れ率':>8s} {'lost3':>7s}")
    for b in FIXED_RANGE:
        m = evaluate(recs, lambda r, b=b: b)
        fixed.append(m)
        mark = '  ← 現行' if b == 3 else ''
        print(f"  {'B' + str(b) + ': 常に' + str(b) + '頭戻す':28s} {m['cut']:7.2f}頭 "
              f"{m['miss']*100:7.2f}% {m['lost3']*100:6.2f}%{mark}")

    cur = fixed[3]
    print(f"\n  {'可変ポリシー':28s} {'平均消去':>8s} {'漏れ率':>8s} {'対現行B3':>9s} "
          f"{'同消去数の固定':>12s} {'フロンティア比':>12s}")
    out = []
    for name, fn in POLICIES:
        m = evaluate(recs, fn)
        f = frontier_miss(fixed, m['cut'])
        d_front = (m['miss'] - f) * 100
        out.append((name, m, d_front))
        print(f"  {name:28s} {m['cut']:7.2f}頭 {m['miss']*100:7.2f}% "
              f"{(m['miss']-cur['miss'])*100:+8.2f}pp {f*100:11.2f}% "
              f"{d_front:+11.2f}pp{'✅' if d_front <= -0.5 else ''}")
    return {name: d for name, _, d in out}


def main():
    recs = build_races()
    tr = [r for r in recs if r['day'] // 10000 <= 2024]
    ho = [r for r in recs if r['day'] // 10000 >= 2025]
    print('=' * 92)
    print('🛟ボーダー残しの可変化 ―― 平均消去頭数を揃えた比較(フロンティア比)')
    print('=' * 92)
    a = report(tr, 'train ≤2024')
    b = report(ho, 'holdout 2025+')
    print('\n' + '=' * 92)
    print('両窓まとめ(フロンティア比・負=同じ消去数でより漏れない=可変化の価値)')
    print(f"  {'ポリシー':28s} {'train':>10s} {'holdout':>10s}  判定")
    for name, _ in POLICIES:
        x, y = a[name], b[name]
        ok = (x <= -0.5 and y <= -0.5)
        print(f"  {name:28s} {x:+9.2f}pp {y:+9.2f}pp  "
              f"{'✅採用' if ok else ('△片窓' if (x <= -0.5 or y <= -0.5) else '❌')}")
    print('\n※ 漏れ率は戻す頭数を増やせば必ず下がる。価値があるのは「同じ平均消去頭数で」')
    print('  漏れ率が固定ボーダーのフロンティアより低い時だけ(=フロンティア比が負)。')


if __name__ == '__main__':
    main()
