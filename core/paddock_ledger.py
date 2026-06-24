# -*- coding: utf-8 -*-
"""
パドック観察タグ台帳 — 自分のパドック観察(タグ)×結果のROIを蓄積して、
「どの観察が回収率に効くか」を自分のデータで実証するための個人検証装置。

【設計思想・正直な前提】
  パドックの主観cue(歩様/発汗/気配 等)は歴史的な正解ラベルが存在せず、
  既存のバックテストでは検証できない(verified_paddock_weight)。だから予測ロジックには
  できない。代わりに本台帳で「自分が付けたタグ × そのレース結果」を貯め、タグ別の
  複勝率・ROIを実測する。検証で効くと分かったタグだけを以後信頼する(elim_reasonsと同思想)。

  タグの極性(fade/buy)は表示用の仮説に過ぎず、効くかどうかは台帳の実測で判定する。
  「白い泡=危険」等は俗説。本台帳はそれを鵜呑みにせず数字で確かめるためにある。

  定量(馬体重/増減)は既に検証済(fade側のみ・買い妙味ゼロ=verified_paddock_weight)なので
  ここでは扱わない。本台帳は『主観cueを個人検証する』ことに専念する。

【使い方(想定)】
  1) レース前: パドックを見て、気づいた観察をタグで記録(+自由メモ)。source='manual'。
     将来 phase B で Ollama/Gemma の自動抽出タグ(source='gemma')も同じ台帳に入れて
     人の眼 vs Gemma のどちらが効くか比較する。
  2) レース後: 着順(と分かれば単勝オッズ)を入れて精算(settle)。
  3) tag_stats でタグ別の複勝率/単ROI/平均人気を見る。十分なnが貯まったら効くタグを採用。
"""
import json
import os
from collections import defaultdict
from datetime import datetime

LEDGER_PATH = os.path.join(os.getcwd(), "paddock_ledger.json")
MIN_SAMPLE = 20   # この件数(精算済)に満たないタグは「サンプル不足」と明示する

# 観察タグ: (key, 表示ラベル, グループ)。group は表示用の仮説(fade=減点候補/buy=加点候補/
# ctx=文脈)。極性が正しいかは台帳の実測で判定する(決め打ちしない)。
TAG_DEFS = [
    # --- fade候補(走らないサイン仮説) ---
    ('sweat_foam',  '白い泡の発汗(首/股)',       'fade'),
    ('sweat_cold',  '季節外れ/大量の発汗',       'fade'),
    ('chaka',       'チャカつき/イレ込み',       'fade'),
    ('diarrhea',    '下痢(尻汚れ)',              'fade'),
    ('umake',       '馬っ気(牡の興奮)',          'fade'),
    ('gait_stiff',  '歩様が硬い/ぎこちない',     'fade'),
    ('head_high',   '頭が高い/力んでいる',       'fade'),
    ('donadona',    'ドナドナ(引かれて歩く/内回り)', 'fade'),
    ('two_handler', '2人引きで必死に抑え',       'fade'),
    ('tomo_loose',  'トモが緩い/張り無し',       'fade'),
    ('over_weight', '太め残り(背割れ/腹ボテ)',   'fade'),
    ('too_thin',    '細すぎ/巻き上がり',         'fade'),
    ('dull_coat',   '毛づや悪い/覇気無し',       'fade'),
    ('eye_red',     '目の充血',                  'fade'),
    # --- buy候補(激走サイン仮説・予測は織込み済みなのでROIで判定) ---
    ('zenigata',    '銭形(代謝良)',              'buy'),
    ('tomo_tight',  'トモがパンと張る',          'buy'),
    ('coat_shine',  '毛艶◎/発光感',             'buy'),
    ('vein',        '血管の浮き(究極仕上げ)',    'buy'),
    ('deep_step',   '踏み込みが深い',            'buy'),
    ('rhythm_out',  'リズム良く外側を大回り',    'buy'),
    ('calm_focus',  '落ち着き/集中',            'buy'),
    ('first_blink', '初ブリンカー等×集中(変わり身)', 'buy'),
    ('kani_ok',     '返し馬でカニ走り→折り合いOK', 'buy'),
    # --- 文脈(過去比較) ---
    ('worse_usual', 'いつもより悪い(過去比較で異常)', 'ctx'),
    ('better_usual','いつもより良い(過去比較)',  'ctx'),
]
TAG_ORDER = [k for k, _, _ in TAG_DEFS]
TAG_LABEL = {k: lbl for k, lbl, _ in TAG_DEFS}
TAG_GROUP = {k: g for k, _, g in TAG_DEFS}
GROUP_LABEL = {'fade': '減点候補', 'buy': '加点候補', 'ctx': '文脈'}


def load_ledger(path=LEDGER_PATH):
    """台帳(エントリのlist)を読み込む。無ければ空list。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_ledger(led, path=LEDGER_PATH):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def make_entry(*, race_id, umaban, name, ninki=None, odds=None, tags=None,
               note='', source='manual'):
    """観察1件。chaku/win_odds は精算時に settle_entry で埋める。"""
    return {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'race_id': str(race_id),
        'umaban': (int(umaban) if umaban not in (None, '') else None),
        'name': str(name or ''),
        'ninki': (int(ninki) if ninki not in (None, '') else None),
        'odds': (float(odds) if odds not in (None, '') else None),
        'tags': [t for t in (tags or []) if t in TAG_LABEL],
        'note': str(note or ''),
        'source': ('gemma' if source == 'gemma' else 'manual'),
        'chaku': None,         # 精算後の着順
        'win_odds': None,      # 精算時点の確定単勝オッズ(あれば)
        'settled': False,
    }


def add_entry(entry, path=LEDGER_PATH):
    """1件追記。成功でTrue。"""
    led = load_ledger(path)
    led.append(entry)
    return save_ledger(led, path)


def _key(race_id, umaban):
    return (str(race_id), (int(umaban) if umaban not in (None, '') else None))


def settle_entry(race_id, umaban, chaku, win_odds=None, path=LEDGER_PATH):
    """同 race_id × umaban の未精算エントリに着順(と単勝オッズ)を記録。
    更新件数を返す(0=該当なし)。"""
    led = load_ledger(path)
    tgt = _key(race_id, umaban)
    n = 0
    for e in led:
        if _key(e.get('race_id'), e.get('umaban')) == tgt:
            try:
                e['chaku'] = int(chaku)
            except (TypeError, ValueError):
                continue
            if win_odds not in (None, ''):
                try:
                    e['win_odds'] = float(win_odds)
                except (TypeError, ValueError):
                    pass
            e['settled'] = True
            n += 1
    if n:
        save_ledger(led, path)
    return n


def _agg():
    return {'n': 0, 'settled': 0, 't3': 0, 'win': 0,
            'pay1': 0.0, 'pay1_n': 0, 'ninki_sum': 0, 'ninki_n': 0}


def _add(d, e):
    d['n'] += 1
    if e.get('ninki') is not None:
        d['ninki_sum'] += e['ninki']
        d['ninki_n'] += 1
    if not e.get('settled'):
        return
    chaku = e.get('chaku')
    if chaku is None:
        return
    d['settled'] += 1
    d['t3'] += 1 if chaku <= 3 else 0
    d['win'] += 1 if chaku == 1 else 0
    # 単ROI: 精算時の単勝オッズが記録されている分だけで計算(無い分は母数から除外)
    o = e.get('win_odds') or e.get('odds')
    if o:
        d['pay1_n'] += 1
        d['pay1'] += (o if chaku == 1 else 0.0)


def baseline(ledger):
    """台帳全体(精算済)のベース複勝率/単勝率/平均人気。タグ判定の比較基準。"""
    d = _agg()
    for e in ledger:
        _add(d, e)
    return _summary('全体ベース', d)


def _summary(label, d):
    st = max(d['settled'], 1)
    return {
        'label': label,
        'n': d['n'],
        'settled': d['settled'],
        't3_rate': d['t3'] / st,
        'win_rate': d['win'] / st,
        'roi1': (d['pay1'] / d['pay1_n']) if d['pay1_n'] else None,
        'roi1_n': d['pay1_n'],
        'avg_ninki': (d['ninki_sum'] / d['ninki_n']) if d['ninki_n'] else None,
    }


def tag_stats(ledger):
    """タグ別の集計list(精算済件数の多い順)。各要素に group/仮説極性も含む。
    複勝率はベースとの差分(delta_t3)で見る。平均人気で『ただの人気薄か』を判別する。"""
    by = defaultdict(_agg)
    for e in ledger:
        for k in (e.get('tags') or []):
            if k in TAG_LABEL:
                _add(by[k], e)
    base = baseline(ledger)
    out = []
    for k, d in by.items():
        s = _summary(TAG_LABEL[k], d)
        s['key'] = k
        s['group'] = TAG_GROUP.get(k, 'ctx')
        s['delta_t3'] = (s['t3_rate'] - base['t3_rate']) if d['settled'] else 0.0
        s['enough'] = d['settled'] >= MIN_SAMPLE
        out.append(s)
    out.sort(key=lambda s: (-s['settled'], -s['n']))
    return out, base


def verdict(s, base):
    """1タグの実測判定(表示用の短文)。仮説極性ではなく実測で言う。"""
    if not s['enough']:
        return f"サンプル不足(精算{s['settled']}/{MIN_SAMPLE}件)"
    grp = s['group']
    d = s['delta_t3']
    roi = s['roi1']
    if grp == 'fade':
        # 減点候補: ベースより複勝率が十分低ければ「消し材料として機能」
        if d <= -0.05:
            return f"消しに機能(複勝率ベース比{d*100:+.1f}pt)"
        if d >= 0.03:
            return f"逆効果の疑い(複勝率ベース比{d*100:+.1f}pt・消すと取りこぼす)"
        return f"効果薄/織込み済み(複勝率ベース比{d*100:+.1f}pt)"
    if grp == 'buy':
        # 加点候補: 予測は織込み済みなので複勝率高でなくROIで判定
        if roi is not None and roi >= 1.0:
            return f"買い妙味あり(単ROI{roi*100:.0f}%)"
        if roi is not None:
            return f"買い妙味なし(単ROI{roi*100:.0f}%・織込み済み)"
        return f"オッズ未記録でROI不明(複勝率{s['t3_rate']*100:.0f}%)"
    return f"複勝率{s['t3_rate']*100:.0f}%(ベース比{d*100:+.1f}pt)"
