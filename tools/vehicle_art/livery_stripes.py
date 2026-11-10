#!/usr/bin/env python3
"""VEHICLE-ART-17 (pmzz): a remapped livery's racing stripes as their own untinted geometry.

The classic sprite of the 071 Rumbler carries two pale stripes over bonnet, roof and boot in every one of its twelve
remaps (the game recolours the body, never the stripes). The generated 3D body has them on one atlas panel only, and
whatever the paint half holds is tinted by the identity record; under Remix the split pair is one merged surface that
the tint multiplies whole (FIX-REMIX-MATERIALS-7 note on the pmzz order), so painted stripes go dark green there too.

This adds a 'stripes' node: the body's up-facing paint triangles clipped to the stripe bands (|x| in [a, b], both
sides), lifted along their normals by OFFSET, mapped to <name>_stripe.tga (a small flat pale picture, the sprite's
stripe colour). It is not a '_paint' texture, so the record never tints it and Remix sees its own draw. The paint
half under it is unchanged. Deterministic; re-running replaces an earlier stripes node.

    vreg/venv/bin/python tools/vehicle_art/livery_stripes.py <models dir> <out dir> 071
"""
import os
import sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import mesh_io  # noqa

NODE = "stripes"
SPRITES = os.environ.get("SPRITES", "/mnt/gta2/gta2-linux/assets-src/cars/sprites")
OFFSET = 0.0012          # blocks (~6 mm): over the paint, under the near fade's z precision
# per model: the bands in the body's x (blocks), the sprite's stripe colour, the least up-facing normal.y
LIVERIES = {
    # 071: sprite body 32 px wide (cols 12..43), nose down; two stripes of 5 px, cols 20..24 and 31..35, over bonnet,
    # roof and boot in all twelve remaps (pale lavender-white 226,203,227 in the default; the glass rows carry none:
    # the paint-only test below drops the glass).
    "071": dict(shapes=[("rect", 20, 25, 0, 64), ("rect", 31, 36, 0, 64)], colour=(226, 212, 228), min_up=0.30),
    # 083 Furore GT: body cols 9..40; one centre stripe, 6 px over the deck (rows 2..9), 8 px over the roof (rows 15..34),
    # a 6 px piece on the bonnet (rows 42..48); pale 241,233,244 in all twelve remaps.
    "083": dict(shapes=[("rect", 22, 28, 0, 15), ("rect", 21, 29, 15, 35), ("rect", 22, 28, 41, 49)], colour=(234, 228, 238), min_up=0.30),
    # 049 Hachura: body cols 16..47; a 4 px centre stripe (cols 30..33) from the tail to the nose, 6 px over the nose
    # (rows 54..60); pale 245,236,248 in all seventeen remaps.
    "049": dict(shapes=[("rect", 30, 34, 2, 54), ("rect", 29, 35, 54, 61)], colour=(236, 229, 240), min_up=0.30),
}


def to_model(shape, sprite_box, mesh_box):
    """a sprite shape (pixel edges: pixel col c spans [c, c + 1]; rows y, nose down) -> a convex polygon in the model's (x, z)"""
    (c0, c1, r0, r1), (x0, x1, z0, z1) = sprite_box, mesh_box
    cx = (c0 + c1 + 1) / 2.0
    hw_s = (c1 + 1 - c0) / 2.0
    X = lambda col: (col - cx) / hw_s * (x1 - x0) / 2.0 + (x0 + x1) / 2.0
    Z = lambda row: z0 + (row - r0) / float(r1 + 1 - r0) * (z1 - z0)      # row r1 (the nose) -> z1 (+z nose)
    if shape[0] == "rect":
        _, a, b, ra, rb = shape
        return [(X(a), Z(ra)), (X(b), Z(ra)), (X(b), Z(rb)), (X(a), Z(rb))]
    _, ccol, crow, rad = shape
    return [(X(ccol + rad * np.cos(t)), Z(crow + rad * np.sin(t))) for t in np.linspace(0, 2 * np.pi, 20, endpoint=False)]


def read_tga(path):
    return np.asarray(Image.open(path).convert("RGBA"))


def clip(poly, e0, e1):
    """Sutherland-Hodgman: keep the part of poly (arrays [pos(3), nrm(3)]) left of the (x, z) edge e0 -> e1
    (the shape polygons are counter-clockwise in (x, z))"""
    ex, ez = e1[0] - e0[0], e1[1] - e0[1]
    side = lambda q: ex * (q[2] - e0[1]) - ez * (q[0] - e0[0])
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        da, db = side(a), side(b)
        if da >= 0:
            out.append(a)
        if (da >= 0) != (db >= 0):
            out.append(a + (b - a) * (da / (da - db)))
    return out


def ccw(poly):
    area = sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))
    return poly if area > 0 else poly[::-1]


def build(m, models_dir, spec, sprite_box):
    W = mesh_io.world(m)
    allP = np.vstack([P for _, me, P, _, _, _ in W if me["tex"].endswith("_paint.tga")])
    mesh_box = (allP[:, 0].min(), allP[:, 0].max(), allP[:, 2].min(), allP[:, 2].max())
    shapes = [ccw(to_model(sh, sprite_box, mesh_box)) for sh in spec["shapes"]]
    F_all, verts = [], []
    for node, me, P, N, UV, F in W:
        if not me["tex"].endswith("_paint.tga"):
            continue
        pic = read_tga(os.path.join(models_dir, me["tex"]))
        h, w = pic.shape[:2]
        for tri in F:
            p = P[tri]; nrm = N[tri]
            fn = np.cross(p[1] - p[0], p[2] - p[0])
            ln = np.linalg.norm(fn)
            if ln < 1e-12:
                continue
            fn /= ln
            if fn[1] < 0:            # wound the other way: use the vertex normals' sense
                if nrm.mean(0)[1] < 0:
                    continue
                fn = -fn
            if fn[1] < spec["min_up"] or nrm.mean(0)[1] < spec["min_up"]:
                continue
            # the triangle must be painted body (the split's alpha), not glass or trim: the centroid and the three
            # corners pulled 20 % in, kept when at least two of the four samples are paint
            uvs = np.vstack([UV[tri].mean(0)[None], UV[tri] * 0.8 + UV[tri].mean(0)[None] * 0.2])
            pxs = np.clip((uvs[:, 0] * w).astype(int), 0, w - 1); pys = np.clip((uvs[:, 1] * h).astype(int), 0, h - 1)
            if (pic[pys, pxs, 3] >= 128).sum() < 2:
                continue
            for shp in shapes:
                xs = [q[0] for q in shp]; zs = [q[1] for q in shp]
                if p[:, 0].max() < min(xs) or p[:, 0].min() > max(xs) or p[:, 2].max() < min(zs) or p[:, 2].min() > max(zs):
                    continue
                poly = [np.concatenate([p[k], nrm[k]]) for k in range(3)]
                for i in range(len(shp)):
                    poly = clip(poly, shp[i], shp[(i + 1) % len(shp)])
                    if len(poly) < 3:
                        break
                if len(poly) < 3:
                    continue
                base = len(verts)
                for q in poly:
                    nn = q[3:6] / max(np.linalg.norm(q[3:6]), 1e-9)
                    pos = q[:3] + nn * OFFSET
                    verts.append(np.concatenate([pos, nn, [0.5 + (pos[0] - np.mean(xs)) / max(1e-6, max(xs) - min(xs)), 0.5 + pos[2]]]))
                for k in range(1, len(poly) - 1):
                    F_all.append((base, base + k, base + k + 1))
    return np.array(verts, np.float32), np.array(F_all, np.uint32).ravel()


def sprite_box(num):
    import glob
    f = sorted(glob.glob(os.path.join(SPRITES, f"{num}_*_default.png")))[0]
    a = np.asarray(Image.open(f).convert("RGBA"))[..., 3] > 0
    ys, xs = np.nonzero(a)
    return xs.min(), xs.max(), ys.min(), ys.max()


def texture(colour, size=32):
    yy, xx = np.mgrid[0:size, 0:size] / float(size - 1)
    edge = np.clip(np.minimum(xx, 1 - xx) / 0.10, 0, 1) ** 0.5   # a slightly softer edge texel column each side
    c = np.array(colour, np.float32)[None, None, :] * (0.93 + 0.07 * edge[..., None])
    a = np.full((size, size, 1), 255, np.float32)
    return Image.fromarray(np.concatenate([c, a], -1).clip(0, 255).astype(np.uint8), "RGBA")


def apply(models_dir, out_dir, num):
    import glob
    import import_assets
    spec = LIVERIES[num]
    name = os.path.basename(glob.glob(os.path.join(models_dir, f"{num}_*.mesh"))[0])[:-5]
    m = mesh_io.read(os.path.join(models_dir, name + ".mesh"))
    if any(n["name"] == NODE for n in m["nodes"]):
        old = [n["mesh"] for n in m["nodes"] if n["name"] == NODE][0]
        m["nodes"] = [n for n in m["nodes"] if n["name"] != NODE]
        for n in m["nodes"]:
            if n["mesh"] > old:
                n["mesh"] -= 1
        del m["meshes"][old]
    V, idx = build(m, models_dir, spec, sprite_box(num))
    tex = f"{name}_stripe.tga"
    m["meshes"].append(dict(tex=tex, skin=-1, v=V, idx=idx))
    m["nodes"].append(dict(name=NODE, parent=-1, t=(0.0, 0.0, 0.0), r=(0.0, 0.0, 0.0, 1.0), s=(1.0, 1.0, 1.0), mesh=len(m["meshes"]) - 1))
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, name + ".mesh")
    if os.path.lexists(out):
        os.unlink(out)
    mesh_io.write(m, out)
    t = os.path.join(out_dir, tex)
    if os.path.lexists(t):
        os.unlink(t)
    import_assets.write_tga(texture(spec["colour"]), t)
    print(f"{name}: {len(idx) // 3} stripe triangles, {len(V)} vertices, x {V[:, 0].min():.3f}..{V[:, 0].max():.3f} "
          f"z {V[:, 2].min():.3f}..{V[:, 2].max():.3f} -> {out}, {t}")


if __name__ == "__main__":
    md, od = sys.argv[1], sys.argv[2]
    for num in sys.argv[3:]:
        apply(md, od, num.zfill(3))
