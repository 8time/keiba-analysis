# -*- coding: utf-8 -*-
"""オッズ自動記録の予約プラン — core/odds_schedule.py

Race Scannerで組んだ『複数レース×複数時間帯』の記録予約をディスクに保存し、
常駐ランナー(scripts/scheduled_odds_recorder.py)が予定時刻にオッズを記録する。

設計: Streamlitはページを開いている間しか動かないため、記録の実体は常駐ランナー
(PCが起動していればアプリを閉じても動く)に持たせる。本モジュールは
  ・プランの読み書き(data/odds_record_plan.json)
  ・『今この瞬間に記録すべき(race, 時刻)』の判定
  ・1レース分のオッズ記録(既存 OddsFetcher/OddsLogger を再利用)
の純ロジックのみを提供する(UIにもランナーにも依存しない=smokeで検証可能)。

プラン形式:
  {
    "date": "20260712",              # 記録対象日(全レース同日・レース跨ぎは別プラン)
    "times": ["08:40", "12:00", ...],# 記録する時刻(HH:MM・全レース共通)
    "night_times": ["22:00"],        # 【前日夜】に記録する時刻(HH:MM・全レース共通・任意)
    "races": [{"race_id": "...", "label": "東京11R", "times": ["15:20"]}, ...],
    "records": {"<race_id>|<HH:MM>": {"done": true, "at": "ISO", "n": 頭数}}
  }
各レースの実効記録時刻 = 全レース共通 times ∪ そのレース個別 times。
個別 times は『発走15分前』のようにレースごとに発走時刻が違う枠を入れるため
(スキャナーのレース一覧から1クリックで予約する導線がUI側にある)。

night_times は date の【前日】の時刻として扱う(例: date=20260713, "22:00"
→ 7/12 22:00 に記録)。「前日夜に人気が高かった馬が当日どんどん売れずに
オッズ断層へ寄っていく=売れてない実力馬」というドリフト仮説(未検証)を
将来自前データで検証するための記録枠。recordsのキーは "<race_id>|前日<HH:MM>"。
"""
import os
import json
from datetime import datetime, timedelta

PLAN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'odds_record_plan.json')
HEARTBEAT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'odds_runner_heartbeat.txt')

# 記録が遅れて起動した時の猶予(分)。予定時刻からこの範囲内なら『今すぐ記録(catch-up)』、
# 超えていたら stale としてスキップ扱いにする(何時間も後に古い枠を記録しないため)。
GRACE_MIN = 25

# 本線の記録枠。発走前の5点(15/10/5分前・直前・最終)を毎回貯めるのが本体。
# これで「直前でオッズ急落」「朝一人気からの置き去り」等の時点別俗説が後日検証できる。
RECOMMENDED = [
    ('前日22:00', '前日夜', '前日の夜。夜→当日のドリフト(人気の移り変わり)観察の起点'),
    ('08:40', '朝一', '午前8時40分。大衆票が入る前の基準値'),
    ('発走15分前', '15分前', '投票が固まり始めたあと。朝一との比較の本線'),
    ('発走10分前', '10分前', 'パドック終わりで大勢が投票済み'),
    ('発走5分前', '5分前', '締切間際。直前急落の検出に必要'),
    ('発走1分前', '直前', '締切直前の実質オッズ'),
    ('発走3分後', '最終', '締切後の確定オッズ(発走後でもオッズは確定済みで取れる)'),
]
OPTIONAL = [
    ('12:00', '中間', '正午ごろ。想定人気との比較用（任意）'),
    ('発走30分前', '30分前', 'パドック直前。おおよその投票が固まり始める（任意）'),
]
DEFAULT_CLOCK_TIMES = ['08:40']
# 発走時刻からのオフセット(分)。負=発走後(最終オッズ=締切で確定するので発走3分後に取る)。
PREPOST_MINUTES = (15, 10, 5, 1, -3)

# DBのphase列に入れる時点ラベル(平仮名表記に統一・分析時のgroupbyキー)
PHASES = ('前日夜', '朝一', '中間', '30分前', '15分前', '10分前', '5分前', '直前', '最終')

NIGHT_PREFIX = '前日'   # 前日夜枠のスロット表記/recordsキーの接頭辞(例: '前日22:00')


def _norm_hhmm(s):
    """'8:40'/'0840'/'08：40' → '08:40'。不正は None。"""
    s = str(s or '').strip().replace('：', ':').replace('.', ':')
    if ':' not in s and s.isdigit() and len(s) in (3, 4):
        s = s.zfill(4)
        s = s[:2] + ':' + s[2:]
    try:
        h, m = s.split(':')
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f'{h:02d}:{m:02d}'
    except (ValueError, AttributeError):
        pass
    return None


def load_plan(path=PLAN_PATH):
    if not os.path.exists(path):
        return {'date': '', 'times': [], 'races': [], 'records': {}}
    try:
        with open(path, encoding='utf-8') as f:
            p = json.load(f)
    except Exception:
        return {'date': '', 'times': [], 'races': [], 'records': {}}
    p.setdefault('records', {})
    p.setdefault('times', [])
    p.setdefault('night_times', [])
    p.setdefault('races', [])
    p.setdefault('date', '')
    return p


def _norm_times(seq):
    """時刻リストを正規化+重複排除+ソート。"""
    out = []
    for t in seq or []:
        n = _norm_hhmm(t)
        if n and n not in out:
            out.append(n)
    return sorted(out)


def save_plan(plan, path=PLAN_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # 全レース共通の時刻を正規化
    plan['times'] = _norm_times(plan.get('times', []))
    plan['night_times'] = _norm_times(plan.get('night_times', []))
    # レース個別の時刻も正規化(空は落とさず保持=UIの並びを壊さない)
    for r in plan.get('races', []):
        if 'times' in r:
            r['times'] = _norm_times(r.get('times', []))
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)
    return plan


def minus_minutes(hhmm, mins):
    """'15:35',15 → '15:20'。発走N分前の時計時刻を返す。不正は ''。"""
    n = _norm_hhmm(hhmm)
    if not n:
        return ''
    base = datetime.strptime(n, '%H:%M') - timedelta(minutes=int(mins))
    return base.strftime('%H:%M')


def prepost_hhmm(post_hhmm, minutes=None):
    """発走時刻から N分前の時計時刻リスト（既定=15分前と10分前）。不正は空。"""
    out = []
    for m in list(minutes or PREPOST_MINUTES):
        t = minus_minutes(post_hhmm, m)
        if t and t not in out:
            out.append(t)
    return out


def attach_prepost_times(plan, post_by_rid, minutes=None, labels_by_rid=None):
    """各レースに発走N分前の個別枠を足す。戻り値: (plan, 新規追加した枠の数)。

    発走時刻(post)もレースエントリに保持する。常駐ランナーが記録する時点で
    『15分前/直前/最終』等のフェーズ名を復元してDBのphase列に入れるため。"""
    n = 0
    labels_by_rid = labels_by_rid or {}
    for rid, post in (post_by_rid or {}).items():
        rid = str(rid)
        label = labels_by_rid.get(rid) or rid
        before = set(race_times(plan, rid))
        for t in prepost_hhmm(post, minutes):
            plan, added = add_race_time(plan, rid, label, t)
            if added and added not in before:
                n += 1
                before.add(added)
        pn = _norm_hhmm(post)
        if pn:
            entry = next((r for r in plan.get('races', []) if str(r.get('race_id')) == rid), None)
            if entry is not None:
                entry['post'] = pn
    return plan, n


def race_times(plan, race_id):
    """このレースの実効記録時刻(全レース共通 ∪ 個別)をソートで返す。"""
    rid = str(race_id)
    entry = next((r for r in plan.get('races', []) if str(r.get('race_id')) == rid), None)
    per = entry.get('times', []) if entry else []
    return _norm_times(list(plan.get('times', [])) + list(per))


def add_race_time(plan, race_id, label, hhmm):
    """指定レースに個別記録時刻を追加(共通timesとは別のこのレース専用枠)。

    レースがプラン未登録なら追加する(常駐ランナーが記録対象として拾えるように)。
    戻り値: (plan, 追加した正規化時刻 or None)。
    """
    n = _norm_hhmm(hhmm)
    if not n:
        return plan, None
    rid = str(race_id)
    races = plan.setdefault('races', [])
    entry = next((r for r in races if str(r.get('race_id')) == rid), None)
    if entry is None:
        entry = {'race_id': rid, 'label': label or rid, 'times': []}
        races.append(entry)
    if label and not entry.get('label'):
        entry['label'] = label
    per = entry.setdefault('times', [])
    if n not in per:
        per.append(n)
        entry['times'] = sorted(per)
    return plan, n


def remove_race_time(plan, race_id, hhmm):
    """指定レースの個別記録時刻を1つ削除(共通timesは触らない)。"""
    n = _norm_hhmm(hhmm)
    rid = str(race_id)
    for r in plan.get('races', []):
        if str(r.get('race_id')) == rid and n in (r.get('times') or []):
            r['times'].remove(n)
    return plan


def _slot_dt(date_str, hhmm):
    """('20260712','08:40') → datetime。失敗時 None。"""
    try:
        return datetime.strptime(f'{date_str} {hhmm}', '%Y%m%d %H:%M')
    except (ValueError, TypeError):
        return None


def _iter_slots(plan, race_id):
    """このレースの全スロット (slot_token, 予定datetime) を返す。

    当日枠: token='08:40' → date 08:40。
    前日夜枠: token='前日22:00' → date の前日 22:00(ドリフト観察の起点・任意)。
    recordsのキーは f'{race_id}|{token}' で、当日枠とは自然に衝突しない。
    """
    date_str = plan.get('date', '')
    for t in race_times(plan, race_id):
        yield t, _slot_dt(date_str, t)
    for t in _norm_times(plan.get('night_times', [])):
        sdt = _slot_dt(date_str, t)
        yield f'{NIGHT_PREFIX}{t}', (sdt - timedelta(days=1) if sdt else None)


def due_slots(plan, now=None, grace_min=GRACE_MIN):
    """今この瞬間に記録すべき (race_id, hhmm, label) のリストを返す。

    条件: 予定時刻 <= now < 予定時刻+grace かつ未記録。grace超過は stale=記録しない。
    now未満(未来)の枠は当然まだ記録しない。
    """
    now = now or datetime.now()
    out = []
    recs = plan.get('records', {})
    for r in plan.get('races', []):
        rid = str(r.get('race_id', ''))
        if not rid:
            continue
        for t, sdt in _iter_slots(plan, rid):  # 共通 ∪ 個別 ∪ 前日夜
            key = f'{rid}|{t}'
            if recs.get(key, {}).get('done'):
                continue
            if sdt is None:
                continue
            if sdt <= now < sdt + timedelta(minutes=grace_min):
                out.append((rid, t, r.get('label', rid)))
    return out


def mark_done(plan, race_id, hhmm, n_records, at=None):
    plan.setdefault('records', {})[f'{race_id}|{hhmm}'] = {
        'done': True, 'at': (at or datetime.now()).isoformat(timespec='seconds'), 'n': int(n_records)}
    return plan


def classify_phase(min_to_post, slot_hhmm=None):
    """発走までの分数 → 時点ラベル。負=発走後。発走が不明な遠い枠は時計時刻で判断。

    帯: 発走後(<= -1)=最終 / 0-2分前=直前 / 3-7=5分前 / 8-12=10分前 / 13-20=15分前 /
    21-45=30分前。それより遠い当日枠は時計で 朝一(<9:30) / 中間(それ以外)。
    """
    if min_to_post is not None:
        if min_to_post <= -1:
            return '最終'
        if min_to_post <= 2:
            return '直前'
        if min_to_post <= 7:
            return '5分前'
        if min_to_post <= 12:
            return '10分前'
        if min_to_post <= 20:
            return '15分前'
        if min_to_post <= 45:
            return '30分前'
    if slot_hhmm:
        return '朝一' if slot_hhmm < '09:30' else '中間'
    return None


def _race_entry(plan, race_id):
    return next((r for r in plan.get('races', []) if str(r.get('race_id')) == str(race_id)), None)


def slot_phase(plan, race_id, token):
    """予約スロット(token='15:20'/'前日22:00')の時点ラベルを返す。

    レースエントリに保持した発走時刻(post)との差で判定。
    postが無い旧プランは時計時刻の決め打ち(08:40=朝一 等)にフォールバック。"""
    if str(token).startswith(NIGHT_PREFIX):
        return '前日夜'
    entry = _race_entry(plan, race_id)
    post = _norm_hhmm((entry or {}).get('post'))
    tok = _norm_hhmm(token)
    if post and tok and plan.get('date'):
        pdt = _slot_dt(plan['date'], post)
        sdt = _slot_dt(plan['date'], tok)
        if pdt and sdt:
            return classify_phase((pdt - sdt).total_seconds() / 60.0, tok)
    if tok:
        return classify_phase(None, tok)
    return None


def current_phase(plan, race_id, now=None):
    """手動『今すぐ記録』用: 現在時刻と発走時刻から時点ラベルを推定。発走不明なら'手動'。"""
    now = now or datetime.now()
    entry = _race_entry(plan, race_id)
    post = _norm_hhmm((entry or {}).get('post'))
    date_str = plan.get('date', '')
    pdt = _slot_dt(date_str, post) if (post and date_str) else None
    if pdt and pdt.date() == now.date():
        return classify_phase((pdt - now).total_seconds() / 60.0) or '手動'
    return '手動'


def plan_status(plan, now=None):
    """プランの進捗サマリー {'total','done','pending','missed','next'} を返す(UI表示用)。"""
    now = now or datetime.now()
    total = done = missed = pending = 0
    next_dt = None
    recs = plan.get('records', {})
    for r in plan.get('races', []):
        rid = str(r.get('race_id', ''))
        for t, sdt in _iter_slots(plan, rid):  # 共通 ∪ 個別 ∪ 前日夜
            total += 1
            if recs.get(f'{rid}|{t}', {}).get('done'):
                done += 1
                continue
            if sdt is None:
                continue
            if sdt + timedelta(minutes=GRACE_MIN) <= now:
                missed += 1
            else:
                pending += 1
                if next_dt is None or sdt < next_dt:
                    next_dt = sdt
    return {'total': total, 'done': done, 'pending': pending, 'missed': missed,
            'next': next_dt.strftime('%m/%d %H:%M') if next_dt else None}


def touch_heartbeat(path=HEARTBEAT_PATH):
    """常駐ランナーの生存印(ループ毎に更新)。アプリの🟢稼働中表示が読む。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(datetime.now().isoformat(timespec='seconds'))
    except Exception:
        pass


def runner_alive(max_age_s=90, path=HEARTBEAT_PATH):
    """常駐ランナーが動いているか(ハートビートがmax_age_s以内)。"""
    try:
        return (datetime.now().timestamp() - os.path.getmtime(path)) <= max_age_s
    except Exception:
        return False


def record_one(race_id, base_dir='data', phase=None):
    """1レースの単複人気オッズをスナップショット記録。戻り値: 記録件数(0=失敗)。

    保存先は OddsTracker のSQLite(data/odds_history.db)＝SRAの
    『📈 時系列オッズ・詳細分析』が読む同一DBに統一。これにより予約記録・手動記録・
    SRA内の📥記録がすべて同じ時系列に溜まり、記録内容がSRAにそのまま表示される。
    (スクレイピングをOCRに置換しない方針は維持=OddsTrackerもnetkeiba API取得)。

    phase: '15分前'/'直前'/'最終' 等の時点ラベル(slot_phase/current_phaseで決める)。
           DBのphase列に入り、後日『直前で急落』等の時点別集計ができる。"""
    try:
        from core.odds_tracker import OddsTracker
        return int(OddsTracker().track(str(race_id), phase=phase) or 0)
    except Exception:
        return 0
