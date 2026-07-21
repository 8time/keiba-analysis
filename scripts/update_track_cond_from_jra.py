# -*- coding: utf-8 -*-
"""JRA公式サイトの過去データPDF(馬場情報アーカイブ)から track_cond テーブルを更新する。

JRA-VANの契約が切れている間の代替データ源(再契約までのブリッジ)。
既存の cushion/dirt_moisture(TARGET形式CSV取り込み)は保持したまま、
新規カラム(kai/course/cushion_time/moisture_time/turf_moist_goal/turf_moist_4c/
dirt_moist_goal/dirt_moist_4c)を追加・更新する。既存値がNoneの行は
cushion/dirt_moisture もJRA公式PDFの値で補完する(TARGET値を優先し上書きしない)。

実行: python scripts/update_track_cond_from_jra.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jra_baba_scraper as jb  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'jravan.db')

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

_NEW_COLUMNS = [
    ('kai', 'TEXT'), ('course', 'TEXT'), ('cushion_time', 'TEXT'),
    ('moisture_time', 'TEXT'), ('turf_moist_goal', 'REAL'), ('turf_moist_4c', 'REAL'),
    ('dirt_moist_goal', 'REAL'), ('dirt_moist_4c', 'REAL'),
]


def _ensure_schema(con):
    con.execute(CREATE_TABLE)
    existing = {r[1] for r in con.execute("PRAGMA table_info(track_cond)").fetchall()}
    for col, typ in _NEW_COLUMNS:
        if col not in existing:
            con.execute(f"ALTER TABLE track_cond ADD COLUMN {col} {typ}")


def main():
    print("JRA公式サイトの馬場情報アーカイブを取得中...")
    rows = jb.fetch_all_rows()
    print(f"パース済み行数: {len(rows)}")
    if not rows:
        print("取得0件のため終了します(ネットワーク or サイト構造変化を確認してください)。")
        return

    con = sqlite3.connect(DB_PATH)
    _ensure_schema(con)

    inserted = updated = 0
    for r in rows:
        cur = con.execute(
            "SELECT cushion, dirt_moisture FROM track_cond WHERE year=? AND monthday=? AND jyo=?",
            (r['year'], r['monthday'], r['jyo'])
        ).fetchone()
        if cur is None:
            con.execute(
                "INSERT INTO track_cond (year, monthday, jyo, cushion, dirt_moisture, kai, "
                "course, cushion_time, moisture_time, turf_moist_goal, turf_moist_4c, "
                "dirt_moist_goal, dirt_moist_4c) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r['year'], r['monthday'], r['jyo'], r['cushion'], r['dirt_moist_goal'],
                 r['kai'], r['course'], r['cushion_time'], r['moisture_time'],
                 r['turf_moist_goal'], r['turf_moist_4c'], r['dirt_moist_goal'], r['dirt_moist_4c'])
            )
            inserted += 1
        else:
            old_cushion, old_dirt = cur
            con.execute(
                "UPDATE track_cond SET cushion=?, dirt_moisture=?, kai=?, course=?, "
                "cushion_time=?, moisture_time=?, turf_moist_goal=?, turf_moist_4c=?, "
                "dirt_moist_goal=?, dirt_moist_4c=? WHERE year=? AND monthday=? AND jyo=?",
                (old_cushion if old_cushion is not None else r['cushion'],
                 old_dirt if old_dirt is not None else r['dirt_moist_goal'],
                 r['kai'], r['course'], r['cushion_time'], r['moisture_time'],
                 r['turf_moist_goal'], r['turf_moist_4c'], r['dirt_moist_goal'], r['dirt_moist_4c'],
                 r['year'], r['monthday'], r['jyo'])
            )
            updated += 1
    con.commit()

    total = con.execute("SELECT COUNT(*) FROM track_cond").fetchone()[0]
    turf_cnt = con.execute(
        "SELECT COUNT(*) FROM track_cond WHERE turf_moist_goal IS NOT NULL").fetchone()[0]
    latest = con.execute(
        "SELECT year, monthday, jyo, cushion, turf_moist_goal, dirt_moist_goal "
        "FROM track_cond ORDER BY year DESC, monthday DESC LIMIT 5").fetchall()
    con.close()

    print(f"\n新規追加: {inserted}件 / 既存更新: {updated}件")
    print(f"track_cond 総行数: {total}（芝含水率あり: {turf_cnt}）")
    print("\n最新5件:")
    for r in latest:
        print(f"  {r}")


if __name__ == '__main__':
    main()
