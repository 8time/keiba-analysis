# -*- coding: utf-8 -*-
"""
軸馬候補セレクタ — 強適Ranking Tableに ◎〇▲ の軸マークを付ける。
─────────────────────────────────────────────
軸＝『3着内に来る信頼度（複勝率）が高い人気馬』。検証済みエッジのみで構成:

  base : 単勝オッズ別の実複勝率(jravan.db 2021-25)。オッズは人気(順位)より遥かに
         細かい3着内信頼度の指標。1.0-1.2倍94.9 / 1.8-2.2倍74.5 / 2.6-3.0倍64.3 /
         4.5-6.0倍45.2% …(scripts/axis_filters_backtest.py #3で検証。「2.5倍の崖」は
         存在せず滑らかな単調=資料の二分法は誤り。但しオッズ自体は強い軸指標)。
         → オッズ欠損(jravan.dbは約37%欠損)時のみ人気別複勝率で代替。

  圧勝(前走着差≥1.0秒): オッズを統制すると複勝率 -5〜-11pp(3帯一貫・小n)。
         前走圧勝馬は『オッズ相応にやや過剰人気』(資料の本来の主張)。
         → 加点しない。🔨は『過剰人気注意』の情報フラグ＋同信頼度の僅差で軽い減点。
         (人気ベース時は順位内の交絡で+15.7ppが有効なので、オッズ欠損時のみ加点)

※ 脚質(習性)は人気に織込み済で軸にはほぼ無効(verified_legtype_axis)＝採用しない。
※ #4 前走僅差負けは人気馬の中では+0.5ppで無効=不採用。
※ win_odds欠損のためROIは使わず、複勝率(3着内・完全)のみを根拠にする。

『迷わないようになるべく少なく』→ マークは最大3頭(◎〇▲)。信頼度フロアを下回る
候補にはマークを付けない(波乱含みのレースではマークが減る)。
"""

# 単勝オッズ別 実複勝率(%) — jravan.db 2021-2025 全出走馬。(upper_exclusive, 複勝率)
ODDS_FUKU = [
    (1.2, 94.9), (1.5, 91.8), (1.8, 81.1), (2.2, 74.5), (2.6, 68.7), (3.0, 64.3),
    (3.5, 59.8), (4.5, 52.5), (6.0, 45.2), (8.0, 37.3), (12.0, 30.5), (20.0, 22.5),
    (9999.0, 7.2),
]
# 人気別 実複勝率(%) — オッズ欠損時のフォールバック
POP_FUKU = {1: 70.1, 2: 56.0, 3: 44.2, 4: 34.6, 5: 26.6, 6: 20.6, 7: 15.4, 8: 11.7}
# NAR(地方)専用 人気別 実複勝率(%) — jravan.db 南関含む地方2023-25・各n≈7000で実測。
# 地方はJRAより「チョーク(人気決着)」: 上位人気が堅く(1番人気78.7%>JRA70.1%)、人気薄は飛ぶ。
# NARはオッズ欠損=常に人気基準。JRA表を使うと1番人気を過小評価し軸が動きやすくなる為、専用表で較正。
POP_FUKU_NAR = {1: 78.7, 2: 61.2, 3: 47.0, 4: 35.9, 5: 26.3, 6: 18.8, 7: 14.0, 8: 9.7}

ATSU_MARGIN = 1.0       # 圧勝とみなす前走着差(秒)
ATSU_DEMERIT = 5.0      # オッズ基準時の圧勝=過剰人気の軽い減点(pp)
ATSU_POP_BONUS = 15.7   # 人気基準(オッズ欠損)時のみ有効な加点(pp)

# 信頼度フロア: これ未満の馬にはその印を付けない(少なく・迷わない)
FLOOR = {'◎': 50.0, '〇': 42.0, '▲': 35.0}
MAX_CAND_POP = 6        # 軸候補とする人気上限(穴は軸にしない=妙味軸/ヒモの役割)


def _valid_odds(odds):
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    return o if (1.0 <= o < 9999.0) else None


def _odds_fuku(o):
    for upper, fr in ODDS_FUKU:
        if o < upper:
            return fr
    return ODDS_FUKU[-1][1]


def _axis_conf(pop, table, odds=None, prev_win_margin=None):
    """内部: 人気別複勝率テーブル table を使って信頼度を算出(JRA/NAR共通ロジック)。"""
    try:
        p = int(pop)
    except (TypeError, ValueError):
        p = None
    if p is not None and (p < 1 or p > MAX_CAND_POP):
        return None

    o = _valid_odds(odds)
    atsu = (prev_win_margin is not None and prev_win_margin >= ATSU_MARGIN)

    if o is not None:
        conf = _odds_fuku(o)
        if atsu:
            conf -= ATSU_DEMERIT          # オッズ統制下では圧勝は過剰人気=軽い減点
    elif p is not None:
        conf = table.get(p, max(8.0, table.get(1, 70.0) - (p - 1) * 11.0))
        if atsu:
            conf += ATSU_POP_BONUS        # 人気基準時のみ順位内交絡で加点が有効
    else:
        return None
    return round(max(0.0, min(conf, 95.0)), 1)


def axis_confidence(pop, odds=None, prev_win_margin=None):
    """1頭の推定3着内信頼度(%)を返す(JRA/中央)。軸候補外(人気なし/MAX超)は None。
    オッズがあればオッズ基準、無ければ人気基準(POP_FUKU)。"""
    return _axis_conf(pop, POP_FUKU, odds, prev_win_margin)


def axis_confidence_nar(pop, odds=None, prev_win_margin=None):
    """NAR(地方)版。NAR実測の複勝率表(POP_FUKU_NAR)を人気基準で使う。
    地方はオッズ市場が中央ほど厚くなく、NAR較正は人気ベースなので odds は使わず人気基準に固定。
    地方は人気決着傾向が強く、JRA表だと1番人気(実78.7%)を過小評価する為の較正。"""
    return _axis_conf(pop, POP_FUKU_NAR, None, prev_win_margin)


def _marks(horses, conf_fn):
    out = {}
    scored = []
    for h in horses:
        nm = str(h.get('name', ''))
        pwm = h.get('prev_win_margin')
        conf = conf_fn(h.get('pop'), h.get('odds'), pwm)
        atsu = (pwm is not None and pwm >= ATSU_MARGIN)
        out[nm] = {'mark': '', 'conf': conf, 'atsu': atsu}
        if conf is not None:
            scored.append((conf, nm))
    scored.sort(key=lambda x: x[0], reverse=True)
    # 軸候補は◎〇の2頭まで(ユーザー方針: 3番手▲は着内が"たまに"で迷いの元。
    # 検証も固定軸=人気1+2の2頭が最適[project_axis_selection]と一致)。▲は廃止。
    order = ['◎', '〇']
    for i, (conf, nm) in enumerate(scored[:2]):
        mk = order[i]
        if conf >= FLOOR[mk]:
            out[nm]['mark'] = mk
    return out


def axis_marks(horses):
    """horses: [{'name','pop','odds'(任意),'prev_win_margin'(任意)}]
    戻り: {name: {'mark': '◎'/'〇'/'▲'/'', 'conf': float|None, 'atsu': bool}}(JRA/中央)
    """
    return _marks(horses, axis_confidence)


def axis_marks_nar(horses):
    """NAR(地方)版の軸マーク。POP_FUKU_NARで較正した信頼度で◎〇▲を付す。
    地方は1番人気が堅い(78.7%)ので軸は素直に人気上位へ。JRA較正スコアに引っ張らせない。"""
    return _marks(horses, axis_confidence_nar)
