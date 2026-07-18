# -*- coding: utf-8 -*-
"""危険人気馬 共通Veto（軸選定・買い目で再利用する1本の窓口）。

検証済みの「人気上位(1-3番人気)が"人気の割に来ない/割引"」シグナルだけを集約する。
これは予測でなく fade(軸からの降格・消去)側＝市場を破れる側。順張り(買い増し)には使わない。
- 1番人気は重不良で構造的に危険(verified_heavy_track_bias)
- 道悪×サンデー瞬発/ステゴ系(verified_baba_blood の FADE)
- 外有利日×内枠×1-3番人気(verified_emp_bias_danger)
- 牝×冬春fade(feedback_folk_signals_overbet)
- トップ騎手乗替/斤量比≥12.6%(project_elimination_engine dangerfav検証)
- ガラス人気馬(単勝売れ×複勝薄=大衆の錯覚人気・verified z-8.5・単複逆転FADE)
- 『ソフト理由』(他に硬い危険がある時のみseverityに算入・単独では非表示):
  半年休み明け(-6.2pp z-7.5)/中9週+ローテ63-179日(-1.6pp z-5.6・2026-07実測・ROIフラット=
  軸信頼度のみ)/前走逃げ(dangerfav残差+0.005≒0で単独では弱い)
- Stressはリーク無しの3つのみ(verified_stress_debuff): 小柄×馬体減/芝×後方ぐせ/馬体増

severity = 該当した危険理由数。使い分け:
  0 = 通常 / 1+ = 注意マーク(⚠)。軸からは外さない。
※66R台帳で検証: 警告あり軸の的中率77.5% vs なし80.8%=差3.3ppで切るには弱すぎる。
  注意マークとして表示し、最終判断はユーザーに委ねる。

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
                prev_kyaku=None, prev_chaku=None, stress_flags=None,
                win_odds=None, place_mid=None):
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

    # ④' ガラスの人気馬(単勝は売れてるのに複勝が売れてない=大衆の錯覚人気・検証z-8.5)
    # 単複逆転FADE(tanpuku_divergenceの裏)。複勝オッズは事前市場値=リーク無し。硬い危険理由。
    if win_odds is not None and place_mid is not None:
        try:
            from core import value_scanner as _vs_glass
            _gl, _gr = _vs_glass.glass_favorite_fade(win_odds, place_mid, ninki=nk)
            if _gl:
                reasons.append(f'🥃ガラス人気馬(複勝薄x{_gr})')
        except Exception:
            pass

    # ⑤ dangerfav検証済み(-ファクター)
    if top_jockey_swap:
        reasons.append('トップ騎手乗替')
    if kinratio:
        reasons.append('斤量比≥12.6%')
    try:
        if layoff_days is not None and int(layoff_days) >= 180:
            reasons.append('半年休み明け')
        elif layoff_days is not None and int(layoff_days) >= 63:
            # 中9週以上(63〜179日)ローテ×人気馬: 複勝残差-1.6pp/z-5.6(2016+ n=3.0万・実測)。
            # 複勝ROIはフラット=市場は織込み済み→fade(儲け)でなく軸信頼度の減点のみ。
            # 半年休み明け(-6.2pp)より弱いため別ラベルの同ソフト扱い。
            reasons.append('中9週+ローテ')
    except (TypeError, ValueError):
        pass
    if str(prev_kyaku or '') == '1':       # 前走逃げ
        reasons.append('前走逃げ')
    # 高齢(7歳+): 削除。66R台帳で軸3回中3回的中=逆効果。元の検証(train-5.0pp/holdout-12.1pp)は
    # 全人気帯の平均値であり、軸候補の1-3番人気では効かない。再導入しない。

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
    _SOFT = {'半年休み明け', '中9週+ローテ', '前走逃げ', '前走5着以下'}
    hard = [r for r in reasons if r not in _SOFT]
    soft = [r for r in reasons if r in _SOFT]
    final = hard + (soft if hard else [])
    sev = len(final)
    return {'veto': False, 'severity': sev, 'reasons': final}


def axis_demote(mark_text, veto_res):
    """AxisMark(◎〇▲...)の表示を severity に応じて注意マーク付与。
    severity>=2: 軸→押さえに降格を推奨(マークは残し ⚠押さえ推奨 と理由を付記)。
    severity==1: マークは残し ⚠注意 と理由を付記。
    軸から完全に外すことはしない(66R台帳で警告あり軸77.5%的中=切ると損)。
    """
    if not veto_res or veto_res['severity'] == 0:
        return mark_text
    rs = '・'.join(veto_res['reasons'])
    if veto_res['severity'] >= 2:
        return (mark_text + f" ⚠押さえ推奨({rs})").strip()
    return (mark_text + f" ⚠注意({rs})").strip()
