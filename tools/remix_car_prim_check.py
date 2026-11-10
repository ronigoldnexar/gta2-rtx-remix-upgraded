#!/usr/bin/env python3
"""List the model textures a manifest model's mesh draws that have no prim in a Remix layer.

    remix_car_prim_check.py [models dir] [layer dir] [--pattern REGEX] [--hashes OUT]

A texture whose texels change (a re-split, a repaint, a regenerated car) gets a new XXH3 hash, and
the layer's prim for the old hash stops applying: under Remix that part is then path traced with
the runtime's default material, and a split car's two halves (paint + rest, the same mesh twice)
are taken as one duplicate draw, so only one half shows: a matte grey "clay" body with ragged black
holes (FIX-REMIX-MATERIALS-2, 10 Nov 2026: 42 of 83 cars, the 018 Shark and the 002 BD4 among them).
Run this after any car-art change; rebuild the listed prims with remix_model_materials.py into a
scratch layer and merge them with remix_layer_merge.py (docs/remix-materials.md).
Defaults: repo/assets/models, repo/package/rtx-remix/mods/gta2hd, cars only (^\\d{3}_).
Exit status 1 when anything is missing. Needs numpy, PIL, xxhash (/mnt/gta2/ab_work/venv/bin/python)."""
import argparse, collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import remix_materials as rm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="?", default=os.path.join(HERE, "..", "assets", "models"))
    ap.add_argument("layer", nargs="?", default=os.path.join(HERE, "..", "package", "rtx-remix", "mods", "gta2hd"))
    ap.add_argument("--pattern", default=r"^\d{3}_", help="mesh names to check (default: the cars)")
    ap.add_argument("--hashes", default=None, help="write the missing textures' hashes here, one per line")
    a = ap.parse_args()
    prims = set(re.findall(r'over "mat_([0-9A-F]{16})"', open(os.path.join(a.layer, "mod.usda"), encoding="utf-8").read()))
    manifest = json.load(open(os.path.join(a.models, "manifest.json")))
    names = sorted(m["name"] for m in manifest.get("models", []) if re.match(a.pattern, m["name"]))
    seen, missing, total = set(), collections.defaultdict(list), 0
    for n in names:
        mp = os.path.join(a.models, n + ".mesh")
        if not os.path.exists(mp): continue
        for t in re.findall(rb"[\w\-]+\.tga", open(mp, "rb").read()):
            t = t.decode()
            rest = None
            for tt in (t, t[:-4] + "_paint.tga"):
                f = os.path.join(a.models, tt)
                if tt in seen or not os.path.exists(f): continue
                px = rm.read_tga(f)
                if tt != t and rest is not None and px.shape != rest.shape: continue   # a stale twin of another size: not a pair (the tool skips it too)
                if tt == t: rest = px
                seen.add(tt); total += 1
                h = rm.remix_hash(px)
                if h not in prims: missing[n].append((tt, h))
    nmiss = sum(len(v) for v in missing.values())
    for n, v in missing.items():
        print(f"{n}: " + ", ".join(f"{t} {h}" for t, h in v))
    print(f"{total} textures of {len(names)} models checked, {nmiss} without a prim in {a.layer} ({len(missing)} models)")
    if a.hashes:
        with open(a.hashes, "w") as fh: fh.write("".join(h + "\n" for v in missing.values() for _, h in v))
    sys.exit(1 if nmiss else 0)


if __name__ == "__main__":
    main()
