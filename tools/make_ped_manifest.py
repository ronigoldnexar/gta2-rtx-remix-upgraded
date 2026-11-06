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

def model_name(folder):
    return "human_" + folder.lower()

def entry(folder):
    d = os.path.join(here, "rocketbox", folder)
    texs = sorted(os.path.basename(t) for t in glob.glob(os.path.join(d, "*_color.tga")))
    mats = {t[:-len("_color.tga")]: f"humans/rocketbox/{folder}/{t}" for t in texs}
    body = [k for k in mats if k.endswith("_body")]
    return {"name": model_name(folder), "glb": f"humans/rocketbox/{folder}/{folder}.glb", "scale": 0.5,
            "texture_max": 512, "material_textures": mats, "tint_clothing": body,
            "animations_from": [{"glb": f"humans/rocketbox/anim/{c}.glb", "name": n, "strip_root": "Bip01"} for c, n in clips],
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

civ = [names[f] for f in folders if f.startswith(("Male_Adult", "Female_Adult"))]   # Sports_* are swimwear, left out
def N(*fs): return [names[f] for f in fs if f in names]
types = [
    {"name": "police", "remaps": [0, 1, 2, 3], "models": N("Police_Male_01", "Police_Male_02", "Police_Male_03", "Police_Female_01"), "tint": 0},
    {"name": "army", "remaps": [4], "models": N("Military_Male_01", "Military_Male_02", "Military_Female_01"), "tint": 0},
    {"name": "redneck", "remaps": [5, 6], "models": N("Construction_Male_01", "Construction_Male_02"), "tint": 0},
    {"name": "scientist", "remaps": [7], "models": N("Medical_Male_01", "Medical_Female_01"), "tint": 0},
    {"name": "zaibatsu", "remaps": [8], "models": N("Business_Male_01", "Business_Male_02", "Business_Male_03", "Business_Female_01"), "tint": 0},
    {"name": "krishna", "remaps": [9], "models": N("Male_Adult_02", "Female_Adult_06", "Male_Adult_11"), "tint": 1},
    {"name": "russian", "remaps": [10], "models": N("Security_Male_01", "Male_Adult_02", "Male_Adult_05"), "tint": 1},
    {"name": "loony", "remaps": [11], "models": N("Male_Adult_08", "Male_Adult_11", "Female_Adult_02"), "tint": 1},
    {"name": "elvis", "remaps": [12], "models": N("Male_Adult_16"), "tint": 1},
    {"name": "yakuza", "remaps": [13], "models": N("Business_Male_02", "Business_Male_03", "Security_Male_01"), "tint": 1},
    {"name": "fireman", "remaps": [14], "models": N("Fire_Male_01", "Fire_Male_02", "Fire_Female_01"), "tint": 0},
    {"name": "medic", "remaps": [16], "models": N("Medical_Male_02", "Medical_Female_02"), "tint": 0},
    {"name": "mugger", "remaps": [17], "models": N("Male_Adult_05", "Male_Adult_02"), "tint": 1},
    {"name": "prisoner", "remaps": [22], "models": N("Male_Adult_11", "Male_Adult_05"), "tint": 1},
]
# Civilian outfits (15, 18-21, 23-52 minus the player 25): the avatars whose
# clothing colour is nearest the outfit's shirt colour, three each, untinted.
# Colours from the outfit names in DMA's remap table.
shirt = {15: (60, 150, 70), 18: (40, 60, 160), 19: (120, 160, 210), 20: (200, 200, 200), 21: (190, 190, 170), 23: (90, 90, 90), 24: (60, 140, 60),
         26: (220, 170, 140), 27: (70, 110, 170), 28: (225, 225, 225), 29: (180, 150, 210), 30: (220, 100, 100), 31: (220, 100, 100), 32: (60, 90, 180),
         33: (220, 200, 60), 34: (190, 140, 210), 35: (140, 30, 40), 36: (40, 90, 50), 37: (130, 90, 60), 38: (130, 90, 60), 39: (90, 40, 110),
         40: (90, 40, 110), 41: (120, 30, 50), 42: (120, 30, 50), 43: (170, 70, 90), 44: (80, 190, 190), 45: (230, 210, 70), 46: (40, 90, 50),
         47: (190, 190, 190), 48: (130, 150, 170), 49: (190, 150, 210), 50: (130, 60, 170), 51: (120, 140, 110), 52: (230, 130, 170)}
# the avatars' own clothing colours, measured by a previous import when present
measured = {}
try:
    for e in json.load(open(os.path.join(src, "..", "repo", "assets", "models", "manifest.json")))["models"]:
        if e["name"].startswith("human_") and "paint_rgb" in e: measured[e["name"]] = tuple(e["paint_rgb"])
except Exception: pass
for r, col in shirt.items():
    if measured:
        ranked = sorted(civ, key=lambda n: sum((a - b) ** 2 for a, b in zip(measured.get(n, (128, 128, 128)), col)))
        models = ranked[:4]
    else:
        models = civ
    types.append({"name": f"civilian_{r}", "remaps": [r], "models": models, "tint": 0})
m["pedestrians"] = civ
m["pedestrian"] = "human_male_01"
m["ped_types"] = types
colours = json.load(open(os.path.join(here, "pedtypes", "ped_types.json")))["tint_colours"]
m["ped_remap_colours"] = [colours.get(str(r), [0, 0, 0]) for r in range(53)]
json.dump(m, open(manifest_path, "w"), indent=1)
print(len(new_models), "avatars;", len(types), "types;", len(civ), "civilians", "measured" if measured else "unmeasured")
