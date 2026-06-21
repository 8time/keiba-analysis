# -*- coding: utf-8 -*-
"""
採点テーブル(総合戦闘力/予測スコア)のレース横断キャッシュ。

左メニューを新タブ化したことで各ページが別Streamlitセッションになり、
🏠 Single Race Analysis の st.session_state['current_bonus_df'] を
🧹 消去フィルター タブから読めなくなった(連携断)。これをディスク経由で復活させる。

🏠で採点したら write_scores(race_id, df) でディスクに保存し、
🧹側は read_scores(race_id) で race_id 一致のスコアを読み戻す。
"""
import os
import json
import time

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'data', 'score_cache')


def _path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.json")


def write_scores(race_id, df):
    """df(Umaban/Projected Score/BattleScore を含む)から umaban->scores を保存。"""
    if not race_id or df is None:
        return
    try:
        import pandas as pd
        rows = {}
        pcol = 'Projected Score' if 'Projected Score' in df.columns else None
        for _, r in df.iterrows():
            try:
                um = int(pd.to_numeric(r.get('Umaban'), errors='coerce'))
            except Exception:
                continue
            proj = pd.to_numeric(r.get(pcol), errors='coerce') if pcol else None
            battle = pd.to_numeric(r.get('BattleScore'), errors='coerce') if 'BattleScore' in df.columns else None
            rows[str(um)] = {
                'proj': float(proj) if proj == proj and proj is not None else None,
                'battle': float(battle) if battle == battle and battle is not None else None,
            }
        if not rows:
            return
        os.makedirs(_DIR, exist_ok=True)
        with open(_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(), 'scores': rows},
                      f, ensure_ascii=False)
    except Exception:
        pass


def _rear_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.rear.json")


def write_rear(race_id, umaban_set):
    """展開MAPの最終直線『後方グループ』馬番を保存(🧹消去クロスから参照)。"""
    if not race_id:
        return
    try:
        ums = sorted(int(u) for u in (umaban_set or []) if u is not None)
        os.makedirs(_DIR, exist_ok=True)
        with open(_rear_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(), 'rear': ums},
                      f, ensure_ascii=False)
    except Exception:
        pass


def read_rear(race_id):
    """{馬番(int), ...} or None。"""
    if not race_id:
        return None
    p = _rear_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return set(int(u) for u in (data.get('rear') or []))
    except Exception:
        return None


def _keep_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.keep.json")


def write_keep(race_id, umaban_list):
    """🧹消去フィルターで最終的に残した馬を保存(🏠3連複エンジンが自動取込)。"""
    if not race_id:
        return
    try:
        ums = sorted({int(u) for u in (umaban_list or []) if u is not None})
        os.makedirs(_DIR, exist_ok=True)
        with open(_keep_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(), 'keep': ums},
                      f, ensure_ascii=False)
    except Exception:
        pass


def read_keep(race_id):
    """{馬番(int), ...} or None。"""
    if not race_id:
        return None
    p = _keep_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return set(int(u) for u in (data.get('keep') or []))
    except Exception:
        return None


def read_scores(race_id):
    """{umaban(int): {'proj':float|None,'battle':float|None}} or None。"""
    if not race_id:
        return None
    p = _path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        out = {}
        for k, v in (data.get('scores') or {}).items():
            try:
                out[int(k)] = v
            except Exception:
                continue
        return out or None
    except Exception:
        return None
