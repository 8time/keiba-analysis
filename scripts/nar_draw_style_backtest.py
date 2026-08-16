"""NAR 逃げ×内枠バイアスの検証バックテスト。

keiba.go.jpの過去レース結果を取得し、
枠番(内/中/外) × 1角通過順(逃げ/先行/差し追込) の勝率・複勝率を検証する。

結果はdata/nar_results_cache.jsonにキャッシュし、再実行時はHTTPリクエストしない。
"""
import sys, os, json, time, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'nar_results_cache.json')

# 検証対象: 南関東4場の直近開催日
# 川崎21, 大井20, 浦和18, 船橋19
TARGETS = [
    # 川崎(21) — キャッシュ済み
    ('2026/07/09', '21'),
    ('2026/06/17', '21'),
    ('2026/07/08', '21'),
    # 大井(20)
    ('2026/05/19', '20'),
    ('2026/03/27', '20'),
    ('2026/03/23', '20'),
    # 浦和(18)
    ('2026/04/22', '18'),
    ('2026/04/21', '18'),
    # 船橋(19)
    ('2026/02/12', '19'),
    ('2026/02/11', '19'),
]


def load_cache():
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def fetch_results():
    """結果データを取得(キャッシュ優先)。"""
    import core.nar_scraper as nar

    cache = load_cache()
    total_fetched = 0

    for date_str, baba_code in TARGETS:
        day_key = f"{date_str}_{baba_code}"
        if day_key in cache:
            print(f"  [cache] {day_key}: {len(cache[day_key])} races")
            continue

        # レース一覧を取得
        race_list = nar.fetch_race_list(date_str, baba_code)
        if not race_list:
            print(f"  [skip] {day_key}: no race list")
            continue
        total_fetched += 1

        day_results = []
        for race in race_list:
            rno = race.get('race_no', 0)
            if not rno:
                continue
            result = nar.fetch_race_result(date_str, baba_code, rno)
            total_fetched += 1
            if result and result.get('result'):
                day_results.append({
                    'date': date_str,
                    'baba_code': baba_code,
                    'race_no': rno,
                    'n_horses': len(result['result']),
                    'horses': result['result'],
                })
            if total_fetched >= 90:
                print(f"  [limit] stopping at {total_fetched} requests")
                break

        cache[day_key] = day_results
        print(f"  [fetch] {day_key}: {len(day_results)} races ({total_fetched} reqs)")

        if total_fetched >= 90:
            break

    save_cache(cache)
    return cache


def classify_position(passing_str, n_horses):
    """通過順文字列の1角位置から脚質を判定する。"""
    if not passing_str:
        return '?'
    parts = passing_str.split('-')
    try:
        pos1 = int(parts[0])
    except ValueError:
        return '?'
    if pos1 == 1:
        return '逃'
    elif pos1 <= max(3, n_horses // 3):
        return '先'
    else:
        return '差追'


def classify_draw(waku, max_waku):
    """枠番を内/中/外に分類。"""
    if max_waku <= 4:
        return '内' if waku <= 2 else '外'
    third = max_waku / 3
    if waku <= third:
        return '内'
    elif waku <= third * 2:
        return '中'
    else:
        return '外'


def z_test_proportions(p1, n1, p2, n2):
    """2群の比率の差のz検定。"""
    if n1 == 0 or n2 == 0:
        return 0.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    if se == 0:
        return 0.0
    return (p1 - p2) / se


def analyze(cache):
    """枠番×脚質の勝率・複勝率を集計。"""
    # 集計用
    groups = {}  # key=(draw_cat, style_cat) → {'n':int, 'win':int, 'show':int}

    total_horses = 0
    total_races = 0

    for day_key, races in cache.items():
        for race in races:
            n_horses = race['n_horses']
            if n_horses < 6:
                continue
            total_races += 1

            max_waku = max(h.get('waku', 1) for h in race['horses'])
            for h in race['horses']:
                waku = h.get('waku', 0)
                finish = h.get('finish', 99)
                passing = h.get('passing', '')

                draw_cat = classify_draw(waku, max_waku)
                style_cat = classify_position(passing, n_horses)

                key = (draw_cat, style_cat)
                if key not in groups:
                    groups[key] = {'n': 0, 'win': 0, 'show': 0}
                groups[key]['n'] += 1
                if finish == 1:
                    groups[key]['win'] += 1
                if finish <= 3:
                    groups[key]['show'] += 1
                total_horses += 1

    print(f"\n{'='*70}")
    print(f"NAR 逃げ×内枠バイアス検証")
    print(f"{'='*70}")
    print(f"対象: {total_races} R / {total_horses} 頭")
    print()

    # ── 1. 枠番別の勝率・複勝率 ──
    print("■ 枠番別(脚質問わず)")
    print(f"{'枠':>4} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    draw_agg = {}
    for (d, s), g in groups.items():
        if d not in draw_agg:
            draw_agg[d] = {'n': 0, 'win': 0, 'show': 0}
        draw_agg[d]['n'] += g['n']
        draw_agg[d]['win'] += g['win']
        draw_agg[d]['show'] += g['show']
    for d in ['内', '中', '外']:
        if d in draw_agg:
            g = draw_agg[d]
            wr = g['win'] / g['n'] * 100 if g['n'] else 0
            sr = g['show'] / g['n'] * 100 if g['n'] else 0
            print(f"{d:>4} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")
    # z-test 内 vs 外
    if '内' in draw_agg and '外' in draw_agg:
        gi = draw_agg['内']
        go = draw_agg['外']
        z_win = z_test_proportions(gi['win']/gi['n'], gi['n'],
                                    go['win']/go['n'], go['n'])
        z_show = z_test_proportions(gi['show']/gi['n'], gi['n'],
                                     go['show']/go['n'], go['n'])
        print(f"  内vs外 z(勝率)={z_win:+.2f}  z(複勝)={z_show:+.2f}")

    # ── 2. 脚質別の勝率・複勝率 ──
    print("\n■ 脚質別(枠問わず)")
    print(f"{'脚質':>4} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    style_agg = {}
    for (d, s), g in groups.items():
        if s not in style_agg:
            style_agg[s] = {'n': 0, 'win': 0, 'show': 0}
        style_agg[s]['n'] += g['n']
        style_agg[s]['win'] += g['win']
        style_agg[s]['show'] += g['show']
    for s in ['逃', '先', '差追', '?']:
        if s in style_agg:
            g = style_agg[s]
            wr = g['win'] / g['n'] * 100 if g['n'] else 0
            sr = g['show'] / g['n'] * 100 if g['n'] else 0
            print(f"{s:>4} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")

    # ── 3. 交差: 枠番×脚質 ──
    print("\n■ 枠番×脚質(交差)")
    print(f"{'枠×脚':>8} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for d in ['内', '中', '外']:
        for s in ['逃', '先', '差追']:
            key = (d, s)
            if key in groups:
                g = groups[key]
                wr = g['win'] / g['n'] * 100 if g['n'] else 0
                sr = g['show'] / g['n'] * 100 if g['n'] else 0
                mark = ' ★' if d == '内' and s == '逃' else ''
                print(f"{d}×{s:>4} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%{mark}")

    # ── 4. 核心検証: 内枠逃げ vs その他逃げ ──
    print("\n■ 核心検証: 内枠逃げ vs 外枠逃げ")
    inner_nige = groups.get(('内', '逃'), {'n': 0, 'win': 0, 'show': 0})
    outer_nige = groups.get(('外', '逃'), {'n': 0, 'win': 0, 'show': 0})
    mid_nige = groups.get(('中', '逃'), {'n': 0, 'win': 0, 'show': 0})
    other_nige_n = outer_nige['n'] + mid_nige['n']
    other_nige_win = outer_nige['win'] + mid_nige['win']
    other_nige_show = outer_nige['show'] + mid_nige['show']

    if inner_nige['n'] > 0 and other_nige_n > 0:
        wr_in = inner_nige['win'] / inner_nige['n']
        sr_in = inner_nige['show'] / inner_nige['n']
        wr_ot = other_nige_win / other_nige_n
        sr_ot = other_nige_show / other_nige_n
        z_w = z_test_proportions(wr_in, inner_nige['n'], wr_ot, other_nige_n)
        z_s = z_test_proportions(sr_in, inner_nige['n'], sr_ot, other_nige_n)
        print(f"  内枠逃げ: {inner_nige['n']}頭  勝率{wr_in*100:.1f}%  複勝率{sr_in*100:.1f}%")
        print(f"  中外逃げ: {other_nige_n}頭  勝率{wr_ot*100:.1f}%  複勝率{sr_ot*100:.1f}%")
        print(f"  差分: 勝率{(wr_in-wr_ot)*100:+.1f}pp  複勝率{(sr_in-sr_ot)*100:+.1f}pp")
        print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")
        sig = '★有意(|z|≥2)' if abs(z_s) >= 2 or abs(z_w) >= 2 else '有意でない(|z|<2)'
        print(f"  → {sig}")
    else:
        print("  データ不足")

    # ── 5. 市場(人気)の織込み度 ──
    print("\n■ 市場の織込み度: 内枠逃げ馬の平均人気")
    inner_nige_pops = []
    other_nige_pops = []
    for day_key, races in cache.items():
        for race in races:
            n_horses = race['n_horses']
            if n_horses < 6:
                continue
            max_waku = max(h.get('waku', 1) for h in race['horses'])
            for h in race['horses']:
                passing = h.get('passing', '')
                style = classify_position(passing, n_horses)
                if style != '逃':
                    continue
                pop = h.get('popularity')
                if pop is None:
                    continue
                draw = classify_draw(h.get('waku', 0), max_waku)
                if draw == '内':
                    inner_nige_pops.append(pop)
                else:
                    other_nige_pops.append(pop)

    if inner_nige_pops and other_nige_pops:
        avg_in = sum(inner_nige_pops) / len(inner_nige_pops)
        avg_ot = sum(other_nige_pops) / len(other_nige_pops)
        print(f"  内枠逃げ: 平均{avg_in:.1f}番人気 (n={len(inner_nige_pops)})")
        print(f"  中外逃げ: 平均{avg_ot:.1f}番人気 (n={len(other_nige_pops)})")
        if avg_in < avg_ot:
            print(f"  → 市場は内枠逃げを既に高く評価している(過剰人気の可能性)")
        else:
            print(f"  → 市場は内枠逃げを見落としている(妙味の可能性)")

    print(f"\n{'='*70}")
    print("判定基準: |z|≥2 = 有意 / |z|≥3 = 強く有意")
    print("注意: 通過順は事後データ(実際にそのレースで前に行った馬)であり、")
    print("      事前に判定できる脚質とは異なる。前に行けた=内枠有利の証拠になる。")


if __name__ == '__main__':
    print("NAR結果データ取得中(2秒間隔・キャッシュ優先)...")
    cache = fetch_results()
    analyze(cache)
