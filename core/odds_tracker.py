import os
import sqlite3
import requests
import json
import base64
import zlib
import time
from datetime import datetime
from functools import wraps
import pandas as pd
import numpy as np
import logging
from bs4 import BeautifulSoup
import re

# Configure logging
logger = logging.getLogger(__name__)

def retry(tries=3, delay=1, backoff=2, exceptions=(sqlite3.OperationalError, Exception)):
    """Retry decorator for unstable operations (e.g. DB locks)."""
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

# Configure logging
logger = logging.getLogger(__name__)

class OddsTracker:
    def __init__(self, db_path="data/odds_history.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite database and creates the table if it doesn't exist."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS odds_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id TEXT,
                umaban INTEGER,
                odds_type TEXT,
                odds_value REAL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # Add index for faster queries
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_race_id ON odds_logs (race_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON odds_logs (timestamp)')
        conn.commit()
        conn.close()

    def fetch_api_odds(self, race_id, odds_type="b1"):
        """Fetches raw odds using scraper.fetch_realtime_odds_api (Scrapling/curl_cffi).
        Returns {umaban_zfill2: {Odds, Popularity}} or None."""
        try:
            from core.scraper import fetch_realtime_odds_api
            data = fetch_realtime_odds_api(race_id)
            if data:
                return data
        except Exception as e:
            logger.warning(f"fetch_realtime_odds_api failed for {race_id}: {e}")
        return None

    def get_win_show_odds(self, race_id):
        """Parses Win/Show/Popularity odds via scraper, with HTML fallback."""
        results = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # ── Priority 1: fetch_realtime_odds_api (Scrapling) ──
        api_data = self.fetch_api_odds(race_id)
        if api_data:
            sorted_by_odds = sorted(
                [(int(u), d) for u, d in api_data.items() if d.get('Odds', 0) > 0],
                key=lambda x: x[1]['Odds']
            )
            pop_rank = {uma: rank + 1 for rank, (uma, _) in enumerate(sorted_by_odds)}
            for u_str, d in api_data.items():
                try:
                    u = int(u_str)
                    o_val = float(d.get('Odds', 0.0))
                    if o_val > 0:
                        results.append({"race_id": str(race_id), "umaban": u, "odds_type": "win", "odds_value": o_val, "timestamp": now})
                    pop = int(d.get('Popularity', pop_rank.get(u, 99)))
                    results.append({"race_id": str(race_id), "umaban": u, "odds_type": "pop", "odds_value": float(pop), "timestamp": now})
                except:
                    continue

        # ── Priority 2: HTML fallback (fetch_robust_html + BeautifulSoup) ──
        if not results:
            logger.info(f"API returned nothing for {race_id}, trying HTML fallback...")
            try:
                from core import scraper
                is_nar = scraper._is_nar(race_id)
                domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
                url = f"https://{domain}/odds/index.html?type=b1&race_id={race_id}"
                html = scraper.fetch_robust_html(url)
                if html:
                    soup = BeautifulSoup(html, 'html.parser')
                    for row in soup.find_all('tr', class_='HorseList'):
                        cols = row.find_all('td')
                        if len(cols) < 6:
                            continue
                        try:
                            u_text = cols[1].get_text(strip=True)
                            m_uma = re.search(r'(\d+)', u_text)
                            if not m_uma:
                                continue
                            u = int(m_uma.group(1))
                            # Win odds
                            m_win = re.search(r'(\d+\.?\d*)', cols[5].get_text(strip=True))
                            if m_win:
                                results.append({"race_id": str(race_id), "umaban": u, "odds_type": "win", "odds_value": float(m_win.group(1)), "timestamp": now})
                            # Show odds
                            if len(cols) >= 7:
                                p_show = re.findall(r'(\d+\.?\d*)', cols[6].get_text(strip=True))
                                if len(p_show) >= 1:
                                    results.append({"race_id": str(race_id), "umaban": u, "odds_type": "show_min", "odds_value": float(p_show[0]), "timestamp": now})
                                if len(p_show) >= 2:
                                    results.append({"race_id": str(race_id), "umaban": u, "odds_type": "show_max", "odds_value": float(p_show[1]), "timestamp": now})
                        except:
                            continue
                    # Derive popularity from win odds if HTML fallback
                    win_recs = [r for r in results if r['odds_type'] == 'win']
                    for rank, rec in enumerate(sorted(win_recs, key=lambda x: x['odds_value']), 1):
                        results.append({"race_id": str(race_id), "umaban": rec['umaban'], "odds_type": "pop", "odds_value": float(rank), "timestamp": now})
            except Exception as e:
                logger.error(f"HTML fallback failed for {race_id}: {e}")

        return results

    def track(self, race_id, ticket_types=None):
        """
        Fetches and saves target odds for a race_id.
        ticket_types: list of 'b1' (Win/Show), 'b3' (Quinella), 'b7' (Trio), etc.
        """
        if ticket_types is None:
            ticket_types = ["b1"] # Default to Win/Show
            
        logger.info(f"Tracking odds for {race_id} (types: {ticket_types})...")
        
        all_records = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for ttype in ticket_types:
            if ttype == "b1":
                win_show = self.get_win_show_odds(race_id)
                if win_show:
                    all_records.extend(win_show)
                    # Derive Popularity
                    win_odds = [r for r in win_show if r['odds_type'] == 'win' and r['odds_value'] > 0]
                    if win_odds:
                        sorted_win = sorted(win_odds, key=lambda x: x['odds_value'])
                        for rank, record in enumerate(sorted_win, 1):
                            all_records.append({
                                "race_id": str(race_id),
                                "umaban": record['umaban'],
                                "odds_type": "pop",
                                "odds_value": float(rank),
                                "timestamp": now
                            })
            else:
                # Other types: b3 (Quinella), b7 (Trio), etc.
                raw_data = self.fetch_api_odds(race_id, ttype)
                if raw_data:
                    for comb, val in raw_data.items():
                        try:
                            odds_val = float(val) if val and val not in ['---.-', '0'] else 0.0
                            if odds_val > 0:
                                all_records.append({
                                    "race_id": str(race_id),
                                    "umaban": 0, # Use 0 or special code for combinations
                                    "odds_type": f"raw_{ttype}_{comb}",
                                    "odds_value": odds_val,
                                    "timestamp": now
                                })
                        except: continue
        
        if all_records:
            self.save_to_db(all_records)
            return len(all_records)
        return 0

    @retry(tries=5, delay=1, exceptions=(sqlite3.OperationalError,))
    def save_to_db(self, records):
        """Inserts multiple records into SQLite with retry for locked DB."""
        if not records: return
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            data_to_insert = [
                (r['race_id'], r['umaban'], r['odds_type'], r['odds_value'], r['timestamp'])
                for r in records
            ]
            
            cursor.executemany('''
                INSERT INTO odds_logs (race_id, umaban, odds_type, odds_value, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', data_to_insert)
            
            conn.commit()
            conn.close()
            logger.debug(f"Saved {len(records)} records to {self.db_path}")
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                logger.warning(f"Database is locked, retry should handle this: {e}")
            raise # Re-raise for fallback/retry
        except Exception as e:
            logger.error(f"Error saving to DB: {e}")
            raise

    def get_history_df(self, race_id):
        """Retrieves and returns history for a specific race as a DataFrame."""
        try:
            conn = sqlite3.connect(self.db_path)
            query = "SELECT * FROM odds_logs WHERE race_id = ? ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, params=(str(race_id),))
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Error reading history from DB: {e}")
            return pd.DataFrame()

    def get_all_races_history_df(self):
        """全てのレースの履歴をデバッグ用に取得する。"""
        try:
            conn = sqlite3.connect(self.db_path)
            query = "SELECT * FROM odds_logs ORDER BY timestamp DESC LIMIT 100"
            df = pd.read_sql_query(query, conn)
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Error reading all history from DB: {e}")
            return pd.DataFrame()

    def get_latest_odds_df(self, race_id):
        """
        最新のオッズスナップショットを分析用 DataFrame 形式で取得する。
        SQLで (umaban, odds_type) ごとの最新値を集約し、pandas pivot を一切使わない。
        """
        try:
            conn = sqlite3.connect(self.db_path)
            # GROUP BY で各(umaban, odds_type)の最新1件だけ取得
            query = """
                SELECT umaban, odds_type, odds_value
                FROM odds_logs
                WHERE race_id = ?
                  AND id IN (
                      SELECT MAX(id)
                      FROM odds_logs
                      WHERE race_id = ?
                      GROUP BY umaban, odds_type
                  )
                ORDER BY umaban ASC
            """
            rows = conn.execute(query, (str(race_id), str(race_id))).fetchall()
            conn.close()
        except Exception as e:
            logger.error(f"get_latest_odds_df SQL error: {e}")
            return pd.DataFrame()

        if not rows:
            return pd.DataFrame()

        col_rename = {
            'win': 'Win Odds',
            'pop': 'Popularity',
            'show_min': 'Show Odds (Min)',
            'show_max': 'Show Odds (Max)',
        }
        # 手動でwide形式に変換（pivot完全不使用）
        records = {}
        for umaban, odds_type, odds_value in rows:
            u = int(umaban)
            col = col_rename.get(str(odds_type), str(odds_type))
            if u not in records:
                records[u] = {'Umaban': u}
            records[u][col] = float(odds_value) if odds_value is not None else float('nan')

        result_df = pd.DataFrame(list(records.values())).sort_values('Umaban').reset_index(drop=True)

        for col in ('Win Odds', 'Popularity', 'Show Odds (Min)', 'Show Odds (Max)'):
            if col not in result_df.columns:
                result_df[col] = float('nan')

        return result_df

if __name__ == "__main__":
    # Test execution
    logging.basicConfig(level=logging.INFO)
    tracker = OddsTracker()
    test_id = "202606020411" # Use a known ID for testing structure (even if it returns no data now)
    count = tracker.track(test_id)
    print(f"Tracked {count} records.")
    
    df = tracker.get_history_df(test_id)
    print(df.head())
