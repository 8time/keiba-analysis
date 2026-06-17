# -*- coding: utf-8 -*-
"""
クッション値・ダート含水率CSVを jravan.db の track_cond テーブルに取り込む。

CSV形式: TARGET外部指数形式（ヘッダなし）
  18桁キー,値
  キー = year(4)+monthday(4)+jyo(2)+kai(2)+nichi(2)+race(2)+uma(2)
  同一 year+monthday+jyo では値が同じなので先頭10桁で重複排除。
"""
import os
import sys
import sqlite3

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'jravan.db')

CUSHION_CSV = os.path.join(BASE_DIR, 'data', '20200912~20260614クッション値.csv')
MOISTURE_CSV = os.path.join(BASE_DIR, 'data', '20180728~20260614ダート含水率.csv')

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS track_cond (
    year       TEXT NOT NULL,
    monthday   TEXT NOT NULL,
    jyo        TEXT NOT NULL,
    cushion    REAL,
    dirt_moisture REAL,
    PRIMARY KEY (year, monthday, jyo)
)
"""


def parse_csv(path):
    """18桁キーCSVを読み、{(year,monthday,jyo): value} を返す。"""
    out = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or ',' not in line:
                continue
            key, val = line.split(',', 1)
            if len(key) < 10:
                continue
            try:
                v = float(val)
            except ValueError:
                continue
            year = key[0:4]
            monthday = key[4:8]
            jyo = key[8:10]
            k = (year, monthday, jyo)
            if k not in out:
                out[k] = v
    return out


def main():
    cushion = parse_csv(CUSHION_CSV) if os.path.exists(CUSHION_CSV) else {}
    moisture = parse_csv(MOISTURE_CSV) if os.path.exists(MOISTURE_CSV) else {}
    print(f"クッション値: {len(cushion)} 件（日×場）")
    print(f"ダート含水率: {len(moisture)} 件（日×場）")

    all_keys = set(cushion.keys()) | set(moisture.keys())
    print(f"合計ユニークキー: {len(all_keys)} 件")

    con = sqlite3.connect(DB_PATH)
    con.execute(CREATE_TABLE)

    rows = []
    for k in all_keys:
        year, monthday, jyo = k
        c = cushion.get(k)
        m = moisture.get(k)
        rows.append((year, monthday, jyo, c, m))

    con.executemany(
        "INSERT OR REPLACE INTO track_cond (year, monthday, jyo, cushion, dirt_moisture) "
        "VALUES (?, ?, ?, ?, ?)",
        rows
    )
    con.commit()

    cnt = con.execute("SELECT COUNT(*) FROM track_cond").fetchone()[0]
    c_cnt = con.execute("SELECT COUNT(*) FROM track_cond WHERE cushion IS NOT NULL").fetchone()[0]
    m_cnt = con.execute("SELECT COUNT(*) FROM track_cond WHERE dirt_moisture IS NOT NULL").fetchone()[0]
    both = con.execute("SELECT COUNT(*) FROM track_cond WHERE cushion IS NOT NULL AND dirt_moisture IS NOT NULL").fetchone()[0]
    print(f"\ntrack_cond テーブル: {cnt} 行")
    print(f"  クッション値あり: {c_cnt}")
    print(f"  含水率あり:       {m_cnt}")
    print(f"  両方あり:         {both}")

    sample = con.execute(
        "SELECT * FROM track_cond ORDER BY year DESC, monthday DESC LIMIT 5"
    ).fetchall()
    print("\n最新5件:")
    for r in sample:
        print(f"  {r}")

    con.close()
    print("\n完了。")


if __name__ == '__main__':
    main()
