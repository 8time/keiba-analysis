# -*- coding: utf-8 -*-
"""
当てにいく馬券フィルター（ソフト＝削除せず並べ替え＋印） — core/bet_filter.py

通常の馬券フィルターは「トリガミ回避で点数を減らす」ネガティブ方向。
これは逆に『検証済みエッジに合致する買い目を上位に並べ＋🎯印を付ける』ポジティブ方向。
全券種(3連複/馬連/馬単/ワイド…)の買い目リストに横断適用できる共通関数。

検証根拠(すべて当セッションで検証済み):
- 価格帯: ②穴は3連複70〜700倍に7割集中(verified_trio_payout_band)。in_bandが入口。
- 穴脚エッジ: 🔵補正T上位/末脚top の人気薄は複勝で来やすい(verified_corrected_time/spurt_index)。
- 危険除外: 重不良×1番人気(verified_heavy_track_bias)・消去フィルターの消し馬は飛ぶ。
※市場は効率的で+ROIは作れない(verified_tansho_roi_efficient)。本フィルターの狙いは
  『同じ点数で当てる確率/価値を上げる』＝削らず並べ替えて根拠を可視化すること。
"""

W_BAND = 3.0      # 狙い目価格帯
W_EDGE = 1.6      # 穴脚に検証エッジ(1脚ごと)
W_DANGER = 2.6    # 危険馬を含む(1頭ごと・減点)


def annotate_bets(bets, *, edge_horses=None, danger_horses=None, ana_set=None,
                  in_band_key='in_band', edge_reasons=None, danger_reasons=None):
    """買い目リストに妙味度(aim_score)・印(aim_tag)・根拠(aim_reason)を付与し降順で返す。

    bets: [{'combo': iterable of umaban(int), in_band_key: bool(任意), ...}, ...]
    edge_horses: 検証エッジ馬(補正T/末脚top/厩舎当ｺｰｽ/黄金ライン/道悪軸…)のumaban set
    danger_horses: 危険馬(重不良×1番人気/道悪FADE/消去の消し馬)のumaban set
    ana_set: 穴馬(人気薄)のumaban set。エッジは穴脚に乗ると価値が高い。
    edge_reasons/danger_reasons: {umaban: [ラベル..]} 馬ごとの具体的な根拠ラベル(任意・表示用)。
    戻り: 同じdictに aim_score/aim_tag/aim_reason/edge_legs/danger_legs を足し aim_score降順。

    🎯は『狙い目価格帯 かつ 穴脚に検証エッジ』が揃った組だけ(価格帯は的中を予測しない=
    [[verified_tansho_roi_efficient]]のため、価格帯のみでは🎯を付けない)。
    """
    edge = {int(u) for u in (edge_horses or [])}
    danger = {int(u) for u in (danger_horses or [])}
    ana = {int(u) for u in (ana_set or [])}
    e_reasons = {int(k): list(v) for k, v in (edge_reasons or {}).items()}
    d_reasons = {int(k): list(v) for k, v in (danger_reasons or {}).items()}

    def _labels(legs, rmap):
        seen = []
        for u in legs:
            for lab in rmap.get(u, []):
                if lab not in seen:
                    seen.append(lab)
        return seen

    out = []
    for b in bets:
        try:
            combo = [int(u) for u in (b.get('combo') or [])]
        except Exception:
            combo = []
        in_band = bool(b.get(in_band_key))
        edge_legs = [u for u in combo if u in edge]
        danger_legs = [u for u in combo if u in danger]
        edge_ana = [u for u in edge_legs if u in ana]
        score = 0.0
        reasons = []
        if in_band:
            score += W_BAND
            reasons.append('狙い目価格帯')
        if edge_legs:
            # 穴脚に乗ったエッジは満額、人気脚のエッジは半額(穴の方が妙味)
            score += W_EDGE * (len(edge_ana) + 0.5 * (len(edge_legs) - len(edge_ana)))
            _elab = _labels(edge_legs, e_reasons)
            reasons.append('・'.join(_elab) if _elab
                           else f"検証エッジ脚{len(edge_legs)}" + (f"(穴{len(edge_ana)})" if edge_ana else ''))
        if danger_legs:
            score -= W_DANGER * len(danger_legs)
            _dlab = _labels(danger_legs, d_reasons)
            reasons.append('⚠' + ('・'.join(_dlab) if _dlab else f"危険馬{len(danger_legs)}"))
        # 🎯は価格帯×穴脚エッジの合致時のみ(価格帯だけ/エッジだけは別チップに降格)
        if danger_legs:
            tag = '⚠'
        elif in_band and edge_ana:
            tag = '🎯'
        elif edge_legs:
            tag = '🔵エッジ'
        elif in_band:
            tag = '価格帯'
        else:
            tag = ''
        nb = dict(b)
        nb['aim_score'] = round(score, 1)
        nb['aim_tag'] = tag
        nb['aim_reason'] = ' / '.join(reasons) or '-'
        nb['edge_legs'] = edge_legs
        nb['danger_legs'] = danger_legs
        out.append(nb)
    out.sort(key=lambda b: -b['aim_score'])
    return out
