#!/usr/bin/env python3
"""PERF-3: the cars stage in a GTA2DX9_FRAME_LOG (frames.tsv), from 5 s after the level:
every frame over 33 ms (cost = whole - wait) whose largest phase is `cars` (and, looser, those
whose `cars` phase alone passes 10 ms: on a shared host every phase stretches with the game step), the cars phase's percentiles, and the driving window's frame cost
(perf2_analyze.summary). perf3_analyze.py out/<run>/frames.tsv [...]"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perf2_analyze as P

def cars_report(path):
    rows = P.load(path)
    lvl = next((r["t_ms"] for r in rows if r.get("px", 0) != 0), 0)
    after = [r for r in rows if r["t_ms"] > lvl + 5000 and r.get("view", 0) in (1, 2)]
    cars = [r.get("cars", 0) for r in after]
    blamed, top = [], []
    for r in after:
        if r["cost"] <= 33.0: continue
        largest = max(P.PHASES, key=lambda k: r.get(k, 0))
        if largest == "cars" or r.get("cars", 0) > 10.0: blamed.append(r)
        if largest == "cars": top.append(r)
    return {"top": top, "frames": len(after), "cars_p50": P.pct(cars, .5), "cars_p99": P.pct(cars, .99), "cars_max": max(cars) if cars else 0,
            "cars_over10": sum(c > 10 for c in cars), "blamed": blamed, "over33": sum(r["cost"] > 33 for r in after)}

if __name__ == "__main__":
    for p in sys.argv[1:]:
        c = cars_report(p)
        print(f"== {p}: {c['frames']} street-view frames after level+5 s, {c['over33']} over 33 ms")
        print(f"   cars phase p50 {c['cars_p50']:.2f} p99 {c['cars_p99']:.2f} max {c['cars_max']:.1f} ms; frames with cars > 10 ms: {c['cars_over10']}")
        print(f"   frames over 33 ms with cars the largest phase: {len(c['top'])}; with cars largest or over 10 ms: {len(c['blamed'])}")
        for r in c["blamed"][:40]: print(f"     frame {int(r['frame'])} t={r['t_ms']/1000:.1f}s cost {r['cost']:.1f} cars {r.get('cars',0):.1f} | {P.cause(r)}")
        s = P.summary(p)
        if s["frames"]:
            print(f"   driving: cost p50 {s['cost_p50']:.1f} p95 {s['cost_p95']:.1f} p99 {s['cost_p99']:.1f} max {s['cost_max']:.1f}; interval p99 {s['interval_p99']:.1f}; over 33 ms {s['over33_cost']} of {s['frames']}")
