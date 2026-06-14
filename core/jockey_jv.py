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
