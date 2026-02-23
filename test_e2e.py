# -*- coding: utf-8 -*-
"""End-to-end test for 指数該当・人気順10選 feature."""
import scraper
import calculator
import pandas as pd

race_id = "202510010811"

# 1. Fetch race data
print("=== Step 1: fetch race data ===")
df = scraper.get_race_data(race_id)
print(f"  Horses: {len(df)}")
print(f"  Jockey column present: {'Jockey' in df.columns}")
if 'Jockey' in df.columns:
    print(f"  Jockeys: {df['Jockey'].tolist()[:3]}")

# 2. Calculate BattleScore
print("\n=== Step 2: calculate BattleScore ===")
df = calculator.calculate_battle_score(df)
top5 = df.nlargest(5, 'BattleScore')
print(f"  Top 5 by BattleScore:")
for _, r in top5.iterrows():
    print(f"    馬番{int(r['Umaban'])} {r.get('Name','')} BS={r['BattleScore']:.1f}")

# 3. Fetch odds
print("\n=== Step 3: fetch Sanrenpuku odds ===")
odds = scraper.fetch_sanrenpuku_odds(race_id)
print(f"  Odds entries: {len(odds)}")

# 4. Get recommendations
print("\n=== Step 4: get recommendations ===")
recs = calculator.get_sanrenpuku_recommendations(df, odds)
print(f"  Recommendations: {len(recs)}")
for r in recs:
    print(f"  {r['Rank']}人気  {r['Combination']}  {r['HorseNames']}  {r['Odds']}倍")

# 5. Mock test (with fake odds)
print("\n=== Step 5: Mock test with synthetic odds ===")
from itertools import combinations
all_uma = sorted(df['Umaban'].astype(int).tolist())
mock_odds = []
rank = 1
for combo in combinations(all_uma, 3):
    mock_odds.append({
        'Combination': f"{combo[0]}-{combo[1]}-{combo[2]}",
        'Horses': list(combo),
        'Odds': round(5.0 + rank * 0.5, 1),
        'Rank': rank
    })
    rank += 1
    if rank > 100:
        break

recs_mock = calculator.get_sanrenpuku_recommendations(df, mock_odds)
print(f"  Mock recommendations: {len(recs_mock)}")
for r in recs_mock:
    print(f"  {r['Rank']}人気  {r['Combination']}  {r['HorseNames']}  {r['Odds']}倍")
