import sys, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.append(os.getcwd())
import scraper
try:
    odds = scraper.fetch_sanrenpuku_odds('202507050501')
    print('Fetched ' + str(len(odds)) + ' items for 202507050501.')
    if odds:
        for item in odds[:5]:
            print(str(item['Rank']) + '番人気 ' + item['Combination'] + ' (' + str(item['Odds']) + '倍)')
except Exception as e:
    print('Error: ' + str(e))
