#!/usr/bin/env python3
"""Review sheets for the districts POC (art stays out of git: sheets are written to a work dir).

    sheet.py archetypes <work> <lvl> <hd dir> <out.png> [per archetype N]
        per archetype the N largest buildings: their longest wall as an elevation (tiles as the renderer
        maps them onto the wall, seen from outside), detected openings outlined, the evidence printed.
    sheet.py building <work> <lvl> <hd dir> <id> <out.png>
        every exterior wall run of one building as elevations."""
import json, os, sys
from collections import defaultdict
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import FaceFrame

PX = 40
HAXIS = {"N": (-1, 0, 0), "S": (1, 0, 0), "E": (0, 0, 1), "W": (0, 0, -1)}
COL = {"window": (80, 200, 255), "door": (255, 200, 60), "loading_door": (255, 120, 0), "shop window": (60, 255, 120), "sill": (255, 80, 200)}


def runs(b):
    """exterior faces grouped into straight runs: same side, same row/column, contiguous"""
    by = defaultdict(list)
    for f in b["faces"]:
        key = (f["side"], f["y"] if f["side"] in "NS" else f["x"])
        by[key].append(f)
    out = []
    for (side, line), fs in by.items():
        along = (lambda f: f["x"]) if side in "NS" else (lambda f: f["y"])
        fs.sort(key=along)
        cur = [fs[0]]
        for f in fs[1:]:
            if along(f) == along(cur[-1]) + 1:
                cur.append(f)
            else:
                out.append((side, cur)); cur = [f]
        out.append((side, cur))
    return out


def elevation(run, lvl, hd, tiles, cache):
    side, fs = run
    ha = HAXIS[side]
    lo = min(l["level"] for f in fs for l in f["levels"])
    hi = max(l["level"] for f in fs for l in f["levels"]) + 1
    pts = []
    for f in fs:
        for l in f["levels"]:
            fr = FaceFrame(f["x"], f["y"], l["level"], side, l["raw"])
            p = fr.at(32, 32)
            pts.append(p[0] * ha[0] + p[2] * ha[2])
    h0 = min(pts) - 0.5
    wpx = int(round((max(pts) + 0.5 - h0) * PX))
    img = Image.new("RGB", (max(wpx, 4), (hi - lo) * PX), (30, 30, 30))
    dr = ImageDraw.Draw(img)
    for f in fs:
        for l in f["levels"]:
            if not l["tile"]:
                continue
            fr = FaceFrame(f["x"], f["y"], l["level"], side, l["raw"])
            def proj(tx, ty):
                p = fr.at(tx, ty)
                return ((p[0] * ha[0] + p[2] * ha[2] - h0) * PX, (hi - p[1]) * PX)
            o = np.array(proj(0, 0)); ax = np.array(proj(64, 0)) - o; ay = np.array(proj(0, 64)) - o
            M = np.array([[ax[0] / 64, ay[0] / 64], [ax[1] / 64, ay[1] / 64]])
            Mi = np.linalg.inv(M)
            t = cache.get(l["tile"])
            if t is None:
                p = os.path.join(hd, lvl, f"tile_{l['tile']:04d}.dds")
                t = Image.open(p).convert("RGB").resize((64, 64), Image.BOX) if os.path.exists(p) else Image.new("RGB", (64, 64), (255, 0, 255))
                cache[l["tile"]] = t
            # output (X, Y) -> texel = Mi @ ((X, Y) - o)
            c = (Mi[0, 0], Mi[0, 1], -(Mi[0, 0] * o[0] + Mi[0, 1] * o[1]), Mi[1, 0], Mi[1, 1], -(Mi[1, 0] * o[0] + Mi[1, 1] * o[1]))
            warped = t.transform(img.size, Image.AFFINE, c, resample=Image.NEAREST)
            mask = Image.new("L", (64, 64), 255).transform(img.size, Image.AFFINE, c, resample=Image.NEAREST)
            img.paste(warped, (0, 0), mask)
            for ob in tiles.get(str(l["tile"]), {}).get("openings", []):
                x0, y0, x1, y1 = ob["box"]
                q = [proj(x0, y0), proj(x1, y0), proj(x1, y1), proj(x0, y1)]
                dr.polygon(q, outline=COL.get(ob["kind"], (255, 255, 255)))
    return img


def main():
    mode = sys.argv[1]
    work, lvl, hd = sys.argv[2:5]
    cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
    an = json.load(open(os.path.join(work, f"{lvl}_analysis.json")))
    tiles = an["tiles"]
    arch = {b["id"]: b for b in an["buildings"]}
    cache = {}
    if mode == "archetypes":
        out = sys.argv[5]; n = int(sys.argv[6]) if len(sys.argv) > 6 else 4
        groups = defaultdict(list)
        for i, a in arch.items():
            groups[a["archetype"]].append(i)
        rows = []
        for k in sorted(groups):
            ids = sorted(groups[k], key=lambda i: -cat[i]["area"] * max(1, cat[i]["levels"]))[:n]
            cells = []
            for i in ids:
                r = max(runs(cat[i]), key=lambda r: len(r[1]) * max(1, len(r[1][0]["levels"])))
                if len(r[1]) > 8:
                    r = (r[0], r[1][:8])
                el = elevation(r, lvl, hd, tiles, cache)
                ev = arch[i]["evidence"]
                lab = f"#{i} {k} lv{ev['levels']} a{ev['area']} win{ev['window_share']:.2f} br{ev['brick']:.2f} rib{ev['rib']:.2f} shop{ev['shop_street']:.2f}"
                c = Image.new("RGB", (max(el.width, 330), el.height + 14), (15, 15, 15))
                c.paste(el, (0, 14)); ImageDraw.Draw(c).text((2, 1), lab, fill=(255, 255, 255))
                cells.append(c)
            if cells:
                w = sum(c.width for c in cells) + 6 * len(cells); h = max(c.height for c in cells)
                row = Image.new("RGB", (w, h), (0, 0, 0)); x = 0
                for c in cells:
                    row.paste(c, (x, 0)); x += c.width + 6
                rows.append(row)
        W_ = max(r.width for r in rows); H_ = sum(r.height + 6 for r in rows)
        sheet = Image.new("RGB", (W_, H_), (0, 0, 0)); y = 0
        for r in rows:
            sheet.paste(r, (0, y)); y += r.height + 6
        sheet.save(out)
    elif mode == "building":
        i = int(sys.argv[5]); out = sys.argv[6]
        rs = sorted(runs(cat[i]), key=lambda r: -len(r[1]))
        els = [(r[0], elevation(r, lvl, hd, tiles, cache)) for r in rs[:8]]
        W_ = sum(e.width + 8 for _, e in els); H_ = max(e.height for _, e in els) + 16
        sheet = Image.new("RGB", (W_, H_), (0, 0, 0)); x = 0
        for s, e in els:
            sheet.paste(e, (x, 16)); ImageDraw.Draw(sheet).text((x + 2, 2), s, fill=(255, 255, 255)); x += e.width + 8
        sheet.save(out)


if __name__ == "__main__":
    main()
