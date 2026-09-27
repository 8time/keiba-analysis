# -*- coding: utf-8 -*-
"""新馬戦モード Phase 1 の契約テスト（core/maiden_mode.py）。

検証するのは「設計書どおりの表示契約」:
  1. 新馬戦判定が既存の条件タグと同じ基準で動く
  2. 行に必須キーがあり、禁止キー（スコア/順位）を含まない
  3. データが取れない馬でも落ちずに '—' で返る（デビュー前の馬が主なので重要）
  4. 表示ラベルが平易な日本語である（略語ベタ書きを禁止）
  5. 基礎傾向/注意の固定文が設計書どおり存在する
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import maiden_mode as mm  # noqa: E402


def test_is_maiden_race():
    assert mm.is_maiden_race({'class': '新馬'}) is True
    assert mm.is_maiden_race({'class': '2歳新馬'}) is True
    assert mm.is_maiden_race({'class': 'メイクデビュー'}) is False  # 現行基準は『新馬』のみ
    assert mm.is_maiden_race({'class': '1勝クラス'}) is False
    assert mm.is_maiden_race({'class': '未勝利'}) is False
    assert mm.is_maiden_race({}) is False
    assert mm.is_maiden_race(None) is False
    print('  ✅ is_maiden_race')


def test_collect_rows_contract():
    """存在しない馬・騎手名でも落ちず、必須キーが揃い禁止キーを含まない。"""
    df = pd.DataFrame([
        {'Umaban': 1, 'Name': 'テストノウマ2026', 'Jockey': '架空騎手',
         'Trainer': '架空厩舎', 'TrainerID': None, 'Popularity': 1},
        {'Umaban': 2, 'Name': 'テストノウマ2026B', 'Jockey': '',
         'Trainer': '', 'TrainerID': '99999', 'Popularity': 2},
    ])
    rows = mm.collect_maiden_rows(df, race_id=None, meta=None, expected=None)
    assert len(rows) == 2, f'rows={len(rows)}'
    required = {'馬番', '馬名', '騎手', '騎手の評価', '騎手の内訳',
                '厩舎', '厩舎の勝率(3年)', '当コース勝率', '黄金ライン'}
    forbidden_substr = ('スコア', '順位', 'score', 'rank', '◎', '○', '▲')
    for r in rows:
        assert required.issubset(set(r.keys())), f'キー不足: {required - set(r.keys())}'
        for k in r.keys():
            for bad in forbidden_substr:
                assert bad not in k, f'禁止キー混入: {k}'
    # 馬番順
    assert [r['馬番'] for r in rows] == [1, 2]
    print('  ✅ collect_maiden_rows 契約（必須キー/禁止キー/馬番順）')


def test_plain_labels():
    """固定文・列名に『USM』等の略語がベタ出しされないこと。"""
    for text in mm.MAIDEN_FACTS + mm.MAIDEN_CAUTIONS:
        assert 'USM' not in text, f'略語ベタ出し: {text}'
        assert 'EV' not in text.split('（')[0], f'略語ベタ出し: {text}'
    # 列名チェック
    df = pd.DataFrame([{'Umaban': 1, 'Name': 'X', 'Jockey': 'Y'}])
    rows = mm.collect_maiden_rows(df)
    for k in rows[0].keys():
        assert 'USM' not in k and 'J5' not in k, f'列名に略語: {k}'
    print('  ✅ 平易ラベル（略語ベタ出しなし）')


def test_facts_and_cautions_present():
    assert any('1番人気' in f and '35.0' in f for f in mm.MAIDEN_FACTS)
    assert any('過去走' in f for f in mm.MAIDEN_FACTS)
    assert any('調教タイム' in c for c in mm.MAIDEN_CAUTIONS)
    assert any('織込み済み' in c or '織込み' in c for c in mm.MAIDEN_CAUTIONS)
    print('  ✅ 固定文（基礎傾向/注意）')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    test_is_maiden_race()
    test_collect_rows_contract()
    test_plain_labels()
    test_facts_and_cautions_present()
    print('\nALL PASS: test_maiden_mode')
