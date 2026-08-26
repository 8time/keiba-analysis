# -*- coding: utf-8 -*-
"""複勝積10点が外すレースの正体。特徴量の微調整はしない。

全体捕捉≈41% を
  A  候補選定で落とした（使う馬の外）
  B  候補にはいたが10点で落とした
に分け、B は複勝積での正解組の順位で
  近い外れ / 中距離 / 遠い外れ
に分ける。

さらにレース属性ごとの全体捕捉を出し、
『市場ベースが苦手な条件』があるかを見る。

基準プール: 人気1-7（本命）と 人気1-9（参考）。
主指標は holdout。アプリは変えない。

Usage: python scripts/trio_fuku_miss_profile.py
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from itertools import combinations

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.axis_selector import fuku_rate
from core.jockey_jv import JV_DB_PATH
from scripts import csv_data as cd

N_POINTS = 10


def load_pays():
    con = sqlite3.connect(f'file:{JV_DB_PATH}?mode=ro', uri=True, timeout=30)
    rows = con.execute(
        "SELECT race_key, combo, payout FROM payouts "
        "WHERE bet_type='3連複' AND payout>0"
    ).fetchall()
    con.close()
    out = {}
    for rk, combo, p in rows:
        try:
            fs = frozenset(int(combo[i:i + 2]) for i in range(0, 6, 2))
            if len(fs) == 3:
                out[str(rk)] = (fs, float(p))
        except Exception:
            continue
    return out


def fuku_of(ninki, odds):
    v = fuku_rate(ninki, odds)
    if v is None:
        v = fuku_rate(ninki, None)
    return max(1.0, float(v or 8.0)) / 100.0


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def keep_ninki(g, k):
    sub = g[g['ninki'] <= k]
    return sub.nsmallest(min(k, len(sub)), 'ninki')


def combo_rank(ums, fk, win):
    combos = [frozenset(c) for c in combinations(ums, 3)]
    ordered = sorted(
        combos,
        key=lambda fs: fk[list(fs)[0]] * fk[list(fs)[1]] * fk[list(fs)[2]],
        reverse=True,
    )
    try:
        return ordered.index(win) + 1, len(combos)
    except ValueError:
        return None, len(combos)


def style_of(pos):
    if pos is None:
        return '不明'
    if pos <= 0.28:
        return '前'
    if pos >= 0.55:
        return '後'
    return '中'


def dist_band(ky):
    if ky is None:
        return '距離不明'
    if ky <= 1400:
        return '短距離~1400'
    if ky <= 1800:
        return 'マイル~1800'
    if ky <= 2200:
        return '中距離~2200'
    return '長距離2201+'


def fs_band(n):
    if n is None:
        return '頭数不明'
    if n <= 10:
        return '少頭~10'
    if n <= 14:
        return '中頭11-14'
    return '多頭15+'


def vs_band(vs):
    if vs is None:
        return '妙味不明'
    if vs < 50:
        return '堅い<50'
    if vs < 70:
        return '中庸50-69'
    return '荒れ70+'


def b_bin(rank, n_combo):
    """ユーザー指定の21-30 / 31-50 / 51+ に、7頭(最大35)でも読める補助を付ける。"""
    if rank is None:
        return 'A候補外'
    if rank <= 10:
        return '的中'
    if rank <= 20:
        return 'B 11-20位'
    if rank <= 30:
        return 'B 21-30位'
    if rank <= 50:
        return 'B 31-50位'
    return 'B 51位以下'


def pct(a, b):
    return a / b * 100 if b else 0.0


def main():
    print('読込...', flush=True)
    h = cd.load_horses(cols=[
        'race_key', 'umaban', 'ninki', 'win_odds', 'top3', 'chakujun',
        'pos_ratio3', 'days_since', 'surface_code', 'kyori_int', 'field_size',
        'is_handi1',
    ])
    rmeta = cd.load_races(cols=[
        'race_key', 'vscore', 'n_front', 'n_hana', 'surface_code',
        'kyori', 'field_size', 'is_handi1',
    ])
    rmeta = rmeta.drop_duplicates('race_key')
    rmap = {}
    for r in rmeta.itertuples(index=False):
        rec = {
            'vscore': _num(r.vscore),
            'n_front': _num(r.n_front),
            'n_hana': _num(r.n_hana),
            'surf': 'ダ' if _num(getattr(r, 'surface_code', None)) == 1 else '芝',
            'kyori': _num(getattr(r, 'kyori', None)),
            'fs': _num(getattr(r, 'field_size', None)),
            'handi': bool(_num(getattr(r, 'is_handi1', None))),
        }
        rmap[str(r.race_key)] = rec
        try:
            rmap[str(int(r.race_key))] = rec
        except (TypeError, ValueError):
            pass
    pays = load_pays()
    print(f'  馬行 {len(h):,} / 配当 {len(pays):,}', flush=True)

    # recs[k] = list of dicts
    recs = {7: [], 9: []}
    a_drop = {7: Counter(), 9: Counter()}  # dropped winner ninki

    for rk, g in h.groupby('race_key', sort=False):
        win_rows = g[g['top3'] == 1]
        if len(win_rows) != 3:
            continue
        win = frozenset(int(x) for x in win_rows['umaban'])
        pay = pays.get(str(rk)) or pays.get(rk)
        if not pay:
            try:
                pay = pays.get(int(rk))
            except (TypeError, ValueError):
                pay = None
        if not pay or pay[0] != win:
            continue
        payout = pay[1]
        period = str(g['period'].iloc[0])
        meta = rmap.get(str(rk)) or {}
        try:
            meta = meta or rmap.get(str(int(rk)), {})
        except (TypeError, ValueError):
            pass

        nk_map = {int(r.umaban): int(r.ninki) for r in g.itertuples(index=False)}
        pos_map = {int(r.umaban): _num(r.pos_ratio3) for r in g.itertuples(index=False)}
        day_map = {int(r.umaban): _num(r.days_since) for r in g.itertuples(index=False)}
        chaku1 = g[g['chakujun'] == 1]
        win_style = '不明'
        if len(chaku1):
            win_style = style_of(_num(chaku1['pos_ratio3'].iloc[0]))
        win_nks = sorted(nk_map[u] for u in win)
        third_nk = max(win_nks)
        fav1_out = 1 not in win_nks
        fav2_out = 2 not in win_nks
        layoff = any((day_map.get(u) or 0) >= 180 for u in win)
        surf = meta.get('surf')
        if not surf:
            sc = _num(g['surface_code'].iloc[0])
            surf = 'ダ' if sc == 1 else '芝'
        ky = meta.get('kyori') or _num(g['kyori_int'].iloc[0])
        fs = meta.get('fs') or _num(g['field_size'].iloc[0])
        vs = meta.get('vscore')
        n_front = meta.get('n_front')
        n_hana = meta.get('n_hana')
        handi = meta.get('handi')
        if handi is None:
            handi = bool(_num(g['is_handi1'].iloc[0]))

        flags = {
            'period': period,
            'payout': payout,
            'surf': surf,
            'dist': dist_band(ky),
            'heads': fs_band(fs),
            'vs': vs_band(vs),
            'handi': 'ハンデ' if handi else 'ハンデ以外',
            'fav1': '1番人気飛び' if fav1_out else '1番人気残',
            'fav12': '1-2とも飛び' if (fav1_out and fav2_out) else '1か2が残',
            'third': (
                '3着が6-7番' if third_nk in (6, 7) else
                '3着が8番以降' if third_nk >= 8 else
                '3着が5番以内'
            ),
            'finish': (
                '逃げ先行残り' if win_style == '前' else
                '差し追込決着' if win_style == '後' else
                '中団決着'
            ),
            'layoff': '勝ち馬に休み明け' if layoff else '休み明けなし',
            'fronts': (
                '先行多い5+' if (n_front is not None and n_front >= 5) else
                '先行少ない~2' if (n_front is not None and n_front <= 2) else
                '先行ふつう'
            ),
            'nige': (
                '逃げ2頭+' if (n_hana is not None and n_hana >= 2) else
                '逃げ0-1'
            ),
            'shape': (
                f'人{sum(1 for n in win_nks if n <= 4)}'
                f'+5が{sum(1 for n in win_nks if n == 5)}'
                f'+穴{sum(1 for n in win_nks if n >= 6)}'
            ),
            'third_nk': third_nk,
            'win_nks': tuple(win_nks),
        }

        for k in (7, 9):
            kg = keep_ninki(g, k)
            if len(kg) < 3:
                continue
            ums = [int(x) for x in kg['umaban']]
            keep = set(ums)
            fk = {int(r.umaban): fuku_of(r.ninki, r.win_odds)
                  for r in kg.itertuples(index=False)}
            in_keep = win <= keep
            rank, n_combo = (None, None)
            if in_keep:
                rank, n_combo = combo_rank(ums, fk, win)
            if not in_keep:
                dropped = [nk_map[u] for u in win if u not in keep]
                a_drop[k][min(dropped) if dropped else 99] += 1
                bucket = 'A候補外'
            elif rank <= N_POINTS:
                bucket = '的中'
            else:
                bucket = b_bin(rank, n_combo)
            rec = dict(flags)
            rec.update({
                'k': k,
                'bucket': bucket,
                'rank': rank,
                'n_combo': n_combo,
                'hit': bucket == '的中',
                'sel': in_keep,
            })
            recs[k].append(rec)

    def subset(rows, period):
        return [r for r in rows if r['period'] == period]

    def summarize(rows, title, k):
        n = len(rows)
        if n == 0:
            return
        print(f'\n=== {title}  人気1-{k}  {n:,}R ===')
        buckets = [
            '的中', 'A候補外', 'B 11-20位', 'B 21-30位', 'B 31-50位', 'B 51位以下',
        ]
        print(f'{"内訳":<14}{"件数":>8}{"全体比":>8}{"残し内比":>10}')
        n_sel = sum(1 for r in rows if r['sel'])
        for b in buckets:
            c = sum(1 for r in rows if r['bucket'] == b)
            extra = ''
            if b.startswith('B') and n_sel:
                extra = f'{pct(c, n_sel):9.1f}%'
            else:
                extra = f'{"—":>10}'
            print(f'{b:<14}{c:8,d}{pct(c, n):7.1f}%{extra}')
        n_hit = sum(1 for r in rows if r['hit'])
        n_a = sum(1 for r in rows if r['bucket'] == 'A候補外')
        n_b = n - n_hit - n_a
        print(f'\n  全体捕捉 {pct(n_hit, n):.1f}% ＝ 選定 {pct(n_sel, n):.1f}%'
              f' × 残し内10点 {pct(n_hit, n_sel):.1f}%')
        print(f'  外れの内訳: A候補 {pct(n_a, n):.1f}pt / B順位 {pct(n_b, n):.1f}pt'
              f'  （合計 {pct(n_a + n_b, n):.1f}pt）')

        # 20点・30点でBがどれだけ救えるか（参考。採用ではない）
        b_rows = [r for r in rows if r['sel'] and not r['hit']]
        if b_rows:
            rks = [r['rank'] for r in b_rows]
            print(f'  Bの順位 中央値 {sorted(rks)[len(rks)//2]}  / 平均 {sum(rks)/len(rks):.1f}'
                  f'  （組数の上限 {max(r["n_combo"] for r in b_rows)}）')
            for lim, lab in ((15, '15点'), (20, '20点'), (30, '30点')):
                saved = sum(1 for r in b_rows if r['rank'] <= lim)
                # 全体捕捉 if we used lim points on in-keep (still miss A)
                all_hit = n_hit + saved
                print(f'    参考 {lab}なら B の {pct(saved, len(b_rows)):.1f}% を救出'
                      f' → 全体捕捉 {pct(all_hit, n):.1f}%')

        if k in a_drop and period_of(rows):
            pass
        print('\n  Aで落ちた側の、一番人気が前の脱落馬の人気:')
        # recompute from rows? we used global a_drop by period mix. compute here.
        drop_c = Counter()
        # can't get dropped ninki from rec easily - skip, print from a_drop filtered
        # We'll print a_drop only for holdout in caller.

        # payout of HIT vs B-close vs B-far
        def pays_of(pred):
            xs = [r['payout'] for r in rows if pred(r)]
            if not xs:
                return 0, 0, 0
            xs = sorted(xs)
            return len(xs), xs[len(xs)//2], sum(xs) / len(xs)

        print('\n  配当（3連複・円）')
        print(f'{"層":<14}{"件数":>8}{"中央値":>10}{"平均":>10}')
        for lab, pred in (
            ('的中10点', lambda r: r['hit']),
            ('B 11-20位', lambda r: r['bucket'] == 'B 11-20位'),
            ('B 21-30位', lambda r: r['bucket'] == 'B 21-30位'),
            ('B 31位以下', lambda r: r['bucket'] in ('B 31-50位', 'B 51位以下')),
            ('A候補外', lambda r: r['bucket'] == 'A候補外'),
        ):
            nn, med, avg = pays_of(pred)
            print(f'{lab:<14}{nn:8,d}{med:10.0f}{avg:10.0f}')

    def period_of(rows):
        return rows[0]['period'] if rows else ''

    def slice_table(rows, key, title):
        print(f'\n  -- {title} --')
        print(f'{"条件":<16}{"R":>6}{"全体捕捉":>8}{"選定":>8}{"残し内10":>8}'
              f'{"A率":>8}{"B率":>8}{"ROI":>8}')
        groups = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        base_hit = pct(sum(1 for r in rows if r['hit']), len(rows))
        for name in sorted(groups, key=lambda x: -len(groups[x])):
            rs = groups[name]
            n = len(rs)
            n_hit = sum(1 for r in rs if r['hit'])
            n_sel = sum(1 for r in rs if r['sel'])
            n_a = sum(1 for r in rs if r['bucket'] == 'A候補外')
            n_b = n - n_hit - n_a
            cost = n * N_POINTS * 100
            ret = sum(r['payout'] for r in rs if r['hit'])
            roi = ret / cost * 100 if cost else 0
            mark = ''
            ov = pct(n_hit, n)
            if ov <= base_hit - 8 and n >= 80:
                mark = ' ←市場が苦手'
            elif ov >= base_hit + 8 and n >= 80:
                mark = ' ←市場が得意'
            print(f'{str(name):<16}{n:6,d}{ov:7.1f}%{pct(n_sel, n):7.1f}%'
                  f'{pct(n_hit, n_sel):7.1f}%{pct(n_a, n):7.1f}%'
                  f'{pct(n_b, n):7.1f}%{roi:7.1f}%{mark}')

    for period, title in (('holdout', 'holdout ← 採用判定'), ('train', 'train 参考')):
        for k in (7, 9):
            rows = subset(recs[k], period)
            summarize(rows, title, k)
            # A脱落人気は holdout だけ詳細（全期間混ざる a_drop は使わない）
            if period == 'holdout':
                drop_c = Counter()
                # 再計算していないので third と win_nks から
                for r in rows:
                    if r['bucket'] != 'A候補外':
                        continue
                    # プール外の勝ち馬人気 = win_nks のうち k 超
                    outs = [n for n in r['win_nks'] if n > k]
                    if outs:
                        drop_c[min(outs)] += 1
                print('  A脱落（勝ち馬のうち一番手前の、プール外の人気）')
                tot = sum(drop_c.values()) or 1
                for nk in sorted(drop_c):
                    print(f'    {nk}番人気が外: {drop_c[nk]:,}  ({drop_c[nk]/tot*100:.1f}%)')

            if period == 'holdout' and k == 7:
                print('\n--- 市場が苦手な条件を探す（人気1-7・holdout）---')
                for key, lab in (
                    ('vs', '妙味度'),
                    ('fav1', '1番人気'),
                    ('fav12', '1-2番人気'),
                    ('third', '3着の人気'),
                    ('finish', '勝ち馬の脚質'),
                    ('surf', '馬場'),
                    ('dist', '距離'),
                    ('heads', '頭数'),
                    ('handi', 'ハンデ'),
                    ('layoff', '休み明け'),
                    ('fronts', '先行数'),
                    ('nige', '逃げ頭数'),
                ):
                    slice_table(rows, key, lab)

    print('\n読み方: A率が高い＝候補に入らない。B率が高い＝10点の並びで落ちる。')
    print('市場が苦手 ← は全体捕捉が基準より8pt以上低い条件（n>=80）。')
    print('アプリは変更していない。複勝積は基準のまま。')


if __name__ == '__main__':
    main()
