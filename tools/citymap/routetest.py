"""CITYMAP-1 offline route test: origin/destination pairs per level, checked and drawn on the map."""
import math, os, random, time, json
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import gmp, mapart, roadgraph as rg, ui

HERE = os.path.dirname(os.path.abspath(__file__))
import mocks
G, OUT = mocks.G, mocks.OUT
gxt = gmp.read_gxt(os.path.join(G, "e.gxt"))
COLS = [(255, 62, 170), (64, 200, 240), (255, 206, 32), (120, 230, 120), (255, 140, 60), (190, 120, 255), (255, 255, 255), (255, 90, 90)]

def check_car_path(g, path):
    """independent of the search: every step must follow the from-cell's arrows, be a lane change
    onto a lane running the same way, or leave an arrowless cell"""
    wrong = lanes = free = 0
    inv = {v: k for k, v in rg.DIRS.items()}
    for a, b in zip(path, path[1:]):
        xa, ya, za, ga, sa, ara, _ = g.nodes[a]; xb, yb, zb, gb, sb, arb, _ = g.nodes[b]
        d = (xb - xa, yb - ya)
        bit = inv.get(d)
        if bit is None:
            wrong += 1; continue
        if ara & 0xFF == 0:
            free += 1
        elif ara & (bit | bit << 4):
            pass
        elif any((ara & k) and (arb & k) and (rg.DIRS[k][0] * d[0] + rg.DIRS[k][1] * d[1]) == 0 for k in rg.DIRS):
            lanes += 1
        else:
            wrong += 1
    return wrong, lanes, free

def landmarks(L):
    pts = {}
    for t, x, y, w, h, k in L.zones:
        if t in (15, 16) and (k in gxt or k.startswith("restart")):
            name = gxt.get(k, k)
            pts.setdefault(name, (x + w / 2, y + h / 2))
    return pts

RUNPATHS = {}

def run(lv, pairs, extra):
    L = gmp.Level(os.path.join(G, lv + ".gmp"))
    t = time.time(); g = rg.Graph(L); tb = time.time() - t
    base_np, _ = mapart.bake(L, 8, g)
    S = 4  # px a cell in the sheet
    img = Image.fromarray(base_np).resize((256 * S, 256 * S), Image.LANCZOS).convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0)); dr = ImageDraw.Draw(ov)
    f = ImageFont.truetype(ui.FONT_XB, 22); fs = ImageFont.truetype(ui.FONT_SB, 15)
    rows = []
    for idx, (oname, o, dname, d, mode) in enumerate(pairs + extra):
        if mode == "car-raw": mode = "car"
        want = (1,) if mode == "car" else (1, 2, 3)
        oz = o[2] if len(o) > 2 else 2.0
        t = time.time(); P = rg.plan_route(g, o[0], o[1], oz, None, d[0], d[1], mode); ts = time.time() - t
        if len(d) > 2:   # an explicit goal node (the crossing tests): no snapping
            P = dict(P); dist, nxt = g.cost_to(d[2], mode); sn = g.start_node(o[0], o[1], oz, None, dist, mode)
            P.update(goal=d[2], start=sn, path=g.path(sn, nxt), dist=dist, pre=0.0, post=0.0)
        dn, sn, path, dist = P["goal"], P["start"], P["path"], P["dist"]
        fallback = P["pre"] > 8 or P["post"] > 8
        # optimality cross-check: a forward search from the start gives the same cost
        fd, _ = g.forward(sn, mode)
        same = abs(fd.get(dn, -1) - dist[sn]) < 1e-6
        wrong, lanes, free = check_car_path(g, path) if mode == "car" else (0, 0, 0)
        levels = sorted({g.nodes[i][2] for i in path})
        # true crossings: the path's cell also holds a road at another level (over or under it)
        over = under = 0
        for i in path:
            x, y, z = g.nodes[i][:3]
            others = [g.nodes[j][2] for j in g.cell.get((x, y), ()) if j != i and g.nodes[j][3] == 1]
            if any(o < z for o in others): over += 1
            if any(o > z for o in others): under += 1
        raw = g.polyline(path, centre=(mode == "car"), want=want)
        pts = rg.fillet(raw, 1.4)
        col = COLS[idx % len(COLS)]
        sp = [(x * S, y * S) for x, y in pts]
        w = 7 if mode == "car" else 5
        dr.line(sp, fill=(0, 0, 0, 220), width=w + 4, joint="curve")
        if mode == "car":
            dr.line(sp, fill=col + (255,), width=w, joint="curve")
        else:
            # walking: dotted
            acc = 0
            for k in range(1, len(sp)):
                a, b = sp[k - 1], sp[k]; Lk = math.hypot(b[0] - a[0], b[1] - a[1])
                tt = 0
                while tt < Lk:
                    if (acc + tt) % 14 < 8:
                        e = min(Lk, tt + 8 - (acc + tt) % 14)
                        dr.line((a[0] + (b[0] - a[0]) * tt / Lk, a[1] + (b[1] - a[1]) * tt / Lk, a[0] + (b[0] - a[0]) * e / Lk, a[1] + (b[1] - a[1]) * e / Lk), fill=col + (255,), width=w)
                        tt = e + 0.01
                    else:
                        tt += 14 - (acc + tt) % 14
                acc += Lk
        # elevated stretches: a white edge where the path runs above street level
        for a, b in zip(path, path[1:]):
            if g.nodes[a][2] >= 2 and g.nodes[b][2] >= 2:
                pass
        lab = chr(65 + idx)
        for (x, y), s, fill in ((sp[0], lab, col), (sp[-1], lab + "'", col)):
            dr.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(0, 0, 0, 230), outline=fill + (255,), width=3)
            dr.text((x, y + 1), s, font=fs, fill=fill + (255,), anchor="mm")
        def dashed(p, q):
            Lq = math.hypot(q[0] - p[0], q[1] - p[1]); n = max(1, int(Lq / 10))
            for k in range(0, n, 2):
                dr.line((p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n, p[0] + (q[0] - p[0]) * (k + 1) / n, p[1] + (q[1] - p[1]) * (k + 1) / n), fill=col + (255,), width=3)
        if P["pre"] > 8:
            dashed((o[0] * S, o[1] * S), sp[0])
            dr.rectangle((o[0] * S - 6, o[1] * S - 6, o[0] * S + 6, o[1] * S + 6), outline=col + (255,), width=3)
        if P["post"] > 8:
            dashed(sp[-1], (d[0] * S, d[1] * S))
            dr.rectangle((d[0] * S - 6, d[1] * S - 6, d[0] * S + 6, d[1] * S + 6), outline=col + (255,), width=3)
        RUNPATHS[(lv, idx)] = set(path)
        rows.append(dict(id=lab, mode=mode, origin=oname, dest=dname, cells=round(rg.length(pts), 1),
                         metres=int(rg.length(pts) * ui.MPB), nodes=len(path), levels=levels,
                         search_ms=round(ts * 1000, 1), wrong_way_steps=wrong, lane_changes=lanes, arrowless_steps=free,
                         forward_check=bool(same), fallback=fallback, over=over, under=under, reached=len(dist), pre=P['pre'], post=P['post']))
    img = Image.alpha_composite(img, ov).convert("RGB")
    # legend strip
    W = img.width + 700
    sheet = Image.new("RGB", (W, img.height), (9, 11, 16))
    sheet.paste(img, (0, 0))
    d2 = ImageDraw.Draw(sheet)
    x0 = img.width + 20
    d2.text((x0, 18), f"{ui.LEVEL_TITLE[lv]} ({lv}.gmp): route test", font=ImageFont.truetype(ui.FONT_XB, 30), fill=ui.YELLOW)
    d2.text((x0, 58), f"graph: {len(g.nodes)} surface nodes, {g.nroad} road; car edges {sum(map(len, g.car))}, "
                      f"walk edges {sum(map(len, g.walk))}; built in {tb:.2f} s (Python)", font=fs, fill=(220, 220, 220))
    y = 92
    for r, col in zip(rows, [COLS[i % len(COLS)] for i in range(len(rows))]):
        d2.text((x0, y), f"{r['id']} → {r['id']}'  {r['mode'].upper()}", font=ImageFont.truetype(ui.FONT_XB, 20), fill=col)
        d2.text((x0 + 120, y + 2), f"{r['origin']}  →  {r['dest']}", font=fs, fill=(240, 240, 240))
        y += 24
        flags = []
        if r["fallback"]: flags.append(f"off the network: dashed hops {r['pre']:.0f} / {r['post']:.0f} cells (square = asked spot)")
        if len(r["levels"]) > 1: flags.append("multi-level: levels " + ",".join(map(str, r["levels"])) + f"; {r['over']} cells over another road, {r['under']} under one")
        d2.text((x0 + 18, y), f"{r['metres']} m, {r['nodes']} nodes, search {r['search_ms']} ms; wrong-way steps {r['wrong_way_steps']}, "
                              f"lane changes {r['lane_changes']}, forward check {'OK' if r['forward_check'] else 'MISMATCH'}", font=fs, fill=(190, 196, 206))
        y += 20
        if flags:
            d2.text((x0 + 18, y), "; ".join(flags), font=fs, fill=(255, 170, 210)); y += 20
        y += 8
    sheet.save(os.path.join(OUT, f"routes_{lv}.png"))
    return rows

CHECK = []

def main():
    random.seed(7)
    allrows = {}
    for lv in ("wil", "ste", "bil"):
        L = gmp.Level(os.path.join(G, lv + ".gmp"))
        lm = landmarks(L)
        names = sorted(lm)
        pairs = []
        rnd = random.Random(lv)
        picks = rnd.sample(names, min(12, len(names)))
        for i in range(0, 10, 2):
            pairs.append((picks[i], lm[picks[i]], picks[i + 1], lm[picks[i + 1]], "car"))
        extra = []
        if lv == "ste":
            # over the elevated expressway (level 4 road, rows 59-60) and onto the 30-node island
            extra.append(("west end of the expressway", (40.0, 59.5), "east of it", (200.0, 59.5), "car"))
            extra.append(("Central Cop HQ", lm["Central Cop HQ"], "the closed yard (88,154)", (88.5, 154.5), "car-raw"))
        extra.append((picks[0], lm[picks[0]], picks[1], lm[picks[1]], "walk"))
        # a bridge: one route along the deck, one along the road under it, through the same cell
        g0 = rg.Graph(L)
        for (x, y), ids in sorted(g0.cell.items()):
            r_ = [i for i in ids if g0.nodes[i][3] == 1 and g0.main['car'][i]]
            if len(set(g0.nodes[i][2] for i in r_)) > 1:
                for i in sorted(r_, key=lambda i: -g0.nodes[i][2]):
                    a = i
                    for _ in range(14): a = g0.car_rev[a][0][0]
                    b = i
                    for _ in range(14): b = g0.car[b][0][0]
                    na, nb = g0.nodes[a], g0.nodes[b]
                    tag = "deck" if g0.nodes[i][2] > min(g0.nodes[j][2] for j in r_) else "under"
                    extra.append((f"{tag} of ({x},{y}) level {g0.nodes[i][2]}, 14 back", (na[0] + .5, na[1] + .5, na[2] + 1.0),
                                  f"14 on (must pass level {g0.nodes[i][2]} at ({x},{y}))", (nb[0] + .5, nb[1] + .5, b), "car"))
                    CHECK.append((lv, len(pairs) + len(extra) - 1, i))
                break
        allrows[lv] = run(lv, pairs, extra)
        for lvl, k, node in CHECK:
            if lvl == lv:
                allrows[lv][k]["passes_crossing_node"] = node in RUNPATHS[(lv, k)]
        for r in allrows[lv]:
            print(lv, r)
    json.dump(allrows, open(os.path.join(OUT, "routes.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
