# -*- coding: utf-8 -*-
"""『前走内容』パネル — core/prev_race.py

穴馬候補を人間が最終比較するための **表示専用** モジュール。
AIスコア(vh2_score/妙味/ランキング/材料数)には一切影響させない。加点も減点もしない。

データ源は netkeiba のみ(JRA-VAN不使用):
  1. PastRuns(出馬表 shutuba_past.html 由来・core/scraper.py) … 追加取得ゼロで取れる分
     グレード/クラス・着順・頭数・馬番・前走人気・1着馬名・1着馬との着差・
     上がり3F・通過順・距離・馬場・騎手・斤量・前走race_id
  2. 前走race_id → core.scraper.fetch_comprehensive_result() … 3着馬との差の算出用
     ※race_idは1.のHTMLに元から含まれるため、race_idを得るための追加取得は不要。
       3着馬との差を出す時だけ、前走レース1本につき1フェッチ(race_id単位で共有)。

⭐バッジ『強敵と接戦』の条件(今回の検証で確認済みのものをそのまま実装):
    前走が重賞またはL(G1/G2/G3/重賞/L) かつ 前走3着馬との差 ≤ 0.3秒
  検証: Rank(ability_score)分位で統制しても3着内率が+5.5〜9pp(4期間とも一貫)。
  ただし複勝ROIは安定してプラスにならず、vh2母集団(7番人気以下)でvh2_scoreを
  統制すると追加リフトはほぼ0 ＝ **スコアには組み込まない**。これは
  「検証済み条件に該当した」という事実の表示であって、AI評価でも妙味でもない。

  3着馬との差が取得できない場合は『条件不成立』とは扱わず、バッジを出さない
  (推測で補完しない)。
"""
import re

# 重賞/L 判定に使うレース名末尾トークン。netkeibaはローマ数字表記(GI/GII/GIII)。
# ⚠ 'GI' は 'GII'/'GIII' の部分文字列なので、部分一致(`'GI' in name`)で判定してはいけない。
#   トークン完全一致で判定すること。
_GRADE_TOKENS = {
    'GIII': 'G3', 'GⅢ': 'G3', 'G3': 'G3', '(G3)': 'G3',
    'GII': 'G2', 'GⅡ': 'G2', 'G2': 'G2', '(G2)': 'G2',
    'GI': 'G1', 'GⅠ': 'G1', 'G1': 'G1', '(G1)': 'G1',
    'L': 'L', '(L)': 'L', 'Ｌ': 'L',
    'OP': 'OP', 'オープン': 'OP',
}
# 重賞/L = 検証時の grade コード {A,B,C,D,L} 相当。OP特別・障害は含めない。
_STAKES = {'G1', 'G2', 'G3', '重賞', 'L'}

_CLASS_PATTERNS = [
    ('3勝', ('3勝', '１６００万', '1600万')),
    ('2勝', ('2勝', '１０００万', '1000万')),
    ('1勝', ('1勝', '５００万', '500万')),
    ('未勝利', ('未勝利',)),
    ('新馬', ('新馬',)),
]


def classify_grade(race_name):
    """前走レース名 → (表示ラベル, 重賞/Lか)。

    netkeibaのData02は '京王杯2歳\\nGII' / 'アイビーS\\nL' / 'こうやまき\\n1勝' の形。
    グレードはレース名の末尾トークンに付く。障害(J・GI等)は重賞扱いしない。
    """
    s = re.sub(r'\s+', ' ', str(race_name or '')).strip()
    if not s:
        return '', False
    is_jump = ('J・' in s) or ('J.' in s) or ('障害' in s)
    toks = [t for t in s.split(' ') if t]
    # 末尾から順にグレードトークンを探す(レース名自体に数字が入るため末尾優先)
    for tok in reversed(toks):
        g = _GRADE_TOKENS.get(tok)
        if g:
            if is_jump:
                return f'J・{g}', False       # 障害は検証対象外＝重賞扱いしない
            return g, g in _STAKES
    for label, keys in _CLASS_PATTERNS:
        if any(k in s for k in keys):
            return label, False
    if '重賞' in s:
        return '重賞', True
    return (toks[-1] if toks else ''), False


def _num(v):
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def extract(past_runs):
    """PastRuns(list) → 前走1走分の表示用dict。追加フェッチは行わない。

    戻り: None(前走なし) または
      {'race_id','race_name','grade','is_stakes','rank','field_size','umaban',
       'popularity','winner_name','margin_win','agari','passing','distance',
       'surface','baba','jockey','weight','date','margin_3rd'(=None)}
    """
    if not past_runs:
        return None
    p = past_runs[0] or {}
    grade, is_stakes = classify_grade(p.get('RaceName'))
    rank = p.get('Rank')
    rank = int(rank) if isinstance(rank, (int, float)) and 0 < rank < 99 else None
    mw = _num(p.get('Margin'))
    if mw is not None and mw >= 9.9:      # 9.9 = scraper側の欠損マーカー
        mw = None
    pop = p.get('Popularity')
    pop = int(pop) if isinstance(pop, (int, float)) and 0 < pop < 99 else None
    ag = _num(p.get('Agari'))
    return {
        'race_id': p.get('RaceId'),
        'race_name': str(p.get('RaceName') or '').replace('\n', ' ').strip(),
        'grade': grade,
        'is_stakes': is_stakes,
        'rank': rank,
        'field_size': p.get('FieldSize'),
        'umaban': p.get('PrevUmaban'),
        'popularity': pop,
        'winner_name': str(p.get('WinnerName') or '').strip(),
        'margin_win': mw,
        'agari': ag if (ag and ag > 0) else None,
        'passing': str(p.get('Passing') or '').strip(),
        'distance': p.get('Distance'),
        'surface': str(p.get('Surface') or '').strip(),
        'baba': str(p.get('Baba') or '').strip(),
        'jockey': str(p.get('PrevJockey') or '').strip(),
        'weight': _num(p.get('Weight')),
        'date': str(p.get('Date') or '').strip(),
        'margin_3rd': None,       # attach_third_margin() で埋める
        'third_name': None,
        'race_name_full': '',     # 同上(前走結果ページの正式名称・切り詰めなし)
    }


def collect_race_ids(prevs):
    """前走dictのlist → 取得すべき前走race_idのset(重複排除)。
    同じ前走レースを走った馬が複数いても1回しか取得しないために使う。"""
    out = set()
    for pv in prevs:
        if pv and pv.get('race_id'):
            out.add(str(pv['race_id']))
    return out


def fetch_results(race_ids, cache=None, fetcher=None):
    """前走レース結果をrace_id単位でまとめて取得する(既取得分はcacheから再利用)。

    race_ids: iterable of race_id
    cache: {race_id: {'horses': {...}}} 呼び元がsession_state等で保持する辞書。
           破壊的に更新して返す。取得失敗は None を入れて再取得を防ぐ。
    fetcher: テスト差し替え用。既定は core.scraper.fetch_comprehensive_result。
    戻り: (cache, 新規に取得した件数)
    """
    if cache is None:
        cache = {}
    if fetcher is None:
        from core.scraper import fetch_comprehensive_result as fetcher
    n_new = 0
    for rid in race_ids:
        rid = str(rid)
        if rid in cache:          # None(失敗)も含めスキップ＝重複フェッチしない
            continue
        try:
            res = fetcher(rid)
        except Exception:
            res = None
        cache[rid] = res if (res and res.get('horses')) else None
        n_new += 1
    return cache, n_new


def attach_third_margin(pv, cache):
    """前走dictに『3着馬との差』を埋める(取得できない場合はNoneのまま)。

    自馬の特定は前走馬番(PrevUmaban)を優先し、無ければ馬名で照合する。
    3着馬が特定できない(出走取消・同着等でタイム欠損)場合もNoneのままにする。
    """
    if not pv or not pv.get('race_id'):
        return pv
    res = (cache or {}).get(str(pv['race_id']))
    if not res:
        return pv
    # レース正式名称(切り詰められていない方)を拾う。追加フェッチは発生しない。
    _rn = ((res.get('race_info') or {}).get('race_name') or '').strip()
    if _rn:
        pv['race_name_full'] = _rn
    horses = res.get('horses') or {}
    if not horses:
        return pv

    third = None
    for h in horses.values():
        if h.get('Rank') == 3 and _num(h.get('Time')):
            third = h
            break
    if not third:
        return pv

    me = None
    ub = pv.get('umaban')
    if ub is not None:
        try:
            me = horses.get(int(ub))
        except (TypeError, ValueError):
            me = None
    if me is None and pv.get('_name'):
        tgt = re.sub(r'\s+', '', str(pv['_name']))
        for h in horses.values():
            if re.sub(r'\s+', '', str(h.get('Name') or '')) == tgt:
                me = h
                break
    if not me or not _num(me.get('Time')):
        return pv

    pv['margin_3rd'] = round(float(me['Time']) - float(third['Time']), 1)
    tname = str(third.get('Name') or '')
    # 自馬自身が3着だった場合は『3着=自分』という自己言及表示になるため名前は付けない
    pv['third_name'] = '' if me is third else tname
    return pv


def badge(pv):
    """⭐バッジ。検証済み条件『前走が重賞/L かつ 3着馬との差≤0.3秒』に該当した時だけ返す。

    3着馬との差が取れていない(None)場合は条件不成立ではなく **判定不能** として
    バッジを出さない。推測で補完しない。

    文言のみ前走着順で出し分ける(**判定条件は同一**):
      前走1〜3着 → '⭐ 重賞で好走'（勝った馬に『接戦』と書く不自然さを避ける）
      前走4着以下 → '⭐ 重賞で3着馬と接戦'
    戻り: バッジ文字列 または ''
    """
    if not pv or not pv.get('is_stakes'):
        return ''
    m3 = pv.get('margin_3rd')
    if m3 is None or m3 > 0.3:
        return ''
    rank = pv.get('rank')
    if rank is not None and rank <= 3:
        return '⭐ 重賞で好走'
    return '⭐ 重賞で3着馬と接戦'


def clean_race_name(pv):
    """表示用のレース名。グレード表記(GIII等)は分類側で出すので名前からは外す。
    前走結果ページから取れたフル名称があればそれを優先する
    (出馬表の過去走セルはセル幅で名前が切り詰められる。例『シンザン記』)。"""
    if not pv:
        return ''
    full = str(pv.get('race_name_full') or '').strip()
    s = full or re.sub(r'\s+', ' ', str(pv.get('race_name') or '')).strip()
    if not s:
        return ''
    toks = [t for t in s.split(' ') if t]
    # 末尾のグレードトークン(GIII/L/1勝 等)を落とす
    drop = set(_GRADE_TOKENS) | {'1勝', '2勝', '3勝', '500万', '1000万', '1600万', '重賞'}
    while toks and toks[-1].strip('（）()') in drop:
        toks.pop()
    return ' '.join(toks).strip()


def summary_line(pv):
    """一覧の1行目。例『G3・8着 / 16頭』。"""
    if not pv:
        return ''
    parts = []
    if pv.get('grade'):
        parts.append(pv['grade'])
    if pv.get('rank'):
        fs = pv.get('field_size')
        parts.append(f"{pv['rank']}着" + (f" / {fs}頭" if fs else ''))
    return '・'.join(parts)


def margin_line(pv):
    """一覧の2行目。例『3着馬との差 +0.7秒』。
    3着差が未取得なら1着馬との差にフォールバックし、何の差かを明示する。"""
    if not pv:
        return ''
    m3 = pv.get('margin_3rd')
    if m3 is not None:
        if pv.get('rank') == 3:
            return '3着馬との差 ±0.0秒（自身が3着）'
        return f"3着馬との差 {m3:+.1f}秒"
    mw = pv.get('margin_win')
    if mw is not None:
        lbl = '2着馬との差' if pv.get('rank') == 1 else '1着馬との差'
        return f"{lbl} {mw:+.1f}秒"
    return ''


def detail_header(pv):
    """詳細の見出し。例『G3「シンザン記念」』。
    分類名がレース名に含まれる場合(例 未勝利×『2歳未勝利』)は重複するので名前だけ出す。"""
    if not pv:
        return ''
    nm = clean_race_name(pv)
    g = pv.get('grade') or ''
    if not nm:
        return g
    if not g or g in nm:
        return nm
    return f'{g}「{nm}」'


def detail_condition(pv):
    """詳細の条件行。例『2026.01.12　芝1600m・良』。"""
    if not pv:
        return ''
    cond = (pv.get('surface') or '') + (f"{pv['distance']}m" if pv.get('distance') else '')
    if pv.get('baba'):
        cond = (cond + '・' + pv['baba']) if cond else pv['baba']
    d = pv.get('date') or ''
    return '　'.join(x for x in (d, cond) if x)


def detail_rows(pv):
    """詳細の事実行 (ラベル, 値)。取得できなかった項目は行ごと出さない。"""
    if not pv:
        return []
    rows = []
    if pv.get('rank'):
        fs = pv.get('field_size')
        v = f"{pv['rank']}着" + (f" / {fs}頭" if fs else '')
        if pv.get('popularity'):
            v += f"（{pv['popularity']}人気）"
        rows.append(('着順', v))
    if pv.get('margin_3rd') is not None:
        if pv.get('rank') == 3:
            v = '±0.0秒（自身が3着）'
        else:
            v = f"{pv['margin_3rd']:+.1f}秒"
            if pv.get('third_name'):
                v += f"（3着＝{pv['third_name']}）"
        rows.append(('3着馬との差', v))
    else:
        rows.append(('3着馬との差', '取得できず（前走レース結果を参照できません）'))
    if pv.get('winner_name'):
        lbl = '2着馬' if (pv.get('rank') == 1) else '1着馬'
        v = pv['winner_name']
        if pv.get('margin_win') is not None:
            v += f"（{pv['margin_win']:+.1f}秒）"
        rows.append((lbl, v))
    if pv.get('agari'):
        rows.append(('上がり3F', f"{pv['agari']:.1f}秒"))
    if pv.get('passing'):
        rows.append(('通過順', pv['passing']))
    if pv.get('jockey') and pv['jockey'] != '-':
        v = pv['jockey']
        if pv.get('weight'):
            v += f"　{pv['weight']:.1f}kg"
        rows.append(('騎手', v))
    return rows
