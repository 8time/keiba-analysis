# -*- coding: utf-8 -*-
"""穴馬しきい値の自動切替(少頭数×堅い→4番人気以降)は妥当か

提案: 出走10頭以下 かつ 市場が堅い(1番人気≤3.5倍 or 上位3頭の合成≤4.0倍)なら
      穴馬しきい値を既定の『6番人気以降』から『4番人気以降』へ自動で下げる。
実装: core/longshot_threshold.default_threshold()

検証する問い(トレードオフを両面で見る):
  ① 捕捉率  … しきい値以降の中に、実際に3着内へ来た馬がどれだけ含まれるか
  ② 精度    … しきい値以降の馬の3着内率(下げると母数が増えて薄まるはず)
  ③ VH上位2頭の捕捉 … 穴馬ハンターが実際に出す2頭が3着内をどれだけ拾えるか
     ＝提案の核心。ここが改善しないなら下げる意味がない。
  ④ 対照   … 多頭数(11頭以上)では下げると悪化するか(=切替が正しいか)

⚠ ①だけ見ると必ず「下げた方が良い」になる(母数が増えるので当たり前)。
  ③の『実際に買う2頭』で改善するかが判定基準。

使い方: python scripts/longshot_threshold_backtest.py
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd


def is_firm(odds):
    """longshot_threshold.default_threshold と同じ堅さ判定。"""
    o = sorted(x for x in odds if x and x > 0)
    if len(o) < 3:
        return None                     # オッズ不明
    inv = sum(1.0 / x for x in o[:3])
    syn3 = 3.0 / inv if inv else None
    return (o[0] <= 3.5) or (syn3 is not None and syn3 <= 4.0)


def main():
    print('CSV読込...')
    h = cd.load_horses(cols=['race_key', 'umaban', 'ninki', 'win_odds',
                             'top3', 'vh2_score', 'field_size'])
    h = h[h['ninki'].notna() & h['vh2_score'].notna()]
    print(f'  {len(h):,}行')

    races = defaultdict(list)
    for r in h.itertuples(index=False):
        races[str(int(r.race_key))].append(r)

    # レースを『少頭数×堅い』/『少頭数×開いている』/『多頭数』に分類
    groups = defaultdict(list)
    for rk, lst in races.items():
        n = len(lst)
        if n < 5:
            continue
        firm = is_firm([r.win_odds for r in lst])
        if n <= 10:
            g = '少頭数×堅い' if firm else ('少頭数×開' if firm is False else '少頭数×オッズ不明')
        else:
            g = '多頭数(11頭〜)'
        groups[g].append((rk, lst))

    print()
    print('=' * 88)
    print('■ 0. レース区分')
    print('=' * 88)
    tot = sum(len(v) for v in groups.values())
    for g in ('少頭数×堅い', '少頭数×開', '少頭数×オッズ不明', '多頭数(11頭〜)'):
        if groups.get(g):
            print(f'  {g:<20}{len(groups[g]):>8,}R ({len(groups[g])/tot*100:5.1f}%)')

    def eval_group(lst_races, th):
        """しきい値th以降を穴馬候補としたときの各指標。"""
        n_cand = n_cand_t3 = 0        # 候補数 / 候補のうち3着内
        n_t3_total = n_t3_in = 0      # 3着内総数 / うち候補に含まれた数
        vh_hit = vh_races = 0         # VH上位2頭が3着内を1頭以上拾えたR
        vh_pick = vh_pick_t3 = 0      # VH上位2頭の延べ / うち3着内
        for rk, rows in lst_races:
            cands = [r for r in rows if r.ninki >= th]
            t3 = [r for r in rows if r.top3 == 1]
            n_cand += len(cands)
            n_cand_t3 += sum(1 for r in cands if r.top3 == 1)
            n_t3_total += len(t3)
            n_t3_in += sum(1 for r in t3 if r.ninki >= th)
            if cands:
                top2 = sorted(cands, key=lambda r: -r.vh2_score)[:2]
                vh_races += 1
                vh_pick += len(top2)
                k = sum(1 for r in top2 if r.top3 == 1)
                vh_pick_t3 += k
                if k:
                    vh_hit += 1
        return dict(
            cand=n_cand,
            cand_t3_rate=(n_cand_t3 / n_cand * 100) if n_cand else 0,
            capture=(n_t3_in / n_t3_total * 100) if n_t3_total else 0,
            vh_races=vh_races,
            vh_hit_rate=(vh_hit / vh_races * 100) if vh_races else 0,
            vh_pick_t3_rate=(vh_pick_t3 / vh_pick * 100) if vh_pick else 0,
        )

    print()
    print('=' * 88)
    print('■ 1. しきい値4 vs 6 の比較')
    print('=' * 88)
    print(f"  {'区分':<20}{'th':>3}{'候補数':>9}{'候補3着内率':>11}"
          f"{'3着内捕捉':>10}{'VH2頭で1頭以上的中':>18}{'VH2頭の3着内率':>15}")
    for g in ('少頭数×堅い', '少頭数×開', '少頭数×オッズ不明', '多頭数(11頭〜)'):
        if not groups.get(g):
            continue
        for th in (4, 6):
            e = eval_group(groups[g], th)
            mark = ' ★' if (g == '少頭数×堅い' and th == 4) else ''
            print(f'  {g:<20}{th:>3}{e["cand"]:>9,}{e["cand_t3_rate"]:>10.1f}%'
                  f'{e["capture"]:>9.1f}%{e["vh_hit_rate"]:>17.1f}%'
                  f'{e["vh_pick_t3_rate"]:>14.1f}%{mark}')
        print()

    print('=' * 88)
    print('■ 2. 判定')
    print('=' * 88)
    a4 = eval_group(groups.get('少頭数×堅い', []), 4)
    a6 = eval_group(groups.get('少頭数×堅い', []), 6)
    m4 = eval_group(groups.get('多頭数(11頭〜)', []), 4)
    m6 = eval_group(groups.get('多頭数(11頭〜)', []), 6)
    print(f'  少頭数×堅い: VH2頭で1頭以上的中 {a6["vh_hit_rate"]:.1f}%(th6) '
          f'→ {a4["vh_hit_rate"]:.1f}%(th4)  差 {a4["vh_hit_rate"]-a6["vh_hit_rate"]:+.1f}pp')
    print(f'  多頭数(対照): VH2頭で1頭以上的中 {m6["vh_hit_rate"]:.1f}%(th6) '
          f'→ {m4["vh_hit_rate"]:.1f}%(th4)  差 {m4["vh_hit_rate"]-m6["vh_hit_rate"]:+.1f}pp')
    print()
    print('  ※多頭数でも下がるなら「少頭数だから」ではなく単に母数効果＝切替の根拠にならない。')
    print('  ※VH2頭の3着内率(精度)が大きく落ちるなら、拾えても買い目が薄まる。')


if __name__ == '__main__':
    main()
