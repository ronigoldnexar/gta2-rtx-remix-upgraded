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
    res = {"name": name, "masks": {}, "H": H, "L": L, "z0": z0, "z1": z1, "minY": minY, "minZ": minZ, "top": top}
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
    return res


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
    ap.add_argument("--nooff", action="store_true", help="without VEHICLE-GLASS-3's off-hue rule")
    ap.add_argument("--old", action="store_true", help="the 33c34be heuristic (before VEHICLE-GLASS-2's class fixes)")
    a = ap.parse_args()
    params = {"roof": 0, "darkscale": 0, "screens": 0, "cool": 0, "split": 0, "offhue": 0, "deep": 0} if a.old else {}
    if a.nooff: params["offhue"] = 0
    if a.nodeep: params["deep"] = 0
    if a.nobelt: params["belt"] = 0
    for name in a.names:
        r = build(a.models, name, params)
        if not r: print(name, "no glass (no roof/too small)"); continue
        if r.get("authored"): print(name, "authored glass, left alone"); continue
        tot = sum(int(m["g"].sum()) for m in r["masks"].values())
        print(name, "glass texels", tot, {k: int(m["g"].sum()) for k, m in r["masks"].items() if m["g"].sum()})
        if a.dump:
            os.makedirs(a.dump, exist_ok=True)
            for st, m in r["masks"].items():
                with open(os.path.join(a.dump, f"glass_{st}.pgm"), "wb") as f:
                    f.write(b"P5\n%d %d\n255\n" % (KR, KR)); f.write((m["g"] * 255).astype(np.uint8).tobytes())
        if a.sheet:
            sheet(r, a.sheet.replace(".png", f"_{name}.png") if len(a.names) > 1 else a.sheet)
