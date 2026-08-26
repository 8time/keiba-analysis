# -*- coding: utf-8 -*-
"""実験用『血統期待値』— 通常の期待値とは別物。

通常の期待値: 同じオッズ帯の平均単勝回収（強適テーブルの✨期待値と同じ式）。
血統期待値: 父・母父の条件別複勝をレース内で相対化し、同じオッズ帯の実測複勝率と比べる。
  1.00＝血統の見立てと市場が同じ。1.25以上かつ血統がレース内上位約4割を『高い』。

スマート出馬表の国系統・シェア・評価A・双馬メモ・IP指数は取り込まない
（当DBに無く、外部サイトも取得しない）。点数・買い目・新聞には配線しない。
"""
from core import bloodline as bl
from core import jockey_jv as jj

# 強適テーブルの✨期待値と同じ帯
_EDGES = [1.5, 2.5, 4.0, 7.0, 15.0, 30.0, 60.0]

# 資料の人気ランクE相当。複勝が極端に低い大穴は計算から外す
ODDS_E = 50.0
NINKI_E = 12

BLOOD_HIGH = 1.25
BLOOD_LOW = 0.85
WIN_EV_HIGH = 0.90   # 帯の単勝回収 90%以上を『高い』
WIN_EV_LOW = 0.75


def odds_band_i(odds):
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if o <= 0:
        return None
    for i, e in enumerate(_EDGES):
        if o <= e:
            return i
    return len(_EDGES)


_BANDS_MEMO = None


def calibrate_bands(db_path=None, years=('2022', '2023', '2024', '2025')):
    """オッズ帯 → 実測 勝率/複勝率。通常期待値・血統期待値の分母。"""
    global _BANDS_MEMO
    if _BANDS_MEMO is not None and db_path is None:
        return _BANDS_MEMO
    import sqlite3
    path = db_path or jj.JV_DB_PATH
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    yf = " OR ".join(["year=?"] * len(years))
    rows = con.execute(
        f"SELECT win_odds, chakujun FROM results "
        f"WHERE ({yf}) AND chakujun>0 AND win_odds>0",
        tuple(years)).fetchall()
    con.close()
    bk = {}
    for o, c in rows:
        b = odds_band_i(o)
        if b is None:
            continue
        d = bk.setdefault(b, [0, 0, 0])
        d[0] += 1
        d[1] += 1 if c == 1 else 0
        d[2] += 1 if c <= 3 else 0
    out = {}
    for b, d in bk.items():
        n = d[0]
        if n:
            out[b] = {'n': n, 'win': d[1] / n, 'top3': d[2] / n}
    if db_path is None:
        _BANDS_MEMO = out
    return out


def is_rank_e(odds, ninki=None):
    """資料の人気ランクE相当。対象外。"""
    try:
        o = float(odds or 0)
    except (TypeError, ValueError):
        o = 0
    if o > ODDS_E:
        return True
    try:
        nk = int(ninki)
    except (TypeError, ValueError):
        nk = 0
    return nk >= NINKI_E


def win_ev(odds, bands):
    """通常の期待値＝帯の平均単勝回収（1.00＝トントン）。個体の予想ではない。"""
    b = odds_band_i(odds)
    e = bands.get(b) if b is not None else None
    if not e:
        return None
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if o <= 0:
        return None
    return o * e['win']


_score_cache = {}


def blood_place(sire, bms, surface, distance, w_sire=0.6):
    """血統スコアを3着内の見立て(0〜1)にしたもの。blood_score と同じ式。"""
    key = (sire, bms, str(surface), int(distance or 0), float(w_sire))
    if key in _score_cache:
        return _score_cache[key]
    v = bl.blood_score(sire, bms, surface, distance, w_sire=w_sire) / 100.0
    _score_cache[key] = v
    return v


def market_place(odds, bands):
    b = odds_band_i(odds)
    e = bands.get(b) if b is not None else None
    return e['top3'] if e else None


def blood_ev(sire, bms, surface, distance, odds, bands, w_sire=0.6):
    """血統期待値。1.00＝血統と市場が同じ。分母ゼロは None。"""
    p_m = market_place(odds, bands)
    if not p_m:
        return None
    return blood_place(sire, bms, surface, distance, w_sire=w_sire) / p_m


def win_label(v):
    if v is None:
        return '不明'
    if v >= WIN_EV_HIGH:
        return '高い'
    if v < WIN_EV_LOW:
        return '低い'
    return 'ふつう'


def blood_label(v):
    if v is None:
        return '不明'
    if v >= BLOOD_HIGH:
        return '高い'
    if v < BLOOD_LOW:
        return '低い'
    return 'ふつう'


def row(sire, bms, surface, distance, odds, ninki, bands, w_sire=0.6):
    """1頭ぶん（レース内の相対は入らない）。点数には使わない。"""
    we = win_ev(odds, bands)
    be = blood_ev(sire, bms, surface, distance, odds, bands, w_sire=w_sire)
    skip = is_rank_e(odds, ninki)
    wl, blb = win_label(we), blood_label(be)
    overlap = (not skip) and wl == '高い' and blb == '高い'
    return {
        'win_ev': we,
        'blood_ev': be,
        'win_label': wl,
        'blood_label': blb,
        'skip_e': skip,
        'overlap': overlap,
        'blood_place': blood_place(sire, bms, surface, distance, w_sire=w_sire),
        'market_place': market_place(odds, bands),
    }


def annotate_race(horses, surface, distance, bands, w_sire=0.6):
    """1レース分。血統期待値は『レース内の相対』にする。

    絶対値(父の複勝÷帯の複勝)だと、大穴は分母が小さいだけで『高い』になりやすい。
    ここでは (血統の見立て÷レース平均) ÷ (市場÷レース平均) にする。
    horses: sire, bms, odds, ninki を持つ dict の list。破壊的にキーを足して返す。
    """
    prepared = []
    bps, mps = [], []
    for h in horses:
        r = dict(h)
        r.update(row(h.get('sire'), h.get('bms'), surface, distance,
                     h.get('odds'), h.get('ninki'), bands, w_sire=w_sire))
        prepared.append(r)
        if r.get('blood_place') is not None:
            bps.append(r['blood_place'])
        if r.get('market_place') is not None:
            mps.append(r['market_place'])
    mean_b = (sum(bps) / len(bps)) if bps else 0.25
    mean_m = (sum(mps) / len(mps)) if mps else 0.22
    if mean_b <= 0:
        mean_b = 0.25
    if mean_m <= 0:
        mean_m = 0.22
    for r in prepared:
        bp, mp = r.get('blood_place'), r.get('market_place')
        if bp is None or not mp:
            r['blood_ev'] = None
        else:
            r['blood_ev'] = (bp / mean_b) / (mp / mean_m)
        r['skip_e'] = is_rank_e(r.get('odds'), r.get('ninki'))
    ranked = sorted(prepared, key=lambda x: -(x.get('blood_place') or 0))
    for i, r in enumerate(ranked):
        r['blood_rank'] = i + 1
    cut = max(3, int(round(len(prepared) * 0.4)))
    for r in prepared:
        # レース内で血統が下位なら、大穴の分母だけで『高い』にしない
        hi = (r.get('blood_ev') or 0) >= BLOOD_HIGH and r['blood_rank'] <= cut
        lo = (r.get('blood_ev') is not None and r['blood_ev'] < BLOOD_LOW)
        r['blood_label'] = '高い' if hi else ('低い' if lo else 'ふつう')
        r['overlap'] = (
            (not r['skip_e'])
            and r.get('win_label') == '高い'
            and r['blood_label'] == '高い'
        )
    return prepared


def overlap_news_line(horses, surface, distance, bands, w_sire=0.6):
    """SRA1行用。両方高い馬を『N番 名前（人気）』でつなぐ。いなければ空文字。"""
    if not horses or not bands:
        return ''
    marked = annotate_race(horses, surface, distance, bands, w_sire=w_sire)
    hits = [r for r in marked if r.get('overlap')]
    return _join_horse_bits(hits)


def overlap_skip_news_line(horses, surface, distance, bands, w_sire=0.6):
    """数字は両方高いが、12番人気以下・単勝50倍超でニュース対象外の馬。"""
    if not horses or not bands:
        return ''
    marked = annotate_race(horses, surface, distance, bands, w_sire=w_sire)
    hits = [
        r for r in marked
        if r.get('skip_e')
        and r.get('win_label') == '高い'
        and r.get('blood_label') == '高い'
    ]
    return _join_horse_bits(hits)


def _join_horse_bits(hits):
    if not hits:
        return ''

    def _nk(r):
        try:
            return int(r.get('ninki') or 99)
        except (TypeError, ValueError):
            return 99

    parts = []
    for r in sorted(hits, key=_nk):
        um = r.get('umaban')
        nm = str(r.get('name') or '').strip()
        bit = f"{um}番 {nm}".strip()
        try:
            bit += f"（{int(r.get('ninki'))}人気）"
        except (TypeError, ValueError):
            pass
        parts.append(bit)
    return " ／ ".join(parts)
