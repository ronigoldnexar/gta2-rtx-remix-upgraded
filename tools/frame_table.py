#!/usr/bin/env python3
"""Frame-time table of a run from its per-frame log (FIX-PERF-2).
  python3 tools/frame_table.py out/<run> [out/<run2> ...] [-v]
Needs the run made with -e 'GTA2DX9_FRAME_LOG=Z:\\out\\frames.tsv'. Frames after the level load (the longest
frame of the first 400), whole-frame percentiles, counts over 40/50/100/250 ms, phase averages/worsts, per view
(0 classic, 1 third, 2 first), and the number of 'hitch @' lines in gta2dx9.log. -v: every frame over 50 ms
with its three largest phases and the resources created in it."""
import csv,sys,re,os,statistics as st
VERBOSE = '-v' in sys.argv
def load(run):
    rows=list(csv.DictReader(open(f'{run}/frames.tsv'),delimiter='\t'))
    out=[]
    for r in rows:
        try: out.append({k:float(v) for k,v in r.items() if v not in (None,'')})
        except ValueError: pass
    return out
for run in [a for a in sys.argv[1:] if a != '-v']:
    R=load(run)
    # level start: the frame after the longest frame in the first 300 (the level load)
    first=R[:400]; i0=max(range(len(first)),key=lambda i:first[i]['whole'])+1
    P=R[i0:]
    w=[r['whole'] for r in P]
    ph=['game','pre','world','spr_loop','cars','peds','props','effects','ui','present','wait','pre_camera']
    log=open(f'{run}/gta2dx9.log',errors='replace').read() if os.path.exists(f'{run}/gta2dx9.log') else ''
    hl=len(re.findall(r'hitch @',log)); hf=len(re.findall(r'hitch @\d+: frame',log))
    q=sorted(w)
    print(f"== {os.path.basename(run)}: frames {len(P)} after the level load (load frame {R[i0-1]['whole']:.0f} ms) | 'hitch' lines {hl} (frame lines {hf})")
    print(f"   whole avg {st.mean(w):.1f} p50 {q[len(q)//2]:.1f} p99 {q[int(len(q)*.99)]:.1f} p99.9 {q[int(len(q)*.999)]:.1f} worst {q[-1]:.1f} | >40ms {sum(x>40 for x in w)} >50ms {sum(x>50 for x in w)} >100ms {sum(x>100 for x in w)} >250ms {sum(x>250 for x in w)}")
    print('   phase avg/worst: '+'  '.join(f"{p} {st.mean(r.get(p,0) for r in P):.2f}/{max(r.get(p,0) for r in P):.1f}" for p in ph))
    for v in (0,1,2):
        V=[r for r in P if r.get('view')==v]
        if V: 
            ww=[r['whole'] for r in V]; print(f"   view {v}: frames {len(V)} >50ms {sum(x>50 for x in ww)} worst {max(ww):.1f}")
    if VERBOSE:
        for r in P:
            if r['whole']>50:
                top=sorted(((r.get(p,0),p) for p in ph if p not in('wait',)),reverse=True)[:3]
                print(f"     f{int(r['frame'])} t{r['t_ms']/1000:.1f}s {r['whole']:.0f}ms view{int(r['view'])} drv{int(r['driving'])} "+' '.join(f"{p}={x:.0f}" for x,p in top)+f" tex_created={int(r['tex_created'])} vb={int(r['vb_created'])} uploads={int(r['tex_uploads'])} new_poses={int(r['new_poses'])}")
