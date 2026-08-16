# -*- coding: utf-8 -*-
"""JRDB UKC(馬基本データ)から血統を取り込み、jravan.db の欠損を埋める。

## なぜ必要か
jravan.db の horses(血統) は JRA-VAN 契約停止の影響で 2023年から劣化している。
デビュー年別の母名取得率(実測):
    〜2022年 100%  /  2023年 76.7%  /  2024年 8.5%  /  2025年 0.2%  /  2026年 0%
ライブ表示は core/scraper.py が netkeiba から直接取るよう修正済み(0%→100%)なので
影響を受けないが、**バックテストは jravan.db を見る**ため過去分の穴が残る。
UKC には 父馬名/母馬名/母父馬名 に加え **母馬生年** があり、
『母の出産年齢』の検証にも使える(netkeibaの出馬表からは取れない項目)。

## 使い方
  1. JRDB会員ページ『年度パックコーナー』から UKC_2025.zip を
     data/jrdb/raw/ に置く(解凍不要)。2024/2023もあれば置く。
     ⚠ JRDBはレース当日 08:00〜19:00 は過去データDLを制限している。平日か19時以降に。
  2. 確認だけ:   python scripts/jrdb_ukc_ingest.py --dry-run
  3. 取り込み:   python scripts/jrdb_ukc_ingest.py

## 何をするか
  jravan.db に **horses_jrdb** テーブルを新規作成して書く(既存 horses は触らない)。
  既存テーブルを壊さないことを優先し、参照側で COALESCE する設計にする。
  列: ketto_num / sire / dam / bms / sire_birth / dam_birth / bms_birth
      / sire_line / bms_line (系統コード) / src('jrdb')
"""
import os
import sys
import argparse
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(ROOT, 'data', 'jravan.db')
RAW = os.path.join(ROOT, 'data', 'jrdb', 'raw')

# ukc_doc.txt の項目名 → 取り込み先カラム。
# 仕様書パース(scripts/jrdb_read.py)が返す列名に合わせて候補を複数持たせる
# (仕様書の表記ゆれで列名が変わることがあるため、見つかった最初のものを使う)。
FIELD_MAP = [
    ('ketto_num',  ['血統登録番号']),
    ('sire',       ['父馬名']),
    ('dam',        ['母馬名']),
    ('bms',        ['母父馬名']),
    ('sire_birth', ['父馬生年']),
    ('dam_birth',  ['母馬生年']),
    ('bms_birth',  ['母父馬生年']),
    ('sire_line',  ['父系統コード']),
    ('bms_line',   ['母父系統コード']),
]


def to_jra_ketto(s):
    """JRDBの血統登録番号(8桁) → JRA-VAN/jravan.db の形式(10桁)。

    JRDB : '20102562' = 生年下2桁(20) + 品種1桁(1) + 連番5桁(02562)
    jravan: '2020102562' = 生年4桁(2020) + 品種1桁 + 連番5桁
    ＝ **世紀の2桁が省略されている**だけなので補って復元する。
    実データで検証: 変換後 21,648頭中16,604頭(76.7%)が jravan.horses と一致し、
    2023/2024/2025年デビュー馬をそれぞれ 100% / 100% / 97.8% カバーできた。
    (一致しない23%は地方・海外馬など jravan.horses に無い馬)
    """
    s = str(s).strip()
    if len(s) != 8 or not s.isdigit():
        return None
    yy = int(s[:2])
    # UKCは現役馬のマスタ。30を境に20xx/19xxを分ける(1931年以前の馬は現役にいない)
    return ('20' if yy <= 30 else '19') + s


def clean_year(v):
    """'2012.0' のような float 文字列を 'YYYY' に正規化。取れなければ ''。
    JRDBの数値項目はpandas経由でfloat文字列になることがある。"""
    s = str(v).strip()
    if s.endswith('.0'):
        s = s[:-2]
    return s if (len(s) == 4 and s.isdigit()) else ''


def pick(df, names):
    for n in names:
        if n in df.columns:
            return n
    # 空白や全角の混入に耐える
    norm = {str(c).replace(' ', '').replace('　', ''): c for c in df.columns}
    for n in names:
        k = n.replace(' ', '')
        if k in norm:
            return norm[k]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='読み込んで内容を確認するだけ(DBに書かない)')
    ap.add_argument('--db', default=DB)
    args = ap.parse_args()

    import glob
    files = sorted(glob.glob(os.path.join(RAW, 'UKC*')))
    if not files:
        print(f'❌ {RAW} に UKC ファイルがありません。')
        print('   JRDB会員ページの「年度パックコーナー」から UKC_2025.zip 等を置いてください。')
        print('   ⚠ レース当日 08:00〜19:00 はJRDB側でDL制限があります(平日か19時以降に)。')
        return 1
    print('対象ファイル:')
    for f in files:
        print(f'  {os.path.basename(f)}  ({os.path.getsize(f)/1024/1024:.1f}MB)')

    from scripts import jrdb_read
    print('\n仕様書(ukc_doc.txt)からレイアウトを生成して読み込み中...')
    try:
        df = jrdb_read.load('UKC')
    except Exception as e:
        print(f'❌ 読み込み失敗: {e}')
        print('   data/jrdb/spec/ukc_doc.txt があるか確認してください。')
        return 1
    print(f'  {len(df):,}行 / {len(df.columns)}列')

    cols = {}
    missing = []
    for dst, names in FIELD_MAP:
        c = pick(df, names)
        if c is None:
            missing.append(names[0])
        cols[dst] = c
    print('\n項目の対応:')
    for dst, _ in FIELD_MAP:
        print(f'  {dst:<12} ← {cols[dst] or "★見つからない"}')
    if missing:
        print(f'\n❌ 必須項目が見つかりません: {missing}')
        print('   仕様書の項目名が想定と違う可能性。df.columns を確認してください:')
        print(f'   {list(df.columns)[:25]}')
        return 1

    sub = df[[cols[d] for d, _ in FIELD_MAP]].copy()
    sub.columns = [d for d, _ in FIELD_MAP]
    for c in sub.columns:
        sub[c] = sub[c].astype(str).str.strip()
    # 血統登録番号を jravan.db の10桁形式へ変換(JRDBは世紀2桁が省略されている)
    sub['ketto_num'] = sub['ketto_num'].map(to_jra_ketto)
    sub = sub[sub['ketto_num'].notna()]
    # 生年は '2012.0' のようなfloat文字列で来るので正規化
    for c in ('sire_birth', 'dam_birth', 'bms_birth'):
        sub[c] = sub[c].map(clean_year)
    sub = sub.drop_duplicates(subset=['ketto_num'], keep='last')
    n_sire = (sub['sire'].str.len() > 0).sum()
    n_dam = (sub['dam'].str.len() > 0).sum()
    n_dbirth = (sub['dam_birth'].str.len() == 4).sum()
    print(f'\n有効レコード {len(sub):,}頭')
    print(f'  父馬名あり   {n_sire:,} ({n_sire/len(sub)*100:.1f}%)')
    print(f'  母馬名あり   {n_dam:,} ({n_dam/len(sub)*100:.1f}%)')
    print(f'  母馬生年あり {n_dbirth:,} ({n_dbirth/len(sub)*100:.1f}%)')
    print('\nサンプル3件:')
    for _, r in sub.head(3).iterrows():
        print(f"  {r['ketto_num']}  父={r['sire']} / 母={r['dam']}({r['dam_birth']}) "
              f"/ 母父={r['bms']}")

    # ── jravan.db の欠損がどれだけ埋まるかを事前に見積もる ──
    con = sqlite3.connect(f'file:{args.db}?mode=ro', uri=True, timeout=60)
    rows = con.execute("""SELECT r.ketto_num, MIN(ra.year) FROM results r
        JOIN races ra ON ra.race_key=r.race_key
        WHERE ra.jyo BETWEEN '01' AND '10' AND r.chakujun>0
          AND r.ketto_num IS NOT NULL GROUP BY r.ketto_num""").fetchall()
    have = set(k for (k,) in con.execute(
        "SELECT ketto_num FROM horses WHERE dam IS NOT NULL AND TRIM(dam)<>''"))
    con.close()
    ukc = set(sub['ketto_num'])
    print('\nデビュー年別の母名カバー(jravan単独 → UKC併用):')
    byy = {}
    for kt, y in rows:
        if not y or int(y) < 2020:
            continue
        d = byy.setdefault(int(y), [0, 0, 0])
        d[0] += 1
        d[1] += (kt in have)
        d[2] += (kt in have or kt in ukc)
    for y in sorted(byy):
        n, a, b = byy[y]
        print(f'  {y}: {n:,}頭  {a/n*100:5.1f}% → {b/n*100:5.1f}%'
              + ('  ★改善' if b - a > n * 0.05 else ''))

    if args.dry_run:
        print('\n--dry-run のためDBには書きません。')
        return 0

    con = sqlite3.connect(args.db, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS horses_jrdb (
        ketto_num TEXT PRIMARY KEY, sire TEXT, dam TEXT, bms TEXT,
        sire_birth TEXT, dam_birth TEXT, bms_birth TEXT,
        sire_line TEXT, bms_line TEXT, src TEXT)""")
    con.executemany(
        "INSERT OR REPLACE INTO horses_jrdb VALUES (?,?,?,?,?,?,?,?,?,'jrdb')",
        [tuple(r) for r in sub[[d for d, _ in FIELD_MAP]].itertuples(index=False)])
    con.commit()
    n = con.execute('SELECT COUNT(*) FROM horses_jrdb').fetchone()[0]
    con.close()
    print(f'\n✅ horses_jrdb に {n:,}頭を書き込みました(既存 horses は無変更)。')
    print('   参照側は horses と horses_jrdb を COALESCE して使ってください。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
