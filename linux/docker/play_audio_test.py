#!/usr/bin/env python3
"""Check the play page's game audio from the client side.

  play_audio_test.py <base url> <play container> <out dir> [audio-only]

(audio-only: the same player started without the noVNC frame, to time the audio path
without the test browser's own software video decoding competing for the CPU)

A helper container (gta2-audio-client, same image, CPUs 0-4) runs a PulseAudio server with one
sink, "client", whose socket is shared with the host; headless Chromium (playwright venv) is
started with PULSE_SERVER pointing at it, so the page's sound really plays out of a sound
server and can be recorded there, as a speaker would get it.
  - opens <base>/, clicks Play (the click starts the audio), logs the page's counters once a
    second (packets, decoded, buffer, transit, latency estimate) -> audio_log.txt
  - latency, 5 beeps: a 5 kHz tone is played into the game container's null sink with pacat;
    the same detector times each onset at the game's sink monitor and at the client sink's
    monitor (both parec, same machine clock): latency = client onset - game-sink onset
  - 10 s of what the browser played, recorded with ffmpeg (-f pulse) -> client_10s.wav
  - CPU of the audio server, parec and websockify over 20 s -> cpu.txt
  - a screenshot of the page with the audio bar -> page.png;  summary.json
"""
import json, os, subprocess, sys, threading, time
from playwright.sync_api import sync_playwright

base, cont, out = sys.argv[1].rstrip("/"), sys.argv[2], os.path.abspath(sys.argv[3])
audio_only = len(sys.argv) > 4 and sys.argv[4] == "audio-only"
CLIENT = "gta2-audio-client"
share = os.path.join(out, "pulse"); os.makedirs(share, exist_ok=True)
log = open(os.path.join(out, "audio_log.txt"), "w")

REC = r'''
import json, subprocess, sys, time
import numpy as np
dev, secs = sys.argv[1], float(sys.argv[2])
p = subprocess.Popen(["parec", "--device=" + dev, "--format=s16le", "--rate=48000", "--channels=2", "--latency-msec=10", "--raw"], stdout=subprocess.PIPE, bufsize=0)
B = 1920; blocks = []; times = []; end = time.time() + secs; buf = b""
while time.time() < end:
    d = p.stdout.read(B)
    if not d: break
    buf += d
    while len(buf) >= B: blocks.append(buf[:B]); buf = buf[B:]; times.append(time.time() * 1000)
p.kill()
x = np.frombuffer(b"".join(blocks), "<i2").reshape(-1, 2)[:, 0].astype(np.float64)
k = np.arange(len(times)); t = np.array(times)
t0 = np.min(t - 10.0 * k)                      # earliest arrival = least scheduling delay: block k ends at t0 + 10 k
W, H = 96, 24; ref = np.exp(-2j * np.pi * 5000 / 48000 * np.arange(W))
onsets = []; last = -1e9
for s in range(0, len(x) - W, H):
    w = x[s:s + W]; e = float(np.sum(w * w)) + 1.0
    frac = abs(np.dot(w, ref)) ** 2 / (W / 2 * e); rms = (e / W) ** 0.5
    ts = t0 + (s + W / 2) / 48.0 - 10.0        # the window's centre on the wall clock
    if frac > 0.5 and rms > 1500 and ts - last > 600: onsets.append(ts); last = ts
print(json.dumps({"onsets": onsets, "blocks": len(times), "rms_db": 20 * np.log10(max(1.0, float(np.sqrt(np.mean(x * x)))) / 32768)}))
'''
INJECT = r'''
import math, struct, subprocess, time
p = subprocess.Popen(["pacat", "--device=null", "--format=s16le", "--rate=48000", "--channels=1", "--latency-msec=20", "--raw"], stdin=subprocess.PIPE, bufsize=0)
sil = b"\0" * 960
tone = b"".join(struct.pack("<h", int(20000 * math.sin(2 * math.pi * 5000 * i / 48000))) for i in range(4800))
t0 = time.time(); n = 0
def w(b):
    global n
    p.stdin.write(b); n += 1; time.sleep(max(0, t0 + n * 0.01 - time.time()))
for r in range(5):
    for _ in range(100): w(sil)
    for k in range(10): w(tone[k * 960:(k + 1) * 960])
for _ in range(100): w(sil)
p.stdin.close(); p.wait()
'''
CPU = r'''
import os, time
me = str(os.getpid())
def cmd(pid):
    try: return open("/proc/%s/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(errors="replace")
    except OSError: return ""
def stat(pid):
    try: return open("/proc/%s/stat" % pid).read().rsplit(")", 1)[1].split()
    except OSError: return None
groups = {"audio server (capture + opus)": [], "parec": [], "websockify (page, VNC and audio relay)": []}
pids = [p for p in os.listdir("/proc") if p.isdigit() and p != me]
for p in pids:
    c = cmd(p)
    if "play_audio.py serve" in c: groups["audio server (capture + opus)"].append(p)
    elif c.startswith("parec --device=null.monitor"): groups["parec"].append(p)
    elif "play_audio.py web" in c: groups["websockify (page, VNC and audio relay)"].append(p)
def ticks(ps):
    s = 0
    for p in ps:
        f = stat(p)
        if f: s += int(f[11]) + int(f[12])
    return s
a = {g: ticks(ps) for g, ps in groups.items()}
T = 20; time.sleep(T); hz = os.sysconf("SC_CLK_TCK"); tot = 0
for g, ps in groups.items():
    v = 100.0 * (ticks(ps) - a[g]) / hz / T; tot += v
    print("%-40s %5.1f %% of one core" % (g, v))
print("%-40s %5.1f %% of one core" % ("total", tot))
'''

def dx(c, code, *args, env="XDG_RUNTIME_DIR=/tmp/xdg-runtime"):
    return subprocess.run(["docker", "exec", "-e", env, c, "python3", "-c", code, *args], capture_output=True, text=True, check=True).stdout.strip()

subprocess.run(["docker", "rm", "-f", CLIENT], capture_output=True)
subprocess.run(["docker", "run", "-d", "--name", CLIENT, "--cpuset-cpus=0-4", "-v", share + ":/s", "--entrypoint", "bash", "gta2-play-audio", "-c",
                "umask 000; export XDG_RUNTIME_DIR=/tmp/x; mkdir -p /tmp/x; exec pulseaudio --daemonize=no --exit-idle-time=-1 --disallow-exit -n "
                "--load='module-null-sink sink_name=client' --load='module-native-protocol-unix auth-anonymous=1 socket=/s/pulse.sock'"], check=True, capture_output=True)
for _ in range(50):
    if os.path.exists(os.path.join(share, "pulse.sock")): break
    time.sleep(0.2)
CENV = "PULSE_SERVER=unix:/s/pulse.sock"
summary = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", ignore_default_args=["--mute-audio"], env=dict(os.environ, PULSE_SERVER="unix:" + os.path.join(share, "pulse.sock")),
                          args=["--autoplay-policy=user-gesture-required"])
    pg = b.new_page(viewport={"width": 1280, "height": 760})
    pg.goto(base + "/"); time.sleep(1.5)
    pg.evaluate("() => localStorage.setItem('gta2_vol', '100')")
    if audio_only: pg.click("h1"); pg.evaluate("() => { startAudio(); }")
    else: pg.click("#playlink")
    time.sleep(12)
    st = pg.evaluate("() => { const A = window.playAudio; return {state: A.state, codec: A.codec, packets: A.packets, decoded: A.decoded, errors: A.errors}; }")
    print("after start:", st, flush=True)
    # latency: record both monitors while the beeps play
    res = {}
    def rec(name, c, dev, env): res[name] = json.loads(dx(c, REC, dev, "11", env=env))
    th = [threading.Thread(target=rec, args=("game", cont, "null.monitor", "XDG_RUNTIME_DIR=/tmp/xdg-runtime")),
          threading.Thread(target=rec, args=("client", CLIENT, "client.monitor", CENV))]
    for t in th: t.start()
    time.sleep(0.3); dx(cont, INJECT)
    for t in th: t.join()
    g, c = res["game"]["onsets"], res["client"]["onsets"]
    lat = []
    for tg in g:
        m = [tc - tg for tc in c if 0 < tc - tg < 1500]
        if m: lat.append(round(min(m), 1))
    print("beeps at the game sink: %d, at the client: %d; latency ms: %s" % (len(g), len(c), lat), flush=True)
    log.write("latency (game sink monitor -> client sound server), ms: %s\n" % lat)
    summary["latency_ms"] = lat
    # 10 s from the client's sound server
    wav = "/s/client_10s.wav"
    subprocess.run(["docker", "exec", "-e", CENV, CLIENT, "ffmpeg", "-y", "-loglevel", "error", "-f", "pulse", "-i", "client.monitor", "-t", "10", "-ac", "2", "-ar", "48000", wav], check=True)
    os.replace(os.path.join(share, "client_10s.wav"), os.path.join(out, "client_10s.wav"))
    # the mute button: the client's level with the sound muted, then unmuted again
    LVL = "timeout 2 parec --device=client.monitor --raw --format=s16le --channels=1 --rate=48000 | python3 -c 'import sys,array,math; a=array.array(\"h\"); a.frombytes(sys.stdin.buffer.read()); print(round(20*math.log10(max(1,math.sqrt(sum(x*x for x in a)/max(1,len(a))))/32768),1))'"
    lvl = lambda: float(subprocess.run(["docker", "exec", "-e", CENV, CLIENT, "bash", "-c", LVL], capture_output=True, text=True).stdout.strip() or "nan")
    pg.click("#amute"); time.sleep(0.5); m = lvl(); pg.click("#amute"); time.sleep(0.5); u = lvl()
    summary["mute_check_dbfs"] = {"muted": m, "unmuted": u}
    print("client level muted %.1f dBFS, unmuted %.1f dBFS" % (m, u), flush=True); log.write("mute check: muted %.1f dBFS, unmuted %.1f dBFS\n" % (m, u))
    cpu = dx(cont, CPU); open(os.path.join(out, "cpu.txt"), "w").write(cpu + "\n"); print(cpu, flush=True)
    st = pg.evaluate("() => { const A = window.playAudio; return {packets: A.packets, decoded: A.decoded, late: A.late, behind: A.behind, errors: A.errors, underruns: A.underruns, dropped_samples: A.dropped, bufferMs: A.bufferMs, transitMs: A.transitMs, outMs: A.outMs, latencyMs: A.latencyMs, log: A.log.slice()}; }")
    for line in st.pop("log"): log.write(line + "\n")
    summary["page"] = st
    pg.mouse.move(1200, 20); time.sleep(0.5)
    pg.screenshot(path=os.path.join(out, "page.png"))
    b.close()
subprocess.run(["docker", "rm", "-f", CLIENT], capture_output=True)
json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
print(json.dumps(summary))
