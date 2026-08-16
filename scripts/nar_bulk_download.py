# -*- coding: utf-8 -*-
"""NAR公式サイトから全月次CSVを一括ダウンロードしSQLiteに格納する。

データソース: https://www.keiba.go.jp/KeibaWeb/DataDownload/
- racelist.csv: レース情報（66列・ラップタイム含む）
- horselist.csv: 出馬表+着順結果（36列）
- payback.csv: 払戻金（54列）
- odds.csv: 全券種確定オッズ（10列）※2026年2月〜

形式: UTF-8 BOM付きCSV（ZIP圧縮）
ログイン不要・全15場・1998年1月〜現在
"""
import csv
import io
import os
import sqlite3
import sys
import time
import zipfile
from datetime import datetime

import requests

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'nar_official.db')
MARKER_TABLE = '_download_log'

BASE_URL = 'https://www.keiba.go.jp/KeibaWeb/DataDownload'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.keiba.go.jp/KeibaWeb/MonthlyConveneInfo/MonthlyConveneInfoTop',
}
REQUEST_INTERVAL = 2.0

RACE_START_YEAR, RACE_START_MONTH = 1998, 1
ODDS_START_YEAR, ODDS_START_MONTH = 2026, 2

RACELIST_COLS = [
    'venue', 'race_date', 'race_no', 'post_time', 'grade_name', 'race_name',
    *[f'sub_prize_{i}' for i in range(1, 16)],
    'surface', 'direction', 'distance', 'weather', 'track_condition', 'field_size',
    'conditions', 'prize_1', 'prize_2', 'prize_3', 'prize_4', 'prize_5',
    'last_4f', 'last_3f',
    *[f'lap_{i}' for i in range(1, 16)],
    *[f'corner_name_{i}' for i in range(1, 9)],
    *[f'corner_order_{i}' for i in range(1, 9)],
]

HORSELIST_COLS = [
    'venue', 'race_date', 'race_no', 'post_pos', 'cap_color', 'horse_no',
    'horse_name', 'sex', 'age', 'coat_color', 'birth_date',
    'sire', 'dam', 'broodmare_sire', 'jockey', 'jockey_region',
    'weight_carried', 'jockey_record', 'trainer', 'trainer_region',
    'owner', 'breeder', 'horse_weight', 'weight_diff',
    'total_record', 'dirt_left_record', 'dirt_right_record',
    'venue_record', 'distance_record',
    'best_time', 'best_time_venue', 'finish_pos', 'time_raw', 'margin',
    'last_3f', 'popularity',
]

ODDS_COLS = [
    'venue', 'race_date', 'race_no', 'bet_type', 'num1', 'num2', 'num3',
    'odds', 'odds_max', 'popularity',
]

PAYBACK_COLS = [
    'venue', 'race_date', 'race_no', 'race_name',
    'win_num', 'win_pay', 'win_pop',
    'place_num1', 'place_pay1', 'place_pop1',
    'place_num2', 'place_pay2', 'place_pop2',
    'place_num3', 'place_pay3', 'place_pop3',
    'quinella_num1', 'quinella_num2', 'quinella_pay', 'quinella_pop',
    'exacta_num1', 'exacta_num2', 'exacta_pay', 'exacta_pop',
    'umaren_num1', 'umaren_num2', 'umaren_pay', 'umaren_pop',
    'umatan_num1', 'umatan_num2', 'umatan_pay', 'umatan_pop',
    'wide_num1a', 'wide_num1b', 'wide_pay1', 'wide_pop1',
    'wide_num2a', 'wide_num2b', 'wide_pay2', 'wide_pop2',
    'wide_num3a', 'wide_num3b', 'wide_pay3', 'wide_pop3',
    'trio_num1', 'trio_num2', 'trio_num3', 'trio_pay', 'trio_pop',
    'trifecta_num1', 'trifecta_num2', 'trifecta_num3', 'trifecta_pay', 'trifecta_pop',
]


def init_db(con):
    con.execute('''CREATE TABLE IF NOT EXISTS racelist (
        venue TEXT, race_date TEXT, race_no INTEGER, post_time TEXT,
        grade_name TEXT, race_name TEXT,
        sub_prize_1 TEXT, sub_prize_2 TEXT, sub_prize_3 TEXT, sub_prize_4 TEXT,
        sub_prize_5 TEXT, sub_prize_6 TEXT, sub_prize_7 TEXT, sub_prize_8 TEXT,
        sub_prize_9 TEXT, sub_prize_10 TEXT, sub_prize_11 TEXT, sub_prize_12 TEXT,
        sub_prize_13 TEXT, sub_prize_14 TEXT, sub_prize_15 TEXT,
        surface TEXT, direction TEXT, distance INTEGER,
        weather TEXT, track_condition TEXT, field_size INTEGER, conditions TEXT,
        prize_1 INTEGER, prize_2 INTEGER, prize_3 INTEGER, prize_4 INTEGER, prize_5 INTEGER,
        last_4f REAL, last_3f REAL,
        lap_1 REAL, lap_2 REAL, lap_3 REAL, lap_4 REAL, lap_5 REAL,
        lap_6 REAL, lap_7 REAL, lap_8 REAL, lap_9 REAL, lap_10 REAL,
        lap_11 REAL, lap_12 REAL, lap_13 REAL, lap_14 REAL, lap_15 REAL,
        corner_name_1 TEXT, corner_name_2 TEXT, corner_name_3 TEXT, corner_name_4 TEXT,
        corner_name_5 TEXT, corner_name_6 TEXT, corner_name_7 TEXT, corner_name_8 TEXT,
        corner_order_1 TEXT, corner_order_2 TEXT, corner_order_3 TEXT, corner_order_4 TEXT,
        corner_order_5 TEXT, corner_order_6 TEXT, corner_order_7 TEXT, corner_order_8 TEXT,
        PRIMARY KEY (venue, race_date, race_no)
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS horselist (
        venue TEXT, race_date TEXT, race_no INTEGER,
        post_pos INTEGER, cap_color TEXT, horse_no INTEGER,
        horse_name TEXT, sex TEXT, age INTEGER, coat_color TEXT, birth_date TEXT,
        sire TEXT, dam TEXT, broodmare_sire TEXT,
        jockey TEXT, jockey_region TEXT, weight_carried REAL, jockey_record TEXT,
        trainer TEXT, trainer_region TEXT, owner TEXT, breeder TEXT,
        horse_weight INTEGER, weight_diff INTEGER,
        total_record TEXT, dirt_left_record TEXT, dirt_right_record TEXT,
        venue_record TEXT, distance_record TEXT,
        best_time TEXT, best_time_venue TEXT,
        finish_pos TEXT, time_raw INTEGER, margin TEXT, last_3f REAL, popularity INTEGER,
        PRIMARY KEY (venue, race_date, race_no, horse_no)
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS odds (
        venue TEXT, race_date TEXT, race_no INTEGER,
        bet_type TEXT, num1 INTEGER, num2 INTEGER, num3 INTEGER,
        odds REAL, odds_max REAL, popularity INTEGER
    )''')
    con.execute('''CREATE TABLE IF NOT EXISTS payback (
        venue TEXT, race_date TEXT, race_no INTEGER, race_name TEXT,
        win_num INTEGER, win_pay INTEGER, win_pop INTEGER,
        place_num1 INTEGER, place_pay1 INTEGER, place_pop1 INTEGER,
        place_num2 INTEGER, place_pay2 INTEGER, place_pop2 INTEGER,
        place_num3 INTEGER, place_pay3 INTEGER, place_pop3 INTEGER,
        quinella_num1 INTEGER, quinella_num2 INTEGER, quinella_pay INTEGER, quinella_pop INTEGER,
        exacta_num1 INTEGER, exacta_num2 INTEGER, exacta_pay INTEGER, exacta_pop INTEGER,
        umaren_num1 INTEGER, umaren_num2 INTEGER, umaren_pay INTEGER, umaren_pop INTEGER,
        umatan_num1 INTEGER, umatan_num2 INTEGER, umatan_pay INTEGER, umatan_pop INTEGER,
        wide_num1a INTEGER, wide_num1b INTEGER, wide_pay1 INTEGER, wide_pop1 INTEGER,
        wide_num2a INTEGER, wide_num2b INTEGER, wide_pay2 INTEGER, wide_pop2 INTEGER,
        wide_num3a INTEGER, wide_num3b INTEGER, wide_pay3 INTEGER, wide_pop3 INTEGER,
        trio_num1 INTEGER, trio_num2 INTEGER, trio_num3 INTEGER, trio_pay INTEGER, trio_pop INTEGER,
        trifecta_num1 INTEGER, trifecta_num2 INTEGER, trifecta_num3 INTEGER, trifecta_pay INTEGER, trifecta_pop INTEGER,
        PRIMARY KEY (venue, race_date, race_no)
    )''')
    con.execute(f'''CREATE TABLE IF NOT EXISTS {MARKER_TABLE} (
        ym TEXT, dtype TEXT, downloaded_at TEXT,
        PRIMARY KEY (ym, dtype)
    )''')
    con.execute('CREATE INDEX IF NOT EXISTS idx_horselist_date ON horselist(race_date)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_horselist_horse ON horselist(horse_name)')
    con.execute('CREATE INDEX IF NOT EXISTS idx_odds_date ON odds(race_date, race_no)')
    con.commit()


def is_downloaded(con, ym, dtype):
    r = con.execute(f'SELECT 1 FROM {MARKER_TABLE} WHERE ym=? AND dtype=?', (ym, dtype)).fetchone()
    return r is not None


def mark_downloaded(con, ym, dtype):
    con.execute(f'INSERT OR REPLACE INTO {MARKER_TABLE} (ym, dtype, downloaded_at) VALUES (?,?,?)',
                (ym, dtype, datetime.now().isoformat(timespec='seconds')))
    con.commit()


def read_csv_from_zip(zf, filename):
    with zf.open(filename) as f:
        raw = f.read()
        if raw[:3] == b'\xef\xbb\xbf':
            raw = raw[3:]
        text = raw.decode('utf-8')
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    return list(reader), header


def safe_int(v):
    if v is None or v == '':
        return None
    try:
        return int(v.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def safe_float(v):
    if v is None or v == '':
        return None
    try:
        return float(v.replace(',', ''))
    except (ValueError, AttributeError):
        return None


def insert_racelist(con, rows):
    for row in rows:
        if len(row) < len(RACELIST_COLS):
            row.extend([''] * (len(RACELIST_COLS) - len(row)))
        vals = row[:len(RACELIST_COLS)]
        d = dict(zip(RACELIST_COLS, vals))
        d['race_no'] = safe_int(d['race_no'])
        d['distance'] = safe_int(d['distance'])
        d['field_size'] = safe_int(d['field_size'])
        for k in ['prize_1', 'prize_2', 'prize_3', 'prize_4', 'prize_5']:
            d[k] = safe_int(d[k])
        for k in ['last_4f', 'last_3f'] + [f'lap_{i}' for i in range(1, 16)]:
            d[k] = safe_float(d[k])
        con.execute(
            f'INSERT OR REPLACE INTO racelist ({",".join(RACELIST_COLS)}) '
            f'VALUES ({",".join("?" * len(RACELIST_COLS))})',
            [d[c] for c in RACELIST_COLS])


def insert_horselist(con, rows):
    for row in rows:
        if len(row) < len(HORSELIST_COLS):
            row.extend([''] * (len(HORSELIST_COLS) - len(row)))
        vals = row[:len(HORSELIST_COLS)]
        d = dict(zip(HORSELIST_COLS, vals))
        d['race_no'] = safe_int(d['race_no'])
        d['post_pos'] = safe_int(d['post_pos'])
        d['horse_no'] = safe_int(d['horse_no'])
        d['age'] = safe_int(d['age'])
        d['weight_carried'] = safe_float(d['weight_carried'])
        d['horse_weight'] = safe_int(d['horse_weight'])
        d['weight_diff'] = safe_int(d['weight_diff'])
        d['time_raw'] = safe_int(d['time_raw'])
        d['last_3f'] = safe_float(d['last_3f'])
        d['popularity'] = safe_int(d['popularity'])
        con.execute(
            f'INSERT OR REPLACE INTO horselist ({",".join(HORSELIST_COLS)}) '
            f'VALUES ({",".join("?" * len(HORSELIST_COLS))})',
            [d[c] for c in HORSELIST_COLS])


def insert_odds(con, rows):
    for row in rows:
        if len(row) < len(ODDS_COLS):
            row.extend([''] * (len(ODDS_COLS) - len(row)))
        vals = row[:len(ODDS_COLS)]
        d = dict(zip(ODDS_COLS, vals))
        d['race_no'] = safe_int(d['race_no'])
        d['num1'] = safe_int(d['num1'])
        d['num2'] = safe_int(d['num2'])
        d['num3'] = safe_int(d['num3'])
        d['odds'] = safe_float(d['odds'])
        d['odds_max'] = safe_float(d['odds_max'])
        d['popularity'] = safe_int(d['popularity'])
        con.execute(
            f'INSERT INTO odds ({",".join(ODDS_COLS)}) '
            f'VALUES ({",".join("?" * len(ODDS_COLS))})',
            [d[c] for c in ODDS_COLS])


def insert_payback(con, rows):
    for row in rows:
        if len(row) < len(PAYBACK_COLS):
            row.extend([''] * (len(PAYBACK_COLS) - len(row)))
        vals = row[:len(PAYBACK_COLS)]
        d = dict(zip(PAYBACK_COLS, vals))
        d['race_no'] = safe_int(d['race_no'])
        for k in PAYBACK_COLS:
            if k in ('venue', 'race_date', 'race_name'):
                continue
            if 'num' in k or 'pay' in k or 'pop' in k:
                d[k] = safe_int(d[k])
        con.execute(
            f'INSERT OR REPLACE INTO payback ({",".join(PAYBACK_COLS)}) '
            f'VALUES ({",".join("?" * len(PAYBACK_COLS))})',
            [d[c] for c in PAYBACK_COLS])


def download_month(session, year, month, dtype, max_retries=3):
    if dtype == 'race':
        url = f'{BASE_URL}/RaceDataDownload?type=monthly&k_year={year}&k_month={month}'
    else:
        url = f'{BASE_URL}/OddsDataDownload?type=monthly&k_year={year}&k_month={month}'
    for attempt in range(max_retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=120)
            if r.status_code != 200 or r.content[:4] != b'PK\x03\x04':
                return None
            return zipfile.ZipFile(io.BytesIO(r.content))
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 10
                print(f'RETRY({attempt+1}) in {wait}s ...', end=' ', flush=True)
                time.sleep(wait)
            else:
                print(f'FAILED after {max_retries} retries: {e}')
                return None


def generate_months(start_year, start_month, end_year, end_month):
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    now = datetime.now()
    end_year, end_month = now.year, now.month

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    init_db(con)

    session = requests.Session()

    # Phase 1: Race data (1998/01 ~ now)
    race_months = list(generate_months(RACE_START_YEAR, RACE_START_MONTH, end_year, end_month))
    print(f'=== Phase 1: Race data ({len(race_months)} months) ===')
    for i, (y, m) in enumerate(race_months):
        ym = f'{y:04d}{m:02d}'
        if is_downloaded(con, ym, 'race'):
            continue
        print(f'  [{i+1}/{len(race_months)}] {y}/{m:02d} ...', end=' ', flush=True)
        zf = download_month(session, y, m, 'race')
        if zf is None:
            print('SKIP (no data)')
            continue
        n_race = n_horse = n_pay = 0
        for info in zf.infolist():
            fn = info.filename
            rows, _ = read_csv_from_zip(zf, fn)
            if 'racelist' in fn:
                insert_racelist(con, rows)
                n_race = len(rows)
            elif 'horselist' in fn:
                insert_horselist(con, rows)
                n_horse = len(rows)
            elif 'payback' in fn:
                insert_payback(con, rows)
                n_pay = len(rows)
        con.commit()
        mark_downloaded(con, ym, 'race')
        print(f'{n_race} races, {n_horse} horses, {n_pay} paybacks')
        time.sleep(REQUEST_INTERVAL)

    # Phase 2: Odds data (2026/02 ~ now)
    odds_months = list(generate_months(ODDS_START_YEAR, ODDS_START_MONTH, end_year, end_month))
    print(f'\n=== Phase 2: Odds data ({len(odds_months)} months) ===')
    for i, (y, m) in enumerate(odds_months):
        ym = f'{y:04d}{m:02d}'
        if is_downloaded(con, ym, 'odds'):
            continue
        print(f'  [{i+1}/{len(odds_months)}] {y}/{m:02d} ...', end=' ', flush=True)
        zf = download_month(session, y, m, 'odds')
        if zf is None:
            print('SKIP (no data)')
            continue
        n_odds = 0
        for info in zf.infolist():
            if 'odds' in info.filename:
                rows, _ = read_csv_from_zip(zf, info.filename)
                insert_odds(con, rows)
                n_odds += len(rows)
        con.commit()
        mark_downloaded(con, ym, 'odds')
        print(f'{n_odds:,} odds rows')
        time.sleep(REQUEST_INTERVAL)

    # Summary
    print('\n=== Summary ===')
    for t in ['racelist', 'horselist', 'payback', 'odds']:
        cnt = con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'  {t}: {cnt:,} rows')
    r = con.execute('SELECT MIN(race_date), MAX(race_date) FROM horselist').fetchone()
    print(f'  Date range: {r[0]} ~ {r[1]}')
    print(f'  DB size: {os.path.getsize(DB_PATH) / 1024 / 1024:.1f} MB')
    print(f'  Path: {DB_PATH}')
    con.close()


if __name__ == '__main__':
    main()
