# -*- coding: utf-8 -*-
"""
#3 戦術①「前走 補正102-109 スイートスポット × 次走人気落ち」の検証 — tactic1_backtest.py

資料の主張:
  前走で補正タイム「102～109」(=基準100より0.2～0.9秒速い)を出して勝った馬は、
  次走で昇級戦以外・人気落ち(4～18番人気)なら単勝回収率100%超。
  ・110+(0.9秒超=圧勝)は次走過剰人気で回収率低下(危険エリア)。
  ・100～101(=多すぎ)は絞れない。

自前換算(corrected:負=速い・1.0=1.0秒):
  補正100相当 = 勝ち馬corrected中央値 T_win。
  102-109 = T_winより0.2〜0.9秒速い = corrected ∈ [T_win-0.9, T_win-0.2]
  110+      = T_win-0.9 より速い(corrected < T_win-0.9)
  100-101   = corrected ∈ [T_win-0.2, T_win]

検証: 前走(直近1走前)がそのバンドで かつ 前走勝ち(chakujun==1) の馬を、今走の人気帯別に
  単勝ROI / 複勝率 / 人気統制残差 で評価。2016-2026(オッズ完備)。
  ※「昇級戦以外」はクラス比較データが煩雑なので本検証では外す(注記)。リーク無し。
"""
import os
import sys
import sqlite3
import math
import time as _time
from collections import defaultdict
from statistics import median

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
BASELINE_FROM = 1990
TEST_FROM, TEST_TO = 2016, 2026


def to_sec(t):
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    s = int(t[0]) * 60 + int(t[1:3]) + int(t[3]) / 10.0
    return s if 50 <= s <= 360 else None


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    print("loading...", file=sys.stderr)
    q = f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
                   r.ketto_num, r.chakujun, r.ninki, r.win_odds, r.time
            FROM races ra JOIN results r ON r.race_key = ra.race_key
            WHERE ra.surface IN ('芝','ダート')
              AND CAST(ra.year AS INTEGER) >= {BASELINE_FROM}
              AND r.chakujun > 0"""
    rows = []
    for (yr, md, jyo, surf, kyori, ketto, chaku, ninki, wo, tm) in con.execute(q):
        sec = to_sec(tm)
        if sec is None or not ketto:
            continue
        try:
            day = int(yr) * 10000 + int(md)
        except Exception:
            continue
        rows.append([day, surf, int(kyori), jyo, str(ketto), int(chaku),
                     (int(ninki) if ninki else 99), (float(wo) if wo else 0.0), sec, None])
    con.close()
    print(f"runs={len(rows):,}", file=sys.stderr)

    by_sk = defaultdict(list)
    for x in rows:
        by_sk[(x[1], x[2])].append(x[8])
    baseline = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    for x in rows:
        b = baseline.get((x[1], x[2]))
        x[9] = (x[8] - b) if b is not None else None
    by_tr = defaultdict(list)
    for x in rows:
        if x[9] is not None:
            by_tr[(x[0], x[3], x[1])].append(x[9])
    tb = {k: median(v) for k, v in by_tr.items() if len(v) >= 4}
    for x in rows:
        if x[9] is None:
            continue
        b = tb.get((x[0], x[3], x[1]))
        x[9] = (x[9] - b) if b is not None else None

    Tw = median([x[9] for x in rows if x[5] == 1 and x[9] is not None])
    print(f"T_win(補正100相当)={Tw:.2f}", file=sys.stderr)

    # per-horse history: (day, corrected, chakujun)
    hist = defaultdict(list)
    for x in rows:
        if x[9] is not None:
            hist[x[4]].append((x[0], x[9], x[5]))
    for k in hist:
        hist[k].sort()

    def prev_run(ketto, day):
        arr = hist.get(ketto, [])
        p = [(d, c, ch) for (d, c, ch) in arr if d < day]
        return p[-1] if p else None

    def band(corr):
        if corr is None:
            return None
        if corr < Tw - 0.9:
            return '110+(圧勝)'
        if corr <= Tw - 0.2:
            return '102-109(SS)'
        if corr <= Tw:
            return '100-101'
        return '<100'

    # test rows
    recs = []  # (ninki, chaku, odds, prev_band, prev_win)
    for x in rows:
        if not (TEST_FROM <= x[0] // 10000 <= TEST_TO):
            continue
        if x[7] <= 0 or x[6] >= 99:
            continue
        pv = prev_run(x[4], x[0])
        if not pv:
            continue
        recs.append((x[6], x[5], x[7], band(pv[1]), pv[2] == 1))
    print(f"test(前走あり,2016-26,オッズ有)={len(recs):,}", file=sys.stderr)

    def nb(n):
        return min(n, 15)
    bt = defaultdict(int); bf = defaultdict(int)
    for (ninki, chaku, odds, pb, pw) in recs:
        bt[nb(ninki)] += 1; bf[nb(ninki)] += 1 if chaku <= 3 else 0
    exp = {k: bf[k] / bt[k] for k in bt}

    def stat(sub):
        n = len(sub)
        if n == 0:
            return None
        win = sum(1 for r in sub if r[1] == 1)
        fuk = sum(1 for r in sub if r[1] <= 3)
        roi = sum(r[2] for r in sub if r[1] == 1) / n * 100
        e = sum(exp[nb(r[0])] for r in sub)
        var = sum(exp[nb(r[0])] * (1 - exp[nb(r[0])]) for r in sub)
        z = (fuk - e) / math.sqrt(var) if var > 0 else 0
        return {'n': n, 'win': win / n * 100, 'fuk': fuk / n * 100, 'roi': roi,
                'resid': (fuk - e) / n * 100, 'z': z}

    base = stat(recs)
    print("=" * 100)
    print(f"母集団(前走あり 2016-26) n={base['n']:,}  勝率{base['win']:.1f}% "
          f"複勝{base['fuk']:.1f}% 単ROI{base['roi']:.0f}%")
    print("=" * 100)
    hdr = f"{'群':<38}{'n':>9}{'勝率%':>7}{'複勝%':>7}{'単ROI%':>8}{'複残差':>8}{'zF':>7}"
    print(hdr); print("-" * 100)

    groups = [
        ('前走102-109(SS)で勝ち', lambda r: r[3] == '102-109(SS)' and r[4]),
        ('  └ ×今走4番人気以下', lambda r: r[3] == '102-109(SS)' and r[4] and r[0] >= 4),
        ('  └ ×今走7番人気以下', lambda r: r[3] == '102-109(SS)' and r[4] and r[0] >= 7),
        ('前走110+(圧勝)で勝ち', lambda r: r[3] == '110+(圧勝)' and r[4]),
        ('  └ ×今走4番人気以下', lambda r: r[3] == '110+(圧勝)' and r[4] and r[0] >= 4),
        ('前走100-101で勝ち', lambda r: r[3] == '100-101' and r[4]),
        ('--- 参考(勝ち負け問わず前走バンド) ---', None),
        ('前走102-109(着問わず)', lambda r: r[3] == '102-109(SS)'),
        ('前走110+(着問わず)', lambda r: r[3] == '110+(圧勝)'),
    ]
    for name, fn in groups:
        if fn is None:
            print(name); continue
        sub = [r for r in recs if fn(r)]
        s = stat(sub)
        if not s or s['n'] < 80:
            print(f"{name:<38}{(s['n'] if s else 0):>9} (sample<80)"); continue
        print(f"{name:<38}{s['n']:>9}{s['win']:>7.1f}{s['fuk']:>7.1f}"
              f"{s['roi']:>8.0f}{s['resid']:>+8.2f}{s['z']:>+7.2f}")
    print("-" * 100)
    print("資料主張: SS(102-109)勝ち×人気落ちで単ROI>100%。圧勝(110+)は過剰人気で低ROI。")
    print("単ROI100%超かつ複残差z>+2でなければ織込み済み(=戦術①は非採用)。")


if __name__ == '__main__':
    main()
