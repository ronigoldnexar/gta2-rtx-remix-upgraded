#!/usr/bin/env python3
"""Street-view photo-set fixes for two kinds of ground tile whose HD art reads wrong up close
(FIX-WORLD-15, qav28 and qav25).

grate  (qav28, wil Downtown plaza lattice 193/196): the HD tile painted a black plate crossed by thin
       white chain-link diamonds, while its alpha keeps the classic tile's holes. The holes land as
       irregular blobs inside the drawn diamonds, so in the street views the field read as near-black
       noise with pale/green speckle instead of the classic's grey wire weave over the green floor.
       The variant keeps the HD alpha exactly (the cut-out, the shadow copy and the Remix-side HD
       tile are unchanged) and repaints the colour from the classic 64 px tile, upscaled: grey wire
       at the classic's luminance, darkened at each hole's rim and lit along the strands, so the
       colour and the holes agree. Where no hole is near (the frame and the nested bars) the HD
       detail stays, scaled to the classic tile's luminance there.

shadow (qav25, map-tree ground tiles: ste 513/529/779/780/742/949/958, bil 717): the classic art
       paints a soft olive tree shadow under every map tree; the HD upscale sharpened it into a
       black bare-twig web. The street views draw a leafy tree model there, so the variant lifts
       the thin dark strokes out (inpainted from the ground around them) and puts back a soft,
       crown-sized dapple of the same strokes blurred, at a fraction of their strength.

Both write gta2dx9_textures_hd/photo/<style>/tile_NNNN.dds (workspace assets/textures_hd/photo/):
the photo set is loaded only while a street view shows and never on an RTX Remix device, so the
classic view and the Remix hashes of assets/textures_hd/<style>/ stay as they are
(memory/doc: hd-tiles-remix-hash-lock). Files are written by rename (a new inode), never through
a stage's hard link.

    street_ground_tiles.py grate  <hd root> <photo root> <classic tiles root> [--tiles wil:193,wil:196]
    street_ground_tiles.py shadow <hd root> <photo root> [--tiles ste:513,...] [--keep 0.35]

hd root: assets/textures_hd; photo root: assets/textures_hd/photo; classic tiles root: a dump of the
64 px tiles (tools/dump_style_tiles.py <game/data> <style> <root>/<style> --all). Needs numpy, Pillow,
scipy and OpenCV (the gen3d venv has them). docs/asset-audit.md (FIX-WORLD-15).
"""
import argparse, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SHADOW_TILES = "ste:513,ste:529,ste:779,ste:780,ste:742,ste:949,ste:958,bil:717"


def load(path):
    return np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0


def luma(rgb):
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def write_dds(path, rgba, fmt):
    from pack_textures_dds import dds_header, encode_level
    rgb = Image.fromarray((np.clip(rgba[..., :3], 0, 1) * 255 + 0.5).astype(np.uint8))
    alpha = Image.fromarray((np.clip(rgba[..., 3], 0, 1) * 255 + 0.5).astype(np.uint8))
    levels, (w, h) = [], rgb.size
    cur = rgb.copy(); cur.putalpha(alpha)
    while True:
        levels.append(encode_level(cur, fmt))
        if w == 1 and h == 1: break
        w, h = max(1, w // 2), max(1, h // 2)
        cur = rgb.resize((w, h), Image.LANCZOS); cur.putalpha(alpha.resize((w, h), Image.BOX))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(dds_header(rgb.size[0], rgb.size[1], len(levels), fmt.encode(), len(levels[0])))
        for lv in levels: f.write(lv)
    os.replace(tmp, path)    # a new inode: never write through a hard link into a stage


def grate(hd, classic):
    n = hd.shape[0]
    solid = hd[..., 3] > 0.5
    hole = (~solid).astype(np.float32)
    # The classic colour at the HD size. Keyed classic texels are black: fill them from their
    # neighbours first so the upscale does not pull every strand towards black.
    c = classic.copy()
    ck = c[..., 3] < 0.5
    if ck.any():
        idx = ndimage.distance_transform_edt(ck, return_distances=False, return_indices=True)
        c[..., :3] = c[idx[0], idx[1], :3]
    s = n / 64.0
    # The classic weave at the HD size: a bicubic upscale (keyed texels filled from their neighbours
    # so the strands are not pulled towards black), its detail above a 2-texel low-pass steepened so
    # the grey diagonal strands and the dark painted gaps come out as crisp shapes instead of an 8x blur.
    up = np.asarray(Image.fromarray((c[..., :3] * 255 + 0.5).astype(np.uint8)).resize((n, n), Image.BICUBIC)).astype(np.float32) / 255.0
    low = ndimage.gaussian_filter(up, (2.0 * s, 2.0 * s, 0))
    det = up - low
    crisp = low + np.tanh(det * 9.0) / 9.0 * 1.7
    # Wire depth: a little darker at a keyed hole's rim (the strand turns away), a fine metal grain.
    dist = ndimage.distance_transform_edt(solid) / s
    rim = np.clip(1.0 - dist / 0.9, 0.0, 1.0)
    rng = np.random.default_rng(193)
    grain = ndimage.gaussian_filter(rng.normal(0.0, 1.0, (n, n)).astype(np.float32), 0.8) * 0.04
    rgb = np.clip(crisp * (1.0 - 0.35 * rim + grain)[..., None], 0.0, 1.0)
    gain = luma(rgb)[solid].mean() / max(luma(hd[..., :3])[solid].mean(), 1e-3)
    out = hd.copy()
    out[..., :3] = np.where(solid[..., None], rgb, up * 0.5)   # behind a hole: only the filtered fringe
    return out, gain


def shadow(hd, keep):
    rgb = hd[..., :3]
    L = luma(rgb)
    base = ndimage.median_filter(L, size=21)
    dark = np.clip((base - L) / np.maximum(base, 1e-3), 0.0, 1.0)
    strokes = dark > 0.16
    strokes = ndimage.binary_opening(strokes, iterations=1) | (dark > 0.30)
    strokes = ndimage.binary_dilation(strokes, iterations=3)
    import cv2
    img8 = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    clean = cv2.inpaint(img8[..., ::-1].copy(), strokes.astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA)[..., ::-1]
    clean = clean.astype(np.float32) / 255.0
    # The leaf-mass dapple: the strokes' own darkness, blurred to the crown's scale.
    dap = ndimage.gaussian_filter(np.where(strokes, dark, 0.0), hd.shape[0] / 22.0, mode="reflect")
    dap = np.clip(dap * 4.0, 0.0, 1.0)
    shade = 1.0 - keep * dap
    out = hd.copy()
    out[..., :3] = clean * shade[..., None]
    return out, float(strokes.mean())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("grate", "shadow"))
    p.add_argument("hd"); p.add_argument("photo")
    p.add_argument("classic", nargs="?")
    p.add_argument("--tiles")
    p.add_argument("--keep", type=float, default=0.35)
    a = p.parse_args()
    tiles = a.tiles or ("wil:193,wil:196" if a.mode == "grate" else SHADOW_TILES)
    for item in tiles.split(","):
        style, t = item.split(":"); t = int(t)
        hd = load(os.path.join(a.hd, style, "tile_%04d.dds" % t))
        if a.mode == "grate":
            cl = load(os.path.join(a.classic, style, "tile_%04d.tga" % t))
            out, gain = grate(hd, cl)
            note = "luma x%.2f of the HD tile" % gain
            fmt = "DXT5"
        else:
            out, frac = shadow(hd, a.keep)
            note = "strokes %.1f%% of the tile" % (100 * frac)
            fmt = "DXT1" if hd[..., 3].min() > 0.99 else "DXT5"
        d = os.path.join(a.photo, style); os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, "tile_%04d.dds" % t)
        write_dds(dst, out, fmt)
        m = out[..., 3] > 0.5
        print("%s %s %d: opaque mean %s -> %s (%s) -> %s" % (a.mode, style, t,
              np.round(255 * hd[..., :3][m].mean(0), 1), np.round(255 * out[..., :3][m].mean(0), 1), note, dst))


if __name__ == "__main__":
    main()
