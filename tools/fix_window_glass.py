#!/usr/bin/env python3
"""FIX-REMIX (defect pt-police-station-window-glass-artefacts): window glass the HD upscale
turned into noise, repainted as dark glass.

The 64 px art dithers dark window glass with a few light texels. Real-ESRGAN and the SD tile
pass (tools/upscale_textures.py, tools/enhance_textures_sd.py) read that dither as shapes and
grew it into cyan "glyph" blobs and diagonal streaks on a muddy gradient: on the Downtown
police station's arched windows (wil tiles 704, 705) every pane reads as rotten texture. The
photo set (tools/photoreal_tiles.py) starts from the HD tile and keeps its glass as it is, so
it carries the same blobs.

What it does, per tile. The panes are the large dark regions of the tile (luma under
--dark), closed and hole-filled so the blobs inside a pane belong to it; a region must be
big (--min-area of the tile) and mostly dark around its edge. Inside each pane: a dark
glass gradient (a faint sky reflection at the top, near black at the foot, a soft diagonal
sheen), thin mullions (one upright, one transom), and a darker rim a few texels wide that
keeps the frame crisp against the stone. Everything outside the panes is untouched, so the
tile wraps as before and the stone keeps its look.

    fix_window_glass.py scan  <dds dir> [--tiles a,b]          tiles whose glass looks like glyphs
    fix_window_glass.py fix   <in.dds> <out.dds> [--preview p] repaint one tile (DXT1, mips)
    fix_window_glass.py albedo <in.dds> <out.a.rtex.dds>        the same, as a Remix albedo (BC3)
    fix_window_glass.py pbr   <hd tile.dds> <mod dir> [--deglyph] the repainted tile's Remix maps, <hash>.<map>g
    fix_window_glass.py usda  <mod dir> <hash> [<hash>...]       point those prims at the <map>g files

The scan is the guard for other tiles: it reports panes whose inside holds many small light
blobs (the hallucinated glyphs) rather than one reflection. Never run `fix` onto
assets/textures_hd/<style>/ (the Remix layer is keyed by those files' hashes): write into the
photo/ set (plain renderer) and give Remix the repainted albedo under the same hash.
Needs numpy, scipy, Pillow (and xxhash for remix_materials' helpers).
"""
import argparse, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm


def read(path):
    return np.asarray(Image.open(path).convert("RGBA")).copy()


def luma(rgb):
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]) / 255.0


def panes(rgba, dark=0.12, min_area=0.01):
    """Labelled pane mask: the dark glass and the teal glyph blobs on it (the upscale's
    colour for the dither), lightly closed; a hole is taken in only when it looks like glass
    too (dark or teal on average), so the stone between two panes stays stone. Each pane
    with how many glyph blobs it held."""
    rgb = rgba[..., :3].astype(np.float32)
    L = luma(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    teal = (g - r > 28) & (b - r > 18) & (L < 0.62)   # the blobs: ~(42, 92, 83); the stone ~(56, 69, 64)
    d = (L < dark) | teal
    d = ndi.binary_opening(d, iterations=1)
    d = ndi.binary_closing(d, iterations=2)
    lab, n = ndi.label(d)
    out = np.zeros(L.shape, np.int32)
    info = []
    k = 0
    for i in range(1, n + 1):
        m = lab == i
        if m.mean() < min_area or (L[m] < dark).mean() < 0.4:
            continue
        filled = ndi.binary_fill_holes(m)
        hl, hn = ndi.label(filled & ~m)
        for h in range(1, hn + 1):
            hm = hl == h
            if L[hm].mean() > 0.35 and teal[hm].mean() < 0.3:
                filled &= ~hm
        # Short gaps across the pane (a light transom line of the old art with flecks
        # on it): bridged along rows and columns up to 13 texels, never the stone pillar
        # between two panes, which is wider.
        bridge = (ndi.binary_closing(filled, structure=np.ones((1, 13), bool)) |
                  ndi.binary_closing(filled, structure=np.ones((13, 1), bool)))
        filled |= bridge & (L < 0.62)
        ys, xs = np.nonzero(filled)
        h, w = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
        if h < 24 or w < 24:
            continue
        bl, bn = ndi.label(teal & filled)
        sizes = ndi.sum(np.ones_like(L), bl, range(1, bn + 1)) if bn else np.zeros(0)
        blobs = int(((sizes > 6) & (sizes < 0.02 * filled.sum())).sum())
        k += 1
        out[filled & (out == 0)] = k
        # How dark the pane is under its blobs, and how small the blobs are: a hallucinated
        # pane is near black with many small teal flecks; a neon sign or a fan is not.
        darkness = float((L[filled & ~teal] < dark).mean()) if (filled & ~teal).any() else 0.0
        small = float(np.median(sizes[(sizes > 6)])) / filled.sum() if (sizes > 6).any() else 1.0
        info.append(dict(id=k, area=float(filled.mean()), box=(int(xs.min()), int(ys.min()), int(w), int(h)),
                         blobs=blobs, darkness=darkness, blob_size=small))
    return out, info


def repaint(rgba, lab, info, rim=5, mullion=5):
    out = rgba.astype(np.float32).copy()
    H, W = lab.shape
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for p in info:
        m = lab == p["id"]
        x0, y0, w, h = p["box"]
        t = np.clip((yy - y0) / max(h - 1, 1), 0, 1)            # 0 top .. 1 foot
        # A pane running off the tile's top is the lower part of a window whose head is
        # on the tile above: carry on from that pane's foot, and leave the transom to it.
        cont = y0 == 0
        if cont:
            t = 0.6 + 0.4 * t
        s = np.clip((xx - x0) / max(w - 1, 1), 0, 1)
        top = np.array([66, 78, 92], np.float32)               # a dull sky in the glass
        foot = np.array([14, 18, 24], np.float32)
        g = top[None, None, :] * (1 - t[..., None]) ** 1.6 + foot[None, None, :] * (1 - (1 - t[..., None]) ** 1.6)
        sheen = np.exp(-((s - 0.35 - 0.5 * t) / 0.09) ** 2) * 18.0 * (1 - t)
        g = g + sheen[..., None]
        # Mullions: an upright at the middle, a transom at a third of the height.
        cx, cy = x0 + w / 2.0, y0 + h / 3.0
        bar = (np.abs(xx - cx) < mullion / 2.0) | ((np.abs(yy - cy) < mullion / 2.0) & (not cont))
        inner = ndi.binary_erosion(m, iterations=rim)
        frame = np.array([34, 34, 36], np.float32)
        col = np.where((bar & inner)[..., None], frame[None, None, :], g)
        col = np.where((m & ~inner)[..., None], frame[None, None, :] * 0.8, col)
        out[..., :3] = np.where(m[..., None], col, out[..., :3])
    # Soften the pane's edge by a texel into the stone around it.
    edge = ndi.binary_dilation(lab > 0, iterations=1) & ~(lab > 0)
    blur = ndi.uniform_filter(out[..., :3], size=(3, 3, 1))
    out[..., :3] = np.where(edge[..., None], 0.5 * out[..., :3] + 0.5 * blur, out[..., :3])
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def write_dxt1(path, rgba):
    data = [rm.bc1_colour_blocks(np.clip(np.rint(m[..., :3]), 0, 255).astype(np.uint8)).tobytes()
            for m in rm.mips(rgba.astype(np.float32))]
    rm.dds(path, (data, rgba.shape[:2]), b"DXT1", 8)


def cmd_scan(a):
    names = sorted(f for f in os.listdir(a.dir) if f.startswith("tile_") and f.endswith(".dds"))
    if a.tiles:
        want = {int(t) for t in a.tiles.split(",")}
        names = [f for f in names if int(f[5:9]) in want]
    for f in names:
        try:
            lab, info = panes(read(os.path.join(a.dir, f)))
        except Exception:
            continue
        bad = [p for p in info if p["blobs"] >= 20 and p["darkness"] > 0.85 and p["blob_size"] < 0.01]
        if bad:
            print(f, "panes", len(info), "glyph panes", len(bad), "blobs", sum(p["blobs"] for p in bad))


def deglyph(rgba, panes_mask, size=13, min_len=48, depth=0.025):
    """FIX-REMIX-MATERIALS-9 (ptrmx30, layer half): the upscaler's pseudo-lettering on the stone ("l d l" on the
    sill blocks, "| |" on the lower band of wil 705) and the glyph blobs the pane repaint missed at a transom
    (wil 704). Thin dark strokes = what a grey closing (size x size) lifts by more than `depth`; strokes whose
    extent reaches `min_len` texels are mortar lines, block edges and cornices and stay; the rest are filled
    from the closing. A small bright blob on the glass (inside a pane's box, below its arch head, under 120
    texels) is filled from a grey opening. Returns (rgba, filled mask, blob mask: the blobs on the glass, which
    the caller adds to the pane mask so they are glass to the path tracer too, not matte stone patches). Stone tone stays the HD tile's (the
    photo set's stone is darker and greener: pasting it would seam against the neighbouring HD tiles)."""
    rgb = rgba[..., :3].astype(np.float32) / 255
    L = rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    closed = np.stack([ndi.grey_closing(rgb[..., c], size=(size, size), mode='wrap') for c in range(3)], -1)
    Lc = closed @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    res = (Lc - L) > depth                          # thin dark strokes
    lab, n = ndi.label(res, structure=np.ones((3, 3)))
    sl = ndi.find_objects(lab)
    keep = np.zeros(n + 1, bool)
    for i, s in enumerate(sl, 1):
        hgt, wid = s[0].stop - s[0].start, s[1].stop - s[1].start
        if max(hgt, wid) >= min_len: keep[i] = True   # mortar lines, block edges, cornices
    glyph = res & ~keep[lab]
    glyph = ndi.binary_dilation(glyph, iterations=2) & ~ndi.binary_dilation(panes_mask, iterations=2)
    # teal glyph blobs the pane repaint missed (at a transom): a bright small feature on the glass
    r_, g_, b_ = [rgba[..., c].astype(np.float32) for c in range(3)]
    teal = (g_ - r_ > 28) & (b_ - r_ > 18) & (L < 0.62)
    teal = ndi.binary_dilation(teal, iterations=3)
    opened = np.stack([ndi.grey_opening(rgb[..., c], size=(25, 25), mode='wrap') for c in range(3)], -1)
    zone = ndi.binary_dilation(panes_mask, iterations=12)
    Lo = opened @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bright = zone & ((L - Lo) > 0.04)
    bl, bn = ndi.label(ndi.binary_dilation(bright, iterations=2))
    plab, _ = ndi.label(panes_mask)
    onglass = np.zeros_like(panes_mask, dtype=bool)   # the blobs on the glass only (the pane mask grows by these)
    for i, s_ in enumerate(ndi.find_objects(bl), 1):
        comp = bl == i
        ys, xs = np.nonzero(comp)
        pl = plab[ndi.binary_dilation(comp, iterations=4)]; pl = pl[pl > 0]
        if pl.size == 0: continue
        pys, pxs = np.nonzero(plab == np.bincount(pl).argmax())
        cy, cx = ys.mean(), xs.mean()
        inside = pxs.min() <= cx <= pxs.max() and pys.min() <= cy <= pys.max()
        low = (cy - pys.min()) > 0.3 * (pys.max() - pys.min())       # not the arch head at the pane's top
        ring = ndi.binary_dilation(comp, iterations=4) & ~comp
        ringed = panes_mask[ring].mean() > 0.6 if ring.any() else False      # on the glass, not a stone chip by a pane
        if max(s_[0].stop - s_[0].start, s_[1].stop - s_[1].start) < 120 and inside and low and ringed:
            teal |= comp & zone                       # a blob on the glass; not a mullion, transom or the stone
            box = np.zeros_like(teal); box[pys.min():pys.max() + 1, pxs.min():pxs.max() + 1] = True
            onglass |= ndi.binary_dilation(comp & zone, iterations=5) & box
    teal = ndi.binary_dilation(teal, iterations=5)
    closed = np.where(teal[..., None], opened, closed)
    glyph = glyph | teal
    out = rgba.copy()
    blend = ndi.gaussian_filter(glyph.astype(np.float32), 0.7)
    blend = np.maximum(blend, glyph)
    out[..., :3] = np.clip((rgb * (1 - blend[..., None]) + closed * blend[..., None]) * 255 + 0.5, 0, 255).astype(np.uint8)
    return out, glyph, onglass


def cmd_fix(a, albedo=False):
    rgba = read(a.src)
    lab, info = panes(rgba)
    out = repaint(rgba, lab, info)
    if albedo:
        rm.write_albedo(a.dst, out)
    else:
        write_dxt1(a.dst, out)
    if a.preview:
        Image.fromarray(np.concatenate([rgba, out], 1)).save(a.preview)
    print(a.src, "->", a.dst, "panes", len(info), "blobs", [p["blobs"] for p in info])


def cmd_pbr(a):
    """The repainted tile through the layer's own map maker (remix_materials.pbr_tile): albedo,
    normal, roughness, height (and metal) without the glyphs' relief, written into the mod's
    textures folder as <hash>.<map>g.rtex.dds - new files beside the tile's own maps, which
    stay as they are (the folder is shared by hard links)."""
    import shutil, tempfile
    tex = os.path.join(a.mod, "textures")
    with tempfile.TemporaryDirectory() as tmp:
        fixed = os.path.join(tmp, "fixed.dds")
        rgba = read(a.src)
        lab, info = panes(rgba)
        out = repaint(rgba, lab, info)
        glass = lab > 0
        if a.deglyph:
            out, _, blob = deglyph(out, glass)
            glass = glass | blob
        write_dxt1(fixed, out)
        h = a.hash or rm.dds_hash(a.src)
        # FIX-REMIX-MATERIALS-6 (ptrmx30): the panes are glass to the path tracer (roughness ~0.05, no
        # relief, set back in the height map), not a matte picture of glass: the sky and street reflect
        rm.pbr_tile((fixed, h, tmp, 512, 256, None, False, None, None, glass))
        for f in sorted(os.listdir(tmp)):
            if f.startswith(h + "."):
                kind = f.split(".")[1]
                dst = os.path.join(tex, f"{h}.{kind}g.rtex.dds")
                if os.path.lexists(dst): os.unlink(dst)
                shutil.copyfile(os.path.join(tmp, f), dst)
                print(dst)


def cmd_usda(a):
    """Points each prim's maps at the <hash>.<map>g files cmd_pbr made, where they exist."""
    import re
    tex = os.path.join(a.mod, "textures")
    for name in ("mod.usda", "mod_wet.usda"):
        path = os.path.join(a.mod, name)
        if not os.path.exists(path):
            continue
        text = open(path, encoding="utf-8").read()
        n = 0
        for h in a.hashes:
            def swap(m):
                nonlocal n
                g = f"{h}.{m.group(1)}g.rtex.dds"
                if os.path.exists(os.path.join(tex, g)): n += 1; return "./textures/" + g
                return m.group(0)
            text = re.sub(r"\./textures/%s\.([anrhmw])\.rtex\.dds" % h, swap, text)
        open(path, "w", encoding="utf-8", newline="\n").write(text)
        print(name, n, "map references repointed")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("dir"); s.add_argument("--tiles")
    for name in ("fix", "albedo"):
        f = sub.add_parser(name); f.add_argument("src"); f.add_argument("dst"); f.add_argument("--preview")
    u = sub.add_parser("usda"); u.add_argument("mod"); u.add_argument("hashes", nargs="+")
    q = sub.add_parser("pbr"); q.add_argument("src"); q.add_argument("mod"); q.add_argument("--hash")
    q.add_argument("--deglyph", action="store_true", help="FIX-REMIX-MATERIALS-9: also fill the upscaler's pseudo-lettering on the stone (deglyph)")
    a = ap.parse_args()
    if a.cmd == "scan": cmd_scan(a)
    elif a.cmd == "usda": cmd_usda(a)
    elif a.cmd == "pbr": cmd_pbr(a)
    else: cmd_fix(a, albedo=a.cmd == "albedo")


if __name__ == "__main__":
    main()
