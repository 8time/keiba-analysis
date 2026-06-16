# -*- coding: utf-8 -*-
"""
圧勝の罠（大谷トラップ）バックテスト
─────────────────────────────────────────────
資料(Racing Quant p4)の主張:
  「前走1.0秒以上の差をつけて圧勝した馬は、過剰人気により単勝回収が66%に急落する危険人気馬」

検証する問い:
  軸候補（=人気上位馬）のうち、前走を 1.0秒以上 で圧勝していた馬は、
  同じ人気帯の他馬より「飛びやすい」か？ ＝ 軸から除外すべきシグナルか？

判定:
  - 対象=今回 1〜N番人気（軸候補）。
  - フラグ=前走 chakujun==1 かつ 着差(=2着とのタイム差) >= margin 秒。
  - フラグ群 vs 同人気帯の非フラグ群で 勝率/複勝率(3着内)/単勝ROI を比較。
  - 軸の土台は「3着内に来るか(複勝率)」。複勝率がフラグ群で有意に低ければ
    『軸から外す』ルールとして価値あり。
すべて人気・ランダムではなく "同人気帯の非フラグ馬" がベースライン（人気の効果を相殺）。
"""
import sys, io, os, sqlite3, argparse
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pace_map import _parse_jv_time

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def date_key(year, monthday):
    try:
        return int(year) * 10000 + int(monthday)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train_from', type=int, default=2014)
    ap.add_argument('--test_from', type=int, default=2021)
    ap.add_argument('--test_to', type=int, default=2025)
    ap.add_argument('--ninki_max', type=int, default=3, help='軸候補とする人気の上限(1..N)')
    ap.add_argument('--margin', type=float, default=1.0, help='圧勝とみなす前走着差(秒)')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print(f"読み込み中... (year>={args.train_from})")
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, chakujun, ninki, win_odds, time "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.train_from,)).fetchall()
    con.close()
    print(f"  results: {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # ── 各レースの勝ち馬の着差(=2着とのタイム差) を計算 ──
    # hist[ketto] = [(date_key, race_key, chakujun, won_margin_or_None)]
    hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        # 着順->time マップ(有効なもの)
        t_by_chaku = {}
        for r in rs:
            if r['chakujun'] and r['chakujun'] > 0:
                t = _parse_jv_time(r['time'])
                if t is not None:
                    t_by_chaku[r['chakujun']] = t
        win_margin = None
        if 1 in t_by_chaku and 2 in t_by_chaku:
            win_margin = t_by_chaku[2] - t_by_chaku[1]
        for r in rs:
            if not r['chakujun'] or r['chakujun'] <= 0:
                continue
            wm = win_margin if r['chakujun'] == 1 else None
            hist[r['ketto_num']].append((dk, rk, r['chakujun'], wm))
    for k in hist:
        hist[k].sort()

    def prev_race(ketto, dk):
        h = hist.get(ketto)
        if not h:
            return None
        past = [x for x in h if x[0] < dk]
        return past[-1] if past else None

    # ── 集計 ──
    def newseg():
        return {'n': 0, 'win': 0, 'fuku': 0, 'odds_sum': 0.0, 'win_odds_sum': 0.0}

    seg_flag = newseg()   # 圧勝罠フラグ(前走1.0秒+圧勝)の人気馬
    seg_base = newseg()   # 同人気帯の非フラグ人気馬
    # 前走勝ち(margin別)の細分も見る
    bins = {'圧勝(>=1.0)': newseg(), '快勝(0.3-1.0)': newseg(), '辛勝(<0.3)': newseg(),
            '前走非勝利': newseg()}

    for rk, rs in by_race.items():
        if not (args.test_from <= int(rs[0]['year']) <= args.test_to):
            continue
        for r in rs:
            nk = r['ninki']
            if not nk or nk < 1 or nk > args.ninki_max:
                continue
            if not r['chakujun'] or r['chakujun'] <= 0:
                continue
            dk = date_key(rs[0]['year'], rs[0]['monthday'])
            pv = prev_race(r['ketto_num'], dk)
            if pv is None:
                continue  # 前走なし(新馬等)は対象外
            _, _, pchaku, pwm = pv
            won = (r['chakujun'] == 1)
            fuku = (r['chakujun'] <= 3)
            wo = r['win_odds'] or 0.0

            def add(seg):
                seg['n'] += 1
                seg['win'] += 1 if won else 0
                seg['fuku'] += 1 if fuku else 0
                if won:
                    seg['win_odds_sum'] += wo

            # margin別bin
            if pchaku == 1 and pwm is not None:
                if pwm >= 1.0:
                    add(bins['圧勝(>=1.0)'])
                elif pwm >= 0.3:
                    add(bins['快勝(0.3-1.0)'])
                else:
                    add(bins['辛勝(<0.3)'])
            else:
                add(bins['前走非勝利'])

            # フラグ vs ベース
            flag = (pchaku == 1 and pwm is not None and pwm >= args.margin)
            add(seg_flag if flag else seg_base)

    def show(name, s):
        if s['n'] == 0:
            print(f"  {name:<16} n=0")
            return
        wr = s['win'] / s['n'] * 100
        fr = s['fuku'] / s['n'] * 100
        roi = s['win_odds_sum'] / s['n'] * 100  # 単勝ROI(各100円賭け)
        print(f"  {name:<16} n={s['n']:>6}  勝率{wr:5.1f}%  複勝率{fr:5.1f}%  単勝ROI{roi:6.1f}%")

    print(f"\n=== 圧勝の罠 検証 (test {args.test_from}-{args.test_to} / 軸候補=1〜{args.ninki_max}番人気 / 圧勝閾値={args.margin}秒) ===")
    print("  ※ win_odds は jravan.db で約63%しか入っておらず欠損が群間で偏るため、単勝ROIは参考値(群間比較は不可)。")
    print("    軸選定の判定は 複勝率(3着内・完全populated) を主指標とする。")
    print(f"[A] フラグ群 vs 同人気帯ベース")
    show(f'圧勝罠フラグ', seg_flag)
    show(f'非フラグ(基準)', seg_base)
    if seg_flag['n'] and seg_base['n']:
        d_fuku = seg_flag['fuku']/seg_flag['n']*100 - seg_base['fuku']/seg_base['n']*100
        d_win  = seg_flag['win']/seg_flag['n']*100 - seg_base['win']/seg_base['n']*100
        print(f"  → 差分: 複勝率 {d_fuku:+.1f}pp / 勝率 {d_win:+.1f}pp  (負なら『軸から外す』根拠)")

    print(f"\n[B] 前走勝ち方 別の今回成績(1〜{args.ninki_max}番人気)")
    for k in ['圧勝(>=1.0)', '快勝(0.3-1.0)', '辛勝(<0.3)', '前走非勝利']:
        show(k, bins[k])


if __name__ == '__main__':
    main()
