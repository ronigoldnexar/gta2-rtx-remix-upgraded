#!/usr/bin/env python3
"""PERF-2: read a GTA2DX9_FRAME_LOG (frames.tsv) and report the third-person driving window:
frame cost (whole - wait) and interval percentiles, every frame over 33 ms with its largest
phases, and the player's per-frame step. perf2_analyze.py out/<run>/frames.tsv [...]"""
import csv, json, math, sys

PHASES = ["game", "pre_load", "pre_anim", "pre_input", "pre_camera", "pre_menu", "pre_tod", "lights", "sky", "world",
          "spr_setup", "spr_loop", "spr_skid", "spr_issue", "cars", "props", "objects", "peds", "effects", "ui",
          "lightsdraw", "present"]

def load(path):
    rows = list(csv.DictReader(open(path), delimiter="\t"))
    out = []
    for r in rows:
        try:
            d = {k: float(v) for k, v in r.items() if v not in (None, "")}
        except ValueError:
            continue
        d["cost"] = d["whole"] - d["wait"]
        out.append(d)
    return out

def window(rows, view=1):
    """frames in the chase view at the wheel, from 5 s after the level started"""
    lvl = next((r["t_ms"] for r in rows if r.get("px", 0) != 0), 0)
    return [r for r in rows if r.get("view") == view and r.get("driving") == 1 and r["t_ms"] > lvl + 5000]

def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else float("nan")

def cause(r):
    parts = sorted(((r.get(k, 0), k) for k in PHASES), reverse=True)[:3]
    extra = []
    for k in ("tex_created", "tex_uploads", "model_tex", "model_buffers", "new_poses", "skin_buffers", "car_built", "vb_created"):
        if r.get(k, 0): extra.append(f"{k}={int(r[k])}")
    return ", ".join(f"{k} {v:.1f}" for v, k in parts) + (" | " + " ".join(extra) if extra else "")

def summary(path):
    rows = load(path); w = window(rows)
    if not w: return {"path": path, "frames": 0}
    cost = [r["cost"] for r in w]; whole = [r["whole"] for r in w]
    spikes = [r for r in w if r["whole"] > 33.4 + 2.0 and r["cost"] > 33.0]
    # player step per frame (blocks), driving
    steps = [math.hypot(b["px"] - a["px"], b["py"] - a["py"]) for a, b in zip(w, w[1:]) if b["frame"] == a["frame"] + 1]
    s = {"path": path, "frames": len(w), "secs": (w[-1]["t_ms"] - w[0]["t_ms"]) / 1000,
         "cost_p50": pct(cost, .5), "cost_p95": pct(cost, .95), "cost_p99": pct(cost, .99), "cost_max": max(cost),
         "interval_p50": pct(whole, .5), "interval_p99": pct(whole, .99), "interval_max": max(whole),
         "fps": len(w) / max(1e-3, (w[-1]["t_ms"] - w[0]["t_ms"]) / 1000),
         "spikes": len(spikes), "over33_cost": sum(c > 33 for c in cost),
         "phase_mean": {k: sum(r.get(k, 0) for r in w) / len(w) for k in PHASES + ["draws", "prims"]},
         "spike_list": [(int(r["frame"]), round(r["whole"], 1), round(r["cost"], 1), cause(r)) for r in spikes]}
    return s

if __name__ == "__main__":
    for p in sys.argv[1:]:
        s = summary(p)
        if not s["frames"]: print(p, "no driving window"); continue
        print(f"== {p}: {s['frames']} frames, {s['secs']:.0f} s, {s['fps']:.1f} fps")
        print(f"   cost p50 {s['cost_p50']:.1f} p95 {s['cost_p95']:.1f} p99 {s['cost_p99']:.1f} max {s['cost_max']:.1f} | "
              f"interval p50 {s['interval_p50']:.1f} p99 {s['interval_p99']:.1f} max {s['interval_max']:.1f} | spikes {s['spikes']}")
        print("   mean ms: " + " ".join(f"{k}={v:.2f}" for k, v in s["phase_mean"].items() if v >= 0.05))
        for sp in s["spike_list"]: print("   spike", sp)
