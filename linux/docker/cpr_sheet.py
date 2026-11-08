#!/usr/bin/env python3
"""CAMERA-PROPS sheet: before/after frames of the camprops.py probe and the mouse-look yaw plot.
  cpr_sheet.py <before run dir> <after run dir> <out.png> [pairs]
pairs: comma-separated frame tags (the part after cpr_, without .png) to show before/after;
default: booth_s08_b, shop_away_b, shop_wall_b, lamp_east."""
import re, sys, datetime
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.image import imread

before, after, out = sys.argv[1:4]
pairs = (sys.argv[4] if len(sys.argv) > 4 else "booth_s08_b,shop_away_b,shop_wall_b,lamp_east").split(",")
LOGT = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\] foot: yaw=(-?[\d.]+) target=(-?[\d.]+) heading=(-?[\d.]+)")


def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def marks(run):
    out = []
    for line in open(f"{run}/marks.txt"):
        t, what = line.split(" ", 1)
        h, m, rest = t.split(":"); s, ms = rest.split(".")
        out.append((secs(h, m, s, ms), what.strip()))
    return out


def yaw_series(run):
    mk = marks(run)
    t0 = next(t for t, w in mk if w == "walk start")
    t1 = next(t for t, w in mk if w == "mouse end")
    ts, off = [], []
    for line in open(f"{run}/gta2dx9.log", encoding="latin-1"):
        m = LOGT.match(line)
        if not m: continue
        t = secs(*m.group(1, 2, 3, 4))
        if t < t0 - 0.5 or t > t1 + 0.5: continue
        d = (float(m.group(5)) - float(m.group(7)) + 180.0) % 360.0 - 180.0   # camera yaw - his heading
        ts.append(t - t0); off.append(d)
    windows = []
    for t, w in mk:
        mm = re.match(r"mouse (\w+) start", w)
        if mm:
            stop = next(tt for tt, ww in mk if ww == f"mouse {mm.group(1)} stop" and tt >= t)
            windows.append((t - t0, stop - t0, mm.group(1)))
    walk_stop = next((t - t0 for t, w in mk if w == "walk stop"), None)
    return ts, off, windows, walk_stop


n = len(pairs)
fig = plt.figure(figsize=(16, 4.2 * n + 4.6), dpi=80)
gs = fig.add_gridspec(n + 1, 2, height_ratios=[4.2] * n + [4.6])
for i, tag in enumerate(pairs):
    for j, (run, label) in enumerate(((before, "before"), (after, "after"))):
        ax = fig.add_subplot(gs[i, j]); ax.axis("off")
        try:
            ax.imshow(imread(f"{run}/cpr_{tag}.png"))
        except OSError:
            ax.text(0.5, 0.5, "missing", ha="center")
        ax.set_title(f"{label}: {tag}", fontsize=13, loc="left")
ax = fig.add_subplot(gs[n, :])
for run, label, colour in ((before, "before", "#9a9a9a"), (after, "after", "#1f6fb4")):
    try:
        ts, off, windows, walk_stop = yaw_series(run)
    except (OSError, StopIteration):
        continue
    ax.plot(ts, off, color=colour, lw=1.8, label=f"{label}: camera yaw minus his heading")
    if label == "after":
        for a, b, name in windows:
            ax.axvspan(a, b, color="#f2c14e", alpha=0.35)
            ax.axvspan(b, b + 1.5, color="#f2c14e", alpha=0.12)
            ax.text(a, ax.get_ylim()[1] if False else 0, f" mouse {name}", fontsize=10, va="bottom")
        if walk_stop is not None:
            ax.axvline(walk_stop, color="#444", ls="--", lw=1); ax.text(walk_stop, 0, " he stops", fontsize=10)
ax.set_xlabel("seconds since he started walking (mouse moving: dark band; the 1.5 s pause after it: light band)")
ax.set_ylabel("degrees")
ax.grid(alpha=0.3); ax.legend(loc="upper right")
ax.set_title("Mouse look with the soft follow: the follow waits 1.5 s after the mouse stops, then eases back behind him", loc="left", fontsize=13)
fig.tight_layout()
fig.savefig(out)
print("wrote", out)
