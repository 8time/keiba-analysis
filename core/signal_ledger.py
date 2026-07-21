# -*- coding: utf-8 -*-
"""🔬当日シグナル(●等) 前向き検証台帳。

馬番ポジション・パターンスキャナーの 🔬シグナル(T●/T◎/J◎ 等)は
全開催横断でその場で計算するため過去データからバックテストできない。
→ パドック台帳/オッズ記録と同じ『前向き記録』方式で、シグナルが出た馬と
   その3着内結果を貯め、貯まったら人気別ベースと比較して効くか裁く。

記録するもの: シグナルが1つでも出た馬について {馬番, 馬名, 人気, オッズ, シグナル文字列}。
判定: シグナル種別ごとに『3着内率』を、人気別の期待3着内率(axis_selector.fuku_rate)と比較。
      残差(実績−期待)>0 で標本が貯まれば「人気を超えるエッジ」、≈0なら効かない。

自分を騙さない設計: 期待値ベース(人気補正)で見る。生の3着内率は人気馬に付きやすい
シグナルほど高く見えるだけなので必ずベースと比較する。
"""
import os
import json
import time

LEDGER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'signal_ledger.json')


def _load():
    if not os.path.exists(LEDGER_PATH):
        return {'records': {}}
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            d = json.load(f)
        d.setdefault('records', {})
        return d
    except Exception:
        return {'records': {}}


def _save(d):
    try:
        os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
        with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def _signal_flags(sig):
    """シグナル文字列から種別フラグ集合を抽出。例 'J◎ T●' → {'J◎','T●'}。"""
    s = str(sig or '')
    out = set()
    for tok in ('J◎', 'T◎', 'T●'):
        if tok in s:
            out.add(tok)
    return out


def record_signals(race_id, entries, meta=None):
    """🔬シグナルが出た馬を台帳に記録(冪等: 同一race_idは上書き・結果は保持)。

    entries: [{'umaban','name','pop','odds','signal'}...] シグナル非空の馬のみ渡す。
    戻り値: 記録した馬数(0=対象なし/失敗)。
    """
    rows = []
    for e in (entries or []):
        sig = str(e.get('signal', '') or '').strip()
        if not sig or not _signal_flags(sig):
            continue
        try:
            rows.append({
                'umaban': int(e['umaban']),
                'name': str(e.get('name', '') or ''),
                'pop': (int(e['pop']) if e.get('pop') not in (None, '') else None),
                'odds': (float(e['odds']) if e.get('odds') not in (None, '') else None),
                'signal': sig,
            })
        except Exception:
            continue
    if not rows:
        return 0
    d = _load()
    rid = str(race_id)
    prev = d['records'].get(rid, {})
    d['records'][rid] = {
        'date': (meta or {}).get('date', prev.get('date', '')),
        'venue': (meta or {}).get('venue', prev.get('venue', '')),
        'ts': time.time(),
        'entries': rows,
        'result': prev.get('result'),   # 既存の結果は保持
    }
    _save(d)
    return len(rows)


def fetch_result(race_id):
    """結果(3着内)を取得し、各馬のhitを台帳に書く。戻り: (ok, msg)。"""
    from core.scraper import fetch_comprehensive_result
    d = _load()
    rid = str(race_id)
    rec = d['records'].get(rid)
    if not rec:
        return False, "台帳に未登録"
    comp = fetch_comprehensive_result(race_id)
    if not comp or not comp.get('horses'):
        return False, "結果未取得(未確定の可能性)"
    ranked = []
    for um_str, h in comp['horses'].items():
        try:
            ranked.append((int(h.get('Rank', 99)), int(um_str)))
        except Exception:
            continue
    ranked.sort()
    top3 = {um for rank, um in ranked[:3]}
    rec['result'] = {'top3': sorted(top3), 'fetched_at': time.time()}
    for e in rec['entries']:
        e['hit'] = 1 if e['umaban'] in top3 else 0
    _save(d)
    return True, "OK"


def fetch_results_batch():
    """未取得の全レース結果をまとめて取得。戻り: {race_id:(ok,msg)}。"""
    d = _load()
    out = {}
    for rid, rec in d['records'].items():
        if rec.get('result'):
            continue
        out[rid] = fetch_result(rid)
        time.sleep(0.5)
    return out


def summary():
    """シグナル種別ごとの 3着内率 と 人気別期待からの残差 を集計。

    戻り: {'signals': {token: {n, hits, hit_rate, exp_rate, resid, resid_pp}},
           'n_races', 'n_pending', 'total_entries'}
    """
    from core import axis_selector as ax
    d = _load()
    agg = {}   # token -> [n, hits, exp_sum]
    n_races = 0
    n_pending = 0
    total = 0
    for rid, rec in d['records'].items():
        res = rec.get('result')
        if not res:
            n_pending += 1
            continue
        n_races += 1
        is_nar = False
        try:
            is_nar = int(str(rid)[4:6]) > 10
        except Exception:
            pass
        for e in rec['entries']:
            total += 1
            hit = e.get('hit')
            if hit is None:
                continue
            exp = ax.fuku_rate(e.get('pop'), e.get('odds'), is_nar=is_nar)
            exp = (exp / 100.0) if exp is not None else None
            for tok in _signal_flags(e.get('signal')):
                a = agg.setdefault(tok, [0, 0, 0.0, 0])  # n, hits, exp_sum, n_exp
                a[0] += 1
                a[1] += hit
                if exp is not None:
                    a[2] += exp
                    a[3] += 1
    out = {}
    for tok, (n, hits, exp_sum, n_exp) in agg.items():
        hit_rate = hits / n if n else None
        exp_rate = (exp_sum / n_exp) if n_exp else None
        resid = (hit_rate - exp_rate) if (hit_rate is not None and exp_rate is not None) else None
        out[tok] = {
            'n': n, 'hits': hits,
            'hit_rate': round(hit_rate * 100, 1) if hit_rate is not None else None,
            'exp_rate': round(exp_rate * 100, 1) if exp_rate is not None else None,
            'resid_pp': round(resid * 100, 1) if resid is not None else None,
        }
    return {'signals': out, 'n_races': n_races, 'n_pending': n_pending,
            'total_entries': total}


def get_records():
    d = _load()
    return d.get('records', {})
