# -*- coding: utf-8 -*-
"""scripts/maiden_score_backtest.py Step A の契約テスト。

対象は純粋関数（DB非依存）+ before_key 伝播の保証:
  1. 3分位エッジ・3段階化の機械的正当性
  2. V2 固定区分（40/30%, 15走未満は0）
  3. 指標計算（残差・z・CI・ROI）の妥当性
  4. 事前固定ゲートの採否マトリクス（設計書 §4 どおり。変更禁止）
  5. compute_one が必ず before_key=race_key を渡すこと（リーク防止の核心）
  6. USM較正が train 期間のみ（EXP_YEARS <= 2017）

注意: 既存WIPの umai_baken 買い目パース失敗とは無関係・混入させない
（このテストは umai_baken を import しない）。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    'maiden_score_backtest', os.path.join(ROOT, 'scripts', 'maiden_score_backtest.py'))
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)


def test_tertile_edges():
    lo, hi = bt.tertile_edges(list(range(1, 301)))  # 1..300
    assert lo == 101 and hi == 201, f'edges=({lo},{hi})'
    assert bt.tertile_edges([]) == (None, None)
    print('  ✅ tertile_edges')


def test_tier_of():
    assert bt.tier_of(10, 100, 200) == 0
    assert bt.tier_of(150, 100, 200) == 1
    assert bt.tier_of(250, 100, 200) == 2
    assert bt.tier_of(100, 100, 200) == 0   # 境界は下位側
    assert bt.tier_of(200, 100, 200) == 1
    assert bt.tier_of(None, 100, 200) is None
    assert bt.tier_of(5, None, None) is None
    # エッジ崩壊（全値同一など）→ 2分割
    assert bt.tier_of(1.0, 1.0, 1.0) == 0
    assert bt.tier_of(1.01, 1.0, 1.0) == 2
    print('  ✅ tier_of')


def test_v2_tier():
    assert bt.v2_tier(None) == 0
    assert bt.v2_tier({'rides': 10, 'top2': 0.50}) == 0   # 15走未満は不採用
    assert bt.v2_tier({'rides': 15, 'top2': 0.29}) == 0
    assert bt.v2_tier({'rides': 15, 'top2': 0.30}) == 1
    assert bt.v2_tier({'rides': 15, 'top2': 0.399}) == 1
    assert bt.v2_tier({'rides': 15, 'top2': 0.40}) == 2
    assert bt.v2_tier({'rides': 200, 'top2': 0.55}) == 2
    print('  ✅ v2_tier 固定区分')


def test_tier_metrics():
    rows = ([{'ninki': 1, 'chakujun': 1, 'win_odds': 2.0}] * 60
            + [{'ninki': 1, 'chakujun': 5, 'win_odds': 2.0}] * 40)
    m = bt.tier_metrics(rows, baseline={1: 0.50})
    assert m['n'] == 100
    assert abs(m['win_rate'] - 0.60) < 1e-9
    assert abs(m['place_rate'] - 0.60) < 1e-9
    assert abs(m['residual'] - 0.10) < 1e-9          # 60% - 50%
    assert m['z'] > 0
    assert m['ci_lo'] is not None and m['ci_lo'] < m['residual'] < m['ci_hi']
    assert abs(m['roi_win'] - 1.20) < 1e-9           # 60回×2.0 / 100
    # ベースラインに無い人気は除外
    m2 = bt.tier_metrics([{'ninki': 18, 'chakujun': 1, 'win_odds': 50.0}], {1: 0.5})
    assert m2 is None
    print('  ✅ tier_metrics（残差/z/CI/ROI）')


def _mk_tier(resid, z, n=500):
    return {'n': n, 'win_rate': 0.2, 'place_rate': 0.3, 'residual': resid,
            'z': z, 'ci_lo': None, 'ci_hi': None, 'roi_win': 0.8}


def test_gate_matrix():
    # 採用: 上位>0 かつ z>=2 かつ 単調
    ok, _ = bt.gate_verdict({2: _mk_tier(0.05, 2.5), 1: _mk_tier(0.01, 0.5),
                             0: _mk_tier(-0.02, -1.0)})
    assert ok is True
    # 残差が非正 → 不採用
    ok, r = bt.gate_verdict({2: _mk_tier(-0.01, -0.5), 1: _mk_tier(-0.02, -1),
                             0: _mk_tier(-0.03, -2)})
    assert ok is False and '非正' in r
    # z 未達 → 不採用
    ok, r = bt.gate_verdict({2: _mk_tier(0.05, 1.5), 1: _mk_tier(0.01, 0.5),
                             0: _mk_tier(-0.02, -1.0)})
    assert ok is False and 'z 未達' in r
    # 非単調 → 不採用
    ok, r = bt.gate_verdict({2: _mk_tier(0.05, 2.5), 1: _mk_tier(0.06, 3.0),
                             0: _mk_tier(-0.02, -1.0)})
    assert ok is False and '単調' in r
    # 標本不足 → 不採用
    ok, r = bt.gate_verdict({2: _mk_tier(0.05, 2.5, n=50), 1: _mk_tier(0.01, 0.5),
                             0: _mk_tier(-0.02, -1.0)})
    assert ok is False and '標本不足' in r
    print('  ✅ gate_verdict 採否マトリクス（事前固定どおり）')


class _StubJV:
    """before_key 伝播を記録するスタブ（実DBには触れない）。"""

    def __init__(self):
        self.calls = []

    def _venue_name(self, jyo):
        return {'09': '阪神'}.get(jyo, '')

    def jockey_factor(self, jockey, venue=None, distance=None, trainer_code=None,
                      before_key=None, expected=None):
        self.calls.append(('jockey_factor', before_key, expected))
        return {'mult': 1.01, 'note': 'x', 'gold': None}

    def jockey_trainer_combo(self, jockey, trainer_code, before_key=None):
        self.calls.append(('combo', before_key))
        return {'rides': 100, 'top2': 0.41}

    def trainer_course_winrate(self, tc, jyo, surface, before_key=None, min_year=None):
        self.calls.append(('trainer_course', before_key, min_year))
        return {'runs': 50, 'wins': 8, 'win_rate': 0.16, 'top3_rate': 0.3,
                'win_rate_shrunk': 0.12}


def test_before_key_propagation():
    jv = _StubJV()
    run = {'race_key': '2018060208080811', 'jockey': '武豊', 'trainer_code': '01105',
           'jyo': '09', 'kyori': 1600, 'surface': '芝', 'year': 2018}
    v1, v2, v3 = bt.compute_one(jv, run, expected={'~3.0': {'top3': 0.7}})
    for c in jv.calls:
        assert c[1] == run['race_key'], f'before_key 未伝播: {c}'
    # min_year はレース年-3
    assert jv.calls[2][2] == '2015'
    assert v1 == 1.01 and v2 == 2 and abs(v3 - 0.12) < 1e-9
    # 全較正年が train 期間内
    assert all(int(y) <= bt.TRAIN_END for y in bt.EXP_YEARS)
    print('  ✅ before_key 伝播（リーク防止の核心）')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    test_tertile_edges()
    test_tier_of()
    test_v2_tier()
    test_tier_metrics()
    test_gate_matrix()
    test_before_key_propagation()
    print('\nALL PASS: test_maiden_score_backtest')
