import requests

def debug_fetch(race_id):
    url = f"https://race.netkeiba.com/race/speed.html?race_id={race_id}"
    print(f"Fetching {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    response.encoding = 'EUC-JP'
    with open("speed_dump.html", "w", encoding="utf-8") as f:
        f.write(response.text)
    print("Dumped speed.html")

if __name__ == "__main__":
    debug_fetch("202608020211")
