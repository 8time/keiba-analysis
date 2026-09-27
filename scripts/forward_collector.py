# -*- coding: utf-8 -*-
"""Shadow research collector. Does not buy tickets.

Examples:
  python scripts/forward_collector.py --status
  python scripts/forward_collector.py --synthetic

Do not register this with Windows Task Scheduler from the script.
A person can run --status on a race day, then record snapshots through
research.forward.automation.ForwardStore. Live scraping is not started here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from datetime import datetime

from research.forward.automation import FORWARD_V1, ForwardStore, run_synthetic
from research.forward.live_ingest import JST, NetkeibaSource, status_view, tick

DIR = os.path.join(ROOT, 'data', 'research', 'forward')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--synthetic', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--diagnose-live', action='store_true')
    args = parser.parse_args()
    if args.diagnose_live:
        source = NetkeibaSource()
        rows = source.discover(datetime.now(JST))
        resolved = [r for r in rows if r.get('post_at')]
        missing = [r for r in rows if not r.get('post_at')]
        nxt = sorted(resolved, key=lambda r: r['post_at'])
        print(json.dumps({
            'requested_date': datetime.now(JST).strftime('%Y%m%d'),
            'raw_race_count': len(rows),
            'resolved_start_times': len(resolved),
            'missing_start_times': len(missing),
            'next_race': nxt[0] if nxt else None,
            'source': 'race_list_sub.RaceList_Itemtime',
            'purchase_path': False,
        }, ensure_ascii=False, indent=2))
        return
    if args.live:
        import time
        store = ForwardStore(DIR)
        source = NetkeibaSource()
        while True:
            now = datetime.now(JST)
            report = tick(store, source, now, dry_run=args.dry_run)
            print(json.dumps({'tick': report, 'status': status_view(store, now)}, ensure_ascii=False, default=str))
            if args.once or args.dry_run:
                return
            time.sleep(180)
    if args.synthetic:
        path = os.path.join(DIR, 'synthetic_v1')
        print(json.dumps({'schema': FORWARD_V1, **run_synthetic(path)}, ensure_ascii=False))
        return
    store = ForwardStore(DIR)
    waiting = store.resume_waiting()
    print(json.dumps({
        'schema': FORWARD_V1,
        'status': 'LIVE_INGESTION_READY',
        'summary': store.summary(),
        'live': status_view(store, datetime.now(JST)),
        'waiting': waiting,
        'purchase_path': False,
        'scheduler_registered': False,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
