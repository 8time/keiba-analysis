import sys
import io
import os
import re
import json
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger("adv_fetch_helper")

async def fetch_horse_bloodline(page_context, h_id):
    """Fetch bloodline flags for a single horse in a new page."""
    if not h_id: return ""
    try:
        page = await page_context.new_page()
        ped_url = f"https://db.netkeiba.com/horse/ped/{h_id}/"
        await page.goto(ped_url, wait_until='commit', timeout=8000)
        if "horse/ped" not in page.url:
            await page.close()
            return ""
        
        txt_loc = page.locator('.blood_table')
        if await txt_loc.count() > 0:
            txt = await txt_loc.first.text_content(timeout=3000)
            await page.close()
            if txt:
                flags = []
                if any(x in txt for x in ['Nijinsky', 'ニジンスキー']): flags.append('Nijinsky')
                if any(x in txt for x in ['Sunday Silence', 'サンデーサイレンス']): flags.append('SS')
                if any(x in txt for x in ['Roberto', 'ロベルト']): flags.append('Roberto')
                return ",".join(flags)
        else:
            await page.close()
    except:
        try: await page.close()
        except: pass
    return ""

async def fetch_advanced_data(race_id, top_horse_ids=None):
    if top_horse_ids is None:
        top_horse_ids = []
        
    advanced_data = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        session_path = "auth_session.json"
        context_kwargs = {
            "user_agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
        if os.path.exists(session_path):
            context_kwargs["storage_state"] = session_path
            
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        
        # --- 1. Shutuba Page ---
        shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            await page.goto(shutuba_url, timeout=20000, wait_until='commit')
            await page.wait_for_selector('tr.HorseList, tr.Entry', timeout=8000)
        except: pass
            
        # Extract Race Date
        date_str = ""
        try:
            title = await page.title()
            m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', title)
            if m_date:
                date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
        except: pass

        # Row extraction from Shutuba
        rows = await page.locator('tr.HorseList, tr.Entry').all()
        for row in rows:
            try:
                # Better Umaban selector
                um_loc = row.locator('td.Umaban, td[class*="Umaban"]')
                if await um_loc.count() > 0:
                    txt = (await um_loc.first.text_content(timeout=1000)).strip()
                    m = re.search(r'(\d+)', txt)
                    if not m: continue
                    umaban = int(m.group(1))
                    
                    advanced_data[umaban] = {
                        'WeightStr': "", 'Popularity': 99, 'Odds': 0.0,
                        'TrainingScore': 0.0, 'BloodlineFlag': "",
                        'TrainingEval': "", 'HorseID': "", 'UIndex': 0.0, 'LaboIndex': 0.0
                    }

                    # Weight
                    w_loc = row.locator('td.Weight')
                    if await w_loc.count() > 0:
                        advanced_data[umaban]['WeightStr'] = (await w_loc.first.text_content(timeout=1000)).strip().replace(' ', '')
                    
                    # Popularity
                    pop_loc = row.locator('td.Popular_Ninki, td[class*="Popular_Ninki"]')
                    if await pop_loc.count() > 0:
                        p_txt = (await pop_loc.first.text_content(timeout=1000)).strip()
                        m_p = re.search(r'(\d+)', p_txt)
                        if m_p: advanced_data[umaban]['Popularity'] = int(m_p.group(1))

                    # Odds
                    odds_loc = row.locator('span[id^="odds-"]')
                    if await odds_loc.count() > 0:
                        o_txt = (await odds_loc.first.text_content(timeout=1000)).strip()
                        m_o = re.search(r'(\d+\.\d+)', o_txt)
                        if m_o: advanced_data[umaban]['Odds'] = float(m_o.group(1))

                    # HorseID
                    h_loc = row.locator('td.HorseInfo a, td[class*="Horse"] a')
                    if await h_loc.count() > 0:
                        href = await h_loc.first.get_attribute('href', timeout=1000)
                        if href:
                            m_id = re.search(r'horse/(\d+)', href)
                            if m_id: advanced_data[umaban]['HorseID'] = m_id.group(1)
            except: pass

        # --- 2. Oikiri (Training Tab) ---
        try:
            o_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
            await page.goto(o_url, wait_until='commit', timeout=12000)
            # Use specific class provided by Netkeiba for Oikiri tables
            rows_o = await page.locator('table.OikiriTable tr, tr.HorseList').all()
            for row in rows_o:
                try:
                    cells = await row.locator('td').all()
                    if len(cells) < 3: continue
                    
                    # Identify Umaban
                    u_loc = row.locator('td.Umaban, td[class*="Umaban"]')
                    if await u_loc.count() > 0:
                        u_txt = await u_loc.first.text_content(timeout=1000)
                        m_u = re.search(r'(\d+)', u_txt or '')
                        if m_u:
                            u = int(m_u.group(1))
                            if u in advanced_data:
                                # Standard Evaluation Grade Column (often index 5 or class-based)
                                # Based on HTML verification, the grade is in a cell with classes like 'Rank_...'
                                eval_grade = ""
                                eval_loc = row.locator('td[class^="Rank_"], td.Evaluation')
                                if await eval_loc.count() > 0:
                                    eval_grade = (await eval_loc.first.text_content(timeout=1000)).strip().upper()
                                
                                if not eval_grade and len(cells) >= 6:
                                    # Fallback to column index based on HTML dump
                                    eval_grade = (await cells[5].text_content(timeout=1000)).strip().upper()
                                    
                                m_g = re.search(r'([A-D])', eval_grade)
                                if m_g:
                                    g = m_g.group(1)
                                    advanced_data[u]['TrainingEval'] = g
                                    score_map = {'A': 100.0, 'B': 70.0, 'C': 40.0, 'D': 10.0}
                                    advanced_data[u]['TrainingScore'] = score_map.get(g, 0.0)
                except: pass
        except: pass

        # --- 3. Bloodline ---
        target_umaban = top_horse_ids if top_horse_ids else list(advanced_data.keys())[:10]
        target_h = [(u, advanced_data[u]['HorseID']) for u in target_umaban if u in advanced_data and advanced_data[u]['HorseID']]
        if target_h:
            tasks = [fetch_horse_bloodline(context, h_id) for _, h_id in target_h]
            b_results = await asyncio.gather(*tasks)
            for i, (u, _) in enumerate(target_h):
                advanced_data[u]['BloodlineFlag'] = b_results[i]

        # --- 4. Umanity (U-Index) ---
        if date_str and len(race_id) == 12:
            u_id = f"{date_str}{race_id[4:6]}{race_id[6:8]}{race_id[8:10]}{race_id[10:12]}"
            u_url = f"https://umanity.jp/racedata/race_8.php?code={u_id}"
            try:
                upage = await context.new_page()
                await upage.goto(u_url, timeout=18000, wait_until='commit')
                rows_u = await upage.locator('table.shutuba_table tr, tr.odd, tr.even').all()
                for row_u in rows_u:
                    cells = await row_u.locator('td').all()
                    if len(cells) >= 11:
                        try:
                            # Use Umaban column to match
                            # Umanity table: 0: Waku, 1: Umaban, 2: Mark, 3: U-Index...
                            n_txt = await cells[1].text_content(timeout=500)
                            m_n = re.search(r'(\d+)', n_txt or '')
                            if m_n:
                                u_num = int(m_n.group(1))
                                if u_num in advanced_data:
                                    # Index 3: U-Index
                                    i_txt = await cells[3].text_content(timeout=500)
                                    m_i = re.search(r'(\d+\.?\d*)', i_txt or '')
                                    if m_i:
                                        import math
                                        advanced_data[u_num]['UIndex'] = math.floor(float(m_i.group(1)) * 10) / 10.0
                        except: pass
                await upage.close()
            except: pass

        # --- 5. KeibaLab (Omega Index) ---
        labo_session = "labo_session.json"
        labo_context = context
        if os.path.exists(labo_session):
            # If for some reason we need a separate context for labo (usually not required if cookies don't conflict)
            # but to be safe we just use the same context or check if we should create a new one.
            # For now, let's just use a new context if labo_session exists to avoid confusion with umanity cookies
            labo_context = await browser.new_context(
                user_agent=context_kwargs["user_agent"],
                storage_state=labo_session
            )
        
        labo_url = f"https://www.keibalab.jp/db/race/{race_id}/omega.html"
        try:
            lpage = await labo_context.new_page()
            await lpage.goto(labo_url, timeout=15000, wait_until='commit')
            # Look for Omega Index inside the table
            # Usually in a table with Umaban and OmegaIndex columns
            rows_l = await lpage.locator('table.dbTable tr').all()
            for row_l in rows_l:
                try:
                    cells = await row_l.locator('td').all()
                    if len(cells) >= 5:
                        # Umaban is usually first or second digit
                        txt = await row_l.text_content()
                        # Extract Umaban and Index using positional logic or text search
                        # Omega Index page columns: Umaban, Name, ... Omega Index
                        # Let's try to find Umaban and float index in the same row
                        nums = re.findall(r'(\d+\.?\d*)', txt)
                        if len(nums) >= 2:
                            u_num = int(nums[0])
                            if u_num in advanced_data:
                                # The Omega Index is usually a value like 91.0
                                # It's often at a specific column but let's be robust
                                for n in nums[1:]:
                                    val = float(n)
                                    if 50.0 < val < 130.0: # Heuristic range for Omega Index
                                        advanced_data[u_num]['LaboIndex'] = val
                                        break
                except: pass
            await lpage.close()
        except: pass

        await browser.close()
    return advanced_data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({}))
        sys.exit(0)
    try:
        rid = sys.argv[1]
        top = [int(x) for x in sys.argv[2].split(",") if x.isdigit()] if len(sys.argv) > 2 else []
        res = asyncio.run(fetch_advanced_data(rid, top))
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        print(json.dumps({}))
