#!/usr/bin/env python3
"""PERF-2 item 3: motion smoothness from frames.tsv. In the chase view at the wheel, over
stretches where the car moves at a steady speed (its per-frame step changes < 3 % between
frames, > 0.05 blocks), how evenly does the camera eye move? Reports the player's and the
camera's per-frame step spread (coefficient of variation) and the camera jumps (> 0.6 block
in one frame). perf2_motion.py out/<run>/frames.tsv ..."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as A

def cv(v):
    if len(v) < 2: return float("nan")
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) / m if m else float("nan")

def motion(path):
    w = A.window(A.load(path))
    pairs = [(a, b) for a, b in zip(w, w[1:]) if b["frame"] == a["frame"] + 1]
    steps = [(math.hypot(b["px"] - a["px"], b["py"] - a["py"]), math.hypot(b["cx"] - a["cx"], b["cz"] - a["cz"]), b["whole"]) for a, b in pairs]
    steady_p, steady_c, ratio, local = [], [], [], []
    for (p0, c0, _), (p1, c1, _) in zip(steps, steps[1:]):
        if p0 > 0.05 and p1 > 0.05 and abs(p1 - p0) / p0 < 0.03 and c1 < 0.6 and c0 < 0.6:
            steady_p.append(p1); steady_c.append(c1); ratio.append(c1 / p1)
            local.append(abs(c1 - c0) / p1)   # frame-to-frame change of the camera's step, in car steps
    jumps = sum(1 for _, c, _ in steps if c > 0.6)
    return {"frames": len(steps), "steady": len(steady_p), "player_cv": cv(steady_p), "camera_cv": cv(steady_c),
            "ratio_cv": cv(ratio), "jumps": jumps, "local_p50": A.pct(local, .5), "local_p90": A.pct(local, .9), "jumps_per_min": jumps / max(1e-3, len(steps) / 30 / 60)}

if __name__ == "__main__":
    for p in sys.argv[1:]:
        m = motion(p)
        print(f"{p}: {m['frames']} frames, {m['steady']} at a steady speed: player step CV {m['player_cv']:.3f}, "
              f"camera step change frame to frame p50 {m['local_p50']:.3f} p90 {m['local_p90']:.3f} car steps; "
              f"camera jumps > 0.6 block: {m['jumps']} ({m['jumps_per_min']:.1f}/min)")
