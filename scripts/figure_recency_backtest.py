# -*- coding: utf-8 -*-
"""
#1「5走前理論(記憶ハック)」の検証 — scripts/figure_recency_backtest.py

資料(競馬データサイエンス)の主張:
  「Nレース前(特に4走前・5走前)に補正タイム100超え(=好走)を出した馬は、近走不振で
   忘れ去られ人気が甘くなる→今走で激走。5走前100超えで単勝回収率219%/複勝161%」

検証する問い: Nレース前に好補正タイムを出した馬は、今走で
  ① 同じ人気順位の馬より来る(=人気を超える残差)か?
  ② 単勝ROIがプラス(>100%)か?
  ③ 近走(前走)より過去走(5走前)の方が"忘れられて"妙味が出るか?

自前補正タイム(scripts/corrected_time_backtest.pyと同一・馬場コード非依存):
  sec→baseline(surface,距離中央値)→raw_dev→track_bias(同日同コース中央値)→corrected(負=速い)
「補正タイム100超え(勝ち負けレベル)」の自前換算 = 勝ち馬(chakujun==1)のcorrected中央値以下。

統制/制約:
  ・オッズ/人気/ROIは win_odds が要るので **検証対象=2016-2026(最重要・オッズ完備)**。
    (1986-95はオッズ無し期間。較正用の生タイムは全期間使う)
  ・残差は人気順位(ninki)で統制。リーク無し: N走前は今走より前のレースのみ参照。
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
TEST_FROM, TEST_TO = 2016, 2026  # オッズ完備の最重要期間
MAX_N = 6                         # 何走前まで見るか


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

    # corrected
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

    # 「100超え」閾値 = 勝ち馬corrected中央値(=勝ち負けレベル)
    win_vals = [x[9] for x in rows if x[5] == 1 and x[9] is not None]
    T = median(win_vals)
    print(f"勝ち馬corrected中央値(=補正100相当の閾値)= {T:.2f} (これ以下=好補正)", file=sys.stderr)

    # per-horse 時系列(全期間, corrected有効のみ)
    hist = defaultdict(list)
    for x in rows:
        if x[9] is not None:
            hist[x[4]].append((x[0], x[9]))
    for k in hist:
        hist[k].sort()  # 昇順(古→新)

    # test rows: 2016-2026 かつ win_odds>0
    recs = []  # (ninki, chaku, odds, strongN_list[bool x MAX_N], any_strong, prev_strong3)
    for x in rows:
        y = x[0] // 10000
        if not (TEST_FROM <= y <= TEST_TO):
            continue
        if x[7] <= 0 or x[6] >= 99:
            continue
        arr = hist.get(x[4], [])
        # x[0]=day。今走より前の run を新しい順に
        prior = [c for (d, c) in arr if d < x[0]][::-1]  # prior[0]=前走
        strongN = []
        for n in range(MAX_N):
            strongN.append(prior[n] <= T if n < len(prior) else None)
        any_strong = any(c <= T for c in prior) if prior else False
        prev3_strong = any((prior[i] <= T) for i in range(min(3, len(prior))))
        recs.append((x[6], x[5], x[7], strongN, any_strong, prev3_strong, len(prior)))

    print(f"test horse-runs(2016-26,オッズ有)={len(recs):,}", file=sys.stderr)

    # 人気順位ベースライン(複勝率/勝率)
    def nb(n):
        return min(n, 15)
    bt = defaultdict(int); bf = defaultdict(int); bw = defaultdict(int)
    for (ninki, chaku, odds, sN, anyS, p3, npri) in recs:
        k = nb(ninki); bt[k] += 1
        bf[k] += 1 if chaku <= 3 else 0
        bw[k] += 1 if chaku == 1 else 0
    exp_f = {k: bf[k] / bt[k] for k in bt}
    exp_w = {k: bw[k] / bt[k] for k in bt}

    def stat(sub):
        n = len(sub)
        if n == 0:
            return None
        win = sum(1 for r in sub if r[1] == 1)
        fuk = sum(1 for r in sub if r[1] <= 3)
        roi = sum(r[2] for r in sub if r[1] == 1) / n * 100
        e_f = sum(exp_f[nb(r[0])] for r in sub)
        e_w = sum(exp_w[nb(r[0])] for r in sub)
        var_f = sum(exp_f[nb(r[0])] * (1 - exp_f[nb(r[0])]) for r in sub)
        z_f = (fuk - e_f) / math.sqrt(var_f) if var_f > 0 else 0
        return {'n': n, 'win': win / n * 100, 'fuk': fuk / n * 100, 'roi': roi,
                'fuk_resid': (fuk - e_f) / n * 100, 'z_f': z_f,
                'win_resid': (win - e_w) / n * 100}

    base = stat(recs)
    print("=" * 100)
    print(f"母集団 {TEST_FROM}-{TEST_TO}(芝ダ・オッズ有): n={base['n']:,}  "
          f"勝率{base['win']:.1f}% 複勝率{base['fuk']:.1f}% 単勝ROI{base['roi']:.0f}%")
    print(f"好補正の閾値=勝ち馬corrected中央値({T:.2f})以下。残差=同人気順位の平均からの乖離pp。")
    print("=" * 100)
    hdr = f"{'群':<34}{'n':>9}{'勝率%':>7}{'複勝%':>7}{'単ROI%':>8}{'複残差':>8}{'zF':>7}"
    print(hdr); print("-" * 100)

    groups = []
    for n in range(MAX_N):
        groups.append((f'{n+1}走前が好補正', lambda r, n=n: r[3][n] is True))
    groups.append(('--- 人気落ち(4番人気以下)条件 ---', None))
    for n in (3, 4):  # 4走前/5走前 × 人気薄(資料の主張ゾーン)
        groups.append((f'{n+1}走前好補正 × 4番人気以下', lambda r, n=n: r[3][n] is True and r[0] >= 4))
    groups.append((f'5走前好補正 × 7番人気以下', lambda r: r[3][4] is True and r[0] >= 7))
    groups.append(('--- 対照 ---', None))
    groups.append(('過去どこかで好補正(any)', lambda r: r[4]))
    groups.append(('前3走に好補正あり', lambda r: r[5]))
    groups.append(('過去好補正なし', lambda r: not r[4] and r[6] >= 1))

    for name, fn in groups:
        if fn is None:
            print(name); continue
        sub = [r for r in recs if fn(r)]
        s = stat(sub)
        if not s or s['n'] < 80:
            print(f"{name:<34}{(s['n'] if s else 0):>9} (sample<80)"); continue
        print(f"{name:<34}{s['n']:>9}{s['win']:>7.1f}{s['fuk']:>7.1f}"
              f"{s['roi']:>8.0f}{s['fuk_resid']:>+8.2f}{s['z_f']:>+7.2f}")
    print("-" * 100)
    print("単ROI100%超=理論プラス。複残差z>+2かつ人気薄で正なら『人気を超えて来る妙味』。")
    print("資料主張(5走前→単ROI219%)が再現するか? 近走好補正と過去走好補正でROI差が出るか(=忘却効果)を見る。")


if __name__ == '__main__':
    main()
