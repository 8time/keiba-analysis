# -*- coding: utf-8 -*-
"""📊 成績台帳バッチ — 過去のメインレース(G1-G3)を自動解析→台帳登録→結果取得。

Usage:
    python scripts/batch_track_record.py                 # 2026年G1-G3全レース
    python scripts/batch_track_record.py --grade G1      # G1のみ
    python scripts/batch_track_record.py --ids 202605021111,202605021112  # 指定ID
    python scripts/batch_track_record.py --fetch-only    # 解析せず結果取得のみ

パイプライン (1レースあたり):
  1. scraper.get_race_data() → 出馬表取得
  2. calculator.calculate_battle_score() → 指数計算
  3. consensus_view.build_edge_sets() → 検証済みエッジ抽出
  4. consensus_view.integrate() → 合議(本命/相手/穴/切る)
  5. trio_engine.recommend_trio() → 3連複買い目
  6. trio_engine.recommend_trifecta() → 3連単買い目
  7. newspaper.write_consensus_snapshot() → cv.json保存
  8. newspaper.write_bets_snapshot() → bets.json保存
  9. track_record.register_race() → 台帳登録
  10. track_record.fetch_result() → 結果取得+照合

裁量ゼロ: 全てコード判定。人間の修正なし。
"""
import sys
import os
import io
import time
import argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# jravan.db の grade 値: A=G1, B=G2, C=G3
_GRADE_MAP = {'A': 'G1', 'B': 'G2', 'C': 'G3'}
_GRADE_REV = {'G1': 'A', 'G2': 'B', 'G3': 'C'}


def _load_graded_from_db(year='2026', grade_filter=None):
    """jravan.dbから重賞レース一覧を取得。
    戻り値: [(race_id, grade_label, race_name, date_str), ...]"""
    import sqlite3
    db_path = os.path.join(ROOT, 'data', 'jravan.db')
    if not os.path.exists(db_path):
        print(f"⚠ {db_path} が見つかりません。--ids で直接指定してください。")
        return []
    conn = sqlite3.connect(db_path)
    grades = ('A', 'B', 'C')
    if grade_filter:
        g = _GRADE_REV.get(grade_filter, grade_filter)
        grades = (g,)
    placeholders = ','.join('?' * len(grades))
    cur = conn.execute(f'''
        SELECT race_id, race_name, grade, year||monthday as rdate
        FROM races
        WHERE year = ? AND grade IN ({placeholders})
          AND race_id GLOB '2026[0-1][0-9]*'
          AND length(race_id) = 12
          AND CAST(SUBSTR(race_id, 5, 2) AS INTEGER) <= 10
        ORDER BY monthday
    ''', [year] + list(grades))
    rows = cur.fetchall()
    conn.close()
    # 重複除去(同一race_idが複数行に入ることがある)
    seen = set()
    out = []
    for rid, rname, g, rdate in rows:
        if rid in seen:
            continue
        seen.add(rid)
        # 今日以前(確定済み)のレースのみ
        try:
            from datetime import date
            rd = date(int(rdate[:4]), int(rdate[4:6]), int(rdate[6:8]))
            if rd > date.today():
                continue
        except Exception:
            pass
        out.append((rid, _GRADE_MAP.get(g, g), rname, rdate))
    return out


def get_race_ids(grade=None, ids_str=None):
    """対象レースIDリストを返す。"""
    if ids_str:
        return [rid.strip() for rid in ids_str.split(',') if rid.strip()]
    rows = _load_graded_from_db(grade_filter=grade)
    return [rid for rid, g, name, d in rows]


def _get_race_label(race_id):
    """race_idからレース名を取得(DBまたはcv.jsonから)。"""
    rows = _load_graded_from_db()
    for rid, g, name, d in rows:
        if rid == race_id:
            return f"{g} {name}"
    return race_id


def analyze_and_register(race_id, verbose=True):
    """1レースを解析→合議→買い目生成→スナップショット保存→台帳登録。"""
    import pandas as pd
    from core import scraper, calculator
    from core import consensus_view as cv
    from core import trio_engine as te
    from core import newspaper as np_mod
    from core import value_scanner as vs
    from core import track_record as tr
    from core import axis_selector as ax

    label = _get_race_label(race_id)
    if verbose:
        print(f"\n{'='*60}")
        print(f"  {race_id} : {label}")
        print(f"{'='*60}")

    # ── 1. 出馬表取得 ──
    try:
        df = scraper.get_race_data(race_id, use_storage=False)
    except Exception as e:
        print(f"  ❌ 出馬表取得失敗: {e}")
        return False
    if df is None or df.empty:
        print(f"  ❌ 出馬表データなし")
        return False
    if verbose:
        print(f"  ✅ 出馬表取得: {len(df)}頭")

    # ── 2. 指数計算 ──
    try:
        df = calculator.calculate_battle_score(df)
    except Exception as e:
        print(f"  ⚠ BattleScore計算失敗(続行): {e}")
    try:
        df = calculator.calculate_n_index(df)
    except Exception:
        pass

    # ── 3. メタ情報 ──
    meta = {}
    for col, key in [('RaceName', 'race_name'), ('Venue', 'venue'), ('RaceDate', 'date'),
                     ('CurrentDistance', 'distance'), ('CurrentSurface', 'surface')]:
        if col in df.columns:
            try:
                meta[key] = str(df.iloc[0][col])
            except Exception:
                pass
    meta['n_horses'] = len(df)
    if verbose:
        print(f"  📍 {meta.get('venue', '?')} {meta.get('surface', '?')}{meta.get('distance', '?')}m "
              f"{meta.get('race_name', '')}")

    # ── 4. 検証済みエッジ抽出 ──
    try:
        aim = cv.build_edge_sets(df, meta, race_id)
    except Exception as e:
        print(f"  ⚠ build_edge_sets失敗(続行): {e}")
        aim = {}
    if verbose:
        danger = aim.get('danger', set())
        ana = aim.get('ana', set())
        print(f"  🔍 エッジ: danger={len(danger)} ana={len(ana)} "
              f"combo keys={len(aim.get('combo', {}))}")

    # ── 5. オッズ取得(荒れ予報/trio_lean) ──
    odds_list = []
    odds_map = {}
    try:
        odds_col = pd.to_numeric(df['Odds'], errors='coerce') if 'Odds' in df.columns else pd.Series()
        for _, r in df.iterrows():
            o = pd.to_numeric(r.get('Odds'), errors='coerce')
            if pd.notnull(o) and o > 0:
                odds_list.append(float(o))
                u = int(pd.to_numeric(r.get('Umaban'), errors='coerce'))
                odds_map[u] = float(o)
    except Exception:
        pass

    # trio_lean (荒れ予報レジーム)
    regime = '中立'
    try:
        lean_r = vs.trio_lean(meta=meta, n_horses=len(df),
                              fav_odds=(odds_list[0] if odds_list else None))
        regime = (lean_r or {}).get('lean', '中立')
    except Exception:
        pass
    if verbose:
        print(f"  🎲 レジーム: {regime}")

    # ── 6. 軸候補(axis_selector) ──
    horses_for_cv = []
    is_nar = int(str(race_id)[4:6]) > 10
    for _, r in df.iterrows():
        un = pd.to_numeric(r.get('Umaban'), errors='coerce')
        if pd.isnull(un):
            continue
        u = int(un)
        pop = pd.to_numeric(r.get('Popularity'), errors='coerce')
        pop = int(pop) if pd.notnull(pop) else None
        od = odds_map.get(u)
        proj = pd.to_numeric(r.get('Projected Score', r.get('BattleScore')), errors='coerce')
        proj = float(proj) if pd.notnull(proj) else 0.0
        alert = str(r.get('Alert', '') or '') + str(r.get('Signal', '') or '')
        horses_for_cv.append({
            'umaban': u, 'name': str(r.get('Name', '')),
            'pop': pop, 'odds': od, 'proj': proj, 'score': proj,
            'alert': alert, 'axis_mark': '',
        })

    # assign axis marks (axis_marks returns {name: {'mark':..}} )
    try:
        mark_fn = ax.axis_marks_nar if is_nar else ax.axis_marks
        mark_result = mark_fn(horses_for_cv)
        for h in horses_for_cv:
            info = mark_result.get(h['name'])
            if info and info.get('mark'):
                h['axis_mark'] = info['mark']
    except Exception:
        if horses_for_cv:
            horses_for_cv[0]['axis_mark'] = '◎'
            if len(horses_for_cv) > 1:
                horses_for_cv[1]['axis_mark'] = '〇'

    # ── 7. 合議 (integrate) ──
    try:
        result = cv.integrate(horses_for_cv, aim, regime)
    except Exception as e:
        print(f"  ❌ integrate失敗: {e}")
        return False

    groups = result.get('groups', {})
    if verbose:
        print(f"  🏆 合議: 本命={groups.get('honmei')} 相手={groups.get('aite')} "
              f"穴={len(groups.get('ana', []))} 切り={len(groups.get('keshi', []))}")

    # ── 8. 買い目生成（切る馬を除外して絞る） ──
    keshi_set = set(groups.get('keshi', []))
    horses_for_bet = [h for h in horses_for_cv if h['umaban'] not in keshi_set]
    if verbose and keshi_set:
        print(f"  ✂ 買い目から{len(keshi_set)}頭除外: {sorted(keshi_set)}")

    # 3連複
    trio_result = {}
    try:
        axis_ums = [h['umaban'] for h in horses_for_bet if h.get('axis_mark') in ('◎', '〇')]
        _pat = '②' if '穴' in regime else '①'
        trio_result = te.recommend_trio(
            horses_for_bet, odds_map=odds_map,
            axis_umaban=axis_ums if axis_ums else None,
            axis_mode='2軸' if len(axis_ums) >= 2 else ('1軸' if axis_ums else 'auto'),
            pattern=_pat, n_points=10)
    except Exception as e:
        if verbose:
            print(f"  ⚠ 3連複生成失敗: {e}")

    # 3連単
    trifecta_result = {}
    try:
        trifecta_result = te.recommend_trifecta(
            horses_for_bet, odds_map=odds_map,
            axis_umaban=axis_ums if axis_ums else None,
            n_points=30)
    except Exception as e:
        if verbose:
            print(f"  ⚠ 3連単生成失敗: {e}")

    if verbose:
        n_trio = len(trio_result.get('bets', []))
        n_tri = len(trifecta_result.get('bets', []))
        print(f"  🎰 買い目: 3連複{n_trio}点 3連単{n_tri}点")

    # ── 9. スナップショット保存 ──
    try:
        np_mod.write_consensus_snapshot(
            race_id, regime, result, lean={'lean': regime}, aim=aim, df=df, meta=meta)
    except Exception as e:
        if verbose:
            print(f"  ⚠ cv.json保存失敗: {e}")

    if trio_result.get('bets'):
        try:
            np_mod.write_bets_snapshot(race_id, 'trio', trio_result,
                                       extra={'pattern': trio_result.get('pattern', '')})
        except Exception:
            pass
    if trifecta_result.get('bets'):
        try:
            np_mod.write_bets_snapshot(race_id, 'trifecta', trifecta_result)
        except Exception:
            pass

    # viewスナップショット(簡易版: 結論カードに必要な最低限)
    try:
        view_records = []
        for h in horses_for_cv:
            rec = {'Umaban': h['umaban'], 'Name': h['name'],
                   'Popularity': h.get('pop'), 'Odds': h.get('odds')}
            view_records.append(rec)
        import json
        os.makedirs(os.path.join(ROOT, 'data', 'newspaper'), exist_ok=True)
        rid_clean = ''.join(ch for ch in str(race_id) if ch.isalnum())
        vpath = os.path.join(ROOT, 'data', 'newspaper', f'{rid_clean}.view.json')
        if not os.path.exists(vpath):
            with open(vpath, 'w', encoding='utf-8') as f:
                json.dump({
                    'race_id': str(race_id), 'ts': time.time(),
                    'meta': meta,
                    'columns': ['Umaban', 'Name', 'Popularity', 'Odds'],
                    'labels': {'Umaban': '馬番', 'Name': '馬名', 'Popularity': '人気', 'Odds': '単勝'},
                    'order': ['Umaban', 'Name', 'Popularity', 'Odds'],
                    'records': view_records,
                }, f, ensure_ascii=False)
    except Exception:
        pass

    # ── 10. 台帳登録 ──
    registered = tr.register_race(race_id)
    if verbose:
        print(f"  📝 台帳登録: {'✅ 新規登録' if registered else '⏭ 登録済み(スキップ)'}")

    return True


def fetch_all_results(verbose=True):
    """台帳内の未取得レースの結果を一括取得。"""
    from core import track_record as tr
    results = tr.fetch_results_batch()
    ok = sum(1 for v in results.values() if v[0])
    fail = sum(1 for v in results.values() if not v[0])
    if verbose:
        print(f"\n{'='*60}")
        print(f"  結果取得完了: ✅{ok}件 / ❌{fail}件")
        print(f"{'='*60}")
        for rid, (success, msg) in results.items():
            status = '✅' if success else '❌'
            print(f"  {status} {rid}: {msg}")
    return ok, fail


def print_summary():
    """台帳サマリーを表示。"""
    from core import track_record as tr
    print(f"\n{'='*60}")
    print("  📊 成績台帳サマリー")
    print(f"{'='*60}")
    print(tr.export_summary_text())
    print()
    monthly = tr.get_monthly_summary()
    if monthly:
        print("  月別:")
        for m in monthly:
            print(f"    {m['month']}: {m['races']}R | 軸{m['axis_rate']}% | "
                  f"3複{m['trio_rate']}%(ROI {m['trio_roi']}%) | "
                  f"3単{m['trifecta_rate']}%(ROI {m['trifecta_roi']}%)")


def main():
    parser = argparse.ArgumentParser(description='成績台帳バッチ: 過去メインレースの自動解析→台帳登録→結果取得')
    parser.add_argument('--grade', choices=['G1', 'G2', 'G3'], help='対象グレード')
    parser.add_argument('--ids', type=str, help='カンマ区切りのレースID')
    parser.add_argument('--fetch-only', action='store_true', help='解析せず結果取得のみ')
    parser.add_argument('--summary-only', action='store_true', help='サマリー表示のみ')
    parser.add_argument('--list', action='store_true', help='対象レース一覧を表示して終了')
    parser.add_argument('--no-fetch', action='store_true', help='結果取得をスキップ')
    parser.add_argument('--delay', type=float, default=3.0, help='レース間のwait秒(デフォルト3)')
    args = parser.parse_args()

    if args.summary_only:
        print_summary()
        return

    if args.fetch_only:
        fetch_all_results()
        print_summary()
        return

    # --list: 対象レース一覧を表示
    if args.list:
        rows = _load_graded_from_db(grade_filter=args.grade)
        print(f"📋 対象レース一覧 ({len(rows)}件):")
        for rid, g, name, d in rows:
            print(f"  {d[:4]}/{d[4:6]}/{d[6:8]}  {g}  {rid}  {name}")
        return

    race_ids = get_race_ids(args.grade, args.ids)
    if not race_ids:
        print("⚠ 対象レースがありません。--list で確認してください。")
        return
    print(f"📊 成績台帳バッチ開始: {len(race_ids)}レース")
    print(f"   ルール: 裁量ゼロ（全てコード判定）")
    print(f"   パイプライン: 出馬表→指数→エッジ→合議→買い目→登録")

    success = 0
    fail = 0
    for i, rid in enumerate(race_ids, 1):
        print(f"\n[{i}/{len(race_ids)}]", end='')
        try:
            if analyze_and_register(rid):
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ❌ 例外: {e}")
            fail += 1
        if i < len(race_ids):
            time.sleep(args.delay)

    print(f"\n\n{'='*60}")
    print(f"  解析完了: ✅{success}件 / ❌{fail}件")
    print(f"{'='*60}")

    if not args.no_fetch:
        print("\n⏳ 結果取得中…")
        fetch_all_results()

    print_summary()


if __name__ == '__main__':
    main()
