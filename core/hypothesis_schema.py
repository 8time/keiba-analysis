# -*- coding: utf-8 -*-
"""検証可能仮説スキーマ + 俗説照合 ―― カード7(⑨ MAGI仮説パイプライン)。

MAGI回顧の学習タグ(人間のおしゃべり由来)を、そのままauto_feature_search等の
検証パイプラインに投げられる『検証可能仮説』へ変換する弁別器。

役割:
  1) 俗説(検証で否定済み)を100%隔離する = is_folk_belief
  2) 検証可能なスキーマに整形する         = make_hypothesis / validate_hypothesis
  3) 検証キュー投入用の候補に変換する      = to_feature_candidate

⚠自動デプロイは絶対にしない。ここは『検証キューに載せる資格があるか』の門番のみ。
実際の採否は auto_feature_search / *_backtest.py の holdout ゲートが決める。
"""

# 検証で否定済み = 隔離する俗説(memory/verified_* 準拠)。(キーワード, 却下理由)。
# ※末脚/単複乖離/ハンデ/16頭/オッズ本命不在/厩舎当コース 等の検証済みエッジは含めない。
REJECTED = [
    (['初ブリンカー', '初ブリ', 'ブリンカー'], '初ブリンカーは正の妙味ゼロ(folk_signals_overbet)'),
    (['距離短縮', '短縮'], '距離短縮は織込み済み(folk_signals_overbet)'),
    (['お帰り', '前走同コース', 'コース替わり巧'], 'お帰り効果は妙味ゼロ(folk_signals_overbet)'),
    (['休み明け', '叩き'], '休み明け/叩き好走は織込み済み'),
    (['季節', '夏馬', '冬馬'], '季節ローテは妙味ゼロ(folk_signals_overbet)'),
    (['初ダート', '初芝'], '初ダートは正の妙味ゼロ(folk_signals_overbet)'),
    (['ショッカー', 'Mの法則', '生体', 'IoT'], 'ショッカー理論はリーク/織込み済み(shocker_leak)'),
    (['展開恩恵', '好位', '展開向く', '展開が向', '前が有利'], '展開恩恵は織込み済み(tenkai_priced_in)'),
    (['巻き返し', 'リベンジ', '次走巻'], '巻き返し穴は誤り・ROI66-68%(comeback_overbet)'),
    (['PCI', 'ペースチェンジ', 'RPCI'], 'PCIは軸/相手/消去いずれもエッジ無し=完全終了(pci_pricedin)'),
    (['脚質', '追込有利', '逃げ有利'], '習性脚質は軸に織込み済み(legtype_axis)'),
    (['5走前', 'SS理論', '補正タイム俗'], '5走前理論/補正タイム俗説は否定(5run_theory_debunk)'),
    (['0.6秒', '0.8秒', '前走着差'], '前走着差は織込み済み(prior_margin_debunk)'),
    (['単勝期待値', '期待値ゾーン', '単勝妙味帯'], '単勝ROIは全帯で効率的(tansho_roi_efficient)'),
    (['バイアス順張り', '合致馬を買', 'Vエリア買'], '当日バイアス順張りは死(emp_bias_danger)'),
    (['圧勝馬を単勝', '圧勝→単勝'], '前走圧勝の人気馬は単勝で過剰人気(ohtani_trap・相手/複勝軸ならOK)'),
]

VALID_ROLES = ('軸', '相手', '消去', '妙味', '荒れ')
VALID_BANDS = ('1-3', '4-5', '6+', '全')


def is_folk_belief(text):
    """テキストが俗説に該当するか。戻り値: (bool, reason or None)。"""
    t = str(text or '')
    for kws, reason in REJECTED:
        if any(kw in t for kw in kws):
            return True, reason
    return False, None


def make_hypothesis(tag, role='相手', popularity_band='6+', note='', feature_hint=''):
    """学習タグを検証可能仮説スキーマに整形する。
    スキーマ = 特徴量名(tag)/役割/対象人気帯/メモ/特徴ヒント/状態。"""
    return {
        'tag': str(tag).strip(),
        'role': role if role in VALID_ROLES else '相手',
        'popularity_band': popularity_band if popularity_band in VALID_BANDS else '6+',
        'note': str(note).strip(),
        'feature_hint': str(feature_hint).strip(),
        'status': 'queued',  # queued -> (backtest) -> adopted/rejected。自動デプロイはしない。
    }


def validate_hypothesis(hyp):
    """スキーマ妥当性 + 俗説でないこと。戻り値: (ok, reason)。
    ok=False の reason は隔離理由 or スキーマ不備。"""
    if not isinstance(hyp, dict):
        return False, 'スキーマがdictでない'
    tag = str(hyp.get('tag', '')).strip()
    if not tag:
        return False, 'tagが空'
    folk, reason = is_folk_belief(tag + ' ' + str(hyp.get('note', '')))
    if folk:
        return False, f'俗説隔離: {reason}'
    if hyp.get('role') not in VALID_ROLES:
        return False, f'roleが不正({hyp.get("role")})'
    if hyp.get('popularity_band') not in VALID_BANDS:
        return False, f'popularity_bandが不正({hyp.get("popularity_band")})'
    return True, 'ok'


def to_feature_candidate(hyp):
    """検証キュー(auto_feature_search等)投入用の候補dictへ。
    validate通過が前提。実際の採否はholdoutゲートが決める(ここでは投入資格のみ)。"""
    return {
        'name': hyp['tag'],
        'role': hyp['role'],
        'band': hyp['popularity_band'],
        'note': hyp.get('note', ''),
        'source': 'magi_retro',
        'gate': 'holdout_recall7_or_residual_z',  # 実際のゲート名(未デプロイ)
    }
