# -*- coding: utf-8 -*-
"""📰 日付指定バッチ解析→新聞発行 — scripts/batch_sra_publish.py

指定日の全レース(またはIDを直接指定)を、実際に動いている
`streamlit run app.py` に対してPlaywrightでブラウザ自動化し、
🏠Single Race Analysis / 🧹消去フィルターの既存UIコードパスを
そのまま走らせて新聞スナップショット(data/newspaper/*.json)を生成する。
最後に --publish を付けるとPDF/HTML新聞をまとめて発行する。

事前準備: 別ターミナルで `streamlit run app.py` を起動しておくこと
(このスクリプトはStreamlitサーバの自動起動はしない)。

Usage:
    python scripts/batch_sra_publish.py --date 20260802
    python scripts/batch_sra_publish.py --date 20260802 --venues 東京,中山
    python scripts/batch_sra_publish.py --race-ids 202605020211,202605020212
    python scripts/batch_sra_publish.py --date 20260802 --publish
    python scripts/batch_sra_publish.py --date 20260802 --no-headless  # 動作確認用
"""
import sys
import os
import io
import argparse
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import batch_analyze as _ba  # noqa: E402


def _log(f, msg):
    print(msg)
    if f:
        f.write(msg + '\n')
        f.flush()


def main():
    ap = argparse.ArgumentParser(description="日付指定バッチ解析→新聞発行")
    ap.add_argument('--date', default=None, help='YYYYMMDD (省略時は今日)')
    ap.add_argument('--race-ids', default=None,
                    help='カンマ区切りのレースID指定(指定時は--dateの一覧取得を使わない)')
    ap.add_argument('--venues', default=None, help='カンマ区切りの開催場名フィルタ(例: 東京,中山)')
    ap.add_argument('--url', default='http://localhost:8501', help='StreamlitサーバのURL')
    ap.add_argument('--skip-existing', dest='skip_existing', action='store_true', default=True)
    ap.add_argument('--no-skip-existing', dest='skip_existing', action='store_false')
    ap.add_argument('--headless', dest='headless', action='store_true', default=True)
    ap.add_argument('--no-headless', dest='headless', action='store_false')
    ap.add_argument('--sra-only', action='store_true',
                    help='🧹消去フィルター段階を飛ばす(✅/🛟/🧹バッジは付かない)')
    ap.add_argument('--with-signal', dest='with_signal', action='store_true', default=True,
                    help='🔬当日シグナル(J◎/T◎/T●)も取得する(既定ON・その日の初回だけ走る)')
    ap.add_argument('--no-signal', dest='with_signal', action='store_false')
    ap.add_argument('--publish', action='store_true', help='解析後に新聞PDF/HTMLも発行する')
    ap.add_argument('--timeout-sra', type=int, default=180)
    ap.add_argument('--timeout-elim', type=int, default=90)
    args = ap.parse_args()

    date_str = args.date or time.strftime('%Y%m%d')
    venues = [v.strip() for v in args.venues.split(',')] if args.venues else None
    race_ids_override = ([r.strip() for r in args.race_ids.split(',') if r.strip()]
                         if args.race_ids else None)

    if not _ba.check_streamlit_alive(args.url):
        print(f"❌ {args.url} に接続できません。")
        print("   先に別ターミナルで `streamlit run app.py` を起動してください"
              "(このスクリプトはサーバを自動起動しません)。")
        sys.exit(2)

    os.makedirs(_ba.ISSUES_DIR, exist_ok=True)
    log_path = os.path.join(_ba.ISSUES_DIR, f"{date_str}_batch.log")
    logf = open(log_path, 'a', encoding='utf-8')

    _log(logf, f"=== バッチ解析開始 date={date_str} url={args.url} "
               f"headless={args.headless} skip_existing={args.skip_existing} ===")

    # UI(📰新聞発行ページ)が進捗を読むためのステータスファイル
    _status = {
        'date': date_str, 'pid': os.getpid(), 'state': 'running',
        'started_ts': time.time(), 'updated_ts': time.time(),
        'i': 0, 'n': 0, 'current': None, 'lines': [],
        'ok': 0, 'skipped': 0, 'failed': 0,
        'publish': None, 'error': None, 'log_path': log_path,
    }
    _ba.write_status(_status)

    def _on_progress(i, n, race_id, result):
        status = result['status']
        icon = {'ok': '✅', 'skipped': '⏭', 'timeout': '⏱', 'failed': '❌'}.get(status, '?')
        elapsed = result.get('elapsed_s', 0.0)
        err = f" err={result['error']}" if result.get('error') else ''
        line = f"[{i}/{n}] {race_id}: {icon}{status}({elapsed}s){err}"
        _log(logf, line)
        _status.update({'i': i, 'n': n, 'current': race_id,
                        'updated_ts': time.time()})
        _status['lines'] = (_status['lines'] + [line])[-40:]
        if status == 'ok':
            _status['ok'] += 1
        elif status == 'skipped':
            _status['skipped'] += 1
        else:
            _status['failed'] += 1
        _ba.write_status(_status)

    try:
        summary = _ba.run_batch(
            date_str, race_ids_override=race_ids_override, venues=venues,
            base_url=args.url, skip_existing=args.skip_existing, headless=args.headless,
            sra_only=args.sra_only, timeout_sra=args.timeout_sra,
            timeout_elim=args.timeout_elim, on_progress=_on_progress,
            with_signal=args.with_signal)

        _log(logf, f"=== 完了: ✅{summary['ok']} / ⏭{summary['skipped']} / "
                   f"❌{summary['failed']} (全{len(summary['targets'])}件) ===")
        failed_rows = [r for r in summary['results'] if r['status'] not in ('ok', 'skipped')]
        if failed_rows:
            _log(logf, "--- 失敗/タイムアウト詳細 ---")
            for r in failed_rows:
                _log(logf, f"  {r['race_id']}: {r['status']} {r.get('error') or ''}")

        if args.publish:
            ok_ids = [r['race_id'] for r in summary['results'] if r['status'] == 'ok']
            skipped_ids = [r['race_id'] for r in summary['results'] if r['status'] == 'skipped']
            publish_ids = ok_ids + skipped_ids
            if not publish_ids:
                _log(logf, "⚠ 発行対象レースがありません(全レース失敗)。")
            else:
                _log(logf, f"📰 新聞発行中... ({len(publish_ids)}R)")
                _status.update({'state': 'publishing', 'updated_ts': time.time()})
                _ba.write_status(_status)
                venue_suffix = '_' + venues[0] if venues and len(venues) == 1 else '_ALL'
                out = _ba.publish_newspaper(publish_ids,
                                            title_suffix=f"_{date_str}{venue_suffix}")
                if out:
                    _log(logf, f"✅ 発行完了: {out['n']}R収録")
                    _log(logf, f"   PDF: {out['pdf_path']}")
                    _log(logf, f"   HTML: {out['html_path']}")
                    _status['publish'] = out
                else:
                    _log(logf, "❌ 新聞発行に失敗しました(収録可能なレースがありません)。")
        _status.update({'state': 'done', 'updated_ts': time.time()})
        _ba.write_status(_status)
    except Exception as e:
        _log(logf, f"❌ バッチが異常終了しました: {type(e).__name__}: {e}")
        _status.update({'state': 'error', 'error': f"{type(e).__name__}: {e}",
                        'updated_ts': time.time()})
        _ba.write_status(_status)
        raise
    finally:
        logf.close()


if __name__ == '__main__':
    main()
