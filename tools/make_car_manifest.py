#!/usr/bin/env python3
"""Adds the generated car models to the asset manifest.

    make_car_manifest.py <assets-src dir> [--models models_proc] [--override models3d] [--manifest manifest.json]

Reads <assets-src>/cars/catalog.json (the game's vehicles by model number,
from the CARI chunk, with the paint colour of each remap) and the car GLBs
under <assets-src>/cars/<models dir>/, one per model in its default paint
(NNN_name.glb; the per-remap variants NNN_name_remapXX.glb are skipped: the
renderer repaints the default one from the car's live sprite, see
dll/src/car_bodies.cpp). With --override models3d, a model found there (the
image-to-3D set) is taken instead of the parametric one; off by default until
that set has been checked in the game (its materials must be named for the
paint rule below, or listed in paint_materials). Each car becomes a "models" entry:

    {"name": "000_romero", "glb": "cars/models_proc/000_romero.glb", "scale": 1.0,
     "paint_materials": ["top", "side", "front", "rear"], "paint_rgb": [r, g, b],
     "texture_max": 512}

and the "cars" map gets "by_model": {"0": "000_romero", ...}. Entries the
manifest already has for other things (people, props) are kept; earlier car
entries (names starting with three digits) are replaced. paint_rgb is measured
from the default sprite the way the renderer measures the live one (the mean of
the brighter half of each row outside the glass), so the runtime tint is the
ratio of like to like.

Then run: python3 tools/import_assets.py <assets-src>/manifest.json assets/models
"""
import json, os, re, sys

from PIL import Image


def measure_paint(png, cabin_rows=None):
    """The renderer's paint measure: per row, the mean of the brighter half of
    the opaque pixels; the car's paint is the mean of that over the rows
    outside the cabin (the hood and the trunk)."""
    im = Image.open(png).convert("RGBA")
    w, h = im.size
    px = im.load()
    rows = []
    for y in range(h):
        opaque = [px[x, y][:3] for x in range(w) if px[x, y][3] >= 128]
        if not opaque:
            rows.append(None)
            continue
        opaque.sort(key=lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2])
        top = opaque[len(opaque) // 2:]
        rows.append(tuple(sum(c[i] for c in top) / len(top) for i in range(3)))
    present = [y for y, r in enumerate(rows) if r]
    if not present:
        return [200, 200, 200]
    deck = [rows[y] for y in present if not cabin_rows or y > cabin_rows[1] + 1 or y < cabin_rows[0] - 1]
    if not deck:
        deck = [rows[y] for y in present]
    return [round(sum(c[i] for c in deck) / len(deck), 1) for i in range(3)]


def main():
    src = sys.argv[1]
    models_dir = "models_proc"
    override_dir = "models3d"   # the image-to-3D set first; "" to ship the parametric set alone
    manifest_name = "manifest.json"
    args = sys.argv[2:]
    while args:
        a = args.pop(0)
        if a == "--models":
            models_dir = args.pop(0)
        elif a == "--override":
            override_dir = args.pop(0)
        elif a == "--manifest":
            manifest_name = args.pop(0)
    catalog = json.load(open(os.path.join(src, "cars", "catalog.json")))
    manifest_path = os.path.join(src, manifest_name)
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"models": []}
    kept = [e for e in manifest.get("models", []) if not re.match(r"^\d{3}_", e.get("name", ""))]
    # hand-set per-model keys survive a rebuild (069 U-Jerk Truck: "forward": "-z", its GLB's nose is at -z)
    carry = {e["name"]: {k: e[k] for k in ("forward",) if k in e} for e in manifest.get("models", []) if "name" in e}
    # authored cars (tools/vehicle_art*: an entry with a "generator") are kept as they are, never
    # replaced by an image-to-3D or parametric glb of the same number
    authored = {e["name"]: e for e in manifest.get("models", []) if "name" in e and e.get("generator")}
    cars = manifest.get("cars", {})
    cars.pop("default", None)
    by_model = {}
    entries = []
    overrides = 0
    for car in catalog["cars"]:
        number = car["model"]
        stem = None
        used_dir = None
        for d in (override_dir, models_dir):
            folder = os.path.join(src, "cars", d) if d else ""
            if not d or not os.path.isdir(folder):
                continue
            for f in sorted(os.listdir(folder)):
                m = re.match(r"^(%03d_[a-z0-9_]+)\.glb$" % number, f)
                if m and "_remap" not in f:
                    stem, used_dir = m.group(1), d
                    break
            if stem:
                break
        if not stem:
            continue
        if used_dir == override_dir:
            overrides += 1
        default = next((r for r in car.get("remaps", []) if r.get("remap") == "default"), None)
        cabin = None
        if "windows_px" in car and "sprite_px" in car:
            # catalog.json counts these rows from the wrong end (the sprite's top is the
            # car's tail; the nose is the larger row): mirror them in the sprite's height.
            h = car["sprite_px"][1]
            rows = (h - car["windows_px"]["rear_y"], h - car["windows_px"]["front_y"])
            cabin = (min(rows), max(rows))
        paint = measure_paint(os.path.join(src, "cars", default["file"]), cabin) if default else [200, 200, 200]
        if stem in authored:
            entries.append(authored[stem]); by_model[str(number)] = stem
            continue
        entry = {"name": stem, "glb": f"cars/{used_dir}/{stem}.glb", "scale": 1.0, "paint_rgb": paint, "texture_max": 512}
        if used_dir == override_dir:
            # one baked texture: the importer splits the paint out of it by colour
            entry["paint_split"] = True
        else:
            entry["paint_materials"] = ["top", "side", "front", "rear"]
        entry.update(carry.get(stem, {}))
        entries.append(entry)
        by_model[str(number)] = stem
    manifest["models"] = kept + entries
    cars["by_model"] = by_model
    cars.setdefault("by_sprite", {})
    cars["_comment"] = ("by_model: the vehicle's model number (CARI order) -> model name; by_sprite: car sprite number -> "
                        "model name. Vehicles named by neither are built from their own sprite at run time (dll/src/car_bodies.cpp).")
    manifest["cars"] = cars
    json.dump(manifest, open(manifest_path, "w"), indent=1)
    print(f"{len(entries)} cars written to {manifest_path} ({overrides} from {override_dir}); by_model covers {len(by_model)} model numbers")


if __name__ == "__main__":
    main()
