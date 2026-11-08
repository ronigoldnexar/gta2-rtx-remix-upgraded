#!/usr/bin/env python3
"""CAMERA-PROPS sheet: before/after frames of the camprops.py probe and the mouse-look yaw plot
(PIL only).
  cpr_sheet.py <before run dir> <after run dir> <out.png> [pairs]
pairs: comma-separated frame tags (the part after cpr_, without .png), shown before | after."""
import re, sys
from PIL import Image, ImageDraw, ImageFont

before, after, out = sys.argv[1:4]
pairs = (sys.argv[4] if len(sys.argv) > 4 else "booth_s08_b,shop_away_b,shop_wall_b").split(",")
FOOT = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\] foot: yaw=(-?[\d.]+) target=(-?[\d.]+) heading=(-?[\d.]+)")
FRAMING = re.compile(r"framing third on foot frames=(\d+) head_in=(\d+) head_seen=(\d+)")
W, H = 640, 360
try:
    FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    SMALL = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
except OSError:
    FONT = SMALL = ImageFont.load_default()


def secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def marks(run):
    res = []
    for line in open(f"{run}/marks.txt"):
        t, what = line.split(" ", 1)
        if t.count(":") != 2: continue   # tour_lib's own marks (epoch seconds)
        h, m, rest = t.split(":"); s, ms = rest.split(".")
        res.append((secs(h, m, s, ms), what.strip()))
    return res


def yaw_series(run):
    mk = marks(run)
    t0 = next(t for t, w in mk if w == "walk start")
    t1 = next(t for t, w in mk if w == "mouse end")
    pts = []
    for line in open(f"{run}/gta2dx9.log", encoding="latin-1"):
        m = FOOT.match(line)
        if not m: continue
        t = secs(*m.group(1, 2, 3, 4))
        if t0 - 0.5 <= t <= t1 + 0.5:
            pts.append((t - t0, (float(m.group(5)) - float(m.group(7)) + 180.0) % 360.0 - 180.0))
    windows = []
    for t, w in mk:
        mm = re.match(r"mouse (\w+) start", w)
        if mm:
            stop = next(tt for tt, ww in mk if ww == f"mouse {mm.group(1)} stop" and tt >= t)
            windows.append((t - t0, stop - t0, mm.group(1)))
    stop = next((t - t0 for t, w in mk if w == "walk stop"), None)
    return pts, windows, stop


def framing(run):
    """the last count logged before the probe ended (the game idles on after it)"""
    last = None
    try:
        end = next(t for t, w in marks(run) if w == "mouse end")
        for line in open(f"{run}/gta2dx9.log", encoding="latin-1"):
            m = FRAMING.search(line)
            if m and secs(*re.match(r"^\[(\d\d):(\d\d):(\d\d)\.(\d\d\d)\]", line).groups()) <= end:
                last = tuple(int(x) for x in m.groups())
    except (OSError, StopIteration):
        pass
    return last


rows = len(pairs)
plot_h = 380
sheet = Image.new("RGB", (2 * W + 30, 50 + rows * (H + 34) + plot_h + 60), "white")
d = ImageDraw.Draw(sheet)
fa = framing(after)
d.text((10, 10), "CAMERA-PROPS: before (left) / after (right)" +
       (f"   after: head in frame {fa[1]}/{fa[0]}, also not behind a wall {fa[2]}/{fa[0]} (on-foot chase frames)" if fa else ""),
       fill="black", font=FONT)
y = 50
for tag in pairs:
    for j, run in enumerate((before, after)):
        x = 10 + j * (W + 10)
        try:
            im = Image.open(f"{run}/cpr_{tag}.png").convert("RGB").resize((W, H))
            sheet.paste(im, (x, y + 24))
        except OSError:
            d.text((x + 20, y + 120), "missing", fill="red", font=FONT)
        d.text((x, y + 2), f"{'before' if j == 0 else 'after'}: {tag}", fill="black", font=FONT)
    y += H + 34

# the yaw plot
px0, py0, pw, ph = 70, y + 30, 2 * W - 80, plot_h - 70
d.text((10, y + 4), "Mouse look with the soft follow (walking, then standing): camera yaw minus his heading, degrees. "
       "Yellow: mouse moving; pale: the 1.5 s the follow waits", fill="black", font=SMALL)
series = []
# the after run only: in the before run (cpr_before2) the walk did not start (speed 0), so its
# mouse phase is a standing one and not comparable
for run, colour in ((after, (31, 111, 180)),):
    try:
        series.append((run, colour) + yaw_series(run))
    except (OSError, StopIteration):
        pass
if series:
    tmax = max(p[0] for s in series for p in s[2]) if any(s[2] for s in series) else 20.0
    vals = [p[1] for s in series for p in s[2]] or [0.0]
    vmin, vmax = min(vals + [-5.0]) - 3, max(vals + [5.0]) + 3
    X = lambda t: px0 + pw * max(0.0, t) / max(tmax, 1e-3)
    Y = lambda v: py0 + ph * (vmax - v) / (vmax - vmin)
    run, colour, pts, windows, stop = series[-1]
    for a, b, name in windows:
        d.rectangle([X(a), py0, X(b), py0 + ph], fill=(250, 225, 140))
        d.rectangle([X(b), py0, X(b + 1.5), py0 + ph], fill=(252, 243, 210))
        d.text((X(a) + 2, py0 + 2), f"mouse {name}", fill="black", font=SMALL)
    if stop is not None:
        d.line([X(stop), py0, X(stop), py0 + ph], fill=(80, 80, 80), width=1)
        d.text((X(stop) + 3, py0 + ph - 18), "he stops", fill="black", font=SMALL)
    d.rectangle([px0, py0, px0 + pw, py0 + ph], outline="black")
    for v in range(int(vmin) // 10 * 10, int(vmax) + 1, 10):
        if vmin <= v <= vmax:
            d.line([px0 - 4, Y(v), px0, Y(v)], fill="black"); d.text((px0 - 40, Y(v) - 8), f"{v}", fill="black", font=SMALL)
    for t in range(0, int(tmax) + 1, 2):
        d.line([X(t), py0 + ph, X(t), py0 + ph + 4], fill="black"); d.text((X(t) - 6, py0 + ph + 6), f"{t}", fill="black", font=SMALL)
    d.text((px0 + pw // 2 - 120, py0 + ph + 24), "seconds since he started walking", fill="black", font=SMALL)
    for i, (run, colour, pts, windows, stop) in enumerate(series):
        if len(pts) > 1:
            d.line([(X(t), Y(v)) for t, v in pts], fill=colour, width=3)
        d.text((px0 + pw - 330, py0 + 8 + 18 * i), f"{'before' if run == before else 'after'}: {run.rstrip('/').split('/')[-1]}",
               fill=colour, font=SMALL)
sheet.save(out)
print("wrote", out)
