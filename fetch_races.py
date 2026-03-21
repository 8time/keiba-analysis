import core.scraper as s
import json
try:
    r = s.get_race_list_for_date("20260321")
    for x in r:
        rid = x['race_id']
        venue = rid[4:6]
        # Check if it has Kochi (47) or Saga (55)
        print(f"ID: {rid} | Venue: {venue} | Race: {x['race_name']}")
except Exception as e:
    print(f"Error: {e}")
