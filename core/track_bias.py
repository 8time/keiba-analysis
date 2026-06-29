# -*- coding: utf-8 -*-
"""
トラックバイアス解析（jravan.db + 手動/外部のクッション値・含水率）。

- Phase 1: 当日逆算バイアス（同日同場同馬場の既走レースから前残り率・内枠率を集計）
           ＋ 3視点枠評価（馬番 / 逆馬番 / 外枠率）＋ コース×馬場マトリクス。
           ※「前半の傾向は後半も続く」は jravan.db で検証済（前残り61%vs50% / 内枠32.5%vs26.3%）。
- Phase 2: クッション値・含水率のエビデンス化。JV-Data に無いが track_cond テーブル
           （外部CSV取り込み: クッション値2020-09〜/ダート含水率2018-07〜）で自動供給。芝/ダで評価が逆。
- Phase 3: バイアス恩恵の分離（恵まれ勝ち＝危険人気 / 逆らい好走＝巻き返し穴）。

効果量は中程度のため、いずれも「断定」ではなく補助フラグ・ナッジとして使うこと。
"""
import os
import sqlite3

JV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db'
)

# 直線が長い「大箱」コース（差しが届きやすい）。それ以外は小回り扱い。
_BIG_COURSES = {'東京', '阪神', '新潟', '中京'}


def lookup_track_cond(year, monthday, jyo, db_path=None):
    """track_cond テーブルからクッション値・ダート含水率を引く。
    戻り値: {'cushion': float|None, 'dirt_moisture': float|None}"""
    db = db_path or JV_DB_PATH
    out = {'cushion': None, 'dirt_moisture': None}
    if not os.path.exists(db):
        return out
    try:
        con = sqlite3.connect(db)
        row = con.execute(
            "SELECT cushion, dirt_moisture FROM track_cond "
            "WHERE year=? AND monthday=? AND jyo=?",
            (str(year), str(monthday).zfill(4), str(jyo).zfill(2))
        ).fetchone()
        con.close()
        if row:
            out['cushion'] = row[0]
            out['dirt_moisture'] = row[1]
    except Exception:
        pass
    return out


# ── 場の信頼度: クッション値と馬場差の相関が高い場 / カオスな場
_HIGH_CORR_VENUES = {'05', '10'}          # 東京(05)・小倉(10): クッション値が素直に馬場差と連動
_CHAOS_VENUES = {'03', '06', '08', '09'}  # 福島(03)・中山(06)・京都(08)・阪神(09)

# ── 芝種: 洋芝/野芝/オーバーシード別の平均クッション値（場間比較禁止の根拠）
_TURF_TYPE = {
    '01': ('洋芝', 7.6), '02': ('洋芝', 7.6),          # 札幌・函館
    '04': ('野芝', 9.4),                                # 新潟
    '05': ('OS', 9.4), '06': ('OS', 9.8), '07': ('OS', 9.3),  # 東京・中山・中京
    '08': ('OS', 10.0), '09': ('OS', 9.1), '10': ('OS', 9.0),  # 京都・阪神・小倉
    '03': ('OS', 9.2),                                  # 福島
}

# ── 種牡馬×クッション値シフト適性（PDF検証済み・2025重賞ベース）
# shift='+' → 硬化時に活性、shift='△' → 軟化時に活性
_SIRE_CUSHION_AFFINITY = {
    'ディープインパクト': {'shift': '+', 'note': '硬化[+]で斬れ・スピード覚醒（複勝率21%→軟化時13%）'},
    'キズナ':         {'shift': '+', 'note': '硬化[+]で複28.2% / 軟化[△]で8.7%。差が極端'},
    # レイデオロ: サンプル不足(55/51走)で検証不能。除外
    'キタサンブラック':  {'shift': '+', 'note': '硬化[+]で複31.7% / 軟化[△]で27.8%（BT検証: +が微優）'},
    'サートゥルナーリア': {'shift': '△', 'note': '軟化[△]で複55.6%（サンプル少だが強烈）'},
    'モーリス':        {'shift': '△', 'note': '⚠ 軟化[△]で複8.3%=危険水域。回避推奨', 'danger': True},
    'エピファネイア':   {'shift': '+', 'note': '京都硬馬場(長距離)で複27.3%。短距離は疑問'},
}
# ND系（母父含む）は軟化時有利の大分類ルール
_ND_SIRES = {'ノーザンダンサー', 'サドラーズウェルズ', 'デインヒル', 'ストームキャット',
             'ハービンジャー', 'オルフェーヴル', 'ゴールドシップ'}

# ── ダート含水率×個別種牡馬（BT検証済みのみ。US/EU大分類は否定済み）
# 湿潤(≥8%)で回収率が顕著に上がる種牡馬
# ※シニミニ: scripts/baba_moisture_split.py 再検証で乾燥<=4%は+0.014フラット・高含水>=8%で
#   複勝残差+0.112(z+4.3・複勝率59.9%・単ROI105%)=高含水○と確定。旧DRY分類は符号が逆だった→WETへ移動。
_WET_DIRT_SIRES = {'パイロ', 'カジノドライヴ', 'シニスターミニスター'}
# 乾燥(≤3.5%)で回収率が顕著に上がる種牡馬
_DRY_DIRT_SIRES = {'キングカメハメハ', 'ヘニーヒューズ'}

# ── 重・不良馬場×人気馬危険(verified_heavy_track_bias)の血統条件化
#    (scripts/heavy_fav_blood_split.py 2016+ 検証)
# 芝重/不良で沈むのは瞬発/ステゴ系の人気馬(芝不良×1-3番人気 複勝残差-0.062/z-2.2)。
# 非該当の人気馬はむしろ平気〜+(芝重×1-3番その他+0.022/z+2.2)。
_FADE_WET_SIRES = {'ディープインパクト', 'ハーツクライ', 'ダイワメジャー', 'エピファネイア',
                   'ステイゴールド', 'オルフェーヴル', 'ディープブリランテ', 'リアルインパクト',
                   'サンデーサイレンス', 'ドゥラメンテ'}
# ダ重/不良でむしろ好走する高含水○パワー系(ダ不良×1-3番人気 複勝残差+0.069/z+2.8・ROI81%)。
# 既存の血統不問「ダ不良×1番人気=危険」はこの系統を誤って危険判定する偽陽性→免除すべき。
_WETPOWER_SIRES = {'シニスターミニスター', 'ヘニーヒューズ', 'パイロ', 'マジェスティックウォリアー',
                   'カレンブラックヒル', 'ダノンレジェンド'}


def cushion_day_shift(year, monthday, jyo, db_path=None):
    """同じ場の前日（直近の開催日）のクッション値と比較して前日比シフトを算出。
    戻り値: {'today': float, 'prev': float, 'delta': float,
             'shift': '+'|'△'|'±0', 'venue_reliable': bool, 'turf_type': str, 'turf_avg': float}
             or None（データ不足時）"""
    db = db_path or JV_DB_PATH
    if not os.path.exists(db):
        return None
    jyo = str(jyo).zfill(2)
    year = str(year)
    monthday = str(monthday).zfill(4)
    try:
        con = sqlite3.connect(db)
        today_row = con.execute(
            "SELECT cushion FROM track_cond WHERE year=? AND monthday=? AND jyo=? AND cushion IS NOT NULL",
            (year, monthday, jyo)).fetchone()
        if not today_row:
            con.close()
            return None
        today_cv = today_row[0]
        date_str = year + monthday
        prev_row = con.execute(
            "SELECT cushion FROM track_cond "
            "WHERE jyo=? AND (year||monthday) < ? AND cushion IS NOT NULL "
            "ORDER BY year||monthday DESC LIMIT 1",
            (jyo, date_str)).fetchone()
        con.close()
        if not prev_row:
            return None
        prev_cv = prev_row[0]
        delta = round(today_cv - prev_cv, 1)
        if delta >= 0.3:
            shift = '+'
        elif delta <= -0.3:
            shift = '△'
        else:
            shift = '±0'
        tt = _TURF_TYPE.get(jyo, ('不明', 9.0))
        return {
            'today': today_cv, 'prev': prev_cv, 'delta': delta,
            'shift': shift,
            'venue_reliable': jyo in _HIGH_CORR_VENUES,
            'venue_chaos': jyo in _CHAOS_VENUES,
            'turf_type': tt[0], 'turf_avg': tt[1],
        }
    except Exception:
        return None


def sire_cushion_flag(sire_name, shift_info):
    """種牡馬名とcushion_day_shiftの結果から、馬場シフト適性フラグを返す。
    戻り値: {'flag': '🟢活性'|'🔴逆風'|'⚠危険'|None, 'detail': str} or None"""
    if not shift_info or shift_info['shift'] == '±0':
        return None
    shift = shift_info['shift']
    aff = _SIRE_CUSHION_AFFINITY.get(sire_name)
    if aff:
        matched = (aff['shift'] == shift)
        if aff.get('danger'):
            if matched:
                return {'flag': '⚠危険', 'detail': f"父{sire_name}: {aff['note']}"}
            return None
        if matched:
            return {'flag': '🟢活性', 'detail': f"父{sire_name}: {aff['note']}"}
        return {'flag': '🔴逆風', 'detail': f"父{sire_name}: 今日のシフト[{shift}]と逆方向"}
    if sire_name in _ND_SIRES:
        if shift == '△':
            return {'flag': '🟢活性', 'detail': f"父{sire_name}(ND系): 軟化[△]でパワー活性"}
        else:
            return {'flag': '🔴逆風', 'detail': f"父{sire_name}(ND系): 硬化[+]は不得手"}
    return None


def dirt_moisture_bloodtype(sire_name, moisture):
    """ダート含水率と種牡馬から検証済みの適性フラグを返す（個別sireのみ）。
    戻り値: {'flag': '🟢'|'🔴'|None, 'detail': str} or None"""
    if moisture is None:
        return None
    mv = float(moisture)
    is_wet = mv >= 8.0
    is_dry = mv <= 3.5
    if not is_wet and not is_dry:
        return None
    if sire_name in _WET_DIRT_SIRES:
        if is_wet:
            return {'flag': '🟢', 'detail': f"父{sire_name}: 高含水{mv:.1f}%で回収率UP(BT検証済)"}
        elif is_dry:
            return {'flag': '🔴', 'detail': f"父{sire_name}: 乾燥{mv:.1f}%では回収率低下"}
    if sire_name in _DRY_DIRT_SIRES:
        if is_dry:
            return {'flag': '🟢', 'detail': f"父{sire_name}: 乾燥{mv:.1f}%で回収率UP(BT検証済)"}
        elif is_wet:
            return {'flag': '🔴', 'detail': f"父{sire_name}: 高含水{mv:.1f}%では回収率低下"}
    return None


_SIRE_KETTO_CACHE = {}


def sire_of_ketto(ketto_num, db_path=None):
    """ketto_num から horses.sire を引く（プロセス内キャッシュ）。見つからなければ None。"""
    if not ketto_num:
        return None
    key = str(ketto_num)
    if key in _SIRE_KETTO_CACHE:
        return _SIRE_KETTO_CACHE[key]
    path = db_path or JV_DB_PATH
    val = None
    if os.path.exists(path):
        try:
            con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)
            r = con.execute("SELECT sire FROM horses WHERE ketto_num=? LIMIT 1",
                            (key,)).fetchone()
            con.close()
            val = r[0] if r else None
        except Exception:
            val = None
    _SIRE_KETTO_CACHE[key] = val
    return val


def heavy_fav_blood_mod(sire_name, surface, baba):
    """重・不良馬場×人気馬危険(verified_heavy_track_bias)を血統で精緻化する。
    検証: scripts/heavy_fav_blood_split.py(2016+)。重/不良以外は None。
    戻り値 or None:
      {'mod':'exempt',    ...} ダ重/不良の高含水○系(シニミニ等)→危険を免除(むしろ+。
                                ダ不良×1-3番人気 複勝残差+0.069/z+2.8・ROI81%)。
      {'mod':'intensify', ...} 芝重/不良の瞬発/ステゴ系→危険を裏付け(芝不良×1-3番人気-0.062/z-2.2)。
    """
    if not sire_name or baba not in ('重', '不良'):
        return None
    is_dirt = 'ダ' in (surface or '')
    is_turf = '芝' in (surface or '')

    def _has(s):
        return any(k in sire_name for k in s)

    if is_dirt and _has(_WETPOWER_SIRES):
        return {'mod': 'exempt', 'flag': '🟢道悪軸',
                'detail': (f"父{sire_name}: ダ{baba}は高含水○で好走"
                           f"(複勝残差+・ROI81%検証済)→危険判定を免除")}
    if is_turf and _has(_FADE_WET_SIRES):
        return {'mod': 'intensify', 'flag': '⚠瞬発系道悪',
                'detail': (f"父{sire_name}: 芝{baba}で瞬発/ステゴ系の人気馬は割引"
                           f"(複勝-6pp/z-2.2検証済)")}
    return None


# ──────────────────────────────────────────────
# Phase 1: 3視点 枠評価
# ──────────────────────────────────────────────
def frame_eval(umaban, tosu):
    """枠を3視点で相対評価。
    戻り値: {'uma':馬番, 'rev':逆馬番(大外=1), 'outer_ratio':0(最内)〜1(最外)}"""
    try:
        u = int(umaban)
        n = int(tosu)
    except Exception:
        return {'uma': None, 'rev': None, 'outer_ratio': 0.5}
    n = max(n, 1)
    return {'uma': u, 'rev': n - u + 1,
            'outer_ratio': round((u - 1) / max(n - 1, 1), 3)}


# ──────────────────────────────────────────────
# Phase 1: 当日逆算バイアス
# ──────────────────────────────────────────────
def empirical_bias(prior_winners):
    """
    同日・同場・同馬場の『既走レースの勝ち馬』情報からバイアスを推定する。
    prior_winners: [{'corner4':int, 'umaban':int, 'tosu':int}, ...]（勝ち馬のみ）
    戻り値: {'n', 'front_rate', 'inner_rate', 'pace_label', 'lane_label',
             'baba_for_v', 'evidence'(str), 'confident'(bool)} もしくは n<2 なら None。
    """
    rows = [w for w in (prior_winners or [])
            if w.get('corner4') and w.get('tosu')]
    n = len(rows)
    if n < 2:
        return None
    front = sum(1 for w in rows if w['corner4'] <= 3) / n
    inner = sum(1 for w in rows if w['umaban'] <= max(1, w['tosu'] / 3)) / n

    if front >= 0.60:
        pace_label = '前有利（前残り）'
    elif front <= 0.35:
        pace_label = '後ろ有利（差し）'
    else:
        pace_label = 'フラット'
    if inner >= 0.50:
        lane_label, baba_for_v = '内有利', 'フラット'        # Vエリアは内ゾーン
    elif inner <= 0.20:
        lane_label, baba_for_v = '外有利', '内4頭目まで荒れ'   # Vエリアは外ゾーン
    else:
        lane_label, baba_for_v = '中庸〜やや内', '内2頭目まで荒れ'

    ev = (f"既走{n}R: 前残り率{front*100:.0f}% / 内枠勝ち率{inner*100:.0f}% "
          f"→ {pace_label}・{lane_label}")
    return {'n': n, 'front_rate': round(front, 3), 'inner_rate': round(inner, 3),
            'pace_label': pace_label, 'lane_label': lane_label,
            'baba_for_v': baba_for_v, 'evidence': ev, 'confident': n >= 4}


def danger_popular_inner(emp_bias, umaban, tosu, ninki):
    """危険人気馬(逆張り消去)フラグ。検証済(scripts/tenkai_bias_backtest.py・2021-25)。
    『はっきり外枠有利と判明した日(confident)に内枠を引いた1-3番人気馬』は複勝率が
    オッズ期待を -4.6pp(z-3.8) 下回る＝過剰人気。順張り(合致馬を買う)は妙味ゼロ(priced-in)
    のため買いには使わず、この逆張り消去のみが検証済みエッジ。
    戻り値: 該当時 {'flag':'⚠危険人気','detail':str} / 非該当 None。
    """
    if not emp_bias or emp_bias.get('lane_label') != '外有利':
        return None
    try:
        u = int(umaban); n = int(tosu); nin = int(ninki)
    except (TypeError, ValueError):
        return None
    if nin < 1 or nin > 3:
        return None
    if u > max(1, n / 3):        # 内枠(下位1/3)でなければ対象外
        return None
    strong = bool(emp_bias.get('confident'))
    pp = '-4.6pp' if strong else '-2.2pp'
    conf_txt = '(明確)' if strong else ''
    return {'flag': '⚠危険人気',
            'detail': (f"外枠有利日{conf_txt}に内枠({u}番)の{nin}番人気＝"
                       f"前提が崩れるのに過剰人気(複勝期待{pp}・検証済)")}


def empirical_bias_from_db(year, monthday, jyo, surface, before_race_num,
                           db_path=None):
    """jravan.db から同日・同場・同馬場で race_num が before より前のレースの勝ち馬を集計。
    当日データが無ければ None（＝コールドスタート: 静的要因にフォールバック）。"""
    db = db_path or JV_DB_PATH
    if not os.path.exists(db):
        return None
    surf = 'ダ' if 'ダ' in str(surface) else '芝'
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            """SELECT r.corner4, r.umaban, ra.shusso_tosu
               FROM races ra JOIN results r ON r.race_key=ra.race_key
               WHERE ra.year=? AND ra.monthday=? AND ra.jyo=? AND ra.surface=?
                 AND ra.race_num < ? AND r.chakujun=1 AND r.corner4>0""",
            (str(year), str(monthday), str(jyo), surf, int(before_race_num)),
        ).fetchall()
        con.close()
    except Exception:
        return None
    winners = [{'corner4': c4, 'umaban': u, 'tosu': t or 0} for c4, u, t in rows]
    return empirical_bias(winners)


# ──────────────────────────────────────────────
# Phase 1: コース × 馬場 マトリクス
# ──────────────────────────────────────────────
def course_empirical_bias(jyo, surface, distance, db_path=None, years_back=10):
    """
    jravan.db から、その『コース（場×芝ダ×距離）』の実際の決着傾向を集計する（静的・コース固有）。
    日替わりバイアスと違いコースの性質は安定なので信頼できる（実績そのもの）。
    戻り値: {'n','front_rate','inner_rate','avg_pos','label'} or None。
      front_rate: 勝ち馬の4角3番手以内率（高い=先行有利コース）
      inner_rate: 勝ち馬の内1/3枠率（高い=内枠有利コース）
    """
    db = db_path or JV_DB_PATH
    if not os.path.exists(db) or not distance:
        return None
    surf = 'ダ' if 'ダ' in str(surface) else '芝'
    try:
        con = sqlite3.connect(db)
        cutoff = str(int(__import__('datetime').datetime.now().year) - years_back)
        rows = con.execute(
            """SELECT r.corner4, r.umaban, ra.shusso_tosu
               FROM races ra JOIN results r ON r.race_key=ra.race_key
               WHERE ra.jyo=? AND ra.surface LIKE ? AND ra.kyori=? AND ra.year>=?
                 AND r.chakujun=1 AND r.corner4>0""",
            (str(jyo).zfill(2), surf + '%', int(distance), cutoff)).fetchall()
        con.close()
    except Exception:
        return None
    rows = [(c, u, t) for c, u, t in rows if t and t >= 2]
    n = len(rows)
    if n < 20:
        return None
    front = sum(1 for c, _, _ in rows if c <= 3) / n
    inner = sum(1 for _, u, t in rows if u <= max(1, t / 3)) / n
    avg_pos = sum((c - 1) / max(t - 1, 1) for c, _, t in rows) / n
    if front >= 0.55:
        pl = '先行有利'
    elif front <= 0.40:
        pl = '差し台頭'
    else:
        pl = '中立'
    il = '内枠有利' if inner >= 0.45 else '外枠も来る' if inner <= 0.28 else '枠フラット'
    return {'n': n, 'front_rate': round(front, 3), 'inner_rate': round(inner, 3),
            'avg_pos': round(avg_pos, 3),
            'label': f"過去{n}R: 逃げ先行決着{front*100:.0f}%({pl})・内枠勝ち{inner*100:.0f}%({il})"}


def course_bias_text(venue, fast_track):
    """大箱/小回り × 高速/時計かかる の4象限から有利傾向の一言を返す。
    fast_track: True=高速馬場 / False=時計かかる / None=不明。"""
    big = venue in _BIG_COURSES
    if fast_track is None:
        return f"{'大箱' if big else '小回り'}コース（馬場差不明）"
    if big and fast_track:
        return "大箱×高速 → 直線勝負・差し届きやすい"
    if big and not fast_track:
        return "大箱×時計かかる → 上がりの差が出にくく先行有利"
    if not big and fast_track:
        return "小回り×高速 → 内・逃げ先行・イン差し有利（外回しロス大）"
    return "小回り×時計かかる → 馬群凝縮、中〜外枠・外差し台頭"


# ──────────────────────────────────────────────
# Phase 2: クッション値・含水率（JRA公式値を手動/外部供給）
# ──────────────────────────────────────────────
_Z2H = str.maketrans('０１２３４５６７８９．％（）：　',
                     '0123456789.%():' + ' ')


def parse_baba_announcement(text):
    """
    JRA-VANのX投稿等の「馬場情報」テキストから数値を抽出する。
    例: 芝クッション値(7時30分測定)：9.9 / 含水率(5時30分測定)：芝 ゴール前 11.4%、4コーナー 10.2%
        馬場状態 芝：良
    戻り値: {'cushion','moist_goal','moist_corner','baba_shiba'}（無い項目は None）
    """
    import re
    out = {'cushion': None, 'moist_goal': None, 'moist_corner': None, 'baba_shiba': None}
    if not text:
        return out
    t = str(text).translate(_Z2H)
    # クッション値（測定時刻の括弧をスキップ）
    m = re.search(r'クッション値\s*(?:\([^)]*\))?\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)', t)
    if m:
        out['cushion'] = float(m.group(1))
    # 含水率: ゴール前 / 4コーナー
    m = re.search(r'ゴール前[^0-9]*([0-9]+(?:\.[0-9]+)?)', t)
    if m:
        out['moist_goal'] = float(m.group(1))
    m = re.search(r'4\s*コーナー[^0-9]*([0-9]+(?:\.[0-9]+)?)', t)
    if m:
        out['moist_corner'] = float(m.group(1))
    # 馬場状態 芝：良/稍重/重/不良
    m = re.search(r'芝\s*[:：]\s*(良|稍重|重|不良)', t)
    if m:
        out['baba_shiba'] = m.group(1)
    return out


def cushion_evidence(surface, cushion=None, moisture=None, moisture_corner=None):
    """
    クッション値・含水率からエビデンス行のステータス文を返す。芝/ダで評価が逆。
    cushion: 芝クッション値（7以下=軟,12以上=硬）/ moisture: 含水率(%)（=ゴール前を代表値に）/
    moisture_corner: 4コーナー含水率(%)。ゴール前との差で直線/コーナーの部分荒れを示す。
    戻り値: [{'項目','値','ステータス'}, ...]（無い項目はスキップ）
    """
    surf = 'ダ' if 'ダ' in str(surface) else '芝'
    out = []
    if cushion is not None:
        try:
            cv = float(cushion)
            if cv >= 10.0:
                s = "🚩 硬め＝高速・前/ストライド有利"
            elif cv <= 8.0:
                s = "⚠️ 軟らかめ＝パワー・差し/ピッチ有利"
            else:
                s = "✅ 標準"
            out.append({"項目": "クッション値", "値": f"{cv:.1f}", "ステータス": s})
        except Exception:
            pass
    if moisture is not None:
        try:
            mv = float(moisture)
            if surf == '芝':
                s = ("⚠️ 高含水＝時計遅・スタミナ/差し" if mv >= 14.0
                     else "🚩 低含水＝高速・前" if mv <= 9.0 else "✅ 標準")
            else:  # ダートは芝と逆: 湿ると締まって速い・前
                s = ("🚩 高含水＝締まって高速・前有利" if mv >= 10.0
                     else "⚠️ 乾燥＝砂逃げてタフ・差し届く" if mv <= 4.0 else "✅ 標準")
            _lbl = f"含水率({surf}ゴール前)" if moisture_corner is not None else f"含水率({surf})"
            out.append({"項目": _lbl, "値": f"{mv:.1f}%", "ステータス": s})
            # 地点差（ゴール前 − 4コーナー）: コース内の部分的な荒れ・重さの手がかり（※参考）
            if moisture_corner is not None:
                mc = float(moisture_corner)
                diff = mv - mc
                if abs(diff) < 0.8:
                    ds = "✅ ほぼ均一"
                elif diff > 0:
                    ds = "⚠️ 直線(ゴール前)が湿って重い＝前残り寄り・差し届きにくい（参考）"
                else:
                    ds = "⚠️ 4コーナーが湿＝コーナーで脚を取られやすい（参考）"
                out.append({"項目": "含水率 地点差(ゴール前−4角)",
                            "値": f"{diff:+.1f}% (4角{mc:.1f}%)", "ステータス": ds})
        except Exception:
            pass
    return out


def cushion_style_bias(surface, cushion=None, moisture=None):
    """馬場メトリクスから想定される脚質バイアスを返す: 'front'|'closer'|None。
    finish/予測スコアの微調整に使える（芝/ダで逆転を考慮）。"""
    surf = 'ダ' if 'ダ' in str(surface) else '芝'
    score = 0  # +が前有利, -が差し有利
    if cushion is not None:
        try:
            cv = float(cushion)
            score += 1 if cv >= 10.0 else -1 if cv <= 8.0 else 0
        except Exception:
            pass
    if moisture is not None:
        try:
            mv = float(moisture)
            if surf == '芝':
                score += -1 if mv >= 14.0 else 1 if mv <= 9.0 else 0
            else:
                score += 1 if mv >= 10.0 else -1 if mv <= 4.0 else 0
        except Exception:
            pass
    return 'front' if score >= 1 else 'closer' if score <= -1 else None


# ──────────────────────────────────────────────
# Phase 3: バイアス恩恵の分離 / 不利巻き返し
# ──────────────────────────────────────────────
def comeback_flag(bamei, before_key, db_path=None, max_lookback=3):
    """
    直近走で『当日バイアスに逆らって好走』した馬を巻き返し候補として検出する。
    例: 前残り馬場(前有利)なのに後方(4角中位以下)から掲示板内 → 展開不利でも能力示した＝次走妙味。
    戻り値: 検出時 {'reason':str, 'run_key':str} / 非検出 None。
    """
    db = db_path or JV_DB_PATH
    if not os.path.exists(db):
        return None
    name = str(bamei).strip().replace('　', '').replace(' ', '')
    if not name:
        return None
    try:
        con = sqlite3.connect(db)
        cur = con.cursor()
        q = ("""SELECT r.race_key, r.corner4, r.chakujun, ra.shusso_tosu,
                       ra.year, ra.monthday, ra.jyo, ra.surface, ra.race_num
                FROM results r JOIN races ra ON ra.race_key=r.race_key
                WHERE r.bamei=? AND r.chakujun>0 AND r.corner4>0 """
             + ("AND r.race_key<? " if before_key else "")
             + "ORDER BY r.race_key DESC LIMIT ?")
        params = [name] + ([str(before_key)] if before_key else []) + [max_lookback]
        runs = cur.execute(q, params).fetchall()
        con.close()
    except Exception:
        return None

    for rkey, c4, chaku, tosu, y, md, jyo, surf, rnum in runs:
        tosu = tosu or 0
        if tosu < 8:
            continue
        bias = empirical_bias_from_db(y, md, jyo, surf, rnum, db_path=db)
        if not bias or not bias['confident']:
            continue
        placed = chaku <= max(3, tosu * 0.3)         # その馬は好走したか
        back = c4 > max(3, tosu * 0.5)               # 後方からの競馬だったか
        front = c4 <= 3                              # 前で運んだか
        # 前残り馬場で後方から好走 → 展開不利を覆した
        if bias['pace_label'].startswith('前') and placed and back:
            return {'reason': f"前残り馬場(前有利{bias['front_rate']*100:.0f}%)を後方({c4}番手)から{chaku}着＝展開不利を能力で克服",
                    'run_key': rkey}
        # 差し馬場で前から粘って好走 → 不利な隊列で残した
        if bias['pace_label'].startswith('後') and placed and front:
            return {'reason': f"差し馬場(前残り{bias['front_rate']*100:.0f}%)を前({c4}番手)で粘り{chaku}着＝不利展開を克服",
                    'run_key': rkey}
    return None


# ──────────────────────────────────────────────
# Phase 4: 当日バイアスダッシュボード（数値化強化）
# ──────────────────────────────────────────────
# JRA芝の全体平均(2018-25): front_rate≈52.5%, inner_waku≈31.5%
_POP_FRONT = 0.525
_POP_INNER = 0.315


def bias_dashboard(year, monthday, jyo, surface, before_race_num, db_path=None):
    """当日バイアスをσ単位の強度 + 信頼度 + レースごとの推移で返す。
    app.pyのエビデンス表で呼び出し、ダッシュボード風に表示する。
    戻り値: {
      'summary': empirical_bias互換dict + sigma_front/sigma_inner,
      'per_race': [{'race_num', 'front_cum', 'inner_cum', 'n'}],
      'confidence': 0〜100,
      'trend': 'stable'|'front_gaining'|'closer_gaining'|'inner_gaining'|'outer_gaining',
    } or None。
    """
    db = db_path or JV_DB_PATH
    if not os.path.exists(db):
        return None
    surf = 'ダ' if 'ダ' in str(surface) else '芝'
    try:
        con = sqlite3.connect(db)
        rows = con.execute(
            """SELECT ra.race_num, r.corner4, r.umaban, ra.shusso_tosu, r.kyakushitsu
               FROM races ra JOIN results r ON r.race_key=ra.race_key
               WHERE ra.year=? AND ra.monthday=? AND ra.jyo=? AND ra.surface=?
                 AND ra.race_num < ? AND r.chakujun=1 AND r.corner4>0
               ORDER BY ra.race_num""",
            (str(year), str(monthday), str(jyo), surf, int(before_race_num)),
        ).fetchall()
        con.close()
    except Exception:
        return None
    if len(rows) < 2:
        return None

    per_race = []
    cum_front = cum_inner = cum_n = 0
    for rnum, c4, uma, tosu, kyaku in rows:
        tosu = tosu or 8
        is_front = 1 if c4 <= 3 else 0
        is_inner = 1 if uma <= max(1, tosu / 3) else 0
        cum_front += is_front
        cum_inner += is_inner
        cum_n += 1
        per_race.append({
            'race_num': rnum,
            'front_cum': round(cum_front / cum_n, 3),
            'inner_cum': round(cum_inner / cum_n, 3),
            'n': cum_n,
        })

    n = len(rows)
    front_rate = cum_front / n
    inner_rate = cum_inner / n

    se_front = (_POP_FRONT * (1 - _POP_FRONT) / n) ** 0.5 if n > 0 else 1
    se_inner = (_POP_INNER * (1 - _POP_INNER) / n) ** 0.5 if n > 0 else 1
    sigma_front = (front_rate - _POP_FRONT) / se_front if se_front > 0 else 0
    sigma_inner = (inner_rate - _POP_INNER) / se_inner if se_inner > 0 else 0

    confidence = min(100, int(n / 6 * 100))

    trend = 'stable'
    if len(per_race) >= 4:
        half = len(per_race) // 2
        early_f = sum(1 for r in rows[:half] if r[1] <= 3) / half
        late_f = sum(1 for r in rows[half:] if r[1] <= 3) / (n - half)
        early_i = sum(1 for r in rows[:half] if r[2] <= max(1, (r[3] or 8) / 3)) / half
        late_i = sum(1 for r in rows[half:] if r[2] <= max(1, (r[3] or 8) / 3)) / (n - half)
        if late_f - early_f > 0.15:
            trend = 'front_gaining'
        elif early_f - late_f > 0.15:
            trend = 'closer_gaining'
        if late_i - early_i > 0.15:
            trend = 'inner_gaining'
        elif early_i - late_i > 0.15:
            trend = 'outer_gaining'

    summary = empirical_bias([{'corner4': r[1], 'umaban': r[2], 'tosu': r[3] or 8}
                              for r in rows])
    if summary:
        summary['sigma_front'] = round(sigma_front, 2)
        summary['sigma_inner'] = round(sigma_inner, 2)

    return {
        'summary': summary,
        'per_race': per_race,
        'confidence': confidence,
        'trend': trend,
    }


def bias_stars(sigma):
    """σ値を★表示(5段階)に変換。正=有利、負=不利。"""
    ab = abs(sigma)
    if ab < 0.5:
        return '★★★'
    if ab < 1.0:
        return '★★★★' if sigma > 0 else '★★'
    if ab < 1.5:
        return '★★★★☆' if sigma > 0 else '★☆'
    return '★★★★★' if sigma > 0 else '☆'


def bias_dashboard_text(dash):
    """bias_dashboard() の戻り値を1行テキストにまとめる。"""
    if not dash or not dash.get('summary'):
        return None
    s = dash['summary']
    sf = s.get('sigma_front', 0)
    si = s.get('sigma_inner', 0)
    conf = dash['confidence']

    front_lbl = '前有利' if sf > 0.5 else '差し有利' if sf < -0.5 else 'フラット'
    inner_lbl = '内有利' if si > 0.5 else '外有利' if si < -0.5 else '枠フラット'

    trend_map = {
        'stable': '', 'front_gaining': ' ↗前有利が強まり中',
        'closer_gaining': ' ↗差し有利が強まり中',
        'inner_gaining': ' ↗内有利が強まり中',
        'outer_gaining': ' ↗外有利が強まり中',
    }
    trend_txt = trend_map.get(dash['trend'], '')

    return (f"{front_lbl}({sf:+.1f}σ) / {inner_lbl}({si:+.1f}σ) "
            f"[信頼度{conf}% / {s['n']}R]{trend_txt}")


# ──────────────────────────────────────────────
# Phase 5: 開催日目(nichi)バイアス
# ──────────────────────────────────────────────
# jravan.db 2018-25 芝の開催日目別平均(バックテスト済み):
#   day1=front56.0%/inner33.7% → day7=front52.2%/inner26.4%
_NICHI_FRONT = {
    1: 0.560, 2: 0.537, 3: 0.551, 4: 0.511, 5: 0.505,
    6: 0.527, 7: 0.522, 8: 0.510, 9: 0.514, 10: 0.478,
}
_NICHI_INNER = {
    1: 0.337, 2: 0.326, 3: 0.326, 4: 0.310, 5: 0.332,
    6: 0.308, 7: 0.264, 8: 0.305, 9: 0.312, 10: 0.314,
}


def nichi_bias(nichi, surface='芝'):
    """開催日目から芝の傷み傾向を返す。ダートは影響なしでNone。
    戻り値: {'nichi', 'front_expected', 'inner_expected', 'wear_label', 'note'} or None。
    """
    if 'ダ' in str(surface):
        return None
    try:
        d = int(nichi)
    except (TypeError, ValueError):
        return None
    if d < 1 or d > 12:
        return None
    fe = _NICHI_FRONT.get(d, 0.52)
    ie = _NICHI_INNER.get(d, 0.31)
    if d <= 2:
        wear = '開幕週'
        note = '芝が新鮮 → 内枠・先行有利が強い傾向'
    elif d <= 4:
        wear = '序盤'
        note = '内側の芝がやや傷み始め → まだ先行有利'
    elif d <= 6:
        wear = '中盤'
        note = '内側の傷みが進行 → 外差しが台頭し始める'
    elif d <= 8:
        wear = '終盤(仮柵移動期)'
        note = '内ラチ沿い荒れ → 外枠・差し有利が増加（仮柵移動で一時リセットの可能性）'
    else:
        wear = '最終盤'
        note = '馬場状態は場/天候次第（日目だけでは判断困難）'
    return {
        'nichi': d, 'front_expected': round(fe, 3),
        'inner_expected': round(ie, 3), 'wear_label': wear, 'note': note,
    }
