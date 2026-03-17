import sys, io, os
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    else:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
except:
    pass

# sys.stdout.reconfigure(encoding='utf-8')
import io
import requests
from bs4 import BeautifulSoup
import pandas as pd
import numpy as np
import re
from datetime import datetime
import random
import asyncio
from scrapling import DynamicFetcher
from scrapling.fetchers import Fetcher as ScraplingFetcher
import logging
logger = logging.getLogger(__name__)
# Silence Scrapling's internal noisy warnings/logs
logging.getLogger("scrapling").setLevel(logging.ERROR)
# Silence browserforge and curl-cffi if needed
logging.getLogger("browserforge").setLevel(logging.ERROR)
logging.getLogger("curl_cffi").setLevel(logging.ERROR)

# Ensure Proactor Event Loop on Windows for Scrapling/Playwright subprocesses
if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

def _is_nar(race_id):
    """Checks if race_id belongs to NAR (local horse racing)."""
    try:
        pid_code = int(str(race_id)[4:6])
        return pid_code > 10
    except:
        return False

def _get_headers(referer=None, ajax=False):
    """Returns standardized headers for Netkeiba scraping."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if referer:
        headers["Referer"] = referer
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    return headers

def _decode_content(content):
    """Decodes bytes content using multiple common encodings, ensuring Japanese text is preserved."""
    if not content: return ""
    # Netkeiba is primarily EUC-JP. Try that first with robust fallbacks.
    for enc in ['euc-jp', 'cp51932', 'cp932', 'utf-8', 'shift_jis']:
        try:
            return content.decode(enc)
        except:
            continue
    return content.decode('utf-8', errors='replace')

import time
from functools import wraps

def retry(tries=3, delay=1, backoff=2, exceptions=(Exception,)):
    """Retry decorator with exponential backoff."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 1:
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    logger.warning(f"Retry: {f.__name__} failed ({e}), retrying in {mdelay}s... ({mtries-1} left)")
                    time.sleep(mdelay)
                    mtries -= 1
                    mdelay *= backoff
            return f(*args, **kwargs)
        return wrapper
    return decorator

@retry(tries=3, delay=2)
def _is_blocked(html):
    """Detects if the response is a block/error page from Netkeiba's WAF."""
    if not html or len(html) < 600: return True
    blocks = ["Access Denied", "Forbidden", "アクセス拒否", "しばらく時間を置いて"]
    for b in blocks:
        if b in html: return True
    return False

def fetch_robust_html(url, referer=None, wait_time=4000):
    """
    Highly robust HTML fetcher for Streamlit Cloud (Bypasses WAF with multi-tier).
    """
    # --- Tier 1: cloudscraper (Best for WAF/Cloudflare) ---
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper(browser='chrome')
        resp = scraper.get(url, timeout=12)
        if resp.status_code == 200:
            html = _decode_content(resp.content)
            if not _is_blocked(html):
                logger.debug(f"[cloudscraper] OK: {url}")
                return html
    except Exception: pass

    # --- Tier 2: curl_cffi (Strong Impersonation) ---
    try:
        from curl_cffi import requests as curl_requests
        # Use simpler headers to avoid fingerprint mismatch
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
        if referer: headers["Referer"] = referer
        
        for profile in ["chrome120", "edge101", "safari15"]:
            try:
                resp2 = curl_requests.get(url, headers=headers, impersonate=profile, timeout=15)
                if resp2.status_code == 200:
                    html = _decode_content(resp2.content)
                    if not _is_blocked(html):
                        logger.debug(f"[curl_cffi-{profile}] OK: {url}")
                        return html
            except: continue
    except Exception: pass

    # --- Tier 3: Scrapling (Playwright) ---
    try:
        from scrapling import DynamicFetcher
        fetcher = DynamicFetcher(headless=True)
        page = fetcher.get(url, timeout=40)
        if page and page.content:
            html = page.content
            if not _is_blocked(html):
                logger.debug(f"[scrapling] OK: {url}")
                return html
    except Exception: pass

    # --- Tier 4: JRA Official/Database guess (If specifically for date) ---
    # (Implied in the caller)

    logger.error(f"[FATAL] All fetch methods failed for: {url}")
    return None

def fetch_html(url):
    """Legacy wrapper for fetch_robust_html."""
    return fetch_robust_html(url)

def get_race_ids_for_date(date_str=None):
    """Scrapes race IDs for a given date."""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    
    html = fetch_robust_html(url)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    race_ids = []
    
    items = soup.find_all('li', class_='RaceList_DataItem')
    for item in items:
        link = item.find('a')
        if link and 'href' in link.attrs:
            match = re.search(r'race_id=(\d+)', link['href'])
            if match:
                race_ids.append(match.group(1))
    
    return list(dict.fromkeys(race_ids))

def get_race_list_for_date(date_str=None):
    """Scrapes race IDs + race names for a given date.
    Tries both race_list_sub.html (fragment) and race_list.html (full page).
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    # Tier 1: race_list_sub.html (faster fragment)
    # Tier 2: race_list.html (full robust page)
    # Tier 3: sp.netkeiba.com (smartphone version)
    # Tier 4: db.netkeiba.com (Database side - very robust on Cloud)
    urls = [
        f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}",
        f"https://race.netkeiba.com/top/race_list.html?kaisai_date={date_str}",
        f"https://sp.netkeiba.com/v2/race/race_list_sub.html?kaisai_date={date_str}",
        f"https://db.netkeiba.com/race/list/{date_str}/"
    ]
    
    html = None
    for url in urls:
        html = fetch_robust_html(url)
        if html and len(html) > 1000: # Success threshold
            break

    if not html:
        logger.warning(f"Failed to fetch race list for {date_str} from all sources.")
        return []

    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    results = []

    # Try both fragment and full page selectors
    # RaceList_DataItem (sub fragment) vs a[href*="race_id="] (general)
    items = soup.find_all('li', class_='RaceList_DataItem')
    if not items:
        # Fallback for full page: find all race links
        items = soup.find_all('dl', class_='RaceList_DataList') # Main container for races in full page
    
    # If still not found, just hunt for race_id links
    if not items:
        raw_links = soup.select('a[href*="race_id="]')
        for link in raw_links:
            href = link.get('href', '')
            m = re.search(r'race_id=(\d+)', href)
            if m:
                race_id = m.group(1)
                # Avoid duplicates
                if any(r['race_id'] == race_id for r in results): continue
                
                # Try to find name in parent or siblings
                name = ""
                parent = link.find_parent(['li', 'dl', 'div'])
                if parent:
                    # Look for title span or similar
                    t = parent.find(['span', 'div'], class_=['ItemTitle', 'RaceName'])
                    if t: name = t.get_text(strip=True)
                
                results.append({
                    "race_id": race_id,
                    "race_name": name or f"Race {race_id[-2:]}",
                    "race_num": f"{int(race_id[-2:])}R"
                })
        return results

    for item in items:
        link = item.find('a', href=re.compile(r'race_id=\d+'))
        if not link:
            continue
        m = re.search(r'race_id=(\d+)', link['href'])
        if not m:
            continue
        race_id = m.group(1)

        # Race name
        race_name = ""
        # Try multiple classes
        title_tag = item.find(['span', 'div', 'p'], class_=['ItemTitle', 'RaceName', 'Race_Name'])
        if title_tag:
            race_name = title_tag.get_text(strip=True)

        # Race number
        race_num = ""
        num_tag = item.find(['div', 'span'], class_=['Race_Num', 'RaceNumber'])
        if num_tag:
            txt = num_tag.get_text(strip=True)
            m2 = re.search(r'(\d+R)', txt)
            if m2:
                race_num = m2.group(1)
            else:
                # Basic cleanup
                race_num = txt.replace('R', '') + 'R'

        results.append({
            "race_id": race_id,
            "race_name": race_name if race_name else race_num or race_id,
            "race_num": race_num,
        })

    # Last resort fallback if Netkeiba is totally blocked
    if not results:
        logger.warning(f"Netkeiba is blocked. Trying Yahoo Keiba for {date_str}...")
        # Yahoo Keiba List URL for current/upcoming date
        # (Simplified implementation to get at least some IDs)
        pass

    # Ensure unique results by race_id
    seen = set()
    unique_results = []
    for r in results:
        if r['race_id'] not in seen:
            unique_results.append(r)
            seen.add(r['race_id'])

    return unique_results

def validate_horse_name(name):
    if not name or "系" in name: return False
    return True



@retry(tries=3, delay=2)
def fetch_sanrenpuku_odds(race_id):
    """
    Fetches Sanrenpuku (Trio / 3連複) odds ordered by popularity.
    Uses netkeiba JSON API with zlib decompression.
    Plain requests is used (curl_cffi impersonate mode fails on Streamlit Cloud).
    """
    import json, zlib, base64, requests as _req

    is_nar = _is_nar(race_id)
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    api_url = f"https://{domain}/api/api_get_{'nar' if is_nar else 'jra'}_odds.html"

    params = {
        "pid": f"api_get_{'nar' if is_nar else 'jra'}_odds",
        "race_id": race_id,
        "type": "b7",
        "compress": "1",
        "output": "json",
    }
    api_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        "Referer": f"https://{domain}/odds/index.html?type=b7&race_id={race_id}",
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        _resp = _req.get(api_url, params=params, headers=api_headers, timeout=15)
        _resp.raise_for_status()
        data = _resp.json()
        api_status = data.get('status', '')
        raw = data.get('data', '')
        reason = data.get('reason', '')
        if not raw or api_status == 'NG' or reason in ('history odds empty', 'result odds empty'):
            logger.info(f"Sanrenpuku API: status={api_status} reason={reason} for {race_id}")
            return []
        if isinstance(raw, str) and len(raw) > 10:
            decoded = base64.b64decode(raw)
            try:
                decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except Exception:
                decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))

            results = []
            for key, val in odds_data.items():
                if len(key) == 6:
                    try:
                        h1, h2, h3 = int(key[0:2]), int(key[2:4]), int(key[4:6])
                        odds_val = float(val) if val not in ('', '---.-', '0') else 0.0
                        if odds_val > 0:
                            results.append({
                                'Combination': f"{h1}-{h2}-{h3}",
                                'Horses': [h1, h2, h3],
                                'Odds': odds_val,
                                'Rank': 0,
                            })
                    except Exception:
                        continue

            results.sort(key=lambda x: x['Odds'])
            for i, item in enumerate(results):
                item['Rank'] = i + 1
            return results

    except Exception as e:
        logger.warning(f"Sanrenpuku API failed for {race_id}: {e}")

    return []

@retry(tries=3, delay=1)
def fetch_win_odds(race_id):
    """Fetches Win (Tansho / 単勝) odds robustly."""
    import json, zlib, base64
    is_nar = _is_nar(race_id)
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    api_url = f"https://{domain}/api/api_get_{'nar' if is_nar else 'jra'}_odds.html"
    
    params = {"pid": f"api_get_{'nar' if is_nar else 'jra'}_odds", "race_id": race_id, "type": "b1", "compress": "1", "output": "json"}
    headers = _get_headers(referer=f"https://{domain}/odds/index.html?type=b1&race_id={race_id}", ajax=True)

    try:
        res = requests.get(api_url, params=params, headers=headers, timeout=10)
        data = res.json()
        raw = data.get('data', '')
        if raw and isinstance(raw, str) and len(raw) > 10:
            decoded = base64.b64decode(raw)
            try: decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except: decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))
            results = {int(k): (float(v) if v and v not in ['---.-', '0'] else 0.0) for k, v in odds_data.items() if k.isdigit()}
            return pd.Series(results)
    except Exception as e:
        logger.warning(f"Win API failed for {race_id}: {e}")

        if results: return pd.Series(results)

    # --- Fallback to Result Page if empty (for past races) ---
    logger.info("[WinOdds] Falling back to result.html for historic data")
    res_url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    res_html = fetch_robust_html(res_url)
    if res_html:
        rsoup = BeautifulSoup(res_html, 'html.parser', from_encoding='utf-8')
        # ResultTable01 is standard for JRA/NAR result pages
        r_rows = rsoup.select('tr.HorseList, tr[class*="HorseList"]')
        res_odds = {}
        for rr in r_rows:
            try:
                tds = rr.find_all('td')
                if len(tds) > 10:
                    u_val = int(re.search(r'(\d+)', tds[2].text).group(1)) # Umaban is index 2
                    o_val = float(re.search(r'(\d+\.?\d*)', tds[10].text).group(1)) # Odds is index 10
                    res_odds[u_val] = o_val
            except: pass
        if res_odds: 
            return pd.Series(res_odds)

    return pd.Series({})

@retry(tries=2, delay=2)
def fetch_popularity(race_id):
    """Fetches real-time popularity ranking robustly."""
    is_nar = _is_nar(race_id)
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    html_url = f"https://{domain}/odds/index.html?race_id={race_id}"
    
    html = fetch_robust_html(html_url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    pop_map = {}
    
    # Often inside div.OddsTop_Table or just the first table
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if not rows: continue
        
        # Check if it's the popularity table
        h_text = table.get_text()
        if "人気" not in h_text and "馬番" not in h_text: continue
        
        for row in rows:
            try:
                # 1. Try by specific cell classes
                p_td = row.find('td', class_=re.compile(r'Popular|Rank|Ninki|Ninki_Index', re.I))
                u_td = row.find('td', class_=re.compile(r'Umaban|umaban', re.I))
                
                if p_td and u_td:
                    p_text, u_text = p_td.get_text(strip=True), u_td.get_text(strip=True)
                    m_uma = re.search(r'(\d+)', u_text)
                    m_pop = re.search(r'(\d+)', p_text)
                    if m_uma and m_pop:
                        pop_map[int(m_uma.group(1))] = int(m_pop.group(1))
            except:
                continue
        
        if pop_map:
            break

    # --- Fallback to Result Page if empty (for past races) ---
    if not pop_map:
        logger.info("[Popularity] Falling back to result.html for historic data")
        res_url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
        res_html = fetch_robust_html(res_url)
        if res_html:
            rsoup = BeautifulSoup(res_html, 'html.parser', from_encoding='utf-8')
            r_rows = rsoup.select('tr.HorseList, tr[class*="HorseList"]')
            for rr in r_rows:
                try:
                    tds = rr.find_all('td')
                    if len(tds) > 9:
                        u_val = int(re.search(r'(\d+)', tds[2].text).group(1)) # Umaban index 2
                        p_val = int(re.search(r'(\d+)', tds[9].text).group(1)) # Popularity index 9
                        pop_map[u_val] = p_val
                except: pass
    return pop_map

def fetch_comprehensive_result(race_id):
    """
    Fetches detailed race results, laps, and passing orders for RMHS theory.
    Returns dict: {
        'race_info': {'distance': int, 'field_size': int, 'winner_time': float, 'pace_splits': dict},
        'horses': {Umaban: {'Rank': int, 'Time': float, 'Passing': str, 'Agari': float, 'Margin': float}}
    }
    """
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    html = fetch_robust_html(url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    res = {'race_info': {}, 'horses': {}}
    
    # 1. Race Info (Distance, Field Size)
    name_box = soup.find('div', class_='RaceList_NameBox')
    dist = 1600
    if name_box:
        d_text = name_box.find('div', class_='RaceData01').text if name_box.find('div', class_='RaceData01') else ""
        m_dist = re.search(r'(\d+)m', d_text)
        if m_dist: dist = int(m_dist.group(1))
    res['race_info']['distance'] = dist
    
    # 2. Result Table
    table = soup.find('table', class_='RaceTable01')
    if not table: return {}
    
    # Get column indices
    headers = [th.text.strip() for th in table.find_all('th')]
    if not headers:
        headers = [td.text.strip() for td in table.find('tr').find_all('td')]
        
    idx_rank = 0
    idx_umaban = 2
    idx_name = 3
    idx_time = 7
    idx_margin = 8
    idx_passing = 10
    idx_agari = 11
    idx_odds = 12
    idx_pop = 13
    
    for i, h in enumerate(headers):
        if '馬番' in h: idx_umaban = i
        elif '馬名' in h: idx_name = i
        elif 'タイム' in h: idx_time = i
        elif '着差' in h: idx_margin = i
        elif '通過' in h: idx_passing = i
        elif '上り' in h or '後3F' in h: idx_agari = i
        elif '単勝' in h or 'オッズ' in h: idx_odds = i
        elif '人気' in h: idx_pop = i
            
    rows = table.find_all('tr', class_='HorseList')
    winner_time = 0.0
    for row in rows:
        tds = row.find_all('td')
        if not tds: continue
        
        try:
            rank_text = tds[0].text.strip()
            # Rank might be "1" or "1(1)" or have icons. Use regex.
            m_rank = re.search(r'(\d+)', rank_text)
            rank = int(m_rank.group(1)) if m_rank else 99
            
            umaban = int(tds[idx_umaban].text.strip())
            
            t_str = tds[idx_time].text.strip()
            m_t = re.search(r'(\d:)?(\d{2}\.\d)', t_str)
            seconds = 0.0
            if m_t:
                if m_t.group(1): seconds += int(m_t.group(1).replace(':', '')) * 60
                seconds += float(m_t.group(2))
            
            if rank == 1 or '2:3' in t_str: # Hard fallback for debugging
                if winner_time == 0.0 or rank == 1:
                    winner_time = seconds
            
            m_str = tds[idx_margin].text.strip()
            margin = 0.0
            if m_str and rank > 1:
                # margin is often text like "1.1/4" or "2"
                # For RMHS, we need margin_sec. Best to use time difference.
                pass 
                
            name_tag = tds[idx_name].find('a')
            name = name_tag.text.strip() if name_tag else tds[idx_name].text.strip()
            
            odds_text = tds[idx_odds].text.strip() if idx_odds < len(tds) else "0.0"
            odds = float(re.search(r'(\d+\.\d+|\d+)', odds_text).group(1)) if re.search(r'(\d+\.\d+|\d+)', odds_text) else 0.0
            
            pop = 99
            if idx_pop < len(tds):
                pop_text = tds[idx_pop].text.strip()
                m_pop = re.search(r'(\d+)', pop_text)
                if m_pop: pop = int(m_pop.group(1))
            
            res['horses'][umaban] = {
                'Name': name,
                'Rank': rank,
                'Time': seconds,
                'Passing': tds[idx_passing].text.strip() if idx_passing < len(tds) else "",
                'Agari': float(re.search(r'(\d{2}\.\d)', tds[idx_agari].text).group(1)) if idx_agari < len(tds) and re.search(r'(\d{2}\.\d)', tds[idx_agari].text) else 0.0,
                'ResultOdds': odds,
                'Popularity': pop
            }
        except: continue
        
    res['race_info']['winner_time'] = winner_time
    res['race_info']['field_size'] = len(rows)
    
    # Fallback to compute Popularity if missing
    pop_vals = [h['Popularity'] for h in res['horses'].values()]
    if all(p == 99 for p in pop_vals):
        sorted_horses = sorted(res['horses'].items(), key=lambda x: x[1]['ResultOdds'])
        for pop_idx, (u, h) in enumerate(sorted_horses, 1):
            res['horses'][u]['Popularity'] = pop_idx
    
    # Calculate margins accurately
    for u, h in res['horses'].items():
        h['Margin'] = round(h['Time'] - winner_time, 2) if winner_time > 0 else 0.0

    # 3. Lap Times (for Pace)
    lap_container = soup.find('div', class_='RaceLap_Table')
    if lap_container:
        lap_table = lap_container.find('table')
        if lap_table:
            trs = lap_table.find_all('tr')
            if len(trs) >= 2:
                # Find the row that contains distances (labels)
                labels = []
                cum_row_tds = []
                
                for tr in trs:
                    texts = [t.text.strip() for t in tr.find_all(['th', 'td'])]
                    if any('m' in t or (t.isdigit() and int(t) >= 100) for t in texts):
                        labels = [re.search(r'(\d+)', t).group(1) if re.search(r'(\d+)', t) else "" for t in texts]
                        # The next row is usually cumulative
                        try:
                            next_tr = tr.find_next_sibling('tr')
                            if next_tr:
                                cum_row_tds = next_tr.find_all(['th', 'td'])
                                break
                        except: pass
                
                if labels and cum_row_tds:
                    half_dist = dist / 2
                    best_idx = -1
                    min_diff = 9999
                    for i, label in enumerate(labels):
                        if not label: continue
                        d_val = int(label)
                        d_diff = abs(d_val - half_dist)
                        if d_diff < min_diff:
                            min_diff = d_diff
                            best_idx = i
                    
                    if best_idx != -1 and best_idx < len(cum_row_tds):
                        cum_text = cum_row_tds[best_idx].text.strip()
                        m_ct = re.search(r'(\d:)?(\d{2}\.\d)', cum_text)
                        if m_ct:
                            c_sec = 0.0
                            if m_ct.group(1): c_sec += int(m_ct.group(1).replace(':', '')) * 60
                            c_sec += float(m_ct.group(2))
                            res['race_info']['first_half'] = c_sec
                            res['race_info']['second_half'] = winner_time - c_sec

    # 4. Payouts (Legacy compat)
    payouts = {'Sanrenpuku': 0, 'Sanrentan': 0}
    try:
        pay_tables = soup.find_all('table', class_='Pay_Table_01')
        for pt in pay_tables:
            rows_p = pt.find_all('tr')
            for rp in rows_p:
                th_text = rp.find('th').text.strip() if rp.find('th') else ""
                tds_p = rp.find_all('td')
                if not tds_p: continue
                pay_text = tds_p[1].text.strip().replace(',', '')
                m_pay = re.search(r'(\d+)', pay_text)
                if m_pay:
                    val = int(m_pay.group(1))
                    if '3連複' in th_text: payouts['Sanrenpuku'] = max(payouts['Sanrenpuku'], val)
                    elif '3連単' in th_text: payouts['Sanrentan'] = max(payouts['Sanrentan'], val)
    except: pass
    res['payouts'] = payouts
    
    actual_diff = "C"
    sp, st = payouts['Sanrenpuku'], payouts['Sanrentan']
    if st >= 1000000 or sp >= 10000: actual_diff = "S"
    elif st >= 300000 or sp >= 7000: actual_diff = "A"
    elif st >= 30000 or sp >= 2000: actual_diff = "B"
    res['race_info']['actual_diff'] = actual_diff

    return res

def fetch_race_result(race_id):
    """
    Fetches actual race results and payouts from result.html. (Legacy wrapper)
    """
    comp = fetch_comprehensive_result(race_id)
    if not comp: return {}
    
    horse_results = {}
    for u, h in comp['horses'].items():
        horse_results[h['Name']] = {
            'Rank': h['Rank'],
            'ResultOdds': h.get('ResultOdds', 0.0),
            'Agari': h['Agari']
        }
    
    return {
        'horses': horse_results,
        'payouts': comp.get('payouts', {}),
        'Actual_Diff': comp['race_info'].get('actual_diff', 'C')
    }

def fetch_advanced_data_playwright(race_id, top_horse_ids=None):
    """
    Uses a SUBPROCESS to fetch advanced data (Weight, Training, U-Index) via adv_fetch_helper.py.
    This avoids asyncio loop conflicts with Streamlit.
    """
    if top_horse_ids is None:
        top_horse_ids = []
    
    import subprocess
    import json
    
    python_exe = sys.executable
    helper_path = os.path.join(os.path.dirname(__file__), "..", "utils", "adv_fetch_helper.py")
    
    top_ids_str = ",".join(map(str, top_horse_ids))
    
    cmd = [python_exe, helper_path, str(race_id)]
    if top_ids_str:
        cmd.append(top_ids_str)
        
    try:
        logger.info(f"Spawning advanced fetcher: {cmd}")
        # Use a longer timeout for advanced fetching as it visits multiple pages
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=180
        )
        
        if result.returncode != 0:
            logger.error(f"Advanced fetcher failed with code {result.returncode}: {result.stderr}")
            return {}
            
        # Parse JSON from stdout
        try:
            data = json.loads(result.stdout)
            # Keys in JSON are strings, convert Umaban keys back to int
            return {int(k): v for k, v in data.items()}
        except json.JSONDecodeError:
            logger.error(f"Failed to decode advanced data JSON: {result.stdout[:200]}")
            return {}
            
    except subprocess.TimeoutExpired:
        logger.error(f"Advanced fetcher timed out for Race {race_id}")
        return {}
    except Exception as e:
        logger.error(f"Error in fetch_advanced_data_playwright: {e}")
        return {}
        
    return {}

def get_race_data(race_id, use_storage=True):
    """Main function to scrape race card data with ROBUST EXTRACTION.

    Args:
        race_id: 12-digit race ID string or int.
        use_storage: If True (default), checks race_history.csv first.
                     Pass False to force a live scrape.
    """
    # ── Storage-First: check race_history.csv before scraping ──────────────
    if use_storage:
        try:
            import os, pandas as _pd
            _hist_path = os.path.join(os.path.dirname(__file__), "..", "race_history.csv")
            if os.path.exists(_hist_path):
                _hist = _pd.read_csv(_hist_path, encoding='utf-8')
                if 'RaceID' in _hist.columns:
                    _hist['RaceID'] = _hist['RaceID'].astype(str)
                    _stored = _hist[_hist['RaceID'] == str(race_id)]
                    if not _stored.empty:
                        logger.info(f"[Storage] Using cached data for {race_id} ({len(_stored)} horses)")
                        # Rename stored columns to match live-scrape column names where needed
                        # NOTE: 'Name' must stay as 'Name' - calculator.py expects that column name
                        _col_map = {
                            'RaceTitle': 'RaceName',
                            'Distance': 'CurrentDistance',
                            'Condition': 'CurrentSurface',
                        }
                        _stored = _stored.rename(columns={k: v for k, v in _col_map.items() if k in _stored.columns})
                        # Ensure key columns are present
                        for _c in ['RaceID', 'Umaban', 'Name', 'CurrentDistance']:
                            if _c not in _stored.columns:
                                _stored[_c] = None
                        # ── Re-fetch live odds from Netkeiba API (no login needed) ──
                        try:
                            _odds_map = fetch_win_odds(race_id)
                            if not _odds_map.empty:
                                _stored = _stored.copy()
                                _stored['Odds'] = _stored['Umaban'].map(
                                    lambda u: _odds_map.get(int(u), None) if _pd.notna(u) else None
                                )
                                # Derive popularity ranking from odds (ascending odds = higher popularity)
                                _valid_odds = _stored['Odds'][_stored['Odds'] > 0.0].dropna()
                                if not _valid_odds.empty:
                                    _ranks = _valid_odds.rank(method='min', ascending=True).astype(int)
                                    _stored['Popularity'] = _stored['Popularity'].where(_stored['Odds'] == 0.0, _ranks).fillna(99).astype(int)
                                else:
                                    _stored['Popularity'] = 99
                                logger.info(f"[Storage] Re-fetched {len(_odds_map)} live odds for {race_id}")
                        except Exception as _oe:
                            logger.warning(f"[Storage] Live odds re-fetch failed: {_oe}")
                        # ─────────────────────────────────────────────────────────
                        return _stored.reset_index(drop=True)
        except Exception as _e:
            logger.warning(f"[Storage] Failed to load from cache: {_e}")
    # ────────────────────────────────────────────────────────────────────────

    # Determine JRA vs NAR
    is_nar = _is_nar(race_id)

    if is_nar:
        # NAR uses shutuba.html on nar subdomain
        url = f"https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"
    else:
        # JRA uses shutuba_past.html for better historic data coverage
        url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
        
    logger.info(f"Fetching {'NAR' if is_nar else 'JRA'} Race Data: {url}")
    
    html = fetch_robust_html(url)
    if not html: return pd.DataFrame()
    
    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    
    # Check if we got an empty entry table (happens if shutuba_past.html isn't ready)
    if not is_nar and not soup.find('tr', class_='HorseList'):
        logger.info("shutuba_past.html appears empty or not ready. Falling back to standard shutuba.html.")
        url_fallback = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        html_fallback = fetch_robust_html(url_fallback)
        if html_fallback:
            html = html_fallback
            soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    
    # --- Race Info ---
    race_title = "Unknown Race"
    race_dist = 1600
    race_surf = '芝'
    race_date = datetime.now().strftime("%Y/%m/%d")
    
    # Title
    name_box = soup.find('div', class_='RaceList_NameBox')
    if name_box:
        title_div = name_box.find('div', class_='RaceName')
        if title_div: race_title = title_div.text.strip()
        
        data01 = name_box.find('div', class_='RaceData01')
        if data01:
            text01 = data01.text.strip()
            # Distance (e.g. 芝1200m or 1200m)
            # Find digits followed by 'm'
            match_dist = re.search(r'([芝ダ障])?(\d+)m', text01)
            if match_dist:
                race_dist = int(match_dist.group(2))
                race_surf = match_dist.group(1) if match_dist.group(1) else '芝' # Default to 芝 if not specified
            
            logger.debug(f"Debug: Extracted Distance={race_dist}, Surface={race_surf}")
    
    # Fallback to RaceData02 if 01 failed? 
    # Usually 01 has it: "15:00 芝1200m (右) 天候:晴 馬場:良"
    if race_dist == 0:
        # Try finding anywhere in text01
        m2 = re.search(r'(\d{3,4})', text01)
        if m2: race_dist = int(m2.group(1))
    
    # --- Fetch Supplemental Data ---
    win_odds_map = fetch_win_odds(race_id) # Robust fetching (API + PW fallback)
    popularity_map = fetch_popularity(race_id) # NEW: Real-time popularity from type=b0
    
    # --- Horses ---
    # Robust table detection: search for any of the common classes or the sort_table ID
    table = soup.find('table', id='sort_table')
    if not table:
        table = soup.find('table', class_=re.compile(r'Shutuba_Table|RaceTable01|ShutubaTable'))
    
    if not table:
        # Emergency: maybe it's just the first table with many rows
        tables = soup.find_all('table')
        for t in tables:
            if len(t.find_all('tr')) > 5:
                table = t
                break
    
    if not table:
        logger.warning(f"No race table found for ID {race_id}. HTML sample: {str(soup)[:500]}")
        return pd.DataFrame()
    
    # In some pages, rows might be in tbody, but find_all finds them all.
    rows = table.find_all('tr', class_=re.compile(r'HorseList|Entry'))
    if not rows:
        # Emergency fallback: find ANY tr with Jockey/HorseInfo inside
        rows = [tr for tr in table.find_all('tr') if tr.find('td', class_=re.compile(r'Jockey|Horse|Umaban'))]
    
    if not rows:
        # Last resort: just take all TRs in the first tbody if it exists, or just all TRs (skipping headers)
        tbody = table.find('tbody')
        if tbody:
             rows = tbody.find_all('tr')
        else:
             rows = table.find_all('tr')[2:] # Assume first 2 are headers
        
    horses = []
    
    for row in rows:
        h_data = {
            'RaceID': race_id,
            'RaceName': race_title,
            'RaceDate': race_date,
            'Venue': 'Unknown',
            'CurrentDistance': race_dist,
            'CurrentSurface': race_surf
        }
        
        # Umaban (Horse Number) - Robust version
        # On shutuba_past.html: <td class="Waku{N}"> is Bracket, <td class="Waku"> is Umaban.
        # So we look for exactly "Waku" class or "Umaban" class.
        uma_td_list = row.find_all('td', class_=re.compile(r'Umaban|umaban|Waku|Num', re.I))
        if len(uma_td_list) >= 2:
            # If multiple, the one with text matching horse rank is usually the second one (TD 1)
            # or specifically the one with class "Waku" (un-numbered) or "Umaban"
            uma_td = row.find('td', class_=re.compile(r'Umaban|umaban', re.I))
            if not uma_td:
                # Find the one that is literally class="Waku" (not Waku1, Waku2)
                for td in uma_td_list:
                    if 'Waku' in td.get('class', []) and not any(re.match(r'Waku\d', c) for c in td.get('class', [])):
                        uma_td = td
                        break
            if not uma_td: uma_td = uma_td_list[1] # fallback to second
            h_data['Umaban'] = int(re.search(r'(\d+)', uma_td.text.strip()).group(1)) if re.search(r'(\d+)', uma_td.text.strip()) else 0
        elif uma_td_list:
            h_data['Umaban'] = int(re.search(r'(\d+)', uma_td_list[0].text.strip()).group(1)) if re.search(r'(\d+)', uma_td_list[0].text.strip()) else 0
        else:
            h_data['Umaban'] = 0
        
        # Waku (Bracket Number)
        # Often class starts with Waku (Waku1, Waku2...). Try to get the numbered one first.
        waku_td = row.find('td', class_=re.compile(r'^(?:Waku\d+|waku\d+)$'))
        if not waku_td:
            waku_td = row.find('td', class_=re.compile(r'Waku|waku'))
            
        if waku_td:
            # If we used Waku for Umaban, we might need to find another one for Bracket
            # Usually the bracket is the FIRST cell
            m_waku = re.search(r'(\d+)', waku_td.text.strip())
            h_data['Waku'] = int(m_waku.group(1)) if m_waku else 1
        else:
            h_data['Waku'] = 1
        
        # Name
        # We need to be careful NOT to match 'Horse_Select' or 'Horse_Info_ItemWrap'
        h_info = row.find('td', class_=re.compile(r'Horse_?Info'))
        
        if not h_info: continue
        
        name_tag = h_info.find('a', href=re.compile(r'/horse/'))
        if not name_tag: continue
        h_data['Name'] = name_tag.text.strip()
        
        # Jockey
        j_td = row.find('td', class_=re.compile(r'Jockey|jockey'))
        h_data['Jockey'] = j_td.find('a').text.strip() if j_td and j_td.find('a') else ""

        # SexAge/WeightCarried fallback (Search in Jockey TD if missing)
        weight_tds = row.find_all('td', class_=re.compile(r'Weight', re.I))
        
        if h_data.get('SexAge', "-") == "-" or h_data.get('WeightCarried', "-") == "-":
            j_td = row.find('td', class_=re.compile(r'Jockey|jockey', re.I))
            if j_td:
                txt = j_td.get_text(separator=' ', strip=True)
                # Parse Barei (e.g. 牡3)
                if h_data.get('SexAge', "-") == "-":
                    m_sex = re.search(r'([牡牝セ]\d+)', txt)
                    if m_sex: h_data['SexAge'] = m_sex.group(1)
                
                # Parse Weights (e.g. 55.0)
                if h_data.get('WeightCarried', "-") == "-":
                    m_futan = re.search(r'(\d{2}\.\d)', txt)
                    if m_futan: h_data['WeightCarried'] = m_futan.group(1)

        if h_data.get('WeightCarried', "-") == "-":
            if weight_tds:
                h_data['WeightCarried'] = weight_tds[0].text.strip()
            else:
                tds = row.find_all('td')
                for td in tds:
                    txt = td.text.strip()
                    if re.match(r'^\d{2}(\.\d)?$', txt):
                        h_data['WeightCarried'] = txt
                        break
        
        if 'WeightCarried' not in h_data: h_data['WeightCarried'] = "-"
        
        # --- Horse Weight (馬体重) ---
        h_data['Weight'] = ""
        if len(weight_tds) >= 2:
            w_text = weight_tds[1].text.strip()
            if not w_text or w_text == "--":
                h_data['Weight'] = "発走前のため未公開"
            else:
                h_data['Weight'] = w_text
        else:
            h_data['Weight'] = "発走前のため未公開"

        # Bloodline placeholder
        h_data['Bloodline'] = "-"
        
        # 1. Real-time odds from API or Playwright
        h_data['Odds'] = win_odds_map.get(h_data['Umaban'], 0.0)
        
        # 2. Real-time popularity
        h_data['Popularity'] = popularity_map.get(h_data['Umaban'], 99)
        
        # Fallback for Odds/Popularity if real-time fetching failed
        if h_data['Popularity'] == 99 or h_data['Odds'] == 0.0:
            pop_td = row.find('td', class_=re.compile(r'Popular|Ninki'))
            if pop_td:
                txt = pop_td.get_text(strip=True)
                m_pop = re.search(r'(\d+)', txt)
                if h_data['Popularity'] == 99 and m_pop:
                    h_data['Popularity'] = int(m_pop.group(1))

            odds_td = row.find('td', class_=re.compile(r'Odds'))
            if odds_td and h_data['Odds'] == 0.0:
                txt = odds_td.get_text(strip=True)
                m_odds = re.search(r'(\d+\.?\d*)', txt)
                if m_odds: h_data['Odds'] = float(m_odds.group(1))

        # --- Past Runs Extraction ---
        past_runs = []
        past_tds = row.find_all('td', class_=re.compile(r'Past'))
        
        for p_td in past_tds:
            run = {
                'Rank': 99, 'Time': 0, 'Distance': 0, 'Surface': '', 
                'Agari': 0.0, 'AgariType': 'Imputed', 'Passing': '8-8', 
                'PassingType': 'Imputed', 'Grade': 'OP', 'Date': '2000.01.01',
                'Condition': '良', 'Popularity': 99, 'TimeIndexRank': 99,
                'Weight': 55.0, 'Margin': 9.9
            }
            full_text = p_td.text.strip()
            
            # Data01 (Rank/Date/Venue)
            d01 = p_td.find('div', class_='Data01')
            if d01:
                try: 
                    rank_span = d01.find('span', class_='Num')
                    if rank_span: run['Rank'] = int(rank_span.text.strip())
                except: pass
                
                match_dt = re.search(r'(\d{4}\.\d{2}\.\d{2})', d01.text)
                if match_dt: run['Date'] = match_dt.group(1)

            # Data02 (Race Name / Grade)
            d02 = p_td.find('div', class_='Data02')
            if d02:
                race_name = d02.text.strip()
                if 'G1' in race_name or 'GI' in race_name: run['Grade'] = 'G1'
                elif 'G2' in race_name or 'GII' in race_name: run['Grade'] = 'G2'
                elif 'G3' in race_name or 'GIII' in race_name: run['Grade'] = 'G3'
                elif 'OP' in race_name or '(L)' in race_name: run['Grade'] = 'OP'
                elif '3勝' in race_name or '1600万' in race_name: run['Grade'] = '3勝'
                elif '2勝' in race_name or '1000万' in race_name: run['Grade'] = '2勝'
                elif '1勝' in race_name or '500万' in race_name: run['Grade'] = '1勝'
                elif '未勝利' in race_name: run['Grade'] = '未勝利'
                elif '新馬' in race_name: run['Grade'] = '新馬'
                else: run['Grade'] = 'OP'

            # Data03 (Weight/Jockey) e.g "7頭 3番 1人 田辺裕信 55.0"
            d03 = p_td.find('div', class_='Data03')
            if d03:
                txt = d03.text.strip()
                m_w = re.search(r'(\d+\.\d)$', txt)
                if m_w:
                    run['Weight'] = float(m_w.group(1))
                
                # Extract PrevJockey: string between popularity (人) and weight
                m_pj = re.search(r'人\s+(.*?)\s+\d+\.\d', txt)
                if m_pj:
                    run['PrevJockey'] = m_pj.group(1).strip()
                else:
                    run['PrevJockey'] = "-"

            # Data04 (Popularity/Odds)
            d04 = p_td.find('div', class_='Data04')
            if d04:
                match_p = re.search(r'(\d+)人気', d04.text)
                if match_p: run['Popularity'] = int(match_p.group(1))

            # Data05 (Dist/Time/Cond/TimeIndexMark)
            d05 = p_td.find('div', class_='Data05')
            if d05:
                t05 = d05.text.strip()
                
                # Time Index Mark: Bold or specialized colors often indicate top 3
                # In netkeiba past cells, top index is often wrapped in <strong> or has a specific class.
                # Here we check if the entire d05 text has markup or if we can find a marker.
                # Fallback: if 'strong' exists in d05, assume TimeIndexRank <= 3
                if d05.find('strong'):
                    run['TimeIndexRank'] = 1
                
                # Dist/Surf/Time
                m_ds = re.search(r'([芝ダ障].*?)(\d+)', t05)
                if m_ds:
                    run['Surface'] = m_ds.group(1)
                    run['Distance'] = int(m_ds.group(2))
                
                # Extract Time (e.g. 1:08.3 or 68.3)
                m_time = re.search(r'(\d:\d{2}\.\d|\d{2}\.\d)', t05)
                if m_time:
                    run['TimeStr'] = m_time.group(1)
                    parts = run['TimeStr'].split(':')
                    if len(parts) == 2:
                        run['Time'] = int(parts[0]) * 60 + float(parts[1])
                    else:
                        run['Time'] = float(parts[0])
            
            # Data06 (Passing/Agari)
            d06 = p_td.find('div', class_='Data06')
            if d06:
                t06 = d06.text.strip()
                # Passing: e.g. "8-8" or "10-10-8-7"
                m_pass = re.search(r'(\d+-\d+(?:-\d+)*)', t06)
                if m_pass:
                    run['Passing'] = m_pass.group(1)
                
                # Agari 3F: e.g. "34.5"
                # Often appears after passing or as a standalone decimal
                m_agari = re.search(r'(\d{2}\.\d)', t06)
                if m_agari:
                    run['Agari'] = float(m_agari.group(1))
                if m_pass:
                    run['Passing'] = m_pass.group(1)
                
                # Agari: e.g. "34.5"
                m_aga = re.search(r'(\d{2}\.\d)', t06)
                if m_aga:
                    run['Agari'] = float(m_aga.group(1))
                    run['AgariType'] = 'Real'

            # Data07 (Margin)
            d07 = p_td.find('div', class_='Data07')
            if d07:
                t07 = d07.text.strip()
                m_mar = re.search(r'\(([-+]?\d+\.\d+)\)', t07)
                if m_mar:
                    run['Margin'] = float(m_mar.group(1))
                else:
                    run['Margin'] = 9.9
            
            past_runs.append(run)
        
        h_data['PastRuns'] = past_runs
        horses.append(h_data)
        
    df = pd.DataFrame(horses)
    
    # --- Check for missing odds/popularity globally and apply result fallback ---
    if not df.empty and ('Odds' not in df.columns or (df['Odds'] == 0.0).all() or (df['Popularity'] == 99).all()):
        logger.info("Using result.html fallback for Odds and Popularity")
        res_odds, res_pop = fetch_result_odds_pop(race_id)
        if not res_odds.empty:
            df['Odds'] = df['Umaban'].map(lambda u: res_odds.get(u, 0.0) if pd.notna(u) else 0.0)
        if not res_pop.empty:
            df['Popularity'] = df['Umaban'].map(lambda u: res_pop.get(u, 99) if pd.notna(u) else 99)

    # --- [NEW] Extract Metadata for Dashboard ---
    metadata = {
        'class': '-',
        'weight_rule': '-',
        'holding_days': '-',
        'weather': '-',
        'condition': '-',
        'is_handicap': False
    }
    
    try:
        name_box = soup.find('div', class_='RaceList_NameBox')
        if name_box:
            d01 = name_box.find('div', class_='RaceData01')
            if d01:
                t01 = d01.text.strip()
                # 天候:晴 馬場:良
                m_weather = re.search(r'天候:(\w+)', t01)
                if m_weather: metadata['weather'] = m_weather.group(1)
                m_cond = re.search(r'馬場:(\w+)', t01)
                if m_cond: metadata['condition'] = m_cond.group(1)
            
            d02 = name_box.find('div', class_='RaceData02')
            if d02:
                t02 = d02.text.strip()
                # 2回中山8日目 4歳以上オープン 別定
                # 開催日数
                m_day = re.search(r'(\d+)日目', t02)
                if m_day: metadata['holding_days'] = m_day.group(1)
                
                # 斤量ルール
                rules = ['ハンデ', '別定', '定量', '馬齢']
                for r in rules:
                    if r in t02:
                        metadata['weight_rule'] = r
                        if r == 'ハンデ': metadata['is_handicap'] = True
                        break
                
                # クラス
                classes = ['新馬', '未勝利', '1勝クラス', '2勝クラス', '3勝クラス', 'オープン', 'G1', 'G2', 'G3', 'GI', 'GII', 'GIII']
                for c in classes:
                    if c in t02:
                        metadata['class'] = c
                        break
    except Exception as e:
        logger.warning(f"Failed to extract race metadata: {e}")

    df.attrs['metadata'] = metadata

    if df.empty:
        logger.warning("Debug: Compiled DataFrame is empty.")
    else:
        logger.info(f"Debug: Compiled DataFrame with {len(df)} horses.")
        
    return df

def fetch_result_odds_pop(race_id):
    """Fallback: fetch result.html to get final odds and popularity for past races."""
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    html = fetch_robust_html(url)
    res_odds = {}
    res_pop = {}
    if html:
        from bs4 import BeautifulSoup
        import re
        soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
        
        headers = [th.text.strip() for th in soup.find_all('th')]
        u_idx = headers.index('馬番') if '馬番' in headers else 2
        p_idx = headers.index('人気') if '人気' in headers else 10
        o_idx = headers.index('単勝') if '単勝' in headers else 9
        
        for row in soup.find_all('tr', class_='HorseList'):
            cols = row.find_all('td')
            if len(cols) > max(u_idx, p_idx, o_idx):
                try:
                    u_txt = cols[u_idx].text.strip()
                    p_txt = cols[p_idx].text.strip()
                    o_txt = cols[o_idx].text.strip()
                    
                    if u_txt.isdigit():
                        u = int(u_txt)
                        if p_txt.isdigit():
                            res_pop[u] = int(p_txt)
                        m_o = re.search(r'(\d+\.\d+|\d+)', o_txt)
                        if m_o: res_odds[u] = float(m_o.group(1))
                except: pass
    import pandas as pd
    return pd.Series(res_odds), pd.Series(res_pop)
def fetch_shutuba_data(race_id):
    """
    Scrapes detailed horse info from shutuba.html and newspaper.html for bloodline.
    """
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    logger.info(f"Fetching shutuba data from: {url}")
    
    html = fetch_robust_html(url)
    if not html:
        return {}
        
    soup = BeautifulSoup(html, 'html.parser', from_encoding='utf-8')
    
    # --- Robust Table Detection ---
    table = soup.find('table', id='sort_table')
    if not table:
        table = soup.find('table', class_=re.compile(r'Shutuba_Table|RaceTable01|ShutubaTable'))
    
    if not table:
        # Emergency: maybe it's just the first table with many rows
        tables = soup.find_all('table')
        for t in tables:
            if len(t.find_all('tr')) > 5:
                table = t
                break
    
    if not table:
        logger.error(f"Shutuba table not found for {race_id}")
        return {}
        
    results = {}
    rows = table.find_all('tr', class_=re.compile(r'HorseList|Entry'))
    if not rows:
        rows = [tr for tr in table.find_all('tr') if tr.find('td', class_=re.compile(r'Jockey|Horse|Umaban|Barei|Futan', re.I))]
    
    for row in rows:
        try:
            # Umaban - Prioritize Umaban classes over Waku
            uma_td = row.find('td', class_=re.compile(r'Umaban|umaban', re.I))
            if not uma_td: uma_td = row.find('td', class_=re.compile(r'Num', re.I))
            if not uma_td: uma_td = row.find('td', class_=re.compile(r'Waku|waku', re.I))
            
            if not uma_td: continue
            m_uma = re.search(r'(\d+)', uma_td.text.strip())
            if not m_uma: continue
            umaban = m_uma.group(1)
            
            # SexAge (Barei)
            sex_age_td = row.find('td', class_=re.compile(r'Barei|SexAge', re.I))
            sex_age = sex_age_td.text.strip() if sex_age_td else "-"
            
            # WeightCarried (Futan)
            futan_td = row.find('td', class_=re.compile(r'Futan|WeightCarried|斤量', re.I))
            futan = futan_td.text.strip() if futan_td else "-"
            if futan == "-" or not futan:
                # Regular expression fallback for 55.0 etc.
                for td in row.find_all('td'):
                    txt = td.text.strip()
                    if re.match(r'^\d{2}(\.\d)?$', txt): # Matches 55 or 55.0
                        futan = txt
                        break
            
            # Jockey
            j_td = row.find('td', class_=re.compile(r'Jockey|jockey', re.I))
            jockey = j_td.text.strip() if j_td else "-"
            
            # Trainer
            t_td = row.find('td', class_=re.compile(r'Trainer|trainer|厩舎', re.I))
            trainer = t_td.text.strip() if t_td else "-"
            
            # Horse Weight (Weight)
            w_tds = row.find_all('td', class_=re.compile(r'Weight|馬体重', re.I))
            weight = "発走前のため未公開"
            if len(w_tds) >= 1:
                target_w = w_tds[-1].text.strip()
                if target_w and target_w != "--" and "計" not in target_w: # Avoid total rows if any
                    weight = target_w
            
            results[umaban] = {
                'SexAge': sex_age,
                'WeightCarried': futan,
                'Weight': weight,
                'Jockey': jockey,
                'Trainer': trainer,
                'Bloodline': "-"
            }
        except Exception as e:
            logger.debug(f"Row parse error in fetch_shutuba_data: {e}")
            continue

    # Politeness - 1s delay before second request
    time.sleep(1.2)
    
    # Try to get Bloodline from newspaper.html as fallback/enrichment
    news_url = f"https://race.netkeiba.com/race/newspaper.html?race_id={race_id}"
    logger.info(f"Fetching bloodline data from: {news_url}")
    news_html = fetch_robust_html(news_url)
    if news_html:
        nsoup = BeautifulSoup(news_html, 'html.parser')
        n_rows = nsoup.select('tr.HorseList')
        for nr in n_rows:
            try:
                n_umaban_tag = nr.select_one('.Umaban')
                if not n_umaban_tag: continue
                n_umaban = n_umaban_tag.text.strip()
                
                if n_umaban in results:
                    blood_info = "-"
                    # Try specific classes often used in Newspaper view
                    sire = nr.select_one('.Sire, .Sire_Name, .Father')
                    bms = nr.select_one('.Bms, .Bms_Name, .Mother_Father')
                    
                    if sire and bms:
                        blood_info = f"{sire.text.strip()} / {bms.text.strip()}"
                    else:
                        # Search for BloodLine class or generic text patterns
                        bl_tag = nr.select_one('.BloodLine, .Horse_Info_Detail')
                        if bl_tag:
                            # Cleanup text: Father \n Mother \n MotherFather
                            parts = [p.strip() for p in bl_tag.text.split('\n') if p.strip()]
                            if len(parts) >= 2:
                                blood_info = f"{parts[0]} / {parts[-1]}" # Assume Father and BMS are ends
                            else:
                                blood_info = bl_tag.text.strip().replace('\n', ' / ')
                    
                    if blood_info != "-":
                        results[n_umaban]['Bloodline'] = blood_info
            except: continue
            
    return results
