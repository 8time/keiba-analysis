import sys, io
try:
    sys.stdout.reconfigure(encoding='utf-8')
except:
    pass

import pandas as pd
import calculator
import scraper

print("🚀 Starting Logic Verification...")

# Mock Data to test logic without network if possible, but let's try real fetch first for authenticity
# Race ID: 202610010811 (User's reference) or 202608020211
race_id = "202610010811" 

print(f"Fetching Data for {race_id}...")
df = scraper.get_race_data(race_id)

if df.empty:
    print("❌ Failed to fetch data. Using Mock Data.")
    # Create Mock DF
    df = pd.DataFrame([
        {'Name': 'TestHorse1', 'OguraIndex': 50.0, 'PastRuns': [{'Agari': 34.0, 'AgariType': 'Real', 'Passing': '2-2', 'Distance': 1200, 'Surface': '芝'}], 'CurrentDistance': 1200},
        {'Name': 'TestHorse2', 'OguraIndex': 45.0, 'PastRuns': [{'Agari': 33.5, 'AgariType': 'Real', 'Passing': '8-8', 'Distance': 1200, 'Surface': '芝'}], 'CurrentDistance': 1200},
    ])
    df['CurrentDistance'] = 1200

df = calculator.calculate_battle_score(df)

print("\n📊 Calculated Stats (Sorted by Agari):")
print(df[['Name', 'AvgAgari', 'AvgPosition', 'AgariRank']].sort_values('AvgAgari'))

print("\n📊 Final Verification Results:")
print(df[['Name', 'OguraIndex', 'BattleScore', 'Alert', 'AlertText'] if 'AlertText' in df.columns else ['Name', 'OguraIndex', 'BattleScore', 'Alert']])

# Check for Bonus application
if df['BattleScore'].max() > 40: # Expecting higher scores
    print("✅ Scores seem to include bonuses.")
else:
    print("⚠️ Scores look low. Check bonus logic.")
