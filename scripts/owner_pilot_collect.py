# -*- coding: utf-8 -*-
"""馬主/生産者パイロット収集 ―― カード4(④馬主特徴)の第0ステップ。

netkeiba horse_id == jravan ketto_num(確認済)を利用し、各馬の馬主ID/生産者IDを
db.netkeiba.com/horse/{id}/ から1回だけ取得(=馬主は馬ごとほぼ静的)。キャッシュ・
resumable・0.5s間隔(アクセス配慮)。fetch_robust_html必須(ボット検知回避)。

対象: JRA(jyo 01-10) 2023-2025 で走ったユニーク馬のうち出走数上位CAP頭(活動馬=馬主
レコードが密)。取得後は scripts/owner_roi_backtest.py で馬主の"過去"成績を逐次計算
(リーク無し)→複勝残差z/ROIを検証する。1フェッチで生産者も取れるので生産牧場仮説も同時可。
"""
import os
import sys
import io
import re
import time
import json
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from core.scraper import fetch_robust_html  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
CACHE = 'scripts/debug/owner_cache.json'
CAP = 4000
SLEEP = 0.5


def horse_set():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    rows = con.execute("""
        SELECT r.ketto_num, COUNT(*) c
        FROM results r JOIN races ra ON ra.race_key=r.race_key
        WHERE ra.jyo BETWEEN '01' AND '10' AND ra.year BETWEEN 2023 AND 2025
          AND r.chakujun>0 AND r.ketto_num IS NOT NULL
        GROUP BY r.ketto_num ORDER BY c DESC LIMIT ?""", (CAP,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def parse_owner(hid):
    html = fetch_robust_html(f'https://db.netkeiba.com/horse/{hid}/')
    if not html:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    out = {'owner_id': '', 'owner_name': '', 'breeder_id': '', 'breeder_name': ''}
    for th in soup.find_all('th'):
        lab = th.get_text(strip=True)
        if lab not in ('馬主', '生産者'):
            continue
        td = th.find_next_sibling('td')
        if not td:
            continue
        name = td.get_text(strip=True)
        a = td.find('a')
        oid = ''
        if a and a.get('href'):
            m = re.search(r'/(owner|breeder)/(\w+)', a['href'])
            if m:
                oid = m.group(2)
        if lab == '馬主':
            out['owner_id'], out['owner_name'] = oid, name
        else:
            out['breeder_id'], out['breeder_name'] = oid, name
    return out


def main():
    horses = horse_set()
    print(f'対象 {len(horses)} 頭 (JRA 2023-25 出走上位)')
    cache = {}
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            cache = json.load(f)
        print(f'  resume: {len(cache)} 頭キャッシュ済')
    todo = [h for h in horses if h not in cache]
    print(f'  残り {len(todo)} 頭 (推定 {len(todo)*(SLEEP+0.6)/60:.0f}分)')

    ok = fail = 0
    for i, hid in enumerate(todo):
        try:
            o = parse_owner(hid)
            if o and o.get('owner_id'):
                cache[hid] = o
                ok += 1
            else:
                cache[hid] = o or {}
                fail += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print(f'  err {hid}: {e}')
        time.sleep(SLEEP)
        if (i + 1) % 100 == 0:
            print(f'  [{i+1}/{len(todo)}] ok={ok} fail={fail}')
            with open(CACHE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False)

    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    withowner = sum(1 for v in cache.values() if v.get('owner_id'))
    print(f'\n完了: {len(cache)}頭キャッシュ / 馬主ID有り {withowner}頭')
    # 馬主別頭数トップ(密度確認)
    from collections import Counter
    oc = Counter(v['owner_id'] for v in cache.values() if v.get('owner_id'))
    print('馬主別頭数トップ10:')
    for oid, c in oc.most_common(10):
        nm = next((v['owner_name'] for v in cache.values() if v.get('owner_id') == oid), '')
        print(f'  {oid} {nm}: {c}頭')


if __name__ == '__main__':
    main()
