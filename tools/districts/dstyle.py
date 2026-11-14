#!/usr/bin/env python3
"""DISTRICTS: bake the per-district style rows for the renderer (dll/src/district_style.cpp).

    dstyle.py <work> <lvl> <out .dstyle>

Reads tools/districts/styles.json (the rows) and <work>/<lvl>_districts.json (catalogue.py: which district each map
cell is in, and the row its overrides/<lvl>.json gives it). Writes GDS1 text: one "row" line per row used (row 0 the
default), the rows' Remix options ("remix <row> <key> <value>"; every row lists every key any row sets, the default's
value where it has none, so leaving a district puts the options back), then "grid 256 256" and run-length pairs
"<count> <row>", map y major. Deterministic; tiny (a few KB)."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    work, lvl, out = sys.argv[1:4]
    sys.path.insert(0, HERE)
    from kit import STYLES as styles     # the rows with their "base" rows merged in
    dj = json.load(open(os.path.join(work, f"{lvl}_districts.json")))
    names = ["default"]
    drow = []
    for d in dj["districts"]:
        n = d.get("style") if d.get("style") in styles else "default"
        if n not in names:
            names.append(n)
        drow.append(names.index(n))
    keys = sorted({k for n in names for k in styles[n].get("remix", {})})
    lines = ["GDS1"]
    for n in names:
        r = styles[n]
        f, a, p = r["grade"]["fog"], r["grade"]["ambient"], r["props"]
        lines.append(f"row {n} fog {f[0]:g} {f[1]:g} {f[2]:g} ambient {a[0]:g} {a[1]:g} {a[2]:g} props "
                     f"{p['furniture']:g} {p['trees']:g} {p['meters']:g} {p['roof']:g} {p['containers']:g}")
    for i, n in enumerate(names):
        for k in keys:
            v = styles[n].get("remix", {}).get(k, styles["default"].get("remix", {}).get(k))
            if v is not None:
                lines.append(f"remix {i} {k} {v}")
    lines.append("grid 256 256")
    runs, prev, cnt = [], None, 0
    for row in dj["grid_rle"]:
        for v, n in row:
            r = drow[v] if 0 <= v < len(drow) else 0
            if r == prev:
                cnt += n
            else:
                if prev is not None:
                    runs.append(f"{cnt} {prev}")
                prev, cnt = r, n
    runs.append(f"{cnt} {prev}")
    for i in range(0, len(runs), 16):
        lines.append(" ".join(runs[i:i + 16]))
    open(out, "w", newline="\n").write("\n".join(lines) + "\n")
    used = {names[i] for i in set(drow)}
    print(f"{lvl}: {len(names)} style rows ({', '.join(names)}), {len(runs)} runs -> {out}")


if __name__ == "__main__":
    main()
