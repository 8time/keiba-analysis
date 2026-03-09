import sys
import os
import pandas as pd
import logging

# Set up logging to stdout
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to path
sys.path.append(os.getcwd())

from core import scraper
from core import calculator

def _detect_pattern(scores):
    GAP_VERY_LARGE, GAP_LARGE, GAP_FLAT, GAP_MIDDLE_SMALL = 50, 30, 15, 20
    s = scores
    if len(s) < 2: return 3
    g12 = s[0] - s[1]
    g13 = s[0] - s[2] if len(s) >= 3 else g12
    g_last = s[0] - s[-1]
    g_mid = (s[2] - s[6]) if len(s) >= 7 else 0
    if g12 >= GAP_VERY_LARGE: return 1
    elif g13 >= GAP_LARGE and g12 < GAP_VERY_LARGE: return 2
    elif g_last < GAP_FLAT: return 5
    elif len(s) >= 7 and g_mid < GAP_MIDDLE_SMALL: return 4
    else: return 3

def test_scanner_logic(race_id):
    print(f"\n--- Testing Race Scanner Logic for ID: {race_id} ---")
    try:
        # 1. Fetch data
        print("1. Fetching race data...")
        df_r = scraper.get_race_data(race_id)
        if df_r is None or df_r.empty:
            print("ERR: No data fetched")
            return
        
        # 2. Determine Profile (Simulated app.py logic)
        prof_idx = 2
        if len(race_id) >= 6:
            vc = race_id[4:6]
            if vc in ['04', '05', '07']: prof_idx = 0
            elif vc in ['01', '02', '03', '06', '10']: prof_idx = 1
        prof_text = ["✨ 直線が長い・差し有利 (東京/外回り 等)", "✨ 小回り・先行有利 (中山/小倉/札幌 等)", "✨ 標準 (バランス)"][prof_idx]
        print(f"Profile: {prof_text}")

        # 3. Calculate Scores
        print("2. Calculating Battle Score...")
        df_r = calculator.calculate_battle_score(df_r)
        print("3. Calculating N-Index...")
        df_r = calculator.calculate_n_index(df_r)
        print("4. Calculating Strength Suitability...")
        # THIS IS THE SUSPECTED FAILURE POINT
        df_r = calculator.calculate_strength_suitability(df_r, prof_text)
        
        # 4. Pattern Detection
        print("5. Detecting Pattern...")
        score_col = 'Projected Score' if 'Projected Score' in df_r.columns else 'BattleScore'
        df_r['_score'] = pd.to_numeric(df_r[score_col], errors='coerce').fillna(0)
        df_r = df_r.sort_values('_score', ascending=False).reset_index(drop=True)
        scores_sorted = df_r['_score'].tolist()
        pattern = _detect_pattern(scores_sorted)
        print(f"Success! Pattern: {pattern}")
        print(f"Top 3: {df_r['Name'].head(3).tolist()}")
        
    except Exception as e:
        print(f"ERR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Test with a known recent race ID or let user provide one
    # If no ID, try to get race list for today
    try:
        from datetime import date
        today = date.today().strftime("%Y%m%d")
        print(f"Fetching race list for {today}...")
        r_list = scraper.get_race_list_for_date(today)
        if r_list:
            test_scanner_logic(r_list[0]['race_id'])
        else:
            print("No races today, testing with a hardcoded ID...")
            test_scanner_logic("202506010111") # Example
    except Exception as e:
        print(f"Setup Error: {e}")
