#!/usr/bin/env python3
"""DISTRICTS-POC: the automated QA metric per building, so people only review the flagged ones.

    qa.py <work> <lvl> <kit file> [--hd <textures_hd>] [--out <json>]

Per building (the kit file's geometry is attributed by footprint):
  footprint   largest distance (per axis) a kit vertex stands outside the footprint in plan (limit 0.26 block: the kit stands nothing beyond 0.25) and
              whether anything goes below the building's lowest wall (its floor: the lowest face level; a building on a
              slope has walls under the street level the catalogue gives it, and their trims are right there)
  zfight      kit polygons coplanar with a wall of the map at the wall plane (the skin and trim stand off it by
              construction; a hit is a kit bug) and pairs of kit triangles coplanar and overlapping (two
              parts sharing a face: the classic cornice-corner case)
  texture     for every opening the kit cuts (kit.cuttable: kind, confidence, size), how much it stands out from
              the wall round it in the tile art (luminance contrast of the box against a 3-texel ring); a recess with
              no contrast is a false window (a vent, a sign) and gets flagged. Since round 4 the generator refuses
              those (kit.contrast), so this is a regression guard on that gate
  pop         height of kit geometry above the roof line (parapet, plant, chimney): the part a classic-view
              player never saw; anything over 0.25 block must fade (it does: TileBatch::kit), it is reported
              so the review can watch the move frames of those buildings
  budget      triangles; flagged over 20 000 for one building
  hosts       every roof part stands on real flat roof (the map's top block flat, lidded, not a floating deck) and
              every wall part (stoop, bay, balcony, shopfront, dock, fire escape, hood, pipe, duct) on a map wall
              face that is there, flat (slope 0) and open (the cell in front of it is not built up at that level)
A building is flagged when any check fails; the JSON lists the reasons."""
import json, math, os, struct, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import W, H
from kit import cuttable, CONF


def read_kit(path):
    """[(tile, owner building, [3 x (x y z nx ny nz)])], the owner from kit.py's sidecar"""
    data = open(path, "rb").read()
    owners = json.load(open(path + ".owners.json"))
    ng = struct.unpack_from("<I", data, 8)[0]
    p, tris = 12, []
    for g in range(ng):
        tile, flags, nv, ni = struct.unpack_from("<iIII", data, p); p += 16
        vs = struct.unpack_from(f"<{nv * 8}f", data, p); p += nv * 32
        ix = struct.unpack_from(f"<{ni}I", data, p); p += ni * 4
        for bid, first, count in owners[g][2]:
            for t in range(first, first + count, 3):
                tris.append((tile, bid, [vs[ix[t + k] * 8: ix[t + k] * 8 + 6] for k in range(3)]))
    return tris


def main():
    work, lvl, kitp = sys.argv[1:4]
    hd = sys.argv[sys.argv.index("--hd") + 1] if "--hd" in sys.argv else "/mnt/gta2/gta2-linux/repo/assets/textures_hd"
    cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    tiles = an["tiles"]
    owner = {}
    for b in cat.values():
        for x, y in b["cells"]:
            owner[(x, y)] = b["id"]
    tris = read_kit(kitp)
    floors = {}
    def floor_of(b):
        if b["id"] not in floors:
            floors[b["id"]] = min([b["street"]] + [f["lo"] for f in b["faces"]])
        return floors[b["id"]]
    per = defaultdict(lambda: {"tris": 0, "over": 0.0, "below": False, "above_roof": 0.0, "zfight_wall": 0, "planes": defaultdict(list)})
    m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
    for tile, bid, vs in tris:
        cx = sum(v[0] for v in vs) / 3; cz = sum(v[2] for v in vs) / 3
        r = per[bid]; b = cat[bid]
        r["tris"] += 1
        cells = set(map(tuple, b["cells"]))
        for v in vs:
            mx, my = v[0], H - v[2]
            cell = (int(math.floor(mx)), int(math.floor(my)))
            if cell not in cells:
                # distance to the nearest footprint cell
                d = min(max(max(c[0] - mx, 0, mx - c[0] - 1), max(c[1] - my, 0, my - c[1] - 1)) for c in cells
                        if abs(c[0] - mx) < 2 and abs(c[1] - my) < 2) if any(abs(c[0] - mx) < 2 and abs(c[1] - my) < 2 for c in cells) else 9.0
                r["over"] = max(r["over"], d)
            if v[1] < floor_of(b) - 0.01:
                r["below"] = True
            r["above_roof"] = max(r["above_roof"], v[1] - b["roof"])
        n = (vs[0][3], vs[0][4], vs[0][5])
        # a front face lying in a map wall plane (axis normal, plane at an integer coordinate)
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax != 1 and abs(abs(n[ax]) - 1) < 1e-3:
            plane = vs[0][ax]
            if all(abs(v[ax] - plane) < 1e-4 for v in vs) and abs(plane - round(plane)) < 1e-4:
                # is there a map wall face there facing the same way?
                side = {(0, 1): "E", (0, -1): "W", (2, 1): "N", (2, -1): "S"}[(ax, 1 if n[ax] > 0 else -1)]
                if side in "EW":
                    x = int(round(plane)) - (1 if side == "E" else 0); y = int(H - 1 - math.floor(cz))
                else:
                    x = int(math.floor(cx)); y = int(H - round(plane)) - (0 if side == "N" else 1)
                lvl_ = int(math.floor(sum(v[1] for v in vs) / 3))
                blk = m.block(x, y, lvl_)
                if blk and blk[gmap.SIDES[side][0]] & 0x3FF:
                    r["zfight_wall"] += 1
            key = (ax, 1 if n[ax] > 0 else -1, round(plane, 4))
            if all(abs(v[ax] - plane) < 1e-4 for v in vs):   # in that plane (a tapered stack's facet is not)
              r["planes"][key].append((tile, [(v[(ax + 1) % 3], v[(ax + 2) % 3]) for v in vs]))
        elif ax == 1:
            key = (1, 1 if n[1] > 0 else -1, round(vs[0][1], 4))
            if all(abs(v[1] - vs[0][1]) < 1e-4 for v in vs):
                r["planes"][key].append((tile, [(v[0], v[2]) for v in vs]))
    # texture alignment: contrast of every recess
    from PIL import Image
    import numpy as np
    lum = {}
    def tl(t):
        if t not in lum:
            p = os.path.join(hd, lvl, f"tile_{t:04d}.dds")
            lum[t] = (np.asarray(Image.open(p).convert("RGB").resize((64, 64), Image.BOX), np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)) if os.path.exists(p) else None
        return lum[t]
    out = []
    for a in an["buildings"]:
        bid = a["id"]
        if bid not in per:
            continue
        r = per[bid]; b = cat[bid]
        holes, weak = 0, 0
        for f in b["faces"]:
            for l in f["levels"]:
                feat = tiles.get(str(l["tile"]), {}).get("features") or {}
                if not l["tile"] or l["slope"] != 0 or feat.get("alpha", 1.0) > 0.02:
                    continue   # a face the kit leaves as it is (slope, lattice, railing): nothing is cut there
                for o in tiles.get(str(l["tile"]), {}).get("openings", []):
                    if cuttable(o) is None:
                        continue
                    L = tl(l["tile"])
                    if L is None:
                        continue
                    x0, y0, x1, y1 = [int(round(v)) for v in o["box"]]
                    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(64, x1), min(64, y1)
                    if x1 - x0 < 2 or y1 - y0 < 2:
                        continue
                    inner = L[y0:y1, x0:x1].mean()
                    ring = np.concatenate([L[max(0, y0 - 3):y0, x0:x1].ravel(), L[y1:min(64, y1 + 3), x0:x1].ravel(),
                                           L[y0:y1, max(0, x0 - 3):x0].ravel(), L[y0:y1, x1:min(64, x1 + 3)].ravel()])
                    holes += 1
                    if ring.size and abs(inner - ring.mean()) < 12:
                        weak += 1
        # coplanar overlaps between kit triangles (bounding-box test inside each plane)
        zf_pairs = 0
        for key, polys in r["planes"].items():
            if len(polys) < 2:
                continue
            boxes = [(min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts), t) for t, pts in polys]
            boxes.sort()
            for i in range(len(boxes)):
                for j in range(i + 1, min(len(boxes), i + 40)):
                    a_, b_ = boxes[i], boxes[j]
                    if b_[0] >= a_[2] - 1e-3:
                        break
                    ox = min(a_[2], b_[2]) - max(a_[0], b_[0]); oy = min(a_[3], b_[3]) - max(a_[1], b_[1])
                    if ox > 2e-3 and oy > 2e-3 and a_[4] != b_[4]:
                        zf_pairs += 1
                        if os.environ.get("QA_DEBUG") and zf_pairs <= 2:
                            print("coplanar", bid, key, [round(v, 3) for v in a_[:4]], a_[4], [round(v, 3) for v in b_[:4]], b_[4])
        reasons = []
        if r["over"] > 0.26: reasons.append(f"overhang {r['over']:.2f}")
        if r["below"]: reasons.append("below street")
        if r["zfight_wall"]: reasons.append(f"{r['zfight_wall']} kit faces in a wall plane")
        if zf_pairs: reasons.append(f"{zf_pairs} coplanar overlapping kit pairs")
        if holes and weak / holes > 0.25: reasons.append(f"{weak}/{holes} recesses on low-contrast art")
        if r["tris"] > 20000: reasons.append(f"{r['tris']} triangles")
        out.append({"id": bid, "archetype": a["archetype"], "triangles": r["tris"], "overhang": round(r["over"], 3), "above_roof": round(r["above_roof"], 2),
                    "zfight_wall": r["zfight_wall"], "zfight_pairs": zf_pairs, "recesses": holes, "weak_recesses": weak, "flagged": bool(reasons), "reasons": reasons})
    # hard check: every roof part (stack, vent, water tower, roof tooth) stands on its host: the map's flat roof at
    # the part's base height (the column's top block one under it, flat, lidded, not a floating deck)
    floating = defaultdict(list)
    ap = kitp + ".anchors.json"
    for a_ in (json.load(open(ap)) if os.path.exists(ap) else []):
        bid_, kind, x, y, base = a_[:5]
        if len(a_) > 5:     # a wall part: the face it is fixed to
            side = a_[5]
            blk = m.block(x, y, base)
            dx, dy = gmap.SIDES[side][3]
            ok = bool(blk) and (blk[gmap.SIDES[side][0]] & 0x3FF) != 0 and (blk[6] >> 2) == 0 and \
                not (0 <= x + dx < W and 0 <= y + dy < H and m.top(x + dx, y + dy)[0] > base)
            if not ok:
                floating[bid_].append(f"{kind}@{x},{y},{base}{side}")
            continue
        off, idx = m.columns[y * W + x]
        top = base - 1 - off
        ok = 0 < top < len(idx) and idx[top] < len(m.blocks) and (m.blocks[idx[top]][6] >> 2) == 0 and (m.blocks[idx[top]][4] & 0x3FF) != 0 \
            and idx[top - 1] < len(m.blocks) and any(f & 0x3FF for f in m.blocks[idx[top - 1]][:5]) and m.top(x, y)[0] == base
        if not ok:
            floating[bid_].append(f"{kind}@{x},{y}")
    for o in out:
        if floating.get(o["id"]):
            o["floating"] = floating[o["id"]]; o["flagged"] = True
            o["reasons"].append(f"{len(floating[o['id']])} parts off their host (" + ", ".join(floating[o["id"]][:3]) + ")")
    path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(work, f"{lvl}_qa.json")
    json.dump(out, open(path, "w"), indent=0)
    fl = [o for o in out if o["flagged"]]
    print(f"{lvl}: {len(out)} buildings checked, {len(fl)} flagged ({100.0 * len(fl) / max(1, len(out)):.0f} %)")
    from collections import Counter
    c = Counter(r.split(" ")[1] if r[0].isdigit() else r.split(" ")[0] for o in fl for r in o["reasons"])
    print("   reasons:", dict(c))
    for o in out[:3]:
        print("  ", o)


if __name__ == "__main__":
    main()
