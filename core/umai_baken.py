# -*- coding: utf-8 -*-
"""ウマい馬券の買い目『形』観察。予想本文の転載はしない。

目的: 券種・点数・流し/通常・資金配分だけを見て、当アプリの検証済み
      playbook（D=3連複2点 / Cクロス多=3連複2-3-6 / Cクロス少=3連単2-4-7）
      とどこが近いかを数える。予想家の印・見解は保存しない。

アクセス方針（拒否対策）:
  - カレンダー横断や「もっとみる」自動巡回はしない。
  - 既定はディスクキャッシュ優先。同じURLは再取得しない。
  - 失敗したらリトライしない。403/429/ブロック文言で即停止。
  - 間隔は REQUEST_INTERVAL 秒＋ゆらぎ。Stealthy/Playwright は使わない。
  - 詳細ページは --max-details で上限（既定5）。
"""
from __future__ import annotations

import json
import os
import random
import re
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_ROOT, 'data', 'umai_baken')
INDEX_PATH = os.path.join(CACHE_DIR, 'shapes.jsonl')

YOSO_HOST = 'https://yoso.netkeiba.com'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
REQUEST_INTERVAL = 12.0
JITTER_SEC = 3.0

_KIND_RE = re.compile(
    r'(3連単|3連複|馬単|馬連|ワイド|単勝|複勝)'
    r'(?:[（(]([^）)]+)[）)])?'
)
_YOSO_ID_RE = re.compile(
    r'(?:[?&]id=|yoso_detail[^\"\'>\s]*[?&]id=)(\d{4,})',
    re.I,
)
_COMBO_RE = re.compile(
    r'(\d{1,2}(?:\s*[-−–ー~〜>＞]\s*\d{1,2}){1,2})'
)
_YEN_RE = re.compile(r'([0-9,]+)\s*円')
_WAYS_RE = re.compile(r'(\d+)\s*通り')
_AXIS_RE = re.compile(r'軸\s*([0-9\s]+)')
_AITE_RE = re.compile(r'相手\s*([0-9\s]+)')

_last_fetch = [0.0]
_stop_reason = [None]


def stopped():
    return _stop_reason[0]


def _ensure_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def cache_path(kind, key):
    safe = re.sub(r'[^0-9A-Za-z_]+', '', str(key))
    return os.path.join(CACHE_DIR, f'{kind}_{safe}.html')


def load_cache(kind, key):
    p = cache_path(kind, key)
    if not os.path.exists(p):
        return None
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return None


def save_cache(kind, key, html):
    if not html:
        return
    _ensure_dir()
    with open(cache_path(kind, key), 'w', encoding='utf-8') as f:
        f.write(html)


def list_url(race_id):
    return f'{YOSO_HOST}/?pid=race_yoso_list&race_id={race_id}'


def detail_url(yoso_id):
    return f'{YOSO_HOST}/?pid=yoso_detail&id={yoso_id}'


def _is_blocked(html, status=None):
    if status in (403, 429, 503):
        return True
    if not html or len(html) < 400:
        return True
    for tok in ('Access Denied', 'Forbidden', 'アクセス拒否',
                'しばらく時間を置いて', 'ご利用を制限'):
        if tok in html:
            return True
    return False


def polite_get(url, referer=None, interval=None):
    """1回だけGET。失敗・ブロックは None（リトライしない）。"""
    if _stop_reason[0]:
        return None
    import requests
    wait = (interval if interval is not None else REQUEST_INTERVAL)
    wait = wait - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0, JITTER_SEC))
    headers = {'User-Agent': UA}
    if referer:
        headers['Referer'] = referer
    try:
        r = requests.get(url, headers=headers, timeout=25)
        _last_fetch[0] = time.time()
        html = r.text or ''
        if r.status_code != 200 or _is_blocked(html, r.status_code):
            _stop_reason[0] = f'blocked status={r.status_code} url={url}'
            return None
        return html
    except Exception as e:
        _last_fetch[0] = time.time()
        _stop_reason[0] = f'fetch_error {e}'
        return None


def fetch_list_html(race_id, interval=None, use_cache=True):
    if use_cache:
        hit = load_cache('list', race_id)
        if hit:
            return hit
    html = polite_get(list_url(race_id), interval=interval)
    if html:
        save_cache('list', race_id, html)
    return html


def fetch_detail_html(yoso_id, race_id=None, interval=None, use_cache=True):
    if use_cache:
        hit = load_cache('detail', yoso_id)
        if hit:
            return hit
    ref = list_url(race_id) if race_id else YOSO_HOST
    html = polite_get(detail_url(yoso_id), referer=ref, interval=interval)
    if html:
        save_cache('detail', yoso_id, html)
    return html


def extract_yoso_ids(html):
    """一覧/結果HTMLから予想詳細IDだけ拾う。"""
    if not html:
        return []
    seen = []
    for m in _YOSO_ID_RE.finditer(html):
        i = m.group(1)
        if i not in seen:
            seen.append(i)
    return seen


def _ints(text):
    return [int(x) for x in re.findall(r'\d{1,2}', text or '')]


def _parse_combo(text):
    nums = [int(x) for x in re.findall(r'\d{1,2}', text or '')]
    return nums


def parse_ticket_cell(kind_cell, combo_cell):
    """券種セル＋組み合わせセル → 形だけ。"""
    kind_cell = str(kind_cell or '')
    combo_cell = str(combo_cell or '')
    km = _KIND_RE.search(kind_cell)
    if not km:
        return None
    kind = km.group(1)
    style = (km.group(2) or '').strip() or '通常'
    ways = None
    wm = _WAYS_RE.search(combo_cell)
    if wm:
        ways = int(wm.group(1))
    stakes = [int(x.replace(',', '')) for x in _YEN_RE.findall(combo_cell)]
    stake = stakes[-1] if stakes else None
    axis = _ints(_AXIS_RE.search(combo_cell).group(1)) if _AXIS_RE.search(combo_cell) else []
    aite = _ints(_AITE_RE.search(combo_cell).group(1)) if _AITE_RE.search(combo_cell) else []
    combos = []
    if not axis:
        for cm in _COMBO_RE.finditer(combo_cell):
            combos.append(_parse_combo(cm.group(1)))
    n_points = ways
    if n_points is None:
        n_points = len(combos) if combos else (1 if stake else 0)
    return {
        'kind': kind,
        'style': style,
        'n_points': n_points,
        'stake_each': stake,
        'axis_n': len(axis),
        'aite_n': len(aite),
        'combo_n': len(combos),
        'hit': ('的中' in combo_cell) or ('的中' in kind_cell),
    }


def parse_detail_tickets(html):
    """詳細HTMLから買い目の形だけ。印・馬名・見解は捨てる。"""
    if not html:
        return {'tickets': [], 'total_stake': None, 'payout': None, 'pl': None}
    tickets = []
    payout = None
    pl = None
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            header = ' '.join(th.get_text(' ', strip=True) for th in (rows[0].find_all(['th', 'td']) if rows else []))
            if ('券種' in header or '買い目' in header) and not tickets:
                for tr in rows[1:]:
                    cells = [c.get_text(' ', strip=True) for c in tr.find_all(['th', 'td'])]
                    if len(cells) < 2 or '合計' in cells[0]:
                        continue
                    rec = parse_ticket_cell(cells[0], cells[1])
                    if rec:
                        tickets.append(rec)
            text = table.get_text(' ', strip=True)
            if payout is None and ('払い戻し' in text or '収支' in text) and len(rows) >= 2:
                cells = [c.get_text(' ', strip=True) for c in rows[1].find_all(['th', 'td'])]
                yens = []
                for c in cells:
                    ym = _YEN_RE.search(c)
                    if ym:
                        yens.append(int(ym.group(1).replace(',', '')))
                if yens:
                    payout = yens[0]
                if len(cells) >= 2:
                    pm = re.search(r'([+\-]?[0-9,]+)', cells[1])
                    if pm:
                        pl = int(pm.group(1).replace(',', ''))
    except Exception:
        tickets = tickets or []
    yen_all = [int(x.replace(',', '')) for x in _YEN_RE.findall(html)]
    total_stake = None
    m_sum = re.search(r'合計[^0-9]{0,12}([0-9,]+)\s*円', html)
    if m_sum:
        total_stake = int(m_sum.group(1).replace(',', ''))
    if payout is None:
        m_pay = re.search(r'払い戻し金額[^0-9]{0,80}([0-9,]+)\s*円', html)
        if m_pay:
            payout = int(m_pay.group(1).replace(',', ''))
    if pl is None:
        m_pl = re.search(r'収支[^0-9+\-]{0,40}([+\-]?[0-9,]+)\s*円', html)
        if m_pl:
            pl = int(m_pl.group(1).replace(',', ''))
    if total_stake is None and tickets:
        total_stake = sum((t.get('stake_each') or 0) * max(1, t.get('n_points') or 1)
                          for t in tickets)
    return {
        'tickets': tickets,
        'total_stake': total_stake,
        'payout': payout,
        'pl': pl,
        'n_yen_mentions': len(yen_all),
    }


def shape_record(race_id, yoso_id, parsed):
    tickets = parsed.get('tickets') or []
    kinds = []
    for t in tickets:
        k = t['kind']
        if k not in kinds:
            kinds.append(k)
    n_points = sum(int(t.get('n_points') or 0) for t in tickets)
    styles = sorted({t.get('style') or '通常' for t in tickets})
    hit = any(t.get('hit') for t in tickets) or (
        parsed.get('payout') is not None and parsed['payout'] > 0)
    primary = None
    if tickets:
        primary = max(tickets, key=lambda t: (t.get('stake_each') or 0) * max(1, t.get('n_points') or 1))
    label = ''
    if primary:
        label = f"{primary['kind']} {primary.get('style') or '通常'} {n_points}点"
    app_near = nearest_app_playbook(kinds, styles, n_points)
    return {
        'race_id': str(race_id or ''),
        'yoso_id': str(yoso_id or ''),
        'kinds': kinds,
        'styles': styles,
        'n_tickets': len(tickets),
        'n_points': n_points,
        'total_stake': parsed.get('total_stake'),
        'payout': parsed.get('payout'),
        'pl': parsed.get('pl'),
        'hit': hit,
        'shape_label': label,
        'app_near': app_near,
        'tickets': tickets,
    }


def nearest_app_playbook(kinds, styles, n_points):
    """当アプリ既定に近い形か。券の中身（どの馬）は見ない。"""
    kinds = set(kinds or [])
    styles = set(styles or [])
    n = int(n_points or 0)
    if '3連複' in kinds and n <= 2:
        return 'D寄り（3連複・少点）'
    if '3連複' in kinds and 6 <= n <= 12:
        return 'Cクロス多寄り（3連複 2-3-6＝10点前後）'
    if '3連単' in kinds and 20 <= n <= 40:
        return 'Cクロス少寄り（3連単 2-4-7＝30点前後）'
    if '3連単' in kinds:
        return '3連単（点数はアプリ既定と違う）'
    if '3連複' in kinds:
        return '3連複（点数はアプリ既定と違う）'
    if kinds & {'馬連', '馬単', 'ワイド'}:
        nagashi = any('流し' in s for s in styles)
        return '対連' + ('流し' if nagashi else '通常') + '（アプリ本線外）'
    if kinds & {'単勝', '複勝'}:
        return '単複（アプリ本線外）'
    return '不明'


def append_index(rec):
    _ensure_dir()
    line = json.dumps(rec, ensure_ascii=False)
    with open(INDEX_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_index():
    if not os.path.exists(INDEX_PATH):
        return []
    rows = []
    with open(INDEX_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def summarize(rows):
    """収集分の形の集計。的中率は『当たった予想が目立つ』偏りあり。"""
    n = len(rows)
    if not n:
        return {'n': 0}
    from collections import Counter
    kind_c = Counter()
    near_c = Counter()
    pts = []
    hits = 0
    stake = 0
    payout = 0
    for r in rows:
        for k in r.get('kinds') or []:
            kind_c[k] += 1
        near_c[r.get('app_near') or '不明'] += 1
        pts.append(int(r.get('n_points') or 0))
        if r.get('hit'):
            hits += 1
        stake += int(r.get('total_stake') or 0)
        payout += int(r.get('payout') or 0)
    pts_s = sorted(pts)
    mid = pts_s[n // 2] if pts_s else 0
    return {
        'n': n,
        'kind_counts': dict(kind_c),
        'app_near_counts': dict(near_c),
        'points_median': mid,
        'points_mean': round(sum(pts) / n, 1) if n else 0,
        'hit_rate': round(hits / n, 3),
        'roi': round(100.0 * payout / stake, 1) if stake else None,
        'note': '的中が目立つ画面から拾っているので回収率は参考にならない。形の頻度だけ見る。',
    }
