# -*- coding: utf-8 -*-
"""Systematically test all known Netkeiba odds endpoints."""
import requests
import json
import zlib
import base64

race_ids = [
    "202610010101",  # Today Kokura 1R (should be finished)
    "202610010105",  # Today Kokura 5R
    "202602010101",  # Today Hanshin 1R
    "202605020101",  # Today Tokyo 1R
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

for rid in race_ids:
    print(f"\n{'='*60}")
    print(f"Race ID: {rid}")
    
    # Method 1: api_get_jra_odds (compressed)
    try:
        url1 = "https://race.netkeiba.com/api/api_get_jra_odds.html"
        p1 = {"pid": "api_get_jra_odds", "race_id": rid, "type": "b7", "compress": "1", "output": "json"}
        h1 = {**headers, "Referer": f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={rid}"}
        r1 = requests.get(url1, params=p1, headers=h1, timeout=10)
        d1 = r1.json()
        data1 = d1.get('data', '')
        print(f"  [1] api_get_jra_odds (compress): status={d1.get('status')}, data_len={len(str(data1))}")
        if data1 and len(str(data1)) > 10:
            decoded = base64.b64decode(data1)
            try:
                dec = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except:
                dec = zlib.decompress(decoded)
            od = json.loads(dec.decode('utf-8'))
            print(f"      Decompressed: type={type(od).__name__}, entries={len(od) if isinstance(od,dict) else '?'}")
            if isinstance(od, dict):
                keys = list(od.keys())[:3]
                for k in keys:
                    print(f"      {k}: {od[k]}")
    except Exception as e:
        print(f"  [1] ERROR: {e}")

    # Method 2: api_get_jra_odds (uncompressed)
    try:
        p2 = {"pid": "api_get_jra_odds", "race_id": rid, "type": "b7", "output": "json"}
        r2 = requests.get(url1, params=p2, headers=h1, timeout=10)
        d2 = r2.json()
        data2 = d2.get('data', '')
        print(f"  [2] api_get_jra_odds (no compress): status={d2.get('status')}, data_len={len(str(data2))}")
        if isinstance(data2, dict):
            keys = list(data2.keys())[:3]
            for k in keys:
                print(f"      {k}: {data2[k]}")
    except Exception as e:
        print(f"  [2] ERROR: {e}")

    # Method 3: api_get_odds_ninki
    try:
        url3 = f"https://race.netkeiba.com/api/api_get_odds_ninki.html?type=b7&race_id={rid}"
        r3 = requests.get(url3, headers=h1, timeout=10)
        print(f"  [3] api_get_odds_ninki: status={r3.status_code}, content_len={len(r3.content)}")
        if len(r3.content) > 100:
            text3 = r3.content.decode('euc-jp', errors='ignore')
            # Check for actual data
            import re
            nums = re.findall(r'\d+ - \d+ - \d+', text3)
            print(f"      Combinations found: {len(nums)}, first: {nums[:3] if nums else 'none'}")
    except Exception as e:
        print(f"  [3] ERROR: {e}")

    # Method 4: db.netkeiba.com race page (for finished races)
    try:
        url4 = f"https://db.netkeiba.com/race/{rid}/"
        r4 = requests.get(url4, headers={"User-Agent": headers["User-Agent"]}, timeout=10)
        print(f"  [4] db.netkeiba.com: status={r4.status_code}, len={len(r4.content)}")
    except Exception as e:
        print(f"  [4] ERROR: {e}")
