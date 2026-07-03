# -*- coding: utf-8 -*-
"""消去クロス強化・拡張版 — 強適表の各"列"の下位を交差/積み上げ(重複)すると
どれが独立に効くか・どれが安全に消せるか(jravan.db・leak-free)。

ユーザーの使い方=クロステーブルの「重複」列を見て脳内で交差判断している。
→ 各列の下位が『人気以上に来ない(独立シグナル)』か、重複を増やすと安全消去に
なるかを定量化する。単一条件で消すのではなく重複(stacking)が本質。

列(すべてレース前情報のみ=hindsight漏れ防止・大きいほど下位に符号を揃える):
  spurt 末脚    = 過去走の上がり3F順位比率の平均(高=遅)
  pos   平均位置 = 過去走の4角通過/頭数の平均(高=後方)
  ten   テン位置 = 過去走の1角通過/頭数の平均(高=テンが遅い/後方)
  form  近走着順 = 過去走の着順/頭数の平均(高=着順悪い)
  ctime 補正T   = 過去走の補正タイム(同(馬場,距離)中央値→当日馬場補正)のベスト(高=遅)
  bweight 馬体重 = 当日馬体重(小さいほど下位=符号反転)
  zogen 体重減   = 当日増減(マイナス=減=下位=符号反転)

実行: python scripts/elim_multicol_backtest.py
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
from statistics import median
from itertools import combinations
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')

# 過去走集計で作る列 と 当日属性の列
HIST_COLS = ['spurt', 'pos', 'ten', 'form', 'ctime']
CUR_COLS = ['bweight', 'zogen']
COLS = HIST_COLS + CUR_COLS
JP = {'spurt': '末脚', 'pos': '平均位置', 'ten': 'テン位置', 'form': '近走着順',
      'ctime': '補正T', 'bweight': '馬体重小', 'zogen': '体重減'}


def dk(y, m):
    try:
        return int(y) * 10000 + int(m)
    except Exception:
        return 0


def to_sec(t):
    s = ''.join(c for c in str(t) if c.isdigit())
    if not s:
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def build():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.monthday md, r.jyo jyo, r.ketto_num kt, "
        "r.chakujun ch, r.ninki nk, r.ato3f a3, r.corner1 c1, r.corner4 c4, r.time tm, "
        "r.bataiju bw, r.zogen zg, ra.surface sf, ra.kyori ki, ra.shusso_tosu st "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= 2014").fetchall()
    con.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    recs = []
    by_sk = defaultdict(list)
    for rk, rs in by_race.items():
        d = dk(rs[0]['y'], rs[0]['md'])
        n = rs[0]['st'] or len(rs)
        a3 = [(x['a3'], x['kt']) for x in rs if x['a3'] and x['a3'] > 0]
        a3.sort(key=lambda t: t[0])
        arank = {kt: (i + 1) / len(a3) for i, (_, kt) in enumerate(a3)} if a3 else {}
        for x in rs:
            if not x['ch'] or x['ch'] <= 0:
                continue
            sec = to_sec(x['tm'])
            rec = {'d': d, 'jyo': x['jyo'], 'sf': x['sf'], 'ki': x['ki'], 'kt': x['kt'],
                   'a3r': arank.get(x['kt']),
                   'c1r': (x['c1'] / n) if (x['c1'] and n) else None,
                   'c4r': (x['c4'] / n) if (x['c4'] and n) else None,
                   'chr': (x['ch'] / n) if n else None, 'sec': sec, 'corr': None}
            recs.append(rec)
            if sec:
                by_sk[(x['sf'], x['ki'])].append(sec)
    base_sk = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    by_dj = defaultdict(list)
    for r in recs:
        b = base_sk.get((r['sf'], r['ki']))
        r['rawdev'] = (r['sec'] - b) if (r['sec'] and b is not None) else None
        if r['rawdev'] is not None:
            by_dj[(r['d'], r['jyo'], r['sf'])].append(r['rawdev'])
    tb = {k: median(v) for k, v in by_dj.items() if v}
    for r in recs:
        if r['rawdev'] is not None:
            r['corr'] = r['rawdev'] - tb.get((r['d'], r['jyo'], r['sf']), 0.0)

    hist = defaultdict(list)
    for r in recs:
        hist[r['kt']].append(r)
    for k in hist:
        hist[k].sort(key=lambda z: z['d'])
    return by_race, hist


def pre(hist, kt, d, n=5, minr=2):
    h = hist.get(kt)
    if not h:
        return {c: None for c in HIST_COLS}
    past = [x for x in h if x['d'] < d][-n:]
    def avg(key):
        v = [x[key] for x in past if x[key] is not None]
        return (sum(v) / len(v)) if len(v) >= minr else None
    co = [x['corr'] for x in past if x['corr'] is not None]
    return {'spurt': avg('a3r'), 'pos': avg('c4r'), 'ten': avg('c1r'),
            'form': avg('chr'), 'ctime': (min(co) if len(co) >= minr else None)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--min_field', type=int, default=10)
    ap.add_argument('--k', type=int, default=3)
    args = ap.parse_args()

    print("読み込み・補正タイム/履歴構築中...")
    by_race, hist = build()

    pop_top3 = defaultdict(lambda: [0, 0])
    for rk, rs in by_race.items():
        if args.test_from <= int(rs[0]['y']) <= args.test_to:
            for r in rs:
                if r['nk'] and r['ch'] and r['ch'] > 0:
                    pop_top3[int(r['nk'])][0] += 1 if r['ch'] <= 3 else 0
                    pop_top3[int(r['nk'])][1] += 1
    base = {p: (s[0] / s[1] if s[1] else 0) for p, s in pop_top3.items()}

    K = args.k
    grp = defaultdict(lambda: [0, 0, 0.0])
    miss = defaultdict(lambda: [0, 0])
    elim_h = defaultdict(int)
    n_races = 0

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['y']) <= args.test_to):
            continue
        if len(rs) < args.min_field:
            continue
        d = dk(rs[0]['y'], rs[0]['md'])
        H = []
        for r in rs:
            if not r['nk'] or not r['ch'] or r['ch'] <= 0:
                continue
            m = pre(hist, r['kt'], d)
            # 当日属性(大きいほど下位に符号反転)
            m['bweight'] = (-(r['bw']) if (r['bw'] and r['bw'] > 0) else None)
            m['zogen'] = (-(r['zg']) if (r['zg'] is not None) else None)
            H.append({'pop': int(r['nk']), 't3': 1 if r['ch'] <= 3 else 0, **m})
        if len(H) < args.min_field:
            continue
        n_races += 1
        botset = {}
        for c in COLS:
            valid = [h for h in H if h[c] is not None]
            if len(valid) < args.min_field:
                botset[c] = None; continue
            valid.sort(key=lambda h: -h[c])
            botset[c] = set(id(h) for h in valid[:K])

        def agg(name, ids):
            if ids is None:
                return
            members = [h for h in H if id(h) in ids]
            g = grp[name]
            for h in members:
                g[0] += h['t3']; g[1] += 1; g[2] += base.get(h['pop'], 0)
            elim_h[name] += len(members)
            mm = miss[name]; mm[1] += 1
            if any(h['t3'] for h in members):
                mm[0] += 1

        for c in COLS:
            agg('単:' + JP[c], botset[c])
        # 重複(ワースト列数)→ union閾値
        cnt = defaultdict(int)
        for c in COLS:
            if botset[c]:
                for i in botset[c]:
                    cnt[i] += 1
        for thr in (2, 3, 4):
            agg(f'重複≥{thr}(ワースト{K})', {i for i, v in cnt.items() if v >= thr})

    def show(names, title):
        print(f"\n=== {title} (test{args.test_from}-{args.test_to}/{args.min_field}頭+/{n_races:,}R/K={K}) ===")
        print(f"{'条件':<20}{'延頭数':>7}{'複勝率':>8}{'人気期待':>9}{'残差':>8}{'誤消去率':>9}{'消去/R':>8}")
        for nm in names:
            g = grp.get(nm)
            if not g or g[1] == 0:
                print(f"{nm:<20}  (該当なし)"); continue
            t3, n, exp = g
            mm = miss[nm]
            fr = 100 * t3 / n; ex = 100 * exp / n
            missr = 100 * mm[0] / mm[1] if mm[1] else 0
            print(f"{nm:<20}{n:>7,}{fr:>7.1f}%{ex:>8.1f}%{fr-ex:>+7.1f}pp{missr:>8.1f}%{elim_h[nm]/n_races:>7.2f}")

    # 残差が負(=人気以上に来ない)ほど独立シグナル。priced-inは≈0。
    show(['単:' + JP[c] for c in COLS], '各列ワーストK 単独(独立シグナル判定=残差<0)')
    show([f'重複≥{t}(ワースト{K})' for t in (2, 3, 4)], '重複(ワースト列数)→複勝率(stacking)')
    print("\n[結論の読み方] 単独で残差が明確に負の列ほど『重複に足す価値』がある。"
          "重複が増えるほど複勝率↓・誤消去率↓なら、重複列は安全な消去の物差しになっている。")


if __name__ == '__main__':
    main()
