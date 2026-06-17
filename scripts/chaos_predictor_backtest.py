# -*- coding: utf-8 -*-
"""
荒れ予測 バックテスト — 「ペース/トラックバイアスは荒れ(人気下位馬が勝つ)を予測できるか」
──────────────────────────────────────────────────────────────────────────
ユーザー要望: 「トラックバイアスとかペースチェンジ指数でその日のレースが荒れる
            (人気下位馬が勝つ)かの予測精度をあげたい。当たれば荒れるレースをサーチで
            出して②(人気-穴-穴)で賭ければいい」

前提(検証済): オッズ(1番人気の支持率)で荒れ度を当てるのは無理だった
            (scripts/trio_selector_backtest.py: ②は最も荒れる層でも22%止まり)。
            → エッジは『オッズに織り込まれていない荒れ要因』にしかない。候補=ペース/馬場。

検証する仮説:
  H1: ハイペース(前半が速い=ato3f-mae3f大)のレースは差し決着で荒れやすい
  H2: クッション値/含水率(馬場の硬軟・水分)が極端なレースは荒れやすい
  H3: 多頭数レースは荒れやすい

重要な但し書き:
  mae3f/ato3f は『レース後』に確定する事後情報。本バックテストは
  「ペース/馬場が荒れと"関係するか"」を測る第一歩であって、「事前に予測できるか」では
  ない。関係があると分かって初めて、脚質(kyakushitsu)から事前にペースを読む器
  (=展開マップ再構築プロジェクト)を作る価値が出る。関係が無ければこの路線は死に筋。

荒れの定義: 勝ち馬(chakujun=1)の ninki >= ANA_TH (デフォ6) = 人気下位馬が勝った。
データ: jravan.db / races(mae3f,ato3f,kyori,surface,shusso_tosu) + results(勝ち馬ninki)
        + track_cond(cushion,dirt_moisture) を (year,monthday,jyo) で結合。
"""
import os, sys, sqlite3, statistics, argparse
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH


def lift(p_bucket, p_base):
    """バケットの荒れ率がベースの何倍か(リフト)。1.0=情報ゼロ。"""
    return p_bucket / p_base if p_base else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='yfrom', type=int, default=2021)
    ap.add_argument('--to', dest='yto', type=int, default=2025)
    ap.add_argument('--ana', type=int, default=6, help='荒れ=勝ち馬ninki>=ana')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # レース基本情報
    races = {}
    for r in con.execute(
        "SELECT race_key, year, monthday, jyo, kyori, surface, shusso_tosu, mae3f, ato3f "
        "FROM races WHERE CAST(year AS INTEGER) BETWEEN ? AND ?", (args.yfrom, args.yto)):
        races[r['race_key']] = dict(r)
    print(f"レース {len(races):,} 件 ({args.yfrom}-{args.yto})")

    # 勝ち馬の人気 + 1番人気オッズ(荒れ度のオッズ代理・層別用)
    win_ninki = {}
    fav_odds = {}
    for r in con.execute(
        "SELECT race_key, ninki, win_odds, chakujun FROM results WHERE ninki>0"):
        rk = r['race_key']
        if rk not in races:
            continue
        if r['chakujun'] == 1:
            win_ninki[rk] = r['ninki']
        if r['ninki'] == 1 and r['win_odds'] and r['win_odds'] > 0:
            fav_odds[rk] = r['win_odds']

    # track_cond を (year,monthday,jyo) で
    tc = {}
    for r in con.execute("SELECT year, monthday, jyo, cushion, dirt_moisture FROM track_cond"):
        tc[(r['year'], r['monthday'], r['jyo'])] = (r['cushion'], r['dirt_moisture'])
    con.close()

    # ── レース×荒れラベル × 各種素材 ──
    recs = []
    for rk, R in races.items():
        wn = win_ninki.get(rk)
        if not wn:
            continue
        chaos = 1 if wn >= args.ana else 0
        # ペース指数(後半-前半, 1/10秒): 正=ハイ(前傾), 負=スロー(後傾)
        pace = None
        if R['mae3f'] and R['ato3f'] and R['mae3f'] > 0 and R['ato3f'] > 0:
            pace = R['ato3f'] - R['mae3f']
        cush, moist = tc.get((R['year'], R['monthday'], R['jyo']), (None, None))
        recs.append({
            'rk': rk, 'chaos': chaos, 'pace': pace,
            'surf': R['surface'], 'band': (R['kyori'] or 0) // 400,
            'tosu': R['shusso_tosu'] or 0, 'fav': fav_odds.get(rk),
            'cush': cush if (cush and cush > 0) else None,
            'moist': moist if (moist and moist > 0) else None,
        })

    N = len(recs)
    base = sum(r['chaos'] for r in recs) / N
    print(f"荒れラベル付き {N:,}R / ベース荒れ率(勝ち馬ninki>={args.ana}) = {base*100:.1f}%\n")

    def show_buckets(title, get_bucket, order=None, note=''):
        agg = defaultdict(lambda: {'n': 0, 'c': 0})
        for r in recs:
            b = get_bucket(r)
            if b is None:
                continue
            agg[b]['n'] += 1
            agg[b]['c'] += r['chaos']
        keys = order or sorted(agg.keys())
        print(f"■ {title} {note}")
        print(f"  {'バケット':<26}{'n':>8}{'荒れ率':>9}{'リフト':>8}")
        for k in keys:
            if k not in agg:
                continue
            a = agg[k]
            p = a['c'] / a['n'] if a['n'] else 0
            print(f"  {str(k):<26}{a['n']:>8}{p*100:>8.1f}%{lift(p, base):>8.2f}")
        print()

    # ── H1: ペース(サーフェス+距離band内で標準化→五分位) ──
    # 距離・馬場で絶対ペースが違うので、グループ内zスコア化してから分位
    grp = defaultdict(list)
    for r in recs:
        if r['pace'] is not None:
            grp[(r['surf'], r['band'])].append(r['pace'])
    stats = {}
    for g, vs in grp.items():
        if len(vs) >= 30:
            stats[g] = (statistics.mean(vs), statistics.pstdev(vs) or 1.0)
    for r in recs:
        r['pace_z'] = None
        if r['pace'] is not None and (r['surf'], r['band']) in stats:
            m, sd = stats[(r['surf'], r['band'])]
            r['pace_z'] = (r['pace'] - m) / sd

    def pace_bucket(r):
        z = r.get('pace_z')
        if z is None:
            return None
        if z <= -0.8:
            return '1:超スロー(後傾)'
        if z <= -0.25:
            return '2:ややスロー'
        if z < 0.25:
            return '3:ミドル'
        if z < 0.8:
            return '4:ややハイ'
        return '5:超ハイ(前傾)'

    n_pace = sum(1 for r in recs if r.get('pace_z') is not None)
    show_buckets('H1 ペース指数(後半3F-前半3F・距離馬場内標準化)', pace_bucket,
                 order=['1:超スロー(後傾)', '2:ややスロー', '3:ミドル', '4:ややハイ', '5:超ハイ(前傾)'],
                 note=f'(ペース判明{n_pace:,}R={n_pace*100//N}%)')

    # ── H2: クッション値 / 含水率 ──
    def cush_bucket(r):
        c = r['cush']
        if c is None:
            return None
        if c < 8.5:
            return 'a:やわ(<8.5)'
        if c < 9.5:
            return 'b:標準(8.5-9.5)'
        if c < 10.5:
            return 'c:ややかた(9.5-10.5)'
        return 'd:かた(>=10.5)'

    def moist_bucket(r):
        m = r['moist']
        if m is None:
            return None
        if m < 5:
            return 'a:乾(<5%)'
        if m < 10:
            return 'b:やや乾(5-10%)'
        if m < 15:
            return 'c:湿(10-15%)'
        return 'd:多湿(>=15%)'

    n_cush = sum(1 for r in recs if r['cush'] is not None)
    show_buckets('H2a クッション値(芝)', cush_bucket,
                 order=['a:やわ(<8.5)', 'b:標準(8.5-9.5)', 'c:ややかた(9.5-10.5)', 'd:かた(>=10.5)'],
                 note=f'(判明{n_cush:,}R)')
    show_buckets('H2b 含水率(ダート)', moist_bucket,
                 order=['a:乾(<5%)', 'b:やや乾(5-10%)', 'c:湿(10-15%)', 'd:多湿(>=15%)'])

    # ── H3: 頭数 ──
    def tosu_bucket(r):
        t = r['tosu']
        if t <= 0:
            return None
        if t <= 8:
            return '1:少頭(<=8)'
        if t <= 12:
            return '2:中(9-12)'
        if t <= 15:
            return '3:多(13-15)'
        return '4:フル(16+)'

    show_buckets('H3 出走頭数', tosu_bucket,
                 order=['1:少頭(<=8)', '2:中(9-12)', '3:多(13-15)', '4:フル(16+)'])

    # ── 参考: オッズ(1番人気)層 — 既知の最強予測子と比較 ──
    fav_recs = [r for r in recs if r['fav']]
    if fav_recs:
        fv = sorted(r['fav'] for r in fav_recs)
        q33 = fv[len(fv) // 3]
        q66 = fv[len(fv) * 2 // 3]

        def fav_bucket(r):
            if not r['fav']:
                return None
            if r['fav'] <= q33:
                return f'A:堅(<={q33:.1f})'
            if r['fav'] <= q66:
                return f'B:中(<={q66:.1f})'
            return 'C:荒(1番人気薄)'

        show_buckets('(参考) 1番人気オッズ層 = 既知の荒れ予測子', fav_bucket,
                     order=[f'A:堅(<={q33:.1f})', f'B:中(<={q66:.1f})', 'C:荒(1番人気薄)'])

    # ── 条件付き: オッズ層を固定して、ペースが追加情報を持つか ──
    # (オッズで既に分かる分を超えてペースが効くか=これが本当のエッジ)
    if fav_recs:
        print("■ オッズ層×ペース = ペースはオッズを超える追加情報か(これがエッジの核心)")
        print(f"  {'オッズ層 / ペース':<30}{'n':>8}{'荒れ率':>9}{'層内リフト':>10}")
        for fb_lo, fb_hi, fb_name in [(0, q33, '堅'), (q33, q66, '中'), (q66, 9e9, '荒')]:
            sub = [r for r in fav_recs if fb_lo < r['fav'] <= fb_hi and r.get('pace_z') is not None]
            if len(sub) < 50:
                continue
            sub_base = sum(r['chaos'] for r in sub) / len(sub)
            print(f"  --- {fb_name}層 (n={len(sub):,}, 層内荒れ率={sub_base*100:.1f}%) ---")
            for lab, lo, hi in [('スロー(z<=-0.25)', -9, -0.25), ('ミドル', -0.25, 0.25), ('ハイ(z>=0.25)', 0.25, 9)]:
                ss = [r for r in sub if lo < r['pace_z'] <= hi] if lab != 'スロー(z<=-0.25)' else [r for r in sub if r['pace_z'] <= -0.25]
                if not ss:
                    continue
                p = sum(r['chaos'] for r in ss) / len(ss)
                print(f"    {lab:<26}{len(ss):>8}{p*100:>8.1f}%{lift(p, sub_base):>10.2f}")
        print()

    print("=" * 72)
    print("【読み方】 リフト>1.2 なら荒れ率がベースの2割増し以上=シグナルあり。")
    print(" 特に『オッズ層×ペース』でオッズ層を固定してもペースで荒れ率が動くなら、")
    print(" それはオッズに織り込まれていない真のエッジ→事前ペース予測器を作る価値がある。")
    print(" 動かないなら、ペースはオッズの焼き直しで②サーチには使えない。")


if __name__ == '__main__':
    main()
