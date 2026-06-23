# -*- coding: utf-8 -*-
"""
JV-Link → SQLite 取り込み（32bit Python専用）

RA(レース詳細)/SE(馬毎成績)/HR(払戻) をパースしてSQLiteに格納する。
JVGetsで生バイトを取得し、jvdata_parser でバイトオフセット解析。

使い方:
  # 小規模テスト（直近データ・option=1）。馬名が化けないか確認用
  python scripts/jvlink_ingest.py --test
  # 通常データ（指定日以降の差分）
  python scripts/jvlink_ingest.py --from 20260101000000 --option 1
  # フルセットアップ（全履歴1986+。重い）
  python scripts/jvlink_ingest.py --from 19860101000000 --option 4 --setup

DB: data/jravan.db
"""
import sys, os, io, time, sqlite3, argparse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import win32com.client
import jvdata_parser as P

def to_bytes(buff):
    if buff is None: return b''
    if isinstance(buff, (bytes, bytearray)): return bytes(buff)
    if isinstance(buff, (tuple, list)):
        return bytes(bytearray(int(x) & 0xFF for x in buff))
    try: return bytes(buff)
    except Exception: return b''

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')

DDL = """
CREATE TABLE IF NOT EXISTS races (
  race_key TEXT PRIMARY KEY, race_id TEXT, data_kubun TEXT, year TEXT, monthday TEXT,
  jyo TEXT, kai INTEGER, nichi INTEGER, race_num INTEGER, race_name TEXT,
  grade TEXT, shubetsu TEXT, kigo TEXT, juryo TEXT, kyori INTEGER, track_code TEXT, surface TEXT,
  hasso_time TEXT, toroku_tosu INTEGER, shusso_tosu INTEGER, nyusen_tosu INTEGER,
  tenko TEXT, baba_shiba TEXT, baba_dirt TEXT, mae3f INTEGER, ato3f INTEGER
);
CREATE TABLE IF NOT EXISTS results (
  race_key TEXT, race_id TEXT, year TEXT, monthday TEXT, jyo TEXT,
  waku INTEGER, umaban INTEGER, ketto_num TEXT, bamei TEXT, sex TEXT, age INTEGER, tozai TEXT,
  trainer_code TEXT, futan INTEGER, blinker TEXT, jockey_code TEXT, jockey_name TEXT, minarai TEXT,
  bataiju INTEGER, zogen INTEGER, ijo TEXT, nyusen INTEGER, chakujun INTEGER, time TEXT,
  corner1 INTEGER, corner2 INTEGER, corner3 INTEGER, corner4 INTEGER,
  win_odds REAL, ninki INTEGER, ato3f INTEGER, kyakushitsu TEXT,
  PRIMARY KEY (race_key, umaban)
);
CREATE TABLE IF NOT EXISTS payouts (
  race_key TEXT, race_id TEXT, bet_type TEXT, combo TEXT, payout INTEGER, pop INTEGER,
  PRIMARY KEY (race_key, bet_type, combo)
);
CREATE TABLE IF NOT EXISTS horses (
  ketto_num TEXT PRIMARY KEY, bamei TEXT, sex TEXT, birth TEXT,
  sire TEXT, dam TEXT, bms TEXT
);
CREATE TABLE IF NOT EXISTS odds (
  race_key TEXT, race_id TEXT, bet_type TEXT, combo TEXT,
  odds REAL, odds_max REAL, ninki INTEGER,
  PRIMARY KEY (race_key, bet_type, combo)
);
CREATE TABLE IF NOT EXISTS training (
  ketto_num TEXT, center TEXT, cho_date TEXT, cho_time TEXT,
  t4f INTEGER, lap_86 INTEGER, t3f INTEGER, lap_64 INTEGER,
  t2f INTEGER, lap_42 INTEGER, lap_20 INTEGER,
  PRIMARY KEY (ketto_num, cho_date, cho_time)
);
CREATE INDEX IF NOT EXISTS idx_training_ketto ON training(ketto_num);
CREATE INDEX IF NOT EXISTS idx_horses_sire ON horses(sire);
CREATE INDEX IF NOT EXISTS idx_horses_bms ON horses(bms);
CREATE INDEX IF NOT EXISTS idx_results_ketto ON results(ketto_num);
CREATE INDEX IF NOT EXISTS idx_results_jockey ON results(jockey_code);
CREATE INDEX IF NOT EXISTS idx_results_raceid ON results(race_id);
CREATE INDEX IF NOT EXISTS idx_odds_raceid ON odds(race_id);
CREATE INDEX IF NOT EXISTS idx_odds_type ON odds(bet_type);
"""

def upsert(cur, table, d):
    cols = list(d.keys())
    ph = ','.join('?' * len(cols))
    cur.execute(f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({ph})", [d[c] for c in cols])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='fromtime', default='20260101000000')
    ap.add_argument('--option', type=int, default=1)
    ap.add_argument('--dataspec', default='RACE')
    ap.add_argument('--test', action='store_true', help='直近少量で馬名デコード確認のみ')
    ap.add_argument('--limit', type=int, default=0, help='最大レコード数(0=無制限)')
    ap.add_argument('--probe', action='store_true', help='JVOpenしてファイル数だけ確認（読まない）')
    ap.add_argument('--from-year', type=int, dest='from_year', help='開始年(例: 1986)')
    ap.add_argument('--to-year', type=int, dest='to_year', help='終了年(例: 1990。この年の12/31まで)')
    ap.add_argument('--savepath', default=None,
                    help='JV-LinkのDL保存先を上書き(空フォルダを指定するとキャッシュ無視で最新を強制DL)')
    args = ap.parse_args()

    # --from-year / --to-year が指定された場合、fromtime と option を自動設定
    if args.from_year:
        args.fromtime = f'{args.from_year}0101000000'
        args.option = 4
    to_year = args.to_year

    if args.probe:
        jv = win32com.client.gencache.EnsureDispatch("JVDTLab.JVLink")
        print("JVInit", jv.JVInit("UNKNOWN"))
        r = jv.JVOpen(args.dataspec, args.fromtime, args.option, 0, 0)
        print(f"JVOpen({args.dataspec}, from={args.fromtime}, opt={args.option}) -> {r}")
        if isinstance(r, (tuple, list)) and len(r) > 2:
            print(f"  読込予定ファイル={r[1]}  DLファイル={r[2]}")
        jv.JVClose()
        return

    if args.test:
        args.fromtime = '20260501000000'; args.option = 1; args.limit = 30000; to_year = None

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(DDL)
    cur = con.cursor()

    # UTF-8ログファイル（PowerShellリダイレクトのUTF-16化を回避）
    import datetime
    logf = open(os.path.join(os.path.dirname(DB_PATH), '..', 'ingest_progress.log'), 'a', encoding='utf-8')
    def log(*a):
        msg = ' '.join(str(x) for x in a)
        stamp = datetime.datetime.now().strftime('%H:%M:%S')
        line = f'[{stamp}] {msg}'
        print(line, flush=True)
        logf.write(line + '\n'); logf.flush()

    jv = win32com.client.gencache.EnsureDispatch("JVDTLab.JVLink")
    rc = jv.JVInit("UNKNOWN")
    log(f"JVInit rc={rc}")
    if rc != 0: return

    # DL保存先の上書き(空フォルダ指定でキャッシュ無視→最新セットアップを強制DL)
    if args.savepath:
        try:
            os.makedirs(args.savepath, exist_ok=True)
            _sp_rc = jv.JVSetSavePath(args.savepath)
            log(f"JVSetSavePath('{args.savepath}') rc={_sp_rc}")
        except Exception as _spe:
            log(f"JVSetSavePath例外(続行): {_spe}")

    # JVOpen（-301認証スロットル等は待って自動リトライ）
    r = None; code = None
    for attempt in range(1, 7):
        r = jv.JVOpen(args.dataspec, args.fromtime, args.option, 0, 0)
        code = r[0] if isinstance(r, (tuple, list)) else r
        log(f"JVOpen rc={code} (dataspec={args.dataspec} from={args.fromtime} option={args.option}) 試行{attempt}")
        if code == 0:
            break
        try: jv.JVClose()
        except Exception: pass
        if code == -301 and attempt < 6:
            log(f"  -301(認証スロットル?) {attempt*60}秒待って再試行")
            time.sleep(attempt * 60)
            continue
        log("JVOpen失敗（リトライ打切り）"); logf.close(); return
    if isinstance(r, (tuple, list)) and len(r) > 2:
        log(f"  読込予定={r[1]}ファイル DL={r[2]}ファイル")

    from collections import Counter
    counts = {'RA': 0, 'SE': 0, 'HR': 0, 'O1': 0, 'O2': 0, 'O3': 0, 'O4': 0, 'O5': 0, 'other': 0}
    kind_counter = Counter()
    total = 0
    waits = 0
    consecutive_skip = 0
    samples = []
    t0 = time.time()

    while True:
        # JVGets(buff, size) -> (rc, buff, filename)。buff=生バイト配列(VT_BYREF|VT_VARIANT)
        try:
            ret = jv.JVGets(b'', 120000)
        except Exception as e:
            print(f"JVGets例外: {e}"); break
        size = ret[0] if isinstance(ret, (tuple, list)) else ret
        raw = ret[1] if isinstance(ret, (tuple, list)) and len(ret) > 1 else None

        if size == 0:
            print("[EOF] 完了"); break
        elif size == -1:
            waits = 0
            continue  # ファイル切替
        elif size == -3:
            waits += 1
            # ダウンロード待ち。進捗をログしつつ気長に待つ（連続30分のみで打切り）
            if waits % 30 == 0:
                try:
                    st = jv.JVStatus()
                except Exception:
                    st = '?'
                log(f"  …DL待ち {waits}s (JVStatus={st} 取込済RA={counts['RA']} SE={counts['SE']})")
            if waits > 1800:
                print("DL待ち30分超 → 打切り"); break
            time.sleep(1); continue
        elif size < 0:
            print(f"size={size} で停止"); break

        waits = 0  # データが流れたら待機カウンタをリセット
        buf = to_bytes(raw)
        kind = buf[:2].decode('ascii', errors='replace')
        kind_counter[kind] += 1

        # --to-year 指定時: レコードの年がto_yearを超えたらスキップ→連続5万件超で打切り
        if to_year and len(buf) >= 15:
            try:
                rec_year = int(buf[11:15].decode('ascii', errors='replace'))
                if rec_year > to_year:
                    counts['skipped'] = counts.get('skipped', 0) + 1
                    consecutive_skip += 1
                    total += 1
                    if counts['skipped'] % 50000 == 0:
                        log(f"  skip {counts['skipped']}件 (year={rec_year} > {to_year})")
                    if consecutive_skip >= 50000:
                        log(f"  連続{consecutive_skip}件スキップ → to_year={to_year}超え打切り")
                        break
                    continue
                else:
                    consecutive_skip = 0
            except (ValueError, IndexError):
                pass

        try:
            if kind == 'HC':
                upsert(cur, 'training', P.parse_hc(buf)); counts['HC'] = counts.get('HC', 0) + 1
            elif kind == 'RA':
                upsert(cur, 'races', P.parse_ra(buf)); counts['RA'] += 1
            elif kind == 'SE':
                d = P.parse_se(buf); upsert(cur, 'results', d); counts['SE'] += 1
                if len(samples) < 8 and d.get('bamei'):
                    samples.append(f"{d['umaban']}番 {d['bamei']} 着={d['chakujun']} 騎手={d['jockey_name']} 単勝={d['win_odds']}")
            elif kind == 'HR':
                for row in P.parse_hr(buf): upsert(cur, 'payouts', row)
                counts['HR'] += 1
            elif kind == 'O1':
                for row in P.parse_o1(buf): upsert(cur, 'odds', row)
                counts['O1'] += 1
            elif kind == 'O2':
                for row in P.parse_o2(buf): upsert(cur, 'odds', row)
                counts['O2'] += 1
            elif kind == 'O3':
                for row in P.parse_o3(buf): upsert(cur, 'odds', row)
                counts['O3'] += 1
            elif kind == 'O4':
                for row in P.parse_o4(buf): upsert(cur, 'odds', row)
                counts['O4'] += 1
            elif kind == 'O5':
                for row in P.parse_o5(buf): upsert(cur, 'odds', row)
                counts['O5'] += 1
            elif kind == 'UM':
                upsert(cur, 'horses', P.parse_um(buf)); counts['UM'] = counts.get('UM', 0) + 1
            else:
                counts['other'] += 1
        except Exception as e:
            print(f"parse例外({kind}): {e}")

        total += 1
        if total % 5000 == 0:
            con.commit()
            el = time.time() - t0
            nr_ = cur.execute('SELECT COUNT(*) FROM races').fetchone()[0]
            log(f"  {total}件 ({el:.0f}s, {total/el:.0f}rec/s) races={nr_} {counts}")
        if args.limit and total >= args.limit:
            print(f"limit {args.limit} 到達"); break

    jv.JVClose()
    con.commit()
    log(f"=== 取込完了 {total}レコード ({time.time()-t0:.0f}秒) ===")
    log("内訳:", counts)
    log("DB:", DB_PATH)
    print("\n--- 馬名デコード確認サンプル ---")
    for x in samples: print("  ", x)
    # 件数確認
    for t in ('races', 'results', 'payouts', 'odds', 'horses'):
        print(f"  {t}: {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]} 行")
    con.close()

if __name__ == '__main__':
    main()
