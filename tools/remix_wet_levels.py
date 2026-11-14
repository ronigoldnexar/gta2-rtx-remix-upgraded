#!/usr/bin/env python3
"""WEATHER-V2 C: stepped wet materials for the road and pavement tiles under RTX Remix.

The renderer draws a road/pavement lid tile with a wet variant of its street-view texture at wetness
levels 1-3 (damp, wet, soaked): the same texels with one byte of the uploaded top mip changed, so Remix
keys a material of its own. The DLL logs each variant ("wet variant: tile T level K DRY -> WET", once for
every tile with [devtools] wx_wet_manifest=1). This tool reads those lines and writes, for every dry hash
that has a material in the layer, one prim per level: the dry prim with its roughness map replaced by a
level map blended from the dry roughness (.r) toward the wet one (.w, or 0.4 x .r where none was made).

  python3 tools/remix_wet_levels.py <gta2dx9.log | manifest>... --mod <gta2hd dir> --out <new gta2hd dir>
  python3 tools/remix_wet_levels.py <logs | manifest>... --merge <layer dir> [--tex-out <dir>] [--manifest-out <file>]

--out: a new folder hard-linking every file of --mod except mod.usda, which it rewrites with the wet prims
appended, and adds textures/<DRY>.wK.rtex.dds (a private test layer).
--merge (the release pipeline, after remix_materials.py / remix_layer_merge.py): the wet prims are inserted into
<layer>/mod.usda and <layer>/mod_wet.usda in place (a prim of the same hash is replaced, every other line is left
alone; text written atomically), the level maps go to --tex-out (default <layer>/textures; a deploy bundle's
textures/ folder when the shared layer must not be written), dry roughness read from --tex-src (default <layer>/textures).
--manifest-out writes the variant pairs found (hashes only, no artwork) in the DLL's log-line format, so the
committed tools/remix_wet_manifest.txt can stand in for the logs. The manifest comes from Remix runs with
[weather] enabled at level load in every district (the DLL logs each variant as it makes it).
Needs numpy and Pillow (remix_materials' writers; xxhash is not needed)."""
import argparse, os, re, shutil, struct, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import xxhash  # noqa: F401  (remix_materials imports it; this tool takes its hashes from the DLL's manifest)
except ImportError:
    import types
    sys.modules["xxhash"] = types.ModuleType("xxhash")
import remix_materials as rm

LEVEL_T = {1: 0.35, 2: 0.70, 3: 1.00}   # damp, wet, soaked: how far toward the wet roughness

def bc4_decode(path):
    """The top mip of a BC4U DDS as a 0..255 float array."""
    b = open(path, "rb").read()
    h, w = struct.unpack_from("<II", b, 12)
    bw, bh = (w + 3) // 4, (h + 3) // 4
    blk = np.frombuffer(b, np.uint8, bw * bh * 8, 128).reshape(bh, bw, 8).astype(np.int32)
    a0, a1 = blk[..., 0], blk[..., 1]
    bits = np.zeros((bh, bw), np.uint64)
    for i in range(6): bits |= blk[..., 2 + i].astype(np.uint64) << np.uint64(8 * i)
    idx = np.stack([((bits >> np.uint64(3 * i)) & np.uint64(7)).astype(np.int32) for i in range(16)], -1)
    pal = np.zeros((bh, bw, 8), np.float32)
    pal[..., 0], pal[..., 1] = a0, a1
    big = a0 > a1
    for k in range(1, 7):
        pal[..., 1 + k] = np.where(big, ((7 - k) * a0 + k * a1) / 7.0, pal[..., 1 + k])
    for k in range(1, 5):
        pal[..., 1 + k] = np.where(~big, ((5 - k) * a0 + k * a1) / 5.0, pal[..., 1 + k])
    pal[..., 6] = np.where(~big, 0, pal[..., 6]); pal[..., 7] = np.where(~big, 255, pal[..., 7])
    vals = np.take_along_axis(pal, idx, -1)            # (bh, bw, 16)
    return vals.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)[:h, :w]

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--mod")
    ap.add_argument("--out")
    ap.add_argument("--merge")
    ap.add_argument("--tex-out")
    ap.add_argument("--tex-src")
    ap.add_argument("--manifest-out")
    a = ap.parse_args()
    if not (a.merge or (a.mod and a.out)): ap.error("--mod and --out, or --merge")
    pairs = {}
    for lp in a.logs:
        for line in open(lp, encoding="latin-1", errors="replace"):
            m = re.search(r"wet variant: tile (\d+) level (\d) ([0-9A-F]{16}) -> ([0-9A-F]{16})", line)
            if m: pairs[(m[3], int(m[2]))] = m[4]
    tiles = {}
    for lp in a.logs:
        for line in open(lp, encoding="latin-1", errors="replace"):
            m = re.search(r"wet variant: tile (\d+) level (\d) ([0-9A-F]{16}) -> ([0-9A-F]{16})", line)
            if m: tiles[(m[3], int(m[2]))] = int(m[1])
    if a.manifest_out:
        with open(a.manifest_out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# WEATHER-V2 wet road variants: tile, level, dry texture hash -> wet variant hash (tools/remix_wet_levels.py)\n")
            for (dry, k), wet in sorted(pairs.items(), key=lambda kv: (tiles[kv[0]], kv[0][1])):
                f.write(f"wet variant: tile {tiles[(dry, k)]} level {k} {dry} -> {wet}\n")
    if a.merge:
        return merge(a, pairs)
    text = open(os.path.join(a.mod, "mod.usda"), encoding="utf-8").read()
    prims = {m.group(1): m for m in re.finditer(r'(?ms)^        over "mat_([0-9A-F]{16})"\n        \{.*?^        \}\n', text)}
    os.makedirs(os.path.join(a.out, "textures"), exist_ok=True)
    for root, _, files in os.walk(a.mod):
        rel = os.path.relpath(root, a.mod)
        os.makedirs(os.path.join(a.out, rel), exist_ok=True)
        for f in files:
            if rel == "." and f.startswith("mod"): continue
            dst = os.path.join(a.out, rel, f)
            if not os.path.exists(dst): os.link(os.path.join(root, f), dst)
    tex = os.path.join(a.mod, "textures")
    added, missing, made = [], 0, 0
    for (dry, k), wet in sorted(pairs.items()):
        if dry not in prims: missing += 1; continue
        r_path = os.path.join(tex, f"{dry}.r.rtex.dds")
        if not os.path.exists(r_path): missing += 1; continue
        out_name = f"{dry}.w{k}.rtex.dds"
        out_path = os.path.join(a.out, "textures", out_name)
        if not os.path.exists(out_path):
            r = bc4_decode(r_path)
            w_path = os.path.join(tex, f"{dry}.w.rtex.dds")
            w = bc4_decode(w_path) if os.path.exists(w_path) else np.clip(r * 0.4, 12, 255)
            rm.write_roughness(out_path, r + (w - r) * LEVEL_T[k]); made += 1
        block = prims[dry].group(0).replace(f'mat_{dry}', f'mat_{wet}', 1)
        block = block.replace(f"./textures/{dry}.r.rtex.dds", f"./textures/{out_name}")
        added.append(block)
    body = text.rstrip()
    assert body.endswith("}\n}") or body.endswith("}\n}".replace("\n", "\n")), "unexpected mod.usda tail"
    head = body[:body.rstrip().rfind("}")].rstrip()
    head = head[:head.rfind("}")]           # inside "Looks"
    new = head + "".join("\n" + b for b in added) + "    }\n}\n"
    open(os.path.join(a.out, "mod.usda"), "w", encoding="utf-8", newline="\n").write(new)
    print(f"wet levels: {len(pairs)} variants in the logs, {len(added)} prims added, {made} roughness maps written, "
          f"{missing} without a dry material")

PRIM_RE = r'(?ms)^        over "mat_([0-9A-F]{16})"\n        \{.*?^        \}\n'

def atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f: f.write(text)
    if os.path.lexists(path): os.unlink(path)
    os.rename(tmp, path)

def insert_prims(text, blocks):
    """Replace prims whose hash is in blocks, append the rest inside Looks; every other line unchanged."""
    left = dict(blocks)
    def sub(m):
        h = m.group(1)
        return left.pop(h) if h in left else m.group(0)
    text = re.sub(PRIM_RE, sub, text)
    if not left: return text
    body = text.rstrip()
    head = body[:body.rfind("}")].rstrip()
    head = head[:head.rfind("}")]           # inside "Looks"
    return head + "".join("\n" + left[h] for h in sorted(left)) + "    }\n}\n"

def merge(a, pairs):
    layer = a.merge
    tex_src = a.tex_src or os.path.join(layer, "textures")
    tex_out = a.tex_out or tex_src
    os.makedirs(tex_out, exist_ok=True)
    text = open(os.path.join(layer, "mod.usda"), encoding="utf-8").read()
    prims = {m.group(1): m for m in re.finditer(PRIM_RE, text)}
    blocks, made, missing = {}, 0, 0
    for (dry, k), wet in sorted(pairs.items()):
        r_path = os.path.join(tex_src, f"{dry}.r.rtex.dds")
        if dry not in prims or not os.path.exists(r_path): missing += 1; continue
        out_name = f"{dry}.w{k}.rtex.dds"
        out_path = os.path.join(tex_out, out_name)
        r = bc4_decode(r_path)
        w_path = os.path.join(tex_src, f"{dry}.w.rtex.dds")
        w = bc4_decode(w_path) if os.path.exists(w_path) else np.clip(r * 0.4, 12, 255)
        if os.path.lexists(out_path): os.unlink(out_path)   # never write through a hard link
        rm.write_roughness(out_path, r + (w - r) * LEVEL_T[k]); made += 1
        block = prims[dry].group(0).replace(f"mat_{dry}", f"mat_{wet}", 1)
        blocks[wet] = block.replace(f"./textures/{dry}.r.rtex.dds", f"./textures/{out_name}")
    for name in ("mod.usda", "mod_wet.usda"):
        path = os.path.join(layer, name)
        if os.path.exists(path):
            atomic_write(path, insert_prims(open(path, encoding="utf-8").read(), blocks))
    print(f"wet levels (merge): {len(pairs)} variants, {len(blocks)} prims into {layer} (mod.usda, mod_wet.usda), "
          f"{made} level maps into {tex_out}, {missing} without a dry material")

if __name__ == "__main__":
    main()
