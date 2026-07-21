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
