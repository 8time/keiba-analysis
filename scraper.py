import sys, io, os
try:
    # sys.stdout.reconfigure(encoding='utf-8')
    pass
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

def fetch_html(url):
    """Fetches HTML with robust encoding handling."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        content = response.content
        for enc in ['euc-jp', 'shift_jis', 'utf-8']:
            try:
                html = content.decode(enc)
                return html
            except UnicodeDecodeError:
                continue
        return content.decode('euc-jp', errors='replace')
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None

def get_race_ids_for_date(date_str=None):
    """Scrapes race IDs for a given date."""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    
    html = fetch_html_with_playwright(url)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
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
    """Scrapes race IDs + race names for a given date from race_list_sub.html.
    Uses Scrapling via fetch_html_with_playwright to ensure JS is executed.
    Returns list of dicts: {race_id, race_name, race_num}
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    
    html = fetch_html_with_playwright(url)
    if not html:
        logger.warning("Error fetching race list via Scrapling.")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results = []

    items = soup.find_all('li', class_='RaceList_DataItem')
    for item in items:
        link = item.find('a')
        if not link or 'href' not in link.attrs:
            continue
        m = re.search(r'race_id=(\d+)', link['href'])
        if not m:
            continue
        race_id = m.group(1)

        # Race name is in span.ItemTitle
        race_name = ""
        title_span = item.find('span', class_='ItemTitle')
        if title_span:
            race_name = title_span.text.strip()

        # Race number from Race_Num div
        race_num = ""
        num_div = item.find('div', class_='Race_Num')
        if num_div:
            txt = num_div.get_text(strip=True)
            m2 = re.search(r'(\d+R)', txt)
            if m2:
                race_num = m2.group(1)

        results.append({
            "race_id": race_id,
            "race_name": race_name if race_name else race_num or race_id,
            "race_num": race_num,
        })

    return results

def validate_horse_name(name):
    if not name or "系" in name: return False
    return True

def fetch_html_with_playwright(url, wait_time=4000):
    """
    Fetches HTML content via a SUBPROCESS to avoid 'Playwright Sync API inside asyncio loop' error.
    This guarantees no conflict with Streamlit's internal loop.
    """
    import subprocess
    import sys
    
    python_exe = sys.executable 
    # Fallback to the one we know works if sys.executable is the store stub
    if "WindowsApps" in python_exe:
        python_exe = r"C:\Users\kimnhaty\AppData\Local\Programs\Python\Python313\python.exe"
    
    helper_path = os.path.join(os.path.dirname(__file__), "fetch_helper.py")
    
    try:
        # We must use shell=False for safety, and capture output
        # Use env with utf-8 forced too
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        result = subprocess.run(
            [python_exe, helper_path, url],
            capture_output=True,
            text=False, # We receive bytes to handle encoding ourselves
            timeout=120,
            env=env
        )
        
        if result.returncode == 0:
            content = result.stdout
            if not content:
                logger.warning(f"Subprocess returned empty stdout for {url}")
                return None
            
            # Try decoding the result
            for enc in ['utf-8', 'euc-jp', 'shift_jis']:
                try:
                    html = content.decode(enc)
                    if "</html" in html.lower():
                        return html
                except: continue
            return content.decode('utf-8', errors='replace')
        else:
            err_msg = result.stderr.decode('utf-8', errors='replace')
            logger.error(f"Subprocess fetch failed for {url}: {err_msg}")
            return None
    except Exception as e:
        logger.error(f"Error spawning fetch subprocess for {url}: {e}")
        return None

def fetch_sanrenpuku_odds(race_id):
    """
    Fetches Sanrenpuku (Trio / 3連複) odds ordered by popularity.
    Uses the official Netkeiba JRA/NAR odds API with zlib decompression.
    Returns list of {'Combination': str, 'Horses': [int], 'Odds': float, 'Rank': int}
    sorted by popularity (lowest odds first).
    """
    import json, zlib, base64

    # Determine JRA vs NAR
    is_nar = False
    try:
        pid_code = int(str(race_id)[4:6])
        if pid_code > 10:
            is_nar = True
    except: pass

    if is_nar:
        url = "https://nar.netkeiba.com/api/api_get_nar_odds.html"
        pid = "api_get_nar_odds"
        referer = f"https://nar.netkeiba.com/odds/index.html?type=b7&race_id={race_id}"
    else:
        url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
        pid = "api_get_jra_odds"
        referer = f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}"

    params = {
        "pid": pid,
        "race_id": race_id,
        "type": "b7",
        "compress": "1",
        "output": "json",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        data = response.json()

        raw = data.get('data', '')
        if raw and isinstance(raw, str) and len(raw) > 10:
            # Decompress: base64 → zlib inflate → JSON
            decoded = base64.b64decode(raw)
            try:
                decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except:
                decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))

            # odds_data is typically dict with keys like "010203" → odds value
            results = []
            for key, val in odds_data.items():
                if len(key) == 6:
                    try:
                        h1 = int(key[0:2])
                        h2 = int(key[2:4])
                        h3 = int(key[4:6])
                        odds_val = float(val) if val not in ['', '---.-', '0'] else 0.0
                        if odds_val > 0:
                            results.append({
                                'Combination': f"{h1}-{h2}-{h3}",
                                'Horses': [h1, h2, h3],
                                'Odds': odds_val,
                                'Rank': 0
                            })
                    except:
                        continue

            # Sort by odds ascending (≈ popularity order)
            results.sort(key=lambda x: x['Odds'])
            for i, item in enumerate(results):
                item['Rank'] = i + 1

            if results:
                logger.debug(f"人気データ取得成功。{len(results)}件のオッズを取得しました。")
                return results

        # If API returned no data (e.g., before odds open), fallback to HTML scraping
        logger.debug(f"オッズ未発表 (status={data.get('status','-')}, reason={data.get('reason','-')}) - API失敗、HTMLから取得を試みます")

        domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
        html_url = f"https://{domain}/odds/index.html?type=b7&race_id={race_id}&housiki=c99"
        
        def parse_table_html(html_text):
            soup = BeautifulSoup(html_text, 'html.parser')
            parsed_results = []
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                if len(rows) > 5:
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 4:
                            rank_text = cols[0].text.strip()
                            comb_raw = cols[2].text.strip()
                            odds_text = cols[3].text.strip()
                            comb_text = re.sub(r'[\n\s]+', '-', comb_raw)
                            
                            if rank_text.isdigit() and '-' in comb_text and odds_text and '---' not in odds_text:
                                try:
                                    rank = int(rank_text)
                                    odds_val = float(odds_text)
                                    h1, h2, h3 = [int(x.strip()) for x in comb_text.split('-')]
                                    parsed_results.append({
                                        'Combination': f"{h1}-{h2}-{h3}",
                                        'Horses': [h1, h2, h3],
                                        'Odds': odds_val,
                                        'Rank': rank
                                    })
                                except:
                                    continue
            if parsed_results:
                parsed_results.sort(key=lambda x: x['Rank'])
            return parsed_results

        # 1. Try simple requests first (fastest)
        res = requests.get(html_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        res.encoding = res.apparent_encoding if res.apparent_encoding else 'EUC-JP'
        html_results = parse_table_html(res.text)
        
        # 2. If 0 results, try Playwright (handles JS-rendered pages and Cloudflare checks)
        if not html_results:
            logger.debug("通常のリクエストではオッズが0件でした。JSレンダリング考慮しブラウザを起動して再取得します...")
            pw_html = fetch_html_with_playwright(html_url)
            if pw_html:
                html_results = parse_table_html(pw_html)

        if html_results:
            logger.debug(f"HTMLスクレイピング成功。{len(html_results)}件のオッズを取得しました。")
            return html_results

        logger.warning("HTMLスクレイピングでもオッズを取得できませんでした。")
        return []

    except Exception as e:
        logger.error(f"Error fetching Sanrenpuku odds: {e}")
        return []

def fetch_win_odds(race_id):
    """
    Fetches Win (Tansho / 単勝) odds from the Odds/Purchase tab API.
    Returns dict: {umaban: float}
    """
    import json, zlib, base64
    
    is_nar = False
    try:
        if int(str(race_id)[4:6]) > 10: is_nar = True
    except: pass

    if is_nar:
        url = "https://nar.netkeiba.com/api/api_get_nar_odds.html"
        pid = "api_get_nar_odds"
    else:
        url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
        pid = "api_get_jra_odds"

    params = {"pid": pid, "race_id": race_id, "type": "b1", "compress": "1", "output": "json"}
    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}

    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        data = res.json()
        raw = data.get('data', '')
        if raw and isinstance(raw, str) and len(raw) > 10:
            decoded = base64.b64decode(raw)
            try: decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except: decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))
            
            results = {}
            for k, v in odds_data.items():
                if len(k) == 2:  # Umaban like "01", "02"
                    try:
                        u = int(k)
                        results[u] = float(v) if v and v not in ['---.-', '0'] else 0.0
                    except: pass
            return pd.Series(results)
    except Exception as e:
        logger.error(f"Error fetching win odds: {e}")
        return pd.Series({})
    # If API failed or returned empty results, try HTML scraping with Playwright
    if data is None or 'data' not in data:
        logger.warning("Win Odds API failed or no data. Trying Playwright fallback...")
    
    sub = "nar" if is_nar else "race"
    html_url = f"https://{sub}.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
    pw_html = fetch_html_with_playwright(html_url)
    
    if pw_html:
        soup = BeautifulSoup(pw_html, 'html.parser')
        results = {}
        # Find the Win Odds table (usually the first one with "単勝" in header or standard classes)
        # Based on rendered dump, it's often a table with standard columns
        for table in soup.find_all('table'):
            if "馬番" in table.text and ("単勝" in table.text or "オッズ" in table.text):
                for row in table.find_all('tr'):
                    cols = row.find_all('td')
                    if len(cols) >= 5: # Waku, Umaban, Mark, Select, Name, Odds
                        try:
                            u_text = cols[1].text.strip()
                            o_text = cols[5].text.strip()
                            if u_text.isdigit():
                                u = int(u_text)
                                m = re.search(r'(\d+\.\d+)', o_text)
                                if m:
                                    results[u] = float(m.group(1))
                        except: continue
                if results:
                    logger.debug(f"Playwrightスクレイピング成功: {len(results)}件の単勝オッズを取得しました。")
                return pd.Series(results)

    return pd.Series({})

def fetch_popularity(race_id):
    """
    Fetches real-time popularity ranking from the Top Popularity (上位人気 / type=b0) tab.
    Returns dict: {umaban: int (popularity rank)}
    """
    is_nar = False
    try:
        if int(str(race_id)[4:6]) > 10: is_nar = True
    except: pass
    
    sub = "nar" if is_nar else "race"
    url = f"https://{sub}.netkeiba.com/odds/index.html?race_id={race_id}"
    logger.debug(f"Fetching popularity from: {url}")
    
    # This page is almost entirely JS-rendered
    pw_html = fetch_html_with_playwright(url)
    if not pw_html: return {}
    
    soup = BeautifulSoup(pw_html, 'html.parser')
    pop_map = {}
    
    # Look for the table in type=b0
    # Structure: 0: Popularity Rank, 1: Waku, 2: Umaban, 3: Mark, 4: Name, 5: Win Odds...
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) < 5: continue
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                try:
                    pop_text = cols[0].text.strip()
                    umaban_text = cols[2].text.strip()
                    if pop_text.isdigit() and umaban_text.isdigit():
                        pop_map[int(umaban_text)] = int(pop_text)
                except: continue
                
    if pop_map:
        logger.debug(f"Playwrightスクレイピング成功: {len(pop_map)}頭の人気順を取得しました。")
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
    html = fetch_html(url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser')
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
    helper_path = os.path.join(os.path.dirname(__file__), "adv_fetch_helper.py")
    
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
        
    return advanced_data

def get_race_data(race_id):
    """Main function to scrape race card data with ROBUST EXTRACTION."""
    # Determine JRA vs NAR
    is_nar = False
    try:
        if int(str(race_id)[4:6]) > 10:
            is_nar = True
    except: pass

    if is_nar:
        # NAR uses shutuba.html on nar subdomain
        url = f"https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"
    else:
        # JRA uses shutuba_past.html for better historic data coverage
        url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
        
    logger.info(f"Fetching {'NAR' if is_nar else 'JRA'} Race Data: {url}")
    
    html = fetch_html_with_playwright(url)
    if not html: return pd.DataFrame()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Check if we got an empty entry table (happens if shutuba_past.html isn't ready)
    if not is_nar and not soup.find('tr', class_='HorseList'):
        logger.info("shutuba_past.html appears empty or not ready. Falling back to standard shutuba.html.")
        url_fallback = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        html_fallback = fetch_html_with_playwright(url_fallback)
        if html_fallback:
            html = html_fallback
            soup = BeautifulSoup(html, 'html.parser')
    
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
        # On shutuba_past.html: <td class="Waku">1</td> is Umaban, <td class="Waku1"> is Waku.
        # On shutuba.html: <td class="Umaban"> is Umaban.
        # Use exact match ^...$ to prevent catching 'Waku1' (the bracket column) as the horse number.
        uma_td = row.find('td', class_=re.compile(r'^(?:Umaban|umaban|Waku|Num)$'))
        if uma_td:
            m_uma = re.search(r'(\d+)', uma_td.text.strip())
            h_data['Umaban'] = int(m_uma.group(1)) if m_uma else 0
        else:
            # Fallback for bracket-based pages: Umaban might be the second numeric td
            numeric_tds = [td for td in row.find_all('td') if td.text.strip().isdigit()]
            if len(numeric_tds) >= 2:
                h_data['Umaban'] = int(numeric_tds[1].text.strip())
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
        
        # Current Popularity and Win Odds
        # 1. Real-time odds from API or Playwright
        h_data['Odds'] = win_odds_map.get(h_data['Umaban'], 0.0)
        
        # 2. Real-time popularity from type=b0
        h_data['Popularity'] = popularity_map.get(h_data['Umaban'], 99)
        
        # Fallback for Odds/Popularity if real-time fetching failed (extract from shutuba_past.html)
        if h_data['Popularity'] == 99 or h_data['Odds'] == 0.0:
            pop_td = row.find('td', class_=re.compile(r'Popular|Popularity|Ninki'))
            if pop_td:
                txt = pop_td.text.strip()
                if h_data['Popularity'] == 99:
                    m_pop = re.search(r'(\d+)', txt)
                    h_data['Popularity'] = int(m_pop.group(1)) if m_pop else 99
                
                if h_data['Odds'] == 0.0:
                    m_odds = re.search(r'(\d+\.\d+)', txt)
                    if m_odds: h_data['Odds'] = float(m_odds.group(1))

        # --- Past Runs Extraction ---
        past_runs = []
        past_tds = row.find_all('td', class_=re.compile(r'Past'))
        
        for p_td in past_tds:
            run = {
                'Rank': 99, 'Time': 0, 'Distance': 0, 'Surface': '', 
                'Agari': 0.0, 'AgariType': 'Imputed', 'Passing': '8-8', 
                'PassingType': 'Imputed', 'Grade': 'OP', 'Date': '2000.01.01',
                'Condition': '良', 'Popularity': 99, 'TimeIndexRank': 99
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
                else: run['Grade'] = 'OP'

            # Data04 (Popularity/Odds)
            d04 = p_td.find('div', class_='Data04')
            if d04:
                # Popularity is often like "3人気"
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

            # Data07 (Horse weight, and often Margin e.g. "0.6")
            d07 = p_td.find('div', class_='Data07')
            if d07:
                t07 = d07.text.strip()
                m_mar = re.search(r'(\d+\.\d+)', t07)
                if m_mar:
                    run['Margin'] = float(m_mar.group(1))
                else:
                    run['Margin'] = 9.9 # Safe default if missing
            
            past_runs.append(run)
        
        h_data['PastRuns'] = past_runs
        horses.append(h_data)
        
    df = pd.DataFrame(horses)
    if df.empty:
        logger.warning("Debug: Compiled DataFrame is empty.")
    else:
        logger.info(f"Debug: Compiled DataFrame with {len(df)} horses.")
        
    return df
