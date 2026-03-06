import scraper
import pandas as pd

def test_indices():
    race_id = "202406050811" # Arima Kinen 2024
    print(f"Testing index extraction for race: {race_id}")
    
    # We'll check all horses since the scraper now processes all rows in the table
    data = scraper.fetch_advanced_data_playwright(race_id, top_horse_ids=[1, 2, 3, 4, 11])
    
    print("\n--- Scraped Indices ---")
    for umaban, info in sorted(data.items()):
        u = info.get('UIndex', 0.0)
        l = info.get('LaboIndex', 0.0)
        if u > 0 or l > 0:
            print(f"Umaban {umaban}: U-Index={u}, Labo-Index={l}")

if __name__ == "__main__":
    test_indices()
