# -*- coding: utf-8 -*-
"""data/ledger.db から遵守率・逸脱コスト・見送り正答率を集計する。

Usage:
  python scripts/ledger_compliance_report.py           # 集計 + CSV 出力
  python scripts/ledger_compliance_report.py --fetch # 未精算 skips を可能な範囲で自動評価
  python scripts/ledger_compliance_report.py --schema  # スキーマのみ

出力:
  標準出力 … 人間可読レポート
  data/ledger_compliance_report.csv … 指標一覧（0件でもヘッダ付き）
"""
import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from core import money
from core.money import Ledger

DB_PATH = money.LEDGER_DB
OUT_CSV = os.path.join(ROOT, 'data', 'ledger_compliance_report.csv')
MIN_N = 5  # ROI 差の解釈に必要な最小 settled 件数（各群）


def norm_gate(status):
    gs = (status or '').strip()
    if '(' in gs:
        gs = gs.split('(')[0].strip()
    return gs


def is_compliant_bet(row):
    """検証済み Gate: 購入してよいのは buy のみ（classify_loss の運用事故と整合）。"""
    gs = norm_gate(row['gate_status'])
    if gs != 'buy':
        return False
    if row['has_danger']:
        return False
    dev = (row['deviation'] or '').strip()
    if dev and dev not in ('なし',):
        return False
    return True


def roi_pct(rows):
    """settled 行の回収率(%)。rows が空なら None。"""
    if not rows:
        return None
    inv = sum(int(r['stake'] or 0) for r in rows)
    ret = sum(int(r['payout'] or 0) for r in rows)
    if inv <= 0:
        return None
    return ret / inv * 100.0


def ts_range(rows, col='ts'):
    vals = [r[col] for r in rows if r[col]]
    if not vals:
        return None, None
    return min(vals), max(vals)


def dump_schema(con):
    print('=== ledger.db schema ===')
    print('path:', DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for (t,) in cur.fetchall():
        if t.startswith('sqlite_'):
            continue
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        n = cur.fetchone()[0]
        cur.execute(f'PRAGMA table_info("{t}")')
        cols = [x[1] for x in cur.fetchall()]
        print(f'  {t}: {n} rows')
        print(f'    cols: {cols}')


def row_to_dict(row):
    return dict(row) if row is not None else {}


def simulate_bet_hit(bet, payouts):
    """settle_multi と同じ照合（DB は更新しない）。"""
    from core import money as _money
    b = row_to_dict(bet)
    match = _money.match_bet_to_payout(b, payouts or {})
    if match is None:
        return None, 0
    if match.get('status') == 'hit':
        return True, int(match.get('payout') or 0)
    if match.get('status') == 'refund':
        return False, int(match.get('payout') or 0)
    return False, 0


def try_auto_settle_skips(lg, fetch=False):
    """未精算 skips を可能な範囲で評価（ネットワーク要）。"""
    if not fetch:
        return 0
    from core.scraper import fetch_race_payouts
    try:
        from core import score_cache as sc
    except Exception:
        sc = None
    updated = 0
    pend = list(lg.con.execute(
        "SELECT * FROM skips WHERE settled=0 OR settled IS NULL"))
    for sk in pend:
        rid = str(sk['race_id'] or '').strip()
        if not rid:
            continue
        bets = list(lg.con.execute(
            "SELECT * FROM bets WHERE race_id=?", (rid,)))
        payouts = None
        would_hit = None
        would_payout = 0
        if bets:
            try:
                payouts = fetch_race_payouts(rid)
            except Exception:
                payouts = None
            if payouts:
                all_resolved = True
                any_hit = False
                max_po = 0
                for b in bets:
                    hit, po = simulate_bet_hit(dict(b), payouts)
                    if hit is None:
                        all_resolved = False
                        break
                    if hit:
                        any_hit = True
                        max_po = max(max_po, po)
                if all_resolved:
                    would_hit = 1 if any_hit else 0
                    would_payout = max_po
        elif sc:
            gate = sc.read_gate(rid)
            if gate and norm_gate(gate.get('status')) == 'skip':
                would_hit = 0
                would_payout = 0
        if would_hit is not None:
            lg.settle_skip(rid, bool(would_hit), would_payout)
            updated += 1
    return updated


def _operational_actual_bets(lg):
    """実運用母集団: committed_actual と検証できた batch の actual bets のみ。"""
    return lg.verified_actual_bet_rows(settled_only=False)


def build_report(lg):
    bets = _operational_actual_bets(lg)
    skips = [dict(r) for r in lg.con.execute("SELECT * FROM skips ORDER BY skip_id")]

    b_from, b_to = ts_range(bets)
    s_from, s_to = ts_range(skips)
    period_from = b_from
    period_to = b_to

    tagged = [b for b in bets if norm_gate(b['gate_status'])]
    compliant_all = [b for b in bets if is_compliant_bet(b)]
    deviant_all = [b for b in bets if not is_compliant_bet(b)]

    settled = [b for b in bets if b.get('settled')]
    compliant_settled = [b for b in settled if is_compliant_bet(b)]
    deviant_settled = [b for b in settled if not is_compliant_bet(b)]

    n_bets = len(bets)
    n_tagged = len(tagged)
    n_compliant = len(compliant_all)
    compliance_denom = n_tagged if n_tagged else n_bets
    compliance_num = n_compliant if n_tagged else n_compliant
    compliance_rate = (compliance_num / compliance_denom * 100.0) if compliance_denom else None

    roi_c = roi_pct(compliant_settled)
    roi_d = roi_pct(deviant_settled)
    roi_all = roi_pct(settled)
    roi_gap = None
    roi_gap_note = ''
    if len(compliant_settled) < MIN_N or len(deviant_settled) < MIN_N:
        roi_gap_note = f'n不足(遵守 settled={len(compliant_settled)}, 逸脱 settled={len(deviant_settled)}, 要各{MIN_N}+)'
    elif roi_c is not None and roi_d is not None:
        roi_gap = roi_c - roi_d

    total_stake = sum(int(b.get('stake') or 0) for b in settled)
    total_payout = sum(int(b.get('payout') or 0) for b in settled)
    total_profit = total_payout - total_stake

    skip_settled = [s for s in skips if s.get('settled')]
    skip_correct = sum(1 for s in skip_settled if not s.get('would_hit'))
    skip_rate = (skip_correct / len(skip_settled) * 100.0) if skip_settled else None
    skip_note = ''
    if not skip_settled:
        skip_note = 'データ不足(精算済み skips=0)'
    elif len(skip_settled) < MIN_N:
        skip_note = f'n={len(skip_settled)}<{MIN_N} 参考値のみ'

    gate_counts = {}
    for b in bets:
        g = norm_gate(b['gate_status']) or '(未タグ)'
        gate_counts[g] = gate_counts.get(g, 0) + 1

    rows = []
    def add(metric, value, unit='', n='', note=''):
        rows.append({'metric': metric, 'value': value, 'unit': unit, 'n': n, 'note': note})

    add('generated_at', datetime.now().isoformat(timespec='seconds'))
    add('period_from', period_from or '', note='bets/skips の ts 最小')
    add('period_to', period_to or '', note='bets/skips の ts 最大')
    add('bets_total', n_bets, 'count')
    add('bets_settled', len(settled), 'count')
    add('bets_gate_tagged', n_tagged, 'count', note='gate_status あり')
    add('compliance_rate', '' if compliance_rate is None else round(compliance_rate, 1),
        'percent', compliance_denom,
        'buy かつ 危険人気なし かつ 逸脱なし / gate タグ付き bets')
    add('compliance_n', compliance_num, 'count')
    add('deviation_n', len(deviant_all), 'count')
    for g, c in sorted(gate_counts.items()):
        add(f'gate_{g}', c, 'count')
    add('roi_compliant_pct', '' if roi_c is None else round(roi_c, 1),
        'percent', len(compliant_settled), 'settled のみ')
    add('roi_deviant_pct', '' if roi_d is None else round(roi_d, 1),
        'percent', len(deviant_settled), 'settled のみ')
    add('deviation_cost_roi_gap', '' if roi_gap is None else round(roi_gap, 1),
        'pt', note=roi_gap_note or '遵守ROI − 逸脱ROI (プラス=遵守の方がマシ)')
    add('skips_total', len(skips), 'count')
    add('skips_settled', len(skip_settled), 'count')
    add('skip_correct_rate', '' if skip_rate is None else round(skip_rate, 1),
        'percent', len(skip_settled), skip_note or 'would_hit=0 の割合')
    add('skips_unsettled', len(skips) - len(skip_settled), 'count',
        note='--fetch で一部自動評価可')

    add('actual_stake_settled', total_stake, 'yen', len(settled))
    add('actual_payout_settled', total_payout, 'yen', len(settled))
    add('actual_profit_settled', total_profit, 'yen', len(settled))
    add('actual_roi_settled_pct', '' if roi_all is None else round(roi_all, 1),
        'percent', len(settled))

    if n_bets == 0 and len(skips) == 0:
        add('status', 'データ不足', note='ledger.db に actual_purchase bets/skips がありません')

    return rows, {
        'bets': n_bets,
        'bets_settled': len(settled),
        'skips': len(skips),
        'compliance_rate': compliance_rate,
        'compliance_n': compliance_num,
        'deviation_n': len(deviant_all),
        'roi_gap': roi_gap,
        'roi_gap_note': roi_gap_note,
        'roi_all_pct': roi_all,
        'stake_settled': total_stake,
        'payout_settled': total_payout,
        'profit_settled': total_profit,
        'skip_rate': skip_rate,
        'skip_note': skip_note,
        'gate_counts': gate_counts,
        'period_from': period_from,
        'period_to': period_to,
    }


def print_report(summary, csv_rows):
    print()
    print('=== 運用遵守レポート (ledger.db) ===')
    if summary['bets'] == 0 and summary['skips'] == 0:
        print('⚠ データ不足: bets / skips が 0 件です。BetSync で購入確定・見送りを記録してください。')
    if summary['period_from']:
        print(f"期間: {summary['period_from']} 〜 {summary['period_to']}")
    print(f"bets: {summary['bets']} 件 / skips: {summary['skips']} 件")
    print()
    if summary['compliance_rate'] is not None:
        print(f"遵守率: {summary['compliance_rate']:.1f}%  "
              f"(gate=buy & 危険人気なし & 逸脱なし)")
    else:
        print('遵守率: — (データ不足)')
    print(f"  gate内訳: {summary['gate_counts'] or '(なし)'}")
    print()
    if summary['roi_gap_note']:
        print(f"逸脱コスト(ROI差): {summary['roi_gap_note']}")
    elif summary['roi_gap'] is not None:
        print(f"逸脱コスト(ROI差): {summary['roi_gap']:+.1f} pt  "
              f"(遵守ROI − 逸脱ROI。プラス=遵守の方が回収率高い)")
    else:
        print('逸脱コスト(ROI差): — (精算済み不足)')
    print()
    if summary['skip_rate'] is not None:
        line = f"見送り正答率: {summary['skip_rate']:.1f}%"
        if summary['skip_note']:
            line += f"  ※{summary['skip_note']}"
        print(line)
    else:
        print(f"見送り正答率: — ({summary['skip_note'] or '精算済み skips なし'})")
    print()
    if (summary['bets'] > 0 and summary['bets'] < MIN_N) or summary.get('skip_note', '').startswith('n='):
        print('⚠ サンプル数が少ないため、的中率・ROI の優劣は断定できません。')
        print('  短期KPIは遵守率（ルール通りに買えているか）を優先して見てください。')
    print()
    print(f'CSV: {OUT_CSV}')


def write_csv(rows):
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    fields = ['metric', 'value', 'unit', 'n', 'note']
    with open(OUT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in fields})


def main():
    ap = argparse.ArgumentParser(description='ledger.db 運用遵守レポート')
    ap.add_argument('--schema', action='store_true', help='スキーマのみ表示')
    ap.add_argument('--fetch', action='store_true',
                    help='未精算 skips を fetch で可能な範囲評価（要ネットワーク）')
    args = ap.parse_args()

    lg = Ledger(DB_PATH)
    dump_schema(lg.con)
    if args.schema:
        lg.close()
        return

    if args.fetch:
        n = try_auto_settle_skips(lg, fetch=True)
        if n:
            print(f'(--fetch) skips 自動評価: {n} 件')

    csv_rows, summary = build_report(lg)
    lg.close()
    print_report(summary, csv_rows)
    write_csv(csv_rows)


if __name__ == '__main__':
    main()
