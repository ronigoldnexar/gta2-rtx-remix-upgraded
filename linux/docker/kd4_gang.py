#!/usr/bin/env python3
"""FIX-KNOCKDOWN-4 pm24: stand at gang spots (KD4_GANG_SPOTS 'x,y;x,y', default the wil Yakuza and Loonie streets) in third
person and film 30 fps bursts of the passers-by (gangs walk in files there)."""
import os, sys, time
sys.path.insert(0, "/work")
import feel_probe as F
from feel_probe import *
import feel17_probe as X
vto = X.vto
spots = [tuple(float(v) for v in p.split(",")) for p in os.environ.get("KD4_GANG_SPOTS", "47.5,150.95;64.5,23.95").split(";")]
for k, (x, y) in enumerate(spots):
    T.warp(x, y, 2, why=f"gang spot {k}"); time.sleep(9); vto("third", 3.0)
    p = burst(f"gang_{k}", float(os.environ.get("KD4_GANG_SECS", "35"))); p.wait()
    A.save_log()
