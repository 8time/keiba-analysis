# -*- coding: utf-8 -*-
"""荒れ予報(trio_lean②穴妙味向き)発火時、強適テーブルのどの項目が
『top7圏外(人気8+)の3着内馬』を捕まえるのに有効かを検証する。

ユーザー仮説(強適テーブルの8項目): 展開適合度/血統スコア上位/血統実績回収率100%超/
Alert初ブリンカー/補正T上位/騎手力上位/末脚指数/33ラップ。

【展開適合度は対象外】: 既に[[verified_tenkai_priced_in]]で全体エッジ無しと確定済み。
かつ実装(positional_map/RPCI/密集補正/風補正)はJV-VAN実時間クエリ等ライブ専用要素が
多く、忠実な過去再現が困難(簡易プロキシは実態と乖離し誤った結論を招くため不採用)。
→ 残り7項目を検証。

方針(リーク無し・過去の教訓遵守):
  1. trio_lean(core/value_scanner)をそのまま呼び、レース単位で"②穴妙味向き"
     (=荒れ予報が出る条件)を過去レースに適用(構造条件のみ=事前情報でリーク無し)。
  2. 対象馬 = 荒れ予報レース内で人気8+(=top7圏外の代理)の馬。
  3. 目的変数 = 3着内(chakujun<=3)。
  4. 各項目は「そのレース時点以前の情報のみ」でレース内ランキングし、上位(または
     条件成立)フラグを立てる。単体 と 2つ以上重複 の両方で、的中率(精度)を比較。
  5. train2021-24 / holdout2025 で安定性を確認。

実行: python scripts/arare_signal_backtest.py
"""
import sys, io, os, sqlite3, math
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import lap33 as l3
from core import bloodline as bl

DB = l3.JV_DB_PATH
BLOOD_DB = os.path.join(ROOT, 'data', 'blood_dict.db')


def _con():
    return sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=10)


def to_sec_full(v):
    try:
        s = str(int(v))
    except (TypeError, ValueError):
        return None
    if not s or s == '0':
        return None
    if len(s) <= 3:
        return int(s) / 10.0
    return int(s[:-3]) * 60 + int(s[-3:]) / 10.0


def is_chaos_race(is_handicap, n_horses, dist, baba, odds_list):
    """core.value_scanner.trio_lean を呼び、②穴妙味向き(荒れ予報)かを判定。"""
    from core import value_scanner as vs
    meta = {'is_handicap': is_handicap}
    r = vs.trio_lean(meta=meta, n_horses=n_horses, dist=dist, baba=baba, odds_list=odds_list)
    return r['lean'] == '②穴妙味向き'


def main():
    print("読み込み中(2016-2025 JRA)...")
    con = _con()
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT r.race_key rk, r.year y, r.ketto_num kt, r.chakujun ch, r.ninki nk, "
        "r.win_odds wo, r.ato3f h_ato3f, r.blinker blinker, r.time h_time, "
        "r.jockey_name jockey_name, "
        "ra.juryo juryo, ra.shusso_tosu tosu, ra.kyori kyori, ra.surface surface, "
        "ra.baba_shiba bsh, ra.baba_dirt bdt, ra.mae3f mae3f, ra.ato3f r_ato3f, "
        "rw.time wtime "
        "FROM results r JOIN races ra ON ra.race_key=r.race_key "
        "JOIN results rw ON rw.race_key=r.race_key AND rw.chakujun=1 "
        "WHERE r.jyo<='10' AND r.chakujun>0 AND CAST(r.year AS INT) >= 2016 "
        "ORDER BY r.race_key").fetchall()
    con.close()
    print(f"  {len(rows):,}行")

    by_race = defaultdict(list)
    for r in rows:
        by_race[r['rk']].append(r)

    # ── 馬ごとの時系列履歴(リーク遮断用): 末脚(agari順位)/近走着順/33ラップ/血統(固定)/
    #    補正タイム原資/初ブリンカー判定用の前走blinker ──
    hist_agari = defaultdict(list)   # kt -> [(rk, agari_rank_ratio)]
    hist_blinker = defaultdict(list)  # kt -> [(rk, blinker)]
    horse_sire = {}
    con = _con()
    hrows = con.execute("SELECT ketto_num, sire, bms FROM horses").fetchall()
    con.close()
    for kt, sire, bms in hrows:
        horse_sire[kt] = (sire, bms)

    for rk, rs in by_race.items():
        n = rs[0]['tosu'] or len(rs)
        a3 = [(x['h_ato3f'], x['kt']) for x in rs if x['h_ato3f'] and x['h_ato3f'] > 0]
        a3.sort(key=lambda t: t[0])
        arank = {kt: (i + 1) / len(a3) for i, (_, kt) in enumerate(a3)} if a3 else {}
        for x in rs:
            if x['h_ato3f'] and x['h_ato3f'] > 0:
                hist_agari[x['kt']].append((rk, arank.get(x['kt'])))
            hist_blinker[x['kt']].append((rk, x['blinker']))
    for k in hist_agari:
        hist_agari[k].sort(key=lambda z: z[0])
    for k in hist_blinker:
        hist_blinker[k].sort(key=lambda z: z[0])

    def past_spurt(kt, rk, n=5, minr=2):
        """末脚指数プロキシ: 過去n走の上がり順位比率平均(低いほど良い)→0-1に反転。"""
        h = hist_agari.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk and v is not None][-n:]
        if len(past) < minr:
            return None
        avg_rank = sum(past) / len(past)
        return 1.0 - avg_rank  # 高いほど好末脚

    def prev_blinker(kt, rk):
        h = hist_blinker.get(kt)
        if not h:
            return None
        past = [v for (k, v) in h if k < rk]
        return past[-1] if past else None

    # 人気別ベース複勝率(区間ごと)
    def popularity_base(y0, y1):
        pt = defaultdict(lambda: [0, 0])
        for rk, rs in by_race.items():
            yr = int(str(rk)[:4])
            if y0 <= yr <= y1:
                for r in rs:
                    if r['nk']:
                        pt[int(r['nk'])][0] += 1 if r['ch'] <= 3 else 0
                        pt[int(r['nk'])][1] += 1
        return {p: (s[0] / s[1] if s[1] else 0.05) for p, s in pt.items()}

    base_train = popularity_base(2021, 2024)
    base_hold = popularity_base(2025, 2025)

    SIGNAL_NAMES = ['blood_score', 'blood_roi100', 'buri', 'corrected_t', 'jpower', 'spurt', 'lap33']
    JP = {'blood_score': '血統スコア上位', 'blood_roi100': '血統実績回収率100%+',
          'buri': '初ブリンカー', 'corrected_t': '補正T上位', 'jpower': '騎手力上位',
          'spurt': '末脚指数上位', 'lap33': '33ラップ適合'}

    # 集計: period -> signal_key(or combo) -> [t3, n]
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    base_agg = defaultdict(lambda: [0, 0])  # period -> [t3, n] (chaos race×人気8+ 全体=分母基準)

    n_chaos_races = 0
    n_races_total = 0
    from core import corrected_time as ct
    from core import jockey_jv as jj

    for rk, rs in by_race.items():
        yr = int(str(rk)[:4])
        if not (2021 <= yr <= 2025):
            continue
        n_races_total += 1
        r0 = rs[0]
        n_horses = r0['tosu'] or len(rs)
        surf = '芝' if '芝' in str(r0['surface']) else 'ダ'
        kyori = r0['kyori']
        baba_code = str(r0['bsh'] if surf == '芝' else r0['bdt'])
        baba = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}.get(baba_code, '良')
        is_handi = (str(r0['juryo']) == '1')
        odds_list = [o / 10.0 for o in (x['wo'] for x in rs) if o and o > 0]
        if not odds_list:
            continue
        if not is_chaos_race(is_handi, n_horses, kyori, baba, odds_list):
            continue
        n_chaos_races += 1
        period = 'train' if yr <= 2024 else 'holdout'
        bp = base_train if period == 'train' else base_hold

        # コース平均33ラップ(このレースのjyo/surf/kyoriで都度取得。lap33側にキャッシュ有)
        # jyoはSELECTしていないため、race_keyの[4:6]から復元
        jyo_code = str(rk)[4:6]
        course_v = l3.course_avg33(surf, kyori, jyo=jyo_code)

        # レース内スコア収集(人気8+のみ対象化)
        cand = []
        for r in rs:
            if not r['nk'] or int(r['nk']) < 8:
                continue
            kt = r['kt']
            cand.append(r)
        if not cand:
            continue

        # 補正T: レース内ランク付け(全馬対象でランクし、人気8+のみ抽出)
        ct_vals = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            fig = ct.get_figure(r['kt'], surf) or ct.get_figure(r['kt'], None)
            if fig and fig.get('fig') is not None:
                ct_vals[r['kt']] = fig['fig']
        ct_rank_top3 = set()
        if ct_vals:
            ranked = sorted(ct_vals.items(), key=lambda x: x[1])[:3]
            ct_rank_top3 = {k for k, _ in ranked}

        # 末脚: レース内ランク付け(全馬)
        spurt_vals = {r['kt']: past_spurt(r['kt'], rk) for r in rs}
        spurt_valid = {k: v for k, v in spurt_vals.items() if v is not None}
        spurt_top3 = set()
        if spurt_valid:
            ranked = sorted(spurt_valid.items(), key=lambda x: -x[1])[:3]
            spurt_top3 = {k for k, _ in ranked}

        # 血統スコア: レース内ランク付け(全馬)
        blood_vals = {}
        for r in rs:
            sire, bms = horse_sire.get(r['kt'], (None, None))
            if sire or bms:
                blood_vals[r['kt']] = bl.blood_score(sire, bms, surf, kyori)
        blood_top3 = set()
        if blood_vals:
            ranked = sorted(blood_vals.items(), key=lambda x: -x[1])[:3]
            blood_top3 = {k for k, _ in ranked}

        # 騎手力: レース内ランク付け(全馬・そのレース時点以前の履歴のみ=リーク遮断)
        jp_vals = {}
        for r in rs:
            jn = r['jockey_name']
            if not jn:
                continue
            jp = jj.jockey_power(jn, before_key=rk)
            if jp.get('jpower') is not None:
                jp_vals[r['kt']] = jp['jpower']
        jp_top3 = set()
        if jp_vals:
            ranked = sorted(jp_vals.items(), key=lambda x: -x[1])[:3]
            jp_top3 = {k for k, _ in ranked}

        for r in cand:
            kt = r['kt']
            t3 = 1 if r['ch'] <= 3 else 0
            base_agg[period][0] += t3
            base_agg[period][1] += 1

            fired = {}
            fired['blood_score'] = kt in blood_top3
            sire, bms = horse_sire.get(kt, (None, None))
            bs = bl.lookup_sire_stats(sire, surf, kyori) if sire else None
            bb = bl.lookup_bms_stats(bms, surf, kyori) if bms else None
            roi_ok = (bs and bs.get('win_roi', 0) >= 100) or (bb and bb.get('win_roi', 0) >= 100)
            fired['blood_roi100'] = bool(roi_ok)
            pb = prev_blinker(kt, rk)
            fired['buri'] = bool(str(r['blinker']) == '1' and str(pb) == '0')
            fired['corrected_t'] = kt in ct_rank_top3
            fired['jpower'] = kt in jp_top3
            fired['spurt'] = kt in spurt_top3
            hfit = l3.horse_fit33(kt, before_key=rk)
            fired['lap33'] = l3.fit_match(hfit.get('avg_lap33'), course_v['avg'] if course_v else None) is True

            for sk in SIGNAL_NAMES:
                if fired.get(sk):
                    a = agg[period][sk]
                    a[0] += t3; a[1] += 1

            n_on = sum(1 for sk in SIGNAL_NAMES if fired.get(sk))
            if n_on >= 2:
                a = agg[period]['combo2+']
                a[0] += t3; a[1] += 1
            if n_on >= 3:
                a = agg[period]['combo3+']
                a[0] += t3; a[1] += 1

    print(f"荒れ予報レース(②穴妙味向き): {n_chaos_races:,} / 全体 {n_races_total:,}")

    def show(period):
        bt3, bn = base_agg[period]
        base_rate = bt3 / bn if bn else 0
        print(f"\n=== {period}: 荒れ予報レース×人気8+ の的中率(基準={100*base_rate:.1f}% n={bn:,}) ===")
        print(f"{'項目':<16}{'n':>8}{'的中率':>8}{'基準比':>9}{'z':>7}")
        for sk in SIGNAL_NAMES + ['combo2+', 'combo3+']:
            t3, n = agg[period][sk]
            if n < 30:
                print(f"{JP.get(sk, sk):<16}{n:>8,}  (n<30)")
                continue
            rate = t3 / n
            exp = base_rate
            z = (t3 - n * exp) / math.sqrt(n * exp * (1 - exp)) if 0 < exp < 1 else 0
            print(f"{JP.get(sk, sk):<16}{n:>8,}{100*rate:>7.1f}%{100*(rate-exp):>+8.2f}pp{z:>+7.1f}")

    show('train')
    show('holdout')
    print("\n[判定] 基準比(pp)が明確にプラスかつz>=2でholdoutも維持なら"
          "『荒れ予報時にこの項目を見る価値あり』。combo2+/3+がさらに伸びれば"
          "複数該当時の精度向上あり=優先確認の目安。")


if __name__ == '__main__':
    main()
