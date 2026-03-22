import sys
import io
import os
import re
import json
import logging
from datetime import datetime
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("adv_fetch_helper")

def _static_get(url, timeout=60):
    """ScraplingFetcher でHTMLを静的取得。失敗時は requests にフォールバック。"""
    try:
        from scrapling import Fetcher as ScraplingFetcher
        # Ensure impersonate='chrome120' is explicitly used
        resp = ScraplingFetcher(impersonate='chrome120').get(url, timeout=timeout)
        if resp and resp.body:
            return resp.body
    except Exception as e:
        logger.warning(f"[Scrapling] fell back to requests: {e}")
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            for enc in ['euc-jp', 'cp932', 'utf-8']:
                try: return resp.content.decode(enc)
                except: pass
    except Exception as e:
        logger.warning(f"[Requests] failed: {e}")
    return ""

def _dynamic_get(url, timeout=60000):
    """
    Scrapling v0.4.x 準拠: 動的取得。
    timeout=60000, wait_until="domcontentloaded" を適用する。
    """
    try:
        from scrapling import Fetcher as ScraplingFetcher
        # 先に impersonate="chrome120" で静的fetchを試行（高速かつ大半のサイトで十分なため）
        html_static = _static_get(url, timeout=60)
        # Javascript Render要素（オメガ等）が見当たらなければ Playwright へフォールバックする
        is_dynamic_needed = False
        if "keibalab" in url and "オメガ" not in html_static and "指数" not in html_static:
            is_dynamic_needed = True

        if not is_dynamic_needed and html_static:
            return html_static

        # Playwright による動的取得
        from scrapling import StealthyFetcher
        # kwargs として additional_args や wait_until などを可能な限り渡す
        page = StealthyFetcher.fetch(
            url,
            headless=True,
            timeout=timeout,
            disable_resources=True,
            additional_args={"wait_until": "domcontentloaded"}
        )
        if page and page.body:
            return page.body
    except Exception as e:
        logger.warning(f"[StealthyFetcher] failed for {url}: {e}")
    # 初回に失敗していれば Fallback は空
    return html_static if 'html_static' in locals() else ""

def fetch_advanced_data_dynamic(race_id, top_horse_ids=None):
    """
    Refactored to use Scrapling v0.4.x API (DynamicFetcher.fetch() class-method form).
    Ensures dynamic metrics like U-Index/Omega are rendered before extraction.
    """
    if top_horse_ids is None:
        top_horse_ids = []

    advanced_data = {}
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. --- Netkeiba Shutuba (Real-time Weight) ---
    try:
        url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
        html = _dynamic_get(url, timeout=30000)
        soup = BeautifulSoup(html, 'html.parser')

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

                # Weight
                w_td = row.find('td', class_='Weight')
                if w_td: advanced_data[umaban]['WeightStr'] = w_td.text.strip().replace(' ', '')

                # Ninki/Odds (JS rendered)
                p_td = row.find('td', class_=re.compile(r'Popular', re.I))
                if p_td:
                    m_p = re.search(r'(\d+)', p_td.text.strip())
                    if m_p: advanced_data[umaban]['Popularity'] = int(m_p.group(1))

                o_sp = row.find('span', id=re.compile(r'odds-'))
                if o_sp:
                    m_o = re.search(r'(\d+\.\d+)', o_sp.text.strip())
                    if m_o: advanced_data[umaban]['Odds'] = float(m_o.group(1))

                # HorseID
                h_a = row.find('a', href=re.compile(r'horse/(\d+)'))
                if h_a:
                    m_id = re.search(r'horse/(\d+)', h_a['href'])
                    if m_id: advanced_data[umaban]['HorseID'] = m_id.group(1)
            except: continue
    except Exception as e:
        sys.stderr.write(f"ERROR during Netkeiba Shutuba fetch: {e}\n")

    # 1.5 --- Realtime Odds API ---
    try:
        rid_str = str(race_id)
        is_nar = len(rid_str) >= 12 and rid_str[4:6] in ('40','41','42','43','44','45','46','47')
        dom = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
        api_url = f"https://{dom}/api/api_get_{'nar' if is_nar else 'jra'}_odds.html?pid=api_get_{'nar' if is_nar else 'jra'}_odds&race_id={race_id}&type=1&action=init&compress=0&output=json"
        html_api = _static_get(api_url, timeout=10)
        if html_api:
            api_data = json.loads(html_api)
            ary = api_data.get('ary_odds', {})
            for u_str, v in ary.items():
                u_int = int(u_str)
                if u_int in advanced_data:
                    if v.get('Odds'): advanced_data[u_int]['Odds'] = float(v['Odds'])
                    if v.get('Ninki'): advanced_data[u_int]['Popularity'] = int(v['Ninki'])
    except Exception as e:
        sys.stderr.write(f"API Odds fetch failed: {e}\n")

    # 2. --- Netkeiba Oikiri (調教) ---
    try:
        o_url = f"https://race.netkeiba.com/race/oikiri.html?race_id={race_id}"
        html_o = _dynamic_get(o_url, timeout=20000)
        o_soup = BeautifulSoup(html_o, 'html.parser')
        score_map = {'A': 100.0, 'B': 70.0, 'C': 40.0, 'D': 10.0}
        for tr in o_soup.find_all('tr'):
            u_td = tr.find(class_=re.compile(r'Umaban|HorseNum|umaban', re.I))
            if not u_td: continue
            m_u = re.search(r'(\d+)', u_td.text.strip())
            if not m_u: continue
            um = int(m_u.group(1))
            if um not in advanced_data: continue
            eval_grade = ""
            for el in tr.find_all(class_=re.compile(r'Hyoka|Rank_|TrainRank', re.I)):
                if el.text.strip().upper() in ('A', 'B', 'C', 'D'):
                    eval_grade = el.text.strip().upper(); break
            if not eval_grade:
                # テキスト全体から 1文字A-Dを探す
                m_g = re.search(r'\b([ABCD])\b', tr.text.strip())
                if m_g: eval_grade = m_g.group(1)
            if eval_grade:
                advanced_data[um]['TrainingEval'] = eval_grade
                advanced_data[um]['TrainingScore'] = score_map.get(eval_grade, 0.0)
    except Exception as e:
        sys.stderr.write(f"ERROR during Oikiri (Training) fetch: {e}\n")

    # 3. --- Bloodline (Fetch Top 10) ---
    target_umaban = top_horse_ids if top_horse_ids else sorted(advanced_data.keys())[:10]
    for u in target_umaban:
        if u in advanced_data and advanced_data[u]['HorseID'] and not advanced_data[u]['BloodlineFlag']:
            h_id = advanced_data[u]['HorseID']
            try:
                db_url = f"https://db.netkeiba.com/horse/ped/{h_id}/"
                html_b = _static_get(db_url)
                if 'blood_table' in html_b:
                    flags = []
                    if 'Nijinsky' in html_b or 'ニジンスキー' in html_b: flags.append('Nijinsky')
                    if 'Sunday Silence' in html_b or 'サンデーサイレンス' in html_b: flags.append('SS')
                    if 'Roberto' in html_b or 'ロベルト' in html_b: flags.append('Roberto')
                    advanced_data[u]['BloodlineFlag'] = ",".join(flags)
            except: pass

    # 4. --- Umanity (U-Index) ---
    try:
        # umanity の race code（12桁 race_id から年 + 8桁 コードで組み立て）
        u_id = f"{datetime.now().strftime('%Y')}{str(race_id)[4:12]}"
        u_url = f"https://umanity.jp/racedata/race_8.php?code={u_id}"
        html_u = _dynamic_get(u_url, timeout=25000)
        u_soup = BeautifulSoup(html_u, 'html.parser')
        table = u_soup.find('table', class_=re.compile(r'race_table|shutuba_table', re.I))
        if table:
            u_col = -1
            for row in table.find_all('tr'):
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
                                m_i = re.search(r'(\d+\.\d+|\d+)', cells[u_col].text.strip())
                                if m_i: advanced_data[um]['UIndex'] = float(m_i.group(1))
                    except: pass
    except Exception as e:
        sys.stderr.write(f"ERROR during Umanity (U-Index) fetch: {e}\n")

    # 5. --- KeibaLab (オメガ指数) ---
    try:
        l_url = f"https://www.keibalab.jp/db/race/{race_id}/syutsuba.html"
        html_l = _dynamic_get(l_url, timeout=25000)
        l_soup = BeautifulSoup(html_l, 'html.parser')
        table = l_soup.find('table', class_=re.compile(r'dbTable|shutubaTable', re.I))
        if table:
            l_col = -1
            for row in table.find_all('tr'):
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
                                m_o = re.search(r'(\d+\.\d+|\d+)', cells[l_col].text.strip())
                                if m_o: advanced_data[um]['LaboIndex'] = float(m_o.group(1))
                    except: pass
    except Exception as e:
        sys.stderr.write(f"ERROR during KeibaLab (omega) fetch: {e}\n")

    # 6. --- Netkeiba Time Index (タイム指数 type=9) ---
    try:
        t_url = f"https://race.netkeiba.com/race/index.html?race_id={race_id}&type=9"
        html_t = _dynamic_get(t_url, timeout=25000)
        t_soup = BeautifulSoup(html_t, 'html.parser')
        # タイム指数のテーブルを探索
        t_table = t_soup.find('table', class_=re.compile(r'RaceTable|shutubaTable', re.I))
        if t_table:
            ti_col = -1
            for row in t_table.find_all('tr'):
                cells = row.find_all(['td', 'th'])
                if not cells: continue
                # ヘッダー行で「タイム指数」の列を探す
                if ti_col == -1:
                    header_text = row.get_text()
                    if '指数' in header_text:
                        for idx, c in enumerate(cells):
                            if '指数' in c.get_text():
                                ti_col = idx
                                break
                    continue
                
                # データ行の処理
                if ti_col != -1 and len(cells) >= max(2, ti_col + 1):
                    try:
                        # 馬番を取得
                        m_u = re.search(r'(\d+)', cells[1].get_text(strip=True))
                        if m_u:
                            um = int(m_u.group(1))
                            if um in advanced_data:
                                # 指数値を取得（--- 等は 0.0 とする）
                                val_text = cells[ti_col].get_text(strip=True)
                                m_ti = re.search(r'(\d+\.\d+|\d+)', val_text)
                                if m_ti:
                                    advanced_data[um]['TimeIndex'] = float(m_ti.group(1))
                                else:
                                    advanced_data[um]['TimeIndex'] = 0.0
                    except: pass
    except Exception as e:
        sys.stderr.write(f"ERROR during Netkeiba TimeIndex (type=9) fetch: {e}\n")

    return advanced_data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({}))
        sys.exit(0)
    try:
        rid = sys.argv[1]
        top = [int(x) for x in sys.argv[2].split(",") if x.isdigit()] if len(sys.argv) > 2 else []
        res = fetch_advanced_data_dynamic(rid, top)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        print(json.dumps({}))
