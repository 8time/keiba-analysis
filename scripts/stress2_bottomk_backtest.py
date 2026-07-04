# -*- coding: utf-8 -*-
"""スト2(🐎Stress Analystの最終予測が全馬中『下から3』)の閾値を検証する。

ユーザー指摘: 「下から3」は目視でいくつか見て決めただけで根拠が無い。
JV-VANの実データ(leak-free)で本当に良い閾値か、そもそも意味のある切り口かを検証する。

方法:
  A) stress1(理由が1つでも該当)単体の複勝率残差(人気バンド基準比較)
  B) 理由の重複数(0/1/2/3個)別の残差 → 単調に悪化するか(=「本当は重複数で見るべき」仮説の検証)
  C) 「下から3(final_score proxy)」の追加効果テスト:
     final_score proxy = (1/オッズ) × stress係数 で馬をレース内順位付けし、
     生オッズだけのbottom-Kと比較して『stressの掛け算で新たにbottom-Kへ落ちた馬』
     (=popularityのbottom-Kには入っていないがadjustedでは入る馬)が
     popularityバンド基準より悪いかどうかを見る。これがYESでなければ
     「下から3」は単に地力の低い馬を指しているだけ(=battle/proj下位30%と冗長)。
     K=1..5で比較し、どのKが良いかも見る。

leak-free: 習性(後方脚質)は直近5走(該当走より前のみ)の平均通過順(corner1-4平均)から算出。
体重/増減はその走自身の当日値(事前確定データなので問題なし)。
train=2016-2024 / holdout=2025(既存の検証群と同じ慣例)。
"""
import os
import sys
import sqlite3
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def main():
    print("読み込み中(JRA 2016-2025)...")
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT r.race_key rk, ra.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.bataiju bw, r.zogen zg, "
        "r.corner1 c1, r.corner2 c2, r.corner3 c3, r.corner4 c4, ra.surface surf "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(ra.year AS INT)>=2016 "
        "ORDER BY r.race_key").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r[0]].append(r)

    # ── 馬ごとの通過順履歴(leak-free): kt -> [(rk, avg_corner)] ──
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        for (rk2, y, kt, ch, nk, wo, bw, zg, c1, c2, c3, c4, surf) in rs:
            cs = [c for c in (c1, c2, c3, c4) if c and c > 0]
            if cs:
                hist[kt].append((rk2, sum(cs) / len(cs)))
    for k in hist:
        hist[k].sort(key=lambda z: z[0])

    def habit_pos(kt, rk, n=5, minr=2):
        h = hist.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk][-n:]
        if len(past) < minr:
            return None
        return sum(past) / len(past)

    def popularity_base(races_iter):
        pt = defaultdict(lambda: [0, 0])
        for rk, rs in races_iter:
            for (rk2, y, kt, ch, nk, wo, bw, zg, c1, c2, c3, c4, surf) in rs:
                if nk:
                    pt[int(nk)][0] += 1 if ch <= 3 else 0
                    pt[int(nk)][1] += 1
        return {p: (s[0] / s[1] if s[1] else 0.05) for p, s in pt.items()}

    train_races = [(rk, rs) for rk, rs in by_race.items() if int(str(rk)[:4]) <= 2024]
    hold_races = [(rk, rs) for rk, rs in by_race.items() if int(str(rk)[:4]) == 2025]
    base_train = popularity_base(train_races)
    base_hold = popularity_base(hold_races)

    def band_rate(nk, base):
        return base.get(int(nk), 0.10) if nk else 0.10

    # ── A/B/C 集計用 ──
    agg_stress1 = {'train': [0, 0], 'holdout': [0, 0]}
    agg_reason_n = {'train': defaultdict(lambda: [0, 0]), 'holdout': defaultdict(lambda: [0, 0])}
    agg_bottomk_new = {'train': defaultdict(lambda: [0, 0]), 'holdout': defaultdict(lambda: [0, 0])}
    agg_bottomk_all = {'train': defaultdict(lambda: [0, 0]), 'holdout': defaultdict(lambda: [0, 0])}

    KS = [1, 2, 3, 4, 5]

    for rk, rs in by_race.items():
        yr = int(str(rk)[:4])
        if yr < 2016 or yr > 2025:
            continue
        period = 'train' if yr <= 2024 else 'holdout'
        base = base_train if period == 'train' else base_hold

        horses = []
        for (rk2, y, kt, ch, nk, wo, bw, zg, c1, c2, c3, c4, surf) in rs:
            if not wo or wo <= 0 or not nk:
                continue
            odds = wo / 10.0
            bw = bw or 0
            zg = zg if zg is not None else 0
            hp = habit_pos(kt, rk)
            r1 = 1 if (0 < bw < 440 and zg <= -6) else 0
            r2 = 1 if ('芝' in str(surf) and hp is not None and hp >= 7.5) else 0
            r3 = 1 if (zg >= 8) else 0
            n_reason = r1 + r2 + r3
            mult = max(1.0 - 0.04 * r1 - 0.03 * r2 - 0.02 * r3, 0.85)
            horses.append({
                'kt': kt, 'ch': ch, 'nk': int(nk), 'odds': odds,
                'n_reason': n_reason, 'mult': mult,
            })
        if len(horses) < 4:
            continue

        for h in horses:
            b = band_rate(h['nk'], base)
            hit = 1 if h['ch'] <= 3 else 0
            # A) stress1単体
            if h['n_reason'] >= 1:
                agg_stress1[period][0] += hit - b
                agg_stress1[period][1] += 1
            # B) 重複数別
            agg_reason_n[period][h['n_reason']][0] += hit - b
            agg_reason_n[period][h['n_reason']][1] += 1

        # C) bottom-K: 生オッズ順位 vs stress調整後(1/odds*mult)順位
        by_odds_rank = sorted(range(len(horses)), key=lambda i: -horses[i]['odds'])  # 弱い(オッズ大)ほど後ろ
        by_adj_rank = sorted(range(len(horses)), key=lambda i: -(1.0 / horses[i]['odds']) * horses[i]['mult'])
        # by_adj_rankは強い順。bottom-Kは末尾K個。
        n = len(horses)
        for K in KS:
            if K >= n:
                continue
            bottom_odds_idx = set(by_odds_rank[-K:])
            bottom_adj_idx = set(by_adj_rank[-K:])
            newly_added = bottom_adj_idx - bottom_odds_idx  # stress調整で新たに脱落した馬
            for i in newly_added:
                h = horses[i]
                b = band_rate(h['nk'], base)
                hit = 1 if h['ch'] <= 3 else 0
                agg_bottomk_new[period][K][0] += hit - b
                agg_bottomk_new[period][K][1] += 1
            for i in bottom_adj_idx:
                h = horses[i]
                b = band_rate(h['nk'], base)
                hit = 1 if h['ch'] <= 3 else 0
                agg_bottomk_all[period][K][0] += hit - b
                agg_bottomk_all[period][K][1] += 1


    def show_line(label, resid, n):
        if n < 30:
            print(f"  {label:28s} n={n:6d} (n<30)")
            return
        rate_resid = resid / n
        se = (0.20 * 0.80 / n) ** 0.5  # 大まかなSE(複勝率20%仮定)
        z = rate_resid / se if se else 0
        print(f"  {label:28s} n={n:6d}  基準比{rate_resid:+.4f}pp相当  z={z:+.2f}")

    for period in ('train', 'holdout'):
        print(f"\n=== {period} ===")
        print("[A] stress1(理由1つ以上)単体:")
        r, n = agg_stress1[period]
        show_line('stress1', r, n)

        print("[B] 理由の重複数別(単調悪化するか):")
        for nr in (0, 1, 2, 3):
            r, n = agg_reason_n[period][nr]
            show_line(f'reason_n={nr}', r, n)

        print("[C] bottom-K: stress調整で『新たに』bottom-Kへ落ちた馬(popularityのbottom-Kには"
              "入っていない馬)の残差 = stress調整の純粋な追加効果:")
        for K in KS:
            r, n = agg_bottomk_new[period][K]
            show_line(f'K={K} 新規追加分', r, n)

        print("[参考] bottom-K全体(newly_added込み・現行スト2に相当するK=3がこれ):")
        for K in KS:
            r, n = agg_bottomk_all[period][K]
            show_line(f'K={K} 全体', r, n)

    print("\n[判定] Bが単調に悪化 かつ z<-2で安定 → 重複数(理由の数)で見るのが妥当。"
          "Cの『新規追加分』がholdoutでもz<-2で安定していれば現行スト2(K=3)に一定の根拠あり。"
          "そうでなければ『下から3』は単に地力の低い馬(battle/proj下位30%と重複)を"
          "指しているだけで、stress由来の追加情報は無いと判断する。")


if __name__ == '__main__':
    main()
