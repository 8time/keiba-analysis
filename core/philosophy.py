# -*- coding: utf-8 -*-
"""思考エンジン — 検証済みエッジを『予想の意思決定フロー』として編成し、言語化して返す。

正本ドキュメント: docs/keiba_ai_philosophy.md（ステップ0〜6と1対1で対応）。

**この層は薄い。** 新しい予測ロジック・新しいスコアを一切作らない。
value_scanner / elim_cross / danger_gate / consensus_view が既に計算した結果を受け取り、
「どの順番で・何を根拠に・どう判断したか」を平易な日本語の理由文に組み立てるだけ。
最終結論(本命/相手/穴/消し)は consensus_view.integrate() の合議を正本として再掲する
(統合ビューと別の結論を出さない=表示の矛盾を作らない)。

LLM呼び出しは含まない(決定的ルールエンジン)。同じ入力なら常に同じ結論になる。

各ステップの『強度』(厳しめ/標準/ゆるめ)は、既に計算済みの数値に対する**下流の絞り込み判断**
だけを変える。エッジの再計算・再閾値化はしない。
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'philosophy.json')

MODES = ('厳しめ', '標準', 'ゆるめ')

# ステップ定義: key -> (表示番号, 表示名, 平易な説明)
# ★ステップの追加はここに1行足し、_step_xxx() を書き、think() の _run に1行足すだけ。
#   詳しい手順は docs/keiba_ai_philosophy.md §8。
STEPS = [
    ('race_filter',    '①', 'レース選別',     'そもそも買うレースか？荒れるか堅いか'),
    ('elimination',    '②', '来ない馬を消す', '消去クロスの重複で切る'),
    ('danger_check',   '③', '危険な人気馬',   '本命は信用できるか'),
    ('value_hunt',     '④', '妙味馬を探す',   '市場が見落とした人気薄(combo馬)'),
    ('axis_support',   '⑤', '軸の裏取り',     '本命の複勝信頼度を実測オッズで確認'),
    ('bet_build',      '⑥', '買い目を組む',   '本命/相手/穴の役割分担と点数'),
    ('devil_advocate', '⑦', '反対役チェック', 'この予想が間違っている可能性'),
    ('my_rules',       '⑧', '自分のルール',   '自分で足した判断ルール(検証外・後から追加可)'),
]

# ── 調整できる数値(閾値) ──
# 値が dict の場合は『強度(厳しめ/標準/ゆるめ)ごとの既定値』。philosophy.json の
# steps[key]['params'][name] に数値を書くと、強度の既定値より優先される(=細かく修正可能)。
# ※ここで変えられるのは『既に検証済みの数値をどう使うか(絞り込みの厳しさ)』だけ。
#   エッジそのもの(z値・複勝率テーブル)は動かせない=検証結果の書き換えにはならない。
PARAM_SPECS = {
    'race_filter': {
        'skip_min_reasons': {'label': '見送りにする「情報不足の理由」の数',
                             'choices': [1, 2, 3, 0],
                             'help': '0＝見送り判定をしない。障害/新馬/未勝利/2歳/少頭数/1倍台本命の該当数',
                             'default': {'厳しめ': 1, '標準': 2, 'ゆるめ': 0}},
        'arare_hot': {'label': '「荒れ寄り」とみなす荒れ確率(%)',
                      'choices': [55, 62, 70],
                      'help': '検証でフォーメーションと最も相性が良かったのは62%以上',
                      'default': 62},
    },
    'elimination': {
        'warn_elim': {'label': '「要注意」に挙げる来にくさフラグの数',
                      'choices': [2, 3, 4],
                      'help': '切りはしないが注意として表示する基準(厳しめ設定のときだけ働く)',
                      'default': 2},
    },
    'value_hunt': {
        'combo_min': {'label': '穴に採用する「好材料の重複数」',
                      'choices': [2, 3, 4],
                      'help': '検証では2個以上でz+9.2。1個だけの馬は全馬に出るので穴にしない',
                      'default': {'厳しめ': 3, '標準': 2, 'ゆるめ': 2}},
    },
    'axis_support': {
        'conf_floor': {'label': '本命に求める複勝信頼度(%)',
                       'choices': [35, 45, 55, 65],
                       'help': '同じオッズ帯の実際の複勝率。下回ると「軸が立たない」と判断',
                       'default': {'厳しめ': 55, '標準': 45, 'ゆるめ': 35}},
    },
    'bet_build': {
        'aite_max': {'label': '相手(2列目)の頭数',
                     'choices': [2, 3, 4, 5],
                     'help': '多いほど当たりやすいが点数が増える',
                     'default': {'厳しめ': 2, '標準': 3, 'ゆるめ': 5}},
    },
}

# 自分のルール(⑧)で使える項目と条件。既に計算済みの値だけを参照する。
RULE_FIELDS = {
    'pop': '人気（何番人気か）',
    'odds': '単勝オッズ（倍）',
    'combo': '好材料の重複数',
    'elim': '来にくさフラグの数',
}
RULE_OPS = {'>=': '以上', '<=': '以下'}
RULE_ACTIONS = {'注意': '注意として表示する（買い目は変えない）',
                '消し': '消し（買い目から外す）'}

DEFAULT_CONFIG = {
    'steps': {k: {'enabled': True, 'mode': '標準', 'params': {}} for k, _, _, _ in STEPS},
    'custom_rules': [],
}


def default_param(key, name, mode='標準'):
    """強度(mode)に応じた既定値を返す。"""
    spec = (PARAM_SPECS.get(key) or {}).get(name) or {}
    d = spec.get('default')
    return d.get(mode) if isinstance(d, dict) else d


def load_config(path=None):
    """philosophy.json を読む。無い/壊れている場合は既定値を返す(例外を投げない)。"""
    p = path or CONFIG_PATH
    cfg = {'steps': {k: {'enabled': True, 'mode': '標準', 'params': {}} for k, _, _, _ in STEPS},
           'custom_rules': []}
    try:
        with open(p, 'r', encoding='utf-8') as f:
            raw = json.load(f) or {}
        for k, v in (raw.get('steps') or {}).items():
            if k in cfg['steps'] and isinstance(v, dict):
                if 'enabled' in v:
                    cfg['steps'][k]['enabled'] = bool(v['enabled'])
                if str(v.get('mode')) in MODES:
                    cfg['steps'][k]['mode'] = str(v['mode'])
                prm = v.get('params')
                if isinstance(prm, dict):
                    for pk, pv in prm.items():
                        if pk in (PARAM_SPECS.get(k) or {}):
                            try:
                                cfg['steps'][k]['params'][pk] = float(pv)
                            except (TypeError, ValueError):
                                pass
        for r in (raw.get('custom_rules') or []):
            if not isinstance(r, dict):
                continue
            if (r.get('field') in RULE_FIELDS and r.get('op') in RULE_OPS
                    and r.get('action') in RULE_ACTIONS):
                try:
                    cfg['custom_rules'].append({
                        'label': str(r.get('label') or ''),
                        'field': r['field'], 'op': r['op'],
                        'value': float(r['value']), 'action': r['action']})
                except (TypeError, ValueError, KeyError):
                    pass
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg, path=None):
    """philosophy.json に保存する。成功=True。"""
    p = path or CONFIG_PATH
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def _mode(cfg, key):
    return (cfg.get('steps', {}).get(key, {}) or {}).get('mode', '標準')


def _on(cfg, key):
    return bool((cfg.get('steps', {}).get(key, {}) or {}).get('enabled', True))


def _pv(cfg, key, name):
    """調整値を取る。philosophy.jsonのparams優先→無ければ強度(mode)ごとの既定値。"""
    prm = (cfg.get('steps', {}).get(key, {}) or {}).get('params') or {}
    if name in prm:
        return prm[name]
    return default_param(key, name, _mode(cfg, key))


def _nums(ul):
    return '・'.join(str(u) for u in ul) if ul else 'なし'


# ── 各ステップ(純関数: 既に計算済みの入力を受け取り、判断と理由文を返す) ──

def _step_race_filter(cfg, arare_p, regime, skip_reasons):
    """ステップ0: 見送り判定 + 荒れ/堅いレジーム。
    調整値: skip_min_reasons(見送りにする理由の数・0で無効) / arare_hot(荒れ寄りの閾値%)。"""
    mode = _mode(cfg, 'race_filter')
    reasons = []
    skips = list(skip_reasons or [])
    need = int(_pv(cfg, 'race_filter', 'skip_min_reasons') or 0)
    hot = float(_pv(cfg, 'race_filter', 'arare_hot') or 62)
    skip = bool(need >= 1 and len(skips) >= need)
    if skips:
        reasons.append(f"情報が読みにくい条件: {'・'.join(skips)}"
                       + (f"（{need}個以上で見送り＝{mode}）" if need >= 1 else "（見送り判定はOFF）"))
    if arare_p is not None:
        pct = arare_p * 100
        if pct >= hot:
            reasons.append(f"荒れ確率{pct:.0f}%＝人気薄が3着内に来やすい（{hot:.0f}%以上を荒れ寄りと判断）")
        elif pct >= 45:
            reasons.append(f"荒れ確率{pct:.0f}%＝やや荒れ寄り")
        else:
            reasons.append(f"荒れ確率{pct:.0f}%＝堅い決着が見込める")
    reg_txt = {'②穴妙味向き': '穴寄りで考える（人気薄×検証シグナルの合議を厚く）',
               '本線向き': '本線寄りで考える（軸候補◎〇＋市場エッジを厚く）',
               '中立': '中立（軸と穴をバランス）'}.get(regime, str(regime or '—'))
    reasons.append(f"方針: {reg_txt}")
    verdict = '⛔ 見送り推奨' if skip else '✅ 検討する'
    return {'verdict': verdict, 'reasons': reasons, 'skip': skip}


def _step_elimination(cfg, horses, keshi):
    """ステップ1: 来ない馬を切る。切る馬は統合ビューの『切る』を正本として再掲する。
    強度=注意喚起の広さ(厳しめ:消去2個以上の残す馬も"要注意"として挙げる)。"""
    mode = _mode(cfg, 'elimination')
    reasons = []
    kl = list(keshi or [])
    if kl:
        detail = []
        for u in kl:
            h = horses.get(u) or {}
            en = h.get('elim', 0)
            detail.append(f"{u}番" + (f"(来にくさ{en}個)" if en else ""))
        reasons.append(f"切る: {'・'.join(detail)}")
        reasons.append("※フラグ1個では切らない。重複した数だけで判断する（単体は人気に織込み済みのため）")
    else:
        reasons.append("切る馬なし（来にくさフラグの重複が基準に届く馬がいない）")
    # 厳しめ: 切られていないが来にくさフラグが規定数ある馬を"要注意"として明示(切りはしない)
    if mode == '厳しめ':
        _w = int(_pv(cfg, 'elimination', 'warn_elim') or 2)
        warn = [u for u, h in horses.items()
                if u not in kl and (h.get('elim', 0) or 0) >= _w]
        if warn:
            reasons.append(f"要注意（切らないが来にくさ{_w}個）: {_nums(sorted(warn))}")
    if mode == 'ゆるめ':
        reasons.append("（ゆるめ: 切る馬も相手候補として一応残して見る）")
    return {'verdict': f"{len(kl)}頭を消す", 'reasons': reasons, 'keshi': kl}


def _step_danger_check(cfg, horses, danger_reasons, honmei):
    """ステップ2: 危険な人気馬。**軸からは外さない**(検証: 警告あり軸でも複勝77.5%)。信頼度の減点のみ。
    強度=どのレベルの警告を拾うか(厳しめ:△も拾う / 標準:⚠(重い)のみ / ゆるめ:本命の警告だけ)。"""
    mode = _mode(cfg, 'danger_check')
    reasons = []
    hon = (honmei or [None])[0]
    targets = []
    for u, h in horses.items():
        pop = h.get('pop')
        if not h.get('danger'):
            continue
        if mode == 'ゆるめ' and u != hon:
            continue
        if mode == '標準' and not h.get('veto') and u != hon:
            continue
        if pop is not None and pop > 5 and u != hon:
            continue          # 人気薄の危険材料は妙味判断の対象外(危険人気馬の話)
        targets.append(u)
    for u in sorted(targets, key=lambda x: (horses.get(x) or {}).get('pop') or 99):
        h = horses.get(u) or {}
        rs = danger_reasons.get(u) or []
        mark = '⚠重い' if h.get('veto') else '△軽い'
        pop = h.get('pop')
        nm = h.get('name', '')
        reasons.append(f"{mark}: {u}番 {nm}"
                       + (f"（{int(pop)}番人気）" if pop else "")
                       + (f" ← {'・'.join(rs)}" if rs else ""))
    if not targets:
        reasons.append("人気上位に危険材料なし")
    reasons.append("※危険でも軸からは外さない（検証: 警告ありの軸でも複勝77.5%的中＝切ると損）。"
                   "信頼度を下げる情報として扱う")
    hon_danger = bool(hon and (horses.get(hon) or {}).get('danger'))
    return {'verdict': ('本命に危険材料あり' if hon_danger
                        else f"{len(targets)}頭に注意" if targets else '危険な人気馬なし'),
            'reasons': reasons, 'honmei_danger': hon_danger}


def _step_value_hunt(cfg, horses, ana):
    """ステップ3: 妙味馬(人気薄)。combo=荒れ予報6シグナルの同時発火数。
    調整値: combo_min(穴に採用する好材料の重複数)。ゆるめは妙味馬ハンター🎯精鋭も追加。"""
    mode = _mode(cfg, 'value_hunt')
    reasons = []
    base = list(ana or [])
    cmin = int(_pv(cfg, 'value_hunt', 'combo_min') or 2)
    picked = [u for u in base if (horses.get(u) or {}).get('combo', 0) >= cmin]
    if mode == 'ゆるめ':
        for u, h in horses.items():
            pop = h.get('pop')
            if (u not in picked and pop is not None and pop >= 6
                    and h.get('vh_tier') == '🎯精鋭'):
                picked.append(u)
    for u in picked:
        h = horses.get(u) or {}
        c = h.get('combo', 0)
        pop = h.get('pop')
        rs = h.get('reasons', '')
        tag = '🔥敗者復活' if '敗者復活' in str(h.get('role', '')) else '🎯穴'
        reasons.append(f"{tag}: {u}番 {h.get('name','')}"
                       + (f"（{int(pop)}番人気）" if pop else "")
                       + (f" 好材料{c}個重複" if c else " 妙味馬ハンターの精鋭")
                       + (f" ← {rs}" if rs else ""))
    if not picked:
        reasons.append(f"穴候補なし（好材料が{cmin}個以上重なる人気薄がいない）")
    reasons.append(f"※好材料が1個だけの馬は穴にしない（単体シグナルはほぼ全馬に出るため）。"
                   f"重複{cmin}個以上だけを採用（検証: 2個以上でz+9.2）")
    return {'verdict': f"{len(picked)}頭を穴に採用", 'reasons': reasons, 'ana': picked}


def _step_axis_support(cfg, horses, honmei, conf_fn):
    """ステップ4: 軸の裏取り。複勝信頼度=単勝オッズ別の実複勝率(実測)。
    調整値: conf_floor(本命に求める複勝信頼度%)。割ると『軸が立たない』。"""
    mode = _mode(cfg, 'axis_support')
    floor = float(_pv(cfg, 'axis_support', 'conf_floor') or 45.0)
    reasons = []
    hon = (honmei or [None])[0]
    conf = None
    if hon is not None:
        h = horses.get(hon) or {}
        try:
            # 過剰人気の減点(前走1着/本物の先行)を受け取れる conf_fn なら渡す(どちらも検証済)
            conf = conf_fn(h.get('pop'), h.get('odds'), h.get('prev_chaku'),
                           h.get('pos_ratio')) if conf_fn else None
        except TypeError:
            try:
                conf = conf_fn(h.get('pop'), h.get('odds')) if conf_fn else None
            except Exception:
                conf = None
        except Exception:
            conf = None
        nm = h.get('name', '')
        pop = h.get('pop')
        if conf is not None:
            reasons.append(f"本命 {hon}番 {nm}"
                           + (f"（{int(pop)}番人気）" if pop else "")
                           + f" の複勝信頼度は {conf:.0f}%（同じオッズ帯の実際の複勝率）")
        else:
            reasons.append(f"本命 {hon}番 {nm} の複勝信頼度は算出できず（オッズ待ち）")
        try:
            if h.get('prev_chaku') is not None and int(h['prev_chaku']) == 1:
                reasons.append("🔨 前走1着（勝ち上がり直後）＝オッズほどには信頼できない"
                               "（検証: 同じオッズ帯の平均より複勝率が約2pp低い。切るのではなく信頼度を割り引く）")
        except (TypeError, ValueError):
            pass
        try:
            _pr = h.get('pos_ratio')
            if _pr is not None and 0 < float(_pr) < 0.28:
                reasons.append("🏃 本物の先行（いつも前めを走る馬）＝これもオッズほどには信頼できない"
                               "（検証: よく来ているように見えるが、その分すでにオッズが安い。"
                               "前走1着と重なると割高がさらに増す）")
        except (TypeError, ValueError):
            pass
        edges = str(h.get('reasons', '') or '')
        if edges:
            reasons.append(f"本命の裏付け材料: {edges}")
        else:
            reasons.append("本命に独立した裏付け材料なし（素点＝能力スコアのみで先頭）")
    else:
        reasons.append("本命が決まっていない")
    weak = (conf is not None and conf < floor)
    if weak:
        reasons.append(f"⚠ 信頼度が基準（{floor:.0f}%・{mode}）を下回る＝軸が立ちにくいレース")
    return {'verdict': (f"信頼度 {conf:.0f}%" if conf is not None else '判定不可'),
            'reasons': reasons, 'weak_axis': weak, 'conf': conf, 'floor': floor}


def _step_bet_build(cfg, regime, honmei, aite, ana, osae, arare_p):
    """ステップ5: 買い目の骨格。券種/点数の絞り方を決める(実際の点数はtrio_engineが出す)。
    調整値: aite_max(相手の頭数)。足りない分は押さえから補充する。"""
    mode = _mode(cfg, 'bet_build')
    reasons = []
    amax = int(_pv(cfg, 'bet_build', 'aite_max') or 3)
    a = list(aite or [])[:amax]
    if len(a) < amax:                       # 相手が足りなければ押さえから補充(手広く見る側)
        for u in (osae or []):
            if len(a) >= amax:
                break
            if u not in a:
                a.append(u)
    hon = list(honmei or [])
    an = list(ana or [])
    hot = float(_pv(cfg, 'race_filter', 'arare_hot') or 62) / 100.0
    if regime == '②穴妙味向き' or (arare_p is not None and arare_p >= hot):
        kind = '3連複/3連単フォーメーション（穴を3列目に厚く）'
        reasons.append("荒れ寄りのレースなので、穴を3列目に置くフォーメーションが合う"
                       "（検証で最も相性が良かった帯）")
    else:
        kind = '3連複（本命から手堅く・点数を絞る）'
        reasons.append("本線寄りのレースなので、本命から手堅く。点数を増やさない")
    reasons.append(f"1列目(本命): {_nums(hon)} ／ 2列目(相手): {_nums(a)} ／ 3列目(穴): {_nums(an)}"
                   f"　※相手は{amax}頭まで（{mode}設定）")
    reasons.append("※3連単フォーメーションの実配当検証: 控除率(75%)は有意に超えるが、"
                   "回収率の中央値は83〜90%で100%には届いていない。**利益が出ると約束はできない**")
    return {'verdict': kind, 'reasons': reasons, 'aite': a, 'kind': kind}


def _step_devil(cfg, weak_axis, honmei_danger, skip, arare_p, ana):
    """ステップ6: 反対役。軸が弱い×本命に危険材料 → 見送りへ差し戻す。
    強度=差し戻しの厳しさ(厳しめ:どちらか一方でも / 標準:両方 / ゆるめ:差し戻さない)。"""
    mode = _mode(cfg, 'devil_advocate')
    reasons = []
    if mode == '厳しめ':
        back = bool(weak_axis or honmei_danger)
    elif mode == 'ゆるめ':
        back = False
    else:
        back = bool(weak_axis and honmei_danger)
    if weak_axis:
        reasons.append("本命の複勝信頼度が基準を下回っている（軸が立たないと点数が膨らむだけ）")
    if honmei_danger:
        reasons.append("本命に危険材料が出ている（過剰人気の疑い）")
    if not ana:
        reasons.append("穴候補もいない＝人気薄で拾える妙味がない")
    reasons.append("この予想が間違っている可能性: シグナルが市場に織込み済み(priced-in)なら妙味はゼロ。"
                   "『きれいにまとまった予想』ほど疑う")
    if back and not skip:
        reasons.append("⛔ 以上より **見送り** に差し戻す")
    elif not weak_axis and not honmei_danger:
        reasons.append("軸は立っている。大きな反対材料なし")
    return {'verdict': ('⛔ 見送りに差し戻し' if back else '✅ このまま進む'),
            'reasons': reasons, 'back_to_skip': back}


def _step_my_rules(cfg, horses, honmei, aite, ana, keshi):
    """ステップ7(⑧): 自分のルール。cfg['custom_rules'] を上から順に当てる。

    **検証外**: ここは統計的裏付けのない個人ルール(elim_reasons/パドック台帳と同じ扱い)。
    参照するのは既に計算済みの値(人気/オッズ/好材料の重複/来にくさ)だけで、新しい指標は作らない。
    action='消し' は買い目から外す。action='注意' は表示のみ。
    """
    rules = list(cfg.get('custom_rules') or [])
    reasons = []
    hit_cut, hit_warn = [], []
    if not rules:
        return {'verdict': 'ルール未設定', 'reasons': [
            "ここに自分の判断ルールを足せます（例: 12番人気以下は買わない）。"
            "※検証外の個人ルールです。検証済みエッジとは分けて扱われます"],
            'cut': [], 'warn': []}
    protect = set(honmei or []) | set(ana or [])   # 本命と穴は自分ルールで消さない(誤爆防止)
    for r in rules:
        f, op, val = r['field'], r['op'], float(r['value'])
        lab = r.get('label') or f"{RULE_FIELDS.get(f, f)} が {val:g} {RULE_OPS.get(op, op)}"
        hits = []
        for u, h in horses.items():
            v = h.get(f)
            if v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if (op == '>=' and v >= val) or (op == '<=' and v <= val):
                hits.append(u)
        hits.sort()
        if not hits:
            reasons.append(f"「{lab}」→ 該当なし")
            continue
        if r['action'] == '消し':
            cut = [u for u in hits if u not in protect and u not in (keshi or [])]
            skipped = [u for u in hits if u in protect]
            hit_cut += cut
            reasons.append(f"「{lab}」→ 消し: {_nums(cut) if cut else 'なし'}"
                           + (f"（{_nums(skipped)}は本命/穴のため消さない）" if skipped else ""))
        else:
            hit_warn += hits
            reasons.append(f"「{lab}」→ 注意: {_nums(hits)}")
    reasons.append("※自分のルールは**検証していない個人の判断**です。"
                   "検証済みエッジ（①〜⑦）とは分けて表示しています")
    v = []
    if hit_cut:
        v.append(f"{len(set(hit_cut))}頭を追加で消し")
    if hit_warn:
        v.append(f"{len(set(hit_warn))}頭に注意")
    return {'verdict': ('・'.join(v) if v else '該当なし'),
            'reasons': reasons, 'cut': sorted(set(hit_cut)), 'warn': sorted(set(hit_warn))}


def think(horses_rows, groups, regime=None, arare_p=None, skip_reasons=None,
          danger_reasons=None, conf_fn=None, config=None):
    """思考フロー(ステップ0〜7)を実行し、判断と理由文を返す。

    horses_rows: consensus_view.integrate() の戻り ['horses'] をそのまま渡す
                 ({'umaban','name','pop','odds','combo','elim','danger','veto','role',
                   'reasons','vh_tier',...})
    groups:      同 ['groups'] ({'honmei','aite','ana','osae','keshi'})
    regime:      trio_lean の 'lean'('②穴妙味向き'/'本線向き'/'中立')
    arare_p:     value_scanner.arare_prob() の戻り(0..1) or None
    skip_reasons: value_scanner.race_skip_reasons() の戻り(list)
    danger_reasons: build_edge_sets()['danger_reasons']
    conf_fn:     axis_selector.axis_confidence 相当(pop, odds)->% or None

    戻り値: {'steps': [{key,no,name,desc,enabled,verdict,reasons[]}...],
             'final': {'honmei','aite','ana','keshi','plan','skip','skip_reasons'}}
    """
    cfg = config or load_config()
    horses = {h['umaban']: h for h in (horses_rows or []) if h.get('umaban') is not None}
    groups = groups or {}
    danger_reasons = danger_reasons or {}

    steps_out = []
    state = {}

    def _run(key, fn):
        meta = next((s for s in STEPS if s[0] == key), None)
        _, no, name, desc = meta
        if not _on(cfg, key):
            steps_out.append({'key': key, 'no': no, 'name': name, 'desc': desc,
                              'enabled': False, 'mode': _mode(cfg, key),
                              'verdict': 'スキップ（このステップはOFF）', 'reasons': []})
            return {}
        r = fn()
        steps_out.append({'key': key, 'no': no, 'name': name, 'desc': desc,
                          'enabled': True, 'mode': _mode(cfg, key),
                          'verdict': r.get('verdict', ''), 'reasons': r.get('reasons', [])})
        return r

    r0 = _run('race_filter', lambda: _step_race_filter(cfg, arare_p, regime, skip_reasons))
    state.update(r0)
    r1 = _run('elimination', lambda: _step_elimination(cfg, horses, groups.get('keshi')))
    r2 = _run('danger_check', lambda: _step_danger_check(cfg, horses, danger_reasons,
                                                         groups.get('honmei')))
    r3 = _run('value_hunt', lambda: _step_value_hunt(cfg, horses, groups.get('ana')))
    r4 = _run('axis_support', lambda: _step_axis_support(cfg, horses, groups.get('honmei'),
                                                         conf_fn))
    ana_final = r3.get('ana', list(groups.get('ana') or []))
    r5 = _run('bet_build', lambda: _step_bet_build(cfg, regime, groups.get('honmei'),
                                                   groups.get('aite'), ana_final,
                                                   groups.get('osae'), arare_p))
    r6 = _run('devil_advocate', lambda: _step_devil(
        cfg, r4.get('weak_axis', False), r2.get('honmei_danger', False),
        r0.get('skip', False), arare_p, ana_final))
    aite_final = r5.get('aite', list(groups.get('aite') or []))
    keshi_final = r1.get('keshi', list(groups.get('keshi') or []))
    r7 = _run('my_rules', lambda: _step_my_rules(cfg, horses, groups.get('honmei'),
                                                 aite_final, ana_final, keshi_final))
    # 自分のルールの『消し』を反映(本命/穴は保護済み)。相手からも外す。
    _mycut = list(r7.get('cut') or [])
    if _mycut:
        keshi_final = keshi_final + [u for u in _mycut if u not in keshi_final]
        aite_final = [u for u in aite_final if u not in _mycut]

    skip = bool(r0.get('skip')) or bool(r6.get('back_to_skip'))
    skip_why = []
    if r0.get('skip'):
        skip_why += list(skip_reasons or [])
    if r6.get('back_to_skip'):
        if r4.get('weak_axis'):
            skip_why.append('本命の複勝信頼度が基準割れ')
        if r2.get('honmei_danger'):
            skip_why.append('本命に危険材料')

    final = {
        'honmei': list(groups.get('honmei') or []),
        'aite': aite_final,
        'ana': ana_final,
        'keshi': keshi_final,
        'plan': ('見送り' if skip else r5.get('kind', '')),
        'skip': skip,
        'skip_reasons': skip_why,
        'my_warn': list(r7.get('warn') or []),
    }
    return {'steps': steps_out, 'final': final}
