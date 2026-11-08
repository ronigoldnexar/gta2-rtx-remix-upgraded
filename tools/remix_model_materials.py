#!/usr/bin/env python3
"""Remix materials for the 3D car models: clear-coat paint, metal trim, lit lamps.

The renderer uploads every model texture (assets/models/*.tga, 32-bit) as a
single-level A8R8G8B8 managed texture, rows top-down, so Remix names it by the
same XXH3-64 of the BGRA texels as the 64 px world tiles. The importer splits a
car's baked texture into `<name>_N.tga` (everything but the paint) and
`<name>_N_paint.tga` (the paint, alpha-masked, tinted per car at draw time by
the renderer's texture factor). car_bodies.cpp draws the mesh twice, once per
half, each alpha-tested at 128 - and under Remix the second of two draws with
the same geometry and transform is taken as a duplicate of the first, so with
each half's own alpha only one half of the car was path traced (seen 8 Nov:
cars in pieces, a different half from frame to frame). So both prims of a split
pair carry the same opaque material for the whole car: the albedo is the two
halves merged (paint texels from _paint, the rest from _N), and the per-texel
maps give the paint texels the clear coat and the rest the trim classes below.
Whichever draw the runtime keeps, the whole car is drawn, once.

Neither touches the baked textures (the layer holds its own DDS copies):

* paint (`_paint.tga`): the texture as albedo with a clear-coat response.
  AperturePBR has no second specular lobe, so the coat is approximated the way
  a coat reads at a distance: a smooth dielectric (roughness 0.12) with a
  little metal flake (metallic 0.2), i.e. sharp white sky and lamp reflections
  over the coloured paint instead of the paint itself turning mirror-dark.
* trim (`_N.tga`, the rest): per-texel metallic and roughness maps from the
  texel colour: bright neutral texels (bumpers, chrome strips, hubcaps, grille
  bars) chrome (metallic 1, roughness 0.16); mid-grey neutral texels brushed
  metal (0.7 / 0.32); dark blue-grey texels glass (0 / 0.05); near-black
  rubber and seals (0 / 0.6); the rest painted metal (0.15 / 0.4). Saturated
  red texels (tail and brake lamps) get an emissive mask in their own colour,
  so the lamps glow and bloom at night (--lamp-intensity).

    remix_model_materials.py assets/models <mod dir> [--paint-roughness 0.12] [--paint-metallic 0.2]
        [--lamp-intensity 6] [--pattern REGEX] [--preview DIR]

Rewrites the car prims in <mod dir>/mod.usda in place (tile prims untouched),
so it can be re-run after the car models change; run it after
remix_materials.py / remix_emissive.py, which rewrite the whole layer.
--preview writes the albedo / metallic / roughness / emissive maps of each
texture as PNGs for a look at the classification.
"""
import argparse, os, re, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm

HEAD = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
'''
TAIL = '''                custom bool inputs:use_legacy_alpha_state = {legacy_alpha}
                token outputs:out
            }}
        }}
'''
PAINT = HEAD + '''                custom float inputs:metallic_constant = {metallic}
                custom float inputs:reflection_roughness_constant = {roughness}
''' + TAIL
TRIM = HEAD + '''                custom asset inputs:metallic_texture = @./textures/{h}.m.rtex.dds@ (
                    colorSpace = "raw"
                )
                custom asset inputs:reflectionroughness_texture = @./textures/{h}.r.rtex.dds@ (
                    colorSpace = "raw"
                )
{emissive}''' + TAIL
EMISSIVE = '''                custom asset inputs:emissive_mask_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom bool inputs:enable_emission = 1
                custom float inputs:emissive_intensity = {intensity}
'''
PAINT_METALLIC, PAINT_ROUGHNESS = 0.2, 0.12
PRIM = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)


def local_std(lum, vis, r=3):
    """standard deviation of the luminance over a (2r+1)^2 window, over the visible
    texels only (an atlas island's edge against the transparent background is not detail)"""
    def box(a):
        p = np.pad(a, ((r + 1, r), (r + 1, r)), mode="edge").cumsum(0).cumsum(1)
        k = 2 * r + 1
        return p[k:, k:] - p[:-k, k:] - p[k:, :-k] + p[:-k, :-k]
    w = vis.astype(np.float32); n = np.maximum(box(w), 1.0)
    m = box(lum * w) / n
    return np.sqrt(np.maximum(box(lum * lum * w) / n - m * m, 0))


def trim_maps(rgba):
    """metallic, roughness (0..255) and an emissive RGB mask from the texel colours.
    A baked texture cannot tell chrome from white paint by colour alone, so chrome is a
    bright neutral texel in a busy neighbourhood (the baked reflections of a bumper or
    a strip), white paint a bright neutral texel in a smooth one; anything not
    classified is painted body and gets the clear coat."""
    rgb = rgba[..., :3].astype(np.float32) / 255.0
    mx, mn = rgb.max(-1), rgb.min(-1)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    sat = np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0.0)
    busy = local_std(lum, rgba[..., 3] >= 128) > 0.11
    metal = np.full(lum.shape, PAINT_METALLIC, np.float32)
    rough = np.full(lum.shape, PAINT_ROUGHNESS + 0.04, np.float32)
    neutral = sat < 0.14
    chrome = neutral & (lum > 0.45) & busy
    brushed = neutral & (lum > 0.28) & (lum <= 0.45) & busy
    rubber = (mx < 0.11)
    glass = ~rubber & (lum < 0.30) & (rgb[..., 2] >= rgb[..., 0]) & (sat > 0.08) & (sat < 0.6)
    lamp = (rgb[..., 0] > 0.50) & (rgb[..., 1] < 0.32) & (rgb[..., 2] < 0.32) & (sat > 0.55)
    for m, (mt, ro) in ((brushed, (0.7, 0.32)), (chrome, (1.0, 0.16)), (glass, (0.0, 0.05)),
                        (rubber, (0.0, 0.60)), (lamp, (0.0, 0.12))):
        metal[m] = mt; rough[m] = ro
    em = np.zeros(rgba.shape, np.uint8); em[..., 3] = 255
    em[..., :3] = np.where(lamp[..., None], rgba[..., :3], 0)
    vis = rgba[..., 3] >= 128; n = max(int(vis.sum()), 1)
    return (metal * 255).astype(np.uint8), (rough * 255).astype(np.uint8), em, \
        {k: float((v & vis).sum()) / n for k, v in (("chrome", chrome), ("brushed", brushed), ("glass", glass), ("rubber", rubber), ("lamp", lamp))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("mod")
    ap.add_argument("--paint-roughness", "--roughness", type=float, default=0.12)
    ap.add_argument("--paint-metallic", "--metallic", type=float, default=0.2)
    ap.add_argument("--lamp-intensity", type=float, default=6.0)
    ap.add_argument("--pattern", default=r"^\d{3}_.*\.tga$")
    ap.add_argument("--preview", default=None)
    a = ap.parse_args()
    global PAINT_METALLIC, PAINT_ROUGHNESS
    PAINT_METALLIC, PAINT_ROUGHNESS = a.paint_metallic, a.paint_roughness
    tex = os.path.join(a.mod, "textures"); os.makedirs(tex, exist_ok=True)
    usda = os.path.join(a.mod, "mod.usda")
    text = open(usda, encoding="utf-8").read() if os.path.exists(usda) else \
        '#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n    }\n}\n'
    files = sorted(f for f in os.listdir(a.models) if re.match(a.pattern, f))
    # Only the textures some mesh still names (and their paint halves): the
    # importer leaves older parts' textures in the folder when a model changes.
    used = set()
    for m in os.listdir(a.models):
        if m.endswith(".mesh") and re.match(r"^\d{3}_", m):
            for t in re.findall(rb"[\w\-]+\.tga", open(os.path.join(a.models, m), "rb").read()):
                t = t.decode(); used.add(t); used.add(t[:-4] + "_paint.tga")
    files = [f for f in files if f in used]
    have = set(files)
    # Units: a split pair (rest + paint) or a lone texture.
    units = []
    for f in files:
        if f.endswith("_paint.tga"):
            if f[:-10] + ".tga" not in have: units.append((None, f))
        else:
            units.append((f, f[:-4] + "_paint.tga" if f[:-4] + "_paint.tga" in have else None))
    entries = []          # (hash, file, rgba albedo, metal, rough, emissive or None, legacy alpha, kind)
    stats, n = {}, {"pair": 0, "paint": 0, "trim": 0, "lamp": 0}
    for rest, paint in units:
        bgr_r = rm.read_tga(os.path.join(a.models, rest)) if rest else None
        bgr_p = rm.read_tga(os.path.join(a.models, paint)) if paint else None
        if rest and paint and bgr_r.shape == bgr_p.shape:
            r, pt = rm.to_rgba(bgr_r), rm.to_rgba(bgr_p)
            is_paint = pt[..., 3] >= 128
            albedo = np.where(is_paint[..., None], pt, r).copy(); albedo[..., 3] = 255
            metal, rough, em, st = trim_maps(np.concatenate([albedo[..., :3], np.maximum(r[..., 3:], pt[..., 3:])], -1))
            metal[is_paint] = int(PAINT_METALLIC * 255); rough[is_paint] = int(PAINT_ROUGHNESS * 255)
            em[is_paint, :3] = 0
            for f, b in ((rest, bgr_r), (paint, bgr_p)):
                entries.append((rm.remix_hash(b), f, albedo, metal, rough, em, 0, "pair"))
            n["pair"] += 1
        elif paint and not rest:
            entries.append((rm.remix_hash(bgr_p), paint, rm.to_rgba(bgr_p), None, None, None, 1, "paint")); n["paint"] += 1
            continue
        else:
            r = rm.to_rgba(bgr_r)
            metal, rough, em, st = trim_maps(r)
            entries.append((rm.remix_hash(bgr_r), rest, r, metal, rough, em, 1, "trim")); n["trim"] += 1
        for k, v in st.items(): stats[k] = stats.get(k, 0.0) + v
    car = {e[0] for e in entries}
    # Drop every prim this tool wrote before (and the older paint-only ones), keep the tiles.
    kept = [m.group(0) for m in PRIM.finditer(text) if m.group(1) not in car]
    start = text.index('over "Looks"'); start = text.index("{", start) + 2
    head = text[:start]
    prims, seen = [], set()
    for h, f, albedo, metal, rough, em, legacy, kind in sorted(entries, key=lambda e: e[1]):
        if h in seen: continue
        seen.add(h)
        rm.write_albedo(os.path.join(tex, f"{h}.a.rtex.dds"), albedo)
        if metal is None:
            prims.append(PAINT.format(h=h, metallic=a.paint_metallic, roughness=a.paint_roughness, legacy_alpha=legacy))
            continue
        rm.write_roughness(os.path.join(tex, f"{h}.m.rtex.dds"), metal)
        rm.write_roughness(os.path.join(tex, f"{h}.r.rtex.dds"), rough)
        emissive, ep = "", os.path.join(tex, f"{h}.e.rtex.dds")
        if int((em[..., :3].max(-1) > 0).sum()) >= 4:
            rm.write_albedo(ep, em); emissive = EMISSIVE.format(h=h, intensity=a.lamp_intensity); n["lamp"] += 1
        elif os.path.exists(ep):
            os.remove(ep)
        prims.append(TRIM.format(h=h, emissive=emissive, legacy_alpha=legacy))
        if a.preview:
            os.makedirs(a.preview, exist_ok=True)
            row = [Image.fromarray(albedo, "RGBA").convert("RGB"), Image.fromarray(metal, "L").convert("RGB"),
                   Image.fromarray(rough, "L").convert("RGB"), Image.fromarray(em[..., :3], "RGB")]
            w, hh = row[0].size; S = Image.new("RGB", (4 * w, hh))
            for i, im in enumerate(row): S.paste(im, (i * w, 0))
            S.save(os.path.join(a.preview, f[:-4] + "_maps.png"))
    text = head + "\n".join(kept + prims) + "    }\n}\n"
    open(usda, "w", encoding="utf-8", newline="\n").write(text)
    prims_all, refs, problems, _ = rm.validate(a.mod)
    units_n = max(n["pair"] + n["trim"], 1)
    print(f"{n['pair']} split pairs (both prims one opaque whole-car material), {n['trim']} lone trim textures, "
          f"{n['paint']} lone paint textures; {n['lamp']} prims with lamp emission {a.lamp_intensity}; paint metallic "
          f"{a.paint_metallic} roughness {a.paint_roughness}; {len(kept)} other prims kept, {len(prims_all)} in the layer; "
          "mean trim class shares: " + ", ".join(f"{k} {v / units_n:.3f}" for k, v in stats.items())
          + f"; validation: {'ok' if not problems else problems[:5]}")


if __name__ == "__main__":
    main()
