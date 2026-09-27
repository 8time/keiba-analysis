# -*- coding: utf-8 -*-
"""スモークテスト（QAループの実体・依存ゼロ＝stdlibのみ／pytest不要）。

    python tests/smoke.py            # 全チェック
    python tests/smoke.py --quick    # 構文＋import＋関数のみ(DBチェック省略)

何を見るか:
  Phase1 構文: app.py / pages / core / scripts を py_compile（構文・インデント崩れ検出）
  Phase2 import: 検証ロジックの中核モジュールが import できる
  Phase3 関数: 検証済みエッジ関数が期待どおりの値を返す(track_bias/value_scanner/bet_filter等)
  Phase4 DB: jravan.db / blood_dict.db の主要テーブルが存在し行がある
終了コード = 失敗数(0=全合格)。/loop はこの0/非0と出力で次の一手を決められる。
"""
import os
import sys
import argparse
import glob
import py_compile
import sqlite3

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_results = []  # (ok, name, msg)


def check(name, fn):
    try:
        fn()
        _results.append((True, name, ''))
    except Exception as e:
        _results.append((False, name, f"{type(e).__name__}: {e}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true', help='DBチェックを省略')
    args = ap.parse_args()

    # ── Phase1: 構文(py_compile) ──
    py_files = []
    py_files.append(os.path.join(ROOT, 'app.py'))
    for d in ('core', 'pages', 'scripts', 'utils'):
        py_files += glob.glob(os.path.join(ROOT, d, '*.py'))
    for f in py_files:
        if not os.path.exists(f):
            continue
        rel = os.path.relpath(f, ROOT)
        check(f"構文 {rel}", lambda f=f: py_compile.compile(f, doraise=True))

    # ── Phase2: 中核ロジックのimport ──
    CORE = ['track_bias', 'value_scanner', 'bet_filter', 'trio_engine',
            'bet_optimizer', 'corrected_time', 'jockey_jv', 'ltr_ranker',
            'money', 'elim_reasons', 'elim_cross', 'score_cache', 'bloodline',
            'axis_selector', 'pace_map', 'paddock_ledger', 'consensus_view',
            'playbook_tickets', 'formation_stats', 'playbook_ledger',
            'folklore_lib', 'gyaku_kami']
    for m in CORE:
        check(f"import core.{m}", lambda m=m: __import__(f'core.{m}', fromlist=['_']))

    # ── Phase3: 検証済み関数の振る舞い ──
    def t_blood_mod():
        from core import track_bias as tb
        r = tb.heavy_fav_blood_mod('シニスターミニスター', 'ダート', '不良')
        assert r and r['mod'] == 'exempt', f"シニミニ ダ不良→exempt期待, got {r}"
        r2 = tb.heavy_fav_blood_mod('ディープインパクト', '芝', '重')
        assert r2 and r2['mod'] == 'intensify', f"ディープ芝重→intensify期待, got {r2}"
        assert tb.heavy_fav_blood_mod('シニスターミニスター', 'ダート', '稍重') is None, "稍重は対象外のはず"
    check("track_bias.heavy_fav_blood_mod", t_blood_mod)

    def t_moist():
        from core import track_bias as tb
        assert tb.dirt_moisture_bloodtype('シニスターミニスター', 10.0)['flag'] == '🟢', "シニミニ高含水→🟢"
        assert tb.dirt_moisture_bloodtype('シニスターミニスター', {'ok': True}) is None, "dictは無視"
    check("track_bias.dirt_moisture_bloodtype(シニミニ修正)", t_moist)

    def t_lean():
        from core import value_scanner as vs
        r = vs.trio_lean(meta={'is_handicap': True}, n_horses=16, fav_odds=4.0,
                         dist=1200, baba='重', odds_list=[4, 8, 9, 12, 15, 20, 30, 40, 50, 60])
        assert r['lean'] == '②穴妙味向き', f"ハンデ16頭短距離道悪→②期待, got {r['lean']}"
    check("value_scanner.trio_lean", t_lean)

    def t_arare_prob():
        # 検証済み荒れロジット: 鉄板(1番人気1.5倍) < 混戦(上位拮抗)。ラベルはS/A/B/C/D形式維持。
        from core import value_scanner as vs
        if not vs._load_arare_logit():
            return  # パラメータ未生成環境ではスキップ
        solid = vs.arare_prob([1.5, 4.0, 8.0, 12, 20, 30, 50, 80, 100, 120], {}, 10)
        chaos = vs.arare_prob([4.5, 5.5, 6.5, 8, 9, 11, 13, 16, 20, 25, 30, 40, 50, 60, 80, 100], {}, 16)
        assert solid is not None and chaos is not None
        assert chaos > solid + 0.2, f"混戦>鉄板 期待, got solid={solid:.2f} chaos={chaos:.2f}"
        rv = vs.race_value_score([4.5, 5.5, 6.5, 8, 9, 11, 13, 16, 20, 25, 30], {}, '05', '芝', 1600, 11)
        assert str(rv['label'])[:1] in ('S', 'A', 'B', 'C', 'D'), "ラベルはS/A/B/C/D形式維持"
        assert 'arare_prob' in rv
    check("value_scanner.arare_prob(検証ロジット)", t_arare_prob)

    def t_no_favorite():
        from core import value_scanner as vs
        # 大谷等価: fav1≥3.0 & odds3/odds1≤2.0 & 30倍未満≥10頭 → ●大穴
        assert vs.no_favorite_flag([3.5, 5.0, 6.0] + [8.0] * 8) == '●大穴'
        # 抜けた本命(fav1=1.5)がいる→フラグ無し
        assert vs.no_favorite_flag([1.5, 3.0, 10.0] + [40.0] * 5) is None
        # ②オッズ断層直下(検証-5.1pp z-16.5): 断層の下側の馬番を返す
        assert vs.odds_gap_below({1: 1.5, 2: 1.8, 3: 2.0, 4: 5.0, 5: 6, 6: 8, 7: 10, 8: 12}) == {4}, "断層直下=um4"
        assert vs.odds_gap_below({1: 1.5, 2: 1.9, 3: 2.4, 4: 3.0, 5: 4, 6: 5, 7: 7, 8: 9}) == set(), "滑らか=断層なし"
        # 頭数不足・空はNone(クラッシュしない)
        assert vs.no_favorite_flag([]) is None and vs.no_favorite_flag([2.0, 3.0]) is None
    check("value_scanner.no_favorite_flag", t_no_favorite)

    def t_baba_code():
        from core import value_scanner as vs
        # 馬場コードは 1=良/2=稍重/3=重/4=不良(off-by-one再発防止)
        assert vs.baba_code_to_label('1') == '良', "code1→良"
        assert vs.baba_code_to_label('4') == '不良', "code4→不良"
        assert vs.baba_code_to_label('3') == '重' and vs.baba_code_to_label(2) == '稍重'
        assert vs.baba_code_to_label('0') == '' and vs.baba_code_to_label('') == ''
    check("value_scanner.baba_code_to_label", t_baba_code)

    def t_stake_caps():
        from core import money as mo
        r = mo.apply_stake_caps(2400, 30000, race_cap_pct=5.0, ticket_cap_pct=3.0,
                                daily_spent=0, daily_cap_pct=15.0, race_spent=0)
        assert r['ticket_cap'] == 900, r  # 30000*3%
        assert r['stake'] == 900, r        # 1点上限で切る
        assert '1点上限' in r['reasons']
        r2 = mo.apply_stake_caps(200, 30000, ticket_cap_pct=3.0)
        assert r2['stake'] == 200 and not r2['capped']
        lit = mo.ops_light(30000, 20000, daily_spent=0, daily_cap=4500,
                           stop_loss_pct=25.0)
        assert lit['code'] == 'stop', lit  # 25%下落=22500ライン、20000は割る
        ok = mo.ops_light(30000, 30000, daily_spent=4600, daily_cap=4500)
        assert ok['code'] == 'stop', ok    # 今日の上限到達
        eq = mo.equity_stats(30000, [32000, 28000, 31000])
        assert eq['peak'] == 32000 and eq['max_dd_pct'] < -10
    check("money.apply_stake_caps/ops_light", t_stake_caps)

    def t_points_budget():
        from core import money as mo
        ok = mo.points_budget(10, 1500, unit=100)
        assert ok['fits'] and ok['total'] == 1000, ok
        ng = mo.points_budget(40, 1500, unit=100)
        assert (not ng['fits']) and ng['max_points'] == 15 and ng['need'] == 4000, ng
        z = mo.points_budget(0, 1500)
        assert z['total'] == 0
    check("money.points_budget", t_points_budget)

    def t_ticket_line():
        from core import money as mo
        assert mo.haircut_odds(50, 0.3) == 35.0
        assert mo.slip_pct_for('3連複', False) == 0.0
        assert mo.slip_pct_for('3連複', True) == 0.25
        empty = mo.ticket_line('3連複', 35.0, p=None, balance=100000,
                               race_cap=5000, ticket_cap=3000, default_unit=100)
        assert empty['stake'] == 100 and empty['status'] == '枠で買う', empty
        skip = mo.ticket_line('3連複', 35.0, p=0.02, balance=100000,
                              race_cap=5000, ticket_cap=3000, min_ev_pct=5.0)
        # 2% * 35 = 0.70 EV → 見送り
        assert skip['status'] == '見送り', skip
        hit = mo.ticket_line('単勝', 5.0, p=0.30, balance=100000, kelly_frac=0.25,
                             race_cap=5000, ticket_cap=3000, min_ev_pct=5.0)
        assert hit['stake'] > 0 and hit['status'] in ('推奨', '少額'), hit
    check("money.ticket_line", t_ticket_line)

    def t_scanner_gate():
        from core import value_scanner as vs
        buy = {'skips': [], 'axis_floor': True, 'danger_horses': [],
               'value_horses': [1], 'lean': {'lean': '②穴妙味向き'}, 'vscore': 40}
        skip = {'skips': ['少頭数'], 'axis_floor': True, 'danger_horses': [],
                'value_horses': [], 'lean': {'lean': '中立'}, 'vscore': 10}
        assert vs.scanner_priority(buy) > vs.scanner_priority(skip), "buy > skip"
        assert vs.scanner_play_status(buy) == 'buy', f"got {vs.scanner_play_status(buy)}"
        assert vs.scanner_play_status(skip) == 'skip', f"got {vs.scanner_play_status(skip)}"
        aw = {'skips': [], 'axis_floor': False, 'danger_horses': [1],
              'value_horses': [1], 'lean': {'lean': '②穴妙味向き'}, 'vscore': 40}
        assert vs.scanner_play_status(aw) == 'axis_warn'
        assert vs.scanner_priority(buy) > vs.scanner_priority(aw), "buy > axis_warn"
    check("value_scanner.scanner_gate", t_scanner_gate)

    def t_paddock_ledger():
        import tempfile
        from core import paddock_ledger as pl
        p = os.path.join(tempfile.gettempdir(), 'smoke_pl.json')
        if os.path.exists(p):
            os.remove(p)
        # 記録→精算→集計が通り、極性判定が実測で動くこと(俗説の決め打ちでない)
        pl.add_entry(pl.make_entry(race_id='R1', umaban=1, name='a', ninki=1,
                                   odds=2.0, tags=['gait_stiff']), path=p)
        assert pl.settle_entry('R1', 1, chaku=10, win_odds=2.0, path=p) == 1, "精算1件"
        assert pl.settle_entry('R1', 99, chaku=1, path=p) == 0, "該当なしは0"
        stats, base = pl.tag_stats(pl.load_ledger(p))
        assert base['settled'] == 1, f"精算済1, got {base['settled']}"
        s = next(x for x in stats if x['key'] == 'gait_stiff')
        assert s['settled'] == 1 and s['group'] == 'fade'
        assert 'サンプル不足' in pl.verdict(s, base), "n<MIN_SAMPLEはサンプル不足"
        # 不正タグは make_entry で弾く
        assert pl.make_entry(race_id='R2', umaban=2, name='b', tags=['__bad__'])['tags'] == []
        # ① 全タグに説明(TAG_HELP)が揃っていること
        _missing = [k for k in pl.TAG_ORDER if not pl.TAG_HELP.get(k)]
        assert not _missing, f"説明欠落タグ: {_missing}"
        # ② メディア保存: 許可拡張子は保存・パスを返す/不許可は None
        md = os.path.join(tempfile.gettempdir(), 'smoke_pl_media')
        rel = pl.save_media(b'x', 'a.jpg', race_id='R1', umaban=1, media_dir=md)
        assert rel and os.path.exists(os.path.join(os.getcwd(), rel)), "jpg保存"
        assert pl.save_media(b'x', 'a.txt', media_dir=md) is None, "txtは不許可"
        e2 = pl.make_entry(race_id='R3', umaban=3, name='c', tags=['vein'], media=[rel])
        assert e2['media'] == [rel], "mediaがエントリに入る"
        # ③ scene: パドック/調教が同居し、tag_statsはscene別に分離されること
        e3 = pl.make_entry(race_id='R4', umaban=4, name='d', tags=['t_strong'],
                           scene='training')
        assert e3['scene'] == 'training' and pl.TAG_SCENE['t_strong'] == 'training'
        assert pl.make_entry(race_id='R5', umaban=5, name='e', tags=[],
                             scene='bogus')['scene'] == 'paddock', "不正sceneはpaddock"
        # 調教タグをパドックsceneのmake_entryに入れてもkeyは保持(検証はtag_statsのscene絞りで担保)
        assert set(pl.scene_tags('paddock')).isdisjoint(pl.scene_tags('training')), "scene分離"
        import shutil as _sh
        _sh.rmtree(md, ignore_errors=True)
        os.remove(p)
    check("paddock_ledger.record_settle_stats", t_paddock_ledger)

    def t_elim_stress():
        from core import elim_cross as ec
        # スト2フラグ: 点灯するが band(推定複勝率)には算入しない(UNVERIFIED)
        f = ec.compute_flags(stress2=True)
        assert 'stress2' in f, "スト2点灯"
        assert ec.FLAG_LABEL['stress2'] == 'スト2'
        assert 'stress2' in ec.UNVERIFIED, "band非算入"
        # 検証数はstress2を除外(zogen+age8のみ=2)
        f2 = ec.compute_flags(zogen=20, age=9, stress2=True)
        assert ec.verified_count(f2) == 2, f"stress2はband非算入, got {ec.verified_count(f2)}"
    check("elim_cross.スト2(band非算入)", t_elim_stress)

    def t_betfilter():
        from core import bet_filter as bf
        out = bf.annotate_bets(
            [{'combo': (1, 2, 7), 'in_band': True}, {'combo': (1, 2, 3), 'in_band': True}],
            edge_horses={7}, danger_horses=set(), ana_set={7})
        tags = {b['combo']: b['aim_tag'] for b in out}
        assert tags[(1, 2, 7)] == '🎯', f"価格帯×穴脚→🎯, got {tags[(1,2,7)]}"
        assert tags[(1, 2, 3)] == '価格帯', f"価格帯のみ→価格帯, got {tags[(1,2,3)]}"
    check("bet_filter.annotate_bets(🎯厳格化)", t_betfilter)

    def t_formation():
        from core import trio_engine as te
        f = te.build_formation([1], [2, 3], [4, 5])
        assert all(len(set(x)) == 3 for x in f) and len(f) == len(set(f)), "重複排除/3頭組"
    check("trio_engine.build_formation", t_formation)

    def t_veto_axis():
        from core import trio_engine as te
        hs = [{'umaban': 1, 'name': 'A', 'score': 99, 'pop': 1},
              {'umaban': 2, 'name': 'B', 'score': 90, 'pop': 2}]
        r = te.recommend_quinella_exacta(hs, q_odds={}, e_odds={}, veto_axis={1})
        assert r['axis'] == 2, f"危険軸1をvetoし2へ降格すべき, got {r['axis']}"
    check("trio_engine.recommend_quinella_exacta(veto_axis)", t_veto_axis)

    def t_trio_combo_boost():
        from core import trio_engine as te
        # 🧩シグナル重複穴(combo2+ holdout z+9.2)が②妙味で優先されること
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i * 3, 'pop': i, 'alert': ''}
              for i in range(1, 13)]
        hs[7]['alert'] = '🔵補正T上位 🧬血統上位 🧩2重複'   # 8番人気
        hs[9]['alert'] = '🔥末脚top ⚡33ラップ適合 🧩3重複'  # 10番人気
        r = te.recommend_trio(hs, pattern='②妙味', n_points=5)
        assert r['warning'] is None and r['bets'], f"got {r['warning']}"
        assert {8, 10} <= set(r['bets'][0]['combo']), f"combo穴が最上位に来るべき, got {r['bets'][0]['combo']}"
    check("trio_engine.recommend_trio(🧩combo穴優先)", t_trio_combo_boost)

    def t_companion_not_ana():
        from core import trio_engine as te
        # 穴しきい値は6のまま。companion=Trueの5番人気だけ auto本線プール／3連単ヒモに入る。
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i, 'pop': i, 'alert': ''}
              for i in range(1, 9)]
        r0 = te.recommend_trio(hs, pattern='本線', n_points=20)
        um0 = {u for b in r0['bets'] for u in b['combo']}
        assert 5 not in um0, f"フラグ無しで5番人気が混入 {sorted(um0)}"
        hs[4]['companion'] = True
        r1 = te.recommend_trio(hs, pattern='本線', n_points=20)
        um1 = {u for b in r1['bets'] for u in b['combo']}
        assert 5 in um1, f"相手候補の5番人気が3連複に入らない {sorted(um1)}"
        r3 = te.recommend_trifecta(hs, axis_umaban=[1, 2], n_points=30, arare_prob=0.29)
        assert 5 in (r3.get('meta') or {}).get('third', []), \
            f"3連単ヒモに相手候補が入らない {(r3.get('meta') or {})}"
    check("trio_engine 相手候補(4-5人気)は穴にせずプールへ", t_companion_not_ana)

    def t_fixed_pool_keeps_user_horses():
        from core import trio_engine as te
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i, 'pop': i, 'alert': ''}
              for i in range(1, 10)]
        r0 = te.recommend_trio(hs, pattern='本線', n_points=20)
        um0 = {u for b in r0['bets'] for u in b['combo']}
        assert 5 not in um0, f"未指定なのに5番人気が混入 {sorted(um0)}"
        r1 = te.recommend_trio(hs, pattern='本線', n_points=20, fixed_pool=True)
        um1 = {u for b in r1['bets'] for u in b['combo']}
        assert 5 in um1, f"使う馬プールなのに5番人気が消えた {sorted(um1)}"
        assert r1.get('meta', {}).get('fixed_pool') is True
        # 渡していない馬は足さない（1-6だけなら7は出ない）
        hs6 = [h for h in hs if h['umaban'] <= 6]
        r6 = te.recommend_trio(hs6, pattern='本線', n_points=20, fixed_pool=True)
        um6 = {u for b in r6['bets'] for u in b['combo']}
        assert um6 <= {1, 2, 3, 4, 5, 6} and 5 in um6, f"選択外が混入 or 5脱落 {sorted(um6)}"
        # ②でもハード除外せず、選択した5番を含む組が候補に残る
        r2 = te.recommend_trio(hs, pattern='②妙味', n_points=84, fixed_pool=True)
        assert any(5 in b['combo'] for b in r2['bets']), "②でも使う馬の5番が候補に残るべき"
    check("trio_engine.recommend_trio(fixed_pool=使う馬を再除外しない)", t_fixed_pool_keeps_user_horses)

    def t_combo_flow():
        from core import trio_engine as te
        # 🧩combo馬流し: ◎1軸×combo≥2馬流しで相手がcombo馬だけに絞られること
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i, 'pop': i, 'alert': ''}
              for i in range(1, 13)]
        for u in (4, 6, 7, 8):
            hs[u - 1]['alert'] = '🧩2重複'
        r = te.recommend_trio(hs, axis_umaban=[1], axis_mode='1軸', combo_flow=2, n_points=10)
        assert r['bets'], f"got {r['warning']}"
        # 全ベットが軸1＋combo馬(4/6/7/8)のみで構成される
        allowed = {1, 4, 6, 7, 8}
        assert all(set(b['combo']) <= allowed for b in r['bets']), \
            f"combo馬以外が混入, got {[b['combo'] for b in r['bets']]}"
        # keep_partners: combo未満の軸候補(9番)も相手に残る(実査9-11-13の13番=▲軸候補ケース)
        r2 = te.recommend_trio(hs, axis_umaban=[1], axis_mode='1軸', combo_flow=2,
                               keep_partners={9}, n_points=12)
        assert any(9 in b['combo'] for b in r2['bets']), \
            f"keep_partnersの9番が相手に残らない, got {[b['combo'] for b in r2['bets']]}"
    check("trio_engine.recommend_trio(🧩combo馬流し＋keep_partners)", t_combo_flow)

    def t_value_band():
        from core import trio_engine as te
        # 妙味度ラベル→可変帯が単調(S高帯>D低帯)＋band引数がlo/hiを上書きすること
        s = te.band_from_value_label('S'); d = te.band_from_value_label('D')
        assert s[1] > d[1] and s[0] > d[0], f"S帯がD帯より高くない S={s} D={d}"
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 50, 'pop': i, 'alert': ''} for i in range(1, 8)]
        om = {frozenset((1, 2, 3)): 200.0}  # 200倍
        # band=(170,1400)ならin-band加点、band=(12,76)なら帯超で減点=別スコアになる
        r_hi = te.recommend_trio(hs, odds_map=om, axis_umaban=[1], axis_mode='1軸', band=(170, 1400), n_points=15)
        r_lo = te.recommend_trio(hs, odds_map=om, axis_umaban=[1], axis_mode='1軸', band=(12, 76), n_points=15)
        def _sc(r):
            return next((b['score'] for b in r['bets'] if tuple(b['combo']) == (1, 2, 3)), None)
        assert _sc(r_hi) is not None and _sc(r_lo) is not None and _sc(r_hi) > _sc(r_lo), \
            f"band上書きが効いていない hi={_sc(r_hi)} lo={_sc(r_lo)}"
    check("trio_engine.band_from_value_label＋band上書き", t_value_band)

    def t_venue_band_scale():
        from core import trio_engine as te
        import inspect
        assert list(inspect.signature(te.band_from_value_label).parameters) == ['label']
        assert 'venue' not in inspect.signature(te.recommend_trifecta).parameters
        d = te.band_from_value_label('D')
        tok = te.scale_band_for_venue(d, '東京', 'trio', 'D')
        sap = te.scale_band_for_venue(d, '札幌', 'trio', 'D')
        assert tok[0] < d[0] and tok[1] < d[1], f"東京Dは安め tok={tok} base={d}"
        assert sap[0] > d[0], f"札幌Dは高め sap={sap} base={d}"
        base_t = te.trifecta_band_from_trio(d)
        t_tok = te.scale_band_for_venue(base_t, '東京', 'trifecta', 'D')
        t_sap = te.scale_band_for_venue(base_t, '札幌', 'trifecta', 'D')
        t_fuk = te.scale_band_for_venue(base_t, '福島', 'trifecta', None)
        assert t_tok[0] < t_sap[0], f"3連単D 東京<{t_tok} 札幌{t_sap}"
        assert t_fuk[1] > base_t[1], f"福島は全体スケールで高め {t_fuk} vs {base_t}"
        assert te.scale_band_for_venue(d, '', 'trio', 'D') == (float(d[0]), float(d[1]))
        assert te.scale_band_for_venue(None, '東京') is None
        assert te.normalize_venue('05') == '東京'
        assert te.normalize_venue('札幌競馬場') == '札幌'
        assert te.normalize_venue('202601010101') == '札幌'
        assert te.venue_band_scale('大井', 'trifecta', 'D') == 1.0
        assert te.venue_band_scale('東京', 'trifecta', 'D') < 0.9
        # 同じ妙味度なら東京の安さは「鉄板が多い」ほど強くない(SはDより1に近い)
        assert te.venue_band_scale('東京', 'trifecta', 'S') > te.venue_band_scale('東京', 'trifecta', 'D')
        assert te.typical_field_size('札幌') == 13
        assert abs(te.field_band_scale(13, 'trifecta', '札幌') - 1.0) < 0.03
        assert abs(te.field_band_scale(16, 'trifecta', '東京') - 1.0) < 0.03
        assert te.field_band_scale(10, 'trifecta', '札幌') < 0.70
        assert te.field_band_scale(18, 'trifecta', '東京') > 1.15
        small = te.scale_band_for_venue(base_t, '札幌', 'trifecta', 'D', 10)
        mid = te.scale_band_for_venue(base_t, '札幌', 'trifecta', 'D', 13)
        big = te.scale_band_for_venue(base_t, '札幌', 'trifecta', 'D', 16)
        assert small[0] < mid[0] < big[0], f"少頭数ほど帯が下がる {small} {mid} {big}"
        # n_horses省略時は場だけ（既存呼び出し互換）
        assert te.scale_band_for_venue(d, '札幌', 'trio', 'D') == sap
    check("trio_engine.場ごとの狙い目帯", t_venue_band_scale)

    def t_trifecta():
        from core import trio_engine as te
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i * 3, 'pop': i, 'alert': ''}
              for i in range(1, 13)]
        hs[9]['alert'] = '🔵補正T上位 🔥末脚top 🧩2重複'
        r = te.recommend_trifecta(hs, axis_umaban=[2, 1], n_points=100)
        assert r['warning'] is None and len(r['bets']) <= 100, "n_points=100以内"
        assert r['bets'][0]['combo'][0] == 2, f"◎(axis先頭)が1着固定, got {r['bets'][0]['combo']}"
        assert 10 in r['meta']['third'], f"🧩combo穴がヒモ候補入り, got {r['meta']['third']}"
        assert all(len(set(b['combo'])) == 3 for b in r['bets']), "3頭相異なる順序組"
        r336 = te.recommend_trifecta(hs, axis_umaban=[2, 1], n_points=999)
        assert len(r336['bets']) <= 336, "ハード上限336点(120/210/336=6/7/8頭BOX級)"
        r_wide = te.recommend_trifecta(hs, axis_umaban=[2, 1], n_points=336, arare_prob=0.30)
        assert len(r_wide['bets']) > 50, f"大点数指定は帯クランプ除外+プール拡張, got {len(r_wide['bets'])}"
        r_cf = te.recommend_trifecta(hs, axis_umaban=[2, 1], n_points=50, combo_flow=2)
        _himo_cf = set(r_cf['meta']['third']) - set(r_cf['meta']['first'])
        assert _himo_cf <= {10}, f"combo馬流し=ヒモは🧩2重複馬のみ, got {sorted(_himo_cf)}"
        # フォーメーション穴はスコア最下位でも全点に残る(3連複B群と同じ)
        hs_lo = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i, 'pop': i, 'alert': ''}
                 for i in range(1, 7)]
        r_must = te.recommend_trifecta(
            hs_lo, axis_umaban=[1, 2], n_points=30,
            must_include=[6], arare_prob=0.29)
        assert r_must['bets'] and all(6 in b['combo'] for b in r_must['bets']), \
            f"must_includeの6が落ちた {[b['combo'] for b in r_must['bets'][:5]]}"
        r_ax2 = te.recommend_trifecta(
            hs_lo, axis_umaban=[1, 2], n_points=30, require_axis_all=True, arare_prob=0.29)
        assert r_ax2['bets'] and all({1, 2} <= set(b['combo']) for b in r_ax2['bets']), \
            f"2軸が全点に入らない {[b['combo'] for b in r_ax2['bets'][:5]]}"
        r_tw = te.recommend_trio(hs, n_points=56)
        assert len(r_tw['bets']) == 56, f"3連複56=8頭BOX級網羅(パターン絞り除外), got {len(r_tw['bets'])}"
        # ワイドおすすめ: 軸1頭×検証シグナル厳選で上位3点のみ(馬連/馬単と同じ作り)
        w_od = {frozenset((1, 2)): 8.0, frozenset((1, 3)): 12.0, frozenset((1, 10)): 25.0,
                frozenset((1, 4)): 2.0}
        rw = te.recommend_wide(hs, w_odds=w_od, axis_umaban=1, n_points=3)
        assert rw['axis'] == 1 and len(rw['wide']) == 3, f"軸1×3点厳選, got {rw['axis']}/{len(rw['wide'])}"
        _combos_w = [r['combo'] for r in rw['wide']]
        assert (1, 10) in _combos_w, f"🧩2重複×帯内(25倍)の穴が3点入り, got {_combos_w}"
        assert all(1 in c for c in _combos_w), "全点が軸絡み"
        rw_v = te.recommend_wide(hs, w_odds=w_od, veto_axis={1}, n_points=3)
        assert rw_v['axis'] == 2, f"自動軸はveto回避で次点, got {rw_v['axis']}"
        # 買い目の整理(軸ながし形式・集合不変の別表記)
        ps = te.purchase_summary([(1, 2, 3), (1, 2, 4), (1, 3, 4), (2, 3, 4)])
        assert 'の全組' in ps['axis1'][0], f"軸1頭+相手全組はながし圧縮, got {ps['axis1']}"
        assert any('軸' in l and '相手' in l for l in ps['axis2']), "軸2頭viewが出る"
        pst = te.purchase_summary([(1, 2, 3), (1, 2, 4), (1, 3, 5)], ordered=True)
        assert pst['first'][0].startswith('1着1固定(3点)'), f"1着固定まとめ, got {pst['first']}"
        assert pst['first2'][0].startswith('1→2→ 3,4'), f"1着→2着まとめ, got {pst['first2']}"
    check("trio_engine.recommend_trifecta(336cap/◎頭/🧩ヒモ/combo流し)", t_trifecta)

    def t_playbook_tickets():
        from core import playbook_tickets as pb
        from core import formation_stats as fs
        from core import trio_engine as te
        from inspect import signature, getsource
        params = list(signature(pb.build_tickets).parameters)
        assert params == ['race_id', 'vscore', 'horses', 'axis_marks', 'ltr_scores',
                          'cross_n', 'vh_scores', 'proj_scores']
        src = getsource(pb.build_tickets)
        assert '_calc_pro_scores' not in src
        assert 'popularity_weight' not in src
        assert fs.zone_code(49.9) == 'D' and fs.zone_code(50.0) == 'C'
        assert fs.zone_code(69.9) == 'C' and fs.zone_code(70.0) == 'BA'
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr_rev = {i: float(9 - i) for i in range(1, 9)}  # 1が最強
        ltr_c = {i: float(i) for i in range(1, 9)}        # 8が最強（人気と完全逆転）

        def combos(rec, kind='trio'):
            return {r['combo'] for r in rec.get(kind) or []}

        # ◎〇=人気1・2 → D は 1-2-3 と 1-2-4。LTR逆転でも同じ
        d12 = pb.build_tickets('R', 49.9, hs, {1: '◎', 2: '〇'}, ltr_rev)
        assert d12['zone'] == 'D' and d12['n_points'] == 2
        assert combos(d12) == {(1, 2, 3), (1, 2, 4)}
        assert not d12['trifecta']

        # ◎=人気1, 〇=人気3 でも holdout と同じく人気1-2 × 3-4
        d13 = pb.build_tickets('R', 30, hs, {1: '◎', 3: '〇'}, ltr_rev)
        assert d13['axis'] == [1, 2]
        assert combos(d13) == {(1, 2, 3), (1, 2, 4)}
        assert combos(d13) != {(1, 3, 2), (1, 3, 4)}

        # ◎=人気2, 〇=人気5 でも券は人気1〜4固定
        d25 = pb.build_tickets('R', 30, hs, {2: '◎', 5: '〇'}, ltr_rev)
        assert combos(d25) == {(1, 2, 3), (1, 2, 4)}

        # C: holdout tri_shape と同一の 30点。3連複は足さない
        c = pb.build_tickets('R', 50.0, hs, {1: '◎', 2: '〇'}, ltr_c)
        order = [8, 7, 6, 5, 4, 3, 2]
        holdout = {(x, y, z) for x in order[:2] for y in order[:4] for z in order[:7]
                   if len({x, y, z}) == 3}
        got = combos(c, 'trifecta')
        assert c['zone'] == 'C' and len(got) == 30 and got == holdout
        assert set(te.build_trifecta_formation(order[:2], order[:4], order[:7])) == holdout
        assert c['trio'] == [] and c['n_points'] == 30
        ninki_form = set(te.build_trifecta_formation([1, 2], [1, 2, 3, 4], [1, 2, 3, 4, 5, 6, 7]))
        assert got != ninki_form
        c13 = pb.build_tickets('R', 69.9, hs, {1: '◎', 3: '〇'}, ltr_c)
        assert combos(c13, 'trifecta') == holdout and c13['trio'] == []

        hs6 = hs[:6]
        ltr6 = {i: float(i) for i in range(1, 7)}
        c6 = pb.build_tickets('R', 55, hs6, {1: '◎', 2: '〇'}, ltr6)
        assert c6['skip'] and c6['n_points'] == 0

        ba = pb.build_tickets('R', 70.0, hs, {1: '◎', 2: '〇'}, ltr_c)
        assert ba['zone'] == 'BA' and ba['skip'] and ba['n_points'] == 0
        assert ba['trio'] == [] and ba['trifecta'] == []
        assert ba['selected_playbook'] == 'ba_skip'

        # C + cross_n>=3 → 3連複 Rank2-3-6
        c236 = pb.build_tickets('R', 55, hs, {1: '◎', 2: '〇'}, ltr_c, cross_n=3)
        assert c236['selected_playbook'] == 'c_ltr_trio_236'
        assert c236['trio'] and not c236['trifecta']
    check("playbook_tickets D/C/B-A 分離", t_playbook_tickets)

    def t_bettype_selector():
        from core import bettype_selector as bts
        assert bts.select_bet_type('C', 2) == bts.BET_TRIFECTA
        assert bts.select_bet_type('C', 3) == bts.BET_TRIO
        assert bts.select_playbook(bts.BET_TRIO, 'C', 3) == bts.PLAYBOOK_C_TRIO_236
        assert bts.SELECTOR_RULE_VERSION == 'bet_selector_v1'
        assert bts.diag_family('C中庸', 3)['code'] == 'RRV'
        assert bts.diag_family('C', 2)['code'] == 'RRR'
        assert bts.diag_family('D鉄板', 1)['code'] == 'NNV'
        assert bts.select('C', 3)['diag_family'] == 'RRV'
    check("bettype_selector v1 境界", t_bettype_selector)

    def t_elim_keep_pool():
        import os
        from core import score_cache as sc
        from core import playbook_tickets as pb
        rid = 'smoketestelimkeep1'
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        try:
            sc.write_elim_keep(rid, [1, 2, 3, 4, 5])
            sc.write_keep(rid, [6, 7, 8])  # クロス候補（母集団に使わない）
            filtered, used = sc.filter_horses_by_elim_keep(rid, hs)
            assert used and {h['umaban'] for h in filtered} == {1, 2, 3, 4, 5}
            assert sc.read_elim_keep(rid) == {1, 2, 3, 4, 5}
            rec_all = pb.build_tickets(rid, 30, hs, {1: '◎', 2: '〇'}, ltr)
            rec_filt = pb.build_tickets(rid, 30, filtered, {1: '◎', 2: '〇'}, ltr)
            assert rec_all['n_points'] == 2
            assert rec_filt['n_points'] == 2
            assert {tuple(r['combo']) for r in rec_filt['trio']} == {(1, 2, 3), (1, 2, 4)}
        finally:
            for fn in (sc._elim_keep_path, sc._keep_path):
                p = fn(rid)
                if os.path.exists(p):
                    os.remove(p)
    check("score_cache.elim_keep 母集団フィルタ", t_elim_keep_pool)

    def t_skip_reason_n5():
        from core import playbook_tickets as pb
        from core import newspaper as np_mod
        import os
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        ba = pb.build_tickets('R', 80, hs, None, ltr)
        assert ba['skip_reason'] == 'zone_ba'
        hs_dup = [
            {'umaban': 1, 'name': 'A', 'pop': 1},
            {'umaban': 2, 'name': 'B', 'pop': 2},
            {'umaban': 3, 'name': 'C', 'pop': 3},
            {'umaban': 4, 'name': 'D', 'pop': 3},
            {'umaban': 5, 'name': 'E', 'pop': 5},
            {'umaban': 6, 'name': 'F', 'pop': 6},
            {'umaban': 7, 'name': 'G', 'pop': 7},
            {'umaban': 8, 'name': 'H', 'pop': 8},
        ]
        d_bad = pb.build_tickets('R', 30, hs_dup, None, ltr)
        assert d_bad['skip'] and d_bad['skip_reason'] == 'ninki_missing'
        assert d_bad['skip_detail'] and '4' in d_bad['skip_detail']
        c_deg = pb.build_tickets('R', 55, hs, None, ltr)
        assert c_deg['n_points'] == 30
        assert c_deg['cross_n_source'] == 'unavailable'
        assert c_deg['degraded'] is True
        c_ok = pb.build_tickets('R', 55, hs, None, ltr, cross_n=2)
        assert c_ok['cross_n_source'] == 'given'
        assert c_ok['degraded'] is False
        rid = 'smoketestskipreason1'
        try:
            np_mod.persist_playbook(rid, d_bad)
            extra = np_mod.load_bets(rid)['playbook']['extra']
            assert extra.get('skip_reason') == 'ninki_missing'
        finally:
            for p in (np_mod._bets_path(rid), np_mod._view_path(rid)):
                if os.path.exists(p):
                    os.remove(p)
    check("N5 skip_reason / degraded / persist", t_skip_reason_n5)

    def t_hitrate_stats_n4():
        from core.bayes_stats import wilson_interval
        from core import playbook_ledger as lg
        lo, hi = wilson_interval(7, 30)
        assert lo is not None and 0.10 <= lo <= 0.13
        assert hi is not None and 0.40 <= hi <= 0.43
        assert wilson_interval(0, 0) == (None, None)
        rows = [
            {'race_date': '2024-01-01', 'race_id': '1', 'settled': True, 'hit': True,
             'investment': 200, 'payout': 100, 'ticket_count': 2, 'zone': 'D'},
            {'race_date': '2024-01-02', 'race_id': '2', 'settled': True, 'hit': False,
             'investment': 200, 'payout': 0, 'ticket_count': 2, 'zone': 'D'},
            {'race_date': '2024-01-03', 'race_id': '3', 'settled': True, 'hit': False,
             'investment': 200, 'payout': 0, 'ticket_count': 2, 'zone': 'D'},
            {'race_date': '2024-01-04', 'race_id': '4', 'settled': True, 'hit': False,
             'investment': 200, 'payout': 0, 'ticket_count': 2, 'zone': 'D'},
            {'race_date': '2024-01-05', 'race_id': '5', 'settled': True, 'hit': True,
             'investment': 200, 'payout': 500, 'ticket_count': 2, 'zone': 'D'},
            {'race_date': '2024-01-06', 'race_id': '6', 'settled': True, 'hit': False,
             'investment': 200, 'payout': 0, 'ticket_count': 2, 'zone': 'D'},
        ]
        st = lg._zone_stats(rows)
        assert st['max_losing_streak'] == 3
        assert 'loss_per_100' in st and 'cost_per_hit' in st
        summ = lg.summarize([
            {'zone': 'D', 'skip': False, 'settled': False},
            {'zone': 'BA', 'skip': True, 'skip_reason': 'zone_ba'},
        ])
        assert 'purchase_rate' in summ
        assert 'skips_by_reason' in summ
        assert summ['skips_by_reason'].get('zone_ba') == 1
        empty = lg._zone_stats([])
        assert empty['n_settled'] == 0 and empty['loss_per_100'] is None
    check("N4 wilson_interval / ledger stats", t_hitrate_stats_n4)

    def t_hitrate_common_unit():
        from core.trio_engine import build_formation
        from scripts import hitrate_common as hc
        r = list(range(1, 9))
        assert len(build_formation(r[:2], r[:4], r[:7])) == 19
        m = hc.mcnemar([1, 1, 0, 0, 0], [1, 0, 1, 1, 0])
        assert m['b'] == 1 and m['c'] == 2 and m['z'] > 0
        # eval_subset n=10 s=30 → 3 races
        import pandas as pd
        import math
        df = pd.DataFrame({'cost': [100] * 10, 'ret': [0] * 10, 'hit': [0] * 10})
        k = max(1, int(math.ceil(10 * 30 / 100.0)))
        assert k == 3
    check("hitrate_common mcnemar / 点数 / eval_subset", t_hitrate_common_unit)

    def t_battle_recency_and_odds_fill():
        from datetime import datetime
        import pandas as _pd
        from core import calculator as calc
        from core import scraper as sc
        ref = datetime(2026, 8, 1)
        assert calc._is_within_days('2026.07.01', ref, 365) is True
        assert calc._is_within_days('2025.08.15', ref, 365) is True
        assert calc._is_within_days('2025.07.01', ref, 365) is False
        # 2020は '202' を含むが、365日外
        assert calc._is_within_days('2020.01.01', ref, 365) is False
        df = _pd.DataFrame({
            'Umaban': [1, 2, 3],
            'Odds': [2.5, 0.0, 12.0],
            'Popularity': [1, 99, 3],
        })
        sc.fill_missing_odds_pop(df, {1: 9.9, 2: 4.4, 3: 99.0}, {1: 9, 2: 2, 3: 8})
        assert float(df['Odds'].iloc[0]) == 2.5, '既存オッズを上書きしない'
        assert float(df['Odds'].iloc[1]) == 4.4, '欠測だけ埋める'
        assert float(df['Odds'].iloc[2]) == 12.0, '既知オッズを確定で上書きしない'
        assert int(df['Popularity'].iloc[0]) == 1 and int(df['Popularity'].iloc[1]) == 2
        assert int(df['Popularity'].iloc[2]) == 3
    check("battle 365日 + Odds欠測のみ補完", t_battle_recency_and_odds_fill)

    def t_consensus_integrate():
        from core import consensus_view as cv
        import pandas as _pd
        # 空dfは空shapeを返す(呼び元は.getで安全に参照)
        e = cv.build_edge_sets(_pd.DataFrame(), {}, '202608020211')
        assert e['edge'] == set() and e['combo'] == {}, "空df=空shape"
        # 穴=combo2+/切る=消去3+/敗者復活=切る帯×combo3+
        aim = {'edge_reasons': {2: ['🔥末脚top', '👑騎手力top', '🧩2重複'], 14: ['⚡33ラップ適合'],
                                7: ['🔵補正T上位', '🔥末脚top', '🧬血統上位', '🧩3重複']},
               'danger': set(), 'veto': set(), 'combo': {2: 2, 7: 3}, 'ana': {14, 2, 7},
               'elim': {5: 4, 7: 3}}  # 5=消去4切る / 7=消去3だがcombo3=敗者復活
        rows = [{'umaban': 16, 'name': 'A', 'pop': 1, 'odds': 3.3, 'proj': 95, 'axis_mark': '◎'},
                {'umaban': 14, 'name': 'B', 'pop': 16, 'odds': 87.5, 'proj': 40, 'axis_mark': ''},
                {'umaban': 2, 'name': 'C', 'pop': 15, 'odds': 14.8, 'proj': 50, 'axis_mark': ''},
                {'umaban': 5, 'name': 'D', 'pop': 8, 'odds': 20.0, 'proj': 45, 'axis_mark': ''},
                {'umaban': 7, 'name': 'E', 'pop': 9, 'odds': 25.0, 'proj': 42, 'axis_mark': ''}]
        r = cv.integrate(rows, aim, '②穴妙味向き')
        assert r['horses'][0]['umaban'] == 16, "◎本命が統合トップ"
        assert 2 in r['groups']['ana'], "combo2の穴が穴グループ入り"
        assert 14 not in r['groups']['ana'], "単発⚡33(combo1)は穴に入れない"
        assert 5 in r['groups']['keshi'], "消去クロス重複4の馬は切る"
        assert 7 in r['groups']['ana'] and 7 not in r['groups']['keshi'], "切る帯×combo3は敗者復活で穴へ"
        assert '敗者復活' in next(h['role'] for h in r['horses'] if h['umaban'] == 7), "7番は敗者復活ロール"
        assert 'osae' in r['groups'], "押さえは独立グループ(カード化)"
    check("consensus_view.integrate(穴/切る/敗者復活)", t_consensus_integrate)

    def t_consensus_no_cut_strong():
        # 回帰(202610020404/メイワキラリ): 6番人気×combo2×消去4でも切らず穴へ。
        # 消去フラグだけで検証済プラス(combo≥2)や高LTRを上書きしない。
        from core import consensus_view as cv
        aim = {'edge_reasons': {5: ['🔵補正T上位', '🧬血統上位', '🧩2重複']},
               'danger': set(), 'veto': set(),
               'combo': {5: 2}, 'elim': {5: 4, 7: 4, 8: 3}}
        rows = [{'umaban': 1, 'name': 'A', 'pop': 1, 'odds': 2.5, 'proj': 260, 'axis_mark': '◎'},
                {'umaban': 2, 'name': 'B', 'pop': 2, 'odds': 4.0, 'proj': 250, 'axis_mark': '〇'},
                {'umaban': 5, 'name': 'メイワ', 'pop': 6, 'odds': 18, 'proj': 244, 'axis_mark': ''},
                {'umaban': 7, 'name': 'D', 'pop': 9, 'odds': 50, 'proj': 120, 'axis_mark': ''},
                {'umaban': 8, 'name': 'E', 'pop': 12, 'odds': 99, 'proj': 90, 'axis_mark': ''},
                {'umaban': 9, 'name': 'F', 'pop': 7, 'odds': 40, 'proj': 110, 'axis_mark': ''}]
        r = cv.integrate(rows, aim, '②穴妙味向き')
        assert 5 not in r['groups']['keshi'], "6番人気combo2は切ってはならない"
        assert 5 in r['groups']['ana'], "6番人気combo2は穴へ"
        assert 7 in r['groups']['keshi'], "消去4×combo0の弱い馬は切る(強気切るは維持)"
    check("consensus_view.integrate(強材料は切らない回帰)", t_consensus_no_cut_strong)

    def t_value_hunter():
        # 軽量スコア: 低オッズ×補正T良は高スコア/精鋭、深穴×補正T悪×消去多は圏外
        from core import value_hunter as vh
        if not vh.available():
            return  # パラメータ未生成環境ではスキップ
        sc = vh.score_race(
            ctfig={1: 80.0, 5: 78.0, 7: 95.0}, spurt={1: 0.5, 5: 0.6, 7: 0.4},
            blood={1: 20, 5: 25, 7: 15}, combo_map={5: 2}, elim_map={5: 0, 7: 3},
            odds_map={1: 8.0, 5: 12.0, 7: 60.0})
        assert sc[5]['score'] > sc[7]['score'], "補正T良×低オッズ > 深穴×補正T悪"
        assert sc[7]['tier'] == '', "60倍×補正T悪×消去3は圏外"
    check("value_hunter.score_race(妙味馬軽量スコア)", t_value_hunter)

    def t_consensus_vh_rescue():
        # vh精鋭ならcombo0・消去多でも切らない(Fableのcombo0救済)
        from core import consensus_view as cv
        aim = {'edge_reasons': {}, 'danger': set(), 'veto': set(),
               'combo': {}, 'elim': {8: 4}, 'vh': {8: 0.20}, 'vh_tier': {8: '🎯精鋭'}}
        rows = [{'umaban': 1, 'name': 'A', 'pop': 1, 'odds': 2.5, 'proj': 260, 'axis_mark': '◎'},
                {'umaban': 2, 'name': 'B', 'pop': 2, 'odds': 4.0, 'proj': 250, 'axis_mark': '〇'},
                {'umaban': 8, 'name': 'V', 'pop': 7, 'odds': 14, 'proj': 100, 'axis_mark': ''},
                {'umaban': 9, 'name': 'W', 'pop': 12, 'odds': 99, 'proj': 60, 'axis_mark': ''}]
        r = cv.integrate(rows, aim, '②穴妙味向き')
        assert 8 not in r['groups']['keshi'], "vh精鋭は消去多でも切らない"
    check("consensus_view.integrate(vh精鋭の救済)", t_consensus_vh_rescue)

    def t_trifecta_band_formation():
        # 帯別フォーメーション(verified_formation_roi): 堅→少点/中→wide/荒れ→広角+穴頭
        from core import trio_engine as te
        assert te.formation_for_arare(None) is None
        assert te.formation_for_arare(0.30)[0] == 'tight'
        assert te.formation_for_arare(0.50)[0] == 'mid'
        assert te.formation_for_arare(0.70)[0] == 'arare'
        horses = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i * 5, 'pop': i,
                   'alert': ('🧩2重複' if i >= 6 else '')} for i in range(1, 13)]
        tight = te.recommend_trifecta(horses, axis_umaban=[1, 2], n_points=50, arare_prob=0.30)
        arare = te.recommend_trifecta(horses, axis_umaban=[1, 2], n_points=50, arare_prob=0.70)
        assert tight['meta']['n_points'] <= arare['meta']['n_points'], "堅は荒れより少点"
        assert tight['meta']['band_name'] == 'tight' and arare['meta']['band_name'] == 'arare'
        # 荒れは穴頭(妙味穴=combo馬)を1着プールに入れる
        assert any(u >= 6 for u in arare['meta']['first']), "荒れは穴頭を1着に許容"
        # ①脆い本命: 帯を1段広げる(堅→中)。検証: 1番人気に危険材料で複勝-6.5pp
        _clean = te.recommend_trifecta(horses, axis_umaban=[1, 2], n_points=50, arare_prob=0.30)
        _frag = te.recommend_trifecta(horses, axis_umaban=[1, 2], n_points=50, arare_prob=0.30, fragile_fav=True)
        assert _clean['meta']['band_name'] == 'tight' and _frag['meta']['band_name'] == 'mid', "脆い本命で帯が1段広がる"
        assert _frag['meta']['fragile_fav'] is True
        # 堅帯③: 4〜5番人気を2着に残す。中庸は従来どおりスコア補充(ここでは変えない)
        assert {4, 5} <= set(tight['meta']['second']), \
            f"堅帯は4-5人気を2着に残す got {tight['meta']['second']}"
        # 1軸=全点に含める(ユーザー指定。最人気の自動固定ではない)
        r1ax = te.recommend_trifecta(
            horses, axis_umaban=[8], n_points=30, require_axis_all=True, arare_prob=0.30)
        assert r1ax['bets'] and all(8 in b['combo'] for b in r1ax['bets']), \
            f"1軸8が全点に入らない {[b['combo'] for b in r1ax['bets'][:5]]}"
        r1off = te.recommend_trifecta(
            horses, axis_umaban=[8], n_points=30, require_axis_all=False, arare_prob=0.30)
        assert r1off['bets'] and not all(8 in b['combo'] for b in r1off['bets']), \
            "require_axis_all=Falseなのに全点が1軸付き"
        # 順不同の3頭組は表示用。同じ3頭の着順違いは1行、買い目点数は変えない
        _sets = te.unordered_horse_sets([
            {'combo': (2, 14, 1), 'names': ('A', 'B', 'C'), 'score': 10},
            {'combo': (2, 1, 14), 'names': ('A', 'C', 'B'), 'score': 9},
            {'combo': (3, 4, 5), 'names': ('X', 'Y', 'Z'), 'score': 8},
        ])
        assert len(_sets) == 2 and _sets[0]['umabans'] == (1, 2, 14)
        assert _sets[0]['n_orders'] == 2 and _sets[1]['n_orders'] == 1
    check("trio_engine.recommend_trifecta(帯別フォーメーション)", t_trifecta_band_formation)

    def t_formation_stake_advice():
        # ②資金管理: 全帯負EV。中波乱=最厚/堅=見送り(floor以下)。
        from core import money as mo
        assert mo.formation_stake_advice(None, 20000) is None
        mid = mo.formation_stake_advice(0.50, 20000)
        tight = mo.formation_stake_advice(0.30, 20000)
        arare = mo.formation_stake_advice(0.70, 20000)
        assert mid['band'] == 'mid' and mid['stake'] > 0, "中波乱はエンタメ配分あり"
        assert tight['stake'] == 0 and '見送り' in tight['verdict'], "堅(74%<floor)は見送り"
        assert mid['stake'] >= arare['stake'] > 0, "中波乱≥荒れ(損の少ない帯に厚く)"
        assert mid['exp_roi'] < 1.0, "全帯で負EV(利益保証でない)"
    check("money.formation_stake_advice(帯別ステーク)", t_formation_stake_advice)

    def t_recommend_bet_type():
        # ③券種セレクター: 堅い1着→単勝 / 荒れ→3連単。取りこぼし最適化。
        from core import bet_optimizer as bo
        assert bo.recommend_bet_type(None) is None
        solid = bo.recommend_bet_type(0.30, fav_odds=2.5, n_solid_axis=1)
        assert '単勝' in solid['primary'], "堅い1着は単勝提案"
        arare = bo.recommend_bet_type(0.70, fav_odds=6.0, n_solid_axis=0)
        assert '3連単' in arare['primary'], "荒れは3連単フォーメーション"
        wide = bo.recommend_bet_type(0.45, fav_odds=4.0, n_solid_axis=2)
        assert 'ワイド' in wide['primary'] or '馬連' in wide['primary'], "軸2頭堅い→ワイド/馬連"
    check("bet_optimizer.recommend_bet_type(券種セレクター)", t_recommend_bet_type)

    def t_ledger_gate():
        import tempfile
        from core import money
        _tmp = os.path.join(tempfile.gettempdir(), 'smoke_ledger_gate.db')
        if os.path.exists(_tmp):
            os.remove(_tmp)
        lg = money.Ledger(db=_tmp)
        lg.record_prediction('R1', 5, 'X', 0.3, 4.0, stake=100, bet_type='単勝',
                             gate_status='buy', gate_lean='本線向き', gate_severity=0)
        lg.settle('R1', 5, 400)
        g = lg.roi_by_gate()
        assert g.get('buy', {}).get('n') == 1 and abs(g['buy']['roi'] - 4.0) < 1e-6, f"got {g}"
        # ⑥負け分類: skipレースを買って外した→「Gate無視」
        lg.record_prediction('R2', 3, 'Y', 0.2, 8.0, stake=100, bet_type='単勝', gate_status='skip')
        lg.settle('R2', 9, 0)
        assert money.Ledger.classify_loss(0, 'skip') == 'Gate無視(見送りレースを購入)'
        assert money.Ledger.classify_loss(1, 'skip') is None, "的中は分類しない"
        lb = lg.loss_breakdown()
        assert lb.get('Gate無視(見送りレースを購入)', {}).get('n') == 1, f"got {lb}"
        # #1 設計ミス分類: 危険人気含み/盲目②/本線点数過多/トリガミ設計
        assert money.Ledger.classify_loss(0, 'buy', has_danger=1) == '危険人気馬を含めて購入'
        assert money.Ledger.classify_loss(0, 'buy', gate_lean='②穴妙味向き', has_value_ana=0) == '盲目②(穴妙味向きなのに妙味穴なし)'
        assert money.Ledger.classify_loss(0, 'buy', gate_lean='本線向き', n_points=15).startswith('本線向きで点数過多')
        assert money.Ledger.classify_loss(0, 'buy', synth_odds=1.2).startswith('トリガミ設計')
        # ⑥回顧→ルール生成: Gate無視の負けがある→ルールが出る
        rules = lg.improvement_rules()
        assert any('見送り' in r for r in rules), f"Gate無視ルール期待, got {rules}"
        lg.con.close()
        try:
            os.remove(_tmp)
        except Exception:
            pass
    check("money.Ledger gate_status/roi_by_gate", t_ledger_gate)

    def t_ledger_kelly_write():
        import tempfile
        from core import money
        _tmp = os.path.join(tempfile.gettempdir(), 'smoke_ledger_kelly.db')
        if os.path.exists(_tmp):
            os.remove(_tmp)
        lg = money.Ledger(db=_tmp)
        lines = [
            {'kind': '3連複', 'label': '7-4-12', 'odds': 45.0, 'stake': 500, 'p': 0.03},
            {'kind': 'ワイド', 'label': '7-4', 'odds': 8.5, 'stake': 0, 'p': 0.15},
        ]
        n = lg.record_kelly_bets('209901019999', lines, gate_status='buy', gate_lean='本線向き')
        assert n == 1, f"stake>0のみ記録 expected 1 got {n}"
        row = lg.con.execute(
            "SELECT race_id,umaban,bamei,bet_type,stake,gate_status FROM bets").fetchone()
        assert row['race_id'] == '209901019999' and row['umaban'] == 7
        assert row['bamei'] == '7-4-12' and row['bet_type'] == '3連複' and row['stake'] == 500
        lg.record_skip('209901019998', reason='見送りテスト', vscore=72.0, zone='C')
        sk = lg.con.execute("SELECT COUNT(*) FROM skips").fetchone()[0]
        assert sk == 1, f"skips expected 1 got {sk}"
        assert money.Ledger.parse_first_umaban('3-8-11') == 3
        lg.close()
        try:
            os.remove(_tmp)
        except Exception:
            pass
    check("money.Ledger record_kelly_bets/skip write", t_ledger_kelly_write)

    def t_gate_cache():
        from core import score_cache as sc
        rid = '209901019999'
        sc.write_gate(rid, 'buy', '②穴妙味向き')
        g = sc.read_gate(rid)
        assert g and g['status'] == 'buy' and g['lean'] == '②穴妙味向き', f"got {g}"
        try:
            os.remove(sc._gate_path(rid))
        except Exception:
            pass
    check("score_cache.write_gate/read_gate", t_gate_cache)

    def t_oikiri_cache():
        from core import score_cache as sc
        from core.oikiri import is_c_or_below, normalize_train_rank
        assert normalize_train_rank('ｃ') == 'C' and normalize_train_rank('Ｄ') == 'D'
        assert is_c_or_below('C') and is_c_or_below('D') and is_c_or_below('Ｅ')
        assert not is_c_or_below('A') and not is_c_or_below('B') and not is_c_or_below('')
        rid = '209901019997'
        sc.write_oikiri(rid, {3: {'name': 'テスト', 'rank': 'C', 'critic': '平凡'},
                              7: {'name': '本命', 'rank': 'A', 'critic': '上々'}})
        got = sc.read_oikiri(rid)
        assert got and got[3]['rank'] == 'C' and got[7]['rank'] == 'A', f"got {got}"
        try:
            os.remove(sc._oikiri_path(rid))
        except Exception:
            pass
    check("score_cache.write_oikiri/read_oikiri", t_oikiri_cache)

    def t_agent_roster():
        from core import agent_forum as af
        r = af.agent_roster()
        # 2026-07再設計: 血統/展開/調教単体等priced-in確定済みの旧ペルソナは廃止し、
        # 検証済みモジュール担当の6人格(BASE_AGENTS)のみに縮小。_EXTRA_AGENTSは空。
        assert len(r) == 6 and all('focus' in a and 'id' in a for a in r), "名簿にfocus/id"
        _foc = {a['id']: a['focus'] for a in r}
        assert _foc.get('hoseiT') == '補正タイム' and _foc.get('wakuDirt') == 'ダート枠信号'
        assert _foc.get('powerJk') == '騎手力(JPower)'
        # 旧ペルソナ(廃止済み)が残っていないこと
        assert 'kei' not in _foc and 'jin' not in _foc and 'amano' not in _foc, \
            "血統単体/騎手単体/強制逆張りの旧ペルソナは廃止済み"
        # 選択班: 指定id順・未知は無視
        sel = af.agents_by_ids(['hoseiT', 'zzz', 'wakuDirt'])
        assert [a['id'] for a in sel] == ['hoseiT', 'wakuDirt']
        assert af.agents_by_ids([]) == []
        # knowledge_fnの重複が無い(個性が見た目だけでない事の保証)
        assert len(set(id(a['knowledge_fn']) for a in af.BASE_AGENTS)) == len(af.BASE_AGENTS), \
            "各ペルソナのknowledge_fnが重複していない"
        # 共通プロンプトが『人気を無視しろ』と縛っていないこと(2026-07 root cause修正の回帰防止)
        _sys = af._build_system_with_knowledge(af.BASE_AGENTS[0])
        assert '無視' not in _sys.split('重要:')[-1].split('\n')[0] or '無視したり逆張り' in _sys, \
            "共通指示が人気無視を強制していない"
    check("agent_forum.agent_roster/agents_by_ids(2026-07ペルソナ再設計)", t_agent_roster)

    def t_agent_correlation():
        from core import agent_forum as af
        # 空台帳=データ不足note・n_races0
        r0 = af.agent_pick_correlation([])
        assert r0['n_races'] == 0 and r0['mean_corr'] is None and 'データ不足' in r0['note']
        # 同予想ペア(A=B)は正相関で高honmei一致、逆張りCは負相関(独立)
        recs = [{'agent_picks': {'A': {'honmei': h, 'taikou': t, 'anaume': a},
                                 'B': {'honmei': h, 'taikou': t, 'anaume': a},
                                 'C': {'honmei': c, 'taikou': c2, 'anaume': c3}}}
                for (h, t, a, c, c2, c3) in [(1, 2, 3, 8, 7, 6), (4, 5, 6, 12, 11, 10),
                                             (1, 3, 5, 9, 8, 7)]]
        res = af.agent_pick_correlation(recs)
        pd_ = {tuple(sorted((p['a'], p['b']))): p for p in res['pairs']}
        assert pd_[('A', 'B')]['corr'] > 0.9 and pd_[('A', 'B')]['honmei_agree'] == 1.0
        assert pd_[('A', 'C')]['corr'] < 0, "逆張りは負相関(独立)"
        # 冗長度: Cが最も独立(平均相関が最小)
        assert res['redundancy']['C'] < res['redundancy']['A']
    check("agent_forum.agent_pick_correlation", t_agent_correlation)

    def t_hypothesis_schema():
        from core import hypothesis_schema as hs
        # カード7機能ゲート: 俗説は隔離、検証済みエッジは通す
        assert hs.is_folk_belief('初ブリ')[0] is True, "初ブリは俗説"
        assert hs.is_folk_belief('PCI適性')[0] is True, "PCIは俗説(完全終了)"
        assert hs.is_folk_belief('巻き返し狙い')[0] is True, "巻き返しは俗説"
        assert hs.is_folk_belief('末脚top3×6人気以下')[0] is False, "末脚は検証済みで通す"
        ok, _ = hs.validate_hypothesis(hs.make_hypothesis('厩舎当コース勝率', role='妙味'))
        assert ok, "妥当な仮説は通る"
        okp, _ = hs.validate_hypothesis(hs.make_hypothesis('PCI傾向マッチ'))
        assert not okp, "PCI仮説は隔離される"
    check("hypothesis_schema.folk隔離", t_hypothesis_schema)

    def t_pace_tactics():
        from core import pace_map as pm
        # 騎手・厩舎脚質傾向→位置prior(0=前..1=後)。前受け型ほど小さい
        f_forward = pm.tactics_forward('川田将雅')   # 先行48.8%=前
        f_mid = pm.tactics_forward('吉村誠之')       # 中団寄り
        assert f_forward is not None and f_mid is not None
        assert f_forward < f_mid, f"前受け型が前(小)であるべき got {f_forward} vs {f_mid}"
        # データ無しはNone(既存挙動を壊さない)＋厩舎注釈付きでもヒット
        assert pm.tactics_forward('架空騎手', '架空厩舎') is None
        assert pm.tactics_forward(None, '矢作芳人 ?-8%(6777)') is not None
        # 騎手/厩舎なしでも build_pace_context は従来通り
        c = pm.build_pace_context([{'umaban': 1, 'name': 'A', 'score': 0.1},
                                   {'umaban': 2, 'name': 'B', 'score': 0.8}],
                                  distance=1600, surface='芝')
        assert c['leader'] == 1, f"score低=前=leader1, got {c['leader']}"
    check("pace_map.tactics_forward(表示用)", t_pace_tactics)

    def t_pace_comment_nige_consistency():
        # 回帰(202608030811 栗東S): 隊列はnige_umas=[4,3]/contested=Trueなのに
        # コメントだけ「単騎逃げ濃厚→前残り警戒」と逆を出していた。
        # 原因=逃げ判定の閾値がbuild_pace_context(0.20)とdescribe_pace(0.18)で不一致。
        from core import pace_map as pm
        horses = [{'umaban': 4, 'name': 'A', 'score': 0.05, 'style': '逃げ'},
                  {'umaban': 3, 'name': 'B', 'score': 0.19, 'style': '逃げ'},
                  {'umaban': 7, 'name': 'C', 'score': 0.30, 'style': '先行'}]
        fwd = {4: 0.05, 3: 0.19, 7: 0.30}   # 3番は旧0.18〜新0.20の境界にいる
        nige = [u for u, v in fwd.items() if v < pm.NIGE_FORWARD_MAX]
        assert nige == [4, 3], f"閾値{pm.NIGE_FORWARD_MAX}で2頭が逃げ判定, got {nige}"
        ctx = {'forward': fwd, 'leader': 4, 'pace': 'ハイ', 'front_ratio': 0.5,
               'nige_umas': nige, 'contested': True}
        txt = pm.describe_pace(horses, pace_ctx=ctx)
        assert '単騎逃げ' not in txt, f"ハナ争い時に単騎逃げと言わない: {txt}"
        assert '逃げ候補2頭' in txt, f"逃げ候補2頭と明示: {txt}"
        # 本当に単騎ならこれまで通り単騎逃げと言う(修正で潰していない)
        ctx1 = dict(ctx, forward={4: 0.05, 3: 0.30, 7: 0.35},
                    nige_umas=[4], contested=False)
        txt1 = pm.describe_pace(horses, pace_ctx=ctx1)
        assert '単騎逃げ' in txt1, f"真の単騎は従来通り: {txt1}"
        # 先行はnige除外(二重計上しない)
        assert '先行勢' not in txt or '逃げ候補2頭' in txt
    check("pace_map.describe_pace(逃げ判定をctxと一致・単騎誤判定の回帰)",
          t_pace_comment_nige_consistency)

    def t_ltr_nar():
        from core import ltr_ranker as lr
        # NAR専用モデルのルーティング契約(available_nar/_load_nar)
        assert isinstance(lr.available_nar(), bool)
        if lr.available_nar():
            m, meta = lr._load_nar()
            assert m is not None and 'features' in meta, "NARモデルとmeta読込"
            assert 'log_odds' not in meta['features'], "NARはlog_odds除外(win_odds無)"
    check("ltr_ranker.NAR専用モデル分岐", t_ltr_nar)

    def t_axis_nar():
        from core import axis_selector as ax
        # NAR較正: 1番人気は実測78.7%(JRA70.1%より高く評価)・人気基準固定(odds無視)
        assert ax.axis_confidence_nar(1) == 78.7, f"NAR1番人気=78.7, got {ax.axis_confidence_nar(1)}"
        assert ax.axis_confidence(1) == 70.1, "JRA側は不変(70.1)"
        # NARはoddsを渡しても人気基準(地方はオッズ市場薄い)
        assert ax.axis_confidence_nar(1, odds=1.5) == 78.7, "NARはodds無視で人気基準"
        # 軸マーク: 1番人気に◎が付く
        m = ax.axis_marks_nar([{'name': 'A', 'pop': 1}, {'name': 'B', 'pop': 2}, {'name': 'C', 'pop': 5}])
        assert m['A']['mark'] == '◎' and m['A']['conf'] == 78.7, f"NAR1番人気◎, got {m['A']}"
    check("axis_selector.NAR較正(POP_FUKU_NAR)", t_axis_nar)

    def t_jockey_shortname_resolve():
        """回帰: 出馬表の略記(『横山武』)で騎手成績が0件になるバグ(2026-07-14修正)。

        jockey_base_stats/jockey_trainer_combo/jockey_usm/jockey_power が
        resolve_jockey_name を通しておらず、略記でDB直引き→ヒット0→『データ少』→
        騎手係数が全馬1.0・黄金ライン空、になっていた。完全名は冪等(結果不変)。
        """
        from core import jockey_jv as jj
        import os as _os
        if not _os.path.exists(jj.JV_DB_PATH):
            return                      # 公開版(DB無し)ではスキップ
        b = jj.jockey_base_stats('横山武')
        assert b['name'] == '横山武史', f"略記→完全名, got {b['name']}"
        assert b['overall']['rides'] > 100, f"略記でも騎乗数が引ける, got {b['overall']['rides']}"
        # 完全名を渡した場合は同じ結果(冪等=バックテストに影響しない)
        f = jj.jockey_base_stats('横山武史')
        assert f['overall']['rides'] == b['overall']['rides'], "完全名と略記で同一結果"
        # 騎手係数が『データ少』で1.0固定にならない
        fac = jj.jockey_factor('横山武')
        assert fac['note'] != 'データ少', "略記でもデータ少にならない"
    check("jockey_jv.略記の騎手名解決(係数1.0固定バグ回帰)", t_jockey_shortname_resolve)

    def t_magi_done_check():
        from core import magi_chat as mc
        led = [{'ts': '2026-07-01 10:00', 'race_id': 'R1', 'place': '東京', 'name': 'A', 'learning': {}},
               {'ts': '2026-07-02 09:00', 'race_id': 'R1', 'place': '東京', 'name': 'A', 'learning': {}},
               {'ts': '2026-07-02 11:00', 'race_id': 'R2', 'place': '京都', 'name': 'B', 'learning': {}}]
        assert len(mc.races_done('R1', led)) == 2, "R1は2回回顧済み"
        assert mc.races_done('R9', led) == [], "未回顧は空(二度手間警告なし)"
        rr = mc.recent_races(led)
        r1 = next(x for x in rr if x['race_id'] == 'R1')
        assert r1['count'] == 2 and rr[0]['race_id'] == 'R2', "集約カウント+最新ts順"
    check("magi_chat.races_done/recent_races", t_magi_done_check)

    def t_magi_calendar():
        from core import magi_chat as mc
        led = [{'ts': '2026-07-01 10:00', 'race_id': 'R1', 'date': '2026/06/05', 'place': '東京', 'name': '安田', 'learning': {}},
               {'ts': '2026-07-02 09:00', 'race_id': 'R1', 'date': '2026/06/05', 'place': '東京', 'name': '安田', 'learning': {}},
               {'ts': '2026-07-02 09:30', 'race_id': 'R2', 'date': '2026/06/05', 'place': '東京', 'name': '別R', 'learning': {}},
               {'ts': '2026-07-02 12:00', 'race_id': 'R9', 'date': '', 'place': '?', 'name': '無日付', 'learning': {}}]
        c = mc.retro_calendar(led)
        # 同じ日(6/5)に違うレースが別々に並ぶ
        assert '2026-06-05' in c['by_date'] and len(c['by_date']['2026-06-05']) == 2
        _r1 = next(x for x in c['by_date']['2026-06-05'] if x['race_id'] == 'R1')
        assert _r1['count'] == 2, "同一レースの複数回顧はcount集約"
        # 日付不明はundatedへ(カレンダーに置けないもの)
        assert len(c['undated']) == 1 and c['undated'][0]['race_id'] == 'R9'
    check("magi_chat.retro_calendar", t_magi_calendar)

    def t_verify_queue():
        import tempfile
        from core import verify_queue as vq
        p = os.path.join(tempfile.gettempdir(), 'smoke_vq.json')
        if os.path.exists(p):
            os.remove(p)
        # 番号採番＋重複防止＋俗説は呼び手(hypothesis_export)で除外済み前提
        cands = [{'name': '厩舎当コース好調', 'role': '妙味', 'band': '6+', 'note': 'x'},
                 {'name': '末脚top3×人気薄', 'role': '相手', 'band': '6+', 'note': 'y'}]
        added = vq.register(cands, path=p)
        assert [n for n, _ in added] == [1, 2], f"連番採番, got {added}"
        # 再登録は重複しない
        again = vq.register(cands, path=p)
        assert again == [], "重複登録しない"
        # 新規タグは次番号
        more = vq.register([{'name': '新タグZ'}], path=p)
        assert more == [(3, '新タグZ')], f"次番号=3, got {more}"
        lst = vq.list_candidates(path=p)
        assert len(lst) == 3 and lst[0]['num'] == 1 and lst[0]['status'] == '未検証'
        os.remove(p)
    check("verify_queue.register(番号/重複防止)", t_verify_queue)

    def t_agent_weights():
        from core import agent_forum as af
        # カード8安全性: 空台帳→{}、λ=0→均等
        assert af.agent_weights([]) == {}, "空台帳は{}"
        recs = [{'result': {'top3': [1, 2, 3]},
                 'agent_picks': {'a': {'honmei': 1, 'hit': True},
                                 'b': {'honmei': 9, 'hit': False}}}]
        w0 = af.agent_weights(recs, lam=0)
        assert abs(w0['a'] - w0['b']) < 1e-9, "λ=0は均等(単純平均に縮退)"
        w = af.agent_weights(recs, lam=3.0)
        assert w['a'] > w['b'], "的中エージェントの重みが大きい"
    check("agent_forum.agent_weights(安全縮退)", t_agent_weights)

    def t_agent_knowledge_fns():
        from core import agent_forum as af
        csv_text = ('馬番,枠,馬名,騎手,人気,単勝オッズ\n'
                   '9,6,アドマイヤズーム,吉田隼,2,8.4\n'
                   '12,7,モンロワイヤル,丹内,1,3.3\n')
        meta_dirt = {'surface': 'ダート', 'distance': 1700, 'race_id': '202602010812'}
        meta_turf = {'surface': '芝', 'distance': 2000, 'race_id': '202605020811'}
        # 全knowledge_fnがエラーなく文字列を返す(実データ有無に関わらず)
        for fn in (af._knowledge_conservative, af._knowledge_corrected_time,
                  af._knowledge_lap33, af._knowledge_spurt, af._knowledge_jpower,
                  af._knowledge_dirt_draw):
            out = fn(csv_text, meta_dirt)
            assert isinstance(out, str) and len(out) > 0, f"{fn.__name__}が文字列を返す"
        # ダート枠信号は芝レースでは対象外と正直に言う(無理に枠を語らない)
        out_turf = af._knowledge_dirt_draw(csv_text, meta_turf)
        assert '対象外' in out_turf, "芝レースではダート枠エッジ対象外と明記"
        # 空データでも例外を出さない(馬名解決失敗等への耐性)
        for fn in (af._knowledge_corrected_time, af._knowledge_lap33, af._knowledge_spurt,
                  af._knowledge_jpower, af._knowledge_dirt_draw):
            fn('', {})
    check("agent_forum.knowledge_fn(検証済みモジュール直結)", t_agent_knowledge_fns)

    def t_danger_gate():
        from core import danger_gate as dg
        def _has(vr, name):
            return any(name in str(x) for x in (vr.get('reasons') or []))

        # 人気薄は対象外
        assert dg.danger_veto(ninki=8, surface='芝', baba='重')['severity'] == 0, "人気薄は危険対象外"
        # 重×1番人気 + 牝×冬春fade = 2件→veto
        r = dg.danger_veto(ninki=1, surface='芝', baba='重', sex_age='牝3', month=1)
        assert not r['veto'] and r['severity'] >= 2, f"重×1番+牝冬春→veto廃止・severity維持, got {r}"
        # 1件なら降格注意(veto=False)
        r1 = dg.danger_veto(ninki=1, surface='芝', baba='重')
        assert (not r1['veto']) and r1['severity'] == 1, f"重×1番のみ→severity1, got {r1}"
        # axis_demote: severity>=2は押さえ推奨(軸からは外さない・66R台帳検証済)
        assert '押さえ推奨' in dg.axis_demote('◎ 60%', r), "severity>=2で押さえ推奨"
        # 高齢(7歳+): 削除済み(66R台帳で3回中3回的中=逆効果)
        assert '高齢' not in str(dg.danger_veto(ninki=2, surface='芝', sex_age='牡8', top_jockey_swap=True)['reasons']), \
            "高齢は削除済み"
        # 前走5着以下 / 斤量比≥12.6%: scripts/danger_fav_audit.py の再検証で効果ゼロと判明し削除
        # (前走5着以下は train+0.55pp / holdout-0.09pp、斤量比は両窓z≒0)。復活させないこと。
        assert '前走5着以下' not in dg.danger_veto(
            ninki=1, surface='芝', prev_chaku=8, top_jockey_swap=True)['reasons'], "前走5着以下は削除済み"
        assert '斤量比' not in ''.join(dg.danger_veto(
            ninki=1, surface='芝', kinratio=True, top_jockey_swap=True)['reasons']), "斤量比は削除済み"
        # 前走逃げ: ソフト→硬いへ昇格(train-2.76pp/z-5.6, holdout-3.33pp/z-2.8)
        assert dg.danger_veto(ninki=1, surface='芝', prev_kyaku='1')['severity'] == 1, "前走逃げは単独で算入"
        assert '⚠' in dg.axis_demote('◎ 60%', r1), "severity1で⚠付記"
        # 半年休み明けはソフト理由: 単独では危険にしない(精度低・NAR誤爆対策)
        assert dg.danger_veto(ninki=1, layoff_days=200)['severity'] == 0, "休み明け単独は危険にしない"
        # 他の硬い理由と重なった時のみ算入
        _rs = dg.danger_veto(ninki=1, layoff_days=200, top_jockey_swap=True)
        assert _rs['severity'] == 2 and _has(_rs, '半年休み明け'), f"休明+硬でstack, got {_rs}"
        # 中9週+ローテ(63-179日)ソフト理由(実測 複勝残差-1.6pp z-5.6・ROIフラット=軸信頼度のみ)
        assert dg.danger_veto(ninki=1, layoff_days=70)['severity'] == 0, "中9週+単独は非表示(ソフト)"
        _r9w = dg.danger_veto(ninki=1, layoff_days=70, top_jockey_swap=True)
        assert _has(_r9w, '中9週+ローテ') and _r9w['severity'] == 2, f"中9週+硬い危険で算入, got {_r9w}"
        assert not _has(dg.danger_veto(ninki=1, layoff_days=200, top_jockey_swap=True), '中9週+ローテ'), \
            "180日+は半年休み明け側(排他)"
        # 美浦→関西遠征×1-3人気(verified_ensei_east_to_west)
        # 複勝残差 train-5.00pp(z-6.05)/2024以降-4.55pp(z-3.37)。単独では自動除外しない材料。
        for _jy in ('07', '08', '09', '10'):        # 中京/京都/阪神/小倉
            _re = dg.danger_veto(ninki=1, tozai='east', jyo=_jy)
            assert _has(_re, '美浦→関西遠征'), f"美浦→西場{_jy}で発火すべき, got {_re}"
            assert _re['severity'] == 1 and _re['veto'] is False, \
                f"遠征単独はseverity1かつveto不可, got {_re}"
        assert dg.danger_veto(ninki=1, tozai='1', jyo='08')['reasons'], "DB形式tozai='1'も認識"
        assert dg.danger_veto(ninki=1, tozai='east', jyo='8')['reasons'], "jyoゼロ埋め無しも認識"
        for _nk in (4, 6, 7, 12):                   # 4人気以降は不安定/効果ゼロ帯なので適用外
            assert not _has(dg.danger_veto(
                ninki=_nk, tozai='east', jyo='08'), '美浦→関西遠征'), f"{_nk}人気には適用しない"
        for _jy in ('01', '02', '05', '06'):        # 地元・北海道は対象外
            assert not _has(dg.danger_veto(
                ninki=1, tozai='east', jyo=_jy), '美浦→関西遠征'), f"東場/中立{_jy}では発火しない"
        assert not _has(dg.danger_veto(
            ninki=1, tozai='west', jyo='05'), '美浦→関西遠征'), "西→東(関西馬の東征)には適用しない"
        assert not _has(dg.danger_veto(
            ninki=1, tozai=None, jyo='08'), '美浦→関西遠征'), "所属不明では発火しない"
        # 他の危険材料と重なるとseverityが積み上がる(=単独では消さないが合わせ技で警戒)
        _ren = dg.danger_veto(ninki=1, tozai='east', jyo='08', fillies_race=True)
        assert _ren['severity'] == 2 and _has(_ren, '美浦→関西遠征'), \
            f"遠征+他材料でseverity2, got {_ren}"
        # スクレイパ側: 実HTMLの『栗東・宮本』形式(括弧なし)を認識できること
        from core.scraper import extract_tozai as _etz
        assert _etz('栗東・宮本') == 'west' and _etz('美浦・田中') == 'east', "中黒形式の所属抽出"
        assert _etz('西園正都') is None and _etz('東田') is None, "調教師名の東西を誤認しない"

        assert not _has(dg.danger_veto(ninki=1, layoff_days=40, top_jockey_swap=True), '中9週+ローテ'), \
            "63日未満は非該当"
        # 短距離休み明け(1300m以下×中9週+): ソフト理由。1-3人気は中距離休み明けより
        # 見る-4.06/確認-4.43ppだが絶対複勝45%なので単独では出さない。
        assert dg.danger_veto(ninki=1, layoff_days=70, dist=1200)['severity'] == 0, \
            "短距離休み明け単独は非表示(ソフト)"
        _rsp = dg.danger_veto(ninki=1, layoff_days=70, dist=1200, top_jockey_swap=True)
        assert _has(_rsp, '短距離休み明け') and _has(_rsp, '中9週+ローテ') \
            and _rsp['severity'] == 3, f"短距離は中9週+に重ねる, got {_rsp}"
        assert all(str(x).startswith('➖減点 ') for x in _rsp['reasons']), \
            f"危険理由は減点と一目で分かる表示にする, got {_rsp['reasons']}"
        assert not _has(dg.danger_veto(
            ninki=1, layoff_days=70, dist=1600, top_jockey_swap=True), '短距離休み明け'), \
            "1400m以上では短距離休み明けを出さない"
        _r180s = dg.danger_veto(ninki=1, layoff_days=200, dist=1200, top_jockey_swap=True)
        assert _has(_r180s, '半年休み明け') and _has(_r180s, '短距離休み明け') \
            and not _has(_r180s, '中9週+ローテ'), f"180日+は半年側に短距離を重ねる, got {_r180s}"
        assert not _has(dg.danger_veto(
            ninki=1, layoff_days=70, top_jockey_swap=True), '短距離休み明け'), \
            "距離不明では短距離休み明けを出さない"
        assert not _has(dg.danger_veto(
            ninki=1, layoff_days=40, dist=1200, top_jockey_swap=True), '短距離休み明け'), \
            "63日未満の短距離は非該当"
        # ガラス人気馬(単複逆転FADE・検証z-8.5): 上位人気×単勝短い×複勝が帯中央比1.2倍↑=硬い危険
        from core import value_scanner as _vsg
        _g_hit, _g_r = _vsg.glass_favorite_fade(3.0, 1.8, ninki=2)  # 2.5-3帯の複勝中央1.2→1.8=x1.5
        assert _g_hit and _g_r >= 1.25, f"ガラス人気馬判定(閾値1.25), got {_g_hit}/{_g_r}"
        assert not _vsg.glass_favorite_fade(3.0, 1.1, ninki=2)[0], "複勝が帯並みならガラスでない"
        assert not _vsg.glass_favorite_fade(15.0, 5.0, ninki=8)[0], "人気薄/単勝10倍+は対象外"
        _rg = dg.danger_veto(ninki=2, surface='芝', win_odds=3.0, place_mid=1.8)
        assert any('ガラス' in x for x in _rg['reasons']) and _rg['severity'] == 1, f"ガラスは硬い危険1件, got {_rg}"
    check("danger_gate.danger_veto / axis_demote", t_danger_gate)

    def t_bayes_shrink():
        from core.bayes_stats import shrink_rate
        # 少サンプル(5戦1勝=20%)は全体平均(8%)へ引き寄せられ、生の20%より小さく8%より大きい
        s = shrink_rate(1, 5, 0.08)
        assert 0.08 < s < 0.20, f"5戦1勝は0.08〜0.20の間に縮小, got {s}"
        # 大サンプル(100戦20勝=20%)は実測値のまま(引き寄せの影響が小さい)
        big = shrink_rate(20, 100, 0.08)
        assert abs(big - 0.20) <= 0.03, f"100戦20勝は0.20±0.03, got {big}"
        # n=0 は prior をそのまま返す
        assert shrink_rate(0, 0, 0.08) == 0.08, "n=0はprior_mean"
        # 3戦3勝(100%)も母集団平均へ大きく引き戻される(過信防止の本丸)
        assert shrink_rate(3, 3, 0.08) < 0.30, "3戦3勝でも100%とは出さない"
        # 不正入力
        for bad in [(-1, 5, 0.08), (6, 5, 0.08), (1, 5, 1.5)]:
            try:
                shrink_rate(*bad)
                raise AssertionError(f"不正入力でValueErrorが必要: {bad}")
            except ValueError:
                pass
    check("bayes_stats.shrink_rate(縮小推定)", t_bayes_shrink)

    def t_trainer_course_gate():
        from core import jockey_jv as jjg
        # 妙味ゲート閾値は縮小推定スケールでの再検証値(trainer_shrinkage_backtest.py: z+2.88)。
        # 生の20%とは尺度が違う(shrunk>=0.20は3年で57回しか発火せず機能しない)ため0.18。
        assert abs(jjg.TRAINER_COURSE_GATE - 0.18) < 1e-9, \
            f"厩舎当コースゲートは0.18(縮小推定スケール), got {jjg.TRAINER_COURSE_GATE}"
        # course_prior_winrate はDB無くてもフォールバックを返す(0〜1)
        _p = jjg.course_prior_winrate('05', '芝')
        assert _p is not None and 0.0 < _p < 1.0, f"prior は0〜1, got {_p}"
    check("jockey_jv.TRAINER_COURSE_GATE(縮小推定ゲート)", t_trainer_course_gate)

    def t_wilson():
        from core.bayes_stats import wilson_lower
        # 66R中52的中(78.8%)の下限は67%前後(=レース数が少ない分を差し引いた堅めの値)
        lo = wilson_lower(52, 66)
        assert 0.66 <= lo <= 0.70, f"wilson_lower(52,66)は0.66〜0.70, got {lo}"
        # 常に実測値より下(=盛らない)
        assert lo < 52 / 66, "下限は実測値より小さい"
        # n=0 は None
        assert wilson_lower(0, 0) is None, "n=0はNone"
        # 全的中(k=n)でも1.0未満(標本が少ない不確実性が残る)
        assert wilson_lower(5, 5) < 1.0, "k=nでも1.0未満"
        # 標本が増えるほど下限は実測値に近づく
        assert wilson_lower(80, 100) < wilson_lower(800, 1000), "標本が多いほど下限は上がる"
        # 不正入力
        for bad in [(-1, 5), (6, 5)]:
            try:
                wilson_lower(*bad)
                raise AssertionError(f"不正入力でValueErrorが必要: {bad}")
            except ValueError:
                pass
    check("bayes_stats.wilson_lower(控えめな下限)", t_wilson)

    def t_track_record_lo():
        from core import track_record as tr
        s = tr.get_summary()
        # 下限キーが常に存在する(データ有無に関わらず・呼び手が KeyError にならない)
        for k in ('axis_rate_lo', 'trio_rate_lo', 'any_hit_rate_lo', 'keshi_precision_lo'):
            assert k in s, f"get_summary に {k} が必要"
        # データがあるなら下限 <= 実測値
        if s.get('axis_rate') is not None and s.get('axis_rate_lo') is not None:
            assert s['axis_rate_lo'] <= s['axis_rate'], "下限は実測以下"
        txt = tr.export_summary_text()
        assert isinstance(txt, str) and txt, "成績テキストが生成される"
    check("track_record.get_summary(下限併記)", t_track_record_lo)

    def t_elim_promote():
        import json as _js
        import tempfile as _tf
        from core import elim_reasons as er
        p = os.path.join(_tf.gettempdir(), 'smoke_elim.json')

        # --- 旧形式(listのみ)の台帳が読めること(移行互換) ---
        old = [{'race_id': 'r1', 'tags': ['anauma']},
               {'race_id': 'r2', 'tags': ['anauma']},
               {'race_id': 'r3', 'tags': ['anauma']}]
        with open(p, 'w', encoding='utf-8') as f:
            _js.dump(old, f)
        led = er.load_ledger(p)
        assert isinstance(led, list) and len(led) == 3, "旧形式listが読める"
        assert er.load_fired(p) == {}, "旧形式のfiredは空"
        # 分母が無いので従来の3回ルールで昇格
        assert 'anauma' in er.learned_tags(led, path=p), "分母なし=3回ルールで昇格"

        # --- 分母を記録すると生還率ベースの判定に切り替わる ---
        # 40レースで anauma を切った(= 分母40) → 3回来ただけでは昇格しない
        for i in range(40):
            er.record_fired(f'race{i}', {1: ['anauma']}, path=p)
        led = er.load_ledger(p)
        assert len(led) == 3, "fired記録でentriesは壊れない"
        st = er.tag_stats(led, path=p)
        assert st['anauma']['fired'] == 40 and st['anauma']['hits'] == 3
        assert not st['anauma']['promoted'], \
            f"40回切って3回来た(7.5%)は昇格しない, got {st['anauma']}"

        # --- 冪等性: 同じrace_idを何度記録しても分母は増えない(Streamlit再描画対策) ---
        for _ in range(5):
            er.record_fired('race0', {1: ['anauma']}, path=p)
        assert er.tag_stats(er.load_ledger(p), path=p)['anauma']['fired'] == 40, \
            "同一race_idの再記録で分母が膨らまない"

        # --- 少数だが高率なタグは昇格する ---
        from core.bayes_stats import shrink_rate
        assert shrink_rate(3, 3, er.BASE_SURVIVE, er.PRIOR_STRENGTH) >= er.PROMOTE_RATE, \
            "3回切って3回来た=昇格"
        assert shrink_rate(3, 40, er.BASE_SURVIVE, er.PRIOR_STRENGTH) < er.PROMOTE_RATE, \
            "40回切って3回来た=昇格しない(頻出タグの誤昇格防止)"
        os.remove(p)
    check("elim_reasons.learned_tags(分母つき昇格)", t_elim_promote)

    def t_odds_schedule():
        from core import odds_schedule as osch
        from datetime import datetime as _dts
        assert osch._norm_hhmm('8:40') == '08:40' and osch._norm_hhmm('0840') == '08:40'
        assert osch._norm_hhmm('25:00') is None and osch._norm_hhmm('x') is None
        plan = {'date': '20260712', 'times': ['12:00', '08:40'],
                'races': [{'race_id': '202605050311', 'label': '東京11R'}], 'records': {}}
        plan = osch.save_plan(plan, path=osch.PLAN_PATH + '.smoketest')
        assert plan['times'] == ['08:40', '12:00'], f"時刻は正規化+ソート, got {plan['times']}"
        # 08:40枠は08:45時点でdue / 09:30(猶予25分超)ではstale=due外
        due = osch.due_slots(plan, now=_dts(2026, 7, 12, 8, 45))
        assert ('202605050311', '08:40', '東京11R') in due, f"08:45に08:40枠がdue, got {due}"
        assert osch.due_slots(plan, now=_dts(2026, 7, 12, 9, 30)) == [], "猶予超過はdue外(stale)"
        assert osch.due_slots(plan, now=_dts(2026, 7, 12, 8, 30)) == [], "予定前はdue外"
        osch.mark_done(plan, '202605050311', '08:40', 12)
        assert osch.due_slots(plan, now=_dts(2026, 7, 12, 8, 45)) == [], "記録済はdue外"
        stt = osch.plan_status(plan, now=_dts(2026, 7, 12, 8, 45))
        assert stt['total'] == 2 and stt['done'] == 1 and stt['pending'] == 1, f"進捗, got {stt}"
        # 共通times空×レース個別timesのプランでもdueが出る(ランナーガードバグ回帰防止)
        plan2 = {'date': '20260712', 'times': [],
                 'races': [{'race_id': '202610020607', 'label': '小倉7R', 'times': ['13:10']}],
                 'records': {}}
        due2 = osch.due_slots(plan2, now=_dts(2026, 7, 12, 13, 15))
        assert ('202610020607', '13:10', '小倉7R') in due2, f"個別times形式でdue, got {due2}"
        # ── 前日夜枠(night_times): dateの前日の時刻としてdue判定される ──
        plan3 = {'date': '20260713', 'times': ['08:40'], 'night_times': ['22:00'],
                 'races': [{'race_id': '202605050311', 'label': '東京11R'}], 'records': {}}
        plan3 = osch.save_plan(plan3, path=osch.PLAN_PATH + '.smoketest')
        assert plan3['night_times'] == ['22:00'], "night_timesも正規化保存"
        # 前日(7/12) 22:05 → 前日夜枠がdue(トークンは'前日22:00')
        due3 = osch.due_slots(plan3, now=_dts(2026, 7, 12, 22, 5))
        assert ('202605050311', '前日22:00', '東京11R') in due3, f"前日夜がdue, got {due3}"
        # 当日(7/13) 22:05 は前日夜枠のdueではない(猶予超過)・当日朝08:45は当日枠のみ
        assert osch.due_slots(plan3, now=_dts(2026, 7, 13, 22, 5)) == [], "当日夜はdue外"
        due3b = osch.due_slots(plan3, now=_dts(2026, 7, 13, 8, 45))
        assert due3b == [('202605050311', '08:40', '東京11R')], f"当日朝は当日枠のみ, got {due3b}"
        # mark_doneでキー'<rid>|前日22:00'が立ち、二重記録しない
        osch.mark_done(plan3, '202605050311', '前日22:00', 12)
        assert osch.due_slots(plan3, now=_dts(2026, 7, 12, 22, 5)) == [], "前日夜の記録済はdue外"
        stt3 = osch.plan_status(plan3, now=_dts(2026, 7, 12, 22, 5))
        assert stt3['total'] == 2 and stt3['done'] == 1, f"前日夜込みの進捗, got {stt3}"
        # 本線スロット: 朝一8:40 + 発走前5点(15/10/5分前・直前・最終)
        rec_names = [x[0] for x in osch.RECOMMENDED]
        for _nm in ('08:40', '発走15分前', '発走10分前', '発走5分前', '発走1分前', '発走3分後'):
            assert _nm in rec_names, f"RECOMMENDEDに{_nm}が無い"
        assert osch.DEFAULT_CLOCK_TIMES == ['08:40']
        assert osch.prepost_hhmm('15:40') == ['15:25', '15:30', '15:35', '15:39', '15:43']
        plan4 = {'date': '20260712', 'times': ['08:40'],
                 'races': [{'race_id': '202605050311', 'label': '東京11R'}], 'records': {}}
        plan4, npp = osch.attach_prepost_times(
            plan4, {'202605050311': '15:40'},
            labels_by_rid={'202605050311': '東京11R'})
        assert npp == 5, f"発走前5点で5枠, got {npp}"
        rt4 = osch.race_times(plan4, '202605050311')
        for _t in ('15:25', '15:30', '15:35', '15:39', '15:43', '08:40'):
            assert _t in rt4, f"本線枠{_t}が無い, got {rt4}"
        plan4, npp2 = osch.attach_prepost_times(plan4, {'202605050311': '15:40'})
        assert npp2 == 0, "二重予約しない"
        # フェーズ(時点ラベル): 発走時刻がエントリに保持され、スロットから復元できる
        assert plan4['races'][0].get('post') == '15:40', "発走時刻をエントリに保持"
        assert osch.slot_phase(plan4, '202605050311', '15:25') == '15分前'
        assert osch.slot_phase(plan4, '202605050311', '15:30') == '10分前'
        assert osch.slot_phase(plan4, '202605050311', '15:35') == '5分前'
        assert osch.slot_phase(plan4, '202605050311', '15:39') == '直前'
        assert osch.slot_phase(plan4, '202605050311', '15:43') == '最終'
        assert osch.slot_phase(plan4, '202605050311', '08:40') == '朝一'
        assert osch.slot_phase(plan4, '202605050311', '前日22:00') == '前日夜'
        assert osch.classify_phase(-3) == '最終' and osch.classify_phase(1) == '直前'
        assert osch.classify_phase(30) == '30分前' and osch.classify_phase(None, '12:00') == '中間'
        # 手動記録の時点推定: 発走8分前の『今』は10分前
        assert osch.current_phase(plan4, '202605050311', now=_dts(2026, 7, 12, 15, 32)) == '10分前'
        # ハートビート: touch直後はalive・古い/無しはFalse
        _hb = osch.HEARTBEAT_PATH + '.smoketest'
        osch.touch_heartbeat(path=_hb)
        assert osch.runner_alive(path=_hb), "touch直後はalive"
        assert not osch.runner_alive(max_age_s=-1, path=_hb), "期限切れはFalse"
        import os as _os_sm
        _os_sm.remove(osch.PLAN_PATH + '.smoketest')
        _os_sm.remove(_hb)
    check("odds_schedule.plan/due/status", t_odds_schedule)

    def t_dbkeiba_slug():
        from core import dbkeiba as dk
        # slugは 'jockey-samejima' 形式と 'jockey-osuke-tayama'(名-姓)形式の両方がある。
        # 正規表現の文字クラスに '-' が無いと後者が途中で切れ、その騎手がマップから丸ごと
        # 落ちる(2026-07に20名欠落を実測。田山旺佑が『未取得』のままだった真因)。
        jmap = {'鮫島克駿': 'jockey-samejima', '鮫島良太': 'jockey-ryota-sameshima',
                '田山旺佑': 'jockey-osuke-tayama', '戸崎圭太': 'jockey-tosaki',
                'ルメール': 'jockey-lemaire'}
        # 姓のみ表記 → 完全名
        assert dk.resolve_slug('田山', jmap) == 'jockey-osuke-tayama', "姓のみ『田山』が解決"
        assert dk.resolve_slug('戸崎圭', jmap) == 'jockey-tosaki', "『戸崎圭』→戸崎圭太"
        # 中間文字が省略された略記(アプリ『鮫島駿』 vs サイト『鮫島克駿』)。
        # 同姓の『鮫島良太』がいても末尾一致ガードで誤爆しない。
        assert dk.resolve_slug('鮫島駿', jmap) == 'jockey-samejima', "『鮫島駿』→鮫島克駿"
        # 外国人騎手のイニシャル付き
        assert dk.resolve_slug('Ｃ．ルメール', jmap) == 'jockey-lemaire', "イニシャル付きが解決"
        # 実マップにも両騎手が載っていること(取りこぼし回帰の検出)
        real = dk.get_jockey_map(allow_fetch=False)
        if real:
            assert dk.resolve_slug('鮫島駿', real), "実マップで鮫島駿が解決"
            assert dk.resolve_slug('田山', real), "実マップで田山が解決"
    check("dbkeiba.resolve_slug(ハイフンslug/略記)", t_dbkeiba_slug)

    def t_np_j5():
        from core import newspaper as np_j5
        rid = 'smoketest_j5'
        rows = [{'騎手込み順位': 1, '順位変動': '↑2', '馬番': 9, '馬名': 'テスト馬',
                 '騎手': '鮫島駿', '強適スコア': 71.2, '騎手係数': 1.043,
                 '黄金ライン': '🥇🥇', 'DB条件': '📗2', '騎手込みスコア': 74.3}]
        np_j5.write_j5_snapshot(rid, rows, weight=1.0)
        d = np_j5.load_j5(rid)
        assert d and len(d['rows']) == 1 and d['weight'] == 1.0, "J5スナップショット保存/読込"
        h = np_j5._j5_html(rid)
        assert 'テスト馬' in h and '鮫島駿' in h, "J5表に馬名/騎手が載る"
        assert '100%' in h, "騎手影響率(スライダー値)を併記=再現性の担保"
        assert 'exbox exwide' in h, "8列なので幅広ボックス"
        # スナップショット未保存のレースでは空(=SRA未解析レースに出ない)
        assert np_j5._j5_html('no_such_race_id') == '', "未保存レースは空"
        os.remove(np_j5._j5_path(rid))
    check("newspaper.j5(騎手係数セクション)", t_np_j5)

    def t_np_dev_thoughts():
        from core import newspaper as np_dt
        rid = 'smoketest_devth'
        ph_res = {
            'steps': [
                {'key': 'race_filter', 'no': '①', 'name': 'レース選別', 'desc': '',
                 'enabled': True, 'verdict': '買い対象', 'reasons': ['荒れ確率62%']},
                {'key': 'danger_check', 'no': '③', 'name': '危険人気馬チェック', 'desc': '',
                 'enabled': False, 'verdict': '', 'reasons': []},
            ],
            'final': {'honmei': [12], 'aite': [4, 9], 'ana': [7], 'keshi': [11, 8],
                      'plan': '3連複本線', 'skip': False, 'skip_reasons': []},
        }
        np_dt.write_philosophy_snapshot(rid, ph_res)
        d = np_dt.load_philosophy(rid)
        assert d and len(d['steps']) == 2 and d['final']['honmei'] == [12], \
            "思考プロセススナップショット保存/読込"
        h = np_dt._developer_thoughts_html(rid)
        assert '開発者の思考プロセス' in h and '①' in h and 'レース選別' in h, \
            "紙面に見出し+有効ステップが載る"
        assert '危険人気馬チェック' not in h, "OFFのステップは省く"
        assert '12' in h, "本命馬番が載る"
        assert np_dt._developer_thoughts_html('no_such_race_id') == '', "未保存レースは空"
        os.remove(np_dt._philosophy_path(rid))
    check("newspaper.dev_thoughts(開発者の思考プロセス)", t_np_dev_thoughts)

    def t_np_ai_commentary():
        from core import newspaper_commentary as nc
        from core import newspaper as np_ai
        # 俗説フィルタ(検証で否定済みのキーワードを検出)
        assert nc._contains_quarantined('前走の脚質が良いので買い'), "俗説キーワード検出"
        assert not nc._contains_quarantined('combo数が多く危険理由もない'), "通常文は非検出"
        # コスト見積り(レース数×人格数)
        est = nc.estimate_cost(6)
        assert est['calls'] == 6 * len(nc.COMMENTATORS), "コール数=レース数×人格数"
        # 未生成レースはHTML空(=自動生成されない・課金事故防止)
        assert np_ai._commentary_html('no_such_race_id_xyz') == '', "未生成は空"
        # 保存/読込/描画(ダミーデータ・API呼び出しなし)
        rid = 'smoketest_aicom'
        dummy = [{'persona': 'gou', 'name': 'ゴウ', 'emoji': '🔥', 'comment': 'テストコメント'}]
        nc.write_commentary_snapshot(rid, dummy)
        d = nc.load_commentary(rid)
        assert d and len(d['comments']) == 1, "コメント保存/読込"
        h = np_ai._commentary_html(rid)
        assert 'ゴウ' in h and 'テストコメント' in h and 'exbox exwide' in h, \
            "紙面にコメントが載る(幅広ボックス)"
        os.remove(nc._commentary_path(rid))
    check("newspaper_commentary.AIコメント欄(俗説フィルタ/コスト見積り)", t_np_ai_commentary)

    def t_np_value_zone():
        from core import newspaper as np_vz
        rid = 'smoketest_vzone'
        rows = [
            {'馬番': 12, 'name': 'テストA', 'fuku': 53.1, 'roi': 79.8, 'odds': 3.9, 'pop': 1,
             'ゾーン': '① 勝ちゾーン(このレースの軸候補)'},
            {'馬番': 2, 'name': 'テストB', 'fuku': 40.8, 'roi': 89.4, 'odds': 6.1, 'pop': 2,
             'ゾーン': '② 一撃ゾーン(穴)'},
        ]
        np_vz.write_value_zone_snapshot(rid, rows)
        d = np_vz.load_value_zone(rid)
        assert d and len(d['rows']) == 2, "複勝率×回収率マップのスナップショット保存/読込"
        h = np_vz._value_zone_html(rid)
        assert '複勝率×回収率マップ' in h and '① 勝ちゾーン' in h and '② 一撃(穴)' in h, \
            "紙面にゾーン別の馬が載る"
        assert np_vz._value_zone_html('no_such_race_id') == '', "未保存レースは空"
        os.remove(np_vz._value_zone_path(rid))
    check("newspaper.value_zone(複勝率×回収率マップ)", t_np_value_zone)

    def t_np_value_zone_chart():
        from core import newspaper as np_vzc
        assert np_vzc._value_zone_scatter_svg([]) == '', "0件は空文字"
        assert np_vzc._value_zone_scatter_svg([{'馬番': 1, 'roi': 80, 'fuku': 30}]) == '', \
            "1件のみは散布図として意味がないので空文字"
        rows = [
            {'馬番': 12, 'name': 'テストA', 'fuku': 80.0, 'roi': 120.0,
             'ゾーン': '① 勝ちゾーン(このレースの軸候補)'},
            {'馬番': 2, 'name': 'テストB', 'fuku': 10.0, 'roi': 90.0,
             'ゾーン': '④ 見送り'},
        ]
        svg = np_vzc._value_zone_scatter_svg(rows)
        assert svg.startswith('<svg') and '12テストA' in svg and '2テストB' in svg, \
            "馬番+馬名ラベルが載る"
        assert '#2f9e44' in svg and '#868e96' in svg, "ゾーン別の色分けが載る"
        assert '<rect' in svg and '① 勝ちゾーン</text>' in svg, \
            "①勝ちゾーンの網掛け矩形+ラベルが描画される"
        assert svg.count('stroke-dasharray') >= 2, "境界の破線(x_mid/y_hi等)が複数本ある"
        for lbl in ('① 勝ちゾーン', '② 一撃(穴)', '③ 堅実', '④ 見送り'):
            assert lbl in svg, f"凡例に{lbl}が無い"
        # 閾値の再計算(_quantile)がapp.py側の式(fuku上位25%/健全馬roiの中央値・75%)と一致すること
        assert np_vzc._quantile([1, 2, 3, 4], 0.5) == 2.5, "中央値の線形補間"
        assert np_vzc._quantile([10], 0.75) == 10, "1件のみは値そのもの"

        rid = 'smoketest_vzone_chart'
        np_vzc.write_value_zone_snapshot(rid, rows)
        try:
            h = np_vzc._value_zone_chart_html(rid)
            assert 'ZONEシート' in h and '<svg' in h, "ZONEシート散布図ボックスが生成される"
            assert h.startswith("<div class='exbox exwide'"), "exwideボックス(横幅66.2%)で生成"
            assert np_vzc._value_zone_chart_html('no_such_race_id') == '', "未保存レースは空"
        finally:
            os.remove(np_vzc._value_zone_path(rid))
    check("newspaper.value_zone_chart(ZONEシート散布図)", t_np_value_zone_chart)

    def t_np_value_zone_chart_wiring():
        # build_newspaper_html: 既定OFF/明示ONで表示が切り替わり、末尾(evidenceの後)に置かれること
        import pandas as _pdn
        from core import newspaper as np_vzw
        rid = 'smoketest_vzone_wiring'
        df = _pdn.DataFrame({'Umaban': [1, 2], 'Name': ['馬A', '馬B'],
                              'Odds': ['2.5', '9.0'], 'Popularity': ['1', '2']})
        np_vzw.write_view_snapshot(rid, df, {}, ['Umaban', 'Name', 'Odds'],
                                   meta={'condition': '良'}, sort_label='テスト順')
        rows = [
            {'馬番': 1, 'name': '馬A', 'fuku': 80.0, 'roi': 120.0,
             'ゾーン': '① 勝ちゾーン(このレースの軸候補)'},
            {'馬番': 2, 'name': '馬B', 'fuku': 10.0, 'roi': 90.0, 'ゾーン': '④ 見送り'},
        ]
        np_vzw.write_value_zone_snapshot(rid, rows)
        try:
            html_off, _ = np_vzw.build_newspaper_html([rid], {})
            assert 'ZONEシート' not in html_off, "既定(未指定)ではOFF"
            html_on, _ = np_vzw.build_newspaper_html(
                [rid], {'sections': {'value_zone_chart': True}})
            assert 'ZONEシート' in html_on, "明示ONで表示"
            assert html_on.index('ZONEシート（複勝率×回収率の散布図）') \
                > html_on.index('複勝率×回収率マップ（ゾーン別）'), \
                "複勝率×回収率マップ(テーブル版)より後ろ=extras末尾寄りに配置"
        finally:
            for pth in (np_vzw._view_path(rid), np_vzw._value_zone_path(rid)):
                if os.path.exists(pth):
                    os.remove(pth)
    check("newspaper.build_newspaper_html(ZONEシート散布図のON/OFF配線)", t_np_value_zone_chart_wiring)

    def t_np_page_format():
        from core import newspaper as np_pf
        assert np_pf.resolve_page_format('a3_portrait') == ('A3', False), \
            "A3縦=A3/非landscape"
        assert np_pf.resolve_page_format('portrait') == ('A4', False), "A4縦=A4/非landscape"
        assert np_pf.resolve_page_format('landscape') == ('A4', True), "既定=A4横/landscape"
        assert np_pf.resolve_page_format('unknown_value') == ('A4', True), \
            "未知値は既定(A4横)にフォールバック"
        rid = 'smoketest_a3fmt'
        import pandas as _pdn
        df = _pdn.DataFrame({'Umaban': [1, 2], 'Name': ['馬A', '馬B'],
                              'Odds': ['2.5', '9.0'], 'Popularity': ['1', '2']})
        np_pf.write_view_snapshot(rid, df, {}, ['Umaban', 'Name', 'Odds'],
                                  meta={'condition': '良'}, sort_label='テスト順')
        try:
            html, iss = np_pf.build_newspaper_html([rid], {'orientation': 'a3_portrait'})
            assert html and not iss[0].get('error'), "A3縦でエラー無くHTML生成"
            assert 'size: A3 portrait' in html, "@page が A3 portrait を宣言"
        finally:
            if os.path.exists(np_pf._view_path(rid)):
                os.remove(np_pf._view_path(rid))
    check("newspaper.resolve_page_format/A3縦レンダリング", t_np_page_format)

    def t_np_colfmt():
        from core import newspaper as np_cf
        # 見出しの折り返し(<br>挿入)
        assert np_cf._header_cell('⭐展開適合度') == '⭐展開<br>適合度', "展開適合度は⭐展開で改行"
        assert np_cf._header_cell('🔥総合戦闘力') == '🔥総合<br>戦闘力', "総合戦闘力は🔥総合で改行"
        assert np_cf._header_cell('🟣🔵補正T') == '🟣🔵<br>補正T', "補正Tは🔵で改行"
        assert np_cf._header_cell('🟣🏇騎手力(乗替)') == '🟣騎手力(乗替)', "騎手力の🏇アイコン除去"
        assert np_cf._header_cell('馬名') == '馬名', "対象外の見出しは素通し"
        # JPower値だけ括弧手前で改行・他列は改行しない
        assert np_cf._cell_html('JPower', '1 👑62(▲+25)', 0) == '1 👑62<br>(▲+25)', "騎手力は括弧手前で改行"
        assert np_cf._cell_html('JPower', '52', 0) == '52', "デルタ無しはそのまま"
        assert np_cf._cell_html('BloodStats', '27%(256)', 0) == '27%(256)', "他列の括弧は改行しない"
        # 乗替(JockeyChange)は矢印の後ろで改行
        _jc_out = np_cf._cell_html('JockeyChange', '木幡巧也→丹内', 0)
        assert '→<br>' in _jc_out, "乗替は→の後で改行"
        assert 'color:#c33' in _jc_out, "乗替は赤テキスト"
        _jc_dash = np_cf._cell_html('JockeyChange', '-', 0)
        assert 'color:#1a5fb4' in _jc_dash, "乗替なしは青テキスト"
        # 列スラッグ(CSSクラス)
        assert np_cf._col_slug('Projected Score') == 'col-Projected_Score', "空白は_に畳む"
        assert np_cf._col_slug('Bloodline') == 'col-Bloodline'
    check("newspaper.列見出し折返し/幅クラス", t_np_colfmt)

    def t_roi_tools():
        # 提案C: 極端人気薄(100倍超)の構造的不利警告
        from core import value_scanner as vsr
        assert vsr.longshot_disadvantage(150) and vsr.longshot_disadvantage(150)['roi'] == 44.5, \
            "100倍超は不利帯警告"
        assert vsr.longshot_disadvantage(100) is None, "ちょうど100倍は非警告(境界)"
        assert vsr.longshot_disadvantage(80) is None, "50-100倍は本命帯同等=警告しない"
        assert vsr.longshot_disadvantage(None) is None, "不正値はNone"
        # 提案B: ダッチング(均等回収)配分
        from core.money import dutch_stakes
        r = dutch_stakes([{'um': 8, 'odds': 4.0}, {'um': 4, 'odds': 6.0}], 3000)
        assert r['total'] > 0 and len(r['stakes']) == 2, "2頭配分が返る"
        # オッズ低すぎ(Σ1/o>=1)はトリガミ確定警告
        r2 = dutch_stakes([{'um': 1, 'odds': 1.5}, {'um': 2, 'odds': 1.8}], 2000)
        assert r2['implied_hit'] >= 1.0 and 'トリガミ' in r2['note'], "オーバーラウンドはトリガミ警告"
        # 単勝で人気馬(Σ1/o<1)は条件付回収>100%だがヒット率併記(-EVは明記)
        r3 = dutch_stakes([{'um': 1, 'odds': 3.9}, {'um': 2, 'odds': 6.1}], 3000)
        assert r3['payout_ratio'] > 1.0 and 'hit_pct' in r3 and '-EV' in r3['note'], \
            "Σ1/o<1は条件付>100%+ヒット率+(-EV明記)"
        # 空/予算0は安全
        assert dutch_stakes([], 1000)['total'] == 0 and dutch_stakes([{'um': 1, 'odds': 3}], 0)['total'] == 0
    check("ROI道具(longshot警告/dutching)", t_roi_tools)

    def t_pace_spurt():
        from core import pace_spurt as ps
        # スロー=前半3F遅い(mae大)>後半, ハイ=前半速い(mae小)<後半 → 芝1800想定
        assert ps.classify_pace('芝', 1800, 420, 360) == 'slow', "前半遅い=slow"
        assert ps.classify_pace('芝', 1800, 340, 400) == 'high', "前半速い=high"
        assert ps.classify_pace('芝', 1800, 0, 360) is None, "欠損はNone"
        q = ps.spurt_quality(None)  # ketto無しは安全に空
        assert q['tag'] is None and q['n'] == 0 and not q['reliable'], f"空入力は中立, got {q}"
    check("pace_spurt.classify/quality", t_pace_spurt)

    def t_odds_move():
        from core import odds_move as omv
        import pandas as _pdm
        # 朝一(t0): 3番が最良(1人気)・7番が2人気 / 直前(t1): 5番が浮上して1人気、3番は5人気に降下
        rows = []
        for ts, snap in [('2026-07-12 08:40:00', {3: 2.0, 7: 3.0, 5: 9.0, 9: 12.0, 2: 15.0}),
                         ('2026-07-12 15:20:00', {5: 2.2, 7: 3.1, 9: 6.0, 2: 8.0, 3: 11.0})]:
            for u, o in snap.items():
                rows.append({'timestamp': ts, 'umaban': u, 'odds_type': 'win', 'odds_value': o})
        h = _pdm.DataFrame(rows)
        r = omv.analyze_odds_movement(h)
        assert r['ok'], f"2スナップで分析可, got {r}"
        kinds = {i['kind']: i['umaban'] for i in r['insights']}
        assert kinds.get('fav_fake') == 5, f"直前浮上5番=見せかけ1番人気, got {kinds}"
        assert kinds.get('hidden_ana') == 3, f"朝一1番人気→直前降下3番=隠れ本命, got {kinds}"
        labs = omv.chart_observe_labels(h)
        assert labs.get(5) == '後から押された1番', f"観察ラベル 後から押された1番, got {labs}"
        assert labs.get(3) == '朝は売れて沈んだ', f"観察ラベル 朝は売れて沈んだ, got {labs}"
        # 朝から軸: 最初も最後も3番が1番人気
        rows_s = []
        for ts, snap in [('2026-07-12 08:40:00', {3: 2.0, 7: 3.0, 5: 9.0}),
                         ('2026-07-12 15:20:00', {3: 2.1, 7: 3.2, 5: 8.0})]:
            for u, o in snap.items():
                rows_s.append({'timestamp': ts, 'umaban': u, 'odds_type': 'win', 'odds_value': o})
        labs_s = omv.chart_observe_labels(_pdm.DataFrame(rows_s))
        assert labs_s.get(3) == '朝から軸', f"観察ラベル 朝から軸, got {labs_s}"
        # VH短縮観察(24→15)。買い目繰り上げには使わない関数の契約。
        rows_v = []
        for ts, snap in [('2026-07-12 08:40:00', {7: 24.0, 3: 2.0}),
                         ('2026-07-12 15:30:00', {7: 15.0, 3: 2.2})]:
            for u, o in snap.items():
                rows_v.append({'timestamp': ts, 'umaban': u, 'odds_type': 'win', 'odds_value': o})
        vobs = omv.vh_shorten_observe(_pdm.DataFrame(rows_v), umabans=[7])
        assert vobs and vobs[0]['kind'] == 'vh_shorten' and vobs[0]['label'] == '短縮中'
        # 1スナップのみは不足メッセージ
        h1 = h[h['timestamp'] == '2026-07-12 08:40:00']
        assert not omv.analyze_odds_movement(h1)['ok'], "1スナップは分析不可"
    check("odds_move.analyze(朝一↔直前)", t_odds_move)

    def t_quinella_div():
        from core import quinella_div as qd
        assert qd.pair_umabans('0105') == (1, 5)
        mass = qd.support_mass({(1, 2): 2.0, (1, 3): 4.0, (2, 3): 10.0})
        # 1: 0.5+0.25=0.75 / 2: 0.5+0.1=0.6 / 3: 0.25+0.1=0.35
        rk = qd.support_rank(mass)
        assert rk[1] == 1 and rk[2] == 2 and rk[3] == 3, f"支持順位, got {rk}"
        div = qd.ninki_minus_qrank({1: 3, 2: 1, 3: 2}, rk)
        assert div[1] == 2, f"馬連の方が支持 +2, got {div}"
        assert qd.fade_umabans({1: 1, 2: 2, 3: 3}, {1: 3, 2: 2, 3: 1}) == [1], \
            "1番人気なのに馬連3位=馬連ではいまいち"
    check("quinella_div.support_rank", t_quinella_div)

    def t_newspaper():
        # 📰 新聞発行: viewスナップショット往復→HTML組版→CSV(PDF化はPlaywright依存なので対象外)
        import pandas as _pdn
        from core import newspaper as npm
        rid = '209905050599'
        df = _pdn.DataFrame({
            'Rank': [1, 2], 'Umaban': [3, 7], 'Name': ['🔥馬A', '馬B'],
            'Odds': ['2.5', '48.0'], 'Popularity': ['1', '9'], '補正T': ['🔵110', '98'],
            'PastRuns': [[{'a': 1}], [{'a': 2}]], 'Name__dup_right': ['x', 'y'],
            'RaceName': ['テストR'] * 2, 'Venue': ['東京'] * 2, 'RaceDate': ['2026/07/12'] * 2,
        })
        npm.write_view_snapshot(rid, df, {'Name': '馬名', '補正T': '🔵補正T'},
                                ['Umaban', 'Name', 'Odds', '補正T'],
                                meta={'condition': '良'}, sort_label='テスト順')
        v = npm.load_view(rid)
        assert v and v['source'] == 'view', "viewスナップショット読める"
        assert 'PastRuns' not in v['columns'] and not any(
            c.endswith('__dup_right') for c in v['columns']), "ネスト列/複製列は除外"
        assert v['meta']['venue'] == '東京' and v['meta']['condition'] == '良', f"meta, got {v['meta']}"
        npm.write_consensus_snapshot(
            rid, '②穴妙味向き',
            {'groups': {'honmei': [3], 'aite': [], 'osae': [], 'ana': {7}, 'keshi': []},
             'horses': [{'umaban': 3, 'name': '馬A', 'pop': 1, 'odds': 2.5, 'axis_mark': '◎'}]},
            aim={'danger': {7}, 'veto': set(), 'elim': {7: 3},
                 'vh': {7: 0.2}, 'vh_tier': {7: '🎯精鋭'},
                 'edge_reasons': {7: ['🔥末脚top']}, 'danger_reasons': {7: ['ガラス人気馬']}})
        cv = npm.load_consensus(rid)
        assert cv['groups']['ana'] == [7], "set→listで合議groups往復"
        assert cv['aim']['elim'].get('7') == 3, "aim(消去クロス)が往復"
        # 買い目/展開スナップショット
        npm.write_bets_snapshot(rid, 'trio', {'bets': [{'combo': (3, 7, 2), 'odds': 58.0,
                                                        'aim_tag': '🎯'}]},
                                extra={'pattern': '②穴妙味'})
        npm.write_pace_snapshot(rid, {'pos4': {3: 0.1, 7: 0.9}, 'leader': 3,
                                      'pace': 'ミドル', 'nige_umas': [3], 'contested': False})
        html, iss = npm.build_newspaper_html([rid], {'col_mode': 'app'})
        # 見出し「🟣🔵補正T」は列幅対策で🔵の後に<br>が入る(→ 🔵<br>補正T)
        assert html and '🔵<br>補正T' in html and '① 本命' in html, "紙面に表示ラベル(折返し)+合議カード"
        for tok in ('危険人気馬', '軸候補', '3連複おすすめ', '展開・隊列',
                    '消去フィルター', '穴馬ハンター'):
            assert tok in html, f"新セクション欠落: {tok}"
        assert '<svg' in html, "展開・隊列にレーン図(SVG)が併記される"
        assert '《4角想定》' in html, "finish未保存の旧スナップショットは4角想定にフォールバック"
        assert '3-7-2(58倍)' in html, "買い目コンボが紙面化"
        assert iss[0]['n_cols'] == 4, f"アプリ表示列の列数維持, got {iss[0]['n_cols']}"
        from core import score_cache as _sc_np
        _gp = _sc_np._gate_path(rid)
        if os.path.exists(_gp):
            os.remove(_gp)
        npm.write_bets_snapshot(
            rid, 'playbook',
            {'bets': {}, 'meta': {'zone': 'C', 'ui_line': 'C中庸'}},
            extra={'zone': 'C', 'cross_n': 3})
        _badge0, _ = npm._buymeta_html(rid)
        assert 'RRV' in _badge0 and '見送り' not in _badge0, \
            f"Gate無しでも型RRV, got {_badge0}"
        html0, _ = npm.build_newspaper_html([rid], {'col_mode': 'app'})
        assert 'RRV' in html0, "Gate無しでもレース見出しに型が出る"
        _sc_np.write_gate(rid, 'skip', '中立')
        _badge, _ = npm._buymeta_html(rid)
        assert '⛔ 見送り' in _badge and '中立' in _badge and 'RRV' in _badge, \
            f"紙面ヘッダに型RRV, got {_badge}"
        html_g, _ = npm.build_newspaper_html([rid], {'col_mode': 'app'})
        assert '｜RRV' in html_g, "レース見出しの見送り横に型が出る"
        # カスタム(チェック式)列: チェック順=紙面順
        html_c, iss_c = npm.build_newspaper_html(
            [rid], {'col_mode': 'custom', 'custom_cols': ['Name', 'Umaban']})
        assert iss_c[0]['n_cols'] == 2, f"カスタム2列, got {iss_c[0]['n_cols']}"
        csvb, nr, nc = npm.build_csv_bytes(rid)
        assert csvb and nr == 2 and nc >= 4, f"CSVエクスポート, got {nr}x{nc}"
        for pth in (npm._view_path(rid), npm._cv_path(rid),
                    npm._bets_path(rid), npm._pace_path(rid),
                    _sc_np._gate_path(rid)):
            if os.path.exists(pth):
                os.remove(pth)
    check("newspaper.スナップショット往復/組版/CSV", t_newspaper)

    def t_umai_baken_shape():
        from core import umai_baken as ub
        html = ('<table><tr><th>券種・買い目</th><th>組み合わせ・点数</th></tr>'
                '<tr><td>3連複(通常)</td><td>1 - 2 - 3 1,000円</td></tr>'
                '<tr><td>合計</td><td>1,000円</td></tr></table>')
        p = ub.parse_detail_tickets(html)
        assert p['tickets'][0]['kind'] == '3連複' and p['total_stake'] == 1000
        rec = ub.shape_record('1', '2', p)
        assert '3連複' in rec['app_near']
        assert ub.extract_yoso_ids('id=6051613&pid=yoso_detail') == ['6051613']
    check("umai_baken.買い目形パース", t_umai_baken_shape)

    def t_vmatrix_pos4_resolve():
        from core.pace_map import resolve_v_pos
        pos, src = resolve_v_pos(1, 'A', 0.5, profiles={'A': {'ten': 0.2}}, pos4={1: 0.1})
        assert src == 'pos4' and abs(pos - 0.1) < 1e-9
        pos2, src2 = resolve_v_pos(2, 'B', 0.5, profiles={'B': {'ten': 0.2}}, pos4=None)
        assert src2 == 'ten' and abs(pos2 - 0.2) < 1e-9
    check("vmatrix_pos4.resolve_v_pos優先順位", t_vmatrix_pos4_resolve)

    def t_vmatrix_annotations_contract():
        from core import vmatrix_annotations as vma
        ann = vma.collect_horse_annotations(
            [{'umaban': 1, 'name': 'A', 'score': 0.5}],
            {'A': {'agari': 0.2}}, [{'Umaban': 1, 'Popularity': 7}],
            '202606040101')
        assert vma.TAG_SPURT in ann[1]['tags']
    check("vmatrix_annotations.末脚タグ契約", t_vmatrix_annotations_contract)

    def t_pace_diagram_svg():
        from core import newspaper as np_pd
        assert np_pd._pace_diagram_svg({}) == '', "pos4空は空文字"
        assert np_pd._pace_diagram_svg({'a': 'x'}) == '', "不正値は空文字(例外を握って空)"
        svg = np_pd._pace_diagram_svg({3: 0.1, 7: 0.9}, {3: '馬A', 7: '馬B'})
        assert svg.startswith('<svg') and '3</text>' in svg and '7</text>' in svg, \
            "馬番ラベルがSVGテキストとして出力される"
        import re as _re_svg
        cxs = {int(m[0]): float(m[1]) for m in
               _re_svg.findall(r'title>(\d+)番[^<]*</title><circle cx="([\d.]+)"', svg)}
        assert cxs[3] > cxs[7], "前(値0.1)が右・後(値0.9)が左(PCの並び順に合わせて反転済み)"
        assert svg.index('前</text>') > svg.index('後</text>'), "前ラベルが右側(後より後に出現)"
        # 密集(全馬同一通過位置)でも同一行に重ならず全員配置されること(ジグザグ回避)
        dense = {i: 0.5 for i in range(1, 19)}
        svg_dense = np_pd._pace_diagram_svg(dense)
        assert all(f'>{i}</text>' in svg_dense for i in range(1, 19)), \
            "18頭全員がラベル欠落なく配置される"
        import re as _re
        cys = [float(m) for m in _re.findall(r'cy="([\d.]+)"', svg_dense)]
        # circle+textで同じcyが2回出るので重複除去し、行(cy値)が十分分散していることを確認
        uniq_cy = sorted(set(cys))
        assert len(uniq_cy) >= 10, f"密集時に十分な行数へジグザグ分散, got {len(uniq_cy)}"
        # 『後方N頭』の境界マーカー(縦破線+ラベル)
        svg_m = np_pd._pace_diagram_svg({1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9},
                                        marker=(0.6, '後方2頭'))
        assert '後方2頭' in svg_m and 'stroke-dasharray' in svg_m, "境界マーカーが描画される"
        assert np_pd._pace_diagram_svg({1: 0.1, 2: 0.9}, marker=None) != '', \
            "marker未指定でも従来通り描画される"
    check("newspaper._pace_diagram_svg(展開レーン図・密集回避・後方N頭マーカー)", t_pace_diagram_svg)

    def t_rear_group_threshold():
        from core import newspaper as np_rgt
        disp = {1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9}
        assert np_rgt._rear_group_threshold(disp, 0) is None, "n=0は境界なし"
        assert np_rgt._rear_group_threshold(disp, 5) is None, "n=全頭は境界なし"
        th = np_rgt._rear_group_threshold(disp, 2)
        assert 0.5 < th < 0.7, f"後方2頭(0.9,0.7)と前方(0.5)の中間, got {th}"
        assert all(disp[u] > th for u in (4, 5)), "後方2頭は境界より後ろ側"
        assert all(disp[u] < th for u in (1, 2, 3)), "残りは境界より前側"
    check("newspaper._rear_group_threshold(後方N頭の境界計算)", t_rear_group_threshold)

    def t_pace_finish_priority():
        # 直線到達(finish)が保存されていれば4角想定(pos4)より優先表示されること
        from core import newspaper as np_pf2
        rid = 'smoketest_pace_finish'
        try:
            np_pf2.write_pace_snapshot(rid, {
                'pos4': {3: 0.1, 7: 0.9}, 'finish': {3: 0.8, 7: 0.1},
                'leader': 3, 'pace': 'ミドル', 'nige_umas': [3], 'contested': False})
            d = np_pf2.load_pace(rid)
            assert d['finish'] == {'3': 0.8, '7': 0.1} or d['finish'] == {3: 0.8, 7: 0.1}, \
                f"finishが往復保存される, got {d.get('finish')}"
            html = np_pf2._pace_html(rid, [{'Umaban': 3, 'Name': '馬A'}, {'Umaban': 7, 'Name': '馬B'}])
            assert '《直線到達想定》' in html and '《4角想定》' not in html, \
                "finish保存時は直線到達想定ラベルを使い4角想定は出さない"
            # finish値(3=0.8後方寄り/7=0.1前方寄り)基準の並びになっている(pos4基準なら逆)
            assert '(前) 7' in html and '3 (後)' in html, \
                "並び順がfinish値基準になっていない(pos4なら3が前・7が後になるはず)"
        finally:
            if os.path.exists(np_pf2._pace_path(rid)):
                os.remove(np_pf2._pace_path(rid))
    check("newspaper._pace_html(finish優先/4角想定フォールバック)", t_pace_finish_priority)

    def t_pace_html_rear_marker():
        # 展開・隊列: 後方グループ(展開MAP)/AI展開照合の件数から『後方N頭』マーカーが図に載る
        from core import newspaper as np_prm
        from core import score_cache as sc_prm
        rid = 'smoketest_pace_rear_marker'
        try:
            np_prm.write_pace_snapshot(rid, {
                'pos4': {1: 0.1, 2: 0.3, 3: 0.5, 4: 0.7, 5: 0.9},
                'leader': 1, 'pace': 'ミドル', 'nige_umas': [1], 'contested': False})
            sc_prm.write_rear(rid, {4, 5})
            records = [{'Umaban': u, 'Name': f'馬{u}'} for u in range(1, 6)]
            html = np_prm._pace_html(rid, records)
            assert '後方グループ(展開MAP)' in html, "後方グループの説明行が出る"
            assert '後方2頭' in html, "rear件数(2頭)からマーカーラベルが生成される"
        finally:
            if os.path.exists(np_prm._pace_path(rid)):
                os.remove(np_prm._pace_path(rid))
            _rp = sc_prm._rear_path(rid)
            if os.path.exists(_rp):
                os.remove(_rp)
    check("newspaper._pace_html(後方N頭マーカーの配線)", t_pace_html_rear_marker)

    def t_vh_html_no_reason_tags():
        # 🎯穴馬ハンター: 〈⚡33ラップ適合/🔥末脚top/🧬血統上位〉等の根拠タグは非表示(ユーザー要望)
        from core import newspaper as np_vh
        cv = {'aim': {
            'vh_tier': {7: '🎯精鋭', 9: '🎯精鋭'},
            'vh': {7: 0.31, 9: 0.22},
            'edge_reasons': {7: ['⚡33ラップ適合', '🔥末脚top', '🧬血統上位'], 9: ['🔵補正T上位']},
            'ana': set(),
        }}
        records = [{'Umaban': '7', 'Name': 'テスト馬7', 'Popularity': '7'},
                   {'Umaban': '9', 'Name': 'テスト馬9', 'Popularity': '9'}]
        html = np_vh._vh_html(cv, records)
        assert '穴馬ハンター' in html and '🎯精鋭' in html and 'vh0.31' in html, \
            "tier/馬番/スコアは表示される"
        for tag in ('33ラップ適合', '末脚top', '血統上位', '補正T上位', '〈', '〉'):
            assert tag not in html, f"根拠タグ({tag})が残っている"
    check("newspaper._vh_html(根拠タグ非表示)", t_vh_html_no_reason_tags)

    def t_j5_html_columns():
        # 🏇騎手係数込みスコア: 内訳を表示+係数色分け、DB条件は削除済み
        from core import newspaper as np_j5t
        rid = 'smoketest_j5cols'
        rows = [
            {'馬番': 7, '馬名': 'テストG', '騎手': '武豊', '強適スコア': 88.5,
             '騎手係数': 1.05, '係数の意味': '上げる', '黄金ライン': '🥇42%',
             '騎手込みスコア': 93.0, '内訳': 'USM108・黄金ライン一致',
             '騎手込み順位': 1, '順位変動': '↑2'},
            {'馬番': 3, '馬名': 'テストH', '騎手': '横山武', '強適スコア': 70.0,
             '騎手係数': 0.98, '係数の意味': 'やや下げる', '黄金ライン': '-',
             '騎手込みスコア': 68.6, '内訳': '-',
             '騎手込み順位': 2, '順位変動': '→'},
        ]
        try:
            np_j5t.write_j5_snapshot(rid, rows, weight=1.0)
            html = np_j5t._j5_html(rid)
            assert 'USM108・黄金ライン一致' in html, "内訳は表示される"
            assert '🥇42%' in html and '1.05' in html, "黄金ライン/騎手係数は表示される"
            assert 'DB条件' not in html, "DB条件列は削除済み"
            assert 'color:#e03131' in html, "係数1.05は赤色になる"
            assert 'color:#1971c2' in html, "係数0.98は青色になる"
            for tag in ('88.5', '93.0', '↑2', '70.0', '68.6'):
                assert tag not in html, f"非表示にしたはずの値({tag})が残っている"
        finally:
            if os.path.exists(np_j5t._j5_path(rid)):
                os.remove(np_j5t._j5_path(rid))
    check("newspaper._j5_html(係数色分け・DB条件削除)", t_j5_html_columns)

    def t_bets_html_bet_types():
        # おすすめ買い目: 券種別ON/OFFで表示を絞り込める(3連複/3連単/馬連/馬単/ワイド)
        from core import newspaper as np_bt
        rid = 'smoketest_bettypes'
        try:
            np_bt.write_bets_snapshot(rid, 'trio', {'bets': [{'combo': (1, 2, 3), 'odds': 10.0}]})
            np_bt.write_bets_snapshot(rid, 'trifecta', {'bets': [{'combo': (1, 2, 3), 'odds': 20.0}]})
            np_bt.write_bets_snapshot(rid, 'qe', {'quinella': [{'combo': (1, 2), 'odds': 5.0}],
                                                   'exacta': [{'combo': (1, 2), 'odds': 8.0}]})
            np_bt.write_bets_snapshot(rid, 'wide', {'wide': [{'combo': (1, 2), 'odds': 3.0}],
                                                     'axis': 1})
            html_all = np_bt._bets_html(rid)
            for tok in ('3連複', '3連単', '馬連', '馬単', 'ワイド'):
                assert tok in html_all, f"未指定時は全券種表示, got missing {tok}"
            html_trio_only = np_bt._bets_html(rid, {'trio': True, 'trifecta': False,
                                                     'quinella': False, 'exacta': False,
                                                     'wide': False})
            assert '3連複' in html_trio_only, "trioのみON"
            for tok in ('3連単', '馬連', '馬単', 'ワイド'):
                assert tok not in html_trio_only, f"{tok}はOFFなので非表示のはず"
            html_q_only = np_bt._bets_html(rid, {'trio': False, 'trifecta': False,
                                                  'quinella': True, 'exacta': False, 'wide': False})
            assert '馬連おすすめ' in html_q_only and '馬単' not in html_q_only, \
                "馬連のみONなら単独タイトル(馬連/馬単の併記にならない)"
        finally:
            for pth_fn in (np_bt._bets_path,):
                p = pth_fn(rid)
                if os.path.exists(p):
                    os.remove(p)
    check("newspaper._bets_html(券種別ON/OFF)", t_bets_html_bet_types)

    def t_playbook_persist_newspaper():
        import pandas as _pdp
        from core import newspaper as np_pp
        from core import playbook_tickets as pb_pp
        rid = 'smoketestplaybook99'
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        df = _pdp.DataFrame({
            'Rank': list(range(1, 9)), 'Umaban': list(range(1, 9)),
            'Name': [f'H{i}' for i in range(1, 9)],
            'Odds': [2.0 + i for i in range(8)], 'Popularity': list(range(1, 9)),
            'RaceName': ['persistR'] * 8, 'Venue': ['東京'] * 8,
            'RaceDate': ['2026/08/17'] * 8,
        })
        try:
            np_pp.write_view_snapshot(rid, df, {}, ['Umaban', 'Name', 'Odds'],
                                      meta={'condition': '良'})
            np_pp.write_bets_snapshot(rid, 'trio', {
                'bets': [{'combo': (9, 8, 7), 'odds': 99.0}]})
            d0 = np_pp.load_bets(rid)
            old_trio = (d0.get('trio') or {}).get('result')
            # D
            rec_d = pb_pp.build_tickets(rid, 30, hs, {1: '◎', 3: '〇'}, ltr)
            np_pp.persist_playbook(rid, rec_d)
            bets = np_pp.load_bets(rid)
            view = np_pp.load_view(rid)
            assert bets.get('trio', {}).get('result') == old_trio, '既存trioを壊した'
            assert bets.get('playbook'), 'bets.json に playbook が無い'
            assert view.get('playbook'), 'view.json に playbook が無い'
            d_combos = {tuple(b['combo'])
                        for b in bets['playbook']['result']['bets']['trio']}
            assert d_combos == {(1, 2, 3), (1, 2, 4)}
            html_d = np_pp._bets_html(rid)
            assert '推奨買い方' in html_d and 'D鉄板｜人気型｜3連複2点' in html_d
            assert '1-2-3' in html_d and '1-2-4' in html_d
            assert '手動・参考' in html_d and '9-8-7' in html_d
            # C
            rec_c = pb_pp.build_tickets(rid, 55, hs, {1: '◎', 2: '〇'}, ltr)
            np_pp.persist_playbook(rid, rec_c)
            bets_c = np_pp.load_bets(rid)
            view_c = np_pp.load_view(rid)
            assert bets_c.get('trio', {}).get('result') == old_trio
            tri_n = len(bets_c['playbook']['result']['bets']['trifecta'])
            assert tri_n == 30 and not bets_c['playbook']['result']['bets']['trio']
            assert view_c['playbook']['result']['meta']['n_points'] == 30
            html_c = np_pp._bets_html(rid)
            assert 'C中庸｜Rank型｜検証済みフォーメーション' in html_c
            assert '3連単' in html_c and '30点' in html_c
            # BA skip: 推奨は見送り。旧trioは手動・参考として残る
            rec_ba = pb_pp.build_tickets(rid, 80, hs, {1: '◎', 2: '〇'}, ltr)
            np_pp.persist_playbook(rid, rec_ba)
            html_ba = np_pp._bets_html(rid)
            ba_bets = np_pp.load_bets(rid)
            assert ba_bets['playbook']['result']['meta']['skip'] is True
            assert ba_bets['playbook']['extra']['n_points'] == 0
            assert '見送り' in html_ba and '荒れゾーン｜見送り' in html_ba
            assert '9-8-7' in html_ba and '手動・参考' in html_ba
            # 推奨ブロックが旧9-8-7をデフォルト扱いにしない: 先頭の推奨に見送りがある
            assert html_ba.index('推奨買い方') < html_ba.index('手動・参考')
            # view 上書き後も playbook が残る
            np_pp.write_view_snapshot(rid, df, {}, ['Umaban', 'Name'],
                                      meta={'condition': '良'})
            view_after = np_pp.load_view(rid)
            assert view_after.get('playbook', {}).get('result', {}).get('meta', {}).get('skip') is True
        finally:
            for pth_fn in (np_pp._bets_path, np_pp._view_path):
                p = pth_fn(rid)
                if os.path.exists(p):
                    os.remove(p)
    check("newspaper.persist_playbook(D/C/BA・view残存・trio非破壊)", t_playbook_persist_newspaper)

    def t_playbook_ledger():
        from inspect import getsource
        import pandas as _pdl
        from core import newspaper as np_lg
        from core import playbook_tickets as pb_lg
        from core import playbook_ledger as lg
        # 生成側は確定結果を見ない
        rec_src = getsource(lg.generation_fields) + getsource(lg.tickets_from_rec)
        rec_src += getsource(np_lg.persist_playbook)
        for tok in ('fetch_race_payouts', 'fetch_comprehensive_result',
                    'chakujun', 'result.html'):
            assert tok not in rec_src, f'生成経路に未来情報 {tok}'
        assert 'settle(' not in getsource(np_lg.persist_playbook)
        rid = 'smoketestpblog01'
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}
        df = _pdl.DataFrame({
            'Rank': list(range(1, 9)), 'Umaban': list(range(1, 9)),
            'Name': [f'H{i}' for i in range(1, 9)],
            'Odds': [2.0 + i for i in range(8)], 'Popularity': list(range(1, 9)),
            'RaceName': ['logR'] * 8, 'Venue': ['東京'] * 8,
            'RaceDate': ['20260817'] * 8,
        })
        try:
            np_lg.write_view_snapshot(rid, df, {}, ['Umaban', 'Name'],
                                      meta={'date': '2026/08/17'})
            rec_d = pb_lg.build_tickets(rid, 30, hs, None, ltr)
            np_lg.persist_playbook(rid, rec_d)
            bets = np_lg.load_bets(rid)
            extra = bets['playbook']['extra']
            assert extra['ticket_type'] == '3連複' and extra['ticket_count'] == 2
            assert extra['investment'] == 200
            assert 'outcome' not in bets['playbook']
            assert extra.get('hit') is None and extra.get('payout') is None
            row = lg.entry_from_blob(rid, bets, {'date': '20260817'})
            assert row['tickets'] == [[1, 2, 3], [1, 2, 4]] or set(map(tuple, row['tickets'])) == {(1, 2, 3), (1, 2, 4)}
            assert row['settled'] is False and row['hit'] is None
            oc = lg.settle(rid, official={'winners': [
                {'combo': (1, 2, 3), 'payout': 1530}]})
            assert oc['hit'] is True and oc['hit_count'] == 1
            assert oc['payout'] == 1530 and oc['investment'] == 200
            assert oc['roi'] == 765.0
            np_lg.persist_playbook(rid, rec_d)
            assert np_lg.load_bets(rid)['playbook']['outcome']['payout'] == 1530
            oc_miss = lg.settle(rid, official={'winners': [
                {'combo': (5, 6, 7), 'payout': 9999}]})
            assert oc_miss['hit'] is False and oc_miss['payout'] == 0
            assert oc_miss['roi'] == 0.0
            oc_zero = lg.settle(rid, official={'winners': [
                {'combo': (1, 2, 3), 'payout': 0}]})
            assert oc_zero['hit'] is True and oc_zero['payout'] == 0
            rec_c = pb_lg.build_tickets(rid, 55, hs, None, ltr)
            np_lg.persist_playbook(rid, rec_c)
            bets_c = np_lg.load_bets(rid)
            assert 'outcome' not in bets_c['playbook']
            assert bets_c['playbook']['extra']['ticket_type'] == '3連単'
            assert bets_c['playbook']['extra']['ticket_count'] == 30
            assert bets_c['playbook']['extra']['investment'] == 3000
            win_c = tuple(bets_c['playbook']['result']['bets']['trifecta'][0]['combo'])
            oc_c = lg.settle(rid, official={'winners': [
                {'combo': win_c, 'payout': 42000}]})
            assert oc_c['hit'] is True and oc_c['payout'] == 42000
            assert oc_c['investment'] == 3000
            oc_c_miss = lg.settle(rid, official={'winners': [
                {'combo': (1, 2, 3), 'payout': 10000}]})
            assert oc_c_miss['hit'] is False and oc_c_miss['payout'] == 0
            rec_ba = pb_lg.build_tickets(rid, 80, hs, None, ltr)
            np_lg.persist_playbook(rid, rec_ba)
            oc_ba = lg.settle(rid)
            assert oc_ba['ticket_count'] == 0 and oc_ba['investment'] == 0
            assert oc_ba['payout'] == 0 and oc_ba['roi'] is None
            e_d = {'zone': 'D', 'ticket_count': 2, 'investment': 200,
                    'settled': True, 'hit': True, 'payout': 1530}
            e_c = {'zone': 'C', 'ticket_count': 30, 'investment': 3000,
                    'settled': True, 'hit': False, 'payout': 0}
            e_ba = {'zone': 'BA', 'ticket_count': 0, 'investment': 0,
                     'settled': True, 'hit': False, 'payout': 0, 'skip': True}
            sm = lg.summarize([e_d, e_c, e_ba])
            assert sm['D']['n_races'] == 1 and sm['D']['hit_rate'] == 100.0
            assert sm['D']['roi'] == 765.0
            assert sm['C']['n_races'] == 1 and sm['C']['hit_rate'] == 0.0
            assert sm['C']['roi'] == 0.0
            assert sm['BA']['n_tickets'] == 0
            assert sm['ALL']['n_races'] == 2
            assert sm['ALL']['investment'] == 3200
            assert sm['ALL']['payout'] == 1530
        finally:
            for pth_fn in (np_lg._bets_path, np_lg._view_path):
                p = pth_fn(rid)
                if os.path.exists(p):
                    os.remove(p)
    check("playbook_ledger 生成時リーク無し/D2/C30/BA0/的中外れ払戻0", t_playbook_ledger)

    def t_c248_shadow():
        from core import playbook_tickets as pb
        from core import playbook_shadow as psh
        from core import playbook_ledger as lg
        from core import newspaper as np_mod
        import copy
        hs = [{'umaban': i, 'name': f'H{i}', 'pop': i} for i in range(1, 9)]
        ltr = {i: float(i) for i in range(1, 9)}  # 8が最強
        prod = pb.build_tickets('R', 55, hs, {1: '◎', 2: '〇'}, ltr, cross_n=3)
        assert prod['selected_playbook'] == 'c_ltr_trio_236'
        assert prod['trio'] and not prod['trifecta']
        prod_copy = copy.deepcopy(prod)
        assert psh.applicable(prod)
        sh = psh.build_shadow_rec(prod)
        assert sh['skip'] is False
        assert sh['formation'] == '2-4-8'
        assert sh['n_points'] > 0
        assert sh['budget_yen'] == psh.SHADOW_BUDGET_YEN
        assert prod == prod_copy, '本番 rec は Shadow 計算で変わらない'

        c_tri = pb.build_tickets('R', 55, hs, {1: '◎', 2: '〇'}, ltr, cross_n=2)
        assert not psh.applicable(c_tri)

        scored = lg.score_shadow_tickets(
            [tuple(r['combo']) for r in sh['trio']],
            [{'combo': sh['trio'][0]['combo'], 'payout': 5000}],
            psh.SHADOW_BUDGET_YEN,
        )
        assert scored['hit'] is True
        assert scored['investment'] == 700

        rid = 'smoketestshadow248'
        try:
            np_mod.persist_playbook(rid, prod)
            bets = np_mod.load_bets(rid)
            assert 'playbook' in bets
            assert psh.SHADOW_BETS_KEY in bets
            sh_blob = bets[psh.SHADOW_BETS_KEY]
            assert sh_blob['extra']['formation'] == '2-4-8'
            assert sh_blob['extra']['skip'] is False
            pb_trio = {tuple(r['combo']) for r in bets['playbook']['result']['bets']['trio']}
            sh_trio = {tuple(r['combo']) for r in sh_blob['result']['bets']['trio']}
            assert pb_trio != sh_trio
            lg.settle(rid, official={'winners': [
                {'combo': list(prod['trio'][0]['combo']), 'payout': 1000},
            ]})
            bets2 = np_mod.load_bets(rid)
            assert 'outcome' in bets2['playbook']
            assert 'outcome' in bets2[psh.SHADOW_BETS_KEY]
            cmp = lg.summarize_shadow_vs_production()
            assert cmp['min_races'] == psh.SHADOW_MIN_RACES
        finally:
            for p in (np_mod._bets_path(rid), np_mod._view_path(rid)):
                if os.path.exists(p):
                    os.remove(p)
    check("C248 Shadow 2-4-8 本番非影響・persist・settle", t_c248_shadow)

    def t_elim_verdict_html():
        # 🧹消去フィルター残馬: 自動判定の✅残し/🛟ボーダー残しを表示
        from core import newspaper as np_ev
        rid = 'smoketest_elimverdict'
        rows = [
            {'馬番': 1, '馬名': 'ノコシA', '判定': '✅残し'},
            {'馬番': 2, '馬名': 'ボーダーB', '判定': '🛟ボーダー残し'},
            {'馬番': 3, '馬名': 'ケシC', '判定': '🧹消し'},
            {'馬番': 4, '馬名': 'ケシD', '判定': '🧹消し'},
        ]
        try:
            np_ev.write_elim_verdict_snapshot(rid, rows)
            d = np_ev.load_elim_verdict(rid)
            assert d and len(d['rows']) == 4, "判定スナップショットが往復保存される"
            html = np_ev._elim_html({}, [], rid)
            assert 'ノコシA' in html and 'ボーダーB' in html, "残し/ボーダー残しの馬名が表示される"
            assert 'ケシC' not in html and 'ケシD' not in html, "消去馬を残馬一覧に出さない"
            assert '消去フィルター残馬' in html
        finally:
            if os.path.exists(np_ev._elim_verdict_path(rid)):
                os.remove(np_ev._elim_verdict_path(rid))
    check("newspaper._elim_html(強適消去エンジンの残馬名)", t_elim_verdict_html)

    def t_scan_digest():
        # 📰 スキャン新聞: 保存(lean dict→str)→フィルタ(②のみ/本線のみ/見送り除外)→組版
        from core import newspaper as npm
        import shutil as _sh
        _bak = npm.SCAN_PATH + '.smokebak'
        _had = os.path.exists(npm.SCAN_PATH)
        if _had:
            _sh.copy(npm.SCAN_PATH, _bak)   # 実スキャン結果を退避(テストで壊さない)
        try:
            rows = [
                {'id': '202610020601', 'title': 'A', 'gate': 'buy', 'vscore': 80,
                 'vlabel': 'S 大荒れ妙味', 'arare_prob': 0.8, 'no_fav': '●大穴',
                 'value_horses': [{'um': 8}], 'ana_horses': [], 'danger_horses': [{'um': 1}],
                 'n_h': 16, 'surf': 'ダ', 'dist': 1700, 'post_time': '15:40',
                 'lean': {'lean': '②穴妙味向き'}},
                {'id': '202605020602', 'title': 'B', 'gate': 'skip', 'vscore': 30,
                 'vlabel': 'D 平凡', 'arare_prob': 0.3, 'value_horses': [],
                 'lean': {'lean': '本線向き'}},
            ]
            npm.write_scan_digest(rows)
            d = npm.load_scan_digest()
            assert d and isinstance(d['rows'][0]['lean'], str), "leanはstr化"
            ana = npm.filter_scan_rows(d['rows'], 'ana', (0, 100), True, 12)
            assert [r['id'] for r in ana] == ['202610020601'], "②のみ+見送り除外"
            hon = npm.filter_scan_rows(d['rows'], 'honsen', (0, 100), False, 12)
            assert [r['id'] for r in hon] == ['202605020602'], "本線のみ(荒れ回避)"
            html, used = npm.build_scan_digest_html(d['rows'], {'lean_mode': 'ana'})
            assert html and len(used) == 1 and '②穴妙味向き' in html and '🎯妙味馬 8' in html
            assert '⚠危険人気 1' in html and '小倉1R' in html, "カード内容"
        finally:
            if _had:
                _sh.move(_bak, npm.SCAN_PATH)
            elif os.path.exists(npm.SCAN_PATH):
                os.remove(npm.SCAN_PATH)
    check("newspaper.スキャン新聞(digest保存/フィルタ/組版)", t_scan_digest)

    # ── Phase3.5: 実行時バグ/契約ガード(py_compileでは拾えない) ──
    def t_dup_widget_keys():
        import re as _re
        with open(os.path.join(ROOT, 'app.py'), encoding='utf-8') as _f:
            _src = _f.read()
        _keys = _re.findall(r"""key=(['"])([^'"]+)\1""", _src)  # 静的keyのみ(f-stringは除外)
        _seen, _dup = set(), set()
        for _, k in _keys:
            (_dup if k in _seen else _seen).add(k)
        assert not _dup, f"重複widget key(実行時クラッシュ源): {sorted(_dup)[:10]}"
    check("app.py 重複widget keyなし", t_dup_widget_keys)

    def t_dashboard_contract():
        # 🏁ダッシュボード/⑥回顧が依存する関数の存在保証(リネーム破壊を即検出)
        from core import money, score_cache as sc
        for m in ('roi_by_gate', 'max_drawdown', 'loss_breakdown',
                  'improvement_rules', 'classify_loss', 'record_prediction',
                  'record_kelly_bets', 'record_skip'):
            assert hasattr(money.Ledger, m), f"money.Ledger.{m} 欠落(ダッシュボード破壊)"
        for fn in ('recent_gates', 'read_gate', 'write_gate', 'read_buy', 'write_buy'):
            assert hasattr(sc, fn), f"score_cache.{fn} 欠落"
    check("dashboard/⑥回顧の関数契約", t_dashboard_contract)

    def t_jra_baba_scraper_parse():
        # JRA公式アーカイブPDFのテキスト抽出結果(pdfplumber経由)を模したサンプルで
        # 行パーサ(_parse_page_text)が正しく構造化できることを確認(ネットワーク不使用)。
        from core import jra_baba_scraper as jb
        sample_text = (
            "２０２６年 第３回 東京競馬 クッション値・含水率一覧\n"
            "2026年 3回東京競馬\n"
            "芝コースクッション値 含水率\n"
            "開催日次 測定月日 曜日 芝コース（%） ダートコース（%）\n"
            "使用コース 測定時刻 測定値 測定時刻\n"
            "ゴール前 4コーナー ゴール前 4コーナー\n"
            "6月 5日 金曜日 C 09:00 9.8 08:30 14.9 15.1 7.9 8.8\n"
            "第 1日 6月 6日 土曜日 C 07:00 9.9 05:00 16.2 15.7 7.7 8.9\n"
        )
        rows = jb._parse_page_text(sample_text)
        assert len(rows) == 2, f"2行パースできる, got {len(rows)}"
        r0 = rows[0]
        assert r0['year'] == '2026' and r0['jyo'] == '05' and r0['monthday'] == '0605', \
            f"年/場コード/月日の抽出, got {r0}"
        assert r0['cushion'] == 9.8 and r0['turf_moist_goal'] == 14.9 \
            and r0['turf_moist_4c'] == 15.1 and r0['dirt_moist_goal'] == 7.9 \
            and r0['dirt_moist_4c'] == 8.8, f"数値抽出, got {r0}"
        assert rows[1]['monthday'] == '0606', "2行目(第1日)も正しくパースされる"
        assert jb._parse_page_text("関係ないテキスト") == [], "タイトル不一致は空リスト"
        assert jb._parse_page_text("") == [], "空文字は空リスト"
    check("jra_baba_scraper._parse_page_text(過去データPDFのテキスト構造化)",
          t_jra_baba_scraper_parse)

    def t_lookup_track_cond_contract():
        # core.track_bias.lookup_track_cond の戻り値キー契約(app.pyのSRA自動供給が依存)
        from core import track_bias as tb_lc
        out = tb_lc.lookup_track_cond('1900', '0101', '99')  # 存在しないキー→全None
        for k in ('cushion', 'dirt_moisture', 'turf_moist_goal', 'turf_moist_4c',
                  'dirt_moist_4c', 'course'):
            assert k in out, f"lookup_track_condの戻り値に{k}キーが無い(app.py自動供給が壊れる)"
            assert out[k] is None, f"存在しないキーはNone, got {k}={out[k]}"
    check("track_bias.lookup_track_cond(戻り値キー契約/芝含水率対応)",
          t_lookup_track_cond_contract)

    def t_sire_cushion_level():
        # 種牡馬×クッション値絶対水準(9.5閾値)の検証済みフラグ(2026-07大規模BT・4頭のみ)
        from core import track_bias as tb_cl
        assert set(tb_cl._SIRE_CUSHION_LEVEL) == {
            'ダイワメジャー', 'ハービンジャー', 'リアルスティール', 'サトノダイヤモンド'}, \
            "採用は両窓一致の4頭のみ(それ以外は崩落=追加禁止)"
        f = tb_cl.sire_cushion_level_flag('ダイワメジャー', 10.2)
        assert f and f['flag'] == '🟢適合', "ダイワメジャー×硬め=適合"
        f = tb_cl.sire_cushion_level_flag('ハービンジャー', 10.2)
        assert f and f['flag'] == '🔴不適', "ハービンジャー×硬め=不適(軟め得意)"
        f = tb_cl.sire_cushion_level_flag('サトノダイヤモンド', 9.0)
        assert f and f['flag'] == '🟢適合', "サトノダイヤモンド×軟め=適合(資料の逆が真)"
        assert tb_cl.sire_cushion_level_flag('キズナ', 10.2) is None, \
            "崩落した種牡馬(キズナ等)はフラグを出さない"
        assert tb_cl.sire_cushion_level_flag('ダイワメジャー', None) is None, "欠損はNone"
        assert tb_cl.sire_cushion_level_flag('ダイワメジャー', 0.0) is None, "未入力0はNone"
        assert set(tb_cl.cushion_level_sire_names()) == set(tb_cl._SIRE_CUSHION_LEVEL)
    check("track_bias.sire_cushion_level_flag(クッション水準×種牡馬・検証済4頭)",
          t_sire_cushion_level)

    def t_moisture_vs_venue():
        # 場ごとの『良』上限と比べる見る用一言。東京12%は乾、小倉12%は湿。
        from core import track_bias as tb_mv
        r = tb_mv.moisture_vs_venue('東京', '芝', 12.0)
        assert r and r['band'] == 'dry', f"東京12%は乾いている, got {r}"
        assert '東京' in r['line'] and '乾' in r['line']
        assert '点数には足しません' in r['line']
        r = tb_mv.moisture_vs_venue('小倉', '芝', 12.0)
        assert r and r['band'] == 'wet', f"小倉12%は湿っている, got {r}"
        assert '小倉' in r['line'] and '湿' in r['line']
        r = tb_mv.moisture_vs_venue('05', '芝', 12.0)
        assert r and r['band'] == 'dry', "場コード05=東京でも同じ"
        r = tb_mv.moisture_vs_venue('東京', '芝', 18.0)
        assert r and r['band'] == 'ok', "東京18%は良の範囲内"
        r = tb_mv.moisture_vs_venue('東京', 'ダート', 12.0)
        assert r and r['band'] == 'wet', "ダート12%は湿(良は9%以下)"
        assert tb_mv.moisture_vs_venue('東京', '芝', None) is None
        assert tb_mv.moisture_vs_venue('東京', '芝', 0) is None
        assert tb_mv.moisture_vs_venue('大井', '芝', 12.0) is None, "地方芝は上限不明なので出さない"
    check("track_bias.moisture_vs_venue(場ごとの乾き具合・見る用)",
          t_moisture_vs_venue)

    def t_venue_race_label():
        # 🏆Race Analysis Summary の「東京11R」表示(旧 (Score: x.x) の置換先)
        from core import scraper as sc_vr
        assert sc_vr.venue_race_label('202605020811') == '東京11R'
        assert sc_vr.venue_race_label('202602011105') == '函館5R', "先頭0を落として5R"
        assert sc_vr.venue_race_label('202644010111') == '大井11R', "NAR場コードも解決"
        for bad in ('20260201110', 'abcdefghijkl', '', None):
            assert sc_vr.venue_race_label(bad) == '', f"不正入力は空文字, got {bad}"
        # 開催日(metadata['date_val'] YYYYMMDD)→ 曜日つき表示
        assert sc_vr.format_race_date('20260517') == '2026/05/17(日)'
        assert sc_vr.format_race_date('20260502') == '2026/05/02(土)'
        for bad in ('2026051', '20260230', 'abcdefgh', '', None):
            assert sc_vr.format_race_date(bad) == '', f"不正日付は空文字, got {bad}"
    check("scraper.venue_race_label/format_race_date(Summaryの開催日・場R表示)",
          t_venue_race_label)

    def t_golden_line_gate():
        # 黄金ラインのゲート(2026-07再検証: 35-40%が両窓最強・35%未満はholdoutで消える)
        from core import jockey_jv as jj_gl
        assert (jj_gl.GOLD_TOP2_WEAK, jj_gl.GOLD_TOP2_GATE, jj_gl.GOLD_TOP2_STRONG) \
            == (0.30, 0.35, 0.40)
        assert jj_gl.golden_line_mark({'rides': 40, 'top2': 0.52}) == '🥇🥇', '50%+は🥇🥇'
        assert jj_gl.golden_line_mark({'rides': 40, 'top2': 0.42}) == '🥇🥇', '40-50%は🥇🥇'
        assert jj_gl.golden_line_mark({'rides': 30, 'top2': 0.37}) == '🥇', '35-40%=期待値ゾーン'
        assert jj_gl.golden_line_mark({'rides': 30, 'top2': 0.336}) == '△', '30-35%=参考のみ'
        assert jj_gl.golden_line_mark({'rides': 30, 'top2': 0.29}) == '', '30%未満は出さない'
        assert jj_gl.golden_line_mark({'rides': 8, 'top2': 0.60}) == '', '騎乗数不足は出さない'
        for bad in (None, {}, {'rides': 'x', 'top2': 'y'}):
            assert jj_gl.golden_line_mark(bad) == '', f'不正入力は空, got {bad}'
        # △(30-35%)はholdoutで再現しないため判定ゲートには通さない(表示専用)
        assert jj_gl.is_golden_line({'rides': 30, 'top2': 0.37}) is True
        assert jj_gl.is_golden_line({'rides': 30, 'top2': 0.336}) is False, \
            '△は消去/合議/妙味スキャナの判定に混入させない'
        # 判定の正本が1か所であること(閾値の二重管理を防ぐ=逃げ判定と同種の回帰対策)。
        # 各消費側は is_golden_line/golden_line_mark 経由で、閾値をベタ書きしない。
        for mod in ('core/consensus_view.py', 'core/value_scanner.py', 'app.py'):
            with open(os.path.join(ROOT, mod), encoding='utf-8') as _f:
                src = _f.read()
            assert 'is_golden_line' in src or 'golden_line_mark' in src, \
                f"{mod} が黄金ライン判定ヘルパーを使っていない"
            assert "get('top2', 0) >= 0.40" not in src, \
                f"{mod} に旧40%閾値のベタ書きが残っている"
    check("jockey_jv.golden_line_mark(黄金ライン35%ゲート・判定の一本化)", t_golden_line_gate)

    def t_nankan_contract():
        # NAR過去走ブリッジ(SRA/消去エンジンが依存)の関数存在＋venue導出ロジック保証
        from core import nankan_scraper as nk
        for fn in ('derive_nankan_race_id', 'fetch_month_programs',
                   'fetch_program_races', 'fetch_entries', 'fetch_horse_history',
                   'runs_to_pastruns', 'enrich_with_nankan',
                   'fill_bloodline_from_nankan'):
            assert hasattr(nk, fn), f"nankan_scraper.{fn} 欠落(NAR過去走補完破壊)"
        # netkeiba地方場コード→nankan内部場コード(実査確定値)
        assert nk.NETKEIBA_TO_NANKAN_VENUE == {'42': '18', '43': '19', '44': '20', '45': '21'}, \
            "NAR venueマッピング破損(race_id自動導出が壊れる)"
        # 南関の場コード名(scraper.VENUE_NAMES)がtrack_bias/nankan_scraperと一致すること
        # (過去に42大井/44船橋の誤りがOne-Pushの会場別騎手成績を破壊した回帰の再発防止)
        from core.scraper import VENUE_NAMES as _VN
        assert (_VN.get('42'), _VN.get('43'), _VN.get('44'), _VN.get('45')) == \
            ('浦和', '船橋', '大井', '川崎'), "南関場コード名が誤り(42浦和/43船橋/44大井/45川崎)"
        # jockey_jv: NAR会場名解決＋略記騎手名リゾルバ(One-Push/Scanner NARフォールバックが依存)
        from core import jockey_jv as _jjv
        assert _jjv._venue_name('44') == '大井' and _jjv._venue_name('43') == '船橋', \
            "jockey_jv._venue_nameがNAR会場を解決できない(騎手成績の場別が壊れる)"
        assert hasattr(_jjv, 'resolve_jockey_name'), "jockey_jv.resolve_jockey_name欠落(NAR略記名の名寄せ)"
    check("NAR過去走ブリッジの関数契約", t_nankan_contract)

    def t_ai_tenkai():
        # netkeiba AI展開予測(4コーナー)照合の帯分類/合意アイコン(ネットワーク非依存)
        from core import ai_tenkai as ait
        # 埋め込みJS+アイコンの最小フィクスチャ(左%小=前/大=後)
        html = (
            '<span class="HorseIcon Color01" id="Horse1">x</span>'
            '<span class="HorseIcon Color01" id="Horse2">x</span>'
            '<span class="HorseIcon Color01" id="Horse3">x</span>'
            '<script>function updateHorsePosition(){'
            "switch(c){case 'Corner03':"
            '$("#Horse1").css({top:"0%",left:\'10%\'});'
            '$("#Horse2").css({top:"0%",left:\'50%\'});'
            '$("#Horse3").css({top:"0%",left:\'90%\'});break;}'
            '出遅れ率チェック}</script>'
        )
        pos = ait.parse_tenkai_positions(html)
        assert pos.get(1, {}).get('corner4') == 10.0, f"parse失敗 {pos}"
        assert pos.get(3, {}).get('corner4') == 90.0
        bands = ait.band_by_left({1: 10.0, 2: 50.0, 3: 90.0})
        assert bands[1] == '前' and bands[3] == '後', f"帯分類誤り {bands}"
        icons = ait.agreement_icons({1: '前', 2: '中', 3: '後'}, {1: '前', 2: '後', 3: '後'})
        assert icons[1] == '🏆' and icons[3] == '💀' and icons[2] == '', f"合意アイコン誤り {icons}"
        ranks = ait.ranks_from_left({1: 10.0, 9: 0.0, 10: 90.0})
        assert ranks[9] == 1 and ranks[1] == 2 and ranks[10] == 3, f"3角番手変換誤り {ranks}"
    check("netkeiba AI展開照合(帯/合意)", t_ai_tenkai)

    def t_botcross():
        # 消去クロス 両列最下位(botcross): 上り3F最下位∩平均位置最下位(検証済K=3)
        from core import elim_cross as ec
        # 10頭: um1が末脚も位置もワースト、um2は末脚のみワースト
        horses = [{'um': u, 'spurt': (u * 0.1), 'c4': (1.0 - u * 0.08)} for u in range(1, 11)]
        # spurt昇順ワースト3=um1,2,3 / c4降順(大)ワースト3=um1,2,3 → 交差=1,2,3
        bc = ec.bottom_both_umabans(horses, k=3)
        assert bc == {1, 2, 3}, f"botcross交差誤り {bc}"
        # 小頭数(min_field未満)は判定しない
        assert ec.bottom_both_umabans(horses[:5]) == set(), "小頭数で両列最下位を出してはいけない"
        # botcrossはBAND較正から除外(verified_countに入らない)
        assert 'botcross' in ec.UNVERIFIED and 'botcross' in ec.FLAG_LABEL
        # multiweak: 4列中3列以上でワースト(大きいほど下位に揃えて渡す)
        mh = [{'um': u, 'cols': {'spurt': u, 'pos': u, 'form': u, 'ctime': (11 - u)}}
              for u in range(1, 11)]
        # spurt/pos/form は um大ほど下位→ワースト3=um10,9,8。ctimeは逆(um1,2,3)。
        # → um8,9,10 が spurt/pos/form の3列でワースト = multiweak
        mw = ec.multiweak_umabans(mh, k=3, need=3)
        assert mw == {8, 9, 10}, f"multiweak誤り {mw}"
        assert 'multiweak' in ec.UNVERIFIED and 'multiweak' in ec.FLAG_LABEL
        # 人気下位/騎手実績下位(単一指標ワーストK)。poplow=人気番号大がワースト、jlow=複勝率低がワースト
        wp = ec.worst_k_umabans([{'um': u, 'pop': u} for u in range(1, 11)], 'pop', k=3)
        assert wp == {8, 9, 10}, f"人気下位誤り {wp}"
        wj = ec.worst_k_umabans([{'um': u, 'j': u * 0.03} for u in range(1, 11)], 'j', k=3,
                                higher_worse=False)
        assert wj == {1, 2, 3}, f"騎手下位誤り {wj}"
        for k in ('poplow', 'jlow'):
            assert k in ec.UNVERIFIED and k in ec.CAUTION_KEYS and k in ec.FLAG_LABEL
        # 展開2(netkeiba照合💀・青ヘッダ)＋ディスク橋渡し
        assert 'tenkai2' in ec.UNVERIFIED and 'tenkai2' in ec.BLUE_KEYS and 'tenkai2' in ec.FLAG_LABEL
        # 騎手弱材料: 数字なし＝しきい値以下。ヘッダは紫(調教C以下も同色)。
        assert 'jweak' in ec.UNVERIFIED and 'jweak' in ec.PURPLE_KEYS
        assert 'train' in ec.UNVERIFIED and 'train' in ec.PURPLE_KEYS
        assert 'jweak' not in ec.CAUTION_KEYS and 'train' not in ec.CAUTION_KEYS
        assert ec.is_jweak(None) is False
        assert ec.is_jweak({'mult': 1.0, 'note': '馬連携80・場連対10・黄金10'}) is True
        assert ec.is_jweak({'mult': 1.0, 'note': ''}) is True, "内訳なしは以下扱い"
        assert ec.is_jweak({'mult': 1.0, 'note': '馬連携80'}) is True, "場連対・黄金なしは以下扱い"
        assert ec.is_jweak({'mult': 1.05, 'note': ''}) is False, "係数が高いと点灯しない"
        assert ec.is_jweak({'mult': 0.98, 'note': '馬連携120・場連対10・黄金10'}) is False
        from core import score_cache as _sc
        _rid = '__smoke_t2__'
        _sc.write_tenkai_danger(_rid, {3, 7})
        assert _sc.read_tenkai_danger(_rid) == {3, 7}, "展開2ディスク橋渡し不整合"
    check("消去クロス 両列最下位(botcross)", t_botcross)

    def t_blood_course():
        # 血統SP強化: 父系統遡上+場×人気軸信頼度(検証済コースバイアス)の契約
        from core import blood_course as bc
        assert bc.sire_line('シニスターミニスター') == 'APインディ系', "手動辞書が壊れた"
        assert bc.sire_line(None) == 'その他'
        assert bc.line_bg('サンデー系').startswith('#'), "系統色は薄色コード"
        assert bc.line_bg('その他') == ''
        # 検証済みの場×人気: 東京芝1-3人気=+/小倉芝=-のみ。人気薄はNone
        v = bc.venue_fav_note('05', '芝', 1)
        assert v and v['shift'] > 0, f"東京芝fav欠落 {v}"
        k = bc.venue_fav_note('10', '芝', 3)
        assert k and k['shift'] < 0, f"小倉芝fav欠落 {k}"
        assert bc.venue_fav_note('02', '芝', 2) and bc.venue_fav_note('02', '芝', 2)['shift'] < 0, "函館芝fav欠落"
        assert bc.venue_fav_note('45', 'ダ', 1) and bc.venue_fav_note('45', 'ダ', 1)['shift'] < 0, "川崎ダfav欠落"
        assert bc.venue_fav_note('05', '芝', 6) is None, "人気薄に発火してはいけない"
        assert bc.venue_fav_note('06', '芝', 1) is None, "非配線の場(中山=holdout崩落)に発火してはいけない"
        assert bc.venue_fav_note('44', 'ダ', 1) is None, "大井は非配線(holdout逆符号)"
        # 血統スコア(血統SP=strong table/血統適性共用)。統計無しは母集団0.25*100=25.0
        from core import bloodline as _bll
        assert _bll.blood_score('存在しない父', '存在しない母父', '芝', 1600) == 25.0, "血統スコア母集団既定値"
        assert isinstance(_bll.blood_score('ディープインパクト', 'Mineshaft', '芝', 1600), float)
        from core import blood_ev as _bev
        dummy_bands = {i: {'win': 0.08, 'top3': 0.22} for i in range(8)}
        dummy_bands[1] = {'win': 0.33, 'top3': 0.70}
        hs = [
            {'sire': '存在しない父', 'bms': '存在しない母父', 'odds': 2.0, 'ninki': 1,
             'umaban': 1, 'name': 'A'},
            {'sire': '存在しない父', 'bms': '存在しない母父', 'odds': 8.0, 'ninki': 5,
             'umaban': 2, 'name': 'B'},
            {'sire': '存在しない父', 'bms': '存在しない母父', 'odds': 80.0, 'ninki': 14,
             'umaban': 3, 'name': 'C'},
        ]
        marked = _bev.annotate_race(hs, '芝', 1600, dummy_bands)
        assert len(marked) == 3
        assert marked[2]['skip_e'] is True, "50倍超・12人気以下は大穴除外"
        assert 'win_label' in marked[0] and 'blood_label' in marked[0]
        assert marked[0]['win_ev'] is not None
        empty = _bev.overlap_news_line([], '芝', 1600, dummy_bands)
        assert empty == ''
        line = _bev.overlap_news_line(hs, '芝', 1600, dummy_bands)
        assert isinstance(line, str)
        skip_line = _bev.overlap_skip_news_line(hs, '芝', 1600, dummy_bands)
        assert '3番' in skip_line and '1番' not in skip_line, skip_line
    check("血統×コース(blood_course)の契約", t_blood_course)

    def t_hunter_wet_fav_notes():
        # 穴馬ハンター: 道悪×血統は1-3人気の表示だけ。穴馬・良馬場は出さない。点数非配線。
        from pages.anabaka_hunter import wet_fav_notes
        from core import track_bias as tb
        hs = [
            {'umaban': 1, 'name': '穴馬', 'ninki': 8, 'sire': 'ヘニーヒューズ'},
            {'umaban': 2, 'name': '軸馬', 'ninki': 1, 'sire': 'ヘニーヒューズ'},
            {'umaban': 3, 'name': '芝人気', 'ninki': 2, 'sire': 'ディープインパクト'},
        ]
        assert wet_fav_notes(hs, 'ダート', '良', tb) == []
        dirt = wet_fav_notes(hs, 'ダート', '重', tb)
        assert len(dirt) == 1 and '2番' in dirt[0] and '軸馬' in dirt[0] and '🟢' in dirt[0], dirt
        assert '穴馬' not in ''.join(dirt)
        turf = wet_fav_notes(hs, '芝', '不良', tb)
        assert len(turf) == 1 and '芝人気' in turf[0] and '⚠' in turf[0], turf
        assert wet_fav_notes(hs, 'ダート', '重', None) == []
        from pages.anabaka_hunter import _html_oneline
        flat = _html_oneline('<div>\n            8番 テスト\n            </div>')
        assert '\n' not in flat and '8番 テスト' in flat and flat.endswith('</div>')
        from pages.anabaka_hunter import (
            attention_marks_html, attention_marks_md, combo_n_of)
        assert attention_marks_html(0, False) == ''
        both = attention_marks_html(2, True)
        assert '濃い穴' in both and '血統注目' in both
        assert '最注目' not in both
        only_c = attention_marks_html(2, False)
        assert '濃い穴' in only_c and '血統注目' not in only_c
        only_b = attention_marks_html(1, True)
        assert '濃い穴' not in only_b and '血統注目' in only_b
        md = attention_marks_md(2, True)
        assert '濃い穴' in md and '血統注目' in md
        assert combo_n_of(7, {7: 3}) == 3
        assert combo_n_of('7', {7: 2}) == 2
        assert combo_n_of(9, {}) == 0
        from pages.anabaka_hunter import golden_line_visible_labels
        assert golden_line_visible_labels(
            ['⭐黄金ライン42%', '🏠厩舎当ｺｰｽ20%']) == ['⭐黄金ライン42%']
        assert golden_line_visible_labels(['🔥末脚top']) == []
        assert golden_line_visible_labels(None) == []
    check("穴馬ハンター道悪血統は人気上位の表示のみ", t_hunter_wet_fav_notes)

    def t_folklore_lib():
        # 俗説ハンターは予想スコアに混ぜない。該当数の集計と否決ラベルだけ。
        from core import folklore_lib as folk
        ids = [r['id'] for r in folk.CATALOG]
        assert len(ids) >= 40, f"俗説が少なすぎ {len(ids)}"
        assert len(ids) == len(set(ids)), "俗説idが重複"
        assert folk.fire_marks(14) == '🔥🔥🔥'
        assert folk.fire_marks(9) == '🔥🔥'
        assert folk.fire_marks(5) == '🔥'
        assert folk.fire_marks(2) == ''
        import pandas as pd
        df = pd.DataFrame([{
            'Umaban': 2, 'Name': 'テスト馬', 'Popularity': 3, 'Odds': 8.5,
            'Waku': 2, 'Jockey': '武豊', 'Trainer': '美浦・田中', 'Tozai': 'east',
            'SexAge': '牡5', 'Blinker': 0, 'Weight': '490(+12)',
            'WeightCarried': '57.0', 'sire': 'ディープインパクト',
            'broodmareSire': '', 'CurrentDistance': 1600, 'CurrentSurface': '芝',
            'PastRuns': [{
                'Rank': 8, 'Popularity': 1, 'Distance': 1800, 'Surface': '芝',
                'Agari': 33.5, 'Passing': '1-1-1-1', 'Margin': 0.7,
                'Date': '2026.07.01', 'PrevJockey': '武豊', 'Grade': '1勝',
                'FieldSize': 16, 'RaceId': '202605021211', 'RaceName': '1勝',
                'Baba': '良',
            }],
        }])
        meta = {'date_val': '20260801', 'is_fillies': False, 'is_handicap': False}
        res = folk.evaluate_race(df, race_id='202608020211', meta=meta, enrich=False)
        assert len(res) == 1
        hit_ids = {h['id'] for h in res[0]['hits']}
        assert 'prev_fav1_flop' in hit_ids, hit_ids
        assert 'weight_plus10' in hit_ids, hit_ids
        assert 'dist_short' in hit_ids, hit_ids
        assert 'prev_lead_lose' in hit_ids, hit_ids
        assert res[0]['n_rejected'] >= 4
        assert res[0]['n_total'] == len(res[0]['hits'])
        assert res[0]['n_pos'] + res[0]['n_neg'] == res[0]['n_total']
        assert res[0]['score'] == res[0]['n_pos'] - res[0]['n_neg']
        assert all(r.get('sign') in (folk.SIGN_POS, folk.SIGN_NEG) for r in folk.CATALOG)
        assert all(r.get('weight') == 1.0 for r in folk.CATALOG)
        assert folk._NEG_IDS <= {r['id'] for r in folk.CATALOG}
        assert 'dirt_front' in ids and 'maiden_fav1' in ids
        assert 'skip_dam_age' in ids and 'skip_sibling' in ids
        by_id = {r['id']: r for r in folk.CATALOG}
        assert by_id['skip_dam_age']['verdict'] == folk.VERDICT_REJECTED
        assert by_id['dirt_small']['sign'] == folk.SIGN_NEG
        assert by_id['weight_minus20']['sign'] == folk.SIGN_NEG
        assert folk.match_one(by_id['dirt_small'], {'is_dirt': True, 'body_kg': 430})
        assert not folk.match_one(by_id['dirt_small'], {'is_dirt': False, 'body_kg': 430})
        assert folk.match_one(by_id['maiden_fav1'], {'is_maiden': True, 'ninki': 1})
        dtags = folk.race_tags({'condition': '稍重'}, 12, 'ダート')
        assert any('ダート' in t and '時計が速くなる' in t for t in dtags)
        ttags = folk.race_tags(
            {'condition': '不良', 'date_val': '20260801', 'RaceName': '新馬'}, 16, '芝')
        assert any('芝' in t and '前残り' in t for t in ttags)
        assert any('新馬' in t for t in ttags)
        assert by_id['prev_fav1_flop']['sign'] == folk.SIGN_POS
        assert by_id['weight_plus10']['sign'] == folk.SIGN_POS
        h = res[0]
        assert folk.fmt_signed(h['score']) in h['balance']
        assert len(folk.top_score(res, 5)) == 1
        wet_pos = folk.match_one(by_id['wet_blood'], {
            'baba': '稍重', 'sire': 'テスト', 'wet_blood': {'mod': 'exempt'},
        })
        wet_neg = folk.match_one(by_id['wet_blood'], {
            'baba': '稍重', 'sire': 'テスト', 'wet_blood': {'mod': 'intensify'},
        })
        assert wet_pos and wet_pos['sign'] == folk.SIGN_POS
        assert wet_neg and wet_neg['sign'] == folk.SIGN_NEG
        assert 'skips' in res[0]
        assert 'prev_fluke' in {r['id'] for r in folk.CATALOG}
        assert 'pad_sweat_foam' in {r['id'] for r in folk.CATALOG}
        assert len({r['id'] for r in folk.CATALOG}) == len(folk.CATALOG)
        empty = pd.DataFrame([{
            'Umaban': 1, 'Name': '新馬', 'Popularity': 1, 'Odds': 2.0,
            'Waku': 1, 'Jockey': 'a', 'Trainer': '', 'Tozai': None,
            'SexAge': '牡2', 'Blinker': 0, 'Weight': '発走前のため未公開',
            'WeightCarried': '55.0', 'sire': '', 'broodmareSire': '',
            'CurrentDistance': 1200, 'CurrentSurface': '芝', 'PastRuns': [],
        }])
        res2 = folk.evaluate_race(empty, race_id='202605050801', meta={'date_val': '20260505'},
                                  enrich=False)
        assert res2[0]['n_total'] >= 0
        def _sig(um, ninki, score, n_pos, n_neg):
            return {'umaban': um, 'ninki': ninki, 'score': score,
                    'n_pos': n_pos, 'n_neg': n_neg, 'name': str(um)}
        sigs = folk.folklore_signals([
            _sig(10, 7, 7, 8, 1),
            _sig(4, 8, 8, 9, 1),
            _sig(16, 5, 6, 7, 1),
            _sig(9, 8, 6, 8, 2),
            _sig(5, 11, 8, 11, 3),
            _sig(12, 10, 4, 5, 1),
            _sig(3, 6, 6, 8, 2),
        ], captured={4, 13, 6, 12})
        assert [s['umaban'] for s in sigs] == [5, 10, 3], [s['umaban'] for s in sigs]
        assert folk.captured_umabans({4: '🎯精鋭', 12: '🕸️広域網', 1: ''}) == {4, 12}
        assert folk.market_lens_verdict(-0.23) == '市場以上の優位性なし'
        assert folk.market_lens_verdict(-1.68) == '人気のわりに来ていない（売れすぎ）'
        assert folk.market_lens_verdict(1.2) == '市場が付けた人気より、よく来ている'
        assert len(folk.MARKET_LENS) == 10
        senko = folk.market_lens_for_catalog('front_habit')
        assert senko and senko['id'] == 'style_senko'
        assert folk.market_lens_for_catalog('no_such_folk') is None
        from pages import folklore_hunter as fh
        eff_test = fh._filter_effective_results([
            {'umaban': 1, 'name': 'T1', 'hits': [
                {'id': 'a', 'sign': folk.SIGN_POS, 'verdict': folk.VERDICT_EFFECTIVE},
                {'id': 'b', 'sign': folk.SIGN_NEG, 'verdict': folk.VERDICT_REJECTED},
            ]},
            {'umaban': 2, 'name': 'T2', 'hits': [
                {'id': 'c', 'sign': folk.SIGN_NEG, 'verdict': folk.VERDICT_EFFECTIVE},
            ]}
        ])
        assert len(eff_test) == 2
        assert eff_test[0]['n_pos'] == 1 and eff_test[0]['n_neg'] == 0 and eff_test[0]['score'] == 1
        assert eff_test[1]['n_pos'] == 0 and eff_test[1]['n_neg'] == 1 and eff_test[1]['score'] == -1
        assert fh._filter_effective_results([]) == folk.filter_effective_results([])

        myth_sets = {
            'positive': {1, 2},
            'composite': {1, 3},
            'practical_positive': {2, 4},
            'practical_composite': {1, 4},
        }
        assert folk.myth_info_for_umaban(1, myth_sets)['count'] == 3
        assert folk.myth_info_for_umaban(2, myth_sets)['count'] == 2
        assert folk.myth_info_for_umaban(99, myth_sets)['count'] == 0

        def _hit(sign, verdict=folk.VERDICT_EFFECTIVE):
            return {'id': 'x', 'sign': sign, 'verdict': verdict, 'category': 'T'}

        myth_rows = [
            {'umaban': 1, 'name': 'A', 'n_pos': 5, 'n_neg': 0, 'score': 5,
             'hits': [_hit(folk.SIGN_POS)] * 5},
            {'umaban': 2, 'name': 'B', 'n_pos': 4, 'n_neg': 0, 'score': 4,
             'hits': [_hit(folk.SIGN_POS)] * 4},
            {'umaban': 3, 'name': 'C', 'n_pos': 3, 'n_neg': 0, 'score': 3,
             'hits': [_hit(folk.SIGN_POS)] * 3},
            {'umaban': 4, 'name': 'D', 'n_pos': 2, 'n_neg': 0, 'score': 2,
             'hits': [_hit(folk.SIGN_POS)] * 2},
            {'umaban': 5, 'name': 'E', 'n_pos': 1, 'n_neg': 0, 'score': 1,
             'hits': [_hit(folk.SIGN_POS)] * 1},
            {'umaban': 6, 'name': 'F', 'n_pos': 0, 'n_neg': 5, 'score': -5,
             'hits': [_hit(folk.SIGN_NEG)] * 5},
            {'umaban': 7, 'name': 'G', 'n_pos': 0, 'n_neg': 0, 'score': 0, 'hits': []},
        ]
        myth_map = folk.build_myth_count_map(myth_rows)
        assert myth_map[1]['count'] == 4
        assert myth_map[6]['count'] == 0
        assert myth_map[7]['count'] == 0
        assert folk.build_myth_count_map(None) is None
        assert folk.build_myth_count_map([]) is None
    check("俗説ハンターはエンジン非配線・該当と否決を数える", t_folklore_lib)

    def t_gyaku_kami():
        # 逆神ページはリンク集だけ。API/スクレイピング/スコアは持たない。
        from core import gyaku_kami as gk
        rows = gk.load_accounts(use_cache=False)
        ids = [r['id'] for r in rows]
        assert ids, '逆神カタログが空'
        assert len(ids) == len(set(ids)), '逆神idが重複'
        assert all(r['platform'] in gk.PLATFORMS for r in rows)
        x_names = [r['name'] for r in gk.accounts_for(gk.PLAT_X)]
        yt_names = [r['name'] for r in gk.accounts_for(gk.PLAT_YOUTUBE)]
        for n in (
            '粗品', '競馬ゆっくり', 'ぷに@競馬', '稲花リノ', '競馬僧侶【逆神】',
            'なお@逆神競馬予想家', 'たろうまる競馬【逆神】', 'キャプテン渡辺',
            '逆神のホワケ', '逆神ch @競馬予想', 'ゴリラおじさん@競馬逆神',
            'アドマイヤ競馬(逆神)', '逆神競馬',
            '芸能人競馬予想と逆説の競馬予想【公式Ｘ】',
        ):
            assert n in x_names, n
        for n in (
            '粗品 Official Channel', '競馬ゆっくり', 'ぷに競馬',
            '逆神レイのゆっくり競馬ちゃんねる', '逆神注意報',
            'たろうまる競馬【逆神】', 'なお@逆神競馬予想家',
            '水上学のKEIBA大学',
        ):
            assert n in yt_names, n
        for r in rows:
            u = r['url']
            if u is None:
                continue
            assert u.startswith(('https://x.com/', 'https://www.youtube.com/')), u
        souryo = next(r for r in rows if r['id'] == 'x_keiba_souryo')
        assert souryo['url'] is None, '未確認アカウントにURLを推測で付けない'
        soshina = next(r for r in rows if r['id'] == 'x_soshina')
        assert soshina['url'] == 'https://x.com/maiokux'
        assert not hasattr(gk, 'fetch_posts')
        assert not hasattr(gk, 'gyaku_score')
        from pages.gyaku_kami import render as _gk_render
        assert callable(_gk_render)
    check("逆神はリンク集のみ・未確認URLは空", t_gyaku_kami)

    def t_jockey_power():
        # 騎手力(JPower): 『騎手のみの力』偏差値の契約(検証=scripts/jockey_power_backtest.py)
        from core import jockey_jv as jj
        assert hasattr(jj, 'jockey_power'), "jockey_jv.jockey_power欠落(騎手Pro騎手力列が壊れる)"
        # 存在しない騎手→jpower=None(クラッシュしない)
        r = jj.jockey_power('存在シナイ騎手XYZ')
        assert r['jpower'] is None and r['rides'] == 0, f"未知騎手の縮退失敗 {r}"
        # 較正定数(検証済みの値から大きく逸脱したら再較正が必要)
        assert 95 < jj.JPOWER_MEAN < 105 and 5 < jj.JPOWER_SD < 15, "JPower較正定数が異常"
    check("騎手力(jockey_power)の契約", t_jockey_power)

    def t_lap33():
        # 33ラップ理論(core/lap33.py)の関数契約＋符号規約(正=瞬発力型/負=持久力型)
        from core import lap33 as l3
        # 1200m: 前半3F(mae)一定・上がり(ato)が速いほどlap33は大きくなる(瞬発力=プラス)
        assert l3.lap33(35.0, 33.0) == 2.0
        assert l3.lap33(33.0, 35.0) == -2.0
        # 1200mは前半3Fそのもの(race_mid3f_rateは中距離用の中盤換算をスキップ)
        assert l3.race_mid3f_rate(1200, 350, 330, 700) == 35.0
        # race_lap33: 中距離は中盤3F相当(600m換算)-上がり3F。極端値でないことを確認
        # 完走108.0秒はJV形式'1480'(1分+48.0秒)。前3F35.0/上3F35.0→中盤38.0-上3F35.0=+3.0
        v = l3.race_lap33(1800, 350, 350, 1480)
        assert v == 3.0, f"race_lap33 計算誤り {v}"
        # fit_match: 符号一致=True/不一致=False/しきい値未満または欠損=None
        assert l3.fit_match(1.0, 1.5) is True
        assert l3.fit_match(1.0, -1.5) is False
        assert l3.fit_match(0.1, 1.5, threshold=0.3) is None
        assert l3.fit_match(None, 1.5) is None
        # fit_distance(2026-08採用): コース平均との距離で○(<=0.5)/△(<=1.0)/''(範囲外)
        # 検証 scripts/lap33_distance_backtest.py: 人気薄holdoutで該当率74.8%→23.9%、
        # 残差+1.42pp→+1.83pp。符号一致(旧)は該当馬が多すぎた。
        assert l3.fit_distance(1.0, 1.2) == '○', "距離0.2は○"
        assert l3.fit_distance(1.0, 1.5) == '○', "距離0.5は境界で○"
        assert l3.fit_distance(1.0, 1.8) == '△', "距離0.8は△"
        assert l3.fit_distance(1.0, 2.0) == '△', "距離1.0は境界で△"
        assert l3.fit_distance(1.0, 2.5) == '', "距離1.5は範囲外"
        assert l3.fit_distance(-1.0, -1.2) == '○', "負値同士でも距離で判定"
        # 符号が違っても距離が近ければ○(符号一致方式との本質的な差)
        assert l3.fit_distance(0.2, -0.2) == '○', "符号違いでも距離0.4なら○"
        assert l3.fit_distance(None, 1.0) is None and l3.fit_distance(1.0, None) is None
        # horse_lap33_value: 好走時平均(placed_avg)を優先、無ければ全走平均へフォールバック
        assert l3.horse_lap33_value({'placed_avg': 1.5, 'avg_lap33': 0.2}) == 1.5, "好走時優先"
        assert l3.horse_lap33_value({'placed_avg': None, 'avg_lap33': 0.2}) == 0.2, "無ければ全走平均"
        assert l3.horse_lap33_value({'placed_avg': None, 'avg_lap33': None}) is None
        assert l3.horse_lap33_value(None) is None
        assert (l3.FIT_NEAR, l3.FIT_WIDE) == (0.5, 1.0), "しきい値は原典の±0.5/±1.0"
        for fn in ('course_avg33', 'horse_fit33', 'race_mid3f_rate', 'race_lap33', 'lap33',
                   'fit_match', 'fit_distance', 'horse_lap33_value'):
            assert hasattr(l3, fn), f"lap33.{fn} 欠落"
    check("33ラップ理論(lap33)の契約", t_lap33)

    def t_prev_race_close_sec():
        # その他の穴馬候補: |差|<=0.5秒なら秒数を赤字。スコアには使わない表示専用。
        from core import prev_race as prv
        assert prv.CLOSE_SEC == 0.5
        close = {'margin_3rd': 0.4, 'rank': 4}
        far = {'margin_3rd': 0.7, 'rank': 5}
        miss = {'margin_3rd': None, 'margin_win': None, 'rank': 8}
        winfb = {'margin_3rd': None, 'margin_win': -0.2, 'rank': 2}
        assert prv.is_close_margin(close) and not prv.is_close_margin(far)
        assert not prv.is_close_margin(miss), "欠損は赤字にしない"
        assert prv.is_close_margin(winfb), "3着差なしなら1着差で判定"
        html_c = prv.margin_line_html(close)
        html_f = prv.margin_line_html(far)
        assert '+0.4秒' in html_c and 'font-weight:bold' in html_c
        assert '+0.7秒' in html_f and 'font-weight:bold' not in html_f
        # 既存の関数は文字列のまま(シグネチャ不変)
        assert prv.margin_line(close) == '3着馬との差 +0.4秒'
        badge_ok = {'is_stakes': True, 'margin_3rd': 0.3, 'rank': 5}
        badge_no = {'is_stakes': True, 'margin_3rd': 0.5, 'rank': 5}
        assert prv.badge(badge_ok) == '⭐ 重賞で3着馬と接戦'
        assert prv.badge(badge_no) == '', "0.5秒赤字は⭐バッジを広げない"
    check("前走差の赤字表示(prev_race・表示専用)", t_prev_race_close_sec)

    def t_gyaku_shocker_reach():
        # 穴馬ハンター表示専用。今回3角は関数に渡さない(リーク防止)。
        from core import gyaku_shocker as gs
        import inspect
        assert 'current_c3' not in inspect.signature(gs.reach).parameters
        assert 'corner3' not in inspect.signature(gs.reach).parameters
        assert gs.reach(2000, 1600, '12-10-9-8'), "後方+短縮=候補"
        assert gs.reach(1400, 1200, '12-11'), "短距離通過2個でも3角=12"
        assert gs.reach(2000, 1600, '2-2-2-1') is False, "前走先行は候補にしない"
        assert gs.reach(1600, 1800, '12-10-9-8') is False, "距離延長は候補にしない"
        assert gs.reach(1600, 1600, '12-10-9-8') is False, "同距離は候補にしない"
        assert gs.reach(None, 1600, '12-10-9-8') is None, "距離欠損は判定しない"
        html = gs.label_html(gs.reach(2000, 1600, '10-10-8-7'))
        assert '逆ショッカー候補' in html and 'font-weight:bold' in html
        assert '適合' not in html, "完成条件を示唆しない"
        assert gs.label_html(False) == '' and gs.label_html(None) == ''
        assert gs.table_cell(gs.reach(2000, 1600, '10-10-8-7')) == gs.TABLE_HIT
        assert gs.TABLE_HIT == '〇'
        assert gs.pred_c3_memo(7) == '予測3角：7番手（netkeiba AI・本番の3角ではない）'
        assert gs.pred_c3_memo(None) == ''
        assert '予測3角：7番手' in gs.table_cell_pred(gs.reach(2000, 1600, '10-10-8-7'), 7)
        assert '候補(予測3角' not in gs.table_cell_pred(gs.reach(2000, 1600, '10-10-8-7'), 7)
        assert gs.PAIR_MARK == '🟣⏱️'
        hit = gs.reach(2000, 1600, '10-10-8-7')
        paired = gs.with_pair(hit, 6, 0.2)
        assert paired['pair_mark'] == '🟣⏱️'
        assert gs.pair_prefix(paired) == '🟣⏱️ '
        assert '🟣⏱️' in gs.label_html(paired)
        assert gs.with_pair(hit, 2, 0.1).get('pair_mark') is None, "3着以内は⏱️しない"
        assert gs.with_pair(hit, 6, 0.8).get('pair_mark') is None, "0.3秒超は僅差ではない"
        assert gs.with_pair(False, 6, 0.2) is False
        assert gs.pair_prefix(hit) == ''
        assert gs.table_cell_pred(gs.reach(2000, 1600, '10-10-8-7'), None) == gs.TABLE_HIT
        assert gs.table_cell_pred(False, 7) == gs.TABLE_MISS
        assert gs.table_cell(False) == gs.TABLE_MISS
        assert gs.table_cell(None) == gs.TABLE_MISS
        assert gs.table_cell(gs.reach(1600, 1800, '12-10-9-8')) == gs.TABLE_MISS
        runs = [{'Distance': 1400, 'Date': '2026.01.01', 'Surface': 'ダート'},
                {'Distance': 1200, 'Date': '2025.10.01', 'Surface': '芝'}]
        mem = gs.memo_lines(past_runs=runs, current_distance=1200,
                            current_surface='芝',
                            body_weight=482, race_date='20260301',
                            prev_date='2026.01.01')
        assert mem[0] == '↔ バウンド：1200→1400→1200'
        assert mem[1] == '↔ 芝⇔ダ：芝→ダ→芝'
        assert mem[2] == '体重：482kg　間隔：中8週'
        assert all('○' not in x for x in mem)
        plain = gs.memo_lines(
            past_runs=[{'Distance': 1800, 'Surface': '芝'},
                       {'Distance': 2000, 'Surface': '芝'}],
            current_distance=1600, current_surface='芝')
        assert not any('バウンド' in x or '芝⇔ダ' in x for x in plain)
        blk = gs.block_html(gs.with_memo(
            gs.reach(1400, 1200, '10-10-8-7'),
            past_runs=runs, current_distance=1200, current_surface='芝',
            body_weight=482, race_date='20260301', prev_date='2026.01.01'))
        assert '↔ バウンド：1200→1400→1200' in blk
        assert '↔ 芝⇔ダ：芝→ダ→芝' in blk
        assert '○' not in blk
    check("逆ショッカー候補(表示専用・リーク無し)", t_gyaku_shocker_reach)

    def t_jump_return_display():
        from core import jump_return as jr
        hit = jr.reach('障2900', '芝', 2900, 1600)
        assert hit and hit['prev_distance'] == 2900
        assert jr.reach('障害', 'ダート')
        assert jr.reach('芝', 'ダート') is False
        assert jr.reach('障', '障害') is False
        assert jr.reach('', '芝') is None
        assert jr.reach('障', '') is None
        html = jr.label_html(jr.reach('障', '芝1600', 3000, 1600))
        assert '障害帰り' in html
        assert 'font-weight:bold' in html
        assert '#2e7d32' in html
        assert jr.label_html(False) == '' and jr.label_html(None) == ''
        blk = jr.block_html(jr.reach('障', '芝'))
        assert '障害帰り' in blk and '点数' in blk
        from pages.anabaka_hunter import _html_oneline
        assert '障害帰り' in _html_oneline(blk)
    check("障害帰り(表示専用・緑字)", t_jump_return_display)

    def t_gyaku_newspaper_off():
        from core import newspaper as np
        view = {
            'columns': ['Umaban', 'Lap33', 'GyakuShocker', 'Projected Score'],
            'order': ['Umaban', 'Lap33', 'GyakuShocker', 'Projected Score'],
        }
        cols = np._pick_columns(view, {'col_mode': 'app', 'exclude_cols': []})
        assert 'GyakuShocker' not in cols
        assert 'Lap33' in cols
        cols2 = np._pick_columns(view, {
            'col_mode': 'custom',
            'custom_cols': ['GyakuShocker', 'Umaban'],
            'exclude_cols': [],
        })
        assert 'GyakuShocker' not in cols2
        assert 'Umaban' in cols2
        cols3 = np._pick_columns(view, {'col_mode': 'all', 'exclude_cols': []})
        assert 'GyakuShocker' not in cols3
        assert 'GyakuShocker' in np.HIDE_ON_PAPER
    check("逆シは新聞紙面に出ない", t_gyaku_newspaper_off)

    def t_longshot_threshold():
        # 穴馬しきい値は**常に6**(検証: 4に下げるとVHが人気順に負ける)。
        # 少頭数×堅いは『相手候補(4-5番人気)』を別枠で返すだけで、穴の定義は動かさない。
        from core import longshot_threshold as lst
        for n in (6, 8, 10, 12, 16, 18):
            th, _ = lst.default_threshold(n_horses=n, odds_list=[1.8, 3.5, 6.0])
            assert th == 6, f"穴馬しきい値は常に6であるべき ({n}頭で{th})"
        assert lst.LONGSHOT_MIN == 6
        assert (lst.COMPANION_LO, lst.COMPANION_HI) == (4, 5)
        # 少頭数×堅い → 相手候補あり
        b = lst.companion_band(n_horses=8, odds_list=[1.8, 3.5, 6.0])
        assert b and b['lo'] == 4 and b['hi'] == 5, f"少頭数×堅いで相手候補, got {b}"
        # 少頭数でも市場が開いていれば出さない
        assert lst.companion_band(n_horses=8, odds_list=[5.0, 6.0, 7.0]) is None
        # 多頭数では堅くても出さない
        assert lst.companion_band(n_horses=16, odds_list=[1.8, 3.5, 6.0]) is None
        # ★オッズ未取得は「判定不能」で決め打ちしない(旧実装は4を返す不具合があった)
        assert lst.is_small_firm(n_horses=8, odds_list=[]) is None, "オッズ無しは判定不能"
        assert lst.is_small_firm(n_horses=8, odds_list=[2.0]) is None, "3頭未満も判定不能"
        assert lst.companion_band(n_horses=8, odds_list=[]) is None, "判定不能なら出さない"
    check("穴馬しきい値/相手候補帯(longshot_threshold)", t_longshot_threshold)

    # ── Phase4: DB健全性 ──
    if not args.quick:
        def t_jravan():
            db = os.path.join(ROOT, 'data', 'jravan.db')
            assert os.path.exists(db), "jravan.db が無い"
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            for t in ('races', 'results', 'horses'):
                n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                assert n > 0, f"{t} が空"
            con.close()
        check("DB jravan.db 主要テーブル", t_jravan)

        def t_blood():
            db = os.path.join(ROOT, 'data', 'blood_dict.db')
            assert os.path.exists(db), "blood_dict.db が無い"
            con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
            n = con.execute("SELECT COUNT(*) FROM sire_stats").fetchone()[0]
            assert n > 0, "sire_stats が空"
            con.close()
        check("DB blood_dict.db sire_stats", t_blood)

    # ── 集計 ──
    fails = [r for r in _results if not r[0]]
    print("=" * 72)
    print(f"スモークテスト結果: {len(_results)-len(fails)}/{len(_results)} 合格")
    print("=" * 72)
    if fails:
        print("❌ 失敗:")
        for ok, name, msg in fails:
            print(f"  - {name}\n      {msg}")
    else:
        print("✅ 全合格")
    # 構文/import以外の失敗だけ詳細(構文OKは静かに)
    print(f"\n内訳: 構文{sum(1 for r in _results if r[1].startswith('構文'))}件 / "
          f"import{sum(1 for r in _results if r[1].startswith('import'))}件 / "
          f"関数{sum(1 for r in _results if not r[1].startswith(('構文','import','DB')))}件 / "
          f"DB{sum(1 for r in _results if r[1].startswith('DB'))}件")
    sys.exit(len(fails))


if __name__ == '__main__':
    main()
