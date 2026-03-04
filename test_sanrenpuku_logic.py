import sys
import os
import pandas as pd
sys.path.append(os.getcwd())
import scraper
import calculator

race_id = "202608020310"
df = scraper.get_race_data(race_id)
df = calculator.calculate_battle_score(df)
df = calculator.calculate_strength_suitability(df, "芝右 外1600")

if 'Projected Score' in df.columns:
    df_for_recs = df.copy()
    df_for_recs['BattleScore'] = df_for_recs['Projected Score']
else:
    df_for_recs = df

odds_list = scraper.fetch_sanrenpuku_odds(race_id)
if not odds_list:
    print("Simulating odds...")
    all_umaban = [int(u) for u in df_for_recs['Umaban'].dropna().tolist()]
    pop_dict = {int(row['Umaban']): float(row.get('Popularity', 99)) for _, row in df_for_recs.iterrows()}
    
    from itertools import combinations
    sim_odds = []
    for comb in combinations(all_umaban, 3):
        h1, h2, h3 = sorted(comb)
        pop_sum = pop_dict.get(h1, 99) + pop_dict.get(h2, 99) + pop_dict.get(h3, 99)
        sim_odds.append({
            'Combination': f"{h1}-{h2}-{h3}",
            'Horses': [h1, h2, h3],
            'Odds': 0.0,
            'pop_sum': pop_sum
        })
    sim_odds.sort(key=lambda x: x['pop_sum'])
    for i, item in enumerate(sim_odds):
        item['Rank'] = i + 1
    odds_list = sim_odds

base_recs = calculator.get_sanrenpuku_recommendations(df_for_recs, odds_list)

sort_col = 'Projected Score' if 'Projected Score' in df_for_recs.columns else 'BattleScore'
top5_horses = df_for_recs.sort_values(by=sort_col, ascending=False).head(5)
top5_umaban = set(int(u) for u in top5_horses['Umaban'].tolist())

recs_2plus = []
recs_1only = []

for item in base_recs:
    count_top = sum(1 for h in item['Horses'] if h in top5_umaban)
    if count_top >= 2:
        recs_2plus.append(item)
    elif count_top == 1:
        recs_1only.append(item)

TARGET_2PLUS = 8
TARGET_1ONLY = 2
selected_2plus = recs_2plus[:TARGET_2PLUS]
shortfall = TARGET_2PLUS - len(selected_2plus)
adj_1only_target = TARGET_1ONLY + shortfall
selected_1only = recs_1only[:adj_1only_target]

still_short = adj_1only_target - len(selected_1only)
if still_short > 0:
    selected_2plus.extend(recs_2plus[TARGET_2PLUS:TARGET_2PLUS + still_short])

combined = selected_2plus + selected_1only
combined.sort(key=lambda x: x['Rank'])
recs = combined[:10]

print(f"Total Base Recs: {len(base_recs)}")
print(f"Recs 2+: {len(recs_2plus)}, Recs 1only: {len(recs_1only)}")
print(f"Selected 2+: {len(selected_2plus)}, Selected 1only: {len(selected_1only)}")
print("FINAL RECS:")
for r in recs:
    count = sum(1 for h in r['Horses'] if h in top5_umaban)
    print(f"Rank {r['Rank']}: {r['Combination']} ({count} top horses) - Odds: {r['Odds']}")
