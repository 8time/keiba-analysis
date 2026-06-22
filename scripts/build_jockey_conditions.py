# -*- coding: utf-8 -*-
"""騎手の条件別成績レポート生成（自前db-keiba） — scripts/build_jockey_conditions.py

db-keibaの「過小評価条件（単勝回収率○○%以上）」と同種の表を jravan.db から自前生成。
決定的な違い: 各条件に【サンプル数 n】と【オッズ残差z】を付け、
『回収率が高いのは本物か運(小標本)か』を判別できる。
単勝回収率は分散が巨大なので、回収率しきい値だけでは小標本ノイズを拾う(検証済)。
残差z = 実勝率 − オッズ帯人口平均の期待勝率 を標準誤差で割った値。z≥2で『人気以上に走らせる』が有意。

使い方:
  python scripts/build_jockey_conditions.py --jockey 横山琉人
  python scripts/build_jockey_conditions.py --jockey ルメール --min-n 100
出力: data/jockey_conditions_<名前>.csv ＋ 標準エラーに有意な買い条件サマリー。
注意: 中央(JRA)芝ダートのみ集計。クラス(1勝/2勝)は条件コードがDBに無く非対応。人気/枠/場/距離/性別/厩舎コードに対応。
"""
import os
import sys
import argparse
import sqlite3
import math
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')

JYO = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
       '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}

ODDS_EDGES = [(0, 1.45), (1.45, 1.95), (1.95, 2.95), (2.95, 3.95), (3.95, 4.95),
              (4.95, 6.95), (6.95, 9.95), (9.95, 14.95), (14.95, 19.95),
              (19.95, 29.95), (29.95, 49.95), (49.95, 99.95), (99.95, 1e9)]


def _band(o):
    for i, (lo, hi) in enumerate(ODDS_EDGES):
        if lo <= o < hi:
            return i
    return len(ODDS_EDGES) - 1


def _dist_cat(surface, kyori):
    if kyori <= 1400:
        c = '短距離'
    elif kyori <= 1800:
        c = 'マイル'
    elif kyori <= 2200:
        c = '中距離'
    else:
        c = '長距離'
    return f"{surface}・{c}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jockey', required=True, help='騎手名(部分一致)')
    ap.add_argument('--min-n', type=int, default=80, help='有意判定の最小サンプル数(既定80)')
    args = ap.parse_args()

    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=20)
    cur = con.cursor()

    # 1) オッズ帯ごとの人口平均勝率(集合知=疑似能力)
    print('集計中: オッズ帯人口平均...', file=sys.stderr)
    band_win = defaultdict(lambda: [0, 0])  # band -> [wins, n]
    for chaku, od in cur.execute(
        """SELECT r.chakujun, r.win_odds FROM results r JOIN races ra ON r.race_key=ra.race_key
           WHERE ra.surface IN ('芝','ダート') AND r.chakujun>0 AND r.win_odds>0
             AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10"""):
        b = _band(od)
        band_win[b][0] += (1 if chaku == 1 else 0)
        band_win[b][1] += 1
    band_rate = {b: (w / n if n else 0.0) for b, (w, n) in band_win.items()}

    # 2) 対象騎手の全騎乗(中央芝ダ)
    rows = cur.execute(
        """SELECT r.chakujun, r.win_odds, r.ninki, r.waku, r.sex, r.trainer_code,
                  ra.surface, ra.kyori, ra.jyo
           FROM results r JOIN races ra ON r.race_key=ra.race_key
           WHERE r.jockey_name LIKE ? AND r.jockey_code!='00000'
             AND ra.surface IN ('芝','ダート') AND r.chakujun>0 AND r.win_odds>0
             AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10""",
        ('%' + args.jockey + '%',)).fetchall()
    con.close()
    if not rows:
        print(f"該当データなし: {args.jockey}", file=sys.stderr)
        return
    print(f"対象騎乗: {len(rows):,}件 ({args.jockey})", file=sys.stderr)

    SEX = {'1': '牡馬', '2': '牝馬', '3': 'セ馬'}
    # 条件スライス集計: dim -> condition -> [wins, n, ret_sum, exp_sum]
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0, 0.0]))

    def add(dim, cond, chaku, od):
        a = agg[dim][cond]
        a[0] += (1 if chaku == 1 else 0)
        a[1] += 1
        a[2] += (od if chaku == 1 else 0.0)   # 単勝払戻(倍)
        a[3] += band_rate.get(_band(od), 0.0)  # 期待勝利数

    for chaku, od, ninki, waku, sex, tc, surface, kyori, jyo in rows:
        add('人気', f"{ninki}人気" if ninki and ninki < 90 else '人気不明', chaku, od)
        add('馬場×枠', f"{surface}{waku}枠", chaku, od)
        add('コース', f"{JYO.get(jyo, jyo)}{surface}", chaku, od)
        add('距離区分', _dist_cat(surface, kyori or 0), chaku, od)
        add('性別', SEX.get(str(sex), '性別不明'), chaku, od)
        add('馬場', surface, chaku, od)
        if tc and tc != '00000':
            add('厩舎(code)', f"厩舎{tc}", chaku, od)

    # 3) 残差z計算してレコード化
    recs = []
    for dim, conds in agg.items():
        for cond, (wins, n, ret_sum, exp_sum) in conds.items():
            if n < 20:
                continue
            win_rate = wins / n
            exp_rate = exp_sum / n
            ret_pct = ret_sum / n * 100.0
            resid = win_rate - exp_rate
            se = math.sqrt(exp_rate * (1 - exp_rate) / n) if 0 < exp_rate < 1 else 1e9
            z = resid / se if se else 0.0
            recs.append({
                'dim': dim, '条件': cond, 'n': n, '勝率%': round(win_rate * 100, 1),
                '単回収%': round(ret_pct, 1), '期待勝率%': round(exp_rate * 100, 1),
                '残差pp': round(resid * 100, 2), 'z': round(z, 2),
                '判定': ('✅有意+' if (z >= 2 and n >= args.min_n) else
                         '○弱め+' if (z >= 1 and n >= args.min_n) else
                         '⚠有意−' if (z <= -2 and n >= args.min_n) else
                         '·' )
            })
    recs.sort(key=lambda r: -r['z'])

    # 4) CSV出力
    import csv
    safe = ''.join(c for c in args.jockey if c.isalnum() or 0x3040 <= ord(c) <= 0x30ff or 0x4e00 <= ord(c) <= 0x9fff)
    out_csv = os.path.join(ROOT, 'data', f'jockey_conditions_{safe}.csv')
    with open(out_csv, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['dim', '条件', 'n', '勝率%', '単回収%', '期待勝率%', '残差pp', 'z', '判定'])
        w.writeheader()
        for r in recs:
            w.writerow(r)

    # 5) サマリー
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"【{args.jockey}】条件別成績（残差z順・n≥20）  CSV → {out_csv}", file=sys.stderr)
    print(f"{'条件':<16}{'n':>5}{'勝率%':>7}{'単回収%':>8}{'期待%':>7}{'残差pp':>8}{'z':>7}  判定", file=sys.stderr)
    sig = [r for r in recs if r['判定'].startswith('✅')]
    print("\n▼ 真に有意な買い条件 (z≥2 ＆ n≥{}) ＝人気以上に走らせる".format(args.min_n), file=sys.stderr)
    if sig:
        for r in sig:
            print(f"{r['条件']:<16}{r['n']:>5}{r['勝率%']:>7}{r['単回収%']:>8}{r['期待勝率%']:>7}{r['残差pp']:>8}{r['z']:>7}  {r['判定']}", file=sys.stderr)
    else:
        print("  （該当なし＝この騎手はオッズ通りに近い）", file=sys.stderr)

    # db-keiba的な『回収率≥100%だが有意でない＝ノイズ警告』
    noisy = [r for r in recs if r['単回収%'] >= 100 and not r['判定'].startswith('✅') and r['n'] >= 20]
    noisy.sort(key=lambda r: -r['単回収%'])
    print("\n▼ 単回収率は高いが統計的に有意でない（小標本ノイズの可能性・鵜呑み注意）", file=sys.stderr)
    for r in noisy[:15]:
        print(f"{r['条件']:<16}{r['n']:>5}{r['勝率%']:>7}{r['単回収%']:>8}{r['期待勝率%']:>7}{r['残差pp']:>8}{r['z']:>7}", file=sys.stderr)
    print(f"\n{'='*70}\n注: 単勝回収率は分散が巨大。z(残差)が小さい高回収率はほぼ運。買い条件はz≥2を重視。", file=sys.stderr)


if __name__ == '__main__':
    main()
