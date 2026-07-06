# -*- coding: utf-8 -*-
"""危険人気馬 共通Veto（軸選定・買い目で再利用する1本の窓口）。

検証済みの「人気上位(1-3番人気)が"人気の割に来ない/割引"」シグナルだけを集約する。
これは予測でなく fade(軸からの降格・消去)側＝市場を破れる側。順張り(買い増し)には使わない。
- 1番人気は重不良で構造的に危険(verified_heavy_track_bias)
- 道悪×サンデー瞬発/ステゴ系(verified_baba_blood の FADE)
- 外有利日×内枠×1-3番人気(verified_emp_bias_danger)
- 牝×冬春fade(feedback_folk_signals_overbet)
- トップ騎手乗替/斤量比≥12.6%(project_elimination_engine dangerfav検証)
- 『ソフト理由』(他に硬い危険がある時のみseverityに算入・単独では非表示):
  半年休み明け(-7ppだが絶対複勝率45-60%と高く精度低・NARはjravan疎で誤爆)/
  前走逃げ(dangerfav残差+0.005≒0で単独では弱い)
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
                prev_kyaku=None, prev_chaku=None, stress_flags=None):
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
    # 高齢(7歳+): 人気馬(1-4)で複勝残差 train-5.0pp/holdout-12.1pp・z有意(ピーク過ぎ・市場が過小割引)。
    # 絶対複勝率36%で単独精度は中程度→ソフト理由(半年休み明けと同扱い)。sex_age例"牡7"から年齢抽出。
    try:
        _agv = int(''.join(c for c in str(sex_age or '') if c.isdigit()) or 0)
        if _agv >= 7:
            reasons.append('高齢(7歳+)')
    except (TypeError, ValueError):
        pass
    # 前走5着以下: 人気馬でも複勝残差 train-1.5pp/holdout-1.8pp・z有意(前走負けたのに今も人気=市場が過信)。
    # 生の前走着順は人気に大半織込み済み(残差は小)だが独立分は残る→ソフト理由(単独では非表示)。
    try:
        if prev_chaku is not None and int(prev_chaku) >= 5:
            reasons.append('前走5着以下')
    except (TypeError, ValueError):
        pass

    # ⑥ Stress(リーク無しのみ)
    for f in (stress_flags or []):
        if f in _STRESS_OK:
            reasons.append('Stress:' + f)

    # ソフト理由(単独では危険表示しない): 半年休み明けは1-3人気で複勝残差-7pp(検証済)だが
    # 絶対複勝率は45〜60%(1番人気は60%)と高く単独では"来る"ことが多い＝精度が低い。
    # 加えてNAR/直近レースはjravanの収録が疎で休養日数を過大算出し誤爆する。
    # → 他に硬い危険理由がある時のみ severity に算入(単独では0＝表示しない)。
    # 前走逃げも同様に単独では弱い(dangerfav検証 残差+0.005≒0)=ソフト理由。
    _SOFT = {'半年休み明け', '前走逃げ', '高齢(7歳+)', '前走5着以下'}
    hard = [r for r in reasons if r not in _SOFT]
    soft = [r for r in reasons if r in _SOFT]
    final = hard + (soft if hard else [])
    sev = len(final)
    return {'veto': sev >= 2, 'severity': sev, 'reasons': final}


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
