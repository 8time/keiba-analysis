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
            'axis_selector', 'pace_map', 'paddock_ledger', 'consensus_view']
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
        # スト1/スト2フラグ: 点灯するが band(推定複勝率)には算入しない(UNVERIFIED)
        f = ec.compute_flags(stress1=True, stress2=True)
        assert 'stress1' in f and 'stress2' in f, "スト1/2点灯"
        assert ec.FLAG_LABEL['stress1'] == 'スト1' and ec.FLAG_LABEL['stress2'] == 'スト2'
        assert 'stress1' in ec.UNVERIFIED and 'stress2' in ec.UNVERIFIED, "band非算入"
        # 検証数はstressを除外(zogen+age8のみ=2)
        f2 = ec.compute_flags(zogen=20, age=9, stress1=True, stress2=True)
        assert ec.verified_count(f2) == 2, f"stressはband非算入, got {ec.verified_count(f2)}"
    check("elim_cross.スト1/スト2(band非算入)", t_elim_stress)

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

    def t_trifecta():
        from core import trio_engine as te
        hs = [{'umaban': i, 'name': f'H{i}', 'score': 100 - i * 3, 'pop': i, 'alert': ''}
              for i in range(1, 13)]
        hs[9]['alert'] = '🔵補正T上位 🔥末脚top 🧩2重複'
        r = te.recommend_trifecta(hs, axis_umaban=[2, 1], n_points=100)
        assert r['warning'] is None and len(r['bets']) <= 50, "ハード上限50点(推奨30・40/50は任意増量)"
        assert r['bets'][0]['combo'][0] == 2, f"◎(axis先頭)が1着固定, got {r['bets'][0]['combo']}"
        assert 10 in r['meta']['third'], f"🧩combo穴がヒモ候補入り, got {r['meta']['third']}"
        assert all(len(set(b['combo'])) == 3 for b in r['bets']), "3頭相異なる順序組"
    check("trio_engine.recommend_trifecta(30点cap/◎頭/🧩ヒモ)", t_trifecta)

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

    def t_agent_roster():
        from core import agent_forum as af
        r = af.agent_roster()
        assert len(r) >= 10 and all('focus' in a and 'id' in a for a in r), "名簿にfocus/id"
        # 情報の切り口ラベルが付く(多様性=脱相関の軸)
        _foc = {a['id']: a['focus'] for a in r}
        assert _foc.get('kei') == '血統' and _foc.get('jin') == '騎手'
        # 選択班: 指定id順・未知は無視
        sel = af.agents_by_ids(['taku', 'zzz', 'kei'])
        assert [a['id'] for a in sel] == ['taku', 'kei']
        assert af.agents_by_ids([]) == []
    check("agent_forum.agent_roster/agents_by_ids", t_agent_roster)

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

    def t_danger_gate():
        from core import danger_gate as dg
        # 人気薄は対象外
        assert dg.danger_veto(ninki=8, surface='芝', baba='重')['severity'] == 0, "人気薄は危険対象外"
        # 重×1番人気 + 牝×冬春fade = 2件→veto
        r = dg.danger_veto(ninki=1, surface='芝', baba='重', sex_age='牝3', month=1)
        assert r['veto'] and r['severity'] >= 2, f"重×1番+牝冬春→veto, got {r}"
        # 1件なら降格注意(veto=False)
        r1 = dg.danger_veto(ninki=1, surface='芝', baba='重')
        assert (not r1['veto']) and r1['severity'] == 1, f"重×1番のみ→severity1, got {r1}"
        # axis_demote: severity>=2はマーク置換
        assert dg.axis_demote('◎ 60%', r).startswith('⚠危険'), "severity>=2でマーク置換"
        # 高齢(7歳+)ソフト理由: 単独では非表示・硬い危険と重なるとseverity算入(検証済-6.5pp)
        assert dg.danger_veto(ninki=2, surface='芝', sex_age='牡8')['severity'] == 0, "高齢単独は非表示(ソフト)"
        _rage = dg.danger_veto(ninki=2, surface='芝', sex_age='牡8', top_jockey_swap=True)
        assert '高齢(7歳+)' in _rage['reasons'] and _rage['severity'] == 2, "高齢+硬い危険で算入"
        # 前走5着以下ソフト理由(検証済 train-1.5/holdout-1.8pp): 単独非表示・硬い危険と算入
        assert dg.danger_veto(ninki=1, surface='芝', prev_chaku=8)['severity'] == 0, "前走5着以下単独は非表示"
        _rp5 = dg.danger_veto(ninki=1, surface='芝', prev_chaku=8, top_jockey_swap=True)
        assert '前走5着以下' in _rp5['reasons'] and _rp5['severity'] == 2, "前走5着以下+硬い危険で算入"
        assert '前走5着以下' not in dg.danger_veto(ninki=1, surface='芝', prev_chaku=3)['reasons'], "前走4着以内は非該当"
        assert '⚠' in dg.axis_demote('◎ 60%', r1), "severity1で⚠付記"
        # 半年休み明けはソフト理由: 単独では危険にしない(精度低・NAR誤爆対策)
        assert dg.danger_veto(ninki=1, layoff_days=200)['severity'] == 0, "休み明け単独は危険にしない"
        # 他の硬い理由と重なった時のみ算入
        _rs = dg.danger_veto(ninki=1, layoff_days=200, top_jockey_swap=True)
        assert _rs['severity'] == 2 and '半年休み明け' in _rs['reasons'], f"休明+硬でstack, got {_rs}"
    check("danger_gate.danger_veto / axis_demote", t_danger_gate)

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
                  'improvement_rules', 'classify_loss', 'record_prediction'):
            assert hasattr(money.Ledger, m), f"money.Ledger.{m} 欠落(ダッシュボード破壊)"
        for fn in ('recent_gates', 'read_gate', 'write_gate', 'read_buy', 'write_buy'):
            assert hasattr(sc, fn), f"score_cache.{fn} 欠落"
    check("dashboard/⑥回顧の関数契約", t_dashboard_contract)

    def t_nankan_contract():
        # NAR過去走ブリッジ(SRA/消去エンジンが依存)の関数存在＋venue導出ロジック保証
        from core import nankan_scraper as nk
        for fn in ('derive_nankan_race_id', 'fetch_month_programs',
                   'fetch_program_races', 'fetch_entries', 'fetch_horse_history',
                   'runs_to_pastruns', 'enrich_with_nankan'):
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
    check("血統×コース(blood_course)の契約", t_blood_course)

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
        for fn in ('course_avg33', 'horse_fit33', 'race_mid3f_rate', 'race_lap33', 'lap33', 'fit_match'):
            assert hasattr(l3, fn), f"lap33.{fn} 欠落"
    check("33ラップ理論(lap33)の契約", t_lap33)

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
