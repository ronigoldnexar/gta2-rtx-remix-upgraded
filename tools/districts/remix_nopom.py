#!/usr/bin/env python3
"""DISTRICTS: under RTX Remix, no facade parallax (QB-25 displacement) on the tiles the facade kit recesses: the kit's
skin already stands those walls out and cuts real openings, so the parallax would recess the windows a second time.

    remix_nopom.py hashes <hd root> <out.json> <lvl>:<kit file> [...]   tile hashes (Remix: XXH3 of the top mip) of
                                                                         every style tile a kit draws its skin with
    remix_nopom.py patch <hashes.json> <layer dir>                       in mod.usda / mod_wet.usda of a layer copy:
                                                                         drop height_texture, displace_in = 0 for those
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
