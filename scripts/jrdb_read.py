# -*- coding: utf-8 -*-
"""JRDBの任意の固定長データを、仕様書から自動生成したレイアウトで読む汎用リーダー。

使い方の流れ:
  1. JRDBの各データ行の「仕様」リンクを data/jrdb/spec/ に保存
  2. データ本体(zip/txt)を data/jrdb/raw/ に置く
  3. これで読める:
       from scripts import jrdb_read
       df = jrdb_read.load('TYB')     # spec名は自動で照合

**形式ごとに手でフィールド定義を書かない。** 仕様書が唯一の正本。
(手書きすると必ずズレる。TYBで騎手名12バイト=全角6文字によるズレを実際に踏んだ)

Usage:
  python scripts/jrdb_read.py TYB            # 読み込んで要約
  python scripts/jrdb_read.py TYB --csv out.csv
"""
import os
import re
import sys
import io
import glob
import zipfile
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from scripts import jrdb_spec

RAW_DIR = os.path.join(ROOT, 'data', 'jrdb', 'raw')

# 仕様書の TYPE から数値かどうかを判定する。X=文字 / F=16進 は文字のまま。
def _is_num(typ):
    t = (typ or '').upper()
    return bool(t) and all(c in '9Z.' for c in t)


def build_layout(spec_key):
    """仕様書 → [(name, pos, bytes, is_num)] 。改行/予備は落とす。"""
    p = jrdb_spec.find_spec(spec_key)
    if not p:
        raise FileNotFoundError(
            f'data/jrdb/spec/ に "{spec_key}" の仕様書がありません。'
            'JRDBの該当データ行の「仕様」リンクを保存してください。')
    sp = jrdb_spec.parse_spec(p)
    lay = []
    seen = {}
    for f in sp['fields']:
        nm = f['name']
        if nm in ('改行', '予備') or nm.startswith('予備'):
            continue
        # 同名項目（前走1〜5走など）が複数ある場合に連番を振る
        if nm in seen:
            seen[nm] += 1
            nm = f'{nm}_{seen[nm]}'
        else:
            seen[nm] = 1
        lay.append((nm, f['pos'], f['bytes'], _is_num(f['type'])))
    return lay, sp['reclen'], os.path.basename(p)


def _num(s):
    s = s.strip()
    if not s:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_buf(buf, layout, reclen, day=None):
    rows = []
    for i in range(0, len(buf) - reclen + 1, reclen):
        rec = buf[i:i + reclen]
        d = {}
        for nm, pos, ln, isnum in layout:
            v = rec[pos - 1:pos - 1 + ln].decode('cp932', errors='replace')
            d[nm] = _num(v) if isnum else v.strip()
        if day:
            d['day'] = day
        rows.append(d)
    return pd.DataFrame(rows)


def _day_from_name(fn):
    ds = ''.join(ch for ch in os.path.basename(fn) if ch.isdigit())
    return f'20{ds[:6]}' if len(ds) >= 6 else None


def load(prefix, spec_key=None, limit_files=None):
    """data/jrdb/raw/ から prefix で始まるファイルを全部読む。

    prefix: 'TYB' 'SED' 'KYI' など。spec_key 省略時は prefix をそのまま使う。
    """
    layout, reclen, spec_name = build_layout(spec_key or prefix)
    frames = []
    for p in sorted(glob.glob(os.path.join(RAW_DIR, '*'))):
        base = os.path.basename(p).upper()
        if not base.startswith(prefix.upper()):
            continue
        if p.lower().endswith('.zip'):
            with zipfile.ZipFile(p) as z:
                # ⚠zipには別形式が同梱されている（SEDのzipにSRB成績レースデータと
                #   RCAコメントCSVが同居）。**中のファイル名もprefixで絞る**こと。
                #   全.TXTを読むとSRBをSEDのレイアウトで解釈して12%が化ける（実際に踏んだ）。
                names = sorted(
                    n for n in z.namelist()
                    if n.upper().endswith('.TXT')
                    and os.path.basename(n).upper().startswith(prefix.upper()))
                if limit_files:
                    names = names[:limit_files]
                for n in names:
                    frames.append(parse_buf(z.read(n), layout, reclen,
                                            _day_from_name(n)))
        elif p.lower().endswith('.txt'):
            frames.append(parse_buf(open(p, 'rb').read(), layout, reclen,
                                    _day_from_name(p)))
    if not frames:
        raise FileNotFoundError(
            f'data/jrdb/raw/ に "{prefix}" で始まるzip/txtがありません。')
    df = pd.concat(frames, ignore_index=True)
    df.attrs['spec'] = spec_name
    df.attrs['reclen'] = reclen
    return df


def main():
    # jrdb_spec がインポート時に sys.stdout を差し替える。
    # ここで再度包むと元のラッパが閉じられるので何もしない。
    ap = argparse.ArgumentParser()
    ap.add_argument('prefix', help='TYB / SED / KYI など')
    ap.add_argument('--spec', help='仕様書名が違う場合に指定')
    ap.add_argument('--limit-files', type=int)
    ap.add_argument('--csv')
    a = ap.parse_args()

    df = load(a.prefix, a.spec, a.limit_files)
    print(f'■ {a.prefix}  仕様={df.attrs["spec"]}  レコード長={df.attrs["reclen"]}')
    print(f'  {len(df):,}行 × {len(df.columns)}列', end='')
    if 'day' in df.columns:
        print(f'  ({df["day"].min()}〜{df["day"].max()} / {df["day"].nunique()}日)')
    else:
        print()

    print(f'\n{"項目":24s}{"型":>6}{"充足率":>9}  例')
    print('-' * 78)
    for c in df.columns:
        if df[c].dtype == object:
            fill = (df[c].astype(str).str.strip() != '').mean()
            ex = next((str(v) for v in df[c] if str(v).strip()), '')
        else:
            fill = df[c].notna().mean()
            ex = f'{df[c].dropna().iloc[0]:g}' if df[c].notna().any() else ''
        typ = '数値' if df[c].dtype != object else '文字'
        print(f'{c:24s}{typ:>6}{fill*100:>8.1f}%  {ex[:26]}')

    if a.csv:
        df.to_csv(a.csv, index=False, encoding='utf-8-sig')
        print(f'\n書き出し: {a.csv}')


if __name__ == '__main__':
    main()
