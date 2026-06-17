# -*- coding: utf-8 -*-
"""
荒れ予測【事前版】 — レース前に分かる情報だけで荒れ(人気下位馬勝利)を読めるか
──────────────────────────────────────────────────────────────────────────
chaos_predictor_backtest.py で「事後ペース(ato3f-mae3f)が荒れと関係する(ハイペースほど荒れる)」
ことは確認できた。だが事後ペースは予測に使えない。本スクリプトは『レース前に確定している情報』だけ
で荒れを予測できるかを測る:
  (A) 出走頭数 (確定)
  (B) 逃げ・先行馬の数 = 想定ハイペース度 (各馬の過去走の習性脚質から事前推定)
  (C) 1番人気オッズ層 (既知の最強予測子・基準線)

ねらい: (A)+(B) が (C)オッズ を固定しても荒れ率を動かすなら、オッズに無い事前エッジ。
        当たれば『荒れ候補レースをサーチ→②(人気-穴-穴)』が現実的になる。

習性脚質: 各馬の過去走(当該レースより前)の kyakushitsu の最頻値。1=逃げ,2=先行,3=差し,4=追込。
          逃げ/先行(1,2)を「前づけ馬」とし、レース内の前づけ馬数・逃げ馬数を数える。
"""
import os, sys, sqlite3, statistics, argparse
from collections import defaultdict, Counter
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def date_key(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hist_from', type=int, default=2018, help='習性脚質の学習開始年')
    ap.add_argument('--from', dest='yfrom', type=int, default=2021)
    ap.add_argument('--to', dest='yto', type=int, default=2025)
    ap.add_argument('--ana', type=int, default=6)
    ap.add_argument('--k', type=int, default=5, help='習性脚質の直近走数')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 全結果(習性脚質の履歴用) — hist_from以降
    print('読み込み中...')
    rows = con.execute(
        "SELECT race_key, year, monthday, ketto_num, ninki, win_odds, chakujun, kyakushitsu "
        "FROM results WHERE CAST(year AS INTEGER) >= ?", (args.hist_from,)).fetchall()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # 馬ごとの脚質履歴 (date, style)
    style_hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            ks = r['kyakushitsu']
            if ks in ('1', '2', '3', '4'):
                style_hist[r['ketto_num']].append((dk, ks))
    for k in style_hist:
        style_hist[k].sort()

    def habit_style(ketto, dk):
        """当該日より前の直近k走の最頻脚質。なければNone。"""
        h = style_hist.get(ketto)
        if not h:
            return None
        past = [s for (d2, s) in h if d2 < dk]
        if not past:
            return None
        seg = past[-args.k:]
        return Counter(seg).most_common(1)[0][0]

    # テスト対象レース
    races = {}
    for r in con.execute(
        "SELECT race_key, year, monthday, shusso_tosu FROM races WHERE CAST(year AS INTEGER) BETWEEN ? AND ?",
        (args.yfrom, args.yto)):
        races[r['race_key']] = dict(r)
    con.close()

    recs = []
    for rk, R in races.items():
        rs = by_race.get(rk)
        if not rs:
            continue
        dk = date_key(R['year'], R['monthday'])
        win = [r for r in rs if r['chakujun'] == 1 and r['ninki'] and r['ninki'] > 0]
        if not win:
            continue
        chaos = 1 if win[0]['ninki'] >= args.ana else 0
        fav = None
        for r in rs:
            if r['ninki'] == 1 and r['win_odds'] and r['win_odds'] > 0:
                fav = r['win_odds']
        # 前づけ馬カウント(習性脚質が判明した馬のうち)
        nige = senko = known = 0
        for r in rs:
            hs = habit_style(r['ketto_num'], dk)
            if hs is None:
                continue
            known += 1
            if hs == '1':
                nige += 1
            elif hs == '2':
                senko += 1
        tosu = R['shusso_tosu'] or len(rs)
        recs.append({'chaos': chaos, 'fav': fav, 'tosu': tosu,
                     'nige': nige, 'front': nige + senko, 'known': known,
                     'front_ratio': (nige + senko) / known if known >= 5 else None})

    N = len(recs)
    base = sum(r['chaos'] for r in recs) / N
    print(f"\n荒れラベル付き {N:,}R ({args.yfrom}-{args.yto}) / ベース荒れ率(勝ち馬ninki>={args.ana})={base*100:.1f}%\n")

    def show(title, get_b, order=None):
        agg = defaultdict(lambda: {'n': 0, 'c': 0})
        for r in recs:
            b = get_b(r)
            if b is None:
                continue
            agg[b]['n'] += 1
            agg[b]['c'] += r['chaos']
        print(f"■ {title}")
        print(f"  {'バケット':<26}{'n':>8}{'荒れ率':>9}{'リフト':>8}")
        for k in (order or sorted(agg)):
            if k not in agg:
                continue
            a = agg[k]; p = a['c'] / a['n']
            print(f"  {str(k):<26}{a['n']:>8}{p*100:>8.1f}%{p/base:>8.2f}")
        print()

    # (B) 前づけ馬比率
    def fr_bucket(r):
        fr = r['front_ratio']
        if fr is None:
            return None
        if fr < 0.30:
            return '1:前少(<30%)'
        if fr < 0.45:
            return '2:やや少(30-45%)'
        if fr < 0.60:
            return '3:標準(45-60%)'
        return '4:前多(>=60%=ハイ想定)'

    def nige_bucket(r):
        if r['known'] < 5:
            return None
        n = r['nige']
        return {0: '0頭', 1: '1頭', 2: '2頭'}.get(n, '3頭+')

    show('(B) 想定前づけ馬比率(逃げ+先行の習性馬 / 脚質判明馬)', fr_bucket,
         order=['1:前少(<30%)', '2:やや少(30-45%)', '3:標準(45-60%)', '4:前多(>=60%=ハイ想定)'])
    show('(B2) 想定逃げ馬の数(競合=ペース崩れ)', nige_bucket, order=['0頭', '1頭', '2頭', '3頭+'])

    # (C) オッズ層
    fav_recs = [r for r in recs if r['fav']]
    fv = sorted(r['fav'] for r in fav_recs)
    q33 = fv[len(fv) // 3]; q66 = fv[len(fv) * 2 // 3]

    def fav_layer(r):
        if not r['fav']:
            return None
        return '堅' if r['fav'] <= q33 else ('中' if r['fav'] <= q66 else '荒')

    # ── 決定的テスト: オッズ層 × (頭数, 前づけ比率) ──
    print(f"■ オッズ層を固定して 頭数/前づけ比率 が荒れ率を動かすか (q33={q33:.1f}, q66={q66:.1f})")
    print(f"  {'オッズ層':<8}{'サブ条件':<24}{'n':>7}{'荒れ率':>9}{'層内ﾘﾌﾄ':>9}")
    for lay in ['堅', '中', '荒']:
        sub = [r for r in fav_recs if fav_layer(r) == lay]
        sb = sum(r['chaos'] for r in sub) / len(sub)
        print(f"  --- {lay}層 n={len(sub):,} 層内荒れ率={sb*100:.1f}% ---")
        # 頭数
        for lab, cond in [('少頭<=8', lambda r: r['tosu'] <= 8),
                          ('中9-12', lambda r: 9 <= r['tosu'] <= 12),
                          ('多13-15', lambda r: 13 <= r['tosu'] <= 15),
                          ('フル16+', lambda r: r['tosu'] >= 16)]:
            ss = [r for r in sub if cond(r)]
            if len(ss) < 30:
                continue
            p = sum(r['chaos'] for r in ss) / len(ss)
            print(f"  {'':<8}{('頭数:'+lab):<24}{len(ss):>7}{p*100:>8.1f}%{p/sb:>9.2f}")
        # 前づけ比率(高い=ハイ想定)
        for lab, lo, hi in [('前少<45%', -1, 0.45), ('前多>=45%', 0.45, 9)]:
            ss = [r for r in sub if r['front_ratio'] is not None and lo < r['front_ratio'] <= hi]
            if len(ss) < 30:
                continue
            p = sum(r['chaos'] for r in ss) / len(ss)
            print(f"  {'':<8}{('前づけ:'+lab):<24}{len(ss):>7}{p*100:>8.1f}%{p/sb:>9.2f}")
    print()

    # ── 実戦サーチ条件: 「中〜荒オッズ層 × フル頭数 × 前づけ多」を②候補とした時の荒れ率 ──
    cand = [r for r in fav_recs
            if fav_layer(r) in ('中', '荒') and r['tosu'] >= 14
            and r['front_ratio'] is not None and r['front_ratio'] >= 0.45]
    if cand:
        cp = sum(r['chaos'] for r in cand) / len(cand)
        print(f"★ ②サーチ候補 [中/荒層 × 14頭+ × 前づけ>=45%]: {len(cand):,}R "
              f"荒れ率 {cp*100:.1f}% (ベース{base*100:.1f}%の {cp/base:.2f}倍)")
    print("\n" + "=" * 72)
    print("【読み方】 層内リフト>1.2 = オッズで分かる以上に頭数/想定ペースが荒れを上乗せ=事前エッジ。")
    print("          ★サーチ候補の荒れ率がベースを大きく超えるなら、その条件でレースを抽出し②を当てる。")


if __name__ == '__main__':
    main()
