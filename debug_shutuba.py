import requests

def debug_fetch(race_id):
    url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
    print(f"Fetching {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    response.encoding = 'EUC-JP'
    with open("shutuba_dump.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("Dumped shutuba.html")

if __name__ == "__main__":
    debug_fetch("202608020211")
