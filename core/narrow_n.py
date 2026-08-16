# -*- coding: utf-8 -*-
"""推奨絞り頭数 — 『5着以内の8割を捕まえるには何頭に絞ればよいか』。

検証: scripts/narrow_n_backtest.py
  ・train(2020-2024 17,276R)で 荒れ予報帯 × 頭数帯 ごとに必要頭数を実測。
  ・holdout(2025+ 5,105R)で全9層が目標80%をクリア(平均カバー率83.2%)。
  ・一律7頭だと79.3%。層別にすると平均7.7頭で83.2%＝『荒れる時だけ広げる』が効く。

設計方針:
  ・新しい予測モデルは作らない。検証済みの荒れ予報(value_scanner.arare_prob)と
    頭数だけで引く実測テーブル。過学習の余地を残さない。
  ・順位付けは人気順が基準。scripts/top5_capture_ceiling.py の実測で
    LTRは人気を超えない(N=7で-0.41pp)と分かっているため。
  ・これは「この頭数を買え」ではなく「この頭数まで絞ると8割残る」という
    “取りこぼしの目安”。買い目点数は別途EV/資金管理で決めること。
"""
import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE_PATH = os.path.join(_HERE, '..', 'data', 'narrow_n_table.json')

_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            with open(_TABLE_PATH, 'r', encoding='utf-8') as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _band_of(v, bands):
    for lbl, lo, hi in bands:
        if lo <= v < hi:
            return lbl
    return bands[-1][0] if bands else ''


def recommend(arare_prob, n_horses):
    """推奨絞り頭数を返す。

    arare_prob: 荒れ予報(0..1)。Noneなら中庸(0.5)扱い。
    n_horses:   出走頭数。
    戻り: {'n', 'target', 'arare_band', 'field_band', 'note'} / 引けない時 None
    """
    d = _load()
    table = (d or {}).get('table') or {}
    if not table or not n_horses:
        return None
    ab = _band_of(float(arare_prob) if arare_prob is not None else 0.5,
                  d.get('arare_bands') or [])
    fb = _band_of(int(n_horses), d.get('field_bands') or [])
    n = table.get(f'{ab}|{fb}')
    if n is None:
        # その層の実測が無い(標本不足)場合は荒れ帯だけで最大値を採る＝広めに倒す
        cand = [v for k, v in table.items() if k.startswith(ab + '|')]
        n = max(cand) if cand else None
    if n is None:
        return None
    n = int(min(n, int(n_horses)))
    tgt = float(d.get('target', 0.80))
    return {'n': n, 'target': tgt, 'arare_band': ab, 'field_band': fb,
            'note': f'{ab}・{fb} では上位{n}頭まで残すと'
                    f'5着以内の約{tgt*100:.0f}%を取りこぼさない(実測)'}


def label(arare_prob, n_horses):
    """UI表示用の1行テキスト。引けない時は空文字。"""
    r = recommend(arare_prob, n_horses)
    if not r:
        return ''
    return (f"🎯 推奨絞り頭数 **{r['n']}頭**"
            f"（{r['arare_band']}／{r['field_band']}）"
            f"　ここまで残すと5着以内の約{r['target']*100:.0f}%を取りこぼしません")
