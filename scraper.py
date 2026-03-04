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
import time
import random

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
        print(f"Error fetching {url}: {e}")
        return None

def get_race_ids_for_date(date_str=None):
    """Scrapes race IDs for a given date."""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    
    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    
    html = fetch_html(url)
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
    Returns list of dicts: {race_id, race_name, race_num}
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    url = f"https://race.netkeiba.com/top/race_list_sub.html?kaisai_date={date_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # race_list_sub.html is UTF-8 (meta charset=UTF-8)
        html = response.content.decode('utf-8', errors='replace')
    except Exception as e:
        print(f"Error fetching race list: {e}")
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
            # Extract just the "XR" part ignoring nested spans
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
    Fetches HTML content using Playwright to handle JS-rendered pages.
    """
    try:
        import asyncio
        from playwright.async_api import async_playwright
        import sys

        async def fetch():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                # Set a common user agent to avoid some blocks
                await page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})
                await page.goto(url, wait_until='domcontentloaded')
                await page.wait_for_timeout(wait_time)
                content = await page.content()
                await browser.close()
                return content

        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            html = loop.run_until_complete(fetch())
            return html
        finally:
            loop.close()
    except Exception as e:
        print(f"Playwright fetching failed for {url}: {e}")
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
                print(f"人気データ取得成功。{len(results)}件のオッズを取得しました。")
                return results

        # If API returned no data (e.g., before odds open), fallback to HTML scraping
        print(f"オッズ未発表 (status={data.get('status','-')}, reason={data.get('reason','-')}) - API失敗、HTMLから取得を試みます")

        html_url = f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=c99"
        
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
            print("通常のリクエストではオッズが0件でした。JSレンダリング考慮しブラウザを起動して再取得します...")
            pw_html = fetch_html_with_playwright(html_url)
            if pw_html:
                html_results = parse_table_html(pw_html)

        if html_results:
            print(f"HTMLスクレイピング成功。{len(html_results)}件のオッズを取得しました。")
            return html_results

        print("HTMLスクレイピングでもオッズを取得できませんでした。")
        return []

    except Exception as e:
        print(f"Error fetching Sanrenpuku odds: {e}")
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
            return results
    except Exception as e:
        print(f"Error fetching win odds: {e}")
    # If API failed or returned empty results, try HTML scraping with Playwright
    print(f"Win Odds API failed or no data. Trying Playwright fallback...")
    html_url = f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
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
                    print(f"Playwrightスクレイピング成功: {len(results)}件の単勝オッズを取得しました。")
                    return results

    return {}

def fetch_popularity(race_id):
    """
    Fetches real-time popularity ranking from the Top Popularity (上位人気 / type=b0) tab.
    Returns dict: {umaban: int (popularity rank)}
    """
    url = f"https://race.netkeiba.com/odds/index.html?type=b0&race_id={race_id}"
    print(f"Fetching popularity from: {url}")
    
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
        print(f"Playwrightスクレイピング成功: {len(pop_map)}頭の人気順を取得しました。")
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
    Uses Playwright to fetch advanced data: Weight, Training Evaluation, and Pedigree.
    Returns dict: {Umaban: {'WeightStr': str, 'TrainingScore': float, 'BloodlineFlag': str, 'HorseID': str}}
    """
    if top_horse_ids is None:
        top_horse_ids = []
        
    import asyncio
    from playwright.async_api import async_playwright
    import sys
    
    advanced_data = {}

    async def _run_scraper():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            # Check for saved session
            session_path = "auth_session.json"
            if os.path.exists(session_path):
                print(f"Debug: Restoring session from {session_path}")
                context = await browser.new_context(
                    storage_state=session_path,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                )
            else:
                print(f"Debug: No session file found at {session_path}. Run create_session.py first for paywalled data.")
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                )
            page = await context.new_page()
            
            # --- 1. Fetch Weight and HorseID from shutuba.html ---
            shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
            print(f"Debug: Navigating to {shutuba_url}")
            try:
                await page.goto(shutuba_url, wait_until='domcontentloaded', timeout=15000)
                print(f"Debug: Current URL after goto: {page.url}")
                try:
                    await page.wait_for_selector('table.Shutuba_Table, table.RaceTable01', timeout=10000)
                except:
                    print("Debug: Shutuba table not found within timeout")
                
                # --- 1.1 Extract Race Date ASAP (before navigating away) ---
                date_str = ""
                try:
                    # Try og:description meta tag (Very robust)
                    meta_desc_loc = page.locator('meta[property="og:description"]')
                    if await meta_desc_loc.count() > 0:
                        meta_desc = await meta_desc_loc.get_attribute('content', timeout=3000)
                        if meta_desc:
                            m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', meta_desc)
                            if m_date:
                                date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
                    
                    # Try page title
                    if not date_str:
                        title = await page.title()
                        m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', title)
                        if m_date:
                            date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
                    
                    # Fallback to navigation bar
                    if not date_str:
                        nav_loc = page.locator('div.RaceList_DateSelect dd.Active a')
                        if await nav_loc.count() > 0:
                            date_loc = await nav_loc.first.text_content(timeout=3000)
                            if date_loc:
                                m_date = re.search(r'(\d+)月(\d+)日', date_loc)
                                if m_date: date_str = f"{year}{m_date.group(1).zfill(2)}{m_date.group(2).zfill(2)}"
                    
                    print(f"Debug: Extracted date_str: {date_str}")
                except Exception as e:
                    print(f"Debug: date extraction error: {e}")

                rows = await page.locator('table.Shutuba_Table tr.HorseList, table.RaceTable01 tr.HorseList, table.Shutuba_Table tr, table.RaceTable01 tr').all()
                print(f"Debug: Netkeiba rows found: {len(rows)}")
                for row in rows:
                    try:
                        umaban_loc = row.locator('td[class*="Umaban"], td.Umaban, td.umaban')
                        if await umaban_loc.count() > 0:
                            umaban_text = await umaban_loc.first.text_content(timeout=1000)
                            m_num = re.search(r'(\d+)', umaban_text)
                            umaban = int(m_num.group(1)) if m_num else 0
                            
                            weight_loc = row.locator('td.Weight, td.Weight_Info')
                            weight_str = await weight_loc.first.text_content(timeout=1000) if await weight_loc.count() > 0 else ""
                            
                            horse_link_loc = row.locator('td.HorseInfo a, td.Horse_Info a, td.Horse a')
                            horse_id = ""
                            if await horse_link_loc.count() > 0:
                                horse_link = await horse_link_loc.first.get_attribute('href', timeout=1000)
                                if horse_link:
                                    m_id = re.search(r'horse/(\d+)', horse_link)
                                    if m_id: horse_id = m_id.group(1)
                                
                            if umaban > 0 and umaban not in advanced_data:
                                advanced_data[umaban] = {
                                    'WeightStr': weight_str.strip() if weight_str else "",
                                    'TrainingScore': 0.0,
                                    'BloodlineFlag': "",
                                    'TrainingEval': "",
                                    'HorseID': horse_id,
                                    'UIndex': 0.0,
                                    'LaboIndex': 0.0
                                }
                    except Exception as e:
                        pass
                print(f"Debug: advanced_data keys: {list(advanced_data.keys())}")
            except Exception as e:
                print(f"Playwright shutuba error: {e}")

            # --- 2. Fetch Training Evaluation from oikiri.html ---
            oikiri_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
            try:
                await page.goto(oikiri_url, wait_until='domcontentloaded', timeout=20000)
                try:
                    await page.wait_for_selector('table.Oikiri_Table, table.RaceTable01', timeout=5000)
                except: pass
                
                rows = await page.locator('tr.HorseList, table.RaceTable01 tr').all()
                for row in rows:
                    try:
                        umaban_loc = row.locator('td.Umaban, td:first-child')
                        if await umaban_loc.count() > 0:
                            umaban_text = await umaban_loc.first.text_content(timeout=1000)
                            umaban = int(re.search(r'(\d+)', umaban_text).group(1)) if re.search(r'(\d+)', umaban_text) else 0
                            
                            # Robust Training Grade Search
                            eval_str = await row.locator('td[class^="Rank_"], td.OikiriEvaluation, td.sk__rank, td.Evaluation').first.text_content(timeout=2000) if await row.locator('td[class^="Rank_"], td.OikiriEvaluation, td.sk__rank, td.Evaluation').count() > 0 else ""
                            if not eval_str:
                                # Fallback: search all td for A, B, C, D Single characters
                                td_texts = await row.locator('td').all_text_contents()
                                for t in td_texts:
                                    t = t.strip()
                                    if len(t) == 1 and t in "ABCD":
                                        eval_str = t
                                        break
                            
                            eval_str = eval_str.strip().upper() if eval_str else ""
                            match_grade = re.search(r'([A-D])', eval_str)
                            eval_grade = match_grade.group(1) if match_grade else ""

                            score_bonus = 0.0
                            if eval_grade == 'A': score_bonus = 100.0 # Standardize to 100-base for weighting
                            elif eval_grade == 'B': score_bonus = 70.0
                            elif eval_grade == 'C': score_bonus = 40.0
                            elif eval_grade == 'D': score_bonus = 10.0
                            
                            if umaban > 0 and umaban in advanced_data:
                                advanced_data[umaban]['TrainingScore'] = score_bonus
                                advanced_data[umaban]['TrainingEval'] = eval_grade
                    except: pass
            except Exception as e:
                print(f"Playwright oikiri error: {e}")

            # --- 3. Fetch Bloodline for ALL horses in advanced_data ---
            target_horse_ids = [(u, advanced_data[u]['HorseID']) for u in advanced_data if advanced_data[u]['HorseID']]
            for u, h_id in target_horse_ids:
                pedigree_url = f"https://db.netkeiba.com/horse/ped/{h_id}/"
                try:
                    await page.goto(pedigree_url, wait_until='domcontentloaded', timeout=10000)
                    blood_table_loc = page.locator('.blood_table')
                    if await blood_table_loc.count() > 0:
                        blood_table = await blood_table_loc.first.text_content(timeout=3000)
                        blood_table = blood_table if blood_table else ""
                        found_flags = []
                        if 'Nijinsky' in blood_table or 'ニジンスキー' in blood_table: found_flags.append('Nijinsky')
                        if 'Sunday Silence' in blood_table or 'サンデーサイレンス' in blood_table: found_flags.append('SS')
                        if 'Roberto' in blood_table or 'ロベルト' in blood_table: found_flags.append('Roberto')
                        for u, horse_data in advanced_data.items():
                            if horse_data['HorseID'] == h_id:
                                horse_data['BloodlineFlag'] = ",".join(found_flags)
                                print(f"Debug: Horse {u} BloodlineFlag={horse_data['BloodlineFlag']}")
                                break
                except: pass

            # --- 4. Fetch External Indices (U-Index & Labo-Index) ---
            if len(race_id) == 12 and date_str:
                year = race_id[:4]
                venue = race_id[4:6]
                kaisai = race_id[6:8]
                day = race_id[8:10]
                race_num = race_id[10:12]
                
                # Umanity
                u_code = f"{date_str}{venue}{kaisai}{day}{race_num}"
                # The horse list and U-Index are in the iframe contents: race_8_1.php
                u_url = f"https://umanity.jp/racedata/race_8_1.php?code={u_code}"
                print(f"Debug: Fetching Umanity: {u_url}")
                try:
                    await page.goto(u_url, wait_until='load', timeout=30000)
                    await asyncio.sleep(5) 
                    print(f"Debug: Umanity Title: {await page.title()}")
                    
                    rows = await page.locator('tr.odd-row, tr.even-row').all()
                    print(f"Debug: Umanity horse rows total: {len(rows)}")
                    
                    for row in rows:
                        try:
                            cells = await row.locator('td').all()
                            if len(cells) >= 4:
                                u_text = await cells[1].text_content() 
                                val_text = await cells[3].text_content()
                                
                                m_num = re.search(r'(\d+)', u_text or '')
                                if m_num:
                                    u_num = int(m_num.group(1))
                                    if u_num in advanced_data:
                                        m_val = re.search(r'(\d+\.?\d*)', val_text or '')
                                        if m_val:
                                            advanced_data[u_num]['UIndex'] = float(m_val.group(1))
                                            # print(f"Debug: Horse {u_num} UIndex={m_val.group(1)}")
                                        elif "**" in (val_text or ""):
                                            advanced_data[u_num]['UIndex'] = 0.0
                        except: pass
                except Exception as e:
                    print(f"Debug: Umanity error: {e}")

                # Keibalab (Labo Index / Omega Index)
                l_code = f"{date_str}{venue}{race_num}"
                l_url = f"https://www.keibalab.jp/db/race/{l_code}/umabashira.html?kind=yoko"
                print(f"Debug: Fetching Keibalab: {l_url}")
                try:
                    lpage = await context.new_page()
                    await lpage.goto(l_url, wait_until='load', timeout=30000)
                    await asyncio.sleep(5)
                    print(f"Debug: Keibalab Title: {await lpage.title()}")
                    
                    horse_rows = await lpage.locator('tr').all()
                    print(f"Debug: Keibalab tr rows: {len(horse_rows)}")
                    
                    for row in horse_rows:
                        try:
                            umaban_td = row.locator('td.umabanBox')
                            shisu_td = row.locator('td.shisuBox')
                            
                            if await umaban_td.count() > 0 and await shisu_td.count() > 0:
                                u_text = await umaban_td.first.text_content()
                                s_text = await shisu_td.first.text_content()
                                
                                m_num = re.search(r'(\d+)', u_text or '')
                                if m_num:
                                    l_num = int(m_num.group(1))
                                    if l_num in advanced_data:
                                        m_val = re.search(r'(\d+\.?\d*)', s_text or '')
                                        if m_val:
                                            advanced_data[l_num]['LaboIndex'] = float(m_val.group(1))
                                            # print(f"Debug: Horse {l_num} LaboIndex={m_val.group(1)}")
                        except: pass
                    await lpage.close()
                except Exception as e:
                    print(f"Debug: Keibalab error: {e}")

            await browser.close()
            
    import threading

    def _start_async_scraper():
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_scraper())
        finally:
            loop.close()

    thread = threading.Thread(target=_start_async_scraper)
    thread.start()
    thread.join()
        
    return advanced_data

def get_race_data(race_id):
    """Main function to scrape race card data with ROBUST EXTRACTION."""
    # Use shutuba_past.html to ensure we get past performance data
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    print(f"Fetching Race Data: {url}")
    
    html = fetch_html(url)
    if not html: return pd.DataFrame()
    
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
            match_dist = re.search(r'(\d+)m', text01)
            if match_dist:
                race_dist = int(match_dist.group(1))
            
            # Surface
            if '芝' in text01: race_surf = '芝'
            elif 'ダ' in text01: race_surf = 'ダ'
            elif '障' in text01: race_surf = '障'
            
            print(f"Debug: Extracted Distance={race_dist}, Surface={race_surf}")
    
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
    table = soup.find('table', class_='Shutuba_Table')
    if not table:
         table = soup.find('table', class_='RaceTable01')
    
    if not table: return pd.DataFrame()
    
    rows = table.find_all('tr', class_='HorseList')
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
        
        # Umaban
        waku_td = row.find('td', class_='Waku')
        h_data['Umaban'] = int(waku_td.text.strip()) if waku_td and waku_td.text.strip().isdigit() else 0
        
        # Name
        h_info = row.find('td', class_='HorseInfo')
        if not h_info: h_info = row.find('td', class_='Horse_Info')
        if not h_info: continue
        
        name_tag = h_info.find('a', href=re.compile(r'/horse/'))
        if not name_tag: continue
        h_data['Name'] = name_tag.text.strip()
        
        # Jockey
        j_td = row.find('td', class_='Jockey')
        h_data['Jockey'] = j_td.find('a').text.strip() if j_td and j_td.find('a') else ""
        
        # Current Popularity and Win Odds
        # 1. Real-time odds from API or Playwright
        h_data['Odds'] = win_odds_map.get(h_data['Umaban'], 0.0)
        
        # 2. Real-time popularity from type=b0
        h_data['Popularity'] = popularity_map.get(h_data['Umaban'], 99)
        
        # Fallback for Odds/Popularity if real-time fetching failed (extract from shutuba_past.html)
        if h_data['Popularity'] == 99 or h_data['Odds'] == 0.0:
            pop_td = row.find('td', class_='Popular_Ninki')
            if not pop_td: pop_td = row.find('td', class_='Popular')
            
            if pop_td:
                if h_data['Popularity'] == 99:
                    m_pop = re.search(r'(\d+)人気', pop_td.text.strip())
                    if not m_pop: m_pop = re.search(r'(\d+)', pop_td.text.strip())
                    h_data['Popularity'] = int(m_pop.group(1)) if m_pop else 99
                
                if h_data['Odds'] == 0.0:
                    odds_span = pop_td.find('span', class_='Odds')
                    if odds_span:
                        try: h_data['Odds'] = float(odds_span.text.strip())
                        except: pass
                    else:
                        m_odds = re.search(r'(\d+\.\d+)', pop_td.text.strip())
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
        print("Debug: Compiled DataFrame is empty.")
    else:
        print(f"Debug: Compiled DataFrame with {len(df)} horses.")
        
    return df
