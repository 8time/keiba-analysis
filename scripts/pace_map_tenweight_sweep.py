# -*- coding: utf-8 -*-
"""展開マップ再構築 ―― テン速力(実タイム由来)の重みに伸びしろが残っているかを掃く。

背景: core/pace_map.py の _PACE_TUNE は core/pace_backtest.py で較正済みで、
      現行は w_ten=0.25 / ch_ten=0.0(コーナー履歴ブレンドにテンを混ぜない)。
      コメントには「テン速力は先頭(ハナ)予測を小さく改善」とある。
      scripts/pace_tenspeed_arare_backtest.py で『テン混雑→荒れ』は否定されたので、
      テン速力に残された使い道は**展開マップの表示精度**(4角隊列の当たり具合)だけ。
      その精度に伸びしろが残っているかを、既存ハーネスで直接測る。

⚠ これはエッジ(回収率)の話ではなく**表示精度**の話。展開恩恵自体は priced-in
   ([[verified_tenkai_priced_in]])。UIの信頼性向上が目的で、買い目には影響させない。

過学習防止:
  - 較正窓(2024)と検証窓(2025-26)を分け、**両窓で同時に改善した設定だけ**を採用候補にする。
  - レースはseed固定でサンプリング(決定論)。
  - 本番の _PACE_TUNE は書き換えない(採否は人が判断)。

Usage: python scripts/pace_map_tenweight_sweep.py [レース数]
"""
import os
import sys
import copy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass

from core import pace_map as pm          # noqa: E402
from core import pace_backtest as pb     # noqa: E402

N_RACES = int(sys.argv[1]) if len(sys.argv) > 1 else 400
# (w_ten, ch_ten) の候補。現行は (0.25, 0.0)
GRID = [(0.0, 0.0), (0.25, 0.0), (0.5, 0.0), (1.0, 0.0), (2.0, 0.0),
        (0.25, 0.15), (0.25, 0.30), (0.5, 0.30), (1.0, 0.30)]


def run(cases, w_ten, ch_ten):
    tune = copy.deepcopy(pm._PACE_TUNE)
    tune['w_ten'] = w_ten
    tune['ch_ten'] = ch_ten
    return pb.evaluate(cases, tune=tune)


def main():
    print(f'ケース収集中 (各窓 {N_RACES}レース)...', file=sys.stderr)
    cal = pb.collect_cases(n_races=N_RACES, years=('2024',), seed=42)
    val = pb.collect_cases(n_races=N_RACES, years=('2025', '2026'), seed=42)
    print(f'  較正窓(2024) {len(cal)}件 / 検証窓(2025-26) {len(val)}件\n', file=sys.stderr)

    base_cal = run(cal, pm._PACE_TUNE['w_ten'], pm._PACE_TUNE['ch_ten'])
    base_val = run(val, pm._PACE_TUNE['w_ten'], pm._PACE_TUNE['ch_ten'])
    print('=' * 96)
    print('展開マップ(4角隊列)の予測精度 ―― テン速力の重み掃引')
    print('=' * 96)
    print(f"参考: コーナー履歴を使わない素朴ベースライン spearman "
          f"較正窓{base_cal['spearman']['baseline']:.4f} / 検証窓{base_val['spearman']['baseline']:.4f}")
    print(f"\n{'w_ten':>6s} {'ch_ten':>7s} | {'較正窓(2024)':^30s} | {'検証窓(2025-26)':^30s}")
    print(f"{'':>6s} {'':>7s} | {'spearman':>9s}{'先頭的中':>10s}{'top3被り':>10s} "
          f"| {'spearman':>9s}{'先頭的中':>10s}{'top3被り':>10s}")
    rows = []
    for w, ch in GRID:
        a, b = run(cal, w, ch), run(val, w, ch)
        cur = (w == pm._PACE_TUNE['w_ten'] and ch == pm._PACE_TUNE['ch_ten'])
        rows.append((w, ch, a, b))
        print(f"{w:6.2f} {ch:7.2f} | {a['spearman']['v2']:9.4f}"
              f"{a['leader_hit_rate']['v2']:10.4f}{a['top3_overlap']['v2']:10.4f} "
              f"| {b['spearman']['v2']:9.4f}{b['leader_hit_rate']['v2']:10.4f}"
              f"{b['top3_overlap']['v2']:10.4f}" + ('  ← 現行' if cur else ''))

    print('\n' + '=' * 96)
    print('採用判定: 現行(w_ten=0.25/ch_ten=0.0)を **両窓とも** spearmanで上回るか')
    print('=' * 96)
    hit = False
    for w, ch, a, b in rows:
        if w == pm._PACE_TUNE['w_ten'] and ch == pm._PACE_TUNE['ch_ten']:
            continue
        da = a['spearman']['v2'] - base_cal['spearman']['v2']
        db = b['spearman']['v2'] - base_val['spearman']['v2']
        ok = da > 0 and db > 0
        hit |= ok
        print(f"  w_ten={w:.2f} ch_ten={ch:.2f}  較正窓{da:+.4f} / 検証窓{db:+.4f}  "
              f"{'✅両窓改善' if ok else ''}")
    if not hit:
        print('\n→ 現行の重みが最良。テン速力の展開マップへの寄与は既に取り切っている。')


if __name__ == '__main__':
    main()
