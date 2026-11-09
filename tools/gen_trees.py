#!/usr/bin/env python3
"""Procedural park trees for the street views: a tapered trunk with a few
branches and a canopy of alpha-cutout leaf cards (three crossed vertical cards
and two tilted horizontal ones), textured with generated bark and a generated
leaf-cluster sheet. Three variants: a tall slim tree, a round one and a wide
one. Output: GLBs with PBR materials, origin at the base of the trunk, +y up,
units in blocks (the importer scales them by the manifest / the placement rule).

    gen_trees.py <out dir>
"""
import math, os, sys
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFilter

def leaf_sheet(seed, tint, size=512, n=3200):
    rng = np.random.default_rng(seed)
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    for i in range(n):
        # cluster toward the middle, fall off at the edge of the card
        ang = rng.uniform(0, 2 * math.pi); r = (rng.uniform(0, 1) ** 0.5) * size * 0.47
        x, y = cx + math.cos(ang) * r, cy + math.sin(ang) * r * 0.92
        lw, lh = rng.uniform(16, 34), rng.uniform(9, 19)
        shade = rng.uniform(0.5, 1.2) * (0.75 + 0.5 * (1 - r / (size * 0.47)))   # darker toward the rim, lit at the crown
        c = tuple(int(min(255, max(0, t * shade + rng.uniform(-12, 12)))) for t in tint)
        rot = rng.uniform(0, 180)
        leaf = Image.new('RGBA', (int(lw) + 4, int(lh) + 4), (0, 0, 0, 0))
        ImageDraw.Draw(leaf).ellipse((2, 2, lw + 1, lh + 1), fill=c + (255,))
        leaf = leaf.rotate(rot, expand=True)
        img.alpha_composite(leaf, (int(x - leaf.width / 2), int(y - leaf.height / 2)))
    # soften the alpha edge a touch so the cutout is not jagged at 512
    a = img.split()[3].filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(a)
    return fill_transparent(img)

def fill_transparent(img):
    """Every texel that is not fully opaque gets the colour of the leaves around it (FIX-PROPS-3,
    defect pm8-ste-trees-render-black-spike-shards). The sheet was drawn on (0,0,0,0) and the
    blurred alpha gave the black around every leaf a little coverage: the renderer alpha-tests
    the props at a low reference and the model textures have no mip levels, so a canopy seen
    from a few blocks sampled mostly that black fringe and read as black shards. Pull-push:
    the colour weighted by alpha, blurred wider and wider, fills the gaps; alpha is unchanged."""
    arr = np.asarray(img, np.float32)
    rgb, a = arr[..., :3], arr[..., 3:] / 255.0
    size = img.size[0]

    def resize(x, n):   # each channel of a float array to n x n (box down, bilinear up)
        filt = Image.BOX if n < x.shape[0] else Image.BILINEAR
        return np.stack([np.asarray(Image.fromarray(x[..., k], 'F').resize((n, n), filt), np.float32)
                         for k in range(x.shape[-1])], -1)
    # push: the premultiplied colour and the coverage down to 1 x 1
    levels = [(rgb * a, a)]
    while levels[-1][1].shape[0] > 1:
        c, w = levels[-1]; n = c.shape[0] // 2
        levels.append((resize(c, n), resize(w, n)))
    # pull: each level's colour where it has coverage, else the coarser level's
    colour = levels[-1][0] / np.maximum(levels[-1][1], 1e-6)
    for c, w in reversed(levels[:-1]):
        up = resize(colour, c.shape[0])
        own = c / np.maximum(w, 1e-6)
        colour = np.where(w > 1e-3, own, up)
    out = rgb.copy()
    hole = a[..., 0] < 0.999
    out[hole] = colour[hole]
    return Image.fromarray(np.concatenate([np.clip(out, 0, 255), arr[..., 3:]], -1).astype(np.uint8), 'RGBA')

def bark_sheet(seed, size=256):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    v = np.zeros((size, size), np.float32)
    for k, amp in ((3, 1.0), (7, 0.5), (15, 0.25), (31, 0.12)):
        v += amp * np.sin(x / size * 2 * math.pi * k + rng.uniform(0, 6) + 0.8 * np.sin(y / size * 2 * math.pi * (k // 2 + 1)))
    v = (v - v.min()) / (v.max() - v.min())
    base = np.array([92, 68, 48], np.float32)
    rgb = base[None, None, :] * (0.55 + 0.6 * v[..., None]) + rng.normal(0, 6, (size, size, 3))
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), 'RGB').convert('RGBA')
    return img

def cylinder(p0, p1, r0, r1, n=8):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    axis = p1 - p0; L = np.linalg.norm(axis); axis /= L
    a = np.array([1, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 0, 1])
    u = np.cross(axis, a); u /= np.linalg.norm(u); w = np.cross(axis, u)
    verts, uvs = [], []
    for ring, (p, r) in enumerate(((p0, r0), (p1, r1))):
        for i in range(n + 1):
            t = i / n * 2 * math.pi
            verts.append(p + (math.cos(t) * u + math.sin(t) * w) * r)
            uvs.append((i / n * 2.0, ring * L / max(r0, 0.05) * 0.5))
    faces = []
    for i in range(n):
        a0, a1, b0, b1 = i, i + 1, n + 1 + i, n + 1 + i + 1
        faces += [(a0, b0, b1), (a0, b1, a1)]
    return np.array(verts), np.array(faces), np.array(uvs)

def card(center, width, height, yaw, tilt=0.0):
    """A quad standing at center, facing its yaw; both windings so it shows from both sides."""
    cx, cy, cz = center
    dx, dz = math.cos(yaw) * width / 2, math.sin(yaw) * width / 2
    ty = math.sin(tilt) * width / 2
    v = np.array([[cx - dx, cy - height / 2 - ty, cz - dz], [cx + dx, cy - height / 2 + ty, cz + dz],
                  [cx + dx, cy + height / 2 + ty, cz + dz], [cx - dx, cy + height / 2 - ty, cz - dz]])
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    f = np.array([[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]])
    return v, f, uv

def flat_card(center, size, rot, tilt):
    cx, cy, cz = center
    c, s = math.cos(rot), math.sin(rot)
    pts = []
    for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x, z = sx * size / 2, sz * size / 2
        pts.append([cx + x * c - z * s, cy + sx * math.sin(tilt) * size / 2 * 0.35, cz + x * s + z * c])
    v = np.array(pts); uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
    f = np.array([[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]])
    return v, f, uv

def build(variant, out_dir):
    name, height, canopy_w, canopy_h, trunk_r, tint, seed = variant
    rng = np.random.default_rng(seed)
    bark_parts, leaf_parts = [], []
    trunk_top = height * 0.55
    bark_parts.append(cylinder((0, 0, 0), (0, trunk_top, 0), trunk_r, trunk_r * 0.55))
    for i in range(4):
        ang = i / 4 * 2 * math.pi + rng.uniform(-0.4, 0.4)
        y0 = trunk_top * rng.uniform(0.6, 0.95)
        tip = (math.cos(ang) * canopy_w * 0.3, y0 + height * 0.2, math.sin(ang) * canopy_w * 0.3)
        bark_parts.append(cylinder((0, y0, 0), tip, trunk_r * 0.45, trunk_r * 0.15, 6))
    cy = trunk_top + canopy_h * 0.42
    for i in range(3):
        leaf_parts.append(card((0, cy, 0), canopy_w, canopy_h, i / 3 * math.pi + rng.uniform(-0.2, 0.2)))
    leaf_parts.append(flat_card((0, cy + canopy_h * 0.12, 0), canopy_w * 0.95, rng.uniform(0, 3), 0.25))
    leaf_parts.append(flat_card((0, cy - canopy_h * 0.18, 0), canopy_w * 0.85, rng.uniform(0, 3), -0.2))
    scene = trimesh.Scene()
    def merge(parts, image, name_):
        vs, fs, uvs = [], [], []; off = 0
        for v, f, uv in parts:
            vs.append(v); fs.append(f + off); uvs.append(uv); off += len(v)
        m = trimesh.Trimesh(np.vstack(vs), np.vstack(fs), process=False)
        mat = trimesh.visual.material.PBRMaterial(name=name_, baseColorTexture=image, metallicFactor=0.0,
                                                  roughnessFactor=0.9, doubleSided=True, alphaMode='MASK' if name_ == 'leaves' else 'OPAQUE')
        m.visual = trimesh.visual.TextureVisuals(uv=np.vstack(uvs), material=mat)
        return m
    scene.add_geometry(merge(bark_parts, bark_sheet(seed), 'bark'), node_name='trunk', geom_name='trunk')
    scene.add_geometry(merge(leaf_parts, leaf_sheet(seed + 1, tint), 'leaves'), node_name='canopy', geom_name='canopy')
    path = os.path.join(out_dir, name + '.glb')
    scene.export(path)
    tris = sum(len(g.faces) for g in scene.geometry.values())
    print(name, 'height', height, 'triangles', tris, '->', path)

VARIANTS = [
    ('tree_01', 2.8, 1.5, 1.7, 0.09, (70, 118, 46), 11),   # tall, slim, mid green
    ('tree_02', 2.2, 1.9, 1.5, 0.11, (88, 128, 52), 23),   # round
    ('tree_03', 2.5, 2.3, 1.3, 0.12, (104, 122, 48), 37),  # wide, yellow-green
]

if __name__ == '__main__':
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    for v in VARIANTS: build(v, out)
