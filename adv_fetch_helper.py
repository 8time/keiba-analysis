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

async def fetch_advanced_data(race_id, top_horse_ids=None):
    if top_horse_ids is None:
        top_horse_ids = []
        
    advanced_data = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        # Check for saved session
        session_path = "auth_session.json"
        
        context_kwargs = {
            "user_agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        }
        if os.path.exists(session_path):
            context_kwargs["storage_state"] = session_path
            
        context = await browser.new_context(**context_kwargs)
        
        page = await context.new_page()
        
        shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            await page.goto(shutuba_url, timeout=30000, wait_until='domcontentloaded')
        except:
            pass
        
        try:
            await page.wait_for_selector('table.Shutuba_Table', timeout=10000)
        except:
            pass
            
        # --- 1.1 Extract Race Date ---
        date_str = ""
        try:
            meta_desc_loc = page.locator('meta[property="og:description"]')
            if await meta_desc_loc.count() > 0:
                meta_desc = await meta_desc_loc.get_attribute('content', timeout=3000)
                if meta_desc:
                    m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', meta_desc)
                    if m_date:
                        date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
            
            if not date_str:
                title = await page.title()
                m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', title)
                if m_date:
                    date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
        except Exception as e:
            sys.stderr.write(f"DEBUG: Date Extraction Error: {e}\n")
            pass

        # Use Locator.all() to get a list of Locators for each row
        rows = await page.locator('tr.HorseList').all()
        
        for row in rows:
            try:
                # Find Umaban (Horse Number) - usually td.Umaban or td.Umaban1, etc.
                umaban_loc = row.locator('td[class*="Umaban"]')
                if await umaban_loc.count() > 0:
                    umaban_text = (await umaban_loc.first.text_content(timeout=1000)).strip()
                    m_num = re.search(r'(\d+)', umaban_text)
                    umaban = int(m_num.group(1)) if m_num else 0
                    
                    # Weight - td.Weight or td.Weight_Info
                    weight_loc = row.locator('td[class*="Weight"]')
                    weight_str = (await weight_loc.first.text_content(timeout=1000)).strip() if await weight_loc.count() > 0 else ""
                    
                    # HorseID - td.HorseInfo a or td.HorseName a
                    horse_link_loc = row.locator('td[class*="Horse"] a')
                    horse_id = ""
                    if await horse_link_loc.count() > 0:
                        horse_link = await horse_link_loc.first.get_attribute('href', timeout=1000)
                        if horse_link:
                            # e.g. /horse/2021105051/ or https://db.netkeiba.com/horse/2021105051/
                            m_id = re.search(r'horse/(\d+)', horse_link)
                            if m_id: horse_id = m_id.group(1)
                        
                    if umaban > 0:
                        advanced_data[umaban] = {
                            'WeightStr': weight_str,
                            'TrainingScore': 0.0,
                            'BloodlineFlag': "",
                            'TrainingEval': "",
                            'HorseID': horse_id,
                            'UIndex': 0.0,
                            'LaboIndex': 0.0
                        }
            except Exception as e:
                sys.stderr.write(f"DEBUG: Error parsing row: {e}\n")

        # --- 2. Fetch Training Evaluation from oikiri.html ---
        oikiri_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        try:
            await page.goto(oikiri_url, wait_until='domcontentloaded', timeout=20000)
            rows = await page.locator('tr.HorseList, table.RaceTable01 tr').all()
            for row in rows:
                try:
                    umaban_loc = row.locator('td[class*="Umaban"]')
                    if await umaban_loc.count() > 0:
                        umaban_text = await umaban_loc.first.text_content(timeout=1000)
                        umaban = int(re.search(r'(\d+)', umaban_text).group(1)) if re.search(r'(\d+)', umaban_text) else 0
                        
                        eval_str = await row.locator('td[class^="Rank_"], td.OikiriEvaluation, td.sk__rank, td.Evaluation').first.text_content(timeout=2000) if await row.locator('td[class^="Rank_"], td.OikiriEvaluation, td.sk__rank, td.Evaluation').count() > 0 else ""
                        if not eval_str:
                            td_texts = await row.locator('td').all_text_contents()
                            for t in td_texts:
                                t = t.strip()
                                if len(t) == 1 and t in "ABCD":
                                    eval_str = t
                                    break
                        eval_str = eval_str.strip().upper() if eval_str else ""
                        match_grade = re.search(r'([A-D])', eval_str)
                        eval_grade = match_grade.group(1) if match_grade else ""
                        score_bonus = {'A': 100.0, 'B': 70.0, 'C': 40.0, 'D': 10.0}.get(eval_grade, 0.0)
                        if umaban in advanced_data:
                            advanced_data[umaban]['TrainingScore'] = score_bonus
                            advanced_data[umaban]['TrainingEval'] = eval_grade
                except Exception as e:
                    pass
        except:
            pass

        # --- 3. Fetch Bloodline ---
        # Only for top horses if provided, else all
        target_umaban = top_horse_ids if top_horse_ids else list(advanced_data.keys())
        target_horse_info = [(u, advanced_data[u]['HorseID']) for u in target_umaban if u in advanced_data and advanced_data[u]['HorseID']]
        
        for u, h_id in target_horse_info:
            pedigree_url = f"https://db.netkeiba.com/horse/ped/{h_id}/"
            try:
                await page.goto(pedigree_url, wait_until='domcontentloaded', timeout=10000)
                blood_table_loc = page.locator('.blood_table')
                if await blood_table_loc.count() > 0:
                    blood_table = await blood_table_loc.first.text_content(timeout=3000)
                    blood_table = blood_table or ""
                    flags = []
                    if any(x in blood_table for x in ['Nijinsky', 'ニジンスキー']): flags.append('Nijinsky')
                    if any(x in blood_table for x in ['Sunday Silence', 'サンデーサイレンス']): flags.append('SS')
                    if any(x in blood_table for x in ['Roberto', 'ロベルト']): flags.append('Roberto')
                    advanced_data[u]['BloodlineFlag'] = ",".join(flags)
            except:
                pass

        # --- 4. External Indices ---
        if len(race_id) == 12 and date_str:
            # Netkeiba ID: YYYY(4) + VenueCode(2) + MeetCount(2) + DayCount(2) + RaceNum(2) = 12 digits
            # Example: 202409010411 (Hanshin, 1st meet, 4th day, 11R)
            
            # --- 4.1 U-Index (Umanity) ---
            # Umanity ID format: YYYYMMDD + VenueCode(2) + Meet(2) + Day(2) + RaceNum(2) = 16 digits
            venue_code_nk = race_id[4:6]
            meet_count = race_id[6:8]
            day_count = race_id[8:10]
            race_num = race_id[10:12]
            
            # Mapping Netkeiba Venue -> Umanity Venue
            nk_to_umanity_venue = {
                '01': '01', # Sapporo
                '02': '02', # Hakodate
                '03': '03', # Fukushima
                '04': '04', # Niigata
                '05': '05', # Tokyo
                '06': '06', # Nakayama
                '07': '07', # Chukyo
                '08': '08', # Kyoto
                '09': '09', # Hanshin
                '10': '10'  # Kokura
            }
            u_venue = nk_to_umanity_venue.get(venue_code_nk, venue_code_nk)
            
            umanity_id = f"{date_str}{u_venue}{meet_count}{day_count}{race_num}"
            u_url = f"https://umanity.jp/racedata/race_7.php?code={umanity_id}"
            try:
                upage = await context.new_page()
                await upage.goto(u_url, timeout=30000, wait_until='domcontentloaded')
                rows = await upage.locator('tr.odd, tr.even').all()
                for row in rows:
                    cells = await row.locator('td').all()
                    if len(cells) >= 3:
                        try:
                            u_text = await cells[0].text_content(timeout=1000)
                            horse_links = await cells[2].locator('a').all()
                            if horse_links:
                                href = await horse_links[0].get_attribute('href')
                                m_id = re.search(r'code=(\d{10})', href or '')
                                if m_id:
                                    hid = m_id.group(1)
                                    m_val = re.search(r'(\d+\.?\d*)', u_text or '')
                                    if m_val:
                                        for u_num, d in advanced_data.items():
                                            if d.get('HorseID') == hid:
                                                d['UIndex'] = float(m_val.group(1))
                                                break
                        except Exception as e:
                            pass
                await upage.close()
            except Exception as e:
                pass

            # --- 4.2 Labo-Index (Keibalab Ω Index) ---
            # Keibalab ID format: YYYYMMDD + VenueCode(2) + RaceNum(2) = 12 digits
            # Using syutsuba.html as yoso.html requires login on Keibalab.
            keibalab_id = f"{date_str}{venue_code_nk}{race_num}"
            l_url = f"https://www.keibalab.jp/db/race/{keibalab_id}/syutsuba.html"
            try:
                lpage = await context.new_page()
                await lpage.goto(l_url, timeout=30000, wait_until='domcontentloaded')
                h_rows = await lpage.locator('tr').all()
                for row in h_rows:
                    try:
                        cells = await row.locator('td').all()
                        if len(cells) >= 8:
                            u_text = await cells[1].text_content(timeout=1000)
                            s_text = await cells[7].text_content(timeout=1000)
                            m_num = re.search(r'^\s*(\d+)\s*$', u_text or '')
                            if m_num:
                                l_num = int(m_num.group(1))
                                if l_num in advanced_data:
                                    m_val = re.search(r'(\d+\.?\d*)', s_text or '')
                                    if m_val: 
                                        advanced_data[l_num]['LaboIndex'] = float(m_val.group(1))
                    except Exception as e:
                        pass
                await lpage.close()
            except Exception as e:
                pass
        else:
            pass
        
        await browser.close()
    return advanced_data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({}))
        sys.exit(0)
        
    rid = sys.argv[1]
    top_ids = []
    if len(sys.argv) > 2:
        top_ids = [int(x) for x in sys.argv[2].split(",") if x.isdigit()]
        
    try:
        # sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        result = asyncio.run(fetch_advanced_data(rid, top_ids))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        # Don't print to stdout to avoid corrupting JSON
        sys.stderr.write(str(e))
        print(json.dumps({}))
