# -*- coding: utf-8 -*-
"""
血統辞書 (blood_dict.db) からの適性引き当て。
種牡馬/母父 × 芝ダ × 距離帯 の複勝率・勝率・単勝回収率を各馬に供給する。
blood_dict.db は scripts/build_blood_dict.py で jravan.db から構築済み。
"""
import os
import re
import sqlite3

_BLOOD_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'blood_dict.db'
)

_DIST_BANDS = {
    (0, 1300): '短距離',
    (1301, 1899): 'マイル',
    (1900, 2200): '中距離',
    (2201, 9999): '長距離',
}


def _dist_band(kyori):
    if not kyori:
        return None
    k = int(kyori)
    for (lo, hi), label in _DIST_BANDS.items():
        if lo <= k <= hi:
            return label
    return None


def _normalize_parent_name(name):
    """名前バリアント統合: 英語名+国コード除去、ローマ数字→全角"""
    if not name:
        return name
    s = name.strip()
    s = re.sub(r'\s*[\(（][^)）]{1,3}[\)）]\s*$', '', s)
    if re.search(r'[぀-ヿ一-鿿]', s):
        last_jp = -1
        for i, c in enumerate(s):
            if '぀' <= c <= 'ヿ' or '一' <= c <= '鿿' or c in '０１２３４５６７８９':
                last_jp = i
        if last_jp >= 0:
            rest = s[last_jp+1:]
            s = s[:last_jp+1]
            m = re.match(r'^(IV|III|II)', rest)
            if m:
                s += {'IV': '４', 'III': '３', 'II': '２'}[m.group(1)]
    return s


def _normalize_surface(surface):
    if not surface:
        return None
    s = str(surface)
    if 'ダ' in s:
        return 'ダート'
    if '芝' in s:
        return '芝'
    return None


def lookup_sire_stats(sire, surface, distance, db_path=None):
    """種牡馬名 × 芝ダ × 距離 → {runs, place_rate, win_rate, win_roi} or None"""
    db = db_path or _BLOOD_DB
    if not os.path.exists(db) or not sire or sire in ('-', '不明'):
        return None
    surf = _normalize_surface(surface)
    band = _dist_band(distance)
    if not surf or not band:
        return None
    norm_sire = _normalize_parent_name(sire)
    try:
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT runs, place_rate, win_rate, win_roi FROM sire_stats "
            "WHERE parent=? AND surface=? AND dist_band=?",
            (norm_sire, surf, band)
        ).fetchone()
        con.close()
        if row:
            return {'runs': row[0], 'place_rate': row[1], 'win_rate': row[2], 'win_roi': row[3]}
    except Exception:
        pass
    return None


def lookup_bms_stats(bms, surface, distance, db_path=None):
    """母父名 × 芝ダ × 距離 → {runs, place_rate, win_rate, win_roi} or None"""
    db = db_path or _BLOOD_DB
    if not os.path.exists(db) or not bms or bms in ('-', '不明'):
        return None
    surf = _normalize_surface(surface)
    band = _dist_band(distance)
    if not surf or not band:
        return None
    norm_bms = _normalize_parent_name(bms)
    try:
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT runs, place_rate, win_rate, win_roi FROM bms_stats "
            "WHERE parent=? AND surface=? AND dist_band=?",
            (norm_bms, surf, band)
        ).fetchone()
        con.close()
        if row:
            return {'runs': row[0], 'place_rate': row[1], 'win_rate': row[2], 'win_roi': row[3]}
    except Exception:
        pass
    return None


def bloodline_label(sire, bms, surface, distance):
    """父と母父の適性をまとめた表示文字列を返す。
    例: '父キズナ 芝マイル 複27.6% 回78.5% (1907走) / 母父ディープ 複35.5%'"""
    parts = []
    ss = lookup_sire_stats(sire, surface, distance)
    if ss:
        roi_icon = '🔥' if ss['win_roi'] >= 100 else ('💰' if ss['win_roi'] >= 85 else '')
        parts.append(f"父{sire} 複{ss['place_rate']:.0f}% 回{ss['win_roi']:.0f}%{roi_icon} ({ss['runs']}走)")
    bs = lookup_bms_stats(bms, surface, distance)
    if bs:
        roi_icon = '🔥' if bs['win_roi'] >= 100 else ('💰' if bs['win_roi'] >= 85 else '')
        parts.append(f"母父{bms} 複{bs['place_rate']:.0f}% 回{bs['win_roi']:.0f}%{roi_icon}")
    return ' / '.join(parts) if parts else None
