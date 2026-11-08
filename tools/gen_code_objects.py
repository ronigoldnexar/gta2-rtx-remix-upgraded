#!/usr/bin/env python3
"""GTA2's code objects (sprite base 4) as 3D models for the street-level views:
weapon pickups (the hand-held weapon models at pickup size), the round power-up
tokens, mission items, the pay phone booths, traffic-light heads and the police
helicopter. Pickups are flagged to spin and float at run time ("objects_anim":
"spin") and are authored at their final size in blocks. Companion models,
drawn by dll/src/map_objects.cpp with the main model's placement:
<name>__lit unlit (lenses, signs, pickup rings: they glow
at night), <name>__glass translucent (the booth's panes).

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
WEAPONS = {  # first frame of each 8-frame rotation, in the game's weapon order
    18: "pickup_pistol", 26: "pickup_machine_gun", 34: "pickup_rocket_launcher", 42: "pickup_electro_gun",
    50: "pickup_molotov", 58: "pickup_grenade", 66: "pickup_shotgun", 74: "pickup_electro_baton",
    82: "pickup_flamethrower", 90: "pickup_silenced_mg", 98: "pickup_dual_pistol",
}
MISC_PICKUPS = {118: "pickup_item_118", 126: "pickup_item_126", 134: "pickup_item_134"}   # 8-frame items, extruded from the sprite
BRIEFCASE = (10, "token_briefcase", 5)   # the briefcase disc, frames 10-14
TOKENS = {  # first frame (30x30) of each 8-frame turn
    151: "token_blue", 159: "token_orange", 167: "token_dollar", 175: "token_purple", 183: "token_green_x",
    191: "token_red_x", 199: "token_cyan", 207: "token_hand", 215: "token_yellow", 223: "token_navy",
    231: "token_bronze", 239: "token_gold", 286: "token_skull",
}
PHONE = [510, 511, 512]
PHONE_NAMES = ["code_phone", "code_phone_ring1", "code_phone_ring2"]   # idle, ringing (handset dim / bright red)
LIGHTS = {549: ((235, 40, 30), 0), 550: ((60, 230, 70), 2), 551: ((245, 170, 40), 1)}   # frame -> (lens colour, lens slot)
LIGHT_NAMES = {549: "light_red", 550: "light_green", 551: "light_amber"}
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
    return scene_with([("coin", coin), ("rim", rim_m)]), scene_with([("glow", glow_ring(tuple(min(255, c + 30) for c in colour), 0.20, 0.235))])


BOOTH_BLUE = (46, 104, 196)      # the sprite's booth blue
BOOTH_DARK = (24, 52, 110)


def blue_steel(rgb=BOOTH_BLUE, w=128, h=128, seed=21):
    """Painted sheet steel: faint vertical brushing, a seam and a rivet row."""
    rng = np.random.default_rng(seed)
    grad = np.linspace(10, -10, h, dtype=np.float32)[:, None, None]          # a little lighter at the top
    a = np.array(rgb, np.float32)[None, None, :] + grad + rng.normal(0, 1.5, (h, w, 1))
    im = Image.fromarray(np.clip(np.broadcast_to(a, (h, w, 3)), 0, 255).astype(np.uint8), "RGB")
    dr = ImageDraw.Draw(im)
    dark = tuple(max(0, c - 40) for c in rgb); lite = tuple(min(255, c + 45) for c in rgb)
    dr.line([0, 3, w, 3], fill=lite, width=2); dr.line([0, h - 4, w, h - 4], fill=dark, width=2)
    for x in range(8, w, 16):
        dr.ellipse([x - 2, h - 12, x + 2, h - 8], fill=lite)
    return im


def keypad_texture():
    """The pay phone's face: brushed chrome, a coin slot, a little display and twelve keys."""
    w, h = 96, 128
    im = Image.new("RGB", (w, h), (176, 180, 186))
    dr = ImageDraw.Draw(im)
    for y in range(0, h, 2):
        dr.line([0, y, w, y], fill=(170 + (y * 7) % 13, 174 + (y * 7) % 13, 180 + (y * 7) % 13))
    dr.rectangle([1, 1, w - 2, h - 2], outline=(90, 92, 98), width=3)
    dr.rectangle([14, 10, w - 14, 28], fill=(30, 60, 40)); dr.text((18, 13), "25c", fill=(120, 240, 140))
    dr.rectangle([w - 26, 36, w - 14, 58], fill=(40, 40, 44))            # coin slot plate
    dr.rectangle([w - 22, 40, w - 18, 54], fill=(10, 10, 10))
    for r in range(4):
        for c in range(3):
            x, y = 14 + c * 18, 62 + r * 15
            dr.rectangle([x, y, x + 12, y + 10], fill=(52, 54, 60)); dr.rectangle([x + 2, y + 2, x + 10, y + 8], fill=(225, 225, 228))
    dr.rectangle([14, h - 14, w - 14, h - 8], fill=(40, 40, 44))         # coin return
    return im


def sign_texture(text="PHONE", w=256, h=64):
    """A back-lit sign panel: white letters on GTA2 blue, a lit rim."""
    im = Image.new("RGB", (w, h), (30, 90, 210))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, w - 1, h - 1], outline=(200, 230, 255), width=4)
    try:
        from PIL import ImageFont
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except Exception:
        f = None
    tw = dr.textlength(text, font=f) if f else len(text) * 6
    dr.text(((w - tw) / 2, 8), text, fill=(255, 255, 240), font=f)
    return im


def glass_texture():
    """Tinted glass, translucent (drawn in the glass pass), with two faint reflection streaks."""
    w = h = 64
    a = np.zeros((h, w, 4), np.uint8)
    a[..., 0], a[..., 1], a[..., 2], a[..., 3] = 165, 205, 228, 70
    for k in (14, 22):
        for y in range(h):
            x = (k + y // 2) % w
            a[y, x:x + 3, :3] = 235; a[y, x:x + 3, 3] = 120
    return Image.fromarray(a, "RGBA")


def handset_parts(D_back, colour):
    """The handset hanging on the right of the unit and its coiled cord."""
    p = Part()
    x0 = D_back - 0.05
    box_part(p, x0, x0 + 0.022, 0.30, 0.43, 0.080, 0.100)      # the handle
    box_part(p, x0 - 0.008, x0 + 0.03, 0.405, 0.44, 0.074, 0.108)   # ear piece
    box_part(p, x0 - 0.008, x0 + 0.03, 0.29, 0.325, 0.074, 0.108)   # mouth piece
    return p.mesh(mat(flat(colour), 0.1, 0.5, name="handset"))


def build_phone(im, ring=0):
    """A GTA2 pay phone booth, from the sprite's plan: a blue steel hood half a
    block square, open on the sprite's left (-x), the phone on the back wall
    (+x) with the handset on its right (the sprite's frames 511/512 light the
    handset red when the phone rings). Corner posts, blue kick panels, glass
    side panes (a separate translucent model), a roof with a lit PHONE sign
    box (a separate unlit model, so it reads at night), a concrete plinth.
    0.62 blocks to the roof: a person (0.46) stands well inside it.

    Returns (main, lit, glass) scenes."""
    W, D, H = 0.25, 0.235, 0.60       # half width (x), half depth (z), roof height
    steel = mat(blue_steel(), 0.55, 0.4, name="booth_steel")
    dark = mat(blue_steel(BOOTH_DARK, seed=3), 0.55, 0.45, name="booth_dark")
    chrome = mat(flat((168, 172, 178)), 0.9, 0.25, name="chrome")
    frame = Part()
    for x in (-W, W):
        for z in (-D, D):
            box_part(frame, x - 0.018, x + 0.018, 0.03, H, z - 0.018, z + 0.018)
    # side kick panels and rails (z = +-D), the back wall full height (x = +W), front header
    for z in (-D, D):
        box_part(frame, -W, W, 0.03, 0.17, z - 0.008, z + 0.008)
        box_part(frame, -W, W, 0.17, 0.19, z - 0.014, z + 0.014)
        box_part(frame, -W, W, 0.52, H, z - 0.012, z + 0.012)
    # the back (+x): kick panel and rail like the sides, glass either side of a steel
    # spine that carries the phone
    box_part(frame, W - 0.012, W, 0.03, 0.17, -D, D)
    box_part(frame, W - 0.016, W + 0.004, 0.17, 0.19, -D, D)
    box_part(frame, W - 0.012, W, 0.52, H, -D, D)
    box_part(frame, W - 0.012, W, 0.19, 0.52, -0.095, 0.095)
    box_part(frame, -W - 0.004, -W + 0.012, 0.52, H, -D, D)
    frame_m = frame.mesh(steel)
    roof = Part()
    box_part(roof, -W - 0.025, W + 0.025, H, H + 0.03, -D - 0.025, D + 0.025)
    roof_m = roof.mesh(dark)
    plinth = Part(); box_part(plinth, -W - 0.01, W + 0.01, 0.0, 0.03, -D - 0.01, D + 0.01)
    plinth_m = plinth.mesh(mat(flat((128, 126, 120)), 0.0, 0.85, name="plinth"))
    # the phone unit: a chrome box on the back wall, keypad facing the opening (-x)
    unit = Part()
    ux0, ux1 = W - 0.012 - 0.055, W - 0.012
    uz0, uz1 = -0.075, 0.075
    uy0, uy1 = 0.25, 0.47
    unit.quad((ux0, uy0, uz1), (ux0, uy1, uz1), (ux0, uy1, uz0), (ux0, uy0, uz0), (1, 0), (1, 1), (0, 1), (0, 0))  # face (-x)
    box_sides = Part(); box_part(box_sides, ux0 + 0.002, ux1, uy0, uy1, uz0, uz1)
    unit_m = unit.mesh(mat(keypad_texture(), 0.7, 0.3, name="keypad"))
    unit_box = box_sides.mesh(chrome)
    shelf = Part(); box_part(shelf, W - 0.10, W - 0.012, 0.24, 0.255, -0.11, 0.11)   # the directory shelf
    box_part(shelf, W - 0.085, W - 0.02, 0.255, 0.275, -0.10, -0.02)              # the directory
    shelf_m = shelf.mesh(mat(flat((60, 62, 68)), 0.6, 0.5, name="shelf"))
    main = scene_with([("plinth", plinth_m), ("frame", frame_m), ("roof", roof_m), ("unit", unit_box), ("keypad", unit_m), ("shelf", shelf_m)])
    # lit: the roof sign box (PHONE on its long faces, toward -x and +x) and the handset
    sign = Part()
    sy0, sy1 = H + 0.03, H + 0.10
    sx0, sx1, sz0, sz1 = -0.03, 0.03, -0.18, 0.18
    sign.quad((sx0, sy0, sz1), (sx0, sy1, sz1), (sx0, sy1, sz0), (sx0, sy0, sz0), (0, 0), (0, 1), (1, 1), (1, 0))
    sign.quad((sx1, sy0, sz0), (sx1, sy1, sz0), (sx1, sy1, sz1), (sx1, sy0, sz1), (0, 0), (0, 1), (1, 1), (1, 0))
    sign_m = sign.mesh(mat(sign_texture(), 0.0, 0.6, name="sign"))
    ends = Part()
    ends.quad((sx0, sy0, sz0), (sx0, sy1, sz0), (sx1, sy1, sz0), (sx1, sy0, sz0))
    ends.quad((sx1, sy0, sz1), (sx1, sy1, sz1), (sx0, sy1, sz1), (sx0, sy0, sz1))
    ends.quad((sx0, sy1, sz1), (sx1, sy1, sz1), (sx1, sy1, sz0), (sx0, sy1, sz0))
    ends_m = ends.mesh(mat(flat((200, 230, 255)), 0.0, 0.6, name="sign_rim"))
    hs_colour = [(26, 26, 30), (150, 30, 20), (255, 70, 40)][ring]
    lit = scene_with([("sign", sign_m), ("sign_rim", ends_m), ("handset", handset_parts(W - 0.012, hs_colour))])
    # glass: the side panes above the kick panels and a pane over the back wall's upper half is steel, so sides only
    glass = Part()
    for z in (-D, D):
        box_part(glass, -W + 0.018, W - 0.018, 0.19, 0.52, z - 0.004, z + 0.004)
    for z0, z1 in ((-D + 0.018, -0.095), (0.095, D - 0.018)):
        box_part(glass, W - 0.008, W - 0.002, 0.19, 0.52, z0, z1)
    glass_s = scene_with([("glass", glass.mesh(mat(glass_texture(), 0.1, 0.05, name="glass")))])
    return main, lit, glass_s


def build_light(colour, lit_index):
    """A traffic-light head lying along the sprite's long edge (18x4 px, 0.28 x
    0.06 blocks): a dark housing with three hooded lenses (red, amber, green
    from the sprite's left) on both long faces and on top. The lit lens is a
    separate unlit model, the dark ones stay in the housing.
    Returns (main, lit)."""
    housing = Part()
    box_part(housing, -0.14, 0.14, 0.0, 0.10, -0.03, 0.03)
    box_part(housing, -0.145, 0.145, 0.10, 0.11, -0.035, 0.035)            # cap
    hoods = Part()
    dims = []
    colours = [(235, 40, 30), (245, 170, 40), (60, 230, 70)]
    for k in range(3):
        cx = -0.09 + 0.09 * k
        dims.append(cx)
        for z in (-1, 1):
            zz = 0.03 * z
            box_part(hoods, cx - 0.04, cx + 0.04, 0.085, 0.092, min(zz, zz + 0.03 * z), max(zz, zz + 0.03 * z))   # visor over the lens
    h_m = housing.mesh(mat(flat((26, 28, 30)), 0.6, 0.5, name="housing"))
    hood_m = hoods.mesh(mat(flat((18, 18, 20)), 0.5, 0.6, name="hood"))
    dimp = Part()
    for k, cx in enumerate(dims):
        if k == lit_index:
            continue
        for z in (-1, 1):
            zz = 0.0305 * z
            box_part(dimp, cx - 0.032, cx + 0.032, 0.022, 0.082, min(zz, zz + 0.004 * z), max(zz, zz + 0.004 * z))
    parts = [("housing", h_m), ("hood", hood_m)]
    if dimp.v:
        parts.append(("lens_off", dimp.mesh(mat(flat((60, 58, 52)), 0.2, 0.3, name="lens_off"))))
    main = scene_with(parts)
    lp = Part()
    cx = dims[lit_index]
    for z in (-1, 1):
        zz = 0.0305 * z
        box_part(lp, cx - 0.032, cx + 0.032, 0.022, 0.082, min(zz, zz + 0.004 * z), max(zz, zz + 0.004 * z))
    box_part(lp, cx - 0.03, cx + 0.03, 0.11, 0.114, -0.02, 0.02)
    lit = scene_with([("lens", lp.mesh(mat(lens_texture(colour), 0.0, 0.2, name="lens")))])
    return main, lit


def build_light_mount():
    """What the traffic-light head stands on (frame 548, 22x20 px): a dark steel
    junction box with a teal band and a bracket, low enough that the head sits on it."""
    p = Part()
    box_part(p, -0.16, 0.16, 0.0, 0.035, -0.145, 0.145)
    box_part(p, -0.05, 0.05, 0.035, 0.05, -0.04, 0.04)
    band = Part()
    box_part(band, -0.165, 0.165, 0.012, 0.024, -0.15, 0.15)
    return scene_with([("box", p.mesh(mat(flat((36, 40, 44)), 0.6, 0.5, name="mount"))),
                       ("band", band.mesh(mat(flat((40, 120, 120)), 0.4, 0.5, name="band")))])


def lens_texture(colour):
    """A lit lens: a bright core fading to the colour at the rim."""
    s = 32
    y, x = np.mgrid[0:s, 0:s]
    r = np.sqrt((x - s / 2 + 0.5) ** 2 + (y - s / 2 + 0.5) ** 2) / (s / 2)
    core = np.clip(1.0 - r, 0, 1)[..., None]
    c = np.array(colour, np.float32)[None, None, :]
    img = c * (0.75 + 0.25 * core) + (255 - c) * 0.6 * core ** 2
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


def glow_ring(colour, r0, r1, y=0.006, segments=24):
    """The pickup's ground ring, as its own part for the unlit pass."""
    p = Part()
    for k in range(segments):
        a0, a1 = 2 * math.pi * k / segments, 2 * math.pi * (k + 1) / segments
        p.quad((r0 * math.cos(a0), y, r0 * math.sin(a0)), (r0 * math.cos(a1), y, r0 * math.sin(a1)),
               (r1 * math.cos(a1), y, r1 * math.sin(a1)), (r1 * math.cos(a0), y, r1 * math.sin(a0)))
    return p.mesh(mat(flat(colour), 0.0, 0.8, name="glow"))


WEAPON_SRC = {   # pickup group -> (hand-held model, length in blocks, how many)
    "pickup_pistol": ("pistol", 0.28, 1), "pickup_machine_gun": ("machine_gun", 0.42, 1),
    "pickup_rocket_launcher": ("rocket_launcher", 0.48, 1), "pickup_electro_gun": ("electro_gun", 0.34, 1),
    "pickup_molotov": ("molotov", 0.22, 3), "pickup_grenade": ("grenade", 0.12, 3),
    "pickup_shotgun": ("shotgun", 0.46, 1), "pickup_electro_baton": ("electro_gun", 0.32, 1),
    "pickup_flamethrower": ("flamethrower", 0.46, 1), "pickup_silenced_mg": ("silenced_mg", 0.42, 1),
    "pickup_dual_pistol": ("pistol", 0.28, 2),
}


def brighten(scene, lift=0.45, add=70):
    """The hand-held models are blued steel and walnut, close to black at pickup
    distance; a pickup lifts them toward a readable mid tone."""
    for g in scene.geometry.values():
        m = getattr(g.visual, "material", None)
        tex = getattr(m, "baseColorTexture", None)
        if tex is None:
            continue
        a = np.array(tex.convert("RGB"), np.float32)
        a = a * (1 - lift) + (a * 1.6 + add) * lift
        m.baseColorTexture = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def build_weapon_model(src, name):
    """A weapon pickup in the street views: the hand-held weapon model (the same
    one a figure aims with), at pickup size, standing on its side a hand above
    the ground so its silhouette reads as it turns, over a green ring.
    Authored at its final size in blocks: the renderer draws spinning pickups
    at scale 1, not fitted to each frame's sprite extent (which made them pulse).
    Returns (main, lit)."""
    kind, length, count = WEAPON_SRC[name]
    w = trimesh.load(os.path.join(src, "weapons", f"weapon_{kind}.glb"), force="scene")
    w = w.copy()
    b = w.bounds
    s = length / float(max(b[1] - b[0]))
    w.apply_transform(trimesh.transformations.scale_matrix(s))
    b = w.bounds
    ctr = (b[0] + b[1]) / 2
    w.apply_transform(trimesh.transformations.translation_matrix([-ctr[0], 0.11 - b[0][1], -ctr[2]]))
    brighten(w)
    meshes = []
    geoms = list(w.dump())
    if count == 1:
        meshes = [(f"gun{i}", g) for i, g in enumerate(geoms)]
    else:
        ext = w.bounds[1] - w.bounds[0]
        step = (ext[0] + 0.02) if kind == "pistol" else max(ext[0], ext[2]) * 1.1
        for k in range(count):
            off = (k - (count - 1) / 2) * step
            for i, g in enumerate(geoms):
                gg = g.copy()
                if kind == "pistol":
                    gg.apply_translation([off, 0, 0])
                else:
                    ang = 2 * math.pi * k / count
                    gg.apply_translation([math.cos(ang) * step * 0.6, 0, math.sin(ang) * step * 0.6])
                meshes.append((f"gun{k}_{i}", gg))
    main = scene_with(meshes)
    lit = scene_with([("glow", glow_ring((90, 230, 110), 0.20, 0.235))])
    return main, lit


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
def build_item(im):
    """A small mission item (8-frame turn): the sprite as a thick pixel solid."""
    big = x4(im)
    body = extrude_pixels(im, height=0.08, lift=0.11).mesh(mat(top_tex(big, body_colour(im)), 0.4, 0.4, name="item"))
    return scene_with([("item", body)]), scene_with([("glow", glow_ring((230, 230, 160), 0.17, 0.205))])


def main():
    src, out_dir = sys.argv[1], sys.argv[2]
    sheet_path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
    os.makedirs(out_dir, exist_ok=True)
    # (name, frames, main scene, {suffix: scene} companions, sprite, anim). Companions are drawn by
    # dll/src/map_objects.cpp with the main model's placement: "__lit" unlit, so lenses, signs and pickup rings glow at night; "__glass" translucent, last.
    jobs = []
    for first, name in WEAPONS.items():
        f, im = fullest(src, first)
        m, lit = build_weapon_model(src, name)
        jobs.append((name, list(range(first, first + 8)), m, {"__lit": lit}, im, "spin"))
    for first, name in list(TOKENS.items()) + [(BRIEFCASE[0], BRIEFCASE[1])]:
        n = BRIEFCASE[2] if first == BRIEFCASE[0] else 8
        f, im = fullest(src, first, n)
        m, lit = build_token(im)
        jobs.append((name, list(range(first, first + n)), m, {"__lit": lit}, im, "spin"))
    for first, name in MISC_PICKUPS.items():
        f, im = fullest(src, first)
        m, lit = build_item(im)
        jobs.append((name, list(range(first, first + 8)), m, {"__lit": lit}, im, "spin"))
    im = load(src, PHONE[0])
    for k, (fr, name) in enumerate(zip(PHONE, PHONE_NAMES)):
        main_m, lit, glass = build_phone(im, k)
        jobs.append((name, [fr], main_m, {"__lit": lit, "__glass": glass}, load(src, fr), ""))
    for frame, (colour, slot) in LIGHTS.items():
        housing, lit = build_light(colour, slot)
        jobs.append((LIGHT_NAMES[frame], [frame], housing, {"__lit": lit}, load(src, frame), ""))
    jobs.append(("light_mount", [548], build_light_mount(), {}, load(src, 548), ""))
    jobs.append(("code_helicopter", [HELI], build_heli(load(src, HELI)), {}, load(src, HELI), "rotor"))

    status, models, objects, anim = {}, [], {}, {}
    cells = []
    for name, frames, scene, comps, im, a in jobs:
        tris = sum(len(g.faces) for g in scene.geometry.values())
        ctris = {k: int(sum(len(g.faces) for g in c.geometry.values())) for k, c in comps.items()}
        b = scene.bounds
        scene.export(os.path.join(out_dir, name + ".glb"))
        models.append(dict(name=name, glb=f"objects/code_models/{name}.glb", scale=1.0, texture_max=256, forward="+z"))
        for suffix, c in comps.items():
            c.export(os.path.join(out_dir, name + suffix + ".glb"))
            models.append(dict(name=name + suffix, glb=f"objects/code_models/{name + suffix}.glb", scale=1.0, texture_max=256, forward="+z"))
        status[name] = dict(frames=frames, triangles=int(tris), companions=ctris, anim=a, sprite_px=[im.width, im.height],
                            size_blocks=[round(float(b[1][i] - b[0][i]), 3) for i in range(3)])
        for fr in frames:
            objects[f"{CODE_OBJ_BASE}:{fr}"] = name
            if a:
                anim[f"{CODE_OBJ_BASE}:{fr}"] = a
        if sheet_path:
            full = trimesh.Scene()
            for g in scene.dump():
                full.add_geometry(g)
            for suffix, c in comps.items():
                for g in c.dump():
                    full.add_geometry(g)
            sp = im.resize((im.width * 4, im.height * 4), Image.NEAREST); sp.thumbnail((150, 150))
            cell = Image.new("RGBA", (160 * 3, 176), (30, 30, 30, 255))
            cell.paste(sp, (80 - sp.width // 2, 80 - sp.height // 2), sp)
            cell.paste(render(full, "top"), (160, 0)); cell.paste(render(full, "3q"), (320, 0))
            ImageDraw.Draw(cell).text((4, 162), f"{name}  frames {frames[0]}-{frames[-1]}  {tris}+{sum(ctris.values())} tris  {a or 'static'}", fill=(255, 255, 0, 255))
            cells.append(cell)
        print(name, tris, "tris", ctris, status[name]["size_blocks"])
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
