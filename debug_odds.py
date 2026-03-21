import sys
import os
import json
from scrapling import DynamicFetcher, Fetcher as ScraplingFetcher
from bs4 import BeautifulSoup

def debug_netkeiba_odds(race_id="202642032001"):
    print(f"=== DEBUG START: race_id={race_id} ===")
    is_nar = race_id.startswith('2026') and int(race_id[4:6]) >= 40
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    url = f"https://{domain}/race/shutuba.html?race_id={race_id}"
    
    print(f"1. Fetching URL via DynamicFetcher (network_idle=True): {url}")
    try:
        fetcher = DynamicFetcher()
        fetcher.configure()
        page = fetcher.fetch(url, timeout=40000, network_idle=True)
        
        if page and page.body:
            print(f"   - Response received. Body length: {len(page.body)}")
            # Scrapling css selectors
            odds_elements = page.css('td.Odds').getall()
            pop_elements = page.css('td.Popular').getall()
            span_odds = page.css('span[id^="odds-"]').getall()
            
            print(f"   - Selector results (Scrapling CSS):")
            print(f"     * td.Odds count: {len(odds_elements)}")
            print(f"     * td.Popular count: {len(pop_elements)}")
            print(f"     * span[id^='odds-'] count: {len(span_odds)}")
            
            if span_odds:
                print(f"   - span[id^='odds-'] sample: {span_odds[:3]}")
                
            # BeautifulSoup check for full transparency
            soup = BeautifulSoup(page.body, 'html.parser')
            rows = soup.find_all('tr', class_='HorseList')
            print(f"   - BeautifulSoup tr.HorseList count: {len(rows)}")
            if rows:
                first_row = rows[0]
                o_td = first_row.find('td', class_='Odds')
                p_td = first_row.find('td', class_='Popular')
                print(f"   - Row 1: Odds_td='{o_td.text.strip() if o_td else 'None'}', Popular_td='{p_td.text.strip() if p_td else 'None'}'")
        else:
            print("   - FAILED: No page or body received.")
    except Exception as e:
        print(f"   - ERROR: {e}")

    print("\n2. Fetching API Directly via Scrapling.Fetcher (Approach B)")
    api_url = f"https://{domain}/api/api_get_{'nar' if is_nar else 'jra'}_odds.html?pid=api_get_{'nar' if is_nar else 'jra'}_odds&race_id={race_id}&type=1&action=init&compress=0&output=json"
    print(f"   - API URL: {api_url}")
    try:
        resp = ScraplingFetcher.get(api_url, impersonate='chrome120', timeout=15)
        if resp and resp.body:
            print(f"   - API Response length: {len(resp.body)}")
            data = json.loads(resp.body)
            print(f"   - API Top Keys: {list(data.keys())}")
            if 'ary_odds' in data:
                print(f"   - ary_odds sample (Horse 01): {data['ary_odds'].get('01', 'N/A')}")
            else:
                print(f"   - FULL DATA: {json.dumps(data, indent=2)[:500]}...")
        else:
            print("   - API FAILED: No body")
    except Exception as e:
        print(f"   - API ERROR: {e}")

    print(f"\n=== DEBUG END ===")

if __name__ == "__main__":
    rid = sys.argv[1] if len(sys.argv) > 1 else "202642032001"
    debug_netkeiba_odds(rid)
