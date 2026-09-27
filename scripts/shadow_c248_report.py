# -*- coding: utf-8 -*-
"""Cゾーン Shadow 2-4-8 蓄積状況レポート。

Usage: python scripts/shadow_c248_report.py
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import playbook_ledger as pl
from core import playbook_shadow as psh


def main():
    entries = pl.list_entries()
    shadow = pl.list_shadow_entries()
    cmp = pl.summarize_shadow_vs_production(shadow, entries)
    sh = cmp['shadow']
    pr = cmp['production_paired']

    print('=' * 72)
    print('Cゾーン Shadow 2-4-8 蓄積レポート')
    print('=' * 72)
    print(f"Shadow 記録総数: {cmp['n_shadow_total']} / 有効 {cmp['n_shadow_active']}")
    print(f"Shadow 確定: {cmp['n_shadow_settled']} / 本番ペア {cmp['n_paired_settled']}")
    print(f"再評価目安: {cmp['min_races']}〜{cmp['target_races']} レース")
    print(f"進捗: {cmp['progress_pct']:.1f}% （確定/{cmp['target_races']}）")
    print(f"初回再評価可能: {'はい' if cmp['evaluation_ready'] else 'いいえ'}")
    print()
    print('--- 本番 2-3-6（ペア比較）---')
    _line(pr)
    print('--- Shadow 2-4-8 ---')
    _line(sh)
    if sh.get('hit_rate') is not None and pr.get('hit_rate') is not None:
        print(
            f"\n差分 Shadow−本番: 的中 {sh['hit_rate'] - pr['hit_rate']:+.1f}pp "
            f"ROI {sh['roi'] - pr['roi']:+.1f}pp"
        )
    print('\n※ 本番ロジックは変更しません。Shadow のみ記録。')


def _line(s):
    if not s or not s.get('n_settled'):
        print('  （確定データなし）')
        return
    cph = f"{s['cost_per_hit']:,.0f}" if s.get('cost_per_hit') else '—'
    print(
        f"  的中{s['hit_rate']:.1f}% ROI{s['roi']:.1f}% "
        f"損失{s.get('loss_per_100', 0):.1f} 1中{cph}円 "
        f"連敗{s.get('max_losing_streak', 0)} "
        f"R{s['n_settled']} 投{s['investment']/1000:.0f}k 払{s['payout']/1000:.0f}k"
    )


if __name__ == '__main__':
    main()
