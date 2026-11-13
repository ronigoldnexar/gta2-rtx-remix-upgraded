"""CITYMAP-1 mock frames: the full-screen map overlay as the DLL will draw it (ImGui draw lists)."""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import gmp, mapart, roadgraph as rg

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.environ.get("CITYMAP_FONTS", os.path.join(HERE, "..", "..", "assets", "fonts"))
FONT_XB = os.path.join(FONTS, "BarlowCondensed-ExtraBoldItalic-hud.ttf")
FONT_BI = os.path.join(FONTS, "BarlowCondensed-BoldItalic-hud.ttf")
FONT_SB = os.path.join(FONTS, "BarlowCondensed-SemiBold-hud.ttf")

WHITE = (244, 240, 228)
YELLOW = (255, 206, 32)
CYAN = (64, 200, 240)
ROUTE = (255, 62, 170)        # the GPS colour: apart from the jobs' yellow and the phones' cyan
ROUTE_HI = (255, 200, 232)
ROUTE_CASE = (40, 4, 26)
LEVEL_TITLE = {"wil": "DOWNTOWN", "ste": "RESIDENTIAL", "bil": "INDUSTRIAL"}
MPB = 5.0     # metres a block, for the read-outs ([citymap] metres_per_block)

def font(path, px):
    return ImageFont.truetype(path, int(round(px)))

def districts(L, gxt):
    """name -> list of rects; district names (nav zones and the 'm' info zones) and landmarks"""
    dist, land = {}, {}
    for typ, x, y, w, h, key in L.zones:
        name = gxt.get(key)
        if not name:
            continue
        name = name.lstrip("ⅺ").strip()
        if typ == 1 or (typ == 15 and key[:1].lower() == "m"):
            dist.setdefault(name, []).append((x, y, w, h))
        elif typ == 15:
            land.setdefault(name, []).append((x, y, w, h))
    return dist, land

def zone_at(L, gxt, x, y):
    best, ba = None, 1e9
    for typ, zx, zy, w, h, key in L.zones:
        if (typ == 1 or (typ == 15 and key[:1].lower() == "m")) and zx <= x < zx + w and zy <= y < zy + h and w * h < ba:
            best, ba = gxt.get(key, key), w * h
    return best

class View:
    """map cells -> screen pixels: centre (cx, cy) in cells, s pixels a cell, the map's screen rect"""
    def __init__(self, rect, cx, cy, s):
        self.rect, self.cx, self.cy, self.s = rect, cx, cy, s
    def to(self, x, y):
        x0, y0, x1, y1 = self.rect
        return ((x - self.cx) * self.s + (x0 + x1) / 2, (y - self.cy) * self.s + (y0 + y1) / 2)

def draw_map_layer(base, ppc, view, size, SS):
    """the baked map resampled into the view (what the rectangles draw)"""
    Wd, Hd = size
    x0, y0, x1, y1 = view.rect
    out = Image.new("RGB", (Wd * SS, Hd * SS), mapart.VOID)
    # source crop for the whole viewport
    a = view.cx - (x1 - x0) / 2 / view.s; b = view.cy - (y1 - y0) / 2 / view.s
    c = view.cx + (x1 - x0) / 2 / view.s; d = view.cy + (y1 - y0) / 2 / view.s
    crop = base.transform((int((x1 - x0) * SS), int((y1 - y0) * SS)), Image.EXTENT,
                          (a * ppc, b * ppc, c * ppc, d * ppc), resample=Image.BILINEAR, fillcolor=mapart.VOID)
    out.paste(crop, (int(x0 * SS), int(y0 * SS)))
    return out

def polyline(dr, pts, col, w, SS):
    pts = [(p[0] * SS, p[1] * SS) for p in pts]
    dr.line(pts, fill=col, width=int(round(w * SS)), joint="curve")
    r = w * SS / 2
    for p in (pts[0], pts[-1]):
        dr.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=col)

def text(dr, xy, s, f, fill, anchor="la", shadow=True, SS=1, spacing=0, stroke=0):
    x, y = xy[0] * SS, xy[1] * SS
    if spacing:
        # letter-spaced: draw glyph by glyph
        total = sum(f.getlength(ch) for ch in s) + spacing * SS * (len(s) - 1)
        if anchor[0] == "m": x -= total / 2
        elif anchor[0] == "r": x -= total
        for ch in s:
            if shadow: dr.text((x + 1.5 * SS, y + 1.5 * SS), ch, font=f, fill=(0, 0, 0, 170), anchor="l" + anchor[1])
            if stroke: dr.text((x, y), ch, font=f, fill=(8, 10, 14, 210), anchor="l" + anchor[1], stroke_width=int(stroke * SS), stroke_fill=(8, 10, 14, 210))
            dr.text((x, y), ch, font=f, fill=fill, anchor="l" + anchor[1])
            x += f.getlength(ch) + spacing * SS
        return
    if shadow:
        dr.text((x + 1.5 * SS, y + 1.5 * SS), s, font=f, fill=(0, 0, 0, 170), anchor=anchor)
    dr.text((x, y), s, font=f, fill=fill, anchor=anchor, stroke_width=int(stroke * SS), stroke_fill=(8, 10, 14, 210))

def keycap(dr, x, y, label, f, SS, h=20):
    w = max(h, f.getlength(label) / SS + 12)
    dr.rounded_rectangle((x * SS, y * SS, (x + w) * SS, (y + h) * SS), radius=4 * SS, fill=(232, 228, 216, 235))
    dr.text(((x + w / 2) * SS, (y + h / 2 + 0.5) * SS), label, font=f, fill=(16, 18, 24), anchor="mm")
    return w

def player_marker(dr, p, heading, SS, r=11, halo=True):
    """white arrow with a dark rim and a soft cyan halo, along the heading (radians, 0 = north)"""
    x, y = p[0] * SS, p[1] * SS
    rr = r * SS
    for k, a in (((2.2, 40), (1.7, 60)) if halo else ()):
        dr.ellipse((x - rr * k, y - rr * k, x + rr * k, y + rr * k), fill=CYAN + (a,))
    f = (math.sin(heading), -math.cos(heading)); s = (math.cos(heading), math.sin(heading))
    tip = (x + f[0] * rr, y + f[1] * rr)
    l = (x - f[0] * rr * 0.75 - s[0] * rr * 0.8, y - f[1] * rr * 0.75 - s[1] * rr * 0.8)
    rgt = (x - f[0] * rr * 0.75 + s[0] * rr * 0.8, y - f[1] * rr * 0.75 + s[1] * rr * 0.8)
    back = (x - f[0] * rr * 0.3, y - f[1] * rr * 0.3)
    dr.polygon([tip, rgt, back, l], fill=WHITE, outline=(0, 0, 0), width=int(2 * SS))

def waypoint(dr, p, SS, t=0.35, label=None, f=None):
    x, y = p[0] * SS, p[1] * SS
    # pulse ring
    R = (14 + 10 * t) * SS
    dr.ellipse((x - R, y - R, x + R, y + R), outline=ROUTE + (int(200 * (1 - t)),), width=int(2 * SS))
    # pin: a diamond on a short stem, the GTA2 objective arrow's shape language
    h = 22 * SS; w = 9 * SS
    top = y - h
    dr.line((x, y, x, top + w), fill=(0, 0, 0, 200), width=int(4 * SS))
    dr.line((x, y, x, top + w), fill=ROUTE, width=int(2 * SS))
    pts = [(x, top - w), (x + w, top), (x, top + w), (x - w, top)]
    dr.polygon(pts, fill=ROUTE, outline=(0, 0, 0), width=int(2 * SS))
    dr.polygon([(x, top - w * 0.45), (x + w * 0.45, top), (x, top + w * 0.45), (x - w * 0.45, top)], fill=ROUTE_HI)
    dr.ellipse((x - 3 * SS, y - 3 * SS, x + 3 * SS, y + 3 * SS), fill=ROUTE, outline=(0, 0, 0), width=int(1 * SS))

def route_draw(dr, pts_screen, SS, w=4.0, dash_phase=0.0):
    polyline(dr, pts_screen, ROUTE_CASE + (230,), w + 4, SS)
    polyline(dr, pts_screen, ROUTE, w, SS)
    # travelling highlights: short bright dashes every 22 px (animated in game)
    seg = []
    acc = -dash_phase
    for k in range(1, len(pts_screen)):
        a, b = pts_screen[k - 1], pts_screen[k]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        t = 0.0
        while L > 0 and t < L:
            ph = (acc + t) % 22.0
            if ph < 6.0:
                e = min(L, t + (6.0 - ph))
                seg.append(((a[0] + (b[0] - a[0]) * t / L, a[1] + (b[1] - a[1]) * t / L),
                            (a[0] + (b[0] - a[0]) * e / L, a[1] + (b[1] - a[1]) * e / L)))
                t = e + 1e-3
            else:
                t += 22.0 - ph
        acc += L
    for p, q in seg:
        dr.line((p[0] * SS, p[1] * SS, q[0] * SS, q[1] * SS), fill=ROUTE_HI, width=int(max(1, (w - 2.0)) * SS))

def frame(level, gxt, base, ppc, size, view, player, heading, dest=None, route=None, cursor=None,
          backdrop=None, info=None, SS=2, show_grid=True, t=0.35, title_note=None):
    Wd, Hd = size
    u = Hd / 720.0
    img = draw_map_layer(base, ppc, view, size, SS).convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(ov)
    x0, y0, x1, y1 = view.rect
    # backdrop outside the map: the game frame under a scrim
    if backdrop is not None:
        bd = backdrop.convert("RGB").resize(img.size, Image.LANCZOS)
        bd = Image.blend(bd, Image.new("RGB", bd.size, (6, 8, 12)), 0.86).convert("RGBA")
        mask = Image.new("L", img.size, 255)
        e0_ = view.to(0, 0); e1_ = view.to(256, 256)
        ImageDraw.Draw(mask).rectangle((max(x0, e0_[0]) * SS, max(y0, e0_[1]) * SS, min(x1, e1_[0]) * SS - 1, min(y1, e1_[1]) * SS - 1), fill=0)
        img.paste(bd, (0, 0), mask)
    # the level's edge
    e0 = view.to(0, 0); e1 = view.to(256, 256)
    dr.rectangle((e0[0] * SS, e0[1] * SS, e1[0] * SS, e1[1] * SS), outline=(255, 255, 255, 40), width=int(1 * SS))
    # grid every 32 cells: a faint survey grid, lettered along the top and numbered down the side
    if show_grid:
        fg = font(FONT_SB, 11 * u * SS)
        for k in range(1, 8):
            gx = view.to(k * 32, 0)[0]; gy = view.to(0, k * 32)[1]
            if x0 < gx < x1:
                dr.line((gx * SS, max(y0, e0[1]) * SS, gx * SS, min(y1, e1[1]) * SS), fill=(255, 255, 255, 14), width=int(SS))
            if y0 < gy < y1:
                dr.line((max(x0, e0[0]) * SS, gy * SS, min(x1, e1[0]) * SS, gy * SS), fill=(255, 255, 255, 14), width=int(SS))
        for k in range(8):
            gx = view.to(k * 32 + 16, 0)[0]; gy = view.to(0, k * 32 + 16)[1]
            ly = max(y0, e0[1]) + 6 * u; lx = max(x0, e0[0]) + 6 * u
            if x0 + 10 < gx < x1 - 10:
                text(dr, (gx, ly), "ABCDEFGH"[k], fg, (255, 255, 255, 110), "mt", True, SS)
            if y0 + 10 < gy < y1 - 10:
                text(dr, (lx, gy), str(k + 1), fg, (255, 255, 255, 110), "lm", True, SS)
    # district names
    dist, land = districts(level["L"], gxt)
    placed = []
    items = []
    for name, rects in dist.items():
        area = sum(w * h for _, _, w, h in rects)
        bx, by, bw, bh = max(rects, key=lambda r: r[2] * r[3])
        items.append((area, name, bx + bw / 2, by + bh / 2))
    items.sort(reverse=True)
    for area, name, cx, cy in items:
        p = view.to(cx, cy)
        px = (13 + 7 * min(1.0, math.sqrt(area) / 90)) * u * (0.85 + 0.15 * min(2.0, view.s / 2.4))
        f = font(FONT_XB, px * SS)
        s = name.upper()
        wtxt = (f.getlength(s) / SS + 1.6 * px * 0.12 * len(s))
        box = (p[0] - wtxt / 2 - 4, p[1] - px * 0.6, p[0] + wtxt / 2 + 4, p[1] + px * 0.6)
        if not (x0 < box[0] and box[2] < x1 and y0 + 16 * u < box[1] and box[3] < y1):
            continue
        if any(not (box[2] < q[0] or q[2] < box[0] or box[3] < q[1] or q[3] < box[1]) for q in placed):
            continue
        placed.append(box)
        text(dr, p, s, f, (236, 240, 248, 215), "mm", False, SS, spacing=px * 0.12, stroke=2.2)
    # landmarks: a small square and the name, only when zoomed in enough to read
    if view.s >= 3.6:
        fl = font(FONT_BI, 11.5 * u * SS)
        seen = set()
        for name, rects in sorted(land.items(), key=lambda kv: -max(w * h for _, _, w, h in kv[1])):
            bx, by, bw, bh = max(rects, key=lambda r: r[2] * r[3])
            p = view.to(bx + bw / 2, by + bh / 2)
            s = name.upper()
            wt = fl.getlength(s) / SS
            box = (p[0] - 6, p[1] - 8, p[0] + 10 + wt, p[1] + 8)
            if not (x0 < box[0] and box[2] < x1 and y0 + 16 < box[1] and box[3] < y1):
                continue
            if any(not (box[2] < q[0] or q[2] < box[0] or box[3] < q[1] or q[3] < box[1]) for q in placed):
                continue
            placed.append(box)
            dr.rectangle(((p[0] - 3) * SS, (p[1] - 3) * SS, (p[0] + 3) * SS, (p[1] + 3) * SS), fill=YELLOW, outline=(0, 0, 0), width=int(SS))
            text(dr, (p[0] + 7, p[1]), s, fl, (255, 226, 140, 240), "lm", False, SS, stroke=2)
    # route, waypoint, player
    if route:
        sp = [view.to(x, y) for x, y in route]
        route_draw(dr, sp, SS, w=max(3.0, min(6.0, view.s * 0.9)) * u)
    if dest is not None:
        waypoint(dr, view.to(*dest), SS, t)
    player_marker(dr, view.to(*player), heading, SS, r=11 * u)
    # cursor: a reticle with a snapped-road tick and the district it is over
    if cursor is not None:
        cp = view.to(*cursor["xy"])
        a = (255, 255, 255, 60)
        dr.line((x0 * SS, cp[1] * SS, x1 * SS, cp[1] * SS), fill=a, width=int(SS))
        dr.line((cp[0] * SS, y0 * SS, cp[0] * SS, y1 * SS), fill=a, width=int(SS))
        r = 13 * u
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            cxp, cyp = cp[0] + sx * r, cp[1] + sy * r
            dr.line((cxp * SS, cyp * SS, (cxp - sx * 6 * u) * SS, cyp * SS), fill=WHITE, width=int(2 * SS))
            dr.line((cxp * SS, cyp * SS, cxp * SS, (cyp - sy * 6 * u) * SS), fill=WHITE, width=int(2 * SS))
        if cursor.get("snap"):
            sp = view.to(*cursor["snap"])
            dr.line((cp[0] * SS, cp[1] * SS, sp[0] * SS, sp[1] * SS), fill=(255, 255, 255, 120), width=int(SS))
            dr.ellipse(((sp[0] - 3.5) * SS, (sp[1] - 3.5) * SS, (sp[0] + 3.5) * SS, (sp[1] + 3.5) * SS), outline=ROUTE, width=int(2 * SS))
        if cursor.get("label"):
            fl = font(FONT_BI, 13 * u * SS)
            lab = cursor["label"]
            wt = fl.getlength(lab) / SS
            bx, by = cp[0] + 18 * u, cp[1] + 14 * u
            dr.rounded_rectangle((bx * SS, by * SS, (bx + wt + 14 * u) * SS, (by + 20 * u) * SS), radius=3 * SS, fill=(10, 12, 18, 210), outline=(255, 255, 255, 50))
            text(dr, (bx + 7 * u, by + 10 * u), lab, fl, WHITE, "lm", False, SS)
    # header and footer glass
    hh, fh = y0, Hd - y1
    dr.rectangle((0, 0, Wd * SS, hh * SS), fill=(9, 11, 16, 236))
    dr.rectangle((0, y1 * SS, Wd * SS, Hd * SS), fill=(9, 11, 16, 236))
    dr.line((0, (hh - 1) * SS, Wd * SS, (hh - 1) * SS), fill=YELLOW + (200,), width=int(2 * SS))
    dr.line((0, y1 * SS, Wd * SS, y1 * SS), fill=(255, 255, 255, 40), width=int(SS))
    ft = font(FONT_XB, 34 * u * SS)
    text(dr, (22 * u, hh / 2 + 1), LEVEL_TITLE[level["name"]], ft, YELLOW, "lm", True, SS, spacing=2 * u)
    tw = sum(ft.getlength(ch) for ch in LEVEL_TITLE[level["name"]]) / SS + 2 * u * len(LEVEL_TITLE[level["name"]])
    fs = font(FONT_SB, 14 * u * SS)
    text(dr, (22 * u + tw + 14 * u, hh / 2 - 7 * u), "CITY MAP", fs, (244, 240, 228, 150), "lm", False, SS, spacing=2 * u)
    zname = (info or {}).get("here", "")
    text(dr, (22 * u + tw + 14 * u, hh / 2 + 9 * u), ("YOU ARE IN  " + zname.upper()) if zname else "", fs, (244, 240, 228, 220), "lm", False, SS, spacing=1 * u)
    # GPS read-out on the right of the header
    if info and info.get("dest"):
        fb = font(FONT_XB, 24 * u * SS)
        fsm = font(FONT_SB, 12 * u * SS)
        xr = Wd - 22 * u
        dist_s = info["dist"]
        text(dr, (xr, hh / 2 + 1), dist_s, fb, WHITE, "rm", True, SS)
        dw = fb.getlength(dist_s) / SS
        text(dr, (xr - dw - 12 * u, hh / 2 - 7 * u), "DESTINATION", fsm, (255, 62, 170, 255), "rm", False, SS, spacing=1.5 * u)
        text(dr, (xr - dw - 12 * u, hh / 2 + 9 * u), info["dest"].upper(), font(FONT_BI, 15 * u * SS), WHITE, "rm", False, SS)
        if info.get("turn"):
            fdw = font(FONT_BI, 15 * u * SS).getlength(info["dest"].upper()) / SS
            fsw = fsm.getlength("DESTINATION") / SS + 1.5 * u * 11
            xx = xr - dw - 12 * u - max(fdw, fsw) - 30 * u
            # a turn arrow chip
            d, lr = info["turn"]
            cx, cy = xx - 14 * u, hh / 2
            dr.rounded_rectangle(((cx - 16 * u) * SS, (cy - 16 * u) * SS, (cx + 16 * u) * SS, (cy + 16 * u) * SS), radius=5 * SS, fill=ROUTE + (255,))
            sgn = 1 if lr == "RIGHT" else -1
            pts = [(cx - sgn * 5 * u, cy + 10 * u), (cx - sgn * 5 * u, cy - 2 * u), (cx + sgn * 5 * u, cy - 2 * u)]
            dr.line([(p[0] * SS, p[1] * SS) for p in pts], fill=WHITE, width=int(3.2 * u * SS), joint="curve")
            ah = [(cx + sgn * 10 * u, cy - 2 * u), (cx + sgn * 3 * u, cy - 8 * u), (cx + sgn * 3 * u, cy + 4 * u)]
            dr.polygon([(p[0] * SS, p[1] * SS) for p in ah], fill=WHITE)
            text(dr, (cx - 22 * u, hh / 2 - 7 * u), "NEXT", fsm, (244, 240, 228, 150), "rm", False, SS, spacing=1.5 * u)
            text(dr, (cx - 22 * u, hh / 2 + 9 * u), f"{lr} IN {d}", font(FONT_BI, 15 * u * SS), WHITE, "rm", False, SS)
        if info.get("note"):
            text(dr, (xr, hh + 16 * u), info["note"], font(FONT_BI, 13 * u * SS), (255, 170, 210), "rt", True, SS)
    # footer: the keys
    fk = font(FONT_BI, 12.5 * u * SS); fkl = font(FONT_SB, 12.5 * u * SS)
    x = 22 * u; y = y1 + (fh - 20 * u) / 2
    for keys, label in info.get("keys", []) if info else []:
        for k in keys:
            x += keycap(dr, x, y, k, fk, SS, 20 * u) + 4 * u
        text(dr, (x + 3 * u, y + 10 * u), label, fkl, (244, 240, 228, 200), "lm", False, SS, spacing=1 * u)
        x += fkl.getlength(label) / SS + 1 * u * len(label) + 22 * u
    # legend, bottom right of the map
    if info and info.get("legend", True):
        lx, ly = x1 - 196 * u, y1 - 92 * u
        dr.rounded_rectangle((lx * SS, ly * SS, (x1 - 14 * u) * SS, (y1 - 14 * u) * SS), radius=6 * SS, fill=(9, 11, 16, 200), outline=(255, 255, 255, 40))
        fl = font(FONT_SB, 12.5 * u * SS)
        rows = [("you", "YOU"), ("way", "WAYPOINT"), ("route", "ROUTE"), ("road", "ROAD  ·  OVERPASS")]
        for i, (k, lab) in enumerate(rows):
            yy = ly + 13 * u + i * 17 * u
            ix = lx + 18 * u
            if k == "you":
                player_marker(dr, (ix, yy), 0.0, SS, r=6 * u)
            elif k == "way":
                dr.polygon([(ix * SS, (yy - 6 * u) * SS), ((ix + 6 * u) * SS, yy * SS), (ix * SS, (yy + 6 * u) * SS), ((ix - 6 * u) * SS, yy * SS)], fill=ROUTE, outline=(0, 0, 0), width=int(SS))
            elif k == "route":
                dr.line(((ix - 9 * u) * SS, yy * SS, (ix + 9 * u) * SS, yy * SS), fill=ROUTE_CASE, width=int(7 * u * SS))
                dr.line(((ix - 9 * u) * SS, yy * SS, (ix + 9 * u) * SS, yy * SS), fill=ROUTE, width=int(4 * u * SS))
            else:
                dr.rectangle(((ix - 9 * u) * SS, (yy - 4 * u) * SS, (ix + 9 * u) * SS, (yy + 4 * u) * SS), fill=mapart.ROAD)
                dr.rectangle(((ix - 2 * u) * SS, (yy - 6 * u) * SS, (ix + 2 * u) * SS, (yy + 6 * u) * SS), fill=(110, 118, 132))
            text(dr, (ix + 18 * u, yy), lab, fl, (244, 240, 228, 210), "lm", False, SS, spacing=1 * u)
    # zoom scale bar, bottom left of the map
    mpp = MPB / view.s
    for nice in (25, 50, 100, 200, 250, 500, 1000):
        if nice / mpp >= 70 * u:
            break
    bl = nice / mpp
    bx, by = max(x0, view.to(0, 0)[0]) + 30 * u, y1 - 22 * u
    dr.rectangle((bx * SS, (by - 3 * u) * SS, (bx + bl) * SS, by * SS), fill=(244, 240, 228, 200))
    dr.rectangle((bx * SS, (by - 3 * u) * SS, (bx + bl / 2) * SS, by * SS), fill=(20, 22, 28, 220), outline=(244, 240, 228, 200))
    text(dr, (bx, by - 8 * u), f"{nice} M" if nice < 1000 else "1 KM", font(FONT_SB, 12 * u * SS), (244, 240, 228, 210), "lb", True, SS)
    if title_note:
        text(dr, (x0 + 22 * u, y0 + 26 * u), title_note, font(FONT_BI, 14 * u * SS), (255, 255, 255, 200), "lt", True, SS)
    img = Image.alpha_composite(img, ov)
    # a soft inner vignette over the map
    return img.convert("RGB").resize(size, Image.LANCZOS)
