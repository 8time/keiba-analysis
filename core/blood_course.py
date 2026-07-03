# -*- coding: utf-8 -*-
"""血統×コースの検証済みユーティリティ(血統SPページの強化用)。

検証(scripts/blood_course_backtest.py・train2021-24/holdout2025):
  ・父系統×コース形状(直線長/坂)・父×当該場コース適性は【人気に織込み済み】。
    (生き残った組合せは全て『場の効果』の交絡=サンデー系と非サンデー系で残差ほぼ同一)
  ・父×場コース適性tier(2014-20算出)も高適性残差≈0/低適性×穴はholdout崩落→両方向とも却下。
  ・本物だった副産物=【場×人気の軸信頼度】(血統でなくコースバイアス):
      東京芝×1-3人気: 複勝残差+3.67pp(頭数帯コントロール後・z+4.5・2021-25全年+・holdout2025 z+2.2)
      小倉芝×1-3人気: 複勝残差-2.98pp(z-2.9)
      (中山芝-1.9pp z-2.05は境界のため非配線)

このモジュールが提供するもの:
  sire_line(sire)      : 父名→大系統(アンカー遡上+手動辞書)。表示用(エッジ主張なし)。
  venue_fav_note(jyo, surface, ninki): 検証済みの場×人気軸信頼度ノート or None。
"""
import os
import sqlite3

_JV_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'data', 'jravan.db')

# 大系統アンカー(遡上して最初に一致した系統を採用)。blood_course_backtest.pyと同一定義。
ANCHORS = [
    ('サンデーサイレンス', 'サンデー系'),
    ('キングカメハメハ', 'キンカメ系'),
    ('Kingmambo', 'ミスプロ系'), ('キングマンボ', 'ミスプロ系'),
    ('Mr. Prospector', 'ミスプロ系'), ('ミスタープロスペクター', 'ミスプロ系'),
    ('Gone West', 'ミスプロ系'), ('ゴーンウエスト', 'ミスプロ系'),
    ('Seeking the Gold', 'ミスプロ系'), ('シーキングザゴールド', 'ミスプロ系'),
    ('Roberto', 'ロベルト系'), ('ロベルト', 'ロベルト系'),
    ('ブライアンズタイム', 'ロベルト系'), ('グラスワンダー', 'ロベルト系'),
    ('シンボリクリスエス', 'ロベルト系'), ('スクリーンヒーロー', 'ロベルト系'),
    ('Storm Cat', 'ストームキャット系'), ('ストームキャット', 'ストームキャット系'),
    ('ヘネシー', 'ストームキャット系'), ('Hennessy', 'ストームキャット系'),
    ('ヨハネスブルグ', 'ストームキャット系'),
    ('A.P. Indy', 'APインディ系'), ('エーピーインディ', 'APインディ系'),
    ('Pulpit', 'APインディ系'), ('タピット', 'APインディ系'), ('Tapit', 'APインディ系'),
    ('Northern Dancer', 'ND欧州系'), ('ノーザンダンサー', 'ND欧州系'),
    ('Danehill', 'ND欧州系'), ('デインヒル', 'ND欧州系'),
    ("Sadler's Wells", 'ND欧州系'), ('サドラーズウェルズ', 'ND欧州系'),
    ('ハービンジャー', 'ND欧州系'), ('Dansili', 'ND欧州系'),
]
# horsesで遡上できない外国産等の手動系統
MANUAL = {
    'シニスターミニスター': 'APインディ系', 'マジェスティックウォリアー': 'APインディ系',
    'ドレフォン': 'ストームキャット系', 'アメリカンペイトリオット': 'ND欧州系',
    'ニューイヤーズデイ': 'ストームキャット系', 'マインドユアビスケッツ': 'その他米国系',
    'デクラレーションオブウォー': 'ND欧州系', 'モーニン': 'その他米国系',
    'パイロ': 'APインディ系', 'ダノンレジェンド': 'ストームキャット系',
    'ベストウォーリア': 'その他米国系', 'カリフォルニアクローム': 'その他米国系',
    'ミッキーアイル': 'サンデー系', 'モズアスコット': 'その他米国系',
    'ブリックスアンドモルタル': 'ストームキャット系',
}
_ANCH = dict(ANCHORS)

_NAME_MAP = None   # {bamei: (sire, birth)} 生年最新(同名馬の曖昧性回避)
_LINE_MEMO = {}


def _load_name_map(db_path=None):
    global _NAME_MAP
    if _NAME_MAP is not None:
        return _NAME_MAP
    path = db_path or _JV_DB
    _NAME_MAP = {}
    if not os.path.exists(path):
        return _NAME_MAP
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
        for bamei, sire, birth in con.execute("SELECT bamei, sire, birth FROM horses"):
            if not bamei:
                continue
            b = str(birth or '')
            cur = _NAME_MAP.get(bamei)
            if cur is None or b > cur[1]:
                _NAME_MAP[bamei] = (sire, b)
        con.close()
    except Exception:
        pass
    return _NAME_MAP


def sire_line(sire_name, db_path=None, _depth=0):
    """父名→大系統。horsesテーブルを名前遡上(同名馬は生年最新を種牡馬とみなす)。
    未解決は'その他'。表示用(血統×コースはpriced-in検証済=エッジ主張なし)。"""
    if not sire_name:
        return 'その他'
    if sire_name in _LINE_MEMO:
        return _LINE_MEMO[sire_name]
    if sire_name in MANUAL:
        _LINE_MEMO[sire_name] = MANUAL[sire_name]
        return MANUAL[sire_name]
    if sire_name in _ANCH:
        _LINE_MEMO[sire_name] = _ANCH[sire_name]
        return _ANCH[sire_name]
    if _depth >= 5:
        return 'その他'
    nm = _load_name_map(db_path)
    parent = (nm.get(sire_name) or (None,))[0]
    res = sire_line(parent, db_path, _depth + 1) if parent else 'その他'
    _LINE_MEMO[sire_name] = res
    return res


# 検証済み: 場×人気の軸信頼度(頭数帯コントロール後の複勝残差・2021-25)
_VENUE_FAV = {
    ('05', '芝'): {'shift': +3.7, 'z': +4.5, 'flag': '🟢軸信頼UP',
                   'detail': '東京芝×1-3人気: 複勝+3.7pp(全年+・holdout z+2.2)'},
    ('10', '芝'): {'shift': -3.0, 'z': -2.9, 'flag': '⚠軸信頼DOWN',
                   'detail': '小倉芝×1-3人気: 複勝-3.0pp(z-2.9)'},
}


def venue_fav_note(jyo, surface, ninki=None):
    """検証済みの場×人気軸信頼度。1-3番人気(またはninki=None=レース文脈)のみ返す。
    戻り値: {'shift': pp, 'z': float, 'flag': str, 'detail': str} or None"""
    try:
        if ninki is not None and not (1 <= int(ninki) <= 3):
            return None
    except (TypeError, ValueError):
        return None
    surf = '芝' if '芝' in str(surface or '') else 'ダ' if 'ダ' in str(surface or '') else ''
    return _VENUE_FAV.get((str(jyo).zfill(2), surf))
