# -*- coding: utf-8 -*-
"""
3連複おすすめ統合エンジン。既存の5機能(推奨買い目/スペシャル/generate_sanrenpuku_10/
from_odds/sniper)を1つに統合する中核ロジック。

バックテスト知見(scripts/trio_pattern_backtest.py)を反映:
- 勝ち3連複の46%は ①人気2-穴1（最頻・ROI最高・配当中央値71倍＝狙い目価格帯10-100倍）
- ②人気1-穴2 は15%だが中央値341倍の高配当（低的中・宝くじ）
- 単純箱買いはROI約70%（マイナス）→ 強適スコア+展開+オッズ狙い目で「絞る」ことが肝
- 穴は絞るほど良い（穴band 5-10/6-12 が広band より上）

人気=Popularity<=pop_th、穴=ana_lo<=Popularity<=ana_hi。
"""
from itertools import combinations

# パターン別の狙い目オッズ価格帯（倍）
_TARGET_BAND = {'①': (10.0, 100.0), '②': (80.0, 1000.0), 'おまかせ': (10.0, 300.0)}


def _classify(trio, pop_set, ana_set):
    """trio(umaban tuple) の人気構成 → (人気数, 穴数)。"""
    n_pop = sum(1 for u in trio if u in pop_set)
    n_ana = sum(1 for u in trio if u in ana_set)
    return n_pop, n_ana


def _match_pattern(n_pop, n_ana, pattern):
    if pattern == '①':       # 人気2-穴1
        return n_pop == 2 and n_ana >= 1
    if pattern == '②':       # 人気1-穴2
        return n_pop == 1 and n_ana >= 2
    return (n_pop + n_ana) >= 2   # おまかせ: 鉄板/全穴に寄りすぎない程度


def recommend_trio(horses, odds_map=None, axis_umaban=None, axis_mode='auto',
                   pattern='①', n_points=10, pop_th=5, ana_lo=6, ana_hi=12,
                   pool_cap=12):
    """
    horses: [{'umaban':int,'name':str,'score':float,'pop':int|None,'alert':str}]
    odds_map: {frozenset({u1,u2,u3}): float} ライブ3連複オッズ（任意）
    axis_umaban: [int,...]（1軸/2軸時の軸馬番）
    axis_mode: '2軸'|'1軸'|'auto'(軸なし=スコア自動)
    pattern: '①'|'②'|'おまかせ'
    戻り値: {'bets':[{...}], 'meta':{...}, 'warning':str|None}
    """
    horses = [h for h in horses if h.get('umaban')]
    by = {h['umaban']: h for h in horses}
    axis_umaban = [u for u in (axis_umaban or []) if u in by]
    lo, hi = _TARGET_BAND.get(pattern, (10.0, 300.0))

    pop_set = {h['umaban'] for h in horses if h.get('pop') and h['pop'] <= pop_th}
    ana_set = {h['umaban'] for h in horses if h.get('pop') and ana_lo <= h['pop'] <= ana_hi}
    if len(pop_set) < 1 or len(ana_set) < 1:
        return {'bets': [], 'meta': {}, 'warning': '人気/穴の頭数が不足（人気・オッズ未取得の可能性）'}

    # ── 候補トリオ生成 ──
    cand = set()
    others = [h['umaban'] for h in horses if h['umaban'] not in axis_umaban]
    if axis_mode == '2軸' and len(axis_umaban) >= 2:
        a, b = axis_umaban[0], axis_umaban[1]
        for x in others:
            cand.add(frozenset((a, b, x)))
    elif axis_mode == '1軸' and len(axis_umaban) >= 1:
        a = axis_umaban[0]
        for x, y in combinations(others, 2):
            cand.add(frozenset((a, x, y)))
    else:
        # auto: 人気pool∪穴pool をスコア上位 pool_cap 頭に絞って総当り
        pool = sorted(pop_set | ana_set, key=lambda u: -by[u].get('score', 0))[:pool_cap]
        for c in combinations(pool, 3):
            cand.add(frozenset(c))

    # ── パターン適合でフィルタ＋スコアリング ──
    scored = []
    for fs in cand:
        trio = tuple(sorted(fs))
        if len(trio) != 3:
            continue
        n_pop, n_ana = _classify(trio, pop_set, ana_set)
        if not _match_pattern(n_pop, n_ana, pattern):
            continue
        base = sum(by[u].get('score', 0) for u in trio)
        # 展開/穴ボーナス: 穴馬に🔥🎯🚀(妙味・上がり)があれば加点
        bonus = 0.0
        for u in trio:
            al = str(by[u].get('alert', '') or '')
            if u in ana_set and any(s in al for s in ('🔥', '🎯', '🚀')):
                bonus += 8.0
        odds = None
        in_band = False
        if odds_map:
            odds = odds_map.get(fs)
            if odds is not None:
                if lo <= odds <= hi:
                    in_band = True
                    bonus += 15.0          # 狙い目価格帯はボーナス
                elif odds < lo:
                    bonus -= 10.0          # 堅すぎ（配当妙味なし）
                elif odds > hi:
                    bonus -= 6.0           # 当たりにくすぎ
        scored.append({'combo': trio,
                       'names': tuple(by[u].get('name', '') for u in trio),
                       'odds': odds, 'in_band': in_band,
                       'score': round(base + bonus, 1),
                       'pop_ana': (n_pop, n_ana)})
    if not scored:
        return {'bets': [], 'meta': {'pop': len(pop_set), 'ana': len(ana_set)},
                'warning': f'パターン{pattern}に合う組合せがありません（軸/人気/穴の設定を調整してください）'}

    scored.sort(key=lambda x: -x['score'])
    bets = scored[:max(1, int(n_points))]
    syn = None
    if all(b['odds'] for b in bets):
        # 合成オッズ（均等買い時の期待倍率の目安）= n / Σ(1/odds)
        inv = sum(1.0 / b['odds'] for b in bets)
        syn = round(len(bets) / inv, 1) if inv else None
    return {'bets': bets,
            'meta': {'pattern': pattern, 'axis_mode': axis_mode, 'n_points': len(bets),
                     'target_band': (lo, hi), 'synthetic_odds': syn,
                     'pop_pool': sorted(pop_set), 'ana_pool': sorted(ana_set)},
            'warning': None}


def build_odds_map(odds_list):
    """scraper.fetch_sanrenpuku_odds の出力 → {frozenset(3 umaban): odds}。"""
    m = {}
    for item in (odds_list or []):
        try:
            hs = [int(x) for x in item['Horses']]
            if len(hs) == 3 and item.get('Odds'):
                m[frozenset(hs)] = float(item['Odds'])
        except Exception:
            continue
    return m
