# -*- coding: utf-8 -*-
"""
Vマトリクス pos4 整合 holdout 確認（本番ロジックには接続しない）。

範囲: holdout day >= 20240101, JRA(場01-10), 8頭以上。
赤枠は baba=フラット, pace=ミドル 固定（縦の差だけ見る）。
DB が重い場合は 2025 年のみに絞る（下の YEAR_FILTER）。
"""
import json
import os
import sys
import sqlite3
import time
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import pace_map as pm
from core.pace_map import _V_COL, _V_ROW, resolve_v_pos

DB = pm.JV_DB_PATH
OUT_DIR = os.path.join(ROOT, 'repo', 'analysis', 'vmatrix_pos4_align')
HOLDOUT_FROM = '20240101'
YEAR_FILTER = None  # 例: ('2025',) で 2025 のみ
MAX_RACES = 3000
BABA = 'フラット'
PACE = 'ミドル'
PROFILE_MIN_RATIO = 0.4


def pos_band(pos):
    if pos < 1.0 / 3:
        return '前'
    if pos < 2.0 / 3:
        return '中'
    return '後'


def v_area_horses(horses, profiles, pos4, use_pos4):
    """build_v_matrix と同じ座標式で V 該当馬番を返す（plotly 不要）。"""
    horses = [h for h in horses if h.get('umaban')]
    if len(horses) < 2:
        return set()
    max_uma = max(h['umaban'] for h in horses)
    pts = []
    p4 = pos4 if use_pos4 else None
    for h in horses:
        pos, _ = resolve_v_pos(
            h['umaban'], h.get('name', ''), h.get('score', 0.5),
            profiles=profiles, pos4=p4)
        gate = (h['umaban'] - 1) / max(max_uma - 1, 1)
        lane = 0.65 * gate + 0.35 * pos
        y = (1.0 - pos) * 3.0
        pts.append({'umaban': h['umaban'], 'x': lane * 3.0, 'y': y, 'pos': pos})

    v_col = _V_COL.get(BABA, 0)
    v_row = _V_ROW.get(PACE, 1)
    vy0, vy1 = (2.0, 3.0) if v_row == 0 else (1.0, 2.0) if v_row == 1 else (0.0, 1.0)
    vx0, vx1 = float(v_col), float(v_col) + 1.0
    return {p['umaban'] for p in pts if vx0 <= p['x'] <= vx1 and vy0 <= p['y'] <= vy1}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    u = a | b
    if not u:
        return 1.0
    return len(a & b) / len(u)


def connect_db():
    for attempt in range(8):
        try:
            return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
        except sqlite3.OperationalError:
            time.sleep(4)
    raise sqlite3.OperationalError('DB locked')


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = connect_db()
    yf = ''
    params = []
    if YEAR_FILTER:
        yf = ' AND (' + ' OR '.join(['ra.year=?'] * len(YEAR_FILTER)) + ')'
        params.extend(YEAR_FILTER)
    sql = f"""SELECT ra.race_key, ra.kyori, ra.surface, ra.jyo, ra.shusso_tosu
              FROM races ra
              WHERE substr(ra.race_key, 1, 8) >= ?
                AND CAST(ra.jyo AS INTEGER) BETWEEN 1 AND 10
                AND ra.shusso_tosu >= 8{yf}
              ORDER BY ra.race_key"""
    rks = [r[0] for r in con.execute(sql, [HOLDOUT_FROM] + params).fetchall()]
    if MAX_RACES and len(rks) > MAX_RACES:
        rks = rks[:MAX_RACES]

    band_match_ten = []
    band_match_pos4 = []
    jaccards = []
    cnt_ten = []
    cnt_pos4 = []
    place_ten = {'hit': 0, 'n': 0, 'stake': 0, 'ret': 0}
    place_pos4 = {'hit': 0, 'n': 0, 'stake': 0, 'ret': 0}
    done = 0

    for rk in rks:
        ra = con.execute(
            'SELECT kyori, surface, jyo FROM races WHERE race_key=?', (rk,)).fetchone()
        if not ra:
            continue
        kyori, surface, jyo = ra
        rows = con.execute(
            """SELECT umaban, bamei, chakujun, win_odds FROM results
               WHERE race_key=? AND chakujun>0 AND win_odds>0""", (rk,)).fetchall()
        if len(rows) < 8:
            continue
        venue = pm.VENUE_CODES.get(str(jyo).zfill(2), '')
        horses = [{'umaban': u, 'name': nm, 'score': 0.5, 'style': '不明'}
                  for u, nm, _, _ in rows]
        profiles = pm.fetch_jv_profiles(
            [h['name'] for h in horses], max_runs=8,
            surface=surface, distance=kyori, before_key=rk)
        if sum(1 for h in horses if h['name'] in profiles) < len(horses) * PROFILE_MIN_RATIO:
            continue
        layout = pm.get_course_layout(venue, surface, kyori)
        ctx = pm.build_pace_context(horses, profiles, kyori, surface, layout)
        pos4 = ctx.get('pos4') or {}
        if len(pos4) < len(horses) * 0.5:
            continue

        v_ten = v_area_horses(horses, profiles, pos4, use_pos4=False)
        v_p4 = v_area_horses(horses, profiles, pos4, use_pos4=True)
        jaccards.append(jaccard(v_ten, v_p4))
        cnt_ten.append(len(v_ten))
        cnt_pos4.append(len(v_p4))

        bm_t, bm_p, n_band = 0, 0, 0
        odds_by_uma = {u: o for u, _, _, o in rows}
        chak_by_uma = {u: c for u, _, c, _ in rows}
        for h in horses:
            u = h['umaban']
            if u not in pos4:
                continue
            map_band = pos_band(pos4[u])
            pos_t, _ = resolve_v_pos(u, h['name'], h['score'], profiles, pos4=None)
            pos_p, _ = resolve_v_pos(u, h['name'], h['score'], profiles, pos4=pos4)
            n_band += 1
            if pos_band(pos_t) == map_band:
                bm_t += 1
            if pos_band(pos_p) == map_band:
                bm_p += 1
        if n_band:
            band_match_ten.append(bm_t / n_band)
            band_match_pos4.append(bm_p / n_band)

        for label, vset, acc in (('ten', v_ten, place_ten), ('pos4', v_p4, place_pos4)):
            for u in vset:
                c = chak_by_uma.get(u)
                o = odds_by_uma.get(u)
                if c is None or o is None:
                    continue
                acc['n'] += 1
                acc['stake'] += 100
                if c <= 3:
                    acc['hit'] += 1
                if c == 1:
                    acc['ret'] += int(o * 100)
        done += 1

    con.close()

    def avg(arr):
        return sum(arr) / len(arr) if arr else None

    def place_rate(acc):
        return acc['hit'] / acc['n'] if acc['n'] else None

    def win_roi(acc):
        return (acc['ret'] - acc['stake']) / acc['stake'] if acc['stake'] else None

    summary = {
        'races': done,
        'holdout_from': HOLDOUT_FROM,
        'band_match_ten': avg(band_match_ten),
        'band_match_pos4': avg(band_match_pos4),
        'v_jaccard_mean': avg(jaccards),
        'v_count_ten_mean': avg(cnt_ten),
        'v_count_pos4_mean': avg(cnt_pos4),
        'place_rate_ten': place_rate(place_ten),
        'place_rate_pos4': place_rate(place_pos4),
        'win_roi_ten': win_roi(place_ten),
        'win_roi_pos4': win_roi(place_pos4),
    }

    with open(os.path.join(OUT_DIR, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    pr_t = summary['place_rate_ten']
    pr_p = summary['place_rate_pos4']
    roi_t = summary['win_roi_ten']
    roi_p = summary['win_roi_pos4']
    roi_t_pct = (roi_t * 100) if roi_t is not None else None
    roi_p_pct = (roi_p * 100) if roi_p is not None else None
    roi_delta_pt = None
    if roi_t_pct is not None and roi_p_pct is not None:
        roi_delta_pt = roi_p_pct - roi_t_pct

    print('=' * 60)
    print(f'holdout races={done}  from={HOLDOUT_FROM}  baba={BABA} pace={PACE}')
    print(f'① 帯一致率  ten案={summary["band_match_ten"]:.4f}  pos4案={summary["band_match_pos4"]:.4f}')
    print(f'② V該当 Jaccard( ten vs pos4 )={summary["v_jaccard_mean"]:.4f}')
    print(f'③ 該当頭数/レース  ten={summary["v_count_ten_mean"]:.3f}  pos4={summary["v_count_pos4_mean"]:.3f}')
    if pr_t is not None:
        print(f'④ 複勝率  ten={pr_t*100:.2f}%  pos4={pr_p*100:.2f}%')
    if roi_t_pct is not None:
        print(f'   単ROI   ten={roi_t_pct:+.2f}%  pos4={roi_p_pct:+.2f}%  (差={roi_delta_pt:+.2f}pt)')
    if roi_delta_pt is not None and roi_delta_pt <= -5:
        print('→ 単ROIがten案より5pt以上悪化: 本番反映は保留推奨')
    else:
        print('→ 整合性修正として許容（精度向上の主張はしない）')
    print(f'出力: {OUT_DIR}/summary.json')


if __name__ == '__main__':
    main()
