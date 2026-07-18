# -*- coding: utf-8 -*-
"""📊 成績台帳 — 新聞発行の予測と実結果を記録し、的中率・回収率を自動集計する。

データの流れ:
  ① 新聞発行(publish)時に cv.json + bets.json のスナップショットから予測を抽出 → ledger に追加
  ② レース終了後に「結果取得」ボタンで着順+配当を取得 → ledger に結果を書き込み
  ③ 予測 vs 結果を自動照合 → 的中/不的中・回収率を eval に書き込み

台帳ファイル: data/newspaper/track_record.json
"""
import os
import json
import time
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NP_DIR = os.path.join(ROOT, 'data', 'newspaper')
LEDGER_PATH = os.path.join(NP_DIR, 'track_record.json')


def _load_ledger():
    if not os.path.exists(LEDGER_PATH):
        return {'records': []}
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'records': []}


def _save_ledger(led):
    os.makedirs(NP_DIR, exist_ok=True)
    with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
        json.dump(led, f, ensure_ascii=False, indent=2)


def _ints(seq):
    out = []
    for x in (seq or []):
        try:
            out.append(int(x))
        except Exception:
            continue
    return out


def _extract_prediction(race_id):
    """cv.json + bets.json から予測情報を抽出する。"""
    from core import newspaper as np_mod
    cv = np_mod.load_consensus(race_id)
    bets_data = np_mod.load_bets(race_id)
    view = np_mod.load_view(race_id)

    if not cv and not bets_data:
        return None

    pred = {}
    if cv:
        groups = cv.get('groups') or {}
        pred['honmei'] = _ints(groups.get('honmei'))
        pred['aite'] = _ints(groups.get('aite'))
        pred['osae'] = _ints(groups.get('osae'))
        pred['ana'] = _ints(groups.get('ana'))
        pred['keshi'] = _ints(groups.get('keshi'))
        # 軸候補(◎〇)
        axis = []
        for h in (cv.get('horses') or []):
            if h.get('axis_mark'):
                try:
                    axis.append(int(h['umaban']))
                except Exception:
                    pass
        pred['axis'] = axis
        pred['regime'] = cv.get('regime') or ''
        # gate
        fc = cv.get('forecast') or {}
        pred['arare_prob'] = fc.get('arare_prob')

    if bets_data:
        # 3連複
        trio = (bets_data.get('trio') or {}).get('result') or {}
        trio_bets = []
        for b in (trio.get('bets') or []):
            combo = _ints(b.get('combo'))
            if len(combo) == 3:
                trio_bets.append(sorted(combo))
        pred['trio_bets'] = trio_bets
        pred['trio_n_points'] = len(trio_bets)
        # 3連単
        tri = (bets_data.get('trifecta') or {}).get('result') or {}
        trifecta_bets = []
        for b in (tri.get('bets') or []):
            combo = _ints(b.get('combo'))
            if len(combo) == 3:
                trifecta_bets.append(combo)
        pred['trifecta_bets'] = trifecta_bets
        pred['trifecta_n_points'] = len(trifecta_bets)
        # ワイド
        wide = (bets_data.get('wide') or {}).get('result') or {}
        wide_bets = []
        for b in (wide.get('wide') or []):
            combo = _ints(b.get('combo'))
            if len(combo) == 2:
                wide_bets.append(sorted(combo))
        pred['wide_bets'] = wide_bets

    # メタ情報
    meta = {}
    if view and view.get('meta'):
        m = view['meta']
        meta['venue'] = m.get('venue', '')
        meta['date'] = m.get('date', '')
        meta['race_name'] = m.get('race_name', '')
        meta['n_horses'] = m.get('n_horses')
    elif cv:
        meta['venue'] = ''
        meta['date'] = ''
    pred['meta'] = meta

    return pred


def register_race(race_id):
    """新聞発行済みレースを台帳に登録する(重複時はスキップ)。予測をスナップショット化。"""
    led = _load_ledger()
    existing_ids = {r['race_id'] for r in led['records']}
    if race_id in existing_ids:
        return False

    pred = _extract_prediction(race_id)
    if not pred:
        return False

    try:
        race_no = int(str(race_id)[-2:])
    except Exception:
        race_no = None

    record = {
        'race_id': race_id,
        'race_no': race_no,
        'date': (pred.get('meta') or {}).get('date', ''),
        'venue': (pred.get('meta') or {}).get('venue', ''),
        'race_name': (pred.get('meta') or {}).get('race_name', ''),
        'n_horses': (pred.get('meta') or {}).get('n_horses'),
        'registered_at': time.time(),
        'prediction': pred,
        'result': None,
        'eval': None,
    }
    led['records'].append(record)
    _save_ledger(led)
    return True


def register_multiple(race_ids):
    """複数レースを一括登録。戻り値: 登録件数。"""
    count = 0
    for rid in race_ids:
        if register_race(rid):
            count += 1
    return count


def fetch_result(race_id):
    """レース結果(着順+配当)をnetkeibaから取得し台帳に書き込む。"""
    from core.scraper import fetch_comprehensive_result, fetch_race_payouts

    led = _load_ledger()
    rec = None
    for r in led['records']:
        if r['race_id'] == race_id:
            rec = r
            break
    if not rec:
        return None, "台帳に未登録のレースです"

    # 着順取得
    comp = fetch_comprehensive_result(race_id)
    if not comp or not comp.get('horses'):
        return None, "結果ページを取得できませんでした(まだ未確定の可能性)"

    horses = comp['horses']
    # top3 抽出
    ranked = []
    for um_str, h in horses.items():
        try:
            rank = int(h.get('Rank', 99))
            um = int(um_str)
            ranked.append((rank, um))
        except Exception:
            continue
    ranked.sort()
    top3 = [um for rank, um in ranked[:3]]

    # 配当取得
    payouts_raw = fetch_race_payouts(race_id)

    result = {
        'top3': top3,
        'all_ranks': {str(um): rank for rank, um in ranked},
        'payouts': {},
        'fetched_at': time.time(),
    }

    # 配当を整理
    for kind in ('trio', 'trifecta', 'umaren', 'umatan', 'wide', 'fuku', 'tan'):
        entries = payouts_raw.get(kind, [])
        if entries:
            result['payouts'][kind] = entries

    rec['result'] = result
    rec['eval'] = _evaluate(rec)
    _save_ledger(led)
    return rec, None


def fetch_results_batch(race_ids=None):
    """結果未取得の全レース(または指定)の結果を一括取得。戻り値: {race_id: (ok, msg)}。"""
    led = _load_ledger()
    targets = []
    for r in led['records']:
        if r.get('result') is not None:
            continue
        if race_ids is None or r['race_id'] in race_ids:
            targets.append(r['race_id'])

    results = {}
    for rid in targets:
        try:
            _, msg = fetch_result(rid)
            results[rid] = (msg is None, msg or 'OK')
        except Exception as e:
            results[rid] = (False, str(e))
    return results


def _evaluate(record):
    """予測 vs 結果を照合し eval を計算する。"""
    pred = record.get('prediction') or {}
    result = record.get('result')
    if not result or not result.get('top3'):
        return None

    top3 = set(result['top3'])
    top1 = result['top3'][0] if result['top3'] else None
    ev = {}

    # 軸的中: ◎〇のいずれかが3着内
    axis = pred.get('axis') or []
    ev['axis_hit'] = any(u in top3 for u in axis)
    ev['axis_in_top3'] = [u for u in axis if u in top3]

    # 本命グループ的中数
    honmei = pred.get('honmei') or []
    ev['honmei_in_top3'] = len([u for u in honmei if u in top3])

    # 切り馬の生存(低いほど良い): 切った馬が3着内に来てしまった数
    keshi = pred.get('keshi') or []
    ev['keshi_survived'] = len([u for u in keshi if u in top3])
    ev['keshi_survivors'] = [u for u in keshi if u in top3]

    # 3連複
    trio_bets = pred.get('trio_bets') or []
    trio_hit = False
    trio_return = 0
    if trio_bets and len(top3) == 3:
        actual_trio = sorted(top3)
        for combo in trio_bets:
            if sorted(combo) == actual_trio:
                trio_hit = True
                break
        if trio_hit:
            payouts = (result.get('payouts') or {}).get('trio', [])
            for p in payouts:
                if sorted(_ints(p.get('combo'))) == actual_trio:
                    trio_return = int(float(p.get('odds', 0)) * 100)
                    break
    ev['trio_hit'] = trio_hit
    ev['trio_return'] = trio_return
    ev['trio_n_points'] = len(trio_bets)

    # 3連単
    trifecta_bets = pred.get('trifecta_bets') or []
    trifecta_hit = False
    trifecta_return = 0
    if trifecta_bets and len(result['top3']) >= 3:
        actual_trifecta = result['top3'][:3]
        for combo in trifecta_bets:
            if combo == actual_trifecta:
                trifecta_hit = True
                break
        if trifecta_hit:
            payouts = (result.get('payouts') or {}).get('trifecta', [])
            for p in payouts:
                if _ints(p.get('combo')) == actual_trifecta:
                    trifecta_return = int(float(p.get('odds', 0)) * 100)
                    break
    ev['trifecta_hit'] = trifecta_hit
    ev['trifecta_return'] = trifecta_return
    ev['trifecta_n_points'] = len(trifecta_bets)

    # ワイド(複数的中あり得る)
    wide_bets = pred.get('wide_bets') or []
    wide_hits = 0
    wide_return = 0
    if wide_bets and len(top3) >= 2:
        from itertools import combinations
        actual_wide_combos = [sorted(list(c)) for c in combinations(top3, 2)]
        wide_payouts = (result.get('payouts') or {}).get('wide', [])
        for combo in wide_bets:
            if sorted(combo) in actual_wide_combos:
                wide_hits += 1
                for p in wide_payouts:
                    if sorted(_ints(p.get('combo'))) == sorted(combo):
                        wide_return += int(float(p.get('odds', 0)) * 100)
                        break
    ev['wide_hits'] = wide_hits
    ev['wide_return'] = wide_return

    # 総合的中: 何らかのbet推奨が当たった
    ev['any_hit'] = trio_hit or trifecta_hit or wide_hits > 0

    return ev


def get_summary():
    """台帳全体の集計サマリーを返す。"""
    led = _load_ledger()
    records = led.get('records', [])
    total = len(records)
    with_result = [r for r in records if r.get('result')]
    pending = total - len(with_result)

    if not with_result:
        return {
            'total': total, 'with_result': 0, 'pending': pending,
            'axis_rate': None, 'trio_rate': None, 'trio_roi': None,
            'trifecta_rate': None, 'trifecta_roi': None,
            'any_hit_rate': None, 'keshi_precision': None,
            'axis_rate_lo': None, 'trio_rate_lo': None,
            'any_hit_rate_lo': None, 'keshi_precision_lo': None,
            'records': records,
        }

    evaluated = [r for r in with_result if r.get('eval')]
    n = len(evaluated)
    if n == 0:
        return {
            'total': total, 'with_result': len(with_result), 'pending': pending,
            'axis_rate': None, 'trio_rate': None, 'trio_roi': None,
            'trifecta_rate': None, 'trifecta_roi': None,
            'any_hit_rate': None, 'keshi_precision': None,
            'axis_rate_lo': None, 'trio_rate_lo': None,
            'any_hit_rate_lo': None, 'keshi_precision_lo': None,
            'records': records,
        }

    axis_hits = sum(1 for r in evaluated if r['eval'].get('axis_hit'))
    trio_hits = sum(1 for r in evaluated if r['eval'].get('trio_hit'))
    trifecta_hits = sum(1 for r in evaluated if r['eval'].get('trifecta_hit'))
    any_hits = sum(1 for r in evaluated if r['eval'].get('any_hit'))

    # ROI: 投資=点数×100円 / 回収=配当
    trio_invest = sum(r['eval'].get('trio_n_points', 0) for r in evaluated) * 100
    trio_return_total = sum(r['eval'].get('trio_return', 0) for r in evaluated)
    trifecta_invest = sum(r['eval'].get('trifecta_n_points', 0) for r in evaluated) * 100
    trifecta_return_total = sum(r['eval'].get('trifecta_return', 0) for r in evaluated)

    # 切り精度: 切った馬が来なかった率
    keshi_total = sum(len(r['prediction'].get('keshi') or []) for r in evaluated)
    keshi_survived = sum(r['eval'].get('keshi_survived', 0) for r in evaluated)
    keshi_precision = ((keshi_total - keshi_survived) / keshi_total * 100) if keshi_total > 0 else None

    # 『最悪でもこのくらいはある』という保守的な下限(95%信頼)。標本が少ないほど下がる。
    # 実績アピールに使う数字を盛らないための併記用(core/bayes_stats.wilson_lower)。
    from core.bayes_stats import wilson_lower

    def _lo(k, tot):
        v = wilson_lower(k, tot) if tot else None
        return round(v * 100, 1) if v is not None else None

    return {
        'total': total,
        'with_result': len(with_result),
        'pending': pending,
        'n_evaluated': n,
        'axis_hits': axis_hits,
        'axis_rate': round(axis_hits / n * 100, 1) if n else None,
        'axis_rate_lo': _lo(axis_hits, n),
        'trio_hits': trio_hits,
        'trio_rate': round(trio_hits / n * 100, 1) if n else None,
        'trio_rate_lo': _lo(trio_hits, n),
        'trio_roi': round(trio_return_total / trio_invest * 100, 1) if trio_invest > 0 else None,
        'trifecta_hits': trifecta_hits,
        'trifecta_rate': round(trifecta_hits / n * 100, 1) if n else None,
        'trifecta_roi': round(trifecta_return_total / trifecta_invest * 100, 1) if trifecta_invest > 0 else None,
        'any_hits': any_hits,
        'any_hit_rate': round(any_hits / n * 100, 1) if n else None,
        'any_hit_rate_lo': _lo(any_hits, n),
        'keshi_precision': round(keshi_precision, 1) if keshi_precision is not None else None,
        'keshi_precision_lo': (_lo(keshi_total - keshi_survived, keshi_total)
                               if keshi_total > 0 else None),
        'records': records,
    }


def get_records():
    """台帳レコード一覧を返す(日付降順)。"""
    led = _load_ledger()
    recs = led.get('records', [])
    recs.sort(key=lambda r: r.get('date', ''), reverse=True)
    return recs


def get_monthly_summary():
    """月別の集計を返す。"""
    led = _load_ledger()
    months = {}
    for r in led.get('records', []):
        if not r.get('eval'):
            continue
        d = r.get('date', '')
        ym = d[:7] if len(d) >= 7 else 'unknown'
        m = months.setdefault(ym, {
            'n': 0, 'axis_hits': 0, 'trio_hits': 0, 'trifecta_hits': 0,
            'trio_invest': 0, 'trio_return': 0,
            'trifecta_invest': 0, 'trifecta_return': 0,
            'any_hits': 0,
        })
        m['n'] += 1
        ev = r['eval']
        if ev.get('axis_hit'):
            m['axis_hits'] += 1
        if ev.get('trio_hit'):
            m['trio_hits'] += 1
        if ev.get('trifecta_hit'):
            m['trifecta_hits'] += 1
        if ev.get('any_hit'):
            m['any_hits'] += 1
        m['trio_invest'] += ev.get('trio_n_points', 0) * 100
        m['trio_return'] += ev.get('trio_return', 0)
        m['trifecta_invest'] += ev.get('trifecta_n_points', 0) * 100
        m['trifecta_return'] += ev.get('trifecta_return', 0)

    result = []
    for ym in sorted(months.keys(), reverse=True):
        m = months[ym]
        result.append({
            'month': ym,
            'races': m['n'],
            'axis_rate': round(m['axis_hits'] / m['n'] * 100, 1) if m['n'] else 0,
            'trio_rate': round(m['trio_hits'] / m['n'] * 100, 1) if m['n'] else 0,
            'trio_roi': round(m['trio_return'] / m['trio_invest'] * 100, 1) if m['trio_invest'] > 0 else 0,
            'trifecta_rate': round(m['trifecta_hits'] / m['n'] * 100, 1) if m['n'] else 0,
            'trifecta_roi': round(m['trifecta_return'] / m['trifecta_invest'] * 100, 1) if m['trifecta_invest'] > 0 else 0,
            'any_hit_rate': round(m['any_hits'] / m['n'] * 100, 1) if m['n'] else 0,
        })
    return result


def export_summary_text(with_lower=True):
    """noteやSNSに貼れる1行〜数行のテキスト成績表を生成。

    with_lower=True のとき『控えめに見て◯%』(95%信頼の下限)を併記する。
    レース数が少ないうちに的中率を断言すると誇大表示になるため、
    売り物の実績表示では下限を出す(盛らない)のが既定。
    """
    s = get_summary()
    if not s.get('n_evaluated'):
        return "成績データなし（結果未取得）"

    def _lo_txt(key):
        v = s.get(key)
        return f"・控えめに見て{v}%" if (with_lower and v is not None) else ''

    lines = [f"📊 成績台帳（{s['n_evaluated']}R集計）"]
    if s.get('axis_rate') is not None:
        lines.append(f"  軸的中率: {s['axis_rate']}%"
                     f"（{s['axis_hits']}/{s['n_evaluated']}{_lo_txt('axis_rate_lo')}）")
    if s.get('trio_rate') is not None:
        roi_txt = f" / ROI {s['trio_roi']}%" if s.get('trio_roi') is not None else ''
        lines.append(f"  3連複的中率: {s['trio_rate']}%"
                     f"（{s['trio_hits']}/{s['n_evaluated']}{_lo_txt('trio_rate_lo')}）{roi_txt}")
    if s.get('trifecta_rate') is not None:
        roi_txt = f" / ROI {s['trifecta_roi']}%" if s.get('trifecta_roi') is not None else ''
        lines.append(f"  3連単的中率: {s['trifecta_rate']}%"
                     f"（{s['trifecta_hits']}/{s['n_evaluated']}）{roi_txt}")
    if s.get('keshi_precision') is not None:
        lines.append(f"  消去精度: {s['keshi_precision']}%"
                     f"（切った馬が来なかった率{_lo_txt('keshi_precision_lo')}）")
    if with_lower:
        lines.append("  ※「控えめに見て」= レース数が少ない分を差し引いた堅めの数字")
    return '\n'.join(lines)


def delete_record(race_id):
    """台帳から1件削除。"""
    led = _load_ledger()
    led['records'] = [r for r in led['records'] if r['race_id'] != race_id]
    _save_ledger(led)
