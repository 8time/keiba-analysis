# -*- coding: utf-8 -*-
"""JRDBの**仕様書**(公開ドキュメント)を data/jrdb/spec/ に取得する。

仕様書は会員限定のデータ本体とは別で、公開されている技術ドキュメント。
1本あたり数KB・全部で十数本しかないので、これはまとめて取ってよい。
（データ本体の一括取得は規約上NG。scripts/jrdb_fetch.py の注意書き参照）

URLパターン: https://jrdb.com/program/{Fld}/{name}_doc.txt
  {Fld} は種別コードの頭大文字＋以降小文字（SED→Sed / TYB→Tyb）
  ファイル名は種別により揺れる（sed_doc / hjcdata_doc / secsoku_doc / Cs_doc1 …）
  → 公開ページで確認できた分は確定URL、それ以外は候補を順に試す。

Usage:
  python scripts/jrdb_fetch_specs.py --dry-run
  python scripts/jrdb_fetch_specs.py
"""
import os
import sys
import io
import time
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SPEC_DIR = os.path.join(ROOT, 'data', 'jrdb', 'spec')
BASE = 'https://jrdb.com/program'
SLEEP = 2.0

# (説明, フォルダ, [試すファイル名...])
# 前半＝公開ページで href を確認できた確定分 / 後半＝命名規則からの候補
TARGETS = [
    ('SED 成績データ',            'Sed', ['sed_doc.txt', 'sedsiyo_doc.txt']),
    ('SKB 成績拡張データ',        'Skb', ['skb_doc.txt', 'skbsiyo_doc.txt']),
    ('KYI 競走馬データ',          'Kyi', ['kyi_doc.txt', 'kyisiyo_doc.txt']),
    ('TYB 直前情報データ',        'Tyb', ['tyb_doc.txt']),
    ('HJC 払戻情報データ',        'Hjc', ['hjcdata_doc.txt', 'hjc_doc.txt']),
    ('KTA 登録馬データ',          'Kta', ['kta_doc.txt']),
    ('SEC 成績速報データ',        'Sec', ['secsoku_doc.txt', 'sec_doc.txt']),
    ('MSA 抹消馬データ',          'Msa', ['msa_doc.txt']),
    ('CSA/CZA 調教師データ',      'Cs',  ['Cs_doc1.txt', 'cs_doc1.txt']),
    ('KSA/KZA 騎手データ',        'Ks',  ['Ks_doc1.txt', 'ks_doc1.txt']),
    # ↓ 命名規則からの推測（無ければスキップされる）
    ('CYB 調教分析データ',        'Cyb', ['cyb_doc.txt', 'cybsiyo_doc.txt']),
    ('CHA 調教本追切データ',      'Cha', ['cha_doc.txt']),
    # ⚠命名が不規則。OWは"Ow"フォルダが存在せず**Ozフォルダ配下**、OVだけ小文字始まり。
    #   ファイル名も data_doc / siyo_doc が混在する。
    ('OZ 基準オッズ(単複連)',     'Oz',  ['Ozdata_doc.txt']),
    ('OZ 基準オッズ 説明',        'Oz',  ['Ozsiyo_doc.txt']),
    ('OW ワイド基準オッズ',       'Oz',  ['Owdata_doc.txt']),
    ('OU 馬単基準オッズ',         'Ou',  ['Oudata_doc.txt']),
    ('OT 3連複基準オッズ',        'Ot',  ['Otdata_doc.txt']),
    ('OV 3連単基準オッズ',        'Ov',  ['ovdata_doc.txt']),
    ('JO 情報データ',             'Jo',  ['Jodata_doc2.txt']),
    ('JO CID/LS指数 説明',        'Jo',  ['Josiyo_doc.txt']),
    ('UKC 馬基本データ',          'Ukc', ['ukc_doc.txt']),
    ('KKA 競走馬拡張データ',      'Kka', ['kka_doc.txt']),
    ('BAC 番組データ',            'Bac', ['bac_doc.txt']),
    ('KAB 開催データ',            'Kab', ['kab_doc.txt']),
    ('ZED 前走データ',            'Zed', ['zed_doc.txt']),
    ('ZKB 前走拡張データ',        'Zkb', ['zkb_doc.txt']),
    ('SRB 成績レースデータ',      'Srb', ['srb_doc.txt']),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--sleep', type=float, default=SLEEP)
    a = ap.parse_args()

    os.makedirs(SPEC_DIR, exist_ok=True)
    if a.dry_run:
        print(f'■ 取得を試すURL（{len(TARGETS)}種別）')
        for desc, fld, names in TARGETS:
            print(f'  {desc:24s} {BASE}/{fld}/{names[0]}')
        return

    s = requests.Session()
    s.headers['User-Agent'] = 'keiba-analysis/1.0 (personal, reading public docs)'

    got = skip = miss = 0
    print(f'■ JRDB仕様書を取得（{len(TARGETS)}種別・1本{a.sleep}秒間隔）\n')
    for desc, fld, names in TARGETS:
        done = False
        for nm in names:
            out = os.path.join(SPEC_DIR, nm)
            if os.path.exists(out) and os.path.getsize(out) > 0:
                print(f'  {desc:24s} 既存 {nm}')
                skip += 1
                done = True
                break
            url = f'{BASE}/{fld}/{nm}'
            try:
                r = s.get(url, timeout=20)
            except Exception as e:
                print(f'  {desc:24s} 通信エラー {e}')
                break
            time.sleep(a.sleep)
            # 仕様書はテキスト。HTMLのエラーページを掴んでいないか確認する
            if r.status_code == 200 and b'<html' not in r.content[:400].lower():
                with open(out, 'wb') as f:
                    f.write(r.content)
                print(f'  {desc:24s} 取得 {nm} ({len(r.content):,}バイト)')
                got += 1
                done = True
                break
        if not done:
            print(f'  {desc:24s} 見つからず（URL名が違う可能性）')
            miss += 1

    print(f'\n取得 {got} / 既存 {skip} / 見つからず {miss}')
    print(f'保存先: {SPEC_DIR}')
    print('\n次: python scripts/jrdb_spec.py            # 一覧')
    print('    python scripts/jrdb_spec.py --grep 不利  # 横断検索')


if __name__ == '__main__':
    main()
