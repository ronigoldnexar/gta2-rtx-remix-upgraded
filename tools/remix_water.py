#!/usr/bin/env python3
"""FIX-REMIX (defect pt-remix-water-matte-no-reflection): the water tiles of the gta2hd
Remix layer as water.

The gta2hd layer is keyed by the HD tiles' top-mip hash (tools/remix_materials.py) and
classified every tile as a surface of the city: the water tiles (608-619, the game's
animated water; tools/make_water_mod.py) came out as a matte stone-like material,
roughness 0.8 from their texture's busy wave highlights, so the harbour read as painted
floor with no sky or lamp in it. This gives every water tile hash of every district one
water material: the tile's own colour, a smooth dielectric (roughness 0.08, Remix's
dielectric Fresnel) and one shared tileable ripple normal map, so the basin and the open
water around the map are the same surface and reflect the sky, facades and lamps.

    remix_water.py <mod dir> --hd assets/textures_hd/wil assets/textures_hd/ste assets/textures_hd/bil

It marks the hashes "water": true in <mod>/pbr.json (remix_materials.py write_usda reads
that, so a regenerated layer keeps them), writes textures/water_ripple.n.rtex.dds, and
rewrites those prims in place in mod.usda and mod_wet.usda (which also hold the car and
sign prims other tools added; a full regeneration would drop them). Never touches the HD
tiles themselves (their hashes are the layer's keys). Needs numpy, Pillow and xxhash.
"""
import argparse, json, os, re, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm

WATER_TILES = range(608, 620)
RIPPLE = "water_ripple.n.rtex.dds"
# The seal: the renderer's one black quad under the world, reaching 512 blocks past the map
# on every side (src/world_mesh.cpp, SealTileIndex in src/renderer.cpp: a 64 px tile of
# 0xFF000000). Past the map's edge it is the open sea the basin looks out on, and as a
# rough black plane it met the basin water in a hard seam. The XXH3 of its texels:
SEAL = "A00D8B41035A6C7F"
# The water tiles' mean colour (tile 608 HD, 70 117 94 sRGB in all three districts), linear.
SEAL_COLOUR = tuple(round(((c / 255 + 0.055) / 1.055) ** 2.4, 4) for c in (70, 117, 94))
SEAL_PRIM = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @{mdl}.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "{mdl}"
                custom color3f inputs:diffuse_color_constant = ({r}, {g}, {b})
                custom asset inputs:normalmap_texture = @./textures/{ripple}@ (
                    colorSpace = "raw"
                )
                custom float inputs:metallic_constant = 0
                custom float inputs:reflection_roughness_constant = 0.08
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
'''


def seal_prim():
    r, g, b = SEAL_COLOUR
    return SEAL_PRIM.format(h=SEAL, mdl=rm.MDL, ripple=RIPPLE, r=r, g=g, b=b)


def ripple_normal(size=512, seed=2026, strength=0.10):
    """A gentle tileable ripple: a few dozen travelling-wave components with whole
    periods across the tile (so it tiles), small amplitude, slopes to a normal."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    h = np.zeros((size, size), np.float32)
    for _ in range(40):
        kx, ky = rng.integers(-9, 10, 2)
        if kx == 0 and ky == 0:
            continue
        k = np.hypot(kx, ky)
        amp = 1.0 / k ** 1.3
        ph = rng.uniform(0, 2 * np.pi)
        h += amp * np.sin(2 * np.pi * (kx * x + ky * y) + ph)
    h /= np.abs(h).max()
    gx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * size
    gy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * size
    s = strength / (2 * np.pi * 4)
    n = np.stack([-gx * s, -gy * s, np.ones_like(h)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def water_prim(h):
    return rm.WATER.format(h=h, mdl=rm.MDL, ripple=RIPPLE)


def patch(path, hashes):
    if not os.path.exists(path):
        return 0
    text = open(path, encoding="utf-8").read()
    n = 0
    for h in hashes:
        rx = re.compile(r' {8}over "mat_%s"\n {8}\{\n.*?\n {8}\}\n' % h, re.S)
        text, k = rx.subn(lambda m: water_prim(h) + "\n", text, count=1)
        n += k
    # The seal: added once, at the head of Looks.
    if 'over "mat_%s"' % SEAL not in text:
        anchor = '    over "Looks"\n    {\n'
        if anchor in text:
            text = text.replace(anchor, anchor + seal_prim(), 1)
            n += 1
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mod")
    ap.add_argument("--hd", nargs="+", required=True)
    a = ap.parse_args()
    hashes = []
    for d in a.hd:
        for t in WATER_TILES:
            p = os.path.join(d, "tile_%04d.dds" % t)
            if os.path.exists(p):
                hashes.append(rm.dds_hash(p))
    hashes = sorted(set(h for h in hashes if h))
    print(f"{len(hashes)} water tile hashes")
    rm.write_normal(os.path.join(a.mod, "textures", RIPPLE), ripple_normal())
    info_path = os.path.join(a.mod, "pbr.json")
    info = json.load(open(info_path)) if os.path.exists(info_path) else {}
    for h in hashes:
        info.setdefault(h, {})["water"] = True
    with open(info_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(info, f, indent=0, sort_keys=True)   # as remix_materials.py writes it
    for name in ("mod.usda", "mod_wet.usda"):
        print(name, patch(os.path.join(a.mod, name), hashes), "prims made water (the seal included)")


if __name__ == "__main__":
    main()
