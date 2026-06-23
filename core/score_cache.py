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


def _gate_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.gate.json")


def write_gate(race_id, status, lean=None, severity=None):
    """Scannerで見たレースのGate判定(scanner_play_status='buy'等)を保存。
    💰BetSyncの台帳記録時に read_gate で自動補完し、運用の取り違え/タグ漏れを防ぐ。"""
    if not race_id or not status:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_gate_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'status': status, 'lean': lean, 'severity': severity},
                      f, ensure_ascii=False)
    except Exception:
        pass


def read_gate(race_id):
    """{'status','lean','severity'} or None。"""
    if not race_id:
        return None
    p = _gate_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _buy_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.buy.json")


def write_buy(race_id, n_points=None, synth_odds=None, has_danger=None, has_value_ana=None):
    """3連複エンジンの買い目設計メタ(点数/合成オッズ/危険馬含有/妙味穴有無)を保存。
    💰BetSync記録時に read_buy で自動補完し、設計ミス系の負け分類(点数過多/トリガミ/盲目②)に使う。"""
    if not race_id:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_buy_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'n_points': n_points, 'synth_odds': synth_odds,
                       'has_danger': int(bool(has_danger)) if has_danger is not None else None,
                       'has_value_ana': int(bool(has_value_ana)) if has_value_ana is not None else None},
                      f, ensure_ascii=False)
    except Exception:
        pass


def read_buy(race_id):
    """{'n_points','synth_odds','has_danger','has_value_ana'} or None。"""
    if not race_id:
        return None
    p = _buy_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
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


def _magi_path():
    return os.path.join(_DIR, '_magi_bridge.json')


def _json_safe(v):
    """1セルをJSON保存可能な値に変換。リスト/辞書(PastRuns等)は構造を保持して往復可能にする。"""
    import pandas as pd
    # ネスト構造(PastRuns/WeightHistory等)はそのまま保持。pd.isnaはリストで例外なので先に判定
    if isinstance(v, (list, dict)):
        return v
    if isinstance(v, (str, bool)):
        return v
    if isinstance(v, (int, float)):
        return v
    try:
        if pd.isna(v):
            return None
    except (ValueError, TypeError):
        pass
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    return str(v)


def write_magi_bridge(race_id, df, metadata=None):
    """SRAで解析したDataFrameをディスクに保存しMAGIタブから読めるようにする。"""
    if not race_id or df is None:
        return
    try:
        cols = [c for c in df.columns if c not in ('_internal',)]
        records = []
        for _, r in df.iterrows():
            rec = {c: _json_safe(r.get(c)) for c in cols}
            records.append(rec)
        os.makedirs(_DIR, exist_ok=True)
        with open(_magi_path(), 'w', encoding='utf-8') as f:
            # default=str: リスト/辞書内にnumpy型等が残っても保存を止めない安全網
            json.dump({
                'race_id': str(race_id),
                'ts': time.time(),
                'metadata': metadata or {},
                'columns': cols,
                'records': records,
            }, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def read_magi_bridge():
    """MAGIタブ用: 最後にSRAで解析したレースのDF・メタデータ・race_idを返す。"""
    p = _magi_path()
    if not os.path.exists(p):
        return None, None, None
    try:
        import pandas as pd
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data.get('records', []), columns=data.get('columns', []))
        return df, data.get('metadata', {}), data.get('race_id', '')
    except Exception:
        return None, None, None


def _kelly_path():
    return os.path.join(_DIR, '_kelly_bridge.json')


def write_kelly_bridge(feed_dict):
    """SRA/買い方最適化タブで算出した勝率×オッズをディスク保存しBetSyncタブから読む。"""
    if not feed_dict:
        return
    try:
        os.makedirs(_DIR, exist_ok=True)
        with open(_kelly_path(), 'w', encoding='utf-8') as f:
            json.dump(feed_dict, f, ensure_ascii=False)
    except Exception:
        pass


def read_kelly_bridge():
    """BetSyncタブ用: SRAが書いたケリー用feedを読む。"""
    p = _kelly_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _full_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(_DIR, f"{rid}.full.json")


def write_race_full(race_id, df):
    """SRAで解析した完全なDataFrameをレースIDごとに永続保存(MAGI回顧がシグナルを読む)。
    _json_safeでリスト/辞書(PastRuns等)も構造保持。"""
    if not race_id or df is None or getattr(df, 'empty', True):
        return
    try:
        cols = [c for c in df.columns if c not in ('_internal',)]
        records = [{c: _json_safe(r.get(c)) for c in cols} for _, r in df.iterrows()]
        os.makedirs(_DIR, exist_ok=True)
        with open(_full_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'columns': cols, 'records': records}, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def read_race_full(race_id):
    """MAGI回顧用: race_id一致のSRA完全dfを返す(無ければNone)。"""
    if not race_id:
        return None
    p = _full_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        import pandas as pd
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data.get('records', []), columns=data.get('columns', []))
        return df if not df.empty else None
    except Exception:
        return None
