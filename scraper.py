import sys, io
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

def validate_horse_name(name):
    if not name or "系" in name: return False
    return True

def _extract_speed_index(td):
    """Extract the actual speed index value from a td cell.
    Cells often contain concatenated text like '1086\n86' or '1086\n86*'.
    We want the actual index (< 200)."""
    if not td: return 0.0
    text = td.text.strip()
    lines = text.split('\n')
    for line in reversed(lines):
        cleaned = re.sub(r'[^0-9.]', '', line.strip())
        if cleaned:
            try:
                val = float(cleaned)
                if val < 200:  # Index should be < 200
                    return val
            except:
                continue
    return 0.0

def fetch_time_index_values(race_id):
    """Fetches Time Index data from speed.html.
    Returns dict: {umaban: {'AvgIndex': float, 'MaxIndex': float, 'Index1': float, 'Index2': float, 'Index3': float}}
    Note: speed.html is partially JS-rendered, so only some horses may be returned.
    """
    url = f"https://race.netkeiba.com/race/speed.html?race_id={race_id}"
    html = fetch_html(url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser')
    data_map = {}
    
    rows = soup.find_all('tr', class_='HorseList')
    for row in rows:
        umaban_td = row.find('td', class_='sk__umaban')
        if not umaban_td: continue
        try:
            uma_text = umaban_td.text.strip()
            if not uma_text.isdigit(): continue
            umaban = int(uma_text)
            
            avg_idx = _extract_speed_index(row.find('td', class_='sk__average_index'))
            max_idx = _extract_speed_index(row.find('td', class_='sk__max_index'))
            idx1 = _extract_speed_index(row.find('td', class_='sk__index1'))
            idx2 = _extract_speed_index(row.find('td', class_='sk__index2'))
            idx3 = _extract_speed_index(row.find('td', class_='sk__index3'))
            
            data_map[umaban] = {
                'AvgIndex': avg_idx,
                'MaxIndex': max_idx,
                'Index1': idx1,
                'Index2': idx2,
                'Index3': idx3
            }
        except:
            continue
    return data_map

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

        # If API returned no data (e.g., before odds open), return empty
        print(f"オッズ未発表 (status={data.get('status','-')}, reason={data.get('reason','-')})")
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
    return {}

def fetch_netkeiba_time_avg(race_id):
    """
    Fetches Time Index (5-run average) from time.html.
    This is the data visible for free users (typically 3 horses).
    Returns dict: {umaban: float}
    """
    url = f"https://race.netkeiba.com/race/time.html?race_id={race_id}"
    html = fetch_html(url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser')
    data_map = {}
    
    # Table search
    table = soup.find('table', class_='RaceTable01')
    if not table: return {}
    
    rows = table.find_all('tr', class_='HorseList')
    for row in rows:
        try:
            # Horse Number (Umaban)
            umaban_td = row.find('td', class_='Umaban')
            if not umaban_td: continue
            umaban = int(umaban_td.text.strip())
            
            # 5-Run Average Index (Av_TimeIndex)
            avg_td = row.find('td', class_='Av_TimeIndex')
            if avg_td:
                text = avg_td.text.strip()
                # Check if it's a numeric value (skip if it contains premium markers)
                match = re.search(r'(\d+\.\d+)', text)
                if match:
                    data_map[umaban] = float(match.group(1))
        except:
            continue
            
    return data_map

def fetch_race_result(race_id):
    """
    Fetches actual race results from result.html.
    Returns dict: {HorseName: {'Rank': int, 'ResultOdds': float, 'Agari': float}}
    """
    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
    html = fetch_html(url)
    if not html: return {}
    
    soup = BeautifulSoup(html, 'html.parser')
    results = {}
    
    # Find result table
    table = soup.find('table', class_='RaceTable01')
    if not table:
        table = soup.find('table', class_='Shutuba_Table')
    if not table:
        # Try any table with result rows
        tables = soup.find_all('table')
        for t in tables:
            if t.find('tr', class_='HorseList'):
                table = t
                break
    
    if not table: return {}
    
    rows = table.find_all('tr', class_='HorseList')
    for row in rows:
        try:
            # Horse Name
            name_tag = row.find('a', href=re.compile(r'/horse/'))
            if not name_tag: continue
            name = name_tag.text.strip()
            
            # Rank (着順)
            rank = 99
            rank_td = row.find('td', class_='Rank')
            if not rank_td:
                # Try first td
                tds = row.find_all('td')
                if tds:
                    rank_text = tds[0].text.strip()
                    m = re.search(r'(\d+)', rank_text)
                    if m: rank = int(m.group(1))
            else:
                m = re.search(r'(\d+)', rank_td.text.strip())
                if m: rank = int(m.group(1))
            
            # Odds (単勝オッズ)
            result_odds = 0.0
            odds_td = row.find('td', class_='Odds')
            if odds_td:
                m = re.search(r'(\d+\.?\d*)', odds_td.text.strip())
                if m: result_odds = float(m.group(1))
            
            # Agari (上がり3F)
            agari = 0.0
            # Look for Agari in various possible locations
            all_tds = row.find_all('td')
            for td in all_tds:
                text = td.text.strip()
                m = re.search(r'^(\d{2}\.\d)$', text)
                if m:
                    val = float(m.group(1))
                    if 33.0 <= val <= 42.0:
                        agari = val
            
            results[name] = {
                'Rank': rank,
                'ResultOdds': result_odds,
                'Agari': agari
            }
        except Exception as e:
            continue
    
    if results:
        print(f"[OK] Race results fetched: {len(results)} horses from {race_id}")
    else:
        print(f"[NG] No results parsed from {race_id}")
    
    return results

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
    time_index_map = fetch_time_index_values(race_id)
    time_avg_map = fetch_netkeiba_time_avg(race_id) # NEW: 5-run average
    win_odds_map = fetch_win_odds(race_id) # API "Odds/Purchase" tab data
    
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
        
        # NEW: Time Index (5-run average)
        h_data['TimeIndexAvg5'] = time_avg_map.get(h_data['Umaban'], 0.0)
        
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
        pop_td = row.find('td', class_='Popular_Ninki')
        if not pop_td: pop_td = row.find('td', class_='Popular')
        
        # 1. Real-time odds from API ("Odds/Purchase" tab)
        h_data['Odds'] = win_odds_map.get(h_data['Umaban'], 0.0)
        
        # 2. Extract Popularity
        if pop_td:
            m_pop = re.search(r'(\d+)人気', pop_td.text.strip())
            if not m_pop: m_pop = re.search(r'(\d+)', pop_td.text.strip())
            h_data['Popularity'] = int(m_pop.group(1)) if m_pop else 99
            
            # Fallback for Odds if API failed (extract from shutuba_past.html)
            if h_data['Odds'] == 0.0:
                odds_span = pop_td.find('span', class_='Odds')
                if odds_span:
                    try: h_data['Odds'] = float(odds_span.text.strip())
                    except: pass
                else:
                    m_odds = re.search(r'(\d+\.\d+)', pop_td.text.strip())
                    if m_odds: h_data['Odds'] = float(m_odds.group(1))
        else:
            h_data['Popularity'] = 99

        # Time Index Logic (from speed.html)
        if h_data['Umaban'] in time_index_map:
            ti_data = time_index_map[h_data['Umaban']]
            h_data['TimeIndexAvg'] = ti_data.get('AvgIndex', 0.0)
            h_data['TimeIndexMax'] = ti_data.get('MaxIndex', 0.0)
            h_data['TimeIndexLast'] = ti_data.get('Index1', 0.0)
            # Add Top 3 Time Index check for current race (rank from speed.html)
            # We'll assume rank 1-3 if the Index1 is high relative to others, 
            # but speed.html rank is safer.
            h_data['TimeIndexRank'] = ti_data.get('Rank', 99)
        else:
            h_data['TimeIndexAvg'] = 0.0
            h_data['TimeIndexMax'] = 0.0
            h_data['TimeIndexLast'] = 0.0
            h_data['TimeIndexRank'] = 99
            
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
                
                # Dist/Surf
                m_ds = re.search(r'([芝ダ障].*?)(\d+)', t05)
                if m_ds:
                    run['Surface'] = m_ds.group(1)
                    run['Distance'] = int(m_ds.group(2))
                
                # Time Extraction
                m_tm = re.search(r'(\d{1,2}:\d{2}\.\d|\d{2,3}\.\d)', t05)
                if m_tm:
                    ts = m_tm.group(1)
                    try:
                        if ':' in ts:
                            mm, ss = ts.split(':')
                            run['Time'] = int(mm)*60 + float(ss)
                        else:
                            run['Time'] = float(ts)
                    except: pass
                    
                # Condition
                if '良' in t05: run['Condition'] = '良'
                elif '稍' in t05: run['Condition'] = '稍重'
                elif '重' in t05: run['Condition'] = '重'
                elif '不' in t05: run['Condition'] = '不良'
                else: run['Condition'] = '良'

            # --- ROBUST AGARI EXTRACTION ---
            agari_cands = []
            matches = re.findall(r'(?<![:\d])(\d{2}\.\d)', full_text)
            for m in matches:
                try:
                    val = float(m)
                    if 33.0 <= val <= 42.0:
                        agari_cands.append(val)
                except: pass
            
            if agari_cands:
                run['Agari'] = sum(agari_cands)/len(agari_cands)
                run['AgariType'] = 'Real'
            else:
                run['Agari'] = 35.0
                run['AgariType'] = 'Imputed'

            # --- ROBUST POSITION EXTRACTION ---
            m_pos = re.findall(r'(\d{1,2})(?:-\d{1,2})+', full_text)
            if m_pos:
                try:
                    run['Passing'] = str(m_pos[0])
                    run['PassingType'] = 'Real'
                except: pass
            else:
                run['Passing'] = "8-8"
                run['PassingType'] = 'Imputed'

            past_runs.append(run)
            
        h_data['PastRuns'] = past_runs
        horses.append(h_data)
        
    return pd.DataFrame(horses)
