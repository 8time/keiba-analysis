# -*- coding: utf-8 -*-
"""危険人気馬 共通Veto（軸選定・買い目で再利用する1本の窓口）。

検証済みの「人気上位(1-3番人気)が"人気の割に来ない/割引"」シグナルだけを集約する。
これは予測でなく fade(軸からの降格・消去)側＝市場を破れる側。順張り(買い増し)には使わない。
- 1番人気は重不良で構造的に危険(verified_heavy_track_bias)
- 道悪×サンデー瞬発/ステゴ系(verified_baba_blood の FADE)
- 外有利日×内枠×1-3番人気(verified_emp_bias_danger)
- 牝×冬春fade(feedback_folk_signals_overbet)
- トップ騎手乗替/斤量比≥12.6%/半年休み明け/前走逃げ(project_elimination_engine dangerfav検証)
- Stressはリーク無しの3つのみ(verified_stress_debuff): 小柄×馬体減/芝×後方ぐせ/馬体増

severity = 該当した危険理由数。使い分け(検証台帳の相対de-rank方針):
  0 = 通常 / 1 = 軸は降格注意(相手までは残す) / 2以上 = 軸不可(veto=True)。
※危険人気馬も来る時は来る(相対 -2.6〜-4.6pp)。"完全消し"でなく軸からの降格が基本。

全引数 optional。呼び出し側は手元にある情報だけ渡せばよい(無い条件はスキップされる)。
"""
try:
    from core import track_bias as _tb
except Exception:  # pragma: no cover
    _tb = None

_FADE_MONTHS = {12, 1, 2, 3}          # 牝×冬春fade の対象月
_STRESS_OK = {'小柄×馬体減', '芝×後方ぐせ', '馬体増'}  # リーク無しのみ採用


def danger_veto(*, ninki=None, surface='', baba='', sire='', sex_age='',
                month=None, emp_bias=None, umaban=None, tosu=None,
                top_jockey_swap=False, kinratio=False, layoff_days=None,
                prev_kyaku=None, stress_flags=None):
    """戻り値: {'veto': bool, 'severity': int, 'reasons': [str,...]}"""
    try:
        nk = int(ninki)
    except (TypeError, ValueError):
        return {'veto': False, 'severity': 0, 'reasons': []}
    if nk < 1 or nk > 3:                # 危険人気馬＝人気上位限定
        return {'veto': False, 'severity': 0, 'reasons': []}

    surf = str(surface or '')
    is_turf = '芝' in surf
    is_dirt = 'ダ' in surf
    bb = str(baba or '')
    wet = bb in ('重', '不良')
    reasons = []

    # ① 重/不良×1番人気(芝は重・不良/ダは不良)
    if nk == 1 and ((is_turf and wet) or (is_dirt and bb == '不良')):
        reasons.append('🌧️重不良×1番人気')

    # ② 道悪×サンデー瞬発/ステゴ系(FADE)
    if sire and wet and _tb is not None:
        try:
            bm = _tb.heavy_fav_blood_mod(sire, surf, bb)
            if bm and bm.get('mod') == 'intensify':
                reasons.append('⚠瞬発系道悪')
        except Exception:
            pass

    # ③ 外有利日×内枠×1-3番人気
    if emp_bias is not None and umaban is not None and tosu is not None and _tb is not None:
        try:
            dp = _tb.danger_popular_inner(emp_bias, umaban, tosu, nk)
            if dp:
                reasons.append('外有利×内枠人気')
        except Exception:
            pass

    # ④ 牝×冬春fade
    try:
        if sex_age and '牝' in str(sex_age) and month and int(month) in _FADE_MONTHS:
            reasons.append('牝×冬春fade')
    except (TypeError, ValueError):
        pass

    # ⑤ dangerfav検証済み(-ファクター)
    if top_jockey_swap:
        reasons.append('トップ騎手乗替')
    if kinratio:
        reasons.append('斤量比≥12.6%')
    try:
        if layoff_days is not None and int(layoff_days) >= 180:
            reasons.append('半年休み明け')
    except (TypeError, ValueError):
        pass
    if str(prev_kyaku or '') == '1':       # 前走逃げ
        reasons.append('前走逃げ')

    # ⑥ Stress(リーク無しのみ)
    for f in (stress_flags or []):
        if f in _STRESS_OK:
            reasons.append('Stress:' + f)

    sev = len(reasons)
    return {'veto': sev >= 2, 'severity': sev, 'reasons': reasons}


def axis_demote(mark_text, veto_res):
    """AxisMark(◎〇▲...)の表示を severity に応じて降格する。
    severity>=2: 軸不可→マークを外し ⚠危険(理由) に置換。
    severity==1: マークは残し ⚠ と理由を付記(降格注意)。
    """
    if not veto_res or veto_res['severity'] == 0:
        return mark_text
    rs = '・'.join(veto_res['reasons'])
    if veto_res['severity'] >= 2:
        return f"⚠危険({rs})"
    return (mark_text + f" ⚠{rs}").strip()
