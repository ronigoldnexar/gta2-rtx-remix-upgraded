#!/usr/bin/env python3
"""Merge a chosen set of model prims from one Remix mod layer into another, touching nothing else.

    remix_layer_merge.py <src-layer> <dst-layer> <hashes.txt> [--dry-run] [--tiles]

For each hash in hashes.txt (one 16-digit XXH3 hash per line): copy its <h>.{a,n,m,r,e}.rtex.dds
from <src>/textures into <dst>/textures (the target file is unlinked first, so a hard link into
another layer is never written through), replace or insert its `mat_<h>` prim in <dst>/mod.usda
and <dst>/mod_wet.usda (a model prim is the same in both: the wet layer only swaps tile
roughness), and add the hash to <dst>/model_prims.txt. Every other prim, texture and file in the
destination is left alone, so work other agents did in <dst> survives (unlike re-running
remix_model_materials.py there, which rewrites every model prim). Text files are replaced
atomically (unlink + write via a temp file) so a reader never sees a half-written layer.

--tiles (REMIX-MATERIALS): the hashes are tile prims (remix_materials.py --dds-tiles
--only-classed into a scratch layer): their height (.h) and wet roughness (.w) maps are
copied or removed too, mod_wet.usda takes the source's wet prim (it differs for tiles), the
hashes' pbr.json entries are copied, and model_prims.txt is left alone. A tile whose
destination prim is special (FIX-REMIX's water, the sign emission, QB-25's facade depth)
is skipped with a note: those passes own that prim.
"""
import os, re, shutil, sys

PRIM = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)
SUF = ("a", "n", "m", "r", "e")
TILE_SUF = ("a", "n", "m", "r", "h", "w")
SPECIAL = ("water_ripple", "emissive_mask_texture", "facade")


def atomic_write(path, text):
    tmp = path + ".merge.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    os.replace(tmp, path)          # a new inode: never writes through a hard link


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    tiles = "--tiles" in sys.argv
    src, dst, lst = args
    hashes = [h for h in open(lst).read().split() if h]
    if tiles:
        dtext = open(os.path.join(dst, "mod.usda"), encoding="utf-8").read()
        dblocks = {m.group(1): m.group(0) for m in PRIM.finditer(dtext)}
        import json
        dj = os.path.join(dst, "pbr.json")
        dinf = json.load(open(dj)) if os.path.exists(dj) else {}
        skip = [h for h in hashes if (h in dblocks and any(k in dblocks[h] for k in SPECIAL))
                or any(k in dinf.get(h, {}) for k in ("water", "facade"))]
        if skip: print(f"skipped {len(skip)} tiles with a special prim in the destination: {skip[:6]}")
        hashes = [h for h in hashes if h not in skip]
    stats = {"tex_copied": 0, "tex_removed": 0, "replaced": 0, "inserted": 0}
    for name in ("mod.usda", "mod_wet.usda"):
        sp, dp = os.path.join(src, name), os.path.join(dst, name)
        sblocks = {m.group(1): m.group(0) for m in PRIM.finditer(open(sp, encoding="utf-8").read())}
        text = open(dp, encoding="utf-8").read()
        have = {m.group(1) for m in PRIM.finditer(text)}
        for h in hashes:
            if h not in sblocks: sys.exit(f"{h} has no prim in {sp}")
            if h in have:
                text = PRIM.sub(lambda m: sblocks[h] if m.group(1) == h else m.group(0), text); stats["replaced"] += 1
            else:
                end = text.rindex("    }\n}\n")         # close of `over "Looks"`
                text = text[:end] + sblocks[h] + text[end:]; stats["inserted"] += 1
        if not dry: atomic_write(dp, text)
    for h in hashes:
        for s in (TILE_SUF if tiles else SUF):
            sf = os.path.join(src, "textures", f"{h}.{s}.rtex.dds")
            df = os.path.join(dst, "textures", f"{h}.{s}.rtex.dds")
            if os.path.exists(sf):
                if not dry:
                    if os.path.lexists(df): os.remove(df)
                    shutil.copyfile(sf, df)
                stats["tex_copied"] += 1
            elif os.path.lexists(df):
                if not dry: os.remove(df)
                stats["tex_removed"] += 1
    if tiles:
        import json
        sj, dj = os.path.join(src, "pbr.json"), os.path.join(dst, "pbr.json")
        sinfo = json.load(open(sj)) if os.path.exists(sj) else {}
        dinfo = json.load(open(dj)) if os.path.exists(dj) else {}
        for h in hashes:
            if h in sinfo: dinfo[h] = sinfo[h]
        if not dry: atomic_write(dj, json.dumps(dinfo, indent=0, sort_keys=True))
        print(("dry run: " if dry else "") + f"{len(hashes)} tile prims; {stats}")
        return
    lp = os.path.join(dst, "model_prims.txt")
    cur = set(open(lp).read().split()) if os.path.exists(lp) else set()
    if not dry: atomic_write(lp, "\n".join(sorted(cur | set(hashes))) + "\n")
    print(("dry run: " if dry else "") + f"{len(hashes)} prims; {stats}; model_prims {len(cur)} -> {len(cur | set(hashes))}")


if __name__ == "__main__":
    main()
