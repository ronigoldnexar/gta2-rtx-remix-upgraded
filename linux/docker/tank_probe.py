#!/usr/bin/env python3
"""SKILL-TANK probe: the Downtown kill-frenzy tank (3.5,164.5 z3): what the keys do in a tank.
Scene warp beside it (probe only), in, then: fire held, fire tapped, Left/Right standing, Left with Up,
the weapon keys; frames and the hull heading / car hp around after each."""
import math, os, sys, time
sys.path.insert(0, "/work")
import drive_lib as D
import mission_lib as M
from skills import tank as TK
say, tap, hold, xdo = D.say, D.tap, D.hold, D.xdo

def snap(tag, n=3, every=0.25):
    for k in range(n): M.shot(f"tp_{tag}_{k}"); time.sleep(every)

def hull():
    s = D.wait_state(); h = TK.heading(s); return s, h

def report(tag, h0):
    time.sleep(0.6); s, h = hull()
    turned = math.atan2(h0[0] * h[1] - h0[1] * h[0], h0[0] * h[0] + h0[1] * h[1])
    hurt = [(c["id"], c["model"], c["hp"], c["fire"]) for c in M.cars() if c["driver"] != "P" and c["hp"] < 32000][:8]
    M.mark(f"probe {tag}: at {s['x']:.2f},{s['y']:.2f} hull {h[0]:.2f},{h[1]:.2f} turned {turned:+.2f} rad; damaged cars {hurt}")
    return h

def main():
    D.start(); D.calibrate_turn()
    world = M.World("wil")
    M.VIEW_HOOK[0] = lambda n: None
    tap("v", 0.3); time.sleep(1.7); M.CUR_VIEW[0] = "third"
    M.scene_warp(4.5, 160.5, 2, "probe: beside the frenzy tank")
    s = TK.get_tank(world, spot=(3.5, 164.5, 2), budget=90, jack=False)
    if not s: M.mark("probe: no tank"); return
    s, h = hull(); M.mark(f"probe: in the tank, hull {h}")
    # out of the yard onto the road, then the classic view (the turret sprite from above)
    TK.drive(world, 9.5, 160.5, tol=1.5, budget=60)
    s, h = hull(); M.mark(f"probe: on the road at {s['x']:.1f},{s['y']:.1f} hull {h}")
    tap("v", 0.3); time.sleep(1.7); tap("v", 0.3); time.sleep(1.7)    # third -> first -> classic
    def shoot(tag):
        tap("Control_L", 0.12)
        for k in range(4): M.shot(f"tp_{tag}_s{k}"); time.sleep(0.12)
    snap("base", 1); shoot("base")
    steps = [("left_stand", lambda: hold("Left", 0.6)), ("right_stand", lambda: hold("Right", 1.2)),
             ("x3", lambda: [tap("x", 0.15) or time.sleep(0.3) for _ in range(3)]),
             ("z3", lambda: [tap("z", 0.15) or time.sleep(0.3) for _ in range(3)]),
             ("tab", lambda: tap("Tab", 0.3)),
             ("space_left", lambda: (xdo("keydown", "space"), hold("Left", 0.6), xdo("keyup", "space"))),
             ("ctrl_left", lambda: (xdo("keydown", "Control_L"), hold("Left", 0.8), xdo("keyup", "Control_L")))]
    for tag, act in steps:
        M.mark(f"probe {tag} begins"); act(); h = report(tag, h); snap(tag, 1); shoot(tag)
    ms = M.mission_state() or {}
    M.mark(f"probe end: lives {ms.get('lives')} msg {ms.get('msg')} ammo {ms.get('ammo')}")

if __name__ == "__main__":
    main()
