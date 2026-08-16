"""NAR 出走間隔(中間日)バイアスの検証バックテスト。

キャッシュ済み結果 + 出馬表から前走日を追加取得して間隔を計算。
間隔帯別の勝率・複勝率を検証する。
"""
import sys, os, json, time, math, re, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CACHE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'data', 'nar_results_cache.json')
INTERVAL_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'data', 'nar_interval_cache.json')


def z_test(p1, n1, p2, n2):
    if n1 == 0 or n2 == 0:
        return 0.0
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    if p_pool <= 0 or p_pool >= 1:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))
    return (p1 - p2) / se if se > 0 else 0.0


def fetch_intervals():
    """出馬表から前走日を取得して間隔を計算。結果キャッシュとマッチ。"""
    import core.nar_scraper as nar

    with open(CACHE_PATH, 'r', encoding='utf-8') as f:
        results_cache = json.load(f)

    if os.path.exists(INTERVAL_CACHE):
        with open(INTERVAL_CACHE, 'r', encoding='utf-8') as f:
            iv_cache = json.load(f)
    else:
        iv_cache = {}

    total_fetched = 0
    max_fetch = 70

    for day_key in sorted(results_cache.keys()):
        parts = day_key.split('_')
        date_str = parts[0]
        baba = parts[1]
        races = results_cache[day_key]

        for race in races:
            rno = race.get('race_no', 0)
            rkey = f"{day_key}_R{rno}"
            if rkey in iv_cache:
                continue
            if total_fetched >= max_fetch:
                break

            entry = nar.fetch_entry_table(date_str, baba, rno)
            total_fetched += 1
            if not entry or 'horses' not in entry:
                iv_cache[rkey] = []
                continue

            from datetime import datetime
            race_horses = []
            for h in entry['horses']:
                umaban = h.get('umaban', 0)
                runs = h.get('past_runs', [])
                interval = None
                if runs and runs[0].get('race_date') and date_str:
                    try:
                        today_dt = datetime.strptime(date_str, '%Y/%m/%d')
                        prev_dt = datetime.strptime(runs[0]['race_date'], '%Y/%m/%d')
                        gap = (today_dt - prev_dt).days
                        if 0 < gap < 365:
                            interval = gap
                    except (ValueError, TypeError):
                        pass
                race_horses.append({'umaban': umaban, 'interval': interval})
            iv_cache[rkey] = race_horses

            if total_fetched % 10 == 0:
                print(f"  [{total_fetched}] {rkey}: {len(race_horses)} horses")

        if total_fetched >= max_fetch:
            print(f"  [limit] {total_fetched} requests")
            break

    os.makedirs(os.path.dirname(INTERVAL_CACHE), exist_ok=True)
    with open(INTERVAL_CACHE, 'w', encoding='utf-8') as f:
        json.dump(iv_cache, f, ensure_ascii=False, indent=1)

    print(f"  interval cache: {len(iv_cache)} races")
    return iv_cache


def analyze():
    with open(CACHE_PATH, 'r', encoding='utf-8') as f:
        results_cache = json.load(f)
    with open(INTERVAL_CACHE, 'r', encoding='utf-8') as f:
        iv_cache = json.load(f)

    bands = {
        '1-7日':   {'n': 0, 'win': 0, 'show': 0, 'pops': []},
        '8-13日':  {'n': 0, 'win': 0, 'show': 0, 'pops': []},
        '14-21日': {'n': 0, 'win': 0, 'show': 0, 'pops': []},
        '22-35日': {'n': 0, 'win': 0, 'show': 0, 'pops': []},
        '36-56日': {'n': 0, 'win': 0, 'show': 0, 'pops': []},
        '57日+':   {'n': 0, 'win': 0, 'show': 0, 'pops': []},
    }

    pop_bands = {}
    matched = 0

    for day_key, races in results_cache.items():
        for race in races:
            rno = race.get('race_no', 0)
            rkey = f"{day_key}_R{rno}"
            if rkey not in iv_cache:
                continue
            if race['n_horses'] < 6:
                continue

            iv_list = {h['umaban']: h['interval'] for h in iv_cache[rkey]}
            for h in race['horses']:
                uma = h.get('umaban', 0)
                interval = iv_list.get(uma)
                if interval is None:
                    continue

                finish = h.get('finish', 99)
                pop = h.get('popularity', 99)
                is_win = finish == 1
                is_show = finish <= 3
                matched += 1

                if interval <= 7:
                    bk = '1-7日'
                elif interval <= 13:
                    bk = '8-13日'
                elif interval <= 21:
                    bk = '14-21日'
                elif interval <= 35:
                    bk = '22-35日'
                elif interval <= 56:
                    bk = '36-56日'
                else:
                    bk = '57日+'

                g = bands[bk]
                g['n'] += 1
                if is_win:
                    g['win'] += 1
                if is_show:
                    g['show'] += 1
                if pop < 99:
                    g['pops'].append(pop)

                if pop <= 3:
                    pb = '1-3人気'
                elif pop <= 6:
                    pb = '4-6人気'
                else:
                    pb = '7人気+'

                short = interval <= 13
                pk = (pb, '短間隔' if short else '通常')
                if pk not in pop_bands:
                    pop_bands[pk] = {'n': 0, 'win': 0, 'show': 0}
                pop_bands[pk]['n'] += 1
                if is_win:
                    pop_bands[pk]['win'] += 1
                if is_show:
                    pop_bands[pk]['show'] += 1

    print(f"\n{'='*70}")
    print(f"NAR 出走間隔(中間日)バイアス検証")
    print(f"{'='*70}")
    print(f"間隔データ取得済み: {matched} 頭")

    print(f"\n■ 間隔帯別")
    print(f"{'帯':>10} {'頭数':>6} {'勝率':>8} {'複勝率':>8} {'平均人気':>8}")
    for bk in ['1-7日', '8-13日', '14-21日', '22-35日', '36-56日', '57日+']:
        g = bands[bk]
        if g['n'] == 0:
            print(f"{bk:>10} {0:>6}    -       -")
            continue
        wr = g['win'] / g['n'] * 100
        sr = g['show'] / g['n'] * 100
        avg_pop = sum(g['pops']) / len(g['pops']) if g['pops'] else 0
        print(f"{bk:>10} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}% {avg_pop:>7.1f}")

    short = {'n': 0, 'win': 0, 'show': 0}
    normal = {'n': 0, 'win': 0, 'show': 0}
    for bk in ['1-7日', '8-13日']:
        short['n'] += bands[bk]['n']
        short['win'] += bands[bk]['win']
        short['show'] += bands[bk]['show']
    for bk in ['14-21日', '22-35日', '36-56日', '57日+']:
        normal['n'] += bands[bk]['n']
        normal['win'] += bands[bk]['win']
        normal['show'] += bands[bk]['show']

    print(f"\n■ 短間隔(≤13日) vs 通常(14日+)")
    if short['n'] and normal['n']:
        wr_s = short['win']/short['n']*100
        sr_s = short['show']/short['n']*100
        wr_n = normal['win']/normal['n']*100
        sr_n = normal['show']/normal['n']*100
        z_w = z_test(short['win']/short['n'], short['n'], normal['win']/normal['n'], normal['n'])
        z_s = z_test(short['show']/short['n'], short['n'], normal['show']/normal['n'], normal['n'])
        print(f"  短間隔: {short['n']}頭  勝率{wr_s:.1f}%  複勝率{sr_s:.1f}%")
        print(f"  通常:   {normal['n']}頭  勝率{wr_n:.1f}%  複勝率{sr_n:.1f}%")
        print(f"  差分: 勝率{wr_s-wr_n:+.1f}pp  複勝率{sr_s-sr_n:+.1f}pp")
        print(f"  z(勝率)={z_w:+.2f}  z(複勝)={z_s:+.2f}")

    print(f"\n■ 人気帯別(織込みチェック): 短間隔≤13日 vs 通常14日+")
    print(f"{'人気帯':>8} {'区分':>6} {'頭数':>6} {'勝率':>8} {'複勝率':>8}")
    for pb in ['1-3人気', '4-6人気', '7人気+']:
        for cat in ['短間隔', '通常']:
            pk = (pb, cat)
            if pk in pop_bands:
                g = pop_bands[pk]
                wr = g['win'] / g['n'] * 100 if g['n'] else 0
                sr = g['show'] / g['n'] * 100 if g['n'] else 0
                print(f"{pb:>8} {cat:>6} {g['n']:>6} {wr:>7.1f}% {sr:>7.1f}%")
        g_s = pop_bands.get((pb, '短間隔'), {'n': 0, 'win': 0, 'show': 0})
        g_n = pop_bands.get((pb, '通常'), {'n': 0, 'win': 0, 'show': 0})
        if g_s['n'] > 0 and g_n['n'] > 0:
            z = z_test(g_s['show']/g_s['n'], g_s['n'], g_n['show']/g_n['n'], g_n['n'])
            diff = (g_s['show']/g_s['n'] - g_n['show']/g_n['n']) * 100
            print(f"  → {pb}内 短vs通常 複勝差{diff:+.1f}pp z={z:+.2f}")

    print(f"\n{'='*70}")
    print("■ 判定")
    if short['n'] and normal['n']:
        z_final = z_test(short['show']/short['n'], short['n'], normal['show']/normal['n'], normal['n'])
        if abs(z_final) >= 2:
            print("  短間隔の不利は有意(|z|≥2) → スコア減点を維持")
        else:
            print("  短間隔の不利は有意でない(|z|<2) → スコア減点を削除すべき")
    else:
        print("  短間隔データ不足")


if __name__ == '__main__':
    print("出馬表から前走日を取得中(2秒間隔・キャッシュ優先)...")
    iv_cache = fetch_intervals()
    analyze()
