# -*- coding: utf-8 -*-
"""
JV-Data レコードパーサ（RA/SE/HR）。
JVGetsで取得した生バイト列を、検証済みのバイトオフセットで切り出す。
- 数値/コード項目: ASCII（JIS8）→ str.strip()
- 馬名/競走名等の全角: cp932(Shift-JIS)でデコード
- 位置(pos)は仕様書の1始まり。バイト単位。
"""

def _slice(buf: bytes, pos: int, length: int) -> bytes:
    return buf[pos - 1: pos - 1 + length]

def s(buf, pos, length):
    """ASCII/コード項目を文字列で（前後空白除去）"""
    return _slice(buf, pos, length).decode('ascii', errors='replace').strip()

def jp(buf, pos, length):
    """全角項目をcp932でデコード"""
    return _slice(buf, pos, length).decode('cp932', errors='replace').strip()

def i(buf, pos, length, default=None):
    """整数。空白/0埋めを考慮"""
    t = s(buf, pos, length)
    try:
        return int(t)
    except Exception:
        return default

def race_key(buf):
    """レース一意キー: 年(4)+月日(4)+競馬場(2)+回(2)+日(2)+R(2) = 16桁"""
    return s(buf, 12, 4) + s(buf, 16, 4) + s(buf, 20, 2) + s(buf, 22, 2) + s(buf, 24, 2) + s(buf, 26, 2)

def netkeiba_id(buf):
    """netkeiba互換 race_id: 年(4)+競馬場(2)+回(2)+日(2)+R(2) = 12桁"""
    return s(buf, 12, 4) + s(buf, 20, 2) + s(buf, 22, 2) + s(buf, 24, 2) + s(buf, 26, 2)

# ── トラックコード → 芝/ダート/障害 ──
def surface_of(track_code):
    try:
        tc = int(track_code)
    except Exception:
        return ''
    if 10 <= tc <= 22: return '芝'
    if 23 <= tc <= 29: return 'ダート'
    if tc >= 51: return '障害'
    return ''

def parse_ra(buf):
    """レース詳細"""
    track = s(buf, 706, 2)
    return {
        'race_key': race_key(buf),
        'race_id': netkeiba_id(buf),
        'data_kubun': s(buf, 3, 1),
        'year': s(buf, 12, 4),
        'monthday': s(buf, 16, 4),
        'jyo': s(buf, 20, 2),            # 競馬場コード
        'kai': i(buf, 22, 2),
        'nichi': i(buf, 24, 2),
        'race_num': i(buf, 26, 2),
        'race_name': jp(buf, 33, 60),
        'grade': s(buf, 615, 1),         # グレードコード
        'shubetsu': s(buf, 617, 2),      # 競走種別コード
        'kigo': s(buf, 619, 3),          # 競走記号コード
        'juryo': s(buf, 622, 1),         # 重量種別
        'kyori': i(buf, 698, 4),         # 距離(m)
        'track_code': track,
        'surface': surface_of(track),
        'hasso_time': s(buf, 874, 4),    # 発走時刻 HHMM
        'toroku_tosu': i(buf, 882, 2),
        'shusso_tosu': i(buf, 884, 2),   # 出走頭数
        'nyusen_tosu': i(buf, 886, 2),
        'tenko': s(buf, 888, 1),         # 天候コード
        'baba_shiba': s(buf, 889, 1),    # 芝馬場状態
        'baba_dirt': s(buf, 890, 1),     # ダート馬場状態
        'mae3f': i(buf, 970, 3),         # 前3ハロン(0.1秒)
        'ato3f': i(buf, 976, 3),         # 後3ハロン(0.1秒)
    }

def parse_se(buf):
    """馬毎レース情報（1頭分）"""
    odds = i(buf, 360, 4)  # 単勝オッズ（0.1倍単位、9999=計算対象外）
    bataiju = i(buf, 325, 3)
    zogen_sign = s(buf, 328, 1)
    zogen = i(buf, 329, 3)
    return {
        'race_key': race_key(buf),
        'race_id': netkeiba_id(buf),
        'year': s(buf, 12, 4),
        'monthday': s(buf, 16, 4),
        'jyo': s(buf, 20, 2),
        'waku': i(buf, 28, 1),
        'umaban': i(buf, 29, 2),
        'ketto_num': s(buf, 31, 10),     # 血統登録番号（馬の一意ID）
        'bamei': jp(buf, 41, 36),
        'sex': s(buf, 79, 1),            # 性別コード
        'age': i(buf, 83, 2),
        'tozai': s(buf, 85, 1),          # 東西所属
        'trainer_code': s(buf, 86, 5),
        'futan': i(buf, 289, 3),         # 負担重量(0.1kg)
        'blinker': s(buf, 295, 1),
        'jockey_code': s(buf, 297, 5),
        'jockey_name': jp(buf, 307, 8),
        'minarai': s(buf, 323, 1),       # 見習コード
        'bataiju': bataiju if bataiju and bataiju != 0 else None,
        'zogen': (None if zogen is None else (zogen if zogen_sign != '-' else -zogen)),
        'ijo': s(buf, 332, 1),           # 異常区分(0=正常,1=取消,2=除外...)
        'nyusen': i(buf, 333, 2),
        'chakujun': i(buf, 335, 2),      # 確定着順
        'time': s(buf, 339, 4),          # 走破タイム MSSm
        'corner1': i(buf, 352, 2),
        'corner2': i(buf, 354, 2),
        'corner3': i(buf, 356, 2),
        'corner4': i(buf, 358, 2),
        'win_odds': (None if (odds is None or odds >= 9999) else round(odds / 10.0, 1)),
        'ninki': i(buf, 364, 2),         # 単勝人気順
        'ato3f': i(buf, 391, 3),         # 後3ハロンタイム(0.1秒)
        'kyakushitsu': s(buf, 553, 1),   # 今回レース脚質判定(1逃2先3差4追)
    }

def parse_um(buf):
    """競走馬マスタ（血統）。3代血統グループ pos=205, rep14・1件44バイト(繁殖登録番号8+馬名36)。
    父=1件目, 母=2件目, 母父=5件目。"""
    def ped_name(idx1):  # 1始まり
        start = 205 + (idx1 - 1) * 44
        return jp(buf, start + 8, 36)
    return {
        'ketto_num': s(buf, 12, 10),
        'bamei': jp(buf, 47, 36),
        'sex': s(buf, 201, 1),          # 性別コード
        'birth': s(buf, 39, 8),
        'sire': ped_name(1),            # 父
        'dam': ped_name(2),             # 母
        'bms': ped_name(5),             # 母父（母の父）
    }

# ── O1: 単勝/複勝/枠連オッズ ──
def parse_hc(buf):
    """坂路調教(HCレコード)。タイムは0.1秒単位の整数で格納（例: t4f=519 → 51.9秒）。
    血統登録番号(ketto_num)・調教年月日で results と紐付け、加速ラップ等の特徴量に使う。"""
    return {
        'ketto_num': s(buf, 25, 10),
        'center': s(buf, 12, 1),       # トレセン区分(1美浦/2栗東 等)
        'cho_date': s(buf, 13, 8),     # 調教年月日 YYYYMMDD
        'cho_time': s(buf, 21, 4),     # 調教時刻 HHMM
        't4f': i(buf, 35, 4),          # 4ハロン合計(800-0M) 0.1秒
        'lap_86': i(buf, 39, 3),       # ラップ 800-600M
        't3f': i(buf, 42, 4),          # 3ハロン合計(600-0M)
        'lap_64': i(buf, 46, 3),       # ラップ 600-400M
        't2f': i(buf, 49, 4),          # 2ハロン合計(400-0M)
        'lap_42': i(buf, 53, 3),       # ラップ 400-200M
        'lap_20': i(buf, 56, 3),       # ラップ 200-0M（ラスト1F・終い）
    }


def parse_o1(buf):
    """O1レコード → 複数行リスト。単勝/複勝/枠連の全馬(枠)オッズ。"""
    rk = race_key(buf)
    rid = netkeiba_id(buf)
    rows = []
    # 単勝: pos=44, repeat=28, stride=8 → 馬番(2)+オッズ(4,0.1倍)+人気(2)
    for k in range(28):
        base = 44 + k * 8
        umaban = i(buf, base, 2)
        odds = i(buf, base + 2, 4)
        ninki = i(buf, base + 6, 2)
        if not umaban or odds is None:
            continue
        rows.append({
            'race_key': rk, 'race_id': rid, 'bet_type': 'win',
            'combo': f'{umaban:02d}',
            'odds': round(odds / 10.0, 1) if odds < 9999 else None,
            'odds_max': None, 'ninki': ninki,
        })
    # 複勝: pos=268, repeat=28, stride=12 → 馬番(2)+最低オッズ(4)+最高オッズ(4)+人気(2)
    for k in range(28):
        base = 268 + k * 12
        umaban = i(buf, base, 2)
        omin = i(buf, base + 2, 4)
        omax = i(buf, base + 6, 4)
        ninki = i(buf, base + 10, 2)
        if not umaban or omin is None:
            continue
        rows.append({
            'race_key': rk, 'race_id': rid, 'bet_type': 'place',
            'combo': f'{umaban:02d}',
            'odds': round(omin / 10.0, 1) if omin < 9999 else None,
            'odds_max': round(omax / 10.0, 1) if omax and omax < 9999 else None,
            'ninki': ninki,
        })
    # 枠連: pos=604, repeat=36, stride=9 → 枠番(2)+オッズ(5)+人気(2)
    for k in range(36):
        base = 604 + k * 9
        waku = s(buf, base, 2)
        odds = i(buf, base + 2, 5)
        ninki = i(buf, base + 7, 2)
        if not waku or waku.strip('0') == '' or odds is None:
            continue
        rows.append({
            'race_key': rk, 'race_id': rid, 'bet_type': 'bracket_q',
            'combo': waku,
            'odds': round(odds / 10.0, 1) if odds < 99999 else None,
            'odds_max': None, 'ninki': ninki,
        })
    return rows

# ── O2〜O5: 馬連/ワイド/馬単/3連複オッズ ──
# 共通ヘッダ: pos 1-39 は O1 と同一構造
def _parse_pair_odds(buf, bet_type, group_pos, repeat, stride, combo_len, odds_len, ninki_len, has_range=False):
    """2頭/3頭組オッズの汎用パーサ。"""
    rk = race_key(buf)
    rid = netkeiba_id(buf)
    rows = []
    for k in range(repeat):
        base = group_pos + k * stride
        combo = s(buf, base, combo_len)
        if not combo or combo.strip('0') == '':
            continue
        if has_range:
            omin = i(buf, base + combo_len, odds_len)
            omax = i(buf, base + combo_len + odds_len, odds_len)
            ninki = i(buf, base + combo_len + odds_len * 2, ninki_len)
            ceil = 10 ** odds_len - 1
            rows.append({
                'race_key': rk, 'race_id': rid, 'bet_type': bet_type,
                'combo': combo,
                'odds': round(omin / 10.0, 1) if omin is not None and omin < ceil else None,
                'odds_max': round(omax / 10.0, 1) if omax is not None and omax < ceil else None,
                'ninki': ninki,
            })
        else:
            odds = i(buf, base + combo_len, odds_len)
            ninki = i(buf, base + combo_len + odds_len, ninki_len)
            ceil = 10 ** odds_len - 1
            rows.append({
                'race_key': rk, 'race_id': rid, 'bet_type': bet_type,
                'combo': combo,
                'odds': round(odds / 10.0, 1) if odds is not None and odds < ceil else None,
                'odds_max': None, 'ninki': ninki,
            })
    return rows

def parse_o2(buf):
    """O2: 馬連オッズ。pos=41, repeat=153, stride=13 → 組番(4)+オッズ(6)+人気(3)"""
    return _parse_pair_odds(buf, 'quinella', 41, 153, 13, 4, 6, 3)

def parse_o3(buf):
    """O3: ワイドオッズ。pos=41, repeat=153, stride=17 → 組番(4)+最低(5)+最高(5)+人気(3)"""
    return _parse_pair_odds(buf, 'wide', 41, 153, 17, 4, 5, 3, has_range=True)

def parse_o4(buf):
    """O4: 馬単オッズ。pos=41, repeat=306, stride=13 → 組番(4)+オッズ(6)+人気(3)"""
    return _parse_pair_odds(buf, 'exacta', 41, 306, 13, 4, 6, 3)

def parse_o5(buf):
    """O5: 3連複オッズ。pos=41, repeat=816, stride=15 → 組番(6)+オッズ(6)+人気(3)"""
    return _parse_pair_odds(buf, 'trio', 41, 816, 15, 6, 6, 3)

# HR払戻グループ定義: (券種, 開始pos, 繰返, stride, 組番len, 払戻len, 人気len)
_HR_GROUPS = [
    ('単勝',   103, 3, 13, 2, 9, 2),
    ('複勝',   142, 5, 13, 2, 9, 2),
    ('枠連',   207, 3, 13, 2, 9, 2),
    ('馬連',   246, 3, 16, 4, 9, 3),
    ('ワイド', 294, 7, 16, 4, 9, 3),
    ('馬単',   454, 6, 16, 4, 9, 3),
    ('3連複',  550, 3, 18, 6, 9, 3),
    ('3連単',  604, 6, 19, 6, 9, 4),
]

def parse_hr(buf):
    """払戻（複数行を返す: 1行=1組）"""
    rk = race_key(buf)
    rid = netkeiba_id(buf)
    rows = []
    for bet_type, start, rep, stride, clen, plen, nlen in _HR_GROUPS:
        for k in range(rep):
            base = start + k * stride
            combo = s(buf, base, clen)
            pay = i(buf, base + clen, plen)
            pop = i(buf, base + clen + plen, nlen)
            if not combo or combo.strip('0') == '' or not pay:
                continue
            rows.append({
                'race_key': rk, 'race_id': rid, 'bet_type': bet_type,
                'combo': combo, 'payout': pay, 'pop': pop,
            })
    return rows
