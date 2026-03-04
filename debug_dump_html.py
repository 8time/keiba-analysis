import asyncio
from playwright.async_api import async_playwright
import sys

async def dump_html(race_id):
    # Construct URLs (logic copied from scraper.py)
    # 202406050811 -> 2024 12 22 ... Arima Kinen
    # date_str: 20241222, venue: 06, kaisai: 05, day: 08, race_num: 11
    date_str = "20241222"
    venue = "06"
    kaisai = "05"
    day = "08"
    race_num = "11"
    
    u_url = f"https://umanity.jp/racedata/race_8.php?code={date_str}{venue}{kaisai}{day}{race_num}"
    l_url = f"https://www.keibalab.jp/db/race/{date_str}{venue}{race_num}/umabashira.html?kind=yoko"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print(f"Fetching Umanity: {u_url}")
        try:
            await page.goto(u_url, wait_until='load', timeout=30000)
            await asyncio.sleep(5)
            content = await page.content()
            with open("u_dump.html", "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Umanity HTML saved to u_dump.html. Title: {await page.title()}")
        except Exception as e:
            print(f"Umanity error: {e}")
            
        print(f"Fetching Keibalab: {l_url}")
        try:
            await page.goto(l_url, wait_until='load', timeout=30000)
            await asyncio.sleep(5)
            content = await page.content()
            with open("l_dump.html", "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Keibalab HTML saved to l_dump.html. Title: {await page.title()}")
        except Exception as e:
            print(f"Keibalab error: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(dump_html("202406050811"))
