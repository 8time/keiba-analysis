# -*- coding: utf-8 -*-
"""
消去理由ラーニング — 「消し→残し」に変えた理由を条件タグ付きで蓄積し、
同じタグが規定回数たまったら、合致する消し馬を自動で『残し』に昇格させる。

使い方(想定): 終了レースを回顧し、3着以内に来た馬が🎯強適消去エンジンの『消し』に
入っていた場合、その馬を残しに変更して理由(自由文)＋条件タグを記録する。
タグが PROMOTE_THRESHOLD 回たまると、以後そのタグに合致する消し馬を自動で残す。

【重要な前提・正直な注意】
  これは backtest 検証済みのエッジではなく、ユーザー個人の実観測を貯める学習台帳。
  人気薄/距離変更/牝馬 等は単体では人気に織込み済(妙味でない)ことが検証で分かっている
  (feedback_folk_signals_overbet / verified_legtype_axis)。広いタグ(例:人気薄)を学習させると
  大量の消し馬が残ってしまうため、できるだけ具体的な状況タグを選んで記録すること。
"""
import json
import os
from collections import Counter
from datetime import datetime

LEDGER_PATH = os.path.join(os.getcwd(), "elim_reasons.json")
PROMOTE_THRESHOLD = 3   # 同じタグがこの回数たまったら自動残しを有効化

# 条件タグ: key -> 表示ラベル。すべて出馬表/過去走から自動判定できる構造タグ。
TAG_DEFS = [
    ('anauma',     '人気薄(8番人気以下)'),
    ('dist_short', '距離短縮(200m以上)'),
    ('dist_long',  '距離延長(200m以上)'),
    ('layoff',     '半年休み明け(180日以上)'),
    ('spurt',      '末脚良好(末脚指数0.8以上)'),
    ('wt_up',      '馬体重増(+8kg以上)'),
    ('wt_down',    '馬体重減(-8kg以下)'),
    ('mare',       '牝馬'),
    ('front',      '前走 逃げ・先行'),
    ('closer',     '前走 差し・追込'),
    ('dirt_new',   '初ダート'),
    ('topswap',    'トップ騎手へ乗替'),
]
TAG_ORDER = [k for k, _ in TAG_DEFS]
TAG_LABEL = {k: lbl for k, lbl in TAG_DEFS}


def compute_tags(*, ninki=None, prev_dist=None, cur_dist=None, layoff_days=None,
                 spurt_index=None, spurt_runs=0, zogen=None, sex_age=None,
                 prev_kyaku=None, surface=None, dirt_runs=None, topswap=False):
    """1頭の構造タグ集合(set of key)を返す。すべて pre-race 情報。"""
    t = set()
    try:
        if ninki is not None and float(ninki) >= 8:
            t.add('anauma')
    except (TypeError, ValueError):
        pass
    try:
        if prev_dist and cur_dist:
            d = int(cur_dist) - int(prev_dist)
            if d <= -200:
                t.add('dist_short')
            elif d >= 200:
                t.add('dist_long')
    except (TypeError, ValueError):
        pass
    try:
        if layoff_days is not None and int(layoff_days) >= 180:
            t.add('layoff')
    except (TypeError, ValueError):
        pass
    if spurt_index is not None and spurt_runs and spurt_runs >= 2 and spurt_index >= 0.8:
        t.add('spurt')
    try:
        if zogen is not None:
            z = int(zogen)
            if z >= 8:
                t.add('wt_up')
            elif z <= -8:
                t.add('wt_down')
    except (TypeError, ValueError):
        pass
    if sex_age and '牝' in str(sex_age):
        t.add('mare')
    if str(prev_kyaku) in ('1', '2'):
        t.add('front')
    elif str(prev_kyaku) in ('3', '4'):
        t.add('closer')
    if surface and 'ダ' in str(surface) and dirt_runs is not None and int(dirt_runs) == 0:
        t.add('dirt_new')
    if topswap:
        t.add('topswap')
    return t


def load_ledger(path=LEDGER_PATH):
    """学習台帳(エントリのlist)を読み込む。無ければ空list。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def add_entry(entry, path=LEDGER_PATH):
    """1件追記。entry={date,race_id,umaban,name,ninki,odds,reason,tags:[key]}。成功でTrue。"""
    led = load_ledger(path)
    led.append(entry)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def make_entry(*, race_id, umaban, name, ninki, odds, reason, tags):
    return {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'race_id': str(race_id), 'umaban': int(umaban) if umaban is not None else None,
        'name': str(name), 'ninki': (int(ninki) if ninki is not None else None),
        'odds': (float(odds) if odds is not None else None),
        'reason': str(reason or ''), 'tags': list(tags or []),
    }


def tag_counts(ledger):
    """台帳全体でのタグ出現回数(Counter)。"""
    c = Counter()
    for e in ledger:
        for k in (e.get('tags') or []):
            c[k] += 1
    return c


def learned_tags(ledger, threshold=PROMOTE_THRESHOLD):
    """出現回数が threshold 以上のタグ集合(=自動残しを有効化するタグ)。"""
    c = tag_counts(ledger)
    return {k for k, n in c.items() if n >= threshold}
