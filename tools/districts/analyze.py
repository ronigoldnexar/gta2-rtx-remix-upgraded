#!/usr/bin/env python3
"""DISTRICTS-POC step 2: automated building analysis.

    analyze.py <work dir> <wil|ste|bil> <hd tiles dir (assets/textures_hd)> <facade boxes json> [--sheet N]

Reads <work>/<lvl>_buildings.json (catalogue.py) and writes <work>/<lvl>_analysis.json: per wall tile the image
features and the openings it shows, per building its archetype with the evidence and the per-face feature grid
the facade kit reads. Nothing is placed by hand.

Openings (window / door / shop window / sill boxes in the 64 px tile frame) are the Qwen3-VL-8B grounding of
every wall tile already committed as tools/facade_boxes.json (QB-25, Apache-2.0 model, docs/facade-depth.md),
cleaned here: boxes under 3 px or covering the whole tile are dropped, a door wider than half the tile is a
loading door. Image features (from the HD tile, box-filtered to 64 px): mean colour, saturation, a brick score
(periodic horizontal mortar lines), a rib score (periodic vertical stripes uniform down the tile: corrugated
cladding), the window share of the tile.

Archetype (rules over the building's shape and its wall tiles, in order; the scores go in the evidence):
  structure       thin parts (walls, fences) or no wall tile with any opening and under 2 levels
  warehouse       ribbed cladding or loading doors, few windows, footprint >= 12 cells
  factory         industrial level, >= 3 levels, windows, footprint >= 16, loading doors or brick
  office_tower    >= 5 levels above the street, glazed (window share >= 0.25), not brick
  shopfront_row   shop windows on >= 30 % of the street-level wall, <= 3 levels
  brownstone      brick or brown stone, 2-4 levels, residential level or warm brown wall
  brick_tenement  brick, >= 3 levels
  house           <= 2 levels, footprint <= 16 cells
  block           anything else (generic masonry block)
"""
import colorsys, json, os, sys
from collections import Counter, defaultdict
import numpy as np
from PIL import Image

LABELS = ("window", "door", "shop window", "sill")


def tile_img(hd_dir, lvl, tile, cache):
    if tile in cache:
        return cache[tile]
    p = os.path.join(hd_dir, lvl, f"tile_{tile:04d}.dds")
    a = None
    if os.path.exists(p):
        try:
            a = np.asarray(Image.open(p).convert("RGBA").resize((64, 64), Image.BOX), dtype=np.float32) / 255.0
        except Exception:
            a = None
    cache[tile] = a
    return a


def periodic(profile, lo, hi):
    p = profile - profile.mean()
    d = float((p * p).sum())
    if d < 1e-9:
        return 0.0
    return max(float((p[:-k] * p[k:]).sum()) / d for k in range(lo, hi + 1))


def tile_features(a):
    rgb = a[..., :3]
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    mean = rgb.reshape(-1, 3).mean(0)
    h, s, v = colorsys.rgb_to_hsv(*[float(c) for c in mean])
    gy = np.abs(np.diff(lum, axis=0)).mean(1)   # per row: horizontal edges (mortar courses)
    gx = np.abs(np.diff(lum, axis=1)).mean(0)   # per column: vertical edges (ribs)
    brick = periodic(gy, 4, 12) * min(1.0, gy.mean() * 12)
    colvar = float(lum.mean(0).std())
    rowvar = float(lum.mean(1).std())
    rib = periodic(gx, 2, 10) * min(1.0, gx.mean() * 12) * (1.0 if colvar > 1.5 * rowvar else 0.5)
    brick, rib = float(brick), float(rib)
    return {"rgb": [round(float(c), 3) for c in mean], "hue": round(h, 3), "sat": round(s, 3), "val": round(v, 3),
            "brick": round(brick, 3), "rib": round(rib, 3), "alpha": round(float((a[..., 3] < 0.5).mean()), 3)}


def clean_boxes(entry):
    out = []
    for b in (entry or {}).get("boxes", []):
        x0, y0, x1, y1 = b["box"]
        x0, y0, x1, y1 = max(0.0, x0), max(0.0, y0), min(64.0, x1), min(64.0, y1)
        w, h = x1 - x0, y1 - y0
        if w < 3 or h < 2:
            continue
        lab = b["label"]
        if lab != "sill" and w * h > 0.92 * 64 * 64:
            continue
        if lab == "window" and w > 62:   # girders, bands (facade-depth rule)
            continue
        kind = lab
        if lab == "door" and w >= 30:
            kind = "loading_door"
        out.append({"kind": kind, "box": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]})
    return out


def dark_openings(a, boxes):
    """dark, compact regions of the tile art no grounded box covers: an arched doorway, a gate, a dark shop front.
    Kept conservative: darker than 45 % of the tile's median luminance, at least 6 % of the tile, filling at least
    60 % of its bounding box, at most half the tile; the box is cut to its rectangular core (the rows where the
    dark run spans 80 % of the box) so an arch's crown stays painted."""
    import numpy as np
    from collections import deque
    lum = a[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    dark = lum < 0.45 * float(np.median(lum))
    seen = np.zeros_like(dark)
    out = []
    for y in range(64):
        for x in range(64):
            if not dark[y, x] or seen[y, x]:
                continue
            q = deque([(y, x)]); seen[y, x] = True; pts = []
            while q:
                cy, cx = q.popleft(); pts.append((cy, cx))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < 64 and 0 <= nx < 64 and dark[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; q.append((ny, nx))
            if len(pts) < 0.06 * 4096 or len(pts) > 0.5 * 4096:
                continue
            ys = [p[0] for p in pts]; xs = [p[1] for p in pts]
            y0, y1, x0, x1 = min(ys), max(ys) + 1, min(xs), max(xs) + 1
            if len(pts) < 0.6 * (y1 - y0) * (x1 - x0):
                continue
            rows = [r for r in range(y0, y1) if dark[r, x0:x1].mean() >= 0.8]
            if len(rows) < 8:
                continue
            box = [float(x0), float(min(rows)), float(x1), float(max(rows) + 1)]
            if any(min(b["box"][2], box[2]) - max(b["box"][0], box[0]) > 2 and min(b["box"][3], box[3]) - max(b["box"][1], box[1]) > 2 for b in boxes):
                continue
            kind = "door" if box[3] >= 60 else "window"
            out.append({"kind": kind, "box": box, "source": "dark"})
    return out


def classify(f, lvl):
    ev = f
    if f["thin"] or (f["open_tiles"] == 0 and f["levels"] <= 1):
        return "structure"
    ind = lvl == "bil"
    if f["area"] >= 12 and (f["rib"] >= 0.25 or f["loading_doors"] >= 1) and f["window_share"] < 0.12:
        return "warehouse"
    warm = 0.0 <= f["hue"] <= 0.11 and f["sat"] >= 0.2
    if ind and f["levels"] >= 3 and f["area"] >= 16 and f["window_tiles"] >= 0.15 and (f["loading_doors"] >= 1 or f["brick"] >= 0.25 or warm):
        return "factory"
    if ind and f["area"] >= 20 and f["window_share"] < 0.08:
        return "warehouse"
    if f["levels"] >= 5 and f["window_share"] >= 0.2 and f["brick"] < 0.3:
        return "office_tower"
    if f["shop_street"] >= 0.3 and f["levels"] <= 3:
        return "shopfront_row"
    warm = 0.0 <= f["hue"] <= 0.11 and f["sat"] >= 0.2
    if f["brick"] >= 0.3 or warm:
        if 2 <= f["levels"] <= 4 and (lvl == "ste" or (warm and f["val"] < 0.55)):
            return "brownstone"
        if f["levels"] >= 3:
            return "brick_tenement"
    if f["levels"] <= 2 and f["area"] <= 16:
        return "house"
    if f["levels"] >= 5:
        return "office_tower"
    return "block"


def main():
    work, lvl, hd_dir, boxes_path = sys.argv[1:5]
    cat = json.load(open(os.path.join(work, f"{lvl}_buildings.json")))
    boxes = json.load(open(boxes_path))
    cache = {}
    tiles = {}
    used = Counter(l["tile"] for b in cat["buildings"] for fc in b["faces"] for l in fc["levels"] if l["tile"])
    for t in used:
        a = tile_img(hd_dir, lvl, t, cache)
        feat = tile_features(a) if a is not None else None
        ob = clean_boxes(boxes.get(f"{lvl}:{t}"))
        if a is not None:
            ob += dark_openings(a, ob)
        win_area = sum((b["box"][2] - b["box"][0]) * (b["box"][3] - b["box"][1]) for b in ob if b["kind"] in ("window", "shop window"))
        tiles[t] = {"uses": used[t], "features": feat, "openings": ob, "window_share": round(float(win_area) / 4096.0, 3)}
    out_b = []
    for b in cat["buildings"]:
        fl = [l for fc in b["faces"] for l in fc["levels"] if l["tile"] and l["slope"] == 0]
        n = max(1, len(fl))
        def tf(key):
            vals = [tiles[l["tile"]]["features"][key] for l in fl if tiles[l["tile"]]["features"]]
            return float(np.median(vals)) if vals else 0.0
        open_tiles = sum(1 for l in fl if tiles[l["tile"]]["openings"])
        window_tiles = sum(1 for l in fl if any(o["kind"] == "window" for o in tiles[l["tile"]]["openings"]))
        street_fl = [l for fc in b["faces"] for l in fc["levels"][:1] if l["tile"] and fc["lo"] <= b["street"]]
        shop_street = sum(1 for l in street_fl if any(o["kind"] == "shop window" for o in tiles[l["tile"]]["openings"])) / max(1, len(street_fl))
        loading = sum(1 for l in fl if any(o["kind"] == "loading_door" for o in tiles[l["tile"]]["openings"]))
        rgb = np.median(np.array([tiles[l["tile"]]["features"]["rgb"] for l in fl if tiles[l["tile"]]["features"]] or [[0.5, 0.5, 0.5]]), 0)
        h, s, v = colorsys.rgb_to_hsv(*[float(c) for c in rgb])
        f = {"thin": b.get("thin", False), "levels": b["levels"], "area": b["area"], "face_levels": len(fl),
             "open_tiles": open_tiles, "window_tiles": round(window_tiles / n, 3),
             "window_share": round(sum(tiles[l["tile"]]["window_share"] for l in fl) / n, 3),
             "shop_street": round(shop_street, 3), "loading_doors": loading,
             "brick": round(tf("brick"), 3), "rib": round(tf("rib"), 3), "hue": round(h, 3), "sat": round(s, 3), "val": round(v, 3),
             "wall_rgb": [round(float(c), 3) for c in rgb]}
        arche = classify(f, lvl)
        out_b.append({"id": b["id"], "archetype": arche, "evidence": f})
    json.dump({"level": lvl, "tiles": {str(k): v for k, v in tiles.items()}, "buildings": out_b},
              open(os.path.join(work, f"{lvl}_analysis.json"), "w"))
    c = Counter(x["archetype"] for x in out_b)
    print(lvl, dict(c))


if __name__ == "__main__":
    main()
