import os
import json
import zlib
import base64
import time
import re
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup
import logging

# Configure logger
logger = logging.getLogger(__name__)

class OddsFetcher:
    """
    Fetches odds data from Netkeiba using API and Scraping.
    Ensures UTF-8 handling and robust error recovery.
    """
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _get_api_data(self, url, params, referer):
        headers = self.headers.copy()
        headers["Referer"] = referer
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            print(f"DEBUG: URL={response.url} Status={response.status_code}")
            if response.status_code != 200:
                logger.warning(f"API Error: Status {response.status_code} for {url}")
                return None
            
            data = response.json()
            # print(f"DEBUG: Response JSON keys: {list(data.keys())}")
            
            # NAR uses 'ary_odds' instead of 'data'
            if 'ary_odds' in data:
                return data['ary_odds']
                
            raw = data.get('data', '')
            if not raw or not isinstance(raw, str) or len(raw) < 10:
                print(f"DEBUG: 'data' field is empty or too short. Length: {len(raw) if raw else 0}")
                return None
                
            # Decompress: base64 → zlib inflate → JSON
            decoded = base64.b64decode(raw)
            try:
                decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except:
                decompressed = zlib.decompress(decoded)
            
            return json.loads(decompressed.decode('utf-8'))
        except Exception as e:
            logger.error(f"Failed to fetch or decompress API data: {e}")
            return None

    def _get_horse_mapping(self, race_id, is_nar):
        """Fetches Umaban to KettoNum mapping from shutuba page."""
        sub = "nar" if is_nar else "race"
        url = f"https://{sub}.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            response = requests.get(url, headers=self.headers, timeout=15)
            # Netkeiba uses EUC-JP for many pages
            for enc in ['euc-jp', 'utf-8', 'shift_jis']:
                try:
                    html = response.content.decode(enc)
                    if "</html" in html.lower(): break
                except: continue
            else:
                html = response.content.decode('utf-8', errors='replace')
                
            soup = BeautifulSoup(html, 'html.parser')
            mapping = {} # KettoNum -> Umaban
            
            # Find all horse links
            for a in soup.find_all('a', href=True):
                if '/horse/' in a['href']:
                    # href looks like https://db.netkeiba.com/horse/2021105030/
                    m = re.search(r'/horse/(\d+)', a['href'])
                    if m:
                        k_num = m.group(1)
                        # Find umaban in the same row or nearby
                        # Usually the parent or sibling cell contains the umaban
                        row = a.find_parent('tr')
                        if row:
                            umaban_td = row.find('td', class_=re.compile(r'Umaban|umaban'))
                            if not umaban_td:
                                # Try to find the second column usually
                                tds = row.find_all('td')
                                if len(tds) > 2:
                                    # Umaban is usually in idx 1 or 2
                                    for td in tds[:4]:
                                        txt = td.get_text(strip=True)
                                        if txt.isdigit():
                                            mapping[k_num] = int(txt)
                                            break
            return mapping
        except Exception as e:
            logger.error(f"Failed to fetch horse mapping: {e}")
            return {}

    def fetch_win_show_popularity(self, race_id):
        """
        Fetches Win, Show, and Popularity ranking.
        Returns a list of dicts: [{'umaban', 'win_odds', 'show_min', 'show_max', 'pop'}]
        """
        is_nar = False
        try:
            pid_code = int(str(race_id)[4:6])
            if pid_code > 10: is_nar = True
        except: pass

        if is_nar:
            url = "https://nar.netkeiba.com/api/api_get_nar_odds.html"
            pid = "api_get_nar_odds"
            referer = f"https://nar.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
        else:
            url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
            pid = "api_get_jra_odds"
            referer = f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"

        params = {"pid": pid, "race_id": race_id, "type": "b1", "compress": "1", "output": "json"}
        odds_data = self._get_api_data(url, params, referer)
        if not odds_data:
            return []

        results = []
        
        # Handle NAR case (KettoNum keyed)
        if is_nar and 'KettoNum' in odds_data:
            mapping = self._get_horse_mapping(race_id, True)
            ketto_dict = odds_data['KettoNum']
            for k_num, vals in ketto_dict.items():
                u = mapping.get(k_num)
                if u is None: continue
                
                # NAR API Win/Show info
                # Some NAR APIs return a dict per horse
                if isinstance(vals, dict):
                    win = float(vals.get('Odds', 0.0))
                    pop = int(vals.get('Ninki', 99))
                    # Show odds might be split or missing in this JSON
                    results.append({
                        "umaban": u, "win": win, "show_min": 0.0, "show_max": 0.0, "pop": pop
                    })
        else:
            # Handle JRA case (Umaban keyed)
            for umaban_str, vals in odds_data.items():
                if len(umaban_str) != 2 or not umaban_str.isdigit():
                    continue
                try:
                    win = float(vals[0]) if len(vals) > 0 and vals[0] not in ['', '---.-', '0'] else 0.0
                    show_min = float(vals[1]) if len(vals) > 1 and vals[1] not in ['', '---.-', '0'] else 0.0
                    show_max = float(vals[2]) if len(vals) > 2 and vals[2] not in ['', '---.-', '0'] else 0.0
                    pop = int(vals[3]) if len(vals) > 3 and vals[3] not in ['', '0'] else 99
                    results.append({
                        "umaban": int(umaban_str),
                        "win": win, "show_min": show_min, "show_max": show_max, "pop": pop
                    })
                except: continue
        
        return results

class OddsLogger:
    """
    Handles time-series logging of odds data into JSON Lines files.
    """
    
    def __init__(self, base_dir="data"):
        self.base_dir = base_dir
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

    def log_odds(self, race_id, odds_list):
        """
        odds_list: list of dicts from OddsFetcher.
        """
        if not odds_list:
            return
            
        timestamp = datetime.now().isoformat()
        filepath = os.path.join(self.base_dir, f"odds_history_{race_id}.jsonl")
        
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                for entry in odds_list:
                    # Enrich entry with metadata
                    log_entry = {
                        "timestamp": timestamp,
                        "race_id": str(race_id),
                        **entry
                    }
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            logger.info(f"Logged {len(odds_list)} records for race {race_id} at {timestamp}")
        except Exception as e:
            logger.error(f"Failed to write odds log: {e}")

if __name__ == "__main__":
    # Test execution
    logging.basicConfig(level=logging.INFO)
    fetcher = OddsFetcher()
    logger_obj = OddsLogger()
    
    test_id = "202608020211" 
    data = fetcher.fetch_win_show_popularity(test_id)
    if data:
        logger_obj.log_odds(test_id, data)
        print(f"Test logged {len(data)} horses.")
    else:
        print("No data fetched.")
