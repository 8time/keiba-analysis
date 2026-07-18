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
    '42': '浦和', '43': '船橋', '44': '大井', '45': '川崎',
}

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
        for k in ('condition', 'course', 'race_name', 'venue', 'date'):
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
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_view_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({
                'race_id': str(race_id), 'ts': time.time(),
                'meta': m,
                'sort_label': str(sort_label or ''),
                'labels': {c: str((labels or {}).get(c, c)) for c in cols},
                'order': [c for c in (order or []) if c in cols],
                'columns': cols,
                'records': records,
            }, f, ensure_ascii=False, default=str)
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
                'aim': aim_out,
                'forecast': forecast,
            }, f, ensure_ascii=False, default=str)
    except Exception:
        pass


def _pace_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.pace.json")


def write_pace_snapshot(race_id, ctx):
    """展開MAPのコンテキスト(想定隊列pos4/ペース/逃げ馬)を新聞用に保存。"""
    if not race_id or not ctx:
        return
    try:
        os.makedirs(NP_DIR, exist_ok=True)
        with open(_pace_path(race_id), 'w', encoding='utf-8') as f:
            json.dump({'race_id': str(race_id), 'ts': time.time(),
                       'pos4': _jsonable(ctx.get('pos4') or {}),
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


def _bets_path(race_id):
    rid = ''.join(ch for ch in str(race_id) if ch.isalnum())
    return os.path.join(NP_DIR, f"{rid}.bets.json")


def write_bets_snapshot(race_id, kind, result, extra=None):
    """おすすめ買い目エンジンの結果を券種別にマージ保存(kind=trio/trifecta/qe/wide)。"""
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
              'cls', 'cond', 'post_time', 'date_val', 'skips')


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
        return {}, {}
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
        for cname, val in race_level.items():
            out[cname] = val
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
    """セルHTML。狭い列の値を要所で改行する。
    - JPower(騎手力): 『1 👑62(▲+25)』の括弧手前で改行
    - JockeyChange(乗替): 『木幡巧也→丹内』の矢印の後ろで改行
    """
    s = _fmt_cell(v, max_chars)
    if c == 'JPower' and '(' in s:
        s = s.replace('(', '<br>(', 1)
    elif c == 'JockeyChange' and '→' in s:
        s = s.replace('→', '→<br>', 1)
    return s


def _pop_int(v):
    m = re.search(r'\d+', str(v or ''))
    return int(m.group()) if m else 999


DEFAULT_OPTS = {
    'title': '強適競馬新聞',
    'subtitle': '',
    'orientation': 'landscape',   # landscape / portrait
    'scale': 1.0,
    'font_pt': 6.8,
    'row_order': 'app',           # app / umaban / pop
    'col_mode': 'app',            # app(アプリ表示列) / all(全列) / lite(軽量)
    'exclude_cols': [],
    'cell_max': 46,
    'page_per_race': True,
    'keep_table': True,
    'mono': False,
    'sections': {'cover': True, 'consensus': True, 'buymeta': True, 'gate': True,
                 'header_plus': True, 'bets': True, 'pace': True,
                 'elim': True, 'vh': True, 'odds_moves': True,
                 'evidence': True, 'pci': True, 'pace_upset': True, 'stress': True,
                 'alerts': True,
                 'j5': False},   # 騎手係数込みスコア(既定OFF・チェックで紙面に追加)
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
    reg = _esc(cv.get('regime') or '')
    return (f"<div class='cvrow'><span class='regime'>合議レジーム: {reg}</span>"
            + ''.join(cards) + "</div>")


def _buymeta_html(race_id, show_gate=True, show_buy=True):
    try:
        from core import score_cache as sc
    except Exception:
        return '', ''
    badge = ''
    if show_gate:
        g = sc.read_gate(race_id)
        if g and g.get('status'):
            lbl = {'buy': '🟢 買い', 'axis_warn': '🟡 軸注意', 'skip': '⛔ 見送り'}.get(
                g['status'], g['status'])
            lean = f"｜{g['lean']}" if g.get('lean') else ''
            badge = f"<span class='gate'>{_esc(lbl)}{_esc(lean)}</span>"
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


def _bets_html(race_id):
    """SRAで生成した4券種おすすめ買い目(スナップショット)を紙面化。"""
    data = load_bets(race_id)
    if not data:
        return ''
    boxes = []
    d = (data.get('trio') or {})
    bets = (d.get('result') or {}).get('bets')
    if bets:
        pat = (d.get('extra') or {}).get('pattern') or ''
        boxes.append(_exbox(f"🎯 3連複おすすめ（{pat}・{len(bets)}点）", _fmt_bet_list(bets)))
    d = (data.get('trifecta') or {})
    bets = (d.get('result') or {}).get('bets')
    if bets:
        band = ((d.get('result') or {}).get('meta') or {}).get('band_name') or ''
        band_j = {'tight': '堅', 'mid': '中波乱', 'arare': '荒れ'}.get(band, band)
        ttl = f"🎯 3連単おすすめ（{len(bets)}点" + (f"・{band_j}帯" if band_j else '') + "）"
        boxes.append(_exbox(ttl, _fmt_bet_list(bets, arrow=True)))
    d = (data.get('qe') or {})
    res = d.get('result') or {}
    q_txt = _fmt_bet_list(res.get('quinella'))
    e_txt = _fmt_bet_list(res.get('exacta'), arrow=True)
    if q_txt or e_txt:
        body = (f"馬連: {q_txt}" if q_txt else '') + ('<br>' if q_txt and e_txt else '') \
             + (f"馬単: {e_txt}" if e_txt else '')
        boxes.append(_exbox("🎯 馬連/馬単おすすめ", body))
    d = (data.get('wide') or {})
    res = d.get('result') or {}
    w_txt = _fmt_bet_list(res.get('wide'))
    if w_txt:
        ax_txt = f"軸{res.get('axis')}番・" if res.get('axis') else ''
        boxes.append(_exbox(f"🎯 ワイドおすすめ（{ax_txt}厳選3点）", w_txt))
    return ''.join(boxes)


def _pace_html(race_id, records):
    """展開・隊列: 4角想定隊列の1行図＋ペース＋AI展開照合💀。"""
    pc = load_pace(race_id)
    ai_danger = None
    rear = None
    try:
        from core import score_cache as sc
        ai_danger = sc.read_tenkai_danger(race_id)
        rear = sc.read_rear(race_id)
    except Exception:
        pass
    if not pc and not ai_danger:
        return ''
    lines = []
    if pc:
        pos4 = {}
        for k, v in (pc.get('pos4') or {}).items():
            try:
                pos4[int(k)] = float(v)
            except Exception:
                continue
        if pos4:
            ordered = sorted(pos4.items(), key=lambda kv: kv[1])
            front = [str(u) for u, v in ordered if v < 0.35]
            mid = [str(u) for u, v in ordered if 0.35 <= v <= 0.65]
            back = [str(u) for u, v in ordered if v > 0.65]
            lines.append("《4角想定》(前) " + ' '.join(front) + " ｜ " + ' '.join(mid)
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
    if ai_danger:
        nm = '・'.join(f"{u}{by_um.get(u, '')[:6]}" for u in sorted(ai_danger))
        lines.append(f"💀 AI展開照合=両AIが後方帯で合意: {nm}")
    elif rear:
        lines.append("後方グループ(展開MAP): " + '・'.join(str(u) for u in sorted(rear)))
    if not lines:
        return ''
    return _exbox("🗺 展開・隊列", '<br>'.join(_esc(x) for x in lines))


def _elim_html(cv, records, race_id):
    """消去フィルター: 消去クロス重複数の高い馬＋残し馬。"""
    aim = (cv or {}).get('aim') or {}
    keep = None
    try:
        from core import score_cache as sc
        keep = sc.read_keep(race_id)
    except Exception:
        pass
    elim = {}
    for k, v in (aim.get('elim') or {}).items():
        try:
            elim[int(k)] = int(v)
        except Exception:
            continue
    if not elim and not keep:
        return ''
    by_um = _names_by_um(records)
    lines = []
    bad = sorted(((u, c) for u, c in elim.items() if c >= 3), key=lambda x: -x[1])
    if bad:
        lines.append("✖消去クロス重複3+（強気に切る候補）: "
                     + '　'.join(f"✖{c} <b>{u}</b>{_esc(by_um.get(u, '')[:7])}" for u, c in bad))
    warn = sorted(u for u, c in elim.items() if c == 2)
    if warn:
        lines.append("△重複2（相手絞りの弱点フラグ）: " + '・'.join(str(u) for u in warn))
    if keep:
        lines.append("🧹消去エンジン残し馬: " + '・'.join(str(u) for u in sorted(keep)))
    return _exbox("🧹 消去フィルター", '<br>'.join(lines))


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
    er = aim.get('edge_reasons') or {}
    by_um = _names_by_um(records)
    items = []
    for u in cand:
        rs = [str(x) for x in (er.get(str(u)) or er.get(u) or [])][:3]
        sc_txt = f" vh{vh[u]:.2f}" if u in vh else ''
        rtxt = f"〈{'/'.join(rs)}〉" if rs else ''
        items.append(f"{_esc(tiers[u])} <b>{u}</b> {_esc(by_um.get(u, '')[:9])}"
                     f"{_esc(sc_txt)}{_esc(rtxt)}")
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
    return _exbox("🏇 展開分析 & 波乱確率", '<br>'.join(lines)) if lines else ''


def _j5_html(race_id):
    """🏇 騎手係数込み 総合スコア(J5)。SRAで表示していた表をそのまま紙面化。

    影響率スライダー依存の表なので、保存時の重みを併記する(再現性の担保)。
    黄金ライン/DB条件も拾うが、DB条件は外部サイト集計=参考表示である旨を明記する。
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

    head = ('<tr><th>順</th><th>変動</th><th>馬番</th><th>馬名</th><th>騎手</th>'
            '<th>騎手係数</th><th>黄金</th><th>騎手込み</th></tr>')
    body = []
    for r in rows[:18]:
        chg = _f(r, '順位変動')
        # ↑=騎手で評価UP / ↓=DOWN。モノクロでも読めるよう記号のまま出す
        body.append(
            f"<tr><td>{_esc(_f(r, '騎手込み順位'))}</td>"
            f"<td>{_esc(chg)}</td>"
            f"<td><b>{_esc(_f(r, '馬番'))}</b></td>"
            f"<td>{_esc(_f(r, '馬名')[:9])}</td>"
            f"<td>{_esc(_f(r, '騎手')[:6])}</td>"
            f"<td>{_esc(_f(r, '騎手係数'))}</td>"
            f"<td>{_esc(_f(r, '黄金ライン'))}</td>"
            f"<td>{_esc(_f(r, '騎手込みスコア'))}</td></tr>")
    tbl = (f"<table class='sub'><thead>{head}</thead>"
           f"<tbody>{''.join(body)}</tbody></table>")
    note = ("※『変動』は強適スコア順位からの変化(↑＝騎手で評価UP)。"
            "黄金ライン🥇＝騎手×厩舎の連対40%+。"
            "騎手係数は検証済みエッジ強度に合わせた保守的設定。")
    box = _exbox(f"🏇 騎手係数込み 総合スコア{w_txt}",
                 tbl + f"<div class='exnote'>{note}</div>")
    # 8列あるので幅広ボックスにする(標準幅32.8%だと潰れる)
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
            return int(r.get('人気'))
        except Exception:
            return 99
    trap = [r for r in rows if _coef(r) < 0.92 and _pop(r) <= 6]
    if trap:
        lines.append("⚠ 過剰評価トラップ(1-6番人気×係数&lt;0.92): " + '　'.join(
            f"<b>{r.get('馬番')}</b>{_esc(str(r.get('馬名', ''))[:8])}"
            f"({r.get('人気')}人気/係数{_esc(str(r.get('ストレス係数')))})"
            f"〈{_esc(str(r.get('ストレス要因', ''))[:40])}〉" for r in trap))
    debuff = [r for r in rows if _coef(r) < 1.0 and r not in trap]
    if debuff:
        lines.append("デバフ該当: " + '　'.join(
            f"{r.get('馬番')}{_esc(str(r.get('馬名', ''))[:7])}"
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


def build_newspaper_html(race_ids, opts=None):
    """選択レースを1つの印刷用HTMLに組版。(html, 収録情報リスト) を返す。"""
    o = dict(DEFAULT_OPTS)
    o.update(opts or {})
    sec = dict(DEFAULT_OPTS['sections'])
    sec.update((opts or {}).get('sections') or {})
    landscape = o.get('orientation', 'landscape') != 'portrait'
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
        # アプリの強適テーブル色分け(Styler計算済みセルCSS)を継承。モノクロ時と
        # 行数不一致(古いスナップショット)時は適用しない。
        smap = {}
        if not mono and v.get('source') == 'view':
            _sty = load_styles(rid)
            if _sty and int(_sty.get('n_rows') or -1) == len(_recs_all):
                smap = _sty.get('styles') or {}
        cv = load_consensus(rid)
        badge, buyline = _buymeta_html(rid, sec.get('gate'), sec.get('buymeta'))

        rn = race_no(rid)
        cond = f"｜馬場 {meta.get('condition')}" if meta.get('condition') else ''
        surface = f"{meta.get('surface', '')}{meta.get('distance', '')}m" \
            if meta.get('distance') else str(meta.get('surface') or '')
        hdr = (f"<div class='racehdr'>"
               f"<span class='rno'>{_esc(meta.get('venue', '?'))} {rn or '?'}R</span>"
               f"<span class='rname'>{_esc(meta.get('race_name', ''))}</span>"
               f"<span class='rmeta'>{_esc(surface)}{_esc(cond)}"
               f"｜{_esc(str(meta.get('date') or ''))}｜{_esc(str(meta.get('n_horses') or len(records)))}頭"
               f"{'｜' + _esc(v.get('sort_label')) + '順' if v.get('sort_label') else ''}</span>"
               f"{badge}</div>")

        thead = ''.join(
            f"<th class='{_col_slug(c)}'>{_header_cell(labels.get(c, c))}</th>" for c in cols)
        body_rows = []
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
            for c in cols:
                _css = _rsty.get(c)
                _attr = f" style=\"{_esc(_css)}\"" if _css else ''
                _tds.append(f"<td class='{_col_slug(c)}'{_attr}>"
                            f"{_cell_html(c, r.get(c), int(o.get('cell_max') or 0))}</td>")
            body_rows.append(f"<tr class='{' '.join(cls)}'>{''.join(_tds)}</tr>")
        note = ("<div class='fbnote'>※このレースはSRAスナップショット未保存のため代表列で再構成"
                "（🏠で再解析すると表示中の全列が紙面化されます）</div>"
                if v.get('source') == 'full' else '')

        hp_html = _header_plus_html(cv, v, rid) if sec.get('header_plus') else ''
        cv_html = _consensus_html(cv, records, mono) if sec.get('consensus') else ''
        analysis = load_analysis(rid)
        extras = []
        if sec.get('alerts'):
            extras.append(_alerts_html(rid, cv, records))
        if sec.get('bets'):
            extras.append(_bets_html(rid))
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
        extras_html = ''.join(x for x in extras if x)
        if extras_html:
            extras_html = f"<div class='extras'>{extras_html}</div>"

        race_blocks.append(
            f"<section class='race'>"
            f"{hdr}{hp_html}{cv_html}{buyline}"
            f"<table class='kt'><thead><tr>{thead}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table>{note}{extras_html}</section>")
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

    page_size = 'A4 landscape' if landscape else 'A4 portrait'
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
    .extras {{ display: block; margin-top: 1.4mm; font-size: 0; }}
    .exbox {{ border: 0.5px solid #bbb; padding: 0.8mm 1.5mm; font-size: 7.5pt;
              line-height: 1.55; background: #fff; page-break-inside: avoid;
              display: inline-block; vertical-align: top; width: 32.8%;
              margin: 0 0.25% 1.2mm 0; }}
    .exttl {{ font-weight: 800; color: {accent}; display: block;
              border-bottom: 0.5px solid #ddd; margin-bottom: 0.5mm; }}
    .exwide {{ width: 66.2%; }}
    /* exbox内の小テーブル(J5=騎手係数込みスコア等)。紙面の主表(.kt)より一段小さく */
    .sub {{ width: 100%; border-collapse: collapse; font-size: 6.6pt; margin-top: 0.4mm; }}
    .sub th, .sub td {{ border: 0.4px solid #ddd; padding: 0.25mm 0.7mm;
                        text-align: center; white-space: nowrap; }}
    .sub th {{ background: {'#f2f2f2' if mono else '#f7eaec'}; font-weight: 700; }}
    .sub td:nth-child(4), .sub td:nth-child(5) {{ text-align: left; }}
    .exnote {{ font-size: 6.4pt; color: #666; margin-top: 0.4mm; line-height: 1.4; }}
    .albox {{ border-left: 1mm solid #999; padding: 0.7mm 1.5mm; margin: 0.5mm 0;
              font-size: 7.5pt; line-height: 1.5; }}
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
    .regime {{ font-size: 7.5pt; color:#333; writing-mode: vertical-rl; text-orientation: mixed;
               border: 0.5px solid #bbb; padding: 0.6mm 0.4mm; }}
    .cvcard {{ flex: 1; border: 0.5px solid #bbb; padding: 0.5mm 1.2mm; background: #fff;
               min-height: 5mm; }}
    .cvttl {{ font-size: 7.5pt; font-weight: 800; margin-bottom: 0.2mm; }}
    .cvbody {{ font-size: 8pt; line-height: 1.3; }}
    .buymeta {{ font-size: 8pt; color:#222; margin: 0 0 1mm 0; }}
    table.kt {{ border-collapse: collapse; width: 100%; font-size: {font_pt}pt;
                table-layout: auto;
                {'page-break-inside: avoid;' if o.get('keep_table', True) else ''} }}
    table.kt thead {{ display: table-header-group; }}
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
    table.kt th.col-Lap33, table.kt td.col-Lap33 {{ max-width: 13mm; }}          /* 33ラップ: -2文字ぶん(狭める) */
    table.kt th.col-WeightCarried, table.kt td.col-WeightCarried {{ min-width: 8mm; }} /* 斤量: +1文字ぶん */
    tr.zeb td {{ background: #f6f6f6; }}
    tr.top1 td {{ background: {'#f6f6f6' if mono else '#fff3d6'}; }}
    tr.top2 td {{ background: {'#f6f6f6' if mono else '#eef3fb'}; }}
    tr.top3 td {{ background: {'#f6f6f6' if mono else '#f2ece4'}; }}
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

def html_to_pdf(html_str, landscape=True, scale=1.0, page_numbers=True, timeout_s=180):
    """HTML→PDF bytes。Streamlitスレッドのasyncioループ衝突を避けるため別スレッド実行。"""
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
                    format='A4', landscape=bool(landscape), print_background=True,
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
