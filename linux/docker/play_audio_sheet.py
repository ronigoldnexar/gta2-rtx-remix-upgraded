#!/usr/bin/env python3
"""Sheet for the play page's game audio: the page with its audio bar, the page's packet/latency
log, the beep latency, server CPU and the waveform of the 10 s recorded on the client side.
  play_audio_sheet.py <test out dir> <sheet.png> [<second out dir> <its label>]   (matplotlib + numpy)
"""
import json, os, re, sys, wave
import numpy as np
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

d, out = sys.argv[1], sys.argv[2]
d2, lab2 = (sys.argv[3], sys.argv[4]) if len(sys.argv) > 4 else (None, None)
summ = json.load(open(os.path.join(d, "summary.json")))
w = wave.open(os.path.join(d, "client_10s.wav")); sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels()).astype(float) / 32768
log = [l.rstrip() for l in open(os.path.join(d, "audio_log.txt"))]
cpu = open(os.path.join(d, "cpu.txt")).read().strip()

fig = plt.figure(figsize=(16, 13), dpi=100, facecolor="white")
gs = fig.add_gridspec(3, 2, height_ratios=[1.25, 1, 0.8], hspace=0.32, wspace=0.12)
ax = fig.add_subplot(gs[0, 0]); ax.imshow(plt.imread(os.path.join(d, "page.png"))); ax.axis("off")
ax.set_title("The page after Play: noVNC in a frame, audio bar top right (mute, volume, codec, latency)", fontsize=11)
# page counters over time
rows = []
for l in log:
    m = re.search(r"pkts=(\d+) dec=(\d+).*?buf=(\d+)ms transit=([\d.\-]+)ms out=(\d+)ms latency~(\d+|null)ms", l)
    if m and m.group(6) != "null": rows.append([float(m.group(i)) for i in (1, 2, 3, 4, 5, 6)])
r = np.array(rows) if rows else np.zeros((0, 6))
ax = fig.add_subplot(gs[0, 1])
if len(r):
    t = np.arange(len(r))
    ax.plot(t, r[:, 5], label="page's latency estimate (20 + transit + buffer + output)", color="#c0392b")
    ax.plot(t, r[:, 2], label="jitter buffer", color="#2980b9"); ax.plot(t, r[:, 3], label="transit (server stamp -> worker)", color="#7f8c8d", lw=0.8)
    ax.axhline(300, ls="--", color="k", lw=0.8); ax.text(0, 305, "300 ms target", fontsize=8)
    ax2 = ax.twinx(); ax2.plot(t, r[:, 0], color="#27ae60", lw=1.2, label="packets received"); ax2.plot(t, r[:, 1], color="#27ae60", ls=":", lw=1.2, label="packets decoded")
    ax2.set_ylabel("packets (cumulative)"); ax2.legend(loc="center right", fontsize=8)
ax.set_ylim(0, 600); ax.set_xlabel("s since Play"); ax.set_ylabel("ms"); ax.legend(loc="upper left", fontsize=8)
p = summ["page"]
ax.set_title("Page counters (window.playAudio, once a second): %d packets, %d decoded, %d late, %d decoder-behind, %d underruns"
             % (p["packets"], p["decoded"], p.get("late", 0), p.get("behind", 0), p["underruns"]), fontsize=10)
# waveform
ax = fig.add_subplot(gs[1, :])
tt = np.arange(len(x)) / sr
ax.plot(tt, x[:, 0], lw=0.3, color="#34495e")
rms = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12); peak = 20 * np.log10(np.max(np.abs(x)) + 1e-12)
ax.set_xlim(0, tt[-1] if len(tt) else 10); ax.set_ylim(-1, 1); ax.set_xlabel("s")
ax.set_title("Client side: 10 s the browser played, recorded with ffmpeg from its sound server (left channel; RMS %.1f dBFS, peak %.1f dBFS, volume 100)" % (rms, peak), fontsize=11)
# text: latency, cpu, log tail
ax = fig.add_subplot(gs[2, 0]); ax.axis("off")
lat = summ["latency_ms"]
txt = "End-to-end latency, 5 kHz beeps into the game's null sink,\ntimed at the game sink's monitor and at the client sound server:\n  %s ms" % (", ".join("%.0f" % v for v in lat) or "none matched")
if lat: txt += "  (median %.0f)" % np.median(lat)
if d2:
    s2 = json.load(open(os.path.join(d2, "summary.json")))["latency_ms"]
    txt += "\n  %s: %s ms" % (lab2, ", ".join("%.0f" % v for v in s2) or "none matched")
txt += "\n\nServer CPU with one listener (20 s, container processes):\n" + "\n".join("  " + l for l in cpu.splitlines())
ax.text(0, 1, txt, va="top", family="monospace", fontsize=9.5)
ax = fig.add_subplot(gs[2, 1]); ax.axis("off")
tail = [l for l in log if "pkts=" in l][-14:]
ax.text(0, 1, "Page log (last lines)\n" + "\n".join(re.sub(r"^\S+ ", "", l)[:118] for l in tail), va="top", family="monospace", fontsize=7.2)
fig.suptitle("GTA2 3D play page: game audio (PulseAudio null sink -> parec -> Opus -> websocket /audio on the page's port -> WebCodecs -> AudioWorklet)", fontsize=13, y=0.995)
fig.savefig(out, bbox_inches="tight"); print(out)
