#!/usr/bin/env python3
"""Turn-rate numbers from a camera_feel_test run.

Usage: camera_feel_rates.py <gta2dx9.log> <marks.json> [label]
For every captured phase (wall-clock window from the marks) prints the player's
heading change, the camera's peak and mean rate while turning (from the
per-frame `cam:` lines when the build logged them, else from the half-second
`view: player face=` samples) and how long the camera took to settle.
"""
import json, math, re, sys, time

log, marks = sys.argv[1], sys.argv[2]
label = sys.argv[3] if len(sys.argv) > 3 else ""
M = json.load(open(marks))
day = None

def tsec(h, m, s):
    return int(h) * 3600 + int(m) * 60 + float(s)

cam, face = [], []
for l in open(log, errors="replace"):
    m = re.match(r'\[(\d+):(\d+):([\d.]+)\] cam: (\w+) yaw=([-\d.]+) heading=([-\d.]+) rate=([-\d]+) dt=([\d.]+)', l)
    if m:
        cam.append((tsec(*m.groups()[:3]), m.group(4), float(m.group(5)), float(m.group(6)), float(m.group(7)), float(m.group(8))))
        continue
    m = re.search(r'\[(\d+):(\d+):([\d.]+)\].*view: player x=.*face=([-\d.]+),([-\d.]+)', l)
    if m:
        face.append((tsec(*m.groups()[:3]), math.degrees(math.atan2(float(m.group(4)), float(m.group(5))))))

def wrap(d):
    return (d + 180.0) % 360.0 - 180.0

out = []
for name, (t0, dur) in M.items():
    # marks are epoch seconds; the log is local time of day (the container is UTC, like the host)
    tod = time.gmtime(t0); a = tod.tm_hour * 3600 + tod.tm_min * 60 + tod.tm_sec + (t0 % 1); b = a + dur
    seg = [c for c in cam if a <= c[0] <= b]
    fs = [f for f in face if a - 1 <= f[0] <= b + 1]
    head = sum(abs(wrap(q[1] - p[1])) for p, q in zip(fs, fs[1:]))
    line = f"{label} {name}: player heading change {head:.0f} deg over {dur} s"
    if seg:
        rates = [abs(c[4]) for c in seg]
        turning = [r for r in rates if r > 5]
        peak = max(rates); mean = sum(turning) / len(turning) if turning else 0.0
        # settle: last frame with |rate| > 10 deg/s
        last = max((c[0] for c in seg if abs(c[4]) > 10), default=seg[0][0])
        first = min((c[0] for c in seg if abs(c[4]) > 10), default=seg[0][0])
        camturn = sum(abs(wrap(q[2] - p[2])) for p, q in zip(seg, seg[1:]))
        steps = [abs(wrap(q[2] - p[2])) for p, q in zip(seg, seg[1:])]
        big = sum(1 for d in steps if d > 4.0)
        line += f"; camera: {len(seg)} frames, peak {peak:.0f} deg/s, mean while turning {mean:.0f} deg/s, turn {camturn:.0f} deg over {last - first:.2f} s, largest step {max(steps) if steps else 0:.1f} deg, frames over 4 deg: {big}"
    else:
        rates = [abs(wrap(q[1] - p[1])) / (q[0] - p[0]) for p, q in zip(fs, fs[1:]) if q[0] > p[0]]
        line += f"; no per-frame camera log; heading peak over sample intervals {max(rates) if rates else 0:.0f} deg/s"
    out.append(line)
print("\n".join(out))
