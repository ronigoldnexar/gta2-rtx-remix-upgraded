#!/usr/bin/env python3
"""PERF-3: a browser player's VNC load on the play container, without a person: headless
Chromium opens the play container's noVNC page (the landing page's Play link: quality and
compression as given), stays connected for SECS and counts what arrives over the websocket
(messages, bytes) per second. Nothing is pressed; the drive comes from elsewhere.
Usage (the playwright venv, pinned off the player's CPUs):
  taskset -c 0-4 ~/.cache/pw-venv/bin/python perf3_vnc_client.py <base url> <secs> <out.json> [quality] [compression]"""
import json, signal, sys, time
from playwright.sync_api import sync_playwright

base, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
quality = sys.argv[4] if len(sys.argv) > 4 else "5"
compression = sys.argv[5] if len(sys.argv) > 5 else "3"
url = base.rstrip("/") + f"/vnc.html?autoconnect=true&resize=scale&reconnect=true&quality={quality}&compression={compression}"
per_sec = {}
stop = []
signal.signal(signal.SIGTERM, lambda *a: stop.append(1))   # the caller ends it when its drive is over
def on_ws(ws):
    def got(payload):
        k = int(time.time())
        n, b = per_sec.get(k, (0, 0))
        per_sec[k] = (n + 1, b + (len(payload) if payload else 0))
    ws.on("framereceived", got)
with sync_playwright() as p:
    b = p.chromium.launch(args=["--disable-gpu"])
    pg = b.new_page(viewport={"width": 1280, "height": 720})
    pg.on("websocket", on_ws)
    t0 = time.time()
    pg.goto(url)
    while time.time() - t0 < secs and not stop: pg.wait_for_timeout(250)   # pumps the event loop (time.sleep would hold the websocket events back)
    b.close()
ks = sorted(per_sec)
json.dump({"url": url, "secs": secs, "start": t0, "per_sec": [[k, *per_sec[k]] for k in ks],
           "msgs_per_s": sum(v[0] for v in per_sec.values()) / max(1, len(ks)),
           "kbytes_per_s": sum(v[1] for v in per_sec.values()) / 1024 / max(1, len(ks))}, open(out, "w"))
print(f"{url}: {len(ks)} s connected, {sum(v[0] for v in per_sec.values())} websocket messages, "
      f"{sum(v[1] for v in per_sec.values()) / 1048576:.1f} MB")
