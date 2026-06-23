# -*- coding: utf-8 -*-
"""血統欠損バックフィル — netkeibaの馬血統ページから父・母父を取得しhorsesに補完。
JRA-VANの血統マスタ(UM)が2023-07で凍結し、2024-26デビュー馬の父/母父が欠損している件の対処
([[project_jravan_setup]])。OCR不使用・新ライブラリ不使用=既存 main.get_single_horse_ped
(fetch_robust_html→db.netkeiba.com/horse/ped/{ketto}/ をparse)を再利用。

再開可能: 既にsireのある馬はスキップ。--year/--limit/--sleep で範囲・量・間隔を調整。
大量(数千〜2万頭)になるので --limit で分割 or run_in_background 推奨。

使い方:
    python scripts/backfill_bloodline.py --year 2024 --limit 50   # まず小さく試す
    python scripts/backfill_bloodline.py --year 2024              # 全部(時間がかかる)
"""
import os
import sys
import time
import argparse
import sqlite3

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import get_single_horse_ped

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=2024, help='対象開始年(results.year>=)')
    ap.add_argument('--limit', type=int, default=0, help='今回処理する最大頭数(0=全部)')
    ap.add_argument('--sleep', type=float, default=0.5, help='1頭ごとの基本待機秒(行儀)')
    ap.add_argument('--jitter', type=float, default=0.7, help='待機にランダム上乗せ(秒・ボット検知回避)')
    ap.add_argument('--commit-every', type=int, default=25, dest='commit_every')
    args = ap.parse_args()
    import random

    con = sqlite3.connect(DB, timeout=30)
    cur = con.cursor()
    # 血統欠損の馬(resultsに居てhorsesにsireが無い)を recency 順で
    rows = cur.execute(
        """SELECT r.ketto_num, MAX(r.bamei) AS bamei
           FROM results r LEFT JOIN horses h ON h.ketto_num=r.ketto_num
           WHERE CAST(r.year AS INTEGER) >= ? AND r.ketto_num IS NOT NULL AND r.ketto_num!=''
             AND (h.ketto_num IS NULL OR h.sire IS NULL OR h.sire='')
           GROUP BY r.ketto_num
           ORDER BY MAX(r.year||r.monthday) DESC""", (args.year,)).fetchall()
    total_missing = len(rows)
    if args.limit:
        rows = rows[:args.limit]
    print(f"血統欠損: {total_missing:,}頭 / 今回処理: {len(rows):,}頭 (year>={args.year})", flush=True)

    filled = unknown = err = 0
    t0 = time.time()
    for i, (ketto, bamei) in enumerate(rows, 1):
        try:
            sire, bms = get_single_horse_ped(str(ketto))
        except Exception:
            sire, bms = '不明', '不明'
            err += 1
        if sire and sire not in ('不明', ''):
            cur.execute(
                """INSERT INTO horses (ketto_num, bamei, sire, bms) VALUES (?,?,?,?)
                   ON CONFLICT(ketto_num) DO UPDATE SET sire=excluded.sire, bms=excluded.bms,
                     bamei=COALESCE(NULLIF(horses.bamei,''), excluded.bamei)""",
                (str(ketto), bamei, sire, bms if bms and bms != '不明' else None))
            filled += 1
        else:
            unknown += 1
        if i % args.commit_every == 0:
            con.commit()
            el = time.time() - t0
            print(f"  {i}/{len(rows)} 補完{filled} 不明{unknown} ({el:.0f}s, {i/max(el,1):.1f}頭/s) "
                  f"最新例: {bamei} 父={sire}", flush=True)
        time.sleep(args.sleep + random.uniform(0, args.jitter))
    con.commit()
    nh = cur.execute("SELECT COUNT(*) FROM horses WHERE sire IS NOT NULL AND sire!=''").fetchone()[0]
    con.close()
    print(f"\n=== 完了 補完{filled} / 不明(NAR等で取得不可){unknown} / 例外{err} "
          f"({time.time()-t0:.0f}秒) ===", flush=True)
    print(f"horses 血統あり総数: {nh:,}", flush=True)
    if total_missing > len(rows):
        print(f"残り欠損 {total_missing-len(rows):,}頭。同コマンドを再実行すれば続きから埋めます。", flush=True)


if __name__ == '__main__':
    main()
