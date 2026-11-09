#!/usr/bin/env python3
"""Do the gta2hd layer's model-material hashes match what RTX Remix computes at run time?

REMIX-HASH-VERIFY (9 Nov 2026). The layer keys every model texture (cars, props, avatars) as
XXH3-64 of the texels as the renderer uploads them (dll/src/model_store.cpp BaseTextureFor:
one A8R8G8B8 level, BGRA bytes, rows top-down; tools/remix_materials.py remix_hash). That was
checked offline only. This writes a flat-colour probe layer that paints, in one session:

    cyan     every HD tile (top-mip hash, the scheme remix_hash_probe.py proved on 6 Nov): the control
    magenta  every model texture under the layer's scheme (rows top-down, BGRA)
    yellow   the same texels hashed rows bottom-up
    green    the same texels hashed with red and blue swapped (RGBA)
    orange   the same texels hashed with every alpha forced to 255

Run the game under Remix with the layer installed as gta2hd (MODS_HD_SRC). Cyan streets prove
the layer is read; a magenta car proves the model scheme; a car in its own colours while the
streets are cyan means the runtime keys model textures some other way.

    remix_model_hash_probe.py <stage dir> <probe mod dir> [--only REGEX]

`--table out.tsv` also writes texture<TAB>scheme<TAB>hash for every model texture.
Needs numpy and xxhash (host: /mnt/gta2/ab_work/venv/bin/python).
"""
import argparse, os, re, sys
import numpy as np
import xxhash

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import remix_hash_probe as hp

COLOURS = {"tile": (0, 255, 255), "topdown": (255, 0, 255), "bottomup": (255, 255, 0),
           "swapped": (0, 255, 0), "opaque": (255, 128, 0)}


def h64(a):
    return "%016X" % xxhash.xxh3_64_intdigest(np.ascontiguousarray(a).tobytes())


def model_hashes(path):
    raw = open(path, "rb").read()
    if len(raw) < 18 or raw[2] != 2 or raw[16] != 32:
        return None
    w, h = raw[12] | raw[13] << 8, raw[14] | raw[15] << 8
    px = np.frombuffer(raw[18:18 + w * h * 4], np.uint8).reshape(h, w, 4)
    if not raw[17] & 0x20:
        px = px[::-1]   # the renderer uploads rows top-down
    sw = px[..., [2, 1, 0, 3]]
    op = px.copy(); op[..., 3] = 255
    return {"topdown": h64(px), "bottomup": h64(px[::-1]), "swapped": h64(sw), "opaque": h64(op)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", help="a stage folder (gta2dx9_models/, gta2dx9_textures_hd/)")
    ap.add_argument("probe", help="write the probe layer here (mod.usda, textures/)")
    ap.add_argument("--only", default="", help="regex: probe only the model textures whose file name matches")
    ap.add_argument("--table", help="write texture<TAB>scheme<TAB>hash here")
    a = ap.parse_args()
    tex = os.path.join(a.probe, "textures")
    os.makedirs(tex, exist_ok=True)
    for name, rgb in COLOURS.items():
        hp.flat_dds(os.path.join(tex, f"probe_{name}.a.rtex.dds"), rgb)
    seen, body, counts, rows = set(), [], {k: 0 for k in COLOURS}, []

    def add(h, name):
        if h in seen:
            return
        seen.add(h); counts[name] += 1
        body.append(hp.PRIM.format(h=h, mdl=hp.MDL, tex=f"probe_{name}.a.rtex.dds"))

    hd = os.path.join(a.stage, "gta2dx9_textures_hd")
    for root, _, files in os.walk(hd):
        for f in sorted(files):
            if f.endswith(".dds"):
                img = hp.read_dds(os.path.join(root, f))
                if img is not None:
                    add(hp.hashes(img[3])["mip0"], "tile")
    md = os.path.join(a.stage, "gta2dx9_models")
    rx = re.compile(a.only) if a.only else None
    for f in sorted(os.listdir(md)):
        if not f.endswith(".tga") or (rx and not rx.search(f)):
            continue
        hs = model_hashes(os.path.join(md, f))
        if not hs:
            continue
        for scheme in ("topdown", "bottomup", "swapped", "opaque"):
            add(hs[scheme], scheme)
            rows.append((f, scheme, hs[scheme]))
    text = ('#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n'
            + "".join(body) + "    }\n}\n")
    open(os.path.join(a.probe, "mod.usda"), "w", newline="\n").write(text)
    if a.table:
        with open(a.table, "w") as t:
            for r in rows:
                t.write("\t".join(r) + "\n")
    print(f"probe layer {a.probe}: {len(seen)} prims " + ", ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
