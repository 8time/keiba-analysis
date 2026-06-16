# -*- coding: utf-8 -*-
"""
JRA-VAN（jravan.db）ベースの騎手分析。netkeibaスクレイピングに依存せず、
30年・283万走の実データから騎手指標を算出する（idx_results_jockey 等で高速）。

- J1: 基礎統計（全体／場別／距離別／オッズ帯別の 勝率・連対率・複勝率・単回収率）
- J2: 騎手×馬コンビ・騎手×調教師（黄金ライン）・乗り替わり強化シグナル
- J3: USM期待値テーブルの実データ較正（オッズ帯→実勝率）
- 調子/勢い: 直近フォーム(Hot/Cold)・連敗ストリーク・勝利間隔パターン（オンカジ的見方）
- J5: 馬スコアへ掛ける騎手係数

すべて before_key（race_key文字列）でその時点以前に限定可＝バックテストのリーク遮断に対応。
race_key は年先頭で辞書順=時系列順。jockey は jockey_name で名寄せ（全角空白除去）。
"""
import os
import sqlite3

JV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db'
)


def _norm(name):
    return str(name or '').strip().replace('　', '').replace(' ', '')


def _con(db_path=None):
    return sqlite3.connect(db_path or JV_DB_PATH)


def _rate_block(rows):
    """rows: [(chakujun, win_odds, tosu), ...] → 集計dict。"""
    n = len(rows)
    if n == 0:
        return {'rides': 0, 'win': 0.0, 'top2': 0.0, 'top3': 0.0, 'roi': 0.0}
    win = sum(1 for c, _, _ in rows if c == 1)
    top2 = sum(1 for c, _, _ in rows if 0 < c <= 2)
    top3 = sum(1 for c, _, _ in rows if 0 < c <= 3)
    payout = sum((o or 0) for c, o, _ in rows if c == 1)  # 単勝配当(倍)の合計
    return {'rides': n,
            'win': round(win / n, 3), 'top2': round(top2 / n, 3),
            'top3': round(top3 / n, 3), 'roi': round(payout / n * 100, 1)}


def _fetch_runs(cur, jockey_name, before_key=None, limit=None, asc=False):
    """騎手の騎乗（chakujun>0）を取得。新しい順(asc=False)。"""
    where = "r.jockey_name=? AND r.chakujun>0"
    params = [jockey_name]
    if before_key:
        where += " AND r.race_key<?"
        params.append(str(before_key))
    order = "ASC" if asc else "DESC"
    q = (f"""SELECT r.race_key, r.chakujun, r.win_odds, ra.shusso_tosu, ra.jyo,
                    ra.kyori, ra.surface, r.umaban, r.ninki, ra.monthday, r.trainer_code
             FROM results r JOIN races ra ON ra.race_key=r.race_key
             WHERE {where} ORDER BY r.race_key {order}""")
    if limit:
        q += f" LIMIT {int(limit)}"
    return cur.execute(q, params).fetchall()


# ── オッズ帯/距離 区分 ──
def _odds_band(o):
    o = o or 999
    return '~3.0' if o <= 3 else '3-10' if o <= 10 else '10-30' if o <= 30 else '30~'


def _dist_band(d):
    d = d or 0
    return '~1400' if d <= 1400 else '1600-2000' if d <= 2000 else '2000~'


# ──────────────────────────────────────────────
# J1: 基礎統計（全体・場別・距離別・オッズ帯別）
# ──────────────────────────────────────────────
def jockey_base_stats(jockey_name, venue=None, distance=None, db_path=None,
                      before_key=None, max_rides=2000):
    """騎手の全体＆（指定があれば）当該場・距離帯・オッズ帯の成績を返す。"""
    name = _norm(jockey_name)
    out = {'name': name, 'overall': _rate_block([]), 'venue': None,
           'dist': None, 'by_odds': {}}
    if not name or not os.path.exists(db_path or JV_DB_PATH):
        return out
    con = _con(db_path)
    runs = _fetch_runs(con.cursor(), name, before_key=before_key, limit=max_rides)
    con.close()
    if not runs:
        return out
    base = [(c, o, t) for _, c, o, t, *_ in runs]
    out['overall'] = _rate_block(base)
    if venue:
        vrows = [(c, o, t) for _, c, o, t, jyo, *_ in runs
                 if _venue_name(jyo) == venue]
        out['venue'] = _rate_block(vrows)
    if distance:
        db_ = _dist_band(distance)
        drows = [(c, o, t) for _, c, o, t, jyo, ky, *_ in runs if _dist_band(ky) == db_]
        out['dist'] = _rate_block(drows)
    bands = {}
    for _, c, o, t, *_ in runs:
        bands.setdefault(_odds_band(o), []).append((c, o, t))
    out['by_odds'] = {k: _rate_block(v) for k, v in bands.items()}
    return out


# 場コード→名（pace_map と重複だが独立運用のため再定義）
_VENUE = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
          '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}


def _venue_name(jyo):
    return _VENUE.get(str(jyo).zfill(2), '')


# ──────────────────────────────────────────────
# J2: コンビ・黄金ライン・乗り替わり
# ──────────────────────────────────────────────
def jockey_horse_combo(jockey_name, ketto_num, db_path=None, before_key=None):
    """騎手×馬コンビの過去成績（同コンビでの騎乗）。"""
    name = _norm(jockey_name)
    if not name or not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return _rate_block([])
    con = _con(db_path)
    where = "jockey_name=? AND ketto_num=? AND chakujun>0"
    params = [name, str(ketto_num)]
    if before_key:
        where += " AND race_key<?"
        params.append(str(before_key))
    rows = con.execute(
        f"SELECT chakujun, win_odds, 0 FROM results WHERE {where}", params).fetchall()
    con.close()
    return _rate_block(rows)


def jockey_trainer_combo(jockey_name, trainer_code, db_path=None, before_key=None):
    """騎手×調教師（黄金ライン）の過去成績。"""
    name = _norm(jockey_name)
    if not name or not trainer_code or not os.path.exists(db_path or JV_DB_PATH):
        return _rate_block([])
    con = _con(db_path)
    where = "jockey_name=? AND trainer_code=? AND chakujun>0"
    params = [name, str(trainer_code)]
    if before_key:
        where += " AND race_key<?"
        params.append(str(before_key))
    rows = con.execute(
        f"SELECT chakujun, win_odds, 0 FROM results WHERE {where}", params).fetchall()
    con.close()
    return _rate_block(rows)


def jockey_change_signal(ketto_num, current_jockey, db_path=None, before_key=None):
    """乗り替わり検出: この馬の前走騎手と今回騎手を比較し、鞍上強化(Jockey Up)かを返す。
    戻り値: {'changed':bool, 'prev_jockey':str, 'up':bool, 'note':str} or None。"""
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return None
    con = _con(db_path)
    where = "ketto_num=? AND chakujun>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND race_key<?"
        params.append(str(before_key))
    prev = con.execute(
        f"SELECT jockey_name FROM results WHERE {where} ORDER BY race_key DESC LIMIT 1",
        params).fetchone()
    con.close()
    if not prev:
        return None
    prev_j = _norm(prev[0])
    cur_j = _norm(current_jockey)
    if not prev_j or prev_j == cur_j:
        return {'changed': False, 'prev_jockey': prev_j, 'up': False, 'note': '継続騎乗'}
    # 勝率比較で鞍上強化を判定
    cw = jockey_base_stats(cur_j, db_path=db_path, before_key=before_key)['overall']['win']
    pw = jockey_base_stats(prev_j, db_path=db_path, before_key=before_key)['overall']['win']
    up = cw >= pw + 0.02
    return {'changed': True, 'prev_jockey': prev_j, 'up': up,
            'note': f"乗替({prev_j}→{cur_j}) {'鞍上強化↑' if up else ''}".strip()}


# ──────────────────────────────────────────────
# J3: USM期待値テーブルの実データ較正
# ──────────────────────────────────────────────
def calibrate_odds_expectation(db_path=None, years=('2022', '2023', '2024', '2025')):
    """オッズ帯ごとの実 勝率/連対率/複勝率 を全レースから算出（USMの期待値較正用）。"""
    if not os.path.exists(db_path or JV_DB_PATH):
        return {}
    con = _con(db_path)
    yfilter = " OR ".join(["year=?"] * len(years))
    rows = con.execute(
        f"SELECT win_odds, chakujun FROM results WHERE ({yfilter}) AND chakujun>0 AND win_odds>0",
        tuple(years)).fetchall()
    con.close()
    bands = {}
    for o, c in rows:
        b = _odds_band(o)
        d = bands.setdefault(b, [0, 0, 0, 0])
        d[0] += 1
        d[1] += 1 if c == 1 else 0
        d[2] += 1 if c <= 2 else 0
        d[3] += 1 if c <= 3 else 0
    return {b: {'n': d[0], 'win': round(d[1]/d[0], 4), 'top2': round(d[2]/d[0], 4),
                'top3': round(d[3]/d[0], 4)} for b, d in bands.items() if d[0]}


def usm_calibrated(runs, expected):
    """runs:[(chakujun,win_odds)], expected: calibrate_odds_expectation()。
    USM = 実成績/期待成績*100（100=平均通り, >100=人気以上に走らせている）。"""
    ew = e2 = e3 = aw = a2 = a3 = 0.0
    for c, o in runs:
        b = _odds_band(o)
        e = expected.get(b)
        if not e:
            continue
        ew += e['win']; e2 += e['top2']; e3 += e['top3']
        aw += 1 if c == 1 else 0
        a2 += 1 if c <= 2 else 0
        a3 += 1 if c <= 3 else 0
    return {'win_usm': int(round(aw/ew*100)) if ew else None,
            'top2_usm': int(round(a2/e2*100)) if e2 else None,
            'top3_usm': int(round(a3/e3*100)) if e3 else None}


# ──────────────────────────────────────────────
# 調子・勢い・連敗ストリーク（オンカジ的パターン）
# ──────────────────────────────────────────────
def momentum(jockey_name, db_path=None, before_key=None, recent_n=20, base_n=200):
    """
    騎手の今の調子・勢い・連敗を返す。
      recent: 直近recent_n走の 勝率/複勝率/単回収率
      base:   直近base_n走の平均（ベースライン）
      hot:    直近複勝率 − ベース複勝率（+で好調）
      lose_streak:    現在の連敗数（1着でない連続）
      no_top3_streak: 現在の連続馬券圏外（4着以下が続く）数
      win_gap_avg:    直近base_nでの「勝ち間隔」平均（≒何走に1回勝つか）
      cur_dry:        最後の勝ちからの経過騎乗数
      due_ratio:      cur_dry / win_gap_avg（>1で平均より長く勝ってない＝オンカジ的"そろそろ"。※予測力は要検証）
      katame:         直近の「同日2勝以上」回数（固め打ち傾向）
    """
    name = _norm(jockey_name)
    res = {'rides': 0}
    if not name or not os.path.exists(db_path or JV_DB_PATH):
        return res
    con = _con(db_path)
    runs = _fetch_runs(con.cursor(), name, before_key=before_key, limit=base_n)  # 新しい順
    con.close()
    if not runs:
        return res
    res['rides'] = len(runs)
    chaku = [c for _, c, *_ in runs]                  # index0=最新
    odds = [o for _, _, o, *_ in runs]
    rec = list(zip(chaku[:recent_n], odds[:recent_n]))
    res['recent'] = _rate_block([(c, o, 0) for c, o in rec])
    res['base'] = _rate_block([(c, o, 0) for c, o in zip(chaku, odds)])
    res['hot'] = round(res['recent']['top3'] - res['base']['top3'], 3)

    # 連敗・連続圏外（最新から数える）
    ls = 0
    for c in chaku:
        if c == 1:
            break
        ls += 1
    nt = 0
    for c in chaku:
        if c <= 3:
            break
        nt += 1
    res['lose_streak'] = ls
    res['no_top3_streak'] = nt

    # 勝ち間隔（直近base_n）・cur_dry・due_ratio
    win_idx = [i for i, c in enumerate(chaku) if c == 1]
    res['cur_dry'] = win_idx[0] if win_idx else len(chaku)  # 最新の勝ちまでの距離
    if len(win_idx) >= 2:
        gaps = [win_idx[i+1] - win_idx[i] for i in range(len(win_idx)-1)]
        avg_gap = sum(gaps) / len(gaps)
    elif win_idx:
        avg_gap = len(chaku) / max(len(win_idx), 1)
    else:
        avg_gap = float(len(chaku))
    res['win_gap_avg'] = round(avg_gap, 1)
    res['due_ratio'] = round(res['cur_dry'] / avg_gap, 2) if avg_gap > 0 else 0.0

    # 固め打ち: 同日(monthday+jyo)に2勝以上した日数
    by_day = {}
    for rk, c, o, t, jyo, ky, su, um, ni, md, tr in runs:
        if c == 1:
            by_day[(md, jyo)] = by_day.get((md, jyo), 0) + 1
    res['katame'] = sum(1 for v in by_day.values() if v >= 2)
    return res


def jockey_usm(jockey_name, expected, db_path=None, before_key=None, n=150):
    """騎手の直近n走で較正USM（人気=オッズ期待値に対し何%実成績を出しているか）。"""
    name = _norm(jockey_name)
    if not name or not expected or not os.path.exists(db_path or JV_DB_PATH):
        return {'win_usm': None, 'top2_usm': None, 'top3_usm': None}
    con = _con(db_path)
    runs = _fetch_runs(con.cursor(), name, before_key=before_key, limit=n)
    con.close()
    return usm_calibrated([(c, o) for _, c, o, *_ in runs if o], expected)


def losing_streak_leaders(db_path=None, recent_days=14, min_recent=8, top=15):
    """直近に騎乗している騎手の中から、現在の連敗数が多い順にピックアップする。
    ※連敗は次走勝率を上げも下げもしない（検証済・ギャンブラーの誤謬）。あくまで参考表示。
    戻り値: [{'name','lose_streak','no_top3','cur_dry','win_gap_avg','due_ratio','recent_top3'}...]"""
    if not os.path.exists(db_path or JV_DB_PATH):
        return []
    con = _con(db_path)
    last_key = con.execute("SELECT MAX(race_key) FROM results").fetchone()[0]
    if not last_key:
        con.close(); return []
    # 直近に乗っている騎手（recent_days ぶんの race_key 接頭で粗くフィルタ）
    cutoff = str(int(str(last_key)[:8]) - recent_days)  # YYYYMMDD 近似
    names = [r[0] for r in con.execute(
        """SELECT jockey_name, COUNT(*) c FROM results
           WHERE jockey_name!='' AND substr(race_key,1,8) >= ?
           GROUP BY jockey_name HAVING c>=? """, (cutoff, min_recent)).fetchall()]
    con.close()
    out = []
    for nm in names:
        m = momentum(nm, db_path=db_path)
        if m.get('rides', 0) < 20:
            continue
        out.append({'name': nm, 'lose_streak': m['lose_streak'],
                    'no_top3': m['no_top3_streak'], 'cur_dry': m['cur_dry'],
                    'win_gap_avg': m['win_gap_avg'], 'due_ratio': m['due_ratio'],
                    'recent_top3': m['recent']['top3']})
    out.sort(key=lambda x: (-x['lose_streak'], -x['cur_dry']))
    return out[:top]


# ──────────────────────────────────────────────
# J5: 馬スコアへ掛ける騎手係数
# ──────────────────────────────────────────────
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def resolve_horse(bamei, db_path=None, before_key=None):
    """馬名から jravan の最新 (ketto_num, trainer_code) を引く。見つからなければ (None, None)。
    ライブ(netkeiba)の馬名→JVコード橋渡し用（黄金ライン/コンビをライブ表で使うため）。"""
    name = _norm(bamei)
    if not name or not os.path.exists(db_path or JV_DB_PATH):
        return (None, None)
    con = _con(db_path)
    where = "bamei=?"
    params = [name]
    if before_key:
        where += " AND race_key<?"
        params.append(str(before_key))
    row = con.execute(
        f"SELECT ketto_num, trainer_code FROM results WHERE {where} "
        f"ORDER BY race_key DESC LIMIT 1", params).fetchone()
    con.close()
    return (row[0], row[1]) if row else (None, None)


def _trainer_rows(where, params, db_path=None):
    con = _con(db_path)
    rows = con.execute(
        f"SELECT r.chakujun FROM results r JOIN races ra ON r.race_key=ra.race_key "
        f"WHERE {where}", params).fetchall()
    con.close()
    n = len(rows)
    if n == 0:
        return {'runs': 0, 'wins': 0, 'win_rate': None, 'top3_rate': None}
    wins = sum(1 for (c,) in rows if c == 1)
    t3 = sum(1 for (c,) in rows if c <= 3)
    return {'runs': n, 'wins': wins, 'win_rate': wins / n, 'top3_rate': t3 / n}


def trainer_course_winrate(trainer_code, jyo, surface, before_key=None,
                           min_year=None, db_path=None):
    """調教師の『当コース(競馬場×馬場)』成績。検証(scripts/trainer_backtest.py)で
    当場×馬場の高勝率(特に>20%)はオッズ超の妙味あり/全体勝率は市場織込み済。
    min_year='2023'等で期間(過去N年)を限定。戻り値: {'runs','wins','win_rate','top3_rate'}。"""
    if not trainer_code or not jyo or not os.path.exists(db_path or JV_DB_PATH):
        return None
    surf = 'ダート' if 'ダ' in str(surface) else '芝'
    where = ("r.trainer_code=? AND ra.jyo=? AND ra.surface=? AND r.chakujun>0 "
             "AND ra.surface IN ('芝','ダート')")
    params = [str(trainer_code), str(jyo)[:2], surf]
    if before_key:
        where += " AND r.race_key<?"; params.append(str(before_key))
    if min_year:
        where += " AND ra.year>=?"; params.append(str(min_year))
    return _trainer_rows(where, params, db_path)


def trainer_overall_winrate(trainer_code, before_key=None, min_year=None, db_path=None):
    """調教師の全体(JRA平地)勝率。厩舎ランク表示用(検証では市場織込み済=妙味は薄い)。"""
    if not trainer_code or not os.path.exists(db_path or JV_DB_PATH):
        return None
    where = ("r.trainer_code=? AND r.chakujun>0 AND ra.surface IN ('芝','ダート') "
             "AND CAST(substr(ra.race_id,5,2) AS INTEGER) BETWEEN 1 AND 10")
    params = [str(trainer_code)]
    if before_key:
        where += " AND r.race_key<?"; params.append(str(before_key))
    if min_year:
        where += " AND ra.year>=?"; params.append(str(min_year))
    return _trainer_rows(where, params, db_path)


def _spurt_index(con, ketto_num, race_keys, k=3):
    """直近k走のレース内標準化上がり3F平均(末脚指数)。速い(小さいato3f)ほど正。
    検証(scripts/spurt_index_backtest.py): 人気薄×末脚指数>=0.8で勝率/複勝率/ROIがベース超。
    戻り: (spurt_index|None, spurt_runs)。"""
    # 馬がato3fを持つ直近k走を特定
    qs = ",".join("?" for _ in race_keys)
    own = con.execute(
        f"SELECT race_key, ato3f FROM results WHERE ketto_num=? AND ato3f IS NOT NULL "
        f"AND ato3f>0 AND race_key IN ({qs}) ORDER BY race_key DESC",
        [str(ketto_num)] + list(race_keys)).fetchall()
    own = own[:k]
    if not own:
        return None, 0
    rks = [r[0] for r in own]
    qs2 = ",".join("?" for _ in rks)
    field = {}
    for rk, a in con.execute(
            f"SELECT race_key, ato3f FROM results WHERE race_key IN ({qs2}) "
            f"AND ato3f IS NOT NULL AND ato3f>0", rks):
        field.setdefault(rk, []).append(a)
    devs = []
    for rk, a in own:
        vals = field.get(rk, [])
        if len(vals) < 5:
            continue
        m = sum(vals) / len(vals)
        var = sum((x - m) ** 2 for x in vals) / len(vals)
        sd = var ** 0.5
        if sd <= 0:
            continue
        devs.append((m - a) / sd)        # 速い=正
    if not devs:
        return None, 0
    return sum(devs) / len(devs), len(devs)


def horse_recent_context(ketto_num, before_key=None, db_path=None):
    """馬の直近コンテキスト(消去エンジン用)。戻り:
    {'prev_dist','prev_surf','prev_ninki','prev_chaku','dirt_runs','runs',
     'spurt_index','spurt_runs'}。
    前走フロック/大幅距離変更/初ダート/🔥末脚救出 判定に使う。"""
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return None
    con = _con(db_path)
    where = "r.ketto_num=? AND r.chakujun>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND r.race_key<?"; params.append(str(before_key))
    rows = con.execute(
        f"SELECT ra.kyori, ra.surface, r.ninki, r.chakujun, r.race_key, "
        f"r.jockey_name, r.kyakushitsu "
        f"FROM results r JOIN races ra ON r.race_key=ra.race_key "
        f"WHERE {where} ORDER BY r.race_key DESC", params).fetchall()
    if not rows:
        con.close()
        return {'prev_dist': None, 'prev_surf': None, 'prev_ninki': None,
                'prev_chaku': None, 'dirt_runs': 0, 'runs': 0,
                'prev_jockey': None, 'prev_date': None, 'prev_kyaku': None,
                'spurt_index': None, 'spurt_runs': 0}
    pk, ps, pn, pc, prk, pj, pky = rows[0]
    dirt = sum(1 for r in rows if r[1] == 'ダート')
    si, sr = _spurt_index(con, ketto_num, [r[4] for r in rows[:8]])
    con.close()
    return {'prev_dist': pk, 'prev_surf': ps, 'prev_ninki': pn, 'prev_chaku': pc,
            'dirt_runs': dirt, 'runs': len(rows),
            'prev_jockey': pj, 'prev_date': str(prk)[:8], 'prev_kyaku': str(pky),
            'spurt_index': si, 'spurt_runs': sr}


_TOPJ_CACHE = {}


def jockey_is_top(jockey_name, db_path=None):
    """トップ騎手判定(全期間 騎乗500以上・勝率15%以上)。乗り替わり危険検知用。"""
    name = _norm(jockey_name)
    if not name or not os.path.exists(db_path or JV_DB_PATH):
        return False
    if name in _TOPJ_CACHE:
        return _TOPJ_CACHE[name]
    con = _con(db_path)
    row = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN chakujun=1 THEN 1 ELSE 0 END) "
        "FROM results WHERE jockey_name=? AND chakujun>0", (name,)).fetchone()
    con.close()
    n, w = (row[0] or 0), (row[1] or 0)
    res = n >= 500 and (w / n) >= 0.15
    _TOPJ_CACHE[name] = res
    return res


def horse_blinker_history(ketto_num, before_key=None, db_path=None):
    """馬の過去ブリンカー着用履歴。戻り: {'runs','blinker_runs'}。
    現走ブリンカー(出馬表B印)＋ blinker_runs==0 → 初ブリンカー。"""
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return None
    con = _con(db_path)
    where = "ketto_num=? AND chakujun>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND race_key<?"; params.append(str(before_key))
    rows = con.execute(
        f"SELECT blinker FROM results WHERE {where}", params).fetchall()
    con.close()
    runs = len(rows)
    bl = sum(1 for (b,) in rows if str(b) == '1')
    return {'runs': runs, 'blinker_runs': bl}


def _parse_time_msst(s):
    """JVの走破タイム '1330' → 93.0（秒）。'MSSt'形式。失敗時 None。"""
    s = str(s or '').strip()
    if not s.isdigit() or int(s) == 0:
        return None
    tenths = int(s[-1]); secs = int(s[-3:-1] or 0); mins = int(s[:-3] or 0)
    return mins * 60 + secs + tenths / 10.0


def horse_prev_win_margin(ketto_num, before_key=None, db_path=None):
    """馬の前走(直近)が『勝ち』なら、その着差(2着とのタイム差・秒)を返す。
    勝ち以外/データ無しは None。圧勝の罠検証(verified_ohtani_trap)用＝軸選定の加点。
    検証(scripts/ohtani_trap_backtest.py): 前走着差>=1.0秒で勝った人気馬は
    今回複勝率72.3%(同人気帯+15.7pp)＝最良の軸。"""
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return None
    con = _con(db_path)
    where = "ketto_num=? AND chakujun>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND race_key<?"; params.append(str(before_key))
    row = con.execute(
        f"SELECT race_key, chakujun FROM results WHERE {where} "
        f"ORDER BY race_key DESC LIMIT 1", params).fetchone()
    if not row or int(row[1] or 0) != 1:
        con.close(); return None
    prk = row[0]
    times = con.execute(
        "SELECT chakujun, time FROM results WHERE race_key=? AND chakujun IN (1,2)",
        (prk,)).fetchall()
    con.close()
    t = {int(c): _parse_time_msst(tm) for (c, tm) in times if c in (1, 2)}
    if 1 in t and 2 in t and t[1] is not None and t[2] is not None:
        return round(t[2] - t[1], 1)
    return None


def horse_elim_stats(ketto_num, before_key=None, db_path=None):
    """消去クロステーブル用の過去走サマリ。直近5走から:
      {'last5_top3':[1/0...新→古], 'avg_c4ratio':float|None, 'c4_n':int, 'runs':int}
    - last5_top3: 各走が3着内(1)/着外(0)。近3走着外/過去5走複勝0の判定に使う。
    - avg_c4ratio: 直近3走の(4角通過/出走頭数)平均=後方脚質の判定(0=先頭,1=最後方)。
    検証(scripts/elim_cross_backtest.py): これら下位フラグは単体では人気に織込み済
    (残差≈0)。重複数が増えるほど絶対複勝率は単調低下(0個31.5%→4個13.7%→7個10.3%)。"""
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return None
    con = _con(db_path)
    where = "r.ketto_num=? AND r.chakujun>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND r.race_key<?"; params.append(str(before_key))
    rows = con.execute(
        f"SELECT r.chakujun, r.corner4, ra.shusso_tosu "
        f"FROM results r JOIN races ra ON r.race_key=ra.race_key "
        f"WHERE {where} ORDER BY r.race_key DESC LIMIT 5", params).fetchall()
    con.close()
    if not rows:
        return {'last5_top3': [], 'avg_c4ratio': None, 'c4_n': 0, 'runs': 0}
    last5 = [1 if (c and c <= 3) else 0 for (c, _, _) in rows]
    ratios = [c4 / st for (_, c4, st) in rows[:3] if c4 and st]
    avg_c4 = (sum(ratios) / len(ratios)) if ratios else None
    return {'last5_top3': last5, 'avg_c4ratio': avg_c4,
            'c4_n': len(ratios), 'runs': len(rows)}


def jockey_factor_by_name(jockey_name, horse_name=None, venue=None, distance=None,
                          expected=None, db_path=None, before_key=None):
    """ライブ表用: 騎手名＋馬名から騎手係数を算出（trainer_code/ketto_numは馬名で解決）。"""
    tr = None
    if horse_name:
        _, tr = resolve_horse(horse_name, db_path=db_path, before_key=before_key)
    return jockey_factor(jockey_name, venue=venue, distance=distance,
                         trainer_code=tr, expected=expected,
                         db_path=db_path, before_key=before_key)


def jockey_factor(jockey_name, venue=None, distance=None, trainer_code=None,
                  db_path=None, before_key=None, expected=None):
    """
    馬の総合スコアに掛ける騎手係数を返す（mult 1.0中心）。
    J4バックテスト（283万走）で『人気以上に来る』と確認できた要素のみで構成:
      ① USM（実力・人気以上に走らせるか）… 下位は沈み上位は上振れ（弱いが一貫）
      ② 場相性（当該場連対率 vs 全体）
      ③ 黄金ライン（騎手×調教師 連対率）… 40%以上で 勝ち+2pp/連対+3pp の最強シグナル
    ※調子(連敗/hot)は検証で予測力ゼロだったため係数には不採用（表示は別途参考）。
    """
    base = jockey_base_stats(jockey_name, venue=venue, distance=distance,
                             db_path=db_path, before_key=before_key)
    ov = base['overall']
    if ov['rides'] < 30:
        return {'mult': 1.0, 'note': 'データ少', 'base': base, 'gold': None}
    mult = 1.0
    parts = []
    # ① USM（複勝・実力）
    if expected:
        usm = jockey_usm(jockey_name, expected, db_path=db_path, before_key=before_key)
        u3 = usm.get('top3_usm')
        if u3:
            mult *= 1.0 + _clamp((u3 - 100) / 100.0 * 0.12, -0.05, 0.04)
            parts.append(f"USM{u3}")
    # ② 場相性
    if base['venue'] and base['venue']['rides'] >= 20 and ov['top2'] > 0:
        ratio = base['venue']['top2'] / ov['top2']
        mult *= 1.0 + _clamp((ratio - 1.0) * 0.12, -0.05, 0.05)
        parts.append(f"場連対{base['venue']['top2']*100:.0f}%")
    # ③ 黄金ライン（最強シグナル・要 trainer_code）
    gold = None
    if trainer_code:
        tc = jockey_trainer_combo(jockey_name, trainer_code,
                                  db_path=db_path, before_key=before_key)
        if tc['rides'] >= 15:
            if tc['top2'] >= 0.40:
                mult *= 1.07; gold = tc
            elif tc['top2'] >= 0.30:
                mult *= 1.035; gold = tc
            parts.append(f"黄金{tc['top2']*100:.0f}%/{tc['rides']}走")
    return {'mult': round(mult, 4), 'note': " ".join(parts) or f"全体複勝{ov['top3']*100:.0f}%",
            'base': base, 'gold': gold}
