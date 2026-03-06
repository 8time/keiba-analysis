import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.getcwd())
import scraper

odds = scraper.fetch_sanrenpuku_odds('202608020211')
print(f"Fetched {len(odds)} items for race 202608020211:")
for o in odds[:5]:
    print(f"{o['Rank']}番人気 {o['Combination']} ({o['Odds']}倍)")
