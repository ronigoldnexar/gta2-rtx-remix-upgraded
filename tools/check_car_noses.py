#!/usr/bin/env python3
"""Which car models drive backwards.

    check_car_noses.py <gta2dx9.log> [--catalog assets-src/cars/catalog.json] [--json out.json]

Reads the `car nose:` lines the renderer writes with GTA2DX9_LOG_CAR_NOSES=1 (one
per drawn car body every 15 frames: the placement's nose direction nx,nz in the
world and the position). Consecutive samples of one object give its velocity;
the sign of velocity . nose, over samples where the car moved at least a quarter
block in the half second, says whether the car travels nose-first. Cars reverse
now and then (parking, backing out of a stall), so a model is flagged only when
most of its moving samples go tail-first. The model's own `forward` (f) is
logged too: the drawn nose is f * placement nose, so the verdict is about what
is drawn, not about the placement.
"""
import argparse, collections, json, math, re, sys

LINE = re.compile(r"car nose: obj=([0-9a-f]+) sprite=(-?\d+) model=(-?\d+) f=([+-]\d) x=(-?[\d.]+) z=(-?[\d.]+) nx=(-?[\d.]+) nz=(-?[\d.]+) own=(\d) frame=(\d+)")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--catalog", default="assets-src/cars/catalog.json")
    ap.add_argument("--json")
    ap.add_argument("--min-move", type=float, default=0.25, help="blocks per sample to count as moving")
    a = ap.parse_args()
    names = {}
    try:
        cat = json.load(open(a.catalog))
        for m in (cat.get("cars") or cat.get("models") or (cat if isinstance(cat, list) else [])):
            names[int(m["model"])] = m.get("name", "")
    except Exception:
        pass
    last = {}
    stats = collections.defaultdict(lambda: {"fwd": 0, "back": 0, "samples": 0, "f": 0})
    for line in open(a.log, errors="replace"):
        m = LINE.search(line)
        if not m:
            continue
        obj, sprite, model, f, x, z, nx, nz, own, frame = m.groups()
        model, f, x, z, nx, nz, frame = int(model), int(f), float(x), float(z), float(nx), float(nz), int(frame)
        if f == 0:
            continue   # a wreck or a car without a model
        key = (obj, model)
        st = stats[model]; st["samples"] += 1; st["f"] = f
        if key in last:
            px, pz, pf, pnx, pnz = last[key]
            if 0 < frame - pf <= 45:
                vx, vz = x - px, z - pz
                d = math.hypot(vx, vz)
                if d >= a.min_move:
                    # the drawn nose is f * the placement nose
                    dot = (vx * pnx + vz * pnz) / d * f
                    if dot > 0.5: st["fwd"] += 1
                    elif dot < -0.5: st["back"] += 1
        last[key] = (x, z, frame, nx, nz)
    rows = []
    for model, st in sorted(stats.items()):
        n = st["fwd"] + st["back"]
        verdict = "no data" if n < 4 else ("BACKWARDS" if st["back"] > 0.6 * n else ("mixed" if st["back"] > 0.3 * n else "ok"))
        rows.append({"model": model, "name": names.get(model, ""), "f": st["f"], "moving_samples": n,
                     "nose_first": st["fwd"], "tail_first": st["back"], "verdict": verdict})
    print(f"{'model':>5} {'name':<24} {'f':>2} {'moving':>6} {'nose':>5} {'tail':>5}  verdict")
    for r in rows:
        print(f"{r['model']:>5} {r['name']:<24} {r['f']:>+2} {r['moving_samples']:>6} {r['nose_first']:>5} {r['tail_first']:>5}  {r['verdict']}")
    flagged = [r["model"] for r in rows if r["verdict"] == "BACKWARDS"]
    print("flagged (drawn tail-first):", flagged if flagged else "none")
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
    return 1 if flagged else 0

if __name__ == "__main__":
    sys.exit(main())
