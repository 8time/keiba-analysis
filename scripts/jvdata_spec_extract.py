# -*- coding: utf-8 -*-
"""
JV-Data仕様書Excel（JV-Data2311.xls）の「フォーマット」シートから
各レコード種別の項目レイアウト（位置・バイト長・繰返）を自動抽出してJSON化する。

出力: scripts/jvdata_layout.json
  { "RA": {"reclen": int, "fields":[ {name,pos,len,repeat,stride,sub:[{name,rel,len}]} ]}, ... }

64bit Pythonで実行（解析のみ、COM不要）:
  py -3.14 scripts/jvdata_spec_extract.py <path-to-JV-Data2311.xls>
"""
import sys, io, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import xlrd

def to_int(v):
    try:
        s = str(v).strip()
        if s == '': return None
        return int(float(s))
    except Exception:
        return None

def main():
    xls = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\kimnhaty\AppData\Local\Temp\JV-Data2311.xls'
    b = xlrd.open_workbook(xls)
    fmt = b.sheet_by_index(2)  # フォーマット

    def cell(r, c):
        try: return str(fmt.cell_value(r, c)).strip()
        except Exception: return ''

    records = {}
    cur = None          # 現在のレコード種別ID
    cur_fields = None
    cur_group = None     # 現在の繰返グループ（subを溜める）
    pending_reclen = None

    for r in range(fmt.nrows):
        col_ban   = cell(r, 1)   # 項番
        col_name  = cell(r, 4)   # 項目名
        col_pos   = cell(r, 5)   # 位置
        col_rep   = cell(r, 6)   # 繰返
        col_len   = cell(r, 7)   # バイト
        col_total = cell(r, 8)   # 合計
        col_desc  = cell(r, 10) if fmt.ncols > 10 else ''

        # レコード長の検出（セクション見出し行: "... レコード長 ... 21657 バイト"）
        rowtext = ' '.join(cell(r, c) for c in range(fmt.ncols))
        if 'レコード長' in rowtext:
            m = re.search(r'(\d{2,6})', col_total or '') or re.search(r'レコード長\D+(\d{2,6})', rowtext)
            if m:
                pending_reclen = int(m.group(1))

        # レコード種別IDの行 → 新しいレコード開始
        if col_name == 'レコード種別ID':
            m = re.search(r'"([A-Z0-9]{2})"', col_desc)
            if m:
                cur = m.group(1)
                cur_fields = []
                records[cur] = {'reclen': pending_reclen, 'fields': cur_fields}
                cur_group = None
                pending_reclen = None
            # レコード種別ID自体も先頭フィールドとして登録
            if cur is not None:
                cur_fields.append({'name': 'レコード種別ID', 'pos': to_int(col_pos) or 1, 'len': to_int(col_len) or 2})
            continue

        if cur is None or cur_fields is None:
            continue

        ban = to_int(col_ban)
        rep = to_int(col_rep)
        ln  = to_int(col_len)

        # サブ項目（繰返グループ内）: 項番空 かつ 位置が "(  N)" 形式
        if ban is None and col_pos.startswith('(') and cur_group is not None:
            rel = to_int(re.sub(r'[()\s]', '', col_pos))
            if rel is not None and ln:
                cur_group['sub'].append({'name': col_name, 'rel': rel, 'len': ln})
            continue

        # 繰返グループのヘッダ: 項番あり かつ 繰返>1
        if ban is not None and rep and rep > 1:
            pos = to_int(col_pos)
            stride = ln
            cur_group = {'name': col_name, 'pos': pos, 'repeat': rep, 'stride': stride, 'sub': []}
            cur_fields.append(cur_group)
            continue

        # 通常のトップレベル項目: 項番あり・位置あり・バイトあり
        if ban is not None and ln:
            pos = to_int(col_pos)
            if pos is not None:
                cur_fields.append({'name': col_name, 'pos': pos, 'len': ln})
                cur_group = None  # トップレベルに戻ったらグループ解除
            continue

    out_path = 'scripts/jvdata_layout.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=1)

    print(f'抽出レコード種別: {len(records)}')
    for k in records:
        nf = len(records[k]['fields'])
        print(f'  {k}: reclen={records[k]["reclen"]} fields={nf}')
    print(f'→ {out_path}')

if __name__ == '__main__':
    main()
