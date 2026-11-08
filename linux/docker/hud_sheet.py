#!/usr/bin/env python3
"""hud_sheet.py <run dir> <out.png>: the MODERN HUD comparison sheet, one row per moment,
the game's own HUD (classic) on the left and the modern HUD on the right, same moment."""
import os, sys
from PIL import Image, ImageDraw, ImageFont

MOMENTS = [("onfoot", "on foot"), ("weapon", "weapon in hand"), ("phone", "by a phone"),
           ("brief", "mission text"), ("timer", "mission clock"), ("lowhealth", "low health"),
           ("driving", "driving (chase)"), ("driving_first", "driving (first person)"),
           ("wanted", "wanted (third)"), ("wanted_first", "wanted (first person)")]

def main():
    run, out = sys.argv[1], sys.argv[2]
    W, H = 800, 450
    rows = [(k, lab) for k, lab in MOMENTS
            if os.path.exists(f"{run}/t_{k}_modern.png") and os.path.exists(f"{run}/t_{k}_classic.png")]
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
    for k, lab in rows:
        d.text((10, y + 6), lab, font=small, fill=(200, 200, 200))
        for i, kind in enumerate(("classic", "modern")):
            im = Image.open(f"{run}/t_{k}_{kind}.png").convert("RGB").resize((W, H), Image.LANCZOS)
            sheet.paste(im, (10 + i * (W + 10), y + 30))
        y += H + 34
    sheet.save(out)
    print(out, sheet.size, len(rows), "rows")

if __name__ == "__main__":
    main()
