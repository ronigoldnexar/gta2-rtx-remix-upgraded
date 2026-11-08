#!/usr/bin/env python3
"""PERF-3 sheet: the cars stage before/after (dents and door splits off the render thread),
the play container's frame cost with a browser connected, and the look A/B strip.
perf3_sheet.py <out.png> before=<run,run> after=<run,run> play=<label:tsv,...> look=<runA,runB,runC>
(runs are out/<run>/frames.tsv; play tsvs are out/perf3_play/<label>.tsv; look runs hold t_*.png;
runA/runB: PERF-2 before/after, runB/runC: PERF-3 before/after). Needs matplotlib (a venv)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as A
import perf3_analyze as C
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

BEFORE, AFTER, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
OUT = os.environ.get("PERF2_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out"))
args = dict(a.split("=", 1) for a in sys.argv[2:])
before = args["before"].split(","); after = args["after"].split(",")
play = [p.split(":", 1) for p in args.get("play", "").split(",") if p]
look = args.get("look", "").split(",")

def style(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8); ax.set_axisbelow(True)

def tsv(run): return os.path.join(OUT, run, "frames.tsv")

def img(run, name):
    p = os.path.join(OUT, run, f"t_{name}.png")
    return np.asarray(Image.open(p).convert("RGB")) if os.path.exists(p) else None

def coarse(a):
    """16 px block means below the HUD band: what a shift of a few pixels does not change"""
    a = a[80:720].astype(np.float32)
    return a.reshape(40, 16, 80, 16, 3).mean(axis=(1, 3))

def diff(a, b):
    """coarse |A - B| (0-255, 16 px blocks) and the share of blocks off by more than 24"""
    if a is None or b is None: return None
    d = np.abs(coarse(a) - coarse(b)).max(axis=2)
    return d, d.mean(), (d > 24).mean() * 100

spots = [f"spot{i}_{v}" for i in range(3) for v in ("third", "first")]
wear = ["force_dmg0", "force_dmg8000", "force_dmg25000", "force_door_right"]
own = ["own_dmg0", "own_dmg4000", "own_dmg8000", "own_dmg16000", "own_dmg25000"]
nstrip = len(spots) + len(wear) + 1
fig = plt.figure(figsize=(18, 5.0 + 2.6 * nstrip), dpi=110)
gs = fig.add_gridspec(1 + nstrip, 3, height_ratios=[3.4] + [2.6] * nstrip, hspace=0.45, wspace=0.28, top=0.97)
fig.suptitle("PERF-3: car dents and doors off the render thread, play with a browser connected, look A/B", x=0.01, y=0.99, ha="left", fontsize=13, color=INK)

# 1. the cars stage per frame
ax = fig.add_subplot(gs[0, 0]); style(ax)
for runs, col, lab in ((before, BEFORE, "before"), (after, AFTER, "after")):
    rows = A.load(tsv(runs[0])); lvl = next((r["t_ms"] for r in rows if r.get("px", 0) != 0), 0)
    w = [r for r in rows if r["t_ms"] > lvl + 5000 and r.get("view", 0) in (1, 2)]
    ax.plot([(r["t_ms"] - lvl) / 1000 for r in w], [r.get("cars", 0) for r in w], color=col, lw=1.0, label=f"{lab} ({runs[0]})")
ax.axhline(33, color=MUTED, lw=0.8, ls="--"); ax.text(ax.get_xlim()[0], 35, " 33 ms", color=MUTED, fontsize=8)
ax.set_yscale("symlog", linthresh=10); ax.set_ylabel("cars stage, ms (log above 10)", color=MUTED, fontsize=9)
ax.set_xlabel("s after the level", color=MUTED, fontsize=9)
ax.set_title("Cars stage per frame, Downtown drive\nwith dents and doors forced every 5 s", fontsize=10, color=INK, loc="left")
ax.legend(fontsize=8, frameon=False)

# 2. frames over 33 ms whose largest phase is the cars stage, per run
ax = fig.add_subplot(gs[0, 1]); style(ax)
labs, vals, cols, maxes = [], [], [], []
for runs, col in ((before, BEFORE), (after, AFTER)):
    for r in runs:
        c = C.cars_report(tsv(r)); labs.append(r.replace("_wil", "")); vals.append(len(c["top"])); cols.append(col); maxes.append(c["cars_max"])
bars = ax.bar(range(len(vals)), vals, color=cols, width=0.7)
for i, v in enumerate(vals): ax.text(i, v + 0.5, f"{v}", ha="center", fontsize=8, color=INK)
ax.set_xticks(range(len(vals))); ax.set_xticklabels([f"{l}\nmax {m:.0f}" for l, m in zip(labs, maxes)], rotation=45, fontsize=7, ha="right")
ax.set_ylabel("frames over 33 ms, cars the largest phase", color=MUTED, fontsize=9)
ax.set_title("Slow frames caused by cars, per 100 s drive\n(blue before, orange after; max = worst cars stage, ms)", fontsize=10, color=INK, loc="left")

# 3. the play container: frame cost percentiles
ax = fig.add_subplot(gs[0, 2]); style(ax)
if play:
    xs = np.arange(len(play)); wd = 0.26
    stats = [A.summary(os.path.join(OUT, "perf3_play", f"{p[1]}.tsv")) for p in play]
    for k, (key, shade) in enumerate((("cost_p50", "#9fc3ef"), ("cost_p95", "#5c9be3"), ("cost_p99", "#1f5fae"))):
        ax.bar(xs + (k - 1) * wd, [s[key] for s in stats], width=wd - 0.03, color=shade, label=key.replace("cost_", ""))
    for i, s in enumerate(stats): ax.text(i + wd, s["cost_p99"] + 0.6, f"{s['cost_p99']:.1f}", ha="center", fontsize=7, color=INK)
    ax.axhline(33, color=MUTED, lw=0.8, ls="--")
    ax.set_xticks(xs); ax.set_xticklabels([p[0] for p in play], fontsize=7, rotation=35, ha="right")
    ax.set_ylabel("frame cost, ms (whole - cap wait)", color=MUTED, fontsize=9)
    ax.legend(fontsize=8, frameon=False, ncol=3)
ax.set_title("Play container (CPUs 5-7), 90 s chase drive\nframe cost with and without a browser", fontsize=10, color=INK, loc="left")

# 4. look strip
def strip_row(row, name, ra, rb, la, lb):
    a, b = img(ra, name), img(rb, name)
    for k, (im, lab) in enumerate(((a, la), (b, lb))):
        ax = fig.add_subplot(gs[row, k]); ax.axis("off")
        if im is not None: ax.imshow(im)
        ax.set_title(f"{name}: {lab}", fontsize=8, color=INK, loc="left")
    ax = fig.add_subplot(gs[row, 2]); ax.axis("off")
    d = diff(a, b)
    if d is not None:
        ax.imshow(d[0], cmap="gray_r", vmin=0, vmax=96, interpolation="nearest")
        ax.set_title(f"coarse |A - B| (16 px blocks): mean {d[1]:.1f}, {d[2]:.1f} % of blocks > 24 (camera framing, traffic, people)", fontsize=8, color=INK, loc="left")
row = 1
if len(look) == 3:
    for n in spots: strip_row(row, n, look[0], look[1], "PERF-2 before (06d1a97)", "PERF-2 after (props merged, culled, 48 blocks)"); row += 1
    for n in wear: strip_row(row, n, look[1], look[2], "PERF-3 before (render thread)", "PERF-3 after (worker)"); row += 1
    ax = fig.add_subplot(gs[row, :])
    ims = [img(look[2], n) for n in own]
    ims = [i if i is not None else np.zeros((720, 1280, 3), np.uint8) for i in ims]
    ax.axis("off"); ax.imshow(np.concatenate([i[290:500, 540:900] for i in ims], axis=1))   # the car beside him, full size
    ax.set_title("PERF-3 after: the player's car, set_car_damage 0 / 4000 / 8000 / 16000 / 25000, seen on foot beside it", fontsize=9, color=INK, loc="left")
fig.savefig(sys.argv[1], bbox_inches="tight", facecolor="white")
print(sys.argv[1])
