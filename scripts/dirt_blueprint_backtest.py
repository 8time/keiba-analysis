# -*- coding: utf-8 -*-
"""
ダート設計図(The Dirt Blueprint)の主張を残差ベースで検証。

検証項目(すべてダート平地・事前確定変数のみ):
  [D1] 枠順残差: 外枠(6-8枠)が内枠(1-3枠)よりオッズ補正後に妙味があるか
  [D2] 大型馬残差: 500kg+×ダートの残差(全体 + 良馬場限定)
  [D3] 道悪ダート×脚質: 道悪(重/不良)で先行習性の残差が良馬場より改善するか
  [D4] クラス×脚質: 上級条件(3勝/OP/重賞)でダート差し習性の残差が改善するか
  [D5] 前走内枠ダート着外→今走外枠: 砂かぶりリバウンドの残差
  [D6] 芝スタートコース×外枠: 中山ダ1200等で外枠の残差が特に大きいか

test=2021-2025・JRA平地ダート・tosu>=8。
リーク無し: 枠/馬体重/baba/距離/コースはすべて事前確定。脚質=過去走平均(habits)。
"""
import os
import sys
import sqlite3
import math
from collections import defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import jockey_jv as jj

DB = jj.JV_DB_PATH
exp = jj.calibrate_odds_expectation(db_path=DB)

YEARS = ('2021', '2022', '2023', '2024', '2025')

# 芝スタートのダートコース (jyo+kyori)
SHIBA_START = {
    ('06', 1200),   # 中山ダ1200
    ('05', 1400),   # 東京ダ1400
    ('05', 1600),   # 東京ダ1600
    ('07', 1200),   # 中京ダ1200
    ('08', 1200),   # 京都ダ1200
    ('09', 1400),   # 阪神ダ1400
    ('04', 1200),   # 新潟ダ1200
}

# 中京ダ1800=例外的に内枠有利(資料)
UCHI_EXCEPTION = {('07', 1800)}


def e3(o):
    e = exp.get(jj._odds_band(o))
    return e['top3'] if e else 0.22


def e1(o):
    e = exp.get(jj._odds_band(o))
    return e['win'] if e else 0.08


def z_score(actual, expected, n):
    if n < 30 or expected <= 0:
        return 0.0
    p_hat = actual / n
    se = math.sqrt(expected * (1 - expected) / n)
    return (p_hat - expected) / se if se > 0 else 0.0


def print_group(label, bucket):
    n = bucket['n']
    if n == 0:
        print(f"  {label}: n=0")
        return
    fk_rate = bucket['fk'] / n
    win_rate = bucket['win'] / n
    res3 = fk_rate - (bucket['exp3'] / n)
    res1 = win_rate - (bucket['exp1'] / n)
    z3 = z_score(bucket['fk'], bucket['exp3'] / n, n)
    z1 = z_score(bucket['win'], bucket['exp1'] / n, n)
    roi_t = bucket['roi_t'] / n * 100 if n else 0
    print(f"  {label}: n={n:,} 複勝率{fk_rate*100:.1f}% 勝率{win_rate*100:.1f}% "
          f"複残差{res3*100:+.1f}pp(z={z3:+.1f}) 勝残差{res1*100:+.1f}pp(z={z1:+.1f}) "
          f"単ROI{roi_t:.0f}%")


def new_bucket():
    return {'n': 0, 'fk': 0, 'win': 0, 'exp3': 0.0, 'exp1': 0.0,
            'roi_t': 0.0}


def add_to(b, chaku, odds):
    b['n'] += 1
    b['exp3'] += e3(odds)
    b['exp1'] += e1(odds)
    if chaku <= 3:
        b['fk'] += 1
    if chaku == 1:
        b['win'] += 1
    b['roi_t'] += (odds / 100) if chaku == 1 and odds else 0


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)

    yf = " OR ".join(["ra.year=?"] * len(YEARS))

    # Main query: ダート平地のみ
    rows = con.execute(
        f"""SELECT ra.race_key, ra.race_id, ra.jyo, ra.kyori, ra.baba_dirt,
                   ra.shusso_tosu, ra.juryo, ra.grade,
                   r.waku, r.umaban, r.bataiju, r.zogen,
                   r.chakujun, r.ninki, r.win_odds,
                   r.ketto_num
            FROM races ra JOIN results r ON r.race_key=ra.race_key
            WHERE ({yf}) AND ra.surface='ダート'
              AND ra.shubetsu IN ('11','12','13','14')
              AND ra.shusso_tosu>=8 AND r.chakujun>0""",
        YEARS).fetchall()
    print(f"ダート出走数: {len(rows):,}", file=sys.stderr)

    # Build horse history for habits (pre-race running style)
    # and for D5 (previous race draw analysis)
    hist_rows = con.execute(
        f"""SELECT r.ketto_num, ra.race_key, r.chakujun, r.waku, r.umaban,
                   ra.surface, ra.kyori, ra.shusso_tosu,
                   r.corner1, r.corner2, r.corner3, r.corner4
            FROM results r JOIN races ra ON ra.race_key=r.race_key
            WHERE ra.year>='2019' AND r.chakujun>0
              AND ra.shubetsu IN ('11','12','13','14')
            ORDER BY r.ketto_num, ra.race_key""").fetchall()
    con.close()

    # ── Build horse history ──
    horse_hist = defaultdict(list)
    for ketto, rkey, chaku, waku, uma, surf, kyori, tosu, c1, c2, c3, c4 in hist_rows:
        if not ketto:
            continue
        corners = [x for x in [c1, c2, c3, c4] if x and x > 0]
        avg_pos_rel = None
        if corners and tosu and tosu > 1:
            avg_pos_rel = sum(c / tosu for c in corners) / len(corners)
        horse_hist[ketto].append({
            'rkey': rkey, 'chaku': chaku, 'waku': waku or 0, 'uma': uma or 0,
            'surf': surf, 'kyori': kyori, 'tosu': tosu,
            'avg_pos_rel': avg_pos_rel,
        })

    def get_habit(ketto, cur_rkey):
        """過去走(cur_rkeyより前)の平均通過位置比率(0=先頭, 1=最後方)"""
        runs = horse_hist.get(ketto, [])
        vals = []
        for r in runs:
            if r['rkey'] >= cur_rkey:
                break
            if r['avg_pos_rel'] is not None:
                vals.append(r['avg_pos_rel'])
        if len(vals) < 2:
            return None
        return sum(vals[-5:]) / len(vals[-5:])

    def get_prev_dirt_run(ketto, cur_rkey):
        """前走(ダート限定)の枠と着順を返す"""
        runs = horse_hist.get(ketto, [])
        prev = None
        for r in runs:
            if r['rkey'] >= cur_rkey:
                break
            if r['surf'] == 'ダート':
                prev = r
        return prev

    # ── Buckets ──
    # D1: 枠順
    d1_waku = {g: new_bucket() for g in ['内(1-3)', '中(4-5)', '外(6-8)']}
    d1_ninki = {}  # ninki_band -> waku_group -> bucket

    # D2: 大型馬
    d2_size = {g: new_bucket() for g in ['500kg+', '480-499', '460-479', '<460']}
    d2_size_good = {g: new_bucket() for g in ['500kg+ 良', '500kg+ 道悪', '<500 良', '<500 道悪']}

    # D3: 道悪×脚質
    d3_baba_style = {}  # (baba_group, style_group) -> bucket

    # D4: クラス×脚質
    d4_class_style = {}  # (class_group, style_group) -> bucket

    # D5: 砂かぶりリバウンド
    d5_rebound = {g: new_bucket() for g in
                  ['前走内枠着外→今走外枠', '前走内枠着外→今走内枠', '前走外枠着外→今走外枠',
                   '前走外枠着外→今走内枠', 'リバウンド_人気薄', 'リバウンド_人気上位']}

    # D6: 芝スタート×外枠
    d6_shiba = {g: new_bucket() for g in
                ['芝ｽﾀｰﾄ外枠', '芝ｽﾀｰﾄ内枠', '全ダートｽﾀｰﾄ外枠', '全ダートｽﾀｰﾄ内枠']}

    def waku_group(w):
        if w <= 3: return '内(1-3)'
        if w <= 5: return '中(4-5)'
        return '外(6-8)'

    def size_group(w):
        if w >= 500: return '500kg+'
        if w >= 480: return '480-499'
        if w >= 460: return '460-479'
        return '<460'

    def style_group(habit):
        if habit is None: return None
        if habit <= 0.35: return '前型'
        if habit <= 0.55: return '中型'
        return '後型'

    def baba_group(baba):
        try:
            b = int(baba)
        except (TypeError, ValueError):
            return '良'
        if b == 1: return '良'
        if b == 2: return '稍重'
        return '重不良'

    def class_group(grade):
        if grade in ('A', 'B', 'C', 'D', 'L'):
            return '上級'
        return '下級'

    def ninki_band(n):
        if n <= 3: return '1-3番人気'
        if n <= 5: return '4-5番人気'
        if n <= 9: return '6-9番人気'
        return '10番人気~'

    # ── Process ──
    for rkey, rid, jyo, kyori, baba, tosu, juryo, grade, \
            waku, uma, bataiju, zogen, chaku, ninki, odds, ketto in rows:
        if not odds or odds <= 0:
            continue
        waku = waku or 0
        bataiju = bataiju or 0
        ninki = ninki or 99
        baba = baba or 1
        jyo = jyo or ''
        kyori = kyori or 0

        # --- D1: 枠順 ---
        wg = waku_group(waku)
        add_to(d1_waku[wg], chaku, odds)
        nb = ninki_band(ninki)
        if nb not in d1_ninki:
            d1_ninki[nb] = {g: new_bucket() for g in ['内(1-3)', '中(4-5)', '外(6-8)']}
        add_to(d1_ninki[nb][wg], chaku, odds)

        # --- D2: 大型馬 ---
        if bataiju > 0:
            sg = size_group(bataiju)
            add_to(d2_size[sg], chaku, odds)
            bg = baba_group(baba)
            if bataiju >= 500:
                k = '500kg+ 良' if bg == '良' else '500kg+ 道悪'
            else:
                k = '<500 良' if bg == '良' else '<500 道悪'
            add_to(d2_size_good[k], chaku, odds)

        # --- D3: 道悪×脚質 ---
        habit = get_habit(ketto, rkey)
        sg_val = style_group(habit)
        if sg_val:
            bg = baba_group(baba)
            key3 = (bg, sg_val)
            if key3 not in d3_baba_style:
                d3_baba_style[key3] = new_bucket()
            add_to(d3_baba_style[key3], chaku, odds)

        # --- D4: クラス×脚質 ---
        if sg_val:
            cg = class_group(grade)
            key4 = (cg, sg_val)
            if key4 not in d4_class_style:
                d4_class_style[key4] = new_bucket()
            add_to(d4_class_style[key4], chaku, odds)

        # --- D5: 砂かぶりリバウンド ---
        prev = get_prev_dirt_run(ketto, rkey)
        if prev and prev['tosu'] and prev['tosu'] >= 8:
            prev_inner = prev['waku'] <= 3
            prev_outer = prev['waku'] >= 6
            prev_lost = prev['chaku'] > 3
            cur_inner = waku <= 3
            cur_outer = waku >= 6
            if prev_lost:
                if prev_inner and cur_outer:
                    add_to(d5_rebound['前走内枠着外→今走外枠'], chaku, odds)
                    if ninki >= 6:
                        add_to(d5_rebound['リバウンド_人気薄'], chaku, odds)
                    else:
                        add_to(d5_rebound['リバウンド_人気上位'], chaku, odds)
                elif prev_inner and cur_inner:
                    add_to(d5_rebound['前走内枠着外→今走内枠'], chaku, odds)
                elif prev_outer and cur_outer:
                    add_to(d5_rebound['前走外枠着外→今走外枠'], chaku, odds)
                elif prev_outer and cur_inner:
                    add_to(d5_rebound['前走外枠着外→今走内枠'], chaku, odds)

        # --- D6: 芝スタート ---
        is_shiba = (jyo, kyori) in SHIBA_START
        if is_shiba:
            k6 = '芝ｽﾀｰﾄ外枠' if waku >= 6 else '芝ｽﾀｰﾄ内枠'
        else:
            k6 = '全ダートｽﾀｰﾄ外枠' if waku >= 6 else '全ダートｽﾀｰﾄ内枠'
        add_to(d6_shiba[k6], chaku, odds)

    # ── Print Results ──
    print("\n" + "=" * 72)
    print("[D1] ダート枠順残差 (外枠有利は妙味か?)")
    print("=" * 72)
    for g in ['内(1-3)', '中(4-5)', '外(6-8)']:
        print_group(g, d1_waku[g])
    for nb in ['1-3番人気', '4-5番人気', '6-9番人気', '10番人気~']:
        print(f"\n  --- {nb} ---")
        if nb in d1_ninki:
            for g in ['内(1-3)', '中(4-5)', '外(6-8)']:
                print_group(f"  {g}", d1_ninki[nb][g])

    print("\n" + "=" * 72)
    print("[D2] ダート大型馬(500kg+)残差")
    print("=" * 72)
    for g in ['500kg+', '480-499', '460-479', '<460']:
        print_group(g, d2_size[g])
    print("\n  --- 馬場×体格 ---")
    for g in ['500kg+ 良', '500kg+ 道悪', '<500 良', '<500 道悪']:
        print_group(g, d2_size_good[g])

    print("\n" + "=" * 72)
    print("[D3] 道悪ダート×脚質(習性)残差 — 道悪で先行がさらに有利になるか?")
    print("=" * 72)
    for bg in ['良', '稍重', '重不良']:
        print(f"\n  --- 馬場: {bg} ---")
        for sg in ['前型', '中型', '後型']:
            key = (bg, sg)
            if key in d3_baba_style:
                print_group(f"{sg}", d3_baba_style[key])

    print("\n" + "=" * 72)
    print("[D4] クラス×脚質 — 上級条件で差し馬の残差が改善するか?")
    print("=" * 72)
    for cg in ['下級', '上級']:
        print(f"\n  --- {cg} ---")
        for sg in ['前型', '中型', '後型']:
            key = (cg, sg)
            if key in d4_class_style:
                print_group(f"{sg}", d4_class_style[key])

    print("\n" + "=" * 72)
    print("[D5] 砂かぶりリバウンド (前走ダート内枠着外→今走外枠)")
    print("=" * 72)
    for g in ['前走内枠着外→今走外枠', '前走内枠着外→今走内枠',
              '前走外枠着外→今走外枠', '前走外枠着外→今走内枠']:
        print_group(g, d5_rebound[g])
    print("\n  --- リバウンド対象の人気帯別 ---")
    for g in ['リバウンド_人気上位', 'リバウンド_人気薄']:
        print_group(g, d5_rebound[g])

    print("\n" + "=" * 72)
    print("[D6] 芝スタートコース×外枠 vs 全ダートスタート×外枠")
    print("=" * 72)
    for g in ['芝ｽﾀｰﾄ外枠', '芝ｽﾀｰﾄ内枠', '全ダートｽﾀｰﾄ外枠', '全ダートｽﾀｰﾄ内枠']:
        print_group(g, d6_shiba[g])

    print("\n" + "=" * 72)
    print("検証完了。残差が正(z>+2)=妙味あり / 残差≈0=priced-in / 負(z<-2)=過剰人気")
    print("=" * 72)


if __name__ == '__main__':
    main()
