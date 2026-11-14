#!/usr/bin/env python3
"""PEDS-CONSISTENT (14 Nov 2026): the avatars with a fixed look (the Haredi men's black coats, the Haredi woman's dark
modest outfit, female_adult_06's headscarf and tunic, female_adult_10's black robe, business_female_01's black suit)
cannot follow a sprite's clothing colours, so they are dealt only in the civilian pools whose sprite is dark and
neutral in both the torso and the legs (the remap's ped_outfits row: chroma < 28, lightness max + min < 200):
seen from above they are as dark as in 3D. Everywhere else each one's slot goes to an ordinary avatar of the same
sex (seeded). Likewise the avatars with an untinted garment (tint_audit: the zone tints do not reach it) are dealt
only where the sprite's colour for that part is near the garment's own (CIEDE2000 <= 20): male_adult_02's beige
sweater and male_adult_05's tan vest where the sprite's top is, male_01's khaki shorts where its legs are, and
female_adult_11's one-colour dress (the top's tint all over) where the sprite's top and legs are alike. Called by tools/make_ped_manifest.py; standalone: consistent_pools.py <manifest.json> (in place)."""
import json, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outfits import sprite_colours
from outfit_parity_de import de2000

FIXED_MEN = ["human_haredi_male_01", "human_haredi_male_02"]
FIXED_WOMEN = ["human_haredi_female_01", "human_female_adult_06", "human_female_adult_10", "human_business_female_01"]


# avatar -> (the part the sprite must match, the garment's own colour) ('dress': the sprite's top and legs alike)
PARTIAL = {"human_male_adult_02": ("top", (188, 168, 136)), "human_male_adult_05": ("top", (176, 150, 108)),
           "human_male_01": ("bottom", (170, 150, 110)), "human_female_adult_11": ("dress", None)}
DE_PARTIAL = 20.0


def partial_ok(name, row):
    sc = sprite_colours(row)
    if not sc: return False
    part, own = PARTIAL[name]
    if part == "dress": return de2000(sc[0], sc[1]) <= DE_PARTIAL
    return de2000(sc[0] if part == "top" else sc[1], own) <= DE_PARTIAL


def dark_neutral(row):
    sc = sprite_colours(row)
    return bool(sc) and all(max(c) - min(c) < 28 and max(c) + min(c) < 200 for c in sc)


def restrict(m):
    rows = m["ped_outfits"]
    civ = [t for t in m["ped_types"] if t["name"].startswith("civilian")]
    fixed = set(FIXED_MEN + FIXED_WOMEN)
    have = {e["name"] for e in m["models"]}
    pool_names = {x for t in civ for x in t["models"]}
    women = sorted(x for x in pool_names if "female" in x and x not in fixed)
    men = sorted(x for x in pool_names if "female" not in x and x not in fixed)
    hosts = [t for t in civ if any(dark_neutral(rows[r]) for r in t["remaps"])]
    rng = random.Random(4243)
    for t in civ:   # the partly tinted avatars out of the pools whose sprite does not suit their own garment
        pool = t["models"]
        for k, x in enumerate(pool):
            if x in PARTIAL and not all(partial_ok(x, rows[r]) for r in t["remaps"]):
                spare = [y for y in (women if "female" in x else men) if y not in pool and y not in PARTIAL]
                pool[k] = rng.choice(spare)
    women = [x for x in women if x not in PARTIAL]; men = [x for x in men if x not in PARTIAL]
    for t in civ:
        pool = t["models"]
        for k, x in enumerate(pool):
            if x in fixed and t not in hosts:
                spare = [y for y in (women if "female" in x else men) if y not in pool]
                pool[k] = rng.choice(spare)
    for t in hosts:   # each host: the fixed avatars in place of ordinary ones of the same sex
        pool = t["models"]
        for group, female in ((FIXED_MEN, False), (FIXED_WOMEN, True)):
            for x in group:
                if x not in have or x in pool: continue
                slots = [k for k, y in enumerate(pool) if ("female" in y) == female and y not in fixed]
                if slots: pool[rng.choice(slots)] = x
    return [t["name"] for t in hosts]


if __name__ == "__main__":
    p = sys.argv[1]; m = json.load(open(p))
    hosts = restrict(m)
    open(p, "w").write(json.dumps(m, indent=1))
    print("fixed-look avatars dealt in", hosts)
