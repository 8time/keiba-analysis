import requests
import sys
sys.stdout.reconfigure(encoding='utf-8')

def fetch_time_index(race_id):
    url = f"https://race.netkeiba.com/race/sum_timeindex.html?race_id={race_id}"
    print(f"Fetching {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    response.encoding = 'EUC-JP'
    return response.text

if __name__ == "__main__":
    race_id = "202608020211" 
    html = fetch_time_index(race_id)
    with open("timeindex_dump.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("Dumped to timeindex_dump.html")
