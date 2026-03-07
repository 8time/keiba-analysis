import pandas as pd
import scraper

race_id = "202605010811"
disp_df = scraper.get_race_data(race_id)
race_results = scraper.fetch_race_result(race_id)

disp_df['ActualRank'] = disp_df['Name'].map(
    lambda n: race_results.get(n, {}).get('Rank', None)
)

result_odds = disp_df['Name'].map(
    lambda n: race_results.get(n, {}).get('ResultOdds', 0.0)
)
print("Result odds series:")
print(result_odds)
print("\nOriginal Odds column:")
print(disp_df['Odds'])

if 'Odds' in disp_df.columns:
    disp_df['Odds'] = disp_df.apply(
        lambda row: result_odds[row.name] if row['Odds'] == 0.0 and result_odds[row.name] > 0 else row['Odds'],
        axis=1
    )
else:
    disp_df['Odds'] = result_odds

print("\nFinal Odds column:")
print(disp_df[['Name', 'Odds', 'ActualRank']])
