#!/usr/bin/env python3
"""hud_sheet.py <out.png> <run dir> [<run dir>...]: the MODERN HUD comparison sheet, one row per
moment, the game's own HUD (classic) on the left and the modern HUD on the right, same moment.
A moment is taken from the last run dir that has both of its frames."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

MOMENTS = [("onfoot", "on foot"), ("brief_open", "mission text: the level's opening brief"), ("weapon", "weapon in hand"), ("phone", "by a phone"),
            ("timer", "mission clock"), ("lowhealth", "low health"),
           ("driving", "driving (chase)"), ("driving_first", "driving (first person)"),
           ("wanted", "wanted (third)"), ("wanted_first", "wanted (first person)")]

def main():
    out, runs = sys.argv[1], sys.argv[2:]
    W, H = 800, 450
    rows = []
    for k, lab in MOMENTS:
        have = [r for r in runs if os.path.exists(f"{r}/t_{k}_modern.png") and os.path.exists(f"{r}/t_{k}_classic.png")]
        if have: rows.append((k, f"{lab}  [{os.path.basename(have[-1].rstrip('/'))}]", have[-1]))
    head = 60
    sheet = Image.new("RGB", (W * 2 + 30, head + len(rows) * (H + 34)), (16, 18, 24))
    d = ImageDraw.Draw(sheet)
    try:
        big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((10, 16), "classic HUD (the game's own)", font=big, fill=(230, 230, 230))
    d.text((W + 20, 16), "modern HUD ([hud] modern=1)", font=big, fill=(255, 206, 32))
    y = head
    for k, lab, run in rows:
        d.text((10, y + 6), lab, font=small, fill=(200, 200, 200))
        for i, kind in enumerate(("classic", "modern")):
            im = Image.open(f"{run}/t_{k}_{kind}.png").convert("RGB").resize((W, H), Image.LANCZOS)
            sheet.paste(im, (10 + i * (W + 10), y + 30))
        y += H + 34
    sheet.save(out)
    print(out, sheet.size, len(rows), "rows")

if __name__ == "__main__":
    main()
