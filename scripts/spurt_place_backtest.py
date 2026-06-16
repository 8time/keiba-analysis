# -*- coding: utf-8 -*-
"""
末脚指数 × 複勝ROI 追検証 ＋ 単複乖離との重ね掛け
─────────────────────────────────────────────
step1: spurt_index_backtest で出た「6番人気以下×末脚top3 = 複勝率13.4%」を
       payouts(複勝)の実配当に当て、複勝ROIがプラス圏か確定させる。
step2: odds(place=事前複勝オッズ)から単複乖離(単≥dan × 複≤fuku)を判定し、
       末脚segと重ねて上積みがあるか見る。※place oddsは収録レースのみ。
"""
import sys, io, os, sqlite3, statistics, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2015)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--k', type=int, default=3)
    ap.add_argument('--top', type=int, default=3)
    ap.add_argument('--ninki_ana', type=int, default=6)
    ap.add_argument('--min_field', type=int, default=8)
    ap.add_argument('--dan', type=float, default=10.0, help='単複乖離:単勝オッズ下限')
    ap.add_argument('--fuku', type=float, default=3.0, help='単複乖離:複勝オッズ上限')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    print(f"読み込み... results(year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, umaban, chakujun, ninki, win_odds, ato3f "
        "FROM results WHERE CAST(year AS INTEGER)>=? AND ato3f IS NOT NULL AND ato3f>0",
        (args.train_from,)).fetchall()
    by_race = {}
    for r in rows:
        by_race.setdefault(r['race_key'], []).append(r)

    # 末脚偏差
    spurt, hist = {}, {}
    for rk, rs in by_race.items():
        vals = [r['ato3f'] for r in rs]
        if len(vals) < 5:
            continue
        m, sd = statistics.mean(vals), statistics.pstdev(vals)
        if sd <= 0:
            continue
        for r in rs:
            dev = (m - r['ato3f']) / sd
            spurt[(rk, r['ketto_num'])] = dev
            hist.setdefault(r['ketto_num'], []).append((date_key(r['year'], r['monthday']), dev))
    for k in hist:
        hist[k].sort()

    def pidx(ket, dk, K):
        h = hist.get(ket)
        if not h:
            return None
        past = [d for (d2, d) in h if d2 < dk]
        return sum(past[-K:]) / len(past[-K:]) if past else None

    # 複勝配当: place_pay[(race_key, umaban)] = payout(100円あたり)
    print("読み込み... payouts(複勝)")
    place_pay = {}
    for r in con.execute("SELECT race_key, combo, payout FROM payouts WHERE bet_type='複勝'"):
        try:
            place_pay[(r['race_key'], int(r['combo']))] = float(r['payout'])
        except Exception:
            pass

    # 事前複勝オッズ(単複乖離用): place_odds[(race_key, umaban)] = odds
    print("読み込み... odds(place)")
    place_odds = {}
    for r in con.execute("SELECT race_key, combo, odds FROM odds WHERE bet_type='place'"):
        try:
            place_odds[(r['race_key'], int(r['combo']))] = float(r['odds'])
        except Exception:
            pass

    races = con.execute(
        "SELECT race_key, year, monthday FROM races WHERE CAST(year AS INTEGER) BETWEEN ? AND ?",
        (args.test_from, args.test_to)).fetchall()

    # 集計器
    def newacc():
        return {'n': 0, 'win': 0, 'place': 0, 'tan_ret': 0.0, 'fuku_ret': 0.0, 'fuku_n': 0}

    seg = newacc()       # 末脚top × 人気薄
    base = newacc()      # 人気薄全体
    seg_div = newacc()   # 末脚top × 人気薄 × 単複乖離
    base_div = newacc()  # 人気薄 × 単複乖離(末脚不問)
    div_cov = 0          # place odds保有レース数

    n_race = 0
    for race in races:
        rk = race['race_key']
        dk = date_key(race['year'], race['monthday'])
        rs = by_race.get(rk)
        if not rs:
            continue
        cand = []
        for r in rs:
            idx = pidx(r['ketto_num'], dk, args.k)
            if idx is None:
                continue
            cand.append({'um': r['umaban'], 'idx': idx, 'chaku': r['chakujun'],
                         'ninki': r['ninki'], 'odds': r['win_odds']})
        if len(cand) < args.min_field:
            continue
        n_race += 1
        for rank, c in enumerate(sorted(cand, key=lambda x: -x['idx']), 1):
            c['idx_rank'] = rank
        has_po = any((rk, c['um']) in place_odds for c in cand)
        if has_po:
            div_cov += 1

        for c in cand:
            if not (c['ninki'] and c['ninki'] >= args.ninki_ana):
                continue
            won = (c['chaku'] == 1)
            placed = bool(c['chaku'] and c['chaku'] <= 3)
            fpay = place_pay.get((rk, c['um']))
            po = place_odds.get((rk, c['um']))
            div = (c['odds'] and c['odds'] >= args.dan and po is not None and po <= args.fuku)

            def add(acc):
                acc['n'] += 1
                if won:
                    acc['win'] += 1
                    if c['odds']:
                        acc['tan_ret'] += c['odds'] * 100
                if placed:
                    acc['place'] += 1
                # 複勝ROIは複勝配当が分かる対象のみ(payout収録)を分母に
                acc['fuku_n'] += 1
                if placed and fpay:
                    acc['fuku_ret'] += fpay

            add(base)
            if c['idx_rank'] <= args.top:
                add(seg)
            if div:
                add(base_div)
                if c['idx_rank'] <= args.top:
                    add(seg_div)

    def show(name, a):
        n = a['n'] or 1
        fn = a['fuku_n'] or 1
        print(f"  {name}: 点数{a['n']}  勝率{100*a['win']/n:.1f}%  "
              f"複勝率{100*a['place']/n:.1f}%  単ROI{100*a['tan_ret']/(n*100):.1f}%  "
              f"複ROI{100*a['fuku_ret']/(fn*100):.1f}%")

    print("\n" + "=" * 70)
    print(f"検証レース{n_race:,} / place odds収録{div_cov:,}R ({100*div_cov//max(1,n_race)}%)")
    print("=" * 70)
    print(f"【step1 複勝ROI】 人気薄={args.ninki_ana}番人気以下")
    show(f"末脚top{args.top}seg", seg)
    show("人気薄ベース", base)
    print(f"\n【step2 単複乖離(単≥{args.dan}×複≤{args.fuku})重ね掛け】※place odds収録レースのみ")
    show("乖離×末脚top", seg_div)
    show("乖離のみ(末脚不問)", base_div)
    print("\n→ 末脚segの複ROIが人気薄ベース・100%を上回るか / 乖離重ねで更に上積みするかを見る")
    con.close()


if __name__ == '__main__':
    main()
