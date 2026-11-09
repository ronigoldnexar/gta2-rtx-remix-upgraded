#!/usr/bin/env python3
"""FIX-FP probe (pm8-fp-full-height-vertical-seam-splits-view): warp to the filer's stop in ste (player 116.15,123.38,
facing 0.362,0.932, eye on the x=116 block boundary), first person, a burst of shots, then small turns and nudges
forward into the corner, a burst after each."""
import sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, hold, tap
import feel_probe as F
from qa_lib import shot
T.warp(116.15, 123.38, 2, why="seam stop")
A.face(116.15 + 0.362 * 6, 123.38 + 0.932 * 6)
Q.set_view("first", settle=1.5)
s = D.wait_state(); F.mark(f"at {s['x']:.2f},{s['y']:.2f}")
for i in range(10): shot(f"s0_{i:02d}"); time.sleep(0.1)
for k, (key, t) in enumerate([("Left", 0.08), ("Left", 0.08), ("Right", 0.25), ("Right", 0.08), ("Up", 0.15), ("Up", 0.15), ("Left", 0.12), ("Up", 0.3)]):
    hold(key, t); time.sleep(0.4)
    s = D.wait_state(); F.mark(f"step {k} {key} at {s['x']:.2f},{s['y']:.2f}")
    for i in range(5): shot(f"s{k+1}_{i:02d}"); time.sleep(0.1)
A.save_log()
