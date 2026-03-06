import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.getcwd())
import scraper
import traceback

def test_jra_race(race_id):
    try:
        print(f"Testing fetch_sanrenpuku_odds for JRA race {race_id}")
        odds = scraper.fetch_sanrenpuku_odds(race_id)
        if odds:
            print(f'Fetched {len(odds)} items for JRA {race_id}.')
            for item in odds[:3]:
                print(f"Rank {item['Rank']}: {item['Combination']} ({item['Odds']})")
        else:
            print(f"Fetched 0 items for {race_id}")
    except Exception as e:
        print(f"Error fetching JRA odds: {e}")
        traceback.print_exc()

test_jra_race('202507050501')
test_jra_race('202508020211')
