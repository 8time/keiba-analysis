"""Read-only PURE ABILITY vs hindsight-market diagnostic.

Current-race market inputs are excluded from the ability score. Historical
market uses *untimed final odds*, so comparisons involving MARKET are never
claimed to be point-in-time deployable or valid ROI evidence.
"""

from collections import defaultdict
from pathlib import Path
import json
import math
import sqlite3
import sys

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import pace_map as pm
from forward_retention_research import fit_logit,predict,report,race_bootstrap_delta,target_exclusions

DB=ROOT/'data/jravan.db'


def rank(values):
    return {u:i+1 for i,u in enumerate(sorted(values,key=lambda u:(values[u],u)))}


def records(year, excluded_races=frozenset(), excluded_horses=frozenset()):
    con=sqlite3.connect(DB.resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    races=con.execute("SELECT race_key,race_id,jyo,kyori,surface,shusso_tosu "
                      "FROM races WHERE year=? AND surface='芝' AND kyori=1200 "
                      "AND shusso_tosu>=8 ORDER BY race_key",(str(year),)).fetchall()
    out=[]; used=0; exclusions=defaultdict(int)
    for ra in races:
        if ra['race_id'] in excluded_races or ra['race_id']=='202606040911':
            exclusions['excluded_race']+=1;continue
        runners=con.execute("SELECT umaban,bamei,ketto_num,chakujun,corner4,"
                            "win_odds,ninki FROM results WHERE race_key=? AND umaban>0 "
                            "AND chakujun>0",(ra['race_key'],)).fetchall()
        if len(runners)<8 or any(not r['corner4'] or r['corner4']<=0 for r in runners):
            exclusions['missing_corner_or_finish']+=1;continue
        if any(not r['win_odds'] or not math.isfinite(r['win_odds']) or
               r['win_odds']<1.01 or r['win_odds']>1000 for r in runners):
            exclusions['missing_final_odds']+=1;continue
        horses=[{'umaban':r['umaban'],'name':r['bamei'],'score':.5,'style':'不明'}
                for r in runners]
        profiles=pm.fetch_jv_profiles([h['name'] for h in horses],max_runs=8,
                                      surface='芝',distance=1200,
                                      before_key=ra['race_key'][:8],read_only=True)
        if len(profiles)<6:
            exclusions['insufficient_history']+=1;continue
        for h in horses:
            p=profiles.get(h['name']) or {}
            h['score']=p.get('ten') if p.get('ten') is not None else .5
            h['style']=pm.style_from_score(h['score'])
        layout=pm.get_course_layout(pm.VENUE_CODES.get(str(ra['jyo']).zfill(2)),'芝',1200)
        ctx=pm.build_pace_context(horses,profiles,1200,'芝',layout)
        ability=pm.predict_finish(horses,profiles,ctx,extras={})
        diag_goal=pm.predict_finish(horses,profiles,ctx,
                                    {r['umaban']:{'pop':r['ninki']} for r in runners
                                     if r['ninki'] and r['ninki']>0})
        ar=rank(ability); gr=rank(diag_goal)
        odds={r['umaban']:float(r['win_odds']) for r in runners}
        overround=sum(1/v for v in odds.values())
        if not 1.0<=overround<=2.0:
            exclusions['implausible_final_overround']+=1;continue
        implied={u:(1/v)/overround for u,v in odds.items()}
        mr=rank({u:-v for u,v in implied.items()})
        k=math.ceil(len(runners)*.4)
        for r in runners:
            if r['ketto_num'] in excluded_horses:
                continue
            u=r['umaban']
            out.append({'race_id':ra['race_id'],'umaban':u,'horse_id':r['ketto_num'],
                        'top3':int(r['chakujun']<=3),'win':int(r['chakujun']==1),
                        'top5':int(r['chakujun']<=5),'ability_score':ability[u],
                        'market_score':-math.log(implied[u]),'market_win_norm':implied[u],
                        'final_odds':odds[u],'final_popularity':r['ninki'],
                        'ability_rank':ar[u],'market_rank':mr[u],
                        'diag_goal_rank':gr[u],'front_rank':rank(ctx['pos4'])[u],
                        'k':k,'overround':overround})
        used+=1
    con.close()
    return out,{'races':used,'horses':len(out),'exclusions':dict(exclusions)}


def fit_models(train):
    return {'ability':fit_logit(train,'top3',['ability_score']),
            'market':fit_logit(train,'top3',['market_score']),
            'combined':fit_logit(train,'top3',['ability_score','market_score'])}


def quantile_freeze(train,models):
    pa=predict(models['ability'],train); pmk=predict(models['market'],train)
    gap=pa-pmk
    return {'low':float(np.quantile(gap,.2)),
            'high':float(np.quantile(gap,.8)),
            'exploration_n':len(gap),
            'market_overround_median':float(np.median([r['overround'] for r in train]))}


def group_summary(rows,indices,pa,pmk):
    if len(indices)==0:return {'n':0}
    y=np.asarray([rows[i]['top3'] for i in indices]); win=np.asarray([rows[i]['win'] for i in indices])
    return {'n':len(indices),'races':len({rows[i]['race_id'] for i in indices}),
            'top3_rate':round(float(y.mean()),4),'ability_top3_mean':round(float(np.mean(pa[indices])),4),
            'market_top3_mean':round(float(np.mean(pmk[indices])),4),
            'top3_excess_vs_market':round(float(np.mean(y-pmk[indices])),4),
            'win_rate':round(float(win.mean()),4),
            'market_win_mean':round(float(np.mean([rows[i]['market_win_norm'] for i in indices])),4),
            'win_excess_vs_market':round(float(np.mean(win-np.array(
                [rows[i]['market_win_norm'] for i in indices]))),4),
            'avg_final_odds':round(float(np.mean([rows[i]['final_odds'] for i in indices])),2),
            'avg_final_popularity':round(float(np.mean([rows[i]['final_popularity'] for i in indices
                                                      if rows[i]['final_popularity']])),2)}


def assess(rows,train,models,freeze):
    p={name:np.asarray(predict(model,rows)) for name,model in models.items()}
    metrics={name:report(rows,'top3',v,topk=5) for name,v in p.items()}
    gap=p['ability']-p['market']
    idx={
        'ability_over_market_top20':[i for i,v in enumerate(gap) if v>=freeze['high']],
        'market_over_ability_bottom20':[i for i,v in enumerate(gap) if v<=freeze['low']],
        'middle60':[i for i,v in enumerate(gap) if freeze['low']<v<freeze['high']],
        'ability_top_market_lower_goal_demoted':[i for i,r in enumerate(rows)
                if r['ability_rank']<=r['k'] and r['market_rank']>r['k']
                and r['diag_goal_rank']>r['k']],
        'market_top_ability_lower':[i for i,r in enumerate(rows)
                if r['market_rank']<=r['k'] and r['ability_rank']>r['k']],
    }
    groups={name:group_summary(rows,np.asarray(ids,dtype=int),p['ability'],p['market'])
            for name,ids in idx.items()}
    # Evaluate a predeclared continuous gradient, not a fitted threshold search.
    bins=[]
    cuts=np.quantile(predict(models['ability'],train)-predict(models['market'],train),
                     [0,.2,.4,.6,.8,1])
    for j in range(5):
        ids=np.asarray([i for i,g in enumerate(gap) if
                        (cuts[j]<=g<cuts[j+1] or (j==4 and g==cuts[j+1]))],dtype=int)
        bins.append({'2024_frozen_gap_range':[round(float(cuts[j]),4),round(float(cuts[j+1]),4)],
                     **group_summary(rows,ids,p['ability'],p['market'])})
    bootstrap=race_bootstrap_delta(rows,'top3',p['market'],p['combined'],nboot=600)
    # Cluster bootstrap of the selected residual; uses frozen selection only.
    rng=np.random.default_rng(20260929)
    residual={}
    for label in ('ability_over_market_top20','market_over_ability_bottom20'):
        selected=idx[label]
        by_race=defaultdict(list)
        for i in selected:by_race[rows[i]['race_id']].append(i)
        keys=list(by_race)
        if not keys:continue
        y=np.asarray([r['top3'] for r in rows])
        sim=[]
        for _ in range(600):
            ids=[i for rj in rng.integers(0,len(keys),len(keys)) for i in by_race[keys[rj]]]
            sim.append(float(np.mean(y[ids]-p['market'][ids])))
        residual[label]={'cluster_bootstrap_excess_top3_ci95':
                         [round(float(v),5) for v in np.quantile(sim,[.025,.975])]}
    return {'metrics':metrics,'gap_groups':groups,'frozen_quintiles':bins,
            'combined_vs_market_paired_bootstrap':bootstrap,
            'selected_residual_bootstrap':residual}


def main():
    d24,c24=records(2024)
    models=fit_models(d24)
    freeze=quantile_freeze(d24,models)
    # Only now evaluate 2025, then determine exclusions for 2026.
    d25,c25=records(2025)
    r25=assess(d25,d24,models,freeze)
    exr,exh=target_exclusions(ROOT/'data/research/forward/decisions.jsonl',DB)
    d26,c26=records(2026,exr,exh)
    r26=assess(d26,d24,models,freeze)
    print(json.dumps({'status':'hindsight_market_diagnostic_only',
                      'warning':'2024/25 odds are untimed final prices, not valid for ROI or deployment.',
                      'coverage':{'2024':c24,'2025':c25,'2026_excluding_examples':c26},
                      'freeze_2024':freeze,
                      'exploration_2024':assess(d24,d24,models,freeze),
                      'holdout_2025':r25,'additional_2026':r26},ensure_ascii=False))


if __name__=='__main__':main()
