# -*- coding: utf-8 -*-
"""地方競馬(NAR)全場スクレイパー — keiba.go.jp (地方競馬情報サイト)。

NAR公式ポータルから出走表(過去走5走付き)・レース結果・払戻を取得する。
全地方場に対応(南関4場 + 門別/盛岡/水沢/金沢/名古屋/笠松/園田/姫路/高知/佐賀)。

Site: https://www.keiba.go.jp
Encoding: UTF-8 (一部Shift_JISページあり)

安全設計:
  - リクエスト間隔 2秒以上(サイト負荷/IPブロック対策)
  - 1セッション最大100リクエスト(安全弁)
  - User-Agent明示
  - エラー時は空を返し後続を止めない
"""
import os
import re
import json
import time
import logging
import urllib.parse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE = "https://www.keiba.go.jp"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = 20
_MIN_INTERVAL = 2.0
_MAX_REQUESTS_PER_SESSION = 100

# keiba.go.jp の k_babaCode → 場名
# 全場を網羅(開催週によってTodayRaceInfoTopに出るコードが変わるため固定定義)
BABA_CODE = {
    "3":  "帯広ば",
    "10": "盛岡",
    "11": "水沢",
    "18": "浦和",
    "19": "船橋",
    "20": "大井",
    "21": "川崎",
    "22": "金沢",
    "23": "笠松",
    "24": "名古屋",
    "25": "中津",
    "27": "園田",
    "28": "姫路",
    "31": "高知",
    "32": "佐賀",
    "36": "門別",
}

# keiba.go.jp k_babaCode → netkeiba/jravan場コード(既存パイプラインとの接続用)
BABA_TO_NETKEIBA = {
    "18": "42",  # 浦和
    "19": "43",  # 船橋
    "20": "44",  # 大井
    "21": "45",  # 川崎
    "36": "30",  # 門別
    "10": "35",  # 盛岡
    "11": "36",  # 水沢
    "22": "46",  # 金沢
    "23": "47",  # 笠松
    "24": "48",  # 名古屋
    "27": "50",  # 園田
    "28": "51",  # 姫路
    "31": "54",  # 高知
    "32": "55",  # 佐賀
}

_request_count = [0]
_last_request_ts = [0.0]


def _throttle():
    """リクエスト間隔を_MIN_INTERVAL秒以上空ける。"""
    elapsed = time.monotonic() - _last_request_ts[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_ts[0] = time.monotonic()


def _fetch(url):
    """HTMLを取得しBeautifulSoupを返す。安全弁(最大リクエスト数)付き。"""
    import requests
    if _request_count[0] >= _MAX_REQUESTS_PER_SESSION:
        logger.warning("[nar] session request limit reached (%d)", _MAX_REQUESTS_PER_SESSION)
        return None
    _throttle()
    _request_count[0] += 1
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        logger.warning("[nar] fetch failed: %s → %s", url, e)
        return None


def reset_session():
    """リクエストカウンターをリセット(新しいセッション開始時に呼ぶ)。"""
    _request_count[0] = 0


# ──────────────────────────────────────────────
# NAR騎手統計(SPAIA + Rakuten)
# ──────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
_JOCKEY_CACHE_PATH = os.path.join(_DATA_DIR, 'nar_jockey_cache.json')
_JOCKEY_CACHE = {}
_JOCKEY_CACHE_MAX_AGE = 7 * 86400  # 1週間


def _fetch_external(url):
    """外部サイト用fetch(keiba.go.jpのリクエスト制限とは独立)。"""
    import requests
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        logger.warning("[nar-jockey] fetch failed: %s → %s", url, e)
        return None


def fetch_nar_jockey_stats(force=False):
    """NAR騎手リーディングデータを取得しキャッシュする。

    ソース(合計2リクエスト・間に2秒wait):
      - Rakuten: 勝率/連対率/3着内率/出走数/所属(全国top100) × 1リクエスト
      - SPAIA: 回収率スコア/複勝率(全国top25) × 1リクエスト

    キャッシュ: data/nar_jockey_cache.json (1週間有効)
    戻り値: {騎手名: {win_rate, place_rate, show_rate, starts,
                      home_venue, recovery_score}, ...}
    """
    global _JOCKEY_CACHE

    # キャッシュ読み込み
    if not force and os.path.exists(_JOCKEY_CACHE_PATH):
        try:
            with open(_JOCKEY_CACHE_PATH, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            ts = cached.get('_timestamp', 0)
            if time.time() - ts < _JOCKEY_CACHE_MAX_AGE:
                _JOCKEY_CACHE = cached.get('jockeys', {})
                logger.info("[nar-jockey] cache hit: %d jockeys", len(_JOCKEY_CACHE))
                return _JOCKEY_CACHE
        except Exception:
            pass

    jockeys = {}

    # ── Rakuten: 勝率/連対率/3着内率/出走/所属 ──
    logger.info("[nar-jockey] fetching Rakuten leading ...")
    rk_url = "https://keiba.rakuten.co.jp/analyze/leading/RACEID/202607290000000000"
    soup = _fetch_external(rk_url)
    if soup:
        tables = soup.find_all('table')
        for tbl in tables:
            rows = tbl.find_all('tr')
            for row in rows:
                tds = row.find_all('td')
                if len(tds) < 9:
                    continue
                name_cell = tds[1].get_text().strip() if len(tds) > 1 else ''
                m_name = re.match(r'(.+?)[（(](.+?)[）)]', name_cell)
                if not m_name:
                    continue
                name = m_name.group(1).strip().replace('　', '').replace(' ', '')
                venue = m_name.group(2).strip()
                try:
                    starts = int(tds[6].get_text().strip().replace(',', ''))
                    win_r = float(tds[7].get_text().strip().replace('%', ''))
                    place_r = float(tds[8].get_text().strip().replace('%', ''))
                    show_r = float(tds[9].get_text().strip().replace('%', '')) if len(tds) > 9 else 0
                except (ValueError, IndexError):
                    continue
                jockeys[name] = {
                    'home_venue': venue,
                    'starts': starts,
                    'win_rate': win_r,
                    'place_rate': place_r,
                    'show_rate': show_r,
                    'source': 'rakuten',
                }
        logger.info("[nar-jockey] Rakuten: %d jockeys", len(jockeys))

    # ── SPAIA: 複勝率/回収率スコア ──
    time.sleep(2)
    logger.info("[nar-jockey] fetching SPAIA leading ...")
    spaia_url = "https://spaia-keiba.com/nar/leading/jockey"
    soup2 = _fetch_external(spaia_url)
    if soup2:
        tables = soup2.find_all('table')
        for tbl in tables:
            rows = tbl.find_all('tr')
            for row in rows:
                tds = row.find_all('td')
                if len(tds) < 8:
                    continue
                name_el = tds[1] if len(tds) > 1 else None
                if not name_el:
                    continue
                a = name_el.find('a')
                name_raw = (a.get_text() if a else name_el.get_text()).strip()
                name_norm = name_raw.replace('　', '').replace(' ', '')
                if not name_norm:
                    continue
                try:
                    show_rate_sp = float(tds[8].get_text().strip().replace('.', '', 1)
                                         .replace(',', '')) if len(tds) > 8 else 0
                    # SPAIA: .250 format → 25.0%
                    wr_raw = tds[6].get_text().strip()
                    sr_raw = tds[8].get_text().strip()
                    score_raw = tds[10].get_text().strip() if len(tds) > 10 else ''
                    wr = float(wr_raw.lstrip('.') or 0) if wr_raw.startswith('.') else float(wr_raw or 0)
                    sr = float(sr_raw.lstrip('.') or 0) if sr_raw.startswith('.') else float(sr_raw or 0)
                    recovery = float(score_raw) if score_raw else 0
                except (ValueError, IndexError):
                    continue

                if name_norm in jockeys:
                    jockeys[name_norm]['recovery_score'] = recovery
                    if sr > 0 and jockeys[name_norm].get('show_rate', 0) == 0:
                        jockeys[name_norm]['show_rate'] = sr * 100
                else:
                    jockeys[name_norm] = {
                        'win_rate': wr * 100 if wr < 1 else wr,
                        'show_rate': sr * 100 if sr < 1 else sr,
                        'recovery_score': recovery,
                        'source': 'spaia',
                    }
        logger.info("[nar-jockey] SPAIA: total %d jockeys", len(jockeys))

    # キャッシュ保存
    if jockeys:
        _JOCKEY_CACHE = jockeys
        os.makedirs(_DATA_DIR, exist_ok=True)
        try:
            with open(_JOCKEY_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump({'_timestamp': time.time(), 'jockeys': jockeys},
                          f, ensure_ascii=False, indent=1)
            logger.info("[nar-jockey] saved %d jockeys to cache", len(jockeys))
        except Exception as e:
            logger.warning("[nar-jockey] cache save failed: %s", e)

    return jockeys


def _load_jockey_cache():
    """キャッシュ済みの騎手統計を読み込む(ネットワーク不要)。"""
    global _JOCKEY_CACHE
    if _JOCKEY_CACHE:
        return _JOCKEY_CACHE
    if os.path.exists(_JOCKEY_CACHE_PATH):
        try:
            with open(_JOCKEY_CACHE_PATH, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            _JOCKEY_CACHE = cached.get('jockeys', {})
            return _JOCKEY_CACHE
        except Exception:
            pass
    return {}


def jockey_factor(name, venue=None):
    """騎手名から騎手力ファクター(0.7〜1.3)を返す。

    キャッシュ済みのリーディングデータから勝率/3着内率で補正。
    ホーム場一致で+0.05ボーナス。
    """
    cache = _load_jockey_cache()
    name_norm = _strip_affiliation(name)
    j = cache.get(name_norm)
    if not j:
        return 1.0

    wr = j.get('win_rate', 0)
    sr = j.get('show_rate', 0)
    factor = 1.0

    # 勝率ベースの補正
    if wr >= 25:
        factor += 0.20
    elif wr >= 20:
        factor += 0.15
    elif wr >= 15:
        factor += 0.08
    elif wr >= 10:
        factor += 0.03
    elif wr < 5:
        factor -= 0.15
    elif wr < 8:
        factor -= 0.08

    # 3着内率の補正
    if sr >= 50:
        factor += 0.05
    elif sr < 25:
        factor -= 0.05

    # ホーム場ボーナス
    if venue:
        home = (j.get('home_venue') or '').replace('　', '').replace(' ', '')
        v_norm = venue.replace('　', '').replace(' ', '')
        if home == v_norm:
            factor += 0.05

    return max(0.7, min(1.3, round(factor, 2)))


def jockey_info(name):
    """騎手の統計情報を返す(表示用)。"""
    cache = _load_jockey_cache()
    name_norm = _strip_affiliation(name)
    return cache.get(name_norm)


# ──────────────────────────────────────────────
# 当日開催場一覧
# ──────────────────────────────────────────────

def fetch_today_venues(date_str=None):
    """当日(または指定日)の開催場一覧を取得する。

    date_str: 'YYYY/MM/DD' 形式。Noneなら今日。
    戻り値: [{'baba_code': str, 'venue': str, 'date': str, 'n_races': int}, ...]
    """
    if date_str is None:
        import datetime
        date_str = datetime.date.today().strftime('%Y/%m/%d')
    url = f"{_BASE}/KeibaWeb/TodayRaceInfo/TodayRaceInfoTop"
    soup = _fetch(url)
    if not soup:
        return []

    venues = []
    seen = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'RaceList' not in href or 'k_babaCode' not in href:
            continue
        m_code = re.search(r'k_babaCode=(\d+)', href)
        m_date = re.search(r'k_raceDate=([\d%A-Fa-f/]+)', href)
        if not m_code:
            continue
        code = m_code.group(1)
        link_date = urllib.parse.unquote(m_date.group(1)) if m_date else ''
        if date_str and link_date and not link_date.startswith(date_str):
            continue
        if code in seen:
            continue
        seen.add(code)
        venue_name = BABA_CODE.get(code, f"不明({code})")
        venues.append({
            'baba_code': code,
            'venue': venue_name,
            'date': link_date or date_str,
        })
    return venues


# ──────────────────────────────────────────────
# レース一覧(1開催場の全R)
# ──────────────────────────────────────────────

def fetch_race_list(date_str, baba_code):
    """指定日・指定場の全レース一覧を取得。

    戻り値: [{'race_no': int, 'post_time': str, 'race_name': str,
              'distance': str, 'surface': str, 'n_horses': int,
              'course_detail': str, 'condition': str}, ...]
    """
    encoded_date = urllib.parse.quote(date_str, safe='')
    url = (f"{_BASE}/KeibaWeb/TodayRaceInfo/RaceList"
           f"?k_raceDate={encoded_date}&k_babaCode={baba_code}")
    soup = _fetch(url)
    if not soup:
        return []

    races = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'DebaTable' not in href:
            continue
        m_rno = re.search(r'k_raceNo=(\d+)', href)
        if not m_rno:
            continue
        rno = int(m_rno.group(1))
        if any(r['race_no'] == rno for r in races):
            continue

        text = a.get_text(strip=True)
        races.append({
            'race_no': rno,
            'race_name': text or f"{rno}R",
            'baba_code': baba_code,
            'date': date_str,
        })

    races.sort(key=lambda r: r['race_no'])
    return races


# ──────────────────────────────────────────────
# 出走表パーサー(1レース)
# ──────────────────────────────────────────────

def _parse_record(row_text):
    """成績文字列 '0-0-1-5' → dict。"""
    m = re.search(r'(\d+)-(\d+)-(\d+)-(\d+)', row_text)
    if not m:
        return None
    return {'win': int(m.group(1)), 'second': int(m.group(2)),
            'third': int(m.group(3)), 'lose': int(m.group(4))}


def _clean(s):
    """全角空白/改行/タブを除去してstrip。"""
    if not s:
        return ''
    return re.sub(r'[\s　]+', ' ', str(s)).strip()


def fetch_entry_table(date_str, baba_code, race_no):
    """出走表(出馬表)を取得・パースする。

    戻り値: {'race_info': {...}, 'horses': [...]} or None
    race_info: レース名/場/距離/馬場/発走時刻/天候/条件
    horses[i]: 馬番/枠番/馬名/性齢/斤量/騎手/調教師/馬体重/増減/
               単勝オッズ/人気/全成績/当場成績/当距離成績/past_runs[5走]
    """
    encoded_date = urllib.parse.quote(date_str, safe='')
    url = (f"{_BASE}/KeibaWeb/TodayRaceInfo/DebaTable"
           f"?k_raceDate={encoded_date}&k_babaCode={baba_code}"
           f"&k_raceNo={race_no}")
    soup = _fetch(url)
    if not soup:
        return None

    # ── レース情報ヘッダー ──
    race_info = {
        'venue': BABA_CODE.get(str(baba_code), ''),
        'baba_code': str(baba_code),
        'race_no': int(race_no),
        'date': date_str,
    }
    h4 = soup.find('h4')
    if h4:
        h4_text = _clean(h4.get_text())
        m_time = re.search(r'(\d{1,2}:\d{2})\s*発走', h4_text)
        if m_time:
            race_info['post_time'] = m_time.group(1)

    # レース名はh3タグ(「Ｃ３三 四」等)。h4は「第N競走 HH:MM発走」のみ
    for h3 in soup.find_all('h3'):
        h3t = _clean(h3.get_text())
        if h3t and h3t != 'オッズ' and '見方' not in h3t:
            race_info['race_name'] = h3t
            break

    # 条件(距離/馬場/天候)はh4直後のul/liにある
    for ul in soup.find_all('ul'):
        for li in ul.find_all('li'):
            li_text = _clean(li.get_text())
            m_dist = re.search(r'(ダート|芝)\s*(\d+)', li_text)
            if m_dist:
                race_info['surface'] = m_dist.group(1)
                race_info['distance'] = int(m_dist.group(2))
                m_course = re.search(r'(\d+)ｍ[（(](.+?)[）)]', li_text)
                if m_course:
                    race_info['course_detail'] = m_course.group(2)
            m_weather = re.search(r'天候[：:]?\s*(\S+)', li_text)
            if m_weather:
                race_info['weather'] = m_weather.group(1)
            m_cond = re.search(r'馬場[：:]?\s*(\S+)', li_text)
            if m_cond:
                race_info['condition'] = m_cond.group(1)
            m_class = re.search(r'(サラブレッド|アラブ).+?(定量|別定|ハンデ)', li_text)
            if m_class:
                race_info['race_class'] = li_text

    # ── 出走馬テーブル ──
    # 構造: 1馬=約10行のブロック。
    #   row+0: [枠,馬番,馬名(link),騎手(link),オッズ(N人気),成績テキスト,...]
    #   row+1〜8: 成績詳細(全/左/右/場/距 の行, 最高タイム行)
    #   row+N: [性齢,毛色,誕生日,斤量,過去走レース名×5(link)]
    #   row+N+1: [父名,調教師(link),馬体重(増減),過去走の人気/体重/騎手/斤量×5]
    #   row+N+2: [母名,馬主,過去走のタイム/通過順/上がり×5]
    horses = []
    tables = soup.find_all('table')
    for tbl in tables:
        rows = tbl.find_all('tr')
        if len(rows) < 2:
            continue
        header_text = _clean(rows[0].get_text()) if rows else ''
        if '馬番' not in header_text and '枠' not in header_text:
            continue

        horses = _parse_horse_blocks(rows[1:])
        break

    if not horses:
        return None

    race_info['n_horses'] = len(horses)
    return {'race_info': race_info, 'horses': horses}


def _parse_horse_blocks(rows):
    """出走表テーブルの行群から馬ブロックを切り出してパースする。

    馬ブロックの先頭行は: セル[0]=枠番(1桁数字), セル[1]=馬番(1-2桁数字),
    セル[2]=馬名(リンク付き) で始まる。
    """
    horses = []
    block_starts = []
    for i, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        if len(cells) < 3:
            continue
        t0 = _clean(cells[0].get_text())
        t1 = _clean(cells[1].get_text())
        if re.match(r'^\d$', t0) and re.match(r'^\d{1,2}$', t1):
            a = cells[2].find('a', href=True)
            if a and 'HorseMarkInfo' in a.get('href', ''):
                block_starts.append(i)

    for bi, start in enumerate(block_starts):
        end = block_starts[bi + 1] if bi + 1 < len(block_starts) else len(rows)
        block = rows[start:end]
        h = _parse_one_horse(block)
        if h:
            horses.append(h)
    return horses


def _parse_one_horse(block_rows):
    """1馬分の行ブロック(約10行)をパースする。"""
    if not block_rows:
        return None

    # 先頭行: 枠/馬番/馬名/騎手/オッズ/成績
    cells0 = block_rows[0].find_all(['td', 'th'])
    ct0 = [_clean(c.get_text()) for c in cells0]
    try:
        waku = int(ct0[0])
        umaban = int(ct0[1])
    except (IndexError, ValueError):
        return None

    horse = {'waku': waku, 'umaban': umaban}

    # 馬名(link)
    if len(cells0) > 2:
        a = cells0[2].find('a', href=True)
        if a:
            horse['name'] = _clean(a.get_text())
            m_id = re.search(r'k_lineageLoginCode=(\d+)', a['href'])
            if m_id:
                horse['horse_id'] = m_id.group(1)

    # 騎手(link)
    if len(cells0) > 3:
        a = cells0[3].find('a', href=True)
        if a and 'RiderMark' in a.get('href', ''):
            horse['jockey'] = _clean(a.get_text())

    # オッズ・人気
    if len(cells0) > 4:
        odds_text = ct0[4]
        m_odds = re.search(r'([\d.]+)\s*\((\d+)人気\)', odds_text)
        if m_odds:
            try:
                horse['odds'] = float(m_odds.group(1))
                horse['popularity'] = int(m_odds.group(2))
            except ValueError:
                pass
        elif not m_odds:
            m_o = re.match(r'([\d.]+)', odds_text)
            if m_o:
                try:
                    v = float(m_o.group(1))
                    if 1.0 <= v <= 9999.9:
                        horse['odds'] = v
                except ValueError:
                    pass

    # 成績(全/場/距) — 先頭行セル[5]にまとまっていることが多い
    if len(ct0) > 5:
        rec_text = ct0[5]
        m_all = re.search(r'全\s*(\d+-\d+-\d+-\d+)', rec_text)
        if m_all:
            horse['record_all'] = m_all.group(1)
        m_venue = re.search(r'場\s*(\d+-\d+-\d+-\d+)', rec_text)
        if m_venue:
            horse['record_venue'] = m_venue.group(1)
        m_dist = re.search(r'距\s*(\d+-\d+-\d+-\d+)', rec_text)
        if m_dist:
            horse['record_distance'] = m_dist.group(1)

    # 残りの行から性齢/斤量/調教師/馬体重/父名/過去走を探す
    past_race_names = []
    past_details = []    # 人気/体重/騎手/斤量
    past_times = []      # タイム/通過順/上がり

    for row in block_rows[1:]:
        cells = row.find_all(['td', 'th'])
        ct = [_clean(c.get_text()) for c in cells]
        full = ' '.join(ct)

        # 性齢行: 「牝6 黒鹿毛 05.11生 54.0」
        m_sex = re.search(r'([牡牝セ])(\d+)', full)
        if m_sex and 'sex' not in horse:
            horse['sex'] = m_sex.group(1)
            horse['age'] = int(m_sex.group(2))
            m_wc = re.search(r'(\d{2,3}\.\d)\s', full)
            if m_wc:
                horse['weight_carried'] = float(m_wc.group(1))
            # 過去走レース名+日付(linkのhrefから抽出)
            for c in cells[4:]:
                a = c.find('a', href=True)
                if a and 'RaceMarkTable' in a.get('href', ''):
                    href = a['href']
                    rn = _clean(a.get_text())
                    m_rd = re.search(r'k_raceDate=([\d%A-Fa-f/]+)', href)
                    race_date = ''
                    if m_rd:
                        race_date = urllib.parse.unquote(m_rd.group(1))
                    m_bc = re.search(r'k_babaCode=(\d+)', href)
                    baba = m_bc.group(1) if m_bc else ''
                    past_race_names.append({
                        'name': rn, 'date': race_date, 'baba_code': baba,
                    })

        # 調教師行: cells=[父名, 調教師(link), 馬体重(増減), 過去走詳細×5]
        has_trainer = False
        for c in cells:
            a = c.find('a', href=True)
            if a and 'TrainerMark' in a.get('href', ''):
                horse['trainer'] = _clean(a.get_text())
                has_trainer = True
        if has_trainer and 'sire' not in horse and len(ct) >= 1:
            sire = ct[0].strip()
            if sire and not re.match(r'^[\d(（]', sire):
                horse['sire'] = sire

        # 母名行: cells=[母名, 馬主, 過去走タイム×5]
        # 母父行: cells=[(母父名), 生産牧場, ...]
        if len(ct) >= 2 and 'dam' not in horse:
            c0 = ct[0].strip()
            m_bf = re.match(r'[（(](.+?)[）)]', c0)
            if m_bf:
                horse['broodmare_sire'] = m_bf.group(1)
            elif (not re.match(r'^[\d]', c0)
                  and 'sire' in horse and 'dam' not in horse
                  and not has_trainer
                  and not re.search(r'[牡牝セ]\d', c0)
                  and not re.search(r'\d:\d{2}', c0)):
                horse['dam'] = c0

        # 馬体重(3桁 (+N))
        m_bw = re.search(r'(\d{3,4})\s*\(([+-]\d+)\)', full)
        if m_bw and 'weight' not in horse:
            w = int(m_bw.group(1))
            if 300 <= w <= 650:
                horse['weight'] = w
                horse['weight_diff'] = int(m_bw.group(2))

        # 過去走タイム行: 「タイム 通過順 上がり」
        if re.search(r'\d:\d{2}\.\d\s+\d+-\d+-', full):
            for c in cells:
                t = _clean(c.get_text())
                m_t = re.match(r'(\d:\d{2}\.\d)\s+([\d-]+)\s+(\d{2}\.\d)', t)
                if m_t:
                    past_times.append({
                        'time': m_t.group(1),
                        'passing': m_t.group(2),
                        'last_3f': float(m_t.group(3)),
                    })

        # 過去走の人気/体重/騎手行: 「N人 NNN 騎手名 NN.N」×5
        if re.search(r'\d+人\s+\d{3}', full):
            for c in cells:
                t = _clean(c.get_text())
                m_d = re.match(r'(\d+)人\s+(\d{3,4})\s+(\S+)\s+([\d.]+)', t)
                if m_d:
                    past_details.append({
                        'popularity': int(m_d.group(1)),
                        'weight': int(m_d.group(2)),
                        'jockey': m_d.group(3),
                        'weight_carried': float(m_d.group(4)),
                    })

    # 過去走を統合
    n_runs = max(len(past_race_names), len(past_times), len(past_details))
    if n_runs > 0:
        past_runs = []
        for j in range(min(n_runs, 5)):
            run = {}
            if j < len(past_race_names):
                prn = past_race_names[j]
                run['race_name'] = prn['name']
                if prn.get('date'):
                    run['race_date'] = prn['date']
                if prn.get('baba_code'):
                    run['baba_code'] = prn['baba_code']
            if j < len(past_details):
                run.update(past_details[j])
            if j < len(past_times):
                run.update(past_times[j])
            past_runs.append(run)
        horse['past_runs'] = past_runs

    return horse


# ──────────────────────────────────────────────
# レース結果パーサー
# ──────────────────────────────────────────────

def fetch_race_result(date_str, baba_code, race_no):
    """レース結果(着順・タイム・払戻)を取得する。

    戻り値: {'result': [{'finish':int,'umaban':int,'name':str,'time':str,...},...],
             'payouts': {...}} or None
    """
    encoded_date = urllib.parse.quote(date_str, safe='')
    url = (f"{_BASE}/KeibaWeb/TodayRaceInfo/RaceMarkTable"
           f"?k_raceDate={encoded_date}&k_babaCode={baba_code}"
           f"&k_raceNo={race_no}")
    soup = _fetch(url)
    if not soup:
        return None

    results = []
    tables = soup.find_all('table')
    # table[0]: 着順/枠/馬番/馬名/所属/性齢/負担重量/騎手/調教師/馬体重/タイム/着差/上がり3F/通過順/人気/単勝オッズ
    for tbl in tables:
        rows = tbl.find_all('tr')
        if not rows:
            continue
        hdr = [_clean(c.get_text()) for c in rows[0].find_all(['td', 'th'])]
        if '着順' not in hdr:
            continue
        for row in rows[1:]:
            cells = row.find_all(['td', 'th'])
            if len(cells) < 10:
                continue
            ct = [_clean(c.get_text()) for c in cells]
            try:
                finish = int(ct[0])
                waku = int(ct[1])
                umaban = int(ct[2])
            except (ValueError, IndexError):
                continue
            if finish < 1 or finish > 30:
                continue
            entry = {
                'finish': finish,
                'waku': waku,
                'umaban': umaban,
                'name': ct[3],
                'affiliation': ct[4],
                'sex_age': ct[5],
            }
            try:
                entry['weight_carried'] = float(ct[6])
            except ValueError:
                pass
            entry['jockey'] = ct[7].strip()
            entry['trainer'] = ct[8].strip()
            m_bw = re.match(r'(\d{3,4})\(([+-]?\d+)\)', ct[9].replace(' ', ''))
            if m_bw:
                entry['weight'] = int(m_bw.group(1))
                entry['weight_diff'] = int(m_bw.group(2))
            m_t = re.search(r'(\d{1,2}:\d{2}\.\d)', ct[10])
            if m_t:
                entry['time'] = m_t.group(1)
            entry['margin'] = ct[11]
            try:
                entry['last_3f'] = float(ct[12])
            except (ValueError, IndexError):
                pass
            if len(ct) > 13:
                entry['passing'] = ct[13]
            if len(ct) > 14:
                try:
                    entry['popularity'] = int(ct[14])
                except ValueError:
                    pass
            if len(ct) > 15:
                try:
                    entry['win_odds'] = float(ct[15])
                except ValueError:
                    pass
            results.append(entry)
        break

    # 払戻金(table[1]=単勝/複勝、table[2]=馬連単/ワイド/3連単等)
    payouts = {}
    for tbl in tables:
        rows = tbl.find_all('tr')
        if not rows:
            continue
        first_ct = [_clean(c.get_text()) for c in rows[0].find_all(['td', 'th'])]
        if not first_ct or first_ct[0] not in ('単勝', '馬連単', '馬連複', '3連単', '3連複', '枠連複', '枠連単'):
            continue
        current_type = None
        for row in rows:
            ct = [_clean(c.get_text()) for c in row.find_all(['td', 'th'])]
            if not ct:
                continue
            if ct[0] in ('単勝', '複勝', '枠連複', '枠連単', '馬連複', '馬連単',
                         'ワイド', '3連複', '3連単'):
                current_type = ct[0]
                nums = ct[1] if len(ct) > 1 else ''
                m_pay = re.search(r'([\d,]+)円', ct[2] if len(ct) > 2 else '')
            else:
                nums = ct[0]
                m_pay = re.search(r'([\d,]+)円', ct[1] if len(ct) > 1 else '')
            if m_pay and current_type:
                key = f"{current_type}_{nums}" if current_type in ('複勝', 'ワイド') else current_type
                payouts[key] = int(m_pay.group(1).replace(',', ''))

    if not results:
        return None
    results.sort(key=lambda r: r['finish'])
    return {'result': results, 'payouts': payouts}


# ──────────────────────────────────────────────
# 便利関数
# ──────────────────────────────────────────────

def fetch_full_card(date_str, baba_code, max_races=12):
    """1開催場の全レース出走表をまとめて取得。

    max_races: 安全上限(既定12R)。
    戻り値: [fetch_entry_table()の戻り値, ...] (Noneは除外)
    """
    reset_session()
    race_list = fetch_race_list(date_str, baba_code)
    if not race_list:
        return []

    entries = []
    for r in race_list[:max_races]:
        entry = fetch_entry_table(date_str, baba_code, r['race_no'])
        if entry:
            entries.append(entry)
        logger.info("[nar] fetched %s R%d (%d horses)",
                    BABA_CODE.get(str(baba_code), baba_code),
                    r['race_no'],
                    len(entry['horses']) if entry else 0)
    return entries


# ──────────────────────────────────────────────
# 新聞パイプライン変換
# ──────────────────────────────────────────────

def _estimate_finish_from_time(runs):
    """過去走のタイムからレース内着順を推定する。

    出馬表には着順が載っていないので、走破タイムの速い順を
    擬似着順とする。同一レースの他馬は見えないため、
    上がり3Fの速さ＋走破タイムの速さを組み合わせて
    相対的な「好走度」を0-100で返す(高い=好走)。
    """
    scores = []
    for r in runs[:5]:
        total = _parse_time_seconds(r.get('time'))
        last_3f = r.get('last_3f')
        pop = r.get('popularity')
        if total is None and last_3f is None:
            continue
        pts = 0
        if last_3f is not None:
            if last_3f < 37.0:
                pts += 30
            elif last_3f < 38.0:
                pts += 25
            elif last_3f < 39.0:
                pts += 18
            elif last_3f < 40.0:
                pts += 10
            elif last_3f < 41.0:
                pts += 5
        if pop is not None:
            if pop <= 2:
                pts += 20
            elif pop <= 4:
                pts += 12
            elif pop <= 6:
                pts += 6
            elif pop <= 8:
                pts += 2
        scores.append(pts)
    if not scores:
        return 0
    weights = [1.5, 1.2, 1.0, 0.8, 0.6]
    weighted = sum(s * weights[i] for i, s in enumerate(scores))
    divisor = sum(weights[:len(scores)])
    return weighted / divisor


def _strip_affiliation(name):
    """騎手名から所属（川崎）等を除去して純粋な名前を返す。"""
    return re.sub(r'[（(][^）)]*[）)]', '', str(name)).strip().replace('　', '').replace(' ', '')


def _detect_jockey_change(h):
    """乗り替わりを検知する。

    戻り値: {'changed': bool, 'prev_jockey': str or None,
             'label': '継続'/'乗替'/'初騎乗'}
    """
    current = h.get('jockey', '')
    runs = h.get('past_runs', [])
    if not runs or not current:
        return {'changed': False, 'prev_jockey': None, 'label': '?'}

    prev = runs[0].get('jockey', '')
    if not prev:
        return {'changed': False, 'prev_jockey': None, 'label': '?'}

    c_norm = _strip_affiliation(current)
    p_norm = _strip_affiliation(prev)

    if c_norm == p_norm:
        return {'changed': False, 'prev_jockey': prev, 'label': ''}

    all_prev = [_strip_affiliation(r.get('jockey', ''))
                for r in runs if r.get('jockey')]
    if c_norm not in all_prev:
        return {'changed': True, 'prev_jockey': prev, 'label': '初騎乗'}

    return {'changed': True, 'prev_jockey': prev, 'label': '乗替'}


def _nar_horse_score(h):
    """過去走データから戦闘力スコア(0-100)を算出する。

    JRA版OguraIndex+Projected Scoreの簡易再現。
    構成:
      - 好走度(30): タイム/上がり/人気からの擬似着順(近走重み付き)
      - 上がり偏差(20): 近3走の上がり3Fの速さ
      - オッズ由来(25): 市場評価(人気=集合知)
      - 人気安定性(10): 近走で上位人気を維持しているか
      - 馬体重安定(5): 体重増減の安定性
      - 乗り替わり(5): 継続騎乗=信頼
      - 脚質適性(5): 逃げ/先行の前有利
    """
    score = 40.0

    runs = h.get('past_runs', [])

    # ── 好走度(擬似着順): 最大±30 ──
    if runs:
        perf = _estimate_finish_from_time(runs)
        score += (perf - 25) * 0.6  # 25が中央、0-50が典型→ -15 to +15

    # ── 上がり3F偏差: 最大±20 ──
    if runs:
        last_3fs = [r['last_3f'] for r in runs[:3] if 'last_3f' in r]
        if last_3fs:
            avg_3f = sum(last_3fs) / len(last_3fs)
            agari_score = max(-15, min(20, (40.0 - avg_3f) * 4))
            score += agari_score

    # ── オッズ由来(市場評価): 最大±25 ──
    odds = h.get('odds')
    if odds and odds > 0:
        import math
        odds_score = max(-10, min(25, 20 - math.log(odds) * 5))
        score += odds_score

    # ── 人気安定性: 最大±10 ──
    if runs:
        pops = [r.get('popularity') for r in runs[:3] if r.get('popularity')]
        if pops:
            avg_pop = sum(pops) / len(pops)
            if avg_pop <= 3:
                score += 10
            elif avg_pop <= 5:
                score += 5
            elif avg_pop >= 10:
                score -= 5

    # ── 馬体重安定: ±5 ──
    wd = h.get('weight_diff', 0)
    if abs(wd) <= 4:
        score += 3
    elif abs(wd) > 10:
        score -= 5

    # ── 乗り替わり: ±5 ──
    jc = _detect_jockey_change(h)
    if jc['label'] == '継続':
        score += 3
    elif jc['label'] == '初騎乗':
        score -= 2

    # ── 脚質(前有利バイアス): ±5 ──
    style = _classify_style(runs)
    if style == '逃':
        score += 4
    elif style == '先':
        score += 2
    elif style == '追':
        score -= 2

    # ── 騎手力ファクター(キャッシュ済みリーディング): ×0.7〜1.3 ──
    venue = h.get('_venue')
    jf = jockey_factor(h.get('jockey', ''), venue=venue)
    score *= jf

    return max(0, min(100, round(score, 1)))


def entry_to_view(entry_data):
    """fetch_entry_table()の戻り値を新聞ビルダー互換のrecords/meta形式に変換する。

    戻り値: {'records': [...], 'meta': {...}, 'source': 'nar'}
    """
    if not entry_data:
        return None

    ri = entry_data['race_info']
    meta = {
        'venue': ri.get('venue', ''),
        'race_name': ri.get('race_name', ''),
        'surface': ri.get('surface', ''),
        'distance': ri.get('distance', 0),
        'condition': ri.get('condition', ''),
        'post_time': ri.get('post_time', ''),
        'n_horses': ri.get('n_horses', 0),
        'date': ri.get('date', ''),
        'race_no': ri.get('race_no', 0),
        'weather': ri.get('weather', ''),
        'nar': True,
    }

    venue_name = ri.get('venue', '')
    records = []
    for h in entry_data['horses']:
        h['_venue'] = venue_name
        score = _nar_horse_score(h)
        rec = {
            'Umaban': h['umaban'],
            'Name': h.get('name', ''),
            '馬名': h.get('name', ''),
            'Waku': h.get('waku', 0),
            '枠': h.get('waku', 0),
            'Jockey': h.get('jockey', ''),
            '騎手': h.get('jockey', ''),
            'Trainer': h.get('trainer', ''),
            '厩舎': h.get('trainer', ''),
            'Odds': h.get('odds', ''),
            '単勝': h.get('odds', ''),
            'BattleScore': score,
        }
        # 性齢
        sex = h.get('sex', '')
        age = h.get('age', '')
        if sex and age:
            rec['sex_age'] = f"{sex}{age}"
        # 馬体重
        if 'weight' in h:
            rec['weight'] = h['weight']
            rec['weight_diff'] = h.get('weight_diff', 0)
        # 斤量
        if 'weight_carried' in h:
            rec['weight_carried'] = h['weight_carried']
        # 乗り替わり
        jc = _detect_jockey_change(h)
        rec['JockeyChange'] = jc['label']

        # 過去走サマリー(コメント用)
        runs = h.get('past_runs', [])
        if runs:
            rec['_past_runs'] = runs

        records.append(rec)

    records.sort(key=lambda r: r['Umaban'])
    return {'records': records, 'meta': meta, 'source': 'nar'}


_RUN_LABELS = ['前走', '2走前', '3走前', '4走前', '5走前']

# ──────────────────────────────────────────────
# NAR独自分析エンジン
# ──────────────────────────────────────────────

# NAR/ダート種牡馬ティア(S=地方最強級, A=ダート適性高)
_NAR_DIRT_TIER = {
    # S-tier: 地方競馬の獲得賞金top5+圧倒的ダート実績
    'サウスヴィグラス': 'S', 'ヘニーヒューズ': 'S',
    'シニスターミニスター': 'S', 'パイロ': 'S',
    'ゴールドアリュール': 'S', 'ホッコータルマエ': 'S',
    # A-tier: 地方賞金top10残り+血統辞典2026で複数場「超爆買い」
    'コパノリッキー': 'A',
    'エスポワールシチー': 'A', 'カネヒキリ': 'A',
    'マジェスティックウォリアー': 'A', 'フリオーソ': 'A',
    'スマートファルコン': 'A', 'ドレフォン': 'A',
    'エスケンデレヤ': 'A', 'ラニ': 'A',
    'アメリカンペイトリオット': 'A', 'アジアエクスプレス': 'A',
    'トランセンド': 'A', 'モーニン': 'A',
    'ダノンレジェンド': 'A', 'カジノドライヴ': 'A',
    'ディスクリートキャット': 'A', 'キングカメハメハ': 'A',
    'ロードカナロア': 'A', 'ルーラーシップ': 'A',
    'キズナ': 'A', 'ニューイヤーズデイ': 'A',
    'マインドユアビスケッツ': 'A', 'カレンブラックヒル': 'A',
    'リアルスティール': 'A', 'ルヴァンスレーヴ': 'A',
    'キタサンブラック': 'A', 'ノボジャック': 'A',
    'ラブリーデイ': 'A', 'ゴールドドリーム': 'A',
    'ベストウォーリア': 'A', 'マクフィ': 'A',
}

# 場×距離で激走する種牡馬(血統辞典2026地方版の「超爆買い/爆買い」)
# キー=(場名, 距離)  距離は±100mで照合
_NAR_VENUE_DIST_SIRES: dict[tuple[str, int], set[str]] = {
    ('大井', 1200): {'ルックスザットキル', 'シャンハイボビー', 'ニューイヤーズデイ',
                     'ノボジャック', 'フォーウィールドライブ'},
    ('大井', 1400): {'シニスターミニスター', 'ミスターメロディ',
                     'アジアエクスプレス', 'デクラレーションオブウォー'},
    ('大井', 1600): {'カレンブラックヒル', 'ラブリーデイ', 'シニスターミニスター',
                     'インカンテーション'},
    ('川崎', 900):  {'ネロ', 'モーニン', 'ロードカナロア', 'リオンディーズ',
                     'フリオーソ', 'キタサンミカヅキ'},
    ('川崎', 1400): {'ダノンレジェンド', 'ダノンバラード', 'モーニン',
                     'ジョーカプチーノ', 'ニューイヤーズデイ'},
    ('川崎', 1500): {'パイロ', 'ホッコータルマエ', 'コパノリッキー',
                     'レッドファルクス', 'マクフィ'},
    ('川崎', 1600): {'アメリカンファラオ', 'リアルスティール',
                     'ゴールドドリーム', 'アジアエクスプレス'},
    ('船橋', 1200): {'エスポワールシチー', 'マクフィ', 'ドレフォン',
                     'モーニン', 'ノボジャック', 'クロフネ'},
    ('船橋', 1500): {'キズナ', 'キタサンブラック', 'スクリーンヒーロー',
                     'バンブーエール', 'ドレフォン'},
    ('船橋', 1600): {'シニスターミニスター', 'パイロ',
                     'マインドユアビスケッツ', 'スマートファルコン'},
    ('園田', 820):  {'ダノンレジェンド', 'ファインニードル', 'モズアスコット',
                     'モーニン', 'スズカコーズウェイ'},
    ('園田', 1400): {'キズナ', 'パイロ', 'コパノリッキー',
                     'マジェスティックウォリアー', 'アジアエクスプレス',
                     'ダノンレジェンド', 'ニューイヤーズデイ', 'ルヴァンスレーヴ'},
    ('名古屋', 920):  {'ラブリーデイ', 'ロードカナロア', 'カレンブラックヒル',
                       'ダノンレジェンド', 'マインドユアビスケッツ'},
    ('名古屋', 1400): {'キズナ', 'ホッコータルマエ', 'ベストウォーリア',
                       'ブリックスアンドモルタル'},
    ('名古屋', 1500): {'ホッコータルマエ', 'キタサンブラック',
                       'コパノリッキー', 'リアルスティール'},
    ('名古屋', 1700): {'マインドユアビスケッツ', 'オルフェーヴル',
                       'マジェスティックウォリアー', 'ルヴァンスレーヴ'},
}


def _sire_venue_match(sire: str, venue: str, distance) -> bool:
    """種牡馬が当該場×距離で「激走血統」か判定(±100m許容)。"""
    if not sire or not venue or not distance:
        return False
    try:
        dist = int(distance)
    except (ValueError, TypeError):
        return False
    for (v, d), sires in _NAR_VENUE_DIST_SIRES.items():
        if v == venue and abs(d - dist) <= 100 and sire in sires:
            return True
    return False


# 父系統テーブル(NARブラッドライン)
_SIRE_LINEAGE = {
    # サンデーサイレンス系
    'ディープインパクト': 'SS瞬発', 'ハーツクライ': 'SS持続',
    'ステイゴールド': 'SS持続', 'ダイワメジャー': 'SSマイル',
    'キズナ': 'SS瞬発', 'エピファネイア': 'SS万能',
    'ドゥラメンテ': 'SS万能', 'リアルスティール': 'SS瞬発',
    'サトノダイヤモンド': 'SS持続', 'マカヒキ': 'SS瞬発',
    'スワーヴリチャード': 'SS万能', 'コントレイル': 'SS瞬発',
    'シャフリヤール': 'SS瞬発', 'イクイノックス': 'SS瞬発',
    'キタサンブラック': 'SS持続',
    # ミスタープロスペクター系
    'キングカメハメハ': 'MP万能', 'ロードカナロア': 'MPスプリント',
    'ルーラーシップ': 'MP持続', 'ホッコータルマエ': 'MPダ',
    'コパノリッキー': 'MPダ', 'ゴールドアリュール': 'MPダ',
    'エスポワールシチー': 'MPダ', 'カネヒキリ': 'MPダ',
    'シニスターミニスター': 'MPダ', 'パイロ': 'MPダ',
    'ヘニーヒューズ': 'MPダ', 'サウスヴィグラス': 'MPダ短',
    'マジェスティックウォリアー': 'MPダ',
    # ノーザンダンサー系
    'ハービンジャー': 'ND芝持続', 'モーリス': 'ND万能',
    'オルフェーヴル': 'ND万能', 'ジャスタウェイ': 'ND芝瞬発',
    'ドレフォン': 'NDダ',
    # ロベルト系
    'シンボリクリスエス': 'RB万能', 'エイシンフラッシュ': 'RB芝',
    'スクリーンヒーロー': 'RB万能',
    # その他ダート血統
    'アジアエクスプレス': 'その他ダ', 'フリオーソ': 'その他ダ',
    'スマートファルコン': 'その他ダ', 'トランセンド': 'その他ダ',
    'エスケンデレヤ': 'その他ダ', 'ラニ': 'その他ダ',
    'アメリカンペイトリオット': 'その他ダ',
    # その他
    'アルアイン': 'SS万能', 'サトノクラウン': 'ND万能',
    'ミッキーアイル': 'SSマイル', 'ビッグアーサー': 'SSスプリント',
    'タリスマニック': 'ND芝持続', 'リオンディーズ': 'MP万能',
}


def _parse_time_seconds(time_str):
    """タイム文字列(M:SS.T)を秒数に変換。"""
    if not time_str:
        return None
    m = re.match(r'(\d+):(\d{2})\.(\d)', str(time_str))
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) * 0.1


def _classify_style(runs):
    """通過順パターンから脚質を判定(NARスタイル判定)。

    戻り値: '逃' / '先' / '差' / '追' / '?'
    """
    if not runs:
        return '?'
    positions = []
    for r in runs[:5]:
        passing = r.get('passing', '')
        if not passing:
            continue
        parts = passing.split('-')
        if parts:
            try:
                positions.append(int(parts[0]))
            except ValueError:
                pass
    if not positions:
        return '?'
    avg = sum(positions) / len(positions)
    if avg <= 1.5:
        return '逃'
    elif avg <= 3.5:
        return '先'
    elif avg <= 6.5:
        return '差'
    else:
        return '追'


def _pace_index(runs):
    """過去走からNARペース指数を計算する。

    走破タイム - 上がり3F = 前半区間タイム。
    前半区間 / 上がり3F = ペース比。
    1.0超=前傾(ハイペース)、1.0未満=後傾(スロー)。
    近3走の平均を返す。
    """
    ratios = []
    front_times = []
    for r in runs[:3]:
        total = _parse_time_seconds(r.get('time'))
        last_3f = r.get('last_3f')
        if total and last_3f and last_3f > 0:
            front = total - last_3f
            if front > 0:
                ratios.append(front / last_3f)
                front_times.append(front)
    if not ratios:
        return None, None
    avg_ratio = sum(ratios) / len(ratios)
    avg_front = sum(front_times) / len(front_times)
    return round(avg_ratio, 2), round(avg_front, 1)


def _predict_pace(horses):
    """出走馬の脚質分布からレースペースを予測(NAR展開図)。

    戻り値: {'pace': 'ハイ'/'ミドル'/'スロー',
             'front_count': int, 'chaser_count': int,
             'style_dist': {...}, 'comment': str}
    """
    styles = {}
    for h in horses:
        runs = h.get('past_runs', [])
        s = _classify_style(runs)
        styles[h['umaban']] = s

    counts = {'逃': 0, '先': 0, '差': 0, '追': 0, '?': 0}
    for s in styles.values():
        counts[s] = counts.get(s, 0) + 1

    front = counts['逃'] + counts['先']
    n = max(len(horses), 1)
    known = n - counts['?']
    front_pct = front / max(known, 1)

    if known < n * 0.5:
        pace = '不明'
        comment = f"過去走データ不足({known}/{n}頭)"
    elif counts['逃'] >= 3:
        pace = 'ハイ'
        comment = f"逃げ{counts['逃']}頭で先行争い激化→差し有利"
    elif counts['逃'] >= 2 and front >= 4:
        pace = 'ハイ'
        comment = f"前に行きたい馬{front}頭→ペース上がる"
    elif counts['逃'] == 0 and front_pct <= 0.17:
        pace = 'スロー'
        comment = "逃げ不在で楽逃げ→前残り警戒"
    elif counts['逃'] <= 1 and front_pct < 0.25:
        pace = 'スロー'
        comment = f"逃げ{counts['逃']}頭で楽逃げ→前残り警戒"
    else:
        pace = 'ミドル'
        comment = f"逃げ{counts['逃']}先行{counts['先']}→平均ペース"

    return {
        'pace': pace,
        'front_count': front,
        'chaser_count': counts['差'] + counts['追'],
        'style_dist': counts,
        'styles': styles,
        'comment': comment,
    }


def _format_weight(h):
    """馬体重文字列を生成。穴帯(7人気+)×500kg+に'P'マーカーを付与。"""
    w = h.get('weight')
    if not w:
        return ''
    diff = h.get('weight_diff', 0)
    s = f"{w}({diff:+d})"
    pop = h.get('popularity', 0)
    try:
        pop = int(pop)
    except (TypeError, ValueError):
        pop = 0
    if w >= 500 and pop >= 7:
        s += 'P'
    return s


def entry_to_full_view(entry_data):
    """通常版新聞用: 過去走をフラット列に展開したrecords/meta形式。

    初心者版(entry_to_view)より多くの列を持つ:
    - 過去5走のレース名/タイム/通過順/上がり3F/人気
    - 平均上がり3F(近3走)
    - 近走成績(勝-2-3-着外)
    - 父名/母名
    - 簡易スコア
    """
    if not entry_data:
        return None

    ri = entry_data['race_info']
    meta = {
        'venue': ri.get('venue', ''),
        'race_name': ri.get('race_name', ''),
        'surface': ri.get('surface', ''),
        'distance': ri.get('distance', 0),
        'condition': ri.get('condition', ''),
        'post_time': ri.get('post_time', ''),
        'n_horses': ri.get('n_horses', 0),
        'date': ri.get('date', ''),
        'race_no': ri.get('race_no', 0),
        'weather': ri.get('weather', ''),
        'nar': True,
    }

    venue_name = ri.get('venue', '')
    race_date_str = ri.get('date', '')
    records = []
    for h in entry_data['horses']:
        h['_venue'] = venue_name
        h['_race_date'] = race_date_str
        score = _nar_horse_score(h)
        jf = jockey_factor(h.get('jockey', ''), venue=venue_name)
        ji = jockey_info(h.get('jockey', ''))
        rec = {
            'Umaban': h['umaban'],
            'Waku': h.get('waku', 0),
            'Name': h.get('name', ''),
            'SexAge': f"{h.get('sex', '')}{h.get('age', '')}",
            'WeightCarried': h.get('weight_carried', ''),
            'Weight': _format_weight(h),
            'Jockey': h.get('jockey', ''),
            'Trainer': h.get('trainer', ''),
            'Odds': h.get('odds', ''),
            'Popularity': h.get('popularity', ''),
            'BattleScore': score,
        }

        # 血統(父/母)
        if h.get('sire'):
            rec['Sire'] = h['sire']
            rec['_sire_tier'] = _NAR_DIRT_TIER.get(h['sire'], '')
            rec['_sire_hot'] = _sire_venue_match(
                h['sire'], venue_name, ri.get('distance', 0))
        if h.get('dam'):
            rec['Dam'] = h['dam']

        # 成績
        rec_all = h.get('record_all', '')
        if rec_all:
            rec['Record'] = rec_all

        # 過去走をフラット展開
        runs = h.get('past_runs', [])
        last_3fs = []
        for j, label in enumerate(_RUN_LABELS):
            if j < len(runs):
                r = runs[j]
                rec[f'{label}R名'] = r.get('race_name', '')
                if 'time' in r:
                    rec[f'{label}T'] = r['time']
                if 'passing' in r:
                    rec[f'{label}通過'] = r['passing']
                if 'last_3f' in r:
                    rec[f'{label}上り'] = r['last_3f']
                    last_3fs.append(r['last_3f'])
                if 'popularity' in r:
                    rec[f'{label}人'] = r['popularity']

        # 平均上がり3F(近3走)
        if last_3fs:
            rec['AvgAgari'] = round(sum(last_3fs[:3]) / len(last_3fs[:3]), 1)

        # ── NAR独自指標 ──
        # NARスタイル判定(脚質分類)
        rec['Style'] = _classify_style(runs)

        # NARペース指数(前半区間タイム/上がり3F比)
        ratio, front_t = _pace_index(runs)
        if ratio is not None:
            rec['PaceIdx'] = ratio
            rec['FrontHalf'] = front_t

        # 乗り替わり検知
        jc = _detect_jockey_change(h)
        rec['JockeyChange'] = jc['label']
        if jc['prev_jockey']:
            rec['PrevJockey'] = jc['prev_jockey']

        # 好走度(擬似着順スコア)
        if runs:
            rec['FormIdx'] = round(_estimate_finish_from_time(runs), 1)

        # 出走間隔(前走日付からの日数)
        race_date_str = ri.get('date', '')
        if runs and runs[0].get('race_date') and race_date_str:
            try:
                from datetime import datetime
                today_dt = datetime.strptime(race_date_str, '%Y/%m/%d')
                prev_dt = datetime.strptime(runs[0]['race_date'], '%Y/%m/%d')
                interval_days = (today_dt - prev_dt).days
                if 0 < interval_days < 365:
                    rec['Interval'] = interval_days
            except (ValueError, TypeError):
                pass

        # 騎手力(リーディングデータ)
        rec['JFactor'] = jf
        if ji:
            rec['JWinRate'] = ji.get('win_rate', '')
            rec['JShowRate'] = ji.get('show_rate', '')
            rec['JHome'] = ji.get('home_venue', '')

        records.append(rec)

    records.sort(key=lambda r: r['Umaban'])

    # ── BattleScoreでRank付与(新聞の行色分けに使う) ──
    by_score = sorted(records, key=lambda r: r.get('BattleScore', 0), reverse=True)
    for rank_i, rec in enumerate(by_score):
        rec['Rank'] = rank_i + 1

    # ── NAR展開予測(レース全体) ──
    pace_pred = _predict_pace(entry_data['horses'])
    meta['pace_prediction'] = pace_pred

    # 列順を定義
    columns = [
        'Umaban', 'Waku', 'Name', 'SexAge', 'WeightCarried', 'Weight',
        'Jockey', 'JockeyChange', 'JFactor', 'Trainer', 'Odds', 'Popularity',
        'BattleScore', 'FormIdx', 'Style',
    ]
    if any(r.get('Interval') for r in records):
        columns.append('Interval')
    if any(r.get('Sire') for r in records):
        columns.append('Sire')
    if any(r.get('Dam') for r in records):
        columns.append('Dam')
    if any(r.get('PaceIdx') for r in records):
        columns.extend(['PaceIdx', 'FrontHalf'])
    columns.append('AvgAgari')
    for label in _RUN_LABELS:
        for suffix in ['R名', 'T', '上り', '通過', '人']:
            col = f'{label}{suffix}'
            if any(r.get(col) for r in records):
                columns.append(col)

    labels = {
        'Umaban': '馬番', 'Waku': '枠', 'Name': '馬名',
        'SexAge': '性齢', 'WeightCarried': '斤量',
        'Weight': '馬体重', 'Jockey': '騎手',
        'JockeyChange': '鞍上', 'PrevJockey': '前走騎手',
        'JFactor': '騎手力', 'JWinRate': '騎手勝率', 'JShowRate': '騎手複率',
        'JHome': '騎手所属',
        'Trainer': '調教師',
        'Odds': '単勝', 'Popularity': '人気',
        'BattleScore': '総合力', 'FormIdx': '好走度',
        'Style': '脚質', 'Interval': '中間日',
        'Sire': '父', 'Bloodline': '血脈型',
        'Dam': '母', 'Record': '成績',
        'PaceIdx': 'ペ指数', 'FrontHalf': '前半T',
        'AvgAgari': '平均上り',
    }
    for label in _RUN_LABELS:
        labels[f'{label}R名'] = f'{label}'
        labels[f'{label}T'] = 'T'
        labels[f'{label}上り'] = '上り'
        labels[f'{label}通過'] = '通過'
        labels[f'{label}人'] = '人'

    return {
        'records': records,
        'meta': meta,
        'source': 'nar',
        'columns': columns,
        'labels': labels,
    }


def _nar_arare_forecast(scored, horses):
    """NAR荒れ予報を算出する。

    JRA版の検証済みロジック(オッズエントロピー主軸・AUC0.69)のNAR再現:
    1. オッズエントロピー(最大の予測力) — オッズが拮抗するほど荒れやすい
    2. 頭数(16頭z5.9/8-10頭は堅い) — フルゲートは荒れ、少頭数は堅い
    3. 本命不在(コンピ大穴等価) — 1番人気オッズが高いほど荒れ
    4. ペース混戦 — 逃げ馬3頭以上は先行争いで荒れやすい
    """
    import math

    odds_list = []
    for _, _, h in scored:
        o = h.get('odds')
        if o and o > 0:
            odds_list.append(o)

    n = len(horses)
    logit = 0.0  # 対数オッズ(正=荒れ)

    # ── 1. オッズエントロピー(最重要シグナル) ──
    if odds_list:
        total = sum(1.0 / o for o in odds_list)
        if total > 0:
            probs = [(1.0 / o) / total for o in odds_list]
            entropy = -sum(p * math.log(p + 1e-9) for p in probs)
            max_entropy = math.log(max(len(probs), 2))
            norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.5
            # エントロピー0.7以上は拮抗(荒れやすい)、0.5未満は一強(堅い)
            logit += (norm_entropy - 0.6) * 4.0

    # ── 2. 頭数 ──
    if n >= 14:
        logit += 0.5
    elif n >= 12:
        logit += 0.2
    elif n <= 8:
        logit -= 0.6
    elif n <= 10:
        logit -= 0.3

    # ── 3. 本命不在(1番人気オッズが高い) ──
    if odds_list:
        top_odds = min(odds_list)
        if top_odds >= 5.0:
            logit += 0.8
        elif top_odds >= 3.5:
            logit += 0.3
        elif top_odds <= 1.5:
            logit -= 0.5

    # ── 4. ペース混戦 ──
    n_esc = sum(1 for h in horses
                if _classify_style(h.get('past_runs', [])) == '逃')
    if n_esc >= 3:
        logit += 0.4
    elif n_esc == 0:
        logit -= 0.2

    # logit → 確率
    prob = 1.0 / (1.0 + math.exp(-logit))
    prob = max(0.10, min(0.90, prob))

    # 理由テキスト
    reasons = []
    if odds_list:
        if norm_entropy >= 0.75:
            reasons.append('オッズ拮抗')
        elif norm_entropy <= 0.45:
            reasons.append('一強・堅い')
    if n >= 14:
        reasons.append(f'{n}頭の多頭数')
    elif n <= 8:
        reasons.append(f'{n}頭の少頭数→堅め')
    if odds_list and min(odds_list) >= 5.0:
        reasons.append('本命不在')
    if n_esc >= 3:
        reasons.append(f'逃げ{n_esc}頭で先行争い')

    return {
        'arare_prob': round(prob, 2),
        'arare_reasons': reasons,
    }


def build_nar_consensus(entry_data):
    """NAR出走表データから簡易合議(マーク+コメント)を生成する。

    JRAのMAGI合議の代わりに、オッズ+過去走成績から
    本命/対抗/注意/穴/消しを判定する。
    """
    if not entry_data:
        return None

    horses = entry_data['horses']
    venue_name = entry_data.get('race_info', {}).get('venue', '')
    scored = []
    for h in horses:
        h['_venue'] = venue_name
        s = _nar_horse_score(h)
        scored.append((h['umaban'], s, h))
    scored.sort(key=lambda x: -x[1])

    n = len(scored)
    groups = {'honmei': [], 'aite': [], 'osae': [], 'ana': [], 'keshi': []}
    aim = {}

    for rank, (umaban, score, h) in enumerate(scored):
        uma_key = str(umaban)
        # マーク割り当て
        if rank == 0:
            groups['honmei'].append(umaban)
        elif rank == 1:
            groups['aite'].append(umaban)
        elif rank == 2:
            groups['osae'].append(umaban)
        elif rank < n - 2 and h.get('odds', 999) >= 15:
            groups['ana'].append(umaban)
        elif rank >= n - 2:
            groups['keshi'].append(umaban)

        # コメント生成
        edge = []
        danger = []
        runs = h.get('past_runs', [])
        if runs:
            last_3fs = [r['last_3f'] for r in runs[:3] if 'last_3f' in r]
            if last_3fs and min(last_3fs) < 38:
                edge.append('末脚キレる')
            elif last_3fs and sum(last_3fs)/len(last_3fs) < 39:
                edge.append('上がり安定')

            recent_pops = [r.get('popularity', 99) for r in runs[:3] if 'popularity' in r]
            if recent_pops and sum(recent_pops)/len(recent_pops) <= 3:
                edge.append('近走人気安定')
            elif recent_pops and min(recent_pops) <= 2:
                edge.append('人気実績あり')

        odds = h.get('odds', 999)
        if odds < 3:
            edge.append('断然人気')
        elif odds > 30 and score >= 55:
            edge.append('穴候補')

        # 騎手力
        jf = jockey_factor(h.get('jockey', ''), venue=venue_name)
        ji = jockey_info(h.get('jockey', ''))
        if ji:
            wr = ji.get('win_rate', 0)
            if wr >= 20:
                hv = ji.get('home_venue', '')
                home_tag = '(地元)' if hv == venue_name else ''
                edge.append(f"騎手勝率{wr:.0f}%{home_tag}")
            elif wr > 0 and wr < 8:
                danger.append(f"騎手勝率{wr:.0f}%")

        # 乗り替わり
        jc = _detect_jockey_change(h)
        if jc['label'] == '初騎乗':
            danger.append(f"初騎乗(前走:{jc['prev_jockey']})")
        elif jc['label'] == '乗替':
            edge.append(f"テン乗り(←{jc['prev_jockey']})")

        # 脚質×展開
        style = _classify_style(runs)
        n_esc = sum(1 for hh in horses
                    if _classify_style(hh.get('past_runs', [])) == '逃')
        if style == '逃':
            edge.append('逃げ馬(複勝率52%)')
            if n_esc == 1:
                edge.append('楽逃げ(1頭)')
        elif style == '先':
            edge.append('先行(複勝率36%)')
        if (style == '差' or style == '追') and n_esc >= 3:
            edge.append('先行争い→差し有利')

        # 大型馬(500kg+パワー型) — 穴帯(7人気+)のみ妙味(検証済)
        hw = h.get('weight', 0)
        _pop = h.get('popularity', 0)
        try:
            _pop = int(_pop)
        except (TypeError, ValueError):
            _pop = 0
        if hw >= 500 and _pop >= 7:
            edge.append(f'大型馬{hw}kg(穴馬で妙味)')

        wd = h.get('weight_diff', 0)
        if wd < -8:
            danger.append(f'馬体重{wd}kg減')
        elif wd > 10:
            danger.append(f'馬体重+{wd}kg増')

        rec_all = h.get('record_all', '')
        if rec_all:
            parts = rec_all.split('-')
            if len(parts) == 4:
                total = sum(int(x) for x in parts)
                wins = int(parts[0])
                if total >= 10 and wins == 0:
                    danger.append('未勝利')

        aim[uma_key] = {
            'edge_reasons': {uma_key: edge} if edge else {},
            'danger_reasons': {uma_key: danger} if danger else {},
            'combo': {},
        }

    forecast = _nar_arare_forecast(scored, horses)

    return {
        'groups': groups,
        'aim': aim,
        'forecast': forecast,
    }


def nar_race_id(date_str, baba_code, race_no):
    """NAR用のrace_idを生成する。形式: NAR{baba_code}{YYYYMMDD}{race_no:02d}"""
    d = date_str.replace('/', '').replace('-', '')
    return f"NAR{int(baba_code):02d}{d}{int(race_no):02d}"


_NP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'newspaper')


def _enrich_nar_view(view):
    """NAR viewにOddsGap/SpurtIdx/LTRを追加する(データがある場合のみ)。"""
    records = view.get('records') or []
    if not records:
        return
    columns = view.get('columns', [])
    labels = view.get('labels', {})
    meta = view.get('meta', {})

    # ── OddsGap(オッズ断層): Odds/Popularityから計算 ──
    try:
        pop_odds = []
        for r in records:
            try:
                p = int(r.get('Popularity') or 0)
                o = float(r.get('Odds') or 0)
            except (TypeError, ValueError):
                p, o = 0, 0
            if p > 0 and o > 0:
                pop_odds.append((p, o, r))
        if len(pop_odds) >= 3:
            pop_odds.sort(key=lambda x: x[0])
            gap_positions = set()
            for i in range(min(5, len(pop_odds) - 1)):
                o_cur, o_nxt = pop_odds[i][1], pop_odds[i + 1][1]
                if o_cur > 0 and o_nxt / o_cur >= 2.0:
                    gap_positions.add(i + 1)
            num_gaps = len(gap_positions)
            for idx, (p, o, r) in enumerate(pop_odds):
                has_gap = idx in gap_positions
                if num_gaps == 0:
                    r['OddsGap'] = '断層なし'
                elif num_gaps >= 2:
                    is_d1 = 1 in gap_positions and 2 in gap_positions
                    is_d2 = 2 in gap_positions and 3 in gap_positions
                    if has_gap:
                        if is_d1 and idx in (1, 2):
                            r['OddsGap'] = '断層D1'
                        elif is_d2 and idx in (2, 3):
                            r['OddsGap'] = '断層D2'
                        else:
                            r['OddsGap'] = '断層D'
                    else:
                        r['OddsGap'] = '-'
                else:
                    if not has_gap:
                        r['OddsGap'] = '-'
                    elif idx == 1:
                        r['OddsGap'] = '断層A'
                    elif idx == 2:
                        r['OddsGap'] = '断層B'
                    elif 3 <= idx <= 5:
                        r['OddsGap'] = '断層C'
                    else:
                        r['OddsGap'] = '-'
            for r in records:
                r.setdefault('OddsGap', '-')
            if 'OddsGap' not in columns:
                _ins = columns.index('Popularity') + 1 if 'Popularity' in columns else len(columns)
                columns.insert(_ins, 'OddsGap')
            labels['OddsGap'] = 'オッズ断層'
    except Exception:
        pass

    # ── SpurtIdx(末脚指数の代理: レース内AvgAgari相対順位) ──
    try:
        agari_map = {}
        for r in records:
            try:
                u = int(r.get('Umaban', 0))
                a = float(r.get('AvgAgari', 0))
                if a > 0:
                    agari_map[u] = a
            except (TypeError, ValueError):
                pass
        if len(agari_map) >= 3:
            sorted_a = sorted(agari_map.items(), key=lambda x: x[1])
            top3 = {u for u, _ in sorted_a[:3]}
            a_mean = sum(agari_map.values()) / len(agari_map)
            for r in records:
                try:
                    u = int(r.get('Umaban', 0))
                except (TypeError, ValueError):
                    continue
                if u in agari_map:
                    dev = a_mean - agari_map[u]
                    prefix = '🔥' if u in top3 else ''
                    r['SpurtIdx'] = f"{prefix}{dev:+.1f}"
                else:
                    r['SpurtIdx'] = '-'
            if 'SpurtIdx' not in columns:
                _ins = columns.index('AvgAgari') if 'AvgAgari' in columns else len(columns)
                columns.insert(_ins, 'SpurtIdx')
            labels['SpurtIdx'] = '末脚指数'
    except Exception:
        pass

    # ── LTR(検証AIスコア): NARモデルが利用可能な場合のみ ──
    try:
        from core import ltr_ranker as _ltr
        if _ltr.available_nar():
            horses = []
            for r in records:
                try:
                    u = int(r.get('Umaban', 0))
                except (TypeError, ValueError):
                    continue
                sa = str(r.get('SexAge', ''))
                sex = sa[:1] if sa and sa[0] in ('牡', '牝', 'セ') else None
                age = None
                try:
                    age = int(re.sub(r'\D', '', sa[1:])) if len(sa) > 1 else None
                except Exception:
                    pass
                bw, zg = None, None
                wt = str(r.get('Weight', ''))
                wm = re.match(r'(\d+)\(([+\-]?\d+)\)', wt)
                if wm:
                    bw, zg = int(wm.group(1)), int(wm.group(2))
                ft = None
                try:
                    ft = float(str(r.get('WeightCarried', '')).replace('kg', ''))
                except Exception:
                    pass
                ni, od = None, None
                try:
                    ni = int(r.get('Popularity') or 0) or None
                except (TypeError, ValueError):
                    pass
                try:
                    od = float(r.get('Odds') or 0) or None
                except (TypeError, ValueError):
                    pass
                horses.append({
                    'umaban': u, 'ketto_num': '',
                    'ninki': ni, 'win_odds': od,
                    'bataiju': bw, 'zogen': zg, 'sex': sex,
                    'age': age, 'futan': ft,
                    'jockey': str(r.get('Jockey', '')),
                })
            ri = {
                'surface': meta.get('surface', ''),
                'kyori': meta.get('distance', 0),
                'field_size': len(records),
                'baba': str(meta.get('condition', '')),
                'is_handicap': False,
                'jyo': str(meta.get('_baba_code', '36')),
                'race_num': str(meta.get('race_no', 0)),
            }
            scores = _ltr.get_scores(horses, ri)
            if scores:
                mx, mn = max(scores.values()), min(scores.values())
                rng = mx - mn if mx != mn else 1
                for r in records:
                    try:
                        u = int(r.get('Umaban', 0))
                    except (TypeError, ValueError):
                        continue
                    s = scores.get(u)
                    r['LTR'] = str(int(round(((s - mn) / rng) * 100))) if s is not None else '-'
                if 'LTR' not in columns:
                    _ins = columns.index('BattleScore') + 1 if 'BattleScore' in columns else len(columns)
                    columns.insert(_ins, 'LTR')
                labels['LTR'] = '検証AI'
    except Exception:
        pass


def save_nar_for_newspaper(entry_data, full=False):
    """NARスクレイパーの出走表データをnewspaper用のview.json+cv.jsonとして保存する。

    full=True: 通常版(過去走フラット展開+父名等の全列)
    full=False: 初心者版(基本列のみ)
    戻り値: race_id (文字列) or None
    """
    if not entry_data:
        return None

    ri = entry_data['race_info']
    rid = nar_race_id(ri['date'], ri['baba_code'], ri['race_no'])
    view = entry_to_full_view(entry_data) if full else entry_to_view(entry_data)
    cv = build_nar_consensus(entry_data)
    if not view:
        return None

    # NAR viewにOddsGap/SpurtIdx/LTRを配線
    view['meta']['_baba_code'] = ri.get('baba_code', '')
    _enrich_nar_view(view)

    os.makedirs(_NP_DIR, exist_ok=True)

    view_data = {
        'race_id': rid,
        'ts': time.time(),
        'meta': view['meta'],
        'sort_label': '',
        'labels': view.get('labels', {}),
        'order': [],
        'columns': view.get('columns', list(view['records'][0].keys()) if view['records'] else []),
        'records': view['records'],
    }
    vp = os.path.join(_NP_DIR, f"{rid}.view.json")
    with open(vp, 'w', encoding='utf-8') as f:
        json.dump(view_data, f, ensure_ascii=False, default=str)

    if cv:
        cp = os.path.join(_NP_DIR, f"{rid}.cv.json")
        with open(cp, 'w', encoding='utf-8') as f:
            json.dump(cv, f, ensure_ascii=False, default=str)

    return rid
