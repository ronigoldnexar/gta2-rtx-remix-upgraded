#!/usr/bin/env python3
"""VEHICLE-FEEL comparison sheet: before (vehicle_feel=0) | after (=1) strips per manoeuvre,
from the frames vehfeel_take.py grabs (out/<run>/vf_<phase>_<variant>_<item>_<i>.png).
    vehfeel_sheet.py <run dir> <out png> [row=before_idx,before_idx,...:after_idx,...] ...
Each row takes up to three frames of each variant; the default picks are spread over the burst."""
import glob, os, sys
from PIL import Image, ImageDraw, ImageFont

RUN, OUT = sys.argv[1], sys.argv[2]
ROWS = [
    ("turn", "day", "turn", "turn: body roll out of the bend, front wheels steered"),
    ("brake", "day", "brake", "brake: nose dives, brake lamps"),
    ("kerb", "day", "kerb", "kerb runs: bounce as a wheel crosses road <-> pavement"),
    ("night_brake", "night", "brake", "night: head-lamp pools on the road, brake lamps"),
    ("night_reverse", "night", "reverse", "night: reverse lamps (white) with the brake lamps"),
    ("night_idle", "night", "idle", "night idle: exhaust puffs"),
    ("handbrake", "day", "handbrake", "handbrake turn: tyre smoke and skid marks"),
    ("scrape", "day", "scrape", "wall hits and scrapes: sparks"),
    ("wreck", "wreck", "blown", "blown up: debris, a wheel off, the wreck sitting on its hubs"),
]
picks = {}
for a in sys.argv[3:]:
    k, v = a.split("=", 1)
    b, f = v.split(":")
    picks[k] = ([int(x) for x in b.split(",") if x], [int(x) for x in f.split(",") if x])
TW, TH = 400, 225          # tile
CROP = (160, 120, 1120, 660)   # the car in the chase view, 16:9
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
except OSError:
    font = big = ImageFont.load_default()


def frames(phase, variant, item):
    fs = glob.glob(os.path.join(RUN, f"vf_{phase}_{variant}_{item}_*.png"))
    return sorted(fs, key=lambda f: int(f.rsplit("_", 1)[1][:-4]))


def choose(fs, idx):
    if idx: return [fs[i] for i in idx if i < len(fs)][:3]
    if len(fs) <= 3: return fs
    n = len(fs)
    return [fs[int(round(i * (n - 1) / 2))] for i in range(3)]


GAP, HEAD, LABEL = 6, 46, 24
W = 6 * TW + 7 * GAP + 12
H = HEAD + len(ROWS) * (TH + LABEL + GAP) + GAP
sheet = Image.new("RGB", (W, H), (18, 18, 20))
d = ImageDraw.Draw(sheet)
d.text((GAP, 10), "Vehicle feel: before (left, vehicle_feel=0) | after (right, vehicle_feel=1)", fill=(240, 240, 240), font=big)
y = HEAD
for key, phase, item, caption in ROWS:
    b_idx, a_idx = picks.get(key, ([], []))
    d.text((GAP, y + 3), caption, fill=(250, 214, 90), font=font)
    y += LABEL
    for col, (variant, idx) in enumerate((("before", b_idx), ("after", a_idx))):
        fs = choose(frames(phase, variant, item), idx)
        for k, f in enumerate(fs):
            try:
                im = Image.open(f).convert("RGB").crop(CROP).resize((TW, TH), Image.LANCZOS)
            except OSError:
                continue
            x = GAP + (col * 3 + k) * (TW + GAP) + (12 if col else 0)
            sheet.paste(im, (x, y))
    d.line([(GAP + 3 * (TW + GAP) + 3, y), (GAP + 3 * (TW + GAP) + 3, y + TH)], fill=(250, 214, 90), width=3)
    y += TH + GAP
sheet.save(OUT)
print(OUT, sheet.size)
