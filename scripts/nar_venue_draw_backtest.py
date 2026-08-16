# -*- coding: utf-8 -*-
"""南関4場の枠順バイアス検証(場別)。

keiba.go.jpの過去レース結果から枠番×人気帯の複勝残差をz検定。
川崎のみ既検証(内枠有利 z+2.55)。大井・船橋・浦和を追加検証。

結果はdata/nar_results_cache.jsonにキャッシュし再実行時はHTTPリクエストしない。
"""
import sys, os, io, json, time, math
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'nar_venue_draw_cache.json')
OLD_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'data', 'nar_results_cache.json')

# 各場5-10開催日(2026年)。取得済み分はキャッシュから読む
# keiba.go.jpは直近の開催日のみ保持(古すぎると"no race list")
TARGETS = [
    # 大井(20)
    ('2026/07/28', '20'), ('2026/07/27', '20'), ('2026/07/26', '20'),
    ('2026/07/23', '20'), ('2026/07/22', '20'), ('2026/07/21', '20'),
    ('2026/07/10', '20'), ('2026/07/09', '20'), ('2026/07/08', '20'),
    ('2026/05/19', '20'), ('2026/03/27', '20'), ('2026/03/23', '20'),
    # 船橋(19)
    ('2026/07/25', '19'), ('2026/07/24', '19'), ('2026/07/23', '19'),
    ('2026/07/16', '19'), ('2026/07/15', '19'), ('2026/07/14', '19'),
    ('2026/02/12', '19'), ('2026/02/11', '19'),
    # 浦和(18)
    ('2026/07/29', '18'), ('2026/07/28', '18'), ('2026/07/17', '18'),
    ('2026/07/16', '18'), ('2026/07/15', '18'), ('2026/07/14', '18'),
    ('2026/05/29', '18'), ('2026/05/28', '18'),
    ('2026/04/22', '18'), ('2026/04/21', '18'),
    # 川崎(21)
    ('2026/07/29', '21'), ('2026/07/28', '21'), ('2026/07/25', '21'),
    ('2026/07/24', '21'), ('2026/07/09', '21'), ('2026/07/08', '21'),
    ('2026/06/17', '21'),
]

VENUE_NAMES = {'18': '浦和', '19': '船橋', '20': '大井', '21': '川崎'}
POP_BANDS = [(1, 3), (4, 5), (6, 99)]


def load_cache():
    merged = {}
    for p in [OLD_CACHE, CACHE_PATH]:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    merged.update(json.load(f))
            except Exception:
                pass
    return merged


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def fetch_results():
    import core.nar_scraper as nar
    cache = load_cache()
    total_req = 0

    for date_str, baba_code in TARGETS:
        day_key = f"{date_str}_{baba_code}"
        if day_key in cache:
            continue

        if total_req > 0 and total_req % 80 == 0:
            nar.reset_session()
            print(f"  [reset] session reset at {total_req} reqs")

        race_list = nar.fetch_race_list(date_str, baba_code)
        total_req += 1
        if not race_list:
            print(f"  [skip] {day_key}: no race list")
            cache[day_key] = []
            save_cache(cache)
            continue

        day_results = []
        for race in race_list:
            rno = race.get('race_no', 0)
            if not rno:
                continue
            if total_req > 0 and total_req % 80 == 0:
                nar.reset_session()
                print(f"  [reset] session reset at {total_req} reqs")
            result = nar.fetch_race_result(date_str, baba_code, rno)
            total_req += 1
            if result and result.get('result'):
                day_results.append({
                    'date': date_str,
                    'baba_code': baba_code,
                    'race_no': rno,
                    'n_horses': len(result['result']),
                    'horses': result['result'],
                })
            time.sleep(0.5)

        cache[day_key] = day_results
        save_cache(cache)
        vn = VENUE_NAMES.get(baba_code, baba_code)
        print(f"  [fetch] {vn} {date_str}: {len(day_results)}R ({total_req} reqs)")

        if total_req >= 500:
            print("  [limit] 500 requests reached, stopping")
            break

    return cache


def pop_band(p):
    if p is None or p < 1:
        return None
    for lo, hi in POP_BANDS:
        if lo <= p <= hi:
            return (lo, hi)
    return None


def pop_label(b):
    if b is None:
        return '?'
    lo, hi = b
    if hi == 99:
        return f'{lo}+'
    return f'{lo}' if lo == hi else f'{lo}-{hi}'


def positional_third(umaban, n_horses):
    cutoff_inner = math.ceil(n_horses / 3)
    cutoff_outer = math.floor(2 * n_horses / 3)
    if umaban <= cutoff_inner:
        return 'inner'
    if umaban > cutoff_outer:
        return 'outer'
    return 'middle'


def z_prop(p1, n1, p2, n2):
    if n1 < 5 or n2 < 5:
        return 0.0
    pp = (p1 * n1 + p2 * n2) / (n1 + n2)
    if pp <= 0 or pp >= 1:
        return 0.0
    se = math.sqrt(pp * (1 - pp) * (1/n1 + 1/n2))
    return (p1 - p2) / se if se > 0 else 0.0


def analyze_venue(rows, venue_name):
    n_races = len(set((r['date'], r['race_no']) for r in rows))
    print(f'\n{"="*65}')
    print(f'  {venue_name}  ({n_races}R / {len(rows)}頭)')
    print(f'{"="*65}')

    # 人気帯別ベースライン
    bl = defaultdict(lambda: {'n': 0, 'h': 0})
    for r in rows:
        b = pop_band(r.get('popularity'))
        if b:
            bl[b]['n'] += 1
            if r['finish'] <= 3:
                bl[b]['h'] += 1
    base = {b: (s['h'] / s['n'] if s['n'] else 0.25) for b, s in bl.items()}

    print('\n[ベースライン]')
    for b in POP_BANDS:
        s = bl[b]
        print(f'  {pop_label(b)}人気: {s["h"]/s["n"]*100:.1f}% (n={s["n"]})')

    def expected(pop):
        b = pop_band(pop)
        return base.get(b, 0.25) if b else 0.25

    # 枠位置分類
    for r in rows:
        r['_pos'] = positional_third(r['umaban'], r['n_horses'])

    # ── 全体: 内vs中vs外 ──
    print('\n[全体] 枠位置別複勝率(人気補正残差):')
    for pos in ['inner', 'middle', 'outer']:
        sub = [r for r in rows if r['_pos'] == pos]
        if not sub:
            continue
        n = len(sub)
        hits = sum(1 for r in sub if r['finish'] <= 3)
        rate = hits / n
        exp_r = sum(expected(r.get('popularity')) for r in sub) / n
        resid = (rate - exp_r) * 100
        z = z_prop(rate, n, exp_r, n) if n >= 20 else 0
        sig = ' ★' if abs(z) >= 2 else ''
        jp = {'inner': '内枠', 'middle': '中枠', 'outer': '外枠'}[pos]
        print(f'  {jp}: 複勝{rate*100:.1f}% 期待{exp_r*100:.1f}% 残差{resid:+.1f}pp z={z:+.2f} (n={n}){sig}')

    # ── 人気帯×枠位置 ──
    print('\n[人気帯×枠位置] 複勝残差:')
    results = {}
    for b in POP_BANDS:
        for pos in ['inner', 'middle', 'outer']:
            sub = [r for r in rows if r['_pos'] == pos and pop_band(r.get('popularity')) == b]
            if len(sub) < 20:
                continue
            n = len(sub)
            hits = sum(1 for r in sub if r['finish'] <= 3)
            rate = hits / n
            exp_r = base.get(b, 0.25)
            resid = (rate - exp_r) * 100
            z = z_prop(rate, n, exp_r, n)
            sig = ' ★' if abs(z) >= 2 else ''
            jp = {'inner': '内', 'middle': '中', 'outer': '外'}[pos]
            print(f'  {pop_label(b)}人気×{jp}枠: 複勝{rate*100:.1f}% 残差{resid:+.1f}pp z={z:+.2f} (n={n}){sig}')
            results[(pop_label(b), pos)] = {'rate': rate, 'resid': resid, 'z': z, 'n': n}

    # ── 内vs外のz検定(JRA検証と同型) ──
    print('\n[JRA型検証] 外枠×本命 vs 内枠×本命(1-3人気):')
    out_h = [r for r in rows if r['_pos'] == 'outer' and r.get('popularity') and r['popularity'] <= 3]
    inn_h = [r for r in rows if r['_pos'] == 'inner' and r.get('popularity') and r['popularity'] <= 3]
    if len(out_h) >= 20 and len(inn_h) >= 20:
        r_o = sum(1 for r in out_h if r['finish'] <= 3) / len(out_h)
        r_i = sum(1 for r in inn_h if r['finish'] <= 3) / len(inn_h)
        z = z_prop(r_o, len(out_h), r_i, len(inn_h))
        print(f'  外枠×1-3人気: {r_o*100:.1f}% (n={len(out_h)})')
        print(f'  内枠×1-3人気: {r_i*100:.1f}% (n={len(inn_h)})')
        print(f'  差分: {(r_o-r_i)*100:+.1f}pp  z={z:+.2f}')
    else:
        print('  標本不足')

    print('\n[JRA型検証] 内枠×中位人気 vs 外枠×中位人気(4-5人気):')
    inn_m = [r for r in rows if r['_pos'] == 'inner' and r.get('popularity') and 4 <= r['popularity'] <= 5]
    out_m = [r for r in rows if r['_pos'] == 'outer' and r.get('popularity') and 4 <= r['popularity'] <= 5]
    if len(inn_m) >= 20 and len(out_m) >= 20:
        r_i = sum(1 for r in inn_m if r['finish'] <= 3) / len(inn_m)
        r_o = sum(1 for r in out_m if r['finish'] <= 3) / len(out_m)
        z = z_prop(r_i, len(inn_m), r_o, len(out_m))
        print(f'  内枠×4-5人気: {r_i*100:.1f}% (n={len(inn_m)})')
        print(f'  外枠×4-5人気: {r_o*100:.1f}% (n={len(out_m)})')
        print(f'  差分: {(r_i-r_o)*100:+.1f}pp  z={z:+.2f}')
    else:
        print('  標本不足')

    # ── 逃げ馬の脚質バイアス ──
    print('\n[脚質] 逃げ/先行/差し追込の複勝率:')
    for style_name, style_test in [('逃', lambda p: p == 1),
                                    ('先行', lambda p: 2 <= p <= 3),
                                    ('差追', lambda p: p >= 4)]:
        sub = []
        for r in rows:
            ps = r.get('passing', '')
            if not ps:
                continue
            try:
                p1 = int(ps.split('-')[0])
            except (ValueError, IndexError):
                continue
            if style_test(p1):
                sub.append(r)
        if len(sub) < 20:
            continue
        n = len(sub)
        hits = sum(1 for r in sub if r['finish'] <= 3)
        rate = hits / n
        win = sum(1 for r in sub if r['finish'] == 1) / n
        print(f'  {style_name}: 勝率{win*100:.1f}% 複勝率{rate*100:.1f}% (n={n})')

    return results


def main():
    print('=' * 65)
    print('  南関4場 枠順バイアス検証(場別)')
    print('=' * 65)

    # データ取得
    cache = fetch_results()

    # 場別に分析
    venue_rows = defaultdict(list)
    for day_key, races in cache.items():
        parts = day_key.split('_')
        if len(parts) < 2:
            continue
        bc = parts[1]
        if bc not in VENUE_NAMES:
            continue
        for race in races:
            if race['n_horses'] < 6:
                continue
            for h in race['horses']:
                h['date'] = race['date']
                h['race_no'] = race['race_no']
                h['n_horses'] = race['n_horses']
                h['baba_code'] = bc
                venue_rows[bc].append(h)

    all_results = {}
    for bc in ['20', '19', '18', '21']:
        vn = VENUE_NAMES[bc]
        if venue_rows[bc]:
            r = analyze_venue(venue_rows[bc], vn)
            all_results[vn] = r
        else:
            print(f'\n  {vn}: データなし')

    # ── 総合まとめ ──
    print(f'\n{"="*65}')
    print('  総合まとめ: 場×枠のエッジ一覧(|z|≥2のみ)')
    print(f'{"="*65}')
    found = False
    for vn, r in all_results.items():
        for (pop_l, pos), s in r.items():
            if abs(s['z']) >= 2:
                jp = {'inner': '内枠', 'middle': '中枠', 'outer': '外枠'}[pos]
                direction = '有利' if s['resid'] > 0 else '不利'
                print(f'  {vn} {pop_l}人気×{jp}: 残差{s["resid"]:+.1f}pp z={s["z"]:+.2f} (n={s["n"]}) → {direction}')
                found = True
    if not found:
        print('  有意なエッジなし')


if __name__ == '__main__':
    main()
