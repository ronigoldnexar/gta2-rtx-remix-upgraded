#!/usr/bin/env python3
"""Inside a Remix run: wait until the Remix runtime has finished compiling shaders (REMIX-PIPELINE, 9 Nov).

The runtime shows "Compiling shaders (N remaining)" as a box in the bottom-left corner of the picture until the
pipelines are built, and renders black / purple frames underneath it. Its log says nothing about it, so this
reads the picture: x11grab of the screen's bottom-left strip, no PIL needed (stdlib + ffmpeg only).
The box has a constant 1 px light-grey (87,87,87) frame: the top edge at y=H-81, x 0..367, and the right edge at x=367.
  gate     [cap_s]   run by the launcher in parallel with the keys script: returns when the picture centre is not black and the
                     overlay has been absent for QUIET polls; writes /out/remix_shaders.txt and /out/.shaders_ready and prints
                     'remix: shaders ready after N s' (N counts from the game start: /out/.t0).
  recheck  [cap_s]   a keys script calls this in the level before its first view shot (same test).
Exit 0 = ready, 1 = cap reached (also logged: 'remix: shaders NOT ready after N s').
Env: SCREEN_W/H (1280x720), REMIX_SHADER_CAP (600), REMIX_SHADER_QUIET (4 polls of 2 s), REMIX_SHADER_GRACE (15 s)."""
import os, subprocess, sys, time

W = int(os.environ.get("SCREEN_W", 1280)); H = int(os.environ.get("SCREEN_H", 720))
BOX_W = 368
Y0 = H - 81                 # 639 at 720: the frame's top edge row; the box is 81 px tall (rows 639..719), flush with the bottom
BOX_H = H - Y0
GREY = 87

def grab(x, y, w, h):
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-video_size", f"{W}x{H}", "-i", os.environ.get("DISPLAY", ":99"),
                        "-frames:v", "1", "-vf", f"crop={w}:{h}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, timeout=20)
    return r.stdout if len(r.stdout) == w * h * 3 else None

def overlay_present():
    """True when the box's grey frame is in the picture: the top edge row and the right edge column."""
    strip = grab(0, Y0, BOX_W, BOX_H)                  # rows Y0 .. H-1
    if strip is None: return None
    px = lambda x, row: strip[(row * BOX_W + x) * 3:(row * BOX_W + x) * 3 + 3]
    ok = lambda p: all(abs(c - GREY) <= 4 for c in p)
    top = sum(ok(px(x, 0)) for x in range(4, BOX_W - 4, 8))          # row 0 = Y0
    right = sum(ok(px(BOX_W - 1, r)) for r in range(6, BOX_H - 2, 6))
    return top >= 0.85 * len(range(4, BOX_W - 4, 8)) and right >= 0.85 * len(range(6, BOX_H - 2, 6))

def lit():
    """Mean (0..255) of the picture's centre, HUD excluded; None when the grab failed. A cold start passes through a dim, half-lit picture
    (mean ~14, the sun not in yet), black again for ~6 s, and only then the real scene (mean 85-90 by day); black is exactly 0."""
    x0, y0, w, h = W // 6, H // 5, W * 2 // 3, H * 5 // 8
    f = grab(x0, y0, w, h)
    if f is None: return None
    return sum(f[::53]) / (len(f[::53]) or 1)

mode = sys.argv[1] if len(sys.argv) > 1 else "gate"
cap = float(sys.argv[2]) if len(sys.argv) > 2 else float(os.environ.get("REMIX_SHADER_CAP", 600))
quiet = int(os.environ.get("REMIX_SHADER_QUIET", 4))
grace = float(os.environ.get("REMIX_SHADER_GRACE", 15))
t_start = time.time()
t0 = t_start
if os.path.exists("/out/.t0"):
    try: t0 = float(open("/out/.t0").read().strip())
    except ValueError: pass
seen = False; first_lit = None; absent = 0; litc = 0; brightc = 0; last = None
while True:
    now = time.time()
    if now - t_start > cap:
        msg = f"remix: shaders NOT ready after {now - t0:.0f} s (cap {cap:.0f} s; overlay still up)"
        print(msg, flush=True); open("/out/remix_shaders.txt", "a").write(msg + "\n"); sys.exit(1)
    o = overlay_present(); m = lit(); l = m is not None and m > 2.0
    if o: seen = True; absent = 0
    elif o is False: absent += 1
    litc = litc + 1 if l else 0                          # any picture (a dark night scene included)
    brightc = brightc + 1 if (m is not None and m >= 30.0) else 0   # a daylight scene
    if l and first_lit is None: first_lit = now
    if o != last and o is not None:
        print(f"remix: shader overlay {'up' if o else 'gone'} at {now - t0:.0f} s", flush=True); last = o
    # gate: the picture must be up, and the overlay (which appears a few seconds after the first lit frame) quiet
    # the grace (the box appears a few seconds after the first lit frame) only matters when the box was never seen: a warm cache
    # ready: the box gone, and the picture held: 3 polls (6 s) at daylight brightness, or 12 polls (24 s) of any picture (a night scene)
    if absent >= quiet and (brightc >= 3 or litc >= 12) and (mode != "gate" or seen or (first_lit is not None and now - first_lit >= grace)):
        msg = f"remix: shaders ready after {now - t0:.0f} s ({'compiled on screen' if seen else 'overlay never seen: warm cache'}; mode {mode})"
        print(msg, flush=True); open("/out/remix_shaders.txt", "a").write(msg + "\n")
        try: open("/out/.shaders_ready", "x").write(f"{now}\n")      # the earliest ready (gate or a keys script's recheck) marks the start of the played segment
        except FileExistsError: pass
        sys.exit(0)
    time.sleep(2)
