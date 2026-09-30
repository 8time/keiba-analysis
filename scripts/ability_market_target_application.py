"""Apply 2024-frozen research formulas to timestamped target inputs only.

No target race result, payout, or post-race cache is read.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import math
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core import pace_map as pm
from core import value_hunter as vh
from ability_market_separation_audit import records,fit_models,quantile_freeze,rank
from forward_retention_research import predict

RACE='202606040911'
START=datetime(2026,9,27,15,40,tzinfo=timezone(timedelta(hours=9)))


def snapshot(kind):
    choices=[]
    with (ROOT/'data/research/forward/decisions.jsonl').open(encoding='utf-8') as f:
        for line in f:
            if f'"race_id": "{RACE}"' not in line:continue
            d=json.loads(line)
            if d.get('rule_version')!=kind:continue
            try:at=datetime.fromisoformat(d['captured_at'])
            except (TypeError,ValueError):continue
            if at<START:choices.append(d)
    if not choices:raise RuntimeError(f'No pre-race {kind} snapshot')
    return min(choices,key=lambda x:x['captured_at'])


def main():
    # All choices are frozen on 2024 before opening the target snapshot.
    train,_=records(2024)
    models=fit_models(train)
    freeze=quantile_freeze(train,models)
    live=snapshot('live_sra_observe')
    playbook=snapshot('production_playbook_observe')
    raw=live['horses']
    profiles=pm.fetch_jv_profiles([h['name'] for h in raw],max_runs=8,
                                  surface='芝',distance=1200,before_key='20260927',
                                  read_only=True)
    horses=[]; extras={}; odds={}
    for h in raw:
        u=h['umaban']
        prof=profiles.get(h['name']) or {}
        score=prof.get('ten') if prof.get('ten') is not None else .5
        horses.append({'umaban':u,'name':h['name'],'score':score,
                       'style':pm.style_from_score(score)})
        o=h.get('decision_time_odds')
        if isinstance(o,(int,float)) and math.isfinite(o) and o>1:
            odds[u]=float(o)
        ex={}
        if isinstance(h.get('battle_score'),(int,float)):
            ex['power']=-h['battle_score']
        pop=h.get('decision_time_popularity')
        if isinstance(pop,(int,float)) and 0<pop<99:
            ex['pop']=pop
        extras[u]=ex
    if len(odds)!=len(raw):raise RuntimeError('Target odds snapshot is incomplete')
    layout=pm.get_course_layout(pm.VENUE_CODES.get('06'),'芝',1200)
    ctx=pm.build_pace_context(horses,profiles,1200,'芝',layout)
    ability=pm.predict_finish(horses,profiles,ctx,extras={})
    partial_goal=pm.predict_finish(horses,profiles,ctx,extras)
    ar=rank(ability); mr=rank({u:odds[u] for u in odds}); gr=rank(partial_goal)
    overround=sum(1/x for x in odds.values())
    vh_scores={h['umaban']:h.get('vh_score') for h in playbook['horses']
               if isinstance(h.get('vh_score'),(int,float))}
    candidate_vh=sorted([h for h in raw if h.get('decision_time_popularity',99)>=6
                         and h['umaban'] in vh_scores],
                        key=lambda h:-vh_scores[h['umaban']])
    vr={h['umaban']:i+1 for i,h in enumerate(candidate_vh)}
    model_rows=[]
    for h in raw:
        u=h['umaban']
        model_rows.append({'ability_score':ability[u],
                           'market_score':-math.log((1/odds[u])/overround)})
    pa=predict(models['ability'],model_rows)
    pmk=predict(models['market'],model_rows)
    pc=predict(models['combined'],model_rows)
    out=[]
    for i,h in enumerate(raw):
        u=h['umaban'];gap=float(pa[i]-pmk[i]);v=vh_scores.get(u)
        out.append({'umaban':u,'name':h['name'],
                    'ability_probability_proxy':round(float(pa[i]),4),
                    'market_top3_probability_proxy':round(float(pmk[i]),4),
                    'combined_probability_proxy':round(float(pc[i]),4),
                    'ability_minus_market':round(gap,4),
                    'frozen_ability_over_market_top20':gap>=freeze['high'],
                    'ability_rank':ar[u],'market_odds_rank':mr[u],
                    'existing_goal_partial_rank':gr[u],
                    'pre_race_popularity':h.get('decision_time_popularity'),
                    'pre_race_odds':odds[u],
                    'vh_snapshot_score':v,'vh_rank_among_pop6plus':vr.get(u),
                    'vh_current_param_tier_proxy':(
                        vh.tier(v) if v is not None and
                        h.get('decision_time_popularity',99)>=6 else None),
                    'jv_history_count':(profiles.get(h['name']) or {}).get('n_runs',0)})
    print(json.dumps({'race_id':RACE,'start':START.isoformat(),
                      'ability_model_train':'2024-JV-turf1200',
                      'market_model_train':'2024-untimed-final-odds-DIAGNOSTIC',
                      'source_warning':'JV stops 2026-06-21; live AvgAgari/Suitability/position_score_map unavailable; existing goal rank is partial pre-race replay; VH version not stored.',
                      'market_overround_at_snapshot':round(overround,4),
                      'frozen_thresholds':freeze,'live_captured_at':live['captured_at'],
                      'vh_captured_at':playbook['captured_at'],
                      'horses':sorted(out,key=lambda x:x['umaban'])},ensure_ascii=False))


if __name__=='__main__':main()
