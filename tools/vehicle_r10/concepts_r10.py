#!/usr/bin/env python3
"""ASSET-VEHICLES round 10 (003 boxy rectangular APC, 021 garbage truck with ribbed hopper, 029 Isetta with long roof, 069 Model AA with slatted crate; copy of concepts_r9). Round 9: briefs from each sprite's identity (003 Saracen APC, 004 1950s armoured van, 019 GT40, 022 jeep with gun, 052 1960s SWAT truck, 071 Road Runner stripes, 005 rounded BMW 503); copy of concepts_r8. CAR-ERA round 8 (era fix for 047/048 Meteor: a 1960s mid-engine coupe instead of a 1980s wedge/hatch; copy of concepts_r7) concepts for the models that still ship v1 and have no clean round-5 candidate: briefs
tuned to the body type (a cab with a taller box, a garbage truck with its hopper, a van with a roof sign,
an armoured car with a turret ...), two wordings (A, B) x seeds, every try checked with concepts_v3.qc
(+ the DINOv2 front-view test for car classes) as in round 5. Tries: concept/r6try/<stem>_<w><seed>.png,
checks concept/r6_qc.json.      concepts_r6.py --models 4,7 [--seeds 3] [--seed0 61] [--words A,B]"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import concepts_v3 as c3
import concepts_r5 as r5
import car_pipeline as v1
from PIL import Image
sys.path.insert(0, os.path.join(HERE, '..', 'repo', 'tools'))
import nose_from_concept as nfc

ROOT = c3.ROOT; OUT = c3.OUT
VIEW = r5.VIEW; TAIL = r5.TAIL
NEG = ("modern car, 2000s, 2010s, 2020s supercar, modern sports car, Lamborghini, Viper, angular, LED headlights, black alloy wheels, matte paint, "
       "rear view, " + r5.NEG)  # the era terms first: SDXL keeps only 77 tokens
# (subject A, subject B, subject C, colour, details) -- each prompt under CLIP's 77 tokens; sprite paint = copper bronze
BRIEF = {
    3: ("1960s Cadillac Gage V-100 Commando armoured car, a perfectly rectangular boxy slab-sided hull with a flat roof and two round roof hatches side by side",
        "boxy rectangular military armoured personnel carrier, square corners, flat top deck, two circular hatch rings, four big wheels, blunt vertical nose",
        "1950s Cold War riot-control armoured truck, rectangular steel box hull, flat roof with two hatches and exhaust stacks at the back, square cab windows",
        "olive drab green", "two small square windows at the front, rear exhaust stacks, steel wheels, no turret, no gun"),
    21: ("1950s rear-loading garbage truck, long open-topped compactor body with a ribbed black grille roof and a rear hopper, small bluff cab",
         "classic 1950s American refuse truck, rust-brown cab, long rectangular ribbed hopper body behind it, chrome grille",
         "vintage dustcart with a tall ribbed rear loader body, dented brown paint, slatted top, chrome bumper",
         "rusty brown and tan", "round headlamps, chrome bumper, steel wheels, dirty and weathered"),
    29: ("1956 BMW Isetta bubble car with a long folding fabric roof over the whole body, tiny headlamps and chrome bumpers",
         "classic 1950s Isetta 300 microcar, egg-shaped body, long cream canvas sunroof, round front door",
         "1955 Isetta bubble microcar, narrow rear track, two small round headlamps, smooth rounded one-box shell",
         "cream and copper bronze", "chrome bumper, tiny wheels, large round headlamps"),
    69: ("1931 Ford Model AA flatbed truck with a tall slatted dark wooden cargo crate on the open bed",
         "classic 1930s utility truck, small upright cab, tall black louvred cargo box filling the whole rear bed",
         "vintage 1930s Chevrolet pickup, short cab, big black slatted wooden crate covering the bed, chrome headlamps",
         "tan and rusty copper", "round chrome headlamps on stalks, running boards, spoked wheels"),
}


def prompt(m, w):
    a, b, c, col, det = BRIEF[m]
    subj = {'A': a, 'B': b, 'C': c}[w]
    return f"studio photograph of one single {col} {subj}, {VIEW}, {TAIL}, {det}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', required=True); ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--seed0', type=int, default=71); ap.add_argument('--words', default='A,B,C')
    a = ap.parse_args()
    import torch, rembg, gen_concept
    cars = {c['model']: c for c in json.load(open(os.path.join(ROOT, 'catalog.json')))['cars']}
    tdir = os.path.join(OUT, 'r10try'); os.makedirs(tdir, exist_ok=True)
    qcp = os.path.join(OUT, 'r10_qc.json')
    allqc = json.load(open(qcp)) if os.path.exists(qcp) else {}
    c3.wait_gpu(torch, 9.0)
    pipe = gen_concept.build_pipe()
    session = rembg.new_session('u2net')
    for m in [int(x) for x in a.models.split(',')]:
        car = cars[m]; stem = f"{m:03d}_{v1.slug(car['name'])}"
        pal = c3.sprite_palette(car)
        for seed in range(a.seed0, a.seed0 + a.seeds):
            for w in a.words.split(','):
                key = f"{stem}_{w}{seed}"
                if key in allqc and os.path.exists(os.path.join(tdir, key + '.png')):
                    continue
                p = prompt(m, w)
                c3.wait_gpu(torch, float(os.environ.get("R10_FREE_GB", "3.0")))  # the L4 is shared with game runs
                g = torch.Generator('cuda').manual_seed(seed)
                im = pipe(prompt=p, negative_prompt=NEG, num_inference_steps=30, guidance_scale=6.0, generator=g,
                          height=1024, width=1024).images[0]
                r, cut = c3.qc(im, session, pal)
                if car['cls'] in nfc.CAR_CLASSES and os.path.exists(nfc.PROTOS) and 'single' in r:
                    bg = Image.new('RGBA', cut.size, nfc.BG + (255,)); bg.alpha_composite(cut)
                    Fm, Rm = nfc._protos(); e = nfc._embed([nfc._square(bg)])[0]
                    r['front'] = float(e @ Fm - e @ Rm)
                    if r['front'] < 0.0:
                        r['score'] *= 0.3
                im.save(os.path.join(tdir, key + '.png'))
                r.update(prompt=p, seed=seed, words=w)
                allqc[key] = r
                json.dump(allqc, open(qcp, 'w'), indent=1)
                print(f"{key}: score {r['score']:.2f}", flush=True)
        torch.cuda.empty_cache()


if __name__ == '__main__':
    main()
