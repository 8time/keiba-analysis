import sys
import os
import logging
import pandas as pd

# Set up logging to stdout with UTF-8 encoding
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Ensure current directory is in path
sys.path.append(os.getcwd())

from core import scraper
from core.odds_tracker import OddsTracker

def test_scraper():
    print("\n--- Testing Scraper ---")
    test_url = "https://race.netkeiba.com/top/race_list_sub.html"
    html = scraper.fetch_robust_html(test_url)
    if html and len(html) > 1000:
        print(f"SUCCESS: Fetched {len(html)} bytes from {test_url}")
        # Check if it contains expected strings
        if "レース一覧" in html or "RaceList" in html:
            print("SUCCESS: HTML content looks valid.")
        else:
            print("WARNING: HTML content might be incomplete.")
    else:
        print(f"FAILURE: Could not fetch {test_url}")

def test_odds_tracker():
    print("\n--- Testing OddsTracker ---")
    tracker = OddsTracker(db_path="data/test_odds.db")
    test_race_id = "202606020411" # Dummy-ish ID
    
    print(f"Tracking odds for {test_race_id}...")
    count = tracker.track(test_race_id)
    print(f"Tracked {count} records.")
    
    df = tracker.get_history_df(test_race_id)
    if not df.empty:
        print(f"SUCCESS: Found {len(df)} records in DB.")
        print(df.head())
    else:
        print("INFO: No records found (expected if no active odds).")

if __name__ == "__main__":
    test_scraper()
    test_odds_tracker()
    print("\nVerification Finished.")
