#!/usr/bin/env python3
"""CAR-ERA round 8 (copy of fit_r7.py; candidates raw/<stem>_r10_*.glb with their concept from r8/jobs*.json, output models3d_r10) -- CAR-QUALITY-7 (copy of fit_r6.py for the era-fix candidates of 047/048/083, output models3d_r7) -- CAR-QUALITY-6 (copy of fit_r5.py for the round-6 candidates, output models3d_r6) -- CAR-QUALITY-5 fit + score for any list of candidates (raw TRELLIS GLB + the concept it came from).
Same steps as car_pipeline2.py --stage fit --tag v3c (drop debris, bilateral delight, side balance,
roof-only sprite, concept-based nose check and turn, scorer), plus --balance-vertical and --roof-norm
(the round-5 roof/flank fix). Each candidate's fit goes to models3d_r5/fit/<stem>__<cand>.glb with a
five-view render in models3d_r5/proof/<stem>__<cand>.png; scores in models3d_r5/r5_status.json.

    fit_r5.py --models 5,31 [--sources r5,v3] [--redo]
      r5: raw/<stem>_r5_<key>.glb made from concept/r5try/<stem>_<key>.png
      v3: the CQ4 candidates raw/<stem>_v3c<k>.glb (concept: concept/<stem>_3q_v3.png), refitted
"""
import argparse, glob, json, os, re, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import car_pipeline as v1
from car_pipeline2 import LIVERY_MODELS, log_run, pick_key
TOOLS = os.path.join(HERE, '..', 'repo', 'tools'); sys.path.insert(0, TOOLS)
ROOT = os.path.abspath(os.path.join(HERE, '..', 'assets-src', 'cars'))
V2 = os.path.join(ROOT, 'models3d_v2'); R5 = os.path.join(ROOT, 'models3d_r10')
CAT = os.path.join(ROOT, 'catalog.json')


def _concepts():
    m = {}
    for j in glob.glob(os.path.join(HERE, 'r10', 'jobs*.json')):
        for job in json.load(open(j)):
            m[os.path.basename(job['out'])] = job['imgs'][0]
    return m


def candidates(stem, sources):
    out = []; cm = _concepts()
    for g in sorted(glob.glob(os.path.join(V2, 'raw', f"{stem}_r10_*.glb"))):
        key = re.match(rf"{stem}_r10_(.+)\.glb", os.path.basename(g)).group(1)
        if os.path.basename(g) in cm:
            out.append((f"r10{key}", g, cm[os.path.basename(g)]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True); ap.add_argument('--sources', default='r10')
    ap.add_argument('--only', default=None, help='candidate names to (re)fit, comma list'); ap.add_argument('--redo', action='store_true')
    ap.add_argument('--faces', type=int, default=8000); ap.add_argument('--no-vertical', action='store_true')
    a = ap.parse_args()
    import score_car_model as scorer, nose_from_concept as nfc
    cars = {c['model']: c for c in json.load(open(CAT))['cars']}
    for sub in ('fit', 'proof'):
        os.makedirs(os.path.join(R5, sub), exist_ok=True)
    sp = os.path.join(R5, 'r10_status.json')
    py = sys.executable
    for m in [int(x) for x in a.models.split(',')]:
        car = cars[m]; stem = f"{m:03d}_{v1.slug(car['name'])}"
        for name, raw, concept in candidates(stem, a.sources.split(',')):
            if a.only and name not in a.only.split(','):
                continue
            st = json.load(open(sp)) if os.path.exists(sp) else {}
            if name in st.get(str(m), {}) and not a.redo and 'error' not in st[str(m)][name]:
                continue
            if time.time() - os.path.getmtime(raw) < 30:      # TRELLIS may still be writing it
                continue
            fitted = os.path.join(R5, 'fit', f"{stem}__{name}.glb"); render = os.path.join(R5, 'proof', f"{stem}__{name}.png")
            def cmd(nose):
                return ([py, os.path.join(TOOLS, 'make_car_model.py'), raw, fitted, '--catalog', CAT, '--model', str(m),
                         '--faces', str(a.faces), '--render', render, '--nose', nose, '--delight', '--no-livery', '--balance-sides',
                         '--roof-only', '0.8'] + (['--no-paint-match'] if m in LIVERY_MODELS else [])
                        + ([] if a.no_vertical else ['--balance-vertical', '--roof-norm']))
            t0 = time.time()
            try:
                flog = []
                log_run(cmd('auto'), flog)
                nose = nfc.check(fitted, concept, car['cls'])
                if nose['backwards']:
                    turned = any('turned nose to +z' in l for l in flog)
                    flog = []
                    log_run(cmd('keep' if turned else 'flip'), flog)
                    nose2 = nfc.check(fitted, concept, car['cls'])
                    nose = dict(nose2, flipped_from=nose)
                sc = scorer.score(fitted, car, ROOT)
                sc.update(nose=nose, candidate=name, raw=os.path.relpath(raw, ROOT), concept=os.path.relpath(concept, ROOT),
                          log=[l for l in flog if any(k in l for k in ('delight', 'sides', 'vertical', 'roof', 'debris', 'paint'))])
                print(f"fit {stem} {name}: total {sc['total']:.3f} lighting {sc['lighting']:.2f} texture {sc['texture']:.2f} "
                      f"nose_front {nose.get('nose_front', 0):.2f}{' TURNED' if 'flipped_from' in nose else ''}{' BACKWARDS' if nose.get('backwards') else ''} "
                      f"({time.time()-t0:.0f}s)", flush=True)
            except Exception as e:  # noqa
                sc = dict(total=0.0, error=str(e)[:200], candidate=name)
                print(f"fit {stem} {name} FAILED {str(e)[:160]}", flush=True)
            st = json.load(open(sp)) if os.path.exists(sp) else {}
            st.setdefault(str(m), {})[name] = sc
            json.dump(st, open(sp, 'w'), indent=1)


if __name__ == '__main__':
    main()
