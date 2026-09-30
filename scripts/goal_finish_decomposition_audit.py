"""Read-only audit of the SRA 4-corner -> finish transformation.

The 2024/25/26 historical finish is a JV *proxy*, not a replay of live SRA:
historical live BattleScore, suitability and timestamped market prices are
unavailable.  Final JV popularity is used only in explicitly labelled proxy
diagnostics and is never presented as a deployable pre-race predictor.
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import pace_map as pm
from forward_retention_research import ROOT, fit_logit, predict, report, target_exclusions


def rank(values):
    return {u: i + 1 for i, u in enumerate(sorted(values, key=lambda u: (values[u], u)))}


def race_records(db_path, year, excluded_races=frozenset(), excluded_horses=frozenset()):
    con = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    races = con.execute(
        """SELECT race_key, race_id, year, jyo, kyori, surface, shusso_tosu
             FROM races WHERE year=? AND kyori=1200
              AND surface='芝'
              AND shusso_tosu>=8 ORDER BY race_key""", (str(year),)).fetchall()
    out = []
    used = 0
    for ra in races:
        rk = ra["race_key"]
        if ra["race_id"] in excluded_races or ra["race_id"] == "202606040911":
            continue
        runners = con.execute(
            "SELECT umaban,bamei,ninki,chakujun,corner4,ketto_num FROM results "
            "WHERE race_key=? AND umaban>0 AND chakujun>0", (rk,)).fetchall()
        if len(runners) < 8 or any(r["corner4"] is None or r["corner4"] <= 0 for r in runners):
            continue
        horses = [dict(umaban=r["umaban"], name=r["bamei"], score=.5, style='不明')
                  for r in runners]
        profiles = pm.fetch_jv_profiles(
            [h['name'] for h in horses], max_runs=8, surface=ra['surface'],
            distance=ra['kyori'], before_key=rk[:8], read_only=True)
        if len(profiles) < 6:
            continue
        for h in horses:
            prof = profiles.get(h['name']) or {}
            h['score'] = prof.get('ten') if prof.get('ten') is not None else .5
            h['style'] = pm.style_from_score(h['score'])
        layout = pm.get_course_layout(pm.VENUE_CODES.get(str(ra['jyo']).zfill(2)),
                                      ra['surface'], ra['kyori'])
        ctx = pm.build_pace_context(horses, profiles, ra['kyori'], ra['surface'], layout)
        pos4 = ctx['pos4']
        # Timed market input is absent historically.  Keep this hindsight
        # popularity proxy separate from the time-safe no-market comparator.
        market = {r['umaban']: r['ninki'] for r in runners if r['ninki'] and r['ninki'] > 0}
        final_extras = {u: {'pop': p} for u, p in market.items()}
        models = {
            'pos4': pos4,
            'goal_no_market': pm.predict_finish(horses, profiles, ctx, {}),
            'goal_final_pop_proxy': pm.predict_finish(horses, profiles, ctx, final_extras),
            'goal_pop_only_oracle': {u: market.get(u, len(horses)/2) for u in pos4},
        }
        for group, key in [('pos4','w_pos4'), ('kick','w_kick'), ('power','w_power'),
                           ('apt','w_apt'), ('pop','w_pop'), ('spurt','w_spurt')]:
            models['minus_'+group] = pm.predict_finish(
                horses, profiles, ctx, final_extras, tune={key: 0.0})
        models['pos4_weight_0p7'] = pm.predict_finish(
            horses, profiles, ctx, final_extras, tune={'w_pos4': .7})
        ranks = {key: rank(value) for key, value in models.items()}
        p4_rank = ranks['pos4']; goal_rank = ranks['goal_final_pop_proxy']
        no_market_rank = ranks['goal_no_market']
        n = len(runners); k = math.ceil(n*.4)
        shadow = pm.predict_finish_shadow(horses, profiles, ctx, final_extras,
                                           popularity=market)
        for r in runners:
            if r['ketto_num'] in excluded_horses:
                continue
            u = r['umaban']
            rec = {'year': int(year), 'race_id': ra['race_id'], 'race_key': rk,
                   'horse_id': r['ketto_num'], 'umaban': u, 'field': n,
                   'pop_final': market.get(u), 'actual_c4': r['corner4'],
                   'actual_finish': r['chakujun'], 'top3': int(r['chakujun'] <= 3),
                   'actual_front': int(r['corner4'] <= k),
                   'p4rank': p4_rank[u], 'goalrank': goal_rank[u],
                   'nomarketrank': no_market_rank[u], 'k': k,
                   'delta': goal_rank[u]-p4_rank[u],
                   'front_pred': int(p4_rank[u] <= k),
                   'goal_pred': int(goal_rank[u] <= k),
                   'score': models['goal_final_pop_proxy'][u],
                   'position_score': pos4[u],
                   'contrib': shadow['contributions'][u]}
            for key, values in models.items():
                rec['score_'+key] = values[u]
                rec['rank_'+key] = ranks[key][u]
            out.append(rec)
        used += 1
    con.close()
    return out, {'eligible_races': used, 'horses': len(out)}


def aggregate(records, threshold):
    by_race = defaultdict(list)
    for r in records:
        by_race[r['race_id']].append(r)
    front = [r for r in records if r['front_pred']]
    demoted = [r for r in front if r['delta'] >= threshold]
    kept = [r for r in front if r['goal_pred']]
    dropped = [r for r in front if not r['goal_pred']]
    lost_hits = sum(r['top3'] for r in dropped)
    correctly_removed = sum(1-r['top3'] for r in dropped)
    gained = [r for r in records if not r['front_pred'] and r['goal_pred']]
    total_hits = sum(r['top3'] for r in records)
    front_hits = sum(r['top3'] for r in front)
    goal_hits = sum(r['top3'] for r in records if r['goal_pred'])
    groups = {'A': [r for r in kept if r['top3']],
              'B': [r for r in dropped if r['top3']],
              'C': [r for r in dropped if not r['top3']],
              'D': [r for r in kept if not r['top3']]}
    def summary(rs):
        if not rs: return {'n': 0}
        return {'n': len(rs), 'top3_rate': round(sum(r['top3'] for r in rs)/len(rs), 4),
                'actual_front_rate': round(sum(r['actual_front'] for r in rs)/len(rs), 4),
                'avg_final_popularity': round(sum(r['pop_final'] for r in rs if r['pop_final']) /
                                              max(1, sum(bool(r['pop_final']) for r in rs)), 2),
                'mean_delta': round(sum(r['delta'] for r in rs)/len(rs), 2),
                'mean_goal_rank': round(sum(r['goalrank'] for r in rs)/len(rs), 2)}
    bands = {}
    for label, lo, hi in [('0-2',0,2),('3-4',3,4),('5-6',5,6),('7+',7,99)]:
        z=[r for r in front if lo<=r['delta']<=hi]
        bands[label]=summary(z)
    popular = {}
    for label,fn in [('top5',lambda p:p<=5),('6-10',lambda p:6<=p<=10),('11+',lambda p:p>=11)]:
        z=[r for r in front if r['pop_final'] and fn(r['pop_final'])]
        popular[label]={'front':summary(z),'demoted':summary([r for r in z if r['delta']>=threshold])}
    contribution = {}
    for key in ('pos4','kick','apt','power','pop','spurt','reach_penalty'):
        means = {label:round(sum(r['contrib'][key] for r in rs)/len(rs),4) if rs else None
                 for label,rs in groups.items()}
        contribution[key]=means
    rescue = {}
    for feature in ('pos4','kick','power','apt','pop','spurt'):
        key='rank_minus_'+feature
        rescue[feature]={label:sum(r[key]<=r['k'] for r in rs)
                         for label,rs in groups.items() if label in ('B','C')}
    return {'races':len(by_race),'front_pred_n':len(front),'demotion_threshold':threshold,
            'front_top3_recall':round(front_hits/max(1,total_hits),4),
            'goal_top3_recall':round(goal_hits/max(1,total_hits),4),
            'front_hits':front_hits,'goal_hits':goal_hits,'total_hits':total_hits,
            'lost_hits':lost_hits,'correctly_removed_nonhits':correctly_removed,
            'gained_hits':sum(r['top3'] for r in gained),
            'added_nonhits':sum(1-r['top3'] for r in gained),
            'removed_nonhits_per_lost_hit':round(correctly_removed/max(1,lost_hits),3),
            'groups':{key:summary(rs) for key,rs in groups.items()},
            'front_actual_front_rate':summary([r for r in front if r['actual_front']]),
            'lost_hits_who_reached_actual_front':sum(r['actual_front'] for r in groups['B']),
            'large_demotion':summary(demoted),'demotion_bands':bands,
            'popularity_diagnostic_final_only':popular,
            'contribution_by_group':contribution,
            'ablation_rescue_of_dropped':rescue}


def no_market_transition(records, threshold):
    """Same 4-corner transition without any current-race market input."""
    front=[r for r in records if r['front_pred']]
    kept=[r for r in front if r['nomarketrank']<=r['k']]
    dropped=[r for r in front if r['nomarketrank']>r['k']]
    gained=[r for r in records if not r['front_pred'] and r['nomarketrank']<=r['k']]
    demoted=[r for r in front if r['nomarketrank']-r['p4rank']>=threshold]
    hits=lambda xs:sum(r['top3'] for r in xs)
    return {'front_n':len(front),'A':hits(kept),'B':hits(dropped),
            'C':len(dropped)-hits(dropped),'D':len(kept)-hits(kept),
            'lost_hits':hits(dropped),
            'correctly_removed_nonhits':len(dropped)-hits(dropped),
            'gained_hits':hits(gained),'added_nonhits':len(gained)-hits(gained),
            'demotion_threshold':threshold,'large_demotion_n':len(demoted),
            'large_demotion_top3_rate':round(hits(demoted)/max(1,len(demoted)),4),
            'lost_hits_reached_actual_front':sum(r['actual_front'] for r in dropped if r['top3'])}


def model_metrics(train, test):
    result={}
    for name in ('pos4','goal_no_market','goal_final_pop_proxy','goal_pop_only_oracle',
                 'minus_pos4','minus_kick','minus_power','minus_apt','minus_pop','minus_spurt',
                 'pos4_weight_0p7'):
        key='score_'+name
        model=fit_logit([{**r,'signal':r[key]} for r in train],'top3',['signal'])
        p=predict(model,[{**r,'signal':r[key]} for r in test])
        result[name]=report(test,'top3',p,topk=5)
        result[name]['top40_recall']=round(sum(r['top3'] for r in test if r['rank_'+name]<=r['k'])/
                                           max(1,sum(r['top3'] for r in test)),4)
    return result


def front_subset_metrics(train, test):
    """Conditional discrimination among predicted front candidates only."""
    tr=[r for r in train if r['front_pred']]
    te=[r for r in test if r['front_pred']]
    out={}
    for name in ('pos4','goal_no_market','goal_final_pop_proxy',
                 'goal_pop_only_oracle','pos4_weight_0p7'):
        key='score_'+name
        model=fit_logit([{**r,'signal':r[key]} for r in tr],'top3',['signal'])
        p=predict(model,[{**r,'signal':r[key]} for r in te])
        score=report(te,'top3',p,topk=5)
        out[name]={k:score[k] for k in ('n','rate','auc','pr_auc','brier','logloss')}
    return out


def paired_bootstrap(train, test):
    """Race-level paired CIs with calibration frozen on 2024 only."""
    names=('pos4','goal_no_market','goal_final_pop_proxy','minus_pos4',
           'minus_kick','minus_power','pos4_weight_0p7')
    preds={}
    for name in names:
        key='score_'+name
        fit=fit_logit([{**r,'signal':r[key]} for r in train],'top3',['signal'])
        preds[name]=np.asarray(predict(fit,[{**r,'signal':r[key]} for r in test]))
    races=defaultdict(list)
    for i,r in enumerate(test):
        races[r['race_id']].append(i)
    groups=list(races.values())
    rng=np.random.default_rng(20240929)
    comparisons=(('goal_no_market','pos4'),
                 ('goal_final_pop_proxy','pos4'),
                 ('goal_final_pop_proxy','minus_pos4'),
                 ('goal_final_pop_proxy','minus_kick'),
                 ('goal_final_pop_proxy','minus_power'),
                 ('goal_final_pop_proxy','pos4_weight_0p7'))
    out={}
    y=np.asarray([r['top3'] for r in test])
    for first,second in comparisons:
        # Positive delta means the first model is worse than the second.
        loss=(preds[first]-y)**2-(preds[second]-y)**2
        boot=[]
        for _ in range(600):
            sampled=rng.integers(0,len(groups),len(groups))
            idx=np.asarray([j for g in sampled for j in groups[g]])
            boot.append(float(np.mean(loss[idx])))
        out[first+'__vs__'+second]={
            'brier_delta_first_minus_second':round(float(np.mean(loss)),6),
            'race_bootstrap_95pct':[
                round(float(np.quantile(boot,.025)),6),
                round(float(np.quantile(boot,.975)),6)]}
    return out


def main():
    db=ROOT/'data'/'jravan.db'
    exr,exh=target_exclusions(ROOT/'data'/'research'/'forward'/'decisions.jsonl',db)
    d24,n24=race_records(db,2024)
    # Choose demotion threshold from the 2024 positive-delta upper quartile only.
    positive=sorted(r['delta'] for r in d24 if r['front_pred'] and r['delta']>0)
    threshold=max(3,int(np.quantile(positive,.75,method='higher'))) if positive else 3
    no_market_positive=sorted(r['nomarketrank']-r['p4rank'] for r in d24
                              if r['front_pred'] and r['nomarketrank']>r['p4rank'])
    no_market_threshold=max(3,int(np.quantile(no_market_positive,.75,method='higher')))
    d25,n25=race_records(db,2025)
    d26,n26=race_records(db,2026,exr,exh)
    result={'warning':'Final popularity is an untimed hindsight proxy, not a deployable pre-race feature.',
            'coverage':{'2024':n24,'2025':n25,'2026_excluding_examples':n26},
            'threshold_from_2024':threshold,
            '2024_exploration':aggregate(d24,threshold),
            '2025_holdout':aggregate(d25,threshold),
            '2026_excluding_examples':aggregate(d26,threshold),
            '2024_no_market_transition':no_market_transition(d24,no_market_threshold),
            '2025_no_market_transition':no_market_transition(d25,no_market_threshold),
            '2026_no_market_transition':no_market_transition(d26,no_market_threshold),
            '2024_exploratory_model_metrics':model_metrics(d24,d24),
            '2025_model_metrics':model_metrics(d24,d25),
            '2026_model_metrics':model_metrics(d24,d26),
            '2025_predicted_front_metrics':front_subset_metrics(d24,d25),
            '2026_predicted_front_metrics':front_subset_metrics(d24,d26),
            '2025_paired_bootstrap':paired_bootstrap(d24,d25),
            '2026_paired_bootstrap':paired_bootstrap(d24,d26)}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
