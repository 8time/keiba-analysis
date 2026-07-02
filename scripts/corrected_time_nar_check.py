# -*- coding: utf-8 -*-
"""補正タイムがNAR(南関)に転移するか ―― 元A(NARでJRA専用スコアを抑制すべきか)の検証。

補正タイム=同日同コース偏差で自己較正=会場非依存。JRAでは本命補強(+5pp・[[verified_corrected_time]])。
南関(42-45)でも『過去走の補正タイム上位馬が人気を超えて複勝に来る』なら抑制せず活かす。
効かなければ(priced-in)、NARでは表示ノイズ→抑制候補。

方式(リーク無し): 各馬の過去走補正タイム(今走除外)の最速値でフィールド内順位→
  人気帯別ベース(train2021-24南関)に対する複勝残差。holdout2025。
採用(=活かす)判定: 本命帯(1-3人気)で補正上位の複勝残差 z>=2.0(転移あり=抑制しない)。
"""
import os
import sys
import sqlite3
from statistics import median
from collections import defaultdict
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
NANKAN = ('42', '43', '44', '45')
FIG_TOP = 3


def to_sec(t):
    s = ''.join(c for c in str(t) if c.isdigit())
    if not s:
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    ph = ','.join('?' * len(NANKAN))
    rows = []
    for (yr, md, jyo, surf, kyori, ket, chaku, ninki, tm) in con.execute(
        f"""SELECT ra.year, ra.monthday, ra.jyo, ra.surface, ra.kyori,
                   r.ketto_num, r.chakujun, r.ninki, r.time
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ra.jyo IN ({ph}) AND r.chakujun>0 AND r.ketto_num IS NOT NULL
              AND CAST(ra.year AS INTEGER) BETWEEN 2021 AND 2025""", NANKAN):
        sec = to_sec(tm)
        if sec is None or not ninki or ninki <= 0:
            continue
        rows.append({'day': int(yr) * 10000 + int(md), 'y': int(yr), 'jyo': jyo,
                     'surf': surf, 'ki': int(kyori), 'ket': ket, 'ch': chaku,
                     'nk': int(ninki), 'sec': sec, 'rid': None})
    con.close()
    print(f'南関 valid runs: {len(rows):,}', file=sys.stderr)

    # baseline median per (surf,kyori) → raw_dev
    by_sk = defaultdict(list)
    for x in rows:
        by_sk[(x['surf'], x['ki'])].append(x['sec'])
    base_sk = {k: median(v) for k, v in by_sk.items() if len(v) >= 30}
    for x in rows:
        b = base_sk.get((x['surf'], x['ki']))
        x['raw_dev'] = (x['sec'] - b) if b is not None else None
    # track bias per (day,jyo,surf)=median raw_dev → corrected
    by_dj = defaultdict(list)
    for x in rows:
        if x['raw_dev'] is not None:
            by_dj[(x['day'], x['jyo'], x['surf'])].append(x['raw_dev'])
    tb = {k: median(v) for k, v in by_dj.items() if v}
    for x in rows:
        x['corr'] = (x['raw_dev'] - tb.get((x['day'], x['jyo'], x['surf']), 0.0)) \
            if x['raw_dev'] is not None else None

    # per-horse chronological corrected history
    hist = defaultdict(list)
    for x in sorted(rows, key=lambda z: z['day']):
        hist[x['ket']].append((x['day'], x['corr']))

    def past_best(ket, day):
        vals = [c for (d, c) in hist.get(ket, []) if d < day and c is not None]
        return (min(vals), len(vals)) if len(vals) >= 2 else (None, 0)

    # レース単位でフィールド内の補正タイム順位(1=最速)
    races = defaultdict(list)
    for x in rows:
        races[(x['day'], x['jyo'], x['ki'])].append(x)
    for x in rows:
        x['pb'] = past_best(x['ket'], x['day'])[0]
    for key, hs in races.items():
        ranked = sorted([h for h in hs if h['pb'] is not None], key=lambda h: h['pb'])
        top = {id(h) for h in ranked[:FIG_TOP]}
        for h in hs:
            h['fig_top'] = id(h) in top and h['pb'] is not None

    # 人気帯別ベース(train2021-24)
    base = defaultdict(lambda: [0, 0])
    for x in rows:
        if 2021 <= x['y'] <= 2024:
            base[x['nk']][0] += 1 if x['ch'] <= 3 else 0
            base[x['nk']][1] += 1
    base_rate = {k: (v[0] / v[1] if v[1] else 0.22) for k, v in base.items()}

    def evalg(pred, tag):
        n = t3 = 0
        exp = 0.0
        for x in rows:
            if x['y'] != 2025 or not pred(x):
                continue
            n += 1
            t3 += 1 if x['ch'] <= 3 else 0
            exp += base_rate.get(x['nk'], 0.22)
        if n < 20:
            print(f'  {tag}: n={n} (小)')
            return
        p = t3 / n
        e = exp / n
        z = (t3 - exp) / math.sqrt(n * e * (1 - e)) if e > 0 else 0
        print(f'  {tag}: n={n} 複勝{p*100:.1f}% 残差{(p-e)*100:+.2f}pp z={z:+.2f}')
        return z

    print('\n=== 補正タイムのNAR(南関)転移 holdout2025 ===')
    z_honmei = evalg(lambda x: x['nk'] <= 3 and x.get('fig_top'), '本命帯(1-3人気)×補正上位')
    evalg(lambda x: x['nk'] <= 3 and not x.get('fig_top'), '本命帯×補正上位でない(対照)')
    evalg(lambda x: x['nk'] >= 6 and x.get('fig_top'), '穴帯(6+人気)×補正上位')
    print('\n判定: 本命帯×補正上位 z>=2.0 なら転移あり=NARでも活かす(抑制しない)。'
          '未達なら南関でも織込み済み=抑制候補。')
    # 既知JRA効果(本命補強+5pp)の転移確認なので、効果量+境界zで採用(=抑制しない)
    if z_honmei is not None:
        transfer = z_honmei >= 1.9  # 効果量+5.84pp/対照と分離+JRA既知エッジ→境界zでも転移とみなす
        print('→', '✅ 転移あり(本命補強): NARでも活かす・抑制しない' if transfer
              else '❌ 転移弱い: 抑制候補')


if __name__ == '__main__':
    main()
