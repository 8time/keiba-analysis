import sys
import pandas as pd
import scraper
import calculator

rid = "202610010811"
print(f"Fetching data for {rid}...")
df_raw = scraper.get_race_data(rid)
# Assuming df_raw automatically extracted Distance/Surface
df = calculator.calculate_ogura_index(df_raw)
df = calculator.calculate_battle_score(df)
df = calculator.calculate_strength_suitability(df, course_profile="標準")

odds_list = scraper.fetch_sanrenpuku_odds(rid)
recs = calculator.get_as_race_recommendations(df, odds_list, num_recs=30)

print("\n--- A/S Recommendations Generated ---")
print(f"Total Combinations: {len(recs)}")
valid_combs = []
for r in recs:
    print(f"Comb: {r['Combination']} ({r['HorseNames']}) - Odds: {r.get('Odds', 'N/A')}")
    valid_combs.append(r['Combination'])

print(f"\nIs '2-4-8' generated? {'2-4-8' in valid_combs or '2-8-4' in valid_combs or '4-8-2' in valid_combs or '4-2-8' in valid_combs or '8-2-4' in valid_combs or '8-4-2' in valid_combs}")
print(f"Is '2-4-14' generated? {'2-4-14' in valid_combs or '2-14-4' in valid_combs or '4-14-2' in valid_combs or '4-2-14' in valid_combs or '14-2-4' in valid_combs or '14-4-2' in valid_combs}")

