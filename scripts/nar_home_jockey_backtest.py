"""NAR 庭騎手(地元所属×当場)バイアスの検証バックテスト。

キャッシュ済みの南関東4場レース結果(data/nar_results_cache.json)を使用。
騎手の所属場 = 開催場（庭騎手）が勝率・複勝率で有利かを検証する。
追加のHTTPリクエストは不要。
"""
import sys, os, json, math, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'nar_results_cache.json')

BABA_TO_VENUE = {
    '18': '浦和', '19': '船橋', '20': '大井', '21': '川崎',
    '24': '名古屋', '36': '門別',
}


def z_test(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return 0.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    return (p1 - p2) / se if se > 0 else 0.0


def extract_jockey_venue(jockey_str):
    """騎手名文字列から所属場名を抽出。例: '櫻井光 （川崎）' → '川崎'"""
    m = re.search(r'[（(]([^）)]+)[）)]', jockey_str or '')
    if m:
        return m.group(1).strip()
    return ''


def analyze():
    with open(CACHE_PATH, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    home = {'n': 0, 'win': 0, 'show': 0, 'pops': []}
    away = {'n': 0, 'win': 0, 'show': 0, 'pops': []}
    jra  = {'n': 0, 'win': 0, 'show': 0, 'pops': []}

    pop_bands = {}
    venue_stats = {}

    total_races = 0

    for day_key, races in cache.items():
        for race in races:
            n_horses = race['n_horses']
            if n_horses < 6:
                continue
            total_races += 1
            baba = race.get('baba_code', '')
            race_venue = BABA_TO_VENUE.get(baba, '')

            for h in race['horses']:
                finish = h.get('finish', 99)
                pop = h.get('popularity', 99)
                is_win = finish == 1
                is_show = finish <= 3

                jockey_venue = extract_jockey_venue(h.get('jockey', ''))

                if not jockey_venue:
                    continue

                if jockey_venue == 'JRA':
                    grp = jra
                    cat = 'JRA'
                elif jockey_venue == race_venue:
                    grp = home
                    cat = '庭'
                else:
                    grp = away
                    cat = '遠征'

                grp['n'] += 1
                if is_win:
                    grp['win'] += 1
                if is_show:
                    grp['show'] += 1
                if pop < 99:
                    grp['pops'].append(pop)

                if pop <= 3:
                    pb = '1-3人気'
                elif pop <= 6:
                    pb = '4-6人気'
                else:
                    pb = '7人気+'
                pk = (pb, cat)
                if pk not in pop_bands:
                    pop_bands[pk] = {'n': 0, 'win': 0, 'show': 0}
                pop_bands[pk]['n'] += 1
                if is_win:
                    pop_bands[pk]['win'] += 1
                if is_show:
                    pop_bands[pk]['show'] += 1

                vk = (race_venue, cat)
                if vk not in venue_stats:
                    venue_stats[vk] = {'n': 0, 'win': 0, 'show': 0}
                venue_stats[vk]['n'] += 1
                if is_win:
                    venue_stats[vk]['win'] += 1
                if is_show:
                    venue_stats[vk]['show'] += 1

    total = home['n'] + away['n'] + jra['n']

    print(f"{'='*70}")
    print(f"NAR 庭騎手(地元所属×当場)バイアス検証")
    print(f"{'='*70}")
    print(f"対象: {total_races} R / {total} 頭")

    print(f"\n■ 全体: 庭 vs 遠征 vs JRA")
    print(f"{'カテゴリ':>8} {'頭数':>6} {'勝率':>8} {'複勝率':>8} {'平均人気':>8}")
    for label, g in [('庭(地元)', home), ('遠征', away), ('JRA', jra)]:
        wr = g['win'] / g['n'] * 100 if g['n'] else 0
        sr = g['show'] / g['n'] * 100 if g['n'] else 0
        avg_pop = sum(g['pops']) / len(g['pops']) if g['pops'] else 0
        print(f"{label:>8} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}% {avg_pop:>7.1f}")

    if home['n'] and away['n']:
        z_w = z_test(home['win']/home['n'], home['n'], away['win']/away['n'], away['n'])
        z_s = z_test(home['show']/home['n'], home['n'], away['show']/away['n'], away['n'])
        diff_w = (home['win']/home['n'] - away['win']/away['n']) * 100
        diff_s = (home['show']/home['n'] - away['show']/away['n']) * 100
        print(f"  庭vs遠征: 勝率{diff_w:+.1f}pp 複勝率{diff_s:+.1f}pp")
        print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")

    if home['n'] and jra['n']:
        z_w = z_test(home['win']/home['n'], home['n'], jra['win']/jra['n'], jra['n'])
        z_s = z_test(home['show']/home['n'], home['n'], jra['show']/jra['n'], jra['n'])
        diff_w = (home['win']/home['n'] - jra['win']/jra['n']) * 100
        diff_s = (home['show']/home['n'] - jra['show']/jra['n']) * 100
        print(f"  庭vsJRA: 勝率{diff_w:+.1f}pp 複勝率{diff_s:+.1f}pp")
        print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")

    print(f"\n■ 人気帯別(織込みチェック)")
    print(f"{'人気帯':>8} {'カテゴリ':>6} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for pb in ['1-3人気', '4-6人気', '7人気+']:
        for cat in ['庭', '遠征', 'JRA']:
            pk = (pb, cat)
            if pk in pop_bands:
                g = pop_bands[pk]
                wr = g['win'] / g['n'] * 100 if g['n'] else 0
                sr = g['show'] / g['n'] * 100 if g['n'] else 0
                print(f"{pb:>8} {cat:>6} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")
        g_h = pop_bands.get((pb, '庭'), {'n': 0, 'win': 0, 'show': 0})
        g_a = pop_bands.get((pb, '遠征'), {'n': 0, 'win': 0, 'show': 0})
        if g_h['n'] > 0 and g_a['n'] > 0:
            z = z_test(g_h['show']/g_h['n'], g_h['n'], g_a['show']/g_a['n'], g_a['n'])
            diff = (g_h['show']/g_h['n'] - g_a['show']/g_a['n']) * 100
            print(f"  → {pb}内 庭vs遠征 複勝差{diff:+.1f}pp z={z:+.2f}")

    print(f"\n■ 場別(庭vs遠征)")
    print(f"{'場':>6} {'カテゴリ':>6} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for venue in ['川崎', '大井', '浦和', '船橋']:
        for cat in ['庭', '遠征']:
            vk = (venue, cat)
            if vk in venue_stats:
                g = venue_stats[vk]
                wr = g['win'] / g['n'] * 100 if g['n'] else 0
                sr = g['show'] / g['n'] * 100 if g['n'] else 0
                print(f"{venue:>6} {cat:>6} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")

    print(f"\n{'='*70}")
    print("■ 判定")
    avg_pop_h = sum(home['pops']) / len(home['pops']) if home['pops'] else 0
    avg_pop_a = sum(away['pops']) / len(away['pops']) if away['pops'] else 0
    print(f"  庭騎手 平均{avg_pop_h:.1f}人気 / 遠征騎手 平均{avg_pop_a:.1f}人気")
    if home['n'] and away['n']:
        z_final = z_test(home['show']/home['n'], home['n'], away['show']/away['n'], away['n'])
        if abs(z_final) >= 2:
            if avg_pop_h < avg_pop_a - 0.3:
                print("  庭騎手は有利だが市場に織込み済み(人気で補正されている)")
            else:
                print("  庭騎手は有利かつ市場に織込まれていない(エッジあり)")
        else:
            print("  庭騎手の有利は有意でない(|z|<2)")


if __name__ == '__main__':
    analyze()
