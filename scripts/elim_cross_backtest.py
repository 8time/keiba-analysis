# -*- coding: utf-8 -*-
"""
消去クロス・バックテスト — 『下位指標が重なった馬は3着内に来ない』仮説の検証
─────────────────────────────────────────────────────────
ユーザー観測:「調教C以下は高確率で3着内に来ない。様々な指標の下位を集めて
重ねれば消去フィルターを強化できるのでは?」

検証方針(検証済みエッジのみ / 過去の教訓=脚質・圧勝は人気に織込み済):
  各「下位フラグ」は PAST(過去走)のみから計算しhindsight漏れを防ぐ。
  各フラグの価値 = 単なる低複勝率ではなく『人気が示す複勝率より低いか』=人気補正残差。
  residual = 実複勝率(flagged) − 人気から期待される複勝率(同じflagged馬の平均)。
  residual が負ほど『人気以上に来ない=消去に有効』。priced-inなら ≈0。
  最後に「負残差フラグの重複数 → 複勝率」の単調性(stacking)を見る。

注意: 調教評価(A〜D)は jravan.db に過去データが無いため本検証の対象外。
      win_odds欠損~37%のためROIは使わず複勝率(3着内・完全populated)主指標。
実行: python scripts/elim_cross_backtest.py
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2014)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--min_field', type=int, default=8)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中 (year>={args.train_from})...")
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.monthday md, r.ketto_num kt, r.chakujun ch, "
        "r.ninki nk, r.win_odds wo, r.ato3f a3, r.corner4 c4, r.zogen zg, r.futan ft, "
        "r.age ag, ra.kyori ki, ra.shusso_tosu st "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    # 各レースで上がり3F順位比率を計算 → 馬ごとの過去走履歴を構築
    # hist[kt] = sorted list of dict(dk, dist, top3, a3rank, c4ratio)
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        d = dk(rs[0]['y'], rs[0]['md'])
        n = rs[0]['st'] or len(rs)
        a3 = [(x['a3'], x) for x in rs if x['a3'] and x['a3'] > 0]
        a3.sort(key=lambda t: t[0])  # 速い順
        rank = {}
        for i, (_, x) in enumerate(a3):
            rank[x['kt']] = (i + 1) / len(a3)  # 0=最速 .. 1=最遅
        for x in rs:
            ch = x['ch']
            if not ch or ch <= 0:
                continue
            c4r = (x['c4'] / n) if (x['c4'] and n) else None
            hist[x['kt']].append({
                'dk': d, 'dist': x['ki'], 'top3': 1 if ch <= 3 else 0,
                'a3rank': rank.get(x['kt']), 'c4r': c4r,
            })
    for k in hist:
        hist[k].sort(key=lambda z: z['dk'])

    def past(kt, d, n=5):
        h = hist.get(kt)
        if not h:
            return []
        return [x for x in h if x['dk'] < d][-n:]

    # フラグ定義(pre-race): 戻り値dict name->bool
    def flags(r, d):
        p5 = past(r['kt'], d, 5)
        p3 = p5[-3:]
        f = {}
        # 近走3走すべて着外(複勝なし)
        f['form3'] = len(p3) >= 3 and all(x['top3'] == 0 for x in p3)
        # 過去5走で一度も3着内なし
        f['nofuku5'] = len(p5) >= 3 and all(x['top3'] == 0 for x in p5)
        # 上がり遅い: 過去3走の平均上がり順位比率 ≥0.70(下位)
        ar = [x['a3rank'] for x in p3 if x['a3rank'] is not None]
        f['slow3f'] = len(ar) >= 2 and (sum(ar) / len(ar)) >= 0.70
        # 後方脚質: 過去3走平均4角比率 ≥0.78
        cr = [x['c4r'] for x in p3 if x['c4r'] is not None]
        f['back'] = len(cr) >= 2 and (sum(cr) / len(cr)) >= 0.78
        # 長期休養: 前走から≥180日
        f['layoff'] = bool(p5) and (d - p5[-1]['dk']) >= 180  # 概算(YYYYMMDD差)
        # 大幅距離変更: |今回-前走|≥400m
        f['distbig'] = bool(p5) and p5[-1]['dist'] and r['ki'] and abs(r['ki'] - p5[-1]['dist']) >= 400
        # 大幅馬体重増減: |zogen|≥16kg
        f['zogen'] = r['zg'] is not None and abs(r['zg']) >= 16
        # 高齢: age≥8
        f['age8'] = r['ag'] is not None and r['ag'] >= 8
        return f

    FLAG_NAMES = ['form3', 'nofuku5', 'slow3f', 'back', 'layoff', 'distbig', 'zogen', 'age8']
    FLAG_LABEL = {'form3': '近3走着外', 'nofuku5': '過去5走複勝0', 'slow3f': '上がり下位',
                  'back': '後方脚質', 'layoff': '半年休み', 'distbig': '大幅距離変更',
                  'zogen': '体重±16k', 'age8': '8歳上'}

    # 集計
    pop_top3 = defaultdict(lambda: [0, 0])     # pop -> [top3, n]  人気別ベースライン
    flag_stat = {fn: [0, 0, 0.0] for fn in FLAG_NAMES}  # top3, n, sum_expected
    recs = []  # (pop, top3, set(flags))

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['y']) <= args.test_to):
            continue
        if len(rs) < args.min_field:
            continue
        d = dk(rs[0]['y'], rs[0]['md'])
        for r in rs:
            if not r['nk'] or not r['ch'] or r['ch'] <= 0:
                continue
            pop = int(r['nk'])
            t3 = 1 if r['ch'] <= 3 else 0
            pop_top3[pop][0] += t3
            pop_top3[pop][1] += 1
            fl = flags(r, d)
            recs.append((pop, t3, {k for k, v in fl.items() if v}))

    # 人気別ベースライン複勝率
    base = {p: (s[0] / s[1] if s[1] else 0) for p, s in pop_top3.items()}

    # フラグごと residual
    for pop, t3, fs in recs:
        exp = base.get(pop, 0)
        for fn in fs:
            flag_stat[fn][0] += t3
            flag_stat[fn][1] += 1
            flag_stat[fn][2] += exp

    print(f"\n=== 個別フラグ検証 (test {args.test_from}-{args.test_to}, {args.min_field}頭以上, n={len(recs):,}) ===")
    print(f"{'フラグ':<14}{'n':>8}{'複勝率':>8}{'人気期待':>8}{'残差':>8}  判定")
    verified = []
    for fn in FLAG_NAMES:
        t3, n, exp = flag_stat[fn]
        if n == 0:
            continue
        fr = 100 * t3 / n
        ex = 100 * exp / n
        res = fr - ex
        ok = res <= -2.0  # 人気以上に来ない=有効
        if ok:
            verified.append(fn)
        print(f"{FLAG_LABEL[fn]:<14}{n:>8,}{fr:>7.1f}%{ex:>7.1f}%{res:>+7.1f}pp  {'✅有効' if ok else '─priced-in' if abs(res)<2 else '⚠逆効果'}")

    print(f"\n  → 有効フラグ(残差≤-2pp): {[FLAG_LABEL[f] for f in verified] or 'なし'}")

    # stacking(全8フラグ): 重複数 → 絶対複勝率(形成絞り用) と 人気残差(妙味用)
    cnt_stat = defaultdict(lambda: [0, 0, 0.0])
    for pop, t3, fs in recs:
        c = len(fs)
        cnt_stat[c][0] += t3
        cnt_stat[c][1] += 1
        cnt_stat[c][2] += base.get(pop, 0)
    print(f"\n=== 全フラグ重複数 → 複勝率(stacking) ===")
    print(f"{'重複数':>6}{'n':>9}{'複勝率':>8}{'人気期待':>8}{'残差':>8}")
    for c in sorted(cnt_stat):
        t3, n, exp = cnt_stat[c]
        if n == 0:
            continue
        print(f"{c:>6}{n:>9,}{100*t3/n:>7.1f}%{100*exp/n:>7.1f}%{100*(t3-exp)/n:>+7.1f}pp")

    # 人気帯別: 上位人気(1-5)に多フラグが付いた時に過剰人気=妙味になるか
    print(f"\n=== 人気1-5番のみ: フラグ重複数 → 複勝率/残差(過剰人気の検出) ===")
    cnt5 = defaultdict(lambda: [0, 0, 0.0])
    for pop, t3, fs in recs:
        if pop > 5:
            continue
        c = len(fs)
        cnt5[c][0] += t3
        cnt5[c][1] += 1
        cnt5[c][2] += base.get(pop, 0)
    print(f"{'重複数':>6}{'n':>9}{'複勝率':>8}{'人気期待':>8}{'残差':>8}")
    for c in sorted(cnt5):
        t3, n, exp = cnt5[c]
        if n == 0:
            continue
        print(f"{c:>6}{n:>9,}{100*t3/n:>7.1f}%{100*exp/n:>7.1f}%{100*(t3-exp)/n:>+7.1f}pp")


if __name__ == '__main__':
    main()
