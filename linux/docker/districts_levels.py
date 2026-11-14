#!/usr/bin/env python3
"""DISTRICTS ship check (5090 run-1 fault): level changes with the facade kit in ONE process. The order Industrial ->
Downtown -> Residential -> Downtown, DK_LEVEL_LAPS times (default 5: 20 level loads; launch with SWAP_LEVEL=bil).
Each stop: third person, a walk, first person and the classic view (the kit streams in and out, the density and
city-ai hooks read the view player), then PLAYER QUIT, BACK TO MAIN MENU, the next district swapped over level 1 in
the frontend (swap_level.sh; Downtown restored from /game/data), START PLAY = a fresh level load. MARK lines carry the
stop, the district and the view; the game log carries the kit's load lines per level."""
import os, subprocess, sys, time
sys.path.insert(0, "/work")
import a3_lib as A
from a3_lib import Q, T, D, say, tap, hold, shot
LAPS = int(os.environ.get("DK_LEVEL_LAPS", "5"))
ORDER = ["bil", "wil", "ste", "wil"] * LAPS
G = "/tmp/wp/drive_c/Games/GTA2"


def swap(L):
    if L == "wil":
        d = G + "/data"
        cmd = ["bash", "-c", f"for e in gmp sty SCR; do cp /game/data/wil.$e {d}/wil.$e; done; rm -rf {d}/wil && cp -r /game/data/wil {d}/wil && cmp /game/data/wil.gmp {d}/wil.gmp && echo restored wil"]
    else:
        cmd = ["bash", "/work/swap_level.sh", G, L]
    r = subprocess.run(cmd, capture_output=True, text=True)
    say("SWAP", L, r.returncode, (r.stdout + r.stderr).strip()[-120:])
    return r.returncode == 0


LOG = G + "/gta2dx9.log"


def loads():
    """level loads so far: the renderer's kit-stream line, written once per map it builds"""
    try:
        return open(LOG, encoding="latin-1", errors="replace").read().count("facade kit stream")
    except OSError:
        return 0


def on_foot():
    for _ in range(4):
        s = D.wait_state()
        if not (s and s.get("driving")):
            return
        tap("Return", 0.15); time.sleep(2.5)     # out of the car (the quit menu does not open from a car in all states)


def start_level(n0):
    """PLAYER QUIT, BACK TO MAIN MENU, START PLAY; True once the log shows a new level load"""
    on_foot()
    tap("Escape", 0.1); time.sleep(1.5); tap("Return", 0.1); time.sleep(4)
    tap("Down", 0.1); time.sleep(0.5); tap("Down", 0.1); time.sleep(0.5); tap("Return", 0.1)
    return n0


Q.start("dklevels"); TT = time.time()
time.sleep(4); D.wait_state()
bad = 0
for k, cur in enumerate(ORDER):
    say("MARK stop start", k, cur, f"{time.time() - TT:.0f}", Q.words(D.wait_state()))
    Q.set_view("third", settle=2.5); hold("Up", 3.0); shot(f"s{k:02d}_{cur}_third")
    Q.set_view("first", settle=1.5); hold("Up", 1.5); shot(f"s{k:02d}_{cur}_first")
    Q.set_view("classic", settle=1.5); shot(f"s{k:02d}_{cur}_classic")
    Q.set_view("third", settle=1.5)
    say("MARK stop end", k, cur, f"{time.time() - TT:.0f}")
    if k + 1 >= len(ORDER):
        break
    nxt = ORDER[k + 1]
    n0 = loads()
    got = False
    for attempt in range(3):
        start_level(n0)
        time.sleep(3)
        if attempt == 0:
            swap(nxt)
        t0 = time.time()
        while time.time() - t0 < 75:
            time.sleep(1.5)
            el = time.time() - t0
            if 12 < el < 40 and int(el) % 6 < 2:
                tap("Return", 0.15)          # past the level's intro text
            if el > 40 and Q.current_view() == "classic":
                Q.set_view("third", settle=1.0)   # the street view builds the map (and the kit) if it has not yet
            if loads() > n0:
                got = True
                break
        if got:
            break
        say("MARK level load not seen, retry", k + 1, nxt, attempt)
    if not got:
        bad += 1
    time.sleep(3)
    say("MARK level loaded", k + 1, nxt, "verified" if got else "NOT VERIFIED", Q.current_view(), Q.words(D.wait_state()))
say("MARK levels done", len(ORDER), "unverified", bad, f"{time.time() - TT:.0f}")
A.finish()
open("/out/.dk_done", "w").write("ok\n")
