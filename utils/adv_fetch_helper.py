import sys
import io
import os
import re
import json
import asyncio
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from scrapling import DynamicFetcher, Fetcher as ScraplingFetcher

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("adv_fetch_helper")

def fetch_advanced_data_dynamic(race_id, top_horse_ids=None):
    """
    Refactored to use Scrapling DynamicFetcher (Playwright).
    Ensures dynamic metrics like U-Index/Omega are rendered before extraction.
    """
    if top_horse_ids is None:
        top_horse_ids = []
    
    advanced_data = {}
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # Session files
    session_path = os.path.join(base_dir, "auth_session.json")
    labo_session_path = os.path.join(base_dir, "labo_session.json")
    
    # 1. --- Netkeiba Shutuba (Real-time Odds & Weight) ---
    fetcher = DynamicFetcher()
    fetcher.configure()
    
    try:
        url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        # network_idle=True (指示A) + タイムアウト延長
        page = fetcher.fetch(url, timeout=35000, network_idle=True)
        soup = BeautifulSoup(page.body, 'html.parser')
        
        for row in soup.find_all('tr', class_=re.compile(r'HorseList|Entry|Horse')):
            try:
                u_td = row.find('td', class_=re.compile(r'Umaban|HorseNum|Waku', re.I))
                if not u_td: continue
                m = re.search(r'(\d+)', u_td.text.strip())
                if not m: continue
                umaban = int(m.group(1))
                
                if umaban not in advanced_data:
                    advanced_data[umaban] = {
                        'WeightStr': "", 'Popularity': 99, 'Odds': 0.0,
                        'TrainingScore': 0.0, 'BloodlineFlag': "",
                        'TrainingEval': "", 'HorseID': "", 'UIndex': 0.0, 'LaboIndex': 0.0
                    }
                
                # Weight (Dynamic)
                w_td = row.find('td', class_='Weight')
                if w_td: advanced_data[umaban]['WeightStr'] = w_td.text.strip().replace(' ', '')
                
                # Ninki/Odds (JS rendered)
                p_td = row.find('td', class_=re.compile(r'Popular', re.I))
                if p_td:
                    p_txt = p_td.text.strip()
                    m_p = re.search(r'(\d+)', p_txt)
                    if m_p: advanced_data[umaban]['Popularity'] = int(m_p.group(1))
                
                o_sp = row.find('span', id=re.compile(r'odds-'))
                if o_sp:
                    o_txt = o_sp.text.strip()
                    m_o = re.search(r'(\d+\.\d+)', o_txt)
                    if m_o: advanced_data[umaban]['Odds'] = float(m_o.group(1))
                
                # HorseID
                h_a = row.find('a', href=re.compile(r'horse/(\d+)'))
                if h_a:
                    m_id = re.search(r'horse/(\d+)', h_a['href'])
                    if m_id: advanced_data[umaban]['HorseID'] = m_id.group(1)
            except: continue
            
        # 1.5 --- Merge Realtime Odds from API (JS rendered elements are often empty in DOM) ---
        try:
            # Determine domain (JRA/NAR)
            rid_str = str(race_id)
            is_nar = len(rid_str) >= 12 and rid_str[4:6] in ('40','41','42','43','44','45','46','47')
            dom = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
            api_url = f"https://{dom}/api/api_get_{'nar' if is_nar else 'jra'}_odds.html?pid=api_get_{'nar' if is_nar else 'jra'}_odds&race_id={race_id}&type=1&action=init&compress=0&output=json"
            api_resp = ScraplingFetcher.get(api_url, impersonate='chrome120', timeout=10)
            if api_resp and api_resp.body:
                api_data = json.loads(api_resp.body)
                ary = api_data.get('ary_odds', {})
                for u_str, v in ary.items():
                    u_int = int(u_str)
                    if u_int in advanced_data:
                        if v.get('Odds'): advanced_data[u_int]['Odds'] = float(v['Odds'])
                        if v.get('Ninki'): advanced_data[u_int]['Popularity'] = int(v['Ninki'])
        except Exception as e:
            sys.stderr.write(f"API Odds fetch failed: {e}\n")

        # 2. --- Netkeiba Oikiri ---
        o_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        page_o = fetcher.fetch(o_url, timeout=15000)
        o_soup = BeautifulSoup(page_o.body, 'html.parser')
        score_map = {'A': 100.0, 'B': 70.0, 'C': 40.0, 'D': 10.0}
        for tr in o_soup.find_all('tr'):
            u_td = tr.find(class_=re.compile(r'Umaban|HorseNum|umaban', re.I))
            if u_td:
                m_u = re.search(r'(\d+)', u_td.text.strip())
                if m_u:
                    um = int(m_u.group(1))
                    if um in advanced_data:
                        eval_grade = ""
                        for el in tr.find_all(class_=re.compile(r'Hyoka|Rank_|TrainRank', re.I)):
                            if el.text.strip().upper() in ('A', 'B', 'C', 'D'):
                                eval_grade = el.text.strip().upper(); break
                        if eval_grade:
                            advanced_data[um]['TrainingEval'] = eval_grade
                            advanced_data[um]['TrainingScore'] = score_map.get(eval_grade, 0.0)
    except Exception as e:
        sys.stderr.write(f"ERROR during Netkeiba Dynamic fetch: {e}\n")

    # 3. --- Bloodline (Fetch Top 10) ---
    target_umaban = top_horse_ids if top_horse_ids else sorted(advanced_data.keys())[:10]
    for u in target_umaban:
        if u in advanced_data and advanced_data[u]['HorseID'] and not advanced_data[u]['BloodlineFlag']:
            h_id = advanced_data[u]['HorseID']
            try:
                db_url = f"https://db.netkeiba.com/horse/ped/{h_id}/"
                # Bloodline is mostly static, Fetcher.get is OK
                p_static = ScraplingFetcher.get(db_url)
                if 'blood_table' in p_static.body:
                    txt = p_static.body
                    flags = []
                    if 'Nijinsky' in txt or 'ニジンスキー' in txt: flags.append('Nijinsky')
                    if 'Sunday Silence' in txt or 'サンデーサイレンス' in txt: flags.append('SS')
                    if 'Roberto' in txt or 'ロベルト' in txt: flags.append('Roberto')
                    advanced_data[u]['BloodlineFlag'] = ",".join(flags)
            except: pass

    # 4. --- Umanity (U-Index) & KeibaLab ---
    # User confirmed environment is safe for Playwright, so we use DynamicFetcher for these too
    try:
        u_id = f"{datetime.now().strftime('%Y')}{str(race_id)[4:12]}"
        u_url = f"https://umanity.jp/racedata/race_8.php?code={u_id}"
        # For Umanity, we might need to handle cookies if redirected.
        # But we try dynamic fetch first.
        # network_idle=True で JS レンダリング待ち
        p_u = fetcher.fetch(u_url, timeout=25000, network_idle=True)
        u_soup = BeautifulSoup(p_u.body, 'html.parser')
        table = u_soup.find('table', class_=re.compile(r'race_table|shutuba_table', re.I))
        if table:
            rows = table.find_all('tr')
            u_col = -1
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if not cells: continue
                if u_col == -1:
                    if 'U指数' in row.text:
                        for idx, c in enumerate(cells):
                            if 'U指数' in c.text: u_col = idx; break
                    continue
                if u_col != -1 and len(cells) >= max(2, u_col + 1):
                    try:
                        m_n = re.search(r'(\d+)', cells[1].text.strip())
                        if m_n:
                            um = int(m_n.group(1))
                            if um in advanced_data:
                                i_txt = cells[u_col].text.strip()
                                m_i = re.search(r'(\d+\.\d+|\d+)', i_txt)
                                if m_i: advanced_data[um]['UIndex'] = float(m_i.group(1))
                    except: pass
    except Exception as e:
        sys.stderr.write(f"ERROR during Umanity fetch: {e}\n")

    try:
        l_url = f"https://www.keibalab.jp/db/race/{race_id}/syutsuba.html"
        # network_idle=True で JS レンダリング待ち
        p_l = fetcher.fetch(l_url, timeout=25000, network_idle=True)
        l_soup = BeautifulSoup(p_l.body, 'html.parser')
        table = l_soup.find('table', class_=re.compile(r'dbTable|shutubaTable', re.I))
        if table:
            rows = table.find_all('tr')
            l_col = -1
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if not cells: continue
                if l_col == -1:
                    if '指数' in row.text or 'オメガ' in row.text:
                        for idx, c in enumerate(cells):
                            if '指数' in c.text or 'オメガ' in c.text: l_col = idx; break
                    continue
                if len(cells) >= max(2, l_col + 1):
                    try:
                        m_u = re.search(r'(\d+)', cells[1].text.strip())
                        if m_u:
                            um = int(m_u.group(1))
                            if um in advanced_data:
                                o_txt = cells[l_col].text.strip()
                                m_o = re.search(r'(\d+\.\d+|\d+)', o_txt)
                                if m_o: advanced_data[um]['LaboIndex'] = float(m_o.group(1))
                    except: pass
    except Exception as e:
        sys.stderr.write(f"ERROR during KeibaLab fetch: {e}\n")

    return advanced_data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({}))
        sys.exit(0)
    try:
        rid = sys.argv[1]
        top = [int(x) for x in sys.argv[2].split(",") if x.isdigit()] if len(sys.argv) > 2 else []
        # Synchronous execution is fine for this helper
        res = fetch_advanced_data_dynamic(rid, top)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        print(json.dumps({}))
