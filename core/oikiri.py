# -*- coding: utf-8 -*-
"""
netkeiba 調教(追い切り)タイムビュー parser/fetcher。
oikiri.html?race_id=...&type=1 の表から、各馬の追い切り(日付/コース/馬場/乗り役/
時計ラップ/位置(分所)/脚色/短評/評価ランク)を抽出する。

注意: 調教タイムは検証で「過剰人気=ROIマイナス」と判明済（坂路, scripts/training_backtest.py）。
本モジュールは『表示・調教採点(情報)』用途。予測ボーナスへの組込みは慎重に。
"""
import re


def _floats(txt):
    return [float(x) for x in re.findall(r'\d+\.\d+', txt or '')]


def parse_oikiri_detail(html):
    """type=1 のHTMLから {umaban(int): {...}} を返す。最終追い切り(最新行)を採用。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_=re.compile('OikiriTable'))
    if not table:
        return {}
    out = {}
    cur_um = None
    cur_name = ''
    cur_comment = ''
    for tr in table.find_all('tr'):
        cells = tr.find_all(['td', 'th'])
        if not cells:
            continue
        info = tr.find(class_=re.compile('Horse_Info'))
        if info:
            # 馬ヘッダ行: 馬番 + 馬名 + 一言コメント
            um_td = tr.find(class_=re.compile('Umaban'))
            try:
                cur_um = int(re.search(r'\d+', um_td.get_text()).group())
            except Exception:
                cur_um = None
            cur_name = info.get_text(' ', strip=True).replace(' 前走', '').strip()
            rv = tr.find(class_=re.compile('TrainingReview_Cell'))
            cur_comment = rv.get_text(' ', strip=True) if rv else ''
            continue
        # 追い切り行（最新が先頭。最初の1本=最終追い切りを採用）
        day = tr.find(class_=re.compile('Training_Day'))
        if not day or cur_um is None or cur_um in out:
            continue
        tt = tr.find(class_=re.compile('TrainingTimeData'))
        load = tr.find(class_=re.compile('TrainingLoad'))
        critic = tr.find(class_=re.compile('Training_Critic'))
        rank_el = tr.find(class_=re.compile(r'Rank_'))
        # 列: [日付, コース, 馬場, 乗り役, タイム, 位置, 脚色, 短評, ランク, 映像]
        txts = [c.get_text(' ', strip=True) for c in cells]
        course = txts[1] if len(txts) > 1 else ''
        baba = txts[2] if len(txts) > 2 else ''
        rider = txts[3] if len(txts) > 3 else ''
        time_str = tt.get_text(' ', strip=True) if tt else ''
        # 位置(分所): タイムセルの次の空でないセル or 位置列
        ichi = ''
        if tt:
            nxt = tt.find_next_sibling('td')
            if nxt:
                ichi = nxt.get_text(strip=True)
        out[cur_um] = {
            'name': cur_name,
            'date': day.get_text(strip=True),
            'course': course,
            'baba': baba,
            'rider': rider,
            'time_str': time_str,
            'laps': _floats(time_str),
            'ichi': ichi,                       # 分所(内外, CW等で1-9)
            'load': load.get_text(strip=True) if load else '',   # 脚色(馬也/一杯/強め)
            'critic': critic.get_text(strip=True) if critic else '',  # 短評
            'rank': rank_el.get_text(strip=True) if rank_el else '',  # A-D
            'comment': cur_comment,
        }
    return out


def parse_oikiri_reviews(html):
    """type=3(全頭一覧)から {umaban(int): {'name','critic','rank'}} を返す（全頭・1発取得）。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    table = soup.find('table', class_=re.compile('OikiriTable'))
    if not table:
        return {}
    out = {}
    for tr in table.find_all('tr'):
        um_td = tr.find(class_=re.compile('Umaban'))
        info = tr.find(class_=re.compile('Horse_Info'))
        if not um_td or not info:
            continue
        try:
            um = int(re.search(r'\d+', um_td.get_text()).group())
        except Exception:
            continue
        critic = tr.find(class_=re.compile('Training_Critic'))
        rank = tr.find(class_=re.compile(r'Rank_'))
        out[um] = {
            'name': info.get_text(' ', strip=True).replace(' 前走', '').strip(),
            'critic': critic.get_text(strip=True) if critic else '',
            'rank': rank.get_text(strip=True) if rank else '',
        }
    return out


def fetch_oikiri_reviews(race_id, fetch_fn=None):
    """全頭の調教評価+短評を取得（type=3・1発）。{umaban: {name,critic,rank}}。"""
    url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}&type=3"
    if fetch_fn is None:
        from core import scraper
        fetch_fn = scraper.fetch_robust_html
    html = fetch_fn(url)
    return parse_oikiri_reviews(html) if html else {}


def fetch_oikiri_detail(race_id, fetch_fn=None):
    """調教タイムビューを取得して parse。fetch_fn 未指定なら scraper.fetch_robust_html。"""
    url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}&type=1"
    if fetch_fn is None:
        from core import scraper
        fetch_fn = scraper.fetch_robust_html
    html = fetch_fn(url)
    return parse_oikiri_detail(html) if html else {}
