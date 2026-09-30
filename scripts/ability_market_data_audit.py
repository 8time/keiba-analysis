"""Read-only inventory of timestamped market snapshots and JV outcomes."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import json
import sqlite3

ROOT=Path(__file__).resolve().parents[1]


def read_market(cutoff_minutes=10):
    con=sqlite3.connect((ROOT/'data/odds_history.db').resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    rows=con.execute("SELECT race_id,umaban,odds_type,odds_value,timestamp,phase FROM odds_logs").fetchall()
    con.close()
    by_race=defaultdict(list)
    for r in rows:
        by_race[r['race_id']].append(dict(r))
    con=sqlite3.connect((ROOT/'data/jravan.db').resolve().as_uri()+'?mode=ro',uri=True)
    con.row_factory=sqlite3.Row
    races={r['race_id']:dict(r) for r in con.execute(
        "SELECT race_id,year,monthday,jyo,kyori,surface,hasso_time,shusso_tosu "
        "FROM races WHERE year='2026'")}
    out=[]; exclusions=Counter(); phases=Counter()
    for rid,lines in by_race.items():
        race=races.get(rid)
        if not race:
            exclusions['no_jv_race']+=1;continue
        try:
            date=datetime.strptime(race['year']+str(race['monthday']).zfill(4)+
                                   str(race['hasso_time']).zfill(4),'%Y%m%d%H%M')
        except (TypeError,ValueError):
            exclusions['bad_start']+=1;continue
        cutoff=date-timedelta(minutes=cutoff_minutes)
        selected={}
        for r in lines:
            if r['odds_type'] not in ('win','pop') or not r['timestamp']:
                continue
            try:
                ts=datetime.fromisoformat(r['timestamp'])
            except ValueError:
                continue
            if ts>cutoff:
                continue
            o=r['odds_value']
            if o is None or o<=0 or (r['odds_type']=='pop' and o>40) or (r['odds_type']=='win' and o>1000):
                continue
            key=(r['umaban'],r['odds_type'])
            if key not in selected or ts>selected[key]['ts']:
                selected[key]={'value':o,'ts':ts,'phase':r['phase']}
        wins={u:x for (u,t),x in selected.items() if t=='win'}
        pops={u:x for (u,t),x in selected.items() if t=='pop'}
        for x in selected.values():phases[str(x['phase'])]+=1
        n=race['shusso_tosu'] or 0
        if len(wins)<max(8,n-2):
            exclusions['insufficient_win_coverage']+=1;continue
        result=con.execute("SELECT umaban,ketto_num,chakujun,win_odds,ninki "
                           "FROM results WHERE race_id=? AND umaban>0",(rid,)).fetchall()
        if len(result)<8:
            exclusions['insufficient_results']+=1;continue
        out.append({'race_id':rid,'date':date.isoformat(),'surface':race['surface'],
                    'distance':race['kyori'],'runners':len(result),'wins':len(wins),
                    'pops':len(pops),'earliest_log':min(x['ts'] for x in selected.values()).isoformat(),
                    'latest_log':max(x['ts'] for x in selected.values()).isoformat(),
                    'overround':round(sum(1/x['value'] for x in wins.values()),4),
                    'margin_to_start_minutes':round((date-max(x['ts'] for x in selected.values())).total_seconds()/60,1)})
    con.close()
    by_month=Counter(x['date'][:7] for x in out)
    by_surface_distance=Counter((x['surface'],x['distance']) for x in out)
    return {'cutoff_minutes':cutoff_minutes,'raw_rows':len(rows),'raw_races':len(by_race),
            'eligible_races':len(out),'eligible_months':dict(sorted(by_month.items())),
            'eligible_surface_distance':{f'{k[0]}{k[1]}':v for k,v in by_surface_distance.items()},
            'exclusions':dict(exclusions),'phase_of_latest_rows':dict(phases),
            'races':sorted(out,key=lambda x:x['date'])}


if __name__=='__main__':
    print(json.dumps(read_market(),ensure_ascii=False))
