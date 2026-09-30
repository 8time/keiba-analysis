import sys, sqlite3,random,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from core import pace_map as pm
def corr(p,a):
    us=sorted(p.keys() & a.keys())
    def rank(d):
        return [sum(d[v]<d[u] for v in us)+(sum(d[v]==d[u] for v in us)-1)/2 for u in us]
    x,y=rank(p),rank(a); mx=sum(x)/len(x);my=sum(y)/len(y)
    den=math.sqrt(sum((v-mx)**2 for v in x)*sum((v-my)**2 for v in y))
    return sum((v-mx)*(w-my) for v,w in zip(x,y))/den if den else 0
con=sqlite3.connect(f'file:{root / "data/jravan.db"}?mode=ro',uri=True)
report={}
for year in ['2024','2025']:
    races=con.execute('select race_key,kyori,surface,jyo from races where year=? and shusso_tosu>=8',(year,)).fetchall()
    random.Random(934).shuffle(races)
    values={k:[] for k in ['old','phase_half','phase_full']}
    used=0
    for rk,dist,surf,jyo in races:
        rows=con.execute('select umaban,bamei,corner1,corner2,corner3,corner4 from results where race_key=? and chakujun>0',(rk,)).fetchall()
        if len(rows)<8 or sum(bool(r[4]) for r in rows)<6: continue
        hs=[dict(umaban=r[0],name=r[1],score=None) for r in rows]
        prof=pm.fetch_jv_profiles([h['name'] for h in hs],max_runs=8,surface=surf,distance=dist,before_key=rk[:8])
        if len(prof)<6:continue
        ctx=pm.build_pace_context(hs,prof,dist,surf,pm.get_course_layout(pm.VENUE_CODES.get(str(jyo).zfill(2)),surf,dist))
        for k,w in [(1,.5),(2,.78),(3,.93)]:
            actual={r[0]:r[k+1] for r in rows if r[k+1]}
            if len(actual)<6:continue
            old={h['umaban']:(1-w)*ctx['forward'][h['umaban']]+w*ctx['pos4'][h['umaban']] for h in hs}
            full={h['umaban']:prof.get(h['name'],{}).get('c'+str(k)) for h in hs}
            full={u:(v if v is not None else old[u]) for u,v in full.items()}
            half={u:(full[u]+old[u])/2 for u in full}
            for name,p in [('old',old),('phase_half',half),('phase_full',full)]:values[name].append(corr(p,actual))
        used+=1
        if used>=300:break
    report[year]={'races':used,'phase_samples':len(values['old']),**{k:round(sum(v)/len(v),5) for k,v in values.items()}}
    print(json.dumps({year:report[year]}),flush=True)
# JSON results are printed to stdout; source database is read-only.
