#!/usr/bin/env python3
"""Which bytes does RTX Remix hash for a block-compressed HD tile?

The runtime names a material by XXH3-64 of the texture data the game uploads.
For the 64x64 A8R8G8B8 tiles that is the texel bytes (tools/remix_materials.py);
for the 512 px DXT tiles of assets/textures_hd the renderer uploads a mip chain
(src/renderer.cpp CreateDdsTexture), so the hash could cover the top mip only
or every level. This script computes both candidates for every DDS of a set and
writes a probe layer that paints the two candidates in different flat colours:

    remix_hash_probe.py <dds dir> [<dds dir>...] --probe <mod dir>

Run the game under Remix with that layer: magenta walls mean the top mip is
hashed, cyan means the whole chain. `--table out.tsv` writes tile, both hashes.
`--scheme mip0|all` prints the chosen hash per tile for other tools.
"""
import argparse, os, struct, sys
import xxhash

PROBE_COLOURS = {"mip0": (255, 0, 255), "all": (0, 255, 255)}
MDL = "AperturePBR_Opacity"
PRIM = """        over "mat_{h}"
        {{
            over "Shader"
            {{
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @{mdl}.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "{mdl}"
                custom asset inputs:diffuse_texture = @./textures/{tex}@ (
                    colorSpace = "sRGB"
                )
                custom float inputs:metallic_constant = 0
                custom float inputs:reflection_roughness_constant = 0.8
                custom bool inputs:use_legacy_alpha_state = 0
                token outputs:out
            }}
        }}
"""


def read_dds(path):
    b = open(path, "rb").read()
    if b[:4] != b"DDS ":
        return None
    flags, h, w = struct.unpack_from("<III", b, 8)
    mips = struct.unpack_from("<I", b, 28)[0] if flags & 0x20000 else 1
    fourcc = b[84:88]
    bpb = {b"DXT1": 8, b"DXT5": 16}.get(fourcc)
    if bpb is None:
        return None
    levels, off = [], 128
    for i in range(max(1, mips)):
        lw, lh = max(1, w >> i), max(1, h >> i)
        n = ((lw + 3) // 4) * ((lh + 3) // 4) * bpb
        levels.append(b[off:off + n])
        off += n
    return w, h, fourcc, levels


def hashes(levels):
    return {"mip0": "%016X" % xxhash.xxh3_64_intdigest(levels[0]),
            "all": "%016X" % xxhash.xxh3_64_intdigest(b"".join(levels))}


def flat_dds(path, rgb, size=16):
    """A solid-colour DXT1 texture with a full mip chain."""
    r, g, b = rgb
    c565 = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    block = struct.pack("<HHI", c565, c565, 0)
    data, w = [], size
    while True:
        data.append(block * (((w + 3) // 4) ** 2))
        if w == 1:
            break
        w = max(1, w // 2)
    header = struct.pack("<7I44x", 124, 0xA1007, size, size, len(data[0]), 0, len(data))
    pixfmt = struct.pack("<2I4s5I", 32, 0x4, b"DXT1", 0, 0, 0, 0, 0)
    caps = struct.pack("<5I", 0x401008, 0, 0, 0, 0)
    open(path, "wb").write(b"DDS " + header + pixfmt + caps + b"".join(data))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dds_dirs", nargs="+")
    ap.add_argument("--probe", help="write a flat-colour probe layer here")
    ap.add_argument("--table", help="write tile<TAB>mip0<TAB>all here")
    ap.add_argument("--scheme", choices=["mip0", "all"], help="print tile<TAB>hash for one scheme")
    a = ap.parse_args()
    rows = []
    for d in a.dds_dirs:
        for f in sorted(os.listdir(d)):
            if not f.endswith(".dds"):
                continue
            img = read_dds(os.path.join(d, f))
            if img is None:
                continue
            hs = hashes(img[3])
            rows.append((os.path.basename(d.rstrip("/")) + "/" + f, hs))
    if a.table:
        with open(a.table, "w") as t:
            for name, hs in rows:
                t.write(f"{name}\t{hs['mip0']}\t{hs['all']}\n")
    if a.scheme:
        for name, hs in rows:
            print(f"{name}\t{hs[a.scheme]}")
    if a.probe:
        tex = os.path.join(a.probe, "textures")
        os.makedirs(tex, exist_ok=True)
        for scheme, rgb in PROBE_COLOURS.items():
            flat_dds(os.path.join(tex, f"probe_{scheme}.a.rtex.dds"), rgb)
        seen, body = set(), []
        for name, hs in rows:
            for scheme in PROBE_COLOURS:
                h = hs[scheme]
                if h in seen:
                    continue
                seen.add(h)
                body.append(PRIM.format(h=h, mdl=MDL, tex=f"probe_{scheme}.a.rtex.dds"))
        text = ('#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n'
                + "".join(body) + "    }\n}\n")
        open(os.path.join(a.probe, "mod.usda"), "w", newline="\n").write(text)
        print(f"probe layer: {len(rows)} tiles, {len(seen)} prims, colours {PROBE_COLOURS}")
    print(f"{len(rows)} DDS tiles hashed", file=sys.stderr)


if __name__ == "__main__":
    main()
