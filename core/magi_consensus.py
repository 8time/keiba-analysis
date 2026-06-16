# -*- coding: utf-8 -*-
"""
MAGI 合議ゲート (Consensus Gate) — 妙味判定／見送り判定器
─────────────────────────────────────────────────────────────
旧MAGI(magi_system.py)の問題: 3機が同じ BattleScore/Projected Score を見ていたため
相関がほぼ1の"偽アンサンブル"で、合議＝BattleScoreの追認装置だった(精度頭打ちの根因)。

本モジュールは予測器をやめ、合議の本来の価値=「独立した別視点が一致するか」を信号にする。
3機を"互いに独立した検証済みエッジ"に差し替える(新ヒューリスティクスは作らない):

  MELCHIOR-1 (論理・実力)  : 強適消去スコア上位 = 実力で消えない本命視点
  BALTHASAR-2(母・市場妙味): 単複乖離(検証2.5→7%)/オッズ断層/黄金ライン/厩舎当コース
  CASPER-3   (女・展開直感): 🔥末脚救出(検証)/展開好位妙味(検証+2.4pp)

出力は「誰が勝つか」ではなく合議状態:
  - 全会一致(3票)の人気薄 → 🟢GO(別々の検証済みエッジが同じ人気薄を指す=本物の可能性)
  - 部分合意(2票)        → 🟡条件付き
  - 分裂(≤1票)          → ⚪見送り(控除率25%で一番効くのは賭けないレースを選ぶこと)
  - 危険人気馬           → 🔴軸外し(消去が残さない/市場過大評価×−ファクター)

自信度は作り物の数字でなく、回顧台帳(consensus_ledger)に実測ヒット率を貯めて与える。
"""
from __future__ import annotations


def _classify_pos(pos):
    """value_scanner の pos(＋ファクター)文字列を BALTHASAR系/CASPER系に振り分ける。"""
    cas = [p for p in pos if '末脚' in p]          # 🔥末脚救出
    bal = [p for p in pos if '末脚' not in p]      # 単複乖離 / 断層上位 / 黄金ライン / 厩舎当ｺｰｽ
    return bal, cas


def evaluate_consensus(rows, vs, jj, jyo, surface, dist, month, min_year,
                       place_map=None, pace_pos=None, date_val='',
                       gap_anchors=None, ana_pop=6, danger_pop=3):
    """3機の独立判定を集計して合議結果を返す。

    rows       : get_race_data の各行(dict-like)の列。Umaban/Name/Popularity/Odds/SexAge/Jockey/Weight等。
    vs         : core.value_scanner モジュール
    jj         : core.jockey_jv モジュール
    place_map  : {umaban: {'Mid': float}} 事前複勝オッズ(単複乖離用)。無ければ単複乖離は不発。
    pace_pos   : 展開好位妙味ゾーンの馬番 set(任意・展開マップ連携)。CASPERの展開票に使用。
    gap_anchors: オッズ断層上位の馬番 set(任意)。無ければ内部で計算しない(value_scannerには渡さない)。
    ana_pop    : 人気薄の下限人気(妙味判定の対象)
    danger_pop : 危険人気馬の上限人気

    戻り: {
      'horses': [{um,name,pop,odds, mel,bal,cas, votes, pos[], neg[]}...],  # votes=承認数(0-3)
      'candidate': 焦点候補horse|None,   # 人気薄の最多得票馬(無ければ実力1位)
      'unit_votes': {'MELCHIOR':bool,'BALTHASAR':bool,'CASPER':bool},  # 焦点候補への承認
      'approvals': int(0-3),
      'verdict': 'GO'|'CONDITIONAL'|'SKIP',
      'verdict_label': str,
      'danger': [{um,name,pop,odds,neg[]}...],  # 危険人気馬(軸外し推奨)
      'consensus_anaUma': [人気薄×2票以上の馬...],
    }
    """
    pace_pos = pace_pos or set()
    gap_anchors = gap_anchors or set()
    place_map = place_map or {}

    horses = []
    for hr in rows:
        try:
            um = int(float(hr.get('Umaban')))
        except (TypeError, ValueError):
            continue
        nm = str(hr.get('Name', '') or '')
        pm = (place_map.get(um) or {}).get('Mid') if place_map else None
        f = vs.horse_value_factors(hr, jj, jyo, surface, dist, month, min_year,
                                   place_mid=pm, date_val=date_val,
                                   gap_anchor=(um in gap_anchors))
        pop = f['pop']
        od = f['odds']
        # オッズ未確定/取消(番兵)は対象外
        if not (od and od > 0 and pop and pop < 90):
            continue
        bal_pos, cas_pos = _classify_pos(f['pos'])
        bal_vote = bool(bal_pos) or f['div_level'] >= 1 or f.get('anchor')
        cas_vote = bool(cas_pos) or (um in pace_pos)
        horses.append({
            'um': um, 'name': nm, 'pop': pop, 'odds': od,
            'has_pos': f['has_pos'], 'has_neg': f['has_neg'],
            'pos': f['pos'], 'neg': f['neg'],
            'bal': bool(bal_vote), 'cas': bool(cas_vote),
            'pace': um in pace_pos,
        })

    if not horses:
        return {'horses': [], 'candidate': None,
                'unit_votes': {'MELCHIOR': False, 'BALTHASAR': False, 'CASPER': False},
                'approvals': 0, 'verdict': 'SKIP',
                'verdict_label': '判定不能（有効データなし）',
                'danger': [], 'consensus_anaUma': []}

    # ── MELCHIOR: 強適消去スコアで上位半分=「実力で残る」=承認 ──
    # 消去エンジンと同一: score = -人気 + 1.5(＋ファクター) - 1.5(−ファクター)
    for h in horses:
        h['elim_score'] = -(h['pop']) + (1.5 if h['has_pos'] else 0) - (1.5 if h['has_neg'] else 0)
    ranked = sorted(horses, key=lambda x: -x['elim_score'])
    keep = (len(ranked) + 1) // 2
    keep_ums = {h['um'] for h in ranked[:keep]}
    for h in horses:
        h['mel'] = h['um'] in keep_ums
        h['votes'] = int(h['mel']) + int(h['bal']) + int(h['cas'])

    # ── 焦点候補: 人気薄(>=ana_pop)で最多得票→同票はオッズ高い順 ──
    ana = [h for h in horses if h['pop'] >= ana_pop and (h['bal'] or h['cas'])]
    consensus_ana = sorted([h for h in ana if h['votes'] >= 2],
                           key=lambda x: (-x['votes'], -x['odds']))
    if ana:
        candidate = sorted(ana, key=lambda x: (-x['votes'], -x['odds']))[0]
    else:
        candidate = ranked[0]   # 妙味の人気薄が無ければ実力1位(堅め本命)

    unit_votes = {'MELCHIOR': candidate['mel'],
                  'BALTHASAR': candidate['bal'],
                  'CASPER': candidate['cas']}
    approvals = sum(unit_votes.values())

    # ── 合議判定 ──
    # バックテスト(scripts/consensus_backtest.py, 2021-25 人気薄127,550点)の知見を反映:
    #   ・的中率は承認数に応じて単調に上がる(合議=集中は本物)。
    #   ・だがROIを生むのは「市場軸=BALTHASAR」の票が混ざったときだけ。
    #     実力軸どうし(MELCHIOR実力+CASPER末脚)を重ねても的中は上がるがROIは出ない
    #     (市場が既に織込み済 ＝ verified_spurt_index step2「AND併用は悪化」と整合)。
    #   ・3軸全一致 / 末脚×断層は別格(複勝率~27%/単ROI~95%)。
    #   → 承認数を対称に扱わず、市場軸(BALTHASAR)が入っているかで格付けする。
    is_ana = candidate['pop'] >= ana_pop
    has_market = candidate['bal']   # BALTHASAR(単複乖離/断層/黄金/厩舎)=市場・別軸の票
    if is_ana and approvals >= 3:
        verdict, label = 'GO', '🟢 GO ／ 全会一致（3軸一致＝別格・複勝/組合せ向き）'
    elif is_ana and approvals == 2 and has_market:
        # 別軸(市場)×実力 の2票 = ROIが出る合議
        verdict, label = 'CONDITIONAL', '🟡 条件付き ／ 別軸合意（市場×実力の2機）'
    elif is_ana and approvals == 2 and not has_market:
        # 実力軸どうしの2票 = 的中は上がるがROIエッジ無し(市場が織込み済)
        verdict, label = 'SKIP', '⚪ 見送り推奨 ／ 実力軸の重複（市場の裏付けなし＝妙味薄）'
    elif not is_ana and approvals >= 2:
        # 人気薄に妙味が無く、本命が実力＋市場で支持 → 堅め
        verdict, label = 'CONDITIONAL', '🟡 堅め本命 ／ 妙味の人気薄なし（本命堅）'
    else:
        verdict, label = 'SKIP', '⚪ 見送り ／ シグナル分裂（賭けない判断）'

    # ── 危険人気馬: 人気<=danger_pop × −ファクター × 市場妙味なし ──
    danger = [{'um': h['um'], 'name': h['name'], 'pop': h['pop'],
               'odds': h['odds'], 'neg': h['neg']}
              for h in horses
              if h['pop'] <= danger_pop and h['has_neg'] and not h['bal']]

    return {
        'horses': sorted(horses, key=lambda x: -x['votes']),
        'candidate': candidate,
        'unit_votes': unit_votes,
        'approvals': approvals,
        'verdict': verdict,
        'verdict_label': label,
        'danger': danger,
        'consensus_anaUma': consensus_ana,
    }


# ─────────────────────────────────────────────────────────────
#  回顧台帳(Consensus Ledger) — 自信度を実測ヒット率にするキャリブレーション層
# ─────────────────────────────────────────────────────────────
import os
import json

LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           'consensus_ledger.json')


def _load_ledger(path=None):
    p = path or LEDGER_PATH
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'records': []}


def log_consensus_outcome(race_id, result, candidate_chaku=None,
                          candidate_placed=None, candidate_odds=None, path=None):
    """合議判定と実際の結果を1件記録する。回顧学習(キャリブレーション)の素データ。

    race_id          : レースID
    result           : evaluate_consensus の戻り
    candidate_chaku  : 焦点候補の確定着順(int)。分かれば。
    candidate_placed : 焦点候補が3着内か(bool)。Noneなら chaku から導出。
    candidate_odds   : 焦点候補の単勝オッズ(確定/事前)。ROI集計用。
    """
    p = path or LEDGER_PATH
    led = _load_ledger(p)
    cand = result.get('candidate') or {}
    if candidate_placed is None and candidate_chaku is not None:
        candidate_placed = candidate_chaku <= 3
    led['records'].append({
        'race_id': str(race_id),
        'verdict': result.get('verdict'),
        'approvals': result.get('approvals'),
        'candidate_um': cand.get('um'),
        'candidate_pop': cand.get('pop'),
        'candidate_odds': candidate_odds if candidate_odds is not None else cand.get('odds'),
        'candidate_chaku': candidate_chaku,
        'candidate_placed': bool(candidate_placed) if candidate_placed is not None else None,
        'candidate_win': (candidate_chaku == 1) if candidate_chaku is not None else None,
    })
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(led, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return led


def calibration_summary(path=None):
    """合議状態(承認数/verdict)別の実測ヒット率・ROIを集計して返す。
    これが各MAGI状態の"自信度"の正体になる(作り物の数字を置き換える)。"""
    led = _load_ledger(path)
    recs = [r for r in led.get('records', []) if r.get('candidate_chaku') is not None]
    buckets = {}
    for r in recs:
        key = f"approvals={r.get('approvals')}"
        b = buckets.setdefault(key, {'n': 0, 'win': 0, 'place': 0, 'win_ret': 0.0})
        b['n'] += 1
        if r.get('candidate_win'):
            b['win'] += 1
            if r.get('candidate_odds'):
                b['win_ret'] += float(r['candidate_odds']) * 100
        if r.get('candidate_placed'):
            b['place'] += 1
    out = {}
    for k, b in buckets.items():
        n = b['n'] or 1
        out[k] = {
            'n': b['n'],
            'win_rate': round(100 * b['win'] / n, 1),
            'place_rate': round(100 * b['place'] / n, 1),
            'win_roi': round(100 * b['win_ret'] / (n * 100), 1),
        }
    return out
