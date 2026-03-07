import asyncio
from playwright.async_api import async_playwright
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("Navigating to local Streamlit app (port 8505)...")
        await page.goto("http://localhost:8505", wait_until="networkidle")
        await asyncio.sleep(2)
        
        print("Finding Race ID input...")
        # Fill in the race ID
        input_locator = page.get_by_label("レースIDを入力")
        if not await input_locator.count():
             input_locator = page.get_by_placeholder("例：202305021211")
        if not await input_locator.count():
             input_locator = page.locator("input[type='text']").first

        await input_locator.fill("202507050501")
        
        print("Clicking the execute button...")
        # Click the fetch button
        btn = page.get_by_role("button", name="データ取得＆算出")
        if not await btn.count():
             btn = page.locator("button:has-text('データ取得')").first
        await btn.click()
        
        print("Waiting for results to load (max 30s)...")
        # Wait until the debug alert box appears or timeout
        try:
            # We look for the st.info generated div
            debug_box = page.locator("div[data-testid='stAlert']", has_text="DEBUG:")
            await debug_box.wait_for(state="visible", timeout=30000)
            text = await debug_box.inner_text()
            print("--- STREAMLIT UI OUTPUT ---")
            print(text)
        except Exception as e:
            print(f"Error waiting for debug UI or it didn't appear: {e}")
            
            # just print whatever alert boxes exist
            alerts = await page.locator("div[data-testid='stAlert']").all_inner_texts()
            print("Found these alerts instead:", alerts)

        await browser.close()

asyncio.run(run())
