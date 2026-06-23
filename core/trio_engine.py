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
# 本線=人気上位2頭以上を必ず含む形＝鉄板(37%)+①(46%)を同時カバー=83%(検証 trio_selector_backtest.py)。
# 帯は鉄板(中央値~15倍)〜①(~71倍)を覆いつつ、安すぎ(<10)は軽く減点して①寄りの配当を取りにいく。
# ②妙味=荒れ(人気上位≤1)×穴2頭の高配当狙い。穴は盲目でなく検証済み妙味シグナルで選別。
# 価格帯は実データで是正(verified_trio_payout_band / scripts/trio_payout_by_type.py 2016-26):
#   ②型決着の配当は中央値242倍・四分位[120〜554倍]、約7割が70〜700倍に集中。
#   旧②妙味(30,2000)は広すぎ(30-70倍=本線価格まで拾い、>700倍=宝くじ)→(70,800)に絞る。
_TARGET_BAND = {'本線': (10.0, 150.0), '②妙味': (70.0, 800.0),
                '①': (10.0, 100.0), '②': (70.0, 700.0), 'おまかせ': (10.0, 300.0)}


def _classify(trio, pop_set, ana_set):
    """trio(umaban tuple) の人気構成 → (人気数, 穴数)。"""
    n_pop = sum(1 for u in trio if u in pop_set)
    n_ana = sum(1 for u in trio if u in ana_set)
    return n_pop, n_ana


def _match_pattern(n_pop, n_ana, pattern):
    if pattern == '本線':     # 人気上位2頭以上＝鉄板(人気3)と①(人気2穴1)を両取り(検証83%)
        return n_pop >= 2
    if pattern == '②妙味':    # 本線の補集合=荒れ(人気上位≤1)×穴2頭以上。穴は妙味シグナルで選別
        return n_pop <= 1 and n_ana >= 2
    if pattern == '①':       # 人気2-穴1
        return n_pop == 2 and n_ana >= 1
    if pattern == '②':       # 人気1-穴2
        return n_pop == 1 and n_ana >= 2
    return (n_pop + n_ana) >= 2   # おまかせ: 鉄板/全穴に寄りすぎない程度


def deploy_bonus_from_ctx(pace_ctx):
    """展開コンテキストから各馬の展開ボーナス {umaban: pts} を作る（互換のため残置）。

    ⚠️ 旧実装は『好位妙味ゾーン+2.4pp』に+12点加点していたが、大標本の再検証
    (scripts/tenkai_alert_backtest.py・2024-25/360R)で否定された:
      - 展開恩恵スコアは全帯で複勝残差≈0〜負(中帯 n=1310 で-0.44pp/z=-0.39)=人気に織込み済み
      - +2.4pp は小標本(n=466/z=1.25)のノイズだった
      - 検証済み末脚エッジ(人気薄×習性末脚上位)に展開恩恵を重ねると逆に悪化
    よって非エッジを3連複エンジンへ配線しないため**加点ゼロ**に変更(2026-06-18)。
    展開恩恵を妙味として使わない。末脚は別途 alert/value_scanner 側で扱う。"""
    return {}


def allocate_budget(bets, budget, mode='均等買い', unit=100):
    """買い目に予算を配分し、各点の購入額・的中時払戻・トリガミ可否を付与する。
    mode='均等買い'(等額) / '払戻均等'(オッズ逆比＝どれが当たっても回収額が近い)。"""
    n = len(bets)
    if not budget or n == 0:
        for b in bets:
            b['stake'] = 0
            b['payout_if_hit'] = round(b['odds'] * 0) if b.get('odds') else None
            b['toriga'] = False
        return {'total': 0, 'mode': mode}
    budget = int(budget)
    if mode == '払戻均等' and all(b.get('odds') for b in bets):
        w = [1.0 / b['odds'] for b in bets]
        sw = sum(w)
        stakes = [max(unit, int(round(budget * wi / sw / unit)) * unit) for wi in w]
    else:
        per = max(unit, budget // n // unit * unit)
        stakes = [per] * n
    total = sum(stakes)
    for b, s in zip(bets, stakes):
        b['stake'] = s
        b['payout_if_hit'] = int(round(b['odds'] * s)) if b.get('odds') else None
        b['toriga'] = (b['payout_if_hit'] is not None and b['payout_if_hit'] < total)
    return {'total': total, 'mode': mode}


def recommend_trio(horses, odds_map=None, axis_umaban=None, axis_mode='auto',
                   pattern='①', n_points=10, pop_th=5, ana_lo=6, ana_hi=12,
                   pool_cap=12, deploy_map=None):
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

    # 軸を明示指定(1軸/2軸)した場合は「軸流し」の意思を最優先する。
    # この時パターン(本線/②妙味)はハード除外でなく『堅め/荒れ』のソフト加点に格下げし、
    # 3頭目を全頭に流す。さもないと軸に穴馬を据えた瞬間、人気構成フィルタが
    # 狙った相手(=高配当の穴)を全部間引いてしまう(2026-06-18 修正)。
    _axis_active = ((axis_mode == '2軸' and len(axis_umaban) >= 2) or
                    (axis_mode == '1軸' and len(axis_umaban) >= 1))

    # 人気/穴の分類は auto(パターンハード適用)モードでのみ必須。軸流し時は人気未取得でも流す。
    if not _axis_active and (len(pop_set) < 1 or len(ana_set) < 1):
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
        if not _axis_active and not _match_pattern(n_pop, n_ana, pattern):
            continue
        base = sum(by[u].get('score', 0) for u in trio)
        # 展開/穴ボーナス: 穴馬に🔥🎯🚀(妙味・上がり)＋展開マップの好位妙味で加点
        bonus = 0.0
        # 軸流し時はパターンを除外でなくソフト加点に: 本線=堅め(人気の3頭目)寄り / ②妙味=荒れ(穴の3頭目)寄り
        if _axis_active:
            if pattern == '本線':
                bonus += 6.0 * n_pop
            elif pattern == '②妙味':
                bonus += 8.0 * n_ana
        # ②妙味は穴の選別を検証済みエッジに寄せる=妙味シグナル穴を強く加点(本命より穴で勝負)
        _val_boost = 18.0 if pattern == '②妙味' else 8.0
        _sig_ana = 0
        for u in trio:
            al = str(by[u].get('alert', '') or '')
            if u in ana_set and any(s in al for s in ('🔥', '🎯', '🚀', '妙味', '乖離')):
                bonus += _val_boost
                _sig_ana += 1
            if deploy_map:
                bonus += float(deploy_map.get(u, 0.0))   # 展開マップ(好位妙味)連携
        # ②妙味: 妙味シグナルの穴を含まないトリオは後退(盲目的な人気1-穴2を買わない=検証で最悪だった形)
        if pattern == '②妙味' and _sig_ana == 0:
            bonus -= 12.0
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


def build_formation(col1, col2, col3):
    """3連複フォーメーション。1列目(軸)/2列目(対抗)/3列目(押さえ)の馬番リストから、
    各列1頭ずつ・3頭が相異なる組合せを生成(3連複=順不同なので重複排除)。
    戻り値: ソート済みtuple(3 umaban)のリスト。例『2-4-7型』=len(col1)=2,col2=4,col3=7。"""
    c1 = [int(x) for x in (col1 or [])]
    c2 = [int(x) for x in (col2 or [])]
    c3 = [int(x) for x in (col3 or [])]
    seen = set()
    out = []
    for a in c1:
        for b in c2:
            for c in c3:
                if len({a, b, c}) != 3:
                    continue
                key = frozenset((a, b, c))
                if key in seen:
                    continue
                seen.add(key)
                out.append(tuple(sorted((a, b, c))))
    out.sort()
    return out


def build_trifecta_formation(col1, col2, col3):
    """3連単フォーメーション。1列目(1着)/2列目(2着)/3列目(3着)の馬番リストから、
    各列1頭ずつ・3頭が相異なる『順序付き』組合せを生成(3連単=着順あり)。
    戻り値: 順序付きtuple(1着,2着,3着)のリスト。3連複と違い順序ごとに別の買い目。"""
    c1 = [int(x) for x in (col1 or [])]
    c2 = [int(x) for x in (col2 or [])]
    c3 = [int(x) for x in (col3 or [])]
    seen = set()
    out = []
    for a in c1:
        for b in c2:
            for c in c3:
                if len({a, b, c}) != 3:
                    continue
                key = (a, b, c)
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
    return out


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


def build_trifecta_odds_map(odds_list):
    """scraper.fetch_sanrentan_odds の出力 → {(1着,2着,3着): odds}（着順あり=順序付きtuple）。"""
    m = {}
    for item in (odds_list or []):
        try:
            hs = [int(x) for x in item['Horses']]
            if len(hs) == 3 and item.get('Odds'):
                m[tuple(hs)] = float(item['Odds'])
        except Exception:
            continue
    return m


# ──────────────────────────────────────────────
# 馬連 / 馬単 おすすめ（3連複の代替・高配当検知）
#   人気馬が3頭目に絡むと3連複は配当が伸びない。そんな時は2頭勝負の
#   馬連/馬単のほうが高配当になりやすい。それを検知して提案する。
# ──────────────────────────────────────────────
def _pop_label(pop):
    """人気 → 簡易区分。人=1〜5 / 中=6〜9 / 穴=10番人気〜。不明は'?'。"""
    if pop is None:
        return '?'
    if pop <= 5:
        return '人'
    if pop <= 9:
        return '中'
    return '穴'


def recommend_quinella_exacta(horses, q_odds=None, e_odds=None, axis_umaban=None,
                              n_opp=6, band_q=(10.0, 120.0), band_e=(20.0, 250.0),
                              both_dir=False, veto_axis=None):
    """
    軸1頭 × 相手(スコア順 n_opp頭) の馬連/馬単おすすめ買い目。
    horses : [{'umaban','name','score','pop','alert'}]（recommend_trio と同形）
    q_odds : 馬連 {tuple(sorted(a,b)): odds(float)}
    e_odds : 馬単 {tuple(a,b): odds(float)}  a=1着,b=2着
    axis_umaban : 軸馬番。None ならスコア最上位を軸に。
    band_q/band_e : 狙い目価格帯（この帯の買い目に🎯）。
    both_dir : True なら馬単の裏(相手→軸)も提案に含める。
    戻り : {'axis':u, 'opp':[u..], 'quinella':[row..], 'exacta':[row..]}
        row = {'combo','names','pop_ana','odds','in_band','score'}
    """
    hs = [h for h in horses if h.get('umaban')]
    if not hs:
        return {'axis': None, 'opp': [], 'quinella': [], 'exacta': []}
    by_um = {h['umaban']: h for h in hs}
    ranked = sorted(hs, key=lambda h: h.get('score', 0) or 0, reverse=True)
    # 自動軸は危険人気馬(veto_axis)を避けて次点へ降格(verified: 危険人気の軸固定は不利)
    _veto = {u for u in (veto_axis or [])}
    if axis_umaban in by_um:
        axis = axis_umaban
    else:
        axis = next((h['umaban'] for h in ranked if h['umaban'] not in _veto),
                    ranked[0]['umaban'])
    opp = [h['umaban'] for h in ranked if h['umaban'] != axis][:n_opp]
    q_odds = q_odds or {}
    e_odds = e_odds or {}

    def _name(u):
        return (by_um.get(u) or {}).get('name', '')

    def _pa(combo):
        return ''.join(_pop_label((by_um.get(u) or {}).get('pop')) for u in combo)

    def _sc(a, b):
        return round(((by_um.get(a) or {}).get('score', 0) +
                      (by_um.get(b) or {}).get('score', 0)) / 2, 1)

    q_rows = []
    for o in opp:
        pair = tuple(sorted((axis, o)))
        od = q_odds.get(pair)
        q_rows.append({'combo': pair, 'names': [_name(pair[0]), _name(pair[1])],
                       'pop_ana': _pa(pair), 'odds': od,
                       'in_band': bool(od and band_q[0] <= od <= band_q[1]),
                       'score': _sc(*pair)})
    q_rows.sort(key=lambda r: (-int(r['in_band']), -(r['odds'] or 0)))

    e_rows = []
    dirs = [(axis, o) for o in opp]
    if both_dir:
        dirs += [(o, axis) for o in opp]
    for a, b in dirs:
        od = e_odds.get((a, b))
        e_rows.append({'combo': (a, b), 'names': [_name(a), _name(b)],
                       'pop_ana': _pa((a, b)), 'odds': od,
                       'in_band': bool(od and band_e[0] <= od <= band_e[1]),
                       'score': _sc(a, b)})
    e_rows.sort(key=lambda r: (-int(r['in_band']), -(r['odds'] or 0)))
    return {'axis': axis, 'opp': opp, 'quinella': q_rows, 'exacta': e_rows}


def trio_vs_pair(trio_combos, t_odds, q_odds, e_odds, pop_by_um=None):
    """
    各3連複買い目について、構成3頭のうち『人気薄2頭』の馬連/馬単と配当を比較。
    人気の3頭目が配当を押し下げ、2頭流しのほうが高配当になるケースを検知する。
    trio_combos : [tuple(3 umaban)]
    t_odds : {frozenset(3)|tuple(3): odds} 3連複
    q_odds : {tuple(sorted 2): odds} 馬連
    e_odds : {tuple(2): odds} 馬単(a→b)
    pop_by_um : {umaban: 人気}。人気薄2頭の選定に使用。None なら3ペア中ベストを採用。
    戻り : [{'trio','trio_odds','pair','q_odds','e_best','better','ratio'}]（高配当順）
        better = '馬連'|'馬単'|None（None=3連複が同等以上）
    """
    out = []
    seen = set()
    for combo in trio_combos:
        try:
            c = tuple(sorted(int(x) for x in combo))
        except Exception:
            continue
        if len(c) != 3 or c in seen:
            continue
        seen.add(c)
        to = t_odds.get(frozenset(c)) or t_odds.get(c)
        if not to:
            continue
        if pop_by_um:
            ranked = sorted(c, key=lambda u: (pop_by_um.get(u) or 999), reverse=True)
            cand_pairs = [tuple(sorted(ranked[:2]))]
        else:
            cand_pairs = [tuple(sorted(p)) for p in
                          ((c[0], c[1]), (c[0], c[2]), (c[1], c[2]))]
        best = None
        for pr in cand_pairs:
            qo = q_odds.get(pr) or 0
            eo = max((e_odds.get((pr[0], pr[1])) or 0),
                     (e_odds.get((pr[1], pr[0])) or 0)) or 0
            val = max(qo, eo)
            if best is None or val > best['_val']:
                better = None
                if qo >= to and qo >= eo:
                    better = '馬連'
                elif eo >= to:
                    better = '馬単'
                best = {'pair': pr, 'q_odds': qo or None, 'e_best': eo or None,
                        'better': better, '_val': val}
        if best:
            out.append({'trio': c, 'trio_odds': to, 'pair': best['pair'],
                        'q_odds': best['q_odds'], 'e_best': best['e_best'],
                        'better': best['better'],
                        'ratio': round(best['_val'] / to, 2) if to else None})
    out.sort(key=lambda r: -(r['ratio'] or 0))
    return out
