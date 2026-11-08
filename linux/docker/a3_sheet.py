#!/usr/bin/env python3
"""ACTIONS-3D contact sheet: out/actions_3d_sheet.png from the probe runs
(out/a3w2, a3m3, a3f1, a3p1: game-driven play; a3s2: the clip showcase on the
player's figure). Each tile is a crop of a 1280x720 frame with a caption.
    a3_sheet.py <out dir>"""
import os, sys
from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
FIG = (440, 170, 840, 670)      # the third-person figure, close
WIDE = (200, 90, 1080, 690)
LOW = (240, 260, 1040, 720)     # a body lying at the foot of the frame
ROWS = [
    ("Game-driven play: the weapon is the game's (ped+0x170), a shot is its ammo/reload word changing", [
        ("a3w2/qa_w01_silenced_mg_carry_walk_side.png", WIDE, "silenced MG carried at low ready, walking"),
        ("a3w2/qa_w01_silenced_mg_fire_side_00.png", WIDE, "firing it: rifle stance, cases out"),
        ("a3w2/qa_w01_silenced_mg_settled_side.png", WIDE, "1 s after the burst: back to the carry"),
        ("a3w2/qa_w02_flamethrower_fire_side_00.png", WIDE, "flamethrower fired from the hip"),
        ("a3w2/qa_w03_molotov_carry_walk_side.png", WIDE, "molotov in the hand, walking"),
    ]),
    ("Game-driven play: throw, launcher, burning, falling", [
        ("a3w2/qa_w03_molotov_fire_side_01.png", WIDE, "the molotov throw"),
        ("a3m3/qa_m_rocket0_00.png", WIDE, "rocket launcher fired (launcher stance)"),
        ("a3m3/qa_m_blown1_00.png", WIDE, "player set alight by the blast: burn layer"),
        ("a3f1/qa_f_fall1_00.png", WIDE, "off the roof: state 8 sub 0x13 -> fall_air"),
        ("a3f1/qa_f_fall1_02.png", WIDE, "landed dead: lying clip (face down)"),
    ]),
    ("Clip showcase on the player's figure (GTA2DX9_FORCE_ACTION_FILE): carrying", [
        ("a3s3/qa_s_carry_mg_front.png", FIG, "carry_heavy (machine gun), front"),
        ("a3s3/qa_s_carry_mg_side.png", FIG, "carry_heavy (machine gun), side"),
        ("a3s2/qa_s_carry_shotgun_front.png", FIG, "carry_heavy (shotgun)"),
        ("a3s2/qa_s_carry_launcher_side.png", FIG, "carry_launcher"),
        ("a3s2/qa_s_carry_flame_front.png", FIG, "carry_flame"),
        ("a3s2/qa_s_carry_molotov_front.png", FIG, "carry (molotov)"),
    ]),
    ("Clip showcase: the stances", [
        ("a3s3/qa_s_aim_pistol_front.png", FIG, "aim (pistol)"),
        ("a3s2/qa_s_aim_dual_front.png", FIG, "aim_dual"),
        ("a3s2/qa_s_aim_mg_side.png", FIG, "aim_heavy (machine gun)"),
        ("a3s2/qa_s_aim_launcher_side.png", FIG, "aim_launcher"),
        ("a3s2/qa_s_aim_flame_front.png", FIG, "aim_flame"),
        ("a3s2/qa_s_aim_electro_side.png", FIG, "aim_heavy (electro gun)"),
    ]),
    ("Clip showcase: other actions", [
        ("a3s2/qa_s_throw_grenade_front.png", FIG, "throw (grenade)"),
        ("a3s2/qa_s_handsup_front.png", FIG, "handsup"),
        ("a3s2/qa_s_cuffed_back.png", FIG, "cuffed"),
        ("a3s2/qa_s_burn_front.png", FIG, "burn (layer over the run)"),
        ("a3s2/qa_s_fall_air_front.png", FIG, "fall_air"),
        ("a3s2/qa_s_drown_front.png", FIG, "drown (sunk as it runs)"),
    ]),
    ("Clip showcase: the lying clips, chosen by the game's damage cause", [
        ("a3s2/qa_s_dead_fall_back.png", LOW, "fall: onto the back (shot)"),
        ("a3s2/qa_s_dead_front_side.png", LOW, "fall_front: onto the face (shot)"),
        ("a3s2/qa_s_dead_runover_getup.png", LOW, "runover (car, cause 1/3), getting up"),
        ("a3s2/qa_s_dead_blown_side.png", LOW, "blown (explosion, cause 4)"),
        ("a3s2/qa_s_dead_burnt_getup.png", LOW, "burnt (fire), getting up"),
    ]),
]
TW, TH, CAP, HEAD = 300, 240, 16, 22
cols = max(len(r[1]) for r in ROWS)
sheet = Image.new("RGB", (cols * TW, sum(HEAD + TH + CAP for _ in ROWS) + 30), (18, 18, 20))
d = ImageDraw.Draw(sheet)
d.text((6, 8), "ACTIONS-3D, 8 Nov 2026: third-person street view (L4 GPU build). Runs out/a3w2 a3m3 a3f1 a3s2 a3s3; generator linux/docker/a3_sheet.py", fill=(230, 230, 230))
y = 30
for title, tiles in ROWS:
    d.text((6, y + 5), title, fill=(255, 210, 90)); y += HEAD
    for i, (path, box, cap) in enumerate(tiles):
        p = os.path.join(OUT, path)
        if not os.path.exists(p):
            d.text((i * TW + 6, y + TH // 2), "missing: " + path, fill=(255, 80, 80)); continue
        im = Image.open(p).convert("RGB").crop(box)
        im.thumbnail((TW - 4, TH - 4))
        sheet.paste(im, (i * TW + (TW - im.width) // 2, y + (TH - im.height) // 2))
        d.text((i * TW + 4, y + TH), cap, fill=(220, 220, 220))
    y += TH + CAP
sheet.save(os.path.join(OUT, "actions_3d_sheet.png"))
print(os.path.join(OUT, "actions_3d_sheet.png"), sheet.size)
