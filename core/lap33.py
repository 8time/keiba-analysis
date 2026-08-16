# -*- coding: utf-8 -*-
"""33ラップ理論(鈴木ショータ氏考案)の実装。

定義: レースの『中盤3F相当ペース』(=残り1200m〜600mのペースを600m換算した値)から
その馬自身の上がり3F(ato3f)を引いた値。
  正(プラス)=瞬発力型(中盤が緩み、上がりで加速するレースに強い)
  負(マイナス)=持久力型(中盤から流れ、上がりが相対的に遅くなるレースに強い)
1200m戦は"中盤"が存在しないため、前半3F(mae3f)と上がり3F(ato3f)の単純比較になる
(原典の「1200mのレースは単純に前後半のペース」に準拠)。

データ源: jravan.db。races.mae3f/ato3f はレース全体で共有される区間タイム(先頭集団の
通過ベース)、results.ato3f は各馬個別の上がり3F。33ラップは「レース共有の中盤ペース」
と「その馬個別の上がり」を比較することで、原典の『展開と馬の個性を照合する』趣旨に合う。

実査(2026-07-04): races.mae3f/ato3f はJRA2016+で96%カバー、results.ato3fは100%カバー。
原典PDFの「コース別平均33ラップ一覧表」を自前計算で再現(符号・序列は完全一致、絶対値は
近似): 中山ダ1200=-3.40(原典-3.47)/小倉芝1200=-1.59(-1.63)/東京芝1800=+2.37(+1.78)等。

注意: 33ラップの骨格(馬の得意展開×今回の想定展開)は展開適合度/PCI適合と同じ概念族で、
それらは検証済みでpriced-in([[verified_pci_pricedin]][[verified_tenkai_priced_in]])。
このモジュール単体はエッジを主張しない・scripts/lap33_backtest.pyでの検証が前提。
NAR(地方)はjravan/nankanともラップデータ無しのため非対応(JRA限定)。
"""
import os
import sqlite3
from collections import defaultdict

JV_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db'
)


def _con(db_path=None):
    return sqlite3.connect(f'file:{db_path or JV_DB_PATH}?mode=ro', uri=True, timeout=10)


def _to_sec10(v):
    """jravanの3F区間タイム(1/10秒int・例349=34.9秒)を秒に変換。0/NoneはNone。
    3F区間は常に60秒未満のため単純/10でよい(分の繰り上がりが無い)。"""
    try:
        v = float(v)
        return v / 10.0 if v > 0 else None
    except (TypeError, ValueError):
        return None


def _to_sec_full(v):
    """jravanの完走タイム(分+1/10秒が連結したint。例1454=1分45.4秒=105.4秒)を秒に変換。
    3F区間タイムと異なり分の繰り上がりがあるため、末尾3桁を秒(0.1刻み)・それ以前を分として扱う。
    0/None/短距離の3桁以下(=分なし)にも対応。"""
    try:
        s = str(int(v))
    except (TypeError, ValueError):
        return None
    if not s or s == '0':
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def race_mid3f_rate(kyori, mae3f, ato3f, race_time):
    """レースの『中盤3F相当ペース』(600m換算・秒)を返す。1200mは前半3Fそのもの。

    kyori: 距離(m)。mae3f/ato3f/race_time: jravan生値(1/10秒int)。
    race_time は基準となる完走タイム(通常は1着馬のtime)。
    戻り値: 秒(float) or None(距離不足/データ欠損)。
    """
    mae = _to_sec10(mae3f)
    ato = _to_sec10(ato3f)
    t = _to_sec_full(race_time)
    if mae is None or ato is None:
        return None
    if kyori and kyori <= 1200:
        return mae
    if t is None:
        return None
    mid_len = (kyori or 0) - 1200
    if mid_len <= 0:
        return None
    mid_time = t - mae - ato
    if mid_time <= 0:
        return None
    return mid_time * 600.0 / mid_len


def lap33(mid3f_rate, agari3f_sec):
    """33ラップ = 中盤3F相当ペース − 上がり3F。正=瞬発力型、負=持久力型。"""
    if mid3f_rate is None or agari3f_sec is None:
        return None
    return round(mid3f_rate - agari3f_sec, 2)


def _fetch_race_context(db_path=None, year_from=2016, year_to=9999):
    """(race_key)→{'jyo','surface','kyori','mid3f_rate'} を全JRAレース分構築する。

    mid3f_rateは1着馬のtimeを基準に算出(レース共有の中盤ペース)。
    """
    con = _con(db_path)
    rows = con.execute(
        "SELECT ra.race_key, ra.jyo, ra.surface, ra.kyori, ra.mae3f, ra.ato3f, r.time "
        "FROM races ra JOIN results r ON r.race_key=ra.race_key AND r.chakujun=1 "
        "WHERE ra.jyo<='10' AND CAST(ra.year AS INT) BETWEEN ? AND ? "
        "AND ra.mae3f>0 AND ra.ato3f>0", (year_from, year_to)).fetchall()
    con.close()
    ctx = {}
    for rk, jyo, surf, kyori, mae, ato, t in rows:
        mid = race_mid3f_rate(kyori, mae, ato, t)
        if mid is None:
            continue
        s = '芝' if '芝' in str(surf) else 'ダ'
        ctx[rk] = {'jyo': jyo, 'surface': s, 'kyori': kyori, 'mid3f_rate': mid}
    return ctx


def race_lap33(kyori, mae3f, ato3f, race_time):
    """レース1本の33ラップ(共有値)。mae3f/ato3fは全馬共有のレース区間タイム(先頭通過ベース)
    なので、個別馬のato3fは使わずレース単位で1つの値を返す(=原典のコース平均表の構成単位)。
    race_timeは中盤区間の長さを逆算するための基準タイム(通常は1着馬のtime)。"""
    if kyori and kyori <= 1200:
        return lap33(_to_sec10(mae3f), _to_sec10(ato3f))
    mid = race_mid3f_rate(kyori, mae3f, ato3f, race_time)
    return lap33(mid, _to_sec10(ato3f))


_COURSE_AVG_CACHE = {}  # (surface,kyori,jyo,year_from,year_to,db_path) -> {'avg','n'} or None


def course_avg33(surface, kyori, jyo=None, db_path=None, year_from=2016, year_to=9999):
    """コース(場×芝ダ×距離)の平均33ラップ(レース単位・原典と同じ構成)を返す。

    原典の『コース別平均33ラップ一覧表』のアプリ内自動生成版。mae3f/ato3fは全馬共有の
    レース区間タイムのため、個別馬の上がりでなくレース単位で1値を採る(=race_lap33)。
    戻り値: {'avg': float, 'n': int} or None(該当なし)。jyo省略時は全国平均。
    プロセス内キャッシュあり(1レース内で馬ごとに呼ばれても再クエリしない・~0.9秒/回)。
    """
    key = (surface, kyori, jyo, year_from, year_to, db_path)
    if key in _COURSE_AVG_CACHE:
        return _COURSE_AVG_CACHE[key]
    con = _con(db_path)
    surf_like = '%芝%' if surface == '芝' else '%ダ%'
    q = ("SELECT ra.mae3f, ra.ato3f, rw.time "
         "FROM races ra JOIN results rw ON rw.race_key=ra.race_key AND rw.chakujun=1 "
         "WHERE ra.jyo<='10' AND CAST(ra.year AS INT) BETWEEN ? AND ? "
         "AND ra.kyori=? AND ra.surface LIKE ? AND ra.mae3f>0 AND ra.ato3f>0")
    params = [year_from, year_to, kyori, surf_like]
    if jyo:
        q += " AND ra.jyo=?"
        params.append(str(jyo).zfill(2))
    rows = con.execute(q, params).fetchall()
    con.close()
    if not rows:
        _COURSE_AVG_CACHE[key] = None
        return None
    vals = [v for mae, ato, wtime in rows
            if (v := race_lap33(kyori, mae, ato, wtime)) is not None]
    if not vals:
        _COURSE_AVG_CACHE[key] = None
        return None
    result = {'avg': round(sum(vals) / len(vals), 2), 'n': len(vals)}
    _COURSE_AVG_CACHE[key] = result
    return result


def horse_fit33(ketto_num, db_path=None, before_key=None, n_runs=10, min_runs=3):
    """馬の過去走(直近n_runs走・before_key以前=リーク遮断)から、33ラップの得意傾向を返す。

    戻り値: {'avg_lap33': float|None, 'runs': int, 'lean': '瞬発力型'|'持久力型'|'両型'|None,
             'placed_avg': float|None, 'unplaced_avg': float|None}
    lean判定: 好走時(3着内)平均33ラップの符号で分類(原典の3パターン分類に対応)。
    """
    out = {'avg_lap33': None, 'runs': 0, 'lean': None, 'placed_avg': None, 'unplaced_avg': None}
    if not ketto_num or not os.path.exists(db_path or JV_DB_PATH):
        return out
    con = _con(db_path)
    where = "r.ketto_num=? AND r.chakujun>0 AND r.jyo<='10' AND r.ato3f>0"
    params = [str(ketto_num)]
    if before_key:
        where += " AND r.race_key<?"
        params.append(str(before_key))
    rows = con.execute(
        f"SELECT r.race_key, r.chakujun, r.ato3f, ra.mae3f, ra.ato3f AS r_ato3f, ra.kyori, "
        f"rw.time FROM results r JOIN races ra ON ra.race_key=r.race_key "
        f"JOIN results rw ON rw.race_key=r.race_key AND rw.chakujun=1 "
        f"WHERE {where} AND ra.mae3f>0 AND ra.ato3f>0 "
        f"ORDER BY r.race_key DESC LIMIT ?", params + [n_runs]).fetchall()
    con.close()
    if not rows:
        return out
    placed, unplaced, all_v = [], [], []
    for rk, chaku, h_ato, ra_mae, ra_ato, kyori, wtime in rows:
        mid = race_mid3f_rate(kyori, ra_mae, ra_ato, wtime)
        v = lap33(mid, _to_sec10(h_ato))
        if v is None:
            continue
        all_v.append(v)
        (placed if chaku <= 3 else unplaced).append(v)
    out['runs'] = len(all_v)
    if len(all_v) < min_runs:
        return out
    out['avg_lap33'] = round(sum(all_v) / len(all_v), 2)
    if placed:
        out['placed_avg'] = round(sum(placed) / len(placed), 2)
        out['lean'] = '瞬発力型' if out['placed_avg'] > 0.3 else ('持久力型' if out['placed_avg'] < -0.3 else '両型')
    if unplaced:
        out['unplaced_avg'] = round(sum(unplaced) / len(unplaced), 2)
    return out


def fit_match(horse_avg_lap33, course_avg_lap33, threshold=0.0):
    """馬の得意33ラップとコース平均33ラップの符号一致(適合)を判定。

    ⚠ 旧方式。符号を見るだけなので該当馬が多すぎる(実測で人気薄の**74.8%**が該当)。
      コース平均は1コース1つの符号に固定されるため、瞬発力型コースでは
      瞬発力型の馬が全員通ってしまう構造的な問題がある。
      新規の判定には fit_distance() を使うこと(この関数は後方互換のため残置)。

    戻り値: True(適合・同符号) / False(不適合・逆符号) / None(データ不足)。
    """
    if horse_avg_lap33 is None or course_avg_lap33 is None:
        return None
    if abs(horse_avg_lap33) < threshold or abs(course_avg_lap33) < threshold:
        return None
    return (horse_avg_lap33 > 0) == (course_avg_lap33 > 0)


# 距離判定のしきい値(原典PDF新聞の『±0.5秒ルール』に準拠)
FIT_NEAR = 0.5     # ○ ドンピシャ
FIT_WIDE = 1.0     # △ 守備範囲


def fit_distance(horse_lap33, course_avg_lap33, near=FIT_NEAR, wide=FIT_WIDE):
    """馬の得意33ラップと今回のコース平均33ラップの『距離』で適合を判定する。

    符号一致(fit_match)ではなく、原典の『±0.5秒ルール』と同じ距離ベース。
    |馬の値 − コース平均| が near以内なら'○'、wide以内なら'△'、それ以外は''。

    検証(scripts/lap33_distance_backtest.py・train2021-24/holdout2025・
      コース平均は2010-2020で凍結・馬の値は各レース時点より前の履歴のみ=リーク無し):
      人気薄(6番人気以下)×好走時平均を使った場合の複勝残差(holdout)
        符号一致(旧)  該当率74.8% → +1.42pp (z+4.28)
        距離<=1.0     該当率44.2% → +1.70pp (z+3.93)
        **距離<=0.5   該当率23.9% → +1.83pp (z+3.12)**  ★採用
        距離<=0.3     該当率14.6% → +2.02pp (z+2.68)
      絞るほど残差が単調に増える＝信号が本物である傍証。bootstrapは全方式で
      95%CIが0を跨がない。人気上位(1-3番人気)はどの方式でも効かない(z-1.5〜+1.4)。

    戻り値: '○' / '△' / ''(範囲外) / None(データ不足)
    """
    if horse_lap33 is None or course_avg_lap33 is None:
        return None
    d = abs(float(horse_lap33) - float(course_avg_lap33))
    if d <= near:
        return '○'
    if d <= wide:
        return '△'
    return ''


def horse_lap33_value(fit_dict):
    """horse_fit33() の戻りから、適合判定に使うべき値を1つ選ぶ。

    **好走時平均(placed_avg)を優先**する。検証で全走平均(avg_lap33)より明確に強い:
      人気薄・holdout複勝残差 全走平均+0.84pp(z+2.97) → 好走時平均+1.42pp(z+4.28)。
    「その馬が実際に走れた時のラップ」を得意条件とみなす原典の考え方に沿う。
    好走歴が無い馬は全走平均にフォールバックする。
    """
    if not fit_dict:
        return None
    v = fit_dict.get('placed_avg')
    return v if v is not None else fit_dict.get('avg_lap33')
