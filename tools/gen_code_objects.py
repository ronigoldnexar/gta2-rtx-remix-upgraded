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
HEALTH = (167, "pickup_health")   # 4:167-174: the red disc with a heart (was mislabelled token_dollar until FIX-WORLD-12)
TOKENS = {  # first frame (30x30) of each 8-frame turn
    151: "token_blue", 159: "token_orange", 175: "token_purple", 183: "token_green_x",
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


def build_token(im):
    """A power-up token (4:151-166, 175-246) as an upright medallion turning like the weapon pickups and
    the health heart (FIX-WORLD-14, WORLD-13 order 5): the sprite's face-on frame on both faces of a
    disc 0.30 block across a hand above the ground, a rolled rim a shade lighter than the token, over a
    ground ring. Before it was a coin lying flat (never even drawn: power-up sprites are 'plain' and
    took no model until live_geometry let token_ through). Spinning pickups are drawn unlit, so the
    face keeps the sprite's own baked shading; the ring goes in the __lit companion. Returns (main, lit)."""
    colour = body_colour(im)
    a = np.array(im.convert("RGBA")).reshape(-1, 4)
    a = a[a[:, 3] > 128][:, :3].astype(np.float32)
    lum = a.mean(1) if len(a) else np.array([128.0])
    rim_rgb = tuple(int(v) for v in np.median(a[lum <= np.percentile(lum, 20)], 0)) if len(a) else colour
    R, T, YC = 0.15, 0.034, 0.25          # disc radius, thickness, centre height (blocks), as pickup_health
    face_img = top_tex(x4(im), rim_rgb)    # the round sprite over its own dark edge colour: no keyed corners
    disc = trimesh.creation.cylinder(radius=R, height=T, sections=40)
    disc.apply_translation((0, YC, 0))
    uv = np.stack([(disc.vertices[:, 0] / R) * 0.5 + 0.5, ((disc.vertices[:, 1] - YC) / R) * 0.5 + 0.5], 1)
    disc.visual = TextureVisuals(uv=uv, material=mat(face_img, 0.15, 0.35, name="coin"))
    rim = trimesh.creation.annulus(r_min=R * 0.97, r_max=R * 1.06, height=T * 1.25, sections=40)
    rim.apply_translation((0, YC, 0))
    rim.visual = TextureVisuals(uv=np.full((len(rim.vertices), 2), 0.5),
                                material=mat(flat(tuple(min(255, c + 40) for c in colour)), 0.6, 0.3, name="rim"))
    ring = tuple(min(255, c + 30) for c in colour)
    return scene_with([("coin", disc), ("rim", rim)]), scene_with([("glow", glow_ring(ring, 0.20, 0.235))])


BOOTH_BLUE = (36, 84, 160)       # the sprite's booth blue, a shade deeper as painted steel (the sprite's 46,104,196 lit flat read as plastic)
BOOTH_DARK = (20, 42, 90)


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


def glass_texture(size=128):
    """Clear tinted glass, translucent (drawn in the glass pass): alpha about 0.13, a soft
    broad sheen and a little grime at the foot of the pane. Smooth gradients only: the
    first one's one-texel diagonal streaks on a 64 px sheet stair-stepped into a zigzag
    that read as a pasted picture (demo-phone-booth-flat-translucent-blue-placeholder-box)."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    a = np.full((size, size), 34.0, np.float32)
    rgb = np.zeros((size, size, 3), np.float32) + np.array((150, 182, 196), np.float32)
    for c, w, k in ((0.30, 0.12, 30.0), (0.56, 0.035, 22.0)):
        d = (x + 0.6 * y) / 1.6 - c
        band = np.exp(-(d / w) ** 2)
        a += k * band
        rgb += (240.0 - rgb) * 0.45 * band[..., None]
    grime = np.clip((y - 0.84) / 0.16, 0.0, 1.0) ** 2
    a += grime * 30.0
    rgb = rgb * (1.0 - 0.3 * grime[..., None]) + np.array((96, 92, 80), np.float32) * 0.3 * grime[..., None]
    out = np.concatenate([np.clip(rgb, 0, 255), np.clip(a, 0, 255)[..., None]], 2)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def handset_parts(D_back, colour):
    """The handset hanging on the right of the unit (+z): a 0.22 m handle with
    ear and mouth pieces."""
    p = Part()
    x0 = D_back - 0.022
    box_part(p, x0, x0 + 0.010, 0.305, 0.362, 0.036, 0.044)          # the handle
    box_part(p, x0 - 0.004, x0 + 0.014, 0.352, 0.368, 0.033, 0.047)  # ear piece
    box_part(p, x0 - 0.004, x0 + 0.014, 0.299, 0.315, 0.033, 0.047)  # mouth piece
    return p.mesh(mat(flat(colour), 0.1, 0.5, name="handset"))


def build_phone(im, ring=0):
    """A GTA2 pay phone booth at human scale (QB-36). The renderer's person is
    0.46 blocks (1.75 m), so a metre is 0.263 blocks: the booth is 0.95 m
    square (0.25 blocks), 2.24 m to the roof (0.59), its PHONE sign box 0.65 m
    long and 0.17 m tall on top (2.47 m overall). Drawn at this authored size
    ("objects_anim": "authored"), not stretched onto the sprite's 0.50-block
    quad, which made a 1.9 m wide booth with a 1.4 m sign.

    From the sprite's plan: open on the sprite's left (-x), the phone on the
    back wall (+x) with the handset on its right (frames 511/512 light the
    handset red when the phone rings). Corner posts, blue kick panels, glass
    side panes (a separate translucent model), a roof with a lit PHONE sign
    box (a separate unlit model, so it reads at night), a concrete plinth.

    Returns (main, lit, glass) scenes."""
    W, D, H = 0.125, 0.125, 0.59      # half width (x), half depth (z), roof height
    P = 0.010                         # half a corner post (7.6 cm square)
    K0, K1, R1, T0 = 0.015, 0.17, 0.185, 0.52   # plinth top, kick panel top, rail top, header bottom
    steel = mat(blue_steel(), 0.55, 0.4, name="booth_steel")
    dark = mat(blue_steel(BOOTH_DARK, seed=3), 0.55, 0.45, name="booth_dark")
    chrome = mat(flat((168, 172, 178)), 0.9, 0.25, name="chrome")
    frame = Part()
    for x in (-W, W):
        for z in (-D, D):
            box_part(frame, x - P, x + P, K0, H, z - P, z + P)
    # side kick panels and rails (z = +-D), the back wall (x = +W), front header
    for z in (-D, D):
        box_part(frame, -W, W, K0, K1, z - 0.004, z + 0.004)
        box_part(frame, -W, W, K1, R1, z - 0.007, z + 0.007)
        box_part(frame, -W, W, T0, H, z - 0.006, z + 0.006)
    # the back (+x): kick panel and rail like the sides, glass either side of a steel
    # spine (0.34 m) that carries the phone
    box_part(frame, W - 0.006, W, K0, K1, -D, D)
    box_part(frame, W - 0.008, W + 0.002, K1, R1, -D, D)
    box_part(frame, W - 0.006, W, T0, H, -D, D)
    box_part(frame, W - 0.006, W, R1, T0, -0.045, 0.045)
    box_part(frame, -W - 0.002, -W + 0.006, T0, H, -D, D)
    frame_m = frame.mesh(steel)
    roof = Part()
    box_part(roof, -W - 0.012, W + 0.012, H, H + 0.015, -D - 0.012, D + 0.012)
    roof_m = roof.mesh(dark)
    plinth = Part(); box_part(plinth, -W - 0.006, W + 0.006, 0.0, K0, -D - 0.006, D + 0.006)
    plinth_m = plinth.mesh(mat(flat((128, 126, 120)), 0.0, 0.85, name="plinth"))
    # the phone unit (23 x 50 x 11 cm, face 1.03-1.52 m up): a chrome box on the
    # back wall, keypad facing the opening (-x)
    unit = Part()
    ux0, ux1 = W - 0.006 - 0.030, W - 0.006
    uz0, uz1 = -0.030, 0.030
    uy0, uy1 = 0.27, 0.40
    unit.quad((ux0, uy0, uz1), (ux0, uy1, uz1), (ux0, uy1, uz0), (ux0, uy0, uz0), (1, 0), (1, 1), (0, 1), (0, 0))  # face (-x)
    box_sides = Part(); box_part(box_sides, ux0 + 0.001, ux1, uy0, uy1, uz0, uz1)
    unit_m = unit.mesh(mat(keypad_texture(), 0.7, 0.3, name="keypad"))
    unit_box = box_sides.mesh(chrome)
    shelf = Part(); box_part(shelf, W - 0.058, W - 0.006, 0.243, 0.250, -0.060, 0.060)   # the directory shelf
    box_part(shelf, W - 0.050, W - 0.012, 0.250, 0.262, -0.055, -0.012)             # the directory
    shelf_m = shelf.mesh(mat(flat((60, 62, 68)), 0.6, 0.5, name="shelf"))
    main = scene_with([("plinth", plinth_m), ("frame", frame_m), ("roof", roof_m), ("unit", unit_box), ("keypad", unit_m), ("shelf", shelf_m)])
    # lit: the roof sign box (PHONE on its long faces, toward -x and +x) and the handset
    sign = Part()
    sy0, sy1 = H + 0.015, H + 0.060
    sx0, sx1, sz0, sz1 = -0.016, 0.016, -0.085, 0.085
    sign.quad((sx0, sy0, sz1), (sx0, sy1, sz1), (sx0, sy1, sz0), (sx0, sy0, sz0), (0, 0), (0, 1), (1, 1), (1, 0))
    sign.quad((sx1, sy0, sz0), (sx1, sy1, sz0), (sx1, sy1, sz1), (sx1, sy0, sz1), (0, 0), (0, 1), (1, 1), (1, 0))
    sign_m = sign.mesh(mat(sign_texture(), 0.0, 0.6, name="sign"))
    ends = Part()
    ends.quad((sx0, sy0, sz0), (sx0, sy1, sz0), (sx1, sy1, sz0), (sx1, sy0, sz0))
    ends.quad((sx1, sy0, sz1), (sx1, sy1, sz1), (sx0, sy1, sz1), (sx0, sy0, sz1))
    ends.quad((sx0, sy1, sz1), (sx1, sy1, sz1), (sx1, sy1, sz0), (sx0, sy1, sz0))
    # and its bottom (FIX-WORLD-7 pm50): seen from below through the faded booth roof, the open
    # bottom showed the far face's lettering upside down under the sign.
    ends.quad((sx0, sy0, sz0), (sx1, sy0, sz0), (sx1, sy0, sz1), (sx0, sy0, sz1))
    # the sign box's ends and top: the roof's dark blue (an unlit near-white read as a
    # floating white tab from the side, demo of 9 Nov)
    ends_m = ends.mesh(mat(flat((34, 62, 124)), 0.0, 0.6, name="sign_rim"))
    hs_colour = [(26, 26, 30), (150, 30, 20), (255, 70, 40)][ring]
    lit = scene_with([("sign", sign_m), ("sign_rim", ends_m), ("handset", handset_parts(W - 0.006, hs_colour))])
    # glass: the side panes above the kick panels, and the back either side of the spine
    glass = Part()
    for z in (-D, D):
        box_part(glass, -W + P, W - P, R1, T0, z - 0.002, z + 0.002)
    for z0, z1 in ((-D + P, -0.045), (0.045, D - P)):
        box_part(glass, W - 0.004, W - 0.001, R1, T0, z0, z1)
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


def steel_texture(base, size=64, seed=1, stripes=0):
    """Blued steel with a faint brushed grain; `stripes` slide serrations across u."""
    rng = np.random.default_rng(seed)
    a = np.zeros((size, size, 3), np.float32) + np.array(base, np.float32)
    a += rng.normal(0, 3.0, (size, 1, 1)).astype(np.float32)          # grain along the length
    if stripes:
        u = np.arange(size)
        band = ((u * stripes // size) % 2 == 0)
        a[:, band] *= 0.62
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB")


def build_pistol_pickup(count=1):
    """FIX-WORLD-7 (pmr1-ste-third-weapon-pickup-reads-as-blurry-grey-slab-no-pistol-shape): the pistol
    pickup authored as a pistol, not the hand-held model blown up to 0.28 block (a 108-triangle slab
    that floated 0.42..1.2 m up and read as a grey plank). A side profile that reads as it turns:
    slide with rear serrations and sights, frame, muzzle, an open trigger guard with its trigger,
    a raked walnut grip and a hammer. 0.20 block long (0.77 m: a pickup is drawn larger than life
    to read like the classic sprite), lying on its side at knee height (0.05..0.19 block).
    Returns (main, lit)."""
    L = 0.10          # half length (z)
    T = 0.013         # half thickness of the slide (x)
    sy0, sy1 = 0.150, 0.186   # slide
    fy0 = 0.128               # frame below the slide
    steel = mat(steel_texture((92, 98, 112), seed=2), 0.75, 0.32, name="slide")
    serr = mat(steel_texture((92, 98, 112), seed=3, stripes=10), 0.75, 0.35, name="serrations")
    frame_m = mat(steel_texture((54, 58, 66), seed=4), 0.5, 0.5, name="frame")
    dark = mat(flat((14, 14, 16)), 0.2, 0.7, name="bore")
    wood = mat(steel_texture((128, 74, 38), seed=5), 0.0, 0.65, name="grip")
    meshes = []
    for k in range(count):
        dx = (k - (count - 1) / 2) * (2 * T + 0.03)
        slide = Part(); box_part(slide, dx - T, dx + T, sy0, sy1, -L + 0.022, L)
        box_part(slide, dx - 0.003, dx + 0.003, sy1, sy1 + 0.009, L - 0.014, L - 0.006)        # front sight
        box_part(slide, dx - T, dx - 0.004, sy1, sy1 + 0.010, -L + 0.008, -L + 0.018)          # rear sight, two ears
        box_part(slide, dx + 0.004, dx + T, sy1, sy1 + 0.010, -L + 0.008, -L + 0.018)
        rear = Part(); box_part(rear, dx - T, dx + T, sy0, sy1, -L, -L + 0.022)                  # serrated rear of the slide
        fr = Part()
        box_part(fr, dx - T + 0.002, dx + T - 0.002, fy0, sy0, -L + 0.004, L - 0.018)           # frame / dust cover
        box_part(fr, dx - 0.006, dx + 0.006, fy0 - 0.036, fy0 - 0.028, -0.050, 0.030)           # trigger guard, bottom bar
        box_part(fr, dx - 0.006, dx + 0.006, fy0 - 0.036, fy0, 0.022, 0.030)                    # trigger guard, front bar
        box_part(fr, dx - 0.003, dx + 0.003, fy0 - 0.026, fy0, -0.018, -0.010)                  # trigger
        box_part(fr, dx - 0.005, dx + 0.005, sy1 - 0.020, sy1 + 0.008, -L - 0.012, -L)          # hammer
        bore = Part(); box_part(bore, dx - 0.007, dx + 0.007, sy0 + 0.010, sy1 - 0.008, L, L + 0.004)  # the muzzle's dark bore
        # the grip: raked back 14 degrees, walnut panels over a steel core, a magazine base plate
        grip = Part(); box_part(grip, dx - T - 0.003, dx + T + 0.003, 0.058, fy0 + 0.004, -L + 0.006, -0.052)
        base = Part(); box_part(base, dx - T, dx + T, 0.050, 0.058, -L + 0.002, -0.048)
        rake = trimesh.transformations.rotation_matrix(math.radians(14), [1, 0, 0], point=[dx, fy0, -0.075])
        for part, m, nm in ((slide, steel, "slide"), (rear, serr, "rear"), (fr, frame_m, "frame"), (bore, dark, "bore"),
                            (grip, wood, "grip"), (base, frame_m, "base")):
            g = part.mesh(m)
            if nm in ("grip", "base"):
                g.apply_transform(rake)
            meshes.append((f"{nm}{k}", g))
    main = scene_with(meshes)
    lit = scene_with([("glow", glow_ring((90, 230, 110), 0.20, 0.235))])
    return main, lit


def build_weapon_model(src, name):
    """A weapon pickup in the street views: the hand-held weapon model (the same
    one a figure aims with), at pickup size, standing on its side a hand above
    the ground so its silhouette reads as it turns, over a green ring.
    Authored at its final size in blocks: the renderer draws spinning pickups
    at scale 1, not fitted to each frame's sprite extent (which made them pulse).
    Returns (main, lit)."""
    if name in ("pickup_pistol", "pickup_dual_pistol"):
        return build_pistol_pickup(2 if name == "pickup_dual_pistol" else 1)
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
def heart_outline(n=72):
    """The classic heart curve, unit width (x -0.5..0.5), lobes up (+y), point down; centred on its box."""
    t = np.linspace(0, 2 * math.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = 13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t)
    x, y = x / 34.0, y / 34.0
    y = y - 0.5 * (y.max() + y.min())
    return np.stack([x, y], 1)


def build_health_pickup(im):
    """FIX-WORLD-12 prz1: the health pickup (code objects 4:167-174, the classic red disc with a raised
    heart) as an upright red medallion with a puffy heart standing proud on both faces, turning like
    the weapon pickups, over a red ground ring. Before it was a coin lying flat a hand above the
    ground (as token_dollar): from the street a squashed red ellipse with the heart lost.
    Spinning pickups are drawn unlit, so the shading is baked: the disc's face a radial gradient from
    the sprite's red to its dark rim, the heart a ramp from its dark edge to a highlight on its crown.
    The heart goes in the __lit companion (unlit at every hour; Remix gives __lit textures an emissive
    prim), so it reads at night. Returns (main, lit)."""
    a = np.array(im.convert("RGBA")).reshape(-1, 4)
    a = a[a[:, 3] > 128][:, :3].astype(np.float32)
    lum = a.mean(1)
    face_rgb = tuple(int(v) for v in np.median(a[lum >= np.percentile(lum, 50)], 0))   # the disc's lit red
    rim_rgb = tuple(int(v) for v in np.median(a[lum <= np.percentile(lum, 15)], 0))    # its dark rim
    R, T, YC = 0.15, 0.036, 0.25          # disc radius, thickness, centre height (blocks)
    # the disc: an upright cylinder about z, planar UVs on x/y (the rim falls on the texture's edge)
    disc = trimesh.creation.cylinder(radius=R, height=T, sections=40)
    disc.apply_translation((0, YC, 0))
    uv = np.stack([(disc.vertices[:, 0] / R) * 0.5 + 0.5, ((disc.vertices[:, 1] - YC) / R) * 0.5 + 0.5], 1)
    N = 256
    yy, xx = np.mgrid[0:N, 0:N]
    r = np.sqrt((xx - N / 2 + 0.5) ** 2 + (yy - N / 2 + 0.5) ** 2) / (N / 2)
    face = np.array(face_rgb, np.float32)
    rim = np.array(rim_rgb, np.float32)
    k = np.clip((r - 0.80) / 0.20, 0, 1)[..., None]                       # the rolled rim, outer fifth
    shade = (1.08 - 0.22 * r)[..., None]                                 # a soft dome of light
    img = face * shade * (1 - k) + rim * (1 - 0.3 * k) * k
    img += 255 * 0.10 * np.exp(-((xx - N * 0.38) ** 2 + (yy - N * 0.34) ** 2) / (2 * (N * 0.12) ** 2))[..., None]
    disc_tex = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    disc.visual = TextureVisuals(uv=uv, material=mat(disc_tex, 0.15, 0.35, name="disc"))
    # the heart: bevelled layers of the outline, each layer a u position on a 1-D ramp
    out = heart_outline()
    W = 0.205                                              # heart width (blocks)
    layers = [(1.00, 0.000), (0.96, 0.007), (0.88, 0.013), (0.74, 0.018), (0.52, 0.021), (0.0, 0.022)]
    heart_rgb = np.array([min(255, face_rgb[0] + 30), min(255, face_rgb[1] + 25), min(255, face_rgb[2] + 20)], np.float32)
    ramp = np.zeros((4, 64, 3), np.float32)
    for i in range(64):
        f = i / 63
        ramp[:, i] = heart_rgb * (0.62 + 0.50 * f) + 255 * 0.22 * max(0.0, f - 0.7) / 0.3
    ramp_tex = Image.fromarray(np.clip(ramp, 0, 255).astype(np.uint8), "RGB")
    hy = YC - 0.004
    meshes = []
    for side in (1, -1):
        v, uvs, faces = [], [], []
        n = len(out)
        for li, (sc, dz) in enumerate(layers):
            u = li / (len(layers) - 1)
            for (x, y) in out if sc > 0 else [(0.0, 0.0)]:
                v.append((x * W * sc, hy + y * W * (sc if sc > 0 else 0), side * (T / 2 + dz)))
                uvs.append((0.02 + 0.96 * u, 0.5))
        for li in range(len(layers) - 2):
            b0, b1 = li * n, (li + 1) * n
            for j in range(n):
                j2 = (j + 1) % n
                q = [b0 + j, b0 + j2, b1 + j2, b1 + j]
                faces += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]] if side < 0 else [[q[0], q[2], q[1]], [q[0], q[3], q[2]]]
        top, cap = (len(layers) - 2) * n, (len(layers) - 1) * n
        for j in range(n):
            j2 = (j + 1) % n
            faces.append([top + j, top + j2, cap] if side < 0 else [top + j, cap, top + j2])
        m = trimesh.Trimesh(vertices=np.array(v, np.float32), faces=np.array(faces), process=False)
        m.visual = TextureVisuals(uv=np.array(uvs, np.float32), material=mat(ramp_tex, 0.1, 0.25, name="heart"))
        meshes.append((f"heart{'f' if side > 0 else 'b'}", m))
    main = scene_with([("disc", disc)])
    lit = scene_with(meshes + [("glow", glow_ring((235, 70, 60), 0.20, 0.235))])
    return main, lit


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
    f, im = fullest(src, HEALTH[0])
    m, lit = build_health_pickup(im)
    jobs.append((HEALTH[1], list(range(HEALTH[0], HEALTH[0] + 8)), m, {"__lit": lit}, im, "spin"))
    for first, name in MISC_PICKUPS.items():
        f, im = fullest(src, first)
        m, lit = build_item(im)
        jobs.append((name, list(range(first, first + 8)), m, {"__lit": lit}, im, "spin"))
    im = load(src, PHONE[0])
    for k, (fr, name) in enumerate(zip(PHONE, PHONE_NAMES)):
        main_m, lit, glass = build_phone(im, k)
        jobs.append((name, [fr], main_m, {"__lit": lit, "__glass": glass}, load(src, fr), "authored"))
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
