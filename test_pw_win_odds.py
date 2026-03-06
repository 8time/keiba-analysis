import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def test_pw_odds(race_id):
    url_b1 = f"https://race.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"
    url_b0 = f"https://race.netkeiba.com/odds/index.html?type=b0&race_id={race_id}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # 1. Fetch Win Odds (b1)
        print(f"Navigating to {url_b1}...")
        await page.goto(url_b1, wait_until='domcontentloaded')
        await page.wait_for_timeout(4000)
        html_b1 = await page.content()
        
        # 2. Fetch Popularity (b0)
        print(f"Navigating to {url_b0}...")
        await page.goto(url_b0, wait_until='domcontentloaded')
        await page.wait_for_timeout(4000)
        html_b0 = await page.content()
        with open("rendered_b0_odds.html", "w", encoding="utf-8") as f:
            f.write(html_b0)
        
        await browser.close()
        
        # Parse b1 (Odds)
        soup_b1 = BeautifulSoup(html_b1, 'html.parser')
        odds_map = {}
        target_table = None
        for table in soup_b1.find_all('table'):
            if "馬番" in table.text and "単勝" in table.text:
                target_table = table
                break
        
        if target_table:
            for row in target_table.find_all('tr'):
                cols = row.find_all('td')
                if len(cols) >= 5:
                    u_text = cols[1].text.strip()
                    o_text = cols[5].text.strip()
                    if u_text.isdigit():
                        m = re.search(r'(\d+\.\d+)', o_text)
                        odds_map[int(u_text)] = float(m.group(1)) if m else 0.0

        # Parse b0 (Popularity)
        soup_b0 = BeautifulSoup(html_b0, 'html.parser')
        pop_map = {}
        for row in soup_b0.find_all('tr'):
            cols = row.find_all('td')
            # Look for Popularity in b0
            # Usually: 0: Popularity, 1: Waku, 2: Umaban...
            if len(cols) >= 4:
                pop_text = cols[0].text.strip()
                umaban_text = cols[2].text.strip()
                if pop_text.isdigit() and umaban_text.isdigit():
                    pop_map[int(umaban_text)] = int(pop_text)
        
        results = {}
        for u in odds_map:
            results[u] = {
                'Odds': odds_map[u],
                'Popularity': pop_map.get(u, 99)
            }
            print(f"Horse {u}: Odds={results[u]['Odds']}, Pop={results[u]['Popularity']}")
        
        return results
        
        # If we need popularity, maybe type=b0 is better
        if results:
            for u, data in results.items():
                print(f"Horse {u} ({data['Name']}): {data['Odds']}")
        
        await browser.close()
        return results

if __name__ == "__main__":
    import sys
    # For Windows/Streamlit compatibility in scripts
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(test_pw_odds("202606020211"))
