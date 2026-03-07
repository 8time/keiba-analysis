import requests
from bs4 import BeautifulSoup
import time

def fetch_with_session(race_id):
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Referer": f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=ninki",
        "X-Requested-With": "XMLHttpRequest"
    }
    
    # 1. Fetch the main odds page to get cookies
    print(f"Fetching main odds page for {race_id}...")
    main_url = f"https://race.netkeiba.com/odds/index.html?type=b7&race_id={race_id}&housiki=ninki"
    r1 = session.get(main_url, headers=headers)
    print(f"Main page status: {r1.status_code}, length: {len(r1.content)}")
    
    time.sleep(1)
    
    # 2. Test different URLs
    urls = [
        f"https://race.netkeiba.com/odds/odds_get_form.html?type=b7&race_id={race_id}&housiki=ninki&rf=shutuba_submenu",
        f"https://race.netkeiba.com/odds/odds_get_form.html?type=b7&race_id={race_id}&housiki=c0&rf=shutuba_submenu",
        f"https://race.netkeiba.com/odds/odds_get_form.html?type=b7&race_id={race_id}&rf=shutuba_submenu",
        f"https://race.netkeiba.com/odds/ninki_odds.html?race_id={race_id}&type=b7"
    ]
    
    for i, url in enumerate(urls):
        print(f"Testing URL {i}: {url}...")
        r = session.get(url, headers=headers)
        print(f"  Status: {r.status_code}, length: {len(r.content)}")
        if len(r.content) > 50:
            print(f"  Success URL {i}!")
            with open(f'odds_success_{i}.html', 'wb') as f:
                f.write(r.content)

if __name__ == "__main__":
    fetch_with_session("202610011011") # Today's race
