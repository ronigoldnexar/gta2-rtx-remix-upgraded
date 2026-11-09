#!/usr/bin/env python3
"""GTA2 map objects as 3D models: the OBJI object table's sprites (benches,
tyres, cones, crates, drums, barriers...) get a model whose top-down look is the
sprite itself and whose body is either a Poly Haven (CC0) model, normalised and
scaled to blocks, or a small procedural body with the upscaled sprite projected
on top. Writes GLBs, an import-manifest fragment, the renderer's
"objects" map and a contact sheet (sprite | top | 3/4).

    gen_objects.py <assets-src dir> <out glb dir> [--sheet out.png]

Units: one GTA2 block = 64 px = 2 m. Models are exported in blocks with the
origin at the footprint centre on the ground, the long axis along +z.
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import trimesh
from trimesh.visual.material import PBRMaterial
from trimesh.visual import TextureVisuals

PX = 1.0 / 64.0          # blocks per sprite pixel
M = 0.5                  # blocks per metre

# OBJI model -> frames (Downtown, Residential and Industrial share the table).
OBJI = [(22, 8, 0, 7), (7, 4, 8, 11), (1, 6, 12, 17), (5, 3, 18, 20), (2, 1, 21, 21), (4, 2, 22, 23), (11, 4, 24, 27),
        (3, 4, 28, 31), (12, 6, 32, 37), (13, 5, 38, 42), (14, 5, 43, 47), (18, 7, 48, 54), (19, 1, 55, 55), (20, 1, 56, 56),
        (10, 1, 57, 57), (15, 3, 58, 60), (8, 5, 61, 65), (9, 1, 66, 66), (16, 4, 67, 70), (23, 5, 71, 75), (21, 8, 76, 83),
        (6, 4, 84, 87), (25, 1, 88, 88), (17, 1, 89, 89)]

# What each frame becomes. Frames left out stay the game's flat sprite (litter,
# newspaper, oil, broken wood: flat things that are right on the ground).
# name -> (frames, builder, source, brief)
SPEC = {
    "obj_bench":       (list(range(0, 8)),   "polyhaven", "painted_wooden_bench", "park bench, green painted slats, cast iron ends"),
    "obj_tyre":        (list(range(8, 18)),  "polyhaven", "old_tyre", "car tyre lying flat, worn black rubber"),
    "obj_girder":      ([21],                "girder_plate", None, "riveted steel girder plate, grey, lying flat"),
    "obj_planter":     (list(range(24, 28)), "planter",   "planter_pot_clay", "clay planter with a green bush and orange flowers"),
    "obj_cone":        ([28],                "cone",      None, "traffic cone, orange with a white band, standing"),
    "obj_cone_lying":  ([29, 30, 31],        "cone_lying", None, "traffic cone knocked over"),
    "obj_crate":       ([32, 33],            "proc_box",  None, "wooden shipping crate with an X brace, pine planks"),
    "obj_football":    (list(range(38, 43)), "ball",      None, "black and white football"),
    "obj_box":         (list(range(43, 48)), "proc_box",  None, "small cardboard box"),
    "obj_extinguisher": (list(range(48, 55)), "extinguisher", None, "red fire extinguisher lying on its side"),
    "obj_drum":        ([67],                "polyhaven", "barrel_03", "steel oil drum, upright"),
    "obj_drum_lying":  ([68, 69, 70],        "polyhaven_lying", "barrel_03", "steel oil drum on its side"),
    "obj_sandbag":     (list(range(71, 76)), "polyhaven", "cement_bag", "sandbag / cement sack"),
    "obj_barrier":     (list(range(76, 84)), "barrier",   None, "road works sawhorse barrier, red and white stripes"),
    "obj_crate_yellow": ([88],               "proc_box",  None, "yellow hazard crate with a cross"),
}
# Procedural box heights and side colours per model (blocks). obj_girder's box
# is the PROPS-2 slab, kept only for the before/after sheet (--props-sheet).
BOX = {
    "obj_girder": dict(h=0.10, side="steel", rough=0.45, metal=0.85),
    "obj_crate": dict(h=0.21, side="planks", rough=0.8, metal=0.0),
    "obj_box": dict(h=0.14, side="cardboard", rough=0.9, metal=0.0),
    "obj_crate_yellow": dict(h=0.22, side="straps", rough=0.5, metal=0.1),
}
MAP_OBJ_BASE = 5   # the sprite object's base value for map objects (cars 2, peds 3, code objects 4/8)


def load_sprite(src, frame):
    nat = Image.open(os.path.join(src, "objects", "sprites_all", f"map_obj_{frame:03d}.png")).convert("RGBA")
    x4p = os.path.join(src, "objects", "sprites_x4", f"map_obj_{frame:03d}.tga")
    x4 = Image.open(x4p).convert("RGBA") if os.path.exists(x4p) else nat.resize((nat.width * 4, nat.height * 4), Image.NEAREST)
    return nat, x4


def body_colour(nat):
    a = np.array(nat).reshape(-1, 4)
    a = a[a[:, 3] > 128][:, :3]
    return tuple(int(v) for v in np.median(a, axis=0)) if len(a) else (128, 128, 128)


def flat(rgb, size=8):
    return Image.new("RGBA", (size, size), tuple(rgb) + (255,))


def top_texture(x4, fill):
    """The sprite on top: transparent surround filled with the body colour."""
    bg = Image.new("RGBA", x4.size, tuple(fill) + (255,))
    bg.alpha_composite(x4)
    return bg


def nails(dr, pts, rgb):
    for (x, y) in pts:
        dr.ellipse([x - 2, y - 2, x + 2, y + 2], fill=tuple(max(0, c - 70) for c in rgb) + (255,))
        dr.point((x - 1, y - 1), fill=(230, 230, 225, 255))


def steel_texture(rgb):
    """Riveted steel plate: panel seams, rivet rows, light brushed streaks."""
    w, h = 256, 128
    base = tuple(int(c) for c in rgb)
    im = Image.new("RGBA", (w, h), base + (255,))
    dr = ImageDraw.Draw(im)
    rng = np.random.default_rng(11)
    for x in range(0, w, 3):
        shade = int(rng.integers(-9, 9))
        dr.line([x, 0, x, h], fill=tuple(max(0, min(255, c + shade)) for c in base) + (255,))
    for x in range(0, w, 64):
        dr.line([x, 0, x, h], fill=tuple(max(0, c - 45) for c in base) + (255,), width=2)
    dr.line([0, 12, w, 12], fill=tuple(max(0, c - 30) for c in base) + (255,), width=2)
    dr.line([0, h - 12, w, h - 12], fill=tuple(max(0, c - 30) for c in base) + (255,), width=2)
    for x in range(10, w, 20):
        for y in (6, h - 6):
            dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=tuple(min(255, c + 25) for c in base) + (255,))
            dr.arc([x - 3, y - 3, x + 3, y + 3], 20, 200, fill=tuple(max(0, c - 60) for c in base) + (255,))
    return im


def cardboard_texture(rgb):
    w, h = 256, 128
    base = tuple(int(c) for c in rgb)
    im = Image.new("RGBA", (w, h), base + (255,))
    dr = ImageDraw.Draw(im)
    rng = np.random.default_rng(13)
    for y in range(0, h, 2):
        shade = int(rng.integers(-6, 6))
        dr.line([0, y, w, y], fill=tuple(max(0, min(255, c + shade)) for c in base) + (255,))
    # a tape strip and a printed label
    dr.rectangle([0, h // 2 - 6, w, h // 2 + 6], fill=tuple(max(0, min(255, c + 22)) for c in base) + (255,))
    dr.rectangle([w // 2 - 30, 20, w // 2 + 30, 56], fill=(236, 232, 220, 255))
    dr.rectangle([w // 2 - 24, 28, w // 2 + 24, 32], fill=(40, 40, 40, 255))
    dr.rectangle([w // 2 - 24, 38, w // 2 + 8, 41], fill=(40, 40, 40, 255))
    dr.rectangle([w // 2 - 24, 46, w // 2 + 18, 49], fill=(40, 40, 40, 255))
    return im


def straps_texture(rgb):
    """Yellow hazard crate: painted steel with black diagonal straps."""
    w, h = 256, 256
    base = tuple(int(c) for c in rgb)
    im = Image.new("RGBA", (w, h), base + (255,))
    dr = ImageDraw.Draw(im)
    rng = np.random.default_rng(17)
    for y in range(0, h, 2):
        shade = int(rng.integers(-7, 7))
        dr.line([0, y, w, y], fill=tuple(max(0, min(255, c + shade)) for c in base) + (255,))
    dr.line([0, 0, w, h], fill=(28, 28, 30, 255), width=22)
    dr.line([0, h, w, 0], fill=(28, 28, 30, 255), width=22)
    dr.rectangle([0, 0, w - 1, h - 1], outline=(28, 28, 30, 255), width=14)
    for (x, y) in [(20, 20), (w - 20, 20), (20, h - 20), (w - 20, h - 20), (w // 2, h // 2)]:
        dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(120, 120, 124, 255))
    return im


def planks_texture(rgb):
    w, h = 256, 128
    im = Image.new("RGBA", (w, h), tuple(rgb) + (255,))
    dr = ImageDraw.Draw(im)
    rng = np.random.default_rng(3)
    for y in range(0, h, 32):
        shade = int(rng.integers(-18, 18))
        dr.rectangle([0, y, w, y + 31], fill=tuple(max(0, min(255, c + shade)) for c in rgb) + (255,))
        dr.line([0, y, w, y], fill=tuple(max(0, c - 50) for c in rgb) + (255,), width=2)
        for x in range(0, w, 7):
            dr.line([x, y + 2, x, y + 30], fill=tuple(max(0, min(255, c + int(rng.integers(-10, 10)))) for c in rgb) + (255,))
    # a diagonal brace and the nails that hold it
    dr.line([0, h - 1, w, 0], fill=tuple(max(0, c - 35) for c in rgb) + (255,), width=10)
    nails(dr, [(x, y + 16) for y in range(0, h, 32) for x in (8, w - 8)] + [(int(w * t), int(h * (1 - t))) for t in (0.15, 0.5, 0.85)], rgb)
    return im


class Part:
    def __init__(self):
        self.v, self.n, self.uv, self.f = [], [], [], []

    def quad(self, p0, p1, p2, p3, uv0=(0, 0), uv1=(1, 0), uv2=(1, 1), uv3=(0, 1)):
        p0, p1, p2, p3 = (np.array(p, np.float32) for p in (p0, p1, p2, p3))
        n = np.cross(p1 - p0, p3 - p0)
        n = n / max(np.linalg.norm(n), 1e-9)
        b = len(self.v)
        self.v += [p0, p1, p2, p3]
        self.n += [n] * 4
        self.uv += [uv0, uv1, uv2, uv3]
        self.f += [[b, b + 1, b + 2], [b, b + 2, b + 3]]

    def mesh(self, material):
        v = np.array(self.v, np.float32)
        f = np.array(self.f, np.int64)
        n = np.array(self.n, np.float32)
        uv = np.array(self.uv, np.float32)
        m = trimesh.Trimesh(vertices=v, faces=f, vertex_normals=n, process=False)
        m.visual = TextureVisuals(uv=uv, material=material)
        return m


def box_part(part, x0, x1, y0, y1, z0, z1, top_uv=True):
    """An axis-aligned box. Top face UVs cover the whole texture (the sprite);
    sides are UV'd by extent."""
    # top (y1), normal up: order so the normal is +y
    part.quad((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0), (0, 1), (1, 1), (1, 0), (0, 0))
    # bottom
    part.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
    L, W, H = z1 - z0, x1 - x0, y1 - y0
    # sides: +x, -x, +z, -z
    part.quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1), (0, 1), (0, 0), (L / H, 0), (L / H, 1))
    part.quad((x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (x0, y0, z0), (0, 1), (0, 0), (L / H, 0), (L / H, 1))
    part.quad((x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1), (0, 1), (0, 0), (W / H, 0), (W / H, 1))
    part.quad((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (0, 1), (0, 0), (W / H, 0), (W / H, 1))


def cylinder_part(part, radius_fn, y0, y1, segments=24, rings=8, cap=True):
    """A surface of revolution about +y: radius_fn(t) for t in 0..1 (bottom..top)."""
    ring = []
    for r in range(rings + 1):
        t = r / rings
        y = y0 + (y1 - y0) * t
        rad = radius_fn(t)
        ring.append([(rad * math.cos(2 * math.pi * s / segments), y, rad * math.sin(2 * math.pi * s / segments)) for s in range(segments + 1)])
    for r in range(rings):
        for s in range(segments):
            a, b, c, d = ring[r][s], ring[r][s + 1], ring[r + 1][s + 1], ring[r + 1][s]
            u0, u1 = s / segments, (s + 1) / segments
            v0, v1 = 1 - r / rings, 1 - (r + 1) / rings
            part.quad(a, d, c, b, (u0, v0), (u0, v1), (u1, v1), (u1, v0))
    if cap:
        top = radius_fn(1.0)
        if top > 1e-4:
            cx = (0.0, y1, 0.0)
            for s in range(segments):
                p1, p2 = ring[-1][s], ring[-1][s + 1]
                b = len(part.v)
                part.v += [np.array(cx, np.float32), np.array(p2, np.float32), np.array(p1, np.float32)]
                part.n += [np.array((0, 1, 0), np.float32)] * 3
                part.uv += [(0.5, 0.5), (0.5 + 0.5 * math.cos(2 * math.pi * (s + 1) / segments), 0.5 + 0.5 * math.sin(2 * math.pi * (s + 1) / segments)),
                            (0.5 + 0.5 * math.cos(2 * math.pi * s / segments), 0.5 + 0.5 * math.sin(2 * math.pi * s / segments))]
                part.f += [[b, b + 1, b + 2]]


def scene_with(meshes):
    scene = trimesh.Scene()
    for i, (name, m) in enumerate(meshes):
        scene.add_geometry(m, node_name=f"{name}_{i}", geom_name=f"{name}_{i}")
    return scene


# ----------------------------------------------------------------------------
# Procedural builders
# ----------------------------------------------------------------------------
def build_box(name, nat, x4):
    cfg = BOX[name]
    W, L = nat.width * PX, nat.height * PX
    H = cfg["h"]
    fill = (222, 186, 40) if cfg["side"] == "straps" else body_colour(nat)   # the hazard crate is yellow, whatever its grey lid
    top = Part()
    box_part(top, -W / 2, W / 2, 0.0, H, -L / 2, L / 2)
    side_img = {"planks": planks_texture, "steel": steel_texture, "cardboard": cardboard_texture, "straps": straps_texture}[cfg["side"]](fill)
    # one mesh for the top (sprite), one for the rest
    top_only = Part()
    top_only.quad((-W / 2, H, L / 2), (W / 2, H, L / 2), (W / 2, H, -L / 2), (-W / 2, H, -L / 2), (0, 1), (1, 1), (1, 0), (0, 0))
    sides = Part()
    sides.v, sides.n, sides.uv, sides.f = top.v[4:], top.n[4:], top.uv[4:], [[i - 4 for i in tri] for tri in top.f[2:]]
    mt = PBRMaterial(name="top", baseColorTexture=top_texture(x4, fill), metallicFactor=cfg["metal"], roughnessFactor=cfg["rough"])
    ms = PBRMaterial(name="side", baseColorTexture=side_img, metallicFactor=cfg["metal"], roughnessFactor=cfg["rough"])
    parts = [("top", top_only.mesh(mt)), ("side", sides.mesh(ms))]
    if cfg["side"] == "planks":
        # a shipping crate's frame: battens along the twelve edges, standing proud of the boards
        b = Part()
        e, o = 0.018, 0.006
        x0, x1, z0, z1 = -W / 2 - o, W / 2 + o, -L / 2 - o, L / 2 + o
        for x in (x0, x1 - e):
            for z in (z0, z1 - e):
                box_part(b, x, x + e, 0.0, H + o, z, z + e)
        for y in (0.0, H + o - e):
            for x in (x0, x1 - e):
                box_part(b, x, x + e, y, y + e, z0, z1)
            for z in (z0, z1 - e):
                box_part(b, x0, x1, y, y + e, z, z + e)
        dark = tuple(max(0, int(c * 0.72)) for c in fill)
        parts.append(("frame", b.mesh(PBRMaterial(name="frame", baseColorTexture=planks_texture(dark), metallicFactor=0.0, roughnessFactor=0.85))))
    return scene_with(parts)


def cone_texture():
    im = Image.new("RGBA", (64, 128), (235, 92, 20, 255))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 40, 64, 62], fill=(240, 240, 240, 255))
    dr.rectangle([0, 72, 64, 88], fill=(240, 240, 240, 255))
    return im


def build_cone(lying=False):
    R, H = 0.10, 0.26
    body = Part()
    cylinder_part(body, lambda t: R * (1.0 - 0.85 * t) if t > 0.08 else R * 1.4 * (1 - t * 2), 0.0, H, 20, 10)
    base = Part()
    cylinder_part(base, lambda t: 0.105, 0.0, 0.016, 16, 1)
    mb = PBRMaterial(name="cone", baseColorTexture=cone_texture(), metallicFactor=0.0, roughnessFactor=0.6)
    mbase = PBRMaterial(name="base", baseColorTexture=flat((30, 30, 32)), metallicFactor=0.0, roughnessFactor=0.9)
    scene = scene_with([("cone", body.mesh(mb)), ("base", base.mesh(mbase))])
    if lying:
        T = trimesh.transformations.rotation_matrix(math.radians(90), [1, 0, 0])   # +y -> +z: lying along z
        scene.apply_transform(T)
        b = scene.bounds
        scene.apply_transform(trimesh.transformations.translation_matrix([0, -b[0][1], -(b[0][2] + b[1][2]) / 2]))
    return scene


def ball_texture():
    im = Image.new("RGBA", (256, 128), (245, 245, 245, 255))
    dr = ImageDraw.Draw(im)
    rng = np.random.default_rng(5)
    for row in range(3):
        for col in range(6):
            cx = col * 42 + (21 if row % 2 else 0) + int(rng.integers(-4, 4)); cy = 20 + row * 44
            pts = [(cx + 16 * math.cos(math.radians(72 * k - 90)), cy + 16 * math.sin(math.radians(72 * k - 90))) for k in range(5)]
            dr.polygon(pts, fill=(20, 20, 22, 255))
    return im


def build_ball():
    ball = trimesh.creation.uv_sphere(radius=0.12, count=[24, 16])
    uv = np.zeros((len(ball.vertices), 2), np.float32)
    v = ball.vertices
    uv[:, 0] = (np.arctan2(v[:, 2], v[:, 0]) / (2 * math.pi)) % 1.0
    uv[:, 1] = 0.5 + np.arcsin(np.clip(v[:, 1] / 0.12, -1, 1)) / math.pi
    ball.visual = TextureVisuals(uv=uv, material=PBRMaterial(name="ball", baseColorTexture=ball_texture(), roughnessFactor=0.7, metallicFactor=0.0))
    ball.apply_translation([0, 0.12, 0])
    return scene_with([("ball", ball)])


def build_extinguisher():
    R, L = 0.055, 0.24
    body = Part()
    cylinder_part(body, lambda t: R if 0.05 < t < 0.9 else (R * 0.8 if t <= 0.05 else R * 0.55), 0.0, L, 18, 8)
    red = PBRMaterial(name="red", baseColorTexture=flat((200, 24, 22)), metallicFactor=0.4, roughnessFactor=0.35)
    head = Part()
    cylinder_part(head, lambda t: 0.02, L, L + 0.03, 10, 1)
    blk = PBRMaterial(name="black", baseColorTexture=flat((30, 30, 30)), metallicFactor=0.3, roughnessFactor=0.6)
    scene = scene_with([("body", body.mesh(red)), ("head", head.mesh(blk))])
    scene.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90), [1, 0, 0]))
    b = scene.bounds
    scene.apply_transform(trimesh.transformations.translation_matrix([0, -b[0][1], -(b[0][2] + b[1][2]) / 2]))
    return scene


def stripes_texture():
    im = Image.new("RGBA", (256, 32), (240, 240, 240, 255))
    dr = ImageDraw.Draw(im)
    for x in range(0, 256, 64):
        dr.polygon([(x, 0), (x + 32, 0), (x + 48, 32), (x + 16, 32)], fill=(210, 30, 30, 255))
    return im


def build_barrier():
    L, H = 0.50, 0.30
    plank = Part()
    # top plank along z, striped
    plank.quad((-0.025, H, L / 2), (0.025, H, L / 2), (0.025, H, -L / 2), (-0.025, H, -L / 2), (0, 1), (0, 0), (1, 0), (1, 1))
    plank.quad((-0.025, H - 0.07, -L / 2), (-0.025, H, -L / 2), (-0.025, H, L / 2), (-0.025, H - 0.07, L / 2), (0, 1), (0, 0), (1, 0), (1, 1))
    plank.quad((0.025, H - 0.07, L / 2), (0.025, H, L / 2), (0.025, H, -L / 2), (0.025, H - 0.07, -L / 2), (0, 1), (0, 0), (1, 0), (1, 1))
    plank.quad((-0.025, H - 0.07, L / 2), (0.025, H - 0.07, L / 2), (0.025, H - 0.07, -L / 2), (-0.025, H - 0.07, -L / 2))
    legs = Part()
    for zc in (-L / 2 + 0.03, L / 2 - 0.03):
        for sx in (-1, 1):
            # a leg leaning out in x
            x_top, x_bot = sx * 0.02, sx * 0.11
            legs.quad((x_bot - 0.012, 0, zc - 0.012), (x_top - 0.012, H - 0.02, zc - 0.012), (x_top + 0.012, H - 0.02, zc - 0.012), (x_bot + 0.012, 0, zc - 0.012))
            legs.quad((x_bot + 0.012, 0, zc + 0.012), (x_top + 0.012, H - 0.02, zc + 0.012), (x_top - 0.012, H - 0.02, zc + 0.012), (x_bot - 0.012, 0, zc + 0.012))
            legs.quad((x_bot + 0.012, 0, zc - 0.012), (x_top + 0.012, H - 0.02, zc - 0.012), (x_top + 0.012, H - 0.02, zc + 0.012), (x_bot + 0.012, 0, zc + 0.012))
            legs.quad((x_bot - 0.012, 0, zc + 0.012), (x_top - 0.012, H - 0.02, zc + 0.012), (x_top - 0.012, H - 0.02, zc - 0.012), (x_bot - 0.012, 0, zc - 0.012))
        # a cross bar between the legs
        legs.quad((-0.07, 0.10, zc - 0.01), (-0.07, 0.125, zc - 0.01), (0.07, 0.125, zc - 0.01), (0.07, 0.10, zc - 0.01))
        legs.quad((0.07, 0.10, zc + 0.01), (0.07, 0.125, zc + 0.01), (-0.07, 0.125, zc + 0.01), (-0.07, 0.10, zc + 0.01))
    ms = PBRMaterial(name="stripes", baseColorTexture=stripes_texture(), metallicFactor=0.0, roughnessFactor=0.6)
    ml = PBRMaterial(name="wood", baseColorTexture=flat((225, 225, 220)), metallicFactor=0.0, roughnessFactor=0.8)
    return scene_with([("plank", plank.mesh(ms)), ("legs", legs.mesh(ml))])


def build_planter(src):
    scene = load_polyhaven(src, "planter_pot_clay")
    # the pot: 0.27 m wide -> keep metres*M; a bush of leaves on top
    b = scene.bounds
    top = b[1][1]
    leaves = trimesh.creation.icosphere(subdivisions=2, radius=0.10)
    leaves.apply_translation([0, top + 0.07, 0])
    leaves.visual = TextureVisuals(uv=np.zeros((len(leaves.vertices), 2)), material=PBRMaterial(name="leaves", baseColorTexture=flat((58, 122, 40)), roughnessFactor=0.9, metallicFactor=0.0))
    scene.add_geometry(leaves, node_name="leaves", geom_name="leaves")
    rng = np.random.default_rng(7)
    for i in range(7):
        a = rng.uniform(0, 2 * math.pi)
        fl = trimesh.creation.icosphere(subdivisions=1, radius=0.018)
        fl.apply_translation([0.09 * math.cos(a), top + 0.07 + rng.uniform(0.0, 0.07), 0.09 * math.sin(a)])
        fl.visual = TextureVisuals(uv=np.zeros((len(fl.vertices), 2)), material=PBRMaterial(name="flower", baseColorTexture=flat((236, 110, 30)), roughnessFactor=0.8, metallicFactor=0.0))
        scene.add_geometry(fl, node_name=f"flower_{i}", geom_name=f"flower_{i}")
    return scene


# ----------------------------------------------------------------------------
# Poly Haven models
# ----------------------------------------------------------------------------
def load_polyhaven(src, asset, rotate=None, keep_largest=False):
    folder = os.path.join(src, "polyhaven", asset)
    gltf = [f for f in os.listdir(folder) if f.endswith(".gltf")][0]
    scene = trimesh.load(os.path.join(folder, gltf), force="scene")
    out = trimesh.Scene()
    geoms = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(T)
        geoms.append((gname, g))
    if keep_largest:
        geoms = [max(geoms, key=lambda ng: len(ng[1].faces))]
    for gname, g in geoms:
        out.add_geometry(g, node_name=gname, geom_name=gname)
    out.apply_transform(trimesh.transformations.scale_matrix(M))
    if rotate is not None:
        out.apply_transform(rotate)
    # the long footprint axis along z, origin at the footprint centre on the ground
    b = out.bounds
    if (b[1][0] - b[0][0]) > (b[1][2] - b[0][2]) * 1.15:
        out.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90), [0, 1, 0]))
        b = out.bounds
    out.apply_transform(trimesh.transformations.translation_matrix([-(b[0][0] + b[1][0]) / 2, -b[0][1], -(b[0][2] + b[1][2]) / 2]))
    return out


ROT_X90 = trimesh.transformations.rotation_matrix(math.radians(90), [1, 0, 0])

# Objects whose model must take the sprite's paint (the sprite is the law):
# name -> how strongly (1 = the texture's mean becomes the sprite's colour).
MATCH = {"obj_bench": 1.0, "obj_sandbag": 1.0, "obj_drum": 0.6, "obj_drum_lying": 0.6, "obj_tyre": 0.5}


def match_colour(scene, target, strength):
    """Multiplies every textured material so its mean colour moves toward the
    sprite's; the texture keeps its own shading and detail."""
    target = np.array(target, np.float32)
    done = set()
    for g in scene.geometry.values():
        mat = getattr(g.visual, "material", None)
        img = getattr(mat, "baseColorTexture", None) if mat is not None else None
        if img is None or id(mat) in done:
            continue
        done.add(id(mat))
        a = np.array(img.convert("RGBA")).astype(np.float32)
        mask = a[:, :, 3] > 0
        mean = a[:, :, :3][mask].mean(axis=0) if mask.any() else np.array([128, 128, 128], np.float32)
        ratio = target / np.maximum(mean, 1.0)
        ratio = 1.0 + (ratio - 1.0) * strength
        a[:, :, :3] = np.clip(a[:, :, :3] * ratio, 0, 255)
        mat.baseColorTexture = Image.fromarray(a.astype(np.uint8), "RGBA")


def colour_report(scene, nat):
    """Mean model colour (weighted by face area, from the textures) vs the sprite's."""
    tris, cols = face_colours(scene)
    if len(tris) == 0:
        return None
    area = 0.5 * np.linalg.norm(np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0]), axis=1)
    model = (cols * area[:, None]).sum(axis=0) / max(area.sum(), 1e-9)
    sprite = np.array(body_colour(nat), np.float32)
    return [int(v) for v in model], [int(v) for v in sprite], float(np.linalg.norm(model - sprite))


def build(name, src):
    frames, kind, asset, _ = SPEC[name]
    nat, x4 = load_sprite(src, frames[0])
    scene = build_kind(name, kind, asset, src, nat, x4)
    if name in MATCH:
        match_colour(scene, body_colour(nat), MATCH[name])
    return scene


def build_kind(name, kind, asset, src, nat, x4):
    if kind == "proc_box":
        return build_box(name, nat, x4)
    if kind == "girder_plate":
        return build_girder_plate(nat, x4)
    if kind == "cone":
        return build_cone(False)
    if kind == "cone_lying":
        return build_cone(True)
    if kind == "extinguisher":
        return build_extinguisher()
    if kind == "ball":
        return build_ball()
    if kind == "barrier":
        return build_barrier()
    if kind == "planter":
        return build_planter(src)
    if kind == "polyhaven":
        if asset == "old_tyre":
            return load_polyhaven(src, asset, rotate=ROT_X90)      # stood-up tyre -> lying flat
        if asset == "football":
            return load_polyhaven(src, asset, keep_largest=True)
        return load_polyhaven(src, asset)
    if kind == "polyhaven_lying":
        return load_polyhaven(src, asset, rotate=ROT_X90)
    raise ValueError(kind)


def plate_texture(rgb, w=512, h=192, seed=23):
    """The girder plate's top: mill-scale steel in the sprite's colour, a
    little rust at the edges, scuffs from the traffic, rolled-in streaks."""
    base = np.array(rgb, np.float32)
    rng = np.random.default_rng(seed)
    a = np.ones((h, w, 3), np.float32) * base
    streak = rng.normal(0, 2.5, (h, 1, 1)).repeat(w, 1)          # rolled along the plate's length
    blot = np.array(Image.fromarray(rng.normal(128, 40, (h // 16, w // 16)).clip(0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32)
    a += streak + rng.normal(0, 2.5, (h, w, 1)) + ((blot - 128) * 0.12)[:, :, None]   # mill-scale blotches
    yy, xx = np.mgrid[0:h, 0:w]
    edge = np.minimum(np.minimum(xx, w - 1 - xx), np.minimum(yy, h - 1 - yy)).astype(np.float32)
    rust = np.clip(1 - edge / 18.0, 0, 1)[:, :, None] * rng.uniform(0.2, 0.6, (h, w, 1))
    a = a * (1 - 0.35 * rust) + np.array([120, 70, 40], np.float32) * 0.35 * rust
    a *= (base / np.maximum(a.reshape(-1, 3).mean(0), 1.0))       # keep the sprite's mean colour
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    dr = ImageDraw.Draw(im)
    for _ in range(40):   # scuffs
        x, y = int(rng.integers(20, w - 20)), int(rng.integers(20, h - 20))
        L = int(rng.integers(8, 40)); t = rng.uniform(-0.3, 0.3)
        c = tuple(int(min(255, v + 28)) for v in base) + (255,)
        dr.line([x, y, x + L, y + int(L * t)], fill=c, width=1)
    return im.filter(ImageFilter.SMOOTH)


def rivet(part, x, y, z, r, h, uv_at, sides=6):
    """A rivet head: a low six-sided dome (a frustum with a flat top)."""
    ring0 = [(x + r * math.cos(2 * math.pi * k / sides), y, z + r * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    ring1 = [(x + 0.55 * r * math.cos(2 * math.pi * k / sides), y + h, z + 0.55 * r * math.sin(2 * math.pi * k / sides)) for k in range(sides)]
    for k in range(sides):
        j = (k + 1) % sides
        part.quad(ring0[k], ring1[k], ring1[j], ring0[j], uv_at, uv_at, uv_at, uv_at)
        if part.n[-1][1] < -0.01 or np.dot(part.n[-1], np.array(ring0[k]) - np.array((x, y, z))) < 0:
            for q in range(4):
                part.n[-1 - q] = -part.n[-1 - q]
            part.f[-1] = [part.f[-1][0], part.f[-1][2], part.f[-1][1]]; part.f[-2] = [part.f[-2][0], part.f[-2][2], part.f[-2][1]]
    b = len(part.v)
    part.v += [np.array(p, np.float32) for p in ring1]
    part.n += [np.array((0, 1, 0), np.float32)] * sides
    part.uv += [uv_at] * sides
    for k in range(1, sides - 1):
        part.f.append([b, b + k + 1, b + k])


def build_girder_plate(nat, x4):
    """Map object 5:21: a riveted steel plate with real thickness. A base plate
    with chamfered top edges, a splice strap across each end, rivet rows along
    both long edges and through the straps, in the sprite's steel grey."""
    W, L = nat.width * PX, nat.height * PX        # x: the sprite's long side
    a = np.array(nat).astype(np.float32)
    light = a[: max(1, int(nat.height * 0.7))].reshape(-1, 4)
    light = light[light[:, 3] > 128][:, :3]
    top_rgb = tuple(int(v) for v in np.median(light, axis=0)) if len(light) else body_colour(nat)
    T, C = 0.034, 0.007                           # plate thickness, chamfer (blocks)
    plate = Part()
    x0, x1, z0, z1 = -W / 2, W / 2, -L / 2, L / 2
    def top_uv(x, z):
        return ((x - x0) / W, 1 - (z - z0) / L)
    # sides (to the start of the chamfer)
    h0 = T - C
    plate.quad((x1, 0, z0), (x1, h0, z0), (x1, h0, z1), (x1, 0, z1), (0, 0.1), (0, 0), (1, 0), (1, 0.1))
    plate.quad((x0, 0, z1), (x0, h0, z1), (x0, h0, z0), (x0, 0, z0), (0, 0.1), (0, 0), (1, 0), (1, 0.1))
    plate.quad((x1, 0, z1), (x1, h0, z1), (x0, h0, z1), (x0, 0, z1), (0, 0.1), (0, 0), (1, 0), (1, 0.1))
    plate.quad((x0, 0, z0), (x0, h0, z0), (x1, h0, z0), (x1, 0, z0), (0, 0.1), (0, 0), (1, 0), (1, 0.1))
    # chamfer ring and top face
    xi0, xi1, zi0, zi1 = x0 + C, x1 - C, z0 + C, z1 - C
    o = [(x0, h0, z0), (x1, h0, z0), (x1, h0, z1), (x0, h0, z1)]
    i = [(xi0, T, zi0), (xi1, T, zi0), (xi1, T, zi1), (xi0, T, zi1)]
    for k in range(4):
        j = (k + 1) % 4
        plate.quad(o[k], i[k], i[j], o[j], top_uv(o[k][0], o[k][2]), top_uv(i[k][0], i[k][2]), top_uv(i[j][0], i[j][2]), top_uv(o[j][0], o[j][2]))
        if plate.n[-1][1] < 0:
            for q in range(4):
                plate.n[-1 - q] = -plate.n[-1 - q]
            plate.f[-1] = [plate.f[-1][0], plate.f[-1][2], plate.f[-1][1]]; plate.f[-2] = [plate.f[-2][0], plate.f[-2][2], plate.f[-2][1]]
    plate.quad(i[3], i[2], i[1], i[0], top_uv(*i[3][::2]), top_uv(*i[2][::2]), top_uv(*i[1][::2]), top_uv(*i[0][::2]))
    # splice straps across the ends, riveted; rivet rows along the long edges
    straps, rivets = Part(), Part()
    sw, sh = 0.05, 0.010
    for sx in (-1, 1):
        cx = sx * (W / 2 - 0.012 - sw / 2)
        box_part(straps, cx - sw / 2, cx + sw / 2, T, T + sh, z0 + 0.006, z1 - 0.006)
        for zz in np.linspace(z0 + 0.03, z1 - 0.03, 3):
            for xx in (cx - sw / 4, cx + sw / 4):
                rivet(rivets, xx, T + sh, zz, 0.0065, 0.006, (0.5, 0.5))
    span0, span1 = x0 + 0.012 + sw + 0.03, x1 - 0.012 - sw - 0.03
    for zz in (z0 + 0.016, z1 - 0.016):
        for xx in np.linspace(span0, span1, 7):
            rivet(rivets, xx, T, zz, 0.0065, 0.006, (0.5, 0.5))
    steel = PBRMaterial(name="plate", baseColorTexture=plate_texture(top_rgb), metallicFactor=0.85, roughnessFactor=0.45)
    strap_rgb = tuple(max(0, int(c * 0.86)) for c in top_rgb)
    mstrap = PBRMaterial(name="strap", baseColorTexture=steel_texture(strap_rgb), metallicFactor=0.85, roughnessFactor=0.45)
    rivet_rgb = tuple(min(255, int(c * 1.12) + 6) for c in top_rgb)
    mriv = PBRMaterial(name="rivet", baseColorTexture=flat(rivet_rgb), metallicFactor=0.85, roughnessFactor=0.4)
    # one texture for the plate and straps would save a draw; the map has a handful of these
    return scene_with([("plate", plate.mesh(steel)), ("straps", straps.mesh(mstrap)), ("rivets", rivets.mesh(mriv))])


# ----------------------------------------------------------------------------
# Slim street props (PROPS-3): the hydrant and the bin are drawn by the dozen
# (rule props, merged per texture: PERF-2), so their Poly Haven scans (43k and
# 6.4k drawn triangles, 86k and 14k in the files with the unused "_aged" and
# "_rust" variants) are rebuilt as low-poly surfaces of revolution about their
# own axes, with the scan's colour and relief baked into one atlas texture.
# ----------------------------------------------------------------------------
def scan_nodes(src, folder, exclude):
    """A Poly Haven glTF's meshes in model space (metres), by node name."""
    path = os.path.join(src, "polyhaven", folder)
    gltf = [f for f in os.listdir(path) if f.endswith(".gltf")][0]
    scene = trimesh.load(os.path.join(path, gltf), force="scene")
    out = {}
    for node in scene.graph.nodes_geometry:
        if exclude in node:
            continue
        T, gname = scene.graph[node]
        g = scene.geometry[gname].copy()
        g.apply_transform(T)
        out[node] = (g, np.array(T, np.float64))
    return out


def scan_samples(nodes, count, seed=1):
    """Area-weighted points on the scan: position, face normal, base colour, node index."""
    rng = np.random.default_rng(seed)
    total = sum(g.area for g, _ in nodes.values())
    P, N, C, K = [], [], [], []
    for k, (g, _) in enumerate(nodes.values()):
        n = max(1000, int(count * g.area / total))
        tri = g.triangles
        area = g.area_faces
        fi = rng.choice(len(tri), size=n, p=area / area.sum())
        a, b = rng.random(n), rng.random(n)
        flip = a + b > 1
        a[flip], b[flip] = 1 - a[flip], 1 - b[flip]
        w = np.stack([1 - a - b, a, b], 1)
        P.append((tri[fi] * w[:, :, None]).sum(1))
        N.append(g.face_normals[fi])
        img = np.array(g.visual.material.baseColorTexture.convert("RGB"))
        uv = (g.visual.uv[g.faces[fi]] * w[:, :, None]).sum(1)
        px = np.clip((uv[:, 0] % 1.0) * img.shape[1], 0, img.shape[1] - 1).astype(int)
        py = np.clip((1 - uv[:, 1] % 1.0) * img.shape[0], 0, img.shape[0] - 1).astype(int)
        C.append(img[py, px].astype(np.float32))
        K.append(np.full(n, k))
    return np.concatenate(P), np.concatenate(N), np.concatenate(C), np.concatenate(K)


def frame_of(axis, ref=None):
    a = np.asarray(axis, np.float64); a = a / np.linalg.norm(a)
    ref = np.array([1.0, 0, 0]) if ref is None else np.asarray(ref, np.float64)
    if abs(np.dot(ref, a)) > 0.9:
        ref = np.array([0, 0, 1.0])
    e1 = ref - a * np.dot(ref, a); e1 /= np.linalg.norm(e1)
    return a, e1, np.cross(a, e1)


def envelope(P, origin, axis, s0, s1, ds=0.004, q=98.0, mask=None):
    """The radius of the scan about an axis, per slice along it: the q-th
    percentile (98: the outer skin, 2 with inward-facing samples: an inner wall)."""
    a, _, _ = frame_of(axis)
    d = P - origin
    s = d @ a
    r = np.linalg.norm(d - s[:, None] * a, axis=1)
    keep = (s >= s0) & (s <= s1) if mask is None else mask & (s >= s0) & (s <= s1)
    s, r = s[keep], r[keep]
    edges = np.arange(s0, s1 + ds, ds)
    pts = []
    for lo in edges[:-1]:
        sel = (s >= lo) & (s < lo + ds)
        if sel.sum() >= 8:
            pts.append((lo + ds / 2, float(np.percentile(r[sel], q))))
    return pts


def simplify(pts, tol):
    """Douglas-Peucker on an (s, r) polyline."""
    pts = [tuple(p) for p in pts]
    if len(pts) < 3:
        return pts
    a, b = np.array(pts[0]), np.array(pts[-1])
    ab = b - a; L = np.linalg.norm(ab)
    best, bi = -1.0, 0
    for i in range(1, len(pts) - 1):
        p = np.array(pts[i])
        d = abs(ab[0] * (p - a)[1] - ab[1] * (p - a)[0]) / L if L > 1e-12 else np.linalg.norm(p - a)
        if d > best:
            best, bi = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:bi + 1], tol)[:-1] + simplify(pts[bi:], tol)


def fit_profile(pts, max_points):
    """The loosest Douglas-Peucker tolerance that keeps max_points or fewer."""
    tol = 0.0005
    while True:
        out = simplify(pts, tol)
        if len(out) <= max_points:
            return out
        tol *= 1.25


class Lathe:
    """A surface of revolution about an axis: profile [(s, r)] in metres along
    the axis from origin, segments around, and its rectangle of the atlas
    (u0, v0, u1, v1; u around, v along the profile by arc length). Outward
    side: to the left of the profile's direction in (s, r), so a profile
    climbing an outer wall faces out and one descending an inner wall faces in."""
    def __init__(self, origin, axis, profile, segments, rect, ref=None, nodes=None, crease=40.0):
        self.o = np.asarray(origin, np.float64)
        self.a, self.e1, self.e2 = frame_of(axis, ref)
        self.prof = [(float(s), float(max(r, 0.0))) for s, r in profile]
        self.n = segments
        self.rect = rect
        self.nodes = nodes            # scan node indices this chart may take colour from (None: any)
        self.crease = math.radians(crease)
        seg = np.diff(np.array(self.prof), axis=0)
        self.seg_len = np.linalg.norm(seg, axis=1)
        self.cum = np.concatenate([[0.0], np.cumsum(self.seg_len)])
        self.length = self.cum[-1]

    def point(self, s, r, th):
        return self.o + self.a * s + r * (math.cos(th) * self.e1 + math.sin(th) * self.e2)

    def seg_normal(self, i):
        (s0, r0), (s1, r1) = self.prof[i], self.prof[i + 1]
        ns, nr = -(r1 - r0), (s1 - s0)
        L = math.hypot(ns, nr)
        return (ns / L, nr / L) if L > 1e-12 else (0.0, 1.0)

    def uv(self, t, th):
        u0, v0, u1, v1 = self.rect
        return (u0 + (u1 - u0) * th / (2 * math.pi), v1 - (v1 - v0) * t)

    def build(self, part):
        """Each profile segment is a band of quads (a triangle fan where a ring
        has no radius); a vertex normal is the mean of its two segments' unless
        they meet at more than the crease angle."""
        nseg = len(self.prof) - 1
        normals = [self.seg_normal(i) for i in range(nseg)]

        def vert_normal(i, end):
            own = normals[i]
            j = i + (1 if end else -1)
            if j < 0 or j >= nseg:
                return own
            other = normals[j]
            if math.acos(max(-1.0, min(1.0, own[0] * other[0] + own[1] * other[1]))) > self.crease:
                return own
            m = (own[0] + other[0], own[1] + other[1]); L = math.hypot(*m)
            return (m[0] / L, m[1] / L) if L > 1e-9 else own

        for i in range(nseg):
            if self.seg_len[i] < 1e-6:
                continue
            (s0, r0), (s1, r1) = self.prof[i], self.prof[i + 1]
            n0, n1 = vert_normal(i, False), vert_normal(i, True)
            t0, t1 = self.cum[i] / self.length, self.cum[i + 1] / self.length
            for k in range(self.n):
                ths = (2 * math.pi * k / self.n, 2 * math.pi * (k + 1) / self.n)
                quad = []
                for (s, r, nn, t) in ((s0, r0, n0, t0), (s1, r1, n1, t1)):
                    for th in ths:
                        radial = math.cos(th) * self.e1 + math.sin(th) * self.e2
                        nrm = nn[0] * self.a + nn[1] * radial
                        quad.append((self.point(s, r, th), nrm, self.uv(t, th)))
                (a, na, ua), (b, nb, ub), (c, nc, uc), (d, nd, ud) = quad   # a,b ring 0; c,d ring 1
                tris = []
                if r0 > 1e-6 and r1 > 1e-6:
                    tris = [(a, c, d), (a, d, b)]
                elif r0 > 1e-6:
                    tris = [(a, c, b)]
                elif r1 > 1e-6:
                    tris = [(a, c, d)]
                lookup = {id(a): (na, ua), id(b): (nb, ub), id(c): (nc, uc), id(d): (nd, ud)}
                for tri in tris:
                    # winding: counter-clockwise seen from the outward side
                    p0, p1, p2 = tri
                    fn = np.cross(p1 - p0, p2 - p0)
                    if np.dot(fn, lookup[id(p0)][0]) < 0:
                        tri = (p0, p2, p1)
                    base = len(part.v)
                    for p in tri:
                        nrm, uvv = lookup[id(p)]
                        part.v.append(np.array(p, np.float32)); part.n.append(np.array(nrm, np.float32)); part.uv.append(uvv)
                    part.f.append([base, base + 1, base + 2])

    def project(self, P):
        """Each point's nearest place on the profile: (t along it 0..1, angle,
        signed distance (+ outside), the surface normal there)."""
        d = P - self.o
        s = d @ self.a
        x, y = d @ self.e1, d @ self.e2
        r = np.hypot(x, y)
        th = np.arctan2(y, x) % (2 * math.pi)
        best = np.full(len(P), np.inf); t = np.zeros(len(P)); sd = np.zeros(len(P))
        ns_out = np.zeros(len(P)); nr_out = np.zeros(len(P))
        for i in range(len(self.prof) - 1):
            if self.seg_len[i] < 1e-6:
                continue
            (s0, r0), (s1, r1) = self.prof[i], self.prof[i + 1]
            ds_, dr_ = s1 - s0, r1 - r0
            L2 = ds_ * ds_ + dr_ * dr_
            u = np.clip(((s - s0) * ds_ + (r - r0) * dr_) / L2, 0.0, 1.0)
            qs, qr = s0 + u * ds_, r0 + u * dr_
            dist = np.hypot(s - qs, r - qr)
            ns, nr = self.seg_normal(i)
            better = dist < best
            best[better] = dist[better]
            t[better] = (self.cum[i] + u[better] * self.seg_len[i]) / self.length
            sd[better] = ((s - qs) * ns + (r - qr) * nr)[better]
            ns_out[better], nr_out[better] = ns, nr
        radial = (np.cos(th)[:, None] * self.e1 + np.sin(th)[:, None] * self.e2)
        nrm = ns_out[:, None] * self.a + nr_out[:, None] * radial
        return t, th, sd, best, nrm

    def texel(self, t, th, size):
        u0, v0, u1, v1 = self.rect
        u = u0 + (u1 - u0) * th / (2 * math.pi)
        v = v1 - (v1 - v0) * t
        return (np.clip(u * size, 0, size - 1).astype(int), np.clip((1 - v) * size, 0, size - 1).astype(int))


def bar_part(part, p0, p1, w, uv_at):
    """A square-section bar (four sides, no ends) from p0 to p1, all UVs at uv_at."""
    p0, p1 = np.asarray(p0, np.float64), np.asarray(p1, np.float64)
    a, e1, e2 = frame_of(p1 - p0, (0, 1, 0))
    h = w / 2
    corners = [h * (e1 + e2), h * (e1 - e2), h * (-e1 - e2), h * (-e1 + e2)]
    for k in range(4):
        c0, c1 = corners[k], corners[(k + 1) % 4]
        part.quad(p0 + c0, p0 + c1, p1 + c1, p1 + c0, uv_at, uv_at, uv_at, uv_at)
        # Part.quad takes its normal from the winding: make it face away from the bar's axis
        n = part.n[-1]
        if np.dot(n, (c0 + c1)) < 0:
            for j in range(4):
                part.n[-1 - j] = -part.n[-1 - j]
            f = part.f
            f[-1] = [f[-1][0], f[-1][2], f[-1][1]]; f[-2] = [f[-2][0], f[-2][2], f[-2][1]]


def bake_atlas(charts, samples, size=512, max_dist=0.05, relief=0.45, flats=()):
    """Every scan sample goes to the chart whose surface is nearest it (and
    faces the same way); a texel keeps its outermost sample (what is seen from
    outside). The scan's relief against the low-poly surface is baked in as
    light from above: a groove or a bolt shades as it did on the scan."""
    P, N, C, K = samples
    best = np.full(len(P), np.inf); which = np.full(len(P), -1)
    keep = {}
    for ci, ch in enumerate(charts):
        t, th, sd, dist, nrm = ch.project(P)
        ok = (dist < max_dist) & ((N * nrm).sum(1) > 0.15)
        if ch.nodes is not None:
            ok &= np.isin(K, ch.nodes)
        better = ok & (dist < best)
        best[better] = dist[better]; which[better] = ci
        keep[ci] = (t, th, sd, nrm)
    img = np.zeros((size, size, 3), np.float32)
    have = np.zeros((size, size), bool)
    up = np.array([0.25, 1.0, 0.35]); up /= np.linalg.norm(up)
    for ci, ch in enumerate(charts):
        sel = which == ci
        if not sel.any():
            continue
        t, th, sd, nrm = (x[sel] for x in keep[ci])
        px, py = ch.texel(t, th, size)
        shade = 1.0 + relief * ((N[sel] @ up) - (nrm @ up)) - 0.25 * (1.0 - np.clip((N[sel] * nrm).sum(1), 0, 1))
        col = C[sel] * np.clip(shade, 0.55, 1.35)[:, None]
        key = py * size + px
        order = np.lexsort((-sd, key))            # per texel, the outermost sample first
        key, col = key[order], col[order]
        first = np.concatenate([[True], key[1:] != key[:-1]])
        # average the outermost few millimetres' worth: the first sample and its neighbours in the run
        img.reshape(-1, 3)[key[first]] = col[first]
        have.reshape(-1)[key[first]] = True
    for (x0, y0, x1, y1), rgb in flats:
        img[y0:y1, x0:x1] = rgb; have[y0:y1, x0:x1] = True
    # fill the texels no sample reached (and the gutters) from their neighbours
    for _ in range(64):
        if have.all():
            break
        acc = np.zeros_like(img); cnt = np.zeros((size, size), np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            sh = np.roll(np.roll(img * have[:, :, None], dy, 0), dx, 1)
            hv = np.roll(np.roll(have, dy, 0), dx, 1)
            acc += sh; cnt += hv
        grow = (~have) & (cnt > 0)
        img[grow] = acc[grow] / cnt[grow][:, None]
        have |= grow
    filled = have.mean()
    # light 3x3 smoothing of single-texel noise from the sampling
    blur = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB").filter(ImageFilter.SMOOTH)
    return blur.convert("RGBA"), filled


def lathe_mesh(charts, extra_parts, atlas, name):
    part = Part()
    for ch in charts:
        ch.build(part)
    for ep in extra_parts:
        b = len(part.v)
        part.v += ep.v; part.n += ep.n; part.uv += ep.uv
        part.f += [[i + b for i in f] for f in ep.f]
    mat = PBRMaterial(name=name, baseColorTexture=atlas, metallicFactor=0.3, roughnessFactor=0.6)
    return part.mesh(mat)


def to_blocks(scene_mesh, centre_xz):
    """Metres -> blocks, the footprint centre (of the main body) at the origin."""
    T = trimesh.transformations.scale_matrix(M) @ trimesh.transformations.translation_matrix([-centre_xz[0], 0, -centre_xz[1]])
    scene_mesh.apply_transform(T)
    return scene_mesh


def build_hydrant(src):
    nodes = scan_nodes(src, "fire_hydrant", "_aged")
    names = list(nodes)
    idx = {n: i for i, n in enumerate(names)}
    samples = scan_samples(nodes, 1_200_000, seed=3)
    P = samples[0]
    body = nodes["fire_hydrant"][0]
    v = body.vertices
    base = v[v[:, 1] < 0.03]
    c = (base[:, [0, 2]].min(0) + base[:, [0, 2]].max(0)) / 2
    O = np.array([c[0], 0.0, c[1]])
    Y = np.array([0.0, 1.0, 0.0])
    # The barrel: the outer skin of the body away from the three nozzles.
    d = P - O
    ang = np.degrees(np.arctan2(d[:, 2], d[:, 0]))
    def away(a0, half, y0, y1):
        return ~((np.abs((ang - a0 + 180) % 360 - 180) < half) & (P[:, 1] > y0) & (P[:, 1] < y1))
    nozzles = {}
    for key in ("cap_01", "cap_02", "cap_03"):
        g = [nodes[n][0] for n in names if key in n]
        b = np.array([[min(x.bounds[0][j] for x in g) for j in range(3)], [max(x.bounds[1][j] for x in g) for j in range(3)]])
        nozzles[key] = b
    body_mask = np.isin(samples[3], [idx["fire_hydrant"]])
    body_mask &= away(90, 50, 0.27, 0.63) & away(150, 38, 0.47, 0.65) & away(30, 38, 0.47, 0.65)
    env = envelope(P, O, Y, 0.0, 0.81, ds=0.004, q=82.0, mask=body_mask)   # the skin, not the lugs on it (baked)
    prof = fit_profile(env, 17)
    prof = [(0.0, prof[0][1])] + prof[1:]
    if prof[-1][1] > 0.002:
        prof.append((prof[-1][0], 0.0))
    charts = [Lathe(O, Y, prof, 24, (0.0, 0.0, 0.62, 1.0), ref=(1, 0, 0))]
    # The nozzles: the pumper (cap_01) to the front, the two hose nozzles at the sides.
    rects = {"cap_01": (0.63, 0.50, 1.0, 1.0), "cap_02": (0.63, 0.25, 1.0, 0.49), "cap_03": (0.63, 0.0, 1.0, 0.24)}
    segs = {"cap_01": 16, "cap_02": 12, "cap_03": 12}
    for key, b in nozzles.items():
        cen = (b[0] + b[1]) / 2
        out = np.array([cen[0] - O[0], 0.0, cen[2] - O[2]]); out /= np.linalg.norm(out)
        org = np.array([O[0], cen[1], O[2]])
        capk = np.isin(samples[3], [idx[n] for n in names if key in n])
        dd = P - org
        s = dd @ out
        tip = float(s[capk].max())
        root = float(np.percentile(s[capk], 0.5))
        # its skin is the cap's (the body's neck under it is baked from the barrel's side)
        e = envelope(P, org, out, root, tip + 0.002, ds=0.003, q=97.0, mask=capk)
        p = fit_profile(e, 6)
        p = [(root - 0.03, p[0][1])] + p[1:]     # run the neck into the barrel
        if p[-1][1] > 0.002:
            p.append((p[-1][0], 0.0))
        charts.append(Lathe(org, out, p, segs[key], rects[key], ref=(0, 1, 0)))
    atlas, filled = bake_atlas(charts, samples, 512, max_dist=0.06)
    mesh = lathe_mesh(charts, [], atlas, "fire_hydrant")
    mesh = to_blocks(mesh, (O[0], O[2]))
    return scene_with([("fire_hydrant", mesh)]), dict(profile_points=len(prof), atlas_filled=round(float(filled), 3))


def build_bin(src):
    nodes = scan_nodes(src, "metal_trash_can", "_rust")
    names = list(nodes)
    idx = {n: i for i, n in enumerate(names)}
    samples = scan_samples(nodes, 1_200_000, seed=5)
    P, N = samples[0], samples[1]
    can, Tcan = nodes["metal_trash_can"]
    O = np.array([Tcan[0, 3], 0.0, Tcan[2, 3]])
    Y = np.array([0.0, 1.0, 0.0])
    top = float(can.bounds[1][1])
    bodyk = samples[3] == idx["metal_trash_can"]
    d = P - O
    r = np.hypot(d[:, 0], d[:, 2])
    radial = np.stack([d[:, 0], np.zeros(len(P)), d[:, 2]], 1) / np.maximum(r, 1e-9)[:, None]
    facing_out = (N * radial).sum(1) > 0.3
    facing_in = (N * radial).sum(1) < -0.3
    # outer wall (no handle brackets: they are baked in), inner wall, the floor inside
    no_brackets = ~((P[:, 1] > 0.6) & (P[:, 1] < 0.7) & (np.abs(d[:, 2]) < 0.1))
    outer = fit_profile(envelope(P, O, Y, 0.0, top, ds=0.004, q=60.0, mask=bodyk & facing_out & no_brackets), 10)
    inner_env = envelope(P, O, Y, 0.0, top, ds=0.006, q=40.0, mask=bodyk & facing_in)
    floor_y = float(np.percentile(P[bodyk & (N[:, 1] > 0.8) & (r < 0.2) & (P[:, 1] < 0.3), 1], 50))
    inner_env = [(s, rr) for s, rr in inner_env if s > floor_y + 0.01]
    inner = fit_profile(inner_env, 5)
    outer = [(0.0, outer[0][1])] + outer[1:]
    r_top_out = max(rr for _, rr in outer[-3:])
    lip = [outer[-1], (top, r_top_out), (top, inner[-1][1])]
    inside = [(top, inner[-1][1])] + [(s, rr) for s, rr in reversed(inner[:-1])] + [(floor_y, inner[0][1]), (floor_y, 0.0)]
    charts = [Lathe(O, Y, outer + lip[1:], 20, (0.0, 0.42, 1.0, 1.0), ref=(1, 0, 0), nodes=[idx["metal_trash_can"]]),
              Lathe(O, Y, inside, 16, (0.0, 0.08, 1.0, 0.41), ref=(1, 0, 0), nodes=[idx["metal_trash_can"]])]
    # The lid, leaning against the can as in the scan: a lathe about its own axis.
    lid, Tl = nodes["metal_trash_can_lid"]
    lo = Tl[:3, 3]; la = Tl[:3, :3] @ np.array([0.0, 1.0, 0.0])
    lk = samples[3] == idx["metal_trash_can_lid"]
    ld = P - lo
    ls = ld @ la
    lr = np.linalg.norm(ld - ls[:, None] * la, axis=1)
    up = (N @ la) > 0.2
    down = (N @ la) < -0.2
    rim_r = float(np.percentile(lr[lk], 99.5))
    rings = np.linspace(0, rim_r, 9)
    def height(mask, r0, r1, q):
        sel = mask & (lr >= r0) & (lr < r1)
        return float(np.percentile(ls[sel], q)) if sel.sum() > 20 else None
    tops = [(height(lk & up, a, b, 95), (a + b) / 2) for a, b in zip(rings[:-1], rings[1:])]
    bots = [(height(lk & down, a, b, 5), (a + b) / 2) for a, b in zip(rings[:-1], rings[1:])]
    tops = [(s, rr) for s, rr in tops if s is not None]
    bots = [(s, rr) for s, rr in bots if s is not None]
    # top: up the rim's edge, then from the rim in to the centre (faces +axis);
    # underside: from the centre out to the rim (faces -axis)
    lid_prof = fit_profile([(bots[-1][0], rim_r), (tops[-1][0], rim_r)] + list(reversed(tops)) + [(tops[0][0], 0.0)], 6)
    under = fit_profile([(bots[0][0], 0.0)] + bots + [(bots[-1][0], rim_r)], 4)
    charts.append(Lathe(lo, la, lid_prof, 16, (0.0, 0.0, 0.5, 0.075), ref=(0, 0, 1), nodes=[idx["metal_trash_can_lid"]]))
    charts.append(Lathe(lo, la, under, 12, (0.5, 0.0, 1.0, 0.075), ref=(0, 0, 1), nodes=[idx["metal_trash_can_lid"]]))
    # handles: three bars each, mount to grip, in the handle's colour (a flat patch of the atlas)
    hk = [idx[n] for n in names if "handle" in n]
    hcol = np.median(samples[2][np.isin(samples[3], hk)], axis=0)
    patch = (496, 496, 512, 512)
    handles = Part()
    huv = ((patch[0] + 8) / 512, 1 - (patch[1] + 8) / 512)
    for n in names:
        if "handle" not in n:
            continue
        hv = nodes[n][0].vertices
        sgn = 1.0 if hv[:, 0].mean() > O[0] else -1.0
        x_wall = O[0] + sgn * (float(np.min(np.abs(hv[:, 0] - O[0]))) + 0.004)
        x_out = O[0] + sgn * (float(np.max(np.abs(hv[:, 0] - O[0]))) - 0.004)
        y_top, y_low = float(hv[:, 1].max()) - 0.006, float(hv[:, 1].min()) + 0.006
        z = float(np.max(np.abs(hv[:, 2] - O[2]))) - 0.006
        for zz in (-z, z):
            bar_part(handles, (x_wall, y_top, O[2] + zz), (x_out, y_low, O[2] + zz), 0.009, huv)
        bar_part(handles, (x_out, y_low, O[2] - z - 0.004), (x_out, y_low, O[2] + z + 0.004), 0.009, huv)
    atlas, filled = bake_atlas(charts, samples, 512, max_dist=0.05, flats=[(patch, hcol)])
    mesh = lathe_mesh(charts, [handles], atlas, "trash_can")
    mesh = to_blocks(mesh, (O[0], O[2]))
    return scene_with([("trash_can", mesh)]), dict(atlas_filled=round(float(filled), 3), floor=round(floor_y, 3))


def build_lamp(src):
    """PROPS-SLIM: the street lamp stands at every one of the map's lamps (up to
    ~60 in range), and the scan's post was 30 050 triangles of cast-iron
    ornament. The post becomes a surface of revolution about its own axis
    (base, shaft, collar, lantern cap) plus one about the x axis for the
    cross-bar under the lantern; the ornament's relief is baked into the atlas.
    The glass and the bulb (560 triangles, their own materials: the glass is
    the part Remix and the night lights read) are kept as they are."""
    nodes = scan_nodes(src, "street_lamp_01", "\0")
    names = list(nodes)
    post = [n for n in names if len(nodes[n][0].faces) > 10000][0]
    pk = names.index(post)
    samples = scan_samples(nodes, 1_500_000, seed=7)
    P, N = samples[0], samples[1]
    postk = samples[3] == pk
    v = nodes[post][0].vertices
    top = float(v[:, 1].max())
    O = np.array([0.0, 0.0, 0.0])
    Y = np.array([0.0, 1.0, 0.0])
    # The cross-bar: where the post reaches out along x at about 2.64-2.70 m.
    arm = (np.abs(v[:, 0]) > 0.06) & (v[:, 1] > 2.5) & (v[:, 1] < 2.8)
    ay0, ay1 = float(v[arm, 1].min()), float(v[arm, 1].max())
    ax = float(np.abs(v[arm, 0]).max())
    armk = postk & (np.abs(P[:, 0]) > 0.055) & (P[:, 1] > ay0 - 0.01) & (P[:, 1] < ay1 + 0.01)
    # The lantern: between the dish under the glass and the roof over it the
    # post is a thin stem and four corner posts (bars, at 45 + 90k degrees), so
    # the glass stays visible (a lathe of the outer skin would wall it in).
    glass = [nodes[n][0] for n in names if n != post and len(nodes[n][0].faces) > 300][0]
    g0, g1 = float(glass.bounds[0][1]), float(glass.bounds[1][1])
    rv = np.hypot(v[:, 0], v[:, 2])
    ang = np.degrees(np.arctan2(v[:, 2], v[:, 0]))
    stem = 0.02
    lower = fit_profile(envelope(P, O, Y, 0.0, g0 + 0.006, ds=0.006, q=92.0, mask=postk & ~armk), 24)
    roof = fit_profile(envelope(P, O, Y, g1 - 0.006, top, ds=0.006, q=92.0, mask=postk), 10)
    prof = [(0.0, 0.0), (0.0, lower[0][1])] + lower[1:]
    prof += [(prof[-1][0], stem), (roof[0][0], stem)] + roof
    if prof[-1][1] > 0.002:
        prof.append((prof[-1][0], 0.0))
    charts = [Lathe(O, Y, prof, 14, (0.0, 0.0, 0.75, 1.0), ref=(1, 0, 0), nodes=[pk])]
    acen = np.array([0.0, (ay0 + ay1) / 2, 0.0])
    aenv = envelope(P, acen, (1, 0, 0), -ax, ax, ds=0.01, q=90.0, mask=armk | (postk & (np.abs(P[:, 1] - acen[1]) < 0.04)))
    aprof = fit_profile(aenv, 8)
    aprof = [(aprof[0][0], 0.0)] + aprof + [(aprof[-1][0], 0.0)]
    charts.append(Lathe(acen, (1, 0, 0), aprof, 6, (0.76, 0.05, 1.0, 1.0), ref=(0, 1, 0), nodes=[pk]))
    # The corner posts: each from the scan's frame vertices at its foot (on the
    # dish rim) to those at the glass's top edge (under the roof's brim).
    patch = (496, 496, 512, 512)
    puv = ((patch[0] + 8) / 512, 1 - (patch[1] + 8) / 512)
    posts = Part()
    nposts = 0
    for a0 in (45, 135, 225, 315):
        near = (np.abs((ang - a0 + 180) % 360 - 180) < 6) & (rv > 0.08)
        foot = v[near & (v[:, 1] > g0 - 0.03) & (v[:, 1] < g0 + 0.005)]
        head = v[near & (np.abs(v[:, 1] - g1) < 0.006)]
        if len(foot) < 3 or len(head) < 3:
            continue
        bar_part(posts, np.median(foot, 0), np.median(head, 0), 0.012, puv)
        nposts += 1
    pcol = np.median(samples[2][postk], axis=0)
    # The bulb (inside the glass) takes its colour from a second flat patch of the
    # atlas, so the lamp is two draws (atlas, glass) and not three.
    bulb_n = [n for n in names if n != post and nodes[n][0] is not glass][0]
    bk = samples[3] == names.index(bulb_n)
    bpatch = (480, 496, 496, 512)
    buv = ((bpatch[0] + 8) / 512, 1 - (bpatch[1] + 8) / 512)
    atlas, filled = bake_atlas(charts, samples, 512, max_dist=0.05, relief=0.5,
                               flats=[(patch, pcol), (bpatch, np.median(samples[2][bk], axis=0))])
    bulb = Part()
    bg = nodes[bulb_n][0]
    bn = bg.vertex_normals
    for f in bg.faces:
        b0 = len(bulb.v)
        for i in f:
            bulb.v.append(np.array(bg.vertices[i], np.float32)); bulb.n.append(np.array(bn[i], np.float32)); bulb.uv.append(buv)
        bulb.f.append([b0, b0 + 1, b0 + 2])
    body = lathe_mesh(charts, [posts, bulb], atlas, "street_lamp")
    body.visual.material.metallicFactor = 0.6
    parts = [("street_lamp", body), ("street_lamp_glass", glass.copy())]
    scene = scene_with(parts)
    scene.apply_transform(trimesh.transformations.scale_matrix(M))
    return scene, dict(profile_points=len(prof), arm_points=len(aprof), posts=nposts, atlas_filled=round(float(filled), 3))


SLIM_PROPS = {   # rule-prop model -> (builder, triangle budget)
    "fire_hydrant": (build_hydrant, 1500),
    "trash_can": (build_bin, 800),
    "street_lamp": (build_lamp, 1800),
}


# ----------------------------------------------------------------------------
# Preview: a tiny painter's renderer (no GPU, no pyrender)
# ----------------------------------------------------------------------------
def gather(scene):
    """World-space triangles with their per-vertex UVs and texture (or flat colour)."""
    out = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        v = trimesh.transform_points(g.vertices, T).astype(np.float32)
        mat = getattr(g.visual, "material", None)
        tex, col = None, np.array([170, 170, 170], np.float32)
        if mat is not None:
            img = getattr(mat, "baseColorTexture", None)
            if img is not None:
                tex = np.array(img.convert("RGB"))
            elif getattr(mat, "baseColorFactor", None) is not None:
                col = np.array(mat.baseColorFactor[:3], np.float32) * (255.0 if max(mat.baseColorFactor[:3]) <= 1.0 else 1.0)
        uv = getattr(g.visual, "uv", None)
        if uv is None or len(uv) != len(g.vertices):
            uv = np.zeros((len(g.vertices), 2), np.float32)
        out.append((v, np.asarray(g.faces), np.asarray(uv, np.float32), tex, col))
    return out


def face_colours(scene):
    tris, cols = [], []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        v = trimesh.transform_points(g.vertices, T)
        f = g.faces
        col = np.array([170, 170, 170], np.float32)
        tex = None
        mat = getattr(g.visual, "material", None)
        if mat is not None:
            img = getattr(mat, "baseColorTexture", None)
            if img is not None:
                tex = np.array(img.convert("RGB"))
            elif getattr(mat, "baseColorFactor", None) is not None:
                col = np.array(mat.baseColorFactor[:3], np.float32) * (255.0 if max(mat.baseColorFactor[:3]) <= 1.0 else 1.0)
            elif getattr(mat, "main_color", None) is not None:
                col = np.array(mat.main_color[:3], np.float32)
        uv = getattr(g.visual, "uv", None)
        for tri in f:
            if tex is not None and uv is not None and len(uv) == len(g.vertices):
                c = uv[tri].mean(axis=0)
                px = int((c[0] % 1.0) * (tex.shape[1] - 1)); py = int(((1 - c[1]) % 1.0) * (tex.shape[0] - 1))
                cols.append(tex[py, px].astype(np.float32))
            else:
                cols.append(col)
            tris.append(v[tri])
    return np.array(tris, np.float32), np.array(cols, np.float32)


def render(scene, view, size=160, yaw=35.0, pitch=-30.0):
    parts = gather(scene)
    if not parts:
        return Image.new("RGBA", (size, size), (50, 50, 50, 255))
    if view == "top":
        R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float32)   # x right, z down the page
        flipdepth = -1.0   # depth = +y: the highest surface wins
    else:
        yaw = math.radians(yaw); pitch = math.radians(pitch)
        Ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]], np.float32)
        Rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]], np.float32)
        R = np.array([[1, 0, 0], [0, -1, 0], [0, 0, 1]], np.float32) @ (Rx @ Ry)
        flipdepth = -1.0
    allv = np.concatenate([p[0] for p in parts]) @ R.T
    mn, mx = allv[:, :2].min(axis=0), allv[:, :2].max(axis=0)
    span = max((mx - mn).max(), 1e-6)
    sc = (size - 16) / span
    off = (size - (mx - mn) * sc) / 2 - mn * sc
    img = np.full((size, size, 3), 50, np.float32)
    zbuf = np.full((size, size), -1e9, np.float32)
    light = np.array([0.4, 0.8, 0.45], np.float32); light /= np.linalg.norm(light)
    ys, xs = np.mgrid[0:size, 0:size]
    for v, f, uv, tex, col in parts:
        p = v @ R.T
        p[:, :2] = p[:, :2] * sc + off
        p[:, 2] *= flipdepth
        for tri in f:
            a, b, c = p[tri[0]], p[tri[1]], p[tri[2]]
            x0, x1 = int(max(0, min(a[0], b[0], c[0]))), int(min(size - 1, max(a[0], b[0], c[0])) + 1)
            y0, y1 = int(max(0, min(a[1], b[1], c[1]))), int(min(size - 1, max(a[1], b[1], c[1])) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            det = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])
            if abs(det) < 1e-9:
                continue
            X = xs[y0:y1, x0:x1] + 0.5; Y = ys[y0:y1, x0:x1] + 0.5
            w1 = ((X - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (Y - a[1])) / det
            w2 = ((b[0] - a[0]) * (Y - a[1]) - (X - a[0]) * (b[1] - a[1])) / det
            w0 = 1.0 - w1 - w2
            inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
            if not inside.any():
                continue
            z = w0 * a[2] + w1 * b[2] + w2 * c[2]
            zb = zbuf[y0:y1, x0:x1]
            win = inside & (z > zb)
            if not win.any():
                continue
            wv = v[tri]
            n = np.cross(wv[1] - wv[0], wv[2] - wv[0]); nn = np.linalg.norm(n)
            shade = 0.55 + 0.45 * abs(float(np.dot(n / nn, light))) if nn > 1e-12 else 0.7
            if tex is not None:
                u = (w0 * uv[tri[0], 0] + w1 * uv[tri[1], 0] + w2 * uv[tri[2], 0]) % 1.0
                vv = (w0 * uv[tri[0], 1] + w1 * uv[tri[1], 1] + w2 * uv[tri[2], 1]) % 1.0
                px = (u * (tex.shape[1] - 1)).astype(int); py = ((1 - vv) * (tex.shape[0] - 1)).astype(int)
                colour = tex[py, px].astype(np.float32)
            else:
                colour = np.broadcast_to(col, X.shape + (3,))
            region = img[y0:y1, x0:x1]
            region[win] = np.clip(colour[win] * shade, 0, 255)
            zb[win] = z[win]
    return Image.fromarray(img.astype(np.uint8), "RGB").convert("RGBA")


def winding_ok(scene):
    """Share of triangles whose winding faces the way their vertex normals do."""
    good = total = 0
    for g in scene.geometry.values():
        fn = np.cross(g.vertices[g.faces[:, 1]] - g.vertices[g.faces[:, 0]], g.vertices[g.faces[:, 2]] - g.vertices[g.faces[:, 0]])
        vn = g.vertex_normals[g.faces].sum(1)
        good += int(((fn * vn).sum(1) > 0).sum()); total += len(fn)
    return round(good / max(total, 1), 4)


def scan_scene(src, name):
    """The Poly Haven scan as the game drew it before PROPS-3, in blocks, with
    its triangle count (drawn nodes only)."""
    folder, exclude = {"fire_hydrant": ("fire_hydrant", "_aged"), "trash_can": ("metal_trash_can", "_rust"),
                       "street_lamp": ("street_lamp_01", "\0")}[name]
    nodes = scan_nodes(src, folder, exclude)
    scene = scene_with([(n, g.copy()) for n, (g, _) in nodes.items()])
    scene.apply_transform(trimesh.transformations.scale_matrix(M))
    b = scene.bounds
    scene.apply_transform(trimesh.transformations.translation_matrix([-(b[0][0] + b[1][0]) / 2, 0, -(b[0][2] + b[1][2]) / 2]))
    return scene, sum(len(g.faces) for _, (g, _) in nodes.items())


def compare_cell(name, before, before_tris, after, after_tris, size=300, pitch=-18.0):
    """Before | after, each from the front-left and the back-right, with counts."""
    cell = Image.new("RGBA", (size * 4 + 30, size + 26), (24, 24, 24, 255))
    for k, (sc, yaw) in enumerate([(before, 35.0), (before, 215.0), (after, 35.0), (after, 215.0)]):
        cell.paste(render(sc, "3q", size, yaw=yaw, pitch=pitch), (k * size + (30 if k >= 2 else 0), 0))
    dr = ImageDraw.Draw(cell)
    dr.text((6, size + 6), f"{name}  BEFORE: {before_tris} triangles", fill=(255, 160, 120, 255))
    dr.text((2 * size + 36, size + 6), f"AFTER: {after_tris} triangles", fill=(140, 255, 140, 255))
    return cell


def main():
    src = sys.argv[1]; out_dir = sys.argv[2]
    sheet_path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
    props_sheet = sys.argv[sys.argv.index("--props-sheet") + 1] if "--props-sheet" in sys.argv else None
    os.makedirs(out_dir, exist_ok=True)
    status, manifest_models, objects_map = {}, [], {}
    cells = []
    for name, (frames, kind, asset, brief) in SPEC.items():
        scene = build(name, src)
        tris = sum(len(g.faces) for g in scene.geometry.values())
        b = scene.bounds
        path = os.path.join(out_dir, name + ".glb")
        scene.export(path)
        nat, x4 = load_sprite(src, frames[0])
        rep = colour_report(scene, nat)
        status[name] = dict(frames=frames, kind=kind, source=asset, brief=brief, triangles=int(tris),
                            colour_model=rep[0] if rep else None, colour_sprite=rep[1] if rep else None, colour_distance=round(rep[2], 1) if rep else None,
                            size_blocks=[round(float(b[1][0] - b[0][0]), 3), round(float(b[1][1] - b[0][1]), 3), round(float(b[1][2] - b[0][2]), 3)],
                            sprite_px=[nat.width, nat.height], sprite_blocks=[round(nat.width * PX, 3), round(nat.height * PX, 3)])
        manifest_models.append(dict(name=name, glb=f"objects/models/{name}.glb", scale=1.0, texture_max=512, forward="+z"))
        for fr in frames:
            objects_map[f"{MAP_OBJ_BASE}:{fr}"] = name
        if sheet_path:
            sp = x4.copy(); sp.thumbnail((150, 150))
            cell = Image.new("RGBA", (160 * 3, 176), (30, 30, 30, 255))
            cell.paste(sp, (80 - sp.width // 2, 80 - sp.height // 2), sp)
            cell.paste(render(scene, "top"), (160, 0)); cell.paste(render(scene, "3q"), (320, 0))
            ImageDraw.Draw(cell).text((4, 162), f"{name}  frames {frames[0]}-{frames[-1]}  {tris} tris  {asset or kind}  colour d={status[name]['colour_distance']}", fill=(255, 255, 0, 255))
            cells.append(cell)
        print(name, tris, "tris", status[name]["size_blocks"])
    # The slim street props (written beside the objects; the import manifest's
    # "fire_hydrant" and "trash_can" entries point at these GLBs).
    props_cells = []
    for name, (builder, budget) in SLIM_PROPS.items():
        scene, info = builder(src)
        tris = sum(len(g.faces) for g in scene.geometry.values())
        assert tris <= budget, f"{name}: {tris} triangles, budget {budget}"
        b = scene.bounds
        scene.export(os.path.join(out_dir, name + ".glb"))
        status[name] = dict(kind="slim_prop", triangles=int(tris), budget=budget, winding_ok=winding_ok(scene),
                            size_blocks=[round(float(b[1][j] - b[0][j]), 3) for j in range(3)], **info)
        manifest_models.append(dict(name=name, glb=f"objects/models/{name}.glb", scale=1.0, texture_max=512))
        print(name, tris, "tris", status[name])
        if props_sheet:
            before, before_tris = scan_scene(src, name)
            props_cells.append(compare_cell(name, before, before_tris, scene, tris))
    if props_sheet:
        nat, x4 = load_sprite(src, 21)
        old_g = build_box("obj_girder", nat, x4)
        new_g = build("obj_girder", src)
        props_cells.append(compare_cell("obj_girder (5:21)", old_g, sum(len(g.faces) for g in old_g.geometry.values()),
                                        new_g, sum(len(g.faces) for g in new_g.geometry.values()), pitch=-22.0))
        sheet = Image.new("RGBA", (props_cells[0].width, sum(c.height for c in props_cells)), (24, 24, 24, 255))
        y = 0
        for c in props_cells:
            sheet.paste(c, (0, y)); y += c.height
        sheet.save(props_sheet)
        print("props sheet", props_sheet)
    json.dump(status, open(os.path.join(out_dir, "status.json"), "w"), indent=1)
    json.dump(dict(models=manifest_models, objects=objects_map), open(os.path.join(out_dir, "manifest_fragment.json"), "w"), indent=1)
    if sheet_path and cells:
        cols = 2; rows = (len(cells) + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * 480, rows * 176), (30, 30, 30, 255))
        for i, c in enumerate(cells):
            sheet.paste(c, ((i % cols) * 480, (i // cols) * 176))
        sheet.save(sheet_path)
        print("sheet", sheet_path)


if __name__ == "__main__":
    main()
