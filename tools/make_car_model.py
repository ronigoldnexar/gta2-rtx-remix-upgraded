#!/usr/bin/env python3
"""Turn an image-to-3D car mesh (TRELLIS GLB) into a game-ready car model that
matches its GTA2 sprite: upright, nose along +z, footprint scaled to the CARI
body size (64 px = 1 block), wheels on y=0, the sprite painted onto the
upward-facing surfaces so the car seen from above is the game's own art, and a
metallic-paint PBR material.

    python3 tools/make_car_model.py in.glb out.glb --catalog assets-src/cars/catalog.json --model 10
            [--sprite sprites_x4/010_bulwark_default.png] [--faces 8000] [--render out.png]

Needs torch + nvdiffrast (the gen3d venv) for the texture projection.
"""
import argparse, json, math, os, sys
import numpy as np
import trimesh
from PIL import Image


def load_single(path):
    scene = trimesh.load(path, force='scene')
    parts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        if isinstance(g, trimesh.Trimesh):
            g = g.copy()
            g.apply_transform(T)
            parts.append(g)
    if len(parts) == 1:
        return parts[0]
    # TRELLIS writes one mesh; if not, keep the biggest textured one.
    parts.sort(key=lambda m: -len(m.faces))
    return parts[0]


def texture_of(mesh):
    vis = mesh.visual
    if isinstance(vis, trimesh.visual.TextureVisuals) and vis.material is not None:
        mat = vis.material
        if getattr(mat, 'baseColorTexture', None) is not None:
            return mat.baseColorTexture.convert('RGBA')
        if getattr(mat, 'image', None) is not None:
            return mat.image.convert('RGBA')
    return None


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], np.float64)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], np.float64)


def face_brightness(mesh, tex, mask_faces):
    """Mean texture brightness over the given faces (sampled at face centroid UVs)."""
    if tex is None or not mask_faces.any():
        return 0.5
    uv = np.asarray(mesh.visual.uv)
    t = np.asarray(tex.convert('L'), np.float32) / 255
    fuv = uv[mesh.faces[mask_faces]].mean(1)
    x = np.clip((fuv[:, 0] * (t.shape[1] - 1)).astype(int), 0, t.shape[1] - 1)
    y = np.clip(((1 - fuv[:, 1]) * (t.shape[0] - 1)).astype(int), 0, t.shape[0] - 1)
    return float(t[y, x].mean())


def orient(mesh, tex, car, log):
    """Upright (+y), long axis along z, nose toward +z."""
    v = mesh.vertices - mesh.vertices.mean(0)
    mesh.vertices = v
    # 1. Which way is up: the lit, painted roof is brighter than the underside.
    n = mesh.face_normals
    up_b = face_brightness(mesh, tex, n[:, 1] > 0.6)
    dn_b = face_brightness(mesh, tex, n[:, 1] < -0.6)
    log(f"brightness up={up_b:.3f} down={dn_b:.3f}")
    if dn_b > up_b + 0.03:
        mesh.apply_transform(rot_z(math.pi))
        log("flipped upright")
    # 2. Long axis along z (PCA in the ground plane).
    xz = mesh.vertices[:, [0, 2]]
    cov = np.cov(xz.T)
    w, vec = np.linalg.eigh(cov)
    ax = vec[:, np.argmax(w)]           # (x, z) of the long axis
    ang = math.atan2(ax[0], ax[1])      # rotate so the axis becomes +z
    mesh.apply_transform(rot_y(ang))
    # 3. Nose: compare where the cabin sits along the length with the sprite's window rows.
    #    Sprite: top of the sprite is the front; rows grow toward the rear.
    wf, wr = car['windows_px']['front_y'], car['windows_px']['rear_y']
    sprite_len = car['body_px'][1]
    cabin_sprite = (sprite_len / 2.0 - (wf + wr) / 2.0) / sprite_len   # >0: cabin forward of centre
    vz = mesh.vertices[:, 2]
    vy = mesh.vertices[:, 1]
    zmin, zmax = vz.min(), vz.max()
    bins = 24
    h = np.zeros(bins)
    for i in range(bins):
        sel = (vz >= zmin + (zmax - zmin) * i / bins) & (vz < zmin + (zmax - zmin) * (i + 1) / bins)
        h[i] = vy[sel].max() if sel.any() else vy.min()
    top = h.max()
    cab = np.where(h > vy.min() + 0.85 * (top - vy.min()))[0]
    cabin_mesh = ((cab.mean() + 0.5) / bins - 0.5) if len(cab) else 0.0   # >0: cabin toward +z
    log(f"cabin offset sprite={cabin_sprite:+.3f} mesh={cabin_mesh:+.3f}")
    if abs(cabin_sprite) > 0.03 and abs(cabin_mesh) > 0.02 and (cabin_sprite > 0) != (cabin_mesh > 0):
        mesh.apply_transform(rot_y(math.pi))
        log("turned nose to +z")
    mesh.vertices -= mesh.vertices.mean(0)


def fit(mesh, car, log):
    """Scale the footprint to the sprite's body size (blocks), wheels on y=0."""
    lo, hi = mesh.vertices.min(0), mesh.vertices.max(0)
    size = hi - lo
    width_b, length_b = car['body_px'][0] / 64.0, car['body_px'][1] / 64.0
    sx, sz = width_b / size[0], length_b / size[2]
    sy = math.sqrt(sx * sz)
    log(f"mesh size {size[0]:.3f} x {size[1]:.3f} x {size[2]:.3f} -> {width_b:.3f} x {size[1]*sy:.3f} x {length_b:.3f} blocks")
    S = np.diag([sx, sy, sz, 1.0])
    mesh.apply_transform(S)
    lo, hi = mesh.vertices.min(0), mesh.vertices.max(0)
    mesh.vertices -= np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])


def paint_from_above(mesh, tex, sprite, car, log, paint_rgb=(190, 160, 120), min_ny=0.3, full_ny=0.75):
    """Project the sprite onto the upward-facing surfaces, in texture space."""
    import torch
    import nvdiffrast.torch as dr
    if tex is None or mesh.visual.uv is None:
        log("no texture; skipping roof paint")
        return tex
    ctx = dr.RasterizeCudaContext()
    H, W = tex.size[1], tex.size[0]
    uv = torch.tensor(np.asarray(mesh.visual.uv), dtype=torch.float32, device='cuda')
    # UV -> clip space: glTF v=0 is the top texture row; nvdiffrast row 0 is clip y=-1,
    # i.e. the bottom, and trimesh's texture array has row 0 at the top, so v flips.
    clip = torch.stack([uv[:, 0] * 2 - 1, (1 - uv[:, 1]) * 2 - 1, torch.zeros_like(uv[:, 0]), torch.ones_like(uv[:, 0])], 1)
    faces = torch.tensor(mesh.faces, dtype=torch.int32, device='cuda')
    rast, _ = dr.rasterize(ctx, clip[None], faces, (H, W))
    pos = torch.tensor(mesh.vertices, dtype=torch.float32, device='cuda')
    nrm = torch.tensor(mesh.vertex_normals, dtype=torch.float32, device='cuda')
    p, _ = dr.interpolate(pos[None], rast, faces)
    n, _ = dr.interpolate(nrm[None], rast, faces)
    hit = rast[0, ..., 3] > 0
    p, n = p[0], n[0]
    n = n / (n.norm(dim=-1, keepdim=True) + 1e-6)
    # Sprite lookup: the body occupies body_px centred in the sprite canvas, nose at the top.
    sp = np.asarray(sprite.convert('RGBA'), np.float32) / 255
    sh, sw = sp.shape[:2]
    scale = sw / car['sprite_px'][0]          # x4 sprites: 4
    body_w, body_l = car['body_px'][0] / 64.0, car['body_px'][1] / 64.0
    cx, cy = sw / 2.0, sh / 2.0
    # Edge-extend the sprite so overhanging texels still get paint.
    rgb, a = sp[..., :3], sp[..., 3]
    known = a > 0.5
    for _ in range(12):
        acc = np.zeros_like(rgb); cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k = np.roll(known, (dy, dx), (0, 1)); c = np.roll(rgb, (dy, dx), (0, 1))
            acc += c * k[:, :, None]; cnt += k
        fill = (~known) & (cnt > 0)
        rgb[fill] = acc[fill] / cnt[fill][:, None]; known |= fill
    sprite_t = torch.tensor(rgb, device='cuda')
    alpha_t = torch.tensor(np.where(a > 0.5, 1.0, 0.0).astype(np.float32), device='cuda')
    # World x (right) -> sprite column; world z (nose +z) -> sprite row from the top.
    u = cx + p[..., 0] / body_w * (car['body_px'][0] * scale)
    vrow = cy - p[..., 2] / body_l * (car['body_px'][1] * scale)
    ui = u.clamp(0, sw - 1).long(); vi = vrow.clamp(0, sh - 1).long()
    col = sprite_t[vi, ui]
    cover = alpha_t[vi, ui]
    wgt = ((n[..., 1] - min_ny) / (full_ny - min_ny)).clamp(0, 1)
    wgt = wgt * cover * hit.float()
    base = torch.tensor(np.asarray(tex, np.float32)[..., :3] / 255, device='cuda')
    # Match the concept's body paint to the sprite's: the median colour of the texels the
    # sprite is about to cover (the concept's roof/hood) against the sprite's own paint there.
    sel = wgt > 0.9
    if sel.sum() > 100:
        concept_paint = base[sel].median(dim=0).values
        # Target: the catalog's paint colour for this remap (the sprite's own top-down shading
        # would make it too dark); keep the shift mostly a brightness change so chrome and
        # glass are not tinted.
        sprite_paint = torch.tensor(np.array(paint_rgb, np.float32) / 255, device='cuda')
        ratio = (sprite_paint / concept_paint.clamp(min=0.05)).clamp(0.5, 2.0)
        ratio = ratio.mean() + (ratio - ratio.mean()).clamp(-0.2, 0.2)
        base = (base * ratio).clamp(0, 1)
        log(f"paint match ratio {ratio.cpu().numpy().round(2).tolist()}")
    out = base * (1 - wgt[..., None]) + col * wgt[..., None]
    # Dilate the painted result a little so bilinear sampling at seams does not pull the old colour.
    img = (out.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
    painted = float((wgt > 0.5).float().mean())
    log(f"roof paint covers {painted*100:.1f}% of the texture")
    res = Image.fromarray(img).convert('RGBA')
    return res


def decimate(mesh, faces):
    if len(mesh.faces) <= faces:
        return mesh
    try:
        import pymeshlab
        ms = pymeshlab.MeshSet()
        m = pymeshlab.Mesh(vertex_matrix=np.asarray(mesh.vertices, np.float64), face_matrix=np.asarray(mesh.faces, np.int32),
                           v_tex_coords_matrix=np.asarray(mesh.visual.uv, np.float64))
        ms.add_mesh(m)
        name = next(f for f in dir(ms) if 'collapse' in f and 'texture' in f)
        getattr(ms, name)(targetfacenum=int(faces), preserveboundary=True, qualitythr=0.3)
        out = ms.current_mesh()
        uv = out.vertex_tex_coord_matrix()
        new = trimesh.Trimesh(out.vertex_matrix(), out.face_matrix(), process=False)
        new.visual = trimesh.visual.TextureVisuals(uv=uv, material=mesh.visual.material)
        return new
    except Exception as e:  # noqa
        print("decimation failed, keeping the mesh:", e)
        return mesh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('out')
    ap.add_argument('--catalog', required=True); ap.add_argument('--model', type=int, required=True)
    ap.add_argument('--sprite', default=None); ap.add_argument('--faces', type=int, default=8000)
    ap.add_argument('--render', default=None); ap.add_argument('--no-paint', action='store_true')
    ap.add_argument('--metallic', type=float, default=0.55); ap.add_argument('--roughness', type=float, default=0.38)
    a = ap.parse_args()
    cat = json.load(open(a.catalog))
    car = next(c for c in cat['cars'] if c['model'] == a.model)
    root = os.path.dirname(os.path.abspath(a.catalog))
    sprite_path = a.sprite or os.path.join(root, car['remaps'][0]['file_x4'])
    logs = []
    def log(s):
        logs.append(s); print(s, flush=True)
    mesh = load_single(a.src)
    tex = texture_of(mesh)
    log(f"{a.src}: {len(mesh.vertices)} verts {len(mesh.faces)} faces, texture {tex.size if tex else None}")
    orient(mesh, tex, car, log)
    fit(mesh, car, log)
    mesh = decimate(mesh, a.faces)
    mesh.fix_normals()
    if not a.no_paint:
        tex = paint_from_above(mesh, tex, Image.open(sprite_path), car, log, paint_rgb=car['remaps'][0]['paint_rgb'])
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex, metallicFactor=a.metallic, roughnessFactor=a.roughness,
                                              name=f"car_{a.model:03d}")
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.asarray(mesh.visual.uv), material=mat)
    mesh.metadata['gta2_model'] = a.model
    mesh.export(a.out)
    lo, hi = mesh.vertices.min(0), mesh.vertices.max(0)
    log(f"wrote {a.out}: {len(mesh.faces)} faces, size {hi[0]-lo[0]:.3f} x {hi[1]-lo[1]:.3f} x {hi[2]-lo[2]:.3f} blocks, nose +z, up +y")
    json.dump(dict(model=a.model, name=car['name'], faces=int(len(mesh.faces)), size_blocks=[float(x) for x in hi - lo],
                   forward="+z", log=logs), open(os.path.splitext(a.out)[0] + '.json', 'w'), indent=1)
    if a.render:
        sys.path.insert(0, os.path.join(os.path.expanduser('~'), 'gta2-linux', 'gen3d'))
        import render_glb
        import nvdiffrast.torch as dr
        ctx = dr.RasterizeCudaContext()
        meshes = render_glb.load(a.out)
        tiles = [render_glb.render(meshes, v, 512, ctx) for v in ('3q', 'top', 'side', 'front')]
        Image.fromarray(np.concatenate(tiles, 1)).save(a.render)


if __name__ == '__main__':
    main()
