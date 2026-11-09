#!/usr/bin/env python3
"""ASSET-VEHICLES round 11 (003 boxy rectangular APC, 021 garbage truck with ribbed hopper, 029 Isetta with long roof, 069 Model AA with slatted crate; copy of concepts_r9). Round 9: briefs from each sprite's identity (003 Saracen APC, 004 1950s armoured van, 019 GT40, 022 jeep with gun, 052 1960s SWAT truck, 071 Road Runner stripes, 005 rounded BMW 503); copy of concepts_r8. CAR-ERA round 8 (era fix for 047/048 Meteor: a 1960s mid-engine coupe instead of a 1980s wedge/hatch; copy of concepts_r7) concepts for the models that still ship v1 and have no clean round-5 candidate: briefs
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
       "rear view, back of the vehicle, turret, gun barrel, cannon, " + r5.NEG)  # the era terms first: SDXL keeps only 77 tokens
# (subject A, subject B, subject C, colour, details) -- each prompt under CLIP's 77 tokens; sprite paint = copper bronze
BRIEF = {
    3: ("1960s boxy olive green armoured security truck, flat roof with exactly two plain round hatch lids side by side and nothing else on the roof, big square glazed windscreen, slab sides",
        "armoured cash-in-transit truck painted olive drab, perfectly rectangular steel body, flat smooth roof with two flat circular hatches, low wide windscreen, no weapons",
        "rectangular olive green riot-police armoured van, square corners, flat roof with two round hatches, wide glazed cab at the front, rear exhaust pipes",
        "olive drab green", "four chunky wheels, steel bumper, no turret, no gun, no cannon, no machine gun, unarmed"),
    21: ("1950s refuse truck in rusty copper brown, small cab, long open-top rear body full of light tan wooden bins and ribbed tan panels, seen from the front",
         "classic 1950s dustcart, copper-brown paint, long open hopper full of tan crates and light corrugated panels, chrome grille",
         "vintage copper brown garbage truck, open rear bed stacked with beige bins, light tan ribbed top, round headlamps",
         "rusty copper brown and tan", "round headlamps, chrome bumper, steel wheels, weathered"),
    29: ("1956 BMW Isetta bubble car in tan sandy bronze paint, long tan fabric roof of the very same tan colour as the body, tiny headlamps",
         "classic 1950s Isetta 300 microcar fully painted tan copper, one-colour tan body and tan canvas roof, round front door",
         "1955 Isetta bubble microcar, warm tan beige bronze all over including the roof, chrome bumper",
         "tan beige copper", "chrome bumper, tiny wheels, large round headlamps, no white paint, no black roof"),
    69: ("1931 Ford Model AA truck, tan copper cab, and a tall black louvred box with horizontal dark slats covering the whole rear bed, front three-quarter view of the cab",
         "classic 1930s utility truck seen from the front, small tan cab, large black slatted box body with horizontal louvres behind the cab, chrome headlamps",
         "vintage 1930s pickup, copper tan cab, black corrugated louvred box on the bed, seen from the front left",
         "tan and copper", "round chrome headlamps, running boards, spoked wheels, front view, facing the camera"),
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
    tdir = os.path.join(OUT, 'r11try'); os.makedirs(tdir, exist_ok=True)
    qcp = os.path.join(OUT, 'r11_qc.json')
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
                c3.wait_gpu(torch, float(os.environ.get("R11_FREE_GB", "3.0")))  # the L4 is shared with game runs
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
