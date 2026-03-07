import asyncio
from playwright.async_api import async_playwright
import sys

async def dump_u_9(race_id):
    date_str = "20241222"
    venue = "06"
    kaisai = "05"
    day = "08"
    race_num = "11"
    
    u_url = f"https://umanity.jp/racedata/race_9.php?code={date_str}{venue}{kaisai}{day}{race_num}"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        print(f"Fetching Umanity race_9: {u_url}")
        try:
            await page.goto(u_url, wait_until='load', timeout=30000)
            await asyncio.sleep(5)
            content = await page.content()
            with open("u_9_dump.html", "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Umanity race_9 HTML saved to u_9_dump.html. Title: {await page.title()}")
        except Exception as e:
            print(f"Umanity error: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(dump_u_9("202406050811"))
