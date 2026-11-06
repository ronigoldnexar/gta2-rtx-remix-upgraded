#!/usr/bin/env python3
"""Remix materials for the 3D models' textures: car paint as glossy metal.

The renderer uploads every model texture (assets/models/*.tga, 32-bit) as a
single-level A8R8G8B8 managed texture, rows top-down, so Remix names it by the
same XXH3-64 of the BGRA texels as the 64 px world tiles. The importer splits a
car's baked texture into `<name>_N.tga` (everything but the paint) and
`<name>_N_paint.tga` (the paint, alpha-masked, tinted per car at draw time by
the renderer's texture factor, which Remix keeps). This writes, into an existing
mod folder, one AperturePBR_Opacity prim per paint texture with the texture
itself as albedo (BC3, mips) and a glossy metallic-paint response, so cars read
as painted metal under the path tracer instead of the legacy matte default.

    remix_model_materials.py assets/models <mod dir> [--roughness 0.3] [--metallic 0.6]

Appends to the mod's mod.usda (regenerated from textures/ by remix_materials.write_usda,
so run this after the tile pass; the paint prims carry their own constants).
"""
import argparse, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_materials as rm

PAINT = '''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom asset inputs:diffuse_texture = @./textures/{h}.a.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom float inputs:metallic_constant = {metallic}
                custom float inputs:reflection_roughness_constant = {roughness}
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models")
    ap.add_argument("mod")
    ap.add_argument("--roughness", type=float, default=0.3)
    ap.add_argument("--metallic", type=float, default=0.6)
    ap.add_argument("--pattern", default=r"^\d{3}_.*_paint\.tga$")
    a = ap.parse_args()
    tex = os.path.join(a.mod, "textures"); os.makedirs(tex, exist_ok=True)
    usda = os.path.join(a.mod, "mod.usda")
    text = open(usda, encoding="utf-8").read() if os.path.exists(usda) else \
        '#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n    }\n}\n'
    have = set(re.findall(r'over "mat_([0-9A-F]{16})"', text))
    prims, made = [], 0
    for f in sorted(os.listdir(a.models)):
        if not re.match(a.pattern, f):
            continue
        bgra = rm.read_tga(os.path.join(a.models, f))
        h = rm.remix_hash(bgra)
        if h in have:
            continue
        have.add(h)
        if not os.path.exists(os.path.join(tex, f"{h}.a.rtex.dds")):
            rm.write_albedo(os.path.join(tex, f"{h}.a.rtex.dds"), rm.to_rgba(bgra))
        prims.append(PAINT.format(h=h, metallic=a.metallic, roughness=a.roughness))
        made += 1
    marker = "    }\n}\n"
    assert text.endswith(marker)
    text = text[:-len(marker)] + "".join(prims) + marker
    open(usda, "w", encoding="utf-8", newline="\n").write(text)
    print(f"{made} paint materials added (roughness {a.roughness}, metallic {a.metallic}); {len(have)} prims in the layer")


if __name__ == "__main__":
    main()
