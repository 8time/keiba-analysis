import sys
import os
import logging

# Ensure we can import from the root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from core.odds_logger import OddsFetcher
    print("Import successful")
    
    fetcher = OddsFetcher()
    test_id = "202644030911"
    print(f"Testing fetch for {test_id}...")
    
    data = fetcher.fetch_win_show_popularity(test_id)
    if data:
        print(f"Success! Fetched {len(data)} horses.")
        for d in data[:3]:
            print(f" Horse {d['umaban']}: Win={d['win']}, Show={d['show_min']}-{d['show_max']}, Pop={d['pop']}")
    else:
        print("Failed to fetch data. (API might be empty for this ID)")
        
except Exception as e:
    print(f"Error during test: {e}")
    import traceback
    traceback.print_exc()
