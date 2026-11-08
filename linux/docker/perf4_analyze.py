#!/usr/bin/env python3
"""PERF-4: car sprite artwork in a GTA2DX9_FRAME_LOG run (out/<run>/frames.tsv and gta2dx9.log).
From 5 s after the level, street views: frames over 33 ms (cost = whole - wait); of those, the ones
attributable to textures (a texture created in the frame, tex_created > 0, and the largest phase one
of the stages that fetch sprite artwork: spr_*, cars, objects, peds, effects, ui); the driving
window's cost percentiles (perf2_analyze.summary); and from the log the car artwork fetches that
took over 8 ms (car_bodies) / 4 ms (the shells' setup), and PERF-4's `car art:` lines.
perf4_analyze.py out/<run> [...]   (--json for a machine-readable line per run)"""
import sys, os, re, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as P

ART_STAGES = {"spr_setup", "spr_loop", "spr_skid", "spr_issue", "cars", "objects", "peds", "effects", "ui"}

CAR_ART = [r"sprite artwork of a car took ([0-9.]+) ms", r"car setup slow: sprite \d+ artwork ([0-9.]+) ms",
           r"car art: asking the worker took ([0-9.]+) ms", r"car art: an upload took ([0-9.]+) ms"]

def hms(t):
    h, m, sec = t.split(":"); return int(h) * 3600 + int(m) * 60 + float(sec)

def car_art_frames(log, min_ms=4.0):
    """frames holding a car-artwork texture cost of min_ms or more, from the log's timestamps mapped
    onto frame numbers through the `view: ... frame=N` lines (linear between them)"""
    marks = [(hms(t), int(f)) for t, f in re.findall(r"^\[([0-9:.]+)\] view: cars frame=(\d+)", log, re.M)]
    ev = []
    for pat in CAR_ART:
        for t, v in re.findall(r"^\[([0-9:.]+)\] .*?" + pat, log, re.M):
            if float(v) >= min_ms: ev.append((hms(t), float(v)))
    out = []
    for t, v in ev:
        a = max((m for m in marks if m[0] <= t), default=None); b = min((m for m in marks if m[0] > t), default=None)
        if not a or not b: continue
        out.append((int(round(a[1] + (b[1] - a[1]) * (t - a[0]) / max(1e-6, b[0] - a[0]))), v))
    return out

def report(run):
    rows = P.load(os.path.join(run, "frames.tsv"))
    lvl = next((r["t_ms"] for r in rows if r.get("px", 0) != 0), 0)
    after = [r for r in rows if r["t_ms"] > lvl + 5000 and r.get("view", 0) in (1, 2)]
    over = [r for r in after if r["cost"] > 33.0]
    tex = [r for r in over if r.get("tex_created", 0) > 0 and max(P.PHASES, key=lambda k: r.get(k, 0)) in ART_STAGES]
    tex_any = [r for r in over if r.get("tex_created", 0) > 0]
    cost = [r["cost"] for r in after]
    log = open(os.path.join(run, "gta2dx9.log"), errors="replace").read() if os.path.exists(os.path.join(run, "gta2dx9.log")) else ""
    fetch = [float(m) for m in re.findall(r"sprite artwork of a car took ([0-9.]+) ms", log)]
    shell = [float(m) for m in re.findall(r"car setup slow: sprite \d+ artwork ([0-9.]+) ms", log)]
    shell = [v for v in shell if v > 4.0]
    s = P.summary(os.path.join(run, "frames.tsv"))
    byframe = {int(r["frame"]): r for r in after}
    ca = car_art_frames(log)
    car_over = [f for f, v in ca if any(g in byframe and byframe[g]["cost"] > 33.0 for g in (f - 1, f, f + 1))]
    return {"run": os.path.basename(run.rstrip("/")), "frames": len(after), "over33": len(over), "tex_over33": len(tex),
            "tex_any_over33": len(tex_any), "p50": P.pct(cost, .5), "p95": P.pct(cost, .95), "p99": P.pct(cost, .99),
            "max": max(cost) if cost else 0, "tex_frames": [(int(r["frame"]), round(r["cost"], 1), P.cause(r)) for r in tex],
            "drive_p50": s.get("cost_p50"), "drive_p99": s.get("cost_p99"), "drive_over33": s.get("over33_cost"), "drive_frames": s.get("frames"),
            "fetch_over8": len(fetch), "fetch_max": max(fetch) if fetch else 0, "shell_over4": len(shell), "shell_max": max(shell) if shell else 0,
            "car_art_events": len(ca), "car_art_over33": len(car_over), "car_art_max": max((v for f, v in ca), default=0),
            "artlines": [l for l in log.splitlines() if "car art:" in l]}

if __name__ == "__main__":
    js = "--json" in sys.argv
    for run in [a for a in sys.argv[1:] if a != "--json"]:
        c = report(run)
        if js:
            c = dict(c); c.pop("artlines"); print(json.dumps(c)); continue
        print(f"== {c['run']}: {c['frames']} street-view frames after level+5 s; cost p50 {c['p50']:.1f} p95 {c['p95']:.1f} p99 {c['p99']:.1f} max {c['max']:.0f}")
        print(f"   over 33 ms: {c['over33']}; with a texture made in an artwork stage: {c['tex_over33']} (any texture made: {c['tex_any_over33']})")
        print(f"   driving window: p50 {c['drive_p50']:.1f} p99 {c['drive_p99']:.1f}, {c['drive_over33']} of {c['drive_frames']} over 33 ms")
        print(f"   car artwork fetches over 8 ms: {c['fetch_over8']} (max {c['fetch_max']:.1f}); shell artwork over 4 ms: {c['shell_over4']} (max {c['shell_max']:.1f})")
        print(f"   car artwork texture costs >= 4 ms in the log: {c['car_art_events']} (max {c['car_art_max']:.1f}); of them in a frame over 33 ms (+-1 frame for the log's timing): {c['car_art_over33']}")
        for f in c["tex_frames"][:30]: print("     tex frame", f)
        for l in c["artlines"][:12] + (["   ..."] if len(c["artlines"]) > 24 else []) + c["artlines"][-12:] if len(c["artlines"]) > 24 else c["artlines"]: print("   ", l)
