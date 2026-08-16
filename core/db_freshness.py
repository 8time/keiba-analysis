# -*- coding: utf-8 -*-
"""jravan.db の鮮度を判定して「更新時期です」を出すための小さなモジュール。

なぜ必要か:
  jravan.db はJRA-VANの契約が切れると更新が止まる。止まっても
  アプリのライブ表示（netkeibaスクレイプ）は動き続けるので**気づけない**。
  一方で補正T・血統/騎手統計・バックテストは jravan.db 由来なので静かに劣化する。

しきい値の根拠（実測・2024-2026のJRA 98,760件の出走間隔）:
  出走間隔の中央値は36日、平均53日。
  「DBがN日古い」とき、その間に走った馬＝**直近走が欠ける馬**の割合は:
    7日 2.1% / 14日 13.2% / 21日 29.4% / 28日 42.0% /
    35日 49.0% / 42日 54.5% / 49日 60.0% / 90日 85.1%
  → 3週間で3割、1ヶ月で4割が欠ける。ここを段階のしきい値にする。

⚠ライブ表示（今日の出馬表・過去5走）はnetkeibaから取るので**この欠損の影響を受けない**。
  効くのは補正T・統計・検証。パニックする必要はないが、放置すると
  [[verified_corrected_time]]（荒れ時z10.4の最強シグナル）の質が落ちる。
"""
import os
import sqlite3
from datetime import datetime, date

_HERE = os.path.dirname(os.path.abspath(__file__))
_DB = os.path.join(_HERE, '..', 'data', 'jravan.db')

# (日数の下限, レベル, 絵文字, 見出し)
LEVELS = [
    (0,  'fresh',  '🟢', '最新です'),
    (14, 'ok',     '🟢', 'まだ大丈夫'),
    (21, 'notice', '🟡', 'そろそろ更新時期'),
    (28, 'warn',   '🟠', '※更新時期です'),
    (49, 'stale',  '🔴', '※要更新（かなり古い）'),
]

# 実測: DBがN日古いとき「直近走が欠ける馬」の割合
_MISSING_CURVE = [(7, 2.1), (14, 13.2), (21, 29.4), (28, 42.0), (35, 49.0),
                  (42, 54.5), (49, 60.0), (60, 67.0), (90, 85.1), (120, 93.2)]


def missing_share(days):
    """DBがdays日古いとき、直近走が欠ける出走馬の割合(%)を実測カーブから引く。"""
    if days is None or days <= 0:
        return 0.0
    lo = _MISSING_CURVE[0]
    for pt in _MISSING_CURVE:
        if days <= pt[0]:
            if pt is _MISSING_CURVE[0]:
                return round(days / pt[0] * pt[1], 1)
            # 線形補間
            x0, y0 = lo
            x1, y1 = pt
            return round(y0 + (y1 - y0) * (days - x0) / (x1 - x0), 1)
        lo = pt
    return 95.0


def latest_day(db_path=None):
    """jravan.db の最新レース日(YYYYMMDD)。読めなければ None。"""
    p = db_path or _DB
    if not os.path.exists(p):
        return None
    try:
        con = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        r = con.execute('SELECT MAX(year||monthday) FROM races').fetchone()
        con.close()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def status(db_path=None, today=None):
    """鮮度の判定結果を返す。

    戻り値: {'ok':bool, 'latest':'YYYYMMDD', 'days':int, 'level':str,
             'emoji':str, 'title':str, 'missing':float, 'msg':str}
    DBが読めない場合は ok=False で理由を返す。
    """
    d = latest_day(db_path)
    if not d or len(str(d)) != 8:
        return {'ok': False, 'latest': None, 'days': None, 'level': 'unknown',
                'emoji': '⚪', 'title': 'DBを確認できません', 'missing': None,
                'msg': 'data/jravan.db が見つからないか読めません。'}
    try:
        last = date(int(d[:4]), int(d[4:6]), int(d[6:]))
    except ValueError:
        return {'ok': False, 'latest': d, 'days': None, 'level': 'unknown',
                'emoji': '⚪', 'title': '日付を解釈できません', 'missing': None,
                'msg': f'最新日付が不正です: {d}'}
    now = today or datetime.now().date()
    days = (now - last).days
    lv = LEVELS[0]
    for x in LEVELS:
        if days >= x[0]:
            lv = x
    miss = missing_share(days)
    return {'ok': True, 'latest': d, 'days': days, 'level': lv[1],
            'emoji': lv[2], 'title': lv[3], 'missing': miss,
            'msg': (f'競馬データは {d[:4]}/{d[4:6]}/{d[6:]} まで入っています'
                    f'（{days}日前）。'
                    + (f'いま出走する馬の約{miss:.0f}%で「前走の記録」が'
                       'まだ入っていない計算です。' if miss >= 15 else ''))}


def should_warn(db_path=None, today=None):
    """左メニューに出すべきか（🟡以上）。"""
    s = status(db_path, today)
    return s['level'] in ('notice', 'warn', 'stale', 'unknown')


def how_to_update():
    """更新手順の案内文（初心者向けに平易に）。"""
    return (
        "**JRA-VANの契約があるとき**（いちばん確実・数分で終わります）\n\n"
        "PowerShellで次を実行してください。`--from` は"
        "「この日以降を取り込む」という意味です。\n\n"
        "```\n"
        "C:\\Users\\kimnhaty\\pythonx86-312\\tools\\python.exe "
        "scripts\\jvlink_ingest.py --from {FROM}000000 --option 1\n"
        "```\n\n"
        "※`--option 1` は差分だけ取る指定です。全部入れ直す`--option 4`は"
        "数時間かかるので、普段は使いません。\n"
        "※32bit版のPythonでないとJV-Linkが動きません（上のパスがそれです）。"
    )
