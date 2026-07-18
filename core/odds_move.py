# -*- coding: utf-8 -*-
"""オッズ変動インサイト(朝一↔直前) — core/odds_move.py

記録した時系列オッズ(OddsTracker.get_history_df)から、蘆口真史『オッズ分析の教科書』の
『時間帯別比較(朝一 vs 直前の人気順位変化)』に基づく気づき/警告/推奨を生成する。

⚠検証ステータス(正直な前提):
  このアプリの凍結DB(jravan)にはオッズ時系列が無く、確定オッズのみ。よって本書の主張
  (朝一1番人気→直前落ち=単回収118 等)は**このアプリでバックテスト未検証**。
  =検証済みエッジ(補正T/末脚/combo/単複乖離等)とは別枠の『書籍準拠・参考』表示に留める。
  今後この記録機能で朝一/直前スナップショットが貯まれば自前データで検証可能。

  既に検証済みで別実装のもの(重複しない): 倍率比r21・単勝30倍未満頭数live30
  →荒れロジット(scanner_arare_logit)に配線済み。ここは"変動(時系列)"の観察に特化。

入力: history_df = OddsTracker.get_history_df の戻り(列 timestamp,umaban,odds_type,odds_value)。
出力: {'ok':bool, 'first_ts','last_ts', 'insights':[{umaban,kind,severity,reason}], 'note':str}
  kind: 'fav_solid'|'fav_fake'|'hidden_ana'|'danger_late' ほか。severity: 'good'|'warn'|'info'。
"""


def _rank_map(snap):
    """{umaban: win_odds} → {umaban: 人気順位(1=最良)}。オッズ昇順。"""
    valid = [(u, o) for u, o in snap.items() if o and o > 0]
    valid.sort(key=lambda x: x[1])
    return {u: i + 1 for i, (u, _) in enumerate(valid)}


def _snap_at(history_df, ts):
    """指定timestampの {umaban: win_odds}。"""
    sub = history_df[(history_df['timestamp'] == ts) & (history_df['odds_type'] == 'win')]
    out = {}
    for _, r in sub.iterrows():
        try:
            u = int(r['umaban']); o = float(r['odds_value'])
            if o > 0:
                out[u] = o
        except (TypeError, ValueError):
            continue
    return out


def analyze_odds_movement(history_df, ana_pop=4):
    """朝一(最古スナップ)↔直前(最新スナップ)の人気順位変化から気づきを生成。

    ana_pop: 直前でこの人気以下=穴馬扱い(隠れた本命候補の抽出帯)。
    """
    empty = {'ok': False, 'insights': [], 'note': ''}
    if history_df is None or len(history_df) == 0 or 'odds_type' not in history_df.columns:
        return empty
    win = history_df[history_df['odds_type'] == 'win']
    ts_list = sorted(win['timestamp'].dropna().unique())
    if len(ts_list) < 2:
        return {'ok': False, 'insights': [],
                'note': '朝一↔直前の比較には2回以上の記録が必要(例:8:40と発走10分前)。'}
    first, last = ts_list[0], ts_list[-1]
    r_first = _rank_map(_snap_at(history_df, first))
    r_last = _rank_map(_snap_at(history_df, last))
    if not r_first or not r_last:
        return empty
    insights = []

    # ① 直前1番人気の『成り立ち』(朝一からの支持か・直前浮上か)
    fav = min(r_last, key=r_last.get)  # 直前1番人気
    ef = r_first.get(fav)
    if ef is not None:
        if ef == 1:
            insights.append({'umaban': fav, 'kind': 'fav_solid', 'severity': 'good',
                             'reason': f'1番人気は朝一から1番人気＝支持が一貫・信頼度高（軸○）'})
        elif ef == 2:
            insights.append({'umaban': fav, 'kind': 'fav_mid', 'severity': 'info',
                             'reason': f'1番人気だが朝一は2番人気＝押さえ評価が妥当（軸は半信）'})
        else:
            insights.append({'umaban': fav, 'kind': 'fav_fake', 'severity': 'warn',
                             'reason': f'⚠見せかけの1番人気（朝一{ef}番人気→直前で浮上）＝'
                                       f'直前の一般票で過剰人気の可能性・軸は慎重に'})

    # ② 隠れた本命(穴): 朝一で売れていたのに直前で人気を落とした馬
    #    書籍: 朝一1番人気→直前4番人気以下は単回収118。より広く『朝一top3→直前ana_pop+落ち』を拾う。
    for u, lr in r_last.items():
        er = r_first.get(u)
        if er is None or lr < ana_pop:
            continue
        if er <= 3 and (lr - er) >= 3:
            _sev = 'good' if er == 1 else 'info'
            insights.append({'umaban': u, 'kind': 'hidden_ana', 'severity': _sev,
                             'reason': f'🔥朝一{er}番人気→直前{lr}番人気に降下＝『隠れた本命』候補'
                                       f'（朝一に売れていた穴・書籍の激走パターン）'})

    # ③ 危険な直前人気: 朝一で不人気だったのに直前で上位に売れた(一般票の過剰人気)
    for u, lr in r_last.items():
        er = r_first.get(u)
        if er is None or lr > 3:
            continue
        if er >= 6 and (er - lr) >= 4:
            insights.append({'umaban': u, 'kind': 'danger_late', 'severity': 'warn',
                             'reason': f'⚠{u}番は直前だけ売れた（朝一{er}番人気→直前{lr}番人気）＝'
                                       f'一般票による過剰人気の可能性・軸は割引'})

    # severity順(warn→good→info)で並べる
    _ord = {'warn': 0, 'good': 1, 'info': 2}
    insights.sort(key=lambda x: _ord.get(x['severity'], 9))
    return {'ok': True, 'first_ts': str(first), 'last_ts': str(last),
            'n_snap': len(ts_list), 'insights': insights,
            'note': '朝一↔直前の人気順位変化ベース。書籍(蘆口真史)準拠・このアプリでは未検証'
                    '(凍結DBにオッズ時系列が無いため)。参考として表示。'}
