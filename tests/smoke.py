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
            'axis_selector', 'pace_map']
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
        lg.con.close()
        try:
            os.remove(_tmp)
        except Exception:
            pass
    check("money.Ledger gate_status/roi_by_gate", t_ledger_gate)

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
        assert '⚠' in dg.axis_demote('◎ 60%', r1), "severity1で⚠付記"
    check("danger_gate.danger_veto / axis_demote", t_danger_gate)

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
