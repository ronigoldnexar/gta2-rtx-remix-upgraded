#!/usr/bin/env python3
"""GTA2's code objects (sprite base 4) as 3D models for the street-level views:
weapon pickups, the round power-up tokens, the pay phones, traffic-light heads
and the police helicopter. The game draws them as flat sprites; here each gets
a small model whose top is the sprite itself (so the top-down view is the
game's own art) and whose sides are built from the sprite's pixels. Pickups
are flagged to spin and float at run time ("objects_anim": "spin").

    python3 tools/gen_code_objects.py <assets-src dir> <out dir> [--sheet out/x.png]

Writes <out>/<name>.glb, status.json and manifest_fragment.json (models,
objects "4:<frame>" -> name, objects_anim). Reads assets-src/objects/
sprites_all/code_obj_NNN.png (RGBA, native size; 64 px = 1 block).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import trimesh
from trimesh.visual.material import PBRMaterial
from trimesh.visual import TextureVisuals

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_objects import Part, box_part, cylinder_part, scene_with, render, PX  # noqa: E402

CODE_OBJ_BASE = 4

# Frame groups. A pickup is drawn with 8 frames (the token turning over, or the
# weapon rotating); every frame of a group maps to the group's one model, whose
# top art is the fullest frame. Names are by inspection of the art.
WEAPONS = {  # first frame of each 8-frame rotation
    18: "pickup_pistol", 26: "pickup_dual_pistol", 34: "pickup_machine_gun", 42: "pickup_rocket_launcher",
    66: "pickup_shotgun", 82: "pickup_flamethrower", 90: "pickup_electro_gun",
}
TOKENS = {  # first frame (30x30) of each 8-frame turn
    151: "token_blue", 159: "token_orange", 167: "token_dollar", 175: "token_purple", 183: "token_green_x",
    191: "token_red_x", 199: "token_cyan", 207: "token_hand", 215: "token_yellow", 223: "token_navy",
    231: "token_bronze", 239: "token_gold", 286: "token_skull",
}
HEART = 143    # the health heart: frames 143..150 (not square, 16 px tall)
PHONE = [510, 511, 512]
LIGHTS = {549: ("light_red", (235, 40, 30)), 550: ("light_green", (60, 230, 70)), 551: ("light_amber", (245, 170, 40))}
HELI = 0


def load(src, frame):
    return Image.open(os.path.join(src, "objects", "sprites_all", f"code_obj_{frame:03d}.png")).convert("RGBA")


def fullest(src, first, n=8):
    best = None
    for f in range(first, first + n):
        p = os.path.join(src, "objects", "sprites_all", f"code_obj_{f:03d}.png")
        if not os.path.exists(p):
            continue
        im = Image.open(p).convert("RGBA")
        a = np.array(im)[..., 3] > 0
        score = int(a.sum())
        if best is None or score > best[0]:
            best = (score, f, im)
    return best[1], best[2]


def x4(im):
    big = im.resize((im.width * 4, im.height * 4), Image.LANCZOS)
    return big.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))


def mat(tex, metallic=0.2, roughness=0.6, emissive=None, name="m"):
    return PBRMaterial(name=name, baseColorTexture=tex, metallicFactor=metallic, roughnessFactor=roughness, emissiveFactor=emissive)


def flat(rgb, size=8):
    return Image.new("RGBA", (size, size), tuple(int(v) for v in rgb) + (255,))


def top_tex(im, fill):
    bg = Image.new("RGBA", im.size, tuple(int(v) for v in fill) + (255,))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def body_colour(im):
    a = np.array(im).reshape(-1, 4)
    a = a[a[:, 3] > 128][:, :3]
    return tuple(int(v) for v in np.median(a, axis=0)) if len(a) else (128, 128, 128)


# ----------------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------------
def extrude_pixels(im, height, lift=0.0, scale=PX, min_run=1):
    """The sprite's opaque pixels as row runs extruded to `height` blocks: a
    pixel-art solid whose top and sides carry the sprite's colours. Origin at
    the sprite centre on the ground; the sprite's top row is -z (the game's
    'up the page' is north)."""
    a = np.array(im)
    alpha = a[..., 3] > 96
    h, w = alpha.shape
    part = Part()
    y0, y1 = lift, lift + height
    for r in range(h):
        row = alpha[r]
        c = 0
        while c < w:
            if not row[c]:
                c += 1
                continue
            e = c
            while e < w and row[e]:
                e += 1
            if e - c >= min_run:
                x0, x1 = (c - w / 2) * scale, (e - w / 2) * scale
                z0, z1 = (r - h / 2) * scale, (r + 1 - h / 2) * scale
                u0, u1, v0, v1 = c / w, e / w, r / h, (r + 1) / h
                # top: UV straight from the sprite
                part.quad((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0), (u0, v1), (u1, v1), (u1, v0), (u0, v0))
                part.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (u0, v0), (u1, v0), (u1, v1), (u0, v1))
                # sides take the colour of the run's edge pixels
                um = (u0 + u1) / 2; vm = (v0 + v1) / 2
                part.quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (u1 - 0.001, vm), (u1 - 0.001, vm), (u1 - 0.001, vm), (u1 - 0.001, vm))
                part.quad((x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0), (u0 + 0.001, vm), (u0 + 0.001, vm), (u0 + 0.001, vm), (u0 + 0.001, vm))
                # the row's front/back faces, only where the neighbouring row is not solid
                if r == h - 1 or not alpha[r + 1, c:e].all():
                    part.quad((x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1), (um, v1 - 0.001), (um, v1 - 0.001), (um, v1 - 0.001), (um, v1 - 0.001))
                if r == 0 or not alpha[r - 1, c:e].all():
                    part.quad((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (um, v0 + 0.001), (um, v0 + 0.001), (um, v0 + 0.001), (um, v0 + 0.001))
            c = e
    return part


def ring(colour, r0, r1, y=0.006):
    """A thin lit ring on the ground under a pickup."""
    p = Part()
    n = 24
    for k in range(n):
        a0, a1 = 2 * math.pi * k / n, 2 * math.pi * (k + 1) / n
        p.quad((r0 * math.cos(a0), y, r0 * math.sin(a0)), (r0 * math.cos(a1), y, r0 * math.sin(a1)),
               (r1 * math.cos(a1), y, r1 * math.sin(a1)), (r1 * math.cos(a0), y, r1 * math.sin(a0)))
    return p.mesh(mat(flat(colour), 0.0, 0.8, emissive=tuple(c / 255 * 0.5 for c in colour), name="glow"))


def build_weapon(im):
    """A weapon pickup: the gun as a pixel solid, floating, over a soft glow disc."""
    big = x4(im)
    tex = top_tex(big, body_colour(im))
    gun = extrude_pixels(im, height=0.05, lift=0.10).mesh(mat(tex, 0.75, 0.35, name="gun"))
    glow_m = ring((80, 200, 100), 0.17, 0.21)
    return scene_with([("gun", gun), ("glow", glow_m)])


def build_token(im, radius=0.23, thick=0.045):
    """A power-up token: a thick coin with the icon on both faces and a
    coloured rim, floating; spins at run time."""
    big = x4(im)
    colour = body_colour(im)
    face = top_tex(big, colour)
    p = Part()
    cylinder_part(p, lambda t: radius, 0.10, 0.10 + thick, segments=28, rings=1, cap=True)
    # the underside cap
    q = Part()
    cylinder_part(q, lambda t: radius, 0.10 + thick, 0.10 + thick + 0.0001, segments=28, rings=1, cap=False)
    coin = p.mesh(mat(face, 0.6, 0.35, emissive=tuple(c / 255 * 0.25 for c in colour), name="coin"))
    rim = Part()
    cylinder_part(rim, lambda t: radius * 1.02, 0.10 - 0.002, 0.10 + thick + 0.002, segments=28, rings=1, cap=False)
    rim_m = rim.mesh(mat(flat(tuple(min(255, c + 40) for c in colour)), 0.8, 0.3, name="rim"))
    glow_m = ring(colour, 0.20, 0.24)
    return scene_with([("coin", coin), ("rim", rim_m), ("glow", glow_m)])


def build_heart(im):
    big = x4(im)
    heart = extrude_pixels(im, height=0.06, lift=0.10).mesh(mat(top_tex(big, (220, 40, 40)), 0.1, 0.4, emissive=(0.5, 0.05, 0.05), name="heart"))
    glow = Part()
    cylinder_part(glow, lambda t: 0.18, 0.004, 0.012, segments=20, rings=1)
    glow_m = glow.mesh(mat(flat((240, 60, 60)), 0.0, 0.9, emissive=(0.6, 0.1, 0.1), name="glow"))
    return scene_with([("heart", heart), ("glow", glow_m)])


def build_phone(im):
    """A GTA2 pay phone as an upright kiosk, half a block square: four steel
    posts, a blue steel back and side panels to waist height with glass above,
    the sprite as the roof, and the phone unit on the back wall, open to the
    front (+z, the sprite's down-the-page side). 0.5 blocks tall: a person is
    0.46, so it stands a head over him, like a real booth."""
    big = x4(im)
    blue = (40, 90, 200)
    W, D, H = 0.22, 0.20, 0.50   # half width, half depth, height
    steel = mat(flat((120, 124, 130)), 0.9, 0.35, name="steel")
    posts = Part()
    for x in (-W, W):
        for z in (-D, D):
            box_part(posts, x - 0.015, x + 0.015, 0.0, H, z - 0.015, z + 0.015)
    posts_m = posts.mesh(steel)
    # roof: the sprite, with a thin fascia under it
    roof = Part()
    roof.quad((-W, H, D), (W, H, D), (W, H, -D), (-W, H, -D), (0, 1), (1, 1), (1, 0), (0, 0))
    roof_m = roof.mesh(mat(top_tex(big, blue), 0.5, 0.45, name="roof"))
    fascia = Part(); box_part(fascia, -W, W, H - 0.03, H, -D, D)
    fascia_m = fascia.mesh(mat(flat(blue), 0.5, 0.45, name="fascia"))
    # lower panels: blue steel with a pale band; back and both sides
    panels = Part()
    box_part(panels, -W, W, 0.02, 0.22, -D, -D + 0.012)            # back
    box_part(panels, -W, -W + 0.012, 0.02, 0.22, -D, D)            # left side
    box_part(panels, W - 0.012, W, 0.02, 0.22, -D, D)              # right side
    side_tex = Image.new("RGB", (64, 32), blue)
    ImageDraw.Draw(side_tex).rectangle([0, 10, 64, 14], fill=(190, 200, 215))
    panels_m = panels.mesh(mat(side_tex, 0.5, 0.45, name="panel"))
    # glass above the panels on the same three sides
    glass = Part()
    box_part(glass, -W, W, 0.22, H - 0.03, -D, -D + 0.006)
    box_part(glass, -W, -W + 0.006, 0.22, H - 0.03, -D, D)
    box_part(glass, W - 0.006, W, 0.22, H - 0.03, -D, D)
    glass_m = glass.mesh(mat(flat((150, 190, 215)), 0.1, 0.1, name="glass"))
    # the phone unit on the back wall: a dark box with a keypad face, the handset beside it
    unit = Part(); box_part(unit, -0.08, 0.08, 0.24, 0.40, -D + 0.012, -D + 0.06)
    unit_m = unit.mesh(mat(flat((70, 72, 78)), 0.8, 0.3, name="unit"))
    hs = Part(); box_part(hs, -0.07, -0.04, 0.27, 0.39, -D + 0.06, -D + 0.085)
    hs_m = hs.mesh(mat(flat((28, 28, 32)), 0.1, 0.6, name="handset"))
    floor = Part(); box_part(floor, -W, W, 0.0, 0.02, -D, D)
    floor_m = floor.mesh(mat(flat((90, 90, 95)), 0.8, 0.5, name="floor"))
    return scene_with([("posts", posts_m), ("roof", roof_m), ("fascia", fascia_m), ("panels", panels_m),
                       ("glass", glass_m), ("unit", unit_m), ("handset", hs_m), ("floor", floor_m)])


def build_light(colour):
    """A traffic-light head: a dark housing 18x4 px (0.28 x 0.06 blocks) with
    a lit lens strip on both long sides and the lit top."""
    housing = Part()
    box_part(housing, -0.14, 0.14, 0.0, 0.11, -0.03, 0.03)
    h_m = housing.mesh(mat(flat((28, 30, 32)), 0.6, 0.5, name="housing"))
    lens = Part()
    for z in (-0.031, 0.031):
        box_part(lens, -0.12, 0.12, 0.03, 0.08, z - 0.004, z + 0.004)
    box_part(lens, -0.12, 0.12, 0.108, 0.116, -0.02, 0.02)
    l_m = lens.mesh(mat(flat(colour), 0.0, 0.25, emissive=tuple(c / 255 * 0.9 for c in colour), name="lens"))
    return scene_with([("housing", h_m), ("lens", l_m)])


def build_heli(im):
    """The police helicopter: fuselage, tail boom, skids, a four-blade rotor
    and the tail rotor; the sprite is only 22 px so the body is modelled."""
    grey = (150, 154, 160)
    body = Part()
    cylinder_part(body, lambda t: 0.10 * math.sin(math.pi * (0.1 + 0.8 * t)) + 0.01, 0.10, 0.34, segments=16, rings=6)
    # cylinder_part builds about +y; the fuselage lies along z: rotate the part's vertices
    rot = trimesh.transformations.rotation_matrix(math.radians(-90), [1, 0, 0])
    body_m = body.mesh(mat(flat(grey), 0.7, 0.4, name="body"))
    body_m.apply_transform(rot); body_m.apply_translation((0, 0.22, 0.0))
    cab = Part(); box_part(cab, -0.07, 0.07, 0.16, 0.30, 0.02, 0.17)
    cab_m = cab.mesh(mat(flat((40, 60, 90)), 0.1, 0.1, name="glass"))
    tail = Part(); box_part(tail, -0.025, 0.025, 0.20, 0.25, -0.46, -0.10)
    tail_m = tail.mesh(mat(flat(grey), 0.7, 0.4, name="tail"))
    fin = Part(); box_part(fin, -0.01, 0.01, 0.20, 0.36, -0.46, -0.38)
    fin_m = fin.mesh(mat(flat((60, 60, 70)), 0.6, 0.5, name="fin"))
    skids = Part()
    for x in (-0.09, 0.09):
        box_part(skids, x - 0.012, x + 0.012, 0.0, 0.025, -0.18, 0.18)
        for z in (-0.10, 0.10):
            box_part(skids, x - 0.008, x + 0.008, 0.02, 0.12, z - 0.008, z + 0.008)
    skids_m = skids.mesh(mat(flat((50, 50, 55)), 0.7, 0.5, name="skids"))
    rotor = Part()
    for k in range(4):
        ang = k * math.pi / 2
        c, s = math.cos(ang), math.sin(ang)
        pts = [(-0.012, 0.0), (0.012, 0.0), (0.012, 0.42), (-0.012, 0.42)]
        p = [(x * c - z * s, 0.36, x * s + z * c) for x, z in pts]
        rotor.quad(p[0], p[1], p[2], p[3])
        rotor.quad(p[3], p[2], p[1], p[0])
    hub = Part(); cylinder_part(hub, lambda t: 0.03, 0.30, 0.37, segments=10, rings=1)
    rotor_m = rotor.mesh(mat(flat((40, 40, 44)), 0.6, 0.5, name="rotor"))
    hub_m = hub.mesh(mat(flat((40, 40, 44)), 0.6, 0.5, name="hub"))
    trotor = Part()
    for k in range(2):
        ang = k * math.pi / 2
        c, s = math.cos(ang), math.sin(ang)
        pts = [(0.0, -0.006), (0.0, 0.006), (0.09, 0.006), (0.09, -0.006)]
        p = [(0.03, 0.28 + x * c - z * s, -0.42 + x * s + z * c) for x, z in pts]
        trotor.quad(p[0], p[1], p[2], p[3]); trotor.quad(p[3], p[2], p[1], p[0])
    tr_m = trotor.mesh(mat(flat((40, 40, 44)), 0.6, 0.5, name="tailrotor"))
    return scene_with([("body", body_m), ("cab", cab_m), ("tail", tail_m), ("fin", fin_m), ("skids", skids_m), ("rotor", rotor_m), ("hub", hub_m), ("tailrotor", tr_m)])


# ----------------------------------------------------------------------------
def main():
    src, out_dir = sys.argv[1], sys.argv[2]
    sheet_path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
    os.makedirs(out_dir, exist_ok=True)
    jobs = []   # (name, frames, scene, sprite, anim)
    for first, name in WEAPONS.items():
        f, im = fullest(src, first)
        jobs.append((name, list(range(first, first + 8)), build_weapon(im), im, "spin"))
    for first, name in TOKENS.items():
        f, im = fullest(src, first)
        jobs.append((name, list(range(first, first + 8)), build_token(im), im, "spin"))
    im = load(src, PHONE[0])
    jobs.append(("code_phone", PHONE, build_phone(im), im, ""))
    for frame, (name, colour) in LIGHTS.items():
        jobs.append((name, [frame], build_light(colour), load(src, frame), ""))
    jobs.append(("code_helicopter", [HELI], build_heli(load(src, HELI)), load(src, HELI), "rotor"))

    status, models, objects, anim = {}, [], {}, {}
    cells = []
    for name, frames, scene, im, a in jobs:
        tris = sum(len(g.faces) for g in scene.geometry.values())
        b = scene.bounds
        scene.export(os.path.join(out_dir, name + ".glb"))
        status[name] = dict(frames=frames, triangles=int(tris), anim=a, sprite_px=[im.width, im.height],
                            size_blocks=[round(float(b[1][i] - b[0][i]), 3) for i in range(3)])
        models.append(dict(name=name, glb=f"objects/code_models/{name}.glb", scale=1.0, texture_max=256, forward="+z"))
        for fr in frames:
            objects[f"{CODE_OBJ_BASE}:{fr}"] = name
            if a:
                anim[f"{CODE_OBJ_BASE}:{fr}"] = a
        if sheet_path:
            sp = im.resize((im.width * 4, im.height * 4), Image.NEAREST); sp.thumbnail((150, 150))
            cell = Image.new("RGBA", (160 * 3, 176), (30, 30, 30, 255))
            cell.paste(sp, (80 - sp.width // 2, 80 - sp.height // 2), sp)
            cell.paste(render(scene, "top"), (160, 0)); cell.paste(render(scene, "3q"), (320, 0))
            ImageDraw.Draw(cell).text((4, 162), f"{name}  frames {frames[0]}-{frames[-1]}  {tris} tris  {a or 'static'}", fill=(255, 255, 0, 255))
            cells.append(cell)
        print(name, tris, "tris", status[name]["size_blocks"])
    json.dump(status, open(os.path.join(out_dir, "status.json"), "w"), indent=1)
    json.dump(dict(models=models, objects=objects, objects_anim=anim), open(os.path.join(out_dir, "manifest_fragment.json"), "w"), indent=1)
    if sheet_path and cells:
        cols = 3; rows = (len(cells) + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * 480, rows * 176), (30, 30, 30, 255))
        for i, c in enumerate(cells):
            sheet.paste(c, ((i % cols) * 480, (i // cols) * 176))
        sheet.save(sheet_path)
        print("sheet", sheet_path)


if __name__ == "__main__":
    main()
