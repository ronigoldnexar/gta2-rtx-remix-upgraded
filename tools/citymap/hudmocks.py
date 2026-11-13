"""CITYMAP-1: the route on the street views' mini-map, the classic view's GPS disc, and the 3D
ground-chevron concept, as HUD-element mocks over stock frames."""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import gmp, mapart, roadgraph as rg, ui, mocks

OUT = mocks.OUT
REF = mocks.REF
# the mini-map's own tones (hud3d.cpp BuildMap kBase, as they reach the screen)
MM = {0: (12, 15, 20), 1: (24, 52, 72), 2: (53, 59, 71), 3: (31, 51, 38), 4: (42, 47, 58), 5: (94, 102, 118)}

def disc_image(L, g, centre, yaw, R, scale, pts, dest, heading, SS=3, alpha=255):
    """the disc as DrawMapDisc draws it (player low of centre, turned with the camera) + the route"""
    cls, hgt, top, cover, elev, rail = mapart.classify(L)
    D = int(2 * R * SS)
    img = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    cs, sn = math.cos(yaw), math.sin(yaw)
    mc = (D / 2, D / 2); pc = (D / 2, D / 2 + R * 0.18 * SS)
    s = scale * SS
    def to(x, y):
        dx, dy = x - centre[0], y - centre[1]
        r = dx * cs + dy * sn; f = dx * sn - dy * cs
        return (pc[0] + r * s, pc[1] - f * s)
    base = Image.new("RGBA", (D, D), MM[2] + (255,))
    bd = ImageDraw.Draw(base)
    rad = int(R / scale) + 6
    cx, cy = int(centre[0]), int(centre[1])
    for y in range(cy - rad, cy + rad):
        for x in range(cx - rad, cx + rad):
            if not (0 <= x < 256 and 0 <= y < 256): continue
            c = cls[y, x]
            col = MM[5] if (c == 5 or cover[y, x]) else MM[{1: 1, 2: 2, 3: 3, 4: 4}.get(int(c), 0)]
            if col == MM[2]: continue
            e = 0.04
            poly = [to(x - e, y - e), to(x + 1 + e, y - e), to(x + 1 + e, y + 1 + e), to(x - e, y + 1 + e)]
            bd.polygon(poly, fill=col + (255,))
    # the route: casing, colour, travelling dashes (as the full map), clipped by the disc mask
    sp = [to(x, y) for x, y in pts]
    w = 3.2
    bd.line(sp, fill=ui.ROUTE_CASE + (230,), width=int((w + 3) * SS), joint="curve")
    bd.line(sp, fill=ui.ROUTE + (255,), width=int(w * SS), joint="curve")
    # waypoint (on the disc or as a chevron on the rim)
    dp = to(*dest)
    inner = R * SS - 10 * SS
    if math.hypot(dp[0] - mc[0], dp[1] - mc[1]) < inner:
        x, y = dp; r = 6 * SS
        bd.polygon([(x, y - r), (x + r, y), (x, y + r), (x - r, y)], fill=ui.ROUTE, outline=(0, 0, 0), width=SS)
    mask = Image.new("L", (D, D), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, D - 1, D - 1), fill=alpha)
    img.paste(base, (0, 0), mask)
    dr = ImageDraw.Draw(img)
    if math.hypot(dp[0] - mc[0], dp[1] - mc[1]) >= inner:
        ux, uy = dp[0] - pc[0], dp[1] - pc[1]; ul = math.hypot(ux, uy); ux /= ul; uy /= ul
        ox, oy = pc[0] - mc[0], pc[1] - mc[1]
        bq = ox * ux + oy * uy; cq = ox * ox + oy * oy - inner * inner
        t = -bq + math.sqrt(max(0, bq * bq - cq))
        p = (pc[0] + ux * t, pc[1] + uy * t); ang = math.atan2(uy, ux); r = 9 * SS
        tri = [(p[0] + math.cos(ang) * r, p[1] + math.sin(ang) * r), (p[0] + math.cos(ang + 2.4) * r, p[1] + math.sin(ang + 2.4) * r), (p[0] + math.cos(ang - 2.4) * r, p[1] + math.sin(ang - 2.4) * r)]
        dr.polygon(tri, fill=ui.ROUTE, outline=(0, 0, 0), width=SS)
    # the player arrow, rim, north
    a = heading - yaw
    ui.player_marker(dr, (pc[0] / SS, pc[1] / SS), a, SS, r=9, halo=False)
    dr.ellipse((0, 0, D - 1, D - 1), outline=(0, 0, 0, 200), width=3 * SS)
    dr.ellipse((SS, SS, D - 1 - SS, D - 1 - SS), outline=(244, 240, 228, 150), width=int(1.2 * SS))
    npx = (mc[0] - sn * R * SS, mc[1] - cs * R * SS)
    dr.ellipse((npx[0] - 8.5 * SS, npx[1] - 8.5 * SS, npx[0] + 8.5 * SS, npx[1] + 8.5 * SS), fill=(20, 22, 28, 240), outline=(244, 240, 228, 150), width=SS)
    f = ImageFont.truetype(ui.FONT_SB, 11 * SS)
    dr.text(npx, "N", font=f, fill=ui.WHITE, anchor="mm")
    return img.resize((int(2 * R), int(2 * R)), Image.LANCZOS)

def gps_chip(dr, x, y, turn, dist, SS=1):
    """the read-out over the disc: the next turn and the distance left"""
    fb = ImageFont.truetype(ui.FONT_XB, 17); fs = ImageFont.truetype(ui.FONT_BI, 14)
    w = 200; h = 30
    dr.rounded_rectangle((x, y, x + w, y + h), radius=5, fill=(10, 12, 18, 170))
    dr.rounded_rectangle((x, y, x + h, y + h), radius=5, fill=ui.ROUTE + (255,))
    cx, cy = x + h / 2, y + h / 2
    sgn = 1 if turn[1] == "RIGHT" else -1
    dr.line([(cx - sgn * 4, cy + 9), (cx - sgn * 4, cy - 1), (cx + sgn * 4, cy - 1)], fill=ui.WHITE, width=3, joint="curve")
    dr.polygon([(cx + sgn * 9, cy - 1), (cx + sgn * 3, cy - 6), (cx + sgn * 3, cy + 4)], fill=ui.WHITE)
    dr.text((x + h + 8, cy), f"{turn[0]}", font=fb, fill=ui.WHITE, anchor="lm")
    dr.text((x + w - 8, cy), f"{dist}", font=fs, fill=(244, 240, 228, 200), anchor="rm")

def main():
    lv, origin, heading, dname = "wil", (150.5, 168.5), 0.0, "Zaibatsu HQ"
    L, g, dn, sn, path, pts, t1, origin = mocks.plan(lv, origin, heading, dname)
    raw = mocks.plan.raw
    heading = math.atan2(raw[1][0] - raw[0][0], -(raw[1][1] - raw[0][1]))
    # put him 8 blocks along the route, the camera behind him
    me, hd, rest = rg.along(pts, 22.0)
    _, _, rest_raw = rg.along(raw, 22.0)
    nt = rg.next_turn(rest_raw)
    # (a) third person: the street views' mini-map with the route
    fr = Image.open(os.path.join(REF, "third.png")).convert("RGBA")
    R = 100; scale = 260.0 / 64.0   # in a car: 64 blocks across the old square
    disc = disc_image(L, g, me, hd, R, scale, rest, pts[-1], hd)
    fr.alpha_composite(disc, (128 - R, 575 - R))
    dr = ImageDraw.Draw(fr)
    gps_chip(dr, 28, 440, (mocks.fmt_m(nt[0]) if nt else "", nt[1] if nt else "RIGHT"), mocks.fmt_m(rg.length(rest)))
    fr.convert("RGB").save(os.path.join(OUT, "mock_minimap_third.png"))
    # (b) classic: the same disc, smaller, shown only while a waypoint is set
    fc = Image.open(os.path.join(REF, "plain15.png")).convert("RGBA")
    R2 = 78
    disc2 = disc_image(L, g, me, 0.0, R2, 260.0 / 64.0 * 0.8, rest, pts[-1], hd)
    fc.alpha_composite(disc2, (24, 720 - 24 - 2 * R2))
    dr = ImageDraw.Draw(fc)
    gps_chip(dr, 24, 720 - 24 - 2 * R2 - 40, (mocks.fmt_m(nt[0]) if nt else "", nt[1] if nt else "RIGHT"), mocks.fmt_m(rg.length(rest)))
    fc.convert("RGB").save(os.path.join(OUT, "mock_classic_disc.png"))

if __name__ == "__main__":
    main()

def chevrons_concept():
    """3D guidance concept over a chase frame: flat chevrons on the road ahead, projected by a
    pinhole fitted to the paving (F 700, eye 1.33 blocks up, horizon y 95), in the HUD layer;
    the ones the player's car covers on screen are left out (its projected box)."""
    fr = Image.open(os.path.join(REF, "chase.png")).convert("RGBA")
    W, H = fr.size
    ov = Image.new("RGBA", (W * 2, H * 2), (0, 0, 0, 0)); dr = ImageDraw.Draw(ov)
    F, Hc, yh = 700.0, 1.33, 95.0
    def P(X, Z): return ((640 + F * X / Z) * 2, (yh + F * Hc / Z) * 2)
    carbox = (505, 205, 780, 455)
    # the route on the ground: ahead to Z 7.3, then left along the road
    path = [(0.0, 3.0), (0.0, 7.0), (-0.4, 7.3), (-9.0, 7.3)]
    pts = []
    for (x0, z0), (x1, z1) in zip(path, path[1:]):
        L = math.hypot(x1 - x0, z1 - z0); n = max(1, int(L / 0.05))
        for i in range(n): pts.append((x0 + (x1 - x0) * i / n, z0 + (z1 - z0) * i / n, (x1 - x0) / L, (z1 - z0) / L))
    acc = 0.0; last = None; spacing = 0.95
    for x, z, dx, dz in pts:
        if last is not None: acc += math.hypot(x - last[0], z - last[1])
        last = (x, z)
        if acc < spacing: continue
        acc = 0.0
        px, py = P(x, z)
        if carbox[0] * 2 < px < carbox[2] * 2 and carbox[1] * 2 < py < carbox[3] * 2: continue
        # nearer people and cars cover it: their projected boxes (feet to head), as the DLL knows them
        if any(b[0] * 2 < px < b[2] * 2 and b[1] * 2 < py < b[3] * 2 for b in ((425, 165, 495, 345), (800, 140, 885, 300), (900, 150, 965, 300))): continue
        # a chevron: tip ahead along (dx,dz), arms back 0.32 and out 0.28 blocks, 0.12 thick
        sx, sz = dz, -dx
        def g(a, b): return (x + dx * a + sx * b, z + dz * a + sz * b)
        outer = [g(0.18, 0), g(-0.14, 0.30), g(-0.26, 0.30), g(0.02, 0.06), g(0.02, -0.06), g(-0.26, -0.30), g(-0.14, -0.30)]
        outer = [g(0.18, 0), g(-0.14, -0.30), g(-0.26, -0.30), g(0.03, 0), g(-0.26, 0.30), g(-0.14, 0.30)]
        fade = max(0.0, min(1.0, (z - 3.0) / 1.2)) * max(0.0, min(1.0, (12 - z) / 4))
        a = int(170 * fade)
        sh = [P(u + 0.03, v + 0.03) for u, v in outer]
        dr.polygon(sh, fill=(0, 0, 0, int(a * 0.5)))
        dr.polygon([P(u, v) for u, v in outer], fill=ui.ROUTE + (a,), outline=ui.ROUTE_HI + (min(255, a + 40),))
    fr.alpha_composite(ov.resize((W, H), Image.LANCZOS))
    d2 = ImageDraw.Draw(fr)
    f = ImageFont.truetype(ui.FONT_BI, 15)
    d2.rounded_rectangle((330, 668, 960, 700), radius=5, fill=(10, 12, 18, 200))
    d2.text((645, 684), "CONCEPT (hand-fitted camera): route chevrons on the road, HUD layer, left out behind his car and nearer people", font=f, fill=(255, 200, 232), anchor="mm")
    fr.convert("RGB").save(os.path.join(OUT, "mock_3d_chevrons_concept.png"))

if __name__ == "__main__":
    chevrons_concept()
