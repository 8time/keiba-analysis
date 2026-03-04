import asyncio
from playwright.async_api import async_playwright
import os
import sys

# Ensure UTF-8 output
# [Console]::OutputEncoding = [System.Text.Encoding]::UTF8; 
# This rule is for shell execution, but for Python print we also force it if possible.

async def create_session():
    print("--- Playwright Session Creator ---")
    print("1. ブラウザが起動します。")
    print("2. ウマニティ等のログインをブラウザ上で行ってください。")
    print("3. ログインが完了し、マイページ等が表示されたら、このコンソールに戻ってEnterキーを押してください。")
    
    async with async_playwright() as p:
        # Launch headed browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Navigate to Umanity Login
        await page.goto("https://umanity.jp/login.php")
        
        print("\n[WAITING] ブラウザでの操作を待機中...")
        input("ログイン完了後、Enterキーを押すとセッションを保存します...")
        
        # Save state
        session_path = "auth_session.json"
        await context.storage_state(path=session_path)
        print(f"✅ セッション情報を {session_path} に保存しました。")
        
        await browser.close()

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(create_session())
    except KeyboardInterrupt:
        print("\nCancelled by user.")
    except Exception as e:
        print(f"\nError: {e}")
