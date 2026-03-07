import requests
import sys
sys.stdout.reconfigure(encoding='utf-8')

url = "https://race.netkeiba.com/top/race_list.html?kaisai_date=20260215"
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}
res = requests.get(url, headers=headers)
res.encoding = 'EUC-JP'

with open("race_list_dump.html", "w", encoding="utf-8") as f:
    f.write(res.text)

print("Dumped HTML to race_list_dump.html")
