# -*- coding: utf-8 -*-
"""JRA公式サイト(馬場情報)からクッション値・含水率(芝/ダート)を取得するスクレイパー。

JRA-VANの契約が切れている間の代替データ源(再契約までのブリッジ)。
`https://www.jra.go.jp/keiba/baba/archive/` に掲載される開催ごとの過去データPDF
(クッション値・含水率一覧)をダウンロード・パースする。このPDFには既存の
track_cond テーブル(外部CSV取り込み)には無い芝含水率(ゴール前/4角)も含まれる。

当日速報(9:30発表等)はJRAサイトが実際のレース直前(金〜日)にしか表を出さないため
このモジュールでは対象外。過去データPDFは開催が進むたびに追記される想定。
"""
import io
import re
import urllib.request

from core.scraper import VENUE_NAMES

ARCHIVE_INDEX_URL = 'https://www.jra.go.jp/keiba/baba/archive/'

_TITLE_RE = re.compile(r'(\d{4})年\s*(\d+)回(\S+?)競馬')
_ROW_RE = re.compile(
    r'(?:第\s*(\d+)日\s*)?(\d{1,2})月\s*(\d{1,2})日\s*([月火水木金土日])曜日\s*([A-D])\s*'
    r'(\d{2}:\d{2})\s*([\d.]+)\s*(\d{2}:\d{2})\s*([\d.]+)\s*([\d.]+)\s*([\d.]+)\s*([\d.]+)'
)

_JYO_BY_NAME = {name: code for code, name in VENUE_NAMES.items()}


def list_archive_pdf_urls():
    """アーカイブ一覧ページから、現在公開されている過去データPDFのURL一覧を返す。"""
    from core.scraper import fetch_robust_html
    html = fetch_robust_html(ARCHIVE_INDEX_URL)
    if not html:
        return []
    hrefs = re.findall(r'href="([^"]+\.pdf)"', html)
    urls = set()
    for h in hrefs:
        urls.add('https://www.jra.go.jp' + h if h.startswith('/') else h)
    return sorted(urls)


def download_pdf(url, timeout=20):
    """PDFをバイト列で取得(JRA公式サイトはボット検知が緩いため直接urllibで十分)。"""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_pdf(pdf_bytes):
    """過去データPDF(クッション値・含水率一覧)をパースする。

    戻り値: [{'year','monthday'(MMDD),'jyo','kai','course','cushion_time','cushion',
              'moisture_time','turf_moist_goal','turf_moist_4c',
              'dirt_moist_goal','dirt_moist_4c'}, ...]
    パース不能な行/ページは無視する(壊れたPDFでも部分的に取れた分だけ返す)。
    """
    import pdfplumber
    out = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ''
                out.extend(_parse_page_text(text))
    except Exception:
        return out
    return out


def _parse_page_text(text):
    lines = text.split('\n')
    m_title = None
    for ln in lines[:4]:
        m_title = _TITLE_RE.search(ln)
        if m_title:
            break
    if not m_title:
        return []
    year, kai, venue_ja = m_title.groups()
    jyo = _JYO_BY_NAME.get(venue_ja)
    if not jyo:
        return []
    rows = []
    for ln in lines:
        m = _ROW_RE.match(ln.strip())
        if not m:
            continue
        (_day_no, mm, dd, _wd, course, c_time, c_val, m_time,
         turf_goal, turf_4c, dirt_goal, dirt_4c) = m.groups()
        try:
            monthday = f"{int(mm):02d}{int(dd):02d}"
            rows.append({
                'year': year, 'monthday': monthday, 'jyo': jyo, 'kai': kai,
                'course': course, 'cushion_time': c_time, 'cushion': float(c_val),
                'moisture_time': m_time,
                'turf_moist_goal': float(turf_goal), 'turf_moist_4c': float(turf_4c),
                'dirt_moist_goal': float(dirt_goal), 'dirt_moist_4c': float(dirt_4c),
            })
        except (TypeError, ValueError):
            continue
    return rows


def fetch_all_rows():
    """アーカイブ一覧の全PDFをダウンロード・パースして1つのリストに結合する。
    ネットワークエラーのPDFはスキップして継続する(1件の失敗で全体を止めない)。"""
    all_rows = []
    for url in list_archive_pdf_urls():
        try:
            pdf_bytes = download_pdf(url)
            rows = parse_pdf(pdf_bytes)
            all_rows.extend(rows)
        except Exception:
            continue
    return all_rows


# ─── 当日ライブ取得 ───────────────────────────────────────────
LIVE_URL = 'https://www.jra.go.jp/keiba/baba/'

# JRA場名→場コード
_JYO_BY_NAME_LIVE = {name: code for code, name in VENUE_NAMES.items()}


def fetch_live_track_data():
    """JRA公式の馬場状態ページから当日のクッション値・含水率を取得する。

    戻り値: {場コード: {'cushion': float|None,
                       'turf_moist_goal': float|None, 'turf_moist_4c': float|None,
                       'dirt_moist_goal': float|None, 'dirt_moist_4c': float|None,
                       'weather': str|None, 'turf_cond': str|None, 'dirt_cond': str|None}}
    取得失敗時は空dict。
    """
    from core.scraper import fetch_robust_html
    html = fetch_robust_html(LIVE_URL)
    if not html:
        return {}
    return _parse_live_html(html)


def _parse_live_html(html):
    """JRA馬場状態ページのHTMLを解析してクッション値・含水率を抽出する。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    results = {}

    # ページ上部に場名タブがある(開催中の場のみ表示)
    # 各場のデータは div#contentsBody 内のセクションに格納されている
    # 構造: タブで場を切り替え → 各場のクッション値テーブル+含水率テーブル

    # 天候・馬場状態(良/稍重/重/不良)をまず取得
    _cond_re = re.compile(r'(良|稍重|重|不良)')
    _venue_re = re.compile(
        r'(札幌|函館|福島|新潟|東京|中山|中京|京都|阪神|小倉)')

    # --- 方法1: テーブルからクッション値・含水率を抽出 ---
    text = soup.get_text('\n')
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]

    # 全テキストから場名を特定
    venues_found = set()
    for ln in lines:
        m = _venue_re.search(ln)
        if m:
            venues_found.add(m.group(1))

    # クッション値の抽出: "クッション値" 近辺の数値
    _cushion_val_re = re.compile(r'(\d+\.\d+)')

    # テーブルベースの解析を試みる
    tables = soup.find_all('table')
    for tbl in tables:
        tbl_text = tbl.get_text()

        # クッション値テーブル: ヘッダに「クッション値」→行にフロート値
        if 'クッション' in tbl_text:
            for row in tbl.find_all('tr'):
                cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
                for cell in cells:
                    m = _cushion_val_re.search(cell)
                    if m:
                        try:
                            val = float(m.group(1))
                            if 5.0 <= val <= 15.0:
                                for vn in venues_found:
                                    jyo = _JYO_BY_NAME_LIVE.get(vn)
                                    if jyo and jyo not in results:
                                        results.setdefault(jyo, {})['cushion'] = val
                        except ValueError:
                            pass

        # 含水率テーブル: 芝/ダート × ゴール前/4コーナーの%値
        if '含水率' in tbl_text or 'ゴール' in tbl_text:
            for row in tbl.find_all('tr'):
                cells = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
                if len(cells) >= 3:
                    pcts = []
                    for cell in cells:
                        m = re.search(r'([\d.]+)%?', cell)
                        if m:
                            try:
                                pcts.append(float(m.group(1)))
                            except ValueError:
                                pass
                    if len(pcts) >= 2:
                        row_text = ' '.join(cells)
                        for vn in venues_found:
                            jyo = _JYO_BY_NAME_LIVE.get(vn)
                            if not jyo:
                                continue
                            results.setdefault(jyo, {})
                            if '芝' in row_text and 'ダ' not in row_text:
                                results[jyo]['turf_moist_goal'] = pcts[0]
                                results[jyo]['turf_moist_4c'] = pcts[1]
                            elif 'ダ' in row_text:
                                results[jyo]['dirt_moist_goal'] = pcts[0]
                                results[jyo]['dirt_moist_4c'] = pcts[1]

    # --- 方法2: テーブルが空ならテキストベースの正規表現フォールバック ---
    if not results:
        # クッション値: "9.6" のような単独フロート値を探す
        for i, ln in enumerate(lines):
            if 'クッション' in ln:
                for j in range(max(0, i-2), min(len(lines), i+5)):
                    m = _cushion_val_re.search(lines[j])
                    if m:
                        try:
                            val = float(m.group(1))
                            if 5.0 <= val <= 15.0:
                                for vn in venues_found:
                                    jyo = _JYO_BY_NAME_LIVE.get(vn)
                                    if jyo:
                                        results.setdefault(jyo, {})['cushion'] = val
                                break
                        except ValueError:
                            pass

        # 含水率: "14.3%" のようなパターンを探す
        _moist_re = re.compile(r'([\d.]+)\s*%')
        for i, ln in enumerate(lines):
            if '含水率' in ln or 'ゴール' in ln:
                vals = _moist_re.findall('\n'.join(lines[max(0,i):i+8]))
                float_vals = []
                for v in vals:
                    try:
                        float_vals.append(float(v))
                    except ValueError:
                        pass
                if len(float_vals) >= 4:
                    for vn in venues_found:
                        jyo = _JYO_BY_NAME_LIVE.get(vn)
                        if not jyo:
                            continue
                        results.setdefault(jyo, {})
                        results[jyo]['turf_moist_goal'] = float_vals[0]
                        results[jyo]['turf_moist_4c'] = float_vals[1]
                        results[jyo]['dirt_moist_goal'] = float_vals[2]
                        results[jyo]['dirt_moist_4c'] = float_vals[3]
                    break

    # 天候・馬場状態を付加
    for i, ln in enumerate(lines):
        if '天候' in ln:
            m = re.search(r'天候[：:]?\s*(\S+)', ln)
            if m:
                for jyo in results:
                    results[jyo].setdefault('weather', m.group(1))
        if '芝' in ln:
            m = _cond_re.search(ln)
            if m and '含水' not in ln:
                for jyo in results:
                    results[jyo].setdefault('turf_cond', m.group(1))
        if 'ダート' in ln or 'ダ' in ln:
            m = _cond_re.search(ln)
            if m and '含水' not in ln:
                for jyo in results:
                    results[jyo].setdefault('dirt_cond', m.group(1))

    return results
