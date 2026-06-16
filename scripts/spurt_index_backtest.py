# -*- coding: utf-8 -*-
"""
末脚指数（上がり3F偏差）バックテスト
─────────────────────────────────────────────
目的: 「指数が高いのに人気がない馬＝妙味」(過小評価の勝ち馬)を、
      jravan.db の results.ato3f(個別上がり3F) から作った"末脚偏差"で拾えるか検証。

末脚偏差 spurt_dev: 各レース内で上がり3Fを標準化（速い=正）。
                   → そのレースのペースに依存する絶対値ではなく「その日その馬が
                      他馬よりどれだけ速く上がったか」を表す相対指標。
末脚指数(予測値): 対象レースより前の、その馬の直近K走の spurt_dev 平均。

検証指標:
  - recall@7         : 各レースの実勝ち馬が、末脚指数の上位7頭に入る割合
  - 過小評価捕捉率   : 穴(6番人気以下)で勝った馬のうち、末脚指数が上位だった割合
  - 妙味ゾーンROI    : 「末脚指数 上位 × 人気薄」segment の単勝回収率・複勝率
  各指標は人気のみ/ランダムのベースラインと比較。
"""
import sys, io, os, sqlite3, statistics, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(year, monthday):
    try:
        return int(year) * 10000 + int(monthday)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2015, help='履歴構築の開始年')
    ap.add_argument('--test_from', type=int, default=2021, help='検証対象レースの開始年')
    ap.add_argument('--test_to', type=int, default=2025, help='検証対象レースの終了年')
    ap.add_argument('--k', type=int, default=3, help='末脚指数に使う直近走数')
    ap.add_argument('--top', type=int, default=3, help='妙味判定の末脚指数ランク上限')
    ap.add_argument('--ninki_ana', type=int, default=6, help='人気薄(穴)の下限人気')
    ap.add_argument('--min_field', type=int, default=8, help='検証対象とする最低出走頭数(指数保有)')
    ap.add_argument('--odds_lo', type=float, default=0.0, help='妙味segの単勝オッズ下限(0=無制限)')
    ap.add_argument('--odds_hi', type=float, default=9999.0, help='妙味segの単勝オッズ上限')
    ap.add_argument('--thr', type=float, default=None,
                    help='指定すると妙味segを「末脚指数>=thr(絶対値)」で判定(ライブ用しきい値検証)')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # ── 1. 全結果を読み、レース内で上がり3Fを標準化して spurt_dev を作る ──
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, chakujun, ninki, win_odds, ato3f "
        "FROM results WHERE CAST(year AS INTEGER) >= ? AND ato3f IS NOT NULL AND ato3f>0",
        (args.train_from,)).fetchall()
    print(f"  上がり3Fありの結果: {len(rows):,}行")

    by_race = {}
    for r in rows:
        by_race.setdefault(r['race_key'], []).append(r)

    # spurt_dev[(race_key, ketto)] = z (faster last-3F => higher)
    spurt = {}
    horse_hist = {}  # ketto -> [(date_key, spurt_dev)]
    for rk, rs in by_race.items():
        vals = [r['ato3f'] for r in rs]
        if len(vals) < 5:
            continue
        m = statistics.mean(vals)
        sd = statistics.pstdev(vals)
        if sd <= 0:
            continue
        for r in rs:
            dev = (m - r['ato3f']) / sd      # 速い(小さいato3f)ほど正
            spurt[(rk, r['ketto_num'])] = dev
            dk = date_key(r['year'], r['monthday'])
            horse_hist.setdefault(r['ketto_num'], []).append((dk, dev))
    for k in horse_hist:
        horse_hist[k].sort()
    print(f"  spurt_dev算出: {len(spurt):,}件 / 馬{len(horse_hist):,}頭")

    def prior_index(ketto, dk, K):
        """dk より前の直近K走の spurt_dev 平均。なければ None。"""
        h = horse_hist.get(ketto)
        if not h:
            return None
        past = [d for (d2, d) in h if d2 < dk]
        if not past:
            return None
        return sum(past[-K:]) / len(past[-K:])

    # ── 2. 検証: 対象年のレースごとに末脚指数でランク付けして指標集計 ──
    races = con.execute(
        "SELECT race_key, year, monthday FROM races "
        "WHERE CAST(year AS INTEGER) BETWEEN ? AND ?",
        (args.test_from, args.test_to)).fetchall()
    print(f"検証対象レース: {len(races):,} ({args.test_from}-{args.test_to})\n")

    n_race = 0
    rec7_idx = 0          # 末脚指数 top7 に勝ち馬
    rec7_pop = 0          # 人気 top7 に勝ち馬(ベースライン)
    rec7_rand_sum = 0.0   # ランダム期待値ベースライン
    # 過小評価(穴勝ち)捕捉
    ana_win = 0
    ana_win_caught = 0    # その穴勝ち馬の末脚指数ランクが top 以内
    # 妙味ゾーン(末脚top × 人気薄)
    seg_n = seg_win = seg_place = 0
    seg_ret = 0.0
    # ベースライン: 人気薄全体
    base_n = base_win = base_place = 0
    base_ret = 0.0

    for race in races:
        rk = race['race_key']
        dk = date_key(race['year'], race['monthday'])
        rs = by_race.get(rk)
        if not rs:
            continue
        cand = []
        for r in rs:
            idx = prior_index(r['ketto_num'], dk, args.k)
            if idx is None:
                continue
            cand.append({'ketto': r['ketto_num'], 'idx': idx,
                         'chaku': r['chakujun'], 'ninki': r['ninki'],
                         'odds': r['win_odds']})
        if len(cand) < args.min_field:
            continue
        n_race += 1
        field = len(cand)

        # ランク付け
        cand_by_idx = sorted(cand, key=lambda x: -x['idx'])
        for rank, c in enumerate(cand_by_idx, 1):
            c['idx_rank'] = rank

        winner = next((c for c in cand if c['chaku'] == 1), None)

        # recall@7
        rec7_rand_sum += min(7, field) / field
        if winner:
            if winner['idx_rank'] <= 7:
                rec7_idx += 1
            if winner['ninki'] and winner['ninki'] <= 7:
                rec7_pop += 1
            # 過小評価捕捉
            if winner['ninki'] and winner['ninki'] >= args.ninki_ana:
                ana_win += 1
                if winner['idx_rank'] <= args.top:
                    ana_win_caught += 1

        # 妙味ゾーン: 末脚指数 top以内 × 人気薄(×任意でオッズ帯)
        for c in cand:
            ana = c['ninki'] and c['ninki'] >= args.ninki_ana
            if not ana:
                continue
            if c['odds'] is None or not (args.odds_lo <= c['odds'] <= args.odds_hi):
                continue
            base_n += 1
            won = (c['chaku'] == 1)
            placed = (c['chaku'] and c['chaku'] <= 3)
            if won:
                base_win += 1
                if c['odds']:
                    base_ret += c['odds'] * 100
            if placed:
                base_place += 1
            in_seg = (c['idx'] >= args.thr) if args.thr is not None else (c['idx_rank'] <= args.top)
            if in_seg:
                seg_n += 1
                if won:
                    seg_win += 1
                    if c['odds']:
                        seg_ret += c['odds'] * 100
                if placed:
                    seg_place += 1

    # ── 3. 出力 ──
    def pct(a, b):
        return f"{100*a/b:.1f}%" if b else "-"

    print("=" * 66)
    print(f"■ 検証レース数(指数保有{args.min_field}頭以上): {n_race:,}")
    print("=" * 66)
    print("【recall@7：勝ち馬が上位7頭に入る割合】")
    print(f"  末脚指数ランク   : {pct(rec7_idx, n_race)}  ({rec7_idx}/{n_race})")
    print(f"  人気ランク(基準) : {pct(rec7_pop, n_race)}  ({rec7_pop}/{n_race})")
    print(f"  ランダム期待値   : {pct(rec7_rand_sum, n_race)}")
    print()
    print(f"【過小評価(穴={args.ninki_ana}番人気以下)で勝った馬の捕捉】")
    print(f"  穴で勝った数        : {ana_win}")
    print(f"  うち末脚指数 top{args.top}内 : {ana_win_caught}  捕捉率 {pct(ana_win_caught, ana_win)}")
    print()
    print(f"【妙味ゾーン：末脚指数 top{args.top} × {args.ninki_ana}番人気以下】 ※単勝")
    print(f"  対象点数 : {seg_n}")
    print(f"  勝率     : {pct(seg_win, seg_n)}   複勝率(3着内): {pct(seg_place, seg_n)}")
    print(f"  単勝ROI  : {pct(seg_ret, seg_n*100)}")
    print(f"  --- ベースライン(人気薄{args.ninki_ana}番人気以下 全体) ---")
    print(f"  対象点数 : {base_n}")
    print(f"  勝率     : {pct(base_win, base_n)}   複勝率(3着内): {pct(base_place, base_n)}")
    print(f"  単勝ROI  : {pct(base_ret, base_n*100)}")
    print()
    print("→ 末脚指数segが ベースラインより 勝率/複勝率/ROI で上回れば、"
          "末脚偏差は『過小評価の妙味馬』抽出に効く特徴量。")
    con.close()


if __name__ == '__main__':
    main()
