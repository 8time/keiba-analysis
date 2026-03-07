import scraper
import pandas as pd

# Test with a known race ID
rid = "202409020601" # Example ID from scraper comments
print(f"Testing Past Run Extraction for {rid}...")

try:
    df = scraper.get_race_data(rid)
    if not df.empty:
        print(f"Columns: {df.columns}")
        if 'PastRuns' in df.columns:
            # Check the first horse's past runs
            first_horse = df.iloc[0]
            print(f"Horse: {first_horse.get('Name')}")
            runs = first_horse.get('PastRuns', [])
            print(f"Past Runs Count: {len(runs)}")
            for i, run in enumerate(runs[:3]): # Show first 3 runs
                print(f"Run {i+1}:")
                print(f"  Date: {run.get('Date')}")
                print(f"  Race: {run.get('RaceName')}")
                print(f"  Time: {run.get('Time')}")
                print(f"  Dist: {run.get('Distance')}")
                print(f"  Cond: {repr(run.get('Condition'))}") # Check Condition
                print(f"  Wght: {run.get('Weight')}")
                print(f"  Surf: {repr(run.get('Surface'))}")
        else:
            print("No 'PastRuns' column found.")
    else:
        print("DataFrame is empty.")
except Exception as e:
    print(f"Error: {e}")
