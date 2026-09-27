# -*- coding: utf-8 -*-
"""🧪 競馬俗説ハンター — 予想エンジンとは切り離した俗説コレクション。

各馬が「ネット上で語られる俗説」に何個当てはまるかを数えるだけ。
点数・買い目・LTR/合議/穴馬スコアには一切足さない。

sign:
  +1 = 俗説としての買い材料
  -1 = 俗説としての消し・危険
表示の点数は今は全部 ±1。weight/confidence は将来の重み付け用で、今は使わない。
総合 = プラス材料の個数 − マイナス材料の個数。

verdict:
  effective  = このアプリが検証して実戦で使っている材料
  rejected   = バックテストで「買い材料としては効かない／売れすぎ」と出た俗説
  unverified = 俗説として存在するが、ここではまだ集合体の検証をしていない
"""
import re
from datetime import datetime

VERDICT_EFFECTIVE = 'effective'
VERDICT_REJECTED = 'rejected'
VERDICT_UNVERIFIED = 'unverified'
SKIP = '__skip__'  # データが無くて「該当しない」とは言えない
SIGN_POS = 1   # 俗説としての「買い材料」
SIGN_NEG = -1  # 俗説としての「消し・危険」
# 表示の点数は今は全部 ±1。weight/confidence は将来の重み付け用で、今は使わない。
CONF_NORMAL = 'normal'
SIGN_LABEL = {SIGN_POS: '買い材料', SIGN_NEG: '消し・危険'}
SIGN_MARK = {SIGN_POS: '＋', SIGN_NEG: '−'}

# 俗説でよく言われる「内枠が有利」な芝の場。統計の正本ではない。
_INNER_TURF_JYO = {'03', '06', '10', '02'}  # 福島・中山・小倉・函館
_EAST_JYO = {'01', '02', '03', '04', '05', '06'}
_WEST_JYO = {'07', '08', '09', '10'}
_LOCAL_JYO = {'01', '02', '03', '04', '07', '10'}  # 札幌函館福島新潟中京小倉
_CLASS_RANK = [
    ('G1', 8), ('GI', 8), ('GⅠ', 8),
    ('G2', 7), ('GII', 7), ('GⅡ', 7),
    ('G3', 6), ('GIII', 6), ('GⅢ', 6), ('重賞', 6),
    ('OP', 5), ('オープン', 5), ('(L)', 5),
    ('3勝', 4), ('1600万', 4), ('１６００万', 4),
    ('2勝', 3), ('1000万', 3), ('１０００万', 3),
    ('1勝', 2), ('500万', 2), ('５００万', 2),
    ('未勝利', 1), ('新馬', 0),
]

VERDICT_LABEL = {
    VERDICT_EFFECTIVE: '検証済み・実戦で使う材料',
    VERDICT_REJECTED: '検証済み・買い材料としては否決',
    VERDICT_UNVERIFIED: '未検証（俗説として存在する）',
}

# 俗説を見るときの主指標。馬の得点ではない。0〜100の有効度は作らない。
# 数字は scripts/folklore_effectiveness_backtest.py の holdout 2025。
# 読みは3択（メーターにしない）: +1pt以上 / −1pt以下 / それ以外。
LENS_OVER_PT = 1.0
LENS_UNDER_PT = -1.0
LENS_WINDOW = '2025年'
MARKET_LENS = (
    dict(id='style_senko', title='先行', catalog_ids=('front_habit',),
         raw_pt=8.3, resid_pt=-0.23),
    dict(id='style_nige', title='逃げ', catalog_ids=(),
         raw_pt=9.5, resid_pt=-0.89),
    dict(id='style_sashi', title='差し', catalog_ids=(),
         raw_pt=-5.5, resid_pt=-0.17),
    dict(id='rot_layoff', title='休み明け', catalog_ids=('layoff_buy',),
         raw_pt=-4.0, resid_pt=-1.68),
    dict(id='rot_second', title='叩き2走目', catalog_ids=('second_start',),
         raw_pt=-1.5, resid_pt=-0.83),
    dict(id='draw_inner', title='内枠', catalog_ids=('inner_draw',),
         raw_pt=-0.5, resid_pt=-0.01),
    dict(id='draw_outer', title='外枠', catalog_ids=(),
         raw_pt=0.2, resid_pt=0.03),
    dict(id='wt_up', title='馬体重増', catalog_ids=('weight_plus10',),
         raw_pt=-1.6, resid_pt=-0.88),
    dict(id='wt_down', title='馬体重減', catalog_ids=('weight_down',),
         raw_pt=-5.1, resid_pt=-0.30),
    dict(id='wt_big', title='大幅増減', catalog_ids=(),
         raw_pt=-5.1, resid_pt=-1.81),
)


def fmt_signed_pt(x, digits=1):
    x = float(x)
    if x > 0:
        return f'+{x:.{digits}f}pt'
    if x < 0:
        return f'−{abs(x):.{digits}f}pt'
    return f'{0:.{digits}f}pt'


def market_lens_verdict(resid_pt):
    """人気をならしたあとの読み。3択。点数ではない。"""
    r = float(resid_pt)
    if r >= LENS_OVER_PT:
        return '市場が付けた人気より、よく来ている'
    if r <= LENS_UNDER_PT:
        return '人気のわりに来ていない（売れすぎ）'
    return '市場以上の優位性なし'


def market_lens_for_catalog(cid):
    for item in MARKET_LENS:
        if cid in item.get('catalog_ids', ()):
            return item
    return None


def market_lens_short(item):
    if not item:
        return ''
    raw = fmt_signed_pt(item['raw_pt'], 1)
    resid = fmt_signed_pt(item['resid_pt'], 2)
    v = market_lens_verdict(item['resid_pt'])
    return f"{LENS_WINDOW}: 生の3着以内 {raw} ／ 人気をならすと {resid} → {v}"


def _i(v, default=None):
    try:
        n = int(float(v))
        return n
    except (TypeError, ValueError):
        return default


def _f(v, default=None):
    try:
        x = float(v)
        if x != x:
            return default
        return x
    except (TypeError, ValueError):
        return default


def parse_weight(w_str):
    """'480(+4)' → (480, 4)。取れなければ (None, None)。"""
    if not w_str or '未公開' in str(w_str):
        return None, None
    m = re.match(r'(\d+)\s*[\(（]\s*([+\-]?\d+)\s*[\)）]', str(w_str))
    if m:
        return int(m.group(1)), int(m.group(2))
    m2 = re.match(r'(\d+)', str(w_str))
    if m2:
        return int(m2.group(1)), None
    return None, None


def parse_sex_age(s):
    t = str(s or '')
    sex = None
    if '牝' in t:
        sex = '牝'
    elif 'セ' in t or 'せん' in t:
        sex = 'セ'
    elif '牡' in t:
        sex = '牡'
    age = None
    m = re.search(r'(\d+)', t)
    if m:
        age = int(m.group(1))
    return sex, age


def class_rank(s):
    t = str(s or '')
    if not t:
        return None
    for k, v in _CLASS_RANK:
        if k in t:
            return v
    return None


def race_kind(meta):
    """新馬／オープン以上か。全馬に足す俗説の切り分け用。"""
    meta = meta or {}
    blob = f"{meta.get('RaceName') or ''} {meta.get('class') or ''} {meta.get('RaceTitle') or ''}"
    cr = class_rank(meta.get('class') or meta.get('RaceName') or '')
    is_maiden = ('新馬' in blob) or cr == 0
    is_open = (cr is not None and cr >= 5) or any(
        k in blob for k in ('オープン', 'ＯＰ', 'Ｇ１', 'Ｇ２', 'Ｇ３', 'G1', 'G2', 'G3', '重賞')
    )
    if is_maiden:
        is_open = False
    return is_maiden, is_open, cr


def season_of(month):
    if month is None:
        return None
    if month in (12, 1, 2):
        return '冬'
    if month in (3, 4, 5):
        return '春'
    if month in (6, 7, 8):
        return '夏'
    if month in (9, 10, 11):
        return '秋'
    return None


def fire_marks(n):
    """適合数の目安（メーターではなく段階表示）。多い＝買い、ではない。"""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 12:
        return '🔥🔥🔥'
    if n >= 8:
        return '🔥🔥'
    if n >= 5:
        return '🔥'
    return ''


def passing_nums(passing):
    nums = [_i(x) for x in re.findall(r'\d+', str(passing or ''))]
    return [n for n in nums if n]


def corner3(passing):
    nums = passing_nums(passing)
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0]
    return nums[-2]


def corner4(passing):
    nums = passing_nums(passing)
    return nums[-1] if nums else None


def _parse_date(s):
    t = str(s or '').strip()
    for fmt, raw in (('%Y%m%d', t[:8]), ('%Y.%m.%d', t.replace('/', '.'))):
        try:
            if fmt == '%Y%m%d' and len(raw) == 8 and raw.isdigit():
                return datetime.strptime(raw, fmt)
            if fmt == '%Y.%m.%d' and re.match(r'\d{4}\.\d{2}\.\d{2}', raw):
                return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue
    return None


def _clean_prev(run):
    if not run or not isinstance(run, dict):
        return None
    rank = _i(run.get('Rank'))
    if rank is not None and (rank <= 0 or rank >= 99):
        rank = None
    pop = _i(run.get('Popularity'))
    if pop is not None and (pop <= 0 or pop >= 99):
        pop = None
    dist = _i(run.get('Distance'))
    if dist is not None and dist <= 0:
        dist = None
    agari = _f(run.get('Agari'))
    if agari is not None and agari <= 0:
        agari = None
    margin = _f(run.get('Margin'))
    if margin is not None and abs(margin) >= 9.9:
        margin = None
    rid = str(run.get('RaceId') or '')
    venue = rid[4:6] if len(rid) >= 6 and rid[:6].isdigit() else ''
    grade = str(run.get('Grade') or '')
    return {
        'rank': rank,
        'pop': pop,
        'dist': dist,
        'surf': str(run.get('Surface') or ''),
        'agari': agari,
        'passing': str(run.get('Passing') or ''),
        'c3': corner3(run.get('Passing')),
        'c4': corner4(run.get('Passing')),
        'margin': margin,
        'date': str(run.get('Date') or ''),
        'jockey': str(run.get('PrevJockey') or '').strip(),
        'grade': grade,
        'field': _i(run.get('FieldSize')),
        'umaban': _i(run.get('PrevUmaban')),
        'venue': venue,
        'race_name': str(run.get('RaceName') or ''),
        'baba': str(run.get('Baba') or ''),
        'weight': _f(run.get('Weight')),
    }


def _agari_rank(all_prev, target):
    if not target or target <= 0:
        return None, 0
    vals = [p['agari'] for p in all_prev if p and p.get('agari')]
    if not vals:
        return None, 0
    rank = sum(1 for a in vals if a < target) + 1
    return rank, len(vals)


def _norm_jockey(s):
    return re.sub(r'\s+', '', str(s or ''))


# ── 1頭分のスナップ（マッチャが何度もパースしないため） ──────────────

def build_snaps(df, race_id='', meta=None, enrich=True):
    """出馬表df → 馬ごとの判定用dict。enrich=False なら DB を見ない（テスト用）。"""
    meta = meta or {}
    if df is None or getattr(df, 'empty', True):
        return []
    race_id = str(race_id or '')
    jyo = race_id[4:6] if len(race_id) >= 6 else ''
    n_horses = len(df)
    date_val = str(meta.get('date_val') or '')
    race_dt = _parse_date(date_val)
    month = race_dt.month if race_dt else None
    baba = str(meta.get('condition') or '')
    is_fillies = bool(meta.get('is_fillies'))
    is_handicap = bool(meta.get('is_handicap'))
    is_maiden, is_open, _cr = race_kind(meta)

    rows = []
    for _, r in df.iterrows():
        um = _i(r.get('Umaban'), 0)
        if not um:
            continue
        past = r.get('PastRuns') or []
        if not isinstance(past, list):
            past = []
        prev = _clean_prev(past[0] if past else None)
        prev2 = _clean_prev(past[1] if len(past) > 1 else None)
        sex, age = parse_sex_age(r.get('SexAge'))
        body_kg, delta_kg = parse_weight(r.get('Weight'))
        dist = _i(r.get('CurrentDistance'))
        surf = str(r.get('CurrentSurface') or '')
        is_dirt = 'ダ' in surf
        ninki = _i(r.get('Popularity'))
        if ninki is not None and ninki >= 99:
            ninki = None
        futan = _f(str(r.get('WeightCarried') or '').replace('kg', ''))
        gap_days = None
        if race_dt and prev and prev.get('date'):
            pdt = _parse_date(prev['date'])
            if pdt:
                gap_days = (race_dt - pdt).days
        gap12 = None
        if prev and prev2 and prev.get('date') and prev2.get('date'):
            d0, d1 = _parse_date(prev['date']), _parse_date(prev2['date'])
            if d0 and d1:
                gap12 = (d0 - d1).days
        dist_diff = None
        if dist and prev and prev.get('dist'):
            dist_diff = dist - prev['dist']
        first_dirt = False
        if is_dirt:
            dirt_hist = 0
            for p in past:
                if p and 'ダ' in str(p.get('Surface') or ''):
                    dirt_hist += 1
            first_dirt = dirt_hist == 0
        same_venue = bool(prev and prev.get('venue') and prev['venue'] == jyo)
        past_venues = set()
        past_dists = []
        for p in past:
            if not p:
                continue
            rid = str(p.get('RaceId') or '')
            if len(rid) >= 6 and rid[:6].isdigit():
                past_venues.add(rid[4:6])
            dd = _i(p.get('Distance'))
            if dd:
                past_dists.append(dd)
        first_venue = bool(jyo and past_venues and jyo not in past_venues)
        first_dist = bool(dist and past_dists and all(abs(dist - d) > 50 for d in past_dists))
        class_now = class_rank(meta.get('class') or meta.get('RaceName') or '')
        class_prev = class_rank((prev or {}).get('grade') or (prev or {}).get('race_name') or '')
        class_up = (class_now is not None and class_prev is not None and class_now > class_prev)
        cur_jk = _norm_jockey(r.get('Jockey'))
        prev_jk = _norm_jockey(prev.get('jockey') if prev else '')
        jockey_changed = bool(cur_jk and prev_jk and prev_jk != '-' and cur_jk != prev_jk)
        rows.append({
            'umaban': um,
            'name': str(r.get('Name') or ''),
            'ninki': ninki,
            'odds': _f(r.get('Odds')),
            'waku': _i(r.get('Waku')),
            'jockey': str(r.get('Jockey') or ''),
            'trainer': str(r.get('Trainer') or ''),
            'tozai': r.get('Tozai'),
            'sex': sex,
            'age': age,
            'blinker': _i(r.get('Blinker'), 0) == 1,
            'body_kg': body_kg,
            'delta_kg': delta_kg,
            'futan': futan,
            'sire': str(r.get('sire') or ''),
            'bms': str(r.get('broodmareSire') or ''),
            'prev': prev,
            'prev2': prev2,
            'past_n': len(past),
            'dist': dist,
            'surface': surf,
            'is_dirt': is_dirt,
            'jyo': jyo,
            'n_horses': n_horses,
            'month': month,
            'season': season_of(month),
            'baba': baba,
            'is_fillies': is_fillies,
            'is_handicap': is_handicap,
            'is_maiden': is_maiden,
            'is_open': is_open,
            'gap_days': gap_days,
            'gap12': gap12,
            'dist_diff': dist_diff,
            'first_dirt': first_dirt,
            'same_venue': same_venue,
            'first_venue': first_venue,
            'first_dist': first_dist,
            'class_now': class_now,
            'class_prev': class_prev,
            'class_up': class_up,
            'jockey_changed': jockey_changed,
            'agari_rank': None,
            'agari_n': 0,
            'blood_hi': False,
            'jockey_top': False,
            'jockey_course_hot': False,
            'golden': False,
            'trainer_course_hot': False,
            'blinker_first': None,
            'spurt_ctx': None,
            'dirt_draw': None,
            'wet_blood': None,
            'jockey_up': False,
            'paddock_tags': None,
            'training_tags': None,
        })

    all_prev = [h['prev'] for h in rows]
    for h in rows:
        if h['prev'] and h['prev'].get('agari'):
            h['agari_rank'], h['agari_n'] = _agari_rank(all_prev, h['prev']['agari'])

    _attach_paddock_tags(rows, race_id)

    if enrich:
        _enrich_live(rows, jyo)

    return rows


def _enrich_live(rows, jyo):
    """jravan 等が取れるときだけ足す。失敗しても俗説判定は止めない。"""
    jj = None
    tb = None
    try:
        from core import jockey_jv as jj
    except Exception:
        jj = None
    try:
        from core import track_bias as tb
    except Exception:
        tb = None

    top_cache = {}
    blood_hi = set()
    if rows:
        try:
            from core import blood_ev as bev
            surf = 'ダート' if rows[0]['is_dirt'] else '芝'
            dist = rows[0].get('dist')
            bands = bev.calibrate_bands()
            hs = [{
                'umaban': h['umaban'],
                'sire': h.get('sire'),
                'bms': h.get('bms'),
                'odds': h.get('odds'),
                'ninki': h.get('ninki'),
            } for h in rows]
            marked = bev.annotate_race(hs, surf, dist, bands)
            blood_hi = {int(r['umaban']) for r in marked if r.get('blood_label') == '高い'}
        except Exception:
            blood_hi = set()

    for h in rows:
        h['blood_hi'] = h['umaban'] in blood_hi
        if tb is not None:
            try:
                sig = tb.dirt_draw_signal(
                    h.get('waku'), h.get('ninki'),
                    'ダート' if h['is_dirt'] else '芝',
                    jyo=h.get('jyo'), kyori=h.get('dist'),
                )
                h['dirt_draw'] = sig
            except Exception:
                h['dirt_draw'] = None
            if h.get('sire') and h.get('ninki') and h['ninki'] <= 3 and h.get('baba') in ('稍重', '重', '不良'):
                try:
                    mod = tb.heavy_fav_blood_mod(
                        h['sire'],
                        'ダート' if h['is_dirt'] else '芝',
                        h['baba'],
                    )
                    h['wet_blood'] = mod
                except Exception:
                    h['wet_blood'] = None

        if jj is None:
            continue
        jk = h.get('jockey')
        if jk:
            if jk not in top_cache:
                try:
                    top_cache[jk] = bool(jj.jockey_is_top(jk))
                except Exception:
                    top_cache[jk] = False
            h['jockey_top'] = top_cache[jk]
            try:
                jcw = jj.jockey_course_winrate(jk, jyo, h.get('surface') or '')
                if jcw and (jcw.get('runs') or 0) >= 30 and (jcw.get('win_rate') or 0) >= 0.15:
                    h['jockey_course_hot'] = True
                    h['jockey_course_wr'] = jcw.get('win_rate')
            except Exception:
                pass
        try:
            kt, tc = jj.resolve_horse(h.get('name'))
        except Exception:
            kt, tc = None, None
        if kt:
            try:
                bh = jj.horse_blinker_history(kt)
                if bh is not None:
                    h['blinker_first'] = bool(h['blinker'] and (bh.get('blinker_runs') or 0) == 0)
            except Exception:
                pass
            try:
                ctx = jj.horse_recent_context(kt)
                h['spurt_ctx'] = ctx
            except Exception:
                pass
        if tc and jk:
            try:
                combo = jj.jockey_trainer_combo(jk, tc)
                h['golden'] = bool(jj.is_golden_line(combo))
                if combo:
                    h['golden_top2'] = combo.get('top2')
            except Exception:
                pass
            try:
                tw = jj.trainer_course_winrate(tc, jyo, h.get('surface') or '')
                if tw and (tw.get('win_rate_shrunk') or 0) >= 0.20:
                    h['trainer_course_hot'] = True
                    h['trainer_course_wr'] = tw.get('win_rate_shrunk')
            except Exception:
                pass
        if h.get('jockey_changed') and h.get('jockey_top'):
            h['jockey_up'] = True


def _attach_paddock_tags(rows, race_id):
    """パドック台帳に観察があればタグを付ける。無い馬は None＝判定しない。"""
    if not race_id or not rows:
        return
    try:
        from core import paddock_ledger as pdl
        led = pdl.load_ledger()
    except Exception:
        return
    pad, trn = {}, {}
    rid = str(race_id)
    for e in led or []:
        if str(e.get('race_id') or '') != rid:
            continue
        u = _i(e.get('umaban'))
        if not u:
            continue
        tags = [t for t in (e.get('tags') or [])]
        if e.get('scene') == 'training':
            trn.setdefault(u, set()).update(tags)
        else:
            pad.setdefault(u, set()).update(tags)
    for h in rows:
        u = h.get('umaban')
        if u in pad:
            h['paddock_tags'] = pad[u]
        if u in trn:
            h['training_tags'] = trn[u]


# ── 俗説マッチャ ──────────────────────────────────────────────

def _hit(h, ok, detail):
    return detail if ok else None


def _m_prev_fav1_flop(h):
    p = h.get('prev') or {}
    if p.get('pop') == 1 and p.get('rank') is not None and p['rank'] >= 5:
        return f"前走1番人気→{p['rank']}着"
    return None


def _m_prev_fav_flop(h):
    p = h.get('prev') or {}
    pop, rank = p.get('pop'), p.get('rank')
    if pop and pop <= 3 and rank is not None and rank >= 6:
        return f"前走{pop}人気→{rank}着"
    return None


def _m_prev_double_digit(h):
    p = h.get('prev') or {}
    rank = p.get('rank')
    if rank is not None and rank >= 10:
        return f"前走{rank}着（2桁）"
    return None


def _m_layoff(h):
    g = h.get('gap_days')
    if g is not None and g >= 90:
        return f"前走から{g}日ぶり"
    return None


def _m_second_start(h):
    g12 = h.get('gap12')
    p = h.get('prev') or {}
    if g12 is not None and g12 >= 90 and p.get('rank') is not None:
        return f"1走前が{g12}日ぶり→前走{p['rank']}着のあと2戦目"
    return None


def _m_weight_plus10(h):
    d = h.get('delta_kg')
    if d is not None and d >= 10:
        return f"馬体重 {h.get('body_kg')}kg（{d:+d}kg）"
    return None


def _m_weight_plus20(h):
    d = h.get('delta_kg')
    if d is not None and d >= 20:
        return f"馬体重 {h.get('body_kg')}kg（{d:+d}kg）"
    return None


def _m_inner_draw(h):
    w = h.get('waku')
    if not w or w > 3:
        return None
    if h.get('is_dirt'):
        return f"{w}枠（ダートは内が有利、という俗説）"
    if h.get('jyo') in _INNER_TURF_JYO:
        return f"{w}枠（この場の芝は内が有利、という俗説）"
    return None


def _m_prev_agari_best(h):
    ar, n = h.get('agari_rank'), h.get('agari_n') or 0
    p = h.get('prev') or {}
    if ar == 1 and n >= 3 and p.get('agari'):
        return f"前走上り{p['agari']:.1f}秒（このメンバーの前走では最速）"
    return None


def _m_dist_short(h):
    d = h.get('dist_diff')
    if d is not None and d <= -200:
        p = h.get('prev') or {}
        return f"{p.get('dist')}m→{h.get('dist')}m（{d}m）"
    return None


def _m_dist_long(h):
    d = h.get('dist_diff')
    if d is not None and d >= 200:
        p = h.get('prev') or {}
        return f"{p.get('dist')}m→{h.get('dist')}m（+{d}m）"
    return None


def _m_same_dist(h):
    d = h.get('dist_diff')
    if d is not None and abs(d) <= 99:
        return f"前走と同じ距離帯（差{d}m）"
    return None


def _m_first_blinker(h):
    if h.get('blinker_first') is True:
        return '今回がブリンカー初着用'
    return None


def _m_blinker_on(h):
    if h.get('blinker') and h.get('blinker_first') is not True:
        return 'ブリンカー着用'
    return None


def _m_first_dirt(h):
    if h.get('first_dirt'):
        extras = []
        if (h.get('waku') or 0) >= 6:
            extras.append('外枠')
        if (h.get('body_kg') or 0) >= 460:
            extras.append(f"{h['body_kg']}kg")
        tag = '・'.join(extras)
        return '芝からの初ダート' + (f'（俗説の加点材料: {tag}）' if tag else '')
    return None


def _m_okaeri(h):
    if h.get('same_venue'):
        return '前走と同じ競馬場（お帰り）'
    return None


def _m_filly_summer(h):
    if h.get('sex') == '牝' and h.get('season') == '夏':
        return f"牝馬×夏（{h.get('month')}月）"
    return None


def _m_filly_winter(h):
    if h.get('sex') == '牝' and h.get('season') in ('冬', '春'):
        return f"牝馬×{h.get('season')}"
    return None


def _m_prev_lead_lose(h):
    p = h.get('prev') or {}
    c4 = p.get('c4')
    rank = p.get('rank')
    if c4 is not None and c4 <= 2 and rank is not None and rank >= 5:
        return f"前走4角{c4}番手→{rank}着"
    return None


def _m_front_habit(h):
    p = h.get('prev') or {}
    nums = passing_nums(p.get('passing'))
    if not nums or p.get('rank') is None:
        return None
    avg = sum(nums) / len(nums)
    fs = p.get('field') or 12
    if avg / fs <= 0.28:
        return f"前走の通過が前寄り（{p.get('passing')}）"
    return None


def _m_tenkai_good(h):
    p = h.get('prev') or {}
    c4 = p.get('c4')
    if c4 is not None and c4 <= 4:
        return f"前走4角{c4}番手（好位残りそう、という俗説）"
    return None


def _m_shocker(h):
    p = h.get('prev') or {}
    c3 = p.get('c3')
    d = h.get('dist_diff')
    if c3 is not None and c3 >= 5 and d is not None and d < 0:
        return f"前走3角{c3}番手＋距離短縮"
    return None


def _m_prev_margin(h):
    p = h.get('prev') or {}
    m, rank = p.get('margin'), p.get('rank')
    if m is not None and rank is not None and rank >= 2 and 0 < m <= 0.8:
        return f"前走{rank}着・勝ち馬まで{m:.1f}秒"
    return None


def _m_prev_win(h):
    p = h.get('prev') or {}
    if p.get('rank') == 1:
        m = p.get('margin')
        extra = f"（着差{abs(m):.1f}秒）" if m is not None else ''
        return f"前走1着{extra}"
    return None


def _m_atsusho_trap(h):
    p = h.get('prev') or {}
    m = p.get('margin')
    if p.get('rank') == 1 and m is not None and abs(m) >= 1.0:
        return f"前走1着・着差{abs(m):.1f}秒（圧勝）"
    return None


def _m_track_change(h):
    p = h.get('prev') or {}
    ps = p.get('surf') or ''
    if not ps:
        return None
    prev_dirt = 'ダ' in ps
    if prev_dirt and not h.get('is_dirt'):
        return 'ダート→芝'
    if (not prev_dirt) and h.get('is_dirt') and not h.get('first_dirt'):
        return '芝→ダート'
    return None


def _m_east_west(h):
    tz = h.get('tozai')
    jyo = h.get('jyo') or ''
    ninki = h.get('ninki')
    if tz == 'east' and jyo in _WEST_JYO:
        return f"美浦所属→関西開催" + (f"（{ninki}番人気）" if ninki else '')
    if tz == 'west' and jyo in _EAST_JYO:
        return f"栗東所属→関東開催"
    return None


def _m_jockey_change(h):
    if h.get('jockey_changed'):
        p = h.get('prev') or {}
        return f"{p.get('jockey')}→{h.get('jockey')}"
    return None


def _m_top_jockey(h):
    if h.get('jockey_top'):
        return f"{h.get('jockey')}（勝率の高い騎手）"
    return None


def _m_course_jockey(h):
    if h.get('jockey_course_hot'):
        wr = h.get('jockey_course_wr')
        extra = f" 勝率{wr*100:.0f}%" if wr else ''
        return f"{h.get('jockey')}はこの場が得意{extra}"
    return None


def _m_blood_sire(h):
    if h.get('blood_hi') and h.get('sire'):
        return f"{h['sire']}産駒（この条件の見立てが人気より上）"
    return None


def _m_big_horse(h):
    kg = h.get('body_kg')
    if kg is not None and kg >= 500:
        return f"{kg}kg"
    return None


def _m_weight_minus20(h):
    d = h.get('delta_kg')
    if d is not None and d <= -20:
        return f"馬体重 {h.get('body_kg')}kg（{d:+d}kg）"
    return None


def _m_light_filly(h):
    if h.get('sex') == '牝' and h.get('futan') is not None and h['futan'] <= 51.0:
        return f"牝馬・斤量{h['futan']}kg"
    return None


def _m_age4(h):
    if h.get('age') == 4:
        return '4歳'
    return None


def _m_short_rest(h):
    g = h.get('gap_days')
    if g is not None and 1 <= g <= 14:
        return f"前走から{g}日（連闘〜中1週）"
    return None


def _m_dirt_layoff(h):
    g = h.get('gap_days')
    if h.get('is_dirt') and g is not None and g >= 63:
        return f"ダート×休み明け（{g}日）"
    return None


def _m_prev_close(h):
    p = h.get('prev') or {}
    m, rank = p.get('margin'), p.get('rank')
    if m is not None and rank is not None and rank >= 4 and 0 < m <= 0.3:
        return f"前走{rank}着・わずか{m:.1f}秒差"
    return None


def _m_prev_stakes(h):
    p = h.get('prev') or {}
    g = str(p.get('grade') or '') + str(p.get('race_name') or '')
    rank = p.get('rank')
    if rank is not None and rank >= 4 and any(k in g for k in ('G1', 'G2', 'G3', 'GI', 'GII', 'GIII', '重賞')):
        return f"前走重賞{rank}着（相手が強かった、という俗説）"
    return None


def _m_spurt_ls(h):
    ninki = h.get('ninki')
    ar = h.get('agari_rank')
    if ninki is not None and ninki >= 6 and ar is not None and ar <= 3:
        return f"{ninki}番人気・前走上りこのメンバー{ar}位"
    ctx = h.get('spurt_ctx') or {}
    si = ctx.get('spurt_index') if isinstance(ctx, dict) else None
    if ninki is not None and ninki >= 6 and si is not None and si <= 3:
        return f"{ninki}番人気・末脚指数が上位"
    return None


def _m_dirt_outer_fav(h):
    sig = h.get('dirt_draw') or {}
    if sig.get('type') == 'boost':
        return sig.get('label') or 'ダート外枠×人気上位'
    return None


def _m_dirt_inner_mid(h):
    sig = h.get('dirt_draw') or {}
    if sig.get('type') == 'danger':
        return sig.get('label') or 'ダート内枠×4〜5番人気'
    return None


def _m_fillies_fav1(h):
    if h.get('is_fillies') and h.get('ninki') == 1:
        return '牝馬限定戦の1番人気'
    return None


def _m_golden(h):
    if h.get('golden'):
        t2 = h.get('golden_top2')
        extra = f"（連対{t2*100:.0f}%）" if t2 else ''
        return f"{h.get('jockey')}×厩舎{extra}"
    return None


def _m_trainer_course(h):
    if h.get('trainer_course_hot'):
        wr = h.get('trainer_course_wr')
        extra = f" 勝率{wr*100:.0f}%" if wr else ''
        return f"この場の厩舎成績が高い{extra}"
    return None


def _m_wet_blood(h):
    mod = h.get('wet_blood')
    if not mod:
        return None
    kind = mod.get('mod') if isinstance(mod, dict) else None
    if kind == 'exempt':
        return SIGN_POS, f"{h.get('baba')}×{h.get('sire')}産駒（道悪向き）"
    if kind == 'intensify':
        return SIGN_NEG, f"{h.get('baba')}×{h.get('sire')}産駒（道悪は注意）"
    return None


def _m_rot_fav(h):
    g = h.get('gap_days')
    ninki = h.get('ninki')
    if ninki is not None and ninki <= 3 and g is not None and g >= 63:
        return f"{ninki}番人気・中{g // 7}週以上"
    return None


def _m_ninki1_solid(h):
    if h.get('ninki') == 1:
        return '1番人気'
    return None


def _m_filly_fav1_any(h):
    if h.get('sex') == '牝' and h.get('ninki') == 1 and not h.get('is_fillies'):
        return '牝馬の1番人気（牝馬限定戦ではない）'
    return None


def _m_colt_winter(h):
    if h.get('sex') == '牡' and h.get('season') == '冬':
        return f"牡馬×冬（{h.get('month')}月）"
    return None


def _m_gelding_summer(h):
    if h.get('sex') == 'セ' and h.get('season') == '夏':
        return f"セン馬×夏（{h.get('month')}月）"
    return None


def _m_dirt_class_up(h):
    if h.get('is_dirt') and h.get('class_up'):
        return 'ダートの昇級戦'
    return None


def _m_maiden_up(h):
    p = h.get('prev') or {}
    g = str(p.get('grade') or '') + str(p.get('race_name') or '')
    if '未勝利' in g and h.get('class_up'):
        return f"前走未勝利{p.get('rank') or ''}着→昇級"
    return None


def _m_nige_win_up(h):
    p = h.get('prev') or {}
    if h.get('class_up') and p.get('rank') == 1 and (p.get('c4') or 99) <= 2:
        return f"前走逃げ切り勝ち（4角{p.get('c4')}番手）の昇級"
    return None


def _m_layoff_fav_plus10(h):
    g, d, n = h.get('gap_days'), h.get('delta_kg'), h.get('ninki')
    if g is not None and g >= 90 and d is not None and d >= 10 and n is not None and n <= 3:
        return f"{n}番人気・{g}日ぶり・馬体重{d:+d}kg"
    return None


def _m_first_venue(h):
    if h.get('first_venue'):
        return 'この競馬場は初めて'
    return None


def _m_first_dist(h):
    if h.get('first_dist'):
        return f"この距離（{h.get('dist')}m）は初めて"
    return None


def _m_local_rensen(h):
    g = h.get('gap_days')
    if (h.get('jyo') or '') in _LOCAL_JYO and g is not None and 1 <= g <= 8:
        return f"ローカル開催の連闘（前走から{g}日）"
    return None


def _m_stay_jockey(h):
    if h.get('past_n') and not h.get('jockey_changed'):
        p = h.get('prev') or {}
        return f"前走から継続騎乗（{h.get('jockey') or p.get('jockey')}）"
    return None


def _m_jockey_change_minus(h):
    if h.get('jockey_changed'):
        p = h.get('prev') or {}
        return f"{p.get('jockey')}→{h.get('jockey')}（乗り替わりはマイナス、という俗説）"
    return None


def _m_jockey_up(h):
    if h.get('jockey_up'):
        p = h.get('prev') or {}
        return f"{p.get('jockey')}→{h.get('jockey')}（勝率の高い騎手へ）"
    return None


def _m_closer_overbet(h):
    p = h.get('prev') or {}
    fs = p.get('field') or h.get('n_horses') or 12
    c4 = p.get('c4')
    ninki = h.get('ninki')
    if c4 is not None and fs and c4 >= max(8, int(fs * 0.7)) and ninki is not None and ninki <= 5:
        return f"前走4角{c4}番手の追い込み型なのに{ninki}番人気"
    return None


def _m_small_field_closer(h):
    n = h.get('n_horses') or 0
    p = h.get('prev') or {}
    c4 = p.get('c4')
    if n and n <= 10 and c4 is not None and c4 >= 6:
        return f"{n}頭立て・前走4角{c4}番手"
    return None


def _m_closer_blinker(h):
    p = h.get('prev') or {}
    c4 = p.get('c4')
    if h.get('blinker') and c4 is not None and c4 >= 8:
        return f"ブリンカー＋前走4角{c4}番手の追い込み"
    return None


def _m_wet_front(h):
    if h.get('baba') not in ('稍重', '重', '不良'):
        return None
    p = h.get('prev') or {}
    nums = passing_nums(p.get('passing'))
    if not nums:
        return None
    if nums[0] <= 3:
        return f"{h.get('baba')}馬場・前走の位置が前（{p.get('passing')}）"
    return None


def _m_futan_up(h):
    p = h.get('prev') or {}
    prev_f = p.get('weight')
    cur = h.get('futan')
    if prev_f is not None and cur is not None and (cur - prev_f) >= 1.0:
        return f"斤量 {prev_f}kg→{cur}kg（+{cur - prev_f:.1f}kg）"
    return None


def _m_prev_fluke(h):
    p = h.get('prev') or {}
    pop, rank = p.get('pop'), p.get('rank')
    if pop is not None and pop >= 6 and rank is not None and rank <= 2:
        ninki = h.get('ninki')
        extra = f"→今回{ninki}番人気" if ninki and ninki <= 5 else ''
        return f"前走{pop}人気で{rank}着{extra}"
    return None


def _m_wet_to_good(h):
    p = h.get('prev') or {}
    if p.get('baba') in ('稍重', '重', '不良') and h.get('baba') == '良':
        rank = p.get('rank')
        extra = f"前走{rank}着" if rank else '前走道悪'
        return f"{extra}（{p.get('baba')}）→今回良馬場"
    return None


def _m_inner_to_outer(h):
    p = h.get('prev') or {}
    pu, w = p.get('umaban'), h.get('waku')
    rank = p.get('rank')
    if pu is not None and pu <= 3 and w is not None and w >= 6 and rank is not None and rank <= 3:
        return f"前走{pu}番で{rank}着→今回{w}枠"
    return None


def _m_dirt_out_to_in(h):
    if not h.get('is_dirt'):
        return None
    p = h.get('prev') or {}
    pu, w = p.get('umaban'), h.get('waku')
    if pu is not None and pu >= 6 and w is not None and w <= 3:
        return f"ダート・前走{pu}番→今回{w}枠"
    return None


def _m_win_up_3win(h):
    p = h.get('prev') or {}
    if h.get('class_up') and p.get('rank') == 1 and (h.get('class_prev') or 0) >= 4:
        return '3勝クラス以上の勝ち上がり直後の昇級'
    return None


def _m_fav_slow_agari(h):
    ninki, ar, n = h.get('ninki'), h.get('agari_rank'), h.get('agari_n') or 0
    if ninki is not None and ninki <= 3 and ar is not None and n >= 5 and ar >= max(6, int(n * 0.6)):
        return f"{ninki}番人気なのに前走上りこのメンバー{ar}/{n}位"
    return None


def _m_weight_down(h):
    d = h.get('delta_kg')
    if d is not None and d <= -8:
        return f"馬体重 {h.get('body_kg')}kg（{d:+d}kg）絞れた、という俗説"
    return None


def _m_dirt_front(h):
    if not h.get('is_dirt'):
        return None
    d = _m_front_habit(h)
    if d:
        return f"ダート・{d}"
    return None


def _m_dirt_closer_miss(h):
    if not h.get('is_dirt'):
        return None
    p = h.get('prev') or {}
    fs = p.get('field') or h.get('n_horses') or 12
    c4 = p.get('c4')
    nums = passing_nums(p.get('passing'))
    back = False
    if c4 is not None and fs and c4 >= max(6, int(fs * 0.55)):
        back = True
    elif nums and fs:
        avg = sum(nums) / len(nums)
        if avg / fs >= 0.50:
            back = True
    if back:
        pos = p.get('passing') or (f"4角{c4}" if c4 is not None else '')
        return f"ダート・前走が後ろ（{pos}）"
    return None


def _m_dirt_small(h):
    kg = h.get('body_kg')
    if h.get('is_dirt') and kg is not None and kg <= 440:
        return f"ダート・{kg}kg（440kg以下は苦戦、という俗説）"
    return None


def _m_dirt_2yo_power(h):
    kg = h.get('body_kg')
    if h.get('is_dirt') and h.get('age') == 2 and kg is not None and kg >= 460:
        return f"ダート2歳・{kg}kg"
    return None


def _m_open_nakaana(h):
    n = h.get('ninki')
    if h.get('is_open') and n is not None and 4 <= n <= 6:
        return f"オープン以上・{n}番人気（中穴が飛びやすい、という俗説）"
    return None


def _m_stakes_nige(h):
    if not h.get('is_open'):
        return None
    d = _m_front_habit(h)
    if d:
        return f"重賞・上級戦の先行（{d}）"
    return None


def _m_open_cond_win_fav(h):
    if not h.get('is_open') or h.get('ninki') != 1:
        return None
    p = h.get('prev') or {}
    prev_cls = h.get('class_prev')
    if p.get('rank') == 1 and prev_cls is not None and prev_cls <= 3:
        return '条件戦を勝ってオープンの1番人気'
    return None


def _m_maiden_fav1(h):
    if h.get('is_maiden') and h.get('ninki') == 1:
        return '新馬戦の1番人気'
    return None


def _m_turf_2yo_small(h):
    kg = h.get('body_kg')
    n = h.get('ninki')
    if h.get('is_dirt') or h.get('age') != 2 or not h.get('is_maiden'):
        return None
    if h.get('month') not in (6, 7, 8, 9):
        return None
    if kg is None or kg >= 400 or n is None or n < 6:
        return None
    return f"芝の夏2歳新馬・{kg}kg・{n}番人気"


def _m_filly_wear(h):
    d = h.get('delta_kg')
    if h.get('sex') == '牝' and d is not None and d <= -10:
        return f"牝馬・馬体重{d:+d}kg（使い減り、という俗説）"
    return None


def _tag_m(store, tag, msg):
    def _m(h):
        tags = h.get(store)
        if tags is None:
            return SKIP
        if tag in tags:
            return msg
        return None
    _m.__name__ = f'_m_{store}_{tag}'
    return _m


def _always_skip(_h):
    return SKIP


# 俗説として「消し・危険・嫌う」側。タイトルの語り口で決める（検証の採否とは別）。
_NEG_IDS = frozenset({
    'weight_minus20', 'dirt_layoff', 'dirt_inner_mid', 'fillies_fav1', 'rot_fav',
    'filly_fav1_any', 'gelding_summer', 'dirt_class_up', 'maiden_up', 'nige_win_up',
    'layoff_fav_plus10', 'first_venue', 'first_dist', 'jockey_change_minus',
    'closer_overbet', 'closer_blinker', 'futan_up', 'prev_fluke', 'wet_to_good',
    'inner_to_outer', 'dirt_out_to_in', 'win_up_3win', 'fav_slow_agari',
    'dirt_closer_miss', 'dirt_small', 'stakes_nige', 'filly_wear',
    'open_cond_win_fav', 'skip_estrus', 'skip_dam_age', 'skip_oikiri_score',
    'pad_sweat_foam', 'pad_sweat_cold', 'pad_umake', 'pad_chaka', 'pad_crane',
    'pad_diarrhea', 'pad_overw', 'pad_thin', 'pad_inner_walk',
    'tr_head_high', 'tr_decel', 'tr_light', 'skip_gyakute', 'skip_prep',
})


def _finalize(rules):
    """sign/confidence/weight を必ず持たせる。weight は今の点数には使わない。"""
    out = []
    for r in rules:
        item = dict(r)
        if 'sign' not in item:
            item['sign'] = SIGN_NEG if item['id'] in _NEG_IDS else SIGN_POS
        item['confidence'] = item.get('confidence') or CONF_NORMAL
        item.setdefault('weight', 1.0)
        out.append(item)
    return out


def _rules():
    R, E, U = VERDICT_REJECTED, VERDICT_EFFECTIVE, VERDICT_UNVERIFIED
    return _finalize([
        dict(id='prev_fav1_flop', title='前走1番人気で凡走→反動で買い',
             category='人気系', verdict=R,
             note='巻き返し・人気落ちは売れすぎ（comeback_overbet）',
             match=_m_prev_fav1_flop),
        dict(id='prev_fav_flop', title='前走の人気馬が大敗したら次走は買い',
             category='人気系', verdict=R,
             note='凡走からの巻き返しは穴帯で残差ゼロ〜マイナス',
             match=_m_prev_fav_flop),
        dict(id='prev_double_digit', title='前走2桁着順からの巻き返しは買い',
             category='前走系', verdict=R,
             note='着順だけの巻き返しは否決',
             match=_m_prev_double_digit),
        dict(id='layoff_buy', title='休み明けは狙い',
             category='ローテ系', verdict=R,
             note='休み明け好走は人気に織込み済み',
             match=_m_layoff),
        dict(id='second_start', title='休み明け2戦目は狙い',
             category='ローテ系', verdict=R,
             note='叩き2走目も織込み済み',
             match=_m_second_start),
        dict(id='weight_plus10', title='馬体重＋10kg以上は成長で買い',
             category='馬体重系', verdict=R,
             note='増減だけで買う妙味は残差で消える（weight_video_claims）',
             match=_m_weight_plus10),
        dict(id='weight_plus20', title='馬体重＋20kgは過小評価で買い',
             category='馬体重系', verdict=R,
             note='単回収の生数字は高く見えるが、複勝残差はマイナス。実装しない',
             match=_m_weight_plus20),
        dict(id='inner_draw', title='内枠有利のコースだから買い',
             category='枠順系', verdict=R,
             note='枠の有利不利は人気にかなり織込まれている。例外はダートの人気帯別のみ',
             match=_m_inner_draw),
        dict(id='prev_agari_best', title='前走上がり最速は買い',
             category='前走系', verdict=R,
             note='上がり単体はスロー由来が多い。効くのは人気薄×上位に限る',
             match=_m_prev_agari_best),
        dict(id='dist_short', title='距離短縮は買い',
             category='距離系', verdict=R,
             note='大幅短縮は過剰人気（folk_signals）',
             match=_m_dist_short),
        dict(id='dist_long', title='距離延長は買い',
             category='距離系', verdict=R,
             note='大幅延長も過剰人気',
             match=_m_dist_long),
        dict(id='same_dist', title='前走と同じ距離は買い',
             category='距離系', verdict=E,
             note='同距離±99mはわずかに残差プラス。エンジンの加点にはしていない',
             match=_m_same_dist),
        dict(id='first_blinker', title='初ブリンカーは大穴',
             category='馬具系', verdict=R,
             note='初ブリンカーは正の妙味ゼロ。注意表示のみ',
             match=_m_first_blinker),
        dict(id='blinker_on', title='ブリンカー着用は集中して買い',
             category='馬具系', verdict=R,
             note='検証2026-08: 着用馬(初回除く) n=4,409で複勝残差+0.2pp z+0.3。効果なし',
             match=_m_blinker_on),
        dict(id='first_dirt', title='初ダートは買い',
             category='馬場系', verdict=R,
             note='初ダートは強い過剰人気。好走条件を足すほど悪化',
             match=_m_first_dirt),
        dict(id='okaeri', title='お帰り（同じコースに戻る）は買い',
             category='コース系', verdict=R,
             note='得意コース戻りは妙味ゼロ',
             match=_m_okaeri),
        dict(id='filly_summer', title='夏の牝馬は買い',
             category='性別系', verdict=R,
             note='資料もダートでは通用せず。芝7〜9月・2kg差が瞬発力、という俗説だが残差では売れすぎ',
             match=_m_filly_summer),
        dict(id='filly_winter', title='冬・春の牝馬は買い',
             category='性別系', verdict=R,
             note='牝×冬/春は有意に過剰人気。フェード注意として実戦表示あり',
             match=_m_filly_winter),
        dict(id='prev_lead_lose', title='前走4角先頭で負けた馬は展開不利だったから買い',
             category='前走系', verdict=R,
             note='展開・脚質の「次走巻き返し」は織込み済み',
             match=_m_prev_lead_lose),
        dict(id='front_habit', title='先行馬は軸向き',
             category='脚質系', verdict=R,
             note='本物の先行は軸として過剰人気（front_runner_overbet）',
             match=_m_front_habit),
        dict(id='tenkai_good', title='展開が向きそうだから買い',
             category='展開系', verdict=R,
             note='展開恩恵は人気薄ほど売れすぎ（tenkai_priced_in）',
             match=_m_tenkai_good),
        dict(id='shocker', title='逆ショッカー（前走後方＋距離短縮）は買い',
             category='展開系', verdict=R,
             note='完成条件を入れると結果論。事前①②だけだとエッジ消滅',
             match=_m_shocker),
        dict(id='prev_margin', title='前走着差0.8秒以内は実力',
             category='前走系', verdict=R,
             note='前走着差の閾値は小標本ノイズ（prior_margin_debunk）',
             match=_m_prev_margin),
        dict(id='prev_win', title='前走1着の勢いは軸向き',
             category='前走系', verdict=R,
             note='勝ち上がり直後の人気馬は複勝が-2pp。圧勝かどうかは問わない',
             match=_m_prev_win),
        dict(id='atsusho', title='前走圧勝馬の単勝は買い',
             category='前走系', verdict=R,
             note='「圧勝の罠」も誤り。複勝軸としては良いが単勝エッジではない',
             match=_m_atsusho_trap),
        dict(id='track_change', title='芝⇔ダート替わりは買い',
             category='馬場系', verdict=R,
             note='トラック変更は過剰人気（track_change_overbet）',
             match=_m_track_change),
        dict(id='east_west', title='遠征馬（東西をまたぐ）は買い',
             category='ローテ系', verdict=R,
             note='東→西×1-6人気は過剰人気。関西馬の東征も織込み済み',
             match=_m_east_west),
        dict(id='jockey_change', title='騎手乗り替わりは買い',
             category='騎手系', verdict=R,
             note='乗替わり一律は織込み済み',
             match=_m_jockey_change),
        dict(id='top_jockey', title='強い騎手だから買い',
             category='騎手系', verdict=U,
             note='騎手名だけの買い材料は未検証。騎手力は比較用',
             match=_m_top_jockey),
        dict(id='course_jockey', title='この騎手はこのコースに強い',
             category='騎手系', verdict=U,
             note='コース巧者への乗替は弱いプラス傾向。スコアには足していない',
             match=_m_course_jockey),
        dict(id='blood_sire', title='この産駒はこの条件に強い',
             category='血統系', verdict=R,
             note='血統×コースは織込み済み。見立てが人気より上は見比べ用',
             match=_m_blood_sire),
        dict(id='big_horse', title='大型馬はダート向きで買い',
             category='馬体重系', verdict=R,
             note='資料はダート2歳から460〜500kg優勢。500kg超は人気に織込み。穴帯の妙味なし',
             match=_m_big_horse),
        dict(id='weight_minus20', title='馬体重-20kgは消し',
             category='馬体重系', verdict=U,
             note='成績は悪いが、数字だけで消すルールにはしていない',
             match=_m_weight_minus20),
        dict(id='light_filly', title='軽ハンデの牝馬は買い',
             category='斤量系', verdict=R,
             note='性別×斤量の俗説は残差ゲート未達（gender_folklore）',
             match=_m_light_filly),
        dict(id='age4', title='4歳は完成期で買い',
             category='性別系', verdict=R,
             note='検証2026-08: n=8,285で残差-0.4pp z-0.9。年齢だけのエッジなし',
             match=_m_age4),
        dict(id='short_rest', title='連闘・中1週は買い',
             category='ローテ系', verdict=R,
             note='検証2026-08: n=5,239で残差+0.1pp z+0.1。買い効果なし（人気馬の短間隔否決と整合）',
             match=_m_short_rest),
        dict(id='dirt_layoff', title='ダートの休み明けは割引',
             category='ローテ系', verdict=E,
             note='検証2026-08: ダート63日+休明 n=7,249で複勝残差-1.1pp z-2.3、recentも-1.1pp同符号。効果は小さくfade側の知識',
             match=_m_dirt_layoff),
        dict(id='prev_close', title='前走僅差の着外は次走買い',
             category='前走系', verdict=U,
             note='重賞×0.3秒は表示バッジあり。スコアには入れていない',
             match=_m_prev_close),
        dict(id='prev_stakes', title='前走重賞負けは相手が強かったから買い',
             category='前走系', verdict=U,
             note='格上挑戦からの降級は参考表示のみ',
             match=_m_prev_stakes),
        dict(id='spurt_ls', title='人気薄で前走上がり上位は買い',
             category='前走系', verdict=E,
             note='6番人気以下×上がり上位は検証済み（spurt_index）。人気上位では効かない',
             match=_m_spurt_ls),
        dict(id='dirt_outer_fav', title='ダートの外枠・人気上位は軸向き',
             category='枠順系', verdict=E,
             note='ダート外枠×1-3人気は複勝残差+4.5pp。穴帯の外枠は効かない',
             match=_m_dirt_outer_fav),
        dict(id='dirt_inner_mid', title='ダートの内枠・4〜5番人気は危ない',
             category='枠順系', verdict=E,
             note='内枠×4-5人気は危険人気（残差-3.9pp）',
             match=_m_dirt_inner_mid),
        dict(id='fillies_fav1', title='牝馬限定の1番人気は危ない',
             category='人気系', verdict=E,
             note='冬毛・愛知杯など冬は人気が飛びやすい、という俗説。1番人気は同じオッズでも来にくい',
             match=_m_fillies_fav1),
        dict(id='golden', title='騎手と調教師の相性が良い（黄金ライン）',
             category='騎手系', verdict=E,
             note='連対35-40%帯が残差で残る。40%超は売れすぎ寄り',
             match=_m_golden),
        dict(id='trainer_course', title='厩舎の当コース勝率が高い',
             category='騎手系', verdict=E,
             note='当コース勝率20%以上のみ妙味。全体勝率A-Dは織込み済み',
             match=_m_trainer_course),
        dict(id='wet_blood', title='道悪で血統が向き／向かない',
             category='血統系', verdict=E,
             note='道悪×血統は人気上位の表示のみ。穴馬の逆張りには使わない',
             match=_m_wet_blood),
        dict(id='rot_fav', title='人気馬の長い休み明けは減点',
             category='ローテ系', verdict=E,
             note='1-3番人気×中9週以上は危険側の材料',
             match=_m_rot_fav),
        dict(id='ninki1_solid', title='1番人気は一番強くて堅い',
             category='人気系', verdict=R,
             note='検証2026-08: 1番人気の複勝残差はほぼ±0（n=3,327 z-0.1）=市場は正確。新馬限定は別項目',
             match=_m_ninki1_solid),
        dict(id='filly_fav1_any', title='牝馬の1番人気は信用できない',
             category='人気系', verdict=U,
             note='検証済みなのは牝馬限定戦の1番人気。一般戦の牝馬1番人気は別',
             match=_m_filly_fav1_any),
        dict(id='colt_winter', title='冬は牡馬',
             category='性別系', verdict=R,
             note='検証2026-08: 冬×牡 n=6,103で残差+0.4pp z+0.7。単独エッジなし',
             match=_m_colt_winter),
        dict(id='gelding_summer', title='夏負けは夏キン（セン馬は夏弱い）',
             category='性別系', verdict=U,
             note='セン馬×夏の残差は未検証',
             match=_m_gelding_summer),
        dict(id='gray_summer', title='芦毛の夏駆け',
             category='性別系', verdict=U,
             note='毛色が出馬表から取れないので、この画面では判定できない',
             match=_always_skip),
        dict(id='dirt_class_up', title='ダートの昇級戦は危険',
             category='ローテ系', verdict=U,
             note='昇級そのものは未検証。前走1着の人気馬は別途減点あり',
             match=_m_dirt_class_up),
        dict(id='maiden_up', title='前走未勝利の昇級馬は信頼できない',
             category='ローテ系', verdict=R,
             note='検証2026-08: 未勝利勝ち上がり n=2,953で残差+0.5pp z+0.7。むしろ微プラスで危険ではない',
             match=_m_maiden_up),
        dict(id='nige_win_up', title='前走逃げて勝った馬の昇級は負けやすい',
             category='脚質系', verdict=U,
             note='逃げ切り＋昇級の交互作用は未検証',
             match=_m_nige_win_up),
        dict(id='layoff_fav_plus10', title='休み明けの人気馬が大幅増は太め残りで嫌う',
             category='馬体重系', verdict=R,
             note='同じ数字を「成長分で買い」とする俗説もある。残差では買い妙味なし',
             match=_m_layoff_fav_plus10),
        dict(id='first_venue', title='初めての競馬場は不安',
             category='コース系', verdict=U,
             note='お帰りの逆。未検証',
             match=_m_first_venue),
        dict(id='first_dist', title='初めての距離は不安',
             category='距離系', verdict=E,
             note='検証2026-08: 初距離 n=10,736で複勝残差-1.1pp z-2.8、recentも-1.1pp同符号。人気よりわずかに過剰評価',
             match=_m_first_dist),
        dict(id='local_rensen', title='ローカル開催の連闘は勝負気配',
             category='ローテ系', verdict=U,
             note='短間隔の集合体は未検証',
             match=_m_local_rensen),
        dict(id='stay_jockey', title='継続騎乗の方が馬を知っていて有利',
             category='騎手系', verdict=U,
             note='乗替わり一律は織込み済み。継続がプラスかは未検証',
             match=_m_stay_jockey),
        dict(id='jockey_change_minus', title='乗り替わりはマイナス',
             category='騎手系', verdict=R,
             note='乗り替わり一律は織込み済み。「買い」も「マイナス」も単独では効かない',
             match=_m_jockey_change_minus),
        dict(id='jockey_up', title='下位騎手から強い騎手への乗り替わりは買い',
             category='騎手系', verdict=U,
             note='鞍上強化は参考表示。スコアには足していない',
             match=_m_jockey_up),
        dict(id='closer_overbet', title='追い込み馬はかっこよくて売れやすい',
             category='脚質系', verdict=E,
             note='検証2026-08: 5人気以内の追込型 n=1,808で複勝残差-2.9pp z-2.5、recentも-2.7pp同符号。過剰人気を確認',
             match=_m_closer_overbet),
        dict(id='small_field_closer', title='少頭数は差し馬を買え',
             category='脚質系', verdict=U,
             note='少頭数×差しの残差は未検証',
             match=_m_small_field_closer),
        dict(id='closer_blinker', title='追い込み馬のブリンカー装着は危険',
             category='馬具系', verdict=R,
             note='検証2026-08: 追込×ブリンカー n=2,356で残差+0.3pp z+0.4。危険ではない',
             match=_m_closer_blinker),
        dict(id='wet_front', title='悪条件を走り抜けるのは先行馬',
             category='脚質系', verdict=R,
             note='道悪×脚質は織込み済み',
             match=_m_wet_front),
        dict(id='futan_up', title='斤量1kg増は1馬身不利',
             category='斤量系', verdict=R,
             note='斤量変化はLTRに織込み済み。1kg=0.2秒は目安の俗説',
             match=_m_futan_up),
        dict(id='prev_fluke', title='前走人気薄の好走はフロックで次走飛ぶ',
             category='前走系', verdict=U,
             note='マグレ次走、という減点俗説。未検証',
             match=_m_prev_fluke),
        dict(id='wet_to_good', title='前走道悪好走→良馬場は評価が逆転する',
             category='馬場系', verdict=R,
             note='検証2026-08: 道悪好走→良 n=7,232で残差+0.5pp z+1.0。評価逆転は起きない',
             match=_m_wet_to_good),
        dict(id='inner_to_outer', title='前走内枠好走→今回外枠は同じ脚が使えない',
             category='枠順系', verdict=U,
             note='枠の恩恵が剥がれる、という減点俗説。未検証',
             match=_m_inner_to_outer),
        dict(id='dirt_out_to_in', title='ダートで外枠から内枠に変わると砂を被る',
             category='枠順系', verdict=R,
             note='検証2026-08: ダ外枠→内枠 n=4,633で残差-0.1pp z-0.2。砂被り効果なし',
             match=_m_dirt_out_to_in),
        dict(id='win_up_3win', title='3勝クラス以上の前走1着昇級は壁',
             category='ローテ系', verdict=R,
             note='前走1着の人気馬は複勝-2pp。クラスの壁というより勝ち上がり直後',
             match=_m_win_up_3win),
        dict(id='fav_slow_agari', title='人気馬なのに上がりが遅いのは飛ぶ',
             category='人気系', verdict=R,
             note='検証2026-08: 3人気内×前走上り下位 n=2,864で残差-0.7pp z-0.8。織込み済み',
             match=_m_fav_slow_agari),
        dict(id='weight_down', title='前走比で絞れていれば好状態',
             category='馬体重系', verdict=R,
             note='減だけで買いにはならない。小柄×大幅減は既存の注意。牝馬の急減は使い減り俗説あり',
             match=_m_weight_down),
        dict(id='dirt_front', title='ダートは逃げ・先行が届く',
             category='脚質系', verdict=R,
             note='検証2026-08: ダート先行勢 n=5,996で残差-0.4pp z-0.7。届く有利さはなし（先行売れすぎと整合）',
             match=_m_dirt_front),
        dict(id='dirt_closer_miss', title='ダートの差し・追い込みは届かない',
             category='脚質系', verdict=R,
             note='検証2026-08: ダート後方勢 n=10,960で残差-0.1pp z-0.4。「届かない」は非確認',
             match=_m_dirt_closer_miss),
        dict(id='dirt_small', title='ダートの440kg以下は苦戦',
             category='馬体重系', verdict=U,
             note='筋肉量が要るので小型は苦戦、という俗説。未検証',
             match=_m_dirt_small),
        dict(id='dirt_2yo_power', title='ダート2歳は460kg以上が優勢',
             category='馬体重系', verdict=U,
             note='2歳夏から中〜大型、という俗説。500kg超の全体は織込み済み',
             match=_m_dirt_2yo_power),
        dict(id='open_nakaana', title='オープン・重賞の中穴（4〜6番人気）は飛びやすい',
             category='人気系', verdict=U,
             note='条件戦より上級戦は穴が来る、という俗説。未検証',
             match=_m_open_nakaana),
        dict(id='stakes_nige', title='重賞の逃げ先行はマークされて失速しやすい',
             category='脚質系', verdict=U,
             note='レベルの高いレースではマークが厳しい、という俗説。未検証',
             match=_m_stakes_nige),
        dict(id='open_cond_win_fav', title='条件戦を勝ってオープンの1番人気は飛ぶ',
             category='人気系', verdict=U,
             note='連勝の過剰人気、という俗説。前哨戦かは出馬表だけでは分からない',
             match=_m_open_cond_win_fav),
        dict(id='maiden_fav1', title='新馬戦の1番人気は信頼できる',
             category='人気系', verdict=U,
             note='血統や戦前評価が素直に出る、という俗説。新馬は人気の識別が弱い、という検証もある',
             match=_m_maiden_fav1),
        dict(id='turf_2yo_small', title='芝の夏2歳新馬は小型馬が穴で走る',
             category='馬体重系', verdict=U,
             note='400kg未満の人気薄、という俗説。未検証。買う指示ではない',
             match=_m_turf_2yo_small),
        dict(id='filly_wear', title='牝馬の馬体重急減は使い減り',
             category='性別系', verdict=U,
             note='神経質で詰めると気性難、という俗説。未検証',
             match=_m_filly_wear),
        dict(id='pad_sweat_foam', title='白い泡の発汗は消し',
             category='パドック系', verdict=U,
             note='予測には使わない。パドック台帳に観察があれば判定',
             match=_tag_m('paddock_tags', 'sweat_foam', '白い泡の発汗')),
        dict(id='pad_sweat_cold', title='涼しいのに大量の発汗は買えない',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'sweat_cold', '季節外れの大量発汗')),
        dict(id='pad_umake', title='パドックで馬っ気の牡馬は消し',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'umake', '馬っ気')),
        dict(id='pad_chaka', title='チャカついている馬はダメ、落ち着いている馬は良い',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'chaka', 'イレ込み・チャカつき')),
        dict(id='pad_calm', title='パドックで落ち着いて堂々と歩く馬は絶好調',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'calm_focus', '落ち着き・集中')),
        dict(id='pad_deep_step', title='後肢の踏み込みがいい馬は調子がいい',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'deep_step', '踏み込みが深い')),
        dict(id='pad_two', title='二人引きの馬は勝負度合いが高い',
             category='パドック系', verdict=U,
             note='気性難の減点、とも言われる。観察が必要',
             match=_tag_m('paddock_tags', 'two_handler', '2人引き')),
        dict(id='pad_crane', title='首が高い（鶴首）馬は緊張して力が出ない',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'head_high', '頭が高い・力み')),
        dict(id='pad_diarrhea', title='下痢（水分の多いボロ）の馬はナーバスで消し',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'diarrhea', '下痢')),
        dict(id='pad_overw', title='お腹が出ている（太め残り）馬は消し',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'over_weight', '太め残り')),
        dict(id='pad_thin', title='腹が巻き上がっている馬は栄養不足で消し',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'too_thin', '細すぎ')),
        dict(id='pad_tomo', title='トモに張りがあり外側を歩く馬は絶好調',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'tomo_tight', 'トモが張る')),
        dict(id='pad_inner_walk', title='パドックの内側を力なく歩く馬は気合不足',
             category='パドック系', verdict=U,
             note='パドック台帳の観察が必要',
             match=_tag_m('paddock_tags', 'donadona', '内側・引かれて歩く')),
        dict(id='tr_head_high', title='調教で頭が高い走法はキレが削がれる',
             category='調教系', verdict=U,
             note='調教観察が必要',
             match=_tag_m('training_tags', 't_form_bad', 'フォーム乱れ（頭高い含む）')),
        dict(id='tr_decel', title='追い切りが減速ラップの馬はスタミナ不足',
             category='調教系', verdict=U,
             note='調教観察が必要',
             match=_tag_m('training_tags', 't_decel_lap', '減速ラップ')),
        dict(id='tr_light', title='使い詰めで調教が軽い馬は失速する',
             category='調教系', verdict=U,
             note='調教観察が必要',
             match=_tag_m('training_tags', 't_lighter', 'いつもより軽い調整')),
        dict(id='tr_ippai', title='追い切りは一杯だから良く、馬なりだから悪い',
             category='調教系', verdict=R,
             note='検証2026-08(JRDB CHA2025本追切): 追切種類 一杯n=7,914で残差-0.2pp z-0.9、馬なりn=25,612で+0.1pp z1.0。負荷の強弱は完全に織込み済みで効果なし',
             match=_tag_m('training_tags', 't_harder', 'いつもより強い負荷')),
        dict(id='tr_fast_clock', title='調教タイムは速ければ速いほど調子が良い',
             category='調教系', verdict=U,
             note='時計の速さだけでは判定しない。観察が必要',
             match=_tag_m('training_tags', 't_easy_fast', '馬なりで好時計')),
        dict(id='skip_news_honmei', title='新聞でグリグリ本命の人気馬には逆らうな',
             category='人気系', verdict=U,
             note='他社の印は出馬表に無いので判定できない',
             match=_always_skip),
        dict(id='skip_ichi_shock', title='前走逃げられなかった馬が今回逃げる位置取りショックは買い',
             category='展開系', verdict=R,
             note='ショッカー系は事前条件だけだとエッジ消滅。今回の位置は出走前には分からない',
             match=_always_skip),
        dict(id='skip_nf_layoff', title='ノーザンファーム外厩の中9週以上・1番人気は買い',
             category='ローテ系', verdict=R,
             note='検証2026-08(JRDB KYI2025): NF外厩&中9週&1番人気 n=359で勝率33.4%(非NF対照33.9%)・複勝残差+0.3pp z0.3。資料の36.6%vs29.9%は再現せず。全人気では残差-1.4pp z-4.6と逆方向',
             match=_always_skip),
        dict(id='skip_odds_crash', title='締め切り直前にオッズが急落した馬は買い',
             category='人気系', verdict=U,
             note='2026-08〜スキャナーのオッズ記録に5分前/直前/最終のphase付き蓄積を開始。データが貯まれば検証可能',
             match=_always_skip),
        dict(id='skip_morning_drop', title='朝一1番人気→直前4番人気以下は買い',
             category='人気系', verdict=U,
             note='2026-08〜朝一/直前のphase付き記録を開始。データが貯まれば検証可能',
             match=_always_skip),
        dict(id='skip_kikyo', title='レース11〜13日前の最短帰厩でラスト1Fが速い馬は勝負',
             category='調教系', verdict=U,
             note='帰厩日はJRDB KYI(入厩年月日)で検証可能。2026-08検証: 11-13日帰厩 n=1,346で複勝残差-0.8pp z-1.8。CYB追切指数上位半分の精緻化(全年)でもn=751で-1.1pp z-1.9と負方向。jravan生時計版(+1.0pp)とは符号不一致で採用根拠なし。標本不足で却下基準にも未達のため保留',
             match=_always_skip),
        dict(id='skip_wood', title='美浦ウッド11.3秒以下／栗東坂路52.7-12.2は上位争い',
             category='調教系', verdict=U,
             note='検証2026-08(JRDB CHA2025): 栗東坂路52.7-12.2はholdout +4.2pp z6.3で強有意だったが、jravan代理検証のrecent(2026.1-6)で-3.1pp z-2.8に反転。生時計は馬場未補正のため2025馬場偏りの疑い。美浦ウッド11.3も1H+0.6/2H+2.4で不安定。採用不可',
             match=_always_skip),
        dict(id='skip_gyakute', title='直線で逆手前の馬はピークアウトで消し',
             category='調教系', verdict=U,
             note='ダートは芝の約6倍(20.2%)という俗説。手前は映像が無いと判定できない',
             match=_always_skip),
        dict(id='skip_prep', title='G1を見据えた前哨戦の実績馬は1番人気でも飛ぶ',
             category='ローテ系', verdict=U,
             note='8割仕上げの叩き台、という俗説。「叩き台」かどうかは出馬表だけでは分からない',
             match=_always_skip),
        dict(id='skip_estrus', title='春先に発情した牝馬は鞭が届かず大敗する',
             category='性別系', verdict=U,
             note='クラシックのフケ、という俗説。パドックやレース中の観察が必要',
             match=_always_skip),
        dict(id='skip_oikiri_score', title='調教採点50点未満は馬券に絡まない',
             category='調教系', verdict=U,
             note='46点以下は消し、という俗説。採点は新聞紙面データで、JRDBにも無い（CYB調教評価◎○△は2025実データで充足0%、CHAは指数と時刻のみ）。JRDBでは検証不可',
             match=_always_skip),
        dict(id='skip_sibling', title='母や兄姉の新馬実績が良い馬は初戦から動く',
             category='血統系', verdict=R,
             note='複勝率の差は人気で説明できる（sibling_debut）。出馬表から兄姉成績は取れない',
             match=_always_skip),
        dict(id='skip_dam_age', title='母が16歳以上の高齢出産馬は回収が落ちる',
             category='血統系', verdict=R,
             note='期間内ベースだと効果なし（dam_age）。母の年齢は出馬表から取れない',
             match=_always_skip),
        dict(id='skip_body_type', title='長腹短背の体型の馬はよく走る',
             category='パドック系', verdict=U,
             note='体型は観察が無いと判定できない',
             match=_always_skip),
    ])


CATALOG = _rules()


def catalog_by_id():
    return {r['id']: r for r in CATALOG}


def catalog_grouped():
    """カテゴリごとの収録一覧（ページの全件表示用）。"""
    out = {}
    for r in CATALOG:
        out.setdefault(r['category'], []).append(r)
    return out


def match_one(rule, horse):
    try:
        detail = rule['match'](horse)
    except Exception:
        return None
    sign = rule.get('sign', SIGN_POS)
    if isinstance(detail, tuple) and len(detail) == 2 and detail[0] in (SIGN_POS, SIGN_NEG):
        sign, detail = detail
    if detail == SKIP:
        return {
            'id': rule['id'],
            'title': rule['title'],
            'category': rule['category'],
            'verdict': rule['verdict'],
            'note': rule['note'],
            'sign': sign,
            'confidence': rule.get('confidence', CONF_NORMAL),
            'weight': rule.get('weight', 1.0),
            'skip': True,
        }
    if not detail:
        return None
    return {
        'id': rule['id'],
        'title': rule['title'],
        'category': rule['category'],
        'verdict': rule['verdict'],
        'note': rule['note'],
        'sign': sign,
        'confidence': rule.get('confidence', CONF_NORMAL),
        'weight': rule.get('weight', 1.0),
        'detail': detail,
    }


def fmt_signed(n, zero='0'):
    """+7 / −2 / 0。表示用。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return zero
    if n > 0:
        return f'＋{n}'
    if n < 0:
        return f'−{abs(n)}'
    return zero


def evaluate_horse(horse, catalog=None):
    """1頭分。hits=該当, misses=非該当, skips=データ不足で判定しない。
    総合 = プラス材料の個数 − マイナス材料の個数（重みは今は使わない）。"""
    cat = catalog if catalog is not None else CATALOG
    hits, misses, skips = [], [], []
    for rule in cat:
        m = match_one(rule, horse)
        if m is None:
            misses.append({
                'id': rule['id'],
                'title': rule['title'],
                'category': rule['category'],
                'verdict': rule['verdict'],
                'note': rule['note'],
                'sign': rule.get('sign', SIGN_POS),
            })
        elif m.get('skip'):
            skips.append(m)
        else:
            hits.append(m)
    n_e = sum(1 for x in hits if x['verdict'] == VERDICT_EFFECTIVE)
    n_r = sum(1 for x in hits if x['verdict'] == VERDICT_REJECTED)
    n_u = sum(1 for x in hits if x['verdict'] == VERDICT_UNVERIFIED)
    n_pos = sum(1 for x in hits if x.get('sign', SIGN_POS) > 0)
    n_neg = sum(1 for x in hits if x.get('sign', SIGN_POS) < 0)
    score = n_pos - n_neg
    by_cat = {}
    for x in hits:
        by_cat[x['category']] = by_cat.get(x['category'], 0) + 1
    return {
        'umaban': horse.get('umaban'),
        'name': horse.get('name'),
        'ninki': horse.get('ninki'),
        'odds': horse.get('odds'),
        'hits': hits,
        'misses': misses,
        'skips': skips,
        'n_total': len(hits),
        'n_pos': n_pos,
        'n_neg': n_neg,
        'score': score,
        'n_effective': n_e,
        'n_rejected': n_r,
        'n_unverified': n_u,
        'n_skip': len(skips),
        'by_category': by_cat,
        'hits_pos': [x for x in hits if x.get('sign', SIGN_POS) > 0],
        'hits_neg': [x for x in hits if x.get('sign', SIGN_POS) < 0],
        'balance': f"＋{n_pos} / −{n_neg} → {fmt_signed(score)}",
        'fire': fire_marks(len(hits)),
    }


def evaluate_race(df, race_id='', meta=None, enrich=True, catalog=None):
    snaps = build_snaps(df, race_id=race_id, meta=meta, enrich=enrich)
    results = [evaluate_horse(h, catalog=catalog) for h in snaps]
    # 総合の既定順。同じ差し引きならマイナスが少ない方を上に。
    results.sort(key=lambda x: (-x['score'], x['n_neg'], -x['n_pos'], x['umaban'] or 0))
    for i, r in enumerate(results, 1):
        r['rank'] = i
    return results


def top_n(results, key, n=5, min_val=1):
    """key の多い順。min_val 未満はランキングから外す（0個の馬を載せない）。"""
    ranked = sorted(results, key=lambda x: (-(x.get(key) or 0), x.get('umaban') or 0))
    if min_val is not None:
        ranked = [x for x in ranked if (x.get(key) or 0) >= min_val]
    return ranked[:n]


def top_pos(results, n=5):
    """買い材料として語られる俗説の該当数が多い順。"""
    return top_n(results, 'n_pos', n=n, min_val=1)


def top_neg(results, n=5):
    """消し・危険として語られる俗説の該当数が多い順。"""
    return top_n(results, 'n_neg', n=n, min_val=1)


def top_score(results, n=5):
    """総合（＋個数 − －個数）。同点ならマイナスが少ない方を上に。"""
    ranked = sorted(
        results,
        key=lambda x: (-x['score'], x['n_neg'], -x['n_pos'], x['umaban'] or 0),
    )
    return ranked[:n]


def filter_effective_results(results):
    """判定が『実戦で使う』（VERDICT_EFFECTIVE）の俗説のみで再集計した結果リスト。

    folklore_hunter.py の「実戦のみ」ランキングと同一。
    """
    eff_results = []
    for r in (results or []):
        hits_eff = [h for h in (r.get('hits') or []) if h.get('verdict') == VERDICT_EFFECTIVE]
        n_pos = sum(1 for h in hits_eff if h.get('sign', SIGN_POS) > 0)
        n_neg = sum(1 for h in hits_eff if h.get('sign', SIGN_POS) < 0)
        score = n_pos - n_neg
        by_cat = {}
        for x in hits_eff:
            cat = x.get('category', 'その他')
            by_cat[cat] = by_cat.get(cat, 0) + 1
        eff_r = dict(r)
        eff_r.update({
            'hits': hits_eff,
            'hits_pos': [h for h in hits_eff if h.get('sign', SIGN_POS) > 0],
            'hits_neg': [h for h in hits_eff if h.get('sign', SIGN_POS) < 0],
            'n_total': len(hits_eff),
            'n_pos': n_pos,
            'n_neg': n_neg,
            'score': score,
            'n_effective': len(hits_eff),
            'n_rejected': 0,
            'n_unverified': 0,
            'by_category': by_cat,
            'balance': f"＋{n_pos} / −{n_neg} → {fmt_signed(score)}",
        })
        eff_results.append(eff_r)
    return eff_results


def _myth_ranking_sets(results, eff_results=None):
    """4つの対象TOP5に載った馬番set。マイナスTOP5は含めない。"""
    if eff_results is None:
        eff_results = filter_effective_results(results)
    def _uma_set(ranked):
        out = set()
        for r in ranked or []:
            um = _i(r.get('umaban'))
            if um is not None:
                out.add(um)
        return out
    return {
        'positive': _uma_set(top_pos(results, 5)),
        'composite': _uma_set(top_score(results, 5)),
        'practical_positive': _uma_set(top_pos(eff_results, 5)),
        'practical_composite': _uma_set(top_score(eff_results, 5)),
    }


def myth_info_for_umaban(umaban, sets_dict):
    """1頭分の俗説TOP5掲載内訳と count(0〜4)。"""
    um = _i(umaban)
    if um is None or not sets_dict:
        return None
    positive = um in sets_dict.get('positive', set())
    composite = um in sets_dict.get('composite', set())
    practical_positive = um in sets_dict.get('practical_positive', set())
    practical_composite = um in sets_dict.get('practical_composite', set())
    return {
        'positive': positive,
        'composite': composite,
        'practical_positive': practical_positive,
        'practical_composite': practical_composite,
        'count': int(positive) + int(composite) + int(practical_positive) + int(practical_composite),
    }


def build_myth_count_map(results):
    """俗説TOP5掲載数(0〜4)を馬番→myth_infoで返す。

    evaluate_race が None のときは None（取得失敗。0と区別）。
    空リストのときも None（ランキング生成不可）。
    """
    if results is None or not results:
        return None
    sets_dict = _myth_ranking_sets(results)
    out = {}
    for r in results:
        um = _i(r.get('umaban'))
        if um is None:
            continue
        info = myth_info_for_umaban(um, sets_dict)
        if info is not None:
            out[um] = info
    return out


HUNTER_CAPTURED_TIERS = frozenset({'🎯精鋭', '🕸️広域網'})
SIGNAL_NINKI_MIN = 6   # 穴馬ハンターと同じ「6番人気以下」
SIGNAL_SCORE_MIN = 5   # 総合がこれ以上だけ通知する
SIGNAL_LIMIT = 3       # 買い候補を増やさないための上限


def captured_umabans(vh_tier_map):
    """穴馬ハンターの精鋭・広域網に出た馬番。"""
    out = set()
    for u, t in (vh_tier_map or {}).items():
        if t in HUNTER_CAPTURED_TIERS:
            n = _i(u)
            if n is not None:
                out.add(n)
    return out


def folklore_signals(results, captured, ninki_min=SIGNAL_NINKI_MIN,
                     score_min=SIGNAL_SCORE_MIN, limit=SIGNAL_LIMIT):
    """穴馬ハンター未捕捉 × 人気薄 × 俗説反応が強い馬。発見用。買いリストには入れない。"""
    captured = {_i(u) for u in (captured or set())}
    captured.discard(None)
    hits = []
    for r in results or []:
        um = _i(r.get('umaban'))
        try:
            nk = int(r.get('ninki'))
        except (TypeError, ValueError):
            continue
        if um is None or nk < ninki_min:
            continue
        if (r.get('score') or 0) < score_min:
            continue
        if um in captured:
            continue
        hits.append(r)
    hits.sort(key=lambda x: (-x['score'], x['n_neg'], -x['n_pos'], x.get('umaban') or 0))
    return hits[:limit]


def umaban_mark(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n or '')
    if 1 <= n <= 20:
        return chr(0x245F + n)
    return f"{n}番"


def race_tags(meta, n_horses, surface=''):
    """レース全体の俗説（全馬に足すと順位が無意味になるので別表示）。"""
    tags = []
    meta = meta or {}
    if meta.get('is_handicap'):
        tags.append('ハンデ戦は荒れやすい、という俗説（ハンデ＋頭数は実戦の荒れ材料）')
    if n_horses and int(n_horses) >= 16:
        tags.append('フルゲートは荒れやすい、という俗説（16頭は実戦の荒れ材料）')
    is_dirt = 'ダ' in str(surface or '')
    is_turf = '芝' in str(surface or '')
    is_maiden, is_open, _cr = race_kind(meta)
    baba = str(meta.get('condition') or '')
    wet = baba in ('稍重', '重', '不良')
    date_val = str(meta.get('date_val') or '')
    digits = ''.join(ch for ch in date_val if ch.isdigit())
    month = int(digits[4:6]) if len(digits) >= 6 else None
    season = season_of(month)

    if is_dirt:
        tags.append(
            '【ダート】外枠から先行できる馬が有利で差しは届きにくい／休み明けは割引／夏牝は通用しない、という俗説'
            '（外枠×人気上位は実戦の軸材料）'
        )
        if wet:
            tags.append('【ダート】稍重・重は時計が速くなる、という俗説（芝とは逆。クッションが締まる）')
    elif is_turf:
        if wet:
            tags.append(
                '【芝】道悪は時計が遅く、不良は前残り、という俗説'
                '（芝の重・不良×1番人気は実戦の危険材料）'
            )
        if month in (7, 8, 9):
            tags.append('【芝】7〜9月は牝馬が走りやすい、という俗説（残差では売れすぎ）')
    elif wet:
        tags.append('雨や道悪だとレースは荒れやすい、という俗説')

    if is_open:
        tags.append(
            '【オープン・重賞】中穴（4〜6番人気）が飛びやすい／逃げはマークされる／前哨戦の本命は飛ぶ、という俗説'
        )
    if meta.get('is_fillies'):
        tags.append('牝馬限定戦')
        if season == '冬':
            tags.append('【牝馬限定】冬は冬毛で人気馬が凡走しやすい、という俗説（1番人気は実戦の注意）')
        else:
            tags.append('【牝馬限定】春先の発情や使い減りで集中力を落とす、という俗説')
    if is_maiden:
        tags.append(
            '【新馬】1番人気と調教（坂路の加速ラップ／ウッド11.3秒）が物を言う、という俗説'
            '（未検証。調教時計は自動判定していない）'
        )
    return tags
