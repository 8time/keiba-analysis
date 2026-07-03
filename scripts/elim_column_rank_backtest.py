# -*- coding: utf-8 -*-
"""消去クロス強化検証 — 『強適ランキング表の 上り3F / 平均位置 の“列内下位”馬は
3着内に来ないか?』をjravan.dbで検証(leak-free)。

ユーザー要望: 消去クロスをもっと多くのチェック項目でふるいたい。ボーダー残しで
3頭戻すなら3頭以上消したい。列(上り3F・平均位置)の“下位の馬”は高確率で
3着圏外か? を1日分＋全期間で調べる。

方針(結果リーク禁止):
  各馬の指標は「そのレース以前の過去走のみ」から算出。
   - 末脚指標  = 過去走の上がり3F順位比率の平均(0=最速…1=最遅)。高いほど末脚下位。
   - 位置指標  = 過去走の4角通過/頭数の平均(0=先頭…1=最後方)。高いほど後方。
  レース内で各指標により順位付けし、「列内ワーストK頭」の複勝率(3着内率)を測る。
  正直指標として人気期待複勝率との残差も併記(priced-inか判別)。
  さらに『ワーストK頭を消したとき、実際の3着内馬を誤って消す率(取りこぼし)』を測る。

実行: python scripts/elim_column_rank_backtest.py [--single_day YYYYMMDD]
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def dk(y, m):
    try:
        return int(y) * 10000 + int(m)
    except Exception:
        return 0


def build():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.monthday md, r.jyo jyo, r.ketto_num kt, "
        "r.bamei nm, r.chakujun ch, r.ninki nk, r.ato3f a3, r.corner4 c4, "
        "ra.shusso_tosu st "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= 2014").fetchall()
    con.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    # 各レースでその馬の(上がり順位比率, 4角比率)を記録し、馬ごとの時系列履歴を作る
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        d = dk(rs[0]['y'], rs[0]['md'])
        n = rs[0]['st'] or len(rs)
        a3 = [(x['a3'], x['kt']) for x in rs if x['a3'] and x['a3'] > 0]
        a3.sort(key=lambda t: t[0])
        arank = {kt: (i + 1) / len(a3) for i, (_, kt) in enumerate(a3)} if a3 else {}
        for x in rs:
            if not x['ch'] or x['ch'] <= 0:
                continue
            c4r = (x['c4'] / n) if (x['c4'] and n) else None
            hist[x['kt']].append({'dk': d, 'a3r': arank.get(x['kt']), 'c4r': c4r})
    for k in hist:
        hist[k].sort(key=lambda z: z['dk'])
    return by_race, hist


def pre_metrics(hist, kt, d, n=5, min_runs=2):
    """レース日dより前の過去n走から (末脚指標, 位置指標) を返す。不足はNone。"""
    h = hist.get(kt)
    if not h:
        return None, None
    past = [x for x in h if x['dk'] < d][-n:]
    ar = [x['a3r'] for x in past if x['a3r'] is not None]
    cr = [x['c4r'] for x in past if x['c4r'] is not None]
    spurt = (sum(ar) / len(ar)) if len(ar) >= min_runs else None
    pos = (sum(cr) / len(cr)) if len(cr) >= min_runs else None
    return spurt, pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--min_field', type=int, default=10)
    ap.add_argument('--single_day', type=str, default='')
    args = ap.parse_args()

    print("読み込み・履歴構築中...")
    by_race, hist = build()

    # 人気別ベース複勝率(test期間)
    pop_top3 = defaultdict(lambda: [0, 0])
    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['y']) <= args.test_to):
            continue
        for r in rs:
            if r['nk'] and r['ch'] and r['ch'] > 0:
                pop_top3[int(r['nk'])][0] += 1 if r['ch'] <= 3 else 0
                pop_top3[int(r['nk'])][1] += 1
    base = {p: (s[0] / s[1] if s[1] else 0) for p, s in pop_top3.items()}

    # ── 列内ワースト順位ごとの複勝率(gradient) ──
    # rankbkt[metric][within_race_worst_rank] = [top3, n, exp]
    grad = {'spurt': defaultdict(lambda: [0, 0, 0.0]),
            'pos':   defaultdict(lambda: [0, 0, 0.0])}
    # ワーストK群 & 交差 & 取りこぼし集計
    botK = {'spurt': {1: [0, 0, 0.0], 2: [0, 0, 0.0], 3: [0, 0, 0.0]},
            'pos':   {1: [0, 0, 0.0], 2: [0, 0, 0.0], 3: [0, 0, 0.0]}}
    cross = {1: [0, 0, 0.0], 2: [0, 0, 0.0], 3: [0, 0, 0.0]}  # 両方でワーストK
    # 取りこぼし: レース単位、ワースト3(各指標)に3着内馬が含まれた率
    miss = {'spurt': [0, 0], 'pos': [0, 0], 'cross': [0, 0]}  # [races_with_placer_in_botK, races]
    n_races = 0

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['y']) <= args.test_to):
            continue
        if len(rs) < args.min_field:
            continue
        d = dk(rs[0]['y'], rs[0]['md'])
        horses = []
        for r in rs:
            if not r['nk'] or not r['ch'] or r['ch'] <= 0:
                continue
            sp, po = pre_metrics(hist, r['kt'], d)
            horses.append({'kt': r['kt'], 'pop': int(r['nk']),
                           't3': 1 if r['ch'] <= 3 else 0, 'sp': sp, 'po': po})
        # 各指標で履歴のある馬のみ順位付け(ワースト=大きい値=先頭)
        for key, fld in (('spurt', 'sp'), ('pos', 'po')):
            ranked = [h for h in horses if h[fld] is not None]
            if len(ranked) < args.min_field:
                continue
            ranked.sort(key=lambda h: -h[fld])  # 0=最ワースト
            for i, h in enumerate(ranked):
                g = grad[key][i + 1]  # within-race worst-rank(1=最下位)
                g[0] += h['t3']; g[1] += 1; g[2] += base.get(h['pop'], 0)
            for K in (1, 2, 3):
                grp = ranked[:K]
                b = botK[key][K]
                for h in grp:
                    b[0] += h['t3']; b[1] += 1; b[2] += base.get(h['pop'], 0)
                # 取りこぼし(K=3のみ集計)
                if K == 3:
                    miss[key][1] += 1
                    if any(h['t3'] for h in grp):
                        miss[key][0] += 1
        # 交差(両指標でワーストK)
        rk_sp = [h for h in horses if h['sp'] is not None]
        rk_po = [h for h in horses if h['po'] is not None]
        if len(rk_sp) >= args.min_field and len(rk_po) >= args.min_field:
            rk_sp.sort(key=lambda h: -h['sp'])
            rk_po.sort(key=lambda h: -h['po'])
            for K in (1, 2, 3):
                setp = {id(h) for h in rk_sp[:K]}
                grp = [h for h in rk_po[:K] if id(h) in setp]
                c = cross[K]
                for h in grp:
                    c[0] += h['t3']; c[1] += 1; c[2] += base.get(h['pop'], 0)
                if K == 3:
                    miss['cross'][1] += 1
                    if grp and any(h['t3'] for h in grp):
                        miss['cross'][0] += 1
        n_races += 1

    def line(lbl, s):
        t3, n, exp = s
        if n == 0:
            print(f"{lbl:<22} n=0"); return
        print(f"{lbl:<22}{n:>8,}{100*t3/n:>8.1f}%{100*exp/n:>9.1f}%{100*(t3-exp)/n:>+8.1f}pp")

    print(f"\n=== レース内ワースト順位ごとの複勝率 (test {args.test_from}-{args.test_to}, "
          f"{args.min_field}頭以上, {n_races:,}レース) ===")
    print(f"{'':<22}{'n':>8}{'複勝率':>8}{'人気期待':>9}{'残差':>8}")
    print("[上り3F 列] ワースト=末脚が最も遅い側")
    for r in range(1, 5):
        line(f"  ワースト{r}番目", grad['spurt'][r])
    print("[平均位置 列] ワースト=最も後方")
    for r in range(1, 5):
        line(f"  ワースト{r}番目", grad['pos'][r])

    print(f"\n=== ワーストK頭グループの複勝率(消去候補) ===")
    print(f"{'':<22}{'n':>8}{'複勝率':>8}{'人気期待':>9}{'残差':>8}")
    for key, jp in (('spurt', '上り3F'), ('pos', '平均位置')):
        for K in (1, 2, 3):
            line(f"{jp} ワースト{K}頭", botK[key][K])
    print("[交差] 上り3F・平均位置 の両方でワーストK")
    for K in (1, 2, 3):
        line(f"  両列ワースト{K}", cross[K])

    print(f"\n=== 取りこぼし: ワースト3頭を消すと3着内馬を誤消去する率(レース単位) ===")
    for key, jp in (('spurt', '上り3F'), ('pos', '平均位置'), ('cross', '両列交差')):
        m = miss[key]
        if m[1]:
            print(f"  {jp:<10} {m[0]:,}/{m[1]:,}レース = {100*m[0]/m[1]:.1f}% で3着内馬を含む"
                  f"(=残り{100-100*m[0]/m[1]:.1f}%は安全に消せた)")

    # ── 1日分の具体例 ──
    day = args.single_day
    if not day:
        # test期間内で最もレース数の多い日を自動選択(JRAのみ)
        daycnt = defaultdict(set)
        for rk, rs in by_race.items():
            if args.test_from <= int(rs[0]['y']) <= args.test_to and rs[0]['jyo'] <= '10':
                daycnt[dk(rs[0]['y'], rs[0]['md'])].add(rk)
        if daycnt:
            day = str(max(daycnt, key=lambda k: len(daycnt[k])))
    if day:
        print(f"\n=== 1日分の具体例: {day} (上り3F列ワースト3頭が3着内に来たか) ===")
        d = int(day)
        races = [(rk, rs) for rk, rs in by_race.items()
                 if dk(rs[0]['y'], rs[0]['md']) == d and rs[0]['jyo'] <= '10' and len(rs) >= args.min_field]
        races.sort(key=lambda t: t[0])
        tot_bot = tot_bot_t3 = 0
        for rk, rs in races[:24]:
            horses = []
            for r in rs:
                if not r['ch'] or r['ch'] <= 0:
                    continue
                sp, po = pre_metrics(hist, r['kt'], d)
                horses.append({'nm': r['nm'], 'pop': r['nk'], 'ch': r['ch'], 'sp': sp, 'po': po})
            ranked = [h for h in horses if h['sp'] is not None]
            if len(ranked) < args.min_field:
                continue
            ranked.sort(key=lambda h: -h['sp'])
            bot = ranked[:3]
            got = [h for h in bot if h['ch'] <= 3]
            tot_bot += len(bot); tot_bot_t3 += len(got)
            names = ' / '.join(f"{h['nm']}({h['pop']}人{h['ch']}着)" for h in bot)
            flag = '❗3着内含む' if got else 'OK全消し正解'
            print(f"  {rk[-2:]}R 末脚ワースト3: {names}  → {flag}")
        if tot_bot:
            print(f"  この日: 末脚ワースト3頭 計{tot_bot}頭中 {tot_bot_t3}頭が3着内"
                  f"({100*tot_bot_t3/tot_bot:.1f}%)")


if __name__ == '__main__':
    main()
