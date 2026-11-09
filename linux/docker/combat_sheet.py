#!/usr/bin/env python3
"""ANIM-COMBAT sheet: for each blow that landed in a combat_probe run (the log's
'fig: contact' lines, wall clock), the burst frames from PRE s before to POST s after
it, cropped around the middle of the screen, in a labelled strip; the strips stacked.

    combat_sheet.py <out/run> <sheet.png> [max_strips] [pre] [post] [crop_w] [crop_h] [kinds]

kinds: a comma list of the contact sides to keep (0 cross, 1 jab, 6 kick, 7 stomp;
default all). Frame times are burst start + index / fps (x11grab; a loaded host can
drop and bunch frames: each frame is timed by its file's write time)."""
import datetime, os, re, sys
from PIL import Image, ImageDraw

run, out = sys.argv[1], sys.argv[2]
maxn = int(sys.argv[3]) if len(sys.argv) > 3 else 6
pre = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
post = float(sys.argv[5]) if len(sys.argv) > 5 else 0.8
cw = int(sys.argv[6]) if len(sys.argv) > 6 else 300
ch = int(sys.argv[7]) if len(sys.argv) > 7 else 330
kinds = set(int(k) for k in sys.argv[8].split(",")) if len(sys.argv) > 8 else None

bursts = []
for line in open(os.path.join(run, "combat_marks.txt")):
    lab, t, fps = line.split()
    files = sorted(f for f in os.listdir(run) if f.startswith(f"cb_{lab}_") and f.endswith(".png"))
    bursts.append((lab, float(t), int(fps), files))

day = None
CONTACT = re.compile(r"^\[(\d+):(\d+):(\d+)\.(\d+)\] fig: contact (\w+) by (\w+) side (\d+) push ([\d.]+) stop (\d+)")
events = []
log = open(os.path.join(run, "gta2dx9.log"), encoding="latin-1").read().splitlines()
# The log's clock is the container's wall clock (UTC), the marks are epoch seconds.
t0 = bursts[0][1] if bursts else 0
base = datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
for line in log:
    m = CONTACT.match(line)
    if not m: continue
    t = base + int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) + int(m[4]) / 1000.0
    side = int(m[7])
    if kinds is not None and side not in kinds: continue
    events.append((t, m[5], m[6], side, float(m[8]), int(m[9])))

NAMES = {0: "cross", 1: "jab", 6: "kick", 7: "stomp"}
strips = []
for t, victim, striker, side, push, stop in events:
    for lab, bt, fps, files in bursts:
        # Each frame's time: its file's write time (x11grab on a loaded host drops and
        # bunches frames, so index / fps drifts by seconds over a burst).
        mt = [os.path.getmtime(os.path.join(run, f)) for f in files]
        if mt and mt[0] <= t <= mt[-1]:
            ic = min(range(len(mt)), key=lambda i: abs(mt[i] - t))
            i0 = min(range(len(mt)), key=lambda i: abs(mt[i] - (t - pre)))
            i1 = min(range(len(mt)), key=lambda i: abs(mt[i] - (t + post)))
            frames = []
            for i in range(max(0, i0), min(len(files), i1 + 1)):
                im = Image.open(os.path.join(run, files[i])).convert("RGB")
                W, H = im.size
                im = im.crop(((W - cw) // 2, (H - ch) // 2 + 30, (W + cw) // 2, (H + ch) // 2 + 30))
                frames.append((i, im))
            strips.append((f"{lab}: {NAMES.get(side, side)} by {striker} on {victim} (stop {stop}, push {push:.3f})", ic, [m - mt[ic] for m in mt], frames))
            break
    if len(strips) >= maxn: break

if not strips:
    print("no contact inside a burst"); sys.exit(1)
n = max(len(s[3]) for s in strips)
sheet = Image.new("RGB", (cw * n, (ch + 40) * len(strips)), (16, 16, 16))
dr = ImageDraw.Draw(sheet)
for r, (title, ic, rel, frames) in enumerate(strips):
    y = r * (ch + 40)
    dr.text((6, y + 4), title, fill=(255, 255, 0))
    for k, (i, im) in enumerate(frames):
        sheet.paste(im, (k * cw, y + 20))
        lab = f"{rel[i] * 1000:+.0f} ms"
        col = (255, 80, 80) if i == ic else (220, 220, 220)
        dr.text((k * cw + 6, y + 22), lab + ("  CONTACT" if i == ic else ""), fill=col)
        if i == ic: dr.rectangle([k * cw, y + 20, k * cw + cw - 1, y + 20 + ch - 1], outline=(255, 60, 60), width=3)
sheet.save(out)
print(f"{len(strips)} strip(s) of {len(events)} contact(s) -> {out}")
