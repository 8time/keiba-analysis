# -*- coding: utf-8 -*-
"""
Path1: 事前ペース予測器の検証 — テン速力(実時計)で事前ペースを読み、オッズを超えるか
──────────────────────────────────────────────────────────────────────────
chaos系の検証で判明したこと:
  ・事後ペース(後半3F-前半3F)は荒れと本物の相関、オッズ層固定でも効く(堅層1.27倍)。
  ・だが習性脚質コードからの事前ペース予測ではシグナル消失(中/荒層で横ばい)。
仮説(Path1): 脚質"コード"でなく テン速力=実時計((走破タイム-上がり3F)/(距離-600)*600) で
            各馬の本当の前進力を測り、出走馬の速い数頭から事前ペースを合成すれば、
            事後ペースのエッジを事前に取り戻せるのではないか。

2段検証:
  STEP1 当たるか : 事前予測ペース vs 実際の前半ペース(races.mae3f, 距離馬場内z) の相関。
  STEP2 効くか   : 予測ペースのバケットで荒れ率(勝ち馬ninki>=ana)が、オッズ層を固定しても動くか。

テン速力 = (parse(time) - ato3f/10) / (kyori-600) * 600  [秒/600m, 小さい=テン速い=前]
事前予測ペース(レース) = 出走馬の テン速力 のうち速い上位TOPK頭の平均(=隊列前方が作るペース)
  低いほど速いペース想定。距離馬場内でz化し符号反転して pace_intensity(高い=ハイ想定)。
各馬の事前テン速力 = 当該race_key未満の過去走を 条件類似(同馬場±400m)×直近0.82^i で加重平均。
"""
import os, sys, sqlite3, statistics, argparse
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj
from core.pace_map import _parse_jv_time

DB = jj.JV_DB_PATH


def date_key(y, md):
    try:
        return int(y) * 10000 + int(md)
    except Exception:
        return 0


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n; my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    sy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hist_from', type=int, default=2018)
    ap.add_argument('--from', dest='yfrom', type=int, default=2021)
    ap.add_argument('--to', dest='yto', type=int, default=2025)
    ap.add_argument('--ana', type=int, default=6)
    ap.add_argument('--k', type=int, default=5, help='各馬テン速力の直近走数')
    ap.add_argument('--topk', type=int, default=3, help='ペースを作る前方頭数')
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    print('読み込み中...')
    rows = con.execute(
        "SELECT r.race_key, r.year, r.monthday, r.ketto_num, r.ninki, r.win_odds, "
        "r.chakujun, r.ato3f, r.time, ra.kyori, ra.surface, ra.shusso_tosu, ra.mae3f "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "WHERE CAST(r.year AS INTEGER) >= ?", (args.hist_from,)).fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['race_key']].append(r)

    # 各馬の テン速力 履歴: ketto -> [(date_key, ten_speed, surf, kyori), ...]
    tspeed_hist = defaultdict(list)
    for rk, rs in by_race.items():
        dk = date_key(rs[0]['year'], rs[0]['monthday'])
        for r in rs:
            if r['chakujun'] is None or r['chakujun'] <= 0:
                continue
            t = _parse_jv_time(r['time'])
            ato = r['ato3f']
            ky = r['kyori']
            if t is None or not ato or ato <= 0 or not ky or ky <= 700:
                continue
            ts = (t - ato / 10.0) / (ky - 600) * 600.0
            if 25.0 < ts < 60.0:
                tspeed_hist[r['ketto_num']].append((dk, ts, r['surface'], ky))
    for k in tspeed_hist:
        tspeed_hist[k].sort()
    print(f"  テン速力履歴を持つ馬 {len(tspeed_hist):,}頭")

    def pre_tspeed(ketto, dk, surf, ky):
        """当該日より前の過去走の条件・直近加重テン速力。None=履歴不足。"""
        h = tspeed_hist.get(ketto)
        if not h:
            return None
        past = [(d, ts, s, k) for (d, ts, s, k) in h if d < dk]
        if len(past) < 2:
            return None
        past = past[-args.k:][::-1]  # 新しい順 idx=0最新
        num = den = 0.0
        for idx, (d, ts, s, k) in enumerate(past):
            cw = 1.0
            if surf and s:
                cw *= 1.6 if str(surf) == str(s) else 0.5
            if ky and k:
                cw *= 1.4 if abs(k - ky) <= 400 else 0.6
            w = cw * (0.82 ** idx)
            num += ts * w; den += w
        return num / den if den else None

    # ── 各テストレースの 予測ペース・実ペースz・荒れ・オッズ ──
    grp_mae = defaultdict(list)   # (surf,band) -> [mae3f] 実ペース標準化用
    recs = []
    for rk, rs in by_race.items():
        y = rs[0]['year']
        if not (args.yfrom <= int(y) <= args.yto):
            continue
        surf = rs[0]['surface']; ky = rs[0]['kyori']
        band = (ky or 0) // 400
        dk = date_key(y, rs[0]['monthday'])
        win = [r for r in rs if r['chakujun'] == 1 and r['ninki'] and r['ninki'] > 0]
        if not win:
            continue
        chaos = 1 if win[0]['ninki'] >= args.ana else 0
        fav = None
        for r in rs:
            if r['ninki'] == 1 and r['win_odds'] and r['win_odds'] > 0:
                fav = r['win_odds']
        # 出走各馬の事前テン速力
        tsps = []
        for r in rs:
            v = pre_tspeed(r['ketto_num'], dk, surf, ky)
            if v is not None:
                tsps.append(v)
        if len(tsps) < args.topk + 2:
            continue
        tsps.sort()  # 小さい=速い
        pred_pace = sum(tsps[:args.topk]) / args.topk   # 前方TOPKの平均テン速力(小=ハイ想定)
        mae = rs[0]['mae3f']
        mae_actual = mae if (mae and mae > 0) else None
        if mae_actual is not None:
            grp_mae[(surf, band)].append(mae_actual)
        recs.append({'rk': rk, 'surf': surf, 'band': band, 'chaos': chaos, 'fav': fav,
                     'pred_pace': pred_pace, 'mae': mae_actual})

    # 予測ペースを距離馬場内でz化(符号反転=高いほどハイ想定), 実maeも同様
    grp_pred = defaultdict(list)
    for r in recs:
        grp_pred[(r['surf'], r['band'])].append(r['pred_pace'])
    pred_stats = {g: (statistics.mean(v), statistics.pstdev(v) or 1.0)
                  for g, v in grp_pred.items() if len(v) >= 30}
    mae_stats = {g: (statistics.mean(v), statistics.pstdev(v) or 1.0)
                 for g, v in grp_mae.items() if len(v) >= 30}
    for r in recs:
        g = (r['surf'], r['band'])
        if g in pred_stats:
            m, sd = pred_stats[g]
            r['pred_z'] = -(r['pred_pace'] - m) / sd     # 高い=速い=ハイ想定
        else:
            r['pred_z'] = None
        if r['mae'] is not None and g in mae_stats:
            m, sd = mae_stats[g]
            r['mae_z'] = -(r['mae'] - m) / sd             # 高い=前半速い=ハイ
        else:
            r['mae_z'] = None

    N = len(recs)
    base = sum(r['chaos'] for r in recs) / N
    print(f"\n対象 {N:,}R ({args.yfrom}-{args.yto}) / ベース荒れ率={base*100:.1f}% / topk={args.topk}\n")

    # ── STEP1: 予測ペース vs 実ペース ──
    both = [(r['pred_z'], r['mae_z']) for r in recs if r['pred_z'] is not None and r['mae_z'] is not None]
    c = corr([a for a, b in both], [b for a, b in both])
    print(f"■ STEP1 予測ペースz vs 実前半ペースz(mae3f) 相関 r={c:+.3f} (n={len(both):,})")
    print("  (r>0.3=予測が実ペースをそこそこ当てている / 0付近=予測になっていない)\n")
    # 予測ペースバケット別の実ペースz平均(単調なら予測力あり)
    pb = defaultdict(list)
    for r in recs:
        if r['pred_z'] is None or r['mae_z'] is None:
            continue
        b = '4ハイ予想' if r['pred_z'] >= 0.7 else ('3やや' if r['pred_z'] >= 0.2 else ('2標準' if r['pred_z'] > -0.2 else ('1スロー予想' if r['pred_z'] > -0.7 else '0超スロー予想')))
        pb[b].append(r['mae_z'])
    print("  予測バケット → 実ペースz平均")
    for b in ['0超スロー予想', '1スロー予想', '2標準', '3やや', '4ハイ予想']:
        if b in pb:
            print(f"    {b:<14} n={len(pb[b]):<6} 実ペースz平均={sum(pb[b])/len(pb[b]):+.3f}")
    print()

    # ── STEP2: 予測ペース × オッズ層 → 荒れ ──
    fav_recs = [r for r in recs if r['fav'] and r['pred_z'] is not None]
    fv = sorted(r['fav'] for r in fav_recs)
    q33 = fv[len(fv) // 3]; q66 = fv[len(fv) * 2 // 3]

    def layer(f):
        return '堅' if f <= q33 else ('中' if f <= q66 else '荒')

    print(f"■ STEP2 予測ペース × オッズ層 → 荒れ率 (q33={q33:.1f}, q66={q66:.1f})")
    print(f"  {'オッズ層':<8}{'予測ペース':<18}{'n':>7}{'荒れ率':>9}{'層内ﾘﾌﾄ':>9}")
    for lay in ['堅', '中', '荒']:
        sub = [r for r in fav_recs if layer(r['fav']) == lay]
        sb = sum(r['chaos'] for r in sub) / len(sub)
        print(f"  --- {lay}層 n={len(sub):,} 荒れ{sb*100:.1f}% ---")
        for lab, lo, hi in [('スロー予想(z<=-0.5)', -9, -0.5), ('標準(-0.5〜0.5)', -0.5, 0.5), ('ハイ予想(z>=0.5)', 0.5, 9)]:
            ss = [r for r in sub if lo < r['pred_z'] <= hi] if lab != 'スロー予想(z<=-0.5)' else [r for r in sub if r['pred_z'] <= -0.5]
            if len(ss) < 30:
                continue
            p = sum(r['chaos'] for r in ss) / len(ss)
            print(f"  {'':<8}{lab:<18}{len(ss):>7}{p*100:>8.1f}%{p/sb:>9.2f}")
    print()

    # 比較: 実(事後)ペースで同じ表 = 上限(予測が完璧ならここまで近づける)
    print("■ (参考)実(事後)ペースz × オッズ層 = 予測が完璧な時の上限")
    print(f"  {'オッズ層':<8}{'実ペース':<18}{'n':>7}{'荒れ率':>9}{'層内ﾘﾌﾄ':>9}")
    mrecs = [r for r in recs if r['fav'] and r['mae_z'] is not None]
    for lay in ['堅', '中', '荒']:
        sub = [r for r in mrecs if layer(r['fav']) == lay]
        if not sub:
            continue
        sb = sum(r['chaos'] for r in sub) / len(sub)
        print(f"  --- {lay}層 n={len(sub):,} 荒れ{sb*100:.1f}% ---")
        for lab, lo, hi in [('スロー(z<=-0.5)', -9, -0.5), ('標準', -0.5, 0.5), ('ハイ(z>=0.5)', 0.5, 9)]:
            ss = [r for r in sub if lo < r['mae_z'] <= hi] if lab != 'スロー(z<=-0.5)' else [r for r in sub if r['mae_z'] <= -0.5]
            if len(ss) < 30:
                continue
            p = sum(r['chaos'] for r in ss) / len(ss)
            print(f"  {'':<8}{lab:<18}{len(ss):>7}{p*100:>8.1f}%{p/sb:>9.2f}")
    print("\n" + "=" * 72)
    print("【判定】 STEP1 r>0.3 かつ STEP2 でハイ予想の層内リフトが中/荒層でも>1.2 なら、")
    print("        テン速力ベース事前ペースはオッズを超えるエッジ→②サーチに採用価値あり。")
    print("        STEP1が0付近、またはSTEP2が層内で横ばいなら、予測精度が壁で不採用。")


if __name__ == '__main__':
    main()
