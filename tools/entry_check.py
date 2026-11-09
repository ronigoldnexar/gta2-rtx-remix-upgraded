#!/usr/bin/env python3
"""ANIM-VEHICLE-ENTRY: frame-by-frame check of getting into and out of a car, from a run's
gta2dx9.log written with GTA2DX9_LOG_FIGURES=1 (and the boarding module on).

    entry_check.py <gta2dx9.log> [--all]

For the player's figure it lists every frame of each enter (state 3) and exit (state 4)
episode plus the frames just after: the drawn position, the step from the frame before
(blocks), the drawn speed, the sink (seated), the action clip and time, the boarding phase,
and the hand/foot contact error (distance of the drawn hand or foot from its target, blocks;
"board contact" lines). It flags:
  POP    the figure disappears while still outside the car (GONE before the plan ends), or its
         drawn speed jumps by > 0.9 block/s in one frame, or it moves > 0.09 block in one frame
  SLIDE  a frame where the figure moves > 0.3 block/s with both feet left to the clips while
         the crouch/exit clip is at full weight (the old crouch-glide)
  NOREACH a driven hand or foot more than 0.02 block from its target at full weight
Writes a summary per episode at the end."""
import math, re, sys

FIG = re.compile(r"fig: f=(\d+) o=(\w+) own=(\d) game=([-\d.]+),([-\d.]+) drawn=([-\d.]+),([-\d.]+) v=([-\d.]+) st=(-?\d+) sub=0x(\w+) "
                 r"fr=(\d+) act=(\d+) t=([-\d.]+) aw=([-\d.]+).*?clip=(\S+)")
BOARD = re.compile(r"board: f=(\d+) ped=(\w+) mode=(\d) t=([-\d.]+) side=(-?\d) u=([-\d.]+) z=([-\d.]+) sink=([-\d.]+) .*?door=([-\d.]+)->(\d).*?clip=(\d+)@([-\d.]+).*?ghost=(\d)(?: pos=([-\d.]+),([-\d.]+))?")
CONTACT = re.compile(r"board contact: f=(\d+) o=(\w+)(.*)")
LIMB = re.compile(r" (\d):w([-\d.]+) err([-\d.]+) y([-\d.]+)")


def main():
    path = sys.argv[1]
    allfig, boards, contacts = {}, {}, {}
    for line in open(path, errors="replace"):
        m = FIG.search(line)
        if m:
            f, o = int(m.group(1)), m.group(2)
            rec = dict(o=o, own=m.group(3) == "1", gx=float(m.group(4)), gz=float(m.group(5)), dx=float(m.group(6)), dz=float(m.group(7)),
                       v=float(m.group(8)), st=int(m.group(9)), sub=int(m.group(10), 16), fr=int(m.group(11)),
                       act=int(m.group(12)), t=float(m.group(13)), aw=float(m.group(14)), clip=m.group(15))
            allfig.setdefault(f, {})[o] = rec
            continue
        m = BOARD.search(line)
        if m:
            boards[(int(m.group(1)), m.group(2))] = dict(mode=int(m.group(3)), t=float(m.group(4)), sink=float(m.group(8)),
                                                         door=float(m.group(9)), tgt=int(m.group(10)), clip=int(m.group(11)),
                                                         ct=float(m.group(12)), ghost=int(m.group(13)),
                                                         x=float(m.group(14)) if m.group(14) else None, z=float(m.group(15)) if m.group(15) else None)
            continue
        m = CONTACT.search(line)
        if m:
            contacts[(int(m.group(1)), m.group(2))] = [(int(a), float(w), float(e), float(y)) for a, w, e, y in LIMB.findall(m.group(3))]
    # The player's figure: the own=1 lines, and the same object while it is drawn as the
    # boarding ghost (the renderer no longer counts it as the player's once he is in the car).
    ids = {r["o"] for fr in allfig.values() for r in fr.values() if r["own"]}
    figs = {}
    for f, fr in allfig.items():
        own = [r for r in fr.values() if r["own"]] or [r for r in fr.values() if r["o"] in ids and r["st"] in (3, 4)]
        if own: figs[f] = own[0]
    # Ghost frames (the figure drawn after the game hid him): from the boarding trace.
    pids = {o for o in ids}
    for (f, ped), bd in boards.items():
        if f in figs or ped not in pids or bd["x"] is None: continue
        figs[f] = dict(o=ped, own=False, gx=bd["x"], gz=bd["z"], dx=bd["x"], dz=bd["z"], v=0.0, st=3 if bd["mode"] == 2 else 4,
                       sub=6, fr=35, act=bd["clip"], t=bd["ct"], aw=1.0, clip="(ghost)")
    frames = sorted(figs)
    # episodes: runs of state 3/4 frames (and ghost frames), plus 20 frames after
    eps, cur = [], None
    for f in frames:
        st = figs[f]["st"]
        if st in (3, 4):
            if cur and f - cur[1] <= 8 and cur[2] == st: cur[1] = f
            else:
                cur = [f, f, st]; eps.append(cur)
    out = []
    for a, b, st in eps:
        kind = "ENTER" if st == 3 else "EXIT"
        lo, hi = a - (12 if st == 3 else 0), b + (60 if st == 4 else 30)   # an exit: its door shut too (kShut, ~1.2 s)
        out.append(f"\n=== {kind} frames {a}-{b} (listing {lo}-{hi}) ===")
        out.append(" frame  st fr act  clip@t      drawn(x,z)        step   v    sink  mode  t    door  contact(limb:w/err)  flags")
        prev = None
        prevStep = 0.0
        pops = slides = noreach = 0
        maxerr = 0.0
        for f in range(lo, hi + 1):
            g = figs.get(f)
            key = (f, g["o"]) if g else None
            bd = boards.get(key) if key else None
            if not bd:
                for k, v in boards.items():
                    if k[0] == f: bd = v; break
            ct = contacts.get(key) if key else None
            flags = []
            if not g:
                if prev is not None and f <= b + 2:
                    flags.append("GONE")
                out.append(f" {f:5d}  -- figure not drawn{'  (car)' if st == 3 and f > b else ''} {' '.join(flags)}")
                if prev is not None and f <= b + 2 and st == 4:
                    pops += 1
                prev = None
                prevStep = 0.0
                continue
            step = math.hypot(g["dx"] - prev["dx"], g["dz"] - prev["dz"]) if prev else 0.0
            # A pop: the drawn speed changes by more than 0.9 block/s (0.03 block a frame) in one
            # frame, or the figure moves more than 0.09 block in one (2.7 block/s: beyond a sprint).
            if prev and (step > 0.09 or abs(step - prevStep) > 0.03): flags.append("POP"); pops += 1
            prevStep = step
            if prev is None and f > lo and f <= b: flags.append("APPEAR")
            sink = bd["sink"] if bd else 0.0
            feetDriven = ct and any(l >= 2 and w > 0.9 for l, w, e, y in ct)
            if g["v"] > 0.3 and g["act"] in (5, 6) and g["aw"] > 0.9 and not feetDriven and not bd:
                flags.append("SLIDE"); slides += 1
            cs = ""
            if ct:
                cs = " ".join(f"{l}:{w:.2f}/{e:.3f}" for l, w, e, y in ct)
                for l, w, e, y in ct:
                    if w > 0.95:
                        maxerr = max(maxerr, e)
                        if e > 0.02: flags.append(f"NOREACH{l}"); noreach += 1
            bs = f"{bd['mode']} {bd['t']:.2f} {bd['door']:.2f}" if bd else "-  -    -   "
            out.append(f" {f:5d}  {g['st']:2d} {g['fr']:2d} {g['act']:2d}  {g['clip'][:9]:9s}@{g['t']:.2f}  {g['dx']:8.3f},{g['dz']:8.3f}  {step:.3f}  {g['v']:.2f}  {sink:.3f}  {bs:13s}  {cs:28s} {' '.join(flags)}")
            prev = g
        out.append(f"--- {kind} summary: pops {pops}, slides {slides}, unreached contact frames {noreach}, max contact error at full weight {maxerr:.3f} block")
    print("\n".join(out))


if __name__ == "__main__":
    main()
