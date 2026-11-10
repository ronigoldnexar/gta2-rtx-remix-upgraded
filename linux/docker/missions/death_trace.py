#!/usr/bin/env python3
"""What killed him: for every life lost in a run's renderer log, the last seconds before it.

MISSIONS-BATCH3 (10 Nov 2026). Reads only the renderer's own lines (docs/actions-3d.md, "Ped and car log
lines"): `view: mission` (health, weapon, ammo, lives), `view: player` (position, z), `view: peds` (live
peds near him: id, gang, distance, state/sub, hp, car), `view: cars` (burning cars near him: fire > 0)
and `explosions: blast at` lines. Peds in state 7 sub 11 are the ones shooting.

    python3 death_trace.py out/<run>/gta2dx9.log [seconds before, default 3] [radius, default 7]

What it told MISSIONS-BATCH3 about LABRAT'S PLAN: mb2_lp6/lp8 were Zaibatsu gunfire at 1-4 blocks with the
burning cars 6-10 off and unexploded (not blasts); mb3l_lp1/lp9 were falls (z 3 -> 2 -> 0 at health 100)
through the hole at columns 204-205 of The Village's level 2.
"""
import math, re, sys

PED = re.compile(r"(\d+):(\w+)/(\w+):(-?\d+):(-?\d+):(-?[\d.]+),(-?[\d.]+),(-?[\d.]+):(-?\d+):(-?\d+):(-?\d+):(\S+?):(\S+)$")
CAR = re.compile(r"(-?\d+):m(-?\d+):(-?[\d.]+),(-?[\d.]+),(-?[\d.]+):(-?[\d.]+),(-?[\d.]+):(-?[\d.]+):(-?\d+):(-?\d+):(\S+?):(\S+)$")


def sec(ts):
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    path = sys.argv[1]
    before = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    radius = float(sys.argv[3]) if len(sys.argv) > 3 else 7.0
    lines = open(path, errors="replace").read().splitlines()
    lives = None; deaths = []
    for i, l in enumerate(lines):
        if "view: mission" in l:
            m = re.search(r"lives=(\d+)", l)
            if m:
                v = int(m.group(1))
                if lives is not None and v < lives: deaths.append(i)
                lives = v
    if not deaths: print("no life lost in this log")
    for di in deaths:
        t = sec(lines[di][1:13]); px = py = pz = 0.0
        print(f"=== life lost at {lines[di][1:13]}")
        for l in lines[max(0, di - 4000):di + 5]:
            if not l.startswith("["): continue
            try: tt = sec(l[1:13])
            except ValueError: continue
            if tt < t - before: continue
            if "view: player" in l:
                m = re.search(r"x=([-\d.]+) y=([-\d.]+) z=([-\d.]+)", l)
                if m: px, py, pz = float(m.group(1)), float(m.group(2)), float(m.group(3))
            elif "view: mission" in l:
                h = re.search(r"health=(-?\d+)", l); w = re.search(r"weapon=\S+ ammo=-?\d+", l)
                print(f"{l[1:13]} health {h.group(1) if h else '?'} at {px:.1f},{py:.1f} z {pz:.2f} {w.group(0) if w else ''}")
            elif "view: peds" in l and int(tt * 2) % 2 == 0:
                out = []
                for it in l.split()[5:]:
                    g = PED.match(it)
                    if not g: continue
                    x, y = float(g.group(6)), float(g.group(7)); st, sub, hp = int(g.group(9)), int(g.group(10)), int(g.group(11))
                    d = math.hypot(x - px, y - py)
                    if st != 9 and hp > 0 and d < radius:
                        out.append(f"{g.group(1)} {g.group(2)}/{g.group(3)} d{d:.1f} s{st}/{sub} hp{hp}{'' if g.group(12) == '-' else ' in ' + g.group(12)}")
                print("    peds: " + " | ".join(out))
            elif "view: cars" in l and int(tt * 2) % 2 == 0:
                out = []
                for it in l.split()[4:]:
                    g = CAR.match(it)
                    if not g: continue
                    d = math.hypot(float(g.group(3)) - px, float(g.group(4)) - py)
                    if int(g.group(10)) > 0 and d < radius + 2: out.append(f"car {g.group(1)} m{g.group(2)} d{d:.1f} hp{g.group(9)} fire{g.group(10)}")
                if out: print("    burning: " + " | ".join(out))
            elif "blast at" in l:
                print("   " + l[:130])


if __name__ == "__main__":
    main()
