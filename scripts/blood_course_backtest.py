# -*- coding: utf-8 -*-
"""血統×コース(コースバイアス)の組み合わせ検証 — 血統SP強化の土台。

質問: 父系統×コース形状(直線長/坂)・父×当該場コースの適性は、
人気(市場)を超える複勝シグナルを持つか?(=軸/消去に使えるか)

方針(リーク無し・過去の教訓遵守):
  ・血統は予測(LTR)には織込み済みと検証済 → ここでは人気補正残差で
    『軸(1-3人気)の信頼度』『穴(6+人気)の妙味』角度のみを見る。
  ・T1: 父系統×直線長帯(短≤330/中/長≥450)×芝ダ
  ・T2: 父系統×急坂(中山阪神中京)/平坦×芝ダ
  ・T3: 父×当該場×芝ダの複勝率を前期間(2014-2020)で算出し、
        上位/下位tierの後期間(2021-25)残差(=コース適性がpriced-inか)
  ・train(2021-24)とholdout(2025)の両方で符号一致+zで判定。

父系統: horses テーブルを名前で遡上(同名馬は生年最新を種牡馬とみなす)し、
アンカー種牡馬で大系統に分類。未解決は父名のまま'その他'。

実行: python scripts/blood_course_backtest.py
"""
import sys, io, os, sqlite3, math
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'jravan.db')

# 大系統アンカー(遡上して最初に一致した系統を採用)
ANCHORS = [
    ('サンデーサイレンス', 'サンデー系'),
    ('キングカメハメハ', 'キンカメ系'),
    ('Kingmambo', 'ミスプロ系'), ('キングマンボ', 'ミスプロ系'),
    ('Mr. Prospector', 'ミスプロ系'), ('ミスタープロスペクター', 'ミスプロ系'),
    ('Gone West', 'ミスプロ系'), ('ゴーンウエスト', 'ミスプロ系'),
    ('Seeking the Gold', 'ミスプロ系'), ('シーキングザゴールド', 'ミスプロ系'),
    ('Roberto', 'ロベルト系'), ('ロベルト', 'ロベルト系'),
    ('ブライアンズタイム', 'ロベルト系'), ('グラスワンダー', 'ロベルト系'),
    ('シンボリクリスエス', 'ロベルト系'), ('スクリーンヒーロー', 'ロベルト系'),
    ('Storm Cat', 'ストームキャット系'), ('ストームキャット', 'ストームキャット系'),
    ('ヘネシー', 'ストームキャット系'), ('Hennessy', 'ストームキャット系'),
    ('ヨハネスブルグ', 'ストームキャット系'),
    ('A.P. Indy', 'APインディ系'), ('エーピーインディ', 'APインディ系'),
    ('Pulpit', 'APインディ系'), ('タピット', 'APインディ系'), ('Tapit', 'APインディ系'),
    ('Northern Dancer', 'ND欧州系'), ('ノーザンダンサー', 'ND欧州系'),
    ('Danehill', 'ND欧州系'), ('デインヒル', 'ND欧州系'),
    ("Sadler's Wells", 'ND欧州系'), ('サドラーズウェルズ', 'ND欧州系'),
    ('ハービンジャー', 'ND欧州系'), ('Dansili', 'ND欧州系'),
]
# horsesで遡上できない外国産等の手動系統(上位出走数から)
MANUAL = {
    'シニスターミニスター': 'APインディ系', 'マジェスティックウォリアー': 'APインディ系',
    'ドレフォン': 'ストームキャット系', 'アメリカンペイトリオット': 'ND欧州系',
    'ニューイヤーズデイ': 'ストームキャット系', 'マインドユアビスケッツ': 'その他米国系',
    'デクラレーションオブウォー': 'ND欧州系', 'モーニン': 'その他米国系',
    'パイロ': 'APインディ系', 'ダノンレジェンド': 'ストームキャット系',
    'ベストウォーリア': 'その他米国系', 'カリフォルニアクローム': 'その他米国系',
    'ミッキーアイル': 'サンデー系', 'モズアスコット': 'その他米国系',
    'ブリックスアンドモルタル': 'ストームキャット系',
}
_ANCH = dict(ANCHORS)

# 直線長: pace_map._STRAIGHT_LEN 相当(検証はここで自前定義・芝は内回り基準の近似)
STRAIGHT = {
    ('01', '芝'): 266, ('01', 'ダ'): 264, ('02', '芝'): 262, ('02', 'ダ'): 260,
    ('03', '芝'): 292, ('03', 'ダ'): 295, ('04', '芝'): 659, ('04', 'ダ'): 354,
    ('05', '芝'): 526, ('05', 'ダ'): 502, ('06', '芝'): 310, ('06', 'ダ'): 308,
    ('07', '芝'): 413, ('07', 'ダ'): 410, ('08', '芝'): 404, ('08', 'ダ'): 329,
    ('09', '芝'): 356, ('09', 'ダ'): 353, ('10', '芝'): 293, ('10', 'ダ'): 291,
}
SLOPE_STEEP = {'06', '09', '07'}   # 中山・阪神・中京=急坂
SLOPE_FLAT = {'03', '04', '08', '10', '01', '02'}  # 平坦〜緩(東京05は緩坂で除外)


def build_sire_line(con):
    """父名→大系統。horsesを名前遡上(同名は生年最新)。"""
    rows = con.execute("SELECT bamei, sire, birth FROM horses").fetchall()
    by_name = {}
    for bamei, sire, birth in rows:
        if not bamei:
            continue
        cur = by_name.get(bamei)
        b = str(birth or '')
        if cur is None or b > cur[1]:
            by_name[bamei] = (sire, b)

    memo = {}

    def line_of(name, depth=0):
        if not name:
            return 'その他'
        if name in memo:
            return memo[name]
        if name in MANUAL:
            memo[name] = MANUAL[name]
            return MANUAL[name]
        if name in _ANCH:
            memo[name] = _ANCH[name]
            return _ANCH[name]
        if depth >= 5:
            return 'その他'
        parent = (by_name.get(name) or (None,))[0]
        res = line_of(parent, depth + 1) if parent else 'その他'
        memo[name] = res
        return res

    return line_of


def main():
    con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    print("horses読み込み・系統遡上構築中...")
    line_of = build_sire_line(con)

    print("results読み込み中(2014-2025 JRA)...")
    rows = con.execute(
        "SELECT r.year y, r.ninki nk, r.chakujun ch, r.jyo jyo, h.sire sire, "
        "ra.surface sf, ra.kyori ki "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "JOIN horses h ON h.ketto_num=r.ketto_num "
        "WHERE CAST(r.year AS INT) BETWEEN 2014 AND 2025 AND r.jyo<='10' "
        "AND r.chakujun>0 AND r.ninki>0").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    # 系統カバレッジ
    cover = defaultdict(int)
    for r in rows:
        cover[line_of(r['sire'])] += 1
    tot = sum(cover.values())
    print("\n系統カバレッジ:", {k: f"{100*v/tot:.1f}%" for k, v in
                          sorted(cover.items(), key=lambda x: -x[1])})

    # 人気ベース(2021-25)
    popt = defaultdict(lambda: [0, 0])
    for r in rows:
        if 2021 <= int(r['y']) <= 2025:
            popt[int(r['nk'])][0] += 1 if r['ch'] <= 3 else 0
            popt[int(r['nk'])][1] += 1
    base = {p: (s[0] / s[1] if s[1] else 0) for p, s in popt.items()}

    def seg(r):
        surf = '芝' if '芝' in str(r['sf']) else 'ダ'
        st = STRAIGHT.get((str(r['jyo']).zfill(2), surf))
        sb = ('短' if st is not None and st <= 330 else
              '長' if st is not None and st >= 450 else '中')
        slope = ('急坂' if str(r['jyo']).zfill(2) in SLOPE_STEEP else
                 '平坦' if str(r['jyo']).zfill(2) in SLOPE_FLAT else '緩坂')
        return surf, sb, slope

    def zres(sub, yr_from, yr_to, popband):
        t3 = n = 0
        exp = 0.0
        for r in sub:
            if not (yr_from <= int(r['y']) <= yr_to):
                continue
            nk = int(r['nk'])
            if popband == 'fav' and nk > 3:
                continue
            if popband == 'long' and nk < 6:
                continue
            n += 1
            t3 += 1 if r['ch'] <= 3 else 0
            exp += base.get(nk, 0.22)
        if n < 200:
            return None
        e = exp / n
        z = (t3 - exp) / math.sqrt(n * e * (1 - e)) if 0 < e < 1 else 0
        return {'n': n, 'rate': t3 / n, 'exp': e, 'res': t3 / n - e, 'z': z}

    # グループ化
    by_combo1 = defaultdict(list)  # (line, surf, 直線帯)
    by_combo2 = defaultdict(list)  # (line, surf, 坂)
    for r in rows:
        if int(r['y']) < 2021:
            continue
        ln = line_of(r['sire'])
        if ln == 'その他':
            continue
        surf, sb, slope = seg(r)
        by_combo1[(ln, surf, sb)].append(r)
        by_combo2[(ln, surf, slope)].append(r)

    def report(title, combos):
        print(f"\n=== {title} (train2021-24 → holdout2025・|z|train≥2 のみ表示) ===")
        print(f"{'組合せ':<32}{'帯':>5}{'n_tr':>8}{'残差tr':>9}{'z_tr':>7}{'n_25':>7}{'残差25':>9}{'z_25':>7} 判定")
        found = 0
        for key, sub in sorted(combos.items()):
            for band, bandjp in (('fav', '1-3人'), ('long', '6人+')):
                tr = zres(sub, 2021, 2024, band)
                ho = zres(sub, 2025, 2025, band)
                if not tr or abs(tr['z']) < 2.0:
                    continue
                hoz = ho['z'] if ho else 0.0
                hores = ho['res'] if ho else 0.0
                ok = ho is not None and (tr['res'] * hores > 0) and abs(hoz) >= 1.0
                mark = '✅' if ok and abs(tr['z']) >= 2.5 else ('△' if ok else '❌崩落')
                lbl = '×'.join(str(k) for k in key)
                print(f"{lbl:<32}{bandjp:>5}{tr['n']:>8,}{100*tr['res']:>+8.2f}pp{tr['z']:>+7.1f}"
                      f"{(ho['n'] if ho else 0):>7,}{100*hores:>+8.2f}pp{hoz:>+7.1f}  {mark}")
                if ok:
                    found += 1
        if not found:
            print("  (holdoutで生き残る組合せなし)")

    report("T1: 父系統×馬場×直線長帯", by_combo1)
    report("T2: 父系統×馬場×坂", by_combo2)

    # ── T3: 父×当該場×馬場のコース適性(前期間で算出→後期間で残差) ──
    prior = defaultdict(lambda: [0, 0])   # (sire,jyo,surf) -> [top3,n] 2014-2020
    for r in rows:
        if int(r['y']) <= 2020:
            surf = '芝' if '芝' in str(r['sf']) else 'ダ'
            k = (r['sire'], str(r['jyo']).zfill(2), surf)
            prior[k][0] += 1 if r['ch'] <= 3 else 0
            prior[k][1] += 1
    fit = {}
    for k, (t3, n) in prior.items():
        if n >= 50:
            fit[k] = t3 / n
    vals = sorted(fit.values())
    if vals:
        q_hi = vals[int(len(vals) * 0.85)]
        q_lo = vals[int(len(vals) * 0.15)]
        hi_set = {k for k, v in fit.items() if v >= q_hi}
        lo_set = {k for k, v in fit.items() if v <= q_lo}
        subs = {'高適性(上位15%)': [], '低適性(下位15%)': []}
        for r in rows:
            if int(r['y']) < 2021:
                continue
            surf = '芝' if '芝' in str(r['sf']) else 'ダ'
            k = (r['sire'], str(r['jyo']).zfill(2), surf)
            if k in hi_set:
                subs['高適性(上位15%)'].append(r)
            elif k in lo_set:
                subs['低適性(下位15%)'].append(r)
        print(f"\n=== T3: 父×当該場×馬場 コース適性tier(2014-20算出/n≥50) → 2021-25残差 ===")
        print(f"{'tier':<16}{'帯':>6}{'n':>9}{'複勝率':>8}{'期待':>8}{'残差':>9}{'z':>7}")
        for lbl, sub in subs.items():
            for band, bandjp in (('fav', '1-3人'), ('long', '6人+'), (None, '全体')):
                if band is None:
                    t3 = sum(1 for r in sub if r['ch'] <= 3)
                    n = len(sub)
                    exp = sum(base.get(int(r['nk']), 0.22) for r in sub)
                    if n < 200:
                        continue
                    e = exp / n
                    z = (t3 - exp) / math.sqrt(n * e * (1 - e))
                    print(f"{lbl:<16}{bandjp:>6}{n:>9,}{100*t3/n:>7.1f}%{100*e:>7.1f}%{100*(t3/n-e):>+8.2f}pp{z:>+7.1f}")
                else:
                    s = zres(sub, 2021, 2025, band)
                    if s:
                        print(f"{lbl:<16}{bandjp:>6}{s['n']:>9,}{100*s['rate']:>7.1f}%{100*s['exp']:>7.1f}%"
                              f"{100*s['res']:>+8.2f}pp{s['z']:>+7.1f}")


if __name__ == '__main__':
    main()
