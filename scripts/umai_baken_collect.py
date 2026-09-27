# -*- coding: utf-8 -*-
"""ウマい馬券の買い目『形』を少量だけ集める。

大量巡回はしない。同じURLはキャッシュ済みならネットに行かない。
ブロックっぽい応答が1回でも出たら止まる。

例:
  python scripts/umai_baken_collect.py --html-file saved_list.html
  python scripts/umai_baken_collect.py --race-id 202606040206 --max-details 5
  python scripts/umai_baken_collect.py --summarize
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import umai_baken as ub


def _read_html(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _ingest_detail(race_id, yoso_id, html):
    parsed = ub.parse_detail_tickets(html)
    rec = ub.shape_record(race_id, yoso_id, parsed)
    ub.append_index(rec)
    return rec


def main():
    ap = argparse.ArgumentParser(description='ウマい馬券の買い目形を少量収集')
    ap.add_argument('--race-id', action='append', default=[],
                    help='12桁race_id。指定したレースの一覧だけ取る')
    ap.add_argument('--detail-id', action='append', default=[],
                    help='予想詳細の数字id（?id=）')
    ap.add_argument('--html-file', action='append', default=[],
                    help='ブラウザで保存した一覧/詳細HTML（通信ゼロ）')
    ap.add_argument('--max-details', type=int, default=5,
                    help='この実行で取る詳細の上限（既定5）')
    ap.add_argument('--interval', type=float, default=ub.REQUEST_INTERVAL,
                    help='リクエスト間隔秒（既定12）')
    ap.add_argument('--no-fetch', action='store_true',
                    help='ネットに行かない。キャッシュと --html-file だけ')
    ap.add_argument('--summarize', action='store_true',
                    help='これまでに集めた形を集計して終わる')
    args = ap.parse_args()

    if args.summarize and not (args.race_id or args.detail_id or args.html_file):
        rows = ub.load_index()
        print(json.dumps(ub.summarize(rows), ensure_ascii=False, indent=2))
        return 0

    fetched_details = 0
    new_rows = []

    for path in args.html_file:
        html = _read_html(path)
        ids = ub.extract_yoso_ids(html)
        parsed = ub.parse_detail_tickets(html)
        if parsed.get('tickets'):
            yid = ids[0] if ids else os.path.basename(path)
            rec = _ingest_detail('', yid, html)
            new_rows.append(rec)
            print(f'[html] {path} → {rec["shape_label"]} / {rec["app_near"]}')
            continue
        print(f'[html] {path} 一覧候補 id={len(ids)}件')
        for yid in ids:
            if fetched_details >= args.max_details:
                break
            cached = ub.load_cache('detail', yid)
            if cached:
                rec = _ingest_detail('', yid, cached)
                new_rows.append(rec)
                print(f'[cache] {yid} → {rec["shape_label"]}')
                continue
            if args.no_fetch:
                continue
            html_d = ub.fetch_detail_html(yid, interval=args.interval)
            if not html_d:
                print('停止:', ub.stopped())
                break
            rec = _ingest_detail('', yid, html_d)
            new_rows.append(rec)
            fetched_details += 1
            print(f'[net] {yid} → {rec["shape_label"]} / {rec["app_near"]}')

    for rid in args.race_id:
        html = ub.load_cache('list', rid)
        if not html and not args.no_fetch:
            html = ub.fetch_list_html(rid, interval=args.interval, use_cache=False)
        if not html:
            print(f'一覧取れず race_id={rid} {ub.stopped() or ""}')
            continue
        ids = ub.extract_yoso_ids(html)
        print(f'[list] {rid} 予想id={len(ids)}件')
        if not ids:
            print('  一覧に詳細リンクが無い（JS描画の可能性）。'
                  'ブラウザで「予想をみる」のページを保存して --html-file を使ってください。')
        for yid in ids:
            if fetched_details >= args.max_details:
                print(f'上限 --max-details {args.max_details} に達したので打ち切り')
                break
            cached = ub.load_cache('detail', yid)
            if cached:
                rec = _ingest_detail(rid, yid, cached)
                new_rows.append(rec)
                print(f'[cache] {rid}/{yid} → {rec["shape_label"]}')
                continue
            if args.no_fetch:
                continue
            html_d = ub.fetch_detail_html(yid, race_id=rid, interval=args.interval)
            if not html_d:
                print('停止:', ub.stopped())
                break
            rec = _ingest_detail(rid, yid, html_d)
            new_rows.append(rec)
            fetched_details += 1
            print(f'[net] {rid}/{yid} → {rec["shape_label"]} / {rec["app_near"]}')

    for yid in args.detail_id:
        if fetched_details >= args.max_details:
            break
        cached = ub.load_cache('detail', yid)
        html = cached
        if not html and not args.no_fetch:
            html = ub.fetch_detail_html(yid, interval=args.interval, use_cache=False)
            if html:
                fetched_details += 1
        if not html:
            print(f'詳細取れず id={yid} {ub.stopped() or ""}')
            continue
        rec = _ingest_detail('', yid, html)
        new_rows.append(rec)
        print(f'{"[cache]" if cached else "[net]"} {yid} → {rec["shape_label"]} / {rec["app_near"]}')

    if new_rows:
        print('--- 今回 ---')
        print(json.dumps(ub.summarize(new_rows), ensure_ascii=False, indent=2))
    print('--- 累計 ---')
    print(json.dumps(ub.summarize(ub.load_index()), ensure_ascii=False, indent=2))
    if ub.stopped():
        print('ブロック疑いのため停止:', ub.stopped())
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
