# -*- coding: utf-8 -*-
"""展開マップ再構築 ―― 『テン混雑→荒れ』を"実タイム由来のテン速力"で再検証する。

前段(scripts/pace_congestion_arare_backtest.py)の結果:
  位置取り代理(n_front=avg_pos3<=3の頭数 / n_hana=pos_ratio3<=0.20 / mean_posr)では
  D>0(符号一貫)だが holdout z≈1.0 < 2 で採用ゲート未達。
  → 台帳[[verified_pace_congestion_weak]]に「実テン3Fタイムで再検証の価値あり＝再挑戦候補筆頭」
    として残されていた。本スクリプトがその再挑戦。

何が変わるか(ここが本質):
  旧: 「過去のコーナー通過"順位"が前だった馬が何頭いるか」= 相対順位の代理。
      18頭立てでも8頭立てでも"3番手以内"は同じ扱いになり、**速さの絶対量が消える**。
  新: ten_speed = (走破タイム − 上がり3F) / (距離−600) × 600  [秒/600m換算・小=速い]
      その馬自身の実測タイムから前半区間の平均ペースを復元した絶対量。
      core/pace_map.py / scripts/build_pace_norms.py の実装と同一定義(ライブと揃える)。
      検証済み: 前方TOP3のten_speedは実際の前半ペース(mae3f)と r=+0.226。

リーク遮断:
  各馬のten_speedは「そのレースより前の走のみ」(日付厳格比較)・直近K=5走・
  条件重み(同馬場1.6/他0.5 × 距離±400m 1.4/他0.6) × 直近重み0.82^idx。
  = build_pace_norms.pre_ts と完全同一。z化のノルムも**train期間だけ**で凍結する。

評価プロトコル(前段と同一・"オッズを超えるか"を厳密化):
  ベース = 凍結ロジット arare_prob(オッズ12特徴・data/scanner_arare_logit.json)
  残差   = 実荒れ(arareA) − 予測
  train(≤2024)で各指標の三分位を凍結 → holdout(2025)/recent(2026)で
  D = 「混雑↑群の残差 − 混雑↓群の残差」と z。
  採用ゲート: D>0 かつ z>=2 が **両窓一貫**。旧代理指標も同じ表に並べて直接比較する。

新指標(すべてレース単位・すべて事前確定):
  ten_top3      前方TOP3のten_speed平均(小=速い先行勢が揃う)。符号反転して"混雑度"に
  ten_top3_z    上記を(馬場,距離band)のtrain凍結ノルムでz化(距離差を除く)
  ten_pack      最速馬から+0.30秒以内のten_speedを持つ頭数(=同じ速さの馬が何頭いるか)
  ten_pack_r    ten_pack / 出走頭数(頭数正規化)
  ten_std       フィールドのten_speed標準偏差(小=横一線=先行争い激化)
  ten_gap14     1位と4位のten_speed差(小=前が渋滞)

Usage: python scripts/pace_tenspeed_arare_backtest.py
"""
import os
import sys
import json
import math
import sqlite3
import time as _time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from scripts import csv_data as cd          # noqa: E402
from core.pace_map import _parse_jv_time    # noqa: E402  ライブと同一のタイム解釈

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JV_DB = os.path.join(ROOT, 'data', 'jravan.db')
LOGIT = os.path.join(ROOT, 'data', 'scanner_arare_logit.json')

HIST_FROM = 2014     # 履歴の下限(2016年のレースにも過去5走が貯まるように前倒し)
K = 5                # 直近何走を使うか(build_pace_norms と同一)
TOPK = 3
PACK_SEC = 0.30      # 最速馬から何秒以内を『同じ速さ』とみなすか
MIN_PAST = 2         # 過去走がこれ未満の馬はten_speed不明(build_pace_norms と同一)


def surf_norm(s):
    s = str(s or '')
    if 'ダ' in s:
        return 'ダ'
    if '障' in s:
        return '障'
    return '芝'


def load_runs():
    """jravan.db から ten_speed 計算に必要な最小列を読む(JRA平地のみ)。"""
    print('jravan.db 読み込み...', file=sys.stderr)
    con = sqlite3.connect(f'file:{JV_DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute(f"""
        SELECT r.race_key, r.year, r.monthday, r.ketto_num, r.chakujun,
               r.ato3f, r.time, ra.kyori, ra.surface
        FROM results r JOIN races ra ON ra.race_key = r.race_key
        WHERE ra.jyo <= '10' AND ra.surface IN ('芝','ダート')
          AND CAST(r.year AS INTEGER) >= {HIST_FROM}
    """).fetchall()
    con.close()
    print(f'  {len(rows):,}行', file=sys.stderr)
    return rows


def build_history(rows):
    """馬ごとの (day, ten_speed, surface, kyori) 履歴と、レースの構成を返す。"""
    hist = defaultdict(list)
    by_race = defaultdict(list)
    for rk, yr, md, kt, chaku, ato, tm, kyori, surf in rows:
        try:
            day = int(yr) * 10000 + int(md)
            rk = int(rk)      # DBはTEXT・races.csvはint64。結合キーをintに揃える
        except (TypeError, ValueError):
            continue
        by_race[rk].append((kt, day, surf, kyori))
        if not chaku or chaku <= 0:
            continue
        t = _parse_jv_time(tm)
        if t is None or not ato or ato <= 0 or not kyori or kyori <= 700:
            continue
        ts = (t - ato / 10.0) / (kyori - 600) * 600.0
        if 25.0 < ts < 60.0:      # 異常値ガード(core/pace_map.pyと同一)
            hist[kt].append((day, ts, surf, kyori))
    for k in hist:
        hist[k].sort()
    return hist, by_race


def pre_ten_speed(hist, ketto, day, surf, kyori):
    """そのレース時点で判る『その馬のテン速力』。build_pace_norms.pre_ts と同一式。"""
    h = hist.get(ketto)
    if not h:
        return None
    past = [x for x in h if x[0] < day]      # 当日を含めない=リーク遮断
    if len(past) < MIN_PAST:
        return None
    past = past[-K:][::-1]                   # 新しい順
    num = den = 0.0
    for idx, (_d, ts, s, k) in enumerate(past):
        cw = 1.0
        if surf and s:
            cw *= 1.6 if str(surf) == str(s) else 0.5
        if kyori and k:
            cw *= 1.4 if abs(k - kyori) <= 400 else 0.6
        w = cw * (0.82 ** idx)
        num += ts * w
        den += w
    return num / den if den else None


def race_features(hist, by_race):
    """レース単位のテン速力指標。すべて事前確定(過去走のみ)。"""
    print('テン速力の集計...', file=sys.stderr)
    out = {}
    for i, (rk, members) in enumerate(by_race.items()):
        if i % 20000 == 0 and i:
            print(f'  ...{i:,}/{len(by_race):,}', file=sys.stderr, flush=True)
        _kt, day, surf, kyori = members[0]
        vals = []
        for kt, d, s, k in members:
            v = pre_ten_speed(hist, kt, d, s, k)
            if v is not None:
                vals.append(v)
        n = len(members)
        if len(vals) < TOPK + 2:
            continue
        vals.sort()                       # 小=速い
        top3 = sum(vals[:TOPK]) / TOPK
        fastest = vals[0]
        pack = sum(1 for v in vals if v <= fastest + PACK_SEC)
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        out[rk] = {
            'ten_top3': top3,
            'ten_pack': float(pack),
            'ten_pack_r': pack / n if n else 0.0,
            'ten_std': var ** 0.5,
            'ten_gap14': (vals[3] - vals[0]) if len(vals) >= 4 else None,
            '_surf': surf_norm(surf), '_band': (kyori or 0) // 400,
        }
    print(f'  対象 {len(out):,}レース', file=sys.stderr)
    return out


def add_zscore(feat, train_keys):
    """ten_top3 を (馬場,距離band) の **train期間だけ** で作ったノルムでz化する。"""
    grp = defaultdict(list)
    for rk in train_keys:
        f = feat.get(rk)
        if f:
            grp[(f['_surf'], f['_band'])].append(f['ten_top3'])
    norms = {}
    for key, vals in grp.items():
        if len(vals) < 30:
            continue
        m = sum(vals) / len(vals)
        sd = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        norms[key] = (m, sd)
    miss = 0
    for f in feat.values():
        nm = norms.get((f['_surf'], f['_band']))
        if nm is None:
            f['ten_top3_z'] = None
            miss += 1
        else:
            f['ten_top3_z'] = (f['ten_top3'] - nm[0]) / nm[1]
    print(f'  z化ノルム {len(norms)}バケット / 対象外 {miss:,}レース', file=sys.stderr)
    return feat


# ──────────────────────────── 荒れ残差の評価(前段と同一プロトコル) ────────────────────────────

def main():
    t0 = _time.time()
    with open(LOGIT, encoding='utf-8') as f:
        lg = json.load(f)
    feats, mu, sd, coef = lg['features'], lg['mu'], lg['sd'], lg['coef']
    icpt = float(lg['intercept'])

    # race_key(結合キー)と day(period付与)を必ず含める。featsと重複しうるので順序保持で一意化。
    need = list(dict.fromkeys(list(feats) + ['race_key', 'day', 'n_front', 'n_hana',
                                             'mean_posr', 'field_size', 'arareA']))
    races = cd.load_races(cols=need)
    races = races[races['arareA'].notna()]
    for c in feats + ['n_front', 'n_hana', 'mean_posr', 'field_size']:
        races = races[races[c].notna()]
    print(f'races.csv: {len(races):,}レース')

    tsfeat = race_features(*build_history(load_runs()))
    train_keys = {int(r) for r in races.loc[races['period'] == 'train', 'race_key']}
    tsfeat = add_zscore(tsfeat, train_keys)

    def logit_pred(d):
        z = icpt
        for f in feats:
            z += coef[f] * ((float(d[f]) - mu[f]) / (sd[f] or 1.0))
        try:
            return 1.0 / (1.0 + math.exp(-z))
        except OverflowError:
            return 0.0 if z < 0 else 1.0

    # 指標名 -> (値の取り出し, 混雑↑の向きが"値が大きい"ならFalse/"小さい"ならTrue)
    #   ten_top3/ten_top3_z … 小=速い前方勢=混雑↑ → invert
    #   ten_std/ten_gap14   … 小=横一線=混雑↑     → invert
    #   ten_pack/ten_pack_r … 大=同速の馬が多い=混雑↑
    SPECS = [
        ('【新】ten_top3(前方3頭の実テン)', lambda d: d['ts'].get('ten_top3'), True),
        ('【新】ten_top3_z(距離馬場正規化)', lambda d: d['ts'].get('ten_top3_z'), True),
        ('【新】ten_pack(±0.3秒の同速頭数)', lambda d: d['ts'].get('ten_pack'), False),
        ('【新】ten_pack_r(同速率)', lambda d: d['ts'].get('ten_pack_r'), False),
        ('【新】ten_std(テン速のばらつき)', lambda d: d['ts'].get('ten_std'), True),
        ('【新】ten_gap14(1位-4位差)', lambda d: d['ts'].get('ten_gap14'), True),
        ('【旧】n_front(先行数・順位代理)', lambda d: d['n_front'], False),
        ('【旧】n_hana(逃げ数・順位代理)', lambda d: d['n_hana'], False),
        ('【旧】mean_posr(平均位置)', lambda d: d['mean_posr'], True),
    ]

    samples = []
    matched = 0
    for row in races.itertuples(index=False):
        d = row._asdict()
        ts = tsfeat.get(int(d['race_key']))
        if ts is None:
            continue
        matched += 1
        d['ts'] = ts
        vals = [spec[1](d) for spec in SPECS]
        samples.append((d['period'], float(d['arareA']) - logit_pred(d), vals))
    print(f'  テン速力とマッチしたレース: {matched:,}\n')

    tr = [s for s in samples if s[0] == 'train']
    if not tr:
        raise SystemExit('train期間のサンプルが無い')
    print(f"  train {len(tr):,} / holdout {sum(1 for s in samples if s[0]=='holdout'):,} "
          f"/ recent {sum(1 for s in samples if s[0]=='recent'):,} "
          f"/ other {sum(1 for s in samples if s[0]=='other'):,}")
    print(f"  train平均残差(≈0なら校正OK): {sum(s[1] for s in tr)/len(tr):+.4f}\n")

    def terciles(i):
        vals = sorted(s[2][i] for s in tr if s[2][i] is not None)
        if len(vals) < 90:
            return None
        return vals[len(vals) // 3], vals[2 * len(vals) // 3]

    def analyze(period, i, invert):
        t = terciles(i)
        if t is None:
            return None
        q1, q2 = t
        cell = defaultdict(lambda: [0.0, 0, 0.0])
        for s in samples:
            if s[0] != period or s[2][i] is None:
                continue
            v = s[2][i]
            grp = 'lo' if v < q1 else ('hi' if v > q2 else 'mid')
            if invert:
                grp = {'lo': 'hi', 'hi': 'lo', 'mid': 'mid'}[grp]
            c = cell[grp]
            c[0] += s[1]; c[1] += 1; c[2] += s[1] * s[1]

        def stat(g):
            s0, n, ss = cell[g]
            if n == 0:
                return 0.0, 0, 0.0
            m = s0 / n
            return m, n, max(1e-9, ss / n - m * m)
        mh, nh, vh = stat('hi')
        ml, nl, vl = stat('lo')
        if nh < 30 or nl < 30:
            return None
        dd = mh - ml
        se = math.sqrt(vh / nh + vl / nl)
        return dd, (dd / se if se else 0.0), nh, nl

    print('=' * 92)
    print('テン混雑↑群 − テン混雑↓群 の『荒れ残差』差 D と z (残差 = 実荒れ − オッズ予測)')
    print('=' * 92)
    header = f"{'指標':34s}"
    windows = ('holdout', 'recent', 'other')
    for w in windows:
        header += f"{w:>22s}"
    print(header)
    verdict = {}
    for i, (name, _fn, inv) in enumerate(SPECS):
        line = f'{name:34s}'
        res = {}
        for w in windows:
            r = analyze(w, i, inv)
            if r is None:
                line += f"{'n不足':>22s}"
            else:
                dd, z, nh, nl = r
                res[w] = (dd, z)
                line += f"  D={dd:+.4f} z={z:+5.2f}"
        print(line)
        verdict[name] = res

    print('\n' + '=' * 92)
    print('採用判定: D>0 かつ z>=2 が holdout/recent の両窓で成立するか')
    print('=' * 92)
    any_pass = False
    for name, res in verdict.items():
        h, r = res.get('holdout'), res.get('recent')
        if not h or not r:
            print(f'  {name:34s} データ不足')
            continue
        ok = h[0] > 0 and h[1] >= 2 and r[0] > 0 and r[1] >= 2
        any_pass |= ok
        print(f"  {name:34s} holdout z={h[1]:+5.2f} / recent z={r[1]:+5.2f}  "
              f"{'✅採用ゲート通過' if ok else '❌未達'}")
    if not any_pass:
        print('\n→ 実タイム化しても『テン混雑→荒れ』はオッズを超えない＝priced-in で確定。')
    print(f'\ndone in {_time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
