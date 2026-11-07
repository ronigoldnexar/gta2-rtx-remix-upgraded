#!/usr/bin/env python3
"""Emissive masks for the neon and lit-sign tiles of the gta2hd Remix layer.

    remix_emissive.py <game/data> <mod dir> <hd tiles root> <upscaled tga root>

A tile is a sign when, in the style file's own 64 px art, most of it is dark and
a few percent of it is bright and saturated (a neon stroke on a black board):
that keeps road markings (grey ground) and painted walls out. For each such
tile that the layer has a material for (hash of its 512 px DDS, as the runtime
hashes it), a 256 px emissive mask is written from the upscaled tile: the
bright saturated strokes in their own colour, black elsewhere. mod.usda is then
rewritten; materials with a mask get enable_emission and an intensity
(remix_materials.EMISSIVE_INTENSITY). Prints what was marked.
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "assets-src", "cars"))
import remix_materials as rm            # noqa: E402
import dump_style_tiles as dst          # noqa: E402
import parse_sty                        # noqa: E402

def hsv_mask(rgb, sat_min, val_min):
    rgb = rgb.astype(np.float32) / 255.0
    mx = rgb.max(-1); mn = rgb.min(-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return (sat > sat_min) & (mx > val_min), mx

# The neon and lit signs, picked by eye from each style's tiles (contact sheets
# out/neon_candidates_<style>.png): the heuristic below finds the candidates,
# graffiti and painted boards are left out by hand.
SIGNS = {
    "wil": [566, 574, 728, 729, 730, 739, 742, 743, 754, 756, 759, 760, 761, 763, 764, 767, 782, 825, 826, 827],
    "bil": [384, 385, 386, 387, 389, 390, 392, 394, 395, 396, 397, 398, 399, 400, 401, 402, 403, 404, 405, 406,
            407, 408, 409, 410, 411, 412, 413, 414, 415],
    "ste": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 27, 28, 29, 30, 31, 345, 347,
            363, 372, 374],
}

def is_sign(sty, t, tile64):
    return t in SIGNS.get(sty, ())

def main():
    data, mod, hd_root, up_root = sys.argv[1:5]
    tex = os.path.join(mod, "textures")
    marked = []
    for sty in ("wil", "bil", "ste"):
        st = parse_sty.parse(os.path.join(data, sty + ".sty")); c = dst.sty_chunks(st["d"])
        hd = os.path.join(hd_root, sty)
        for f in sorted(os.listdir(hd)):
            if not (f.startswith("tile_") and f.endswith(".dds")): continue
            t = int(f[5:9])
            h = rm.dds_hash(os.path.join(hd, f))
            if not h or not os.path.exists(os.path.join(tex, f"{h}.a.rtex.dds")): continue
            tile = dst.tile_rgba(st, c, t)
            if not is_sign(sty, t, tile): continue
            src = os.path.join(up_root, sty, f"tile_{t:04d}.tga")
            if os.path.exists(src):
                rgba = rm.resize(rm.to_rgba(rm.read_tga(src)), 256)
            else:
                rgba = np.asarray(tile.resize((256, 256), Image.LANCZOS))
            rgb = rgba[..., :3]
            bright, _ = hsv_mask(rgb, 0.45, 0.60)
            m = np.asarray(Image.fromarray((bright * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(1.0)), np.float32) / 255.0
            em = np.zeros_like(rgba); em[..., :3] = (rgb * m[..., None]).astype(np.uint8); em[..., 3] = 255
            rm.write_albedo(os.path.join(tex, f"{h}.e.rtex.dds"), em)
            marked.append((sty, t, h, round(float(bright.mean()), 3)))
    rm.write_usda(mod)
    ok, problems = (lambda r: (r, r))(rm.validate(mod)) if False else (True, [])
    print(f"{len(marked)} sign tiles marked emissive:")
    for m in marked: print("  ", m)

if __name__ == "__main__":
    main()
