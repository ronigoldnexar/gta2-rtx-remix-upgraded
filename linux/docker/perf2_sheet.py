#!/usr/bin/env python3
"""PERF-2 sheets from frames.tsv logs.
perf2_sheet.py frametimes <out.png> <label=run> ...         frame cost over time + histogram per run
perf2_sheet.py sheet <out.png> <district> <before_run> <after_run> ...   (repeat district/before/after)"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as A
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BEFORE, AFTER, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
OUT = os.environ.get("PERF2_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out"))   # out/<run>/frames.tsv
GROUPS = [("game (GTA2's step)", ["game"]), ("camera, input, load", ["pre_load", "pre_anim", "pre_input", "pre_camera", "pre_menu", "pre_tod", "lights"]),
          ("sky + world", ["sky", "world"]), ("game sprites", ["spr_setup", "spr_loop", "spr_skid", "spr_issue"]),
          ("cars", ["cars"]), ("props + objects", ["props", "objects"]), ("people", ["peds"]), ("effects + UI", ["effects", "ui", "lightsdraw"]),
          ("present", ["present"])]
GCOL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948", "#52514e"]

def style(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    for s in ("left", "bottom"): ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8); ax.set_axisbelow(True)

def series(run):
    w = A.window(A.load(f"{OUT}/{run}/frames.tsv"))
    t0 = w[0]["t_ms"] if w else 0
    return w, [(r["t_ms"] - t0) / 1000 for r in w], [r["cost"] for r in w]

def stats(c):
    return A.pct(c, .5), A.pct(c, .99), max(c), sum(x > 33 for x in c)

def frametimes(out, runs):
    fig, axes = plt.subplots(len(runs), 2, figsize=(13, 3.0 * len(runs)), gridspec_kw={"width_ratios": [3, 1]}, squeeze=False)
    for i, (label, run) in enumerate(runs):
        w, t, c = series(run)
        ax = axes[i][0]; style(ax)
        ax.plot(t, c, color=BEFORE, linewidth=0.8)
        ax.axhline(33.3, color=MUTED, linestyle="--", linewidth=0.8); ax.axhline(20, color=MUTED, linestyle=":", linewidth=0.8)
        ax.set_ylim(0, 120); ax.set_xlabel("seconds of third-person driving", fontsize=8, color=MUTED); ax.set_ylabel("frame cost, ms", fontsize=8, color=MUTED)
        p50, p99, mx, n = stats(c)
        ax.set_title(f"{label}: p50 {p50:.1f} ms, p99 {p99:.1f} ms, max {mx:.0f} ms, {n} frames over 33 ms", fontsize=10, color=INK, loc="left")
        ax.text(t[-1], 34.5, "33 ms (30 fps cap)", fontsize=7, color=MUTED, ha="right"); ax.text(t[-1], 21, "20 ms target p99", fontsize=7, color=MUTED, ha="right")
        hx = axes[i][1]; style(hx)
        hx.hist([min(x, 120) for x in c], bins=60, range=(0, 120), color=BEFORE)
        hx.axvline(33.3, color=MUTED, linestyle="--", linewidth=0.8); hx.set_yscale("log"); hx.set_xlabel("frame cost, ms (log count)", fontsize=8, color=MUTED)
    fig.tight_layout(); fig.savefig(out, dpi=110); print("wrote", out)

def worst_bars(ax, w, title, n=10):
    worst = sorted(w, key=lambda r: -r["cost"])[:n]
    for j, r in enumerate(worst):
        left = 0.0
        for g, (name, keys) in enumerate(GROUPS):
            v = sum(r.get(k, 0) for k in keys)
            ax.barh(j, v, left=left, color=GCOL[g], height=0.7, edgecolor="white", linewidth=0.5, label=name if j == 0 else None)
            left += v
        ax.text(left + 2, j, f"{r['cost']:.0f} ms", va="center", fontsize=7, color=INK)
    ax.set_yticks(range(len(worst))); ax.set_yticklabels([f"#{int(r['frame'])}" for r in worst], fontsize=7)
    ax.invert_yaxis(); style(ax); ax.grid(axis="x", color=GRID); ax.grid(axis="y", visible=False)
    ax.set_title(title, fontsize=9, color=INK, loc="left")

def sheet(out, triples):
    fig = plt.figure(figsize=(16, 4.2 * len(triples) + 0.8))
    gs = fig.add_gridspec(len(triples), 4, width_ratios=[3.2, 1.2, 1.6, 1.6])
    for i, (dist, before, after) in enumerate(triples):
        wb, tb, cb = series(before); wa, ta, ca = series(after)
        ax = fig.add_subplot(gs[i, 0]); style(ax)
        ax.plot(tb, cb, color=BEFORE, linewidth=0.7, label="before")
        ax.plot(ta, ca, color=AFTER, linewidth=0.7, label="after")
        ax.axhline(33.3, color=MUTED, linestyle="--", linewidth=0.8); ax.axhline(20, color=MUTED, linestyle=":", linewidth=0.8)
        ax.set_ylim(0, 120); ax.set_ylabel("frame cost, ms", fontsize=8, color=MUTED); ax.set_xlabel("seconds of third-person driving", fontsize=8, color=MUTED)
        b, a = stats(cb), stats(ca)
        ax.set_title(f"{dist}: p99 {b[1]:.0f} -> {a[1]:.0f} ms, max {b[2]:.0f} -> {a[2]:.0f} ms, frames over 33 ms {b[3]} -> {a[3]}", fontsize=10, color=INK, loc="left")
        ax.legend(fontsize=8, frameon=False, loc="upper right")
        hx = fig.add_subplot(gs[i, 1]); style(hx)
        hx.hist([min(x, 120) for x in cb], bins=48, range=(0, 120), color=BEFORE, alpha=0.9, label="before")
        hx.hist([min(x, 120) for x in ca], bins=48, range=(0, 120), color=AFTER, alpha=0.75, label="after")
        hx.set_yscale("log"); hx.axvline(33.3, color=MUTED, linestyle="--", linewidth=0.8); hx.set_xlabel("frame cost, ms", fontsize=8, color=MUTED)
        worst_bars(fig.add_subplot(gs[i, 2]), wb, f"{dist} before: 10 worst frames")
        wx = fig.add_subplot(gs[i, 3]); worst_bars(wx, wa, f"{dist} after: 10 worst frames")
        if i == 0: handles, labels = wx.get_legend_handles_labels()
    fig.suptitle("PERF-2: frame cost (frame time without the 30 fps cap's wait) while driving in the chase view, play-container settings (gta2-play, CPUs 5-7, 1280x720)",
                 fontsize=11, color=INK, x=0.01, ha="left")
    fig.legend(handles, labels, loc="lower center", ncol=len(labels), fontsize=8, frameon=False)
    fig.tight_layout(rect=(0, 0.03, 1, 0.97)); fig.savefig(out, dpi=100); print("wrote", out)

if __name__ == "__main__":
    if sys.argv[1] == "frametimes":
        frametimes(sys.argv[2], [tuple(a.split("=", 1)) for a in sys.argv[3:]])
    else:
        a = sys.argv[3:]; sheet(sys.argv[2], [tuple(a[k:k + 3]) for k in range(0, len(a), 3)])
