try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import concurrent.futures

try:
    from core.scraper import get_shared_fetcher
except ImportError:
    get_shared_fetcher = lambda: None

if HAS_FASTAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], 
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app = None

# ⚠️ 文字化け回避ルール準拠
def load_json_file(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return default_val

# 1. 個別調整用（既存）
sire_db = load_json_file("sire_db.json", {})
# 2. 主要種牡馬カタログ（新機能）
sire_specs = load_json_file("sire_specs.json", {})

def decode_content(content):
    if not content: return ""
    for enc in ['euc-jp', 'cp51932', 'cp932', 'utf-8', 'shift_jis']:
        try: return content.decode(enc)
        except: continue
    return content.decode('utf-8', errors='replace')

def get_single_horse_ped(horse_id):
    """個別馬の血統ページから父と母父を正確に取得"""
    url = f"https://db.netkeiba.com/horse/ped/{horse_id}/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    html = ""
    # Scrapling優先（ボット検知回避）
    fetcher = get_shared_fetcher()
    if fetcher:
        try:
            resp = fetcher.get(url)
            html = resp.text if hasattr(resp, 'text') else ""
        except:
            pass

    # fallback: requests
    if not html:
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            html = decode_content(resp.content)
        except:
            pass

    if not html:
        return "不明", "不明"

    try:
        soup = BeautifulSoup(html, "html.parser")

        blood_tbl = soup.find("table", class_="blood_table")
        if not blood_tbl:
            return "不明", "不明"

        rows = blood_tbl.find_all("tr")
        if not rows:
            return "不明", "不明"

        # 父 (sire): テーブル最初の行の最初のtd > a
        sire = "不明"
        first_tds = rows[0].find_all("td")
        if first_tds:
            a_tag = first_tds[0].find("a")
            if a_tag:
                sire = a_tag.get_text(strip=True)

        # 母父 (broodmareSire): テーブル行数に応じて位置を推定
        # - 16行(葉ノードのみ): rows[8]の2番目td
        # - 32行(全祖先): rows[16]の2番目td
        bms = "不明"
        bms_row_idx = 8 if len(rows) <= 20 else 16
        if len(rows) > bms_row_idx:
            bms_tds = rows[bms_row_idx].find_all("td")
            if len(bms_tds) >= 2:
                a_tag = bms_tds[1].find("a")
                if a_tag:
                    bms = a_tag.get_text(strip=True)
            # フォールバック: 最初のtdがdam本体でなく母父の場合
            if bms == "不明" and bms_tds:
                a_tag = bms_tds[0].find("a")
                if a_tag and sire != a_tag.get_text(strip=True):
                    bms = a_tag.get_text(strip=True)

        return sire, bms
    except:
        pass
    return "不明", "不明"

def calculate_sire_bonus(name, race_track, race_dist):
    """
    静的カタログスペックに基づき、今日のレース条件に対するボーナス/デバフを論理計算する
    """
    if name not in sire_specs:
        return 0.0
    
    spec = sire_specs[name]
    score = 0.0
    
    # 1. 馬場（トラック）判定
    catalogue_track = spec.get("track", "不明")
    if catalogue_track == "万能":
        score += 5.0
    elif catalogue_track == race_track: # 芝 == 芝 or ダート == ダート
        score += 5.0
    else:
        # 不一致（芝専用馬がダートに出る、など）
        score -= 5.0
        
    # 2. 距離判定
    try:
        dist_min = spec.get("dist_min", 0)
        dist_max = spec.get("dist_max", 9999)
        d_val = int(race_dist)
        
        if dist_min <= d_val <= dist_max:
            score += 5.0
        else:
            # 距離適性外
            score -= 3.0
    except:
        pass
        
    return score

def get_bloodline_data(race_id: str, track_override: str = None, dist_override: int = None):
    is_nar = str(race_id)[4:6] > "10"
    domain = "nar.netkeiba.com" if is_nar else "race.netkeiba.com"
    # JRAはshutuba_past.htmlを使用（馬IDリンクが含まれる）
    page_name = "shutuba.html" if is_nar else "shutuba_past.html"
    url = f"https://{domain}/race/{page_name}?race_id={race_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    html = ""
    fetcher = get_shared_fetcher()
    if fetcher:
        try:
            resp = fetcher.get(url)
            html = resp.text if hasattr(resp, 'text') else ""
        except: pass

    if not html:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            html = decode_content(response.content)
        except: pass

    # JRAでshutuba_past.htmlが空なら通常shutuba.htmlにフォールバック
    if html and not is_nar:
        _tmp_soup = BeautifulSoup(html, "html.parser")
        if not _tmp_soup.find('tr', class_=re.compile(r'HorseList')):
            fb_url = f"https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
            try:
                resp2 = fetcher.get(fb_url) if fetcher else None
                html = resp2.text if (resp2 and hasattr(resp2, 'text')) else ""
            except: html = ""
            if not html:
                try:
                    response2 = requests.get(fb_url, headers=headers, timeout=15)
                    html = decode_content(response2.content)
                except: pass

    if not html:
        return {"race_id": race_id, "condition": "error_fetch", "data": [], "error": "HTML Fetch Failed"}

    try:
        soup = BeautifulSoup(html, "html.parser")
        
        # 1. レース条件（芝/ダート、距離）の自動取得
        # --- Override or Scrape ---
        track_type = track_override
        distance_val = dist_override
        
        if not track_type or not distance_val:
            race_data_div = soup.select_one(".RaceData01")
            scr_track = "不明"
            scr_dist = 0
            if race_data_div:
                match = re.search(r'(芝|ダ)(\d+)m', race_data_div.text)
                if match:
                    track_char = match.group(1)
                    scr_track = "芝" if track_char == "芝" else "ダート"
                    scr_dist = int(match.group(2))
            
            if not track_type: track_type = scr_track
            if not distance_val: distance_val = scr_dist

        condition_key = f"{track_type}_{distance_val}" if track_type != "不明" else "不明"
        
        # 2. 出馬表から各馬のID取得
        horse_list = []
        rows = soup.find_all('tr', class_=re.compile(r'HorseList|Entry|Horse_?List'))
        if not rows:
            # フォールバック: horse/ リンクを含む全tr
            rows = [tr for tr in soup.find_all('tr') if tr.find('a', href=re.compile(r'/horse/\d+'))]

        for row in rows:
            try:
                # 馬番取得: Umaban > Waku系 > 最初の数字td
                uma_tds = row.find_all('td', class_=re.compile(r'Umaban|umaban', re.I))
                if not uma_tds:
                    uma_tds = row.find_all('td', class_=re.compile(r'Waku', re.I))
                num_td = uma_tds[0] if uma_tds else None
                if not num_td:
                    continue
                m_num = re.search(r'(\d+)', num_td.get_text(strip=True))
                if not m_num: continue

                # 馬IDリンク取得
                name_a = row.find('a', href=re.compile(r'/horse/\d+'))
                if not name_a or 'href' not in name_a.attrs: continue

                h_url = name_a['href']
                m_id = re.search(r'horse/(\d+)', h_url)
                if not m_id: continue

                horse_list.append({"number": int(m_num.group(1)), "name": name_a.get_text(strip=True), "id": m_id.group(1)})
            except: continue

        if not horse_list:
            return {"race_id": race_id, "condition": condition_key, "data": [], "error": "No horses found"}

        # 3. 各馬の血統を並列取得 & 論理計算
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_horse = {executor.submit(get_single_horse_ped, h['id']): h for h in horse_list}
            
            for future in concurrent.futures.as_completed(future_to_horse):
                h = future_to_horse[future]
                try:
                    sire, bms = future.result()
                    
                    # カタログスペックに基づく計算
                    sire_score = calculate_sire_bonus(sire, track_type, distance_val)
                    bms_score = calculate_sire_bonus(bms, track_type, distance_val)
                    
                    # sire_db (既存の特定条件用DB) にエントリーがあれば上書き/加算も可能だが、
                    # 今回はユーザー様提案の「カタログ計算」をメインにする。
                    # 特定条件DBがあればそれを優先、なければカタログ計算とする。
                    db_sire_bonus = sire_db.get(sire, {}).get(condition_key, None)
                    db_bms_bonus = sire_db.get(bms, {}).get(condition_key, None)
                    
                    final_sire = db_sire_bonus if db_sire_bonus is not None else sire_score
                    final_bms = db_bms_bonus if db_bms_bonus is not None else bms_score
                    
                    total_bonus = round(final_sire + (final_bms * 0.5), 1)
                    
                    results.append({
                        "number": h['number'],
                        "name": h['name'],
                        "sire": sire,
                        "broodmareSire": bms,
                        "bonus": total_bonus
                    })
                except: continue

        results.sort(key=lambda x: x['number'])
        return {"race_id": race_id, "condition": condition_key, "data": results}

    except Exception as e:
        return {"race_id": race_id, "condition": "error", "data": [], "error": str(e)}

if HAS_FASTAPI and app:
    @app.get("/api/bloodline/{race_id}")
    def get_bloodline_api(race_id: str, track_override: str = None, dist_override: int = None):
        return get_bloodline_data(race_id, track_override, dist_override)

if __name__ == "__main__":
    if HAS_FASTAPI:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=8000)
    else:
        print("FastAPI is not installed. API server cannot be started, but functions are available for import.")
