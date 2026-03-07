import requests
url = "https://nar.netkeiba.com/odds/index.html?type=b7&race_id=202645030711&housiki=c99"
res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
res.encoding = 'euc-jp'
with open("nar_odds_test.html", "w", encoding="utf-8") as f:
    f.write(res.text)
print("Saved to nar_odds_test.html")
