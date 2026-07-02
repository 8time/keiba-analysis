# -*- coding: utf-8 -*-
"""ペース圧力(騎手・厩舎の前受け意図)は荒れを予測するか ―― 展開MAP案B。

仮説: 逃げ/先行を好む騎手・厩舎が多く集まったレース=前受け意図が過密=ペース速化・
先行総崩れ=荒れ寄り。展開恩恵/脚質は織込み済み([[verified_tenkai_priced_in]]
[[verified_legtype_axis]])だが、それは"馬選び"の話。ここは"レース選択器"(⑧と同じ)として、
騎手/厩舎の意図が荒れを予測するか(しかも頭数統制後も=priced-inでないか)を測る。

リーク無し: 各騎手code/厩舎codeの『前受け率』を過去走から逐次計算(corner4<=2=最終コーナー
前受けを前型proxyに。序盤corner1/2は半数null不可)。対象レースには『各連の"過去"前受け率』のみ使用。
荒れ定義: 3着以内に6番人気以下が1頭以上混入。
プロトコル: 閾値(前型騎手の分位)と頭数別荒れベースをtrain2021-24で凍結→holdout2025→confirm2026。
採用ゲート: holdout2025で 高圧力の荒れ残差 z>=2.0 かつ 頭数統制後も符号維持。
  満たさねば「展開意図も織込み済み」で打ち切り(展開MAPは表示改善のみ)。
"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
MIN_J = 50   # 騎手の最低過去騎乗
MIN_T = 30   # 厩舎の最低過去出走


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    rows = con.execute("""
        SELECT ra.race_key, ra.year, ra.monthday, ra.shusso_tosu,
               r.jockey_code, r.trainer_code, r.corner4, r.chakujun, r.ninki, r.win_odds
        FROM races ra JOIN results r ON r.race_key=ra.race_key
        WHERE ra.jyo BETWEEN '01' AND '10' AND CAST(ra.year AS INTEGER) BETWEEN 2019 AND 2026
          AND r.chakujun>0
    """).fetchall()
    con.close()

    races = defaultdict(list)
    meta = {}
    fav1 = {}  # rk -> 1番人気オッズ(min win_odds>0) or None
    for (rk, y, md, tosu, jc, tc, c4, ch, nk, wo) in rows:
        races[rk].append({'jc': jc, 'tc': tc, 'c4': c4, 'ch': ch,
                          'nk': nk or 99, 'tosu': tosu or 0})
        meta[rk] = (int(y) * 10000 + int(md), int(y), tosu or 0)
        if wo and wo > 0:
            fav1[rk] = min(fav1.get(rk, 9e9), wo)

    order = sorted(races.keys(), key=lambda k: (meta[k][0], k))

    jstat = defaultdict(lambda: [0, 0])  # code -> [front, total]
    tstat = defaultdict(lambda: [0, 0])
    samples = []  # (year, tosu, n_speed_j, arare, jrate_sum)

    # train2021-24分位のため2パス: 1パス目で騎手/厩舎の"最終"前受け率分布→閾値。
    # ただしリーク厳守は各レース時点の逐次率で判定する。閾値だけtrain全体の分布から決める
    # (閾値=定数ハイパラなのでリークにならない)。
    # まず逐次で各レースの各馬のjrate/trateを記録しつつ、train期間のjrate値を集めて分位を出す。
    train_jrates = []
    per_race = []  # (rk, [ (jrate,trate) per horse ])
    for rk in order:
        hs = races[rk]
        row = []
        for h in hs:
            jf, jn = jstat[h['jc']]
            tf, tn = tstat[h['tc']]
            jr = (jf / jn) if jn >= MIN_J else None
            tr = (tf / tn) if tn >= MIN_T else None
            row.append((jr, tr))
            if meta[rk][1] and 2021 <= meta[rk][1] <= 2024 and jr is not None:
                train_jrates.append(jr)
        per_race.append((rk, row))
        # 更新(このレースの結果で前受け率を更新)
        for h in hs:
            front = 1 if (h['c4'] and h['c4'] <= 2) else 0
            jstat[h['jc']][0] += front
            jstat[h['jc']][1] += 1
            tstat[h['tc']][0] += front
            tstat[h['tc']][1] += 1

    train_jrates.sort()
    J_THRESH = train_jrates[int(len(train_jrates) * 0.75)] if train_jrates else 0.3
    print(f'前型騎手 閾値(train75%ile jrate)={J_THRESH:.3f} (n={len(train_jrates)})')

    # per race: n_speed_j = 前型騎手(jrate>=J_THRESH)の頭数, 荒れ
    for rk, row in per_race:
        hs = races[rk]
        day, yr, tosu = meta[rk]
        if tosu < 8:
            continue
        n_speed = sum(1 for (jr, tr) in row if jr is not None and jr >= J_THRESH)
        arare = any(h['ch'] <= 3 and h['nk'] >= 6 for h in hs)
        samples.append((yr, tosu, n_speed, 1 if arare else 0, fav1.get(rk)))

    # 頭数別荒れベース(train2021-24)
    base = defaultdict(lambda: [0, 0])
    for (yr, tosu, ns, ar, f1) in samples:
        if 2021 <= yr <= 2024:
            base[tosu][0] += ar
            base[tosu][1] += 1
    base_rate = {t: (v[0] / v[1] if v[1] else 0.5) for t, v in base.items()}
    vals_tr = sorted(s[2] for s in samples if 2021 <= s[0] <= 2024)
    P = vals_tr[len(vals_tr) // 2] if vals_tr else 2

    def evalp(y_lo, y_hi, tag, fav_filter=None):
        # 高圧力=n_speed>P, 低=<=P。頭数統制=頭数別ベース残差。fav_filter=fav1オッズ帯で層別。
        hi = {'n': 0, 'ar': 0, 'exp': 0.0}
        lo = {'n': 0, 'ar': 0, 'exp': 0.0}
        for (yr, tosu, ns, ar, f1) in samples:
            if not (y_lo <= yr <= y_hi):
                continue
            if fav_filter and not fav_filter(f1):
                continue
            g = hi if ns > P else lo
            g['n'] += 1
            g['ar'] += ar
            g['exp'] += base_rate.get(tosu, 0.5)
        print(f'\n=== {tag} (前型騎手数>{P}=高圧力) ===')  # noqa
        res = {}
        for name, g in (('高圧力', hi), ('低圧力', lo)):
            if g['n'] < 20:
                print(f'  {name}: n={g["n"]}(小)')
                res[name] = None
                continue
            p = g['ar'] / g['n']
            e = g['exp'] / g['n']
            z = (g['ar'] - g['exp']) / math.sqrt(g['n'] * e * (1 - e)) if e > 0 else 0
            print(f"  {name}: n={g['n']} 荒れ{p*100:.1f}% 頭数統制残差{(p-e)*100:+.2f}pp z={z:+.2f}")
            res[name] = {'p': p, 'resid': (p - e) * 100, 'z': z, 'n': g['n']}
        # 高-低コントラスト(純圧力シグナル)
        if res['高圧力'] and res['低圧力']:
            a, b = res['高圧力'], res['低圧力']
            diff = (a['resid'] - b['resid']) / 100
            se = math.sqrt(a['p'] * (1 - a['p']) / a['n'] + b['p'] * (1 - b['p']) / b['n'])
            cz = diff / se if se > 0 else 0
            print(f"  高-低コントラスト: {a['resid']-b['resid']:+.2f}pp z={cz:+.2f}")
            return cz
        return None

    evalp(2021, 2024, 'train 2021-24')
    cz_h = evalp(2025, 2025, 'holdout 2025')
    evalp(2026, 2026, 'confirm 2026')

    # 独立性: ⑧(オッズ本命不在=fav1高)と重複でないか。本命明確(fav1<2.5)レースでも
    # ペース圧力が荒れを予測するなら、オッズが知らない独立情報=統合価値あり。
    print('\n--- 独立性チェック(holdout2025・fav1オッズ層別) ---')
    cz_clear = evalp(2025, 2025, '本命明確 fav1<2.5 (⑧が鳴らない層)',
                     fav_filter=lambda f: f is not None and f < 2.5)
    cz_open = evalp(2025, 2025, '割れ fav1>=2.5 (⑧領域)',
                    fav_filter=lambda f: f is not None and f >= 2.5)

    print('\n' + '=' * 60)
    print('採用ゲート: holdout2025 高-低 z>=2.0 かつ ⑧が鳴らない本命明確層でも z>=1.5(=独立)')
    if cz_h is None:
        print('判定: 評価不能')
    elif cz_h >= 2.0 and (cz_clear is not None and cz_clear >= 1.5):
        print(f'判定: ✅ 採用 (全体z={cz_h:+.2f}/本命明確層z={cz_clear:+.2f}=独立) '
              '→ ⑧荒れ選択にペース圧力を統合')
    elif cz_h >= 2.0:
        print(f'判定: ❌ 却下 (全体z={cz_h:+.2f}は有意だが本命明確層z={cz_clear:+.2f}で独立性なし)')
        print('  → ペース圧力の荒れ予測は"割れレース"に集中=オッズ構造(⑧)とほぼ重複。')
        print('  統合は二重計上。展開意図も実質priced-in。展開MAPは表示改善のみ。')
    else:
        print(f'判定: ❌ 却下 (z={cz_h:+.2f}) → 展開意図も織込み済み。展開MAPは表示改善のみ')


if __name__ == '__main__':
    main()
