# -*- coding: utf-8 -*-
"""末脚の質(ペース補正) — core/pace_spurt.py

上がり3F(末脚)は『スローペースの時だけ信頼できる』(検証済・scripts/spurt_pace_backtest.py)。
前走がハイペースの上がり上位は"バテ差し"(前が失速しただけ)で次走エッジ無し(z≈0)、
スローペースの上がり上位は次走も人気以上に走る(z+3.8〜+8.5・train/2024-25/2026安定)。
=末脚指数(spurt_index)を"その上がりがスローで出たものか"で質分けする表示補助。

検証の要点(2016+・mae3f/ato3f coverage 54%のJRA):
  前走スロー×上がりtop3 → 次走複勝残差 z+8.5(16-23)/+6.0(24-25)/+3.8(26) 単ROI 76/69/74%
  前走ハイ ×上がりtop3 → z+0.6 / +0.7 / -0.4(バテ差し=priced-in)
  ※動画の狙い目(スロー×先行×上がり1-2位×0.3秒勝ち)はz+0.3=織込み済み(却下)。
  単ROIは全帯<100%=利益シグナルでなく"軸信頼度/相手の質"の道具(spurt_indexと同扱い)。

ペース判定は data/pace_norm.json(train2016-23の mae3f-ato3f の馬場×距離帯別 平均/SD)で
z化=凍結表なのでライブでも全レース走査不要。mae3f/ato3fが無い過去走はスキップ(中立)。
"""
import os
import json
import sqlite3

JV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
_NORM = None


def _load_norm():
    global _NORM
    if _NORM is None:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'data', 'pace_norm.json')
        try:
            with open(p, encoding='utf-8') as f:
                _NORM = json.load(f)
        except Exception:
            _NORM = {'z_slow': 0.5, 'z_high': -0.5, 'bands': {}}
    return _NORM


def _dist_bucket(kyori):
    try:
        k = int(kyori)
    except (TypeError, ValueError):
        return 'X'
    return 'S' if k <= 1400 else 'M' if k <= 1800 else 'L' if k <= 2200 else 'X'


def classify_pace(surface, kyori, mae3f, ato3f):
    """レースのペースを 'slow'/'high'/'mid'/None で返す。
    surface: '芝'/'ダート'(含む文字列可)。mae3f/ato3f: jravan生値(1/10秒int)。"""
    try:
        mae = float(mae3f); ato = float(ato3f)
    except (TypeError, ValueError):
        return None
    if mae <= 0 or ato <= 0:
        return None
    s = '芝' if '芝' in str(surface or '') else 'ダート'
    nb = _load_norm()
    band = nb['bands'].get(f'{s}|{_dist_bucket(kyori)}')
    if not band or not band.get('std'):
        return None
    z = (mae - ato - band['mean']) / band['std']
    if z >= nb.get('z_slow', 0.5):
        return 'slow'
    if z <= nb.get('z_high', -0.5):
        return 'high'
    return 'mid'


def spurt_quality(ketto_num, before_key=None, db_path=None, n_runs=8, top_k=3):
    """馬の直近走の『上がり上位(レース内top_k)』が、スロー/ハイどちらのペースで出たかを集計。

    戻り値: {'tag': str|None, 'slow': int, 'high': int, 'mid': int, 'n': int, 'reliable': bool}
      tag = '🐢末脚◎(スロー質)'   … 上がり上位がスロー由来主体=信頼(検証z+)
            '⚡末脚△(バテ差し注意)' … 上がり上位がハイ由来主体=次走割引(検証z≈0)
            None                    … 判定材料不足(ato3f/mae3f欠損等)
    reliable=Trueは『スロー由来の上がり上位が1走以上あり、ハイ由来を上回る』。
    """
    out = {'tag': None, 'slow': 0, 'high': 0, 'mid': 0, 'n': 0, 'reliable': False}
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return out
    con = sqlite3.connect(f'file:{db_path or JV_DB_PATH}?mode=ro', uri=True, timeout=10)
    try:
        where = "r.ketto_num=? AND r.chakujun>0 AND r.ato3f>0"
        params = [str(ketto_num)]
        if before_key:
            where += " AND r.race_key<?"
            params.append(str(before_key))
        rows = con.execute(
            f"SELECT r.race_key, r.ato3f, ra.surface, ra.kyori, ra.mae3f, ra.ato3f "
            f"FROM results r JOIN races ra ON ra.race_key=r.race_key "
            f"WHERE {where} AND ra.mae3f>0 AND ra.ato3f>0 "
            f"ORDER BY r.race_key DESC LIMIT ?", params + [n_runs]).fetchall()
        for rk, h_ato, surf, kyori, r_mae, r_ato in rows:
            # レース内上がり順位(top_k以内か)
            field = [a for (a,) in con.execute(
                "SELECT ato3f FROM results WHERE race_key=? AND ato3f>0", (rk,))]
            if len(field) < 5:
                continue
            rank = sum(1 for a in field if a < h_ato) + 1
            if rank > top_k:
                continue
            pace = classify_pace(surf, kyori, r_mae, r_ato)
            if pace == 'slow':
                out['slow'] += 1
            elif pace == 'high':
                out['high'] += 1
            elif pace == 'mid':
                out['mid'] += 1
    except Exception:
        return out
    finally:
        con.close()
    out['n'] = out['slow'] + out['high'] + out['mid']
    if out['n'] == 0:
        return out
    if out['slow'] >= 1 and out['slow'] >= out['high']:
        out['tag'] = '🐢末脚◎(スロー質)'
        out['reliable'] = True
    elif out['high'] >= 2 and out['high'] > out['slow']:
        out['tag'] = '⚡末脚△(バテ差し注意)'
    return out
