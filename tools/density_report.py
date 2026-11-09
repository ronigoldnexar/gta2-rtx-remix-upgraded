#!/usr/bin/env python3
"""QB-9 density before/after report.

  tools/density_report.py <run dir> [<run dir> ...]

Per run: the `density:` census lines of gta2dx9.log summarised per view, and,
when the run has a per-frame log (GTA2DX9_FRAME_LOG=Z:\\out\\frames.tsv), the
frame cost per segment (view x on foot / driving): median and p95 of the work
per frame (whole - wait), of the game's own simulation and of the car and ped
draws, plus the workload counts that do not depend on host load (draw calls,
skinned figures, car bodies). Frames from a container the CPU governor paused
(a present or whole over 1 s) are dropped and counted.
"""
import csv, re, statistics, sys
from collections import defaultdict
from pathlib import Path

CENSUS = re.compile(r"density: view=(\w+) .*?traffic=(-?\d+)/(\d+) .*?dummies=(\d+)/(-?\d+) "
                    r"peds_in_window=(\d+) .*?driven=(\d+) driven_within8=(\d+) driven_within16=(\d+)")
VIEWS = {"0": "classic", "1": "third", "2": "first"}


def pct(xs, q):
    if not xs: return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


def census(run):
    log = Path(run) / "gta2dx9.log"
    rows = defaultdict(list)
    if not log.exists(): return rows
    for line in log.read_text(errors="replace").splitlines():
        m = CENSUS.search(line)
        if m: rows[m.group(1)].append([int(g) for g in m.groups()[1:]])
    return rows


def frames(run):
    tsv = Path(run) / "frames.tsv"
    if not tsv.exists(): return None
    segs, paused = defaultdict(list), 0
    with tsv.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            try:
                whole, wait = float(r["whole"]), float(r["wait"])
            except (KeyError, ValueError):
                continue
            if whole > 1000 or float(r.get("present") or 0) > 1000:
                paused += 1
                continue
            key = (VIEWS.get(r.get("view", ""), r.get("view", "?")), "driving" if r.get("driving") == "1" else "on foot")
            segs[key].append(r)
    return segs, paused


def main():
    for run in sys.argv[1:]:
        print(f"== {run}")
        for view, rows in census(run).items():
            cols = list(zip(*rows))
            def rng(i): return f"{min(cols[i])}-{max(cols[i])}"
            print(f"  census {view:8s} n={len(rows):3d} traffic {rng(0)} (cap {rng(1)})  dummies {rng(2)} (cap {rng(3)})"
                  f"  peds in window {rng(4)}  driven {rng(5)}  driven <8 {rng(6)}  <16 {rng(7)}")
        got = frames(run)
        if not got:
            print("  (no frames.tsv)")
            continue
        segs, paused = got
        print(f"  frames dropped as paused: {paused}")
        for (view, mode), rs in sorted(segs.items()):
            if len(rs) < 60: continue
            def f(name): return [float(r[name]) for r in rs if r.get(name) not in (None, "")]
            work = [float(r["whole"]) - float(r["wait"]) for r in rs]
            print(f"  {view:7s} {mode:8s} n={len(rs):5d}  work med/p95 {pct(work, .5):5.1f}/{pct(work, .95):5.1f} ms"
                  f"  game {pct(f('game'), .5):4.1f}/{pct(f('game'), .95):5.1f}"
                  f"  cars {pct(f('cars'), .5):4.1f}/{pct(f('cars'), .95):4.1f}"
                  f"  peds {pct(f('peds'), .5):4.1f}/{pct(f('peds'), .95):4.1f}"
                  f"  draws {statistics.mean(f('draws')):6.0f}  skinned {statistics.mean(f('skinned')):5.1f}"
                  f"  car_bodies {statistics.mean(f('car_bodies')):5.1f}  over 33ms {sum(w > 33.3 for w in work) / len(work) * 100:4.1f}%")


if __name__ == "__main__":
    main()
