# -*- coding: utf-8 -*-
"""
消去理由ラーニング — 「消し→残し」に変えた理由を条件タグ付きで蓄積し、
同じタグが規定回数たまったら、合致する消し馬を自動で『残し』に昇格させる。

使い方(想定): 終了レースを回顧し、3着以内に来た馬が🎯強適消去エンジンの『消し』に
入っていた場合、その馬を残しに変更して理由(自由文)＋条件タグを記録する。
そのタグの『生還率』(切ったのに来た率)が基準を超えると、以後そのタグに合致する消し馬を自動で残す。

【昇格判定 — 2026-07に分母つきへ改修】
  旧: 同じタグが3回たまったら昇格(PROMOTE_THRESHOLD)。
      → 分母(そのタグで切った総回数)を見ていないため、頻出タグ(例:人気薄)は
        すぐ3回に達して誤昇格していた。
  新: 『来た回数 ÷ 切った回数』を縮小推定(少ない観測を全体平均へ引き寄せ)して、
      PROMOTE_RATE(25%)以上なら昇格。全体平均は消去エンジンの実測生還率15.6%
      (=切った馬が来なかった率84.4%の裏返し・66R台帳2026-07実測)。
      切った総回数は record_fired() が記録する。分母の無い旧タグは3回ルールで判定。

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
PROMOTE_THRESHOLD = 3   # 【旧・分母が無いタグ用】同じタグがこの回数たまったら自動残し

# 【新】分母つきの昇格判定
PROMOTE_RATE = 0.25     # 補正後の生還率がこれ以上なら「このタグは切ってはいけない」と判断
BASE_SURVIVE = 0.156    # 全体平均の生還率(切った馬が3着内に来る率)。66R台帳2026-07実測
                        # (消去精度84.4% の裏返し = 1 - 0.844)
PRIOR_STRENGTH = 10.0   # 事前分布の重み(仮想サンプル数)。10回ぶん切った実績で全体平均と拮抗

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


def _load_raw(path=LEDGER_PATH):
    """台帳ファイルを dict 形式 {'entries': [...], 'fired': {...}} で読む。

    旧形式(エントリのlistがそのまま入ったJSON)も読める(移行互換)。
    fired = {race_id: {umaban(str): [tag,...]}} — 消去エンジンが『切った』馬の記録。
    race_id/馬番をキーにするので、同じレースを何度描画しても二重計上されない。
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {'entries': [], 'fired': {}}
    if isinstance(data, list):                      # 旧形式: listのみ
        return {'entries': data, 'fired': {}}
    if isinstance(data, dict):
        return {'entries': data.get('entries') or [],
                'fired': data.get('fired') or {}}
    return {'entries': [], 'fired': {}}


def _save_raw(raw, path=LEDGER_PATH):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_ledger(path=LEDGER_PATH):
    """学習台帳(エントリのlist)を読み込む。無ければ空list。
    ※戻り値は従来どおり list(呼び手の契約を変えない)。分母は load_fired() で取る。"""
    return _load_raw(path)['entries']


def load_fired(path=LEDGER_PATH):
    """消去エンジンが『切った』記録 {race_id: {umaban: [tag,...]}} を返す。"""
    return _load_raw(path)['fired']


def record_fired(race_id, tags_by_umaban, path=LEDGER_PATH):
    """消去エンジンが切った馬のタグを記録する(昇格判定の"分母")。

    tags_by_umaban: {馬番: [tagキー,...]} — 判定が『🧹消し』になった馬だけを渡す。
    同一 race_id は上書き(冪等)。Streamlitの再描画で何度呼ばれても分母は膨らまない。
    内容に変化が無ければ書き込みもしない。戻り値: 書き込んだらTrue。
    """
    if not race_id or not tags_by_umaban:
        return False
    raw = _load_raw(path)
    rid = str(race_id)
    new = {str(u): sorted(set(t or [])) for u, t in tags_by_umaban.items()}
    if raw['fired'].get(rid) == new:
        return False                                # 変化なし=書かない
    raw['fired'][rid] = new
    return _save_raw(raw, path)


def fired_counts(fired):
    """切った回数をタグ別に集計(Counter)。fired=load_fired()の戻り。"""
    c = Counter()
    for _rid, horses in (fired or {}).items():
        for _u, tags in (horses or {}).items():
            for k in (tags or []):
                c[k] += 1
    return c


def add_entry(entry, path=LEDGER_PATH):
    """1件追記。entry={date,race_id,umaban,name,ninki,odds,reason,tags:[key]}。成功でTrue。"""
    raw = _load_raw(path)
    raw['entries'].append(entry)
    return _save_raw(raw, path)


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


def tag_stats(ledger, fired=None, path=LEDGER_PATH):
    """タグ別の {来た回数 / 切った回数 / 補正後の生還率 / 昇格したか} を返す。

    生還率 = 切ったのに3着内に来た率。少ない観測は全体平均(BASE_SURVIVE=15.6%)へ
    引き寄せる(縮小推定)。『3回来た』だけでは昇格せず、『何回切ったうちの3回か』を見る。

    戻り値: {tag: {'hits':int, 'fired':int, 'rate':float|None, 'promoted':bool,
                   'basis':'rate'|'count'}}  basis=判定に使った方式。
    """
    from core.bayes_stats import shrink_rate
    if fired is None:
        fired = load_fired(path)
    hits = tag_counts(ledger)
    fc = fired_counts(fired)
    out = {}
    for k in set(hits) | set(fc):
        h = hits.get(k, 0)
        n = fc.get(k, 0)
        if n > 0:
            # 分母あり: 縮小推定した生還率で判定(頻出タグの誤昇格を防ぐ)
            r = shrink_rate(min(h, n), n, BASE_SURVIVE, PRIOR_STRENGTH)
            out[k] = {'hits': h, 'fired': n, 'rate': r,
                      'promoted': r >= PROMOTE_RATE, 'basis': 'rate'}
        else:
            # 分母なし(旧台帳からの移行期): 従来の3回ルール
            out[k] = {'hits': h, 'fired': 0, 'rate': None,
                      'promoted': h >= PROMOTE_THRESHOLD, 'basis': 'count'}
    return out


def learned_tags(ledger, threshold=PROMOTE_THRESHOLD, fired=None, path=LEDGER_PATH):
    """自動残しを有効化するタグ集合。

    分母(切った回数)が記録されているタグは、縮小推定した生還率 >= PROMOTE_RATE で昇格。
    分母の無いタグ(旧台帳)は従来どおり出現 threshold 回で昇格。
    ※シグネチャは後方互換(既存の呼び出し learned_tags(ledger) はそのまま動く)。
    """
    stats = tag_stats(ledger, fired=fired, path=path)
    promoted = set()
    for k, s in stats.items():
        if s['basis'] == 'rate':
            if s['promoted']:
                promoted.add(k)
        elif s['hits'] >= threshold:                # 旧ルール(threshold引数を尊重)
            promoted.add(k)
    return promoted
