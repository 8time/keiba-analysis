# -*- coding: utf-8 -*-
"""マクリ指数の検証 — 3→4角で位置を押し上げる脚質は人気を超えて来るか?

末脚指数(上がり3F=直線の脚)に対し、マクリ=3〜4角で外を回して順位を上げる動き。
metric(リーク無し・過去走のみ): push = (corner3/頭数 − corner4/頭数) の直近5走平均。
  正=3角→4角で前へ押し上げ(マクリ傾向)。前で運ぶ逃げ先行は≈0、動かない追込も≈0。

末脚と同じ土俵で: レース内でマクリ指数top3の馬が、人気帯別に複勝率で人気を超えるか。
train2021-24/holdout2025・人気補正残差z。展開/位置はpriced-in既確定([[verified_tenkai_priced_in]])
のため、人気薄(6+)で独立エッジが出るかが焦点(末脚は6+×top3で+検証済)。

実行: python scripts/makuri_backtest.py
"""
import sys, io, os, sqlite3, math
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    print("読み込み中(2016-2025 JRA)...")
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.corner3 c3, r.corner4 c4, ra.shusso_tosu st, r.jyo jyo, ra.kyori ki "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INT) BETWEEN 2016 AND 2025 AND r.jyo<='10' "
        "AND r.chakujun>0 ORDER BY r.race_key").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    # 馬ごとの時系列 push 履歴
    hist = defaultdict(list)  # kt -> [(race_key, push)]
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)
    for rk, rs in by_race.items():
        n = rs[0]['st'] or len(rs)
        for r in rs:
            if r['c3'] and r['c4'] and n:
                push = (r['c3'] - r['c4']) / n   # 正=3→4角で前進
                hist[r['kt']].append((rk, push))
    for k in hist:
        hist[k].sort(key=lambda z: z[0])

    def pre_push(kt, rk, n=5, minr=2):
        h = hist.get(kt)
        if not h:
            return None
        past = [p for (k, p) in h if k < rk][-n:]
        return (sum(past) / len(past)) if len(past) >= minr else None

    # 人気別ベース(2021-25)
    popt = defaultdict(lambda: [0, 0])
    for r in rows:
        if 2021 <= int(r['y']) <= 2025 and r['nk']:
            popt[int(r['nk'])][0] += 1 if r['ch'] <= 3 else 0
            popt[int(r['nk'])][1] += 1
    base = {p: (s[0] / s[1] if s[1] else 0.25) for p, s in popt.items()}

    # 集計器
    def band(nk):
        return 'fav(1-3)' if nk <= 3 else 'mid(4-5)' if nk <= 5 else 'long(6+)'
    # マクリtop3 in race × 人気帯 → 複勝残差
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0]))  # period -> (band, is_top3makuri) -> [t3,n,exp]
    # 連続指標の五分位(マクリ強さそのもの)も
    quint = defaultdict(lambda: [0, 0, 0.0])  # (period, qbucket, band) 省略、まずtop3で

    for rk, rs in by_race.items():
        yr = int(rs[0]['y'])
        if yr < 2021:
            continue
        period = 'train' if yr <= 2024 else 'holdout'
        vals = []
        for r in rs:
            if not r['nk'] or int(r['nk']) > 90 or not r['ch']:
                continue
            mp = pre_push(r['kt'], rk)
            vals.append((r, mp))
        ranked = [(r, mp) for (r, mp) in vals if mp is not None]
        if len(ranked) < 8:
            continue
        ranked.sort(key=lambda t: -t[1])   # マクリ強い順
        top3set = {id(r) for (r, _) in ranked[:3]}
        for (r, mp) in vals:
            if mp is None:
                continue
            nk = int(r['nk'])
            b = band(nk)
            is_top = id(r) in top3set
            a = agg[period][(b, is_top)]
            a[0] += 1 if r['ch'] <= 3 else 0
            a[1] += 1
            a[2] += base.get(nk, 0.25)

    def show(period):
        print(f"\n=== {period}: マクリ指数top3(レース内) × 人気帯 → 複勝残差 ===")
        print(f"{'人気帯':<10}{'マクリ':<8}{'n':>8}{'複勝率':>8}{'期待':>8}{'残差':>9}{'z':>7}")
        for b in ('fav(1-3)', 'mid(4-5)', 'long(6+)'):
            for is_top, lbl in ((True, 'top3'), (False, '非top3')):
                a = agg[period][(b, is_top)]
                t3, n, exp = a
                if n < 100:
                    continue
                e = exp / n
                z = (t3 - exp) / math.sqrt(n * e * (1 - e)) if 0 < e < 1 else 0
                print(f"{b:<10}{lbl:<8}{n:>8,}{100*t3/n:>7.1f}%{100*e:>7.1f}%{100*(t3/n-e):>+8.2f}pp{z:>+7.1f}")

    show('train')
    show('holdout')

    # ── コース小回り/大回り分割(マクリは小回り限定説の検証) × 6番人気以下 ──
    SMALL = {'02', '03', '06', '10'}  # 函館/福島/中山/小倉

    def course_run(y0, y1, small):
        a = {True: [0, 0, 0.0], False: [0, 0, 0.0]}
        for rk, rs in by_race.items():
            yr = int(rs[0]['y'])
            if not (y0 <= yr <= y1):
                continue
            insmall = str(rs[0]['jyo']).zfill(2) in SMALL
            if small != insmall:
                continue
            vals = [(r, pre_push(r['kt'], rk)) for r in rs if r['nk'] and int(r['nk']) <= 90 and r['ch']]
            ranked = [(r, m) for r, m in vals if m is not None]
            if len(ranked) < 8:
                continue
            ranked.sort(key=lambda t: -t[1])
            top = {id(r) for r, _ in ranked[:3]}
            for r, m in vals:
                if m is None or int(r['nk']) < 6:
                    continue
                g = a[id(r) in top]
                g[0] += 1 if r['ch'] <= 3 else 0
                g[1] += 1
                g[2] += base.get(int(r['nk']), 0.25)
        return a

    print("\n=== 6番人気以下 × マクリtop3: 小回り(函館/福島/中山/小倉) vs 大回り ===")
    for small, nm in ((True, '小回り'), (False, '大回り')):
        for y0, y1, tag in ((2021, 2024, 'train'), (2025, 2025, 'hold ')):
            a = course_run(y0, y1, small)
            for is_top, lbl in ((True, 'マクリtop3'), (False, '非top3')):
                t3, n, exp = a[is_top]
                if n < 100:
                    continue
                e = exp / n
                z = (t3 - exp) / math.sqrt(n * e * (1 - e))
                print(f"  [{nm}]{tag} {lbl:<9} n={n:>6,} 複勝{100*t3/n:5.1f}% 残差{100*(t3/n-e):+6.2f}pp z={z:+.1f}")

    print("\n[結論(2026-07-04)] マクリ指数=priced-inで非採用。人気薄(6+)×マクリtop3の残差は"
          "全体+0.4pp/z<2、最良スライス(小回り)でも+1.2pp/holdout z+1.7かつ『非top3(=コーナー履歴あり"
          "の他の長shot)』の+0.8〜0.9ppを有意には超えない=独立エッジなし。末脚(上がり=速度)とは異なり"
          "マクリ(位置押上=展開)は市場に織込み済み。列追加せず。")


if __name__ == '__main__':
    main()
