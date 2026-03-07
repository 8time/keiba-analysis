# -*- coding: utf-8 -*-
"""Test the actual Netkeiba odds JSONP API with zlib decompression."""
import requests
import json
import zlib
import base64

race_id = "202510010811"

# The API URL pattern from jquery.odds_update.js
# apiUrl is typically https://race.netkeiba.com/api/api_get_jra_odds.html
url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
params = {
    "pid": "api_get_jra_odds",
    "race_id": race_id,
    "type": "b7",      # 3連複
    "compress": "1",    # request zlib compressed
    "output": "json",
}
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}",
    "X-Requested-With": "XMLHttpRequest",
}

try:
    r = requests.get(url, params=params, headers=headers, timeout=10)
    print(f"Status: {r.status_code}, Length: {len(r.content)}")
    
    # Try parsing as JSON
    try:
        data = r.json()
        print(f"JSON keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        
        if 'data' in data and data['data']:
            raw = data['data']
            if isinstance(raw, str) and len(raw) > 0:
                # Decompress: base64 -> zlib inflate
                try:
                    decoded = base64.b64decode(raw)
                    decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
                    odds_data = json.loads(decompressed.decode('utf-8'))
                    print(f"Decompressed type: {type(odds_data)}")
                    if isinstance(odds_data, dict):
                        print(f"Decompressed keys: {list(odds_data.keys())[:10]}")
                        # Print first few entries
                        for k in list(odds_data.keys())[:5]:
                            print(f"  {k}: {odds_data[k]}")
                    elif isinstance(odds_data, list):
                        print(f"Decompressed list length: {len(odds_data)}")
                        for item in odds_data[:5]:
                            print(f"  {item}")
                except Exception as e2:
                    print(f"Decompression error: {e2}")
                    # Try without wbits
                    try:
                        decoded = base64.b64decode(raw)
                        decompressed = zlib.decompress(decoded)
                        odds_data = json.loads(decompressed.decode('utf-8'))
                        print(f"Alt decompress OK: {type(odds_data)}")
                        if isinstance(odds_data, dict):
                            print(f"Keys: {list(odds_data.keys())[:10]}")
                    except Exception as e3:
                        print(f"Alt decompress also failed: {e3}")
                        print(f"Raw data (first 200 chars): {raw[:200]}")
            else:
                print(f"Data field type: {type(raw)}, value: {str(raw)[:200]}")
        else:
            print(f"No 'data' key or empty. Full response: {str(data)[:500]}")
    except json.JSONDecodeError:
        print(f"Not JSON. Content type: {r.headers.get('Content-Type')}")
        text = r.text[:500]
        print(f"Raw text: {text}")
except Exception as e:
    print(f"Request error: {e}")
