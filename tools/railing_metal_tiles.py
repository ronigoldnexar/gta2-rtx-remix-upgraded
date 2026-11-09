#!/usr/bin/env python3
"""Street-view iron for near-black railing tiles (FIX-WORLD-3, pm5-iron-fence-renders-solid-black-blocks).

The Downtown park fence (wil tile 635, the spear fence QB-11 builds as bars, rails and finials)
is painted almost pure black in the HD art: its opaque texels average 18/255, with orange specks
on the finials. Lit in the street views the bars came out at about 15/255, a black silhouette
with no shading and no metal. This writes a photo-set variant of such a tile
(gta2dx9_textures_hd/photo/<style>/tile_NNNN.dds in a stage, assets/textures_hd/photo/<style>/
in the workspace): dark grey painted iron. The HD tile's own luminance structure is kept as relief
around a new mean (edges, rivets, the finial's bevels), the colour is a cool neutral grey (the
orange specks go), and alpha is the HD tile's, untouched, so the cut-out and QB-11's geometry
are the same.

The photo set is street-view only (the renderer loads it before the HD set while a street view
shows, never in the classic view and never on an RTX Remix device), so the classic view and the
Remix hashes are untouched. Run it after tools/photoreal_tiles.py build, which would otherwise
leave the tile as the near-black transfer.

    railing_metal_tiles.py <hd root> <photo root> [--tiles wil:635] [--mean 0.23] [--relief 0.06]

hd root: assets/textures_hd (reads <style>/tile_NNNN.dds); photo root: assets/textures_hd/photo.
Needs numpy and Pillow.
"""
import argparse, os, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def iron(rgba, mean, relief):
    a = rgba[..., 3] > 0.5
    L = rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722
    mu, sd = float(L[a].mean()), float(L[a].std()) or 1.0
    s = np.clip((L - mu) / sd, -2.0, 2.0)
    g = np.clip(mean + relief * s, 0.04, 0.6)
    out = rgba.copy()
    for c, tint in enumerate((0.96, 1.0, 1.05)):
        out[..., c] = np.where(a, np.clip(g * tint, 0.0, 1.0), rgba[..., c])
    return out


def write_dds(path, rgba):
    from pack_textures_dds import dds_header, encode_level
    rgb = Image.fromarray((rgba[..., :3] * 255 + 0.5).astype(np.uint8))
    alpha = Image.fromarray((rgba[..., 3] * 255 + 0.5).astype(np.uint8))
    levels, (w, h) = [], rgb.size
    cur = rgb.copy(); cur.putalpha(alpha)
    while True:
        levels.append(encode_level(cur, "DXT5"))
        if w == 1 and h == 1: break
        w, h = max(1, w // 2), max(1, h // 2)
        cur = rgb.resize((w, h), Image.LANCZOS); cur.putalpha(alpha.resize((w, h), Image.BOX))
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(dds_header(rgb.size[0], rgb.size[1], len(levels), b"DXT5", len(levels[0])))
        for lv in levels: f.write(lv)
    os.replace(tmp, path)    # a new inode: never write through a hard link into a stage


def main():
    p = argparse.ArgumentParser()
    p.add_argument("hd"); p.add_argument("photo")
    p.add_argument("--tiles", default="wil:635")
    p.add_argument("--mean", type=float, default=0.23)
    p.add_argument("--relief", type=float, default=0.06)
    a = p.parse_args()
    for item in a.tiles.split(","):
        style, t = item.split(":")
        src = os.path.join(a.hd, style, "tile_%04d.dds" % int(t))
        rgba = np.asarray(Image.open(src).convert("RGBA")).astype(np.float32) / 255.0
        out = iron(rgba, a.mean, a.relief)
        dst_dir = os.path.join(a.photo, style); os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, "tile_%04d.dds" % int(t))
        write_dds(dst, out)
        m = rgba[..., 3] > 0.5
        print("%s tile %s: opaque mean %.1f -> %.1f /255 -> %s" % (style, t, 255 * rgba[..., :3][m].mean(), 255 * out[..., :3][m].mean(), dst))


if __name__ == "__main__":
    main()
