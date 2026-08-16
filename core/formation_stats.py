# -*- coding: utf-8 -*-
"""買い方の性質（実配当ベースの分布統計）を引く。

data/formation_stats.json は scripts/formation_distribution.py が生成。
34,212レース(2016-2026)の実配当payoutsで、妙味度ゾーン×券種ごとに
「その買い方を長く続けたら何が起きるか」を測ったもの。

⚠これはレース単位の予測ではない。「この帯でこの形を買い続けた場合の性質」であり、
  目の前のレースが当たるかどうかは何も言っていない。
⚠全ゾーン・全形でROI<100%(最良でC中庸3連単の88%)。資金管理は-EVを+EVに変えない
  ([[verified_formation_sweep_holdout]])。ここで示すのは"負けの深さ"と"必要資金"。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_HERE, '..', 'data', 'formation_stats.json')
_cache = None

# 妙味度→ゾーン名(scripts/vscore_zone_formation.py の ZONES と一致させること)
ZONE_BOUNDS = [('D 鉄板 (1-49)', 0, 50), ('C 中庸 (50-69)', 50, 70),
               ('B/A 荒れ (70-)', 70, 201)]
ZONE_SHORT = {'D 鉄板 (1-49)': 'D 鉄板', 'C 中庸 (50-69)': 'C 中庸',
              'B/A 荒れ (70-)': 'B/A 荒れ'}


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_PATH, 'r', encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def zone_of(vscore):
    """妙味度(0-100)→ゾーン名。Noneなら中庸扱い。"""
    v = 50.0 if vscore is None else float(vscore)
    for lbl, lo, hi in ZONE_BOUNDS:
        if lo <= v < hi:
            return lbl
    return ZONE_BOUNDS[-1][0]


def get(vscore, kind):
    """kind: 'trio'(3連複) / 'trifecta'(3連単)。引けなければ None。"""
    d = _load()
    if not d:
        return None
    return d.get(f'{zone_of(vscore)}|{kind}')


def summary_line(vscore, kind):
    """1行サマリ。UIのキャプション用。"""
    s = get(vscore, kind)
    if not s:
        return ''
    return (f"{ZONE_SHORT.get(s['zone'], s['zone'])}帯で{s['kind_jp']}"
            f"{s['shape']}({s['points']}点)を買い続けた場合の実測: "
            f"的中{s['hit_rate']:.1f}% / 回収率{s['roi']:.0f}% / "
            f"平均配当{s['pay_mean']:,.0f}円(中央値{s['pay_median']:,.0f}円) / "
            f"最大{s['max_streak']}連敗")


def required_bankroll(vscore, kind, unit=100, safety=1.5):
    """最大連敗に耐えるのに要る資金の目安(円)。

    safety=1.5 は「実測の最大連敗より5割長い不runを見込む」ぶんの余裕。
    過去の最大連敗はあくまで観測値で、これを超える連敗は普通に起こりうる。
    """
    s = get(vscore, kind)
    if not s:
        return None
    per_race = s['points'] * unit
    return int(per_race * s['max_streak'] * safety)


def caution(vscore, kind):
    """注意すべき点を短文リストで返す(UIで箇条書きする用)。"""
    s = get(vscore, kind)
    if not s:
        return []
    out = []
    if s['roi'] < 100:
        out.append(f"回収率{s['roi']:.0f}%＝長期では負ける買い方です"
                   f"（控除率の壁。全ゾーンで100%超は見つかっていません）")
    if s['pay_mean'] > s['pay_median'] * 1.8:
        out.append(f"平均配当{s['pay_mean']:,.0f}円に対し中央値{s['pay_median']:,.0f}円＝"
                   f"回収率は一部の高配当が作っています。普段の的中はもっと安いです")
    if s.get('max_streak'):
        out.append(f"最大{s['max_streak']}連敗の実績があります"
                   f"（1点{100}円なら{s['points']*100*s['max_streak']:,}円ぶん外し続けた計算）")
    if s.get('plus_year_rate') is not None:
        out.append(f"年間で見てプラスになる確率は約{s['plus_year_rate']:.0f}%"
                   f"（{max(1, round(100/max(s['plus_year_rate'],1)))}年に1回）")
    if s.get('year_roi_min') is not None:
        out.append(f"年ごとの回収率は{s['year_roi_min']:.0f}〜{s['year_roi_max']:.0f}%で振れます")
    return out


# ── ゾーン別の「買う／見送る」助言 ──────────────────────
# 出典はすべて実測（[[verified_vscore_zone_formation]] [[verified_axis_vh_trio]]
# [[verified_rank_vs_ninki_legs]] [[verified_arare_zone_buy]]）。
# ⚠全ゾーンでROI100%未満。「勝てる買い方」ではなく「負けが浅い買い方」。
ZONE_ADVICE = {
    'D 鉄板 (1-49)': {
        'mark': '🟢', 'verdict': '買い候補',
        'best': '◎〇+人気3-4位の3連複2点',
        'hit': 23.5, 'roi': 90,
        'alt': '的中回数が欲しいなら +穴1-2位の4点（的中31.5% / 回収89%）',
        'why': 'このゾーンが最も効率が良い。投資も最小（2点＝200円）',
    },
    'C 中庸 (50-69)': {
        'mark': '🟡', 'verdict': '買うなら3連単',
        'best': '3連単 Rank2-4-7（30点）',
        'hit': 7.9, 'roi': 92,
        'alt': '3連複なら ◎〇+人気3-4位+穴1-2位の4点（回収83%）',
        'why': '3連単の方が明確に良い唯一のゾーン',
    },
    'B/A 荒れ (70-)': {
        'mark': '🔴', 'verdict': '見送り推奨',
        'best': '（買うなら）3連複 人気3-5-8の37点',
        'hit': 40.5, 'roi': 84,
        'alt': '20点で済ませるなら vh上位1+人気上位5（回収83%）',
        'why': '最良でも84%でD鉄板の90%に届かず、37点＝3,700円が必要。'
               '人気1・2を外すと40〜64%に壊滅するので穴一辺倒も不可',
    },
}


def zone_advice(vscore):
    """妙味度 → 買う/見送るの助言。引けなければ None。"""
    a = ZONE_ADVICE.get(zone_of(vscore))
    if not a:
        return None
    out = dict(a)
    out['zone'] = zone_of(vscore)
    out['zone_short'] = ZONE_SHORT.get(out['zone'], out['zone'])
    return out


def zone_line(vscore):
    """1行サマリ（スキャナーの一覧用）。"""
    a = zone_advice(vscore)
    if not a:
        return ''
    return (f"{a['mark']} {a['verdict']}（{a['zone_short']}）"
            f" → {a['best']} 的中{a['hit']:.1f}% / 回収{a['roi']}%")
