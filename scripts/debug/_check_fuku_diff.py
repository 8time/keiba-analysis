# -*- coding: utf-8 -*-
"""推定3着内率の2ソース食い違いを実数値で確認する一時スクリプト。"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from core import axis_selector as a

fj_axis = a.axis_confidence(1, 2.8, prev_chaku=1, pos_ratio=0.25)   # フリッカージャブ再現(1人気・前走1着・先行)
fj_fuku = a.fuku_rate(1, 2.8)
bm_axis = a.axis_confidence(2, 4.4, prev_win_margin=1.2)            # ビューロマジック再現(2人気・前走圧勝)
bm_fuku = a.fuku_rate(2, 4.4)
print('FJ axis:', fj_axis, '-> fuku:', fj_fuku)
print('BM axis:', bm_axis, '-> fuku:', bm_fuku)
print('fmt:', f"{fj_axis:.0f}%", f"{fj_fuku:.0f}%", f"{bm_axis:.0f}%", f"{bm_fuku:.0f}%")
print('guards:', a.axis_confidence(1, 2.2), a.axis_confidence(1, 2.2, prev_chaku=1),
      a.axis_confidence(1, 2.2, prev_chaku=1, pos_ratio=0.2),
      a.axis_confidence(7, 9.0), a.axis_confidence(1, 2.2, fillies_race=True))
print('fuku misc:', a.fuku_rate(1, None), a.fuku_rate(1, 2.8, is_nar=True), a.fuku_rate(9, None))
