"""NAR 大型馬(500kg+)バイアスの検証バックテスト。

キャッシュ済みの南関東4場レース結果(data/nar_results_cache.json)を使用。
馬体重500kg+の馬が勝率・複勝率で有利かを検証する。
追加のHTTPリクエストは不要。
"""
import sys, os, json, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'nar_results_cache.json')


def z_test(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return 0.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    return (p1 - p2) / se if se > 0 else 0.0


def analyze():
    with open(CACHE_PATH, 'r', encoding='utf-8') as f:
        cache = json.load(f)

    # ── 1. 全体: 500kg+ vs <500kg ──
    big = {'n': 0, 'win': 0, 'show': 0, 'pops': []}
    small = {'n': 0, 'win': 0, 'show': 0, 'pops': []}

    # ── 2. 人気帯別 ──
    pop_bands = {}  # key=(pop_band, size_cat) → {'n','win','show'}

    # ── 3. 体重カテゴリ(細分化) ──
    weight_cats = {}  # key=weight_cat → {'n','win','show'}

    total_races = 0

    for day_key, races in cache.items():
        for race in races:
            n_horses = race['n_horses']
            if n_horses < 6:
                continue
            total_races += 1
            for h in race['horses']:
                w = h.get('weight')
                if not w or w <= 0:
                    continue
                finish = h.get('finish', 99)
                pop = h.get('popularity', 99)
                is_win = finish == 1
                is_show = finish <= 3

                # 全体
                grp = big if w >= 500 else small
                grp['n'] += 1
                if is_win:
                    grp['win'] += 1
                if is_show:
                    grp['show'] += 1
                if pop < 99:
                    grp['pops'].append(pop)

                # 人気帯別
                if pop <= 3:
                    pb = '1-3人気'
                elif pop <= 6:
                    pb = '4-6人気'
                else:
                    pb = '7人気+'
                sc = '500+' if w >= 500 else '<500'
                pk = (pb, sc)
                if pk not in pop_bands:
                    pop_bands[pk] = {'n': 0, 'win': 0, 'show': 0}
                pop_bands[pk]['n'] += 1
                if is_win:
                    pop_bands[pk]['win'] += 1
                if is_show:
                    pop_bands[pk]['show'] += 1

                # 体重カテゴリ
                if w < 440:
                    wc = '~439'
                elif w < 460:
                    wc = '440-459'
                elif w < 480:
                    wc = '460-479'
                elif w < 500:
                    wc = '480-499'
                elif w < 520:
                    wc = '500-519'
                else:
                    wc = '520+'
                if wc not in weight_cats:
                    weight_cats[wc] = {'n': 0, 'win': 0, 'show': 0}
                weight_cats[wc]['n'] += 1
                if is_win:
                    weight_cats[wc]['win'] += 1
                if is_show:
                    weight_cats[wc]['show'] += 1

    total_horses = big['n'] + small['n']

    print(f"{'='*70}")
    print(f"NAR 大型馬(500kg+)バイアス検証")
    print(f"{'='*70}")
    print(f"対象: {total_races} R / {total_horses} 頭")

    # ── 1. 全体 ──
    print(f"\n■ 全体: 500kg+ vs <500kg")
    print(f"{'カテゴリ':>10} {'頭数':>6} {'勝率':>8} {'複勝率':>8} {'平均人気':>8}")
    for label, g in [('500kg+', big), ('<500kg', small)]:
        wr = g['win'] / g['n'] * 100 if g['n'] else 0
        sr = g['show'] / g['n'] * 100 if g['n'] else 0
        avg_pop = sum(g['pops']) / len(g['pops']) if g['pops'] else 0
        print(f"{label:>10} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}% {avg_pop:>7.1f}")
    z_w = z_test(big['win']/big['n'], big['n'], small['win']/small['n'], small['n'])
    z_s = z_test(big['show']/big['n'], big['n'], small['show']/small['n'], small['n'])
    diff_w = (big['win']/big['n'] - small['win']/small['n']) * 100
    diff_s = (big['show']/big['n'] - small['show']/small['n']) * 100
    print(f"  差分: 勝率{diff_w:+.1f}pp  複勝率{diff_s:+.1f}pp")
    print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")

    # ── 2. 体重カテゴリ別 ──
    print(f"\n■ 体重カテゴリ別(単調性チェック)")
    print(f"{'体重帯':>10} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for wc in ['~439', '440-459', '460-479', '480-499', '500-519', '520+']:
        if wc in weight_cats:
            g = weight_cats[wc]
            wr = g['win'] / g['n'] * 100 if g['n'] else 0
            sr = g['show'] / g['n'] * 100 if g['n'] else 0
            print(f"{wc:>10} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")

    # ── 3. 人気帯別(織込み度チェック) ──
    print(f"\n■ 人気帯別(織込み度チェック)")
    print(f"{'人気帯':>8} {'カテゴリ':>6} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for pb in ['1-3人気', '4-6人気', '7人気+']:
        for sc in ['500+', '<500']:
            pk = (pb, sc)
            if pk in pop_bands:
                g = pop_bands[pk]
                wr = g['win'] / g['n'] * 100 if g['n'] else 0
                sr = g['show'] / g['n'] * 100 if g['n'] else 0
                print(f"{pb:>8} {sc:>6} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")
        # z-test within each pop band
        g_b = pop_bands.get((pb, '500+'), {'n': 0, 'win': 0, 'show': 0})
        g_s = pop_bands.get((pb, '<500'), {'n': 0, 'win': 0, 'show': 0})
        if g_b['n'] > 0 and g_s['n'] > 0:
            z = z_test(g_b['show']/g_b['n'], g_b['n'], g_s['show']/g_s['n'], g_s['n'])
            diff = (g_b['show']/g_b['n'] - g_s['show']/g_s['n']) * 100
            print(f"  → {pb}内 500+ vs <500 複勝差{diff:+.1f}pp z={z:+.2f}")

    # ── 4. 判定 ──
    print(f"\n{'='*70}")
    print("■ 判定")
    avg_pop_big = sum(big['pops']) / len(big['pops']) if big['pops'] else 0
    avg_pop_small = sum(small['pops']) / len(small['pops']) if small['pops'] else 0
    if abs(z_s) >= 2:
        if avg_pop_big < avg_pop_small - 0.5:
            print("  大型馬は有利だが市場に織込み済み(過剰人気の可能性)")
        else:
            print("  大型馬は有利かつ市場に織込まれていない(エッジあり)")
    else:
        print("  大型馬の有利は有意でない(|z|<2)")
    print(f"  参考: 500+平均{avg_pop_big:.1f}人気 vs <500平均{avg_pop_small:.1f}人気")


if __name__ == '__main__':
    analyze()
