# -*- coding: utf-8 -*-
"""逆神リンク集 — アカウント一覧の読み込みだけ。

X / YouTube の投稿取得・スクレイピング・本命抽出・スコアはしない。
表示は pages/gyaku_kami.py。予想エンジン（Rank / 穴馬 / 買い目）には繋がない。

将来、手動で本命を記録して重複を見る場合は、このカタログとは別ファイルにする。
"""
import json
import os

PLAT_X = 'x'
PLAT_YOUTUBE = 'youtube'
PLATFORMS = (PLAT_X, PLAT_YOUTUBE)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(_ROOT, 'data', 'gyaku_kami.json')

_ALLOWED_PREFIX = (
    'https://x.com/',
    'https://twitter.com/',
    'https://www.youtube.com/',
    'https://youtube.com/',
)

_cache = None


def _normalize_url(raw):
    """確認済みURLだけ残す。空・不正は未登録(None)。推測はしない。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if not s.startswith(_ALLOWED_PREFIX):
        return None
    if s.startswith('https://twitter.com/'):
        s = 'https://x.com/' + s[len('https://twitter.com/'):]
    if s.startswith('https://youtube.com/'):
        s = 'https://www.youtube.com/' + s[len('https://youtube.com/'):]
    return s


def load_catalog(path=None):
    """JSONを読む。取得はしない。"""
    p = path or CATALOG_PATH
    with open(p, encoding='utf-8') as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {'accounts': []}


def load_accounts(path=None, use_cache=True):
    global _cache
    if use_cache and path is None and _cache is not None:
        return list(_cache)
    data = load_catalog(path)
    rows = []
    for raw in data.get('accounts') or []:
        if not isinstance(raw, dict):
            continue
        aid = str(raw.get('id') or '').strip()
        name = str(raw.get('name') or '').strip()
        plat = str(raw.get('platform') or '').strip().lower()
        if not aid or not name or plat not in PLATFORMS:
            continue
        if raw.get('active', True) is False:
            continue
        handle = raw.get('handle')
        handle = str(handle).strip() if handle else ''
        note = str(raw.get('note') or '').strip()
        rows.append({
            'id': aid,
            'name': name,
            'platform': plat,
            'url': _normalize_url(raw.get('url')),
            'handle': handle or None,
            'note': note,
            'active': True,
        })
    if use_cache and path is None:
        _cache = list(rows)
    return rows


def accounts_for(platform, path=None):
    plat = str(platform or '').strip().lower()
    return [a for a in load_accounts(path=path) if a['platform'] == plat]


def has_url(account):
    return bool((account or {}).get('url'))
