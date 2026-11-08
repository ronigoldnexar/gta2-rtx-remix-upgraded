#!/usr/bin/env python3
"""POLICE-3D contact sheet: out/police_3d_sheet.png from the probe runs (all game-driven
play on the L4 GPU build; the wanted level set through [devtools] force_wanted, everything
after it the game's own doing). Each tile is a crop of a 1280x720 frame with a caption.
    pol_sheet.py <out dir> [tiles.json]
tiles.json (optional) replaces ROWS: [[title, [[path, [x0,y0,x1,y1], caption], ...]], ...]"""
import json, os, sys
from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
FULL = (0, 0, 1280, 720)
ROWS = [
    ("The arrest, game-driven (pol_arrest3): 2 stars via force_wanted, officers punch him down (state 8 sub 0x16) and the game busts him", [
        ("pol_arrest3/qa_a_037.png", (300, 120, 1180, 620), "officer at him, cop car beacons"),
        ("pol_arrest3/qa_a_040.png", (300, 120, 1180, 620), "BUSTED: up from the knock-down, hands up"),
        ("pol_arrest3/qa_a_042.png", (300, 120, 1180, 620), "hands up (handsup layer)"),
        ("pol_arrest3/qa_a_043.png", (300, 120, 1180, 620), "cuffed"),
        ("pol_arrest3/qa_a_044.png", (300, 120, 1180, 620), "cuffed, walking (led off)"),
        ("pol_arrest6/qa_a_046.png", (200, 80, 1180, 620), "pol_arrest6: hands up among officers"),
    ]),
    ("Police lights and the army (6 stars via force_wanted): tanks, turrets, cannon fire", [
        ("pol_arrest3/qa_a_037.png", (700, 280, 1100, 500), "cop car roof beacon (siren delta 16)"),
        ("pol_army1/qa_tank10_03.png", None, "army tanks and soldiers arrive"),
        ("pol_army1/qa_tank10_04.png", None, "a tank fires at him"),
        ("pol_rescue1/qa_r17_01_05.png", (500, 0, 1280, 560), "tank turret turned off the hull"),
        ("pol_rescue1/qa_r17_01_10.png", (0, 0, 1280, 720), "turret aimed at the player (left)"),
        ("pol_veh3/qa_tank03_c.png", None, "classic view: the game's turret sprites"),
    ]),
    ("Other vehicles and fire", [
        ("pol_arrest6/qa_a_047.png", None, "bus (model 11) driving past the arrest"),
        ("pol_veh3/qa_tank03_04.png", (300, 200, 1280, 720), "tank shell's flame at the camera (1st person)"),
        ("pol_army2/qa_tank10_09.png", (700, 200, 1280, 720), "soldier with rifle (drawn flat yellow: bug)"),
        ("pol_veh6/qa_tr2_05.png", None, "elevated line from the street (no train caught)"),
    ]),
]
if len(sys.argv) > 2: ROWS = json.load(open(sys.argv[2]))
TW, TH, CAP, HEAD = 320, 200, 16, 22
cols = max(len(r[1]) for r in ROWS)
sheet = Image.new("RGB", (cols * TW, sum(HEAD + TH + CAP for _ in ROWS) + 30), (18, 18, 20))
d = ImageDraw.Draw(sheet)
d.text((6, 8), "POLICE-3D, 8 Nov 2026: third/first-person street views, L4 GPU build, game-driven (wanted level via [devtools] force_wanted). Generator linux/docker/pol_sheet.py", fill=(230, 230, 230))
y = 30
for title, tiles in ROWS:
    d.text((6, y + 5), title, fill=(255, 210, 90)); y += HEAD
    for i, (path, box, cap) in enumerate(tiles):
        p = os.path.join(OUT, path)
        if not os.path.exists(p):
            d.text((i * TW + 6, y + TH // 2), "missing: " + path, fill=(255, 80, 80)); continue
        im = Image.open(p).convert("RGB").crop(tuple(box or FULL))
        im.thumbnail((TW - 4, TH - 4))
        sheet.paste(im, (i * TW + (TW - im.width) // 2, y + (TH - im.height) // 2))
        d.text((i * TW + 4, y + TH), cap, fill=(220, 220, 220))
    y += TH + CAP
sheet.save(os.path.join(OUT, "police_3d_sheet.png"))
print(os.path.join(OUT, "police_3d_sheet.png"), sheet.size)
