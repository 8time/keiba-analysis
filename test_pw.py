import asyncio
import sys
from playwright.async_api import async_playwright

async def run_test():
    print("Test START")
    async with async_playwright() as p:
        print("Launching browser...")
        try:
            browser = await p.chromium.launch(headless=True, timeout=10000)
            print("Browser launched OK.")
            page = await browser.new_page()
            print("Page created.")
            await page.goto("https://www.google.com", timeout=10000)
            print("Title:", await page.title())
            await browser.close()
        except Exception as e:
            print("FAILED:", e, file=sys.stderr)
    print("Test END")

if __name__ == "__main__":
    asyncio.run(run_test())
