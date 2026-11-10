#!/usr/bin/env python3
"""Graft chosen inputs of model prims from a scratch layer onto a shipped layer's prims (FIX-REMIX-CARS-1).

    remix_layer_graft.py <scratch-layer> <shipped-layer> <hashes.txt> <out-layer> [--inputs normal,roughness]

For each hash: the out layer's prim is the SHIPPED prim with only the listed inputs replaced by the scratch
prim's (normal: `normalmap_texture`; roughness: `reflectionroughness_texture` or
`reflection_roughness_constant`; metallic: `metallic_texture` or `metallic_constant`), and its textures are the
shipped files (hard links) except the grafted maps' DDS, copied from the scratch layer. Everything else the shipped
prim carries (another pass's per-texel metallic, the lamps' emissive mask and gain, the albedo DDS) is kept as
shipped. A hash whose grafted inputs and DDS are byte-identical to the shipped ones is left out. The out layer is
a complete source for `remix_layer_merge.py <out-layer> <dst> <out-layer>/hashes.txt` and for a coordinator
bundle (`<out-layer>/files.txt` lists the DDS that differ from the shipped layer; `replaced.txt` those of them
that replace a shipped file).
"""
import filecmp, os, re, shutil, sys

PRIM = re.compile(r' {8}over "mat_([0-9A-F]{16})"\n {8}\{\n.*?\n {8}\}\n', re.S)
INPUT_LINES = {
    "normal": (("normalmap_texture",), "n"),
    "roughness": (("reflectionroughness_texture", "reflection_roughness_constant"), "r"),
    "metallic": (("metallic_texture", "metallic_constant"), "m"),
}


def blocks(prim, names):
    """the input declarations of one prim for the given input names, as text chunks (an asset input spans 3 lines)"""
    lines = prim.splitlines(keepends=True); out, i = [], 0
    while i < len(lines):
        if any(f"inputs:{n} " in lines[i] for n in names):
            j = i + 1
            if "@" in lines[i] and lines[i].rstrip().endswith("("):
                while j < len(lines) and lines[j].strip() != ")": j += 1
                j += 1
            out.append((i, j)); i = j
        else: i += 1
    return lines, out


def graft(ship_prim, new_prim, names):
    sl, sb = blocks(ship_prim, names)
    nl, nb = blocks(new_prim, names)
    new_text = "".join("".join(nl[a:b]) for a, b in nb)
    if sb:
        res, put = [], False
        for k, l in enumerate(sl):
            if any(x <= k < y for x, y in sb):
                if not put: res.append(new_text); put = True
                continue
            res.append(l)
        return "".join(res)
    # no such input in the shipped prim: put it before use_legacy_alpha_state
    k = next(i for i, l in enumerate(sl) if "use_legacy_alpha_state" in l or "token outputs:out" in l)
    return "".join(sl[:k]) + new_text + "".join(sl[k:])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    inputs = ["normal", "roughness"]
    for a in sys.argv[1:]:
        if a.startswith("--inputs="): inputs = a.split("=", 1)[1].split(",")
    if "--inputs" in sys.argv: inputs = sys.argv[sys.argv.index("--inputs") + 1].split(","); args.remove(",".join(inputs))
    src, ship, lst, out = args
    names = [n for i in inputs for n in INPUT_LINES[i][0]]
    sufs = [INPUT_LINES[i][1] for i in inputs]
    sp = {m.group(1): m.group(0) for m in PRIM.finditer(open(os.path.join(src, "mod.usda"), encoding="utf-8").read())}
    shp = {m.group(1): m.group(0) for m in PRIM.finditer(open(os.path.join(ship, "mod.usda"), encoding="utf-8").read())}
    os.makedirs(os.path.join(out, "textures"), exist_ok=True)
    done, files, replaced, missing = [], [], [], []
    for h in [h for h in open(lst).read().split() if h]:
        if h not in sp: sys.exit(f"{h} has no prim in {src}")
        if h not in shp: missing.append(h); continue
        prim = graft(shp[h], sp[h], names)
        changed = prim != shp[h]
        for s in sufs:
            sf = os.path.join(src, "textures", f"{h}.{s}.rtex.dds"); df = os.path.join(ship, "textures", f"{h}.{s}.rtex.dds")
            if os.path.exists(sf) and not (os.path.exists(df) and filecmp.cmp(sf, df, False)): changed = True
        if not changed: continue
        done.append((h, prim))
        for s in "anmreh":
            sf = os.path.join(src, "textures", f"{h}.{s}.rtex.dds"); df = os.path.join(ship, "textures", f"{h}.{s}.rtex.dds")
            of = os.path.join(out, "textures", f"{h}.{s}.rtex.dds")
            if os.path.lexists(of): os.remove(of)
            if s in sufs:
                if os.path.exists(sf):
                    shutil.copyfile(sf, of)
                    if not (os.path.exists(df) and filecmp.cmp(sf, df, False)):
                        files.append(os.path.basename(of))
                        if os.path.exists(df): replaced.append(os.path.basename(of))
            elif os.path.exists(df):
                os.link(df, of) if os.stat(df).st_dev == os.stat(os.path.join(out, "textures")).st_dev else shutil.copyfile(df, of)
    head = '#usda 1.0\n(\n    upAxis = "Y"\n)\n\nover "RootNode"\n{\n    over "Looks"\n    {\n'
    body = "".join(p for _, p in done) + "    }\n}\n"
    for name in ("mod.usda", "mod_wet.usda"):
        with open(os.path.join(out, name), "w", encoding="utf-8", newline="\n") as f: f.write(head + body)
    open(os.path.join(out, "hashes.txt"), "w").write("".join(h + "\n" for h, _ in done))
    open(os.path.join(out, "files.txt"), "w").write("".join(f + "\n" for f in sorted(files)))
    open(os.path.join(out, "replaced.txt"), "w").write("".join(f + "\n" for f in sorted(replaced)))
    print(f"{len(done)} prims grafted ({','.join(inputs)}); {len(files)} DDS differ from the shipped layer, "
          f"{len(replaced)} of them replace a shipped file; {len(missing)} hashes without a shipped prim skipped")


if __name__ == "__main__":
    main()
