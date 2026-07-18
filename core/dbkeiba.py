# -*- coding: utf-8 -*-
"""db-keiba.com（パンダズ競馬）の騎手・条件別成績スクレイパー＋条件重複カウント。

目的: 騎手ごとの『買い条件』(回収率が高い条件)・『消し条件』(低い条件)を取得し、
      今日のレース条件と何個重複するかを combo と同じ発想で表示する。
      **表示・参考専用**。回収率は同サイトの集計値(2021-2025)で、当プロジェクトの
      leak-free検証を通ったものではない([[verified_*]]台帳とは別物として扱う)。

アクセス方針(アクセス拒否対策):
  - robots.txt確認済み: /wp-admin/ 以外は許可(WordPress静的ページ・2026-07-14時点)。
  - 通常のブラウザUAを名乗り、リクエスト間に REQUEST_INTERVAL 秒空ける。
  - 取得結果はディスクにキャッシュ(騎手ページ=CACHE_TTL_DAYS日)。サイトは週1更新なので
    実質「1騎手につき2週間に1回」しかアクセスしない。
  - 失敗時はリトライせず None を返す(呼び元は'-'表示)。連打で負荷を掛けない。

データ構造(騎手ページ・静的HTML):
  h2見出し「◯◯騎手の人気別成績・回収率（2021-2025）」の直後に
  <table>: [ラベル, 1着, 2着, 3着, 着外, 出走, 勝率, 連対, 複勝, 単回, 複回]
  カテゴリ: 人気別/クラス別/重賞グレード別/性別/コース別/枠順別(芝・ダ)/脚質別(芝・ダ)/
            競馬場別(芝・ダ)/距離別(芝・ダ)/調教師別/馬主別/血統別(芝・ダ)
  ページ内タブ「2021-2025」「2026」のうち、標本の大きい複数年側だけを使う。
"""
import json
import os
import re
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_ROOT, 'data', 'dbkeiba')
MAP_PATH = os.path.join(CACHE_DIR, 'jockey_map.json')

BASE = 'https://db-keiba.com'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
REQUEST_INTERVAL = 2.0      # リクエスト間隔(秒)。サイトに優しく
CACHE_TTL_DAYS = 14         # 騎手ページのキャッシュ寿命(サイトは週1更新)
MAP_TTL_DAYS = 30           # 騎手一覧のキャッシュ寿命

# 条件の採用基準。サイトの注記=「全買いで回収率80%に収束するよう計算」→80%が損益分岐。
MIN_RUNS = 20               # 最低標本数(これ未満の行はノイズとして無視)
BUY_WIN_ROI = 100.0         # 買い条件: 単回がこれ以上
BUY_FUKU_ROI = 95.0         # または複回がこれ以上
FADE_FUKU_ROI = 55.0        # 消し条件: 複回がこれ以下(単回はブレるので複回で判定)

_last_fetch = [0.0]


def _polite_get(url):
    """間隔を空けて1回だけGET。失敗はNone(リトライしない=負荷を掛けない)。"""
    import requests
    wait = REQUEST_INTERVAL - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    try:
        r = requests.get(url, headers={'User-Agent': UA}, timeout=25)
        _last_fetch[0] = time.time()
        if r.status_code != 200:
            return None
        r.encoding = 'utf-8'
        return r.text
    except Exception:
        _last_fetch[0] = time.time()
        return None


def _load_json(path, ttl_days):
    try:
        if not os.path.exists(path):
            return None
        if (time.time() - os.path.getmtime(path)) > ttl_days * 86400:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:
        pass


def _norm_name(nm):
    """騎手名の正規化: 空白/全角空白除去。『Ｃ．ルメール』→『ルメール』のような姓抽出も。"""
    s = re.sub(r'[\s　]', '', str(nm or ''))
    s = s.replace('▲', '').replace('△', '').replace('☆', '').replace('◇', '').replace('★', '')
    return s


def _family_key(nm):
    """外国人騎手『Ｃ．ルメール』とアプリ側『ルメール』を突き合わせる緩いキー。"""
    s = _norm_name(nm)
    s = re.sub(r'^[Ａ-ＺA-Z]\．?', '', s)   # 頭文字イニシャルを除去
    return s


def get_jockey_map(allow_fetch=True):
    """{騎手名(正規化): slug} を返す。キャッシュ優先。"""
    m = _load_json(MAP_PATH, MAP_TTL_DAYS)
    if m:
        return m
    if not allow_fetch:
        return _load_json_ignore_ttl(MAP_PATH) or {}
    html = _polite_get(f'{BASE}/jockey-main/')
    if not html:
        return _load_json_ignore_ttl(MAP_PATH) or {}
    # slugは 'jockey-samejima' だけでなく 'jockey-osuke-tayama'(名-姓)形式もある。
    # 文字クラスに '-' が無いと後者が途中で切れてマッチせず、その騎手がマップから丸ごと
    # 落ちる(2026-07に実測: 田山旺佑/佐々木大輔/鮫島良太など20名が欠落していた)。
    pairs = re.findall(
        r'href="https?://db-keiba\.com/(jockey-[a-z0-9_-]+)/"[^>]*>([^<]+)<', html)
    out = {}
    for slug, nm in pairs:
        nm = _norm_name(nm)
        # 個人ページ以外(一覧/ランキング等)を除外。ランキング見出しは長文なので len>12 で落ちる。
        if (slug in ('jockey-main', 'jockey-new') or slug.startswith('jockey-popularity')
                or not nm or len(nm) > 12):
            continue
        out.setdefault(nm, slug)
    if out:
        _save_json(MAP_PATH, out)
    return out


def _load_json_ignore_ttl(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _is_subseq(a, b):
    """a が b の部分列か(『鮫島駿』⊂『鮫島克駿』)。jockey_jv.resolve_jockey_name と同じ発想。"""
    it = iter(b)
    return all(ch in it for ch in a)


def resolve_slug(jockey_name, jmap=None):
    """アプリの騎手名(『ルメール』等・記号/半角混在)から slug を引く。"""
    jmap = jmap or get_jockey_map(allow_fetch=False)
    if not jmap:
        return None
    key = _norm_name(jockey_name)
    if key in jmap:
        return jmap[key]
    fam = _family_key(key)
    if not fam:
        return None
    for nm, slug in jmap.items():
        if _family_key(nm) == fam or nm.endswith(fam) or fam.endswith(nm):
            return slug
    # 部分一致(姓のみ表記対応): アプリ『戸崎圭』 vs サイト『戸崎圭太』
    cands = [slug for nm, slug in jmap.items() if nm.startswith(fam[:2]) and
             (fam in nm or nm in fam)]
    if len(cands) == 1:
        return cands[0]
    # 中間文字が省略された略記の救済: アプリ『鮫島駿』 vs サイト『鮫島克駿』。
    # 誤爆防止に 先頭/末尾一致・文字数差<=2・候補が一意 のときだけ採用
    # (『鮫島良太』は末尾が違うので候補に入らない)。jockey_jv と同じガード。
    if len(fam) >= 2:
        fz = [slug for nm, slug in jmap.items()
              if len(nm) > len(fam) and len(nm) - len(fam) <= 2
              and nm[0] == fam[0] and nm[-1] == fam[-1] and _is_subseq(fam, nm)]
        if len(fz) == 1:
            return fz[0]
    return None


# ── ページ解析 ──

_HEAD_RE = re.compile(r'<h2[^>]*>([^<]*?騎手の([^（<]+?)成績・回収率（([^）]+)）)</h2>', re.S)
_H3_RE = re.compile(r'<h3[^>]*>\s*(芝コース|ダートコース)\s*</h3>')
_TABLE_RE = re.compile(r'<table[^>]*>(.*?)</table>', re.S)
_TR_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
_TD_RE = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.S)


def _strip(html):
    return re.sub(r'<[^>]+>', '', html).replace('&nbsp;', ' ').strip()


def _parse_table(seg):
    """table HTML → [{'label','runs','win_roi','fuku_roi','fukusho'}]"""
    rows = []
    for tr in _TR_RE.findall(seg):
        cells = [_strip(c) for c in _TD_RE.findall(tr)]
        if len(cells) < 11 or cells[0] in ('', '着別度数'):
            continue
        try:
            rows.append({
                'label': cells[0],
                'runs': int(float(cells[5])),
                'fukusho': float(cells[8]),
                'win_roi': float(cells[9]),
                'fuku_roi': float(cells[10]),
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_summary(html):
    """ページ末尾の『傾向まとめ』(サイト精選の買い/消し条件)を解析する。

    構造: <h3>過小評価条件（買い条件）</h3> ※出走件数100件以上、勝率5%以上
          「回収率100%以上！」「回収率90%以上！」の階層 → <ul><li>ラベル （単勝回収率N%）</li>
          <h3>過大評価条件（消し条件）</h3> → 「回収率60%未満」「回収率70%未満」の階層
    戻り: {'buy': [{'label','roi','tier'}..], 'fade': [...]} / 見つからなければ None。
    """
    i = html.find('傾向まとめ')
    if i < 0:
        return None
    seg = html[i:]
    m_end = re.search(r'<h2', seg[100:])
    if m_end:
        seg = seg[:100 + m_end.start()]
    out = {'buy': [], 'fade': []}
    for part in re.split(r'<h3[^>]*>', seg):
        head = _strip(part[:80])
        if '過小評価' in head:
            side = 'buy'
        elif '過大評価' in head:
            side = 'fade'
        else:
            continue
        for tm in re.finditer(r'回収率(\d+)%(以上|未満)(.*?)(?=回収率\d+%(?:以上|未満)|\Z)',
                              part, re.S):
            tier = f"{tm.group(1)}%{tm.group(2)}"
            ul = re.search(r'<ul>(.*?)</ul>', tm.group(3), re.S)
            if not ul:
                continue
            for li in re.findall(r'<li[^>]*>(.*?)</li>', ul.group(1), re.S):
                txt = _strip(li)
                if not txt or txt == 'なし':
                    continue
                mm = re.match(r'(.+?)\s*[（(]単勝回収率(\d+)%[）)]', txt)
                if not mm:
                    continue
                out[side].append({'label': re.sub(r'[\s　]+', '', mm.group(1)),
                                  'roi': int(mm.group(2)), 'tier': tier})
    return out if (out['buy'] or out['fade']) else None


def parse_jockey_page(html):
    """騎手ページHTML → {'jockey': 名前, 'period': '2021-2025',
                          'tables': {カテゴリ名(+_芝/_ダ): [rows]}}
    複数年タブ(2021-2025等)のカテゴリだけを採用(単年タブはラベル重複で上書きしない)。"""
    tables = {}
    jockey = ''
    period = ''
    heads = list(_HEAD_RE.finditer(html))
    for i, h in enumerate(heads):
        cat = h.group(2).strip().rstrip('の')
        per = h.group(3).strip()
        if not jockey:
            m = re.match(r'(.+?)騎手の', h.group(1))
            jockey = m.group(1) if m else ''
        if '-' not in per:            # 単年タブ(例: 2026)はスキップ=複数年だけ使う
            continue
        period = period or per
        end = heads[i + 1].start() if i + 1 < len(heads) else len(html)
        seg = html[h.end():end]
        subs = list(_H3_RE.finditer(seg))
        if subs:                       # 芝/ダートのサブ見出し付きカテゴリ
            for j, s in enumerate(subs):
                send = subs[j + 1].start() if j + 1 < len(subs) else len(seg)
                tm = _TABLE_RE.search(seg[s.end():send])
                if tm:
                    suf = '芝' if '芝' in s.group(1) else 'ダ'
                    key = f'{cat}_{suf}'
                    if key not in tables:
                        tables[key] = _parse_table(tm.group(1))
        else:
            tm = _TABLE_RE.search(seg)
            if tm and cat not in tables:
                tables[cat] = _parse_table(tm.group(1))
    return {'jockey': jockey, 'period': period, 'tables': tables,
            'summary': _parse_summary(html)}


def get_jockey_data(jockey_name, allow_fetch=True):
    """騎手名 → 解析済みデータ(キャッシュ優先)。取れなければ None。"""
    slug = resolve_slug(jockey_name, get_jockey_map(allow_fetch=allow_fetch))
    if not slug:
        return None
    path = os.path.join(CACHE_DIR, f'{slug}.json')
    d = _load_json(path, CACHE_TTL_DAYS)
    if d and 'summary' not in d and allow_fetch:
        d = None                      # 旧形式キャッシュ(傾向まとめ未収録)は再取得して更新
    if d:
        return d
    if not allow_fetch:
        return _load_json_ignore_ttl(path)
    html = _polite_get(f'{BASE}/{slug}/')
    if not html:
        return _load_json_ignore_ttl(path)
    d = parse_jockey_page(html)
    if d.get('tables'):
        _save_json(path, d)
        return d
    return None


# ── 買い/消し条件の抽出とレース条件マッチ ──

def extract_conditions(data):
    """解析済みデータ → {'buy': [cond..], 'fade': [cond..]}

    サイトの『傾向まとめ』(過小評価/過大評価条件・出走100件以上/勝率5%以上でサイト側が精選)が
    あればそれを正とする(src='summary')。無いページのみテーブルから自前閾値で抽出(src='table')。
    """
    smry = data.get('summary')
    if smry:
        def _mk(c, side):
            arrow = '' if side == 'buy' else '⚠'
            return {'src': 'summary', 'label': c['label'], 'tier': c.get('tier', ''),
                    'text': f"{arrow}{c['label']}(単回{c['roi']}%)"}
        return {'buy': [_mk(c, 'buy') for c in smry.get('buy', [])],
                'fade': [_mk(c, 'fade') for c in smry.get('fade', [])]}
    buy, fade = [], []
    for cat, rows in (data.get('tables') or {}).items():
        # 年別は「条件」ではないので対象外。馬主別はアプリ側に馬主情報が無いので対象外
        if cat.startswith('年別') or cat.startswith('全体') or cat.startswith('馬主'):
            continue
        for r in rows:
            if r['runs'] < MIN_RUNS or r['label'] in ('合計', '全体'):
                continue
            c = {'src': 'table', 'cat': cat, 'label': r['label'], 'runs': r['runs'],
                 'win_roi': r['win_roi'], 'fuku_roi': r['fuku_roi'],
                 'text': f"{r['label']}(単回{r['win_roi']:.0f}%/複回{r['fuku_roi']:.0f}%"
                         f"・{r['runs']}走)"}
            if r['win_roi'] >= BUY_WIN_ROI or r['fuku_roi'] >= BUY_FUKU_ROI:
                buy.append(c)
            elif r['fuku_roi'] <= FADE_FUKU_ROI:
                fade.append(c)
    return {'buy': buy, 'fade': fade}


_VENUES = ('東京', '中山', '阪神', '京都', '中京', '新潟', '福島', '小倉', '札幌', '函館')
_LEGS = ('逃げ', '先行', '差し', '追込')


def _summary_hits(label, ctx):
    """『傾向まとめ』の複合ラベル(例: ダート1枠/福島ダートコース/ダートコース先行/芝短距離)を
    今日のレース条件と照合する。判定できないラベルはFalse(数えない)。"""
    lb = str(label or '')
    surf = str(ctx.get('surface') or '')
    surf_c = '芝' if '芝' in surf else ('ダ' if surf else '')

    def _surf_ok(prefix):
        return (prefix == '芝' and surf_c == '芝') or (prefix == 'ダート' and surf_c == 'ダ')

    try:
        m = re.fullmatch(r'(\d+)人気', lb)
        if m:
            return bool(ctx.get('ninki')) and int(ctx['ninki']) == int(m.group(1))
        m = re.fullmatch(r'(芝|ダート)(\d)枠', lb)
        if m:
            return _surf_ok(m.group(1)) and bool(ctx.get('waku')) \
                and int(ctx['waku']) == int(m.group(2))
        m = re.fullmatch(r'(.+?)(芝|ダート)コース(逃げ|先行|差し|追込)?', lb)
        if m and (m.group(1) in _VENUES or not m.group(1)):
            if not _surf_ok(m.group(2)):
                return False
            if m.group(1) and str(ctx.get('venue') or '') != m.group(1):
                return False
            if m.group(3):
                return str(ctx.get('legtype') or '') == m.group(3)
            return bool(m.group(1))     # 場+コースのみ(例: 福島ダートコース)
        m = re.fullmatch(r'(芝|ダート)コース(逃げ|先行|差し|追込)', lb)
        if m:
            return _surf_ok(m.group(1)) and str(ctx.get('legtype') or '') == m.group(2)
        m = re.fullmatch(r'(芝|ダート)(短距離|中距離|長距離)', lb)
        if m:
            return _surf_ok(m.group(1)) and \
                _dist_band(ctx.get('dist'), surf_c) == m.group(2)
        if lb in ('新馬', '未勝利', '1勝クラス', '2勝クラス', '3勝クラス'):
            cls = str(ctx.get('class') or '')
            return bool(cls) and lb in cls
        if lb in ('重賞・OP', 'オープン'):
            return bool(re.search(r'オープン|OP|G[1-3ⅠⅡⅢ]|リステッド',
                                  str(ctx.get('class') or '')))
        if lb in ('G1', 'G2', 'G3', 'GⅠ', 'GⅡ', 'GⅢ'):
            g = lb.replace('Ⅰ', '1').replace('Ⅱ', '2').replace('Ⅲ', '3')
            return str(ctx.get('grade') or '').upper() == g
        if lb in ('セン馬', '牝馬', '牡馬'):
            return bool(ctx.get('sex')) and lb.startswith(str(ctx['sex'])[:1])
        # 残り=人名(調教師 or 種牡馬)。どちらかに含まれていれば一致
        nm = _norm_name(lb)
        if len(nm) >= 2:
            t = _norm_name(ctx.get('trainer'))
            s = _norm_name(ctx.get('sire'))
            return (bool(t) and (nm in t or t in nm)) or \
                   (bool(s) and s not in ('-', 'nan') and (nm in s or s in nm))
    except (TypeError, ValueError):
        return False
    return False


def _dist_of(label):
    m = re.search(r'(\d{3,4})m', label)
    return int(m.group(1)) if m else None


def _dist_band(dist, surf_c):
    """距離→サイトの距離帯ラベル。ページ注記より
    芝: 短距離〜1600 / 中距離1700-2200 / 長距離2300〜
    ダ: 短距離〜1400 / 中距離1600-2000 / 長距離2100〜"""
    try:
        d = int(dist)
    except (TypeError, ValueError):
        return None
    if surf_c == '芝':
        return '短距離' if d <= 1600 else ('中距離' if d <= 2200 else '長距離')
    if surf_c == 'ダ':
        return '短距離' if d <= 1400 else ('中距離' if d <= 2000 else '長距離')
    return None


def _cond_hits(cond, ctx):
    """1条件が今日のレース条件(ctx)に合致するか。判定できないカテゴリはFalse(=数えない)。
    ctx: {'ninki','surface'('芝'/'ダ'),'dist','waku','venue','sex'('牡'/'牝'/'セ'),
          'class'(レース条件名),'grade'('G1'等),'trainer','sire'}"""
    cat, label = cond['cat'], cond['label']
    surf = str(ctx.get('surface') or '')
    surf_c = '芝' if '芝' in surf else ('ダ' if surf else '')
    # 芝/ダ付きカテゴリはコース一致が前提
    if cat.endswith('_芝') and surf_c != '芝':
        return False
    if cat.endswith('_ダ') and surf_c != 'ダ':
        return False
    base = cat.split('_')[0]
    try:
        if base.startswith('人気'):
            m = re.match(r'(\d+)人気', label)
            return bool(m and ctx.get('ninki') and int(ctx['ninki']) == int(m.group(1)))
        if base.startswith('クラス'):
            cls = str(ctx.get('class') or '')
            if not cls:
                return False
            if label == '重賞・OP':
                return bool(re.search(r'オープン|OP|G[1-3ⅠⅡⅢ]|リステッド|\bL\b', cls))
            return label in cls or cls in label
        if base.startswith('重賞'):
            g = str(ctx.get('grade') or '')
            return bool(g) and (label.replace('Ⅰ', '1').replace('Ⅱ', '2').replace('Ⅲ', '3')
                                .upper().startswith(g.upper()))
        if base.startswith('性'):
            return bool(ctx.get('sex')) and label.startswith(str(ctx['sex']))
        if base.startswith('コース'):
            return bool(surf_c) and label.startswith(surf_c[:1])
        if base.startswith('枠順'):
            m = re.match(r'(\d)枠', label)
            return bool(m and ctx.get('waku') and int(ctx['waku']) == int(m.group(1)))
        if base.startswith('競馬場'):
            v = str(ctx.get('venue') or '')
            return bool(v) and (label.startswith(v) or v.startswith(label))
        if base.startswith('距離'):
            d = _dist_of(label)
            if d:                          # '芝1600m' 形式のラベル
                return bool(ctx.get('dist') and int(ctx['dist']) == d)
            band = _dist_band(ctx.get('dist'), surf_c)   # '短距離/中距離/長距離' 形式
            return bool(band) and label.startswith(band)
        if base.startswith('調教師'):
            t = _norm_name(ctx.get('trainer'))
            lb = _norm_name(label)
            return bool(t) and (lb in t or t in lb)
        if base.startswith('血統'):
            s = _norm_name(ctx.get('sire'))
            lb = _norm_name(label)
            return bool(s) and s not in ('-', 'nan') and (lb in s or s in lb)
        if base.startswith('脚質'):
            lg = str(ctx.get('legtype') or '')
            return bool(lg) and label.startswith(lg[:2])
    except (TypeError, ValueError):
        return False
    return False


def match_race(jockey_name, ctx, allow_fetch=True):
    """騎手×今日のレース条件 → {'buy':[text..], 'fade':[text..], 'found':bool}
    found=False はデータ未取得(地方/新人/サイト未収録)。"""
    d = get_jockey_data(jockey_name, allow_fetch=allow_fetch)
    if not d:
        return {'buy': [], 'fade': [], 'found': False}
    conds = extract_conditions(d)

    def _hit(c):
        return (_summary_hits(c['label'], ctx) if c.get('src') == 'summary'
                else _cond_hits(c, ctx))
    return {
        'buy': [c['text'] for c in conds['buy'] if _hit(c)],
        'fade': [c['text'] for c in conds['fade'] if _hit(c)],
        'found': True,
    }
