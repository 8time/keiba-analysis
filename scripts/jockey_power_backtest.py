# -*- coding: utf-8 -*-
"""騎手力(JPower)の持続性検証 — 『騎手のみの力』の数値化の土台。

考え方: オッズは馬の質(＋騎手評価)を織り込む。よって『オッズ期待値に対する
実複勝率の上振れ(USM)』は騎手の寄与に最も近い。ただし過去のUSMが未来も
続く(=実力でありノイズでない)ことを示さないと数値化する意味がない。

方法(リーク無し・時系列ストリーム):
  ・期待値較正: 2016-2020のオッズ帯→実複勝率
  ・各騎乗時点で、その騎手の【直近500騎乗(その時点以前)】から縮小USMを計算
    縮小: 疑似騎乗k=100を期待値どおりの成績で追加(少サンプルを100へ寄せる)
  ・テスト期間(2021-25)で縮小USM五分位ごとに 実複勝-期待複勝 の残差を集計
  ・train(2021-24)とholdout(2025)の両方で単調＋zを確認
  ・偏差値化のための母集団分布(平均/SD)も出力

実行: python scripts/jockey_power_backtest.py
"""
import sys, io, os, sqlite3, math
from collections import defaultdict, deque
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')

K_PSEUDO = 100   # 縮小の疑似騎乗数
N_WINDOW = 500   # USM算出窓
MIN_PRIOR = 150  # これ未満の履歴しか無い騎乗は評価対象外


def odds_band(o):
    o = o or 999
    return '~3.0' if o <= 3 else '3-10' if o <= 10 else '10-30' if o <= 30 else '30~'


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    print("読み込み中(2016-2025 JRA)...")
    rows = con.execute(
        "SELECT r.race_key, r.year, r.jockey_name, r.chakujun, r.win_odds "
        "FROM results r WHERE CAST(r.year AS INT) BETWEEN 2016 AND 2025 "
        "AND r.jyo<='10' AND r.chakujun>0 AND r.win_odds>0 AND r.jockey_name!='' "
        "ORDER BY r.race_key").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    # 期待値較正(2016-2020)
    cal = defaultdict(lambda: [0, 0])
    for rk, y, jn, ch, wo in rows:
        if int(y) <= 2020:
            b = odds_band(wo)
            cal[b][0] += 1 if ch <= 3 else 0
            cal[b][1] += 1
    exp3 = {b: v[0] / v[1] for b, v in cal.items() if v[1]}
    print("期待複勝率(2016-20較正):", {b: f"{v:.3f}" for b, v in sorted(exp3.items())})

    # 時系列ストリーム
    hist = defaultdict(lambda: deque(maxlen=N_WINDOW))  # jockey -> (act, exp)
    # テスト集計: bucket -> [act_sum, exp_sum, n]
    tr = defaultdict(lambda: [0.0, 0.0, 0])
    ho = defaultdict(lambda: [0.0, 0.0, 0])
    usm_samples = []  # 母集団分布(2021-24のレース時点USM)

    def shrunk_usm(dq):
        a = sum(x for x, _ in dq)
        e = sum(x for _, x in dq)
        n = len(dq)
        if n < MIN_PRIOR or e <= 0:
            return None
        ebar = e / n
        return (a + K_PSEUDO * ebar) / (e + K_PSEUDO * ebar) * 100.0

    def bucket(u):
        # 五分位近似(初回実行の分布から固定): 後で母集団統計を表示して調整
        if u < 90: return 'Q1(<90)'
        if u < 96: return 'Q2(90-96)'
        if u < 102: return 'Q3(96-102)'
        if u < 108: return 'Q4(102-108)'
        return 'Q5(108+)'

    for rk, y, jn, ch, wo in rows:
        yr = int(y)
        b = odds_band(wo)
        e = exp3.get(b)
        if e is None:
            continue
        act = 1.0 if ch <= 3 else 0.0
        if yr >= 2021:
            u = shrunk_usm(hist[jn])
            if u is not None:
                tgt = tr if yr <= 2024 else ho
                bk = bucket(u)
                tgt[bk][0] += act
                tgt[bk][1] += e
                tgt[bk][2] += 1
                if yr <= 2024:
                    usm_samples.append(u)
        hist[jn].append((act, e))

    def report(tag, agg):
        print(f"\n=== {tag}: 縮小USM帯 → 実複勝-期待複勝(オッズ較正) ===")
        print(f"{'帯':<12}{'n':>9}{'実複勝':>8}{'期待':>8}{'残差':>9}{'z':>7}")
        order = ['Q1(<90)', 'Q2(90-96)', 'Q3(96-102)', 'Q4(102-108)', 'Q5(108+)']
        for bk in order:
            a, e, n = agg[bk]
            if n < 300:
                print(f"{bk:<12}{n:>9,}  (小)")
                continue
            ar, er = a / n, e / n
            z = (a - e) / math.sqrt(n * er * (1 - er))
            print(f"{bk:<12}{n:>9,}{100*ar:>7.1f}%{100*er:>7.1f}%{100*(ar-er):>+8.2f}pp{z:>+7.1f}")

    report("train 2021-24", tr)
    report("holdout 2025", ho)

    if usm_samples:
        m = sum(usm_samples) / len(usm_samples)
        sd = math.sqrt(sum((x - m) ** 2 for x in usm_samples) / len(usm_samples))
        print(f"\n母集団分布(騎乗重み・2021-24): mean={m:.2f} sd={sd:.2f} n={len(usm_samples):,}")
        print("→ 偏差値 = 50 + 10*(USM - mean)/sd の較正定数に使う")


if __name__ == '__main__':
    main()
