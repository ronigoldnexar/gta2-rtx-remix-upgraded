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
from PIL import Image, ImageDraw
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
    "obj_girder":      ([21],                "proc_box",  None, "steel girder / road plate, grey, lying flat"),
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
# Procedural box heights and side colours per model (blocks).
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


def render(scene, view, size=160):
    parts = gather(scene)
    if not parts:
        return Image.new("RGBA", (size, size), (50, 50, 50, 255))
    if view == "top":
        R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float32)   # x right, z down the page
        flipdepth = -1.0   # depth = +y: the highest surface wins
    else:
        yaw = math.radians(35); pitch = math.radians(-30)
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


def main():
    src = sys.argv[1]; out_dir = sys.argv[2]
    sheet_path = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv else None
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
