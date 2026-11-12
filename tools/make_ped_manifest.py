#!/usr/bin/env python3
"""Writes the pedestrian part of assets-src/manifest.json: one model entry per
Rocketbox avatar in rocketbox/ (walk/run/idle clips merged, clothing split for
tinting), the "pedestrians" list (the civilian set), "ped_types" (which remaps
use which avatars, tinted or not; the remap numbers and names are DMA's own,
see pedtypes/ped_types.json) and "ped_remap_colours" (a clothing colour per
remap, for the tints). Usage: make_ped_manifest.py [manifest.json]"""
import json, os, sys, glob
# Copy of assets-src/humans/make_ped_manifest.py: run it from assets-src/humans/
# (it finds the avatars relative to itself; this copy is for the record).
here = os.path.dirname(os.path.abspath(__file__))
src = os.path.dirname(here)                     # assets-src
manifest_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(src, "manifest.json")
m = json.load(open(manifest_path))
clips = [("walk_neutral", "walk"), ("idle_breathe", "idle"), ("run_neutral_01", "run"),
         ("idle_look_around_01", "idle2"), ("idle_neutral_03", "idle3")]

# QB-20/21/39 (9 Nov 2026): the mocap locomotion set, retargeted. Rocketbox's own motion
# capture (Assets/Animations, MIT; fetched into rocketbox/anim_loco/ and converted with
# FBX2glTF): the men's clips on the male avatars, the women's on the female ones (until
# now every avatar walked the women's walk on the women's bone lengths). Each avatar gets
# one of two walks by a hash of its name, a run, a fast run, walk and run starts and
# stops, and fidgets for standing still. "retarget": rotations and root motion only (the
# avatar keeps its bones; tools/import_assets.py); "ref": the cycle the clip's foot
# phases are measured on (tools/locomotion_meta.py), for the renderer's transitions.
def loco_clips(folder):
    female = "Female" in folder
    s = "f" if female else "m"
    h = sum(folder.encode()) % 2
    walk = (["f_walk_neutral", "f_walk_neutral_01"] if female else ["m_walk_neutral_01", "m_walk_neutral_02"])[h]
    run = "f_run_neutral" if female else "m_run_neutral"
    fidgets = (["f_idle_look_around_02", "f_idle_touch_hair_01", "f_idle_move_leg_01", "f_idle_waiting_01"] if female else
               ["m_idle_look_around_02", "m_idle_scratch_head_01", "m_idle_shake_leg_01", "m_idle_waiting_01"])
    idles = ["f_idle_breathe_01", "f_idle_neutral_01", "f_idle_neutral_02"] if female else \
            ["m_idle_neutral_01", "m_idle_neutral_02", "idle_neutral_03"]
    # the run's phases are measured on the walk (that lines the two up), the rest on their own cycle
    out = [(walk, "walk", "walk"), (run, "run", "walk"), (f"{s}_run_fast_01", "run_fast", "run"),
           (f"{s}_walk_start", "walk_start", "walk"), (f"{s}_walk_stop", "walk_stop", "walk"),
           (f"{s}_run_start", "run_start", "run"), (f"{s}_run_stop", "run_stop", "run"),
           (idles[0], "idle", None), (idles[1], "idle2", None), (idles[2], "idle3", None)]
    out += [(f, f"fidget{i + 1}", None) for i, f in enumerate(fidgets)]
    res = []
    for c, n, ref in out:
        d = "anim" if c in ("idle_neutral_03",) else "anim_loco"
        if not os.path.exists(os.path.join(here, "rocketbox", d, c + ".glb")): continue
        e = {"glb": f"humans/rocketbox/{d}/{c}.glb", "name": n, "strip_root": "Bip01", "retarget": True}
        if ref: e["ref"] = ref
        if n.startswith("fidget"): e["max_len"] = 9.0      # the renderer plays at most 9 s of one
        res.append(e)
    return res

def model_name(folder):
    return "human_" + folder.lower()

def entry(folder):
    d = os.path.join(here, "rocketbox", folder)
    # Colour textures by material: "<mat>_color.tga", or a variant "<mat>_color_<v>.tga" (the military
    # avatars ship only "_color_acu", medic 02 "_color_blue"); "_od" (tools/army_olive.py, olive drab)
    # wins over the others. Without this the military bodies, helmets and kit had no texture and the
    # importer's 1x1 fallback drew the soldiers flat yellow.
    rank = lambda t: (0 if t.endswith("_color.tga") else 1 if t.endswith("_color_od.tga") else 2, t)
    mats = {}
    for t in sorted((os.path.basename(t) for t in glob.glob(os.path.join(d, "*_color*.tga"))), key=rank):
        mats.setdefault(t.split("_color")[0], f"humans/rocketbox/{folder}/{t}")
    # material names with a typo in the FBX (Police_Male_03's "m172_equpiment") take the nearest texture
    try:
        import struct, difflib
        raw = open(os.path.join(d, folder + ".glb"), "rb").read()
        names = [x.get("name", "") for x in json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]]).get("materials", [])]
        for n in names:
            if n and n not in mats:
                near = difflib.get_close_matches(n, list(mats), n=1, cutoff=0.85)
                if near: mats[n] = mats[near[0]]
    except Exception: pass
    body = [k for k in mats if k.endswith("_body")]
    return {"name": model_name(folder), "glb": f"humans/rocketbox/{folder}/{folder}.glb", "scale": 0.5,
            "texture_max": 512, "material_textures": mats, "tint_clothing": body,
            "animations_from": loco_clips(folder) or [{"glb": f"humans/rocketbox/anim/{c}.glb", "name": n, "strip_root": "Bip01"} for c, n in clips],
            "forward": "+z", "_licence": "Microsoft Rocketbox avatar library, MIT (github.com/microsoft/Microsoft-Rocketbox)"}

folders = sorted(f for f in os.listdir(os.path.join(here, "rocketbox")) if f != "anim" and os.path.exists(os.path.join(here, "rocketbox", f, f + ".glb")))
# the old human_male_01 style names stay for the first nine
legacy = {"Male_Adult_01": "human_male_01", "Male_Adult_04": "human_male_04", "Male_Adult_07": "human_male_07", "Male_Adult_10": "human_male_10",
          "Male_Adult_13": "human_male_13", "Female_Adult_01": "human_female_01", "Female_Adult_03": "human_female_03",
          "Female_Adult_05": "human_female_05", "Female_Adult_08": "human_female_08"}
names = {}
new_models = []
for f in folders:
    e = entry(f)
    if f in legacy: e["name"] = legacy[f]
    names[f] = e["name"]
    new_models.append(e)
m["models"] = [e for e in m["models"] if not e["name"].startswith("human_")] + new_models

# ASSET-PEDS (9 Nov 2026): every ped type drawn as the GTA2 original reads. The
# outfit of each remap is read from the game's own sprite palettes
# (tools/ped_sprite_outfits.py -> pedtypes/outfits.json: torso, forearms, thighs,
# shins, hair, skin), the avatar is chosen for the sprite's silhouette (short
# sleeves, shorts, a shaved head, a uniform, a suit) and the renderer tints the
# avatar's two clothing zones (top, bottom; tools/import_assets.py ped_zones) and,
# where the sprite says so, the hair, to the sprite's colours. Uniforms, suits and
# kit that already match the sprite keep their own textures (no zones).
NO_ZONES = ("Military_", "Police_", "Security_", "Sports_Male_01", "Sports_Female_01", "Business_Male_01", "Business_Male_02", "Business_Male_03",
            "Business_Male_05", "Business_Female_01", "Female_Adult_06", "Female_Adult_10", "Construction_Male_01")
for e, f in zip(new_models, folders):
    if not f.startswith(NO_ZONES): e["ped_zones"] = 1
    # the prisoners wear the construction coveralls: without the hard hat
    if f.startswith("Construction_Male_0") and f != "Construction_Male_01":
        e["materials_exclude"] = [k for k in e["material_textures"] if k.endswith("_helmet")]

# ASSET-PEDS-2 (9 Nov 2026): variants of avatars baked by tools/ped_identity/recolor_hair.py
# (the hair is painted into the head map, so a hair colour is a copy of the head texture):
# zoned police (the coloured police remaps 1-3 wore the black uniform), red / blonde rednecks,
# Elvis's black hair, the Krishna's robe (a lab coat, saffron, shaved head), the Hulks
# (green skin by a baked multiply). tools/ped_identity/ap2_variants.json lists them.
import subprocess
RECOLOR = os.environ.get("RECOLOR", os.path.join(here, "tools", "recolor_hair.py"))
variants = json.load(open(os.environ.get("AP2_VARIANTS", os.path.join(here, "tools", "ap2_variants.json"))))
os.makedirs(os.path.join(here, "rocketbox", "_ap2"), exist_ok=True)
base_by_name = {e["name"]: e for e in new_models}
for v in variants:
    b = base_by_name[names[v["base"]]]
    e = json.loads(json.dumps(b))
    e["name"] = names[v["base"]] + v["suffix"]
    if v.get("zones"): e["ped_zones"] = 1
    for mat, mode, rgb in v.get("bake", []):          # (a material suffix, hair|mul, r g b)
        for k, path in list(e["material_textures"].items()):
            if not k.endswith(mat): continue
            src = os.path.join(here, path.split("humans/", 1)[1])
            dst_rel = f"humans/rocketbox/_ap2/{e['name']}_{k}.tga"
            subprocess.run([sys.executable, RECOLOR, mode, src, os.path.join(here, dst_rel.split("humans/", 1)[1]), *map(str, rgb)], check=True)
            e["material_textures"][k] = dst_rel
    names[v["name"]] = e["name"]
    new_models.append(e); m["models"].append(e)
civ_long = ["Male_Adult_06", "Male_Adult_08", "Male_Adult_20", "Male_Adult_18", "Male_Adult_13", "Female_Adult_04", "Female_Adult_02"]
civ_short = ["Male_Adult_16", "Male_Adult_11", "Male_Adult_09", "Female_Adult_08", "Female_Adult_17", "Female_Adult_13"]
civ_shorts = ["Male_Adult_01", "Sports_Male_04", "Female_Adult_12"]
# FIX-AVATAR-IDENTITY: the protagonist's avatar is his alone (the "player" type, remap 25, and the
# manifest's "pedestrian"): kept out of the crowd list and every civilian type, so no passer-by shares
# his face, hair and build (feel3-ped-wears-identical-outfit-to-player). The rotation below still
# deals from the full pools, so the other civilian types keep the avatars they had.
HERO = "Male_Adult_11"
civ = [names[f] for f in civ_long + civ_short + civ_shorts if f in names and f != HERO]
def N(*fs): return [names[f] for f in fs if f in names]
types = [
    {"name": "police", "remaps": [0], "models": N("Police_Male_03", "Police_Male_04", "Security_Female_01"), "tint": 0},
    # ASSET-PEDS-2: the green, red and yellow police: the black uniform's zones in the sprite's shirt colour
    {"name": "police_coloured", "remaps": [1, 2, 3], "models": N("Police_Male_03_z", "Police_Male_04_z", "Security_Female_01_z"), "tint": 1},
    {"name": "army", "remaps": [4], "models": N("Military_Male_01", "Military_Male_02", "Military_Female_01"), "tint": 0},
    {"name": "redneck_red", "remaps": [5], "models": N("Male_Adult_16_hr", "Male_Adult_09_hr"), "tint": 1},
    {"name": "redneck_blonde", "remaps": [6], "models": N("Male_Adult_16_hb", "Male_Adult_09_hb"), "tint": 1},
    {"name": "scientist", "remaps": [7], "models": N("Medical_Male_01", "Medical_Female_02"), "tint": 1},
    {"name": "zaibatsu", "remaps": [8], "models": N("Business_Male_01", "Business_Male_03", "Business_Female_01"), "tint": 0},
    {"name": "krishna", "remaps": [9], "models": N("Medical_Male_01_k"), "tint": 1},   # a long coat in saffron, shaved head
    {"name": "russian", "remaps": [10], "models": N("Male_Adult_06", "Male_Adult_20"), "tint": 1},
    {"name": "loony", "remaps": [11], "models": N("Male_Adult_10", "Male_Adult_08", "Female_Adult_17"), "tint": 1},
    {"name": "elvis", "remaps": [12], "models": N("Male_Adult_10_k", "Male_Adult_16_k"), "tint": 1},   # black hair
    {"name": "yakuza", "remaps": [13], "models": N("Business_Male_02", "Business_Male_05"), "tint": 0},
    {"name": "fireman", "remaps": [14], "models": N("Fire_Male_02", "Fire_Male_03", "Fire_Female_01"), "tint": 1},
    {"name": "medic", "remaps": [16], "models": N("Medical_Male_04", "Medical_Female_01"), "tint": 1},
    {"name": "mugger", "remaps": [17], "models": N("Male_Adult_18", "Male_Adult_10"), "tint": 1},
    {"name": "prisoner", "remaps": [22], "models": N("Construction_Male_05", "Construction_Male_02"), "tint": 1},
    {"name": "player", "remaps": [25], "models": N("Male_Adult_11"), "tint": 1},
    # ASSET-PEDS-2: the Hulks, bigger (the type's "scale", "width") and, for 24, green-skinned avatars
    {"name": "hulk", "remaps": [23], "models": N("Male_Adult_01", "Sports_Male_04"), "tint": 1, "scale": 1.3, "width": 1.18},
    {"name": "hulk_green", "remaps": [24], "models": N("Male_Adult_01_g", "Sports_Male_04_g"), "tint": 1, "scale": 1.3, "width": 1.18},
    {"name": "naked", "remaps": [26], "models": N("Sports_Male_01", "Sports_Female_01"), "tint": 0},
    # 53: not a remap, the EMERG_GRAPHIC body (SWAT, FBI) the renderer maps here
    {"name": "swat", "remaps": [53], "models": N("Police_Male_02", "Police_Female_01"), "tint": 0},
]
outfits = json.load(open(os.path.join(here, "pedtypes", "outfits.json")))
def lift(c, gain=1.1):
    """A sprite colour (the mean of its shaded texels) as cloth albedo: a little
    brighter, and the near-black gang palettes raised so their hue still reads."""
    v = max(max(c), 1)
    k = gain if v >= 100 else max(gain, min(3.0, (40 + 0.8 * v) / v))
    return [min(255, round(x * k)) for x in c]
def mix(a, b, t): return [round(x * (1 - t) + y * t) for x, y in zip(a, b)]
def silhouette(o):
    return "shorts" if o["shorts"] else "short" if o["short_sleeves"] else "long"
default_hair = ([72, 44, 10], [35, 21, 1], [35, 21, 4], [59, 22, 0], [49, 29, 6])
typed = {r for t in types for r in t["remaps"]}
# PEDS-VARIETY (12 Nov 2026): each civilian type deals from sixteen avatars (PEDS-VARIETY-2: eight women, eight men;
# was nine or ten with four women), a mix of its own (seeded by the remap) instead of three or four picked by the sprite's sleeve length.
# The DLL dresses them (identity.cpp CrowdVariety: a curated outfit three in four, else the avatar's own colours).
import random
CIV_WOMEN = ["human_female_01", "human_female_03", "human_female_05", "human_female_08", "human_female_adult_02",
             "human_female_adult_04", "human_female_adult_12", "human_female_adult_13", "human_female_adult_17",
             "human_business_female_01",
             # PEDS-VARIETY-2: the two in religious dress (no zones: their own look, never tinted) and nine fetched
             # from the Rocketbox library (fetch_rocketbox_pro.sh Adults|Professions ...), gated by eye on a render
             # sheet. Left out: Female_Adult_16 (a burqa on a low-detail single-texture body), Female_Party_01 (hot
             # pants, knee boots in the trouser colour), Business_Female_03 (the skirt speckles under a tint even after
             # paint_resplit.py), Sports_Female_01 (bikini).
             "human_female_adult_06", "human_female_adult_10",
             "human_female_adult_07", "human_female_adult_09", "human_female_adult_11", "human_female_adult_14",
             "human_female_adult_15", "human_female_party_02", "human_business_female_02", "human_business_female_04",
             "human_sports_female_02"]
CIV_MEN = ["human_male_01", "human_male_04", "human_male_07", "human_male_10", "human_male_13", "human_male_adult_02",
           "human_male_adult_05", "human_male_adult_06", "human_male_adult_08", "human_male_adult_09", "human_male_adult_12",
           "human_male_adult_16", "human_male_adult_18", "human_male_adult_20", "human_business_male_04",
           "human_business_male_06", "human_business_male_07"]
SUIT_POOLS = 4   # human_business_female_01 (a black suit, never recoloured) is in at most this many civilian pools
def civilian_pools(remaps, have, hero):
    """remap -> nine or ten avatars, four of them women, a mix of its own (seeded by the remap)."""
    pools, suits = {}, 0
    for remap in remaps:
        rng = random.Random(7919 + remap)
        w = [x for x in CIV_WOMEN if x in have and x != hero]
        m_ = [x for x in CIV_MEN if x in have and x != hero]
        women = rng.sample(w, min(8, len(w)))   # PEDS-VARIETY-2: 8 women and 8 men per type
        if "human_business_female_01" in women:
            if suits >= SUIT_POOLS:
                spare = [x for x in w if x not in women and x != "human_business_female_01"]
                women[women.index("human_business_female_01")] = rng.choice(spare)
            else:
                suits += 1
        pool = women + rng.sample(m_, min(8, len(m_)))
        rng.shuffle(pool)
        pools[remap] = pool
    return pools
have = {e["name"] for e in m["models"]}
civ_remaps = [r for r in range(53) if r not in typed]
pools = civilian_pools(civ_remaps, have, names.get(HERO))
for r in civ_remaps:
    types.append({"name": f"civilian_{r}", "remaps": [r], "models": pools[r], "tint": 1})
civ = [x for x in CIV_WOMEN + CIV_MEN if x in have and x != names.get(HERO) and x != "human_business_female_01"]
outfit_rows = []
for r in range(54):
    o = outfits.get(str(r))
    if not o: outfit_rows.append([0] * 9); continue
    top, bottom = o["top"], o["thigh"]
    if r == 9:  top = mix(top, o["forearm"], 0.85); bottom = top   # Krishna: a saffron robe to the ground
    if r == 12: top = mix(top, o["forearm"], 0.5)        # Elvis: pale sleeves over a mauve jacket
    if r == 24: top = mix(top, o["forearm"], 0.5); bottom = mix(bottom, o["shin"], 0.35)   # the green Hulk: the tint also reaches the bare arms and legs
    if r == 14: bottom = o["shin"]                       # firemen: the orange suit all the way down
    hair = o["hair"] if (r in (5, 6) or o["hair"] not in default_hair and r not in range(0, 5) and r != 9) else [0, 0, 0]
    if r == 25: top, bottom = [30, 30, 32], [24, 24, 28]  # the protagonist: black, as the sprite (lifted below)
    outfit_rows.append(lift(top) + lift(bottom) + (lift(hair, 1.0) if any(hair) else [0, 0, 0]))
m["pedestrians"] = civ   # PEDS-VARIETY: every crowd avatar (remaps with no type)
m["pedestrian"] = names.get(HERO, "human_male_01")
m["ped_types"] = types
m["ped_outfits"] = outfit_rows
colours = json.load(open(os.path.join(here, "pedtypes", "ped_types.json")))["tint_colours"]
m["ped_remap_colours"] = [colours.get(str(r), [0, 0, 0]) for r in range(53)]
json.dump(m, open(manifest_path, "w"), indent=1)
print(len(new_models), "avatars;", len(types), "types;", len(civ), "civilians;", sum(1 for e in new_models if e.get("ped_zones")), "with clothing zones")
# Left out of the tinted pools: Female_Adult_01 (a pink blouse partly read as skin), Male_Adult_02 (a beige sweater the skin test cannot tell
# from his skin, so it stays untinted), Female_Adult_06/10 (religious dress, not recoloured),
# Construction_Male_01 (a welding mask), the swimwear (the "naked" remap 26 only).
