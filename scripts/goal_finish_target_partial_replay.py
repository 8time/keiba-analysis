"""Partial, read-only pre-race replay after the audit model/threshold freeze.

Only a timestamped forward snapshot and pre-race JV history are read. This is
deliberately not labelled as a full SRA replay: live AvgAgari, Suitability,
position_score_map, and the actual stored pre-race finish are unavailable.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import pace_map as pm

ROOT = Path(__file__).resolve().parents[1]
RACE = '202606040911'
SNAPSHOT = ROOT / 'data/research/forward/decisions.jsonl'


def main():
    with SNAPSHOT.open(encoding='utf-8') as f:
        choices = [json.loads(line) for line in f if f'"race_id": "{RACE}"' in line]
    choices = [x for x in choices if x.get('rule_version') == 'live_sra_observe'
               and x.get('captured_at', '') < '2026-09-27']
    if not choices:
        raise RuntimeError('No independently timestamped pre-race snapshot')
    snap = min(choices, key=lambda x:x['captured_at'])
    raw=snap['horses']
    profiles=pm.fetch_jv_profiles([h['name'] for h in raw], max_runs=8,
                                   surface='芝', distance=1200,
                                   before_key='20260927', read_only=True)
    horses=[]; extras={}
    for h in raw:
        prof=profiles.get(h['name']) or {}
        score=prof.get('ten') if prof.get('ten') is not None else .5
        horses.append({'umaban':h['umaban'],'name':h['name'],'score':score,
                       'style':pm.style_from_score(score)})
        ex={}
        if isinstance(h.get('battle_score'),(float,int)):
            ex['power']=-h['battle_score']
        if isinstance(h.get('decision_time_popularity'),(float,int)):
            ex['pop']=h['decision_time_popularity']
        extras[h['umaban']]=ex
    layout=pm.get_course_layout(pm.VENUE_CODES.get('06'),'芝',1200)
    ctx=pm.build_pace_context(horses,profiles,1200,'芝',layout)
    finish=pm.predict_finish(horses,profiles,ctx,extras)
    pr={u:i+1 for i,u in enumerate(sorted(ctx['pos4'],key=lambda u:(ctx['pos4'][u],u)))}
    fr={u:i+1 for i,u in enumerate(sorted(finish,key=lambda u:(finish[u],u)))}
    shadow=pm.predict_finish_shadow(horses,profiles,ctx,extras,
                                     popularity={u:e['pop'] for u,e in extras.items() if 'pop' in e})
    data=[]
    for h in raw:
        u=h['umaban']
        data.append({'umaban':u,'name':h['name'],
                     'snapshot_popularity':h.get('decision_time_popularity'),
                     'snapshot_battle_score':h.get('battle_score'),
                     'partial_pos4_rank':pr[u],'partial_goal_rank':fr[u],
                     'partial_rank_change':fr[u]-pr[u],
                     'partial_score':finish[u],
                     'contributions':shadow['contributions'][u],
                     'jv_history_runs':(profiles.get(h['name']) or {}).get('n_runs',0)})
    print(json.dumps({'race_id':RACE,'captured_at':snap['captured_at'],
                      'snapshot_code_version':snap.get('code_version'),
                      'status':'partial_pre_race_replay_not_full_SRA',
                      'missing':['live_AvgAgari','live_Suitability',
                                 'live_position_score_map','pre_race_finish_snapshot'],
                      'jv_last_available':'2026-06-21',
                      'horses':sorted(data,key=lambda x:x['umaban'])},
                     ensure_ascii=False))


if __name__=='__main__':
    main()
