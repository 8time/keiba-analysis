# -*- coding: utf-8 -*-
"""
③Gate Scanner Priority バックテスト。
Gate階層ソート(見送り→軸フロア→危険なし→相手質→trio_lean明確)が
実際のレース結果と正の相関を持つかを検証する。

計測 (per gate tier = buy / wait / axis_warn / skip):
  - fav1_top3:  1番人気 3着内率（軸信頼度）
  - honsen:     人気1+2 両方3着内率（本線率）
  - ana2:       5番人気以下 3着内≥2頭率（②型率）
  - anchor_hit: 断層上位(value_horse proxy) 3着内率

期待: buy > wait > axis_warn > skip の fav1_top3 / honsen で単調。
"""
import os
import sys
import sqlite3
import math
import re
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.value_scanner import (race_skip_reasons, race_value_score, trio_lean,
                                odds_gap_anchors, scanner_priority, scanner_play_status,
                                baba_code_to_label)

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')
YEARS = ('2021', '2022', '2023', '2024', '2025')
# 馬場コード変換は共通ヘルパーに統一(以前 0=良 とズレていたバグの再発防止。正=1良/2稍/3重/4不良)


def _month(monthday):
    try:
        return int(str(monthday)[:2]) if monthday else 0
    except Exception:
        return 0


def main():
    for attempt in range(8):
        try:
            con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=20)
            yf = " OR ".join(["ra.year=?"] * len(YEARS))
            rows = con.execute(
                f"""SELECT ra.race_key, ra.shusso_tosu, ra.kigo, ra.juryo,
                           ra.race_name, ra.surface, ra.kyori, ra.monthday,
                           ra.baba_shiba, ra.baba_dirt,
                           r.chakujun, r.ninki, r.win_odds, r.umaban,
                           r.sex, r.futan, r.bataiju
                    FROM races ra JOIN results r ON r.race_key=ra.race_key
                    WHERE ({yf}) AND ra.shubetsu IN ('11','12','13','14')
                      AND ra.shusso_tosu>=8 AND r.chakujun>0""",
                YEARS).fetchall()
            con.close()
            break
        except sqlite3.OperationalError:
            import time
            time.sleep(4)
    else:
        print("DB locked", file=sys.stderr)
        return

    print(f"loaded {len(rows)} result rows", file=sys.stderr)

    races = {}
    for (rk, tosu, kigo, juryo, rname, surf, kyori, md,
         bshiba, bdirt, chaku, ninki, wo, um, sex, futan, bataiju) in rows:
        d = races.setdefault(rk, {
            'tosu': tosu, 'kigo': kigo or '', 'juryo': juryo or '',
            'rname': rname or '', 'surf': surf or '', 'kyori': kyori,
            'monthday': md, 'bshiba': bshiba or '0', 'bdirt': bdirt or '0',
            'horses': []
        })
        d['horses'].append({
            'chaku': chaku, 'ninki': ninki or 99, 'wo': wo or 0,
            'um': um, 'sex': sex or '', 'futan': futan, 'bataiju': bataiju,
        })
    print(f"grouped into {len(races)} races", file=sys.stderr)

    tiers = defaultdict(lambda: {
        'n': 0, 'fav1_top3': 0, 'honsen': 0, 'ana2': 0,
        'anchor_hit': 0, 'anchor_total': 0,
    })

    for rk, d in races.items():
        hs = d['horses']
        surf = d['surf']
        is_turf = '芝' in surf   # 芝
        is_dirt = 'ダ' in surf   # ダ(ート)
        baba_code = d['bshiba'] if is_turf else d['bdirt']
        baba = baba_code_to_label(baba_code)
        month = _month(d['monthday'])
        dist = d['kyori']

        odds_list = sorted(h['wo'] for h in hs if h['wo'] and h['wo'] > 0)
        if not odds_list:
            continue
        fav_odds = odds_list[0]
        n_h = d['tosu'] or len(hs)

        # ── skip_reasons ──
        meta_class = d['rname']
        skips = race_skip_reasons(
            {'class': meta_class}, n_h, surf, d['rname'],
            min_win_odds=fav_odds
        )

        # ── race_value_score ──
        meta = {
            'is_handicap': d['juryo'] == '1',
            'weight_rule': 'ハンデ' if d['juryo'] == '1' else '',
            'condition': baba,
            'class': meta_class,
        }
        jyo = ''
        rv = race_value_score(odds_list, meta, jyo, surf, dist, n_h)

        # ── trio_lean ──
        lean = trio_lean(meta, n_h, fav_odds, pace_z=None,
                         dist=dist, baba=baba, odds_list=odds_list)

        # ── value_horses (proxy: odds gap anchors) ──
        odds_by_um = {h['um']: h['wo'] for h in hs if h['wo'] and h['wo'] > 0}
        anchors = odds_gap_anchors(odds_by_um)
        vh_list = [{'um': u} for u in anchors]

        # ── danger_horses (simplified: 牝×冬春 / 斤量比 for pop 1-3) ──
        dh_list = []
        top3_count, top3_severe = 0, 0
        for h in hs:
            nk = h['ninki']
            if nk < 1 or nk > 3:
                continue
            top3_count += 1
            neg_n = 0
            if h['sex'] == '2' and month in (12, 1, 2, 3):
                neg_n += 1
            try:
                if h['futan'] and h['bataiju'] and h['bataiju'] > 0:
                    if float(h['futan']) / float(h['bataiju']) >= 0.126:
                        neg_n += 1
            except (TypeError, ValueError, ZeroDivisionError):
                pass
            if neg_n:
                dh_list.append({'um': h['um'], 'pop': nk})
            if neg_n >= 2:
                top3_severe += 1

        axis_floor = (top3_count - top3_severe) > 0 if top3_count else True

        # ── build result dict for scanner_priority ──
        result = {
            'skips': skips,
            'axis_floor': axis_floor,
            'danger_horses': dh_list,
            'value_horses': vh_list,
            'lean': lean,
            'vscore': rv['score'],
        }
        status = scanner_play_status(result)

        # ── actual outcomes ──
        t = tiers[status]
        t['n'] += 1

        fav1_in = any(h['ninki'] == 1 and h['chaku'] <= 3 for h in hs)
        fav2_in = any(h['ninki'] == 2 and h['chaku'] <= 3 for h in hs)
        t['fav1_top3'] += int(fav1_in)
        t['honsen'] += int(fav1_in and fav2_in)

        deep = sum(1 for h in hs if h['ninki'] >= 5 and h['chaku'] <= 3)
        t['ana2'] += int(deep >= 2)

        for u in anchors:
            t['anchor_total'] += 1
            hit = any(h['um'] == u and h['chaku'] <= 3 for h in hs)
            t['anchor_hit'] += int(hit)

    # ── report ──
    print()
    print("=" * 80)
    print("③Gate Scanner Priority バックテスト (2021-2025 平地 >=8頭)")
    print("=" * 80)
    _ORDER = ['buy', 'wait', 'axis_warn', 'skip']
    _LABEL = {'buy': '✅買える', 'wait': '△様子見', 'axis_warn': '⚠軸注意', 'skip': '⏸見送り'}
    fmt = "{:<12s}  {:>6s}  {:>10s}  {:>10s}  {:>8s}  {:>12s}"
    print(fmt.format('Tier', 'n', 'fav1_top3', 'honsen', '②型率', 'anchor_hit'))
    print("-" * 80)
    for s in _ORDER:
        t = tiers[s]
        n = t['n'] or 1
        f1 = t['fav1_top3'] / n * 100
        ho = t['honsen'] / n * 100
        a2 = t['ana2'] / n * 100
        ah = t['anchor_hit'] / t['anchor_total'] * 100 if t['anchor_total'] else 0
        print(fmt.format(_LABEL[s], str(t['n']),
                         f"{f1:.1f}%", f"{ho:.1f}%", f"{a2:.1f}%",
                         f"{ah:.1f}% ({t['anchor_total']})"))

    print()
    print("fav1_top3 = 1番人気3着内率（軸信頼度）")
    print("honsen    = 人気1+2 両方3着内率（本線決着率）")
    print("②型率    = 5番人気以下3着内≥2頭率（穴妙味型）")
    print("anchor_hit= 断層上位(value_horse proxy) 3着内率")

    # ── z-test: buy vs wait ──
    b, w = tiers['buy'], tiers['wait']
    if b['n'] > 30 and w['n'] > 30:
        pb = b['fav1_top3'] / b['n']
        pw = w['fav1_top3'] / w['n']
        pp = (b['fav1_top3'] + w['fav1_top3']) / (b['n'] + w['n'])
        se = math.sqrt(pp * (1 - pp) * (1 / b['n'] + 1 / w['n'])) if pp > 0 and pp < 1 else 1
        z = (pb - pw) / se if se else 0
        diff = (pb - pw) * 100
        print(f"\n✅買える vs △様子見: fav1_top3 差 {diff:+.1f}pp (z={z:.1f})")

    a = tiers['axis_warn']
    if a['n'] > 30 and b['n'] > 30:
        pa = a['fav1_top3'] / a['n']
        pb2 = b['fav1_top3'] / b['n']
        pp2 = (a['fav1_top3'] + b['fav1_top3']) / (a['n'] + b['n'])
        se2 = math.sqrt(pp2 * (1 - pp2) * (1 / a['n'] + 1 / b['n'])) if 0 < pp2 < 1 else 1
        z2 = (pb2 - pa) / se2 if se2 else 0
        diff2 = (pb2 - pa) * 100
        print(f"✅買える vs ⚠軸注意: fav1_top3 差 {diff2:+.1f}pp (z={z2:.1f})")


if __name__ == '__main__':
    main()
