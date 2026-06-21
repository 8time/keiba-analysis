# -*- coding: utf-8 -*-
"""
クッション値/含水率の24時間キャッシュ — core/track_cond_cache.py

クッション値・含水率は『開催日×競馬場』単位の値(その日その場の全レース共通)。
毎レース入力するのは手間なので、一度入れたら同じ開催日・場の他レースに自動引き継ぎ、
24時間で自動消去する。キー = race_idの先頭10桁(年4+場2+回2+日2 = 開催日×場を一意特定)。
"""
import os
import json
import time

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'data', 'track_cond_cache.json')
TTL = 86400  # 24時間(秒)


def _load_all():
    if not os.path.exists(_PATH):
        return {}
    try:
        with open(_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _prune(data):
    """24時間を過ぎたエントリを削除して返す(自動消去)。"""
    now = time.time()
    return {k: v for k, v in data.items()
            if isinstance(v, dict) and (now - v.get('ts', 0)) < TTL}


def day_key(race_id):
    """race_id(12桁) → 開催日×場キー(先頭10桁 = 年+場+回+日)。"""
    s = ''.join(ch for ch in str(race_id) if ch.isdigit())
    return s[:10] if len(s) >= 10 else s


def load(race_id):
    """{cushion, moist_goal, moist_corner} or None。24h超過は無視&自動削除。"""
    k = day_key(race_id)
    if not k:
        return None
    data = _prune(_load_all())
    # 期限切れがあれば掃除を反映
    try:
        with open(_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
    v = data.get(k)
    if not v:
        return None
    return {'cushion': v.get('cushion'), 'moist_goal': v.get('moist_goal'),
            'moist_corner': v.get('moist_corner')}


def save(race_id, cushion=None, moist_goal=None, moist_corner=None):
    """開催日×場キーで保存(24時間有効)。Noneや0は保存しない(既存値を消さない)。"""
    k = day_key(race_id)
    if not k:
        return
    data = _prune(_load_all())
    cur = data.get(k, {}) if isinstance(data.get(k), dict) else {}
    for name, val in (('cushion', cushion), ('moist_goal', moist_goal),
                      ('moist_corner', moist_corner)):
        try:
            fv = float(val) if val is not None else 0.0
        except Exception:
            fv = 0.0
        if fv > 0:
            cur[name] = fv
    if not cur:
        return
    cur['ts'] = time.time()
    data[k] = cur
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        with open(_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
