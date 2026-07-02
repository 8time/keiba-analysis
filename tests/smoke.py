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
            'axis_selector', 'pace_map', 'paddock_ledger']
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

    def t_no_favorite():
        from core import value_scanner as vs
        # 大谷等価: fav1≥3.0 & odds3/odds1≤2.0 & 30倍未満≥10頭 → ●大穴
        assert vs.no_favorite_flag([3.5, 5.0, 6.0] + [8.0] * 8) == '●大穴'
        # 抜けた本命(fav1=1.5)がいる→フラグ無し
        assert vs.no_favorite_flag([1.5, 3.0, 10.0] + [40.0] * 5) is None
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
        assert '⚠' in dg.axis_demote('◎ 60%', r1), "severity1で⚠付記"
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
    check("NAR過去走ブリッジの関数契約", t_nankan_contract)

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
