#!/usr/bin/env python3
"""PERF-4 sheet: car sprite artwork off the render thread. perf4_sheet.py <out.png> pairs=<before:after,...>
(runs are out/<run>). Left: frames over 33 ms attributable to textures, per run; middle: the 99th
percentile of frame cost; right: one pair's frame cost over the drive, texture-attributed spikes
marked. Needs matplotlib (gen3d/venv)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as P
import perf4_analyze as Q
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BEFORE, AFTER, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out")
args = dict(a.split("=", 1) for a in sys.argv[2:])
pairs = [p.split(":") for p in args["pairs"].split(",")]

def style(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8); ax.set_axisbelow(True)

reps = [(Q.report(os.path.join(OUT, b)), Q.report(os.path.join(OUT, a))) for b, a in pairs]
fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 1, 2.2]})
x = range(len(reps)); w = 0.38
for ax, key, title in ((axes[0], "tex_over33", "Frames over 33 ms with a texture made\nin an artwork stage (street views)"),
                       (axes[1], "p99", "Frame cost p99, ms")):
    style(ax)
    bb = ax.bar([i - w / 2 for i in x], [r[0][key] for r in reps], w - 0.04, color=BEFORE, label="before")
    ab = ax.bar([i + w / 2 for i in x], [r[1][key] for r in reps], w - 0.04, color=AFTER, label="after (PERF-4)")
    for bars in (bb, ab):
        for b in bars: ax.annotate(f"{b.get_height():.0f}", (b.get_x() + b.get_width() / 2, b.get_height()), ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(list(x)); ax.set_xticklabels([f"pair {i + 1}" for i in x])
    ax.set_title(title, fontsize=10, color=INK, loc="left")
axes[0].legend(frameon=False, fontsize=8)
ax = axes[2]; style(ax)
b, a = pairs[int(args.get("show", "1")) - 1]
for run, col, lab in ((b, BEFORE, "before"), (a, AFTER, "after (PERF-4)")):
    rows = P.load(os.path.join(OUT, run, "frames.tsv"))
    lvl = next((r["t_ms"] for r in rows if r.get("px", 0) != 0), 0)
    rows = [r for r in rows if r["t_ms"] > lvl + 5000 and r.get("view", 0) in (1, 2)]
    t0 = rows[0]["t_ms"] if rows else 0
    ax.plot([(r["t_ms"] - t0) / 1000 for r in rows], [r["cost"] for r in rows], color=col, linewidth=0.8, label=lab, alpha=0.85)
    tx = [r for r in rows if r["cost"] > 33 and r.get("tex_created", 0) > 0 and max(P.PHASES, key=lambda k: r.get(k, 0)) in Q.ART_STAGES]
    ax.scatter([(r["t_ms"] - t0) / 1000 for r in tx], [r["cost"] for r in tx], s=22, color=col, edgecolor="white", linewidth=1, zorder=3)
ax.axhline(33, color=MUTED, linewidth=0.8, linestyle="--")
ax.set_ylim(0, 150); ax.set_xlabel("seconds in the street views", fontsize=8, color=MUTED)
ax.set_title(f"Frame cost, ms (pair {args.get('show', '1')}); dots: texture-attributed frames over 33 ms", fontsize=10, color=INK, loc="left")
ax.legend(frameon=False, fontsize=8, loc="upper right")
fig.suptitle("PERF-4: car sprite artwork built on a worker, uploaded to dynamic textures, all car sprites made ahead at level load (Downtown, 100 s drive, forced damage/doors/models)",
             fontsize=10.5, color=INK, x=0.01, ha="left")
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(sys.argv[1], dpi=110)
print("wrote", sys.argv[1])
