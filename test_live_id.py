import requests, json, base64, zlib
import sys

def inspect_odds(race_id, odds_type="b1"):
    is_nar = False
    try:
        if int(str(race_id)[4:6]) > 10: is_nar = True
    except: pass
    
    url = "https://nar.netkeiba.com/api/api_get_nar_odds.html" if is_nar else "https://race.netkeiba.com/api/api_get_jra_odds.html"
    pid = "api_get_nar_odds" if is_nar else "api_get_jra_odds"
    
    params = {"pid": pid, "race_id": race_id, "type": odds_type, "compress": "1", "output": "json"}
    headers = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
    
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        data = res.json()
        raw = data.get('data', '')
        if raw:
            decoded = base64.b64decode(raw)
            try: decompressed = zlib.decompress(decoded, -zlib.MAX_WBITS)
            except: decompressed = zlib.decompress(decoded)
            odds_data = json.loads(decompressed.decode('utf-8'))
            print(f"SUCCESS: Found {len(odds_data)} odds entries for {race_id}")
            # print(json.dumps(odds_data, indent=2))
        else:
            print(f"FAILED: No data returned for {race_id}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    inspect_odds("202619030901")
