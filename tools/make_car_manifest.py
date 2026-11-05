#!/usr/bin/env python3
"""Adds the generated car models to the asset manifest.

    make_car_manifest.py <assets-src dir> [--models models_proc] [--manifest manifest.json]

Reads <assets-src>/cars/catalog.json (the game's vehicles by model number,
from the CARI chunk, with the paint colour of each remap) and the car GLBs
under <assets-src>/cars/<models dir>/, one per model in its default paint
(NNN_name.glb; the per-remap variants NNN_name_remapXX.glb are skipped: the
renderer repaints the default one from the car's live sprite, see
dll/src/car_bodies.cpp). Each car becomes a "models" entry:

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
    manifest_name = "manifest.json"
    args = sys.argv[2:]
    while args:
        a = args.pop(0)
        if a == "--models":
            models_dir = args.pop(0)
        elif a == "--manifest":
            manifest_name = args.pop(0)
    catalog = json.load(open(os.path.join(src, "cars", "catalog.json")))
    manifest_path = os.path.join(src, manifest_name)
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {"models": []}
    kept = [e for e in manifest.get("models", []) if not re.match(r"^\d{3}_", e.get("name", ""))]
    cars = manifest.get("cars", {})
    cars.pop("default", None)
    by_model = {}
    entries = []
    folder = os.path.join(src, "cars", models_dir)
    for car in catalog["cars"]:
        number = car["model"]
        stem = None
        for f in sorted(os.listdir(folder)):
            m = re.match(r"^(%03d_[a-z0-9_]+)\.glb$" % number, f)
            if m and "_remap" not in f:
                stem = m.group(1)
                break
        if not stem:
            continue
        default = next((r for r in car.get("remaps", []) if r.get("remap") == "default"), None)
        cabin = None
        if "windows_px" in car:
            # rows from the sprite's top: the windscreen (front) is nearer the top
            cabin = (car["windows_px"]["front_y"], car["windows_px"]["rear_y"])
        paint = measure_paint(os.path.join(src, "cars", default["file"]), cabin) if default else [200, 200, 200]
        entries.append({
            "name": stem,
            "glb": f"cars/{models_dir}/{stem}.glb",
            "scale": 1.0,
            "paint_materials": ["top", "side", "front", "rear"],
            "paint_rgb": paint,
            "texture_max": 512,
        })
        by_model[str(number)] = stem
    manifest["models"] = kept + entries
    cars["by_model"] = by_model
    cars.setdefault("by_sprite", {})
    cars["_comment"] = ("by_model: the vehicle's model number (CARI order) -> model name; by_sprite: car sprite number -> "
                        "model name. Vehicles named by neither are built from their own sprite at run time (dll/src/car_bodies.cpp).")
    manifest["cars"] = cars
    json.dump(manifest, open(manifest_path, "w"), indent=1)
    print(f"{len(entries)} cars written to {manifest_path}; by_model covers {len(by_model)} model numbers")


if __name__ == "__main__":
    main()
