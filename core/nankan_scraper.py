# -*- coding: utf-8 -*-
"""南関東(大井・川崎・船橋・浦和) nankankeiba.com スクレイパー。

netkeiba NAR版にない過去走詳細(上がり3F/通過順)を補完し、
末脚指数やハンター用シグナルを計算する。

Site: https://www.nankankeiba.com
Encoding: Shift_JIS
"""
import re
import time
import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://www.nankankeiba.com"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 15
_MIN_INTERVAL = 0.4  # IPブロック回避のための最小リクエスト間隔(秒)

# nankankeiba 競馬場コード(ASSIGN_JO) → netkeiba場コード
NANKAN_VENUES = {
    "浦和": "42", "船橋": "43", "大井": "44", "川崎": "45",
}

# netkeiba地方場コード → nankankeiba内部場コード(16桁race_id/14桁program_idの[8:10])
# 実査で確定(2026-07 calendar): 18浦和/19船橋/20大井/21川崎
NETKEIBA_TO_NANKAN_VENUE = {
    "42": "18", "43": "19", "44": "20", "45": "21",
}

_last_request_ts = [0.0]

# 月別開催カレンダー(program_id)キャッシュ: {'YYYYMM': {(date8, venue2): program14}}
_month_program_cache = {}


def _throttle():
    """連続リクエストの間隔を_MIN_INTERVAL秒以上空ける(サイト負荷/IPブロック対策)。"""
    elapsed = time.monotonic() - _last_request_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_ts[0] = time.monotonic()


def _fetch(url):
    """Shift_JISページを取得しBeautifulSoupを返す。"""
    _throttle()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return BeautifulSoup(resp.content.decode("shift_jis", errors="replace"), "lxml")
    except Exception as e:
        logger.warning(f"[nankan] fetch failed: {url} → {e}")
        return None


def _fetch_text(url):
    """Shift_JISページを取得しデコード済みHTML文字列を返す(正規表現パース用)。"""
    _throttle()
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.content.decode("shift_jis", errors="replace")
    except Exception as e:
        logger.warning(f"[nankan] fetch failed: {url} → {e}")
        return None


# ──────────────────────── 開催カレンダー / race_id自動導出 ────────────────────────

def fetch_month_programs(yyyymm):
    """月別開催カレンダーから、その月の全開催のprogram_id(14桁)を取得。

    program_id構造: date(8) + venue(2) + kaiji(2) + day(2)
    戻り値: dict {(date8:str, venue2:str): program14:str}
    (例: {('20260701','20'): '20260701200503', ...})
    月単位でキャッシュするため、同一開催日の複数レース分析でも取得は1回のみ。
    """
    yyyymm = str(yyyymm)
    if yyyymm in _month_program_cache:
        return _month_program_cache[yyyymm]

    result = {}
    html = _fetch_text(f"{_BASE}/calendar/{yyyymm}.do")
    if html:
        for pid in re.findall(r"/program/(\d{14})\.do", html):
            if pid == "00000000000000":
                continue  # フォームのプレースホルダ
            date8, venue2 = pid[:8], pid[8:10]
            result[(date8, venue2)] = pid
    _month_program_cache[yyyymm] = result
    return result


def derive_nankan_race_id(netkeiba_race_id, date_yyyymmdd):
    """netkeiba地方レースID + 開催日付 から、nankankeiba 16桁race_idを自動導出。

    これにより「🐴nankankeiba.com レースID」の手入力なしに過去走補完が可能になる。
    netkeiba_race_id: 12桁(YYYY + jyo2 + kaiji2 + day2 + race2)。例 '202644070112'
    date_yyyymmdd: 実開催日(scraperのdate_valから)。例 '20260701'
    戻り値: nankan 16桁race_id(str) or None

    導出: nankankeibaのkaiji/dayはnetkeibaと異なるため、開催カレンダーから
    date+venueに一致するprogram_id(=date+venue+kaiji+day)を引き、race番号を付す。
    """
    s = re.sub(r"\D", "", str(netkeiba_race_id or ""))
    if len(s) < 12:
        return None
    jyo = s[4:6]
    race_num = s[10:12]
    venue = NETKEIBA_TO_NANKAN_VENUE.get(jyo)
    if not venue:
        return None

    date8 = re.sub(r"\D", "", str(date_yyyymmdd or ""))[:8]
    if len(date8) != 8:
        return None

    programs = fetch_month_programs(date8[:6])
    program_id = programs.get((date8, venue))
    if not program_id:
        return None
    return f"{program_id}{race_num}"


def fetch_program_races(program_id):
    """開催プログラム(1日1場)ページから、その日の全レースの16桁race_idを取得。

    program_id: 14桁(date8+venue2+kaiji2+day2)。fetch_month_programsの値。
    戻り値: list[str] (16桁race_id、レース番号昇順)
    """
    html = _fetch_text(f"{_BASE}/program/{str(program_id)}.do")
    if not html:
        return []
    ids = sorted(set(re.findall(r"/syousai/(\d{16})\.do", html)))
    return ids


def _safe_float(v, default=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    try:
        return int(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return default


# ──────────────────────────── レース結果ページ ────────────────────────────

def fetch_result(nankan_race_id):
    """レース結果を取得。戻り値: list[dict] (着順ソート)。

    nankan_race_id: nankankeiba固有の16桁ID (例: '2026060820040101')
    各dict: rank, waku, umaban, name, sex_age, weight_carried, body_weight,
            weight_change, jockey, trainer, time, margin, agari3f, passing,
            popularity, horse_id
    """
    url = f"{_BASE}/result/{nankan_race_id}.do"
    soup = _fetch(url)
    if not soup:
        return []

    # Table 0: 着順テーブル (class='nk23_c-table01__table')
    tables = soup.find_all("table")
    if not tables:
        return []

    result_table = tables[0]
    rows = result_table.find_all("tr")
    if len(rows) < 2:
        return []

    results = []
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 15:
            continue

        horse_id = None
        uma_link = row.find("a", href=re.compile(r"/uma_info/\d+\.do"))
        if uma_link:
            m = re.search(r"/uma_info/(\d+)\.do", uma_link["href"])
            if m:
                horse_id = m.group(1)

        results.append({
            "rank": _safe_int(cells[0].get_text(strip=True)),
            "waku": _safe_int(cells[1].get_text(strip=True)),
            "umaban": _safe_int(cells[2].get_text(strip=True)),
            "name": cells[3].get_text(strip=True),
            "sex_age": cells[4].get_text(strip=True),
            "weight_carried": _safe_float(cells[5].get_text(strip=True)),
            "body_weight": cells[6].get_text(strip=True).replace("kg", ""),
            "weight_change": cells[7].get_text(strip=True),
            "jockey": cells[8].get_text(strip=True),
            "trainer": cells[9].get_text(strip=True),
            "time": cells[10].get_text(strip=True),
            "margin": cells[11].get_text(strip=True),
            "agari3f": _safe_float(cells[12].get_text(strip=True)),
            "passing": cells[13].get_text(strip=True),
            "popularity": _safe_int(cells[14].get_text(strip=True)),
            "horse_id": horse_id,
        })

    return results


# ──────────────────────────── 出馬表ページ ────────────────────────────

def fetch_entries(nankan_race_id):
    """出馬表からhorse_idリストを取得。戻り値: list[dict]。

    各dict: waku, umaban, name, horse_id, sex_age, jockey, trainer,
            sire, dam, weight_carried
    """
    url = f"{_BASE}/syousai/{nankan_race_id}.do"
    soup = _fetch(url)
    if not soup:
        return []

    # Table 1: 出馬表 (class='nk23_c-table23__table', rows > 1)
    # 注意: 同枠2頭ペアの2頭目は枠番セルがrowspanで省略され、
    # 1セル少ない行(11セル)になる。その場合は前行の枠番を引き継ぎ、
    # 以降の列インデックスを-1オフセットして揃える。
    entries = []
    for table in soup.find_all("table", class_="nk23_c-table23__table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        last_waku = 0
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) < 9:
                continue

            if len(cells) >= 12:
                offset = 0
                waku = _safe_int(cells[0].get_text(strip=True))
                last_waku = waku
            else:
                # 枠番セル省略行: 前行(同枠1頭目)の枠番を引き継ぐ
                offset = -1
                waku = last_waku

            def _cell(idx):
                real_idx = idx + offset
                return cells[real_idx].get_text(strip=True) if 0 <= real_idx < len(cells) else ""

            horse_id = None
            uma_link = row.find("a", href=re.compile(r"/uma_info/\d+\.do"))
            if uma_link:
                m = re.search(r"/uma_info/(\d+)\.do", uma_link["href"])
                if m:
                    horse_id = m.group(1)

            # 馬名セルから馬名と生年月日を分離(末尾に"(中同名)"等の注記が付く場合あり)
            name_cell = _cell(2)
            name_match = re.match(r"(.+?)\d{2}\.\d{1,2}\.\d{1,2}(?:\([^)]*\))?$", name_cell)
            name = name_match.group(1) if name_match else name_cell

            # 父馬名母馬名セル(sire+damの連結文字列。厳密な分離は不可のため参考値)
            blood_cell = _cell(8)
            sire, dam = "", ""
            if blood_cell:
                parts = re.split(r"(?<=[ァ-ヶー])\s*(?=[ァ-ヶー])", blood_cell, maxsplit=1)
                if len(parts) == 2:
                    sire, dam = parts
                else:
                    sire = blood_cell

            entries.append({
                "waku": waku,
                "umaban": _safe_int(_cell(1)),
                "name": name,
                "horse_id": horse_id,
                "sex_age": _cell(3),
                "weight_carried": _safe_float(_cell(6)),
                "jockey": _cell(7),
                "sire": sire,
                "dam": dam,
                "trainer": _cell(9),
            })

    return entries


# ──────────────────────────── 馬情報ページ(過去走) ────────────────────────────

def fetch_horse_history(horse_id):
    """馬の過去走成績(最大24走)を取得。

    horse_id: nankankeiba固有のID (例: '2022106480')
    戻り値: dict {
        'name': str, 'sire': str, 'dam': str, 'dam_sire': str,
        'trainer': str, 'birthdate': str,
        'runs': list[dict]  # 新しい順
    }
    各run: date, venue, race_num, race_name, distance, condition, weather,
           umaban, popularity, rank, n_horses, time, margin, agari3f,
           passing, body_weight, jockey, weight_carried, trainer, prize
    """
    url = f"{_BASE}/uma_info/{horse_id}.do"
    soup = _fetch(url)
    if not soup:
        return None

    tables = soup.find_all("table")
    if len(tables) < 8:
        return None

    # ── 血統(Table 0) ──
    info = {"name": "", "sire": "", "dam": "", "dam_sire": "",
            "trainer": "", "birthdate": ""}
    t0 = tables[0]
    for row in t0.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 3:
            label = cells[0].get_text(strip=True)
            value = cells[2].get_text(strip=True)
            if "父" == label:
                info["sire"] = value
            elif "母" == label:
                info["dam"] = value
            elif "母父" in label:
                info["dam_sire"] = value

    # ── 基本情報(Table 2, id='horse-info') ──
    for t in tables:
        if t.get("id") == "horse-info":
            for row in t.find_all("tr"):
                cells = row.find_all("td")
                for i, c in enumerate(cells):
                    txt = c.get_text(strip=True)
                    if "生年月日" in txt and i + 1 < len(cells):
                        info["birthdate"] = cells[i + 1].get_text(strip=True)
                    if "調教師" in txt and i + 1 < len(cells):
                        info["trainer"] = cells[i + 1].get_text(strip=True)
            break

    # ── 馬名(Table 0の最初のリンクか、ページタイトルから) ──
    title = soup.find("title")
    if title:
        m = re.search(r"(.+?)[\s　]", title.get_text())
        if m:
            info["name"] = m.group(1)

    # ── 過去走(Table 7: class含む 'stripe-two-lines' のテーブル) ──
    runs = []
    # Table 7 が過去走の詳細テーブル(18カラム)
    # ヘッダ: 年月日/場名/R/レース名/距離/天候馬場/馬番/人気/着/頭数/タイム/差/上3F/通過/体重/騎手/斤量/調教師/賞金
    past_table = None
    for t in tables:
        cls = " ".join(t.get("class", []))
        if "stripe" in cls:
            rows = t.find_all("tr")
            # 18カラム以上のヘッダを持つテーブルを探す
            if rows:
                header_cells = rows[0].find_all(["th", "td"])
                if len(header_cells) >= 16:
                    past_table = t
                    break

    if not past_table:
        info["runs"] = runs
        return info

    past_rows = past_table.find_all("tr")
    for row in past_rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 16:
            continue

        date_str = cells[0].get_text(strip=True)
        venue = cells[1].get_text(strip=True)
        race_num = cells[2].get_text(strip=True)
        race_name = cells[3].get_text(strip=True)
        distance_str = cells[4].get_text(strip=True)
        cond_str = cells[5].get_text(strip=True)
        umaban_str = cells[6].get_text(strip=True)
        pop_str = cells[7].get_text(strip=True)

        # 着/頭数 パース (例: "7着/11頭")
        rank_head = cells[8].get_text(strip=True)
        rank, n_horses = 0, 0
        rm = re.match(r"(\d+)着?/(\d+)頭?", rank_head)
        if rm:
            rank = int(rm.group(1))
            n_horses = int(rm.group(2))
        else:
            rank = _safe_int(re.sub(r"[^\d]", "", rank_head.split("/")[0]))

        time_str = cells[9].get_text(strip=True)
        margin = cells[10].get_text(strip=True)
        agari3f = _safe_float(cells[11].get_text(strip=True))
        passing = cells[12].get_text(strip=True)
        body_weight = _safe_int(re.sub(r"[^\d]", "", cells[13].get_text(strip=True)))
        jockey = cells[14].get_text(strip=True)
        weight_carried = _safe_float(cells[15].get_text(strip=True))
        trainer = cells[16].get_text(strip=True) if len(cells) > 16 else ""
        prize = cells[17].get_text(strip=True) if len(cells) > 17 else ""

        # 天候/馬場分離 (例: "曇/不良")
        weather, baba = "", ""
        cp = cond_str.split("/")
        if len(cp) == 2:
            weather, baba = cp[0].strip(), cp[1].strip()
        else:
            baba = cond_str

        # 距離 数値化
        dist = _safe_int(re.sub(r"[^\d]", "", distance_str))

        # 日付正規化 (26/06/08 → 2026/06/08)
        dm = re.match(r"(\d{2,4})/(\d{1,2})/(\d{1,2})", date_str)
        if dm:
            y = dm.group(1)
            if len(y) == 2:
                y = "20" + y
            date_str = f"{y}/{dm.group(2).zfill(2)}/{dm.group(3).zfill(2)}"

        runs.append({
            "date": date_str,
            "venue": venue,
            "race_num": race_num.replace("R", ""),
            "race_name": race_name,
            "distance": dist,
            "weather": weather,
            "baba": baba,
            "umaban": _safe_int(re.sub(r"[^\d]", "", umaban_str)),
            "popularity": _safe_int(re.sub(r"[^\d]", "", pop_str)),
            "rank": rank,
            "n_horses": n_horses,
            "time": time_str,
            "margin": margin,
            "agari3f": agari3f,
            "passing": passing,
            "body_weight": body_weight,
            "jockey": jockey,
            "weight_carried": weight_carried,
            "trainer": trainer,
            "prize": prize,
        })

    info["runs"] = runs
    return info


# ──────────────────────────── 末脚指数計算 ────────────────────────────

def compute_spurt_index(runs, min_runs=2):
    """過去走の上がり3Fから末脚指数(偏差値的スコア)を計算。

    JRA-VAN版(jockey_jv.horse_recent_context)と同等のロジック:
    直近の有効な走り(上がり3F > 0)からフィールド内での相対位置を推定。

    戻り値: (spurt_index: float or None, n_runs: int)
    """
    valid_agaris = [r["agari3f"] for r in runs if r.get("agari3f") and r["agari3f"] > 0]
    if len(valid_agaris) < min_runs:
        return None, len(valid_agaris)

    # 簡易的な偏差値計算: 上がり3Fが速いほど高スコア
    # nankankeiba.comにはレース全体のagariがないため、
    # 馬の直近5走のagariの相対的な良さを使う
    recent = valid_agaris[:5]
    avg = sum(recent) / len(recent)
    # 南関東ダートの平均的な上がり3F ≈ 39-40秒
    # 偏差: (平均 - 実際) / 平均 の正規化
    # 高い = 上がりが速い = 末脚がある
    baseline = 39.5
    index = (baseline - avg) / baseline + 0.5

    # 最速上がりのボーナス
    best = min(recent)
    if best <= 37.5:
        index += 0.15
    elif best <= 38.0:
        index += 0.10
    elif best <= 38.5:
        index += 0.05

    return round(max(0.0, min(1.5, index)), 2), len(valid_agaris)


# ──────────────────────────── PastRuns形式ブリッジ ────────────────────────────

def _grade_from_race_name(race_name):
    rn = str(race_name or "")
    if 'JpnI' in rn or 'GI' in rn or 'Ｇ I' in rn:
        return 'G1'
    if 'JpnII' in rn or 'GII' in rn:
        return 'G2'
    if 'JpnIII' in rn or 'GIII' in rn:
        return 'G3'
    if 'OP' in rn or '(L)' in rn or 'Ｌ' in rn:
        return 'OP'
    if '新馬' in rn:
        return '新馬'
    if '未勝利' in rn:
        return '未勝利'
    return 'OP'


def runs_to_pastruns(runs):
    """nankankeiba過去走(fetch_horse_historyの'runs')を、
    core/scraper.pyのget_race_data()が生成する'PastRuns'と同じdictスキーマに変換する。

    これにより既存のPCI/脚質分類/展開マップ(race_analysis_tools.get_pci_summary,
    calculator.analyze_pace_profile等)をJRA/NAR問わずそのまま流用できる。

    戻り値: list[dict] (新しい順、PastRuns互換)
    """
    pastruns = []
    for r in (runs or []):
        time_str = str(r.get("time", "") or "")
        t_sec = 0.0
        if ':' in time_str:
            parts = time_str.split(':')
            try:
                t_sec = float(parts[0]) * 60 + float(parts[1])
            except (ValueError, IndexError):
                t_sec = 0.0
        else:
            try:
                t_sec = float(time_str)
            except ValueError:
                t_sec = 0.0

        rank = r.get("rank", 99) or 99
        if rank == 1:
            margin_val = 0.0
        else:
            margin_val = _safe_float(str(r.get("margin", "")).replace("大差", "10"), default=9.9)

        agari = r.get("agari3f", 0.0) or 0.0
        date_str = str(r.get("date", "") or "").replace("/", ".")

        pastruns.append({
            'Rank': rank,
            'Time': t_sec,
            'Distance': r.get("distance", 0) or 0,
            'Surface': 'ダ',
            'Agari': agari,
            'AgariType': 'Real' if agari > 0 else 'Imputed',
            'Passing': r.get("passing", "-") or "-",
            'PassingType': 'Real',
            'Grade': _grade_from_race_name(r.get("race_name", "")),
            'Date': date_str or '2000.01.01',
            'Condition': r.get("baba", "良") or "良",
            'Popularity': r.get("popularity", 99) or 99,
            'TimeIndexRank': 99,
            'Weight': r.get("weight_carried", 55.0) or 55.0,
            'Margin': margin_val,
            'RaceAgari': agari,
        })
    return pastruns


# ──────────────────────────── 馬名→horse_id マッチング ────────────────────────────

def match_horses_by_name(netkeiba_names, nankan_entries):
    """netkeiba馬名リストとnankankeiba出馬表をマッチング。

    netkeiba_names: list[str] - netkeiba側の馬名
    nankan_entries: list[dict] - fetch_entries()の結果
    戻り値: dict {netkeiba_name: horse_id or None}
    """
    result = {}
    # nankanの馬名を正規化(全角英数→半角、スペース除去)
    nk_map = {}
    for entry in nankan_entries:
        norm = _normalize_name(entry["name"])
        nk_map[norm] = entry["horse_id"]

    for name in netkeiba_names:
        norm = _normalize_name(name)
        horse_id = nk_map.get(norm)
        if not horse_id:
            # 部分一致フォールバック
            for nk_norm, hid in nk_map.items():
                if norm in nk_norm or nk_norm in norm:
                    horse_id = hid
                    break
        result[name] = horse_id

    return result


def _normalize_name(name):
    """馬名を正規化。NFKC(全角英数→半角/半角カナ→全角カナ)＋空白/中黒/括弧注記除去。

    netkeiba と nankankeiba で表記(全半角・中黒・"(地)"等の注記)が揺れても
    照合できるようにする。カタカナ本体は保持。
    """
    import unicodedata
    s = unicodedata.normalize("NFKC", str(name or ""))
    s = re.sub(r"[（(][^）)]*[）)]", "", s)   # (中同名)/(地) 等の注記を除去
    s = re.sub(r"[\s　・･]+", "", s)            # 空白・中黒
    return s.strip()


# ──────────────────────────── 統合関数: netkeiba補完 ────────────────────────────

def enrich_with_nankan(netkeiba_df, nankan_race_id=None, nankan_entries=None):
    """netkeibaのDataFrameにnankankeiba.comの過去走データを補完。

    netkeiba_df: scraper.get_race_data()の結果
    nankan_race_id: nankankeiba固有のレースID(出馬表/結果ページ用)
    nankan_entries: 事前取得済みのfetch_entries()結果(任意)

    戻り値: dict {馬名: {horse_id, spurt_index, spurt_runs, history, ...}}
    """
    if nankan_entries is None and nankan_race_id:
        nankan_entries = fetch_entries(nankan_race_id)

    if not nankan_entries:
        return {}

    names = [str(r.get("Name", "")) for _, r in netkeiba_df.iterrows()]
    name_to_id = match_horses_by_name(names, nankan_entries)

    enriched = {}
    for name, horse_id in name_to_id.items():
        if not horse_id:
            continue

        history = fetch_horse_history(horse_id)
        if not history or not history.get("runs"):
            enriched[name] = {"horse_id": horse_id, "spurt_index": None,
                              "spurt_runs": 0, "history": None}
            continue

        si, sr = compute_spurt_index(history["runs"])
        enriched[name] = {
            "horse_id": horse_id,
            "spurt_index": si,
            "spurt_runs": sr,
            "sire": history.get("sire", ""),
            "dam_sire": history.get("dam_sire", ""),
            "trainer": history.get("trainer", ""),
            "runs": history["runs"],
            "pastruns": runs_to_pastruns(history["runs"]),
            "prev_agari": history["runs"][0].get("agari3f") if history["runs"] else None,
            "prev_rank": history["runs"][0].get("rank") if history["runs"] else None,
            "prev_pop": history["runs"][0].get("popularity") if history["runs"] else None,
            "prev_passing": history["runs"][0].get("passing") if history["runs"] else None,
            "prev_distance": history["runs"][0].get("distance") if history["runs"] else None,
            "prev_baba": history["runs"][0].get("baba") if history["runs"] else None,
            "prev_body_weight": history["runs"][0].get("body_weight") if history["runs"] else None,
        }

    return enriched
