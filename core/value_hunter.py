# -*- coding: utf-8 -*-
"""妙味馬ハンター 軽量・透明スコア (core/value_hunter.py)。

Fable案件①(重いLGBM vh2)の改善主成分＝「①帯内オッズ順序の回収 ②二値top3の崖の除去(連続量化)」を、
モデルファイル不要・高速・特徴量パリティ問題なしの透明な7特徴ロジスティックで再現したもの。
検証(scripts/value_hunter_light.py・7番人気以下・fit≤2024/holdout2025/直近3ヶ月):
  recall70% @ precision16.3%(基準の2.09倍)。現行combo≥2(52%@12.2%)を全域で上回り、
  重いLGBM(73.5%@14.3%)にも匹敵。係数は neg_log_odds0.88(市場支配)+ct_pct0.41(補正T)が主。

⚠ 正直な位置づけ: スコアの主成分は市場情報(オッズ順序)。これは「7番人気以下で3着内に来る馬を
   高再現率で網羅するショートリスト」であって『買えば儲かる(+EV)リスト』ではない(単勝市場は効率的)。
   単勝EV/回収率の主張には使わない。用途は複勝/ワイド/3連複の相手・軸候補の絞り込みと、
   統合ビューでの『強材料があれば消去フラグだけで切らない』救済。

パラメータは data/value_hunter_light.json (scripts/value_hunter_light.py が生成)。
"""
import os
import json
import math

_PARAMS = None
_PARAM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'data', 'value_hunter_light.json')

# 特徴の並び(JSONと一致させる)
FEATS = ['neg_log_odds', 'ct_pct', 'spurt_pct', 'blood_pct', 'combo', 'low_elim', 'pos_front']


def load_params():
    """学習済みパラメータ(mu/sd/w/b/ops)を読む。無ければNone。"""
    global _PARAMS
    if _PARAMS is None:
        try:
            with open(_PARAM_PATH, encoding='utf-8') as f:
                _PARAMS = json.load(f)
        except Exception:
            _PARAMS = {}
    return _PARAMS or None


def available():
    return load_params() is not None


def prob(feat):
    """7特徴dictから3着内確率(0..1)を返す。パラメータ無ければNone。
    feat: {'neg_log_odds','ct_pct','spurt_pct','blood_pct','combo','low_elim','pos_front'}
    欠損は中立値(percentile=0.5, フラグ=0)で埋める。"""
    p = load_params()
    if not p:
        return None
    mu, sd, w, b = p['mu'], p['sd'], p['w'], p['b']
    defaults = {'neg_log_odds': None, 'ct_pct': 0.5, 'spurt_pct': 0.5,
                'blood_pct': 0.5, 'combo': 0.0, 'low_elim': 0.0, 'pos_front': 0.0}
    z = b
    for i, fname in enumerate(FEATS):
        v = feat.get(fname)
        if v is None:
            v = defaults[fname]
        if v is None:   # neg_log_odds欠損=スコア不能
            return None
        sdi = sd[i] if sd[i] else 1.0
        z += w[i] * ((float(v) - mu[i]) / sdi)
    return 1.0 / (1.0 + math.exp(-z))


def tier(score):
    """スコア→運用点ラベル。ops['recall0.5']以上=精鋭 / recall0.7以上=広域網 / それ未満=圏外。"""
    p = load_params()
    if not p or score is None:
        return ''
    ops = p.get('ops', {})
    if score >= ops.get('recall0.5', 1.1):
        return '🎯精鋭'
    if score >= ops.get('recall0.7', 1.1):
        return '🕸️広域網'
    return ''


def _pct(valmap, higher_better):
    """{key:value}→{key:percentile 0..1(1=最良)}。None除外。field相対=連続量化。"""
    items = [(k, v) for k, v in valmap.items() if v is not None]
    if not items:
        return {}
    items.sort(key=lambda x: x[1], reverse=higher_better)
    n = len(items)
    return {k: 1.0 - i / max(n - 1, 1) for i, (k, _) in enumerate(items)}


def build_features(ctfig, spurt, blood, combo_map, elim_map, odds_map, front_set=None):
    """レース内の各指標マップから7特徴を組み立てる(field percentile化はここで一括)。
    ctfig={um:補正T fig(小=良)}, spurt/blood={um:値(大=良)}, combo_map/elim_map={um:count},
    odds_map={um:単勝オッズ}, front_set=平均位置≤3の馬番set(任意)。
    戻り: {um: feat_dict}。オッズ欠損の馬は neg_log_odds=None(スコア不能)。
    """
    ct_pct = _pct(ctfig or {}, higher_better=False)
    sp_pct = _pct(spurt or {}, higher_better=True)
    bl_pct = _pct(blood or {}, higher_better=True)
    front_set = front_set or set()
    out = {}
    ums = set(odds_map or {}) | set(ct_pct) | set(sp_pct) | set(bl_pct) | set(combo_map or {})
    for u in ums:
        o = (odds_map or {}).get(u)
        out[u] = {
            'neg_log_odds': (-math.log(float(o)) if o and float(o) > 0 else None),
            'ct_pct': ct_pct.get(u, 0.5),
            'spurt_pct': sp_pct.get(u, 0.5),
            'blood_pct': bl_pct.get(u, 0.5),
            'combo': float((combo_map or {}).get(u, 0)),
            'low_elim': 1.0 if (elim_map or {}).get(u, 9) <= 1 else 0.0,
            'pos_front': 1.0 if u in front_set else 0.0,
        }
    return out


def score_race(ctfig, spurt, blood, combo_map, elim_map, odds_map, front_set=None):
    """レース分の {um: {'score','tier','prob'}} を返す(スコア降順は呼び元で)。"""
    feats = build_features(ctfig, spurt, blood, combo_map, elim_map, odds_map, front_set)
    out = {}
    for u, f in feats.items():
        pv = prob(f)
        if pv is not None:
            out[u] = {'score': pv, 'tier': tier(pv), 'prob': pv}
    return out
