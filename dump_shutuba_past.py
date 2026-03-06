import requests
import sys

def dump_shutuba_past(race_id):
    url = f"https://race.netkeiba.com/race/shutuba_past.html?race_id={race_id}"
    res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    res.encoding = res.apparent_encoding if res.apparent_encoding else 'EUC-JP'
    
    with open("shutuba_past_dump.html", "w", encoding="utf-8") as f:
        f.write(res.text)
    print(f"Dumped HTML to shutuba_past_dump.html (Length: {len(res.text)})")

if __name__ == "__main__":
    dump_shutuba_past("202606020211")
