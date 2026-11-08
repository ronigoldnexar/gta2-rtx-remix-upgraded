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


def drop_debris(mesh, log, max_share=0.02, margin=0.0):
    """TRELLIS leaves small floating pieces next to the body (a stray mirror, a fleck of
    background): drop connected pieces with < 2 % of the faces whose centre lies outside the
    main body's bounding box (wheels and trim sit inside it and are kept)."""
    try:
        # connectivity by position: the UV seams split the textured mesh into many islands
        geo = trimesh.Trimesh(mesh.vertices.copy(), mesh.faces.copy(), process=False)
        geo.merge_vertices(merge_tex=True, merge_norm=True)
        comp = trimesh.graph.connected_component_labels(geo.face_adjacency, node_count=len(geo.faces))
    except Exception:  # noqa
        return mesh
    counts = np.bincount(comp)
    if len(counts) < 2:
        return mesh
    # the body: the biggest pieces that together hold 90 % of the faces
    order = np.argsort(-counts)
    body = order[:int(np.searchsorted(np.cumsum(counts[order]), 0.9 * len(mesh.faces))) + 1]
    mv = mesh.vertices[np.unique(mesh.faces[np.isin(comp, body)])]
    lo, hi = mv.min(0), mv.max(0); pad = (hi - lo) * margin
    keep = np.ones(len(mesh.faces), bool)
    dropped = 0
    for c in np.where(counts < max_share * len(mesh.faces))[0]:
        if c in body:
            continue
        sel = comp == c
        centre = mesh.vertices[np.unique(mesh.faces[sel])].mean(0)
        if np.any(centre < lo - pad) or np.any(centre > hi + pad):
            keep[sel] = False; dropped += int(sel.sum())
    if dropped:
        mesh.update_faces(keep); mesh.remove_unreferenced_vertices()
        log(f"dropped {dropped} faces of floating debris outside the body")
    return mesh


def balance_sides(mesh, tex, log, min_diff=0.12):
    """Image-to-3D sees one side of the car; the hidden side comes out darker and duller (a
    baked shadow). Cars are left/right symmetric, so the dark side's low-frequency colour is
    pulled to its mirror image on the lit side: per face, a smoothed colour on each side, the
    gain = mirror / own (per channel, clamped), interpolated per vertex and applied in texture
    space. Only the low frequencies move: the hidden side keeps its own detail and lettering
    (nothing is mirrored)."""
    import torch
    import nvdiffrast.torch as dr
    from scipy.spatial import cKDTree
    if tex is None or mesh.visual.uv is None:
        return tex
    arr = np.asarray(tex.convert('RGBA'), np.float32) / 255
    H, W = arr.shape[:2]
    uv = np.asarray(mesh.visual.uv)
    f = mesh.faces
    # per-face colour: mean of 4 samples (centroid + 3 towards the corners)
    cols = []
    for w in ((1/3, 1/3, 1/3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)):
        c = (uv[f] * np.array(w)[None, :, None]).sum(1)
        x = np.clip((c[:, 0] * (W - 1)).astype(int), 0, W - 1); y = np.clip(((1 - c[:, 1]) * (H - 1)).astype(int), 0, H - 1)
        cols.append(arr[y, x, :3])
    col = np.mean(cols, 0)
    cen = mesh.triangles_center; n = mesh.face_normals; area = mesh.area_faces
    L = col @ np.array([0.2126, 0.7152, 0.0722])
    def side_mean(sel):
        return float((L[sel] * area[sel]).sum() / max(area[sel].sum(), 1e-9))
    left, right = side_mean(n[:, 0] < -0.5), side_mean(n[:, 0] > 0.5)
    diff = abs(left - right) / max(left, right, 1e-3)
    if diff < min_diff:
        log(f"sides balanced already (left {left:.2f} right {right:.2f})")
        return tex
    dark = -1.0 if left < right else 1.0          # sign of x on the dark side
    # smooth the face colours over the surface (k nearest face centres, area weighted)
    tree = cKDTree(cen)
    ext = np.linalg.norm(mesh.vertices.max(0) - mesh.vertices.min(0))
    k = min(24, len(cen))
    d, idx = tree.query(cen, k)
    wts = area[idx] * np.exp(-(d / (0.04 * ext)) ** 2)
    smooth = (col[idx] * wts[..., None]).sum(1) / np.maximum(wts.sum(1), 1e-9)[:, None]
    mirror = cen * np.array([-1.0, 1.0, 1.0])
    _, mi = tree.query(mirror, 1)
    gain = smooth[mi] / np.maximum(smooth, 0.03)
    gain = np.clip(gain, 0.8, 3.0)
    # only on the dark side, faded in from the centre plane so there is no seam
    xw = mesh.vertices[:, 0].max() - mesh.vertices[:, 0].min()
    ramp = np.clip((cen[:, 0] * dark) / (0.15 * xw), 0, 1)
    gain = 1.0 + (gain - 1.0) * ramp[:, None]
    # per-vertex gain (by position, across UV seams), interpolated in texture space
    key = np.round(mesh.vertices / (ext * 1e-4)).astype(np.int64)
    _, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(-1)
    acc = np.zeros((vid.max() + 1, 3)); cnt = np.zeros(vid.max() + 1)
    for j in range(3):
        np.add.at(acc, vid[f[:, j]], gain * area[:, None]); np.add.at(cnt, vid[f[:, j]], area)
    vg = (acc / np.maximum(cnt, 1e-12)[:, None])[vid].astype(np.float32)
    ctx = dr.RasterizeCudaContext()
    uvt = torch.tensor(uv, dtype=torch.float32, device='cuda')
    clip = torch.stack([uvt[:, 0] * 2 - 1, (1 - uvt[:, 1]) * 2 - 1, torch.zeros_like(uvt[:, 0]), torch.ones_like(uvt[:, 0])], 1)
    ft = torch.tensor(f, dtype=torch.int32, device='cuda')
    rast, _ = dr.rasterize(ctx, clip[None], ft, (H, W))
    g, _ = dr.interpolate(torch.tensor(vg, device='cuda')[None], rast, ft)
    hit = (rast[0, ..., 3] > 0).cpu().numpy()
    g = g[0].cpu().numpy()
    g[~hit] = 1.0
    # texels outside every triangle (padding) take the nearest gain: dilate a few times
    for _ in range(4):
        m = ~hit
        if not m.any():
            break
        nb = np.maximum(np.roll(g, 1, 0), np.roll(g, -1, 0))
        g[m] = nb[m]
    out = arr.copy()
    out[..., :3] = np.clip(arr[..., :3] * g, 0, 1)
    after = np.mean(cols, 0)
    log(f"sides: left {left:.2f} right {right:.2f} ({diff*100:.0f} % apart): the {'left' if dark < 0 else 'right'} side lifted, "
        f"mean gain {float(np.mean(gain[ramp > 0.5], 0).mean()) if (ramp > 0.5).any() else 1.0:.2f}")
    return Image.fromarray((out * 255).astype(np.uint8))


def _face_colours(mesh, arr):
    """Per-face texture colour: mean of 4 samples (centroid + 3 towards the corners)."""
    H, W = arr.shape[:2]
    uv = np.asarray(mesh.visual.uv); f = mesh.faces
    cols = []
    for w in ((1/3, 1/3, 1/3), (0.6, 0.2, 0.2), (0.2, 0.6, 0.2), (0.2, 0.2, 0.6)):
        c = (uv[f] * np.array(w)[None, :, None]).sum(1)
        x = np.clip((c[:, 0] * (W - 1)).astype(int), 0, W - 1); y = np.clip(((1 - c[:, 1]) * (H - 1)).astype(int), 0, H - 1)
        cols.append(arr[y, x, :3])
    return np.mean(cols, 0)


def _apply_face_gain(mesh, arr, gain, soft=False):
    """Multiply the texture by a per-face gain (N x 3), averaged per vertex by position (across UV
    seams) and interpolated in texture space, so the change is smooth over the surface."""
    import torch
    import nvdiffrast.torch as dr
    H, W = arr.shape[:2]
    uv = np.asarray(mesh.visual.uv); f = mesh.faces; area = mesh.area_faces
    ext = np.linalg.norm(mesh.vertices.max(0) - mesh.vertices.min(0))
    key = np.round(mesh.vertices / (ext * 1e-4)).astype(np.int64)
    _, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(-1)
    acc = np.zeros((vid.max() + 1, 3)); cnt = np.zeros(vid.max() + 1)
    for j in range(3):
        np.add.at(acc, vid[f[:, j]], gain * area[:, None]); np.add.at(cnt, vid[f[:, j]], area)
    vg = (acc / np.maximum(cnt, 1e-12)[:, None])[vid].astype(np.float32)
    ctx = dr.RasterizeCudaContext()
    uvt = torch.tensor(uv, dtype=torch.float32, device='cuda')
    clip = torch.stack([uvt[:, 0] * 2 - 1, (1 - uvt[:, 1]) * 2 - 1, torch.zeros_like(uvt[:, 0]), torch.ones_like(uvt[:, 0])], 1)
    ft = torch.tensor(f, dtype=torch.int32, device='cuda')
    rast, _ = dr.rasterize(ctx, clip[None], ft, (H, W))
    g, _ = dr.interpolate(torch.tensor(vg, device='cuda')[None], rast, ft)
    hit = (rast[0, ..., 3] > 0).cpu().numpy()
    g = g[0].cpu().numpy()
    g[~hit] = 1.0
    for _ in range(4):
        m = ~hit
        if not m.any():
            break
        nb = np.maximum(np.roll(g, 1, 0), np.roll(g, -1, 0))
        g[m] = nb[m]
    out = arr.copy()
    x = arr[..., :3]
    if soft:     # a lift (g > 1) as x*g / (1 + (g-1)*x): dark paint rises ~g times, light paint and chrome never clip
        out[..., :3] = np.where(g > 1, x * g / (1 + (g - 1) * x), x * g)
    else:
        out[..., :3] = np.clip(x * g, 0, 1)
    return out


def balance_vertical(mesh, tex, log, min_diff=0.08):
    """The concept is lit from above: hood, roof and trunk come out brighter than the flanks (a
    bright roof over dark sides). Paint faces = faces whose chromaticity is close to the flanks'
    dominant paint colour; the median luminance of the upward-facing paint faces is brought to the
    flank paint level by a smooth gain over the face normal's height (tops scaled by
    sqrt(g), flanks lifted softly by 1/sqrt(g)). Only a function of the normal, so liveries keep their own contrast."""
    if tex is None or mesh.visual.uv is None:
        return tex
    arr = np.asarray(tex.convert('RGBA'), np.float32) / 255
    col = _face_colours(mesh, arr)
    n = mesh.face_normals; area = mesh.area_faces; cen = mesh.triangles_center
    L = col @ np.array([0.2126, 0.7152, 0.0722])
    y0, y1 = mesh.vertices[:, 1].min(), mesh.vertices[:, 1].max()
    yf = (cen[:, 1] - y0) / max(y1 - y0, 1e-6)
    side = (np.abs(n[:, 0]) > 0.6) & (yf > 0.18) & (yf < 0.6) & (L > 0.08)
    top = (n[:, 1] > 0.7) & (L > 0.08)
    if area[side].sum() < 0.03 * area.sum() or area[top].sum() < 0.03 * area.sum():
        log("vertical balance: too few side/top faces"); return tex
    chrom = col / np.maximum(col.sum(1, keepdims=True), 1e-3)
    # the flanks' dominant paint: area-weighted 2D chromaticity histogram peak
    hb = 24
    ci = np.clip((chrom[:, :2] * hb).astype(int), 0, hb - 1)
    hist = np.zeros((hb, hb)); np.add.at(hist, (ci[side, 0], ci[side, 1]), area[side])
    pk = np.unravel_index(np.argmax(hist), hist.shape)
    paint = chrom[side][(ci[side, 0] == pk[0]) & (ci[side, 1] == pk[1])].mean(0)
    near = np.abs(chrom - paint).max(1) < 0.035
    sp, tp = side & near, top & near
    if area[sp].sum() < 0.02 * area.sum() or area[tp].sum() < 0.02 * area.sum():
        log("vertical balance: the top shows little of the flank paint (two-tone or livery), left"); return tex
    def wmed(sel):
        o = np.argsort(L[sel]); c = np.cumsum(area[sel][o]); return float(L[sel][o][np.searchsorted(c, 0.5 * c[-1])])
    ls, lt = wmed(sp), wmed(tp)
    g = ls / max(lt, 1e-3)
    if abs(1 - g) < min_diff:
        log(f"vertical balance: top {lt:.2f} flanks {ls:.2f}, balanced already"); return tex
    g = float(np.clip(g, 0.62, 1.0))
    gt, gs = g ** 0.5, g ** -0.5      # meet in the middle; the flank lift is soft (no clipping, see _apply_face_gain)
    w = np.clip((n[:, 1] - 0.25) / 0.5, 0, 1)
    gain = (gs * (1 - w) + gt * w)[:, None].repeat(3, 1)
    out = _apply_face_gain(mesh, arr, gain, soft=True)
    log(f"vertical balance: top paint {lt:.2f} vs flanks {ls:.2f}: tops x{gt:.2f}, flanks x{gs:.2f}")
    return Image.fromarray((out * 255).astype(np.uint8))


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


def orient(mesh, tex, car, log, nose='auto'):
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
    #    The catalog's window rows are cy - offset (offset positive toward the nose), so
    #    cy - mean(rows) is the cabin's offset toward the nose in sprite pixels, whichever
    #    end the sprite draws the nose at.
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
    flip = abs(cabin_sprite) > 0.03 and abs(cabin_mesh) > 0.02 and (cabin_sprite > 0) != (cabin_mesh > 0)
    if nose == 'flip':
        flip = True
    elif nose == 'keep':
        flip = False
    if flip:
        mesh.apply_transform(rot_y(math.pi))
        log("turned nose to +z" + ("" if nose == 'auto' else f" ({nose})"))
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


def paint_from_above(mesh, tex, sprite, car, log, paint_rgb=(190, 160, 120), min_ny=0.3, full_ny=0.75, livery=False, paint_match=True, roof_from=0.0, roof_norm=False):
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
    # World x (right) -> sprite column; world z (nose +z) -> sprite row. GTA2 draws its car
    # sprites nose-down (the front is the bottom of the sprite: cab-forward trucks, the
    # pickup's bed and the tow truck's boom all sit at the top), so +z grows the row.
    u = cx + p[..., 0] / body_w * (car['body_px'][0] * scale)
    vrow = cy + p[..., 2] / body_l * (car['body_px'][1] * scale)
    ui = u.clamp(0, sw - 1).long(); vi = vrow.clamp(0, sh - 1).long()
    col = sprite_t[vi, ui]
    cover = alpha_t[vi, ui]
    wgt = ((n[..., 1] - min_ny) / (full_ny - min_ny)).clamp(0, 1)
    wgt = wgt * cover * hit.float()
    if roof_from > 0:
        # Only the cabin roof takes the sprite: the hood and trunk keep the concept's crisp paint
        # (the x4 sprite is soft and carries its own drawn highlights, which read as smears there).
        ymin, ymax = float(mesh.vertices[:, 1].min()), float(mesh.vertices[:, 1].max())
        yf_ = (p[..., 1] - ymin) / max(ymax - ymin, 1e-6)
        wgt = wgt * ((yf_ - roof_from) / 0.05).clamp(0, 1)
    base = torch.tensor(np.asarray(tex, np.float32)[..., :3] / 255, device='cuda')
    # Match the concept's body paint to the sprite's: the median colour of the texels the
    # sprite is about to cover (the concept's roof/hood) against the sprite's own paint there.
    sel = wgt > 0.9
    if paint_match and sel.sum() > 100:
        concept_paint = base[sel].median(dim=0).values
        # Target: the catalog's paint colour for this remap (the sprite's own top-down shading
        # would make it too dark); keep the shift mostly a brightness change so chrome and
        # glass are not tinted.
        sprite_paint = torch.tensor(np.array(paint_rgb, np.float32) / 255, device='cuda')
        ratio = (sprite_paint / concept_paint.clamp(min=0.05)).clamp(0.5, 2.0)
        ratio = ratio.mean() + (ratio - ratio.mean()).clamp(-0.2, 0.2)
        ratio = ratio.clamp(0.8, 1.25)       # a nudge, not a repaint: a big dimming makes clean paint look dull and worn
        base = (base * ratio).clamp(0, 1)
        log(f"paint match ratio {ratio.cpu().numpy().round(2).tolist()}")
    if roof_from > 0 and roof_norm and (wgt > 0.5).sum() > 100:
        # The x4 sprite is drawn bright (lit from above): a roof much lighter than the flanks. Bring the
        # sprite's roof to the body's own paint level: liveries keep the sprite's colours, scaled so
        # their median brightness is the concept roof's; plain cars take the body paint of the top surfaces (hood,
        # trunk, roof after the vertical balance) with
        # the sprite's brightness pattern (sunroof, stripes, vinyl lines) on top of it.
        Ls = 0.2126 * col[..., 0] + 0.7152 * col[..., 1] + 0.0722 * col[..., 2]
        Lb = 0.2126 * base[..., 0] + 0.7152 * base[..., 1] + 0.0722 * base[..., 2]
        rsel = wgt > 0.5
        ymin_, ymax_ = float(mesh.vertices[:, 1].min()), float(mesh.vertices[:, 1].max())
        yfb = (p[..., 1] - ymin_) / max(ymax_ - ymin_, 1e-6)
        ssel = hit & ((1.0 - n[..., 1].abs()) > 0.7) & (yfb > 0.18) & (yfb < 0.6) & (Lb > 0.1)
        lroof = Ls[rsel].median()
        if livery or not paint_match or ssel.sum() < 200:
            ref = Lb[rsel].median()
            gain_r = (ref / lroof.clamp(min=0.03)).clamp(0.6, 1.15)
            col = (col * gain_r).clamp(0, 1)
            log(f"roof sprite brightness x{float(gain_r):.2f} (to the concept roof)")
        else:
            tsel = hit & (n[..., 1] > 0.7) & (Lb > 0.06)
            body = base[tsel] if tsel.sum() > 200 else base[ssel]
            bl = 0.2126 * body[:, 0] + 0.7152 * body[:, 1] + 0.0722 * body[:, 2]
            lo_, hi_ = bl.quantile(0.25), bl.quantile(0.8)
            pk = body[(bl >= lo_) & (bl <= hi_)].median(dim=0).values       # the hood/trunk/roof paint (balanced), not trim or glare
            lpk = float(0.2126 * pk[0] + 0.7152 * pk[1] + 0.0722 * pk[2])
            if float(lroof) > 1.1 * lpk:
                rel = (Ls / lroof.clamp(min=0.03)).clamp(0.35, 1.08)   # the sprite's drawn highlights do not come along
                col = (pk[None, None, :] * rel[..., None]).clamp(0, 1)
                log(f"roof sprite recoloured to the body paint {(pk.cpu().numpy() * 255).round().astype(int).tolist()} (sprite roof lum {float(lroof):.2f} > paint {lpk:.2f})")
            else:      # a dark (vinyl/two-tone) sprite roof is part of the design: kept
                log(f"roof sprite kept (sprite roof lum {float(lroof):.2f} <= paint {lpk:.2f})")
    out = base * (1 - wgt[..., None]) + col * wgt[..., None]
    if livery:
        # Side livery: the sprite's colour profile along the length (one colour per row,
        # the median of the body's non-dark texels) painted onto the side-facing texels
        # below the window line, so police/taxi/van stripes run along the flanks the way
        # the top-down art has them. Glass (upper band) and the bumpers (ends) are left.
        spn = rgb.copy(); lum = 0.2126 * spn[..., 0] + 0.7152 * spn[..., 1] + 0.0722 * spn[..., 2]
        body_mask = (a > 0.5) & (lum > 0.22)
        rowcol = np.zeros((sh, 3), np.float32); rowok = np.zeros(sh, bool)
        for r_ in range(sh):
            sel = body_mask[r_]
            if sel.sum() >= 3:
                rowcol[r_] = np.median(spn[r_][sel], axis=0); rowok[r_] = True
        # fill rows without body from neighbours
        idx = np.where(rowok)[0]
        if len(idx):
            for r_ in range(sh):
                if not rowok[r_]:
                    j = idx[np.argmin(np.abs(idx - r_))]; rowcol[r_] = rowcol[j]
        rowcol_t = torch.tensor(rowcol, device='cuda')
        side_col = rowcol_t[vi]
        hy = p[..., 1]
        ymin, ymax = float(mesh.vertices[:, 1].min()), float(mesh.vertices[:, 1].max())
        yf = (hy - ymin) / max(ymax - ymin, 1e-6)
        horiz = (1.0 - n[..., 1].abs()).clamp(0, 1)
        sidew = ((horiz - 0.6) / 0.3).clamp(0, 1)                 # side-facing
        sidew = sidew * ((0.62 - yf) / 0.08).clamp(0, 1)           # below the window line
        sidew = sidew * ((yf - 0.12) / 0.08).clamp(0, 1)           # above the sills/tyres
        zf = (p[..., 2] / body_l + 0.5).clamp(0, 1)
        sidew = sidew * ((zf - 0.06) / 0.04).clamp(0, 1) * ((0.94 - zf) / 0.04).clamp(0, 1)   # not the bumpers
        sidew = sidew * hit.float() * 0.85
        # keep the texture's own shading detail: use its luminance relative to its local mean
        out = out * (1 - sidew[..., None]) + side_col * sidew[..., None]
        log(f"side livery covers {float((sidew > 0.4).float().mean())*100:.1f}% of the texture")
    # Dilate the painted result a little so bilinear sampling at seams does not pull the old colour.
    img = (out.clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
    painted = float((wgt > 0.5).float().mean())
    log(f"roof paint covers {painted*100:.1f}% of the texture")
    res = Image.fromarray(img).convert('RGBA')
    return res


def light_bar(mesh, sprite, car, log):
    """A small light bar on the roof for emergency cars: found from the sprite's red/blue
    roof pixels; two coloured domes on a dark base, placed on the roof surface."""
    sp = np.asarray(sprite.convert('RGBA'), np.float32) / 255
    sh, sw = sp.shape[:2]
    rgb, a = sp[..., :3], sp[..., 3]
    red = (a > 0.5) & (rgb[..., 0] > 0.55) & (rgb[..., 1] < 0.35) & (rgb[..., 2] < 0.35)
    blue = (a > 0.5) & (rgb[..., 2] > 0.55) & (rgb[..., 0] < 0.35) & (rgb[..., 1] < 0.5)
    lit = red | blue
    # Only the cabin roof: between the sprite's window rows and the middle half of the width.
    scale = sw / car['sprite_px'][0]
    cx, cy = sw / 2.0, sh / 2.0
    body_w, body_l = car['body_px'][0] / 64.0, car['body_px'][1] / 64.0
    win = car.get('windows_px') or {}
    r0 = min(win.get('front_y', 0), win.get('rear_y', sh / scale)) * scale
    r1 = max(win.get('front_y', 0), win.get('rear_y', sh / scale)) * scale
    roof = np.zeros_like(lit)
    c0, c1 = int(cx - car['body_px'][0] * scale * 0.3), int(cx + car['body_px'][0] * scale * 0.3)
    roof[int(max(r0, 0)):int(min(r1, sh)), max(c0, 0):min(c1, sw)] = True
    lit = lit & roof
    if lit.sum() < 12:
        return None
    ys, xs = np.where(lit)
    # keep the densest cluster: trim outliers beyond 1.5 median absolute deviations
    for _ in range(2):
        my, mx = np.median(ys), np.median(xs)
        keep = (np.abs(ys - my) < 1.5 * max(np.median(np.abs(ys - my)), 2) + 2) & (np.abs(xs - mx) < 1.5 * max(np.median(np.abs(xs - mx)), 2) + 2)
        ys, xs = ys[keep], xs[keep]
    if len(xs) < 8:
        return None
    x_b = (xs.mean() - cx) / (car['body_px'][0] * scale) * body_w
    z_b = (ys.mean() - cy) / (car['body_px'][1] * scale) * body_l
    w_b = (xs.max() - xs.min() + 2) / (car['body_px'][0] * scale) * body_w
    l_b = (ys.max() - ys.min() + 2) / (car['body_px'][1] * scale) * body_l
    w_b = float(np.clip(w_b, 0.25 * body_w, 0.6 * body_w)); l_b = float(np.clip(l_b, 0.04 * body_l, 0.10 * body_l))
    # roof height under the bar: the highest vertex within the bar's footprint
    v = mesh.vertices
    near = (np.abs(v[:, 0] - x_b) < max(w_b, 0.06)) & (np.abs(v[:, 2] - z_b) < max(l_b, 0.06))
    roof_y = float(v[near, 1].max()) if near.any() else float(v[:, 1].max())
    h = 0.018
    parts = []
    def coloured(geom, rgba, name, metallic=0.3, roughness=0.5, emissive=None):
        mat = trimesh.visual.material.PBRMaterial(baseColorFactor=[c / 255.0 for c in rgba], metallicFactor=metallic,
                                                  roughnessFactor=roughness, name=name)
        if emissive is not None:
            mat.emissiveFactor = emissive
        geom.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(geom.vertices), 2)), material=mat)
        return geom
    base = trimesh.creation.box(extents=(w_b, h, l_b)); base.apply_translation((x_b, roof_y + h / 2, z_b))
    parts.append(coloured(base, (40, 40, 45, 255), 'lightbar_base', 0.6, 0.4))
    dome_r = min(w_b * 0.22, l_b * 0.45)
    for k, (dx, colr, nm) in enumerate(((-w_b * 0.28, (230, 30, 30, 255), 'lightbar_red'), (w_b * 0.28, (40, 70, 240, 255), 'lightbar_blue'))):
        d = trimesh.creation.icosphere(subdivisions=1, radius=dome_r)
        d.apply_scale((1.0, 0.7, 1.0)); d.apply_translation((x_b + dx, roof_y + h + dome_r * 0.5, z_b))
        parts.append(coloured(d, colr, nm, 0.0, 0.25, emissive=[c / 255.0 * 0.6 for c in colr[:3]]))
    bar = parts
    log(f"light bar at x={x_b:+.3f} z={z_b:+.3f} roof y={roof_y:.3f} size {w_b:.3f} x {l_b:.3f} ({int(lit.sum())} lit px)")
    return bar


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
    ap.add_argument('--nose', default='auto', choices=['auto', 'keep', 'flip'], help='override the nose test')
    ap.add_argument('--metallic', type=float, default=0.55); ap.add_argument('--roughness', type=float, default=0.38)
    ap.add_argument('--delight', action='store_true', help='remove the baked concept lighting from the texture before painting')
    ap.add_argument('--livery', action='store_true'); ap.add_argument('--no-livery', action='store_true')
    ap.add_argument('--lightbar', action='store_true', help='add a roof light bar found from the sprite (emergency cars)')
    ap.add_argument('--balance-sides', action='store_true', help="lift the hidden (darker) side's colour to its mirror side's")
    ap.add_argument('--roof-only', type=float, default=0.0, metavar='YF',
                    help='project the sprite only above this fraction of the height (0.8: the cabin roof; 0: every upward face)')
    ap.add_argument('--balance-vertical', action='store_true', help='bring the lit top (hood, roof, trunk) to the flank paint level')
    ap.add_argument('--roof-norm', action='store_true', help='with --roof-only: the sprite roof at the body paint level/colour, not its own bright drawn shade')
    ap.add_argument('--no-paint-match', action='store_true', help='keep the concept paint (liveries: the concept already has the right colours)')
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
    mesh = drop_debris(mesh, log)
    orient(mesh, tex, car, log, a.nose)
    fit(mesh, car, log)
    mesh = decimate(mesh, a.faces)
    mesh.fix_normals()
    if a.delight and tex is not None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import delight_texture as dt
        arr = np.asarray(tex.convert('RGBA'), np.float32) / 255
        before = (dt.highlight_fraction(arr[..., :3]), dt.shading_variance(arr[..., :3]))
        out = dt.delight(arr[..., :3])
        after = (dt.highlight_fraction(out), dt.shading_variance(out))
        tex = Image.fromarray((np.concatenate([out, arr[..., 3:]], -1) * 255).astype(np.uint8))
        log(f"delight: highlights {before[0]*100:.2f}% -> {after[0]*100:.2f}%, shading var {before[1]:.4f} -> {after[1]:.4f}")
    if a.balance_sides and tex is not None:
        for _ in range(2):          # a second pass when the first one hit the gain clamp
            tex = balance_sides(mesh, tex, log)
    if a.balance_vertical and tex is not None:
        tex = balance_vertical(mesh, tex, log)
    sprite_img = Image.open(sprite_path)
    if not a.no_paint:
        tex = paint_from_above(mesh, tex, sprite_img, car, log, paint_rgb=car['remaps'][0]['paint_rgb'],
                               livery=bool(a.livery and not a.no_livery), paint_match=not a.no_paint_match, roof_from=a.roof_only,
                               roof_norm=a.roof_norm)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=tex, metallicFactor=a.metallic, roughnessFactor=a.roughness,
                                              name=f"car_{a.model:03d}")
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.asarray(mesh.visual.uv), material=mat)
    mesh.metadata['gta2_model'] = a.model
    extra = []
    if a.lightbar or (a.livery and car['cls'] in ('police', 'emergency')):
        bar = light_bar(mesh, sprite_img, car, log)
        if bar is not None:
            extra.extend(bar)
    if extra:
        scene = trimesh.Scene()
        scene.add_geometry(mesh, node_name='body', geom_name='body')
        for i, g in enumerate(extra):
            scene.add_geometry(g, node_name=f'lightbar{i}', geom_name=f'lightbar{i}')
        scene.export(a.out)
    else:
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
        tiles = [render_glb.render(meshes, v, 512, ctx) for v in ('3q', 'top', 'side', 'front', '3qr')]   # 3qr: the far side
        Image.fromarray(np.concatenate(tiles, 1)).save(a.render)


if __name__ == '__main__':
    main()
