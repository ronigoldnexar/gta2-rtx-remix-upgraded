#!/usr/bin/env python3
"""DISTRICTS: under RTX Remix, no facade parallax (QB-25 displacement) on the tiles the facade kit recesses: the kit's
skin already stands those walls out and cuts real openings, so the parallax would recess the windows a second time.

    remix_nopom.py hashes <hd root> <out.json> <lvl>:<kit file> [...]   tile hashes (Remix: XXH3 of the top mip) of
                                                                         every style tile a kit draws its skin with
    remix_nopom.py patch <hashes.json> <layer dir>                       in mod.usda / mod_wet.usda of a layer copy:
                                                                         drop height_texture, displace_in = 0 for those
    remix_nopom.py emissive <kit dir> <layer dir>                        round 6: the kit's lit sign and neon textures
                                                                         (kit_NN.dds of the "_lit" materials) as
                                                                         emissive materials in mod.usda / mod_wet.usda
The patch unlinks before writing (safe on a hard-link copy of the shipped layer). Deterministic."""
import json, os, re, struct, sys


def kit_tiles(path):
    data = open(path, "rb").read()
    ng = struct.unpack_from("<I", data, 8)[0]
    p, tiles = 12, set()
    for _ in range(ng):
        tile, flags, nv, ni = struct.unpack_from("<iIII", data, p)
        p += 16 + nv * 32 + ni * 4
        if tile >= 0:
            tiles.add(tile)
    return tiles


def main():
    if sys.argv[1] == "emissive":
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import remix_materials as rmat, shutil
        from kit import KIT
        kd, layer = sys.argv[2], sys.argv[3]
        entries = []
        for k, name in enumerate(KIT):
            if not name.endswith("_lit"):
                continue
            src = os.path.join(kd, f"kit_{k:02d}.dds")
            h = rmat.dds_hash(src)
            if not h:
                continue
            dst = os.path.join(layer, "textures", f"{h}.e.rtex.dds")
            if os.path.lexists(dst): os.unlink(dst)
            shutil.copyfile(src, dst)
            entries.append(f"""        over "mat_{h}"
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
""")
            print(f"{name}: kit_{k:02d}.dds -> mat_{h} (emissive)")
        for name in ("mod.usda", "mod_wet.usda"):
            path = os.path.join(layer, name)
            if not os.path.exists(path): continue
            t = open(path).read()
            if "DISTRICTS emissive" in t: continue
            anchor = '    over "Looks"\n    {\n'
            assert anchor in t, name
            t = t.replace(anchor, anchor + "        # DISTRICTS emissive: the facade kit's lit signs and neon\n" + "".join(entries), 1)
            os.unlink(path); open(path, "w").write(t)
            print(f"{name}: {len(entries)} emissive kit materials")
        return
    if sys.argv[1] == "hashes":
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        import remix_materials as rmat
        hd, out = sys.argv[2], sys.argv[3]
        res = {}
        for spec in sys.argv[4:]:
            lvl, kp = spec.split(":", 1)
            for t in sorted(kit_tiles(kp)):
                h = rmat.dds_hash(os.path.join(hd, lvl, f"tile_{t:04d}.dds"))
                if h:
                    res[h] = f"{lvl}:{t}"
        json.dump(res, open(out, "w"), indent=0, sort_keys=True)
        print(f"{len(res)} tile hashes -> {out}")
    else:
        hashes = json.load(open(sys.argv[2]))
        for name in ("mod.usda", "mod_wet.usda"):
            path = os.path.join(sys.argv[3], name)
            if not os.path.exists(path):
                continue
            text = open(path, encoding="utf-8").read()
            parts = re.split(r'(?m)^(        over "mat_[0-9A-F]{16}"\n)', text)
            out, n = [parts[0]], 0
            for i in range(1, len(parts), 2):
                head, body = parts[i], parts[i + 1]
                if head.split('"mat_')[1][:16] in hashes and "displace_in" in body:
                    body = re.sub(r'(?m)^ *custom asset inputs:height_texture = @[^@]*@ \(\n[^\n]*\n *\)\n', "", body)
                    body = re.sub(r'(?m)^( *custom float inputs:displace_in = )[^\n]*\n', r"\g<1>0\n", body)
                    n += 1
                out += [head, body]
            os.unlink(path)
            open(path, "w", encoding="utf-8", newline="\n").write("".join(out))
            print(f"{name}: parallax dropped on {n} kit tiles")


if __name__ == "__main__":
    main()
