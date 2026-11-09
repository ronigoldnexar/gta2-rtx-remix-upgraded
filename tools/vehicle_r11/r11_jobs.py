#!/usr/bin/env python3
"""ASSET-VEHICLES round 11: TRELLIS jobs for picked concepts.  r8_jobs.py picks.json out_jobs.json [--seed2]
picks.json: {"83": ["r7try/A71", "r7try/C71"], "47": ["r8try/A81"]}: concept dir under models3d_v2/concept, key;
raw output raw/<stem>_r11_<dir-tag><key>.glb (dir-tag = 'p' for r7try, '' for r8try); the first pick also gets seed 2."""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import car_pipeline as v1
ROOT = os.path.join(HERE, '..', 'assets-src', 'cars'); V2 = os.path.join(ROOT, 'models3d_v2')
cars = {c['model']: c for c in json.load(open(os.path.join(ROOT, 'catalog.json')))['cars']}
picks = json.load(open(sys.argv[1])); jobs = []
for m, keys in picks.items():
    stem = f"{int(m):03d}_{v1.slug(cars[int(m)]['name'])}"
    for i, dk in enumerate(keys):
        d, k = dk.split('/')
        img = os.path.abspath(os.path.join(V2, 'concept', d, f"{stem}_{k}.png"))
        tag = ('p' if d == 'r7try' else '') + k
        jobs.append(dict(out=os.path.abspath(os.path.join(V2, 'raw', f"{stem}_r11_{tag}.glb")), imgs=[img], seed=1, faces=8000))
        if i == 0 and '--seed2' in sys.argv:
            jobs.append(dict(out=os.path.abspath(os.path.join(V2, 'raw', f"{stem}_r11_{tag}_s2.glb")), imgs=[img], seed=2, faces=8000))
json.dump(jobs, open(sys.argv[2], 'w'), indent=1); print(len(jobs), 'jobs')
