#!/usr/bin/env python3
"""A capture of what the browser player sees: headless Chromium opens the play
container's noVNC page, the keys go through the page (noVNC's own keyboard
path, over its websocket), and the page is recorded as video.

Usage: novnc_capture.py <base url, e.g. http://127.0.0.1:6091> <out.mp4> <key script>
The key script is comma separated: "wait:2,v,down:ArrowLeft,wait:2,up:ArrowLeft,..."
(a bare key is a 0.3 s tap). Needs playwright in the venv named by $PW (default
~/.cache/pw-venv) with chromium installed.
"""
import os, shutil, subprocess, sys, tempfile, time
from playwright.sync_api import sync_playwright

base, out, script = sys.argv[1], sys.argv[2], sys.argv[3]
url = base.rstrip("/") + "/vnc.html?autoconnect=true&resize=scale&reconnect=true&show_dot=true&quality=5&compression=3"
vdir = tempfile.mkdtemp()
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=vdir, record_video_size={"width": 1280, "height": 720})
    pg = ctx.new_page()
    pg.goto(url)
    time.sleep(7)   # connected and the first frame up (the canvas has no visible box to wait on)
    pg.mouse.click(640, 360)   # focus the canvas so the keys go to the game
    t0 = time.time()
    for step in script.split(","):
        step = step.strip()
        if not step: continue
        if step.startswith("wait:"): time.sleep(float(step[5:]))
        elif step.startswith("down:"): pg.keyboard.down(step[5:])
        elif step.startswith("up:"): pg.keyboard.up(step[3:])
        else: pg.keyboard.down(step); time.sleep(0.3); pg.keyboard.up(step)
    print("keys done after %.1f s" % (time.time() - t0), flush=True)
    ctx.close()
    b.close()
webm = [f for f in os.listdir(vdir) if f.endswith(".webm")][0]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(vdir, webm), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out], check=True)
shutil.rmtree(vdir)
print(out)
