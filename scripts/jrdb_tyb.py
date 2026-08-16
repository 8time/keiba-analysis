# -*- coding: utf-8 -*-
"""JRDB 直前情報データ(TYB) のパーサ。

固定長128バイト・cp932。仕様は data/jrdb/spec/tyb_doc.txt（第4b版）。
**バイト位置は1始まり**なので slice は -1 する。

このデータが欲しい理由:
  [[verified_r40_place_ev]]の残る唯一の未検証点＝「検証は確定オッズでやったが、
  ライブで見えるのは締切前オッズ。そのズレは未知」を潰すため。
  TYBには **単勝オッズ / 複勝オッズ(下限) / オッズ取得時間(HHMM) / 発走時間(HHMM)**
  が入っているので、「発走何分前のオッズか」まで分かる。

⚠複勝オッズは**下限のみ**（仕様に「複勝オッズの下側」と明記）。上限は入っていない。
  r40の較正EVは上限が要るので、上限は確定オッズ(jravan.db)側から補う設計になる。

⚠JRDBデータは他社著作物。data/jrdb/ は .gitignore 済み。自分の計算にのみ使う。

Usage:
  python scripts/jrdb_tyb.py                 # 中身の要約を表示
  python scripts/jrdb_tyb.py --to-csv out.csv
"""
import os
import sys
import io
import zipfile
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

RAW_DIR = os.path.join(ROOT, 'data', 'jrdb', 'raw')
RECLEN = 128

# (項目名, 開始位置(1始まり), バイト数)
FIELDS = [
    ('jyo', 1, 2), ('yy', 3, 2), ('kai', 5, 1), ('nichi', 6, 1), ('r', 7, 2),
    ('umaban', 9, 2),
    ('idm', 11, 5), ('jockey_idx', 16, 5), ('info_idx', 21, 5),
    ('odds_idx', 26, 5), ('paddock_idx', 31, 5), ('_rsv1', 36, 5),
    ('total_idx', 41, 5),
    ('bagu', 46, 1), ('ashimoto', 47, 1), ('cancel', 48, 1),
    ('jockey_code', 49, 5), ('jockey_name', 54, 12),
    ('futan', 66, 3), ('minarai', 69, 1),
    ('baba_code', 70, 2), ('tenko', 72, 1),
    ('win_odds', 73, 6), ('place_odds_min', 79, 6),
    ('odds_time', 85, 4),
    ('weight', 89, 3), ('weight_diff', 92, 3),
    ('mark_odds', 95, 1), ('mark_paddock', 96, 1), ('mark_total', 97, 1),
    ('batai_code', 98, 1), ('kehai_code', 99, 1),
    ('start_time', 100, 4),
]
NUM = {'idm', 'jockey_idx', 'info_idx', 'odds_idx', 'paddock_idx', 'total_idx',
       'win_odds', 'place_odds_min'}
INT = {'umaban', 'futan', 'weight', 'r'}


def _num(s):
    s = s.strip()
    if not s:
        return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def parse_bytes(buf, day=None):
    """128バイト固定長のバイト列 → DataFrame。

    ⚠仕様のバイト位置は**バイト単位**。cp932でデコードしてから文字位置で切ると、
      騎手名(12バイト=全角6文字)以降が6文字ぶんズレる（実際に踏んだ）。
      必ず**バイト列のまま切ってから**フィールドごとにデコードすること。
    """
    rows = []
    for i in range(0, len(buf) - RECLEN + 1, RECLEN):
        rec = buf[i:i + RECLEN]
        d = {}
        for name, pos, ln in FIELDS:
            v = rec[pos - 1:pos - 1 + ln].decode('cp932', errors='replace')
            if name in NUM:
                d[name] = _num(v)
            elif name in INT:
                s = v.strip()
                d[name] = int(s) if s.isdigit() else np.nan
            else:
                d[name] = v.strip()
        if day:
            d['day'] = day
        rows.append(d)
    return pd.DataFrame(rows)


def load_zip(path, limit_files=None):
    """TYB_YYYY.zip をまとめて読む。ファイル名から日付を取る。"""
    out = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.upper().endswith('.TXT')]
        names.sort()
        if limit_files:
            names = names[:limit_files]
        for n in names:
            base = os.path.basename(n)
            ymd = ''.join(ch for ch in base if ch.isdigit())[:6]   # YYMMDD
            day = f'20{ymd}' if len(ymd) == 6 else None
            out.append(parse_bytes(z.read(n), day=day))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def load_all(limit_files=None):
    """data/jrdb/raw/ 配下の TYB zip / txt を全部読む。"""
    frames = []
    for fn in sorted(os.listdir(RAW_DIR)):
        p = os.path.join(RAW_DIR, fn)
        if fn.upper().startswith('TYB') and fn.lower().endswith('.zip'):
            frames.append(load_zip(p, limit_files))
        elif fn.upper().startswith('TYB') and fn.lower().endswith('.txt'):
            ymd = ''.join(ch for ch in fn if ch.isdigit())[:6]
            frames.append(parse_bytes(open(p, 'rb').read(),
                                      day=f'20{ymd}' if len(ymd) == 6 else None))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    # 発走何分前のオッズか
    def _mins(row):
        try:
            o, s = str(row['odds_time']), str(row['start_time'])
            if len(o) != 4 or len(s) != 4 or not o.isdigit() or not s.isdigit():
                return np.nan
            om = int(o[:2]) * 60 + int(o[2:])
            sm = int(s[:2]) * 60 + int(s[2:])
            return sm - om
        except Exception:
            return np.nan
    df['mins_before'] = df.apply(_mins, axis=1)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--to-csv')
    ap.add_argument('--limit-files', type=int)
    a = ap.parse_args()

    df = load_all(a.limit_files)
    if df.empty:
        print('data/jrdb/raw/ にTYBのzip/txtがありません。')
        return
    print(f'読込 {len(df):,}行 / {df["day"].nunique()}日 '
          f'({df["day"].min()}〜{df["day"].max()})\n')

    print('■ オッズは発走何分前のものか')
    m = df['mins_before'].dropna()
    print(f'  中央値 {m.median():.0f}分前 / 平均 {m.mean():.1f}分前 '
          f'/ 範囲 {m.min():.0f}〜{m.max():.0f}分')
    for lo, hi in ((0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 999)):
        c = ((m >= lo) & (m < hi)).sum()
        if c:
            print(f'    {lo:>2}-{hi if hi<999 else "":>3}分前: {c/len(m)*100:>5.1f}%')

    print('\n■ 主要項目の充足率')
    for c in ('win_odds', 'place_odds_min', 'idm', 'weight', 'batai_code',
              'kehai_code', 'mark_paddock', 'mark_odds', 'paddock_idx'):
        if c in df.columns:
            if df[c].dtype == object:
                ok = (df[c].astype(str).str.strip() != '').mean()
            else:
                ok = df[c].notna().mean()
            print(f'  {c:18s}{ok*100:>6.1f}%')

    print('\n■ 馬体コード / 気配コードの分布（パドック評価）')
    for c in ('batai_code', 'kehai_code'):
        vc = df[c].astype(str).str.strip().replace('', '(空)').value_counts()
        print(f'  {c}: ' + ' / '.join(f'{k}={v:,}' for k, v in vc.head(9).items()))

    if a.to_csv:
        df.to_csv(a.to_csv, index=False, encoding='utf-8-sig')
        print(f'\n書き出し: {a.to_csv}')


if __name__ == '__main__':
    main()
