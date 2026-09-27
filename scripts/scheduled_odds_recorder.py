# -*- coding: utf-8 -*-
"""オッズ自動記録 常駐ランナー — scripts/scheduled_odds_recorder.py

Race Scannerで保存した記録プラン(data/odds_record_plan.json)を読み、予定時刻になったら
複数レースの単複人気オッズを自動記録する。**PCが起動していればアプリを閉じても動く**。

使い方:
  python scripts/scheduled_odds_recorder.py            # プランを見張って常駐(30秒間隔)
  python scripts/scheduled_odds_recorder.py --once     # 今記録すべき枠だけ処理して終了
  START_odds_recorder.bat をダブルクリックでも起動可(同じ)。

動作:
  ・30秒ごとにプランを読み直し(アプリでプランを更新しても即反映)。
  ・予定時刻を過ぎ、かつ猶予(25分)以内の未記録枠を記録→プランにdone印。
  ・全枠が done/stale になったら待機継続(その日の追加プランに備える)。Ctrl+Cで終了。
出力: data/odds_history.db の odds_logs(時系列追記・phase列に時点ラベル付き)。
"""
import os
import sys
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8')
    except Exception:
        pass
from core import odds_schedule as osch


def _log(msg):
    print(f'[{datetime.now().strftime("%m/%d %H:%M:%S")}] {msg}', flush=True)


def process_due(once_note=''):
    """今記録すべき枠を処理。戻り値: 処理した枠数。"""
    plan = osch.load_plan()
    # 注: 共通times が空でも各レース個別times(発走N分前予約)があれば記録対象。
    #     旧ガード `not plan.get('times')` は個別times形式のプランを握り潰すバグだった。
    if not plan.get('races'):
        return 0
    due = osch.due_slots(plan)
    n = 0
    for rid, hhmm, label in due:
        phase = osch.slot_phase(plan, rid, hhmm)  # 15分前/直前/最終 等の時点ラベル
        cnt = osch.record_one(rid, phase=phase)
        if cnt > 0:
            osch.mark_done(plan, rid, hhmm, cnt)
            osch.save_plan(plan)
            _log(f'✅ 記録 {label}({rid}) {hhmm}枠[{phase or "-"}] → {cnt}頭')
            n += 1
        else:
            _log(f'⚠ 取得失敗 {label}({rid}) {hhmm}枠(発売前/終了/通信) — 猶予内で再試行')
        time.sleep(1)  # API連打防止
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true', help='今すぐ記録すべき枠だけ処理して終了')
    ap.add_argument('--interval', type=int, default=30, help='見張り間隔(秒・既定30)')
    args = ap.parse_args()

    if args.once:
        n = process_due()
        _log(f'--once: {n}枠を記録して終了')
        return

    _log('オッズ自動記録ランナー起動。プラン=' + osch.PLAN_PATH)
    _log('Race Scannerで予約を保存すると自動で拾います。終了はCtrl+C。')
    last_summary = None
    try:
        while True:
            osch.touch_heartbeat()   # アプリ側の🟢ランナー稼働中表示用
            process_due()
            plan = osch.load_plan()
            st = osch.plan_status(plan)
            summary = (st['total'], st['done'], st['pending'], st['missed'])
            if summary != last_summary:
                _log(f'進捗: 全{st["total"]}枠 / 記録済{st["done"]} / 待機{st["pending"]}'
                     f' / 見送り{st["missed"]}' + (f' / 次={st["next"]}' if st['next'] else ''))
                last_summary = summary
            time.sleep(max(5, args.interval))
    except KeyboardInterrupt:
        _log('終了しました。')


if __name__ == '__main__':
    main()
