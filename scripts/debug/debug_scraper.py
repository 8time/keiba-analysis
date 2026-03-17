
import os
import sys

# Add current directory to path
sys.path.append(os.getcwd())

from core import scraper
import pandas as pd

def debug_race(race_id):
    print(f"--- Debugging Race ID: {race_id} ---")
    
    print("Testing fetch_win_odds...")
    odds = scraper.fetch_win_odds(race_id)
    print(f"Odds Map: {odds.to_dict() if not odds.empty else 'EMPTY'}")
    
    print("\nTesting fetch_popularity...")
    pop = scraper.fetch_popularity(race_id)
    print(f"Pop Map: {pop}")
    
    print("\nTesting get_race_data (Live)...")
    df = scraper.get_race_data(race_id, use_storage=False)
    if not df.empty:
        print(f"DF Head (Umaban, Name, Pop, Odds):\n{df[['Umaban', 'Name', 'Popularity', 'Odds']].head(10)}")
    else:
        print("DF is EMPTY")

if __name__ == "__main__":
    test_id = "202636030811" # Mizusawa (NAR)
    debug_race(test_id)
    
    test_id_jra = "202606020411" # Nakayama (JRA)
    debug_race(test_id_jra)
