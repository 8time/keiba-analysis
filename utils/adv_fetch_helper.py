import sys
import io
import os
import re
import json
import asyncio
import logging
from datetime import datetime
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

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
        # Session files are in the parent directory (project root)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        session_path = os.path.join(base_dir, "auth_session.json")
        labo_session_path = os.path.join(base_dir, "labo_session.json")
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        context_kwargs = {"user_agent": ua}
        if os.path.exists(session_path):
            context_kwargs["storage_state"] = session_path
            sys.stderr.write(f"DEBUG: Loaded auth_session.json for Umanity\n")

        context = await browser.new_context(**context_kwargs)

        # Separate context for KeibaLab (labo_session.json)
        labo_context_kwargs = {"user_agent": ua}
        if os.path.exists(labo_session_path):
            labo_context_kwargs["storage_state"] = labo_session_path
            sys.stderr.write(f"DEBUG: Loaded labo_session.json for KeibaLab\n")
        labo_context = await browser.new_context(**labo_context_kwargs)

        page = await context.new_page()
        
        # --- 1. Shutuba Page ---
        shutuba_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        try:
            await page.goto(shutuba_url, timeout=20000, wait_until='commit')
            await page.wait_for_selector('tr.HorseList, tr.Entry', timeout=8000)
        except: pass
            
        # --- 0. Extract Race Date (CRITICAL for Umanity) ---
        date_str = ""
        try:
            title = await page.title()
            m_date = re.search(r'(\d{4})年(\d+)月(\d+)日', title)
            if m_date:
                # Format to YYYYMMDD
                date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
            
            if not date_str:
                # Try finding date in specific meta tags or text
                date_loc = page.locator('.RaceData01')
                if await date_loc.count() > 0:
                    dt_txt = await date_loc.first.text_content()
                    m_date = re.search(r'(\d{4})[年/](\d+)[月/](\d+)', dt_txt or "")
                    if m_date:
                        date_str = f"{m_date.group(1)}{m_date.group(2).zfill(2)}{m_date.group(3).zfill(2)}"
            
            if not date_str and race_id and len(str(race_id)) >= 4:
                # Last resort fallback: Year from ID + current month/day
                date_str = f"{str(race_id)[:4]}{datetime.now().strftime('%m%d')}"
                
            sys.stderr.write(f"DEBUG: Date extracted: {date_str} for {race_id}\n")
        except Exception as e:
            sys.stderr.write(f"DEBUG: Date extraction failed: {e}\n")

        # Row extraction from Shutuba
        rows = await page.locator('tr.HorseList, tr.Entry, tr[class*="Horse"]').all()
        logger.debug(f"Found {len(rows)} horse rows on Shutuba page for {race_id}")
        for row in rows:
            try:
                # Better Umaban selector
                um_loc = row.locator('td.Umaban, td[class*="Umaban"], td.Waku')
                if await um_loc.count() > 0:
                    txt = (await um_loc.first.text_content(timeout=1000)).strip()
                    m = re.search(r'(\d+)', txt)
                    if not m: 
                        txt = await um_loc.first.inner_text()
                        m = re.search(r'(\d+)', txt)
                    
                    if m:
                        umaban = int(m.group(1))
                        if umaban not in advanced_data:
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
        
        # Ensure top_horse_ids exist in advanced_data even if shutuba parse failed
        if top_horse_ids:
            for u in top_horse_ids:
                if u not in advanced_data:
                    advanced_data[u] = {
                        'WeightStr': "", 'Popularity': 99, 'Odds': 0.0,
                        'TrainingScore': 0.0, 'BloodlineFlag': "",
                        'TrainingEval': "", 'HorseID': "", 'UIndex': 0.0, 'LaboIndex': 0.0
                    }

        # --- 2. Oikiri (Training Tab) ---
        # Strategy: get full HTML then parse with BS4 (more reliable than locator selectors)
        try:
            o_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
            await page.goto(o_url, wait_until='domcontentloaded', timeout=15000)
            try:
                await page.wait_for_selector('table', timeout=8000)
            except: pass

            o_html = await page.content()
            o_soup = BeautifulSoup(o_html, 'html.parser')
            sys.stderr.write(f"DEBUG Oikiri: got HTML len={len(o_html)}\n")

            # Detect "評価" header column index
            eval_col_idx = -1
            for tbl in o_soup.find_all('table'):
                header_row = tbl.find('tr')
                if not header_row: continue
                ths = header_row.find_all(['th', 'td'])
                for idx, th in enumerate(ths):
                    txt = th.get_text(strip=True)
                    if '評価' in txt or '評価' in txt:
                        eval_col_idx = idx
                        break
                if eval_col_idx >= 0:
                    break
            sys.stderr.write(f"DEBUG Oikiri: eval_col_idx={eval_col_idx}\n")

            score_map = {'A': 100.0, 'B': 70.0, 'C': 40.0, 'D': 10.0}

            # Parse all rows across all tables
            for tr in o_soup.find_all('tr'):
                tds = tr.find_all('td')
                if len(tds) < 3: continue

                # 1. Find umaban: td.Umaban or first numeric-only cell with value 1-18
                umaban = None
                u_td = tr.find('td', class_=re.compile(r'Umaban', re.I))
                if u_td:
                    m_u = re.search(r'(\d+)', u_td.get_text())
                    if m_u: umaban = int(m_u.group(1))
                if umaban is None:
                    # Fallback: first 1-2 cells that are single numbers 1-18
                    for td in tds[:3]:
                        ct = td.get_text(strip=True)
                        if ct.isdigit() and 1 <= int(ct) <= 18:
                            umaban = int(ct)
                            break

                if umaban is None or umaban not in advanced_data:
                    continue

                # 2. Find grade: class-based first, then header-col, then scan all cells
                eval_grade = ""

                # a) Class-based: span/td with class containing Hyoka/Hyouka/Rank_ + letter
                for el in tr.find_all(class_=re.compile(r'Hyoka|Hyouka|Rank_|OikiriRank', re.I)):
                    cls_str = ' '.join(el.get('class', [])).upper()
                    m_c = re.search(r'(?:HYOKA|HYOUKA|RANK)[_-]?([A-D])\b', cls_str)
                    if m_c:
                        eval_grade = m_c.group(1)
                        break
                    # Also check text content
                    txt = el.get_text(strip=True).upper()
                    if txt in ('A', 'B', 'C', 'D'):
                        eval_grade = txt
                        break

                # b) Header column index
                if not eval_grade and eval_col_idx >= 0 and len(tds) > eval_col_idx:
                    ct = tds[eval_col_idx].get_text(strip=True).upper()
                    if ct in ('A', 'B', 'C', 'D'):
                        eval_grade = ct

                # c) Scan every cell for isolated A/B/C/D
                if not eval_grade:
                    for td in tds:
                        ct = td.get_text(strip=True).upper()
                        if ct in ('A', 'B', 'C', 'D'):
                            eval_grade = ct
                            break

                if eval_grade:
                    advanced_data[umaban]['TrainingEval'] = eval_grade
                    advanced_data[umaban]['TrainingScore'] = score_map.get(eval_grade, 0.0)
                    sys.stderr.write(f"DEBUG Oikiri: horse {umaban} → {eval_grade}\n")

        except Exception as e:
            sys.stderr.write(f"ERROR: Oikiri fetch failed: {e}\n")

        # --- 3. Bloodline (Concurrency Limited) ---
        target_umaban = top_horse_ids if top_horse_ids else list(advanced_data.keys())[:10]
        target_h = [(u, advanced_data[u]['HorseID']) for u in target_umaban if u in advanced_data and advanced_data[u]['HorseID']]
        if target_h:
            sem = asyncio.Semaphore(5) # Max 5 concurrent bloodline pages
            async def limited_bloodline(u, h_id):
                async with sem:
                    res = await fetch_horse_bloodline(context, h_id)
                    advanced_data[u]['BloodlineFlag'] = res
            
            await asyncio.gather(*[limited_bloodline(u, h_id) for u, h_id in target_h])

        # --- 4. Umanity (U-Index) ---
        if date_str and len(str(race_id)) == 12:
            rid_str = str(race_id)
            # JRA 16-digit code: YYYYMMDD + Venue(2) + Meeting(2) + Day(2) + Race(2)
            u_id = f"{date_str}{rid_str[4:]}"
            u_url = f"https://umanity.jp/racedata/race_8.php?code={u_id}"
            sys.stderr.write(f"DEBUG: Umanity URL: {u_url}\n")
            try:
                upage = await context.new_page()
                await upage.goto(u_url, timeout=20000, wait_until='domcontentloaded')
                
                u_title = await upage.title()
                if "ログイン" in u_title or "Login" in u_title:
                    sys.stderr.write("WARNING: Umanity redirected to login. Session might be invalid.\n")
                
                u_col = -1
                rows_u = await upage.locator('.race_table_01 tr, table.shutuba_table tr, table#shutubatable tr, tr.odd, tr.even').all()
                for i, row_u in enumerate(rows_u):
                    cells = await row_u.locator('td, th').all()
                    if not cells: continue
                    
                    # 1. Detect Header
                    if u_col == -1:
                        row_txt = await row_u.inner_text()
                        if 'U指数' in row_txt or '指数' in row_txt:
                            for c_idx, cell in enumerate(cells):
                                c_txt = await cell.text_content()
                                if 'U指数' in (c_txt or ''):
                                    u_col = c_idx
                                    break
                        continue # Skip header row or look for header
                    
                    # 2. Extract Data using dynamic column
                    if len(cells) >= max(2, u_col + 1):
                        try:
                            n_txt = await cells[1].text_content()
                            m_n = re.search(r'(\d+)', n_txt or '')
                            if m_n:
                                u_num = int(m_n.group(1))
                                if u_num in advanced_data:
                                    target_col = u_col if u_col != -1 else 3
                                    i_txt = (await cells[target_col].text_content()).strip()
                                    if '**' in i_txt: continue
                                    m_i = re.search(r'(\d+\.\d+|\d+)', i_txt)
                                    if m_i:
                                        import math
                                        advanced_data[u_num]['UIndex'] = math.floor(float(m_i.group(1)) * 10) / 10.0
                        except: pass
                await upage.close()
            except Exception as e:
                sys.stderr.write(f"ERROR: Umanity fetch failed: {e}\n")

        # --- 5. KeibaLab (Omega Index) ---
        labo_url = f"https://www.keibalab.jp/db/race/{race_id}/syutsuba.html"
        sys.stderr.write(f"DEBUG: KeibaLab URL: {labo_url}\n")
        try:
            lpage = await labo_context.new_page()  # Use labo_context with labo_session.json
            await lpage.goto(labo_url, timeout=20000, wait_until='domcontentloaded')
            
            l_col = -1
            rows_l = await lpage.locator('table.dbTable tr, .shutubaTable tr, table tr').all()
            for row_l in rows_l:
                cells = await row_l.locator('td, th').all()
                if not cells: continue
                
                # 1. Detect Header
                if l_col == -1:
                    row_txt = await row_l.inner_text()
                    if '指数' in row_txt or 'オメガ' in row_txt:
                        for c_idx, cell in enumerate(cells):
                            c_txt = await cell.text_content()
                            if '指数' in (c_txt or '') or 'オメガ' in (c_txt or ''):
                                l_col = c_idx
                                break
                    continue
                
                # 2. Data extraction
                try:
                    if len(cells) >= max(2, l_col + 1):
                        u_txt = await cells[1].text_content()
                        m_u = re.search(r'(\d+)', u_txt or "")
                        if m_u:
                            u_num = int(m_u.group(1))
                            if u_num in advanced_data:
                                target_col = l_col if l_col != -1 else 7
                                o_txt = await cells[target_col].text_content()
                                m_o = re.search(r'(\d+\.\d+|\d+)', o_txt or "")
                                if m_o:
                                    advanced_data[u_num]['LaboIndex'] = float(m_o.group(1))
                except: pass
            await lpage.close()
        except Exception as e:
            sys.stderr.write(f"ERROR: KeibaLab fetch failed: {e}\n")

        await labo_context.close()
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
