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

import math as _math

# 単勝オッズ別 実複勝率(%) — jravan.db 2021-2025 全出走馬。(upper_exclusive, 複勝率)
ODDS_FUKU = [
    (1.2, 94.9), (1.5, 91.8), (1.8, 81.1), (2.2, 74.5), (2.6, 68.7), (3.0, 64.3),
    (3.5, 59.8), (4.5, 52.5), (6.0, 45.2), (8.0, 37.3), (12.0, 30.5), (20.0, 22.5),
    (9999.0, 7.2),
]
# ── 表示用の滑らかな複勝率カーブ(散布図など『全馬を打つ』用途専用) ──
# ODDS_FUKU は軸マーク判定用の階段テーブルで、最終段が「20倍以上=一律7.2%」に潰れている。
# 20倍超を実測で割ると 20-25倍16.6% / 32-40倍11.3% / 55-75倍6.5% / 110-200倍2.6% / 200倍超0.9% と
# 大きく違うため、階段のまま散布図に打つと人気薄が全員同じ高さに並んでしまう(横一列)。
# 複勝率はオッズに対し『崖なく滑らかに単調』(scripts/axis_filters_backtest.py で確認済)なので、
# 各ビンの幾何中心をアンカーにして log(オッズ) で線形補間する。数値の捏造ではなく実測の内挿。
# (代表オッズ, 実複勝率%) — jravan.db 全出走馬(n=1,843,036)。
ODDS_FUKU_CURVE = [
    (1.10, 94.9), (1.34, 91.8), (1.64, 81.1), (1.99, 74.5), (2.39, 68.7), (2.79, 64.3),
    (3.24, 59.8), (3.97, 52.5), (5.20, 45.2), (6.93, 37.3), (9.80, 30.5), (15.49, 22.5),
    (22.36, 16.6), (28.28, 13.8), (35.78, 11.3), (46.90, 8.8), (64.20, 6.5),
    (90.80, 4.6), (148.30, 2.6), (316.00, 0.9),
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

# 前走1着(勝ち上がり直後)の人気馬は『勝ち幅に関係なく』オッズ相応より走らない。
# scripts/axis_ng_backtest.py で検証(1-5番人気・オッズ20分位で統制した複勝率残差):
#   前走1着 全体        : train -1.28pp(z-7.18) / holdout -2.28pp(z-2.62)  ★両窓で有意
#   うち勝ち幅0.3-1.0秒 : train -1.00pp(z-3.43) / holdout -3.67pp(z-2.66)  ★圧勝でなくても負
#   うち僅差勝ち<0.3秒  : train -1.41pp(z-5.82) / holdout -0.97pp(z-0.82)
# → 現行の🔨圧勝(ATSU=勝ち幅1.0秒以上)は"前走1着"の一部でしかなく、大多数(圧勝でない勝ち馬)が
#   無警戒だった。ここを軽い減点で埋める。※複勝率の絶対値は高い(44.5%)ので軸から外すのではなく
#   『オッズほどには信頼できない』という信頼度の割引([[verified_ohtani_trap]]の運用と同じ)。
PREV_WIN_DEMERIT = 1.5  # 前走1着の軽い減点(pp)。ATSU(圧勝)が立つ時は二重計上しない

# 『本物の先行』(直近走の平均通過位置比率 < 0.28 = 前方28%以内)の人気馬も過剰人気。
# scripts/pci_front_axis_backtest.py で検証(1-5番人気・オッズ20分位で統制した複勝率残差):
#   先行(全体)                 : train -1.61pp(z-6.84) / holdout -1.86pp(z-3.23) ★
#   先行 × 前走1着でない(純粋分): train -1.03pp(z-4.00) / holdout -1.54pp(z-2.44) ★
#   先行 × 前走1着(最悪の組合せ): train -4.63pp(z-7.87) / holdout -3.41pp(z-2.45) ★
#   非先行 × 前走1着でない(対照): train +0.82pp(z+5.09) / holdout +1.00pp(z+2.54) ★ ←最も信頼できる軸
# ※[[verified_legtype_axis]]と矛盾しない: 先行馬の"生の"複勝率は確かに高い(44.1%)。だが
#   オッズがそれ以上に高い=過剰人気。前走1着と同じ『絶対値は高いが割高』のパターン。
#   前走1着とは独立(上記の純粋分)なので減点は加算する。
FRONT_RATIO = 0.28      # 本物の先行とみなす平均通過位置比率(core/calculator.front_threshold と同値)
FRONT_DEMERIT = 1.2     # 先行の軽い減点(pp)。前走1着の減点とは加算(独立に効くと検証済)

# 牝馬限定戦×1番人気: オッズ統制した複勝率残差 train-1.1pp(z-1.54)/holdout-4.9pp(z-2.94)。
# 2番人気以下は残差≈0で無効。1.5-3.0倍帯の「普通の1番人気」で-2.0〜-2.6pp。
# trainのzが弱い(-1.54)のでまず保守的に1.0ppで導入し、実運用で監視する。
FILLIES_DEMERIT = 1.0   # 牝馬限定×1番人気の軽い減点(pp)。前走1着/先行とは加算


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


def _odds_fuku_smooth(o):
    """表示用: ODDS_FUKU_CURVE を log(オッズ)で線形補間した滑らかな複勝率(%)。
    軸マーク判定には使わない(検証済みの階段テーブル _odds_fuku は据え置き)。"""
    xs = ODDS_FUKU_CURVE
    if o <= xs[0][0]:
        return xs[0][1]
    if o >= xs[-1][0]:
        return xs[-1][1]
    lo = _math.log(o)
    for (x0, y0), (x1, y1) in zip(xs, xs[1:]):
        if o <= x1:
            t = (lo - _math.log(x0)) / (_math.log(x1) - _math.log(x0))
            return y0 + t * (y1 - y0)
    return xs[-1][1]


def _axis_conf(pop, table, odds=None, prev_win_margin=None, prev_chaku=None,
               pos_ratio=None, fillies_race=False):
    """内部: 人気別複勝率テーブル table を使って信頼度を算出(JRA/NAR共通ロジック)。

    prev_chaku(前走着順)は任意。1着なら PREV_WIN_DEMERIT を引く(勝ち上がり直後は過剰人気)。
    圧勝(ATSU)が立つ場合は ATSU_DEMERIT のみ適用し二重計上しない(圧勝 ⊂ 前走1着)。
    pos_ratio(平均通過位置比率)は任意。FRONT_RATIO未満(=本物の先行)なら FRONT_DEMERIT を引く。
    前走1着の減点とは独立に効くと検証済みなので加算する。
    fillies_race(bool)は任意。1番人気のみ FILLIES_DEMERIT を引く(2番人気以下は残差≈0で無効)。
    """
    try:
        p = int(pop)
    except (TypeError, ValueError):
        p = None
    if p is not None and (p < 1 or p > MAX_CAND_POP):
        return None

    o = _valid_odds(odds)
    atsu = (prev_win_margin is not None and prev_win_margin >= ATSU_MARGIN)
    try:
        prev_win = (prev_chaku is not None and int(prev_chaku) == 1)
    except (TypeError, ValueError):
        prev_win = False
    try:
        front = (pos_ratio is not None and 0 < float(pos_ratio) < FRONT_RATIO)
    except (TypeError, ValueError):
        front = False

    if o is not None:
        conf = _odds_fuku(o)
        if atsu:
            conf -= ATSU_DEMERIT          # オッズ統制下では圧勝は過剰人気=軽い減点
        elif prev_win:
            conf -= PREV_WIN_DEMERIT      # 圧勝でなくても『前走1着』は同様に過剰人気(検証済)
        if front:
            conf -= FRONT_DEMERIT         # 本物の先行も過剰人気(前走1着とは独立・検証済)
        if fillies_race and p is not None and p == 1:
            conf -= FILLIES_DEMERIT       # 牝馬限定×1番人気(2番人気以下は効果なし)
    elif p is not None:
        conf = table.get(p, max(8.0, table.get(1, 70.0) - (p - 1) * 11.0))
        if atsu:
            conf += ATSU_POP_BONUS        # 人気基準時のみ順位内交絡で加点が有効
    else:
        return None
    return round(max(0.0, min(conf, 95.0)), 1)


def axis_confidence(pop, odds=None, prev_win_margin=None, prev_chaku=None,
                    pos_ratio=None, fillies_race=False):
    """1頭の推定3着内信頼度(%)を返す(JRA/中央)。軸候補外(人気なし/MAX超)は None。
    オッズがあればオッズ基準、無ければ人気基準(POP_FUKU)。
    prev_chaku(前走着順)=1なら軽い減点、pos_ratio<0.28(本物の先行)ならさらに軽い減点。
    どちらも『生の複勝率は高いがオッズがそれ以上に高い=過剰人気』(検証済・両窓有意)。
    fillies_race=Trueなら1番人気のみ軽い減点(2番人気以下は残差≈0で無効)。"""
    return _axis_conf(pop, POP_FUKU, odds, prev_win_margin, prev_chaku, pos_ratio,
                      fillies_race=fillies_race)


def axis_confidence_nar(pop, odds=None, prev_win_margin=None, prev_chaku=None,
                        pos_ratio=None, fillies_race=False):
    """NAR(地方)版。NAR実測の複勝率表(POP_FUKU_NAR)を人気基準で使う。
    地方はオッズ市場が中央ほど厚くなく、NAR較正は人気ベースなので odds は使わず人気基準に固定。
    地方は人気決着傾向が強く、JRA表だと1番人気(実78.7%)を過小評価する為の較正。
    ※前走1着/先行の減点はオッズ基準(中央)で検証したものなので、人気基準のNARには適用しない。
    ※fillies_raceはNARでは人気基準パスに入り効果なし(中央のオッズ基準でのみ検証済)。"""
    return _axis_conf(pop, POP_FUKU_NAR, None, prev_win_margin, prev_chaku, pos_ratio)


# ── レース単位の軸信頼度（補正Tトップ3 ∩ 人気トップ3 の重複数）──────────────
# 検証: scripts/time_pop_overlap_backtest.py (31,613レース・補正T被覆率91%)
#   重複数 → 1番人気の複勝率(holdout2025+recent2026の加重平均)
#     0(13%) 57%  /  1(43%) 62%  /  2(38%) 68%  /  3(6%) 76%
#   本線決着率も 26%→28%→36%→46% と単調。
# ⚠ 荒れ予報には足さないこと。凍結オッズロジット(AUC0.690)との残差は
#   両窓とも|z|<2で非有意＝荒れ予測としてはpriced-in([[verified_time_pop_overlap]])。
#   使ってよいのは「軸が信頼できるか」の表示だけ。
_RACE_AXIS_TABLE = {
    0: (57, '⚠軸が立ちにくい', '実力上位と人気上位が食い違う'),
    1: (62, 'ふつう', '実力上位と人気上位が1頭だけ一致'),
    2: (68, '軸は立つ', '実力上位と人気上位が2頭一致'),
    3: (76, '🎯勝負向き', '実力上位3頭と人気上位3頭が完全一致'),
}


def race_axis_confidence(horses):
    """レース単位の軸信頼度。補正Tトップ3と人気トップ3が何頭重なるかを返す。

    horses: [{'umaban':int, 'ninki':int|None, 'ct_fig':float|None}, ...]
            ct_fig は補正タイム(負=速い)。None の馬は実力上位の判定から除く。
    戻り値: {'overlap':0-3, 'label':str, 'fav_top3':int(%), 'why':str,
             'time_top3':[馬番], 'pop_top3':[馬番]} / 判定不能なら None

    判定不能: 補正Tを持つ馬が3頭未満、または人気が3頭分揃わないレース。
    """
    if not horses:
        return None
    ct, pop = [], []
    for h in horses:
        try:
            um = int(h.get('umaban'))
        except (TypeError, ValueError):
            continue
        f = h.get('ct_fig')
        if f is not None:
            try:
                ct.append((float(f), um))
            except (TypeError, ValueError):
                pass
        try:
            n = int(h.get('ninki'))
            if n >= 1:
                pop.append((n, um))
        except (TypeError, ValueError):
            pass
    if len(ct) < 3 or len(pop) < 3:
        return None
    ct.sort()                      # 補正Tは小さいほど速い
    pop.sort()
    t3 = {um for _v, um in ct[:3]}
    p3 = {um for _n, um in pop[:3]}
    ov = len(t3 & p3)
    rate, label, why = _RACE_AXIS_TABLE[ov]
    return {'overlap': ov, 'label': label, 'fav_top3': rate, 'why': why,
            'time_top3': sorted(t3), 'pop_top3': sorted(p3)}


def fuku_rate(pop, odds=None, is_nar=False):
    """全出走馬の推定複勝率(%)。軸候補ゲート(MAX_CAND_POP)を掛けない表示専用版。

    axis_confidence() は『軸マークを付けるか』の判定器なので7番人気以下を None で弾く。
    ZONEシート(散布図)のように全馬をプロットする用途でそれを使うと人気薄が丸ごと消える為、
    ゲート無しの複勝率だけをここで返す。軸マーク判定には使わないこと。

    オッズがある場合は階段テーブルでなく ODDS_FUKU_CURVE の対数補間を使う。階段のままだと
    20倍超が全員7.2%に潰れて散布図で横一列になる(実測では16.6%〜0.9%まで開きがある)。

    ※2026-09-08: SRAの推定3着内率の表示はこの関数に統一(🎯軸馬候補列＋「軸の信頼度」ブロック)。
      以前は🎯軸馬候補列が axis_confidence(階段+減点)の conf を表示しており、同じ馬に
      2種類の%(例: 62%と64%)が出ていた。◎〇マークの判定は従来どおり axis_confidence を使う。
    """
    try:
        p = int(pop)
    except (TypeError, ValueError):
        p = None
    table = POP_FUKU_NAR if is_nar else POP_FUKU
    o = None if is_nar else _valid_odds(odds)   # NARはオッズ市場が薄く人気基準に固定
    if o is not None:
        return round(max(0.0, min(_odds_fuku_smooth(o), 95.0)), 1)
    if p is not None and p >= 1:
        conf = table.get(p, max(3.0, table.get(8, 10.0) - (p - 8) * 1.5))
        return round(max(0.0, min(conf, 95.0)), 1)
    return None


def _marks(horses, conf_fn, fillies_race=False):
    out = {}
    scored = []
    for h in horses:
        nm = str(h.get('name', ''))
        pwm = h.get('prev_win_margin')
        pch = h.get('prev_chaku')
        prr = h.get('pos_ratio')
        conf = conf_fn(h.get('pop'), h.get('odds'), pwm, pch, prr,
                       fillies_race=fillies_race)
        atsu = (pwm is not None and pwm >= ATSU_MARGIN)
        try:
            prev_win = (pch is not None and int(pch) == 1)
        except (TypeError, ValueError):
            prev_win = False
        try:
            front = (prr is not None and 0 < float(prr) < FRONT_RATIO)
        except (TypeError, ValueError):
            front = False
        out[nm] = {'mark': '', 'conf': conf, 'atsu': atsu,
                   'prev_win': prev_win, 'front': front}
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


def axis_marks(horses, fillies_race=False):
    """horses: [{'name','pop','odds'(任意),'prev_win_margin'(任意),'prev_chaku'(任意)}]
    戻り: {name: {'mark': '◎'/'〇'/'▲'/'', 'conf': float|None, 'atsu': bool, 'prev_win': bool}}
    fillies_race: 牝馬限定戦なら1番人気に-1.0pp減点(2番人気以下は効果なし)。
    """
    return _marks(horses, axis_confidence, fillies_race=fillies_race)


def axis_marks_nar(horses):
    """NAR(地方)版の軸マーク。POP_FUKU_NARで較正した信頼度で◎〇▲を付す。
    地方は1番人気が堅い(78.7%)ので軸は素直に人気上位へ。JRA較正スコアに引っ張らせない。"""
    return _marks(horses, axis_confidence_nar)
