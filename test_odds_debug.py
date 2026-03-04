import sys
import io
# Ensure UTF-8
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import scraper
import json

def debug_odds(race_id):
    print(f"--- Debugging Win Odds for {race_id} ---")
    win_odds = scraper.fetch_win_odds(race_id)
    print(f"Win Odds: {win_odds}")
    
    print(f"\n--- Debugging Sanrenpuku Odds for {race_id} ---")
    sanrenpuku_odds = scraper.fetch_sanrenpuku_odds(race_id)
    if sanrenpuku_odds:
        print(f"Fetched {len(sanrenpuku_odds)} Sanrenpuku combinations.")
        print(f"Top 5: {sanrenpuku_odds[:5]}")
    else:
        print("Failed to fetch Sanrenpuku odds.")

if __name__ == "__main__":
    # Race ID from user screenshot: 202406020211 (Nakayama Kinen)
    # Actually, the user says "latest race", but the screenshot shows 202406020211.
    # Let's try that first.
    test_id = "202606020211"
    debug_odds(test_id)
