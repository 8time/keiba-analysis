import sys
import os
sys.path.append(os.getcwd())
import scraper
odds = scraper.fetch_sanrenpuku_odds("202608020310")
print(f"Num odds fetched: {len(odds) if odds else 0}")
if odds:
    print(odds[:3])
