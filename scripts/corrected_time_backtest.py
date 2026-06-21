# -*- coding: utf-8 -*-
"""
自前「補正タイム」の妙味検証 (Corrected-Time / speed-figure backtest)

JRA-VANに補正タイムは無い(生の走破タイムと馬場状態コードのみ)。
そこで馬場コードの解釈に依存しない方法で補正タイムを自作する:

  1) sec      = 走破タイムを秒に変換 ('1543'→1分54.3秒=114.3)
  2) baseline = (馬場surface, 距離kyori) ごとの中央値タイム
  3) raw_dev  = sec − baseline                      … 距離・コース差を除去
  4) track    = (開催日, 競馬場, surface) ごとの raw_dev 中央値 … その日の馬場の速い/遅いを除去
  5) corrected= raw_dev − track  (負=基準より速い) ← これを「補正タイム(偏差)」とする

  ※ 馬場差を「同日同コースの偏差」で吸収するので、良/重などコードの当否に依存しない。
  ※ track は同レースの自馬も含む field-relative 図(スピード指数の標準的作法)。
     予測に使うのは各馬の『過去走の補正タイム』のみ(リーク無し)。

問い(中核目標: 過小評価の勝ち馬を拾う):
  過去走の補正タイムが今日のメンバー中で上位なのに人気が無い馬は、
  オッズ帯期待を超えて複勝に来る(=妙味)か? それとも織込み済みか?

統制: win_odds帯ごとに複勝率の期待を作り、各サブセットの残差(z)で測る([[verified_spurt_index]]と同型)。
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

BASELINE_FROM = 1990          # baseline / track 較正に使う最古年
TEST_FROM, TEST_TO = 2019, 2025  # ランキング検証の対象年(過去走は全年から参照)
MIN_PAST = 1                  # 過去走が最低この本数ある馬だけ図を持つ
FIG_TOP = 3                   # レース内で補正タイム上位何頭を「速い図」とみなすか
ODDS_EDGES = [1.5, 2, 2.5, 3, 4, 5, 7, 10, 15, 25, 1e9]


def to_sec(t):
    """'1543' -> 114.3 sec。'0000'や不正は None。"""
    if not t or len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    m = int(t[0]); ss = int(t[1:3]); f = int(t[3])
    sec = m * 60 + ss + f / 10.0
    if sec < 50 or sec > 360:
        return None
    return sec


def oband(o):
    o = o if (o and o > 0) else 1e9
    for i, e in enumerate(ODDS_EDGES):
        if o <= e:
            return i
    return len(ODDS_EDGES) - 1


def connect_ro():
    for _ in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            _time.sleep(4)
    raise SystemExit("DB locked")


def main():
    con = connect_ro()
    print("loading rows...", file=sys.stderr)
    q = f"""SELECT ra.year, ra.monthday, ra.race_num, ra.race_id, ra.jyo,
                   ra.surface, ra.kyori,
                   r.ketto_num, r.chakujun, r.ninki, r.win_odds, r.time
            FROM races ra JOIN results r ON r.race_key = ra.race_key
            WHERE ra.surface IN ('芝','ダート')
              AND CAST(ra.year AS INTEGER) >= {BASELINE_FROM}
              AND r.chakujun > 0"""
    rows = []
    for (yr, md, rn, rid, jyo, surf, kyori, ketto, chaku, ninki, wo, tm) in con.execute(q):
        sec = to_sec(tm)
        if sec is None:
            continue
        try:
            y = int(yr); mdi = int(md); day = y * 10000 + mdi
        except Exception:
            continue
        rows.append([day, rid, jyo, surf, int(kyori), ketto, int(chaku),
                     (int(ninki) if ninki else 99), (float(wo) if wo else 0.0), sec, None])
    con.close()
    print(f"valid runs: {len(rows):,}", file=sys.stderr)

    # 1) baseline median per (surface, kyori)
    by_sk = defaultdict(list)
    for x in rows:
        by_sk[(x[3], x[4])].append(x[9])
    baseline = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}

    # 3) raw_dev
    for x in rows:
        b = baseline.get((x[3], x[4]))
        x[10] = (x[9] - b) if b is not None else None

    # 4) track bias per (day, jyo, surface) median raw_dev
    by_track = defaultdict(list)
    for x in rows:
        if x[10] is not None:
            by_track[(x[0], x[2], x[3])].append(x[10])
    track_bias = {k: median(v) for k, v in by_track.items() if len(v) >= 4}

    # 5) corrected = raw_dev − track_bias
    corrected = {}  # id(x) not stable; store inline as x[10] replaced
    for x in rows:
        if x[10] is None:
            continue
        tb = track_bias.get((x[0], x[2], x[3]))
        x[10] = (x[10] - tb) if tb is not None else None

    # build per-horse chronological corrected history
    hist = defaultdict(list)  # ketto -> list of (day, corrected)
    for x in rows:
        if x[10] is not None:
            hist[x[5]].append((x[0], x[10]))
    for k in hist:
        hist[k].sort()

    def past_best(ketto, day):
        """day より前の最速(最小)補正タイムと本数。"""
        arr = hist.get(ketto)
        if not arr:
            return None, 0
        vals = [c for (d, c) in arr if d < day]
        if len(vals) < MIN_PAST:
            return None, len(vals)
        return min(vals), len(vals)

    # group test rows by race
    races = defaultdict(list)
    for x in rows:
        y = x[0] // 10000
        if TEST_FROM <= y <= TEST_TO:
            races[x[1]].append(x)

    # per-horse record for test: (band, fukusho, ninki, odds, fig_rank, is_fast, has_fig)
    recs = []
    for rid, hs in races.items():
        day = hs[0][0]
        figs = []
        for x in hs:
            pb, n = past_best(x[5], day)
            figs.append(pb)
        # rank by past corrected fig (ascending: faster=smaller). None goes last.
        order = sorted(range(len(hs)), key=lambda i: (figs[i] is None, figs[i] if figs[i] is not None else 1e9))
        fig_rank = {}
        rr = 0
        for i in order:
            if figs[i] is not None:
                rr += 1
                fig_rank[i] = rr
        for i, x in enumerate(hs):
            band = oband(x[8])
            fuk = 1 if x[6] <= 3 else 0
            has = i in fig_rank
            is_fast = has and fig_rank[i] <= FIG_TOP
            recs.append((band, fuk, x[7], x[8], fig_rank.get(i, 99), is_fast, has))

    print(f"test horse-runs: {len(recs):,}  (races={len(races):,})", file=sys.stderr)

    # 統制キー = 人気順位(市場コンセンサス)。同じ人気の馬どうしで補正図の効果を測る。
    # (オッズ帯だと帯が粗く不均質で残差が歪むため、ninkiで統制する)
    def nband(ninki):
        return min(ninki, 15) if ninki and ninki < 99 else 99
    btot = defaultdict(int); bfuk = defaultdict(int)
    for (band, fuk, ninki, odds, fr, fast, has) in recs:
        nb = nband(ninki)
        btot[nb] += 1; bfuk[nb] += fuk
    exp_n = {b: bfuk[b] / btot[b] for b in btot}
    exp = {}  # not used (kept for compat)

    def stat(sub):
        n = len(sub)
        if n == 0:
            return None
        fuk = sum(r[1] for r in sub)
        e = sum(exp_n[nband(r[2])] for r in sub)
        var = sum(exp_n[nband(r[2])] * (1 - exp_n[nband(r[2])]) for r in sub)
        z = (fuk - e) / math.sqrt(var) if var > 0 else 0
        return {'n': n, 'fuk': fuk / n * 100, 'resid': (fuk - e) / n * 100, 'z': z}

    base_fuk = sum(r[1] for r in recs) / len(recs) * 100
    print("=" * 96)
    print(f"検証母集団 {TEST_FROM}-{TEST_TO}(芝ダ): 馬延べ{len(recs):,}  複勝率(全体){base_fuk:.1f}%")
    print(f"補正タイム = (生秒 − [surface,距離]中央値) − [同日同コース]中央値。図=過去走の最小(最速)補正。")
    print("=" * 96)
    hdr = f"{'群':<40}{'n':>9}{'複勝%':>8}{'残差pp':>9}{'z':>8}"
    print(hdr); print("-" * 96)

    groups = [
        ('全馬(過去図あり)', lambda r: r[6]),
        (f'補正図トップ{FIG_TOP}(全人気)', lambda r: r[5]),
        ('--- 人気帯 × 補正図トップ ---', None),
        (f'1-2番人気 × 図トップ{FIG_TOP}', lambda r: r[5] and r[2] <= 2),
        (f'3-5番人気 × 図トップ{FIG_TOP}', lambda r: r[5] and 3 <= r[2] <= 5),
        (f'6番人気以下 × 図トップ{FIG_TOP} ★', lambda r: r[5] and r[2] >= 6),
        (f'9番人気以下 × 図トップ{FIG_TOP} ★', lambda r: r[5] and r[2] >= 9),
        ('--- 対照: 人気薄(図トップ外) ---', None),
        ('6番人気以下(図トップ外)', lambda r: (not r[5]) and r[2] >= 6 and r[6]),
        ('6番人気以下(過去図なし)', lambda r: (not r[6]) and r[2] >= 6),
    ]
    for name, fn in groups:
        if fn is None:
            print(name); continue
        sub = [r for r in recs if fn(r)]
        s = stat(sub)
        if not s or s['n'] < 80:
            print(f"{name:<40}{(s['n'] if s else 0):>9} (sample<80)"); continue
        print(f"{name:<40}{s['n']:>9}{s['fuk']:>8.1f}{s['resid']:>+9.2f}{s['z']:>+8.2f}")
    print("-" * 96)
    print("残差=同人気順位(ninki)の馬の平均複勝率からの乖離pp。z>+2 かつ人気薄で正なら『人気を超えて来る=妙味』。")
    print("残差≈0なら織込み済み(=補正タイム単体を妙味根拠にできない)。")


if __name__ == '__main__':
    main()
