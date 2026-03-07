import scraper
from datetime import datetime
import json

# Get a valid race ID from yesterday or today
date_str = datetime.now().strftime("%Y%m%d")
race_ids = scraper.get_race_ids_for_date()
if not race_ids:
    # try yesterday
    race_ids = scraper.get_race_ids_for_date("20260222")

if race_ids:
    rid = race_ids[0]
    print(f"Testing with Race ID: {rid}")
    
    res1 = scraper.fetch_netkeiba_time_avg(rid)
    print("time.html Result:")
    print(json.dumps(res1, indent=2))
    
    res2 = scraper.fetch_time_index_values(rid)
    print("speed.html Result:")
    print(json.dumps(res2, indent=2))
else:
    print("No valid race IDs found.")
