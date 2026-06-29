# -*- coding: utf-8 -*-
"""血統欠損バックフィル — netkeibaの馬血統ページから父・母父を取得しhorsesに補完。
JRA-VANの血統マスタ(UM)が2023-07で凍結し、2024-26デビュー馬の父/母父が欠損している件の対処
([[project_jravan_setup]])。OCR不使用・新ライブラリ不使用=既存 main.get_single_horse_ped
(fetch_robust_html→db.netkeiba.com/horse/ped/{ketto}/ をparse)を再利用。

再開可能: 既にsireのある馬はスキップ。--year/--daily-limit/--sleep で範囲・量・間隔を調整。

安全策(IPブロック回避):
  - デフォルト 3〜6秒間隔 (sleep 3 + jitter 3)
  - 1日300頭上限 (--daily-limit)
  - 30頭ごとに60秒の長休み (--batch-pause)
  - 連続不明5件で緊急停止 (--max-streak) ← ブロック検知

使い方:
    python scripts/backfill_bloodline.py --year 2024 --daily-limit 50   # 最初は50頭で様子見
    python scripts/backfill_bloodline.py --year 2024                     # デフォルト300頭/日
    python scripts/backfill_bloodline.py --year 2024 --daily-limit 500 --sleep 2  # やや攻め
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
    ap.add_argument('--daily-limit', type=int, default=300, dest='daily_limit',
                    help='今回処理する最大頭数(1日分・デフォルト300)')
    ap.add_argument('--limit', type=int, default=0, help='旧互換: daily-limitと同等(0=daily-limit)')
    ap.add_argument('--sleep', type=float, default=3.0, help='1頭ごとの基本待機秒')
    ap.add_argument('--jitter', type=float, default=3.0, help='待機にランダム上乗せ(秒)')
    ap.add_argument('--batch-size', type=int, default=30, dest='batch_size',
                    help='N頭ごとに長休み')
    ap.add_argument('--batch-pause', type=float, default=60.0, dest='batch_pause',
                    help='バッチ間の長休み秒')
    ap.add_argument('--max-streak', type=int, default=5, dest='max_streak',
                    help='連続不明N件でブロック疑い緊急停止')
    ap.add_argument('--commit-every', type=int, default=25, dest='commit_every')
    args = ap.parse_args()
    import random

    effective_limit = args.limit if args.limit > 0 else args.daily_limit

    con = sqlite3.connect(DB, timeout=30)
    cur = con.cursor()
    rows = cur.execute(
        """SELECT r.ketto_num, MAX(r.bamei) AS bamei
           FROM results r LEFT JOIN horses h ON h.ketto_num=r.ketto_num
           WHERE CAST(r.year AS INTEGER) >= ? AND r.ketto_num IS NOT NULL AND r.ketto_num!=''
             AND (h.ketto_num IS NULL OR h.sire IS NULL OR h.sire='')
           GROUP BY r.ketto_num
           ORDER BY MAX(r.year||r.monthday) DESC""", (args.year,)).fetchall()
    total_missing = len(rows)
    rows = rows[:effective_limit]
    est_sec = len(rows) * (args.sleep + args.jitter / 2)
    est_min = est_sec / 60
    batch_pauses = (len(rows) // args.batch_size) * args.batch_pause
    est_total = (est_sec + batch_pauses) / 60
    print(f"血統欠損: {total_missing:,}頭 / 今回処理: {len(rows):,}頭 (year>={args.year})", flush=True)
    print(f"推定所要: {est_total:.0f}分 (間隔{args.sleep}〜{args.sleep+args.jitter:.0f}秒 "
          f"+ {args.batch_size}頭ごとに{args.batch_pause:.0f}秒休み)", flush=True)
    print(f"連続不明{args.max_streak}件で緊急停止", flush=True)
    print(flush=True)

    filled = unknown = err = 0
    streak_unknown = 0
    stopped_early = False
    t0 = time.time()

    for i, (ketto, bamei) in enumerate(rows, 1):
        # ketto_num が無効(外国馬等)はスキップ
        if not ketto or ketto == '0000000000' or len(str(ketto)) < 8:
            unknown += 1
            continue

        try:
            sire, bms = get_single_horse_ped(str(ketto))
        except Exception as e:
            sire, bms = '不明', '不明'
            err += 1

        if sire and sire not in ('不明', ''):
            cur.execute(
                """INSERT INTO horses (ketto_num, bamei, sire, bms) VALUES (?,?,?,?)
                   ON CONFLICT(ketto_num) DO UPDATE SET sire=excluded.sire, bms=excluded.bms,
                     bamei=COALESCE(NULLIF(horses.bamei,''), excluded.bamei)""",
                (str(ketto), bamei, sire, bms if bms and bms != '不明' else None))
            filled += 1
            streak_unknown = 0
        else:
            unknown += 1
            streak_unknown += 1
            if streak_unknown >= args.max_streak:
                con.commit()
                print(f"\n🚨 連続不明{streak_unknown}件 — IPブロックの疑い。緊急停止。", flush=True)
                print(f"   時間を空けて再実行してください。", flush=True)
                stopped_early = True
                break

        if i % args.commit_every == 0:
            con.commit()
            el = time.time() - t0
            remaining = len(rows) - i
            eta_sec = (el / i) * remaining if i > 0 else 0
            print(f"  {i}/{len(rows)} 補完{filled} 不明{unknown} "
                  f"({el:.0f}s・残り{eta_sec/60:.0f}分) "
                  f"最新: {bamei} 父={sire}", flush=True)

        # バッチ休み: N頭ごとに長休み
        if i % args.batch_size == 0 and i < len(rows):
            con.commit()
            print(f"  ☕ {args.batch_size}頭完了 — {args.batch_pause:.0f}秒休憩...", flush=True)
            time.sleep(args.batch_pause)
        else:
            time.sleep(args.sleep + random.uniform(0, args.jitter))

    con.commit()
    nh = cur.execute("SELECT COUNT(*) FROM horses WHERE sire IS NOT NULL AND sire!=''").fetchone()[0]
    con.close()
    elapsed = time.time() - t0
    status = "緊急停止" if stopped_early else "完了"
    print(f"\n=== {status} 補完{filled} / 不明{unknown} / 例外{err} "
          f"({elapsed:.0f}秒 = {elapsed/60:.1f}分) ===", flush=True)
    print(f"horses 血統あり総数: {nh:,}", flush=True)
    remaining = total_missing - filled - unknown
    if remaining > 0:
        days_left = remaining / effective_limit
        print(f"残り欠損 約{remaining:,}頭（約{days_left:.0f}日分）。"
              f"翌日以降に同コマンドを再実行すれば続きから埋めます。", flush=True)


if __name__ == '__main__':
    main()
