# on the 6000: the three emissive kit materials into a copy of the shipped gta2hd layer (no numpy there: the hashes
# come from remix_nopom.py emissive on Tokyo)
import os, shutil, sys
layer, tex = sys.argv[1], sys.argv[2]
H = ["98BF5CEAA644B8E4", "3ACCCEF98A4E9C9D", "64DB03E3625A6BCC"]
ent = ""
for h in H:
    d = os.path.join(layer, "textures", f"{h}.e.rtex.dds")
    if os.path.lexists(d): os.unlink(d)
    shutil.copyfile(os.path.join(tex, f"{h}.e.rtex.dds"), d)
    ent += f'''        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @AperturePBR_Opacity.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "AperturePBR_Opacity"
                custom asset inputs:diffuse_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom float inputs:reflection_roughness_constant = 0.6
                custom asset inputs:emissive_mask_texture = @./textures/{h}.e.rtex.dds@ (
                    colorSpace = "sRGB"
                )
                custom bool inputs:enable_emission = 1
                custom float inputs:emissive_intensity = 8
                token outputs:out
            }}
        }}
'''
for n in ("mod.usda", "mod_wet.usda"):
    p = os.path.join(layer, n)
    if not os.path.exists(p): continue
    t = open(p).read()
    if "DISTRICTS emissive" in t: continue
    a = '    over "Looks"\n    {\n'
    t = t.replace(a, a + "        # DISTRICTS emissive: the facade kit's lit signs and neon\n" + ent, 1)
    os.unlink(p); open(p, "w").write(t)
    print(n, "emissive entries added")
