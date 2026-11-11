#!/usr/bin/env python3
"""VEHICLE-GLASS-2: offline twin of dll/src/car_glass.cpp's glass-mask builder (Build), for measuring the
heuristic against every generated body without a game run.

  python3 tools/car_glass_mask.py <models dir> <model stem>... [--sheet out.png] [--dump dir]

Writes, per model, the mask of each body texture (255 = glass) as <dump>/glass_<stem>.pgm (the same file the DLL
writes with GTA2DX9_GLASS_DUMP=1) and a sheet: texture | texture with the mask tinted | the glass texels' 3D points
seen from the side and from above. Keep this file in step with Build() (the constants are named the same)."""
import argparse, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw

KR = 256
DEBUG = os.environ.get("GLASS_DEBUG") == "1"   # sheet colours: glass cyan, strict red, paint-like orange, band yellow


def read_mesh(path):
    d = open(path, "rb").read(); p = 4
    _, nn, nm, _, _ = struct.unpack_from("<IIIII", d, p); p += 20
    p += nn * 80
    out = []
    for _ in range(nm):
        nv, ni = struct.unpack_from("<II", d, p); p += 8
        tex = d[p:p + 64].split(b"\0")[0].decode(); p += 64
        skin, = struct.unpack_from("<i", d, p); p += 4
        v = np.frombuffer(d, np.float32, nv * 8, p).reshape(nv, 8); p += nv * 32
        if skin >= 0: p += nv * 24
        idx = np.frombuffer(d, np.uint32, ni, p).reshape(-1, 3); p += ni * 4
        out.append((tex, v, idx, skin))
    return out


def stem_of(tex):
    s = tex.rsplit(".", 1)[0]
    return s.replace("_paint", "", 1)


def downsample(path):
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
    h, w = im.shape[:2]
    cy = (np.arange(h) * KR // h); cx = (np.arange(w) * KR // w)
    acc = np.zeros((KR, KR, 4)); cnt = np.zeros((KR, KR))
    np.add.at(acc, (cy[:, None].repeat(w, 1), cx[None, :].repeat(h, 0)), im)
    np.add.at(cnt, (cy[:, None].repeat(w, 1), cx[None, :].repeat(h, 0)), 1)
    acc /= np.maximum(cnt, 1)[..., None]
    return acc[..., :3].reshape(-1, 3), acc[..., 3].reshape(-1)


def hsv(rgb):
    mx = rgb.max(-1); mn = rgb.min(-1); d = mx - mn
    sat = np.where(mx > 1e-4, d / np.maximum(mx, 1e-9), 0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    dd = np.maximum(d, 1e-9)
    h = np.where(mx == r, np.mod((g - b) / dd + 6, 6), np.where(mx == g, (b - r) / dd + 2, (r - g) / dd + 4))
    h = np.where(d > 1e-5, h, 0) * 60
    return h, sat, mx


def dilate(m):
    o = m.copy().reshape(KR, KR); a = m.reshape(KR, KR)
    o[:, 1:] |= a[:, :-1]; o[:, :-1] |= a[:, 1:]; o[1:, :] |= a[:-1, :]; o[:-1, :] |= a[1:, :]
    return o.reshape(-1)


def erode(m):
    return ~dilate(~m)


def components(m):
    """Labels (4-connected) of a boolean mask; 0 = background."""
    from collections import deque
    a = m.reshape(KR, KR); lab = np.zeros((KR, KR), np.int32); n = 0
    for y, x in zip(*np.nonzero(a)):
        if lab[y, x]: continue
        n += 1; q = deque([(y, x)]); lab[y, x] = n
        while q:
            cy, cx = q.popleft()
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < KR and 0 <= nx < KR and a[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n; q.append((ny, nx))
    return lab.reshape(-1), n


def keep_components(m, min_size):
    lab, n = components(m)
    if not n: return m
    sizes = np.bincount(lab, minlength=n + 1)
    keep = sizes >= min_size; keep[0] = False
    return keep[lab]


def build(models, name, params=None):
    meshes = read_mesh(os.path.join(models, name + ".mesh"))
    for tex, *_ in meshes:
        if "_glass" in tex or "_interior" in tex:
            return {"name": name, "authored": True}
    tris = {}
    allp = []
    for tex, v, idx, skin in meshes:
        if skin >= 0 or len(idx) < 1: continue
        st = stem_of(tex)
        if st in tris: continue
        allp.append(v[:, :3])
        tris[st] = (v, idx)
    allp = np.concatenate(allp)
    if len(allp) < 100: return None
    minX, maxX = allp[:, 0].min(), allp[:, 0].max(); minY = allp[:, 1].min()
    minZ, maxZ = allp[:, 2].min(), allp[:, 2].max()
    W = maxX - minX; midX = 0.5 * (minX + maxX)
    top = allp[np.abs(allp[:, 0] - midX) < 0.30 * W, 1].max()
    H = top - minY; L = maxZ - minZ
    NB = 48
    hm = np.zeros(NB)
    b = np.clip(((allp[:, 2] - minZ) / L * NB).astype(int), 0, NB - 1)
    np.maximum.at(hm, b, np.minimum(1.2, (allp[:, 1] - minY) / H))
    roof = np.nonzero(hm >= 0.86)[0]
    if not len(roof): return None
    r0, r1 = roof[0], roof[-1]
    z0 = minZ + r0 * L / NB; z1 = minZ + (r1 + 1) * L / NB
    rake = 0.45 * H
    res = {"name": name, "masks": {}, "H": H, "L": L, "z0": z0, "z1": z1, "minY": minY, "minZ": minZ, "top": top,
           "midX": midX, "W": W, "rake": rake}
    for st, (v, idx) in tris.items():
        path = os.path.join(models, st + ".tga")
        if not os.path.exists(path): continue
        rgb, _ = downsample(path)
        pp = os.path.join(models, st + "_paint.tga")
        paintA = downsample(pp)[1] if os.path.exists(pp) else None
        pos = np.zeros((KR * KR, 3), np.float32); nrm = np.zeros((KR * KR, 3), np.float32); valid = np.zeros(KR * KR, bool)
        P = v[idx][:, :, :3]; UV = v[idx][:, :, 6:8]
        e1 = P[:, 1] - P[:, 0]; e2 = P[:, 2] - P[:, 0]
        N = np.cross(e1, e2); ln = np.linalg.norm(N, axis=1)
        for k in range(len(idx)):
            if ln[k] < 1e-12: continue
            n = N[k] / ln[k]
            u = (UV[k, :, 0] - np.floor(UV[k, :, 0])) * KR; vv = (UV[k, :, 1] - np.floor(UV[k, :, 1])) * KR
            if u.max() - u.min() > KR / 2 or vv.max() - vv.min() > KR / 2: continue
            den = (vv[1] - vv[2]) * (u[0] - u[2]) + (u[2] - u[1]) * (vv[0] - vv[2])
            if abs(den) < 1e-9: continue
            e = -0.6 / np.sqrt(abs(den))
            x0 = max(0, int(np.floor(u.min()))); x1 = min(KR - 1, int(np.ceil(u.max())))
            y0 = max(0, int(np.floor(vv.min()))); y1 = min(KR - 1, int(np.ceil(vv.max())))
            if x1 < x0 or y1 < y0: continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            l1 = ((vv[1] - vv[2]) * (gx - u[2]) + (u[2] - u[1]) * (gy - vv[2])) / den
            l2 = ((vv[2] - vv[0]) * (gx - u[2]) + (u[0] - u[2]) * (gy - vv[2])) / den
            l3 = 1 - l1 - l2
            ins = (l1 >= e) & (l2 >= e) & (l3 >= e)
            if not ins.any(): continue
            ii = ((gy[ins] - 0.5).astype(int) * KR + (gx[ins] - 0.5).astype(int))
            pos[ii] = l1[ins, None] * P[k, 0] + l2[ins, None] * P[k, 1] + l3[ins, None] * P[k, 2]
            nrm[ii] = n; valid[ii] = True
        res["masks"][st] = mask_for(rgb, paintA, pos, nrm, valid, minY, H, L, minZ, z0, z1, rake, midX, W, params or {})
        res["masks"][st]["rgb"] = rgb
    if (params or {}).get("synth", 1):
        synthesize(res, params or {})
    return res


NON_CABIN = (54, 55, 61, 65, 66)


def synthesize(res, P):
    """VEHICLE-GLASS-6: a pane the colour rules did not find is synthesized from the glasshouse's geometry (the body's
    own window apertures), so no closed body keeps an opaque baked window. Regions, model-wide over every body texture:
    each side's windows (side faces under the roof span, 0.63-0.87 of the roof height, pillars of 0.05 of the length
    kept at each end, a B-pillar of 0.035 of the length on a span over 0.30 of it), the windscreen and the rear screen
    (facing forward / back, 0.66-0.87 of the roof, inset 0.14 of the screen's width at each side). A region whose
    found glass covers under SYN_FRAC of its aperture takes the whole aperture (less livery). Sides and the rear only
    on a car-like glasshouse (roof span at most SYN_SPAN of the length: a box truck's or van's long roof has blank
    flanks); the windscreen on every closed body."""
    H, L, z0, z1, minY, minZ, midX, W, rake = (res[k] for k in ("H", "L", "z0", "z1", "minY", "minZ", "midX", "W", "rake"))
    span = (z1 - z0) / L
    try: number = int(res["name"][:3])
    except ValueError: number = -1
    if number in NON_CABIN or 72 <= number <= 81:   # a tank, trailers, the flatbed, the wrecks: no glasshouse to glaze
        res["synth"] = {}; res["carlike"] = (round(span, 2), False); return
    # car-like: a short roof with tumblehome (the side glass leans in: its |x| at 0.78-0.87 of the roof under 0.90 of the
    # belt's at 0.45-0.55); a box truck's, a van's or a bus's flanks stand upright the whole height (0.96-1.00)
    xs_hi, xs_lo = [], []
    for st, m in res["masks"].items():
        if "underpan" in st: continue
        pos, nrm, valid = m["pos"], m["nrm"], m["valid"]
        h = (pos[:, 1] - minY) / H; z = pos[:, 2]
        s = valid & (np.abs(nrm[:, 0]) > 0.4) & (z > z0) & (z < z1)
        xs_hi.append(np.abs(pos[s & (h > 0.78) & (h < 0.87), 0] - midX)); xs_lo.append(np.abs(pos[s & (h > 0.45) & (h < 0.55), 0] - midX))
    hi = np.concatenate(xs_hi) if xs_hi else np.zeros(0); lo = np.concatenate(xs_lo) if xs_lo else np.zeros(0)
    tumble = float(np.median(hi) / max(np.median(lo), 1e-6)) if len(hi) >= 20 and len(lo) >= 20 else 1.0
    carlike = span <= P.get("synspan", 0.70) and tumble < P.get("syntumble", 0.90)
    frac = P.get("synfrac", 0.25)
    pin = 0.05 * L
    regs = {}
    for st, m in res["masks"].items():
        if "underpan" in st: continue   # VEHICLE-ART-13's floor pan
        pos, nrm, valid = m["pos"], m["nrm"], m["valid"]
        h = (pos[:, 1] - minY) / H; z = pos[:, 2]; x = pos[:, 0]; nx, ny, nz = nrm[:, 0], nrm[:, 1], nrm[:, 2]
        hue, sat, val = hsv(m["rgb"])
        livery = (sat > 0.55) & (val > 0.60)   # a bright sign or stripe; the bake's dark red seats behind a pane are not
        base = valid & (ny <= 0.80) & ~livery
        side = base & (np.abs(nx) > 0.4) & (h >= 0.63) & (h <= 0.87) & (z >= z0 + pin) & (z <= z1 - pin)
        if z1 - z0 > 0.30 * L:
            zm = 0.5 * (z0 + z1)
            side &= np.abs(z - zm) > 0.0175 * L
        scr = base & (h >= 0.66) & (h <= 0.87) & (np.abs(nx) <= 0.6)
        scr &= ~side   # as the DLL: a texel is a side's first
        front = scr & (nz > 0.35) & (z > z1 - 0.05 * L) & (z < z1 + rake)
        rear = scr & (nz < -0.35) & (z < z0 + 0.05 * L) & (z > z0 - rake)
        # VEHICLE-GLASS-7: the side band up to the glasshouse bound (0.90, the band's own top) for column completion's
        # fill: a window's top follows the glasshouse (the roof's turn), not the bake's pale band under it
        top = base & (np.abs(nx) > 0.4) & (h > 0.87) & (h <= 0.90) & (z >= z0 + pin) & (z <= z1 - pin)
        if z1 - z0 > 0.30 * L:
            top &= np.abs(z - 0.5 * (z0 + z1)) > 0.0175 * L
        regs[st] = {"side+": side & (nx > 0), "side-": side & (nx < 0), "front": front, "rear": rear, "x": x,
                    "top+": top & (nx > 0), "top-": top & (nx < 0)}
    out = {}
    def missed(r):
        ap = sum(int(g[r].sum()) for g in regs.values())
        found = sum(int((res["masks"][st]["g"] & g[r]).sum()) for st, g in regs.items())
        return ap >= 40 and found < frac * ap
    # a side is synthesized only when BOTH sides missed (a painted-on window); one side found and the other not is an
    # asymmetric body (023's serving hatch) or the mirror fill's business
    both_sides = carlike and missed("side+") and missed("side-")
    for r in ("front", "rear", "side+", "side-"):
        if r.startswith("side") and not both_sides: continue
        if r != "front" and not carlike: continue
        if r in ("front", "rear"):   # the screen's own width at its height, inset at each side (the pillars)
            xs = np.concatenate([g["x"][g[r]] for g in regs.values()]) if regs else np.zeros(0)
            if len(xs) < 20: continue
            lo, hi = np.percentile(xs, 2), np.percentile(xs, 98)
            inset = 0.14 * (hi - lo)
            for g in regs.values(): g[r] = g[r] & (g["x"] > lo + inset) & (g["x"] < hi - inset)
        ap = sum(int(g[r].sum()) for g in regs.values())
        found = sum(int((res["masks"][st]["g"] & g[r]).sum()) for st, g in regs.items())
        take = ap >= 40 and found < frac * ap
        out[r] = (ap, found, take)
        if take:   # a synthesized side starts at 0.66 of the roof (0.63 cut under 028's chrome sill)
            for st, g in regs.items():
                add = g[r] if not r.startswith("side") else g[r] & ((res["masks"][st]["pos"][:, 1] - minY) / H >= 0.66)
                res["masks"][st]["g"] = res["masks"][st]["g"] | add
    if carlike and P.get("columns", 1):
        # Column completion: on a side the colour rules found, a station (1/48 of the length) whose aperture is at least
        # 0.4 glass takes its whole aperture height (the pale band the bakes leave along a window's top, a ragged sill);
        # a station under that (a pillar, a door's baked slab) stays as it is.
        for r in ("side+", "side-"):
            if out.get(r, (0, 0, False))[2]: continue
            zb = {st: np.clip(((m["pos"][:, 2] - minZ) / L * 48).astype(int), 0, 47) for st, m in res["masks"].items() if st in regs}
            ap = np.zeros(48); fd = np.zeros(48); ys = [[] for _ in range(48)]
            for st, g in regs.items():
                f = g[r] & res["masks"][st]["g"]
                np.add.at(ap, zb[st][g[r]], 1); np.add.at(fd, zb[st][f], 1)
                for b, y in zip(zb[st][f], res["masks"][st]["pos"][f, 1]): ys[b].append(y)
            # the median as the DLL's nth_element (upper median)
            mh = np.array([np.sort(v)[len(v) // 2] if v else 1e9 for v in ys])
            full = (ap >= 4) & (fd >= 0.4 * ap)
            added = 0
            for st, g in regs.items():   # above the station's median found glass, never its lower half (071/002 sill notches)
                y = res["masks"][st]["pos"][:, 1]
                reg = g[r] | g["top" + r[-1]] if P.get("coltop", 1) else g[r]
                add = reg & full[zb[st]] & ~res["masks"][st]["g"] & (y >= mh[zb[st]])
                added += int(add.sum()); res["masks"][st]["g"] = res["masks"][st]["g"] | add
            out[r + " columns"] = added
    if carlike and P.get("beltcut", 1):
        out["belt cut"] = belt_cut(res)
    res["synth"] = out
    res["carlike"] = (round(span, 2), round(tumble, 2), carlike)


def belt_cut(res):
    """VEHICLE-GLASS-7: a side window starts above the belt. Where the body has a sill ledge (an up-facing surface,
    normal y > 0.7, at 0.55-0.72 of the roof in the outer part of the width, |x| > 0.30 of the width from the middle),
    side glass at that station (1/48 of the length) and side lower than the ledge's top and outboard of its inner edge
    (on the door's skin; a window stands inboard of its sill) is the door's top, not glass
    (001 Wellard: a strip of its beige paint under the chrome sill ledge, taken because its bake gives no paint
    cluster): dropped."""
    H, L, minY, minZ, midX, W = res["H"], res["L"], res["minY"], res["minZ"], res["midX"], res["W"]
    ledge = {}   # (side, station) -> the ledge's top height (fraction of the roof)
    data = {}
    for st, m in res["masks"].items():
        if "underpan" in st: continue
        pos, nrm, valid = m["pos"], m["nrm"], m["valid"]
        h = (pos[:, 1] - minY) / H
        sd = (pos[:, 0] > midX).astype(int); zb = np.clip(((pos[:, 2] - minZ) / L * 48).astype(int), 0, 47)
        data[st] = (h, sd, zb)
        up = valid & (nrm[:, 1] > 0.7) & (h >= 0.55) & (h <= 0.72) & (np.abs(pos[:, 0] - midX) > 0.30 * W)
        ax = np.abs(pos[:, 0] - midX)
        for i in np.nonzero(up)[0]:
            k = (sd[i], zb[i])
            lh, lx = ledge.get(k, (0.0, 1e9))
            ledge[k] = (max(lh, h[i]), min(lx, ax[i]))
    dropped = 0
    for st, (h, sd, zb) in data.items():
        m = res["masks"][st]; g = m["g"]
        cand = g & (np.abs(m["nrm"][:, 0]) > 0.4) & (h < 0.72)
        ax = np.abs(m["pos"][:, 0] - midX)
        for i in np.nonzero(cand)[0]:
            lh, lx = ledge.get((sd[i], zb[i]), (None, None))
            if lh is not None and h[i] < lh and ax[i] >= lx:
                g[i] = False; dropped += 1
    return dropped


def on_belt(black, paint, valid, h, z, nx, minZ, L, P):
    """VEHICLE-GLASS-4: a near-black side texel is a window, not tyre-black trim, when it sits on the paint belt at its
    station along the car (071 Rumbler: near-black side windows straight over the red belt line; the tyre-black rule
    dropped them, 290 of ~1100 texels found). Cells of (side, 1/24 of 0.40-0.90 of the roof height, 1/48 of the length)
    over the side faces: a cell is paint / black when at least half of its texels (and 2) are. Accepted: a black
    cell at 0.55 of the roof or higher with a paint cell below it in its column, in a run of 3 such cells up the
    column (019's black deck streaks are thinner), whose mirrored cell on the other side is accepted too (+-1 cell:
    the bodies are symmetric; 003's black camo on one flank is green on the other). Rear and front faces never
    (003's rear doors, 007's cab back wall)."""
    NH, NZ = 24, 48
    hb = np.floor((h - 0.40) / 0.50 * NH).astype(int)
    zb = np.clip(((z - minZ) / L * NZ).astype(int), 0, NZ - 1)
    sd = (nx > 0).astype(int)
    ok = valid & (np.abs(nx) > 0.4) & (hb >= 0) & (hb < NH)
    cnt = np.zeros((2, NH, NZ)); pc = np.zeros((2, NH, NZ)); bc = np.zeros((2, NH, NZ))
    np.add.at(cnt, (sd[ok], hb[ok], zb[ok]), 1)
    np.add.at(pc, (sd[ok], hb[ok], zb[ok]), (paint & ~black)[ok].astype(float))
    np.add.at(bc, (sd[ok], hb[ok], zb[ok]), black[ok].astype(float))
    pcell = (pc >= 2) & (2 * pc >= cnt)
    bcell = (bc >= 2) & (2 * bc >= cnt)
    acc = np.zeros((2, NH, NZ), bool); seen = np.zeros((2, NZ), bool)
    for k in range(NH):
        acc[:, k] = bcell[:, k] & seen & (k >= 7)      # 7 = 0.55 of the roof height
        seen |= pcell[:, k] & ~bcell[:, k]
    keep = np.zeros_like(acc)
    for k in range(NH - 2):
        blk = acc[:, k] & acc[:, k + 1] & acc[:, k + 2]
        for j in range(3): keep[:, k + j] |= blk
    acc = keep
    acc = acc | (np.roll(acc, 1, 2) & np.roll(acc, -1, 2))   # a lone missing station between two (wraps, as the DLL)
    mir = acc[::-1]
    mir = mir | np.roll(mir, 1, 1) | np.roll(mir, -1, 1)
    mir = mir | np.roll(mir, 1, 2) | np.roll(mir, -1, 2)
    acc &= mir
    res = np.zeros_like(black)
    res[ok] = acc[sd[ok], hb[ok], zb[ok]]
    return res & black, res


def convex_hull(pts):
    """Andrew's monotone chain; pts (n, 2); counter-clockwise, no repeated end point."""
    P = sorted(set(map(tuple, pts)))
    if len(P) < 3: return P
    def cross(o, a, b): return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in P:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0: lo.pop()
        lo.append(p)
    for p in reversed(P):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0: hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def hull_fill(g, band, livery, valid, h, z, nx, minZ, L, P):
    """VEHICLE-GLASS-5: a side window's opening is near-convex; the bake paints part of it in the paint's own hue (071
    Rumbler: the front quarter of each window, 446 of 531 pale texels within the paint tolerance), which no colour rule
    can take without taking paint. Per side, the found side glass is grouped in cells (1/12 of 0.60-0.90 of the roof
    height, 1/48 of the length, 4-connected); a group of at least HULL_MIN texels fills the side texels of the
    glasshouse inside its convex hull in (length, height), quantised to the texel grid, when the group already covers
    HULL_SOLID of what the hull holds (a window wrapped around a pillar, or two windows joined by a drip, has a hull far
    larger than itself and is left alone). Never a livery texel."""
    NH, NZ = 12, 48
    sidef = valid & band & (np.abs(nx) > 0.4)
    hb = np.clip(((h - 0.60) / 0.30 * NH).astype(int), 0, NH - 1)
    zb = np.clip(((z - minZ) / L * NZ).astype(int), 0, NZ - 1)
    sd = (nx > 0).astype(int)
    # quantised coordinates: 1/96 of the length, 1/48 of 0.60-0.90
    qz = np.round((z - minZ) / L * 96).astype(int); qh = np.round((h - 0.60) / 0.30 * 48).astype(int)
    out = g.copy()
    for s in (0, 1):
        gs = g & sidef & (sd == s)
        if gs.sum() < P.get("hull_min", 120): continue
        cell = np.zeros((NH, NZ), bool); cell[hb[gs], zb[gs]] = True
        # 4-connected cell groups
        lab = np.zeros((NH, NZ), int); n = 0
        for a in range(NH):
            for b in range(NZ):
                if not cell[a, b] or lab[a, b]: continue
                n += 1; st = [(a, b)]; lab[a, b] = n
                while st:
                    x, y = st.pop()
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        u, w = x + dx, y + dy
                        if 0 <= u < NH and 0 <= w < NZ and cell[u, w] and not lab[u, w]:
                            lab[u, w] = n; st.append((u, w))
        tl = lab[hb, zb]
        elig = sidef & (sd == s) & ~livery
        for c in range(1, n + 1):
            mem = gs & (tl == c)
            if mem.sum() < P.get("hull_min", 120): continue
            hull = convex_hull(np.stack([qz[mem], qh[mem]], 1))
            if len(hull) < 3: continue
            ins = elig.copy()
            for k in range(len(hull)):
                (ax, ay), (bx, by) = hull[k], hull[(k + 1) % len(hull)]
                ins &= (bx - ax) * (qh - ay) - (by - ay) * (qz - ax) >= 0
            if mem.sum() < P.get("hull_solid", 0.70) * (ins | mem).sum(): continue
            out |= ins
    return out


def mirror_fill(g, band, livery, valid, h, z, nx, minZ, L, P):
    """VEHICLE-GLASS-5 (DLL MirrorFill, docs/car-glass.md 10.1): the bodies are symmetric, the bakes are not: 071
    Rumbler's left window is found to the A pillar, its right one stops a quarter short (that corner is baked in the paint's
    own hue, which no colour rule can take without taking paint). Cells over the side faces of the glasshouse (1/48 of the
    length, 1/16 of 0.60-0.90 of the roof height); a cell is glass when at least 0.6 of its texels (and 2) are. Sources:
    glass cells with glass (or no texel) above and below, in an 8-connected group at least 4 rows tall and 12 cells big
    (never a trim strip: 001's chrome belt). Only when the two sides' glass cells overlap (IoU 0.5; 003's camo sides:
    0.00). A side glasshouse texel, not livery, becomes glass when the cell at its station and height on the OTHER side
    is a source; then a closing of 2 inside the side glasshouse."""
    NZ, NH = P.get("mirror_nz", 48), P.get("mirror_nh", 16)
    sidef = valid & band & (np.abs(nx) > 0.4)
    qz = np.clip(((z - minZ) / L * NZ).astype(int), 0, NZ - 1)
    qh = np.clip(((h - 0.60) / 0.30 * NH).astype(int), 0, NH - 1)
    sd = (nx > 0).astype(int)
    cnt = np.zeros((2, NH, NZ)); gc = np.zeros((2, NH, NZ))
    np.add.at(cnt, (sd[sidef], qh[sidef], qz[sidef]), 1)
    np.add.at(gc, (sd[sidef], qh[sidef], qz[sidef]), g[sidef].astype(float))
    gcell = (gc >= 2) & (gc >= P.get("mirror_frac", 0.6) * cnt)
    ncell = gcell | (cnt == 0)   # glass or no texel there (a UV seam)
    core = gcell.copy()
    nb = ((-1, 0), (1, 0))   # a source cell with glass (or no texel) above and below it: never a thin strip (001's chrome belt)
    for dh, dz in nb:
        sh = np.zeros_like(ncell)
        a0, a1 = max(0, dh), NH + min(0, dh); b0, b1 = max(0, dz), NZ + min(0, dz)
        sh[:, a0 - dh:a1 - dh, b0 - dz:b1 - dz] = ncell[:, a0:a1, b0:b1]
        core &= sh
    # sources: cells of a window, an 8-connected group of glass cells at least MIRROR_ROWS rows tall and MIRROR_CELLS
    # cells big (a trim strip copied by the bake into one side's mask is 1-3 rows: 001's chrome belt)
    for s_ in (0, 1):
        lab = np.zeros((NH, NZ), int); n = 0
        for a in range(NH):
            for b in range(NZ):
                if not core[s_, a, b] or lab[a, b]: continue
                n += 1; st = [(a, b)]; lab[a, b] = n; mem = []
                while st:
                    x, y = st.pop(); mem.append((x, y))
                    for dx in (-1, 0, 1):
                        for dy in (-1, 0, 1):
                            u, w = x + dx, y + dy
                            if 0 <= u < NH and 0 <= w < NZ and core[s_, u, w] and not lab[u, w]:
                                lab[u, w] = n; st.append((u, w))
                rows = len(set(x for x, _ in mem))
                if rows < P.get("mirror_rows", 4) or len(mem) < P.get("mirror_cells", 12):
                    for x, y in mem: core[s_, x, y] = False
    inter = (gcell[0] & gcell[1]).sum(); uni = (gcell[0] | gcell[1]).sum()
    iou = inter / max(uni, 1)
    if os.environ.get("MIRROR_DEBUG"): print("mirror iou %.2f (%d cells)" % (iou, uni))
    if iou < P.get("mirror_iou", 0.5): return g   # the two sides disagree (003's camo): a mirror would copy errors
    add = sidef & ~livery & ~g & core[1 - sd, qh, qz]
    out = g | add
    if add.any() and P.get("mirror_close", 1):
        # close the copied glass with the found glass (2 texels, side glasshouse only): the two sides' UV rasters do not
        # line up texel for texel, so the copy alone is ragged where it meets the pane
        c = out.copy()
        for _ in range(2): c = dilate(c)
        for _ in range(2): c = erode(c)
        out |= c & sidef & ~livery
    return out


def fill_holes(g, valid, strict, P):
    """VEHICLE-GLASS-5 (DLL FillHoles): hull islands enclosed by glass (GLASS-4's measure: 030 211 texels, 035 111, 034 78,
    084 108) are bake blobs inside a pane: drawn as torn hull patches. A 4-connected component of non-glass texels that
    touches no texel outside the body raster (invalid: the UV island's border) and no image edge, of at most HOLE_MAX
    texels, becomes glass, unless at least half of it is strictly bodywork (the paint pillars between the 006 box car's
    windows are enclosed by its glass in UV)."""
    ng = ~g
    lab, n = components(ng)
    if not n: return g
    cnt = np.bincount(lab, minlength=n + 1)
    bad = np.zeros(n + 1, bool)
    np.logical_or.at(bad, lab, ~valid & ng)
    edge = np.zeros((KR, KR), bool); edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = True
    np.logical_or.at(bad, lab[edge.reshape(-1)], True)
    sc = np.bincount(lab, weights=(strict & ng).astype(float), minlength=n + 1)
    fill = ~bad & (cnt <= P.get("hole_max", 300)) & (2 * sc < cnt); fill[0] = False
    return g | fill[lab]


def mask_for(rgb, paintA, pos, nrm, valid, minY, H, L, minZ, z0, z1, rake, midX, W, P):
    h = (pos[:, 1] - minY) / H
    side = np.zeros(0, int)
    for pas in range(2):
        sel = valid & (h >= 0.35) & (h <= 0.55) & (np.abs(nrm[:, 0]) >= 0.6)
        if pas == 0 and paintA is not None: sel &= paintA >= 0.5
        side = np.nonzero(sel)[0]
        if len(side) >= 50: break
    clusters = []
    if len(side):
        q = np.minimum(7.99, rgb[side] * 8).astype(int)
        key = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
        vals, counts = np.unique(key, return_counts=True)
        order = sorted(zip(counts, vals), reverse=True)
        for c, kv in order:
            if len(clusters) >= 3 or c * 100 < len(side) * 15: break
            clusters.append(rgb[side[key == kv]].mean(0))
    clusters = np.array(clusters).reshape(-1, 3)
    paintVal = max([c.max() for c in clusters], default=0.5)
    darkPaint = any(c.max() < 0.2 for c in clusters)
    nFlank = len(clusters)
    if P.get("roof", 1):
        # VEHICLE-GLASS-2: the roof's colour is paint too (the upper body of a two-tone van or bus is
        # the roof's colour, and the flanks sampled above never see it). Light roofs only: a dark
        # roof may share the glass's tone.
        roof = np.nonzero(valid & (h > 0.92) & (nrm[:, 1] > 0.80) & (np.abs(pos[:, 0] - midX) < 0.30 * W))[0]
        if len(roof) >= 40:
            q = np.minimum(7.99, rgb[roof] * 8).astype(int)
            key = q[:, 0] * 64 + q[:, 1] * 8 + q[:, 2]
            vals, counts = np.unique(key, return_counts=True)
            extra = []
            for c, kv in sorted(zip(counts, vals), reverse=True)[:2]:
                if c * 100 < len(roof) * 25: break
                col = rgb[roof[key == kv]].mean(0)
                if col.max() > 0.45 and hsv(col[None])[1][0] < 0.25 and all(((col - k) ** 2).sum() > 0.06 ** 2 for k in clusters): extra.append(col)
            if extra: clusters = np.concatenate([clusters, np.array(extra)])
    hue, sat, val = hsv(rgb)
    z = pos[:, 2]; nx, ny, nz = nrm[:, 0], nrm[:, 1], nrm[:, 2]
    inRoof = (z >= z0) & (z <= z1)
    sideW = inRoof & (np.abs(nx) > 0.4)
    screen = (h > 0.64) & (((nz > 0.35) & (z > z1 - 0.05 * L) & (z < z1 + rake)) | ((nz < -0.35) & (z < z0 + 0.05 * L) & (z > z0 - rake)))
    band = valid & (h >= 0.60) & (h <= 0.90) & (ny <= 0.80) & (sideW | screen)
    rear = band & ~sideW & (nz < -0.35)
    nearPaint = np.zeros(KR * KR, bool); paintLike = np.zeros(KR * KR, bool)
    dmin = np.full(KR * KR, 9.0)
    for c in clusters:
        d2 = ((rgb - c) ** 2).sum(1)
        # VEHICLE-GLASS-2: the distance scales with the paint's brightness: 0.10 of RGB is most of a
        # dark green's whole range, so every dark glass texel matched a dark paint (030).
        sc = float(np.clip(c.max() / 0.40, P.get("dfloor", 0.6), 1.0)) if P.get("darkscale", 1) else 1.0
        dmin = np.minimum(dmin, np.sqrt(d2) / sc)
        nearPaint |= d2 < (0.12 * sc) ** 2
        paintLike |= d2 < (0.10 * sc) ** 2
        ch, cs, cv = hsv(c[None])
        if cs[0] < 0.30: continue
        dh = np.abs(hue - ch[0]); dh = np.where(dh > 180, 360 - dh, dh)
        paintLike |= (sat >= 0.25) & (val >= 0.10) & (dh < 22) & (sat > 0.45 * cs[0])
    if P.get("offhue", 1) and len(clusters):
        # VEHICLE-GLASS-3: glass within the RGB tolerance of a saturated dark paint but off its hue (or far
        # less saturated) and not in shade is not the paint: 030's grey-green windows on dark olive paint
        # (paint hue 100, sat 0.46; window hue 136-143, sat 0.30, the same value: 0.025 of RGB apart).
        csat = [(hsv(c[None])[0][0], hsv(c[None])[1][0], c.max()) for c in clusters]
        if all(cs >= 0.30 and cv < 0.40 for _, cs, cv in csat):   # dark saturated paints only (002 cream: its highlights)
            near = np.argmin(np.stack([((rgb - c) ** 2).sum(1) for c in clusters]), 0)
            cv_near = np.array([cv for *_, cv in csat])[near]
            off = val >= P.get("offval", 0.6) * cv_near
            for ch, cs, cv in csat:
                dh = np.abs(hue - ch); dh = np.where(dh > 180, 360 - dh, dh)
                off &= (dh > P.get("offdh", 25)) | (sat < 0.4 * cs)
            nearPaint &= ~off; paintLike &= ~off
    livery = (sat > 0.55) & (val > 0.25)
    liveryScreen = np.zeros(KR * KR, bool)
    if P.get("screens", 1):
        liveryScreen = livery & ~sideW   # may be grown into from real glass, never seeds it
        livery &= sideW   # VEHICLE-GLASS-2: a screen carries no livery; its saturated bake (a dash's reflection) is glass
    # VEHICLE-GLASS-2: a rear screen reflecting the sky is cooler (bluer) than a warm pale paint: not the paint.
    cool = np.zeros(KR * KR, bool)
    if P.get("cool", 1) and len(clusters):
        br = rgb[:, 2] - rgb[:, 0]
        cool = (sat < 0.35) & (dmin > 0.10) & np.all([br > (c[2] - c[0]) + 0.08 for c in clusters], axis=0)
    rearPaint = rear & ~cool & (((ny < 0.15) & ~(val < 0.55 * paintVal)) | ~((val < 0.9 * paintVal) | (val < 0.35)))
    strict = nearPaint | livery | rearPaint
    strict &= band
    paintLike = band & (strict | paintLike | liveryScreen)
    g = band & ~paintLike
    beltFill = None
    if darkPaint:
        black = val < (0.08 if P.get("darkscale", 1) else 0.18)
        if P.get("belt", 1) and P.get("darkscale", 1):
            onb, wcell = on_belt(black, nearPaint | livery, valid, h, z, nx, minZ, L, P)
            black &= ~onb
            if P.get("beltfill", 0): beltFill = wcell & band & (val < 0.45 * paintVal) & ~livery
        g &= ~black
    g = dilate(erode(g))
    g = keep_components(g, 30)
    for _ in range(2): g = dilate(g)
    for _ in range(2): g = erode(g)
    g &= band & ~paintLike
    for _ in range(6):
        g |= dilate(g) & band & ~strict
    if P.get("deep", 1):
        # VEHICLE-GLASS-3: the bake paints the cabin seen through a pane in the paint's hue but far darker
        # (000: value 0.26 under a 0.57 paint), paint-like only by hue, and the 6-texel growth stops inside
        # such a patch (blobs and drips left in the pane, drawn as hull under Remix). A side texel of that
        # kind becomes glass when glass lies on the same side at its height both ahead of it and behind it
        # (within a quarter of the length), both of at least 120 texels: a patch between two windows, never an
        # open-ended dark panel (003's shaded flank and rear doors) or a strip between two false specks.
        dark = band & ~strict & (val < P.get("deepval", 0.45) * paintVal) & (np.abs(nx) > 0.4)
        hb = np.clip(((h - 0.60) / 0.30 * 12).astype(int), 0, 11); zb = np.clip(((z - minZ) / L * 48).astype(int), 0, 47)
        sd = (nx > 0).astype(int)
        G = np.zeros((2, 12, 48), bool)
        gs = keep_components(g, P.get("deepmin", 120)) & (np.abs(nx) > 0.4) & band   # real windows, not specks
        G[sd[gs], hb[gs], zb[gs]] = True
        G = G | np.roll(G, 1, 1) | np.roll(G, -1, 1)   # +-1 height bin (edges wrap harmlessly: 12 bins of 0.025)
        ahead = np.zeros_like(G); behind = np.zeros_like(G)
        for k in range(1, 13):
            ahead[:, :, :-k] |= G[:, :, k:]; behind[:, :, k:] |= G[:, :, :-k]
        bridge = dark & ahead[sd, hb, zb] & behind[sd, hb, zb]
        for _ in range(P.get("deepn", 16)):
            g |= dilate(g) & bridge
    if beltFill is not None:
        # VEHICLE-GLASS-4: inside a window found on the belt (its accepted cells), the cabin's dark bake in the paint's
        # own dark shade (071: dark red seats under a dark red shade cluster) is glass too, whatever the paint test says
        g |= beltFill
    # DropPaintComponents
    def paint_comps(g):
        lab, n = components(g)
        if not n: return lab, np.zeros(1, bool)
        cnt = np.bincount(lab, minlength=n + 1).astype(float)
        mv = np.bincount(lab, weights=val, minlength=n + 1) / np.maximum(cnt, 1)
        ms = np.bincount(lab, weights=sat, minlength=n + 1) / np.maximum(cnt, 1)
        drop = ((mv > 0.62) & (ms > 0.12)) | (mv > 0.85); drop[0] = False
        return lab, drop
    lab, drop = paint_comps(g)
    if P.get("split", 1) and drop.any():
        # VEHICLE-GLASS-2: a component that reads as paint as a whole loses only its bright texels (a
        # two-tone van's cream band); what is left (the darker cab window grown into it) is closed over
        # small highlights and kept when it reads as glass on its own.
        flagged = drop[lab]
        bright = ((val > 0.62) & (sat > 0.12)) | (val > 0.85)
        # the shaded part of the same paint: the bright part's chromaticity at a lower value
        chroma = rgb / np.maximum(val, 1e-3)[:, None]
        same = np.zeros(KR * KR, bool)
        for c in np.unique(lab[flagged]):
            comp = lab == c
            cb = comp & bright
            if cb.sum() < 10: continue
            ref = chroma[cb].mean(0)
            same |= comp & (np.sqrt(((chroma - ref) ** 2).sum(1)) < P.get("chroma", 0.12))
        rest = flagged & ~bright & ~same
        for _ in range(2): rest = dilate(rest)
        for _ in range(2): rest = erode(rest)
        rest &= flagged
        rest = keep_components(rest, 30)
        g = (g & ~flagged) | rest
        lab, drop = paint_comps(g)
    g &= ~drop[lab]
    if P.get("hull", 0):
        g = hull_fill(g, band, livery, valid, h, z, nx, minZ, L, P)
    if P.get("mirror", 1):
        g = mirror_fill(g, band, livery, valid, h, z, nx, minZ, L, P)
    if P.get("holes", 1):
        g = fill_holes(g, valid, strict, P)
    return {"g": g, "band": band, "strict": strict, "plike": paintLike, "valid": valid, "pos": pos, "nrm": nrm, "clusters": clusters,
            "rear": int((g & (nz < -0.35) & (z < z0 + 0.05 * L)).sum())}


def sheet(res, out):
    rows = []
    for st, m in res["masks"].items():
        if not m["g"].any(): continue
        rgb = (m["rgb"].reshape(KR, KR, 3) * 255).astype(np.uint8)
        a = Image.fromarray(rgb).resize((384, 384), Image.NEAREST)
        tint = rgb.copy().astype(float)
        g = m["g"].reshape(KR, KR); band = m["band"].reshape(KR, KR)
        tint[band & ~g] = tint[band & ~g] * 0.6 + np.array([200, 160, 0]) * 0.4
        tint[g] = tint[g] * 0.35 + np.array([0, 200, 255]) * 0.65
        b = Image.fromarray(tint.astype(np.uint8)).resize((384, 384), Image.NEAREST)
        # 3D views of the valid texels coloured by texture, glass cyan: the right side (z, y), the front and the rear (x, y)
        pos = m["pos"]; v = m["valid"]; nrm = m["nrm"]
        views = []
        for ax, sel in (((2, 1), nrm[:, 0] > 0.3), ((0, 1), nrm[:, 2] > 0.3), ((0, 1), nrm[:, 2] < -0.3)):
            im = Image.new("RGB", (384, 384), (40, 40, 40)); dr = ImageDraw.Draw(im)
            vv = v & sel
            P = pos[vv]; C = (m["rgb"][vv] * 255).astype(int); G = g.reshape(-1)[vv]
            lo = pos[v].min(0); hi = pos[v].max(0); s = 360 / max(hi[ax[0]] - lo[ax[0]], hi[ax[1]] - lo[ax[1]])
            for i in range(len(P)):
                x = int(12 + (P[i, ax[0]] - lo[ax[0]]) * s); y = int(372 - (P[i, ax[1]] - lo[ax[1]]) * s)
                if DEBUG:
                    k = np.nonzero(vv)[0][i]
                    col = (0, 220, 255) if G[i] else (255, 0, 0) if m["strict"][k] else (255, 140, 0) if m["plike"][k] else (255, 255, 0) if m["band"][k] else tuple(C[i] // 3)
                else:
                    col = (0, 220, 255) if G[i] else tuple(C[i])
                dr.rectangle([x, y, x + 2, y + 2], fill=col)
            views.append(im)
        row = Image.new("RGB", (384 * 5, 400), (0, 0, 0))
        for k, im in enumerate([a, b] + views): row.paste(im, (384 * k, 16))
        ImageDraw.Draw(row).text((4, 2), f"{st}: {int(g.sum())} glass texels, rear {m['rear']}, paints {np.round(m['clusters'], 2).tolist()}", fill=(255, 255, 255))
        rows.append(row)
    if not rows: return
    S = Image.new("RGB", (384 * 5, 400 * len(rows)))
    for k, r in enumerate(rows): S.paste(r, (0, 400 * k))
    S.save(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("models"); ap.add_argument("names", nargs="+")
    ap.add_argument("--sheet"); ap.add_argument("--dump")
    ap.add_argument("--nodeep", action="store_true", help="without VEHICLE-GLASS-3's deep growth")
    ap.add_argument("--nobelt", action="store_true", help="without VEHICLE-GLASS-4's black-window-on-the-belt rule")
    ap.add_argument("--noholes", action="store_true", help="without VEHICLE-GLASS-5's fill of hull islands inside a pane")
    ap.add_argument("--nomirror", action="store_true", help="without VEHICLE-GLASS-5's mirror fill of each side window")
    ap.add_argument("--nosynth", action="store_true", help="without VEHICLE-GLASS-6's panes synthesized from the glasshouse")
    ap.add_argument("--nooff", action="store_true", help="without VEHICLE-GLASS-3's off-hue rule")
    ap.add_argument("--nobeltcut", action="store_true", help="without VEHICLE-GLASS-7's drop of side glass under the sill ledge")
    ap.add_argument("--nocoltop", action="store_true", help="column completion to 0.87 (before VEHICLE-GLASS-7's 0.90 glasshouse bound)")
    ap.add_argument("--old", action="store_true", help="the 33c34be heuristic (before VEHICLE-GLASS-2's class fixes)")
    a = ap.parse_args()
    params = {"roof": 0, "darkscale": 0, "screens": 0, "cool": 0, "split": 0, "offhue": 0, "deep": 0, "mirror": 0, "holes": 0, "synth": 0} if a.old else {}
    if a.nooff: params["offhue"] = 0
    if a.nodeep: params["deep"] = 0
    if a.nobelt: params["belt"] = 0
    if a.nomirror: params["mirror"] = 0
    if a.noholes: params["holes"] = 0
    if a.nosynth: params["synth"] = 0
    if a.nobeltcut: params["beltcut"] = 0
    if a.nocoltop: params["coltop"] = 0
    for name in a.names:
        r = build(a.models, name, params)
        if not r: print(name, "no glass (no roof/too small)"); continue
        if r.get("authored"): print(name, "authored glass, left alone"); continue
        tot = sum(int(m["g"].sum()) for m in r["masks"].values())
        print(name, "glass texels", tot, {k: int(m["g"].sum()) for k, m in r["masks"].items() if m["g"].sum()},
              "synth", r.get("carlike"), {k: v for k, v in r.get("synth", {}).items()})
        if a.dump:
            os.makedirs(a.dump, exist_ok=True)
            for st, m in r["masks"].items():
                with open(os.path.join(a.dump, f"glass_{st}.pgm"), "wb") as f:
                    f.write(b"P5\n%d %d\n255\n" % (KR, KR)); f.write((m["g"] * 255).astype(np.uint8).tobytes())
        if a.sheet:
            sheet(r, a.sheet.replace(".png", f"_{name}.png") if len(a.names) > 1 else a.sheet)
