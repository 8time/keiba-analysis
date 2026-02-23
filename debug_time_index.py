import scraper
import pandas as pd

race_id = "202605010811" # A higher numbered race likely has indices
df = scraper.get_race_data(race_id)

if not df.empty:
    print("Columns:", df.columns.tolist())
    print("\nTimeIndexAvg5 Data:")
    ti_data = df[['Umaban', 'Name', 'TimeIndexAvg5']].sort_values(by='TimeIndexAvg5', ascending=False)
    print(ti_data[ti_data['TimeIndexAvg5'] > 0])
else:
    print("Failed to fetch data.")
