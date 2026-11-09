#!/usr/bin/env python3
"""Facade depth from tile-art segmentation (QB-25): height maps with recessed windows,
doors and shop windows, glazing bars and frames between glass and wall, and protruding
sills, for the wall tiles of the gta2hd RTX Remix layer, so Remix's parallax displacement
gives the city's flat box faces depth.

Why a separate pass: tools/remix_pbr.py derives a height only from a band-passed
luminance and leaves out every tile with windows or signs (a dark window reads as a
groove, a bright frame as a ridge: the wrong shape), so the facades that most need depth
had none, or a wrong one.

Pipeline:
  1. usage(): which tiles the three maps put on building side faces (a tile used mostly
     as a lid is a roof or ground tile and is left alone).
  2. tools/facade_ground.py: a vision-language model (Qwen3-VL-8B) grounds windows, doors,
     shop windows and sills in each wall tile's HD texture as boxes (64 px tile units).
  3. segment_boxes(): the boxes on the game's own 64 px art, snapped to its pixel grid;
     a box that does not stand out from the wall round it (same colour, flat, not darker)
     is dropped; inside an opening the texels much lighter than its median are frame and
     glazing bars.
  4. height512(): label levels (1 = outermost, what the runtime's POM treats as the
     surface): sill 1.0, wall 0.80, frame 0.70, door 0.34, glass 0.18, bevelled edges,
     plus the HD tile's own structure band (bricks, joints) at a small amplitude.
     displace_in 0.04 (depth / UV width): a window recess of ~2.5 % of a block.
  5. build(): writes <hash>.h.rtex.dds (BC4, max mip chain) and <hash>.n.rtex.dds (the
     remix_pbr normal plus the relief's slope) for every wall tile with an opening, sets
     displace_in in pbr.json and patches those prims in mod.usda / mod_wet.usda in place
     (every other prim stays byte-identical). Files are unlinked before they are written,
     so a private layer made of hard links to the package layer is safe to build into.

segment() is the earlier colour-only segmentation (wall colour clusters + exhaustive
rectangle search); kept for `sheet` without BOXES, it misses windows with light frames
and is not used by build.

    facade_depth.py usage <game/data> <out.json>
    [BOXES=boxes.json] facade_depth.py sheet <game/data> <sty> <out.png> [tiles...]
    facade_depth.py build <game/data> <hd root> <mod dir> <boxes.json> [--min-side N] [--report out.json]

Needs numpy, scipy (segment only), Pillow, xxhash.
"""
import json, os, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "assets-src", "cars"))

H_CORNICE, H_PILASTER, H_WALL, H_FRAME, H_DOOR, H_GLASS = 1.0, 0.92, 0.80, 0.70, 0.34, 0.18
LABELS = ["wall", "glass", "frame", "sill", "cornice", "groove", "pilaster", "door"]
COLOURS = np.array([(150, 150, 150), (40, 90, 220), (240, 200, 60), (250, 250, 250), (255, 120, 40),
                    (60, 30, 30), (120, 220, 120), (200, 40, 160)], np.uint8)

# ------------------------------------------------------------------- map --
def usage(gmp):
    """side-face and lid counts per tile index of one .gmp (flat = transparent faces apart)"""
    d = open(gmp, "rb").read(); off = 6; c = {}
    while off + 8 <= len(d):
        tag = d[off:off + 4].decode("latin1"); size = struct.unpack_from("<I", d, off + 4)[0]
        c[tag] = (off + 8, size); off += 8 + size
    o, _ = c["DMAP"]; base = o + 256 * 256 * 4
    ncol = struct.unpack_from("<I", d, base)[0]; coldata = base + 4; nb = coldata + ncol * 4
    nblk = struct.unpack_from("<I", d, nb)[0]; bdata = nb + 4
    blocks = [struct.unpack_from("<5H", d, bdata + i * 12) for i in range(nblk)]
    side, lid, flat = {}, {}, {}
    for cell in range(256 * 256):
        wi = struct.unpack_from("<I", d, o + cell * 4)[0]; p = coldata + wi * 4
        h, offs = d[p], d[p + 1]
        for i in range(max(0, h - offs)):
            b = blocks[struct.unpack_from("<I", d, p + 4 + i * 4)[0]]
            for f in range(4):
                t = b[f] & 0x3FF
                if t in (0, 1023): continue
                dst = flat if b[f] & 0x1000 else side
                dst[t] = dst.get(t, 0) + 1
            t = b[4] & 0x3FF
            if t not in (0, 1023): lid[t] = lid.get(t, 0) + 1
    return side, lid, flat

def style_tiles(data, sty):
    """index -> 64x64 RGBA uint8 straight from the style file (palette index 0 transparent)"""
    # parse_sty lives in assets-src/cars beside the repo; from a detached worktree look beside game/data
    sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(data))), "assets-src", "cars"))
    import parse_sty, dump_style_tiles as dst
    st = parse_sty.parse(os.path.join(data, sty + ".sty")); c = dst.sty_chunks(st["d"])
    return lambda i: np.asarray(dst.tile_rgba(st, c, i), np.uint8)

# ----------------------------------------------------------- segmentation --
def lab(rgb):
    """sRGB (0..1) -> CIE Lab (D65)"""
    c = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = c @ M.T / np.array([0.9505, 1.0, 1.089], np.float32)
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

def kmeans(x, k, it=12, seed=0):
    rng = np.random.default_rng(seed)
    cen = x[rng.choice(len(x), k, replace=False)].copy()
    for _ in range(it):
        d = ((x[:, None, :] - cen[None]) ** 2).sum(-1); a = d.argmin(1)
        for j in range(k):
            if (a == j).any(): cen[j] = x[a == j].mean(0)
    d = ((x[:, None, :] - cen[None]) ** 2).sum(-1)
    return cen, d.argmin(1)

def _ndi():
    from scipy import ndimage
    return ndimage

def wall_mask(L, vis):
    """texels of the wall's own colour family. A tile repeats sideways along a wall, so the wall
    colours are the clusters found in both side strips; of those the biggest, plus the others that
    are not glass-like (much darker, blue-grey or lit), e.g. brick and its mortar."""
    h, w = vis.shape
    x = L[vis].reshape(-1, 3)
    k = 6 if len(x) >= 64 else 2
    cen, a = kmeans(x, k)
    lab_full = np.full((h, w), -1); lab_full[vis] = a
    area = np.bincount(a, minlength=k) / len(a)
    sw = max(w // 10, 3)
    left = np.bincount(lab_full[:, :sw][lab_full[:, :sw] >= 0], minlength=k) / max((lab_full[:, :sw] >= 0).sum(), 1)
    right = np.bincount(lab_full[:, -sw:][lab_full[:, -sw:] >= 0], minlength=k) / max((lab_full[:, -sw:] >= 0).sum(), 1)
    span = [j for j in range(k) if area[j] >= 0.05 and left[j] >= 0.08 and right[j] >= 0.08]
    if not span: span = [int(np.argmax(area))]
    span.sort(key=lambda j: -area[j])
    keep = [span[0]]; l0 = cen[span[0]][0]
    def glassy(c): return (c[2] < -7 and np.hypot(c[1], c[2]) < 40) or (c[0] > 60 and c[2] > 35) or c[0] < l0 - 25
    for j in span[1:]:
        if not glassy(cen[j]): keep.append(j)
    order = np.argsort(-area)
    for j in order:                                    # close shades of a wall colour anywhere in the tile
        if j in keep or area[j] < 0.04: continue
        if min(np.linalg.norm(cen[j] - cen[i]) for i in keep) < 12: keep.append(j)
    wall = np.isin(lab_full, keep)
    return wall, cen[keep], float(area[keep].sum())

def rect_search(nonwall, wall, min_h=6, min_w=4, min_area=30, max_area=0.5, inside=0.75, ring_wall=0.5, wallcols=True):
    """every axis-aligned rectangle whose inside is non-wall (>= `inside`) and whose one-texel
    ring (clipped at the tile's edge) is mostly wall; returns (area, y0, y1, x0, x1) sorted by
    area, largest first. Exhaustive with integral images (64 px: ~4 M rectangles)."""
    h, w = nonwall.shape
    In = np.zeros((h + 1, w + 1), np.int32); In[1:, 1:] = nonwall.cumsum(0).cumsum(1)
    Iw = np.zeros((h + 1, w + 1), np.int32); Iw[1:, 1:] = wall.cumsum(0).cumsum(1)
    def box(I, y0, y1, x0, x1):     # inclusive-exclusive, arrays broadcast
        return I[y1, x1] - I[y0, x1] - I[y1, x0] + I[y0, x0]
    xs0, xs1 = np.triu_indices(w + 1, 1)                 # x0 < x1 (exclusive end)
    xs0 = xs0.astype(np.int32); xs1 = xs1.astype(np.int32)
    keep = (xs1 - xs0) >= min_w
    xs0, xs1 = xs0[keep], xs1[keep]
    out = []
    wallcol_cs = True if wallcols else None
    for y0 in range(h):
        for y1 in range(y0 + min_h, h + 1):
            rh = y1 - y0
            area = rh * (xs1 - xs0)
            ok = (area >= min_area) & (area <= max_area * h * w)
            if not ok.any(): continue
            a0, a1 = xs0[ok], xs1[ok]; ar = area[ok]
            nin = box(In, y0, y1, a0, a1)
            good = nin >= inside * ar
            if not good.any(): continue
            a0, a1, ar = a0[good], a1[good], ar[good]
            if wallcol_cs is not None:               # no column inside that is wall top to bottom (two windows, not one)
                colN = In[y1, 1:] - In[y0, 1:] - In[y1, :-1] + In[y0, :-1]
                wc = np.concatenate([[0], np.cumsum(colN <= 0.12 * rh)])
                g1 = (wc[a1] - wc[a0]) == 0
                a0, a1, ar = a0[g1], a1[g1], ar[g1]
                if not len(a0): continue
            Y0, Y1 = max(y0 - 1, 0), min(y1 + 1, h)
            X0, X1 = np.maximum(a0 - 1, 0), np.minimum(a1 + 1, w)
            ring_n = (Y1 - Y0) * (X1 - X0) - ar
            ring_w = box(Iw, Y0, Y1, X0, X1) - box(Iw, y0, y1, a0, a1)
            g2 = (ring_n > 0) & (ring_w >= ring_wall * np.maximum(ring_n, 1))
            for x0, x1, A in zip(a0[g2].tolist(), a1[g2].tolist(), ar[g2].tolist()):
                out.append((A, y0, y1, x0, x1))
    out.sort(reverse=True)
    return out

def segment(rgba):
    """labels (64x64 int8, indices into LABELS, -1 transparent) and a summary dict"""
    nd = _ndi()
    h, w = rgba.shape[:2]
    vis = rgba[..., 3] >= 128
    lbl = np.full((h, w), -1, np.int8)
    info = {"openings": 0, "doors": 0, "bands": 0, "pilasters": 0, "wall_share": 0.0, "kind": "skip"}
    if vis.mean() < 0.95: return lbl, info                   # fences, railings, cut-outs: no facade
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    L = lab(rgb)
    lum = L[..., 0]
    chroma = np.hypot(L[..., 1], L[..., 2])
    wall, wcen, share = wall_mask(L, vis)
    info["wall_share"] = round(share, 3)
    lbl[:] = 0
    if share < 0.2: info["kind"] = "nowall"; return lbl, info
    wl = float(np.median(lum[wall]))
    dw = np.min(np.stack([np.linalg.norm(L - c, axis=-1) for c in wcen]), 0)
    nonwall = (~wall) & (dw > 9)
    wallish = ~nonwall
    bluish = (L[..., 2] < -6) & (chroma < 40)
    lit = (lum > 60) & (L[..., 2] > 35)                        # lit shop glass (warm yellow)
    openings = np.zeros((h, w), bool); doors = np.zeros((h, w), bool); taken = np.zeros((h, w), bool)
    rejected = np.zeros((h, w), bool)
    for A, y0, y1, x0, x1 in rect_search(nonwall, wallish):
        if taken[y0:y1, x0:x1].any(): continue
        if rejected[y0:y1, x0:x1].mean() > 0.5: continue       # a piece of a band or strip already turned down
        rh, rw = y1 - y0, x1 - x0
        if (nonwall[y0:y1, x0:x1].mean(1) <= 0.12).any(): continue   # a wall row inside: two windows stacked
        m = np.zeros((h, w), bool); m[y0:y1, x0:x1] = True
        shop = lit[m].mean() > 0.3 or bluish[m].mean() > 0.5
        bad_shape = ((rw >= w - 1 and (rh < 14 or not shop))      # a full-width band: cornice, shadow, roof edge
                     or (rh >= h - 1 and rw >= 0.5 * w)
                     or (max(rh, rw) > 5 * min(rh, rw) and min(rh, rw) < 8))   # thin: a joint, a pipe, a strip
        if bad_shape: rejected |= m; continue
        inner = lum[m]
        glass_ev = (bluish[m].mean() > 0.15) or (lit[m].mean() > 0.3) or ((lum[m] < wl - 20).mean() > 0.4)
        is_open = glass_ev and ((inner.mean() < wl - 8) or (bluish[m].mean() > 0.35) or (lit[m].mean() > 0.3))
        if not is_open: continue
        taken |= m
        if y1 >= h and rh >= 0.6 * h and rw < 0.5 * w: doors |= m
        else: openings |= m
    # inside an opening: the lighter texels are its frame and glazing bars (stand proud of the glass)
    for M, glass_lbl in ((openings, 1), (doors, 7)):
        if not M.any(): continue
        comp, n = nd.label(M)
        for k in range(1, n + 1):
            mk = comp == k
            med = float(np.median(lum[mk]))
            frame = mk & (lum > med + 18) & ~lit
            lbl[mk] = glass_lbl; lbl[frame] = 2
    info["openings"] = int(nd.label(openings)[1]); info["doors"] = int(nd.label(doors)[1])
    anyo = openings | doors
    # sills: lighter non-wall texels in the 4 rows under an opening, within its columns +-2
    if anyo.any():
        below = np.zeros((h, w), bool)
        cols = nd.binary_dilation(anyo, np.ones((1, 5), bool))
        for dy in range(1, 5):
            below[dy:] |= cols[:-dy]
        sill = below & ~anyo & nonwall & (lum > wl - 4)
        lbl[sill] = 3
    info["kind"] = "windows" if (info["openings"] or info["doors"]) else "plain"
    return lbl, info

def segment_boxes(rgba, boxes):
    """labels from grounded boxes (facade_ground.py): openings recessed, the lighter texels
    inside an opening (glazing bars, frame) between glass and wall, sills proud of the wall.
    Boxes are snapped to the 64 px grid; implausible ones (a whole-tile 'window', slivers)
    are dropped."""
    h, w = rgba.shape[:2]
    vis = rgba[..., 3] >= 128
    lbl = np.full((h, w), -1, np.int8)
    info = {"openings": 0, "doors": 0, "sills": 0, "kind": "plain"}
    if vis.mean() < 0.95: info["kind"] = "skip"; return lbl, info
    lbl[:] = 0
    L = lab(rgba[..., :3].astype(np.float32) / 255.0); lum = L[..., 0]
    order = {"sill": 0, "window": 1, "shop window": 1, "door": 2}
    for b in sorted(boxes, key=lambda b: order.get(b["label"], 9)):
        lab_ = b["label"]
        if lab_ not in order: continue
        x0, y0, x1, y1 = [int(round(v)) for v in b["box"]]
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, w), min(y1, h)
        bw, bh = x1 - x0, y1 - y0
        if bw < 3 or bh < 2: continue
        if lab_ == "sill":
            if bh > 10 or bw * bh > 0.25 * h * w: continue
            lbl[y0:y1, x0:x1] = 3; info["sills"] += 1; continue
        if bw * bh > 0.75 * h * w or min(bw, bh) < 4: continue
        if bw >= 0.95 * w and lab_ != "shop window": info["dropped"] = info.get("dropped", 0) + 1; continue   # girders, bands
        m = np.zeros((h, w), bool); m[y0:y1, x0:x1] = True
        # an opening must stand out from the wall round it: darker, or another colour, or busy inside
        ring = np.zeros((h, w), bool); ring[max(y0 - 3, 0):y1 + 3, max(x0 - 3, 0):x1 + 3] = True; ring &= ~m
        if ring.sum() >= 8:
            Lb = L[m].mean(0); Lr = L[ring].mean(0)
            busy = float(L[m][:, 0].std())
            if np.linalg.norm(Lb - Lr) < 9 and busy < 9 and Lb[0] > Lr[0] - 6: info["dropped"] = info.get("dropped", 0) + 1; continue
            if bw * bh > 0.4 * h * w and Lb[0] > Lr[0] - 10 and lab_ != "shop window":   # a big panel, not glass
                info["dropped"] = info.get("dropped", 0) + 1; continue
        med = float(np.median(lum[m]))
        g = 7 if lab_ == "door" else 1
        lbl[m] = g
        light = m & (lum > med + 20)
        # frame and glazing bars are lines: keep the light texels on a mostly-light row or column
        # of the box, or on its rim; light blobs inside (curtains, reflections) stay glass
        sub = light[y0:y1, x0:x1]
        rows = sub.mean(1) >= 0.6; cols_ = sub.mean(0) >= 0.6
        keep = np.zeros_like(sub); keep[rows, :] = True; keep[:, cols_] = True
        keep[0, :] = keep[-1, :] = True; keep[:, 0] = keep[:, -1] = True
        fr = np.zeros((h, w), bool); fr[y0:y1, x0:x1] = sub & keep
        lbl[fr] = 2
        if lab_ == "door": info["doors"] += 1
        else: info["openings"] += 1
    if info["openings"] or info["doors"]: info["kind"] = "windows"
    return lbl, info

# ----------------------------------------------------------------- height --
LEVEL = np.array([H_WALL, H_GLASS, H_FRAME, H_CORNICE, H_CORNICE, H_WALL - 0.12, H_PILASTER, H_DOOR], np.float32)

def height512(lbl, hd_rgba, size=512):
    """the label levels at `size`, edges softened into short bevels, plus the HD tile's fine
    structure (bricks, joints, sash bars) at a small amplitude. 1 = outermost."""
    import remix_pbr as rp
    from PIL import Image
    lv = np.where(lbl >= 0, LEVEL[np.clip(lbl, 0, None)], H_WALL).astype(np.float32)
    s = size / lbl.shape[0]
    big = np.asarray(Image.fromarray(lv, "F").resize((size, size), Image.NEAREST), np.float32)
    big = rp.gauss(big, 0.25 * s, True)                       # bevel: ~2 px at 512
    r = rp.analyse(hd_rgba, True, kind="tile")
    lum = hd_rgba[..., :3].astype(np.float32).mean(-1) / 255.0
    d = rp.gauss(lum, 0.9 * s / 8, True) - rp.gauss(lum, 13.0 * s / 8, True)
    loc = np.sqrt(np.maximum(rp.gauss(d * d, 20 * s / 8, True), 0)) + 0.035
    Hs = np.tanh(1.4 * d / loc)
    # structure only on the wall/cornice planes, almost none on glass (a flat pane)
    glassy = rp.gauss((np.asarray(Image.fromarray((lbl == 1).astype(np.uint8) * 255).resize((size, size), Image.NEAREST)) > 0)
                      .astype(np.float32), 1.0, True)
    H = big + 0.05 * Hs * (1 - 0.8 * glassy)
    return np.clip(H, 0, 1).astype(np.float32), r

def normal_with_relief(r_normal, H, depth_texels):
    """add the slope of the relief (H scaled to depth in texels) to the remix_pbr normal"""
    import remix_pbr as rp
    gx, gy = rp.grad(H * depth_texels, True)
    n = r_normal.copy()
    # the existing normal as slopes, plus the relief's (DirectX tangent space: +V down the image)
    sx = -n[..., 0] / np.maximum(n[..., 2], 0.2) - gx
    sy = n[..., 1] / np.maximum(n[..., 2], 0.2) + gy
    out = np.stack([sx, sy, np.ones_like(sx)], -1)
    return out / np.linalg.norm(out, axis=-1, keepdims=True)

# ------------------------------------------------------------------ sheet --
def colourise(lbl):
    out = np.zeros(lbl.shape + (3,), np.uint8)
    m = lbl >= 0
    out[m] = COLOURS[lbl[m]]
    return out

def sheet(data, sty, out, tiles, hd_root=None, size=160, boxes=None):
    from PIL import Image, ImageDraw
    import remix_pbr as rp
    get = style_tiles(data, sty)
    hd_root = hd_root or os.path.join(HERE, "..", "assets", "textures_hd")
    cells = []
    for t in tiles:
        rgba = get(t)
        if boxes is not None: lbl, info = segment_boxes(rgba, boxes.get(f"{sty}:{t}", {}).get("boxes", []))
        else: lbl, info = segment(rgba)
        hdp = os.path.join(hd_root, sty, f"tile_{t:04d}.dds")
        hd = np.asarray(Image.open(hdp).convert("RGBA")) if os.path.exists(hdp) else np.repeat(np.repeat(rgba, 8, 0), 8, 1)
        H, r = height512(lbl, hd)
        n = normal_with_relief(r["normal"], H, 0.07 * 512)
        lit = rp.shade(hd, n, light=(-0.75, -0.35, 0.45))
        row = [Image.fromarray(rgba).convert("RGB").resize((size, size), Image.NEAREST),
               Image.fromarray(colourise(lbl)).resize((size, size), Image.NEAREST),
               Image.fromarray((H * 255).astype(np.uint8)).convert("RGB").resize((size, size)),
               Image.fromarray(rp.shade(hd, r["normal"], light=(-0.75, -0.35, 0.45))).resize((size, size)),
               Image.fromarray(lit).resize((size, size))]
        cells.append((t, info, row))
    heads = ["art 64px", "segments", "height", "old normal lit", "new relief lit"]
    per = 2; cw = len(heads) * (size + 3) + 10
    W = per * cw; Hh = 16 + ((len(cells) + per - 1) // per) * (size + 14)
    S = Image.new("RGB", (W, Hh), (24, 24, 28)); d = ImageDraw.Draw(S)
    for p in range(per):
        for i, hname in enumerate(heads): d.text((p * cw + i * (size + 3) + 2, 3), hname, fill=(220, 220, 220))
    for j, (t, info, row) in enumerate(cells):
        x0 = (j % per) * cw; y0 = 16 + (j // per) * (size + 14)
        for i, im in enumerate(row): S.paste(im, (x0 + i * (size + 3), y0))
        d.text((x0 + 2, y0 + size), f"{sty} {t} " + " ".join(f"{k}:{v}" for k, v in info.items()), fill=(255, 230, 120))
    S.save(out); print(out, S.size)

# ------------------------------------------------------------------ build --
DISPLACE = 0.04          # depth of the full 0..1 range in UV units (a block): glass 0.18 -> wall 0.80 = 2.5 %
# (0.07 was tried first: under Remix the reveals smeared into wide bands of frame colour at grazing
# angles and arched windows looked melted; docs/facade-depth.md)

def patch_usda(path, disp):
    """set height_texture + displace_in on the prims of `disp` (hash -> displace_in) in a layer
    file, in place; every other prim and line is left as it is (the car, prop and avatar prims
    of remix_model_materials and the emissive inputs stay). Returns the number patched."""
    import re
    text = open(path, encoding="utf-8").read()
    out, n = [], 0
    parts = re.split(r'(?m)^(        over "mat_[0-9A-F]{16}"\n)', text)
    out.append(parts[0])
    for i in range(1, len(parts), 2):
        head, body = parts[i], parts[i + 1]
        h = head.split('"mat_')[1][:16]
        if h in disp:
            body = re.sub(r'(?m)^ *custom asset inputs:height_texture = @[^@]*@ \(\n[^\n]*\n *\)\n', "", body)
            body = re.sub(r'(?m)^ *custom float inputs:displace_in = [^\n]*\n', "", body)
            ins = ('                custom asset inputs:height_texture = @./textures/%s.h.rtex.dds@ (\n'
                   '                    colorSpace = "raw"\n                )\n'
                   '                custom float inputs:displace_in = %s\n' % (h, disp[h]))
            body = body.replace("                token outputs:out\n", ins + "                token outputs:out\n", 1)
            n += 1
        out.append(head); out.append(body)
    new = "".join(out)
    if os.path.lexists(path): os.unlink(path)                    # may be a hard link into the package layer
    open(path, "w", encoding="utf-8", newline="\n").write(new)
    return n

def build(data, hd_root, mod, boxes_path, min_side=1, report=None, styles=("wil", "bil", "ste"), only=None):
    from PIL import Image
    import remix_materials as rmat
    tex = os.path.join(mod, "textures")
    boxes = json.load(open(boxes_path))
    info_path = os.path.join(mod, "pbr.json")
    pbr = json.load(open(info_path)) if os.path.exists(info_path) else {}
    rep = {"tiles": {}, "counts": {}}; disp = {}
    for sty in styles:
        side, lid, flat = usage(os.path.join(data, sty + ".gmp"))
        get = style_tiles(data, sty)
        n_done = 0
        for t in sorted(side):
            key = f"{sty}:{t}"
            if side[t] < min_side or side[t] < 0.5 * lid.get(t, 0) or key not in boxes: continue
            if only and key not in only: continue
            hdp = os.path.join(hd_root, sty, f"tile_{t:04d}.dds")
            if not os.path.exists(hdp): continue
            lbl, info = segment_boxes(get(t), boxes[key]["boxes"])
            if info["kind"] != "windows": continue
            h = rmat.dds_hash(hdp)
            if not os.path.exists(os.path.join(tex, f"{h}.a.rtex.dds")): continue   # not in this layer
            hd = np.asarray(Image.open(hdp).convert("RGBA"))
            H, r = height512(lbl, hd)
            n = normal_with_relief(r["normal"], H, DISPLACE * 512)
            for ext in ("h", "n"):
                p = os.path.join(tex, f"{h}.{ext}.rtex.dds")
                if os.path.lexists(p): os.unlink(p)
            rmat.write_height(os.path.join(tex, f"{h}.h.rtex.dds"), rmat.small((H * 255).astype(np.uint8), 256))
            rmat.write_normal(os.path.join(tex, f"{h}.n.rtex.dds"), n)
            e = pbr.setdefault(h, {}); e["displace_in"] = DISPLACE; e["facade"] = {k: v for k, v in info.items() if k != "kind"}
            disp[h] = DISPLACE
            rep["tiles"][key] = dict(info, hash=h, side=side[t], lid=lid.get(t, 0))
            n_done += 1
        rep["counts"][sty] = n_done
        print(sty, "facade tiles written:", n_done, flush=True)
    tmp = info_path + ".tmp"; json.dump(pbr, open(tmp, "w"), indent=0, sort_keys=True)
    if os.path.lexists(info_path): os.unlink(info_path)
    os.replace(tmp, info_path)
    for name in ("mod.usda", "mod_wet.usda"):
        p = os.path.join(mod, name)
        if os.path.exists(p): print(name, "prims patched:", patch_usda(p, disp))
    if report: json.dump(rep, open(report, "w"), indent=1)
    return rep

def main():
    a = sys.argv[1:]
    if not a: print(__doc__); return
    if a[0] == "usage":
        out = {}
        for sty in ("wil", "bil", "ste"):
            s, l, f = usage(os.path.join(a[1], sty + ".gmp")); out[sty] = {"side": s, "lid": l, "flat": f}
        json.dump(out, open(a[2], "w")); print(a[2])
    elif a[0] == "sheet":
        data, sty, out = a[1], a[2], a[3]
        tiles = [int(t) for t in a[4:]]
        if not tiles:
            s, l, f = usage(os.path.join(data, sty + ".gmp"))
            tiles = sorted(s, key=lambda t: -s[t])[:40]
        bx = os.environ.get("BOXES")
        sheet(data, sty, out, tiles, boxes=json.load(open(bx)) if bx else None)
    elif a[0] == "build":
        data, hd_root, mod, bx = a[1], a[2], a[3], a[4]
        ms = int(a[a.index("--min-side") + 1]) if "--min-side" in a else 1
        rp = a[a.index("--report") + 1] if "--report" in a else None
        only = set(a[a.index("--only") + 1].split(",")) if "--only" in a else None
        build(data, hd_root, mod, bx, ms, rp, only=only)

if __name__ == "__main__":
    main()
