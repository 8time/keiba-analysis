"""卍氏ファクターの未検証2項目を検証。

1. 芝×馬体重が重い馬の加点(卍: 芝で重い馬は回収率が高い)
2. 遠征バイアス(関東馬が関西場へ/関西馬が関東場へ)

データ: jravan.db results (2016-2025, ~25万頭)
"""
import sys, os, math, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'data', 'jravan.db')

EAST_VENUES = {'01', '02', '03', '04', '05'}  # 札幌/函館/福島/新潟/東京/中山
WEST_VENUES = {'06', '07', '08', '09', '10'}  # 中京/京都/阪神/小倉/...

# jyo codes: 01札幌 02函館 03福島 04新潟 05東京 06中山 07中京 08京都 09阪神 10小倉
# Actually: 01札幌 02函館 03福島 04新潟 05東京 06中山 07中京 08京都 09阪神 10小倉
# East = 01-06 (札幌/函館/福島/新潟/東京/中山)
# West = 07-10 (中京/京都/阪神/小倉)
# tozai in results: 1=関東, 2=関西, etc.

def z_test(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return 0.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    return (p1 - p2) / se if se > 0 else 0.0


def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get race surface from races table
    races = {}
    for r in conn.execute("""
        SELECT race_key, jyo,
               CASE WHEN track_code IN ('10','11','12','13','14','15','16','17') THEN 'turf'
                    WHEN track_code IN ('20','21','22','23','24','25','26','27') THEN 'dirt'
                    ELSE 'other' END as surface
        FROM races WHERE year >= 2016 AND year <= 2025
    """):
        races[r['race_key']] = {'jyo': r['jyo'], 'surface': r['surface']}

    rows = conn.execute("""
        SELECT race_key, ketto_num, bataiju, zogen, chakujun, ninki, tozai, jyo
        FROM results
        WHERE race_key IN (SELECT race_key FROM races WHERE year >= 2016 AND year <= 2025)
          AND chakujun > 0 AND chakujun < 30
          AND ninki > 0
          AND bataiju > 0
    """).fetchall()
    conn.close()
    return races, rows


def venue_region(jyo):
    """場コードから東西を判定。"""
    j = int(jyo) if jyo else 0
    if j <= 6:
        return 'east'
    else:
        return 'west'


def horse_region(tozai):
    """tozai列(1=関東, 2=関西, etc.)から所属を判定。"""
    t = str(tozai).strip()
    if t == '1':
        return 'east'
    elif t == '2':
        return 'west'
    return 'other'


def analyze_weight_turf(races, rows):
    """検証1: 芝×馬体重が重い馬の加点。"""
    print(f"\n{'='*70}")
    print("検証1: 芝×馬体重(重い馬は回収率が高いか)")
    print(f"{'='*70}")

    # 芝レースのみ
    turf_rows = [r for r in rows if races.get(r['race_key'], {}).get('surface') == 'turf']
    print(f"芝レース: {len(turf_rows)} 頭")

    # 体重帯別
    weight_bands = {}
    for r in turf_rows:
        w = r['bataiju']
        finish = r['chakujun']
        pop = r['ninki']
        is_top3 = finish <= 3

        if w < 420:
            wb = '~419'
        elif w < 440:
            wb = '420-439'
        elif w < 460:
            wb = '440-459'
        elif w < 480:
            wb = '460-479'
        elif w < 500:
            wb = '480-499'
        elif w < 520:
            wb = '500-519'
        else:
            wb = '520+'

        if wb not in weight_bands:
            weight_bands[wb] = {'n': 0, 'top3': 0, 'win': 0, 'pops': []}
        weight_bands[wb]['n'] += 1
        if is_top3:
            weight_bands[wb]['top3'] += 1
        if finish == 1:
            weight_bands[wb]['win'] += 1
        weight_bands[wb]['pops'].append(pop)

    print(f"\n■ 芝: 体重帯別(単調性チェック)")
    print(f"{'体重帯':>10} {'頭数':>8} {'勝率':>8} {'複勝率':>8} {'平均人気':>8}")
    ordered = ['~419', '420-439', '440-459', '460-479', '480-499', '500-519', '520+']
    for wb in ordered:
        if wb in weight_bands:
            g = weight_bands[wb]
            wr = g['win'] / g['n'] * 100
            sr = g['top3'] / g['n'] * 100
            avg_pop = sum(g['pops']) / len(g['pops'])
            print(f"{wb:>10} {g['n']:>8} {wr:>7.1f}% {sr:>7.1f}% {avg_pop:>7.1f}")

    # 人気帯別で重い vs 軽い
    print(f"\n■ 芝: 人気帯別 × 馬体重(織込みチェック)")
    print(f"{'人気帯':>8} {'体重':>6} {'頭数':>8} {'複勝率':>8}")
    pop_weight = {}
    for r in turf_rows:
        w = r['bataiju']
        pop = r['ninki']
        finish = r['chakujun']
        is_top3 = finish <= 3

        if pop <= 3:
            pb = '1-3人気'
        elif pop <= 6:
            pb = '4-6人気'
        else:
            pb = '7人気+'

        wc = '重(480+)' if w >= 480 else '軽(<480)'
        pk = (pb, wc)
        if pk not in pop_weight:
            pop_weight[pk] = {'n': 0, 'top3': 0}
        pop_weight[pk]['n'] += 1
        if is_top3:
            pop_weight[pk]['top3'] += 1

    for pb in ['1-3人気', '4-6人気', '7人気+']:
        for wc in ['重(480+)', '軽(<480)']:
            pk = (pb, wc)
            if pk in pop_weight:
                g = pop_weight[pk]
                sr = g['top3'] / g['n'] * 100
                print(f"{pb:>8} {wc:>6} {g['n']:>8} {sr:>7.1f}%")
        g_h = pop_weight.get((pb, '重(480+)'), {'n': 0, 'top3': 0})
        g_l = pop_weight.get((pb, '軽(<480)'), {'n': 0, 'top3': 0})
        if g_h['n'] and g_l['n']:
            z = z_test(g_h['top3']/g_h['n'], g_h['n'], g_l['top3']/g_l['n'], g_l['n'])
            diff = (g_h['top3']/g_h['n'] - g_l['top3']/g_l['n']) * 100
            print(f"  → {pb}内 重vs軽 複勝差{diff:+.1f}pp z={z:+.2f}")

    # train/holdout split
    print(f"\n■ 期間別(両窓チェック): train(2016-2023) / holdout(2024-2025)")
    for period_name, year_range in [('train', range(2016, 2024)), ('holdout', range(2024, 2026))]:
        period_rows = [r for r in turf_rows if int(r['race_key'][:4]) in year_range]
        heavy = {'n': 0, 'top3': 0}
        light = {'n': 0, 'top3': 0}
        for r in period_rows:
            w = r['bataiju']
            pop = r['ninki']
            if pop > 6:
                grp = heavy if w >= 480 else light
                grp['n'] += 1
                if r['chakujun'] <= 3:
                    grp['top3'] += 1
        if heavy['n'] and light['n']:
            z = z_test(heavy['top3']/heavy['n'], heavy['n'], light['top3']/light['n'], light['n'])
            diff = (heavy['top3']/heavy['n'] - light['top3']/light['n']) * 100
            sr_h = heavy['top3']/heavy['n']*100
            sr_l = light['top3']/light['n']*100
            print(f"  {period_name} 7人気+: 重{sr_h:.1f}% vs 軽{sr_l:.1f}% diff={diff:+.1f}pp z={z:+.2f}")


def analyze_expedition(races, rows):
    """検証2: 遠征バイアス。"""
    print(f"\n{'='*70}")
    print("検証2: 遠征バイアス(関東馬が関西場へ / 関西馬が関東場へ)")
    print(f"{'='*70}")

    groups = {}  # key=(expedition_type) → stats
    pop_groups = {}

    for r in rows:
        race_info = races.get(r['race_key'])
        if not race_info:
            continue

        h_region = horse_region(r['tozai'])
        v_region = venue_region(race_info['jyo'])

        if h_region == 'other':
            continue

        if h_region == v_region:
            exp = '地元'
        else:
            exp = '遠征'

        finish = r['chakujun']
        pop = r['ninki']
        is_top3 = finish <= 3

        if exp not in groups:
            groups[exp] = {'n': 0, 'top3': 0, 'win': 0, 'pops': []}
        groups[exp]['n'] += 1
        if is_top3:
            groups[exp]['top3'] += 1
        if finish == 1:
            groups[exp]['win'] += 1
        groups[exp]['pops'].append(pop)

        if pop <= 3:
            pb = '1-3人気'
        elif pop <= 6:
            pb = '4-6人気'
        else:
            pb = '7人気+'
        pk = (pb, exp)
        if pk not in pop_groups:
            pop_groups[pk] = {'n': 0, 'top3': 0}
        pop_groups[pk]['n'] += 1
        if is_top3:
            pop_groups[pk]['top3'] += 1

    total = sum(g['n'] for g in groups.values())
    print(f"対象: {total} 頭")

    print(f"\n■ 全体: 地元 vs 遠征")
    print(f"{'区分':>8} {'頭数':>8} {'勝率':>8} {'複勝率':>8} {'平均人気':>8}")
    for label in ['地元', '遠征']:
        if label in groups:
            g = groups[label]
            wr = g['win'] / g['n'] * 100
            sr = g['top3'] / g['n'] * 100
            avg_pop = sum(g['pops']) / len(g['pops'])
            print(f"{label:>8} {g['n']:>8} {wr:>7.1f}% {sr:>7.1f}% {avg_pop:>7.1f}")

    if '地元' in groups and '遠征' in groups:
        g_h = groups['地元']
        g_a = groups['遠征']
        z_w = z_test(g_h['win']/g_h['n'], g_h['n'], g_a['win']/g_a['n'], g_a['n'])
        z_s = z_test(g_h['top3']/g_h['n'], g_h['n'], g_a['top3']/g_a['n'], g_a['n'])
        diff_w = (g_h['win']/g_h['n'] - g_a['win']/g_a['n']) * 100
        diff_s = (g_h['top3']/g_h['n'] - g_a['top3']/g_a['n']) * 100
        print(f"  地元vs遠征: 勝率{diff_w:+.1f}pp 複勝率{diff_s:+.1f}pp")
        print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")

    print(f"\n■ 人気帯別(織込みチェック)")
    print(f"{'人気帯':>8} {'区分':>6} {'頭数':>8} {'複勝率':>8}")
    for pb in ['1-3人気', '4-6人気', '7人気+']:
        for exp in ['地元', '遠征']:
            pk = (pb, exp)
            if pk in pop_groups:
                g = pop_groups[pk]
                sr = g['top3'] / g['n'] * 100
                print(f"{pb:>8} {exp:>6} {g['n']:>8} {sr:>7.1f}%")
        g_h = pop_groups.get((pb, '地元'), {'n': 0, 'top3': 0})
        g_a = pop_groups.get((pb, '遠征'), {'n': 0, 'top3': 0})
        if g_h['n'] and g_a['n']:
            z = z_test(g_h['top3']/g_h['n'], g_h['n'], g_a['top3']/g_a['n'], g_a['n'])
            diff = (g_h['top3']/g_h['n'] - g_a['top3']/g_a['n']) * 100
            print(f"  → {pb}内 地元vs遠征 複勝差{diff:+.1f}pp z={z:+.2f}")

    # train/holdout
    print(f"\n■ 期間別(両窓チェック)")
    for period_name, year_range in [('train(16-23)', range(2016, 2024)), ('holdout(24-25)', range(2024, 2026))]:
        period_rows = [r for r in rows if int(r['race_key'][:4]) in year_range]
        home = {'n': 0, 'top3': 0}
        away = {'n': 0, 'top3': 0}
        for r in period_rows:
            race_info = races.get(r['race_key'])
            if not race_info:
                continue
            h_region = horse_region(r['tozai'])
            v_region = venue_region(race_info['jyo'])
            if h_region == 'other':
                continue
            grp = home if h_region == v_region else away
            grp['n'] += 1
            if r['chakujun'] <= 3:
                grp['top3'] += 1
        if home['n'] and away['n']:
            z = z_test(home['top3']/home['n'], home['n'], away['top3']/away['n'], away['n'])
            diff = (home['top3']/home['n'] - away['top3']/away['n']) * 100
            sr_h = home['top3']/home['n']*100
            sr_a = away['top3']/away['n']*100
            print(f"  {period_name}: 地元{sr_h:.1f}% vs 遠征{sr_a:.1f}% diff={diff:+.1f}pp z={z:+.2f}")

    # direction detail
    print(f"\n■ 遠征方向の詳細")
    dir_groups = {}
    for r in rows:
        race_info = races.get(r['race_key'])
        if not race_info:
            continue
        h_region = horse_region(r['tozai'])
        v_region = venue_region(race_info['jyo'])
        if h_region == 'other':
            continue
        if h_region == v_region:
            continue
        direction = f"{'関東' if h_region == 'east' else '関西'}→{'関東' if v_region == 'east' else '関西'}"
        if direction not in dir_groups:
            dir_groups[direction] = {'n': 0, 'top3': 0, 'pops': []}
        dir_groups[direction]['n'] += 1
        if r['chakujun'] <= 3:
            dir_groups[direction]['top3'] += 1
        dir_groups[direction]['pops'].append(r['ninki'])

    print(f"{'方向':>12} {'頭数':>8} {'複勝率':>8} {'平均人気':>8}")
    for d in ['関東→関西', '関西→関東']:
        if d in dir_groups:
            g = dir_groups[d]
            sr = g['top3'] / g['n'] * 100
            avg_pop = sum(g['pops']) / len(g['pops'])
            print(f"{d:>12} {g['n']:>8} {sr:>7.1f}% {avg_pop:>7.1f}")


if __name__ == '__main__':
    print("jravan.dbからデータ読込中...")
    races, rows = load_data()
    print(f"読込完了: {len(rows)} 頭 / {len(races)} レース")
    analyze_weight_turf(races, rows)
    analyze_expedition(races, rows)
