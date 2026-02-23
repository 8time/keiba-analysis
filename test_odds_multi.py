# -*- coding: utf-8 -*-
"""Test odds API with multiple races to find one with data."""
import requests
import json
import zlib
import base64

def test_race(race_id):
    url = "https://race.netkeiba.com/api/api_get_jra_odds.html"
    params = {
        "pid": "api_get_jra_odds",
        "race_id": race_id,
        "type": "b7",
        "compress": "1",
        "output": "json",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    r = requests.get(url, params=params, headers=headers, timeout=10)
    data = r.json()
    status = data.get('status', '')
    reason = data.get('reason', '')
    raw = data.get('data', '')
    
    if raw and isinstance(raw, str) and len(raw) > 10:
        # Try decompress
        try:
            decoded = base64.b64decode(raw)
            decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            odds_data = json.loads(decompressed.decode('utf-8'))
            return f"OK (decompressed, type={type(odds_data).__name__}, keys={list(odds_data.keys())[:5] if isinstance(odds_data, dict) else len(odds_data)})"
        except:
            try:
                decoded = base64.b64decode(raw)
                decompressed = zlib.decompress(decoded)
                odds_data = json.loads(decompressed.decode('utf-8'))
                return f"OK-alt (type={type(odds_data).__name__})"
            except Exception as e:
                return f"DECOMPRESS_FAIL ({e}), raw_len={len(raw)}"
    else:
        return f"status={status}, reason={reason}"

# Test with various race IDs
races = [
    "202406050811",  # 2024 past race
    "202410010811",  # 2024 past race (Kokura)
    "202610010811",  # 2026 future race
    "202610011001",  # Today's 1R
    "202610011005",  # Today's 5R
]

for rid in races:
    result = test_race(rid)
    print(f"{rid}: {result}")
