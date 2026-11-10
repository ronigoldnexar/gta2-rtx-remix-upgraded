#!/usr/bin/env python3
"""FIX-REMIX-MATERIALS-8 (prx2): Remix prims for the flat rooftop sign plates (wil tiles 61-63: the round atom disc, FUTURO
RADIO), which stand in the street views as double-sided plates in full sun.

As plain wall tiles their prims were a matte pale plate (albedo ~200,205,215, roughness 0.8) that the street exposure
clipped to a cream decal at noon, with nothing of a lit sign at night. Here, per tile:
- the plate (pale, unsaturated texels) becomes painted sheet metal: albedo scaled down to PLATE_LUM (sRGB of its
  brightest texels), roughness PLATE_ROUGH, metallic PLATE_METAL, so by day it carries the sky's reflection instead
  of a flat clipped white;
- the sign's coloured strokes (saturated, bright: the yellow atom orbits) keep their colour and get an emissive mask in
  that colour at EMIT_INTENSITY: a lit sign, day and night (FIX-REMIX-NIGHT-7's floodlight lights the plate at night).
The alpha (the plate's cut-out) is kept. Writes <h>.a / .e DDS into <mod>/textures and the prims as text to stdout
(paste over the tiles' old prims in mod.usda and mod_wet.usda, or let --apply do it).

    remix_sign_plates.py <mod-layer> <hd tile.dds> [...] [--apply]
"""
import os, re, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm

PLATE_LUM = 150.0      # sRGB of the plate's brightest texels (was ~215)
PLATE_ROUGH = 0.38
PLATE_METAL = 0.55
EMIT_INTENSITY = 4.0

PRIM = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom asset inputs:normalmap_texture = @./textures/{h}.n.rtex.dds@ (
                    colorSpace = "raw"
                )
                custom float inputs:metallic_constant = {metal}
                custom float inputs:reflection_roughness_constant = {rough}
                custom asset inputs:emissive_mask_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom bool inputs:enable_emission = 1
                custom float inputs:emissive_intensity = {gain}
                custom bool inputs:use_legacy_alpha_state = 1
                token outputs:out
            }}
        }}
'''


def maps(rgba):
    a = rgba.astype(np.float32)
    rgb = a[..., :3] / 255.0
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    vis = a[..., 3] >= 128
    stroke = vis & (sat > 0.45) & (mx > 0.55)
    plate = vis & ~stroke & (sat < 0.25) & (lum > 0.45)
    out = a.copy()
    if plate.any():
        top = np.percentile(a[..., :3][plate].max(-1), 98)
        k = min(1.0, PLATE_LUM / max(top, 1.0))
        # pull the plate down smoothly (texels darker than the plate keep more of their value)
        w = np.clip((lum - 0.35) / 0.2, 0, 1)[..., None] * plate[..., None]
        out[..., :3] = a[..., :3] * (1 - w) + a[..., :3] * k * w
    em = np.zeros(a.shape[:2] + (4,), np.float32); em[..., 3] = 255
    em[..., :3][stroke] = a[..., :3][stroke]
    return out, em, float(plate.mean()), float(stroke.mean())


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    mod, tiles = args[0], args[1:]
    tex = os.path.join(mod, "textures")
    prims = {}
    for t in tiles:
        h = str(rm.dds_hash(t)).upper()
        rgba = np.asarray(Image.open(t).convert("RGBA"))
        alb, em, pf, sf = maps(rgba)
        for suf, img in (("a", alb), ("e", em)):
            p = os.path.join(tex, f"{h}.{suf}.rtex.dds")
            if os.path.lexists(p): os.unlink(p)        # never write through a hard link
            rm.write_albedo(p, img)
        if not os.path.exists(os.path.join(tex, f"{h}.n.rtex.dds")): sys.exit(f"{h}: no normal map in {tex}")
        prims[h] = PRIM.format(h=h, metal=PLATE_METAL, rough=PLATE_ROUGH, gain=EMIT_INTENSITY)
        print(f"# {os.path.basename(t)} {h}: plate {pf:.3f}, strokes {sf:.3f} of the texels", file=sys.stderr)
    if "--apply" in sys.argv:
        pat = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)
        for u in ("mod.usda", "mod_wet.usda"):
            p = os.path.join(mod, u); s = open(p, encoding="utf-8").read(); n = 0
            def sub(m):
                nonlocal n
                if m.group(1) in prims: n += 1; return prims[m.group(1)]
                return m.group(0)
            s = pat.sub(sub, s)
            tmp = p + ".tmp"; open(tmp, "w", encoding="utf-8", newline="\n").write(s); os.replace(tmp, p)
            print(f"{u}: {n} prims replaced", file=sys.stderr)
    else:
        for v in prims.values(): sys.stdout.write(v)


if __name__ == "__main__":
    main()
