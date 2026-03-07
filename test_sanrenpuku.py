import scraper
import calculator
import pandas as pd

# Test 1: fetch_sanrenpuku_odds
race_id = "202510010811"
print(f"=== Test: fetch_sanrenpuku_odds({race_id}) ===")
odds = scraper.fetch_sanrenpuku_odds(race_id)
print(f"  Results: {len(odds)} items")
if odds:
    for o in odds[:5]:
        print(f"  {o}")
else:
    print("  (empty - odds may not be available for this race yet)")

# Test 2: Jockey column presence
print(f"\n=== Test: Jockey column in get_race_data ===")
try:
    df = scraper.get_race_data(race_id)
    if 'Jockey' in df.columns:
        print(f"  OK: Jockey column present. Sample: {df['Jockey'].tolist()[:3]}")
    else:
        print(f"  FAIL: Jockey column missing. Columns: {df.columns.tolist()}")
except Exception as e:
    print(f"  Error fetching race data: {e}")

# Test 3: get_sanrenpuku_recommendations
print(f"\n=== Test: get_sanrenpuku_recommendations ===")
if odds and 'df' in dir():
    try:
        df = calculator.calculate_battle_score(df)
        recs = calculator.get_sanrenpuku_recommendations(df, odds)
        print(f"  Recommendations: {len(recs)}")
        for r in recs[:5]:
            print(f"  {r}")
    except Exception as e:
        print(f"  Error: {e}")
else:
    # Test with mock data
    mock_df = pd.DataFrame({
        'Umaban': [1,2,3,4,5],
        'BattleScore': [65.0, 70.0, 55.0, 60.0, 50.0]
    })
    mock_odds = [
        {'Combination': '1-2-3', 'Horses': [1,2,3], 'Odds': 5.5, 'Rank': 1},
        {'Combination': '1-2-4', 'Horses': [1,2,4], 'Odds': 8.0, 'Rank': 2},
        {'Combination': '2-3-4', 'Horses': [2,3,4], 'Odds': 12.0, 'Rank': 3},
        {'Combination': '1-3-5', 'Horses': [1,3,5], 'Odds': 20.0, 'Rank': 4},
    ]
    recs = calculator.get_sanrenpuku_recommendations(mock_df, mock_odds)
    print(f"  Mock Recommendations: {len(recs)}")
    for r in recs:
        print(f"  {r}")
