#!/usr/bin/env python3
"""Street furniture, dock and rooftop models for the street views, procedural,
in GTA2's retro-modern palette (dark teal steel, mustard yellow, rust, chrome).
Nothing third-party. Same conventions as gen_objects.py: units in blocks
(one block = 64 px = 2 m), origin at the footprint centre on the ground, +y up,
the long axis along +z, PBR materials, alpha cutouts where a plate is not a box.

    gen_env2.py <out glb dir> [--sheet out.png]

Models: sign_stop, sign_oneway, bus_shelter, parking_meter, mailbox,
container_1..4, crane, roof_ac, roof_vent, water_tower, rail (one block of
elevated track: rails, sleepers and the side girders that stand on the lid).
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh
from trimesh.visual.material import PBRMaterial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_objects as G  # noqa: E402  (Part, box_part, cylinder_part, scene_with, render)

TEAL = (38, 84, 86)        # GTA2's dark teal steel
TEAL_LIGHT = (62, 118, 118)
MUSTARD = (214, 168, 44)
RUST = (118, 62, 38)
CHROME = (190, 196, 200)
DARK = (34, 36, 40)
POST = (120, 124, 128)


def font(size):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except Exception:
        return ImageFont.load_default()


def noisy(rgb, size=64, amount=10, seed=1):
    rng = np.random.default_rng(seed)
    base = np.array(rgb, np.float32)[None, None, :] + rng.uniform(-amount, amount, (size, size, 1))
    a = np.full((size, size, 1), 255, np.float32)
    return Image.fromarray(np.clip(np.concatenate([base, a], 2), 0, 255).astype(np.uint8), "RGBA")


def mat(img, metal=0.0, rough=0.7, name="m"):
    return PBRMaterial(baseColorTexture=img, metallicFactor=metal, roughnessFactor=rough, name=name)


def rot_y(points, deg, cx=0.0, cz=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    out = []
    for x, y, z in points:
        x -= cx; z -= cz
        out.append((cx + c * x + s * z, y, cz - s * x + c * z))
    return out


def tilted_box(part, x0, x1, y0, y1, z0, z1, pitch_deg, pivot):
    """A box rotated about the x axis through `pivot` (y, z): used for a crane boom."""
    c, s = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    py, pz = pivot

    def R(p):
        x, y, z = p
        y -= py; z -= pz
        return (x, py + c * y - s * z, pz + s * y + c * z)
    faces = [
        [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
        [(x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0)],
        [(x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1)],
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
    ]
    for f in faces:
        part.quad(*[R(p) for p in f])


def plate(part, w, h, y_centre, z, thick=0.012, u_flip=False, back=None, back_grow=0.0):
    """A vertical plate facing -z (the viewer on the pavement). The back face goes into
    `back` when given (a part of its own, so it can carry a plain metal texture: a
    stop sign seen from behind must not read STOP mirrored), else into `part` with the
    same picture.

    UVs are trimesh's (v=0 at the picture's bottom; the glb export turns them over), so
    the plate's bottom edge takes v=0: with v=0 at the top the picture stood on its head
    in game. And the renderer draws the glb's right-handed coordinates in D3D's
    left-handed space with no flip, so the front face shows its picture mirrored left to
    right: a front with text or an arrow is given the picture MIRRORED (FLIP_LEFT_RIGHT)
    and then reads right; the back face, seen from +z, reads a picture as drawn.
    (Defects pt-stopsign-back-mirrored / tri-plate-text-mirrored-oneway-bus: runs
    out/tri_signs1..4 tried the four combinations; this is the one that reads.)"""
    x0, x1 = -w / 2, w / 2
    y0, y1 = y_centre - h / 2, y_centre + h / 2
    part.quad((x0, y0, z), (x0, y1, z), (x1, y1, z), (x1, y0, z), (1, 0), (1, 1), (0, 1), (0, 0))                 # front (-z), read from -z
    # back_grow: the back a little larger than the front, so seen from behind it covers the
    # front picture's edge (the stop sign's red rim showed as stray pixels past the back).
    g = back_grow
    (back if back is not None else part).quad((x1 + g, y0 - g, z + thick), (x1 + g, y1 + g, z + thick), (x0 - g, y1 + g, z + thick), (x0 - g, y0 - g, z + thick), (0, 0), (0, 1), (1, 1), (1, 0))  # back


def post(part, r, y0, y1, x=0.0, z=0.0, segments=16):
    """A round post with smooth (radial) normals, so lit it reads as a tube, not facets."""
    ring = [(x + r * math.cos(2 * math.pi * s / segments), z + r * math.sin(2 * math.pi * s / segments)) for s in range(segments + 1)]
    for s in range(segments):
        (ax, az), (bx, bz) = ring[s], ring[s + 1]
        b = len(part.v)
        na = np.array(((ax - x) / r, 0.0, (az - z) / r), np.float32)
        nb = np.array(((bx - x) / r, 0.0, (bz - z) / r), np.float32)
        part.v += [np.array(q, np.float32) for q in ((ax, y0, az), (ax, y1, az), (bx, y1, bz), (bx, y0, bz))]
        part.n += [na, na, nb, nb]
        part.uv += [(0, 1), (0, 0), (0.3, 0), (0.3, 1)]
        part.f += [[b, b + 1, b + 2], [b, b + 2, b + 3]]   # the winding Part.quad gave it
    # cap
    for s in range(segments):
        (ax, az), (bx, bz) = ring[s], ring[s + 1]
        b = len(part.v)
        part.v += [np.array((x, y1, z), np.float32), np.array((bx, y1, bz), np.float32), np.array((ax, y1, az), np.float32)]
        part.n += [np.array((0, 1, 0), np.float32)] * 3
        part.uv += [(0.5, 0.5)] * 3
        part.f += [[b, b + 1, b + 2]]


# --- textures -----------------------------------------------------------------

def stop_face(size=256):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = size / 2; r = size * 0.48
    oct_pts = [(c + r * math.cos(math.radians(22.5 + 45 * i)), c + r * math.sin(math.radians(22.5 + 45 * i))) for i in range(8)]
    d.polygon(oct_pts, fill=(196, 30, 36, 255), outline=(240, 240, 240, 255), width=max(2, size // 40))
    f = font(size // 4)
    tw = d.textlength("STOP", font=f)
    d.text((c - tw / 2, c - size * 0.15), "STOP", font=f, fill=(245, 245, 245, 255))
    return im


def stop_back(size=256):
    """The back of a stop plate: painted dark grey steel in the same octagon (same alpha
    cut-out as the face), a darker rim, the bracket strap where it meets the post and its
    bolts. (Defect pm17-wil-third-sign-panel-blank-white-slab: the light galvanised grey,
    150, read as a blank white slab in the sun.)"""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = size / 2; r = size * 0.48
    oct_pts = [(c + r * math.cos(math.radians(22.5 + 45 * i)), c + r * math.sin(math.radians(22.5 + 45 * i))) for i in range(8)]
    d.polygon(oct_pts, fill=(62, 65, 70, 255), outline=(120, 124, 130, 255), width=max(3, size // 32))   # a brighter rolled rim
    rng = np.random.default_rng(3)
    a = np.array(im, np.float32)
    a[..., :3] += rng.uniform(-4, 4, (size, size, 1)) * (a[..., 3:4] > 0)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(im)
    s = size // 18
    d.rectangle((c - s, c - r * 0.85, c + s, c + r * 0.85), fill=(40, 42, 46, 255))   # bracket strap
    for y in (c - r * 0.6, c + r * 0.6):
        d.ellipse((c - s * 0.7, y - s * 0.7, c + s * 0.7, y + s * 0.7), fill=(118, 120, 124, 255))   # bolt heads
    return im


def oneway_face(size=(256, 96)):
    im = Image.new("RGBA", size, (24, 24, 28, 255))
    d = ImageDraw.Draw(im)
    w, h = size
    d.rectangle((3, 3, w - 4, h - 4), outline=(235, 235, 235, 255), width=3)
    # arrow
    d.polygon([(w * 0.12, h * 0.5), (w * 0.62, h * 0.12), (w * 0.62, h * 0.36), (w * 0.92, h * 0.36), (w * 0.92, h * 0.64), (w * 0.62, h * 0.64), (w * 0.62, h * 0.88)], fill=(240, 240, 240, 255))
    f = font(h // 3)
    d.text((w * 0.16, h * 0.62), "ONE WAY", font=f, fill=(240, 240, 240, 255))
    return im


def bus_face(size=(192, 96)):
    im = Image.new("RGBA", size, MUSTARD + (255,))
    d = ImageDraw.Draw(im)
    d.rectangle((3, 3, size[0] - 4, size[1] - 4), outline=DARK + (255,), width=4)
    f = font(size[1] // 2)
    tw = d.textlength("BUS", font=f)
    d.text((size[0] / 2 - tw / 2, size[1] * 0.18), "BUS", font=f, fill=DARK + (255,))
    return im


def meter_face(size=128):
    im = Image.new("RGBA", (size, size), (150, 152, 156, 255))
    d = ImageDraw.Draw(im)
    d.rectangle((size * 0.2, size * 0.15, size * 0.8, size * 0.55), fill=(30, 32, 36, 255), outline=(90, 90, 90, 255), width=2)
    d.rectangle((size * 0.26, size * 0.22, size * 0.74, size * 0.48), fill=(196, 40, 40, 255))
    f = font(size // 9)
    d.text((size * 0.3, size * 0.27), "EXPIRED", font=f, fill=(250, 240, 220, 255))
    d.ellipse((size * 0.42, size * 0.65, size * 0.58, size * 0.81), fill=(60, 60, 64, 255))
    return im


def paint(rgb, size=64):
    """Painted steel: the colour with a faint large-scale mottle, no per-pixel speckle."""
    rng = np.random.default_rng(7)
    low = rng.uniform(-1, 1, (4, 4)).astype(np.float32)
    mottle = np.array(Image.fromarray(((low + 1) * 127.5).astype(np.uint8)).resize((size, size), Image.BICUBIC), np.float32) / 127.5 - 1
    base = np.array(rgb, np.float32)[None, None, :] * (1.0 + 0.04 * mottle[:, :, None])
    a = np.full((size, size, 1), 255, np.float32)
    return Image.fromarray(np.clip(np.concatenate([base, a], 2), 0, 255).astype(np.uint8), "RGBA")


def mail_face(size=(240, 256)):
    """The collection box's front door: the body's paint, a dark door seam inset from the edge,
    the MAIL stencil with a round emblem above it and a lock plate at the bottom."""
    im = paint((30, 66, 138), size=256).resize(size)
    d = ImageDraw.Draw(im)
    W, H = size
    white, seam = (236, 238, 242, 255), (14, 26, 52, 255)
    d.rectangle((W * 0.06, H * 0.05, W * 0.94, H * 0.95), outline=seam, width=max(2, W // 80))
    f = font(W // 5)
    tw = d.textlength("MAIL", font=f)
    d.text((W / 2 - tw / 2, H * 0.44), "MAIL", font=f, fill=white)
    cx, cy, r = W / 2, H * 0.27, W * 0.11
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=white, width=max(3, W // 50))
    d.rectangle((cx - r * 0.65, cy - r * 0.14, cx + r * 0.65, cy + r * 0.14), fill=white)
    d.rectangle((W * 0.2, H * 0.70, W * 0.8, H * 0.715), fill=white)
    d.rectangle((W * 0.44, H * 0.80, W * 0.56, H * 0.88), fill=(150, 156, 164, 255), outline=seam)   # the lock plate
    return im


def corrugated(rgb, size=256, seed=3):
    rng = np.random.default_rng(seed)
    x = np.arange(size)
    stripe = (0.86 + 0.14 * np.cos(x * 2 * math.pi / 16.0))[None, :, None]
    base = np.array(rgb, np.float32)[None, None, :] * stripe
    rust = rng.uniform(0, 1, (size, size, 1)) ** 6 * 70
    base = base * (1 - rust / 120) + np.array(RUST, np.float32)[None, None, :] * (rust / 120)
    base += rng.uniform(-6, 6, (size, size, 1))
    a = np.full((size, size, 1), 255, np.float32)
    im = Image.fromarray(np.clip(np.concatenate([base, a], 2), 0, 255).astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(im)
    d.line((0, size * 0.5, size, size * 0.5), fill=tuple(max(0, c - 40) for c in rgb) + (255,), width=3)   # a weld line
    return im


def container_door(rgb, size=256):
    im = corrugated(rgb, size, seed=5)
    d = ImageDraw.Draw(im)
    for x in (size * 0.22, size * 0.42, size * 0.58, size * 0.78):
        d.rectangle((x - 4, 8, x + 4, size - 8), fill=tuple(max(0, c - 50) for c in rgb) + (255,))
        d.rectangle((x - 2, 8, x + 2, size - 8), fill=CHROME + (255,))
    d.line((0, size * 0.5 - 1, size, size * 0.5 - 1), fill=DARK + (255,), width=4)
    return im


def grille(size=128):
    im = Image.new("RGBA", (size, size), (96, 100, 104, 255))
    d = ImageDraw.Draw(im)
    d.ellipse((size * 0.1, size * 0.1, size * 0.9, size * 0.9), fill=(40, 42, 46, 255), outline=(70, 72, 76, 255), width=3)
    for i in range(6):
        a = math.radians(i * 60)
        d.line((size / 2, size / 2, size / 2 + size * 0.38 * math.cos(a), size / 2 + size * 0.38 * math.sin(a)), fill=(130, 132, 136, 255), width=5)
    d.ellipse((size * 0.44, size * 0.44, size * 0.56, size * 0.56), fill=(120, 120, 124, 255))
    return im


def lattice(size=128, rgb=TEAL):
    """Cross-braced girder face: steel diagonals on a cutout, for crane legs and rail sides."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    col = tuple(rgb) + (255,)
    t = max(4, size // 14)
    d.rectangle((0, 0, size, t), fill=col); d.rectangle((0, size - t, size, size), fill=col)
    d.rectangle((0, 0, t, size), fill=col); d.rectangle((size - t, 0, size, size), fill=col)
    d.line((0, 0, size, size), fill=col, width=t); d.line((0, size, size, 0), fill=col, width=t)
    return im


def wood(size=128, seed=7):
    rng = np.random.default_rng(seed)
    y = np.arange(size)[:, None]
    base = np.array((112, 78, 50), np.float32)[None, None, :] * (0.85 + 0.15 * np.sin(y * 0.9)[:, :, None]) + rng.uniform(-10, 10, (size, size, 1))
    a = np.full((size, size, 1), 255, np.float32)
    return Image.fromarray(np.clip(np.concatenate([base, a], 2), 0, 255).astype(np.uint8), "RGBA")


# --- builders -----------------------------------------------------------------

# Scale. An adult figure is 0.46 block (live_geometry.cpp kPedHeight), so a metre is
# about 0.263 block: every rule prop here is authored at its real size on that scale
# (FIX-PROPS-3; they were made at 2 m a block, so a meter stood 2.5 m and a stop sign 4 m).
MPB = 0.263   # blocks per metre


def build_sign_stop():
    """A stop sign: a 75 cm octagon on a 6 cm galvanised post, its centre 2.1 m up (2.5 m overall)."""
    p_post, p_plate, p_back = G.Part(), G.Part(), G.Part()
    size, yc = 0.75 * MPB, 2.1 * MPB
    z0, thick = -0.006, 0.004
    post(p_post, 0.03 * MPB, 0.0, yc + 0.4 * size)
    plate(p_plate, size, size, yc, z0, thick=thick, back=p_back, back_grow=0.002)
    # The plate's edge: an octagonal band between the face and the back, so from an angle
    # behind it the face's red rim no longer shows past the back (defect pm17).
    r, z1 = size * 0.48 * 0.99, z0 + thick
    for i in range(8):
        a0, a1 = math.radians(22.5 + 45 * i), math.radians(22.5 + 45 * (i + 1))
        xa, ya, xb, yb = r * math.cos(a0), yc + r * math.sin(a0), r * math.cos(a1), yc + r * math.sin(a1)
        p_post.quad((xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1))
    # the clamp strap on the post behind the plate
    G.box_part(p_post, -0.012, 0.012, yc - 0.012, yc + 0.012, z1, z1 + 0.012)
    return G.scene_with([("post", p_post.mesh(mat(noisy(POST, amount=6), 0.8, 0.45, "post"))),
                         # The face mirrored (see plate()); the back is plain metal.
                         ("plate", p_plate.mesh(mat(stop_face().transpose(Image.FLIP_LEFT_RIGHT), 0.1, 0.5, "plate"))),
                         ("plate_back", p_back.mesh(mat(stop_back(), 0.7, 0.45, "plate_back")))])


def build_sign_oneway():
    """A one-way plate, 90 x 30 cm, its centre 2.2 m up on a 6 cm post.
    Two parts: the front shows its picture mirrored, the back (seen from the other side)
    as drawn, so the front gets the picture mirrored: "ONE WAY" reads left to right from
    both sides (see plate())."""
    p_post, p_plate, p_back = G.Part(), G.Part(), G.Part()
    w, h, yc = 0.9 * MPB, 0.3 * MPB, 2.2 * MPB
    post(p_post, 0.03 * MPB, 0.0, yc + h / 2 + 0.01)
    plate(p_plate, w, h, yc, -0.006, thick=0.004, back=p_back)
    face = oneway_face()
    return G.scene_with([("post", p_post.mesh(mat(noisy(POST, amount=6), 0.8, 0.45, "post"))),
                         ("plate", p_plate.mesh(mat(face.transpose(Image.FLIP_LEFT_RIGHT), 0.1, 0.5, "plate"))),
                         ("plate_back", p_back.mesh(mat(face, 0.1, 0.5, "plate_back")))])


# The bus shelter (FIX-PROPS-3): 3.4 m long, 1.4 m deep, 2.5 m to the roof's edge, open to
# the road (-x), glazed at the back (+x) and at one end (+z). The glass is its own model,
# bus_shelter__glass, drawn translucent after every opaque prop (DrawProps).
SH_X, SH_Z, SH_H = 0.70 * MPB, 1.70 * MPB, 2.40 * MPB     # half depth, half length, post height
SH_P = 0.04 * MPB                                          # half a post (8 cm square)
SH_G0, SH_G1 = 0.10 * MPB, 2.25 * MPB                      # the glass's bottom and top


def glass_sheet(size=128, tint=(150, 182, 196), alpha=34, seed=5):
    """Clear tinted glass: mostly see-through (alpha about 0.13), a soft broad sheen across
    it and a little grime toward the bottom edge. Smooth gradients only: a hard one-texel
    streak on a 64 px sheet stair-stepped into a zigzag (the booth's panes, demo 9 Nov)."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    a = np.full((size, size), float(alpha), np.float32)
    rgb = np.zeros((size, size, 3), np.float32) + np.array(tint, np.float32)
    for c, w, k in ((0.32, 0.12, 30.0), (0.55, 0.035, 22.0)):   # two diagonal sheens, faint, soft-edged
        d = (x + 0.6 * y) / 1.6 - c
        band = np.exp(-(d / w) ** 2)
        a += k * band
        rgb += (240.0 - rgb) * 0.45 * band[..., None]
    grime = np.clip((y - 0.82) / 0.18, 0.0, 1.0) ** 2           # v grows downward in the picture
    rng = np.random.default_rng(seed)
    low = np.array(Image.fromarray((rng.uniform(0, 255, (8, 8))).astype(np.uint8)).resize((size, size), Image.BICUBIC), np.float32) / 255.0
    a += grime * (24.0 + 16.0 * low)
    rgb = rgb * (1.0 - 0.35 * grime[..., None]) + np.array((96, 92, 80), np.float32) * 0.35 * grime[..., None]
    out = np.concatenate([np.clip(rgb, 0, 255), np.clip(a, 0, 255)[..., None]], 2)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def build_bus_shelter():
    frame, roof, trim, bench, sign, legs = G.Part(), G.Part(), G.Part(), G.Part(), G.Part(), G.Part()
    X, Z, H, P = SH_X, SH_Z, SH_H, SH_P
    # Posts at the four corners and one at the middle of the back.
    for z in (-Z, Z):
        for x in (-X, X):
            G.box_part(frame, x - P, x + P, 0.0, H, z - P, z + P)
    G.box_part(frame, X - P, X + P, 0.0, H, -P, P)
    # The glazing frame: rails along the bottom and the top of the back and the end pane.
    r = 0.015 * MPB
    for y0 in (SH_G0 - 2 * r, SH_G1):
        G.box_part(frame, X - r, X + r, y0, y0 + 2 * r, -Z, Z)
        G.box_part(frame, -X, X, y0, y0 + 2 * r, Z - r, Z + r)
    # The roof: a mustard canopy with an overhang, a teal fascia round its edge.
    G.box_part(roof, -X - 0.06, X + 0.03, H, H + 0.012, -Z - 0.035, Z + 0.035)
    G.box_part(trim, -X - 0.064, X + 0.034, H - 0.008, H + 0.016, -Z - 0.039, -Z - 0.033)
    G.box_part(trim, -X - 0.064, X + 0.034, H - 0.008, H + 0.016, Z + 0.033, Z + 0.039)
    G.box_part(trim, -X - 0.066, -X - 0.058, H - 0.008, H + 0.016, -Z - 0.039, Z + 0.039)
    # The bench along the back: seat 45 cm up, 2 m long, on two legs.
    sy, bz = 0.45 * MPB, 1.0 * MPB
    G.box_part(bench, X - P - 0.40 * MPB, X - P, sy - 0.012, sy, -bz, bz)
    G.box_part(bench, X - P - 0.02, X - P, sy, sy + 0.30 * MPB, -bz, bz)          # the back rest
    for z in (-0.8 * MPB, 0.8 * MPB):
        G.box_part(legs, X - P - 0.34 * MPB, X - P - 0.30 * MPB, 0.0, sy - 0.012, z - 0.006, z + 0.006)
    # The BUS sign on its own post at the front corner, toward the oncoming traffic.
    sx, sz = -X - 0.06, -Z - 0.10
    post(sign, 0.03 * MPB, 0.0, 2.75 * MPB, x=sx, z=sz)
    plate_sign, plate_sign_back = G.Part(), G.Part()
    pw, ph = 0.45 * MPB, 0.22 * MPB
    plate(plate_sign, pw, ph, 2.62 * MPB, -0.006, thick=0.004, back=plate_sign_back)
    # the plate faces -z here; the shelter's road side is -x, so turn it about the y axis
    # and stand it at the post
    for part in (plate_sign, plate_sign_back):
        part.v = [np.array(q, np.float32) + np.array((sx, 0, sz), np.float32) for q in rot_y([tuple(v) for v in part.v], 90)]
        part.n = [np.array(q, np.float32) for q in rot_y([tuple(n) for n in part.n], 90)]
    return G.scene_with([("frame", frame.mesh(mat(paint(TEAL), 0.6, 0.45, "frame"))),
                         ("roof", roof.mesh(mat(paint(MUSTARD), 0.3, 0.55, "roof"))),
                         ("trim", trim.mesh(mat(paint(TEAL_LIGHT), 0.6, 0.45, "trim"))),
                         ("bench", bench.mesh(mat(wood(), 0.0, 0.8, "bench"))),
                         ("legs", legs.mesh(mat(noisy(DARK, amount=4), 0.7, 0.45, "legs"))),
                         ("signpost", sign.mesh(mat(noisy(POST, amount=6), 0.8, 0.45, "post"))),
                         # front mirrored, back as drawn: "BUS" reads left to right from both sides (see plate())
                         ("sign", plate_sign.mesh(mat(bus_face().transpose(Image.FLIP_LEFT_RIGHT), 0.1, 0.5, "sign"))),
                         ("sign_back", plate_sign_back.mesh(mat(bus_face(), 0.1, 0.5, "sign_back")))])


def build_bus_shelter_glass():
    """The shelter's panes (pm6-bus-shelter-glass-opaque-flat-pale-blue-pane): the back in two
    panes either side of the middle post, and the end pane, 6 mm sheets."""
    X, Z, P = SH_X, SH_Z, SH_P
    g = G.Part()
    t = 0.003
    for z0, z1 in ((-Z + P, -P), (P, Z - P)):
        G.box_part(g, X - t, X + t, SH_G0, SH_G1, z0, z1)
    G.box_part(g, -X + P, X - P, SH_G0, SH_G1, Z - t, Z + t)
    return G.scene_with([("glass", g.mesh(mat(glass_sheet(), 0.0, 0.05, "glass")))])


def meter_dial(size=128):
    """A 1950s meter's window: a white dial, the red EXPIRED flag up, the coin slot below."""
    im = Image.new("RGBA", (size, size), (168, 172, 178, 255))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((size * 0.12, size * 0.08, size * 0.88, size * 0.62), radius=size * 0.2, fill=(52, 54, 58, 255))
    d.pieslice((size * 0.18, size * 0.14, size * 0.82, size * 0.78), 180, 360, fill=(238, 236, 226, 255))
    for k in range(7):
        a = math.pi * (1 + k / 6)
        cx, cy, r = size * 0.5, size * 0.46, size * 0.3
        d.line((cx + r * 0.8 * math.cos(a), cy + r * 0.8 * math.sin(a), cx + r * math.cos(a), cy + r * math.sin(a)), fill=(30, 30, 30, 255), width=2)
    d.polygon([(size * 0.5, size * 0.46), (size * 0.36, size * 0.2), (size * 0.47, size * 0.17)], fill=(200, 30, 30, 255))   # the flag
    f = font(size // 11)
    d.text((size * 0.3, size * 0.5), "EXPIRED", font=f, fill=(200, 30, 30, 255))
    d.rectangle((size * 0.44, size * 0.72, size * 0.56, size * 0.76), fill=(20, 20, 22, 255))       # coin slot
    d.ellipse((size * 0.42, size * 0.82, size * 0.58, size * 0.94), fill=(110, 112, 118, 255))      # the turn handle
    return im


def build_parking_meter():
    """A 1950s parking meter at its real size (FIX-PROPS-3): a 5 cm steel post 1.0 m tall on a
    flange, a collar, and a chrome head 17 x 12 cm with a rounded top and a dial window on both
    faces (toward the kerb and the pavement); 1.37 m overall, a figure's chest."""
    p, head, face, trim = G.Part(), G.Part(), G.Part(), G.Part()
    py = 1.0 * MPB
    post(p, 0.025 * MPB, 0.0, py)
    G.cylinder_part(trim, lambda t: 0.06 * MPB, 0.0, 0.01, segments=16, rings=1)       # flange
    G.cylinder_part(trim, lambda t: (0.045 - 0.012 * t) * MPB, py, py + 0.06 * MPB, segments=16, rings=1)   # collar
    W, D, y0, y1 = 0.085 * MPB, 0.06 * MPB, py + 0.06 * MPB, py + 0.29 * MPB
    G.box_part(head, -W, W, y0, y1, -D, D)
    seg = 12
    for k in range(seg):   # the rounded top: a half cylinder across x, smooth normals
        a0, a1 = math.pi * k / seg, math.pi * (k + 1) / seg
        xa, ya = -W * math.cos(a0), y1 + W * 0.8 * math.sin(a0)
        xb, yb = -W * math.cos(a1), y1 + W * 0.8 * math.sin(a1)
        b = len(head.v)
        for q in ((xa, ya, D), (xb, yb, D), (xb, yb, -D), (xa, ya, -D)):
            head.v.append(np.array(q, np.float32))
            nx, ny = q[0] / W, (q[1] - y1) / (0.8 * W)
            L = math.hypot(nx, ny) or 1.0
            head.n.append(np.array((nx / L, ny / L, 0.0), np.float32))
        head.uv += [(0, 0), (0, 1), (1, 1), (1, 0)]
        head.f += [[b, b + 1, b + 2], [b, b + 2, b + 3]]
        for z, sgn in ((D, 1), (-D, -1)):   # the end caps of the dome
            b = len(head.v)
            pts = [(0.0, y1, z), (xa, ya, z), (xb, yb, z)] if sgn > 0 else [(0.0, y1, z), (xb, yb, z), (xa, ya, z)]
            head.v += [np.array(q, np.float32) for q in pts]
            head.n += [np.array((0, 0, sgn), np.float32)] * 3
            head.uv += [(0.5, 0.5)] * 3
            head.f += [[b, b + 1, b + 2]]
    plate(face, 2 * W * 0.88, (y1 - y0) * 0.9, 0.5 * (y0 + y1) + 0.01 * MPB, -D - 0.0015, thick=2 * D + 0.003)
    return G.scene_with([("post", p.mesh(mat(noisy(POST, amount=6), 0.8, 0.45, "post"))),
                         ("trim", trim.mesh(mat(noisy(DARK, amount=4), 0.7, 0.45, "trim"))),
                         ("head", head.mesh(mat(noisy(CHROME, amount=5), 0.85, 0.3, "head"))),
                         ("face", face.mesh(mat(meter_dial(), 0.3, 0.4, "face")))])


def build_mailbox():
    """A US-style collection box at the figures' scale: an adult is 0.46 block (live_geometry.cpp
    kPedHeight, so 1 m is about 0.26 block), and the box is 1.2 m tall, 0.52 m wide: 0.305 block,
    a little above a figure's hip. A matt blue painted-steel body with a rounded top, a dark
    pull-down slot under it, the door seam and MAIL stencil on the front, standing on a short
    pedestal and foot plate of its own. Front at -z (the DLL turns it away from the wall).
    (Defect pm-mailbox-prop-oversized-blue-box-on-legs: the first one stood on four detached
    sticks; the second, 0.55 block, was sized at 2 m a block and stood 2.2 m beside the figures.)"""
    body, base, slot, front = G.Part(), G.Part(), G.Part(), G.Part()
    W, D, Y0, Y1 = 0.067, 0.064, 0.06, 0.238   # half width (x), half depth (z), body bottom, dome spring line
    G.box_part(body, -W, W, Y0, Y1, -D, D)
    seg = 12
    for s_ in range(seg):   # the rounded top: a half cylinder along z, with end caps
        a0, a1 = math.pi * s_ / seg, math.pi * (s_ + 1) / seg
        xa, ya = -W * math.cos(a0), Y1 + W * math.sin(a0)
        xb, yb = -W * math.cos(a1), Y1 + W * math.sin(a1)
        k = len(body.v)
        for q in ((xa, ya, D), (xb, yb, D), (xb, yb, -D), (xa, ya, -D)):   # smooth normals on the dome
            body.v.append(np.array(q, np.float32))
            body.n.append(np.array((q[0] / W, (q[1] - Y1) / W, 0.0), np.float32))
        body.uv += [(0, 0), (0, 1), (1, 1), (1, 0)]
        body.f += [[k, k + 1, k + 2], [k, k + 2, k + 3]]
        for z, sgn in ((D, 1), (-D, -1)):
            k = len(body.v)
            pts = [(0.0, Y1, z), (xa, ya, z), (xb, yb, z)] if sgn > 0 else [(0.0, Y1, z), (xb, yb, z), (xa, ya, z)]
            body.v += [np.array(q, np.float32) for q in pts]
            body.n += [np.array((0, 0, sgn), np.float32)] * 3
            body.uv += [(0.5, 0.5)] * 3
            body.f += [[k, k + 1, k + 2]]
    # the pedestal the body sits on (meets it at Y0) and the foot plate under it
    G.box_part(base, -0.048, 0.048, 0.012, Y0, -0.044, 0.044)
    G.box_part(base, -0.062, 0.062, 0.0, 0.012, -0.058, 0.058)
    # the pull-down slot: a dark lip proud of the front, under the dome
    G.box_part(slot, -0.046, 0.046, 0.206, 0.224, -D - 0.008, -D)
    plate(front, 2 * W - 0.008, Y1 - Y0 - 0.044, 0.5 * (Y0 + Y1) - 0.012, -D - 0.0015, thick=0.0)
    blue = (30, 66, 138)
    return G.scene_with([("body", body.mesh(mat(paint(blue), 0.35, 0.55, "steel"))),
                         ("base", base.mesh(mat(noisy(DARK, amount=3), 0.5, 0.6, "base"))),
                         ("slot", slot.mesh(mat(noisy((40, 46, 56), amount=2), 0.6, 0.4, "slot"))),
                         ("front", front.mesh(mat(mail_face().transpose(Image.FLIP_LEFT_RIGHT),   # plate() front: mirrored picture reads right
                     0.35, 0.55, "front")))])


def build_container(rgb, seed):
    body, doors = G.Part(), G.Part()
    L, W, H = 1.9, 0.46, 0.5
    G.box_part(body, -W / 2, W / 2, 0.0, H, -L / 2, L / 2 - 0.02)
    plate(doors, W, H, H / 2, L / 2 - 0.005, thick=0.02)
    # the plate faces -z; the doors are at +z: flip it round
    doors.v = [np.array(q, np.float32) for q in rot_y([tuple(v) for v in doors.v], 180)]
    doors.n = [np.array(q, np.float32) for q in rot_y([tuple(n) for n in doors.n], 180)]
    # the steel frame: corner posts and top/bottom rails, a shade darker, standing proud of the sides
    frame = G.Part()
    e = 0.025
    for x in (-W / 2 + e - 0.004, W / 2 - e + 0.004):
        for z in (-L / 2 + e, L / 2 - e):
            G.box_part(frame, x - e, x + e, 0.0, H, z - e, z + e)
    for y in (0.0, H - 2 * e):
        for x in (-W / 2, W / 2):
            G.box_part(frame, x - 0.004, x + 0.004, y, y + 2 * e, -L / 2, L / 2)
        for z in (-L / 2, L / 2):
            G.box_part(frame, -W / 2, W / 2, y, y + 2 * e, z - 0.004, z + 0.004)
    return G.scene_with([("body", body.mesh(mat(corrugated(rgb, seed=seed), 0.6, 0.55, "body"))),
                         ("doors", doors.mesh(mat(container_door(rgb), 0.6, 0.55, "doors"))),
                         ("frame", frame.mesh(mat(noisy(tuple(int(c * 0.7) for c in rgb), amount=6), 0.6, 0.5, "frame")))])


def build_crane():
    legs, deck, cab, boom, cable, hook = G.Part(), G.Part(), G.Part(), G.Part(), G.Part(), G.Part()
    # Gantry: four lattice legs, a deck, a cab, a boom pitched up over +z, a cable and hook.
    for x in (-0.45, 0.45):
        for z in (-0.35, 0.35):
            G.box_part(legs, x - 0.05, x + 0.05, 0.0, 1.8, z - 0.05, z + 0.05)
    G.box_part(deck, -0.55, 0.55, 1.8, 1.92, -0.45, 0.45)
    G.box_part(cab, -0.18, 0.18, 1.92, 2.3, -0.2, 0.2)
    G.box_part(cab, -0.2, 0.2, 2.3, 2.34, -0.22, 0.22)
    tilted_box(boom, -0.07, 0.07, 2.1, 2.24, 0.0, 3.2, -28.0, (2.17, 0.0))     # boom: 3.2 blocks, 28 degrees up
    # a counterweight at the back
    G.box_part(boom, -0.16, 0.16, 1.95, 2.25, -0.55, -0.25)
    # tip of the boom, after the pitch
    c, s = math.cos(math.radians(-28.0)), math.sin(math.radians(-28.0))
    tip_y = 2.17 + s * 0.0 - 0.0; tip_z = 0.0
    yb, zb = 0.0, 3.1
    tip_y = 2.17 + c * yb - s * zb; tip_z = 0.0 + s * yb + c * zb
    G.box_part(cable, -0.008, 0.008, tip_y - 1.3, tip_y, tip_z - 0.008, tip_z + 0.008)
    G.box_part(hook, -0.05, 0.05, tip_y - 1.42, tip_y - 1.3, tip_z - 0.05, tip_z + 0.05)
    return G.scene_with([("legs", legs.mesh(mat(lattice(rgb=MUSTARD), 0.6, 0.55, "legs"))),
                         ("deck", deck.mesh(mat(noisy(TEAL, amount=8), 0.6, 0.5, "deck"))),
                         ("cab", cab.mesh(mat(noisy(MUSTARD, amount=10), 0.3, 0.55, "cab"))),
                         ("boom", boom.mesh(mat(lattice(rgb=MUSTARD), 0.6, 0.55, "boom"))),
                         ("cable", cable.mesh(mat(noisy(DARK, amount=4), 0.8, 0.4, "cable"))),
                         ("hook", hook.mesh(mat(noisy(CHROME, amount=8), 0.9, 0.3, "hook")))])


def build_roof_ac():
    body, top = G.Part(), G.Part()
    G.box_part(body, -0.16, 0.16, 0.0, 0.2, -0.16, 0.16)
    G.box_part(body, -0.05, 0.05, 0.2, 0.26, -0.16, -0.1)   # a pipe stub
    # grille on top as a thin plate
    top.quad((-0.14, 0.201, 0.14), (0.14, 0.201, 0.14), (0.14, 0.201, -0.14), (-0.14, 0.201, -0.14), (0, 1), (1, 1), (1, 0), (0, 0))
    return G.scene_with([("body", body.mesh(mat(noisy((150, 152, 156), amount=8), 0.6, 0.5, "body"))),
                         ("grille", top.mesh(mat(grille(), 0.5, 0.5, "grille")))])


def build_roof_vent():
    p = G.Part()
    G.cylinder_part(p, lambda t: 0.06, 0.0, 0.26, segments=12, rings=1, cap=False)
    G.cylinder_part(p, lambda t: 0.1 * (1 - t) + 0.02 * t, 0.26, 0.36, segments=12, rings=1, cap=True)
    return G.scene_with([("vent", p.mesh(mat(noisy((132, 136, 140), amount=8), 0.8, 0.4, "vent")))])


def build_water_tower():
    legs, tank, roof = G.Part(), G.Part(), G.Part()
    for x in (-0.2, 0.2):
        for z in (-0.2, 0.2):
            G.box_part(legs, x - 0.02, x + 0.02, 0.0, 0.6, z - 0.02, z + 0.02)
    G.box_part(legs, -0.22, 0.22, 0.3, 0.33, -0.22, 0.22)   # brace ring
    G.cylinder_part(tank, lambda t: 0.28, 0.6, 1.1, segments=16, rings=1, cap=False)
    G.cylinder_part(tank, lambda t: 0.28, 0.58, 0.6, segments=16, rings=1, cap=True)   # bottom lip
    G.cylinder_part(roof, lambda t: 0.3 * (1 - t) + 0.02 * t, 1.1, 1.32, segments=16, rings=1, cap=True)
    return G.scene_with([("legs", legs.mesh(mat(noisy(DARK, amount=6), 0.6, 0.5, "legs"))),
                         ("tank", tank.mesh(mat(wood(seed=11), 0.0, 0.85, "tank"))),
                         ("roof", roof.mesh(mat(noisy(RUST, amount=10), 0.4, 0.7, "roof")))])


def build_rail():
    rails, sleepers, girders = G.Part(), G.Part(), G.Part()
    for x in (-0.13, 0.13):
        G.box_part(rails, x - 0.015, x + 0.015, 0.03, 0.06, -0.5, 0.5)
    for i in range(6):
        z = -0.5 + (i + 0.5) / 6
        G.box_part(sleepers, -0.22, 0.22, 0.0, 0.03, z - 0.035, z + 0.035)
    for x in (-0.44, 0.44):
        G.box_part(girders, x - 0.03, x + 0.03, 0.0, 0.22, -0.5, 0.5)
        G.box_part(girders, x - 0.04, x + 0.04, 0.22, 0.25, -0.5, 0.5)   # top flange
    return G.scene_with([("rails", rails.mesh(mat(noisy(CHROME, amount=10), 0.9, 0.35, "rails"))),
                         ("sleepers", sleepers.mesh(mat(wood(seed=5), 0.0, 0.9, "sleepers"))),
                         ("girders", girders.mesh(mat(noisy(TEAL, amount=8), 0.6, 0.5, "girders")))])


SPEC = {
    "sign_stop": build_sign_stop,
    "sign_oneway": build_sign_oneway,
    "bus_shelter": build_bus_shelter,
    "bus_shelter__glass": build_bus_shelter_glass,
    "parking_meter": build_parking_meter,
    "mailbox": build_mailbox,
    "container_1": lambda: build_container((150, 48, 36), 1),
    "container_2": lambda: build_container((40, 84, 140), 2),
    "container_3": lambda: build_container((60, 110, 70), 3),
    "container_4": lambda: build_container((150, 150, 140), 4),
    "crane": build_crane,
    "roof_ac": build_roof_ac,
    "roof_vent": build_roof_vent,
    "water_tower": build_water_tower,
    "rail": build_rail,
}


def main():
    out_dir = sys.argv[1]
    sheet_path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
    os.makedirs(out_dir, exist_ok=True)
    manifest_models, status, cells = [], {}, []
    for name, build in SPEC.items():
        scene = build()
        tris = sum(len(g.faces) for g in scene.geometry.values())
        b = scene.bounds
        scene.export(os.path.join(out_dir, name + ".glb"))
        manifest_models.append(dict(name=name, glb=f"env2/{name}.glb", scale=1.0, texture_max=512, forward="+z",
                                    _licence="procedural (tools/gen_env2.py), no third-party content"))
        status[name] = dict(triangles=int(tris), size_blocks=[round(float(b[1][i] - b[0][i]), 3) for i in range(3)])
        if sheet_path:
            cell = Image.new("RGBA", (480, 176), (30, 30, 30, 255))
            cell.paste(G.render(scene, "top"), (0, 0)); cell.paste(G.render(scene, "3q"), (160, 0))
            ImageDraw.Draw(cell).text((4, 162), f"{name}  {tris} tris  {status[name]['size_blocks']} blocks", fill=(255, 255, 0, 255))
            cells.append(cell)
        print(name, tris, "tris", status[name]["size_blocks"])
    json.dump(status, open(os.path.join(out_dir, "status.json"), "w"), indent=1)
    json.dump(dict(models=manifest_models), open(os.path.join(out_dir, "manifest_fragment.json"), "w"), indent=1)
    if sheet_path and cells:
        cols = 3; rows = (len(cells) + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * 480, rows * 176), (30, 30, 30, 255))
        for i, c in enumerate(cells):
            sheet.paste(c, ((i % cols) * 480, (i // cols) * 176))
        sheet.save(sheet_path)


if __name__ == "__main__":
    main()
