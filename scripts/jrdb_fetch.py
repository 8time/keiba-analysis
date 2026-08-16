# -*- coding: utf-8 -*-
"""JRDB会員データの**少量・欠落補充用**ダウンローダ。

⚠️⚠️ 大量取得には使わないこと ⚠️⚠️
  会員規約(https://jrdb.com/terms)を確認した結果:
    ・第8条11項「JRDBの業務を妨げるような行為」を禁止
      → 機械的な一括取得・反復的な大量アクセスは抵触のおそれ
    ・レース当日 08:00〜19:00 は過去データDLをサーバ負荷対策として制限
    ・第5条: 個人利用限定。複製・頒布・公開・第三者提供は一切禁止
  「大量取得が許可されている」根拠は見当たらなかった。

**過去データが欲しい場合は必ず公式の「バックナンバー」を使う。**
  年単位の1ファイル（例: TYB_2025.zip）で配布されており、
  16年分でも16リクエストで済む。日別に109ファイル叩く理由は無い。
  本スクリプトは「バックナンバーに未収録の直近日を数件補う」用途に限る。

安全弁（既定で有効）:
  ・レース当日 08:00〜19:00 は実行を拒否（規約の制限時間帯に合わせる）
  ・1回あたり最大 --max-files 件（既定8件）まで
  ・1リクエスト3秒待ち・並列化なし

URL構造:
  Zip : https://jrdb.com/member/datazip/{Fld}/{YYYY}/{CODE}{YYMMDD}.zip
  Lzh : https://jrdb.com/member/data/{Fld}/{CODE}{YYMMDD}.lzh
  {Fld} は種別コードの頭大文字＋以降小文字（SED→Sed / TYB→Tyb）

認証: 環境変数 JRDB_USER / JRDB_PASS、または data/jrdb/.credentials
      （data/jrdb/ は .gitignore 済み。コードに書かないこと）

Usage:
  python scripts/jrdb_fetch.py --code TYB --from 20260801 --to 20260809 --dry-run
"""
import os
import sys
import io
import time
import argparse
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import requests

from core import jockey_jv as jj

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

RAW_DIR = os.path.join(ROOT, 'data', 'jrdb', 'raw')
CRED = os.path.join(ROOT, 'data', 'jrdb', '.credentials')
BASE = 'https://jrdb.com/member'
SLEEP = 3.0          # 規約に配慮して長めに取る
MAX_FILES = 8        # 1回の実行で取る上限（大量取得の抑止）


def creds():
    u, p = os.environ.get('JRDB_USER'), os.environ.get('JRDB_PASS')
    if u and p:
        return u, p
    if os.path.exists(CRED):
        lines = [l.strip() for l in open(CRED, encoding='utf-8') if l.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    raise SystemExit(
        '認証情報がありません。次のどちらかを用意してください:\n'
        '  ① 環境変数 JRDB_USER / JRDB_PASS\n'
        f'  ② {CRED} に1行目=ID / 2行目=パスワード\n'
        '  （data/jrdb/ は .gitignore 済みです）')


def race_days(d_from, d_to):
    """jravan.db から実際の開催日を引く。無ければ全日付を返す。"""
    try:
        con = sqlite3.connect(f'file:{jj.JV_DB_PATH}?mode=ro', uri=True)
        # JRDBは中央競馬のみ。jyo<='10'がJRA10場（地方を含めると開催日が
        # ほぼ毎日になり、404を大量に叩くことになる）
        rows = con.execute(
            "SELECT DISTINCT year||monthday FROM races "
            "WHERE year||monthday BETWEEN ? AND ? AND jyo<='10' ORDER BY 1",
            (d_from, d_to)).fetchall()
        con.close()
        days = [r[0] for r in rows if r[0]]
        if days:
            return days
    except Exception:
        pass
    # フォールバック: 全日付
    from datetime import date, timedelta
    a = date(int(d_from[:4]), int(d_from[4:6]), int(d_from[6:]))
    b = date(int(d_to[:4]), int(d_to[4:6]), int(d_to[6:]))
    out, cur = [], a
    while cur <= b:
        out.append(cur.strftime('%Y%m%d'))
        cur += timedelta(days=1)
    return out


# ⚠フォルダ名とファイル名が一致しない種別がある（JOA→Joフォルダ / OW→Ozフォルダ）。
#   既定は「頭大文字+以降小文字」だが、合わないものはここで対応づける。
FOLDER_OVERRIDE = {'JOA': 'Jo', 'OW': 'Oz'}


def urls_for(code, day, folder=None):
    """(zip_url, lzh_url) を返す。day は YYYYMMDD。"""
    fld = folder or FOLDER_OVERRIDE.get(code.upper())         or (code[0].upper() + code[1:].lower())
    yy = day[2:]                       # YYMMDD
    return (f'{BASE}/datazip/{fld}/{day[:4]}/{code.upper()}{yy}.zip',
            f'{BASE}/data/{fld}/{code.upper()}{yy}.lzh')


def show_index(url):
    """会員ページの索引を1回だけ取得してリンクを一覧表示する（探索用）。

    どこに何年分のファイルがあるかを知るための単発リクエスト。
    ダウンロードではないので件数制限の対象外だが、連打しないこと。
    """
    import re as _re
    from urllib.parse import urljoin
    user, pw = creds()
    r = requests.get(url, auth=(user, pw), timeout=30,
                     headers={'User-Agent': 'keiba-analysis/1.0 (personal member use)'})
    if r.status_code == 401:
        raise SystemExit('認証に失敗しました(401)。ID/パスワードを確認してください。')
    if r.status_code != 200:
        raise SystemExit(f'HTTP {r.status_code}: {url}')
    html = r.content.decode('cp932', errors='replace')
    links = _re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, _re.I)
    seen, out = set(), []
    for h in links:
        if h.startswith(('#', 'javascript:', 'mailto:')):
            continue
        full = urljoin(url, h)
        if full not in seen:
            seen.add(full)
            out.append(full)
    print(f'■ {url}\n  リンク {len(out)}件\n')
    for h in out:
        print('  ' + h)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--index-url', help='会員ページの索引URLを1回だけ取得して中身を表示')
    ap.add_argument('--code', help='TYB / SED / SKB / KYI / CYB など')
    ap.add_argument('--folder', help='サーバ側フォルダ名がコードと違う場合に指定')
    ap.add_argument('--from', dest='d_from')
    ap.add_argument('--to', dest='d_to')
    ap.add_argument('--year', type=int, help='--from/--to の代わりに年で指定')
    ap.add_argument('--dry-run', action='store_true', help='URLを表示するだけ')
    ap.add_argument('--sleep', type=float, default=SLEEP)
    ap.add_argument('--max-files', type=int, default=MAX_FILES,
                    help=f'1回の実行で取る上限（既定{MAX_FILES}件）')
    ap.add_argument('--allow-lzh', action='store_true',
                    help='zipが無い時にlzhも取る（別途解凍ツールが必要）')
    a = ap.parse_args()

    if a.index_url:
        show_index(a.index_url)
        return
    if not a.code:
        raise SystemExit('--code か --index-url を指定してください。')

    if a.year:
        a.d_from, a.d_to = f'{a.year}0101', f'{a.year}1231'
    if not (a.d_from and a.d_to):
        raise SystemExit('--from/--to か --year を指定してください。')

    days = race_days(a.d_from, a.d_to)
    print(f'■ {a.code.upper()}  {a.d_from}〜{a.d_to}  開催日 {len(days)}日')

    # ── 安全弁① 件数 ──────────────────────────────
    # 大量取得は会員規約 第8条11項(業務妨害)に抵触するおそれ。
    # 過去分は必ず公式の「バックナンバー」(年1ファイル)を使うこと。
    if len(days) > a.max_files:
        print(f'\n🚫 対象が {len(days)}件 で上限 {a.max_files}件 を超えています。')
        print('   JRDBの会員規約は「業務を妨げる行為」を禁じており、')
        print('   機械的な一括取得は抵触のおそれがあります。')
        print('\n   ▶ 過去データは**公式の「バックナンバー」**を使ってください。')
        print('     年単位の1ファイルで配布されています（例: TYB_2025.zip）。')
        print('     16年分でも16回のダウンロードで済み、サーバ負荷も最小です。')
        print(f'\n   どうしても必要な数日だけなら --from/--to を狭めるか '
              f'--max-files で明示してください。')
        raise SystemExit(2)

    # ── 安全弁② 時間帯 ────────────────────────────
    # JRDBは「レース当日 08:00〜19:00 は過去データDLを制限」と明記している。
    # 開催日の日中は走らせない。
    from datetime import datetime as _dt
    now = _dt.now()
    today = now.strftime('%Y%m%d')
    if (not a.dry_run) and today in race_days(today, today) and 8 <= now.hour < 19:
        print(f'\n🚫 本日({today})は開催日で、現在 {now.hour}時 です。')
        print('   JRDBは開催日 08:00〜19:00 の過去データDLを制限しています。')
        print('   19時以降か非開催日に実行してください。')
        raise SystemExit(2)

    os.makedirs(RAW_DIR, exist_ok=True)

    if a.dry_run:
        for d in days[:5]:
            z, l = urls_for(a.code, d, a.folder)
            print(f'  {z}')
        if len(days) > 5:
            print(f'  ... 他 {len(days)-5} 件')
        print('\n※ --dry-run なので取得はしていません。')
        return

    user, pw = creds()
    s = requests.Session()
    s.auth = (user, pw)
    s.headers['User-Agent'] = 'keiba-analysis/1.0 (personal member use)'

    got = skip = miss = err = 0
    for i, d in enumerate(days, 1):
        zurl, lurl = urls_for(a.code, d, a.folder)
        for url, ext in ([(zurl, 'zip')] + ([(lurl, 'lzh')] if a.allow_lzh else [])):
            out = os.path.join(RAW_DIR, os.path.basename(url))
            if os.path.exists(out) and os.path.getsize(out) > 0:
                skip += 1
                break
            try:
                r = s.get(url, timeout=30)
            except Exception as e:
                print(f'  [{i}/{len(days)}] {d} 通信エラー: {e}')
                err += 1
                break
            if r.status_code == 200 and r.content[:2] in (b'PK', b'-l'):
                with open(out, 'wb') as f:
                    f.write(r.content)
                got += 1
                print(f'  [{i}/{len(days)}] {os.path.basename(out)} '
                      f'{len(r.content):,}バイト')
                break
            elif r.status_code == 401:
                raise SystemExit('認証に失敗しました(401)。ID/パスワードを確認してください。')
            elif r.status_code == 404:
                continue
            else:
                print(f'  [{i}/{len(days)}] {d} HTTP {r.status_code}')
                err += 1
                break
        else:
            miss += 1
        time.sleep(a.sleep)

    print(f'\n取得 {got} / 既存スキップ {skip} / 見つからず {miss} / エラー {err}')
    print(f'保存先: {RAW_DIR}')
    if got:
        print(f'次: python scripts/jrdb_read.py {a.code.upper()}')


if __name__ == '__main__':
    main()
