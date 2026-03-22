import requests
from scrapling import Fetcher
from bs4 import BeautifulSoup
import re
import logging

logger = logging.getLogger(__name__)

def fetch_horse_weights(race_id):
    """
    [Scrapling v0.4.2 準拠]
    競馬ラボから馬体重と増減を抽出する (スピード優先: requests)
    """
    url = f"https://www.keibalab.jp/db/race/{race_id}/syutsuba.html"
    weights = {}
    
    try:
        logger.info(f"[LabFetcher] fetching weights: {url}")
        html = None
        
        # 1. Try requests first (Fast)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.keibalab.jp/"
        }
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                html = r.text
        except:
            pass
            
        # 2. Fallback to Scrapling
        if not html:
            fetcher = Fetcher(impersonate="chrome120")
            response = fetcher.get(url, timeout=12)
            if response and response.body:
                html = response.body.decode('utf-8', errors='ignore') if isinstance(response.body, bytes) else response.body

        if not html:
            return {}
            
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. テーブルを探す (table_sh は今日のレースなどで使われる)
        table = soup.select_one('table.table_sh') or soup.select_one('table.db_table') or soup.find('table')
        if not table:
            return {}
            
        # 2. ヘッダーから「馬体重」の列番号を探す
        target_col_idx = -1
        header_row = table.find('tr')
        if header_row:
            ths = header_row.find_all(['th', 'td'])
            for i, th in enumerate(ths):
                if "馬体重" in th.get_text():
                    target_col_idx = i
                    break
                    
        # 3. 馬番と体重を抽出
        # 馬番の列は通常 'umaban' クラスが付いている
        rows = table.find_all('tr')[1:] # ヘッダー以降
        for row in rows:
            tds = row.find_all('td')
            if len(tds) < 2:
                continue
                
            # 馬番列を探す
            umaban_td = row.find('td', class_=re.compile(r'umaban', re.I))
            umaban_text = ""
            if umaban_td:
                umaban_text = umaban_td.get_text(strip=True)
            else:
                # 1番目の列を馬番とみなす（フォールバック）
                umaban_text = tds[0].get_text(strip=True)
                
            m_num = re.search(r'(\d+)', umaban_text)
            if not m_num:
                continue
            num_key = m_num.group(1).zfill(2)
            
            # 体重列 (インデックスで見つかった場合)
            if target_col_idx != -1 and target_col_idx < len(tds):
                weight_text = tds[target_col_idx].get_text(strip=True)
            else:
                # 'weight' クラスを探す
                weight_td = row.find('td', class_=re.compile(r'weight', re.I))
                weight_text = weight_td.get_text(strip=True) if weight_td else ""
                
            if weight_text and weight_text != "--":
                weights[num_key] = weight_text
                
        if weights:
            logger.info(f"[LabFetcher] OK: Found {len(weights)} weights")
            
    except Exception as e:
        logger.error(f"[LabFetcher] Error: {e}")
        
    return weights
