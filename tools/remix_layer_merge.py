#!/usr/bin/env python3
"""Merge a chosen set of model prims from one Remix mod layer into another, touching nothing else.

    remix_layer_merge.py <src-layer> <dst-layer> <hashes.txt> [--dry-run]

For each hash in hashes.txt (one 16-digit XXH3 hash per line): copy its <h>.{a,n,m,r,e}.rtex.dds
from <src>/textures into <dst>/textures (the target file is unlinked first, so a hard link into
another layer is never written through), replace or insert its `mat_<h>` prim in <dst>/mod.usda
and <dst>/mod_wet.usda (a model prim is the same in both: the wet layer only swaps tile
roughness), and add the hash to <dst>/model_prims.txt. Every other prim, texture and file in the
destination is left alone, so work other agents did in <dst> survives (unlike re-running
remix_model_materials.py there, which rewrites every model prim). Text files are replaced
atomically (unlink + write via a temp file) so a reader never sees a half-written layer.
"""
import os, re, shutil, sys

PRIM = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)
SUF = ("a", "n", "m", "r", "e")


def atomic_write(path, text):
    tmp = path + ".merge.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    os.replace(tmp, path)          # a new inode: never writes through a hard link


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    src, dst, lst = args
    hashes = [h for h in open(lst).read().split() if h]
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
        for s in SUF:
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
    lp = os.path.join(dst, "model_prims.txt")
    cur = set(open(lp).read().split()) if os.path.exists(lp) else set()
    if not dry: atomic_write(lp, "\n".join(sorted(cur | set(hashes))) + "\n")
    print(("dry run: " if dry else "") + f"{len(hashes)} prims; {stats}; model_prims {len(cur)} -> {len(cur | set(hashes))}")


if __name__ == "__main__":
    main()
