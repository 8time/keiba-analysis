# -*- coding: utf-8 -*-
"""出馬表の騎手リンク構造を詳細に確認する"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from core.scraper import fetch_robust_html
from bs4 import BeautifulSoup
import re

race_id = "202606030601"
url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
html = fetch_robust_html(url)
soup = BeautifulSoup(html, 'html.parser')

rows = soup.select('tr.HorseList')
print(f"HorseList行数: {len(rows)}")

for i, row in enumerate(rows[:3]):
    print(f"\n=== Row {i} ===")
    # 全tdを表示
    tds = row.find_all('td')
    for j, td in enumerate(tds):
        txt = td.get_text(strip=True)[:30]
        cls = td.get('class', [])
        print(f"  [{j}] class={cls} text='{txt}'")
        # リンクがあれば
        for a in td.find_all('a'):
            href = a.get('href', '')
            a_txt = a.get_text(strip=True)
            print(f"       -> <a> href='{href}' text='{a_txt}'")

    # 馬番を確認
    uma_el = row.select_one('td.Umaban, td[class*="Umaban"]')
    if uma_el:
        print(f"  馬番要素: class={uma_el.get('class')} text='{uma_el.get_text(strip=True)}'")
    else:
        print("  馬番要素: NOT FOUND")

    # 騎手を確認
    jockey_el = row.select_one('td.Jockey a, a[href*="/jockey/"]')
    if jockey_el:
        print(f"  騎手要素: href='{jockey_el.get('href','')}' text='{jockey_el.get_text(strip=True)}'")
    else:
        print("  騎手要素: NOT FOUND (trying broader search)")
        all_a = row.find_all('a')
        for a in all_a:
            href = a.get('href', '')
            print(f"    <a> href='{href}' text='{a.get_text(strip=True)}'")
