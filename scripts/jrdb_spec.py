# -*- coding: utf-8 -*-
"""JRDBの仕様書(.txt)を読んで、固定長レイアウトを自動抽出する。

なぜ作るか:
  JRDBは20種類以上のデータ形式(SED/KYI/TYB/CYB/OZ/JO/UKC...)を出しており、
  各々に「項目名/OCC/BYTE/TYPE/相対位置」を書いた仕様書テキストが付いている。
  これを手でコード化すると膨大かつ間違える(実際TYBで6文字ズレを踏んだ)。
  **仕様書そのものをパースしてレイアウトを作れば、全形式を自動で読める。**

仕様書の行フォーマット（例: tyb_doc.txt）:
    項目名          OCC     BYTE    TYPE    相対    備考
    　　場コード            2       99      1
    ＩＤＭ                  5       ZZ9.9   11      前日情報と同じ
  OCCは省略されることが多い。そこで**末尾から** 相対→TYPE→BYTE→(OCC) の順に読む。

⚠バイト位置は**バイト単位**。cp932でデコードしてから文字位置で切ると
  全角を含む項目(騎手名12バイト=6文字)以降が全部ズレる。必ずバイトで切る。

Usage:
  python scripts/jrdb_spec.py                # spec/ 配下を一覧
  python scripts/jrdb_spec.py --show tyb     # 特定の仕様の項目を表示
"""
import os
import re
import sys
import io
import glob
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(ROOT, 'data', 'jrdb', 'spec')

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# TYPEとして現れうる形（9/Z/X/F の組合せ、小数点可）
TYPE_RE = re.compile(r'^[9ZXF][9ZXF.]*$', re.I)
INT_RE = re.compile(r'^\d+$')


def read_text(path):
    raw = open(path, 'rb').read()
    for enc in ('cp932', 'utf-8', 'euc-jp'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('cp932', errors='replace')


def parse_spec(path):
    """仕様書 → {'reclen': int, 'fields': [{'name','occ','bytes','type','pos','note'}]}"""
    text = read_text(path)
    reclen = None
    m = re.search(r'レコード長[：:]\s*(\d+)', text)
    if m:
        reclen = int(m.group(1))

    fields = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('*'):
            continue
        toks = line.split()
        if len(toks) < 4:
            continue
        # 末尾から「相対(整数)」を探す。備考が後ろに付くので右から走査する。
        pos_i = None
        for i in range(len(toks) - 1, 1, -1):
            if INT_RE.match(toks[i]) and i >= 3 and TYPE_RE.match(toks[i - 1]) \
                    and INT_RE.match(toks[i - 2]):
                pos_i = i
                break
        if pos_i is None:
            continue
        pos = int(toks[pos_i])
        typ = toks[pos_i - 1]
        nbytes = int(toks[pos_i - 2])
        occ = None
        name_end = pos_i - 2
        if name_end >= 1 and INT_RE.match(toks[name_end - 1]) and name_end >= 2:
            # OCCがある形。ただし項目名が数字で終わる場合と紛れるので
            # 「OCCらしさ=小さい整数」で判定する
            cand = int(toks[name_end - 1])
            if 1 <= cand <= 30:
                occ = cand
                name_end -= 1
        name = ''.join(toks[:name_end]).replace('　', '')
        if not name or pos < 1:
            continue
        note = ' '.join(toks[pos_i + 1:])
        fields.append({'name': name, 'occ': occ, 'bytes': nbytes,
                       'type': typ, 'pos': pos, 'note': note})

    # 位置の重複/矛盾を除去（見出し行を誤検出した場合の保険）
    seen, clean = set(), []
    for f in sorted(fields, key=lambda x: x['pos']):
        if f['pos'] in seen:
            continue
        seen.add(f['pos'])
        clean.append(f)
    return {'reclen': reclen, 'fields': clean, 'path': path}


def list_specs():
    return sorted(glob.glob(os.path.join(SPEC_DIR, '*.txt')))


def find_spec(key):
    """'tyb' のような部分一致で仕様書を探す。"""
    key = key.lower()
    for p in list_specs():
        if key in os.path.basename(p).lower():
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--show', help='仕様名の部分一致（例: tyb / sed / kyi）')
    ap.add_argument('--grep', help='項目名に含む文字で全仕様を横断検索（例: 不利）')
    a = ap.parse_args()

    specs = list_specs()
    if not specs:
        print(f'{SPEC_DIR} に仕様書(.txt)がありません。')
        print('JRDBの各データ行にある「仕様」リンクを保存してください。')
        return

    if a.grep:
        print(f'■ 全仕様から「{a.grep}」を含む項目を検索\n')
        hit = 0
        for p in specs:
            sp = parse_spec(p)
            fs = [f for f in sp['fields'] if a.grep in f['name'] or a.grep in f['note']]
            if fs:
                print(f'--- {os.path.basename(p)} (レコード長{sp["reclen"]}) ---')
                for f in fs:
                    print(f'  {f["name"]:24s} 位置{f["pos"]:>4} {f["bytes"]:>3}byte '
                          f'{f["type"]:>8}  {f["note"][:40]}')
                hit += len(fs)
        print(f'\n計 {hit} 項目')
        return

    if a.show:
        p = find_spec(a.show)
        if not p:
            print(f'"{a.show}" に一致する仕様書がありません。')
            return
        sp = parse_spec(p)
        print(f'■ {os.path.basename(p)}  レコード長={sp["reclen"]}  '
              f'項目数={len(sp["fields"])}\n')
        print(f'{"位置":>5}{"byte":>6}{"type":>9}  {"項目名":24s}備考')
        print('-' * 92)
        for f in sp['fields']:
            print(f'{f["pos"]:>5}{f["bytes"]:>6}{f["type"]:>9}  '
                  f'{f["name"]:24s}{f["note"][:44]}')
        return

    print(f'■ data/jrdb/spec/ の仕様書 {len(specs)}件\n')
    print(f'{"ファイル":28s}{"レコード長":>10}{"項目数":>8}')
    print('-' * 50)
    for p in specs:
        sp = parse_spec(p)
        print(f'{os.path.basename(p):28s}{str(sp["reclen"]):>10}{len(sp["fields"]):>8}')
    print('\n--show tyb で項目一覧 / --grep 不利 で全仕様を横断検索')


if __name__ == '__main__':
    main()
