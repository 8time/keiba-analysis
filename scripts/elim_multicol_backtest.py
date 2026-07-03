# -*- coding: utf-8 -*-
"""消去クロス強化・第2弾 — 複数の"強適列"の下位を交差/積み上げすると
どれが安全に3頭以上消せるか(jravan.db・leak-free)。

対象列(すべてレース以前の過去走のみ=hindsight漏れ防止):
  spurt 末脚    = 過去走の上がり3F順位比率の平均(高=遅)
  pos   平均位置 = 過去走の4角通過/頭数の平均(高=後方)
  form  近走着順 = 過去走の着順/頭数の平均(高=着順悪い)
  ctime 補正T   = 過去走の補正タイム(baseline=同(馬場,距離)中央値→当日馬場補正)の
                  ベスト(最速)。下位=そのベストが遅い側(値が大)。

各列で"レース内ワースト3頭"を出し、単独/全ペア交差/『N列以上でワースト』の
複勝率・人気残差・誤消去率(3着内馬を消す率)・平均消去頭数/レースを比較する。

実行: python scripts/elim_multicol_backtest.py
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
from statistics import median
from itertools import combinations
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')

COLS = ['spurt', 'pos', 'form', 'ctime']
JP = {'spurt': '末脚', 'pos': '平均位置', 'form': '近走着順', 'ctime': '補正T'}


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
        "r.bamei nm, r.chakujun ch, r.ninki nk, r.ato3f a3, r.corner4 c4, r.time tm, "
        "ra.surface sf, ra.kyori ki, ra.shusso_tosu st "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= 2014").fetchall()
    con.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    # 補正タイム: baseline(surface,kyori)中央値 → raw_dev → track_bias(day,jyo,surf)中央値 → corrected
    recs = []  # per run dict
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
            rec = {'rk': rk, 'd': d, 'jyo': x['jyo'], 'sf': x['sf'], 'ki': x['ki'],
                   'kt': x['kt'], 'a3r': arank.get(x['kt']),
                   'c4r': (x['c4'] / n) if (x['c4'] and n) else None,
                   'chr': (x['ch'] / n) if n else None, 'sec': sec, 'corr': None}
            recs.append(rec)
            if sec:
                by_sk[(x['sf'], x['ki'])].append(sec)
    base_sk = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    by_dj = defaultdict(list)
    for r in recs:
        b = base_sk.get((r['sf'], r['ki']))
        if r['sec'] and b is not None:
            r['rawdev'] = r['sec'] - b
            by_dj[(r['d'], r['jyo'], r['sf'])].append(r['rawdev'])
        else:
            r['rawdev'] = None
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
        return {c: None for c in COLS}
    past = [x for x in h if x['d'] < d][-n:]
    ar = [x['a3r'] for x in past if x['a3r'] is not None]
    cr = [x['c4r'] for x in past if x['c4r'] is not None]
    fr = [x['chr'] for x in past if x['chr'] is not None]
    co = [x['corr'] for x in past if x['corr'] is not None]
    return {
        'spurt': (sum(ar) / len(ar)) if len(ar) >= minr else None,
        'pos':   (sum(cr) / len(cr)) if len(cr) >= minr else None,
        'form':  (sum(fr) / len(fr)) if len(fr) >= minr else None,
        'ctime': (min(co)) if len(co) >= minr else None,  # ベスト補正(最速)。下位=大
    }


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
    # 集計器: name -> [top3, n, exp]  / miss: name -> [races_with_placer, races] / elim頭数
    grp = defaultdict(lambda: [0, 0, 0.0])
    miss = defaultdict(lambda: [0, 0])
    elim_horses = defaultdict(int)  # 消去した延べ頭数
    n_races = 0

    higher_worse = {'spurt': True, 'pos': True, 'form': True, 'ctime': True}

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
            H.append({'pop': int(r['nk']), 't3': 1 if r['ch'] <= 3 else 0, **m})
        if len(H) < args.min_field:
            continue
        n_races += 1
        # 各列のワーストK集合(値が大きい方からK・欠損は除外)
        botset = {}
        for c in COLS:
            valid = [h for h in H if h[c] is not None]
            if len(valid) < args.min_field:
                botset[c] = None
                continue
            valid.sort(key=lambda h: -h[c])
            botset[c] = set(id(h) for h in valid[:K])

        def agg(name, ids, placer_capable=True):
            if ids is None:
                return
            members = [h for h in H if id(h) in ids]
            g = grp[name]
            for h in members:
                g[0] += h['t3']; g[1] += 1; g[2] += base.get(h['pop'], 0)
            elim_horses[name] += len(members)
            mm = miss[name]
            mm[1] += 1
            if any(h['t3'] for h in members):
                mm[0] += 1

        # 単独
        for c in COLS:
            agg('単:' + JP[c], botset[c])
        # 全ペア交差
        for a, b in combinations(COLS, 2):
            if botset[a] is not None and botset[b] is not None:
                agg(f'交差:{JP[a]}×{JP[b]}', botset[a] & botset[b])
        # 『N列以上でワースト』union(重み=ワースト列数)
        cnt = defaultdict(int)
        for c in COLS:
            if botset[c]:
                for i in botset[c]:
                    cnt[i] += 1
        for thr in (2, 3):
            ids = {i for i, v in cnt.items() if v >= thr}
            agg(f'≥{thr}列でワースト{K}', ids)

    def show(names, title):
        print(f"\n=== {title} (test{args.test_from}-{args.test_to}/{args.min_field}頭+/{n_races:,}R/K={K}) ===")
        print(f"{'条件':<22}{'延頭数':>7}{'複勝率':>8}{'人気期待':>9}{'残差':>8}{'誤消去率':>9}{'消去/R':>8}")
        for nm in names:
            g = grp.get(nm)
            if not g or g[1] == 0:
                print(f"{nm:<22}  (該当なし)"); continue
            t3, n, exp = g
            mm = miss[nm]
            fr = 100 * t3 / n
            ex = 100 * exp / n
            missr = 100 * mm[0] / mm[1] if mm[1] else 0
            per = elim_horses[nm] / n_races
            print(f"{nm:<22}{n:>7,}{fr:>7.1f}%{ex:>8.1f}%{fr-ex:>+7.1f}pp{missr:>8.1f}%{per:>7.2f}")

    show(['単:' + JP[c] for c in COLS], '単独列ワーストK(参考)')
    show([f'交差:{JP[a]}×{JP[b]}' for a, b in combinations(COLS, 2)], '2列交差ワーストK')
    show([f'≥2列でワースト{K}', f'≥3列でワースト{K}'], 'N列以上でワースト(積み上げ union)')
    print("\n[読み方] 残差<0=人気以上に来ない。誤消去率=その群を消したレースで3着内馬を含んだ率"
          "(低いほど安全)。消去/R=1レース平均で消える頭数。安全に3頭消したいなら"
          "『誤消去率が低くかつ消去/Rが大きい』条件を選ぶ。")


if __name__ == '__main__':
    main()
