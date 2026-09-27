# -*- coding: utf-8 -*-
"""📰 新聞発行 — SRA解析結果をA4のPDF競馬新聞として組版・出力する。

データの流れ:
  🏠 Single Race Analysis が強適Ranking Table(表示用view_df)を確定した時点で
  write_view_snapshot() が data/newspaper/{race_id}.view.json に保存。
  統合ビュー(合議)の確定時に write_consensus_snapshot() が {race_id}.cv.json に保存。
  📰 新聞発行ページ(pages/newspaper_pub.py)はこれらを読み、HTMLに組版して
  Playwright(chromium)の page.pdf() でA4横/縦のPDFに変換する。

  SRAスナップショットが無い過去解析レースは data/score_cache/{rid}.full.json から
  代表列サブセットで紙面を再構成する(フォールバック)。

  PDF化はrequirements.txt既存のPlaywrightのみ使用(新ライブラリ追加なし)。
"""
import os
import re
import json
import time
import glob
import html as _htmlesc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NP_DIR = os.path.join(ROOT, 'data', 'newspaper')
SC_DIR = os.path.join(ROOT, 'data', 'score_cache')

VENUE_BY_CODE = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
    '30': '門別', '35': '盛岡', '36': '水沢',
    '42': '浦和', '43': '船橋', '44': '大井', '45': '川崎',
    '46': '金沢', '47': '笠松', '48': '名古屋',
    '50': '園田', '51': '姫路', '54': '高知', '55': '佐賀', '65': '帯広',
}

_EAST_VENUES = {'札幌', '函館', '福島', '新潟', '東京', '中山'}
_WEST_VENUES = {'中京', '京都', '阪神', '小倉'}

def _venue_region(venue_name):
    if venue_name in _EAST_VENUES:
        return 'east'
    if venue_name in _WEST_VENUES:
        return 'west'
    return None

# ────────────────────────────────────────────────────────────
# スナップショット保存(SRAから呼ばれる)
# ────────────────────────────────────────────────────────────

# 紙面テーブルに不要な重量級ネスト列(CSVはfull.json側から出すので欠落しない)
_SKIP_COLS = {'PastRuns', '_internal', '_suit_raw'}


def _scalar(v):
    """1セルをJSON保存可能なスカラーへ。ネスト(list/dict)はNone=列ごと除外対象。"""
    if isinstance(v, (list, dict)):
        return None
    if isinstance(v, (str, bool, int, float)):
        return v
    try:
        import pandas as pd
        if pd.isna(v):
            return None
    except Exception:
        pass
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    return str(v)


def _view_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.view.json")


def _cv_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.cv.json")


def _meta_from_df(df, meta=None):
    """view_df/full dfの先頭行からレースメタを抽出。"""
    m = {}
    try:
        r0 = df.iloc[0]
        for src, dst in [('RaceName', 'race_name'), ('Venue', 'venue'),
                         ('RaceDate', 'date'), ('CurrentDistance', 'distance'),
                         ('CurrentSurface', 'surface')]:
            if src in df.columns:
                v = _scalar(r0.get(src))
                if v is not None and str(v) != '':
                    m[dst] = v
    except Exception:
        pass
    if meta:
        for k in ('condition', 'course', 'race_name', 'venue', 'date', 'post_time'):
            if meta.get(k) and not m.get(k):
                m[k] = _scalar(meta.get(k))
    m['n_horses'] = int(len(df))
    return m


def write_view_snapshot(race_id, view_df, labels=None, order=None, meta=None, sort_label=''):
    """強適Ranking Table(表示用・全列フォーマット済み)を新聞用に保存。

    labels: {列名: 表示ラベル} / order: 現在アプリで表示中の列順(列名リスト)。
    """
    if not race_id or view_df is None or getattr(view_df, 'empty', True):
        return
    try:
        cols = [c for c in view_df.columns
                if c not in _SKIP_COLS and not str(c).endswith('__dup_right')]
        # ネスト値を含む列は紙面対象外(CSVはfull.jsonから出す)
        drop = set()
        records = []
        for _, r in view_df.iterrows():
            rec = {}
            for c in cols:
                v = r.get(c)
                if isinstance(v, (list, dict)):
                    drop.add(c)
                    continue
                rec[c] = _scalar(v)
            records.append(rec)
        cols = [c for c in cols if c not in drop]
        records = [{c: rec.get(c) for c in cols} for rec in records]
        # view_dfは表示整形でRaceName/Venue/日付列が落ちていることがある→full.jsonから補完
        # (欠けるとレース一覧が'?'表示になり日付フィルタも効かなくなる)
        m = _meta_from_df(view_df, meta)
        if not (m.get('race_name') and m.get('venue') and m.get('date')):
            fb = _read_full(race_id)
            if fb and fb.get('records'):
                r0 = fb['records'][0]
                for src, dst in [('RaceName', 'race_name'), ('Venue', 'venue'),
                                 ('RaceDate', 'date'), ('CurrentDistance', 'distance'),
                                 ('CurrentSurface', 'surface')]:
                    if not m.get(dst) and r0.get(src) not in (None, ''):
                        m[dst] = r0.get(src)
        # テーブル上書きでも検証済み買い方(playbook)は残す
        keep_pb = None
        vp = _view_path(race_id)
        if os.path.exists(vp):
            try:
                with open(vp, 'r', encoding='utf-8') as f:
                    keep_pb = (json.load(f) or {}).get('playbook')
            except Exception:
                keep_pb = None
        payload = {
            'race_id': str(race_id), 'ts': time.time(),
            'meta': m,
            'sort_label': str(sort_label or ''),
            'labels': {c: str((labels or {}).get(c, c)) for c in cols},
            'order': [c for c in (order or []) if c in cols],
            'columns': cols,
            'records': records,
        }
        if keep_pb is not None:
            payload['playbook'] = keep_pb
        os.makedirs(NP_DIR, exist_ok=True)
        with open(vp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _jsonable(v):
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (set, frozenset)):
        return sorted(_jsonable(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return _scalar(v)


def _forecast_from_odds(odds_list, meta, race_id, surface='', dist=None):
    """荒れ予報/妙味度/オッズ本命不在フラグ(全て検証済みの純関数)を計算。"""
    out = {}
    try:
        from core import value_scanner as vs
        odds = [float(o) for o in (odds_list or []) if o and float(o) > 0]
        if len(odds) < 5:
            return out
        n = len(odds)
        jyo = str(race_id)[4:6]
        p = vs.arare_prob(odds, meta or {}, n)
        if p is not None:
            out['arare_prob'] = round(float(p), 3)
        rv = vs.race_value_score(odds, meta or {}, jyo, surface or '', dist, n)
        if rv:
            out['value_label'] = str(rv.get('label', ''))
            try:
                out['value_score'] = round(float(rv.get('score')), 1)
            except Exception:
                pass
        nf = vs.no_favorite_flag(odds)
        if nf:
            out['no_fav'] = str(nf)
    except Exception:
        pass
    return out


def write_consensus_snapshot(race_id, regime, result, lean=None, aim=None, df=None, meta=None):
    """統合ビュー(合議)の結果(groups/horses)＋検証エッジ全セット(_aim)＋荒れ予報を新聞用に保存。

    aim: consensus_view.build_edge_sets の戻り値(danger/veto/combo/elim/vh/vh_tier/edge_reasons…)。
    df/meta を渡すと荒れ予報/妙味度をSRA時点のメタ(ハンデ等)込みで計算して同梱する。
    """
    if not race_id or not result:
        return
    forecast = {}
    if df is not None:
        try:
            import pandas as pd
            odds = pd.to_numeric(df['Odds'], errors='coerce').dropna().tolist() \
                if 'Odds' in df.columns else []
            surf = str(df['CurrentSurface'].iloc[0]) if 'CurrentSurface' in df.columns else ''
            try:
                dist = int(pd.to_numeric(df['CurrentDistance'].iloc[0], errors='coerce'))
            except Exception:
                dist = None
            forecast = _forecast_from_odds(odds, meta, race_id, surf, dist)
        except Exception:
            forecast = {}
    aim_out = None
    if aim:
        aim_out = _jsonable({k: aim.get(k) for k in
                             ('danger', 'veto', 'ana', 'combo', 'elim', 'vh', 'vh_tier',
                              'edge_reasons', 'danger_reasons') if k in aim})
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_cv_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({
                'race_id': str(race_id), 'ts': time.time(),
                'regime': str(regime or ''),
                'lean': _jsonable(lean or {}),
                'groups': _jsonable(result.get('groups', {})),
                'horses': _jsonable(result.get('horses', [])),
                'cross': _jsonable(result.get('cross') or {}),
                'aim': aim_out,
                'forecast': forecast,
            }, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _pace_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.pace.json")


def write_pace_snapshot(race_id, ctx):
    """展開MAPのコンテキスト(想定隊列pos4/直線到達finish/ペース/逃げ馬)を新聞用に保存。"""
    if not race_id or not ctx:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_pace_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'pos4': _jsonable(ctx.get('pos4') or {}),
                       'finish': _jsonable(ctx.get('finish') or {}),
                       'leader': _scalar(ctx.get('leader')),
                       'pace': str(ctx.get('pace') or ''),
                       'nige': _jsonable(ctx.get('nige_umas') or []),
                       'front_ratio': _scalar(ctx.get('front_ratio')),
                       'contested': bool(ctx.get('contested'))},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_pace(race_id):
    p = _pace_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _elim_verdict_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.elimv.json")


def write_elim_verdict_snapshot(race_id, rows):
    """🎯強適消去エンジンの判定(✅残し/🛟ボーダー残し/🧹消し)を新聞用に保存。
    rows: [{'馬番','馬名','判定'}, ...]（app.pyの_edf 判定列そのまま）。"""
    if not race_id or not rows:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_elim_verdict_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'rows': _jsonable(list(rows))},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_elim_verdict(race_id):
    p = _elim_verdict_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _bets_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.bets.json")


def write_bets_snapshot(race_id, kind, result, extra=None):
    """おすすめ買い目を券種別にマージ保存(kind=playbook/trio/trifecta/qe/wide)。
    playbook を足しても既存の trio/trifecta キーは消さない。"""
    if not race_id or not kind or not result:
        return
    try:
        data = {}
        p = _bets_path(race_id)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        keep = {k: result.get(k) for k in
                ('bets', 'wide', 'quinella', 'exacta', 'axis', 'meta', 'warning')
                if result.get(k) is not None}
        data[str(kind)] = {'ts': time.time(), 'extra': _jsonable(extra or {}),
                           'result': _jsonable(keep)}
        data['race_id'] = str(race_id)
        os.makedirs(NP_DIR, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def persist_playbook(race_id, rec):
    """検証済み買い方を bets.json と view.json の両方へ同じ形で残す。

    rec: playbook_tickets.build_tickets の戻り値。券の組み方は変えない。
    view.json がまだ無いときは bets だけ書き、後から view 保存時に再呼ぶ。
    """
    if not race_id or not isinstance(rec, dict):
        return
    try:
        from core import playbook_tickets as _pb
        payload = _pb.snapshot_payload(rec)
    except Exception:
        payload = {
            'bets': {'trio': rec.get('trio') or [],
                     'trifecta': rec.get('trifecta') or []},
            'axis': rec.get('axis') or [],
            'meta': {
                'zone': rec.get('zone'),
                'strategy': rec.get('strategy'),
                'rank_logic': rec.get('rank_logic'),
                'n_points': rec.get('n_points'),
                'ui_line': rec.get('ui_line'),
                'skip': rec.get('skip'),
                'warning': rec.get('warning'),
            },
            'warning': rec.get('warning'),
        }
    extra = {
        'zone': rec.get('zone'),
        'strategy': rec.get('strategy'),
        'rank_logic': rec.get('rank_logic'),
        'axis': rec.get('axis'),
        'n_points': rec.get('n_points'),
        'ui_line': rec.get('ui_line'),
        'skip': rec.get('skip'),
        'cross_n': rec.get('cross_n'),
        'selected_bet_type': rec.get('selected_bet_type'),
        'selected_playbook': rec.get('selected_playbook'),
        'selector_rule_version': rec.get('selector_rule_version'),
        'selection_reason': rec.get('selection_reason'),
        'skip_reason': rec.get('skip_reason'),
        'skip_detail': rec.get('skip_detail'),
        'cross_n_source': rec.get('cross_n_source'),
        'degraded': rec.get('degraded'),
        'diag_family': rec.get('diag_family'),
        'diag_plain': rec.get('diag_plain'),
        'diag_verdict': rec.get('diag_verdict'),
    }
    try:
        from core import playbook_ledger as _plg
        extra.update(_plg.generation_fields(rec))
    except Exception:
        pass
    prev = None
    try:
        prev = load_bets(race_id)
    except Exception:
        prev = None
    write_bets_snapshot(race_id, 'playbook', payload, extra=extra)
    _merge_playbook_into_view(race_id, payload, extra)
    try:
        from core import playbook_ledger as _plg2
        _plg2.preserve_outcome_if_same(race_id, rec, prev)
    except Exception:
        pass
    try:
        from core import playbook_shadow as _psh
        _psh.persist(race_id, rec)
    except Exception:
        pass


def _merge_playbook_into_view(race_id, payload, extra=None):
    """既存 view.json に playbook だけ足す。records / columns は触らない。"""
    p = _view_path(race_id)
    if not os.path.exists(p):
        return
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f) or {}
        keep = {k: payload.get(k) for k in
                ('bets', 'axis', 'meta', 'warning')
                if payload.get(k) is not None}
        data['playbook'] = {
            'ts': time.time(),
            'extra': _jsonable(extra or {}),
            'result': _jsonable(keep),
        }
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _j5_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.j5.json")


def write_j5_snapshot(race_id, rows, weight=None):
    """『騎手係数込み 総合スコア』(J5)の表示スナップショットを保存。

    rows: SRAで表示中の行(dictのlist)。weight: 騎手影響率スライダーの値(発行時点で固定)。
    J5は _j5_w スライダーに依存するため、紙面には『そのとき表示していた値』をそのまま載せる。
    """
    if not race_id or not rows:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_j5_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'weight': (float(weight) if weight is not None else None),
                       'rows': _jsonable(list(rows))},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_j5(race_id):
    p = _j5_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _value_zone_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.valuezone.json")


def write_value_zone_snapshot(race_id, rows):
    """複勝率×回収率マップ(①勝ちゾーン等)の判定結果を新聞用に保存。

    rows: SRAのゾーン散布図が計算した行(dictのlist・馬番/fuku/roi/odds/ゾーン等)。
    印刷ではテーブル形式を優先(散布図の画像化はPDF生成コスト増につながるため)。
    """
    if not race_id or not rows:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_value_zone_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'rows': _jsonable(list(rows))},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_value_zone(race_id):
    p = _value_zone_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _philosophy_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.philosophy.json")


def write_philosophy_snapshot(race_id, ph_res):
    """🧠開発者の思考(core/philosophy.think()の戻り値)を新聞用に保存。

    ph_res: {'steps':[{key,no,name,desc,enabled,verdict,reasons[]}...],
             'final':{'honmei','aite','ana','keshi','plan','skip','skip_reasons',...}}
    新しい予測ロジックは作らない層なので、ここでは受け取った結果をそのまま保存するだけ。
    """
    if not race_id or not ph_res:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_philosophy_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'steps': _jsonable(ph_res.get('steps') or []),
                       'final': _jsonable(ph_res.get('final') or {})},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_philosophy(race_id):
    p = _philosophy_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def load_bets(race_id):
    p = _bets_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _analysis_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.analysis.json")


def write_analysis_snapshot(race_id, key, payload):
    """SRAの分析パネルを紙面用にマージ保存。
    key: 'evidence'(判定根拠エビデンス表) / 'pci'(PCI&展開適合) /
         'pace_upset'(展開分析&波乱確率) / 'stress'(Stress Analyst)。"""
    if not race_id or not key or payload is None:
        return
    try:
        data = {}
        p = _analysis_path(race_id)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data[str(key)] = {'ts': time.time(), 'data': _jsonable(payload)}
        data['race_id'] = str(race_id)
        os.makedirs(NP_DIR, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_analysis(race_id):
    p = _analysis_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


SCAN_PATH = os.path.join(NP_DIR, 'scan_digest.json')

# ダイジェストに保存するスキャン結果のキー(重いbreakdown等は落とす)
_SCAN_KEEP = ('id', 'title', 'gate', 'vscore', 'vlabel', 'arare_prob', 'no_fav',
              'value_horses', 'ana_horses', 'danger_horses', 'n_h', 'surf', 'dist',
              'cls', 'cond', 'post_time', 'date_val', 'skips',
              # レース単位の軸信頼度(表示専用・scripts/time_pop_overlap_backtest.py)
              'axis_conf')


def write_scan_digest(rows):
    """🔍Race Scannerの結果(妙味度/荒れ予報/Gate/妙味馬…)を最新1回分ディスク保存。
    新聞発行ページ(別タブ=別セッション)からもスキャン新聞を発行できるようにする。"""
    if not rows:
        return
    try:
        out = []
        for r in rows:
            rec = {k: _jsonable(r.get(k)) for k in _SCAN_KEEP}
            rec['lean'] = str(((r.get('lean') or {}).get('lean')) or '')
            out.append(rec)
        os.makedirs(NP_DIR, exist_ok=True)
        with open(SCAN_PATH, 'w', encoding='utf-8') as f:
            json.dump({'ts': time.time(), 'rows': out}, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_scan_digest():
    """{'ts', 'rows': [...]} or None。"""
    if not os.path.exists(SCAN_PATH):
        return None
    try:
        with open(SCAN_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _ums_of(horses):
    """value_horses/danger_horses等(dict list or int list)から馬番intを取り出す。"""
    out = []
    for h in (horses or []):
        try:
            if isinstance(h, dict):
                out.append(int(h.get('um', h.get('umaban'))))
            else:
                out.append(int(h))
        except Exception:
            continue
    return out


def _lean_of(r):
    """決着タイプ文字列。Scannerセッション行はdict({'lean':..})・保存済み行はstrの両対応。"""
    v = r.get('lean')
    if isinstance(v, dict):
        v = v.get('lean')
    return str(v or '')


_GATE_DEF = {'buy': ('✅買える', '#2b8a3e'), 'axis_warn': ('🟡軸注意', '#e6a700'),
             'skip': ('⛔見送り', '#9e9e9e')}


def filter_scan_rows(rows, lean_mode='all', arare_range=(0, 100),
                     exclude_skip=True, max_races=12, sort_by='priority'):
    """ダイジェストの収録レースを絞る。lean_mode: all/ana(②穴妙味のみ)/honsen(本線=荒れ回避)。"""
    out = []
    for r in (rows or []):
        lean = _lean_of(r)
        if lean_mode == 'ana' and lean != '②穴妙味向き':
            continue
        if lean_mode == 'honsen' and lean != '本線向き':
            continue
        if exclude_skip and str(r.get('gate') or '') == 'skip':
            continue
        ap = r.get('arare_prob')
        if ap is not None:
            p = float(ap) * 100
            if not (float(arare_range[0]) <= p <= float(arare_range[1])):
                continue
        out.append(r)
    if sort_by == 'value':
        out.sort(key=lambda r: -(float(r.get('vscore') or 0)))
    # priority=保存順(Scannerの『買える順』階層ソート)を維持
    return out[:max(1, int(max_races or 12))]


def build_scan_digest_html(rows, opts=None):
    """スキャン結果ダイジェストをA4縦・2列カードで組版。(html, 採用rows) を返す。"""
    o = dict(opts or {})
    used = filter_scan_rows(rows, o.get('lean_mode', 'all'),
                            o.get('arare_range', (0, 100)),
                            bool(o.get('exclude_skip', True)),
                            int(o.get('max_races') or 12),
                            o.get('sort_by', 'priority'))
    if not used:
        return None, []
    mono = bool(o.get('mono'))
    accent = '#111' if mono else '#b3001b'
    cards = []
    for r in used:
        rid = str(r.get('id') or '')
        venue = VENUE_BY_CODE.get(rid[4:6], '')
        rno = race_no(rid)
        gate_lbl, gate_col = _GATE_DEF.get(str(r.get('gate') or ''), ('', '#888'))
        if mono:
            gate_col = '#555'
        title = str(r.get('title') or '')
        # レース性質行
        l1 = []
        vs_txt = ''
        if r.get('vscore') is not None:
            vs_txt = f"{float(r['vscore']):.0f}・"
        if r.get('vlabel'):
            l1.append(f"妙味度 <b>{vs_txt}{_esc(str(r['vlabel']))}</b>")
        if r.get('arare_prob') is not None:
            l1.append(f"荒れ予報 <b>{float(r['arare_prob']) * 100:.0f}%</b>")
        if _lean_of(r):
            l1.append(f"<b>{_esc(_lean_of(r))}</b>")
        if r.get('no_fav'):
            l1.append(f"<b>{_esc(str(r['no_fav']))}</b>")
        # 馬番行
        l2 = []
        v_ums = _ums_of(r.get('value_horses'))
        if v_ums:
            l2.append("🎯妙味馬 " + '・'.join(str(u) for u in v_ums[:6]))
        a_ums = [u for u in _ums_of(r.get('ana_horses')) if u not in v_ums[:6]]
        if a_ums:
            l2.append("🕳穴候補 " + '・'.join(str(u) for u in a_ums[:4]))
        d_ums = _ums_of(r.get('danger_horses'))
        if d_ums:
            l2.append("⚠危険人気 " + '・'.join(str(u) for u in d_ums[:4]))
        # コース/発走行
        l3 = []
        crs = f"{r.get('surf') or ''}{r.get('dist') or ''}m" if r.get('dist') else str(r.get('surf') or '')
        if crs:
            l3.append(_esc(crs))
        if r.get('n_h'):
            l3.append(f"{r['n_h']}頭")
        if r.get('cond'):
            l3.append(f"馬場{_esc(str(r['cond']))}")
        if r.get('post_time'):
            l3.append(f"発走{_esc(str(r['post_time']))}")
        skip_cls = ' sk' if str(r.get('gate') or '') == 'skip' else ''
        cards.append(
            f"<div class='scard{skip_cls}' style='border-left-color:{gate_col};'>"
            f"<div class='sc-h'><span class='sc-race'>{_esc(venue)}{rno or '?'}R</span>"
            f"<span class='sc-name'>{_esc(title)}</span>"
            f"<span class='sc-gate' style='color:{gate_col};'>{_esc(gate_lbl)}</span></div>"
            + (f"<div class='sc-l'>{'｜'.join(l1)}</div>" if l1 else '')
            + (f"<div class='sc-l'>{'｜'.join(l2)}</div>" if l2 else '')
            + f"<div class='sc-f'>{'　'.join(l3)}<span class='sc-id'>{_esc(rid)}</span></div>"
            + "</div>")

    import datetime as _dt
    today = _dt.date.today().strftime('%Y年%m月%d日')
    lean_note = {'ana': '②穴妙味（荒れ・大穴）のみ', 'honsen': '本線向きのみ（荒れ回避）',
                 'all': 'すべて'}.get(o.get('lean_mode', 'all'), '')
    css = f"""
    @page {{ size: A4 portrait; margin: 9mm 8mm; }}
    body {{ font-family: 'Yu Gothic UI','Yu Gothic','Meiryo',sans-serif; color: #111; margin: 0;
            -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .masthead {{ border-bottom: 3px double #111; padding-bottom: 1.5mm; margin-bottom: 3mm;
                 display: flex; align-items: baseline; justify-content: space-between; }}
    .daiji {{ font-family: 'Yu Mincho','MS Mincho',serif; font-size: 20pt; font-weight: 900;
              letter-spacing: 0.1em; color: {accent}; }}
    .issue {{ font-size: 8.5pt; color: #333; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2.5mm; }}
    .scard {{ border: 0.5px solid #999; border-left: 1.6mm solid #888; border-radius: 1.5mm;
              padding: 1.6mm 2.2mm; page-break-inside: avoid; background: #fff; }}
    .scard.sk {{ background: #f4f4f4; color: #888; }}
    .sc-h {{ display: flex; align-items: baseline; gap: 2mm; border-bottom: 0.4px solid #ddd;
             padding-bottom: 0.6mm; margin-bottom: 0.8mm; }}
    .sc-race {{ font-size: 12pt; font-weight: 900; }}
    .sc-name {{ font-size: 9.5pt; font-weight: 700; flex: 1; }}
    .sc-gate {{ font-size: 9pt; font-weight: 800; }}
    .sc-l {{ font-size: 8.5pt; line-height: 1.55; }}
    .sc-f {{ font-size: 7.5pt; color: #555; margin-top: 0.6mm; display: flex; gap: 2mm; }}
    .sc-id {{ margin-left: auto; font-family: Consolas, monospace; color: #999; }}
    .legend {{ font-size: 7.5pt; color: #444; margin-top: 2.5mm; border-top: 0.5px solid #999;
               padding-top: 1mm; }}
    """
    html = (f"<meta charset='utf-8'><style>{css}</style>"
            f"<div class='masthead'><span class='daiji'>{_esc(o.get('title') or '妙味レース速報')}</span>"
            f"<span class='issue'>{today} 発行｜{_esc(lean_note)}｜{len(used)}レース</span></div>"
            f"<div class='grid'>{''.join(cards)}</div>"
            "<div class='legend'>妙味度＝頭数/1番人気オッズ/上位拮抗/構造条件の集約(S-D)　"
            "荒れ予報＝検証済みオッズロジット(AUC0.69)　🎯妙味馬＝単複乖離/黄金ライン/厩舎当コース🔴の過小評価馬　"
            "⚠危険人気＝検証済み危険材料　✅買える/⛔見送り＝Scanner Gate。"
            "並びは買える順(見送り除外→軸フロア→危険なし→相手質→決着タイプ明確)。</div>")
    return html, used


def _styles_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.styles.json")


def write_view_styles(race_id, view_df, styler):
    """強適Ranking Table表示用Stylerの計算済みセルCSSを保存(アプリの色分けを紙面へ完全継承)。

    ルールを二重実装せず、表示時にStylerが計算した実セル色(ctx)をそのまま持ち出す。
    行は表示時の行順の位置(pos)キー=viewスナップショットのrecords順と同一。"""
    if not race_id or view_df is None or styler is None:
        return
    try:
        styler._compute()   # pandas Styler: ctxをクリアして再計算(冪等)
        ctx = getattr(styler, 'ctx', None) or {}
        cols = list(view_df.columns)
        keep = ('background-color', 'color', 'font-weight', 'font-style', 'text-align')
        styles = {}
        for (ri, ci), props in ctx.items():
            try:
                col = str(cols[ci])
            except Exception:
                continue
            if col.endswith('__dup_right'):
                continue
            try:
                css = '; '.join(f"{str(p).strip()}: {str(v).strip()}" for p, v in props
                                if str(p).strip() in keep and str(v).strip())
            except Exception:
                continue
            if css:
                styles.setdefault(str(int(ri)), {})[col] = css
        if not styles:
            return
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_styles_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'n_rows': int(len(view_df)), 'styles': styles},
                      f, ensure_ascii=False)
    except Exception:
        pass


def load_styles(race_id):
    p = _styles_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _alerts_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.alerts.json")


def write_alert(race_id, kind, title, lines, severity='warn'):
    """条件発動アラート(末脚妙味/枠順エッジ等)をkind別にマージ保存。

    lines=[] でも保存する=条件が消えたら古いアラートをクリアするため。
    紙面側は lines が空のアラートを表示しない。"""
    if not race_id or not kind:
        return
    try:
        data = {}
        p = _alerts_path(race_id)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        data[str(kind)] = {'ts': time.time(), 'title': str(title or ''),
                           'lines': [str(x) for x in (lines or [])],
                           'severity': str(severity or 'warn')}
        data['race_id'] = str(race_id)
        os.makedirs(NP_DIR, exist_ok=True)
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def load_alerts(race_id):
    p = _alerts_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# ────────────────────────────────────────────────────────────
# 読み出し・一覧
# ────────────────────────────────────────────────────────────

def load_view(race_id):
    """view.json(SRA表示スナップショット)。無ければfull.jsonフォールバック。Noneあり。"""
    p = _view_path(race_id)
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if d.get('records'):
                d['source'] = 'view'
                return d
        except Exception:
            pass
    return _fallback_view_from_full(race_id)


# full.jsonから紙面を再構成する時の代表列(列名, 表示ラベル)
_FB_COLS = [
    ('Umaban', '馬番'), ('Waku', '枠'), ('Name', '馬名'), ('SexAge', '性齢'),
    ('WeightCarried', '斤量'), ('Weight', '馬体重'), ('Jockey', '騎手'),
    ('Trainer', '厩舎'), ('Odds', '単勝'), ('Popularity', '人気'),
    ('Projected Score', '⭐予測スコア'), ('BattleScore', '🔥総合戦闘力'),
    ('Strength (X)', '💪強さX'), ('Suitability (Y)', '🎯適性Y'),
    ('NIndex', 'N指数'), ('OguraIndex', '指数'), ('AvgAgari', '平均上がり'),
    ('AvgPosition', '平均位置'), ('PCILabel', 'PCI'), ('Pos600m', '残600m'),
    ('Signal', '🔬シグナル'), ('Alert', '印'), ('ボーナス詳細', 'ボーナス内訳'),
    ('Bloodline', '血統'),
]


def _read_full(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    p = os.path.join(SC_DIR, f"{rid}.full.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _fallback_view_from_full(race_id):
    d = _read_full(race_id)
    if not d or not d.get('records'):
        return None
    recs = d['records']
    cols = [c for c, _ in _FB_COLS if c in (d.get('columns') or [])]
    # 予測スコア(無ければ総合戦闘力)降順に並べ、Rankを振る
    def _num(r, c):
        try:
            v = float(r.get(c))
            return v if v == v else float('-inf')
        except Exception:
            return float('-inf')
    key = 'Projected Score' if 'Projected Score' in cols else 'BattleScore'
    recs = sorted(recs, key=lambda r: -_num(r, key))
    out_recs = []
    for i, r in enumerate(recs, 1):
        rec = {'Rank': i}
        for c in cols:
            rec[c] = _scalar(r.get(c))
        out_recs.append(rec)
    columns = ['Rank'] + cols
    labels = {'Rank': 'Rank'}
    labels.update({c: lb for c, lb in _FB_COLS if c in cols})
    import pandas as pd
    return {
        'race_id': str(race_id), 'ts': d.get('ts'),
        'meta': _meta_from_df(pd.DataFrame(recs)),
        'sort_label': key,
        'labels': labels, 'order': columns, 'columns': columns,
        'records': out_recs, 'source': 'full',
    }


def load_consensus(race_id):
    p = _cv_path(race_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def race_no(race_id):
    try:
        return int(str(race_id)[-2:])
    except Exception:
        return None


def race_label(info):
    """一覧表示用 '07/11 小倉5R 3歳未勝利(16頭)'。"""
    m = info.get('meta', {}) if isinstance(info.get('meta'), dict) else {}
    d = str(m.get('date') or '')
    d = d.replace('-', '/')
    dd = d[5:] if len(d) >= 10 else d
    rn = race_no(info.get('race_id'))
    return (f"{dd} {m.get('venue', '?')}{rn or '?'}R "
            f"{m.get('race_name', '')}"
            f"({m.get('n_horses', '?')}頭)")


def list_available_races():
    """新聞に載せられるレース一覧(viewスナップショット∪full.json)。日付降順。"""
    seen = {}
    for p in glob.glob(os.path.join(NP_DIR, '*.view.json')):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                d = json.load(f)
            rid = d.get('race_id')
            if rid and d.get('records'):
                seen[rid] = {'race_id': rid, 'ts': d.get('ts'), 'meta': d.get('meta', {}),
                             'source': 'view', 'n_cols': len(d.get('columns') or [])}
        except Exception:
            continue
    for p in glob.glob(os.path.join(SC_DIR, '*.full.json')):
        rid = os.path.basename(p).split('.')[0]
        if rid in seen:
            continue
        d = _read_full(rid)
        if not d or not d.get('records'):
            continue
        r0 = d['records'][0]
        meta = {'race_name': r0.get('RaceName'), 'venue': r0.get('Venue'),
                'date': r0.get('RaceDate'), 'distance': r0.get('CurrentDistance'),
                'surface': r0.get('CurrentSurface'), 'n_horses': len(d['records'])}
        seen[rid] = {'race_id': rid, 'ts': d.get('ts'), 'meta': meta,
                     'source': 'full', 'n_cols': None}

    def _key(x):
        d = str((x['meta'] or {}).get('date') or '')
        return (d.replace('/', '-'), str(x['race_id']))
    return sorted(seen.values(), key=_key, reverse=True)


# ────────────────────────────────────────────────────────────
# CSVエクスポート(そのレースの全情報)
# ────────────────────────────────────────────────────────────

def _consensus_csv_cols(race_id, umabans):
    """合議スナップショット(cv.json)から馬番→結論列(役割/🧩重複/妙味tier/危険材料)と
    レース単位判定(荒れ予報%/妙味度/決着タイプ/●大穴)を返す。CSVに結論を同梱するため。

    背景: 外部LLMにCSVを渡す実験(2026-07 七夕賞)で、生特徴量だけだと
    人気内包スコアに引き寄せられ、合議が穴カードで捕捉していた2-3着馬を
    見落とした。結論列を同梱し「どの列が検証済みでどう使うか」を明示する。"""
    cv = load_consensus(race_id)
    if not cv:
        # 合議未計算でも列自体は必ず出す。列ごと消えると受け手(特にLLM)が
        # 「列が無い＝データ破損/添付ミス」と誤読して分析を止めてしまう
        # (2026-08 実例: 合議無しレースのCSVでGPTが分析を拒否)。
        # 『欠落』ではなく『未計算』だと分かる値を入れる。
        na = '(合議未計算)'
        return ({'合議役割': {u: na for u in umabans},
                 '検証シグナル根拠': {u: '' for u in umabans},
                 '🧩シグナル重複数': {u: '' for u in umabans},
                 '妙味馬tier': {u: '' for u in umabans},
                 '危険材料': {u: '' for u in umabans}},
                {'R荒れ予報%': na, 'R妙味度': na, 'R決着タイプ判定': na})
    groups = cv.get('groups') or {}
    role_lbl = {'honmei': '◎本命', 'aite': '〇相手', 'osae': '△押さえ',
                'ana': '🎯穴(検証シグナル)', 'keshi': '✖切る'}
    role_by_um = {}
    for g, lbl in role_lbl.items():
        for u in _ints(groups.get(g)):
            role_by_um[u] = lbl
    aim = cv.get('aim') or {}

    def _imap(key, cast=str):
        out = {}
        for k, x in (aim.get(key) or {}).items():
            try:
                out[int(k)] = cast(x)
            except Exception:
                continue
        return out
    combo = _imap('combo', int)
    vht = _imap('vh_tier')
    dr = {}
    for k, rs in (aim.get('danger_reasons') or {}).items():
        try:
            dr[int(k)] = '・'.join(str(x) for x in (rs or []))
        except Exception:
            continue
    er = {}
    for k, rs in (aim.get('edge_reasons') or {}).items():
        try:
            er[int(k)] = '・'.join(str(x) for x in (rs or []))
        except Exception:
            continue
    per_horse = {
        '合議役割': {u: role_by_um.get(u, '') for u in umabans},
        '検証シグナル根拠': {u: er.get(u, '') for u in umabans},
        '🧩シグナル重複数': {u: combo.get(u, 0) for u in umabans},
        '妙味馬tier': {u: vht.get(u, '') for u in umabans},
        '危険材料': {u: dr.get(u, '') for u in umabans},
    }
    fc = cv.get('forecast') or {}
    race_level = {}
    if fc.get('arare_prob') is not None:
        race_level['R荒れ予報%'] = round(float(fc['arare_prob']) * 100)
    if fc.get('value_label'):
        race_level['R妙味度'] = str(fc['value_label'])
    if cv.get('regime'):
        race_level['R決着タイプ判定'] = str(cv['regime'])
    if fc.get('no_fav'):
        race_level['R本命不在'] = str(fc['no_fav'])
    return per_horse, race_level


def build_csv_bytes(race_id):
    """view表示列 + 合議の結論列(役割/🧩/危険材料/レース判定) + full.json全列を1枚のCSVに。

    戻り値: (bytes, 行数, 列数) / データ無しは (None, 0, 0)。
    """
    import pandas as pd
    v = load_view(race_id)
    full = _read_full(race_id)

    df_v = None
    if v and v.get('source') == 'view':
        df_v = pd.DataFrame(v['records'], columns=v['columns'])
    df_f = None
    if full and full.get('records'):
        df_f = pd.DataFrame(full['records'], columns=full.get('columns'))
        for c in df_f.columns:
            df_f[c] = df_f[c].apply(
                lambda x: json.dumps(x, ensure_ascii=False, default=str)
                if isinstance(x, (list, dict)) else x)

    if df_v is not None and df_f is not None and 'Umaban' in df_v.columns and 'Umaban' in df_f.columns:
        extra = [c for c in df_f.columns if c not in df_v.columns]
        try:
            df_v = df_v.copy()
            df_v['_um'] = pd.to_numeric(df_v['Umaban'], errors='coerce')
            df_f = df_f.copy()
            df_f['_um'] = pd.to_numeric(df_f['Umaban'], errors='coerce')
            out = df_v.merge(df_f[['_um'] + extra], on='_um', how='left').drop(columns=['_um'])
        except Exception:
            out = df_v
    else:
        out = df_v if df_v is not None else df_f
    if out is None or out.empty:
        return None, 0, 0
    # 合議の結論列＋レース単位判定を同梱(cv.jsonが無い過去レースはスキップ)
    try:
        _ums = [int(x) if x == x else -1
                for x in pd.to_numeric(out['Umaban'], errors='coerce')]
        per_horse, race_level = _consensus_csv_cols(race_id, [u for u in _ums if u > 0])
        _ins = min(len(out.columns), 6)   # 馬名近くの読みやすい位置に挿入
        for cname in reversed(list(per_horse.keys())):
            out.insert(_ins, cname, [per_horse[cname].get(u, '') for u in _ums])
        # レース単位の判定は末尾でなく先頭付近に置く。100列目付近にあると
        # CSVを途中までしか読まない受け手に丸ごと見落とされる。
        for cname in reversed(list(race_level.keys())):
            val = race_level[cname]
            if cname in out.columns:
                out.drop(columns=[cname], inplace=True)
            out.insert(_ins, cname, [val] * len(out))
    except Exception:
        pass
    csv = out.to_csv(index=False).encode('utf-8-sig')
    return csv, len(out), len(out.columns)


CSV_DATA_DICTIONARY = """# データ辞書 — レース全情報CSVの読み方(LLM/分析者向け)
このCSVは競馬予想アプリ「強適」の1レース分エクスポートです。列は【結論】【検証済みシグナル】【参考指標】【生データ】に分かれます。
バックテスト(JRA 2016-2025・リーク無し・holdout検証)で有効性を確認した列とそうでない列を区別してください。

## まず見る列（アプリの結論・検証済み合議）
- 合議役割: ◎本命/〇相手/△押さえ/🎯穴(検証シグナル)/✖切る。検証済みエッジの合議結果(votes=3で複勝率27% vs ベース9.4%)。🎯穴は複数シグナル一致の人気薄=複勝・ワイド・3連複の相手向き。✖切るは消去クロス重複3+（強材料馬は自動で穴へ救済済み）。
- R荒れ予報%: 検証済みオッズロジット(AUC0.69)による「7番人気以下が3着内に入る」確率。60%超は人気薄を厚めに。
- R妙味度 / R決着タイプ判定: S〜D(荒れ配当妙味) / ②穴妙味向き=人気-穴-穴型が出やすい・本線向き=人気上位で決まりやすい。
- 危険材料: 検証済みの危険人気馬シグナル(ガラス人気馬/牝×冬春/断層直下等)。該当馬を「軸」にするのは避ける(複勝残差-5pp級)。ただし来る確率も45-60%残るので「消し」でなく「軸回避」が正しい使い方。
- 🧩シグナル重複数: 検証済み6シグナル(補正T/血統/血統回収/騎手力/33ラップ/末脚)の同時発火数。人気薄で2+なら複勝率が単調上昇(0個4.1%→4個18.8%)。

## 帯限定で有効な列（使い方を間違えると逆効果）
- CorrectedT(補正T): 過去走ベスト補正タイム。🔵=レース内top3。人気上位の「本命補強」に有効(+5pp)。人気薄には弱い(+1pp)。
- SpurtIdx(末脚指数): 習性の上がり3F偏差。🔥=6番人気以下×末脚上位で単勝回収≈111%(検証済)。人気上位では効果なし(織込み済)。
- Lap33: 33ラップ適合。人気薄(6+)×適合のみ有効(複勝残差+0.9pp)。
- Trainer末尾の🔴: 厩舎の当コース勝率≥20%のみ妙味(検証済)。全体勝率A-Dランクは市場織込み済。
- BloodStats: 父×今回条件の複勝率/回収率。回収率100%+🔥は荒れ時に注目(holdout z+6.4)。

## 市場情報を内包する列（人気とほぼ同じ動きをする点に注意）
- Projected Score: 総合戦闘力+ボーナス。ボーナスの主成分は人気(+150〜0の線形)。**この列に頼る=人気に頼るのと近い**。
- LTR: 検証AI(LambdaRank recall@7最適化)。オッズを特徴に含むため市場情報を内包。「勝ち馬を上位7頭に含める」網羅用で、序列の妙味判定には使わない。
- BattleScore/NIndex/SpeedIndex等の能力指数: 参考。市場とほぼ相関。

## 生データの注意(PastRuns列)
- PastRuns内の Popularity:99 は「未取得」のプレースホルダ(実人気ではない)。
- TimeIndexRank は常に1が入るプレースホルダ。Grade表記は不正確な場合がある。
- Passing(通過順)のPassingType:"Imputed"は推定値。

## 検証で否定済みの俗説（このデータから再発見しても採用しないこと）
展開有利/脚質/マクリ/PCI乖離/前走着差/圧勝の軸外し/巻き返し/斤量変化/コース適性(血統×コース)/馬主/騎手連敗——いずれも市場に織込み済み(残差≈0)と大規模検証済み。もっともらしく見えても回収率は改善しない。
"""


def csv_data_dictionary():
    """CSVに同梱するデータ辞書(LLM/外部分析者向けの列説明)を返す。"""
    return CSV_DATA_DICTIONARY


# ────────────────────────────────────────────────────────────
# HTML組版
# ────────────────────────────────────────────────────────────

def _esc(v):
    return _htmlesc.escape(str(v), quote=True)


def _fmt_cell(v, max_chars=0):
    if v is None:
        return ''
    if isinstance(v, float):
        s = f"{int(v)}" if float(v).is_integer() else f"{v:.1f}"
    else:
        s = str(v)
    s = s.replace('\n', ' / ')
    if max_chars and len(s) > max_chars:
        s = s[:max_chars - 1] + '…'
    return _esc(s)


# 列見出しの整形。エスケープ後の見出し文字列に対して needle→replacement を適用する
# (needleを含む時だけ発火)。<br>挿入(折り返し)と、不要アイコンの除去の両方を担う。
_HDR_WRAP = [
    ('⭐展開適合度', '⭐展開<br>適合度'),
    ('🔥総合戦闘力', '🔥総合<br>戦闘力'),
    ('🔵補正T', '🔵<br>補正T'),
    ('🏇騎手力', '騎手力'),          # 🏇アイコンは列が狭いので除去(乗替は見出し文言で分かる)
]


def _header_cell(label):
    """見出しHTML。指定の見出しは折り返し<br>挿入やアイコン除去を行う(それ以外は素通し)。"""
    s = _esc(str(label))
    for needle, rep in _HDR_WRAP:
        s = s.replace(_esc(needle), rep)
    return s


def _col_slug(c):
    """列キー→CSSクラス名(col-XXX)。空白/記号を _ に畳む。"""
    import re as _re_cs
    return 'col-' + _re_cs.sub(r'[^A-Za-z0-9]+', '_', str(c)).strip('_')


def _cell_html(c, v, max_chars):
    """セルHTML。狭い列の値を要所で改行する。"""
    s = _fmt_cell(v, max_chars)
    if c == 'JPower' and '(' in s:
        s = s.replace('(', '<br>(', 1)
    elif c == 'JockeyChange' and '→' in s:
        s = s.replace('→', '→<br>', 1)
        s = f"<span style='color:#c33'>{s}</span>"
    # ── NAR独自列のビジュアル強化(色はSRA展開MAPのSTYLE_COLORSに準拠) ──
    elif c == 'Style':
        _sv = str(v or '')
        if _sv == '逃':
            s = f"<span style='color:#fff;background:#E63946;padding:1px 4px;border-radius:3px;font-weight:bold' title='逃げ馬(複勝率52%)'>🏃{s}</span>"
        elif _sv == '先':
            s = f"<span style='color:#F4A261;font-weight:bold' title='先行(複勝率36%)'>{s}</span>"
        elif _sv == '差':
            s = f"<span style='color:#457B9D;font-weight:bold'>{s}</span>"
        elif _sv == '追':
            s = f"<span style='color:#6A4C93;font-weight:bold'>{s}</span>"
    elif c == 'JockeyChange':
        _jc_str = str(v or '')
        if _jc_str == '初騎乗':
            s = f"<span style='color:#c33;font-weight:bold'>⚠{s}</span>"
        elif _jc_str == '乗替':
            s = f"<span style='color:#c33'>🔄{s}</span>"
        elif _jc_str == '継続':
            s = f"<span style='color:#1a5fb4'>✓{s}</span>"
        elif _jc_str == '-':
            s = f"<span style='color:#1a5fb4'>{s}</span>"
    elif c == 'JFactor':
        try:
            _jfv = float(v)
            if _jfv >= 1.2:
                s = f"<span style='color:#fff;background:#2a7;padding:1px 3px;border-radius:3px;font-weight:bold'>{s}</span>"
            elif _jfv >= 1.1:
                s = f"<span style='color:#2a7;font-weight:bold'>{s}</span>"
            elif _jfv <= 0.85:
                s = f"<span style='color:#c33'>{s}</span>"
        except (TypeError, ValueError):
            pass
    elif c == 'BattleScore':
        try:
            _bsv = float(v)
            if _bsv >= 80:
                s = f"<span style='color:#fff;background:#d44;padding:1px 4px;border-radius:3px;font-weight:bold'>◎{s}</span>"
            elif _bsv >= 65:
                s = f"<span style='color:#c55;font-weight:bold'>○{s}</span>"
            elif _bsv >= 50:
                s = f"<span style='font-weight:bold'>▲{s}</span>"
            elif _bsv < 20:
                s = f"<span style='color:#999'>{s}</span>"
        except (TypeError, ValueError):
            pass
    elif c == 'FormIdx':
        try:
            _fiv = float(v)
            if _fiv >= 40:
                s = f"<span style='color:#2a7;font-weight:bold'>{s}</span>"
            elif _fiv >= 25:
                s = f"<span style='font-weight:bold'>{s}</span>"
            elif _fiv < 10:
                s = f"<span style='color:#999'>{s}</span>"
        except (TypeError, ValueError):
            pass
    elif c == 'Bloodline':
        _bl = str(v or '')
        if 'ダ' in _bl:
            s = f"<span style='color:#964B00;font-weight:bold'>{s}</span>"
        elif 'SS' in _bl:
            s = f"<span style='color:#2a5db0'>{s}</span>"
    elif c == 'Weight':
        _wv = str(v or '')
        if _wv.endswith('P'):
            s = s.replace('P', '')
            s = f"<span style='color:#964B00;font-weight:bold' title='穴馬×大型馬(パワー型・人気薄で妙味)'>🐴{s}</span>"
    elif c == 'Trainer':
        _trv = str(v or '')
        if _trv.endswith('E'):
            s = s[:-1] if s.endswith('E') else s
            s = f"<span style='color:#1a6;font-weight:bold' title='遠征馬(穴馬×厩舎が適性を見て送り出し)'>✈{s}</span>"
    elif c == 'Interval':
        try:
            _iv = int(v)
            if _iv <= 7:
                s = f"<span style='font-weight:bold' title='連闘級'>{s}日</span>"
            elif _iv <= 13:
                s = f"<span title='中1-2週'>{s}日</span>"
            else:
                s = f"{s}日"
        except (TypeError, ValueError):
            pass
    elif c == 'OddsGap':
        _ogv = str(v or '')
        if '断層A' in _ogv:
            s = f"<span style='color:#fff;background:#d44;padding:1px 4px;border-radius:3px;font-weight:bold' title='1番人気の前に断層=1強'>{s}</span>"
        elif '断層B' in _ogv:
            s = f"<span style='color:#fff;background:#c55;padding:1px 4px;border-radius:3px;font-weight:bold' title='2番人気の前に断層=2頭強し'>{s}</span>"
        elif '断層D1' in _ogv:
            s = f"<span style='color:#fff;background:#b33;padding:1px 4px;border-radius:3px;font-weight:bold' title='1-2間+2-3間に断層=上位2頭圧倒的'>{s}</span>"
        elif '断層D2' in _ogv:
            s = f"<span style='color:#fff;background:#b33;padding:1px 4px;border-radius:3px;font-weight:bold' title='2-3間+3-4間に断層'>{s}</span>"
        elif '断層C' in _ogv or '断層D' in _ogv:
            s = f"<span style='color:#c55;font-weight:bold'>{s}</span>"
    elif c == 'SpurtIdx':
        _siv = str(v or '')
        if '🔥' in _siv:
            s = f"<span style='color:#d44;font-weight:bold' title='レース内の末脚上位3頭(人気薄なら妙味あり)'>{s}</span>"
        elif _siv.startswith('-') and _siv != '-':
            s = f"<span style='color:#999'>{s}</span>"
    elif c == 'LTR':
        try:
            _lv = int(v)
            if _lv >= 80:
                s = f"<span style='color:#fff;background:#2a7;padding:1px 4px;border-radius:3px;font-weight:bold'>{s}</span>"
            elif _lv >= 60:
                s = f"<span style='color:#2a7;font-weight:bold'>{s}</span>"
            elif _lv <= 20:
                s = f"<span style='color:#999'>{s}</span>"
        except (TypeError, ValueError):
            pass
    return s


def _pop_int(v):
    m = re.search(r'\d+', str(v or ''))
    return int(m.group()) if m else 999


# 強適テーブル専用で紙面に出さない列。発行の列チェックはOFFのまま。
HIDE_ON_PAPER = frozenset({'GyakuShocker'})

DEFAULT_OPTS = {
    'title': '強適競馬新聞',
    'subtitle': '',
    'orientation': 'landscape',   # landscape / portrait
    'scale': 1.0,
    'font_pt': 6.8,
    'row_order': 'app',           # app / umaban / pop
    'col_mode': 'app',            # app(アプリ表示列) / all(全列) / lite(軽量)
    'exclude_cols': ['GyakuShocker'],
    'cell_max': 46,
    'page_per_race': True,
    'keep_table': True,
    'mono': False,
    'sections': {'cover': True, 'consensus': True, 'buymeta': True, 'gate': True,
                 'header_plus': True, 'bets': True, 'pace': True,
                 'elim': True, 'vh': True, 'odds_moves': True,
                 'evidence': True, 'pci': True, 'pace_upset': True, 'stress': True,
                 'alerts': True,
                 'j5': False,     # 騎手係数込みスコア(既定OFF・チェックで紙面に追加)
                 'dev_thoughts': True,   # 開発者の思考プロセス(既定ON・差別化の核)
                 'ai_commentary': False,  # AIコメント欄(既定OFF・課金が発生するため)
                 'value_zone': True,    # 複勝率×回収率マップ(テーブル形式・既定ON)
                 'value_zone_chart': False},  # 同内容の散布図版(ZONEシート・既定OFF・空きスペース埋め用)
    'bet_types': {'trio': True, 'trifecta': True, 'quinella': True,
                  'exacta': True, 'wide': True},  # おすすめ買い目セクション内の券種別ON/OFF
    'footer_text': '',
    'page_numbers': True,
    'custom_cols': [],
}

_LITE_PREF = ['Rank', 'AxisMark', 'Umaban', 'Waku', 'Name', 'SexAge', 'WeightCarried',
              'Jockey', 'Trainer', 'Odds', 'Popularity', 'OddsGap',
              'Projected Score', 'LTR', 'BattleScore', 'Strength (X)', 'Suitability (Y)',
              'NIndex', 'AvgAgari', 'Signal', 'Alert']

_CARD_DEFS = [('honmei', '① 本命', '#f0a020'), ('aite', '② 相手候補', '#12a594'),
              ('osae', '③ 押さえ', '#607d8b'), ('ana', '④ 穴・妙味', '#9c27b0'),
              ('keshi', '✖ 切る', '#9e9e9e')]


def _pick_columns(view, opts):
    cols_all = view.get('columns') or []
    mode = opts.get('col_mode', 'app')
    if mode == 'app' and view.get('order'):
        cols = [c for c in view['order'] if c in cols_all]
        if not cols:
            cols = cols_all
    elif mode == 'lite':
        cols = [c for c in _LITE_PREF if c in cols_all]
        if not cols:
            cols = cols_all
    elif mode == 'custom':
        # チェック式で選んだ列(チェック順=紙面順)。未選択/全滅時はアプリ表示列へフォールバック
        cols = [c for c in (opts.get('custom_cols') or []) if c in cols_all]
        if not cols:
            cols = [c for c in (view.get('order') or []) if c in cols_all] or list(cols_all)
    else:
        cols = list(cols_all)
    excl = set(opts.get('exclude_cols') or [])
    # 逆シ(GyakuShocker)は強適テーブル専用。紙面には出さない（チェックOFF固定）。
    excl.update(HIDE_ON_PAPER)
    cols = [c for c in cols if c not in excl]
    # レース列(全行同値)は紙面ヘッダーに出すので表からは省く
    for c in ('RaceID', 'RaceName', 'RaceDate', 'Venue', 'CurrentDistance', 'CurrentSurface'):
        if c in cols:
            cols.remove(c)
    return cols


def _sort_records(records, order_mode):
    if order_mode == 'umaban':
        return sorted(records, key=lambda r: _pop_int(r.get('Umaban')))
    if order_mode == 'pop':
        return sorted(records, key=lambda r: _pop_int(r.get('Popularity')))
    return list(records)


def _names_by_um(records):
    """records → {馬番int: 表示用に整形した馬名}。先頭の🔥等のアイコンは除去。"""
    by_um = {}
    for r in records:
        m = re.search(r'\d+', str(r.get('Umaban', '')))
        if m:
            nm = re.sub(r'^[^ぁ-んァ-ヶ一-龠A-Za-zｱ-ﾝ]*', '', str(r.get('Name', '')).strip())
            by_um[int(m.group())] = nm
    return by_um


def _consensus_html(cv, records, mono=False):
    if not cv:
        return ''
    by_um = _names_by_um(records)
    groups = cv.get('groups') or {}

    def _names(ul):
        parts = []
        for u in (ul or []):
            try:
                u = int(u)
            except Exception:
                continue
            parts.append(f"<b>{u}</b> {_esc(by_um.get(u, '')[:9])}")
        return '　'.join(parts) if parts else '—'

    cards = []
    for key, ttl, col in _CARD_DEFS:
        ul = groups.get(key) or []
        if key == 'keshi' and not ul:
            continue
        c = '#555' if mono else col
        cards.append(
            f"<div class='cvcard' style='border-top:3px solid {c};'>"
            f"<div class='cvttl' style='color:{c};'>{_esc(ttl)}</div>"
            f"<div class='cvbody'>{_names(ul)}</div></div>")
    return f"<div class='cvrow'>{''.join(cards)}</div>"


def _digest_html(cv, records, meta, mono=False):
    """レースダイジェスト — 馬柱の前に合議の要約を大きく視覚的に表示。"""
    if not cv:
        return ''
    groups = cv.get('groups') or {}
    aim = cv.get('aim') or {}
    forecast = cv.get('forecast') or {}
    by_um = _names_by_um(records)

    def _stars(score):
        try:
            s = float(score)
        except (TypeError, ValueError):
            return ''
        n = min(5, max(0, round(s / 20)))
        return '★' * n + '☆' * (5 - n)

    def _score_of(umaban):
        for r in records:
            try:
                if int(r.get('Umaban', -1)) == umaban:
                    return r.get('BattleScore') or r.get('FormIdx') or 0
            except (TypeError, ValueError):
                continue
        return 0

    def _edge_text(um):
        a = aim.get(str(um)) or {}
        reasons = []
        for _k in ('edge_reasons', 'danger_reasons'):
            d = a.get(_k) or {}
            for vs in d.values():
                reasons.extend(vs)
        return '／'.join(reasons[:3]) if reasons else ''

    rows = []
    # 記号を重ねすぎない: 以前は『★穴』の★(役割)と★★★★☆(点数)で同じ記号が
    # 別の意味に使われていて紛らわしかったため、役割側の★を外した。
    marks = [('honmei', '◎', '#f0a020'), ('aite', '○', '#12a594'),
             ('osae', '▲', '#607d8b'), ('ana', '穴', '#9c27b0')]
    for key, mark, col in marks:
        ul = groups.get(key) or []
        for u in ul:
            try:
                u = int(u)
            except (TypeError, ValueError):
                continue
            sc = _score_of(u)
            name = strip_name_deco(by_um.get(u, ''), 8)
            edge = _edge_text(u)
            c = '#555' if mono else col
            # 馬番は丸数字(⑦)でなく素の数字。総合点は★ゲージでなく数値にする。
            try:
                _sc_disp = f"{float(sc):.0f}点"
            except (TypeError, ValueError):
                _sc_disp = ''
            rows.append(
                f"<tr><td style='color:{c};font-weight:bold;font-size:1.1em;'>{mark}</td>"
                f"<td style='font-weight:bold;font-size:1.1em;text-align:right;"
                f"padding-right:6px;'>{u}</td>"
                f"<td style='font-weight:bold;'>{_esc(name)}</td>"
                f"<td style='color:{c};font-weight:bold;'>{_sc_disp}</td>"
                f"<td style='font-size:0.85em;color:#666;'>{_esc(edge)}</td></tr>")

    arare_prob = forecast.get('arare_prob')
    arare_line = ''
    if arare_prob is not None:
        pct = int(arare_prob * 100)
        _lv = '高め' if pct >= 60 else ('ふつう' if pct >= 40 else '低め')
        arare_line = (f"<div style='margin-top:6px;font-size:0.95em;'>"
                      f"波乱度 <b>{_lv}</b>（荒れ予報 {pct}%）</div>")
    pace = meta.get('pace_prediction') or {}
    pace_line = ''
    if pace.get('pace'):
        pace_line = (f"<div style='font-size:0.95em;'>"
                     f"展開 {_esc(pace['pace'])}"
                     f"{'(' + _esc(pace.get('comment', '')) + ')' if pace.get('comment') else ''}"
                     f"</div>")

    if not rows:
        return ''
    return (
        f"<div class='digest' style='border:2px solid {'#888' if mono else '#f0a020'};"
        f"border-radius:8px;padding:8px 12px;margin:6px 0;'>"
        f"<div style='font-weight:bold;font-size:1.0em;margin-bottom:4px;'>このレースは…</div>"
        f"<table style='border-collapse:collapse;width:100%;'>{''.join(rows)}</table>"
        f"{pace_line}{arare_line}</div>")


def _diag_family_code(race_id):
    """紙面ヘッダ用の型コード(NNV/RRV/RRR)。買い目の形ではなく診断ラベル。無ければNone。"""
    extra, meta = {}, {}
    try:
        data = load_bets(race_id) or {}
        pb = data.get('playbook') or {}
        extra = pb.get('extra') or {}
        meta = (pb.get('result') or {}).get('meta') or {}
    except Exception:
        extra, meta = {}, {}
    if not extra and not meta:
        try:
            v = load_view(race_id) or {}
            pb = v.get('playbook') or {}
            extra = pb.get('extra') or {}
            meta = (pb.get('result') or {}).get('meta') or extra
        except Exception:
            extra, meta = {}, {}
    code = extra.get('diag_family') or meta.get('diag_family')
    if code:
        return str(code)
    zone = extra.get('zone') or meta.get('zone')
    cross_n = extra.get('cross_n')
    if cross_n is None:
        cross_n = meta.get('cross_n')
    if zone is None or cross_n is None:
        try:
            cv = load_consensus(race_id) or {}
        except Exception:
            cv = {}
        if zone is None:
            vs = (cv.get('forecast') or {}).get('value_score')
            if vs is not None:
                try:
                    from core import formation_stats as _fs
                    zone = _fs.zone_code(vs)
                except Exception:
                    zone = None
        if cross_n is None:
            cross_n = (cv.get('cross') or {}).get('n')
    if not zone:
        return None
    try:
        from core.bettype_selector import diag_family
        return diag_family(zone, cross_n).get('code')
    except Exception:
        return None


def _buymeta_html(race_id, show_gate=True, show_buy=True):
    try:
        from core import score_cache as sc
    except Exception:
        return '', ''
    badge = ''
    if show_gate:
        # 型(NNV/RRV/RRR)はスキャナGateと独立。SRAだけ済ませた紙面でも黒帯右に出す。
        parts = []
        g = sc.read_gate(race_id)
        if g and g.get('status'):
            lbl = {'buy': '🟢 買い', 'axis_warn': '🟡 軸注意', 'skip': '⛔ 見送り'}.get(
                g['status'], g['status'])
            parts.append(lbl)
            if g.get('lean'):
                parts.append(str(g['lean']))
        fam = _diag_family_code(race_id)
        if fam:
            parts.append(str(fam))
        fam_plain = {'NNV': '人気＋穴', 'RRV': '能力＋穴', 'RRR': '能力のみ'}.get(fam or '', '')
        title = (f"型{fam}＝{fam_plain}（どの判定パターンに入ったか。券の形そのものではない）"
                 if fam else '')
        if parts:
            badge = (f"<span class='gate' title='{_esc(title)}'>"
                     f"{_esc('｜'.join(parts))}</span>")
    meta_line = ''
    if show_buy:
        b = sc.read_buy(race_id)
        parts = []
        if b:
            if b.get('n_points'):
                parts.append(f"買い目 {b['n_points']}点")
            if b.get('synth_odds'):
                try:
                    parts.append(f"合成オッズ {float(b['synth_odds']):.1f}倍")
                except Exception:
                    pass
            if b.get('has_danger'):
                parts.append("⚠危険人気馬を含む")
        keep = sc.read_keep(race_id)
        if keep:
            parts.append("🧹残し馬 " + '・'.join(str(u) for u in sorted(keep)))
        if parts:
            meta_line = "<div class='buymeta'>" + "　／　".join(_esc(p) for p in parts) + "</div>"
    return badge, meta_line


def _hbox(title, body):
    return (f"<div class='hbox'><b class='t'>{_esc(title)}</b>{body}</div>") if body else ''


def _exbox(title, body):
    return (f"<div class='exbox'><span class='exttl'>{_esc(title)}</span>{body}</div>") if body else ''


def _ints(seq):
    out = []
    for x in (seq or []):
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _header_plus_html(cv, view, race_id):
    """予想ヘッダー強化: 荒れ予報/妙味度/決着タイプ/軸候補◎〇▲+複勝信頼度/危険人気馬警告。"""
    records = view.get('records') or []
    by_um = _names_by_um(records)
    boxes = []
    # ── 荒れ予報/妙味度(SRA保存値を優先・無ければ紙面時に純関数で再計算) ──
    fc = dict((cv or {}).get('forecast') or {})
    if not fc:
        odds = []
        for r in records:
            m = re.search(r'\d+(?:\.\d+)?', str(r.get('Odds', '')))
            if m:
                odds.append(float(m.group()))
        meta = view.get('meta') or {}
        try:
            dist = int(float(meta.get('distance')))
        except Exception:
            dist = None
        fc = _forecast_from_odds(odds, {}, race_id, str(meta.get('surface') or ''), dist)
    parts = []
    if fc.get('arare_prob') is not None:
        parts.append(f"荒れ予報 <b>{float(fc['arare_prob']) * 100:.0f}%</b>")
    if fc.get('value_label'):
        sc_txt = f"({fc.get('value_score')})" if fc.get('value_score') is not None else ''
        parts.append(f"妙味度 <b>{_esc(fc['value_label'])}</b>{_esc(sc_txt)}")
    if fc.get('no_fav'):
        parts.append(f"<b>{_esc(fc['no_fav'])}</b>(本命不在)")
    regime = (cv or {}).get('regime')
    if regime:
        parts.append(f"決着 <b>{_esc(regime)}</b>")
    if parts:
        boxes.append(_hbox('🎲 レース性質', '　'.join(parts)))
    # ── 軸候補◎〇▲＋複勝信頼度(オッズ実複勝率・検証済) ──
    horses = (cv or {}).get('horses') or []
    axs = [h for h in horses if h.get('axis_mark')]
    if axs:
        try:
            from core import axis_selector as ax
            try:
                is_nar = int(str(race_id)[4:6]) > 10
            except Exception:
                is_nar = False
            _order = {'◎': 0, '〇': 1, '○': 1, '▲': 2}
            items = []
            for h in sorted(axs, key=lambda h: _order.get(str(h.get('axis_mark'))[:1], 9)):
                try:
                    u = int(h.get('umaban'))
                except Exception:
                    continue
                pop = h.get('pop')
                conf = (ax.axis_confidence_nar(pop) if is_nar
                        else ax.axis_confidence(pop, h.get('odds')))
                ctx = f"(複{conf:.0f}%)" if conf is not None else ''
                items.append(f"<b>{_esc(str(h.get('axis_mark')))}{u}</b> "
                             f"{_esc(by_um.get(u, str(h.get('name', '')))[:9])}{_esc(ctx)}")
            if items:
                boxes.append(_hbox('🎯 軸候補', '　'.join(items)))
        except Exception:
            pass
    # ── 危険人気馬警告(danger_gate/検証済アンチ市場) ──
    aim = (cv or {}).get('aim') or {}
    veto = set(_ints(aim.get('veto')))
    danger = set(_ints(aim.get('danger'))) | veto
    if danger:
        dr = aim.get('danger_reasons') or {}
        items = []
        for u in sorted(danger):
            rs = [str(x) for x in (dr.get(str(u)) or dr.get(u) or [])][:2]
            rtxt = f"〈{'/'.join(rs)}〉" if rs else ''
            mark = '🚫' if u in veto else '⚠'
            items.append(f"<b>{mark}{u}</b> {_esc(by_um.get(u, '')[:9])}{_esc(rtxt)}")
        boxes.append(_hbox('⚠ 危険人気馬', '　'.join(items)))
    return f"<div class='hplus'>{''.join(boxes)}</div>" if boxes else ''


def _fmt_bet_list(bets, arrow=False, cap=36):
    out = []
    for b in (bets or [])[:cap]:
        c = b.get('combo') or []
        s = ('→' if arrow else '-').join(str(x) for x in c)
        o = b.get('odds')
        try:
            o = float(o)
            s += f"({o:.0f}倍)" if o >= 10 else f"({o:.1f}倍)"
        except (TypeError, ValueError):
            pass
        if str(b.get('aim_tag') or '') == '🎯':
            s = '🎯' + s
        out.append(_esc(s))
    more = len(bets or []) - cap
    if more > 0:
        out.append(_esc(f"…他{more}点"))
    return ' / '.join(out)


def _bets_html(race_id, bet_types=None):
    """SRAで生成した買い目スナップショットを紙面化。
    先頭は検証済み『推奨買い方』(playbook)。旧エンジンは手動・参考として続ける。
    """
    data = load_bets(race_id) or {}
    if not data.get('playbook'):
        v = None
        try:
            v = load_view(race_id)
        except Exception:
            v = None
        if v and v.get('playbook'):
            data = dict(data)
            data['playbook'] = v['playbook']
    if not data:
        return ''
    bt = dict(DEFAULT_OPTS['bet_types'])
    bt.update(bet_types or {})
    boxes = []
    pb = data.get('playbook') or {}
    pb_res = pb.get('result') or {}
    pb_meta = (pb_res.get('meta') or {})
    if not pb_meta:
        pb_meta = pb.get('extra') or {}
    pb_bets = pb_res.get('bets')
    if pb_meta.get('ui_line') or pb_meta.get('skip') or pb_bets is not None:
        line = pb_meta.get('ui_line') or '推奨買い方'
        if pb_meta.get('skip') or str(pb_meta.get('zone') or '') == 'BA':
            boxes.append(_exbox(
                f"推奨買い方 {line}",
                'デフォルト買い目なし（見送り）。下の🎯は手動・参考です。'))
        elif isinstance(pb_bets, dict):
            parts = []
            t = _fmt_bet_list(pb_bets.get('trio'))
            f = _fmt_bet_list(pb_bets.get('trifecta'), arrow=True)
            if t:
                parts.append('3連複: ' + t)
            if f:
                parts.append('3連単: ' + f)
            n = pb_meta.get('n_points', 0)
            if parts:
                boxes.append(_exbox(
                    f"推奨買い方 {line}（{n}点）",
                    '<br>'.join(parts)))
            elif n == 0:
                boxes.append(_exbox(
                    f"推奨買い方 {line}",
                    'デフォルト買い目なし（見送り）。下の🎯は手動・参考です。'))
    if bt.get('trio'):
        d = (data.get('trio') or {})
        bets = (d.get('result') or {}).get('bets')
        if bets:
            pat = (d.get('extra') or {}).get('pattern') or ''
            boxes.append(_exbox(
                f"🎯 3連複おすすめ（手動・参考{'・'+pat if pat else ''}・{len(bets)}点）",
                _fmt_bet_list(bets)))
    if bt.get('trifecta'):
        d = (data.get('trifecta') or {})
        bets = (d.get('result') or {}).get('bets')
        if bets:
            band = ((d.get('result') or {}).get('meta') or {}).get('band_name') or ''
            band_j = {'tight': '堅', 'mid': '中波乱', 'arare': '荒れ'}.get(band, band)
            ttl = (f"🎯 3連単おすすめ（手動・参考・{len(bets)}点"
                   + (f"・{band_j}帯" if band_j else '') + "）")
            boxes.append(_exbox(ttl, _fmt_bet_list(bets, arrow=True)))
    if bt.get('quinella') or bt.get('exacta'):
        d = (data.get('qe') or {})
        res = d.get('result') or {}
        q_txt = _fmt_bet_list(res.get('quinella')) if bt.get('quinella') else ''
        e_txt = _fmt_bet_list(res.get('exacta'), arrow=True) if bt.get('exacta') else ''
        if q_txt or e_txt:
            body = (f"馬連: {q_txt}" if q_txt else '') + ('<br>' if q_txt and e_txt else '') \
                 + (f"馬単: {e_txt}" if e_txt else '')
            if q_txt and e_txt:
                ttl = "🎯 馬連/馬単おすすめ"
            elif q_txt:
                ttl = "🎯 馬連おすすめ"
            else:
                ttl = "🎯 馬単おすすめ"
            boxes.append(_exbox(ttl, body))
    if bt.get('wide'):
        d = (data.get('wide') or {})
        res = d.get('result') or {}
        w_txt = _fmt_bet_list(res.get('wide'))
        if w_txt:
            ax_txt = f"軸{res.get('axis')}番・" if res.get('axis') else ''
            boxes.append(_exbox(f"🎯 ワイドおすすめ（{ax_txt}厳選3点）", w_txt))
    return ''.join(boxes)


def _rear_group_threshold(disp, n):
    """disp(0=前〜1=後)の値から『後方n頭』の境界値を計算する。
    後ろからn番目とn+1番目の値の中間に境界線を引く(表示専用・判定ロジックの追加ではない)。"""
    if not disp or not n or n <= 0 or n >= len(disp):
        return None
    vals = sorted(disp.values())
    idx = len(vals) - n
    if idx <= 0:
        return max(0.0, vals[0] - 0.03)
    return (vals[idx - 1] + vals[idx]) / 2.0


def _pace_diagram_svg(pos4, labels=None, marker=None):
    """展開・隊列レーン図(静的SVG)。{umaban: 0(先頭/1着想定)〜1(最後方)}の値を
    そのまま横軸に並べる表示専用の視覚化で、新しい予測ロジックは追加しない
    (verified_tenkai_priced_in)。呼び元は4角位置(pos4)/直線到達想定(finish)を渡す。
    marker: 任意で(value, text)を渡すと、その位置(0=前〜1=後)に縦の破線+ラベルを重ねる
    (例:『後方N頭』の境界線=AI展開照合/展開MAPの後方グループ件数から算出)。"""
    if not pos4:
        return ''
    labels = labels or {}
    try:
        items = sorted(
            ((int(u), max(0.0, min(1.0, float(v)))) for u, v in pos4.items()),
            key=lambda t: t[1]
        )
    except Exception:
        return ''
    if not items:
        return ''
    w, margin_x, row_gap, thresh = 600, 30, 32, 28
    lane_w = w - 2 * margin_x
    zigzag = [0]
    for k in range(1, max(10, len(items))):
        zigzag += [k, -k]
    placed = []
    xy = {}
    for um, v in items:
        x = margin_x + (1.0 - v) * lane_w   # 前(0)を右・後(1)を左に配置(PCの並び順に合わせる)
        row = zigzag[-1]
        for r in zigzag:
            if all(abs(x - px) >= thresh for px, pr in placed if pr == r):
                row = r
                break
        placed.append((x, row))
        xy[um] = (x, row)
    max_row = max((abs(r) for _, r in placed), default=0)
    h = 60 + max_row * row_gap * 2
    cy = h / 2
    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
             f'style="width:100%;height:auto;display:block;margin:1mm 0;">']
    parts.append(f'<line x1="{margin_x}" y1="{cy:.1f}" x2="{w - margin_x}" y2="{cy:.1f}" '
                 f'stroke="#bbb" stroke-width="1.5" stroke-dasharray="4,3"/>')
    parts.append(f'<text x="2" y="{cy:.1f}" font-size="13" fill="#777" '
                 f'dominant-baseline="middle">後</text>')
    parts.append(f'<text x="{w - 16}" y="{cy:.1f}" font-size="13" fill="#777" '
                 f'dominant-baseline="middle">前</text>')
    if marker:
        mv, mtext = marker[0], marker[1]
        try:
            mv = max(0.0, min(1.0, float(mv)))
        except Exception:
            mv = None
        if mv is not None:
            mx = margin_x + (1.0 - mv) * lane_w
            parts.append(f'<line x1="{mx:.1f}" y1="8" x2="{mx:.1f}" y2="{h - 8}" '
                         f'stroke="#7048e8" stroke-width="1.3" stroke-dasharray="4,3"/>')
            parts.append(f'<text x="{mx:.1f}" y="11" font-size="10" fill="#7048e8" '
                         f'text-anchor="middle" font-weight="700">{_esc(mtext)}</text>')
    for um, (x, row) in xy.items():
        y = cy + row * row_gap
        nm = _esc(str(labels.get(um, '')))[:8]
        title = f'{um}番 {nm}' if nm else f'{um}番'
        parts.append(
            f'<g><title>{title}</title>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="13" fill="#fff" stroke="#333" stroke-width="1.3"/>'
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="12" fill="#111" text-anchor="middle" '
            f'dominant-baseline="middle" font-weight="700">{um}</text></g>'
        )
    parts.append('</svg>')
    return ''.join(parts)


def _pace_html(race_id, records):
    """展開・隊列: 直線到達(到達=着順)想定の1行図＋レーン図(SVG)＋ペース＋AI展開照合💀。
    直線到達(finish)は4角位置+決め手+適性+総合力+人気の合成(pace_map.predict_finish)。
    旧スナップショット(finish未保存)は4角位置(pos4)にフォールバックする。"""
    pc = load_pace(race_id)
    rear = None
    try:
        from core import score_cache as sc
        rear = sc.read_rear(race_id)
    except Exception:
        pass
    if not pc and not rear:
        return ''
    lines = []
    disp = {}
    if pc:
        finish, pos4 = {}, {}
        for k, v in (pc.get('finish') or {}).items():
            try:
                finish[int(k)] = float(v)
            except Exception:
                continue
        for k, v in (pc.get('pos4') or {}).items():
            try:
                pos4[int(k)] = float(v)
            except Exception:
                continue
        disp = finish or pos4
        disp_label = "《直線到達想定》" if finish else "《4角想定》"
        if disp:
            ordered = sorted(disp.items(), key=lambda kv: kv[1])
            front = [str(u) for u, v in ordered if v < 0.35]
            mid = [str(u) for u, v in ordered if 0.35 <= v <= 0.65]
            back = [str(u) for u, v in ordered if v > 0.65]
            lines.append(f"{disp_label}(前) " + ' '.join(front) + " ｜ " + ' '.join(mid)
                         + " ｜ " + ' '.join(back) + " (後)")
        meta_p = []
        if pc.get('pace'):
            meta_p.append(f"ペース想定: {pc['pace']}")
        if pc.get('leader') is not None:
            _ldu = None
            try:
                _ldu = int(pc['leader'])
            except Exception:
                pass
            _ldn = _names_by_um(records).get(_ldu, '') if _ldu is not None else ''
            meta_p.append(f"ハナ予想: {pc['leader']}番{_ldn[:8]}")
        if pc.get('front_ratio') is not None:
            try:
                meta_p.append(f"前向き率: {float(pc['front_ratio']) * 100:.0f}%")
            except Exception:
                pass
        nige = _ints(pc.get('nige'))
        if nige:
            meta_p.append("逃げ型: " + '・'.join(str(u) for u in nige))
        if pc.get('contested'):
            meta_p.append("⚔ハナ争い(前崩れ警戒)")
        if meta_p:
            lines.append('　'.join(meta_p))
    by_um = _names_by_um(records)
    rear_group = None
    # 後方グループは**必ず自前の展開MAP**を使う。
    # 以前は🤝netkeiba AI展開予測との照合結果(score_cache.read_tenkai_danger)があれば
    # 「💀AI展開照合=両AIが後方帯で合意」に差し替えていたが、紙面は配布物なので
    # 他社(netkeiba)の予測に依存する行を載せない方針にした(2026-07-23)。
    # ・アプリ内の🤝照合表示は私的利用のため従来どおり残す(app.py側は変更なし)
    # ・展開恩恵はpriced-in([[verified_tenkai_priced_in]])で紙面価値への寄与も乏しい
    if rear:
        lines.append("後方グループ(展開MAP): " + '・'.join(str(u) for u in sorted(rear)))
        rear_group = rear
    if not lines:
        return ''
    body = '<br>'.join(_esc(x) for x in lines)
    marker = None
    if disp and rear_group:
        n_rear = len(rear_group)
        th = _rear_group_threshold(disp, n_rear)
        if th is not None:
            marker = (th, f"後方{n_rear}頭")
    diagram = _pace_diagram_svg(disp, by_um, marker) if disp else ''
    if diagram:
        body += diagram
    return _exbox("🗺 展開・隊列", body)


def _elim_html(cv, records, race_id):
    """既存の消去欄を自動消去後の残馬一覧に置換する（手動選択とは分離）。"""
    verdict = load_elim_verdict(race_id)
    by_um = _names_by_um(records)
    keep_names = {}
    rows = (verdict or {}).get('rows') or []
    if rows:
        for r in rows:
            if r.get('判定') not in ('✅残し', '🛟ボーダー残し'):
                continue
            try:
                u = int(r['馬番'])
            except (KeyError, TypeError, ValueError):
                continue
            keep_names[u] = str(r.get('馬名') or by_um.get(u, ''))
    else:
        # 旧保存形式も読めるが、手動の read_keep は自動残馬として使わない。
        try:
            from core import score_cache as sc
            keep = sc.read_elim_keep(race_id)
        except Exception:
            keep = None
        if keep is None:
            return ''
        keep_names = {u: by_um.get(u, '') for u in keep}
    body = ' ・ '.join(
        f"<span style='display:inline-block'><b>{u}</b> {_esc(name)}</span>"
        for u, name in sorted(keep_names.items())) or '残馬なし'
    return _exbox(f"🧹 消去フィルター残馬（{len(keep_names)}頭・ボーダー含む）", body)


def _vh_html(cv, records):
    """穴馬ハンター(妙味馬): 人気薄(6番人気以下)×vhスコア上位に絞って紙面化。

    実レースではvh tierがほぼ全馬に付くことがある(実査: 18頭中16頭が精鋭)ため、
    穴馬ハンターの本旨(過小評価の人気薄)に合わせ 人気薄∪穴セット×上位6頭でカット。"""
    aim = (cv or {}).get('aim') or {}
    tiers = {}
    for k, t in (aim.get('vh_tier') or {}).items():
        if t:
            try:
                tiers[int(k)] = str(t)
            except Exception:
                continue
    if not tiers:
        return ''
    vh = {}
    for k, v in (aim.get('vh') or {}).items():
        try:
            vh[int(k)] = float(v)
        except Exception:
            continue
    # 人気を紙面テーブルから逆引き
    pops = {}
    for r in records:
        mu = re.search(r'\d+', str(r.get('Umaban', '')))
        mp = re.search(r'\d+', str(r.get('Popularity', '')))
        if mu and mp:
            pops[int(mu.group())] = int(mp.group())
    ana = set(_ints(aim.get('ana')))
    cand = [u for u in tiers if pops.get(u, 99) >= 6 or u in ana]
    cand = sorted(cand, key=lambda u: -(vh.get(u, 0)))[:6]
    if not cand:
        return ''
    by_um = _names_by_um(records)
    items = []
    for u in cand:
        sc_txt = f" vh{vh[u]:.2f}" if u in vh else ''
        items.append(f"{_esc(tiers[u])} <b>{u}</b> {_esc(by_um.get(u, '')[:9])}"
                     f"{_esc(sc_txt)}")
    body = '　'.join(items)
    rest = len(tiers) - len(cand)
    if rest > 0:
        body += _esc(f"　(他{rest}頭は人気上位のため省略)")
    return _exbox("🎯 穴馬ハンター（妙味馬・人気薄上位）", body)


def _odds_moves_html(race_id, records):
    """オッズ動向: 朝一↔直前の変動インサイト(記録済みレースのみ・紙面時に算出)。"""
    try:
        from core.odds_tracker import OddsTracker
        from core import odds_move as omv
        t = OddsTracker(db_path=os.path.join(ROOT, 'data', 'odds_history.db'))
        h = t.get_history_df(race_id)
        if h is None or getattr(h, 'empty', True):
            return ''
        mv = omv.analyze_odds_movement(h)
        if not mv.get('ok') or not mv.get('insights'):
            return ''
    except Exception:
        return ''
    by_um = _names_by_um(records)
    icon = {'warn': '⚠', 'good': '◎', 'info': '・'}
    lines = []
    for ins in mv['insights'][:8]:
        try:
            u = int(ins.get('umaban'))
        except Exception:
            continue
        lines.append(f"{icon.get(str(ins.get('severity')), '・')}{u} "
                     f"{_esc(by_um.get(u, '')[:8])}: {_esc(str(ins.get('reason', '')))}")
    if not lines:
        return ''
    return _exbox("🔀 オッズ動向（朝一↔直前）", '<br>'.join(lines))


def _evidence_html(analysis):
    """判定根拠エビデンス表: 項目/値/ステータスの3列ミニ表。"""
    rows = ((analysis or {}).get('evidence') or {}).get('data') or []
    if not rows:
        return ''
    trs = []
    for r in rows:
        trs.append(f"<tr><td>{_fmt_cell(r.get('項目'), 18)}</td>"
                   f"<td>{_fmt_cell(r.get('値'), 26)}</td>"
                   f"<td>{_fmt_cell(r.get('ステータス'), 60)}</td></tr>")
    body = ("<table class='ev'><thead><tr><th>項目</th><th>値</th><th>ステータス</th></tr>"
            f"</thead><tbody>{''.join(trs)}</tbody></table>")
    return f"<div class='exbox exwide'><span class='exttl'>📊 判定根拠エビデンス表</span>{body}</div>"


def _pci_html(analysis):
    """PCI(ペースチェンジ指数)&展開適合: 総合判定＋指標＋適合馬＋展開逆らい馬。"""
    d = ((analysis or {}).get('pci') or {}).get('data') or {}
    if not d:
        return ''
    lines = []
    if d.get('verdict'):
        lines.append(f"🧭 ペース総合判定: <b>{_esc(str(d['verdict']))}</b>"
                     f"（信じるのは {_esc(str(d.get('verdict_src') or ''))}／"
                     f"{_esc(str(d.get('verdict_conf') or ''))}）")
    if d.get('lean_txt'):
        lines.append(_esc(str(d['lean_txt'])))
    m = []
    if d.get('rpci') is not None:
        m.append(f"想定RPCI {float(d['rpci']):.1f}({_esc(str(d.get('rpci_type') or ''))})")
    if d.get('avg_pci') is not None:
        m.append(f"平均PCI {float(d['avg_pci']):.1f}")
    if d.get('match_pct') is not None:
        m.append(f"展開適合率 {float(d['match_pct']):.0f}%")
    if d.get('raw_density') is not None and d.get('cor_density') is not None:
        m.append(f"先行密集 {float(d['raw_density']):.0f}%→補正{float(d['cor_density']):.0f}%")
    if m:
        lines.append('　'.join(m))
    fits = []
    for h in (d.get('match_horses') or []):
        fit = str(h.get('適合度', ''))
        if '◎' in fit or '○' in fit:
            mk = '◎' if '◎' in fit else '○'
            fits.append(f"{mk}{h.get('馬番', '?')}")
    if fits:
        lines.append("適合馬(RPCI基準): " + '・'.join(fits[:12]))
    anom = d.get('anom') or []
    if anom:
        lines.append("🚨 展開逆らい馬(次走注目): " + '・'.join(
            f"{_esc(str(a.get('馬名', ''))[:8])}(+{float(a.get('残り600m秒差', 0)):.2f}s)"
            for a in anom[:5]))
    return _exbox("⚡ PCI & 展開適合", '<br>'.join(lines)) if lines else ''


def _pace_upset_html(analysis):
    """展開分析&波乱確率: 波乱%＋内訳＋波乱要因＋脚質構成。"""
    d = ((analysis or {}).get('pace_upset') or {}).get('data') or {}
    if not d:
        return ''
    lines = []
    head = []
    if d.get('pace_label'):
        head.append(f"想定ペース <b>{_esc(str(d['pace_label']))}</b>")
    if d.get('upset_prob') is not None:
        up = int(float(d['upset_prob']))
        bar = '●' * min(5, up // 20) + '○' * (5 - min(5, up // 20))
        head.append(f"波乱確率 <b>{up}%</b> {bar}")
    if d.get('front_collapse_risk') is not None:
        head.append(f"前崩れリスク {float(d['front_collapse_risk']):.1f}/5")
    if d.get('closer_advantage'):
        head.append(f"差し有利度 {_esc(str(d['closer_advantage']))}")
    if head:
        lines.append('　'.join(head))
    if d.get('scenario'):
        lines.append(_esc(str(d['scenario'])))
    fac = d.get('upset_factors') or []
    if fac:
        lines.append("⚠波乱要因: " + '／'.join(_esc(str(x)) for x in fac[:6]))
    bd = d.get('upset_breakdown') or {}
    if bd:
        lines.append("内訳: " + '　'.join(
            f"{_esc(str(k))} {float(v):.1f}%" for k, v in bd.items()))
    sub = []
    if d.get('front_count') is not None:
        sub.append(f"先行馬{int(d['front_count'])}頭")
    if d.get('weighted_front_density') is not None:
        sub.append(f"重み付き密集率{float(d['weighted_front_density']):.0f}%")
    if d.get('makuri_count'):
        sub.append(f"マクリ癖{int(d['makuri_count'])}頭")
    if d.get('ability_variance') is not None:
        sub.append(f"能力分散σ{float(d['ability_variance']):.1f}")
    if d.get('odds_concentration') is not None:
        sub.append(f"上位3頭オッズ計{float(d['odds_concentration']):.1f}倍")
    if sub:
        lines.append('　'.join(sub))
    pos = d.get('positional_map') or {}
    if pos:
        groups = {}
        for u, lbl in pos.items():
            groups.setdefault(str(lbl), []).append(str(u))
        emj = {'逃げ': '🔴', '先行': '🟠', '差し': '🔵', '追込': '🟣', '不明': '⚪'}
        lines.append("脚質構成: " + '　'.join(
            f"{emj.get(k, '⚪')}{_esc(k)}:{'・'.join(vs)}"
            for k, vs in groups.items() if k != '不明'))
    if lines:
        lines.append("<span style='color:#888;font-size:6.4pt;'>※展開恩恵(展開が向く馬)は"
                     "検証で人気に織込み済みと確認済み。これは表示のみで買い妙味の主張ではありません。</span>")
    return _exbox("🏇 展開分析 & 波乱確率", '<br>'.join(lines)) if lines else ''


# ゾーン名は2026-08にX軸を『回収率EV』→『アプリの評価』へ変えた際に改名した。
# 旧スナップショットも読めるよう、新旧どちらの名前も並べておく(先頭記号で突き合わせる)。
_ZONE_ORDER = ['① 本命ゾーン(両方が高評価)', '② 妙味ゾーン(アプリだけ高評価)',
               '③ 危険ゾーン(市場だけ高評価)', '④ 見送り(両方が低評価)',
               '① 勝ちゾーン(このレースの軸候補)', '② 一撃ゾーン(穴)',
               '③ 堅実(中位)', '④ 見送り']
_ZONE_SHORT = {'① 本命ゾーン(両方が高評価)': '① 本命',
               '② 妙味ゾーン(アプリだけ高評価)': '② 妙味',
               '③ 危険ゾーン(市場だけ高評価)': '③ 危険',
               '④ 見送り(両方が低評価)': '④ 見送り',
               '① 勝ちゾーン(このレースの軸候補)': '① 勝ちゾーン',
               '② 一撃ゾーン(穴)': '② 一撃(穴)',
               '③ 堅実(中位)': '③ 堅実', '④ 見送り': '④ 見送り'}
_ZONE_COLOR = {'① 本命ゾーン(両方が高評価)': '#2f9e44',
               '② 妙味ゾーン(アプリだけ高評価)': '#f59f00',
               '③ 危険ゾーン(市場だけ高評価)': '#e03131',
               '④ 見送り(両方が低評価)': '#868e96',
               '① 勝ちゾーン(このレースの軸候補)': '#2f9e44',
               '② 一撃ゾーン(穴)': '#f59f00',
               '③ 堅実(中位)': '#1971c2', '④ 見送り': '#868e96'}


def _quantile(values, q):
    """パーセンタイル(線形補間・pandas Series.quantile()と同じ既定方式)。"""
    s = sorted(values)
    n = len(s)
    if n == 0:
        return 0.0
    if n == 1:
        return s[0]
    pos = q * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _value_zone_scatter_svg(rows):
    """複勝率×回収率マップの散布図(静的SVG)。SRA(🏠)のAltair散布図と同じ軸/ゾーン色/
    ①勝ちゾーンの網掛け・境界線・凡例を印刷向けに再現する表示専用の可視化。
    ゾーン閾値(y_hi/x_mid/x_hi)はrows(fuku/roi/odds)からapp.pyと同じ式で再計算するだけで、
    新しい判定ロジックは追加しない。"""
    pts = []
    for r in (rows or []):
        try:
            um = int(r.get('馬番'))
            # 2026-08 にX軸を『回収率EV(roi)』→『アプリの評価(abil)』へ変更した。
            # 旧スナップショットにはroiしか入っていないので両対応にする。
            _x = r.get('abil')
            roi = float(r.get('roi') if _x is None else _x)
            fuku = float(r.get('fuku'))
        except Exception:
            continue
        odds = None
        try:
            odds = float(r.get('odds'))
        except Exception:
            pass
        pts.append({'um': um, 'name': str(r.get('name', ''))[:6], 'roi': roi, 'fuku': fuku,
                    'odds': odds, 'zone': str(r.get('ゾーン', '④ 見送り'))})
    if len(pts) < 2:
        return ''
    w, h = 640, 300
    ml, mr, mt, mb = 40, 16, 14, 26
    pw, ph = w - ml - mr, h - mt - mb - 34   # 下段34pxは凡例用に確保
    roi_vals = [p['roi'] for p in pts]
    fuku_vals = [p['fuku'] for p in pts]
    x0, x1 = min(roi_vals + [95.0]) - 8, max(roi_vals + [110.0]) + 8
    y0, y1 = max(0.0, min(fuku_vals) - 6), min(100.0, max(fuku_vals) + 8)
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0

    # ①勝ちゾーンの閾値(app.py ZONEシートの散布図と同じ式): y_hi=複勝率上位25%、
    # x_mid=健全馬(60倍以下)の回収率中央値、x_hi=同75%(②一撃の境界)。
    y_hi = _quantile(fuku_vals, 0.75)
    sane_roi = [p['roi'] for p in pts if p['odds'] is None or p['odds'] <= 60.0]
    if not sane_roi:
        sane_roi = roi_vals
    x_mid = _quantile(sane_roi, 0.5)
    x_hi = _quantile(sane_roi, 0.75)

    def _px(roi):
        return ml + (roi - x0) / (x1 - x0) * pw

    def _py(fuku):
        return mt + ph - (fuku - y0) / (y1 - y0) * ph

    parts = [f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
             f'style="width:100%;height:auto;display:block;margin:1mm 0;">']
    # ①勝ちゾーン(右上コーナー)の薄い赤網掛け+ラベル(app.pyの_sm_rect/_sm_zlabと同じ判定域)
    zx0 = max(_px(x_mid), ml)
    if zx0 < ml + pw:
        parts.append(f'<rect x="{zx0:.1f}" y="{mt:.1f}" width="{ml + pw - zx0:.1f}" '
                     f'height="{_py(y_hi) - mt:.1f}" fill="#ffc9c9" fill-opacity="0.3"/>')
        parts.append(f'<text x="{(zx0 + ml + pw) / 2:.1f}" y="{mt + 10:.1f}" font-size="9" '
                     f'font-weight="700" fill="#e03131" text-anchor="middle">① 勝ちゾーン</text>')
    parts.append(f'<line x1="{ml}" y1="{mt}" x2="{ml}" y2="{mt + ph}" stroke="#999" stroke-width="1"/>')
    parts.append(f'<line x1="{ml}" y1="{mt + ph}" x2="{ml + pw}" y2="{mt + ph}" '
                 f'stroke="#999" stroke-width="1"/>')
    if x0 < 100 < x1:
        rx = _px(100)
        parts.append(f'<line x1="{rx:.1f}" y1="{mt}" x2="{rx:.1f}" y2="{mt + ph}" '
                     f'stroke="#adb5bd" stroke-width="1" stroke-dasharray="3,3"/>')
        parts.append(f'<text x="{rx:.1f}" y="{mt - 3}" font-size="9" fill="#adb5bd" '
                     f'text-anchor="middle">EV100</text>')
    if x0 < x_mid < x1:
        rxm = _px(x_mid)
        parts.append(f'<line x1="{rxm:.1f}" y1="{mt}" x2="{rxm:.1f}" y2="{mt + ph}" '
                     f'stroke="#e03131" stroke-width="1" stroke-dasharray="5,4"/>')
    if x0 < x_hi < x1:
        rxh = _px(x_hi)
        parts.append(f'<line x1="{rxh:.1f}" y1="{mt}" x2="{rxh:.1f}" y2="{mt + ph}" '
                     f'stroke="#f59f00" stroke-width="1" stroke-dasharray="3,3"/>')
    if y0 < y_hi < y1:
        ryh = _py(y_hi)
        parts.append(f'<line x1="{ml}" y1="{ryh:.1f}" x2="{ml + pw}" y2="{ryh:.1f}" '
                     f'stroke="#e03131" stroke-width="1" stroke-dasharray="5,4"/>')
    parts.append(f'<text x="{ml + pw / 2:.1f}" y="{mt + ph + 22:.1f}" font-size="10" fill="#555" '
                 f'text-anchor="middle">回収率EV(%)</text>')
    parts.append(f'<text x="10" y="{mt + ph / 2:.1f}" font-size="10" fill="#555" '
                 f'text-anchor="middle" transform="rotate(-90 10 {mt + ph / 2:.1f})">複勝率(%)</text>')
    for yv in (0, 25, 50, 75, 100):
        if y0 <= yv <= y1:
            yy = _py(yv)
            parts.append(f'<line x1="{ml - 3}" y1="{yy:.1f}" x2="{ml}" y2="{yy:.1f}" stroke="#999"/>')
            parts.append(f'<text x="{ml - 6}" y="{yy:.1f}" font-size="8" fill="#777" '
                         f'text-anchor="end" dominant-baseline="middle">{yv}</text>')

    placed = []

    def _fits(bx0, by0, bx1, by1):
        for (px0, py0, px1, py1) in placed:
            if not (bx1 < px0 or bx0 > px1 or by1 < py0 or by0 > py1):
                return False
        return True

    dots, labels = [], []
    for p in sorted(pts, key=lambda p: -p['fuku']):
        cx, cy = _px(p['roi']), _py(p['fuku'])
        color = _ZONE_COLOR.get(p['zone'], '#868e96')
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="7" fill="{color}" '
                    f'fill-opacity="0.85" stroke="#fff" stroke-width="1"/>')
        label = f"{p['um']}{_esc(p['name'])}"
        lw = max(3.6 * len(label) + 4, 14)
        lh = 10
        candidates = [(cx - lw / 2, cy - 9 - lh, cx + lw / 2, cy - 9),
                     (cx - lw / 2, cy + 9, cx + lw / 2, cy + 9 + lh),
                     (cx + 8, cy - lh / 2, cx + 8 + lw, cy + lh / 2),
                     (cx - 8 - lw, cy - lh / 2, cx - 8, cy + lh / 2)]
        chosen = next((c for c in candidates if _fits(*c)), candidates[0])
        placed.append(chosen)
        tx, ty = (chosen[0] + chosen[2]) / 2, (chosen[1] + chosen[3]) / 2
        labels.append(f'<text x="{tx:.1f}" y="{ty:.1f}" font-size="7.5" fill="#333" '
                      f'text-anchor="middle" dominant-baseline="middle">{label}</text>')
    parts.extend(dots)
    parts.extend(labels)

    # 凡例(ゾーン色の説明): 下段に横並びで配置
    ly = h - 12
    lx = ml
    for z in _ZONE_ORDER:
        color = _ZONE_COLOR[z]
        lbl = _ZONE_SHORT.get(z, z)
        parts.append(f'<circle cx="{lx + 5:.1f}" cy="{ly:.1f}" r="5" fill="{color}" '
                     f'fill-opacity="0.85" stroke="#fff" stroke-width="1"/>')
        parts.append(f'<text x="{lx + 13:.1f}" y="{ly:.1f}" font-size="8.5" fill="#333" '
                     f'dominant-baseline="middle">{_esc(lbl)}</text>')
        lx += 13 + len(lbl) * 8.6 + 16
    parts.append('</svg>')
    return ''.join(parts)


def _value_zone_chart_html(race_id):
    """📊 ZONEシート散布図(複勝率×回収率マップの図版)。既存value_zoneテーブルと同じ
    データ・同じゾーン判定を図で見せるだけの追加ビュー(既定OFF・任意で紙面に追加)。"""
    d = load_value_zone(race_id)
    rows = (d or {}).get('rows') or []
    if not rows:
        return ''
    svg = _value_zone_scatter_svg(rows)
    if not svg:
        return ''
    note = ("縦=複勝率(単勝オッズ別の実測値)／横=回収率EV(モデル推定勝率×オッズ・目安)。"
            "色は複勝率×回収率マップと同じゾーン判定(緑=①勝ちゾーン/橙=②一撃(穴)/青=③堅実/灰=④見送り)。"
            "単勝は市場効率的で『必ず儲かる』ではありません(表示専用)。")
    box = _exbox("📊 ZONEシート（複勝率×回収率の散布図）", svg + f"<div class='exnote'>{note}</div>")
    return box.replace("class='exbox'", "class='exbox exwide'", 1)


def _value_zone_html(race_id):
    """📈複勝率×回収率マップの結果をテーブル形式で紙面化(印刷コストを抑えテキスト表に)。

    SRA散布図と同じゾーン判定(①勝ちゾーン=複勝率上位25%×回収率が健全馬の中央値以上、
    等)をそのまま転記するだけ。新しい判定基準は作らない。
    """
    d = load_value_zone(race_id)
    rows = (d or {}).get('rows') or []
    if not rows:
        return ''
    by_zone = {z: [] for z in _ZONE_ORDER}
    for r in rows:
        by_zone.setdefault(r.get('ゾーン', '④ 見送り'), []).append(r)
    lines = []
    for z in _ZONE_ORDER:
        rs = sorted(by_zone.get(z) or [], key=lambda r: -(r.get('fuku') or 0))
        if not rs:
            continue
        items = []
        for r in rs[:6]:
            _x = r.get('abil')
            _xlbl = ('評' if _x is not None else '回')
            _xval = _x if _x is not None else r.get('roi')
            items.append(f"{_esc(r.get('馬番'))}{_esc(str(r.get('name', ''))[:6])}"
                         f"(複{_esc(r.get('fuku'))}%/{_xlbl}{_esc(_xval)})")
        lines.append(f"<b>{_esc(_ZONE_SHORT.get(z, z))}</b>: " + '　'.join(items))
    note = ("複=市場の評価(単勝オッズ別の実測複勝率)／評=アプリの評価(レース内0-100)。"
            "①本命=両方が高い／②妙味=アプリだけ高く市場が安い／③危険=市場だけ高い／"
            "④見送り=両方低い。境界はレース内の中央値。"
            "単勝は市場効率的で『必ず儲かる』ではありません。")
    box = _exbox("📈 複勝率×回収率マップ（ゾーン別）", '<br>'.join(lines) + f"<div class='exnote'>{note}</div>")
    return box.replace("class='exbox'", "class='exbox exwide'", 1)


def _developer_thoughts_html(race_id):
    """🧠開発者の思考プロセス。core/philosophy.pyの判定結果をそのまま紙面化する。

    LLM呼び出しなし・新規ロジックなし。統合ビュー(合議)の結論を再掲しつつ、
    『どの順番で・何を根拠に判断したか』を①〜⑧の番号付きで見せるだけの層。
    """
    d = load_philosophy(race_id)
    if not d or not d.get('steps'):
        return ''
    final = d.get('final') or {}
    steps = d.get('steps') or []

    def _join(ul):
        return '・'.join(str(u) for u in (ul or [])) or 'なし'

    lines = []
    if final.get('skip'):
        _why = '・'.join(final.get('skip_reasons') or [])
        lines.append(f"⛔ <b>このレースは見送り推奨</b>" + (f"（{_esc(_why)}）" if _why else ''))
    else:
        lines.append(f"✅ <b>この思考で選んだ買い方: {_esc(str(final.get('plan', '')))}</b>")
    lines.append(f"本命 {_join(final.get('honmei'))}　｜　相手 {_join(final.get('aite'))}"
                 f"　｜　穴 {_join(final.get('ana'))}　｜　消し {_join(final.get('keshi'))}")
    lines.append("<hr style='border:none;border-top:0.4px solid #ddd;margin:1mm 0;'>")
    for s in steps:
        if not s.get('enabled', True):
            continue
        no = _esc(str(s.get('no', '')))
        name = _esc(str(s.get('name', '')))
        verdict = _esc(str(s.get('verdict', '')))
        lines.append(f"<b>{no} {name}</b> → <b>{verdict}</b>")
        for r in (s.get('reasons') or [])[:3]:
            lines.append(f"<span style='margin-left:3mm;color:#666;font-size:6.6pt;'>・{_esc(str(r))}</span>")
    box = _exbox("🧠 開発者の思考プロセス（この予想の考え方）", '<br>'.join(lines))
    return box.replace("class='exbox'", "class='exbox exwide'", 1)


def _commentary_html(race_id):
    """🎭AIコメント欄。core/newspaper_commentary.pyが生成したスナップショットを紙面化。

    5人格が**それぞれ別の検証済みシグナルを担当**して出した◎を並べる読み物枠。
    各人単独の◎は単体で儲かると検証されたものではない(検証済みなのは
    『独立シグナルが一致すると複勝率が上がる』の方)。よって見出しと注記で
    「意見が割れたか一致したか」を読ませる作りにし、個々の◎を買い推奨にしない。
    スナップショットが無い(=ボタン未実行)レースには何も出さない。

    旧形式のスナップショット(umaban無し)も描画できるよう後方互換を保つ。
    """
    from core import newspaper_commentary as nc
    d = nc.load_commentary(race_id)
    comments = (d or {}).get('comments') or []
    if not comments:
        return ''
    lines, tally = [], None
    for c in comments:
        if c.get('mode') == 'summary':
            tally = c.get('tally') or tally
        um = c.get('umaban')
        # 担当シグナル名(lens)は長いので先頭の指標名だけ出す(紙面の幅制約)
        lens = str(c.get('lens') or '').split('/')[0].strip()
        head = (f"{_esc(c.get('emoji', ''))} <b>{_esc(c.get('name', ''))}</b>"
                + (f"<span style='color:#888;font-size:6.4pt;'>［{_esc(lens)}］</span>"
                   if lens else ''))
        if um is not None:
            mark = '⚠軸回避' if c.get('mode') == 'cut' else '◎'
            head += (f" <b style='color:#c00;'>{_esc(mark)}{_esc(str(um))}番"
                     f"{_esc(c.get('pick_name', ''))}</b>")
        lines.append(f"{head}: {_esc(c.get('comment', ''))}")
    if tally:
        n = tally.get('agree_n') or 0
        note = (f"※4人は別々のデータを見ています。一致{n}人"
                if n >= 2 else "※4人は別々のデータを見ています。今回は一致なし")
        lines.append(f"<span style='color:#888;font-size:6.4pt;'>{_esc(note)}"
                     "／一致が多いほど複勝圏の信頼度が上がります（単勝の推奨ではありません）</span>")
    box = _exbox("🎭 AIコメント欄（5人が別々のデータで予想）", '<br>'.join(lines))
    return box.replace("class='exbox'", "class='exbox exwide'", 1)


def _j5_html(race_id):
    """🏇 騎手係数込み 総合スコア(J5)。SRAで表示していた表をそのまま紙面化。

    影響率スライダー依存の表なので、保存時の重みを併記する(再現性の担保)。
    スコア/順位/変動は本紙の強適表・合議カードと重複するため割き、
    内訳(騎手係数の根拠)を中心に見せる。騎手係数・係数の意味を赤/青で色分け。
    """
    d = load_j5(race_id)
    rows = (d or {}).get('rows') or []
    if not rows:
        return ''
    w = (d or {}).get('weight')
    w_txt = f"（騎手影響率 {float(w) * 100:.0f}%）" if isinstance(w, (int, float)) else ''

    def _f(r, k, dflt=''):
        v = r.get(k)
        return '' if v is None else str(v)

    def _um_key(r):
        try:
            return int(r.get('馬番'))
        except Exception:
            return 999
    rows_sorted = sorted(rows, key=_um_key)

    head = ('<tr><th>馬番</th><th>馬名</th><th>騎手</th>'
            '<th>騎手係数</th><th>係数</th><th>黄金</th><th>内訳</th></tr>')
    body = []
    for r in rows_sorted[:18]:
        coef_val = 1.0
        try:
            coef_val = float(r.get('騎手係数', 1.0))
        except (TypeError, ValueError):
            pass
        if coef_val >= 1.02:
            cc = 'color:#e03131;font-weight:bold'
        elif coef_val >= 1.005:
            cc = 'color:#e8590c'
        elif coef_val >= 0.995:
            cc = ''
        elif coef_val >= 0.98:
            cc = 'color:#1971c2'
        else:
            cc = 'color:#1971c2;font-weight:bold'
        coef_meaning = _esc(_f(r, '係数の意味'))
        body.append(
            f"<tr><td><b>{_esc(_f(r, '馬番'))}</b></td>"
            f"<td>{_esc(_f(r, '馬名')[:9])}</td>"
            f"<td>{_esc(_f(r, '騎手')[:6])}</td>"
            f"<td style='{cc}'>{_esc(_f(r, '騎手係数'))}</td>"
            f"<td style='{cc}'>{coef_meaning}</td>"
            f"<td>{_esc(_f(r, '黄金ライン'))}</td>"
            f"<td>{_esc(_f(r, '内訳'))}</td></tr>")
    tbl = (f"<table class='sub'><thead>{head}</thead>"
           f"<tbody>{''.join(body)}</tbody></table>")
    note = ("黄金ライン🥇＝騎手×厩舎の連対40%+。騎手係数は検証済みエッジ強度に合わせた保守的設定。"
            "赤＝騎手で評価UP／青＝騎手で評価DOWN。")
    box = _exbox(f"🏇 騎手係数込み 総合スコア{w_txt}",
                 tbl + f"<div class='exnote'>{note}</div>")
    # 7列あるので幅広ボックスにする(標準幅32.8%だと潰れる)
    return box.replace("class='exbox'", "class='exbox exwide'", 1)


def _stress_html(analysis, records):
    """Stress Analyst: 危険人気トラップ＋デバフ該当馬＋スト2(最終予測下位2)。"""
    d = ((analysis or {}).get('stress') or {}).get('data') or {}
    rows = d.get('rows') or []
    if not rows:
        return ''
    lines = []

    def _coef(r):
        try:
            return float(r.get('ストレス係数'))
        except Exception:
            return 1.0

    def _pop(r):
        try:
            return int(r.get('人') or r.get('人気'))
        except Exception:
            return 99

    def _um(r):
        return r.get('番') or r.get('馬番')

    def _reason(r):
        return str(r.get('要因') or r.get('ストレス要因') or '')

    trap = [r for r in rows if _coef(r) < 0.92 and _pop(r) <= 6]
    if trap:
        lines.append("⚠ 過剰評価トラップ(1-6番人気×係数&lt;0.92): " + '　'.join(
            f"<b>{_um(r)}</b>{_esc(str(r.get('馬名', ''))[:8])}"
            f"({_pop(r)}人気/係数{_esc(str(r.get('ストレス係数')))})"
            f"〈{_esc(_reason(r)[:40])}〉" for r in trap))
    debuff = [r for r in rows if _coef(r) < 1.0 and r not in trap]
    if debuff:
        lines.append("デバフ該当: " + '　'.join(
            f"{_um(r)}{_esc(str(r.get('馬名', ''))[:7])}"
            f"({_esc(str(r.get('ストレス係数')))})" for r in debuff[:8]))
    bot2 = _ints(d.get('bottom2'))
    if bot2:
        lines.append("🐎スト2(最終予測 下位2・holdout z-2.83): "
                     + '・'.join(str(u) for u in bot2))
    if not any(_coef(r) < 1.0 for r in rows):
        lines.append("全馬デバフなし(標準✅)")
    lines.append("※効果は±1〜2pp。軸を消すより相手の優先度を下げる用途(検証済)")
    return _exbox("🐎 Stress Analyst（検証済デバフ）", '<br>'.join(lines))


_ALERT_ORDER = ['spurt_value', 'dirt_draw_danger', 'turf_start_caution', 'dirt_draw_boost']


def _alerts_html(race_id, cv, records):
    """条件発動アラートの集約ブロック。

    荒れ予報(lean)と危険人気馬(veto)は合議スナップショットから常に最新を再構成、
    末脚妙味/ダート枠順エッジ等は {rid}.alerts.json(SRA表示時に保存・空=クリア)から。"""
    by_um = _names_by_um(records)
    items = []  # (severity, title, [lines])
    # ── 荒れ予報/決着タイプ判定(trio_lean・検証済) ──
    lean = (cv or {}).get('lean') or {}
    if lean.get('lean') == '②穴妙味向き':
        sc = lean.get('score')
        try:
            sc_txt = f"（lean {float(sc):+.1f}）" if sc is not None else ''
        except Exception:
            sc_txt = ''
        items.append(('warn', f"⚠ 荒れ予報: top7圏外に3着馬がいるリスク高{sc_txt}→②穴妙味狙い推奨",
                      [str(x) for x in (lean.get('pos') or [])[:4]] or ['(根拠詳細なし)']))
    elif lean.get('lean') == '本線向き':
        items.append(('good', '🛡 決着タイプ判定: 本線向き（top7で捕獲しやすい）',
                      [str(x) for x in (lean.get('neg') or [])[:3]] or ['(根拠詳細なし)']))
    # ── 危険人気馬(複数の危険材料で軸不可=veto) ──
    aim = (cv or {}).get('aim') or {}
    veto = sorted(set(_ints(aim.get('veto'))))
    if veto:
        dr = aim.get('danger_reasons') or {}
        lines = []
        for u in veto:
            rs = [str(x) for x in (dr.get(str(u)) or dr.get(u) or [])]
            lines.append(f"{u}番 {by_um.get(u, '')[:9]}" + (f"（{'・'.join(rs)}）" if rs else ''))
        lines.append('→ 軸の自動採用から降格。相手/押さえで再検討を。')
        items.append(('warn', '⚠ 危険人気馬（複数の危険材料で軸不可）', lines))
    # ── 保存済みアラート(末脚妙味/ダート枠順エッジ等・SRA表示時に保存) ──
    saved = load_alerts(race_id) or {}
    keys = [k for k in _ALERT_ORDER if k in saved] + \
           [k for k in saved if k not in _ALERT_ORDER and k != 'race_id']
    for k in keys:
        a = saved.get(k) or {}
        if a.get('lines'):
            items.append((str(a.get('severity') or 'warn'), str(a.get('title') or k),
                          [re.sub(r'^-\s*', '', str(x)) for x in a['lines']]))
    if not items:
        return ''
    sev_rank = {'warn': 0, 'info': 1, 'good': 2}
    items.sort(key=lambda x: sev_rank.get(x[0], 1))
    divs = []
    for sev, ttl, lines in items:
        body = '<br>'.join(_esc(x) for x in lines)
        divs.append(f"<div class='albox al-{_esc(sev)}'><b>{_esc(ttl)}</b>"
                    + (f"<br>{body}" if body else '') + "</div>")
    return ("<div class='exbox exwide'><span class='exttl'>🚨 条件アラート"
            f"（このレースで発動した警告・妙味）</span>{''.join(divs)}</div>")


def resolve_page_format(orientation):
    """orientation設定('landscape'/'portrait'/'a3_portrait')→(pdf_format, is_landscape)。

    @page CSS(build_newspaper_html)とhtml_to_pdf()のPlaywright呼び出しの両方が
    ここを通ることで、ページサイズの二重管理によるズレ(2026-07診断)を防ぐ。
    A3縦(297×420mm)はA4横(297×210mm)と同じ幅で高さがちょうど2倍のため、
    既存の%ベースCSSのまま『A4横2枚ぶんの内容が1枚に収まる』設計が成立する。
    """
    if orientation == 'a3_portrait':
        return 'A3', False
    if orientation == 'portrait':
        return 'A4', False
    return 'A4', True  # 既定: landscape


def build_newspaper_html(race_ids, opts=None):
    """選択レースを1つの印刷用HTMLに組版。(html, 収録情報リスト) を返す。"""
    o = dict(DEFAULT_OPTS)
    o.update(opts or {})
    sec = dict(DEFAULT_OPTS['sections'])
    sec.update((opts or {}).get('sections') or {})
    bet_types = dict(DEFAULT_OPTS['bet_types'])
    bet_types.update((opts or {}).get('bet_types') or {})
    _pdf_fmt, landscape = resolve_page_format(o.get('orientation', 'landscape'))
    font_pt = float(o.get('font_pt') or 6.8)
    mono = bool(o.get('mono'))
    accent = '#111' if mono else '#b3001b'

    issued = []
    race_blocks = []
    toc_rows = []
    for rid in race_ids:
        v = load_view(rid)
        if not v:
            continue
        cols = _pick_columns(v, o)
        _recs_all = v.get('records') or []
        for _pi, _pr in enumerate(_recs_all):
            _pr['_pos'] = _pi   # 表示行順の位置(アプリ色スナップショットのキー)
        records = _sort_records(_recs_all, o.get('row_order', 'app'))
        labels = v.get('labels') or {}
        meta = v.get('meta') or {}
        _vr = _venue_region(meta.get('venue', ''))
        if _vr:
            for _er in records:
                _tz = _er.get('Tozai')
                if _tz and _tz != _vr:
                    try:
                        _ep = int(_er.get('Popularity') or _er.get('Pop') or 0)
                    except (TypeError, ValueError):
                        _ep = 0
                    if _ep >= 7:
                        _tv = _er.get('Trainer') or ''
                        if not str(_tv).endswith('E'):
                            _er['Trainer'] = str(_tv) + 'E'
        # アプリの強適テーブル色分け(Styler計算済みセルCSS)を継承。モノクロ時と
        # 行数不一致(古いスナップショット)時は適用しない。
        smap = {}
        if not mono and v.get('source') == 'view':
            _sty = load_styles(rid)
            if _sty and int(_sty.get('n_rows') or -1) == len(_recs_all):
                smap = _sty.get('styles') or {}
        cv = load_consensus(rid)
        _ev_labels = {}
        try:
            _ana = load_analysis(rid)
            if _ana and _ana.get('ev_labels'):
                _ev_labels = _ana['ev_labels'].get('data') or {}
        except Exception:
            pass
        # ⚠ ここには以前『SRA未実行時のフォールバック』として、jravan.dbのオッズ帯平均勝率から
        #   _roi = その馬のオッズ × 帯の平均勝率 を計算し、>=1.0 なら '✨EV>1' を付ける処理があった。
        #   帯平均を個体に当てはめる誤りで、各帯の上端(帯内で最も人気の無い馬)だけで機械的に
        #   1.0を超える帯量子化アーティファクトだった。実測(2022-25・14.7万頭)で点灯馬の
        #   単勝ROIは79.1%(勝率5.27%)・非点灯78.0%(9.98%)＝妙味ゼロ。
        #   [[verified_tansho_roi_efficient]](単勝は全帯で+ROIポケット無し)と整合。
        #   2026-08-15 に削除。妙味表示は🔥+ファクター(オッズと独立に検証済み)のみとする。
        #   ＝ _ev_labels は SRA(強適消去エンジン)が書いたスナップショットのみを使う。
        badge, buyline = _buymeta_html(rid, sec.get('gate'), sec.get('buymeta'))

        rn = race_no(rid)
        cond = f"｜馬場 {meta.get('condition')}" if meta.get('condition') else ''
        surface = f"{meta.get('surface', '')}{meta.get('distance', '')}m" \
            if meta.get('distance') else str(meta.get('surface') or '')
        _pt = meta.get('post_time')
        _pt_part = f"｜発走{_esc(str(_pt))}" if _pt else ''
        _pp = meta.get('pace_prediction')
        _nar_pace_tag = ''
        if _pp:
            _pc = _pp.get('pace', '')
            _pcmt = _pp.get('comment', '')
            _nar_pace_tag = (f"<span class='rmeta' style='margin-left:8px;color:#c55;'>"
                             f"展開:{_esc(_pc)}({_esc(_pcmt)})</span>")
        hdr = (f"<div class='racehdr'>"
               f"<span class='rno'>{_esc(meta.get('venue', '?'))} {rn or '?'}R</span>"
               f"<span class='rname'>{_esc(meta.get('race_name', ''))}</span>"
               f"<span class='rmeta'>{_esc(surface)}{_esc(cond)}"
               f"｜{_esc(str(meta.get('date') or ''))}{_pt_part}｜{_esc(str(meta.get('n_horses') or len(records)))}頭"
               f"{'｜' + _esc(v.get('sort_label')) + '順' if v.get('sort_label') else ''}</span>"
               f"{_nar_pace_tag}"
               f"{badge}</div>")

        _pr_re = re.compile(r'^(前走|[2-5]走前)')

        # NAR通常版: 過去走を別テーブルに分離して横幅を確保
        _nar_split = bool(meta.get('nar') and any(_pr_re.match(c) for c in cols))
        if _nar_split:
            cols_main = [c for c in cols if not _pr_re.match(c)]
            cols_past = ['Umaban', 'Name'] + [c for c in cols if _pr_re.match(c)]
        else:
            cols_main = cols
            cols_past = []

        def _build_tbl(target_cols):
            th = ''.join(
                f"<th class='{_col_slug(c)}{' pr' if _pr_re.match(c) else ''}'>"
                f"{_header_cell(labels.get(c, c))}</th>" for c in target_cols)
            rows = []
            for i, r in enumerate(records):
                cls = []
                if i % 2 == 1:
                    cls.append('zeb')
                try:
                    rk = int(float(r.get('Rank', 0)))
                except Exception:
                    rk = 0
                if not mono and o.get('row_order', 'app') == 'app' and rk in (1, 2, 3):
                    cls.append(f"top{rk}")
                _rsty = smap.get(str(r.get('_pos'))) or {}
                _tds = []
                for c in target_cols:
                    _css = _rsty.get(c)
                    _hot = False
                    if c == 'Sire' and r.get(c):
                        _st = r.get('_sire_tier')
                        _hot = bool(r.get('_sire_hot'))
                        if _st is None:
                            try:
                                from core.nar_scraper import _NAR_DIRT_TIER, _sire_venue_match
                                _st = _NAR_DIRT_TIER.get(str(r[c]).strip(), '')
                                if not _hot:
                                    _hot = _sire_venue_match(
                                        str(r[c]).strip(),
                                        meta.get('venue', ''),
                                        meta.get('distance'))
                            except Exception:
                                _st = ''
                        if _st == 'S':
                            _css = (_css + ';' if _css else '') + 'color:#c00;font-weight:bold'
                        elif _st == 'A':
                            _css = (_css + ';' if _css else '') + 'color:#1a5fb4;font-weight:bold'
                    _attr = f" style=\"{_esc(_css)}\"" if _css else ''
                    _pr_cls = ' pr' if _pr_re.match(c) else ''
                    _val = _cell_html(c, r.get(c), int(o.get('cell_max') or 0))
                    if _hot and c == 'Sire':
                        _val = f"\U0001f525{_val}"
                    if _css and 'background-color' in _css and c in ('BattleScore', 'JockeyChange'):
                        import re as _re
                        _val = _re.sub(r"color:#[0-9a-fA-F]{3,6}", "color:#fff", _val)
                    if c == 'Name' and _ev_labels:
                        _um_s = str(r.get('Umaban', ''))
                        _evl = _ev_labels.get(_um_s, '')
                        if '+ファクター' in _evl:
                            _val += "<span style='color:#e63946;font-size:0.75em' title='＋ファクター(人気薄8番以下×検証済み市場エッジ。test2023-25で単勝ROI108.8%/無印63.7%・n=453)'> 🔥+F</span>"
                        # ✨EV>1 は**掲載しない**(2026-08-15 削除)。
                        # 判定式が「その馬のオッズ × そのオッズ帯の平均勝率 >= 1.0」で、
                        # 帯の平均勝率を個体に当てはめているため、**各帯の上端(帯内で最も
                        # 人気が無い馬)だけで機械的に点灯する**帯量子化アーティファクト。
                        # 実測(2022-25・14.7万頭): 点灯馬の単勝ROI 79.1%(勝率5.27%) vs
                        # 非点灯 78.0%(9.98%)＝100%を全く超えず、勝率はむしろ半分。
                        # ツールチップの『実測回収率100%超』は事実に反していた。
                        # [[verified_tansho_roi_efficient]](単勝は全帯で+ROIポケット無し)と整合。
                        # Alert列では2026-07-12に同じ理由で非掲載化済みだったが、
                        # 新聞側に反映漏れがあり『買えるサイン』として誤読されていた。
                        # 再掲載しないこと。妙味は🔥+F(オッズと独立な検証済みシグナル)のみ。
                    _tds.append(f"<td class='{_col_slug(c)}{_pr_cls}'{_attr}>{_val}</td>")
                rows.append(f"<tr class='{' '.join(cls)}'>{''.join(_tds)}</tr>")
            return th, rows

        thead_main, body_main = _build_tbl(cols_main)
        if _nar_split:
            thead_past, body_past = _build_tbl(cols_past)
            table_html = (
                f"<table class='kt'><thead><tr>{thead_main}</tr></thead>"
                f"<tbody>{''.join(body_main)}</tbody></table>"
                f"<div class='past-sep'>過去走</div>"
                f"<table class='kt kt-past'><thead><tr>{thead_past}</tr></thead>"
                f"<tbody>{''.join(body_past)}</tbody></table>")
        else:
            table_html = (
                f"<table class='kt'><thead><tr>{thead_main}</tr></thead>"
                f"<tbody>{''.join(body_main)}</tbody></table>")

        note = ("<div class='fbnote'>※このレースはSRAスナップショット未保存のため代表列で再構成"
                "（🏠で再解析すると表示中の全列が紙面化されます）</div>"
                if v.get('source') == 'full' else '')

        hp_html = _header_plus_html(cv, v, rid) if sec.get('header_plus') else ''
        digest_html = _digest_html(cv, records, meta, mono) if sec.get('digest') else ''
        cv_html = _consensus_html(cv, records, mono) if sec.get('consensus') else ''
        analysis = load_analysis(rid)
        extras = []
        if sec.get('dev_thoughts'):
            extras.append(_developer_thoughts_html(rid))
        if sec.get('ai_commentary'):
            extras.append(_commentary_html(rid))
        if sec.get('value_zone'):
            extras.append(_value_zone_html(rid))
        if sec.get('alerts'):
            extras.append(_alerts_html(rid, cv, records))
        if sec.get('bets'):
            extras.append(_bets_html(rid, bet_types))
        if sec.get('pace'):
            extras.append(_pace_html(rid, records))
        if sec.get('pace_upset'):
            extras.append(_pace_upset_html(analysis))
        if sec.get('pci'):
            extras.append(_pci_html(analysis))
        if sec.get('stress'):
            extras.append(_stress_html(analysis, records))
        if sec.get('j5'):
            extras.append(_j5_html(rid))
        if sec.get('elim'):
            extras.append(_elim_html(cv, records, rid))
        if sec.get('vh'):
            extras.append(_vh_html(cv, records))
        if sec.get('odds_moves'):
            extras.append(_odds_moves_html(rid, records))
        if sec.get('evidence'):
            extras.append(_evidence_html(analysis))
        if sec.get('value_zone_chart'):
            extras.append(_value_zone_chart_html(rid))
        extras_html = ''.join(x for x in extras if x)
        if extras_html:
            extras_html = f"<div class='extras'>{extras_html}</div>"

        race_blocks.append(
            f"<section class='race'>"
            f"{hdr}{hp_html}{digest_html}{cv_html}{buyline}"
            f"{table_html}{note}{extras_html}</section>")
        toc_rows.append(
            f"<tr><td>{_esc(meta.get('venue', '?'))}{rn or '?'}R</td>"
            f"<td>{_esc(meta.get('race_name', ''))}</td>"
            f"<td>{_esc(surface)}</td><td>{_esc(str(meta.get('date') or ''))}</td>"
            f"<td>{_esc(str(meta.get('n_horses') or ''))}頭</td>"
            f"<td>{len(cols)}列{'(代表列)' if v.get('source') == 'full' else ''}</td></tr>")
        issued.append({'race_id': rid, 'label': race_label(v), 'n_cols': len(cols),
                       'n_rows': len(records), 'source': v.get('source')})

    if not race_blocks:
        return None, []

    import datetime as _dt
    today = _dt.date.today().strftime('%Y年%m月%d日')
    sub = _esc(o.get('subtitle') or f"{today} 発行")
    cover = ''
    if sec.get('cover'):
        # 1-2Rの時は目次・凡例が紙面の無駄(ほぼ白紙ページの原因)なので題字帯だけに縮小
        if len(race_blocks) >= 3:
            cover = (
                "<section class='cover'>"
                f"<div class='masthead'><span class='daiji'>{_esc(o.get('title'))}</span>"
                f"<span class='issue'>{sub}｜収録 {len(race_blocks)}レース</span></div>"
                "<table class='toc'><thead><tr><th>レース</th><th>名称</th><th>コース</th>"
                "<th>日付</th><th>頭数</th><th>紙面列数</th></tr></thead>"
                f"<tbody>{''.join(toc_rows)}</tbody></table>"
                "<div class='legend'>◎〇▲=軸候補(オッズ実複勝率) 🔥=1-3番人気 🧩=検証シグナル重複 "
                "🐢=信頼できる末脚 ⚡=バテ差し注意 🌀=33ラップ適合 🔵=補正T上位 🧬=血統上位<br>"
                "①本命/②相手/③押さえ/④穴=検証済みエッジの合議(votes多いほど複勝率単調UP・"
                "市場を出し抜く予測ではなく本命信頼度+絞り込みの道具)</div>"
                "</section>")
        else:
            cover = (
                "<section class='cover'>"
                f"<div class='masthead'><span class='daiji'>{_esc(o.get('title'))}</span>"
                f"<span class='issue'>{sub}｜収録 {len(race_blocks)}レース</span></div>"
                "</section>")
    footer = ''
    if o.get('footer_text'):
        footer = f"<div class='ftr'>{_esc(o.get('footer_text'))}</div>"

    # ── 改ページ設計(空白ページ・変な切れ方の防止) ──
    # ・表紙は3R以上の時だけ独立ページ(1-2Rなら1R目と同じページに詰めて白紙化を防ぐ)
    # ・レース区切りは page-break-BEFORE(2R目以降)＝末尾に空白ページを作らない
    standalone_cover = bool(cover) and len(race_blocks) >= 3
    if o.get('page_per_race'):
        out_blocks = []
        for _bi, _blk in enumerate(race_blocks):
            if _bi > 0 or standalone_cover:
                _blk = _blk.replace("<section class='race'>",
                                    "<section class='race pbb'>", 1)
            out_blocks.append(_blk)
        race_blocks = out_blocks

    page_size = f"{_pdf_fmt} {'landscape' if landscape else 'portrait'}"
    css = f"""
    @page {{ size: {page_size}; margin: 8mm 7mm 10mm 7mm; }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: 'Yu Gothic UI','Yu Gothic','Meiryo',sans-serif; color:#111;
            margin:0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .pbb {{ page-break-before: always; }}
    .masthead {{ border-bottom: 3px double #111; padding: 2mm 0 1.5mm 0; margin-bottom: 3mm;
                 display:flex; align-items: baseline; justify-content: space-between; }}
    .daiji {{ font-family:'Yu Mincho','MS Mincho',serif; font-size: 26pt; font-weight: 900;
              letter-spacing: 0.12em; color: {accent}; }}
    .issue {{ font-size: 9pt; color:#333; }}
    table.toc {{ border-collapse: collapse; width: 100%; font-size: 9pt; margin-bottom: 3mm; }}
    table.toc th, table.toc td {{ border: 0.5px solid #999; padding: 1.2mm 2mm; text-align: left; }}
    table.toc th {{ background: {'#eee' if mono else '#f7ecec'}; }}
    .legend {{ font-size: 7.5pt; color: #444; line-height: 1.6; border:0.5px solid #bbb;
               padding: 1.5mm 2mm; }}
    .racehdr {{ background: {'#222' if mono else '#1a1a2e'}; color: #fff; padding: 1.2mm 2.5mm;
                display:flex; align-items: baseline; gap: 3mm; margin: 0 0 1.2mm 0;
                border-left: 4mm solid {accent}; }}
    .rno {{ font-size: 13pt; font-weight: 900; }}
    .rname {{ font-size: 11pt; font-weight: 700; }}
    .rmeta {{ font-size: 8pt; color: #ddd; }}
    .gate {{ margin-left:auto; font-size: 8.5pt; font-weight:700; background:#fff;
             color:#111; border-radius: 2mm; padding: 0.4mm 2mm; }}
    .hplus {{ display: flex; flex-wrap: wrap; gap: 1.5mm; margin: 0 0 1.2mm 0; }}
    .hbox {{ border: 0.5px solid #bbb; padding: 0.7mm 1.5mm; font-size: 8pt; background: #fff; }}
    .hbox b.t {{ color: {accent}; font-size: 7.5pt; margin-right: 1.2mm; }}
    /* extras: flexだと『入りきらない行の箱群ごと次ページへジャンプ』して大きな空白が
       できるため、印刷分割に強い inline-block 流し込みにする */
    .extras {{ display: block; margin-top: 1mm; font-size: 0; }}
    .exbox {{ border: 0.5px solid #bbb; padding: 0.5mm 1.3mm; font-size: 7.3pt;
              line-height: 1.35; background: #fff; page-break-inside: avoid;
              display: inline-block; vertical-align: top; width: 32.8%;
              margin: 0 0.25% 0.8mm 0; }}
    .exttl {{ font-weight: 800; color: {accent}; display: block;
              border-bottom: 0.5px solid #ddd; margin-bottom: 0.3mm; }}
    .exwide {{ width: 66.2%; }}
    /* exbox内の小テーブル(J5=騎手係数込みスコア等)。紙面の主表(.kt)より一段小さく */
    .sub {{ width: 100%; border-collapse: collapse; font-size: 6.6pt; margin-top: 0.3mm; }}
    .sub th, .sub td {{ border: 0.4px solid #ddd; padding: 0.2mm 0.7mm;
                        text-align: center; white-space: nowrap; }}
    .sub th {{ background: {'#f2f2f2' if mono else '#f7eaec'}; font-weight: 700; }}
    .sub td:nth-child(4), .sub td:nth-child(5) {{ text-align: left; }}
    .exnote {{ font-size: 6.4pt; color: #666; margin-top: 0.3mm; line-height: 1.25; }}
    .albox {{ border-left: 1mm solid #999; padding: 0.4mm 1.3mm; margin: 0.3mm 0;
              font-size: 7.3pt; line-height: 1.3; }}
    .al-warn {{ background: {'#f0f0f0' if mono else '#fff6e0'};
                border-color: {'#666' if mono else '#e09b00'}; }}
    .al-info {{ background: {'#f4f4f4' if mono else '#e9f0fb'};
                border-color: {'#777' if mono else '#457b9d'}; }}
    .al-good {{ background: {'#f7f7f7' if mono else '#e9f5ec'};
                border-color: {'#888' if mono else '#2a9d8f'}; }}
    table.ev {{ border-collapse: collapse; width: 100%; font-size: 7pt; }}
    table.ev th, table.ev td {{ border: 0.4px solid #bbb; padding: 0.4mm 1mm;
                                text-align: left; word-break: break-all; }}
    table.ev th {{ background: {'#eee' if mono else '#f3e6e6'}; }}
    .cvrow {{ display: flex; gap: 1.5mm; margin: 0 0 1mm 0; align-items: stretch; }}
    .cvcard {{ flex: 1; border: 0.5px solid #bbb; padding: 0.3mm 1.2mm; background: #fff;
               min-height: 0; }}
    .cvttl {{ font-size: 7pt; font-weight: 800; margin-bottom: 0.1mm; }}
    .cvbody {{ font-size: 7.5pt; line-height: 1.15; }}
    .buymeta {{ font-size: 8pt; color:#222; margin: 0 0 1mm 0; }}
    table.kt {{ border-collapse: collapse; width: 100%; font-size: {font_pt}pt;
                table-layout: auto;
                {'page-break-inside: avoid;' if o.get('keep_table', True) else ''} }}
    table.kt thead {{ display: table-header-group; }}
    /* 診断済み(2026-07・Playwright実測): この行のavoidにより、ページ末尾に収まりきらない
       行は丸ごと次ページへ送られ、ページ末尾に数mmの余白が残る(行高が不揃いなため発生位置は
       レースごとに変わる)。行を裂いて読みにくくするより望ましいため維持するが、ページを
       縦に長くする(A3縦=A4横の2倍高)ことで発生頻度・余白量の両方が減る想定
       (実測: 14頭A4横で余白13.8px/711.9px時点で発生→A3縦での再測定は開発ログ参照)。 */
    table.kt tr {{ page-break-inside: avoid; }}
    table.kt th {{ background: {'#e8e8e8' if mono else '#f3e6e6'}; border: 0.4px solid #888;
                   padding: 0.6mm 0.8mm; font-size: {max(font_pt - 0.6, 4.5):.1f}pt;
                   font-weight: 700; text-align: center; }}
    table.kt td {{ border: 0.4px solid #aaa; padding: 0.5mm 0.8mm; vertical-align: middle;
                   word-break: break-all; }}
    /* 列ごとの幅調整(ユーザー要望・print A4)。table-layout:autoでの列幅ヒント。 */
    table.kt th.col-Bloodline, table.kt td.col-Bloodline {{ max-width: 27mm; }}   /* 血統(父/母父): 1頭名+余裕 */
    table.kt th.col-Trainer, table.kt td.col-Trainer {{ max-width: 18mm; }}       /* 厩舎: 『美浦・大竹 B14%』で折り返す幅 */
    table.kt th.col-BloodStats, table.kt td.col-BloodStats {{ min-width: 11mm; }} /* 血統実績: -1文字ぶん(13→11) */
    table.kt th.col-CorrectedT, table.kt td.col-CorrectedT {{ min-width: 15mm; }} /* 補正T: +2文字ぶん */
    table.kt th.col-SpurtIdx, table.kt td.col-SpurtIdx {{ min-width: 13mm; }}     /* 末脚指数: +1文字ぶん */
    table.kt th.col-OddsGap, table.kt td.col-OddsGap {{ min-width: 14mm; }}       /* オッズ断層: 『断層D1』で収まる幅 */
    table.kt th.col-Lap33, table.kt td.col-Lap33 {{ max-width: 13mm; }}          /* 33ラップ: -2文字ぶん(狭める) */
    table.kt th.col-WeightCarried, table.kt td.col-WeightCarried {{ min-width: 8mm; }} /* 斤量: +1文字ぶん */
    .past-sep {{ font-size: {max(font_pt - 0.5, 5):.1f}pt; font-weight: 700;
                  margin: 1.5mm 0 0.5mm 0; padding: 0.3mm 1mm;
                  background: {'#ddd' if mono else '#e8eef5'}; border-left: 3px solid {'#888' if mono else '#6688bb'};
                  color: {'#333' if mono else '#335'}; }}
    table.kt-past th {{ background: {'#e8e8e8' if mono else '#e0e8f3'} !important; }}
    tr.zeb td {{ background: #f6f6f6; }}
    tr.top1 td {{ background: {'#f6f6f6' if mono else '#fff3d6'}; }}
    tr.top2 td {{ background: {'#f6f6f6' if mono else '#eef3fb'}; }}
    tr.top3 td {{ background: {'#f6f6f6' if mono else '#f2ece4'}; }}
    /* 過去走ゾーン(前走〜5走前): 薄い別色で情報エリアを区別 */
    th.pr {{ background: {'#e8e8e8' if mono else '#e8eef5'} !important; }}
    td.pr {{ background: {'#f4f4f4' if mono else '#f0f4fa'} !important; }}
    tr.zeb td.pr {{ background: {'#efefef' if mono else '#e8edf4'} !important; }}
    tr.top1 td.pr {{ background: {'#f0f0f0' if mono else '#f5efd0'} !important; }}
    tr.top2 td.pr {{ background: {'#f0f0f0' if mono else '#e5eef8'} !important; }}
    tr.top3 td.pr {{ background: {'#f0f0f0' if mono else '#ebe6dd'} !important; }}
    .fbnote {{ font-size: 7pt; color: #777; margin-top: 0.8mm; }}
    .ftr {{ font-size: 7.5pt; color:#555; border-top: 0.5px solid #999; margin-top: 2mm;
            padding-top: 1mm; }}
    """
    html = (f"<meta charset='utf-8'><style>{css}</style>"
            f"{cover}{''.join(race_blocks)}{footer}")
    return html, issued


# ────────────────────────────────────────────────────────────
# PDF出力(Playwright chromium・requirements既存依存のみ)
# ────────────────────────────────────────────────────────────

def html_to_pdf(html_str, landscape=True, scale=1.0, page_numbers=True, timeout_s=180,
                page_format='A4'):
    """HTML→PDF bytes。Streamlitスレッドのasyncioループ衝突を避けるため別スレッド実行。

    page_format: 'A4'(既定) or 'A3'。HTML内の@page CSS(build_newspaper_html側)と
    必ず一致させること(resolve_page_format()を両方から呼ぶと自動的に揃う)。
    """
    def _work():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            try:
                pg = b.new_page()
                pg.set_content(html_str, wait_until='load')
                foot = ("<div style='font-size:7px;width:100%;text-align:center;color:#666;'>"
                        "<span class='pageNumber'></span> / <span class='totalPages'></span></div>")
                pdf = pg.pdf(
                    format=str(page_format or 'A4'), landscape=bool(landscape), print_background=True,
                    scale=max(0.1, min(2.0, float(scale or 1.0))),
                    margin={'top': '8mm', 'bottom': '11mm', 'left': '7mm', 'right': '7mm'},
                    display_header_footer=bool(page_numbers),
                    header_template="<span></span>", footer_template=foot)
            finally:
                b.close()
        return pdf
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(_work).result(timeout=timeout_s)


def pdf_page_count(pdf_bytes):
    """Chromium(Skia)PDFのページ数を素朴にカウント。不明はNone。"""
    if not pdf_bytes:
        return None
    try:
        n = len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])', pdf_bytes))
        return n or None
    except Exception:
        return None


# ────────────────────────────────────────────────────────────
# 結論カード (1レース1枚の結論だけ圧縮出力)
# ────────────────────────────────────────────────────────────

def _conclusion_card_data(race_id):
    """1レース分の結論カードに必要なデータを収集して返す。None=データ不足。"""
    cv = load_consensus(race_id)
    view = load_view(race_id)
    bets_data = load_bets(race_id)
    if not cv and not view:
        return None

    records = (view or {}).get('records') or []
    meta = (view or {}).get('meta') or {}
    groups = (cv or {}).get('groups') or {}
    horses = (cv or {}).get('horses') or []
    aim = (cv or {}).get('aim') or {}
    forecast = (cv or {}).get('forecast') or {}

    by_um = _names_by_um(records)

    # Gate判定
    gate = None
    try:
        from core import score_cache as sc
        gate = sc.read_gate(race_id)
    except Exception:
        pass

    # 軸候補(with confidence)
    axis_info = []
    try:
        from core import axis_selector as ax
        is_nar = int(str(race_id)[4:6]) > 10
    except Exception:
        ax = None
        is_nar = False
    _order = {'◎': 0, '〇': 1, '○': 1, '▲': 2}
    for h in sorted(horses, key=lambda h: _order.get(str(h.get('axis_mark', ''))[:1], 9)):
        if not h.get('axis_mark'):
            continue
        try:
            u = int(h.get('umaban'))
        except Exception:
            continue
        conf = None
        if ax:
            try:
                conf = (ax.axis_confidence_nar(h.get('pop')) if is_nar
                        else ax.axis_confidence(h.get('pop'), h.get('odds')))
            except Exception:
                pass
        axis_info.append({
            'um': u, 'mark': str(h.get('axis_mark')),
            'name': by_um.get(u, '')[:10], 'conf': conf,
            'pop': h.get('pop'), 'odds': h.get('odds'),
        })

    # 相手候補(消去後の残り)
    aite = _ints(groups.get('aite'))
    osae = _ints(groups.get('osae'))
    partners = aite + osae

    # 穴注目
    ana = _ints(groups.get('ana'))
    edge_reasons = aim.get('edge_reasons') or {}

    # 危険人気馬
    veto = set(_ints(aim.get('veto')))
    danger = set(_ints(aim.get('danger'))) | veto
    danger_reasons = aim.get('danger_reasons') or {}

    # 切る
    keshi = _ints(groups.get('keshi'))

    # 買い目
    bets = {}
    if bets_data:
        trio_r = (bets_data.get('trio') or {}).get('result') or {}
        trio_bets = trio_r.get('bets') or []
        if trio_bets:
            bets['trio'] = {'n': len(trio_bets), 'bets': trio_bets[:5],
                            'pattern': ((bets_data.get('trio') or {}).get('extra') or {}).get('pattern', '')}
        tri_r = (bets_data.get('trifecta') or {}).get('result') or {}
        tri_bets = tri_r.get('bets') or []
        if tri_bets:
            bets['trifecta'] = {'n': len(tri_bets), 'bets': tri_bets[:5]}
        wide_r = (bets_data.get('wide') or {}).get('result') or {}
        wide_bets = wide_r.get('wide') or []
        if wide_bets:
            bets['wide'] = {'n': len(wide_bets), 'bets': wide_bets[:3]}

    # 買い目メタ
    buy_meta = None
    try:
        from core import score_cache as sc
        buy_meta = sc.read_buy(race_id)
    except Exception:
        pass

    return {
        'race_id': race_id,
        'meta': meta,
        'race_no': race_no(race_id),
        'gate': gate,
        'forecast': forecast,
        'regime': (cv or {}).get('regime') or '',
        'axis': axis_info,
        'partners': partners,
        'ana': ana,
        'danger': sorted(danger),
        'danger_reasons': danger_reasons,
        'keshi': keshi,
        'bets': bets,
        'buy_meta': buy_meta,
        'by_um': by_um,
        'edge_reasons': edge_reasons,
    }


def build_conclusion_card_html(race_ids, opts=None):
    """結論カード: 1レース1枚の結論だけ圧縮出力。(html, issued_list) を返す。

    opts['exclude_scan']=True(既定): スキャン新聞(scan_digest)に載っているレースは
    結論カードから除外(商品として重複させない)。
    """
    o = dict(opts or {})
    mono = bool(o.get('mono'))
    cards_html = []
    issued = []

    # スキャン新聞に載っているレースを除外(既定ON)
    if o.get('exclude_scan', True):
        try:
            _sd = load_scan_digest() or {}
            _scan_ids = {str(r.get('id')) for r in (_sd.get('rows') or []) if r.get('id')}
            if _scan_ids:
                race_ids = [r for r in race_ids if str(r) not in _scan_ids]
        except Exception:
            pass

    for rid in race_ids:
        d = _conclusion_card_data(rid)
        if not d:
            continue

        meta = d['meta']
        venue = meta.get('venue') or VENUE_BY_CODE.get(str(rid)[4:6], '')
        rno = d['race_no']
        rname = meta.get('race_name') or ''
        n_h = meta.get('n_horses') or ''

        # Gate badge
        gate = d.get('gate') or {}
        gate_status = gate.get('status', '')
        gate_map = {'buy': ('✅ 買い', '#2b8a3e'), 'axis_warn': ('🟡 軸注意', '#e6a700'),
                    'skip': ('⛔ 見送り', '#9e9e9e')}
        gate_lbl, gate_col = gate_map.get(gate_status, ('', '#888'))
        if mono:
            gate_col = '#333'

        # Forecast line
        fc = d.get('forecast') or {}
        fc_parts = []
        if fc.get('arare_prob') is not None:
            fc_parts.append(f"荒れ予報 {float(fc['arare_prob']) * 100:.0f}%")
        regime = d.get('regime')
        if regime:
            fc_parts.append(regime)
        if fc.get('no_fav'):
            fc_parts.append(str(fc['no_fav']))

        # Axis
        axis_parts = []
        for ax in d.get('axis') or []:
            conf_txt = f" (複{ax['conf']:.0f}%)" if ax.get('conf') is not None else ''
            axis_parts.append(f"{_esc(ax['mark'])}{ax['um']} {_esc(ax['name'])}{_esc(conf_txt)}")

        # Partners
        by_um = d.get('by_um') or {}
        partner_parts = []
        for u in d.get('partners') or []:
            partner_parts.append(f"{u}{by_um.get(u, '')[:6]}")

        # Ana（馬番＋馬名のみ。⚡33ラップ適合/🧬血統上位等の根拠ラベルは非表示）
        ana_parts = []
        for u in d.get('ana') or []:
            ana_parts.append(f"{u}{by_um.get(u, '')[:6]}")

        # Danger
        danger_parts = []
        dr = d.get('danger_reasons') or {}
        for u in d.get('danger') or []:
            rs = [str(x) for x in (dr.get(str(u)) or dr.get(u) or [])][:2]
            rtxt = f"({'/'.join(rs)})" if rs else ''
            mark = '🚫' if u in set(_ints((d.get('gate') or {}).get('veto') or (
                ((load_consensus(rid) or {}).get('aim') or {}).get('veto') or []))) else '⚠'
            danger_parts.append(f"{mark}{u}{by_um.get(u, '')[:6]}{_esc(rtxt)}")

        # Bets
        bets_lines = []
        bets_d = d.get('bets') or {}
        if bets_d.get('trio'):
            t = bets_d['trio']
            pat = t.get('pattern') or ''
            bets_lines.append(f"3連複 {_esc(pat)} <b>{t['n']}点</b>")
        if bets_d.get('trifecta'):
            t = bets_d['trifecta']
            bets_lines.append(f"3連単 <b>{t['n']}点</b>")
        if bets_d.get('wide'):
            t = bets_d['wide']
            bets_lines.append(f"ワイド <b>{t['n']}点</b>")
        bm = d.get('buy_meta')
        if bm and bm.get('synth_odds'):
            try:
                bets_lines.append(f"合成オッズ <b>{float(bm['synth_odds']):.1f}倍</b>")
            except Exception:
                pass

        # Keshi
        keshi = d.get('keshi') or []

        # Build card HTML
        card = []
        card.append(f"<div class='ccard'>")
        # Header
        card.append(f"<div class='cc-head' style='border-left-color:{gate_col};'>")
        card.append(f"<span class='cc-venue'>{_esc(venue)}{rno or '?'}R</span>")
        card.append(f"<span class='cc-name'>{_esc(rname)}</span>")
        if n_h:
            card.append(f"<span class='cc-nh'>{n_h}頭</span>")
        if gate_lbl:
            card.append(f"<span class='cc-gate' style='color:{gate_col};'>{_esc(gate_lbl)}</span>")
        card.append("</div>")
        # Forecast
        if fc_parts:
            card.append(f"<div class='cc-fc'>{'　'.join(_esc(p) for p in fc_parts)}</div>")
        # Axis
        if axis_parts:
            card.append(f"<div class='cc-sec'><span class='cc-lbl'>軸</span>"
                        f"<span class='cc-val'>{'　'.join(axis_parts)}</span></div>")
        # Partners
        if partner_parts:
            card.append(f"<div class='cc-sec'><span class='cc-lbl'>相手</span>"
                        f"<span class='cc-val'>{'　'.join(_esc(p) for p in partner_parts)}"
                        f" <i>({len(partner_parts)}頭)</i></span></div>")
        # Ana
        if ana_parts:
            card.append(f"<div class='cc-sec'><span class='cc-lbl'>穴注目</span>"
                        f"<span class='cc-val ana'>{'　'.join(ana_parts)}</span></div>")
        # Danger
        if danger_parts:
            card.append(f"<div class='cc-sec'><span class='cc-lbl'>危険</span>"
                        f"<span class='cc-val danger'>{'　'.join(danger_parts)}</span></div>")
        # Bets
        if bets_lines:
            card.append(f"<div class='cc-sec'><span class='cc-lbl'>買い目</span>"
                        f"<span class='cc-val'>{'　／　'.join(bets_lines)}</span></div>")
        # Keshi (compact)
        if keshi:
            card.append(f"<div class='cc-keshi'>切る: "
                        f"{'・'.join(str(u) for u in keshi)}</div>")
        card.append("</div>")

        cards_html.append('\n'.join(card))
        issued.append({'race_id': rid, 'venue': venue, 'race_no': rno, 'race_name': rname})

    if not cards_html:
        return None, []

    import datetime as _dt
    today = _dt.date.today().strftime('%Y年%m月%d日')
    title = _esc(o.get('title') or '結論カード')
    accent = '#111' if mono else '#b3001b'

    css = f"""
    @page {{ size: A4 portrait; margin: 8mm 7mm; }}
    body {{ font-family: 'Yu Gothic UI','Yu Gothic','Meiryo',sans-serif; color: #111; margin: 0;
            -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .masthead {{ border-bottom: 3px double #111; padding-bottom: 1.5mm; margin-bottom: 3mm;
                 display: flex; align-items: baseline; justify-content: space-between; }}
    .daiji {{ font-family: 'Yu Mincho','MS Mincho',serif; font-size: 18pt; font-weight: 900;
              letter-spacing: 0.08em; color: {accent}; }}
    .issue {{ font-size: 8pt; color: #333; }}
    .grid {{ display: grid; grid-template-columns: 1fr; gap: 3mm; }}
    .ccard {{ border: 1px solid #bbb; border-radius: 2mm; padding: 2.5mm 3mm;
              page-break-inside: avoid; background: #fff; }}
    .cc-head {{ display: flex; align-items: baseline; gap: 2.5mm; border-left: 2.5mm solid #888;
                padding-left: 2mm; margin-bottom: 1.5mm; }}
    .cc-venue {{ font-size: 13pt; font-weight: 900; }}
    .cc-name {{ font-size: 10pt; font-weight: 700; flex: 1; }}
    .cc-nh {{ font-size: 8pt; color: #666; }}
    .cc-gate {{ font-size: 10pt; font-weight: 800; }}
    .cc-fc {{ font-size: 8.5pt; color: #444; margin-bottom: 1.5mm; padding-left: 4mm; }}
    .cc-sec {{ display: flex; align-items: baseline; gap: 2mm; font-size: 9pt;
               padding: 0.8mm 0 0.8mm 4mm; border-bottom: 0.3px solid #eee; }}
    .cc-lbl {{ font-weight: 800; min-width: 3.5em; color: #333; }}
    .cc-val {{ flex: 1; }}
    .cc-val.ana {{ color: #7b1fa2; }}
    .cc-val.danger {{ color: #c62828; }}
    .cc-keshi {{ font-size: 8pt; color: #888; padding: 1mm 0 0 4mm; }}
    .footer {{ font-size: 7pt; color: #666; margin-top: 3mm; border-top: 0.5px solid #aaa;
               padding-top: 1mm; }}
    """
    html = (f"<meta charset='utf-8'><style>{css}</style>"
            f"<div class='masthead'><span class='daiji'>{title}</span>"
            f"<span class='issue'>{today} 発行｜{len(issued)}レース</span></div>"
            f"<div class='grid'>{''.join(cards_html)}</div>"
            f"<div class='footer'>"
            f"軸(◎〇)＝検証済み複勝信頼度に基づく3着内候補　"
            f"相手＝消去エンジン通過後の残り　"
            f"穴注目＝末脚/33ラップ/単複乖離等の検証済みエッジ持ち　"
            f"危険＝検証済みアンチ市場(脆い本命/断層直下/休み明け等)　"
            f"切る＝消去クロス重複3+の強い切り対象"
            f"</div>")
    return html, issued


# ────────────────────────────────────────────────────────────
# 初心者競馬新聞 (Beginner-Friendly Newspaper)
# ────────────────────────────────────────────────────────────

_BEGINNER_MARK = {'honmei': '◎', 'aite': '○', 'osae': '▲', 'ana': '☆', 'keshi': '✖'}
_BEGINNER_MARK_LABEL = {
    'honmei': ('◎ 本命', '最も3着以内に入りやすいと判定された馬'),
    'aite':   ('○ 対抗', '本命に次いで有力な馬'),
    'osae':   ('▲ 単穴', '人気は落ちるが実力が侮れない馬'),
    'ana':    ('☆ 穴馬', '検証済みの強みを持つ人気薄。配当の上乗せ要員'),
    'keshi':  ('✖ 消し', '弱点が重なっており見送り推奨'),
    # 印ではないが凡例に並べる(過去走が無い馬の扱いを誤解させないため)
    'chu':    ('注 データ無し', '過去走の記録が無い馬。弱いのではなく判断材料が無いだけで、'
                              '上位に来ることもあります'),
}
_BEGINNER_COLORS = {
    'honmei': '#e74c3c', 'aite': '#2980b9', 'osae': '#27ae60',
    'ana':    '#8e44ad', 'keshi': '#95a5a6',
}


def _beginner_win_prob(odds):
    """単勝オッズから概算勝率(%)を算出。控除率25%を補正。"""
    try:
        o = float(odds)
        if o <= 0:
            return None
        raw = 100.0 / o
        return min(99, round(raw * 0.80, 1))
    except Exception:
        return None


def _beginner_score_100(records, key='Projected Score'):
    """レース内のProjected Score(or BattleScore)を0-100に正規化。"""
    vals = {}
    for r in records:
        try:
            v = float(r.get(key, ''))
            um = int(r.get('Umaban', 0))
            vals[um] = v
        except (TypeError, ValueError):
            continue
    if not vals:
        return {}
    mn, mx = min(vals.values()), max(vals.values())
    rng = mx - mn if mx > mn else 1
    return {u: round((v - mn) / rng * 80 + 20) for u, v in vals.items()}


def _beginner_waku(rec):
    """枠番を取り出す。view の Waku は '内 2' / '外 7' / '5' の表示文字列なので
    そのまま int() すると必ず失敗して 0 になる(紙面の枠色が全部灰色になる不具合)。"""
    raw = rec.get('Waku', rec.get('枠', ''))
    m = re.search(r'\d+', str(raw))
    if m:
        return int(m.group())
    # Waku欠損時は馬番と頭数から推定できないため0(色なし)を返す
    return 0


def strip_name_deco(name, limit=None):
    """馬名から表示用の装飾( '(🔥)' 等)を外す。

    素で name[:8] のように切ると 'チョコラテ (🔥' と装飾の途中で切れて
    紙面に壊れた文字列が出る。先に装飾を落としてから切ること。
    """
    s = str(name or '')
    s = re.sub(r'\s*[（(][^）)]*[）)]\s*$', '', s).strip()
    s = re.sub(r'[🔥⭐★☆👑💣💀🅑]', '', s).strip()
    return s[:limit] if limit else s


def _beginner_name(rec, limit=14):
    """馬名から装飾を外して切り詰める(初心者紙面用)。"""
    return strip_name_deco(rec.get('Name', rec.get('馬名', '')), limit)


def _beginner_pop(rec):
    m = re.search(r'\d+', str(rec.get('Popularity', rec.get('人気', ''))))
    return int(m.group()) if m else None


def _beginner_odds(rec):
    m = re.search(r'\d+(?:\.\d+)?', str(rec.get('Odds', rec.get('単勝', ''))))
    return float(m.group()) if m else None


def _beginner_place_rate(rec, is_nar=False):
    """馬券内率(=複勝率)。オッズ別の実測カーブ(検証済み)を使う。"""
    try:
        from core import axis_selector as _axs
    except Exception:
        return None
    v = _axs.fuku_rate(_beginner_pop(rec), _beginner_odds(rec), is_nar=is_nar)
    return round(float(v), 1) if v is not None else None


def _beginner_marks(records, cv, scores_100):
    """馬番→(役割キー, 印) を決める。

    合議スナップショット(cv.json)があればそれを最優先で使う。無い場合でも
    紙面が印なしの空同然にならないよう、view列(🎯軸馬候補=AxisMark)と
    総合力順から組み立てる。cv無しは『🏠で解析したが合議未保存』の
    レースで普通に起きる(実際に発行済みPDFが印なしになっていた)。
    """
    groups = (cv.get('groups') or {}) if cv else {}
    out = {}
    if groups:
        # 合議の相手/押さえは頭数が多い(18頭で▲が7頭等)。初心者紙面では
        # 印が多いほど迷うので、総合力の高い順に上限を設けて絞る。
        # 上限は出走頭数に応じて調整する: 12頭で10頭に印が付くと
        # 『ほぼ全馬に印』になり選別の意味が無くなるため(実測で発生)。
        _n = len([r for r in records if _int_or(r.get('Umaban')) is not None])
        if _n >= 15:
            _CAP = {'honmei': 1, 'aite': 1, 'osae': 2, 'ana': 1, 'keshi': 3}
        elif _n >= 11:
            _CAP = {'honmei': 1, 'aite': 1, 'osae': 1, 'ana': 1, 'keshi': 2}
        else:
            _CAP = {'honmei': 1, 'aite': 1, 'osae': 1, 'ana': 1, 'keshi': 1}
        for g, mark in _BEGINNER_MARK.items():
            us = []
            for u in (groups.get(g) or []):
                iu = _int_or(u)
                if iu is not None and iu not in out:
                    us.append(iu)
            us.sort(key=lambda u: -scores_100.get(u, 0))
            for u in us[:_CAP.get(g, 3)]:
                out[u] = (g, mark)
        if out:
            return out

    # ── フォールバック: AxisMark(◎〇▲) → 総合力順 の順に埋める ──
    ranked = sorted(records,
                    key=lambda r: -scores_100.get(_int_or(r.get('Umaban')), 0))
    taken = set()
    for rec in records:
        um = _int_or(rec.get('Umaban'))
        if um is None:
            continue
        am = str(rec.get('AxisMark', '') or '')
        g = ('honmei' if '◎' in am else
             'aite' if ('〇' in am or '○' in am) else
             'osae' if '▲' in am else None)
        if g and g not in {v[0] for v in out.values()}:
            out[um] = (g, _BEGINNER_MARK[g])
            taken.add(um)
    for g in ('honmei', 'aite', 'osae'):
        if g in {v[0] for v in out.values()}:
            continue
        for rec in ranked:
            um = _int_or(rec.get('Umaban'))
            if um is None or um in taken:
                continue
            out[um] = (g, _BEGINNER_MARK[g])
            taken.add(um)
            break

    # ☆穴: 人気薄(6番人気以下)で総合力が最も高い馬(検証済みエッジ帯と同じ発想)
    for rec in ranked:
        um = _int_or(rec.get('Umaban'))
        pop = _beginner_pop(rec)
        if um is None or um in taken or pop is None or pop < 6:
            continue
        out[um] = ('ana', _BEGINNER_MARK['ana'])
        taken.add(um)
        break

    # ✖消し: 総合力が下位の馬。少頭数で2頭消すと印だらけになるので頭数で調整。
    _cut_cap = 2 if len(ranked) >= 11 else 1
    n_cut = 0
    for rec in reversed(ranked):
        if n_cut >= _cut_cap:
            break
        um = _int_or(rec.get('Umaban'))
        if um is None or um in taken:
            continue
        out[um] = ('keshi', _BEGINNER_MARK['keshi'])
        taken.add(um)
        n_cut += 1
    return out


def _int_or(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _beginner_last3(race_id, limit=3):
    """馬番→近走[(馬場記号, 距離, 着順), ...]。score_cacheのfull.json(PastRuns)から取る。
    view.jsonには過去走が入っていないためこちらを参照する。

    ⚠ 全レースで取れるわけではない:
      ・地方競馬かんたん新聞の経路(race_idが'NAR'始まり)はfull.jsonを書かない
      ・nar.netkeibaはPast走セルが無い開催があり PastRuns=[] になる
        (南関東4場はnankan_scraperのブリッジで埋まるが門別等は埋まらない)
    取れなかったレースは空dictを返し、紙面側で『データなし』と明示する。
    """
    out = {}
    try:
        d = _read_full(race_id)
    except Exception:
        return out
    for rec in ((d or {}).get('records') or []):
        um = _int_or(rec.get('Umaban'))
        if um is None:
            continue
        runs = []
        for pr in (rec.get('PastRuns') or [])[:limit]:
            dist = _int_or(pr.get('Distance'))
            rank = _int_or(pr.get('Rank'))
            if dist and rank:
                s = str(pr.get('Surface') or '')
                surf = 'ダ' if 'ダ' in s else ('芝' if '芝' in s else '')
                runs.append((surf, dist, rank))
        if runs:
            out[um] = runs
    return out


def _beginner_stars(ratio, lo, hi):
    """比率を5段階の★表現にする(lo以下=★1 / hi以上=★5)。"""
    try:
        f = (float(ratio) - lo) / max(hi - lo, 1e-9)
    except (TypeError, ValueError):
        return None
    n = max(1, min(5, int(round(f * 4)) + 1))
    return '★' * n + '☆' * (5 - n)


def _beginner_course_feature(race_id, meta):
    """コースの特徴(先行有利/内枠有利/差し届く)を実測10年分から★表示にする。

    core.track_bias.course_empirical_bias は『そのコースで勝った馬の
    4角3番手以内率/内枠率』の実績集計。予想エッジの主張ではなく
    コース性質の説明として出す(展開・枠はpriced-in＝買い材料にはしない)。
    """
    try:
        from core import track_bias as _tb
        jyo = str(race_id)[4:6]
        dist = _int_or(meta.get('distance'))
        cb = _tb.course_empirical_bias(jyo, meta.get('surface', ''), dist)
    except Exception:
        return None
    if not cb:
        return None
    front = cb.get('front_rate')
    inner = cb.get('inner_rate')
    rows = []
    s = _beginner_stars(front, 0.35, 0.70)
    if s:
        rows.append(('先行有利', s))
    s = _beginner_stars(inner, 0.22, 0.50)
    if s:
        rows.append(('内枠有利', s))
    s = _beginner_stars(1.0 - (front or 0.5), 0.30, 0.65)
    if s:
        rows.append(('差し届く', s))
    if front is not None:
        if front >= 0.55:
            note = 'ハイペースになりにくく、先行馬に有利なコース形態。'
        elif front <= 0.40:
            note = '差し・追い込みも届きやすく、決め手が問われるコース。'
        else:
            note = '極端な脚質の偏りは小さく、力どおりに決まりやすい。'
    else:
        note = ''
    return {'rows': rows, 'note': note, 'n': cb.get('n')}


# 合議の根拠ラベル→初心者向けの言い換え。
# 根拠は2系統ある: build_edge_setsが返す絵文字つき日本語('⭐黄金ライン'等)と、
# 内部キー('spurt_top3'等)。どちらも同じ表に通して絵文字を紙面から締め出す。
_BEGINNER_PLAIN = {
    '黄金ライン': '騎手と厩舎の相性が良い',
    '厩舎当ｺｰｽ': 'このコースが得意な厩舎',
    '厩舎当コース': 'このコースが得意な厩舎',
    '道悪軸': '渋った馬場に強い',
    '末脚top': '終いの脚が上位',
    'spurt_top3': '終いの脚が上位',
    'lap33_fit': 'レースの流れが合う',
    'tanpuku_gap': 'オッズに妙味あり',
    'corrtime_top3': '持ち時計が優秀',
    'golden_line': '騎手と厩舎の相性が良い',
    'blood_power': '血統が合う',
    'glass_fav': '人気ほど堅くない',
    'rotation_long': '休み明け',
    '短距離休み明け': '短距離の休み明けは人気の割に来にくい',
    '中9週+ローテ': '間隔が空きすぎて人気の割に来にくい',
    '半年休み明け': '長い休み明けは人気の割に来にくい',
    'prev_win_demerit': '前走勝ちの反動',
    'front_overbet': '逃げ馬で人気先行',
    'danger_popular_inner': '枠順が不利',
}


def _beginner_plain(label):
    """根拠ラベルを平易な日本語にする。未知ラベルは絵文字と記号を落として返す。"""
    s = str(label or '').strip()
    if not s:
        return ''
    for key, plain in _BEGINNER_PLAIN.items():
        if key in s:
            return plain
    # 未知ラベルは絵文字を除去して素の文字だけ残す(紙面に絵文字を出さない)
    s = re.sub(r'[^\wぁ-んァ-ヶー一-龠々ａ-ｚＡ-Ｚ()（）・%＋+\-]', '', s)
    return s[:12]


def _beginner_style_map(records):
    """レース内の平均位置取りから 馬番→'front'/'back' を返す(上位/下位1/3)。"""
    vals = {}
    for r in records:
        um = _int_or(r.get('Umaban'))
        m = re.search(r'\d+(?:\.\d+)?', str(r.get('AvgPosition', '') or ''))
        if um is not None and m:
            vals[um] = float(m.group())
    if len(vals) < 4:
        return {}
    order = sorted(vals, key=lambda u: vals[u])
    k = max(1, len(order) // 3)
    out = {u: 'front' for u in order[:k]}
    out.update({u: 'back' for u in order[-k:]})
    return out


def _beginner_horse_comment(um, aim, groups, by_um, rec=None, role=None, style=None):
    """馬ごとの一言コメント。

    合議(cv.json)があればその根拠を平易化して使い、無ければ view の列
    (末脚/補正T/33ラップ/脚質/不安要素/人気)から組み立てる。cv無しの
    レースでコメントが全部空になるのを防ぐ。
    """
    reasons = (aim.get('edge_reasons') or {}).get(str(um)) or []
    dangers = (aim.get('danger_reasons') or {}).get(str(um)) or []
    combo = int((aim.get('combo') or {}).get(str(um), 0))

    if role is None:
        for g in ('honmei', 'aite', 'osae', 'ana', 'keshi'):
            if um in [int(x) for x in (groups.get(g) or [])]:
                role = g
                break

    parts = []
    if role == 'honmei':
        parts.append('崩れにくい軸馬。')
    elif role == 'aite':
        parts.append('能力上位。相手筆頭。')
    elif role == 'osae':
        parts.append('展開が向けば上位争い。')
    elif role == 'ana':
        parts.append('人気薄だが一発あり。')
    elif role == 'keshi':
        parts.append('今回は様子見。')

    if reasons:
        simplified = [s for s in (_beginner_plain(r) for r in reasons[:2]) if s]
        if simplified:
            parts.append('強み: ' + '、'.join(simplified))

    if dangers:
        simp_d = [s for s in (_beginner_plain(d) for d in dangers[:2]) if s]
        if simp_d:
            parts.append('注意: ' + '、'.join(simp_d))

    if combo >= 3:
        parts.append(f'好材料が{combo}個重複 → 要注目')
    elif combo == 2:
        parts.append('好材料が2個重複')

    # ── cv由来の材料が無い場合は view 列から拾う ──
    if rec is not None and len(parts) <= 1:
        good, bad = [], []
        # 脚質はレース内の相対順位で言う。PCIType('前傾型'等)をそのまま使うと
        # ダート短距離では全馬が同じ型になり『先行力あり』が全馬に並んで無意味になる。
        if style == 'front':
            good.append('前に行ける脚質')
        elif style == 'back':
            good.append('後方から差す脚質')
        _sp = str(rec.get('SpurtIdx', '') or '')
        if '🔥' in _sp:
            good.append('末脚が上位')
        elif '🐢' in _sp:
            good.append('決め手は信頼できる')
        if '⚡' in _sp:
            bad.append('前崩れ頼みの決め手')
        if '🔵' in str(rec.get('CorrectedT', '') or ''):
            good.append('持ち時計が優秀')
        if '🌀' in str(rec.get('Lap33', '') or ''):
            good.append('流れが向く')
        _al = str(rec.get('Alert', '') or '')
        if '🔥+F' in _al:
            good.append('人気薄だが好材料あり')
        if '💣' in _al or '💀' in _al:
            bad.append('人気ほど信頼できない')
        _rf = str(rec.get('RiskFlags', '') or '')
        if _rf and _rf not in ('-', 'nan', 'None'):
            bad.append(_rf.replace(',', '・')[:18])
        # ✖消しの馬に長所を並べると初心者には矛盾して見えるので短所だけにする
        if good and role != 'keshi':
            parts.append('　'.join(good[:2]) + '。')
        if bad:
            parts.append('注意: ' + '・'.join(bad[:2]) + '。')

    return ' '.join(parts) if parts else ''


def _beginner_recommended_bets(cv, records, marks=None):
    """初心者向けのかんたん買い目。

    合議(cv.json)があればその本命/相手/押さえを使う。無い場合は
    marks(_beginner_marksのフォールバック結果)から組み立てて、
    紙面から買い目セクションが丸ごと消えないようにする。
    """
    groups = (cv.get('groups') or {}) if cv else {}
    honmei = [int(x) for x in (groups.get('honmei') or [])]
    aite = [int(x) for x in (groups.get('aite') or [])]
    osae = [int(x) for x in (groups.get('osae') or [])]
    if not honmei and marks:
        _by_role = {}
        for u, (g, _m) in marks.items():
            _by_role.setdefault(g, []).append(u)
        honmei = _by_role.get('honmei') or []
        aite = _by_role.get('aite') or []
        osae = (_by_role.get('osae') or []) + (_by_role.get('ana') or [])
    if not honmei:
        return ''

    # 買い目の馬名も装飾( '(🔥)' 等)を外す。_names_by_um は表示名そのままなので
    # 『5番マイネルラジェム (🔥)』のように紙面へ絵文字が出てしまう。
    by_um = {}
    for r in records:
        u = _int_or(r.get('Umaban'))
        if u is not None:
            by_um[u] = _beginner_name(r)

    # 券種は馬連・馬単の2つだけに絞る(初心者が最初に買うのはこの2つ。
    # 3連複/ワイドまで載せると紙面が縦に伸びて1レース1ページに収まらない)。
    axis = honmei[0]
    partners = [u for u in (aite + osae) if u != axis][:3]
    if not partners:
        return ''

    _WAKU_BG = {1: '#fff', 2: '#000', 3: '#c00', 4: '#00f',
                5: '#ff0', 6: '#0a0', 7: '#f80', 8: '#f69'}
    waku_of = {}
    for r in records:
        u = _int_or(r.get('Umaban'))
        if u is not None:
            waku_of[u] = _beginner_waku(r)

    def _chip(u):
        w = waku_of.get(u, 0)
        bg = _WAKU_BG.get(w, '#ddd')
        fg = '#fff' if w in (2, 3, 4, 6) else '#000'
        return (f"<span class='bchip' style='background:{bg};color:{fg};'>{u}</span>")

    axis_chip = _chip(axis)
    partner_chips = ''.join(_chip(u) for u in partners)
    n = len(partners)

    return (
        f"<div class='bg-betgrid'>"
        f"<div class='bg-bet'>"
        f"<div class='bg-bet-title'>馬連（軸1頭ながし）</div>"
        f"<div class='bg-bet-line'>{axis_chip}<span class='bop'>－</span>{partner_chips}</div>"
        f"<div class='bg-bet-meta'>{n}点　2頭が1・2着（順不同）／的中しやすさ ★★★☆☆</div>"
        f"</div>"
        f"<div class='bg-bet'>"
        f"<div class='bg-bet-title'>馬単（1着固定）</div>"
        f"<div class='bg-bet-line'>{axis_chip}<span class='bop'>→</span>{partner_chips}</div>"
        f"<div class='bg-bet-meta'>{n}点　{axis}番が1着で相手が2着／配当 ★★★☆☆</div>"
        f"</div></div>"
        f"<div class='bg-bet-axis'>軸 = {_esc(str(axis))}番 {_esc(by_um.get(axis, ''))}</div>")


def build_beginner_newspaper_html(race_ids, opts=None):
    """初心者向けの競馬新聞HTMLを組版する。

    既存の build_newspaper_html とは独立した簡潔なレイアウト。
    大きなフォント・色分け・平易な用語・かんたん買い目を提供する。
    戻り値: (html_str, issued_list) / データ無しは ('', [])。
    """
    o = dict(opts or {})
    title = o.get('title', 'かんたん競馬新聞')
    subtitle = o.get('subtitle', '')
    import datetime as _dt
    today = subtitle or _dt.date.today().strftime('%Y年%m月%d日')

    issued = []
    race_blocks = []

    skipped_races = []
    for rid in race_ids:
        v = load_view(rid)
        if not v:
            continue
        records = v.get('records') or []
        if not records:
            continue
        meta = v.get('meta') or {}
        # 新馬戦は収録しない。全馬が過去走ゼロで、末脚・持ち時計・33ラップ等の
        # 検証済み材料が丸ごと使えず、印も買い目も根拠が無いまま並ぶだけになる
        # (2026-07-31 川崎4R新馬では✖消しにした馬が2着)。初心者向けに
        # 『当てられない材料で当てられるように見せる』のは避ける。
        if '新馬' in str(meta.get('race_name', '') or ''):
            skipped_races.append(
                f"{meta.get('venue', '')}{race_no(rid) or ''}R "
                f"{meta.get('race_name', '')}")
            continue
        cv = load_consensus(rid)

        groups = (cv.get('groups') or {}) if cv else {}
        aim = (cv.get('aim') or {}) if cv else {}
        forecast = (cv.get('forecast') or {}) if cv else {}
        by_um = _names_by_um(records)

        score_key = 'Projected Score' if any(
            r.get('Projected Score') for r in records) else 'BattleScore'
        scores_100 = _beginner_score_100(records, score_key)
        mark_by_um = _beginner_marks(records, cv, scores_100)
        _is_nar = str(rid)[4:6].isdigit() and int(str(rid)[4:6]) > 10
        last3 = _beginner_last3(rid)
        style_map = _beginner_style_map(records)

        rn = race_no(rid)
        surface = f"{meta.get('surface', '')}{meta.get('distance', '')}m" \
            if meta.get('distance') else str(meta.get('surface') or '')
        cond = meta.get('condition', '')
        post_time = meta.get('post_time', '')
        arare = forecast.get('arare_prob')
        if arare is None:
            # 合議スナップショットが無いレースでも荒れ度を出す(検証済みロジット。
            # オッズ列だけで計算できるので view から復元する)。
            try:
                from core import value_scanner as _vs_bg
                _ol = [o for o in (_beginner_odds(r) for r in records) if o]
                if _ol:
                    arare = _vs_bg.arare_prob(_ol, meta, len(records))
            except Exception:
                arare = None
        arare_pct = round(float(arare) * 100) if arare is not None else None

        # 頭数で密度を切り替える(A4縦1枚に1レースを収めるため)。
        # 実測: 既定の行高53pxでは10頭まで。18頭は1行36px以内に詰める必要がある。
        _nh = len(records)
        _dens = '' if _nh <= 10 else ('dz' if _nh <= 13 else 'dzz')
        race_html = f"<div class='bg-race {_dens}'>".replace(' ">', '">')
        race_html += (
            f"<div class='bg-race-hdr'>"
            f"<span class='bg-venue'>{_esc(meta.get('venue', '?'))} {rn or '?'}R</span>"
            f"<span class='bg-rname'>{_esc(meta.get('race_name', ''))}</span>"
            f"</div>")
        # ── レース情報 / コースの特徴 / 荒れ度 の3枚組ボックス ──
        _rows_info = []
        if surface:
            _rows_info.append(('コース', surface))
        if cond:
            _rows_info.append(('馬場', str(cond)))
        if post_time:
            _rows_info.append(('発走時刻', str(post_time)))
        _rows_info.append(('頭数', f"{meta.get('n_horses', len(records))}頭立て"))
        if meta.get('date'):
            _rows_info.append(('日付', str(meta['date'])))
        _info_html = ''.join(
            f"<div class='bg-i-row'><span class='bg-i-k'>{_esc(k)}</span>"
            f"<span class='bg-i-v'>{_esc(v)}</span></div>" for k, v in _rows_info)

        _cf = _beginner_course_feature(rid, meta)
        _cf_html = ''
        if _cf and _cf['rows']:
            _cf_html = (
                f"<div class='bg-box'><div class='bg-box-ttl'>"
                f"コースの特徴（{_esc(meta.get('venue', ''))}{_esc(surface)}）</div>")
            for _k, _stars in _cf['rows']:
                _cf_html += (f"<div class='bg-i-row'><span class='bg-i-k'>{_esc(_k)}</span>"
                             f"<span class='bg-stars'>{_esc(_stars)}</span></div>")
            if _cf.get('note'):
                _cf_html += f"<div class='bg-cf-note'>{_esc(_cf['note'])}</div>"
            _cf_html += "</div>"

        _ar_html = ''
        if arare_pct is not None:
            _lv = max(1, min(6, int(round(arare_pct / 100 * 6)) or 1))
            if arare_pct >= 60:
                _ar_lbl, _ar_col = '高め', '#e74c3c'
                _ar_tip = '波乱含み。☆穴馬も相手に入れると配当アップのチャンス。'
            elif arare_pct >= 40:
                _ar_lbl, _ar_col = 'ふつう', '#f39c12'
                _ar_tip = 'やや荒れ模様。人気馬だけに頼らない方が無難。'
            else:
                _ar_lbl, _ar_col = '低め', '#27ae60'
                _ar_tip = '堅い決着が多い。本命◎を中心に組み立てを。'
            _cells = ''.join(
                f"<span class='bg-ar-cell' style='background:"
                f"{_ar_col if _i < _lv else '#e5e8ea'};'></span>" for _i in range(6))
            _ar_html = (
                f"<div class='bg-box'><div class='bg-box-ttl'>荒れ度</div>"
                f"<div class='bg-ar-wrap'><span class='bg-ar-lbl'>{_esc(_ar_lbl)}</span>"
                f"{_cells}</div>"
                f"<div class='bg-cf-note'>荒れ予報 {arare_pct}% — {_esc(_ar_tip)}</div></div>")
        else:
            # 荒れ度はオッズの散らばりから出すため、解析時にオッズが未発表だと
            # 出せない。枠ごと消すと『表示バグ』に見えるので理由を出す。
            _ar_html = (
                "<div class='bg-box'><div class='bg-box-ttl'>荒れ度</div>"
                "<div class='bg-cf-note'>オッズが未取得のため算出できません。"
                "オッズが出てから🏠 Single Race Analysisで解析し直すと表示されます。"
                "</div></div>")

        _pp_b = meta.get('pace_prediction')
        _pace_html = ''
        if _pp_b:
            _pace_html = (
                f"<div class='bg-cf-note' style='color:#c0392b;font-weight:700;'>"
                f"展開よそう: {_esc(_pp_b.get('pace', ''))}ペース — "
                f"{_esc(_pp_b.get('comment', ''))}</div>")

        race_html += (
            f"<div class='bg-infogrid'>"
            f"<div class='bg-box'><div class='bg-box-ttl'>レース情報</div>{_info_html}</div>"
            f"{_cf_html}{_ar_html}</div>{_pace_html}")

        # ── 新馬戦/データ皆無レースの警告 ──
        # 過去走が無い馬ばかりのレースは、末脚・補正T・33ラップ等の検証済み材料が
        # 全部欠ける。総合点は血統と騎手くらいしか根拠が無く、印も買い目も
        # 「材料が無いまま並べただけ」になる。実際 2026-07-31 川崎4R(新馬)では
        # ✖消しにした馬が2着に来た。読み手が数字を信用しすぎないよう明示する。
        _nodata_n = sum(1 for r in records
                        if not (last3.get(_int_or(r.get('Umaban'))) or []))
        _is_shinba = '新馬' in str(meta.get('race_name', '') or '')
        _low_info = _is_shinba or (_nodata_n >= max(1, int(len(records) * 0.7)))
        if _low_info:
            race_html += (
                "<div class='bg-warn'>⚠ "
                + ("<b>新馬戦です。</b>" if _is_shinba else "<b>過去走データがほとんどありません。</b>")
                + "出走馬の過去走が無いため、末脚・持ち時計などの判断材料が使えません。"
                "下の総合点・印・買い目は<b>参考度が大きく下がります</b>"
                "（見送りも有力な選択です）。</div>")

        def _sort_key(r):
            um = _int_or(r.get('Umaban'), 99)
            g = mark_by_um.get(um, ('z',))[0]
            # 買う印(◎○▲☆)を上に集め、それ以外(無印と✖)は総合力順で並べる。
            # ✖だけを最後に固定すると『20点の無印が51点の✖より上』になり
            # 点数順が崩れて見えるため、✖も無印と同じ扱いにする。
            order = {'honmei': 0, 'aite': 1, 'osae': 2, 'ana': 3}
            return (order.get(g, 5), -scores_100.get(um, 0))
        sorted_records = sorted(records, key=_sort_key)

        # ── 出走表(参考デザイン準拠の表組み: 印/馬番/馬名/総合点/馬券内率/近3走/コメント) ──
        _WAKU_BG = {1: '#fff', 2: '#000', 3: '#c00', 4: '#00f',
                    5: '#ff0', 6: '#0a0', 7: '#f80', 8: '#f69'}
        race_html += (
            "<table class='bg-tbl'><thead><tr>"
            "<th class='c-mark'>印</th><th class='c-um'>馬番</th>"
            "<th class='c-name'>馬名<span class='th-sub'>騎手（斤量）</span></th>"
            "<th class='c-score'>総合点<span class='th-sub'>100点満点</span></th>"
            "<th class='c-rate'>馬券内率</th>"
            "<th class='c-last3'>近3走<span class='th-sub'>距離・着順</span></th>"
            "<th class='c-cmt'>コメント</th>"
            "</tr></thead><tbody>")
        for r in sorted_records:
            um = _int_or(r.get('Umaban'))
            if um is None:
                continue
            name = _beginner_name(r)
            jockey = str(r.get('Jockey', r.get('騎手', '')) or '').strip()[:8]
            futan = str(r.get('WeightCarried', '') or '').strip()
            waku = _beginner_waku(r)
            odds_val = _beginner_odds(r)
            score = scores_100.get(um, 50)
            role_key, mark_char = mark_by_um.get(um, (None, ''))
            # role='' は『印を絞った結果この馬は無印』の意味。Noneを渡すと
            # コメント側が合議groupsから役割を引き直し、無印馬に
            # 『相手筆頭』等が出てしまう(印と本文が食い違う)。
            comment = _beginner_horse_comment(um, aim, groups, by_um,
                                              rec=r, role=(role_key or ''),
                                              style=style_map.get(um))
            # 多頭数はコメントが2〜3行に折り返して行高を押し上げるので刈り込む
            _cmax = 44 if not _dens else (32 if _dens == 'dz' else 24)
            if len(comment) > _cmax:
                comment = comment[:_cmax].rstrip('　 、。') + '…'
            place_rate = _beginner_place_rate(r, is_nar=_is_nar)
            mark_color = _BEGINNER_COLORS.get(role_key, '#bbb')
            waku_bg = _WAKU_BG.get(waku, '#ddd')
            waku_fg = '#fff' if waku in (2, 3, 4, 6) else '#000'
            bar_w = max(5, min(100, score))
            bar_color = ('#e74c3c' if role_key == 'honmei' else
                         '#27ae60' if score >= 70 else
                         '#f39c12' if score >= 40 else '#95a5a6')

            # 2段表示: 上段=馬場+距離 / 下段=着順。1行に詰めると数字が並んで読めない。
            _l3 = ''.join(
                f"<span class='l3'><span class='l3d'>{_esc(_sf)}{_d}</span>"
                f"<span class='l3r r{min(_rk, 4)}'>{_rk}着</span></span>"
                for _sf, _d, _rk in (last3.get(um) or []))
            _jt = _esc(jockey) + (f"（{_esc(futan)}）" if futan and futan != '-' else '')
            _od = f"{odds_val:.1f}倍" if odds_val is not None else '-'
            _pr = f"{place_rate:.1f}%" if place_rate is not None else '-'

            # 注: 過去走データが無い馬(転入初戦・新馬・出典に記録なし)。
            # 弱いのではなく『判断材料が無い』だけで、実際に上位に来ることがある
            # (2026-07-31 川崎2R 10番=データ無しで2着)。スコアは材料不足で低めに
            # 出るため、読み手が誤って軽視しないよう明示する。
            _nodata = not (last3.get(um) or [])
            _mark_cell = (mark_char if mark_char
                          else ("<span class='m-chu'>注</span>" if _nodata else ''))
            _name_chu = ("<span class='chu-chip'>注</span>"
                         if (_nodata and mark_char) else '')

            race_html += (
                f"<tr class='{'row-cut' if role_key == 'keshi' else ''}'>"
                f"<td class='c-mark' style='color:{mark_color};'>{_mark_cell}</td>"
                f"<td class='c-um'><span class='umb' style='background:{waku_bg};"
                f"color:{waku_fg};'>{um}</span></td>"
                f"<td class='c-name'><span class='hn'>{_esc(name)}{_name_chu}</span>"
                f"<span class='hj'>{_jt}</span></td>"
                f"<td class='c-score'><span class='sc'>{score}</span><span class='scu'>点</span>"
                f"<div class='bar-bg'><div class='bar' style='width:{bar_w}%;"
                f"background:{bar_color};'></div></div>"
                f"<span class='odds'>{_od}</span></td>"
                f"<td class='c-rate'>{_pr}</td>"
                f"<td class='c-last3'>{_l3 or '<span class=\"nod\">データなし</span>'}</td>"
                f"<td class='c-cmt'>{_esc(comment)}</td>"
                f"</tr>")
        race_html += "</tbody></table>"

        # 近3走が1頭も取れなかったレースは理由を明示(空欄=不具合と誤解されるため)
        if not last3:
            race_html += (
                "<div class='bg-cf-note'>※ このレースは過去走データを取得できていないため"
                "「近3走」が空欄です（地方競馬はサイト側に過去走欄が無い開催があります）。"
                "🏠 Single Race Analysis で解析し直すと表示される場合があります。</div>")

        bets_html = _beginner_recommended_bets(cv, records, marks=mark_by_um)
        if bets_html:
            _bet_note = ("※ <b>このレースは判断材料が乏しいため、この買い目の信頼度は"
                         "低いです。</b>見送りも有力です。" if _low_info else
                         "※ 合議結果をもとにした参考例です。的中を保証するものでは"
                         "ありません。")
            race_html += (
                f"<div class='bg-bets-section'>"
                f"<div class='bg-section-title'>かんたん買い目ガイド</div>"
                f"<div class='bg-bets-note'>{_bet_note}</div>"
                f"{bets_html}</div>")

        race_html += "</div>"

        issued.append({
            'race_id': rid, 'label': race_label({'race_id': rid, 'meta': meta}),
            'n_rows': len(records), 'n_cols': 0, 'source': v.get('source', 'view'),
        })
        race_blocks.append(race_html)

    if not race_blocks:
        return '', []

    guide_html = (
        "<div class='bg-guide'>"
        "<div class='bg-section-title'>印の見かた（はじめての方へ）</div>"
        "<div class='bg-guide-grid'>")
    for g in ('honmei', 'aite', 'osae', 'ana', 'keshi', 'chu'):
        lbl, desc = _BEGINNER_MARK_LABEL[g]
        col = _BEGINNER_COLORS.get(g, '#b26a00')
        guide_html += (
            f"<div class='bg-guide-item' style='border-left: 4px solid {col};'>"
            f"<span class='bg-guide-mark' style='color:{col};'>{_esc(lbl)}</span>"
            f"<span class='bg-guide-desc'>{_esc(desc)}</span></div>")
    guide_html += "</div>"
    guide_html += (
        "<div class='bg-guide-tips'>"
        "<b>初心者のためのヒント</b>"
        "<ul>"
        "<li><b>まず馬連から。</b>選んだ2頭が1・2着に入れば当たり（順番は問いません）。</li>"
        "<li><b>馬単</b>は「1着まで当てる」ぶん難しいですが、その分だけ配当が上がります。</li>"
        "<li><b>荒れ予報が高い時</b>は☆穴馬も相手に入れると配当アップのチャンス。</li>"
        "<li><b>✖消しの馬</b>は弱点が多いので、買い目から外すことで点数を減らせます。</li>"
        "<li><b>総合点のバー</b>が長い馬ほど、このレースで力を発揮しやすいと判定しています。</li>"
        "<li><b>馬券内率</b>は「3着以内に入る割合」の実測目安（オッズ帯ごとの過去実績）です。</li>"
        "<li><b>近3走</b>は直近3レースの「距離」と「着順」。同じ距離で好走していれば好材料。</li>"
        "</ul></div></div>")

    css = f"""
    @page {{ size: A4 portrait; margin: 8mm; }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Hiragino Kaku Gothic ProN', 'Meiryo', 'Yu Gothic', sans-serif;
            font-size: 11pt; color: #2c3e50; background: #fff; }}
    .bg-page {{ max-width: 210mm; margin: 0 auto; padding: 5mm; }}
    .bg-masthead {{ background: linear-gradient(135deg, #1a5276, #2980b9);
                    color: #fff; padding: 6mm 8mm; border-radius: 4mm;
                    margin-bottom: 5mm; page-break-inside: avoid; }}
    .bg-daiji {{ font-size: 22pt; font-weight: 900; display: block; letter-spacing: 2px; }}
    .bg-issue {{ font-size: 10pt; opacity: 0.85; display: block; margin-top: 2mm; }}
    /* 1レース=1ページ。表紙(印の見かた)と同居させると溢れるので必ず改ページする */
    .bg-race {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 3mm;
                padding: 3mm; margin-bottom: 0; page-break-inside: avoid;
                page-break-before: always; }}
    .bg-race-hdr {{ display: flex; align-items: baseline; gap: 3mm; margin-bottom: 1.5mm;
                    border-bottom: 2px solid #2980b9; padding-bottom: 1.5mm; }}
    .bg-venue {{ font-size: 13pt; font-weight: 900; color: #1a5276; }}
    .bg-rname {{ font-size: 12pt; font-weight: 700; color: #2c3e50; }}
    .bg-race-info {{ font-size: 9.5pt; color: #555; margin-bottom: 2mm; }}
    /* レース情報 / コースの特徴 / 荒れ度 の3枚組 */
    .bg-infogrid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 2mm;
                    margin-bottom: 2mm; }}
    .bg-box {{ background: #fff; border: 1px solid #d6dde3; border-radius: 2mm;
               padding: 1.5mm 2mm; }}
    .bg-box-ttl {{ font-size: 8.2pt; font-weight: 800; color: #fff; background: #1a5276;
                   border-radius: 1mm; padding: 0.6mm 1.5mm; margin-bottom: 1mm;
                   text-align: center; }}
    .bg-i-row {{ display: flex; justify-content: space-between; align-items: baseline;
                 font-size: 7.8pt; padding: 0.3mm 0; }}
    .bg-i-k {{ color: #1a5276; font-weight: 700; }}
    .bg-i-v {{ color: #2c3e50; }}
    .bg-stars {{ color: #f39c12; letter-spacing: 0.3px; font-size: 8.2pt; }}
    .bg-cf-note {{ font-size: 7pt; color: #666; margin-top: 0.8mm; line-height: 1.35; }}
    .bg-ar-wrap {{ display: flex; align-items: center; gap: 0.8mm; }}
    .bg-ar-lbl {{ font-size: 8pt; font-weight: 700; color: #2c3e50; margin-right: 0.8mm; }}
    .bg-ar-cell {{ display: inline-block; width: 3.8mm; height: 2.6mm; border-radius: 0.6mm; }}
    /* 出走表 (A4縦1枚に1レースが収まるよう行を詰めている) */
    .bg-tbl {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
    .bg-tbl thead th {{ background: #f1f5f8; border-bottom: 2px solid #1a5276;
                        color: #1a5276; font-size: 7.5pt; font-weight: 800;
                        padding: 1mm 0.8mm; text-align: center; }}
    .bg-tbl .th-sub {{ display: block; font-size: 6.2pt; font-weight: 500; color: #7a8a99; }}
    .bg-tbl tbody td {{ border-bottom: 1px solid #e6ebef; padding: 0.7mm 0.8mm;
                        vertical-align: middle; }}
    .bg-tbl tr.row-cut {{ background: #fafbfc; color: #97a3ad; }}
    .c-mark {{ width: 6%; text-align: center; font-size: 13pt; font-weight: 900; }}
    .c-um {{ width: 6.5%; text-align: center; }}
    .umb {{ display: inline-block; min-width: 4.8mm; padding: 0.3mm 0.7mm;
            border: 1px solid #666; border-radius: 1mm; font-size: 9pt;
            font-weight: 800; text-align: center; }}
    .c-name {{ width: 21%; }}
    .hn {{ display: block; font-size: 9.5pt; font-weight: 800; color: #1c2b36;
           line-height: 1.12; }}
    .hj {{ display: block; font-size: 6.8pt; color: #78868f; line-height: 1.15; }}
    .c-score {{ width: 18%; text-align: center; }}
    .sc {{ font-size: 11.5pt; font-weight: 900; color: #c0392b; }}
    .scu {{ font-size: 7pt; color: #888; }}
    .bar-bg {{ height: 1.8mm; background: #e9edf0; border-radius: 0.9mm;
               overflow: hidden; margin: 0.5mm 0 0.3mm; }}
    .bar {{ height: 100%; border-radius: 0.9mm; }}
    .odds {{ font-size: 7pt; color: #667; }}
    .c-rate {{ width: 9%; text-align: center; font-size: 9.5pt; font-weight: 700;
               color: #2c3e50; }}
    .c-last3 {{ width: 16%; text-align: center; white-space: nowrap; }}
    .l3 {{ display: inline-block; border: 1px solid #dfe5ea; border-radius: 1mm;
           padding: 0.4mm 1mm; margin: 0 0.3mm; text-align: center;
           background: #fbfcfd; }}
    .l3d {{ display: block; font-size: 6.6pt; color: #66757f; line-height: 1.15; }}
    .l3r {{ display: block; font-size: 8pt; font-weight: 800; line-height: 1.15; }}
    .l3r.r1 {{ color: #c0392b; }} .l3r.r2 {{ color: #1f6fb2; }}
    .l3r.r3 {{ color: #1e8449; }} .l3r.r4 {{ color: #8a949c; }}
    .nod {{ color: #b9c2c9; }}
    .bg-warn {{ background: #fff4e5; border: 1.5px solid #e8a33d; border-radius: 2mm;
                color: #8a5200; font-size: 8pt; line-height: 1.5;
                padding: 1.5mm 2.5mm; margin-bottom: 2mm; }}
    /* 注 = 過去走データが無い馬(弱いのではなく判断材料が無い) */
    .m-chu {{ display: inline-block; font-size: 8.5pt; font-weight: 800; color: #b26a00;
              border: 1.2px solid #e0a34a; background: #fff6e5;
              border-radius: 1mm; padding: 0.1mm 0.9mm; line-height: 1.35; }}
    .chu-chip {{ display: inline-block; font-size: 6.5pt; font-weight: 800; color: #b26a00;
                 background: #fff2dc; border: 1px solid #e6bd80; border-radius: 1mm;
                 padding: 0 0.7mm; margin-left: 1mm; vertical-align: middle; }}
    .c-cmt {{ width: 20%; font-size: 7.2pt; color: #46535e; line-height: 1.4; }}
    .bg-bets-section {{ background: #eaf2f8; border: 1px solid #aed6f1; border-radius: 2mm;
                        padding: 2mm 2.5mm; margin-top: 2mm; }}
    .bg-section-title {{ font-size: 10.5pt; font-weight: 800; color: #1a5276;
                         margin-bottom: 1.2mm; border-bottom: 2px solid #2980b9;
                         padding-bottom: 0.8mm; }}
    .bg-bets-note {{ font-size: 7pt; color: #888; margin-bottom: 1.2mm; }}
    .bg-betgrid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2mm; }}
    .bg-bet {{ background: #fff; border: 1px solid #d5e8f0; border-radius: 2mm;
               padding: 1.2mm 2mm; }}
    .bg-bet-title {{ font-size: 8.5pt; font-weight: 800; color: #1a5276;
                     text-align: center; }}
    .bg-bet-line {{ display: flex; align-items: center; justify-content: center;
                    gap: 0.8mm; margin: 1mm 0 0.8mm; flex-wrap: wrap; }}
    .bchip {{ display: inline-block; min-width: 5.4mm; padding: 0.5mm 1mm;
              border: 1px solid #666; border-radius: 1mm; font-size: 10pt;
              font-weight: 900; text-align: center; }}
    .bop {{ font-size: 10pt; font-weight: 800; color: #55606a; margin: 0 0.5mm; }}
    .bg-bet-meta {{ font-size: 6.8pt; color: #7a858e; text-align: center; }}
    .bg-bet-axis {{ font-size: 7.5pt; color: #46535e; margin-top: 1.2mm;
                    text-align: center; }}
    /* ── 多頭数レース用の密度調整(A4縦1枚に収めるため) ──
       .dz = 11〜14頭 / .dzz = 15頭以上。近3走は2段→1段に畳み、
       スコア/馬名/コメントを段階的に縮める。 */
    .dz .bg-tbl tbody td {{ padding: 0.4mm 0.7mm; }}
    .dz .hn {{ font-size: 8.6pt; }}
    .dz .hj {{ font-size: 6.2pt; }}
    .dz .c-mark {{ font-size: 11pt; }}
    .dz .umb {{ font-size: 8.2pt; padding: 0.2mm 0.6mm; }}
    .dz .sc {{ font-size: 10pt; }}
    .dz .scu {{ font-size: 6.2pt; }}
    .dz .bar-bg {{ height: 1.4mm; margin: 0.35mm 0 0.2mm; }}
    .dz .odds {{ font-size: 6.4pt; }}
    .dz .c-rate {{ font-size: 8.6pt; }}
    .dz .l3 {{ padding: 0.2mm 0.6mm; margin: 0 0.2mm; }}
    .dz .l3d {{ display: inline; font-size: 6.3pt; }}
    .dz .l3r {{ display: inline; font-size: 6.8pt; margin-left: 0.4mm; }}
    .dz .c-cmt {{ font-size: 6.6pt; line-height: 1.28; }}
    .dz .bg-infogrid {{ gap: 1.5mm; margin-bottom: 1.5mm; }}
    .dz .bg-box {{ padding: 1mm 1.5mm; }}
    .dz .bg-bets-section {{ padding: 1.4mm 2mm; margin-top: 1.4mm; }}
    .dz .bg-bet-meta {{ font-size: 6.2pt; }}

    .dzz .bg-tbl tbody td {{ padding: 0.22mm 0.6mm; }}
    .dzz .hn {{ font-size: 7.8pt; line-height: 1.08; }}
    .dzz .hj {{ font-size: 5.6pt; line-height: 1.1; }}
    .dzz .c-mark {{ font-size: 9.5pt; }}
    .dzz .umb {{ font-size: 7.4pt; padding: 0.1mm 0.5mm; }}
    .dzz .sc {{ font-size: 8.8pt; }}
    .dzz .scu {{ font-size: 5.6pt; }}
    .dzz .bar-bg {{ height: 1.1mm; margin: 0.25mm 0 0.15mm; }}
    .dzz .odds {{ font-size: 5.8pt; }}
    .dzz .c-rate {{ font-size: 7.8pt; }}
    .dzz .l3 {{ padding: 0.1mm 0.45mm; margin: 0 0.15mm; }}
    .dzz .l3d {{ display: inline; font-size: 5.7pt; }}
    .dzz .l3r {{ display: inline; font-size: 6.2pt; margin-left: 0.3mm; }}
    .dzz .c-cmt {{ font-size: 5.9pt; line-height: 1.2; }}
    .dzz .bg-tbl thead th {{ padding: 0.6mm 0.6mm; font-size: 6.6pt; }}
    .dzz .bg-tbl .th-sub {{ font-size: 5.4pt; }}
    .dzz .bg-infogrid {{ gap: 1.2mm; margin-bottom: 1.2mm; }}
    .dzz .bg-box {{ padding: 0.8mm 1.2mm; }}
    .dzz .bg-box-ttl {{ font-size: 7.2pt; padding: 0.4mm 1mm; margin-bottom: 0.6mm; }}
    .dzz .bg-i-row {{ font-size: 6.8pt; padding: 0.15mm 0; }}
    .dzz .bg-cf-note {{ font-size: 6pt; margin-top: 0.5mm; }}
    .dzz .bg-stars {{ font-size: 7.2pt; }}
    .dzz .bg-ar-cell {{ width: 3mm; height: 2.1mm; }}
    .dzz .bg-race-hdr {{ margin-bottom: 1mm; padding-bottom: 1mm; }}
    .dzz .bg-venue {{ font-size: 11.5pt; }}
    .dzz .bg-rname {{ font-size: 10.5pt; }}
    .dzz .bg-bets-section {{ padding: 1mm 1.6mm; margin-top: 1mm; }}
    .dzz .bg-section-title {{ font-size: 9pt; margin-bottom: 0.8mm; padding-bottom: 0.5mm; }}
    .dzz .bg-bets-note {{ display: none; }}
    .dzz .bg-bet-title {{ font-size: 7.6pt; }}
    .dzz .bg-bet-line {{ margin: 0.6mm 0 0.5mm; }}
    .dzz .bchip {{ font-size: 8.6pt; min-width: 4.6mm; padding: 0.3mm 0.7mm; }}
    .dzz .bop {{ font-size: 8.6pt; }}
    .dzz .bg-bet-meta {{ font-size: 5.8pt; }}
    .dzz .bg-bet-axis {{ font-size: 6.4pt; margin-top: 0.7mm; }}

    .bg-guide {{ background: #f0f9f4; border: 1px solid #a3d9a5; border-radius: 3mm;
                 padding: 4mm; margin-bottom: 5mm; page-break-inside: avoid; }}
    .bg-guide-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
                      gap: 2mm; margin-bottom: 3mm; }}
    .bg-guide-item {{ background: #fff; padding: 2mm 3mm; border-radius: 2mm;
                      display: flex; flex-direction: column; }}
    .bg-guide-mark {{ font-size: 12pt; font-weight: 900; }}
    .bg-guide-desc {{ font-size: 8.5pt; color: #555; }}
    .bg-guide-tips {{ font-size: 9.5pt; color: #333; line-height: 1.6; }}
    .bg-guide-tips ul {{ padding-left: 5mm; }}
    .bg-guide-tips li {{ margin-bottom: 1mm; }}
    .bg-footer {{ font-size: 7.5pt; color: #999; text-align: center; margin-top: 5mm;
                  border-top: 1px solid #ddd; padding-top: 2mm; }}
    @media print {{
        .bg-race {{ page-break-inside: avoid; }}
        .bg-guide {{ page-break-inside: avoid; }}
    }}
    """

    html = (
        f"<meta charset='utf-8'>"
        f"<style>{css}</style>"
        f"<div class='bg-page'>"
        f"<div class='bg-masthead'>"
        f"<span class='bg-daiji'>{_esc(title)}</span>"
        f"<span class='bg-issue'>{_esc(today)} 発行　{len(issued)}レース収録</span>"
        f"</div>"
        f"{guide_html}"
        f"{''.join(race_blocks)}"
        f"<div class='bg-footer'>"
        + (("収録を見送ったレース（新馬戦＝過去走が無く判断材料が足りないため）: "
            + '　/　'.join(_esc(s) for s in skipped_races) + "<br>")
           if skipped_races else "")
        + f"本紙はAI分析に基づく参考情報です。馬券の購入は自己責任でお願いします。"
        f"「総合力」はレース内での相対的な力関係を示す目安(100=最高/20=最低)であり、"
        f"勝率を意味するものではありません。"
        f"</div></div>")
    return html, issued
