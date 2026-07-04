# -*- coding: utf-8 -*-
"""33ラップ理論(鈴木ショータ氏)の検証 — core/lap33.py の実力測定。

原典の主張: 馬の得意33ラップ(過去の好走時の傾向)と、今回のコース平均33ラップが
一致(適合)すれば好走しやすく、逆(不適合)なら凡走しやすい。

方針(リーク無し・過去の教訓遵守):
  ・コース平均33ラップは基準期間(2010-2020)で凍結算出→test期間には未来情報を使わない。
  ・馬の得意33ラップ(horse_fit33)は各レース時点のbefore_key(race_key)以前の過去走のみ。
  ・末脚指数/展開適合度と同じ型で検証: 「絶対複勝率」でなく「人気補正残差」で見る
    (単体では人気に織込み済みの可能性が高いという前提を踏まえ、まず素直に測る)。

角度:
  T1: 人気薄(6+)×適合 → 複勝残差(末脚指数と同型。最有力候補)
  T2: 人気上位(1-3)×不適合 → 複勝残差(危険人気/消去クロス候補のフェード)
  T3: 参考として全人気帯×適合/不適合/データ無し の複勝率テーブル(生の分布確認)

train=2021-2024 / holdout=2025。JRA限定(NARはラップデータ無し)。

実行: python scripts/lap33_backtest.py
"""
import sys, io, os, sqlite3, math
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import lap33 as l3

DB = l3.JV_DB_PATH
BASE_FROM, BASE_TO = 2010, 2020   # コース平均33ラップの基準期間(凍結)
TRAIN_FROM, TRAIN_TO = 2021, 2024
HOLD_FROM, HOLD_TO = 2025, 2025
FIT_THRESHOLD = 0.3               # この絶対値未満は「特徴なし」として適合判定から除外


def build_course_baseline():
    """基準期間(2010-2020)の(jyo,surface,kyori)別コース平均33ラップを凍結算出。"""
    con = l3._con()
    rows = con.execute(
        "SELECT ra.jyo, ra.surface, ra.kyori, ra.mae3f, ra.ato3f, rw.time "
        "FROM races ra JOIN results rw ON rw.race_key=ra.race_key AND rw.chakujun=1 "
        "WHERE ra.jyo<='10' AND CAST(ra.year AS INT) BETWEEN ? AND ? "
        "AND ra.mae3f>0 AND ra.ato3f>0", (BASE_FROM, BASE_TO)).fetchall()
    con.close()
    agg = defaultdict(list)
    for jyo, surf, kyori, mae, ato, wtime in rows:
        s = '芝' if '芝' in str(surf) else 'ダ'
        v = l3.race_lap33(kyori, mae, ato, wtime)
        if v is not None:
            agg[(jyo, s, kyori)].append(v)
    base = {k: (sum(v) / len(v)) for k, v in agg.items() if len(v) >= 20}
    print(f"コース基準(2010-2020・n>=20のコースのみ): {len(base)}コース")
    return base


def build_horse_history():
    """馬ごとの時系列33ラップ履歴(race_key, lap33, chakujun)を構築。"""
    con = l3._con()
    rows = con.execute(
        "SELECT r.race_key, r.ketto_num, r.chakujun, r.ninki, r.ato3f, "
        "ra.jyo, ra.surface, ra.kyori, ra.mae3f, ra.ato3f AS ra_ato, rw.time "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "JOIN results rw ON rw.race_key=r.race_key AND rw.chakujun=1 "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND r.ato3f>0 "
        "AND ra.mae3f>0 AND ra.ato3f>0 AND CAST(r.year AS INT) >= ? "
        "ORDER BY r.race_key", (BASE_FROM,)).fetchall()
    con.close()
    hist = defaultdict(list)   # ketto -> [(race_key, lap33_horse)]
    recs = []                  # 評価対象行(test期間で使う)
    for rk, kt, chaku, nk, h_ato, jyo, surf, kyori, mae, ra_ato, wtime in rows:
        s = '芝' if '芝' in str(surf) else 'ダ'
        mid = l3.race_mid3f_rate(kyori, mae, ra_ato, wtime) if (kyori and kyori > 1200) else None
        if kyori and kyori <= 1200:
            v_horse = l3.lap33(l3._to_sec10(mae), l3._to_sec10(h_ato))
        else:
            v_horse = l3.lap33(mid, l3._to_sec10(h_ato))
        recs.append({'rk': rk, 'kt': kt, 'chaku': chaku, 'nk': nk,
                     'jyo': jyo, 'surf': s, 'kyori': kyori, 'v_horse': v_horse})
    return recs


def past_avg_lap33(hist_map, kt, rk, n=10, min_runs=3):
    h = hist_map.get(kt)
    if not h:
        return None, 0
    past = [v for (k, v) in h if k < rk and v is not None][-n:]
    if len(past) < min_runs:
        return None, len(past)
    return sum(past) / len(past), len(past)


def main():
    print("コース基準33ラップを構築中...")
    base = build_course_baseline()
    print("馬別レコードを構築中...")
    recs = build_horse_history()
    print(f"  {len(recs):,}行")

    # 馬ごとの時系列(race_key, v_horse)を積み上げながら、test期間の行は
    # 「そのレースより前の履歴のみ」で判定する(リーク遮断)。
    hist = defaultdict(list)

    # 人気別ベース複勝率(test期間ごとに個別算出)
    def popularity_base(y0, y1):
        pt = defaultdict(lambda: [0, 0])
        for r in recs:
            rk_year = int(str(r['rk'])[:4])
            if y0 <= rk_year <= y1 and r['nk']:
                pt[int(r['nk'])][0] += 1 if r['chaku'] <= 3 else 0
                pt[int(r['nk'])][1] += 1
        return {p: (s[0] / s[1] if s[1] else 0.22) for p, s in pt.items()}

    base_train = popularity_base(TRAIN_FROM, TRAIN_TO)
    base_hold = popularity_base(HOLD_FROM, HOLD_TO)

    # 集計: period -> band('long'/'fav') -> match('match'/'mismatch'/'none') -> [t3,n,exp]
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0])))
    dist_table = defaultdict(lambda: [0, 0])  # (period,match) -> [t3,n] (T3参考表用)

    recs_sorted = sorted(recs, key=lambda r: r['rk'])
    for r in recs_sorted:
        rk_year = int(str(r['rk'])[:4])
        kt = r['kt']
        if TRAIN_FROM <= rk_year <= HOLD_TO:
            h_avg, n_prior = past_avg_lap33(hist, kt, r['rk'])
            course_v = base.get((r['jyo'], r['surf'], r['kyori']))
            m = l3.fit_match(h_avg, course_v, threshold=FIT_THRESHOLD)
            match_lbl = 'match' if m is True else ('mismatch' if m is False else 'none')
            period = 'train' if rk_year <= TRAIN_TO else 'holdout'
            bp = base_train if period == 'train' else base_hold
            nk = int(r['nk']) if r['nk'] else None
            if nk:
                exp = bp.get(nk, 0.22)
                t3 = 1 if r['chaku'] <= 3 else 0
                if nk >= 6:
                    a = agg[period]['long'][match_lbl]
                    a[0] += t3; a[1] += 1; a[2] += exp
                elif nk <= 3:
                    a = agg[period]['fav'][match_lbl]
                    a[0] += t3; a[1] += 1; a[2] += exp
                dt = dist_table[(period, match_lbl)]
                dt[0] += t3; dt[1] += 1
        # 履歴に積む(このレース自体は次回以降の判定に使う)
        if r['v_horse'] is not None:
            hist[kt].append((r['rk'], r['v_horse']))

    def show(period, band, bandjp):
        print(f"\n--- {period} / {bandjp} ---")
        print(f"{'適合':<10}{'n':>8}{'複勝率':>8}{'人気期待':>9}{'残差':>9}{'z':>7}")
        for lbl, ljp in (('match', '適合'), ('mismatch', '不適合'), ('none', 'データ無/弱')):
            t3, n, exp = agg[period][band][lbl]
            if n < 100:
                print(f"{ljp:<10}{n:>8,}  (n<100)")
                continue
            e = exp / n
            z = (t3 - exp) / math.sqrt(n * e * (1 - e)) if 0 < e < 1 else 0
            print(f"{ljp:<10}{n:>8,}{100*t3/n:>7.1f}%{100*e:>7.1f}%{100*(t3/n-e):>+8.2f}pp{z:>+7.1f}")

    print("\n=== T1: 人気薄(6+人気)× 33ラップ適合 → 複勝残差 ===")
    show('train', 'long', '人気薄6+')
    show('holdout', 'long', '人気薄6+')

    print("\n=== T2: 人気上位(1-3人気)× 33ラップ不適合 → 複勝残差(フェード候補) ===")
    show('train', 'fav', '人気上位1-3')
    show('holdout', 'fav', '人気上位1-3')

    print("\n=== T3(参考): 全人気帯 適合/不適合の絶対複勝率(生分布) ===")
    for period in ('train', 'holdout'):
        for lbl, ljp in (('match', '適合'), ('mismatch', '不適合')):
            t3, n = dist_table[(period, lbl)]
            if n:
                print(f"  {period} {ljp}: n={n:,} 複勝率{100*t3/n:.1f}%")

    print("\n[判定] T1のz>=2かつholdoutで方向維持=独立エッジ(採用候補)。"
          "T2のz<=-2かつholdout維持=危険/消去候補。いずれも≈0ならpriced-in(非採用)。")


if __name__ == '__main__':
    main()
