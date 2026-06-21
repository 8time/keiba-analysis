# -*- coding: utf-8 -*-
"""
補正タイム(スピード指数)のライブ読み出し。

scripts/build_corrected_time.py が作る data/corrected_time.db (horse_fig) を read-only で引く。
図はH7化(直近7走 × 芝ダ別の最高補正)=検証 scripts/h7_refine_backtest.py で
勝ち馬を図トップ3に捉える率 38.6→44.6%・穴複勝残差 +1.02→+1.62 に改善。
- get_figure(ketto, surface): その馬の {fig, runs, last_day} or None。surface('芝'/'ダート')別。
- field_ranks(figs): フィールド内順位(1=最速=fig最小)
- fmt(fig): 表示用(負=基準より速い)

検証: corrected_time_backtest.py。1-2番人気×図トップ3で複勝+4.8〜5pp(本命補強に有効)、
人気薄では+1.6pp(複勝/相手向き・単勝ROIは戻らない[[verified_5run_theory_debunk]])。穴単体の単勝妙味根拠にはしない。
"""
import os
import sqlite3

_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'corrected_time.db')
_conn = None
_missing = False


def _c():
    global _conn, _missing
    if _missing:
        return None
    if _conn is None:
        if not os.path.exists(_DB):
            _missing = True
            return None
        try:
            _conn = sqlite3.connect(f'file:{_DB}?mode=ro', uri=True, timeout=5,
                                    check_same_thread=False)
        except Exception:
            _missing = True
            return None
    return _conn


def available():
    return _c() is not None


def get_figure(ketto, surface=None):
    """surface('芝'/'ダート'/含む文字列)に応じたH7図を返す。{fig, runs, last_day} or None。
    同一馬場の図が無い(例:芝専門馬が初ダート)場合は None(=該当図なし)。"""
    if not ketto:
        return None
    c = _c()
    if c is None:
        return None
    try:
        r = c.execute(
            "SELECT fig_shiba, fig_dirt, runs_shiba, runs_dirt, last_day FROM horse_fig WHERE ketto=?",
            (str(ketto),)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    s = str(surface or '')
    if 'ダ' in s:
        fig, runs = r[1], r[2 + 1]
    elif '芝' in s:
        fig, runs = r[0], r[2]
    else:
        # 馬場不明: 速い方(min)を返す
        cands = [(r[0], r[2]), (r[1], r[3])]
        cands = [(f, n) for f, n in cands if f is not None]
        if not cands:
            return None
        fig, runs = min(cands, key=lambda t: t[0])
    if fig is None:
        return None
    return {'fig': fig, 'runs': runs, 'last_day': r[4]}


def field_ranks(figs):
    """figs: {umaban: best(float) or None} → {umaban: rank}(1=最速)。Noneは除外。"""
    valid = [(u, v) for u, v in figs.items() if v is not None]
    valid.sort(key=lambda x: x[1])
    return {u: i + 1 for i, (u, _) in enumerate(valid)}


def fmt(best):
    """補正タイム表示。負=基準より速い。"""
    if best is None:
        return '-'
    try:
        return f"{float(best):+.1f}"
    except Exception:
        return '-'
