#!/usr/bin/env python3
"""Score a game-ready car GLB for visual quality, so the worst models can be
ranked and regenerated first. Geometry-only metrics need numpy + trimesh; the
top-view IoU against the sprite uses the mesh's own footprint, no renderer.

    score_car_model.py --catalog assets-src/cars/catalog.json <glb> [<glb> ...] [--json out.json]

Metrics, each 0 (bad) .. 1 (good):
  symmetry   left/right mirror distance of the silhouette about the long (z) axis
  smooth     1 - (share of edges with a dihedral angle > 60 deg, outside wheel arches)
  lumps      1 - share of z-slices whose top deviates > 8 % of the body height from the reference roof line:
             a smoothed curve for cars, a step-preserving running median for trucks, vans, buses, pickups,
             tanks and other boxy bodies (a cab with a taller box behind it is the vehicle's own profile),
             and on models whose sprite carries a roof item (gun, turret, rack, sign, ladder) a raised
             item above the reference is not a lump
  wheels     wheel-well positions along z vs the CARI axle rows (0.5 per axle found within 12 % of the length)
  top_iou    footprint of the mesh seen from above vs the sprite alpha
  texture    sharpness (Laplacian variance) and background-free (share of texels near the SDXL grey background
             that are not the model's own flank paint, so light grey and cream paint is neutral)
  smear      flat paint: band-pass and low-frequency luma/chroma variation of the lower flank panels
             (texture sampled through the UVs onto a side-view grid, paint texels only) against the same
             measure on the sprite's paint; the worn, smeared v1 look scores low
  lighting   no baked light: specular blobs and shading over the bilateral paint level, left/right flank balance
  aspect     the body height is plausible for the class (sedan 0.30-0.42 of the length etc.)
Total = mean of the metrics (9 since round 6; scores from before 8 Nov 2026 used 8, without smear). Models under 0.55 are candidates for regeneration.
"""
import argparse, json, math, os, sys
import numpy as np
import trimesh
from PIL import Image, ImageFilter

BG = np.array([200, 200, 200], float)   # the concept renders' plain light grey
HEIGHT_RATIO = {  # body height / length, plausible band per class
    'sedan': (0.26, 0.45), 'coupe': (0.24, 0.42), 'sports': (0.20, 0.40), 'limo': (0.22, 0.38), 'van': (0.35, 0.70),
    'pickup': (0.30, 0.55), 'truck': (0.35, 0.80), 'bus': (0.30, 0.60), 'police': (0.26, 0.45), 'taxi': (0.26, 0.45),
    'emergency': (0.30, 0.70), 'bike': (0.30, 0.70), 'special': (0.20, 0.90),
}


# Body types whose roof line is not a smooth sedan curve (round 6): classes, plus per-model entries
BOXY_CLASSES = {'van', 'pickup', 'truck', 'bus', 'emergency', 'special', 'offroad', 'trailer', 'train', 'wreck'}
BOXY_MODELS = {52, 67, 68, 69}                      # SWAT van (police class), TV van, van, U-Jerk
OPEN_TOP_MODELS = {22, 30, 31, 39, 45, 53}          # jeeps and roadsters: a windscreen frame over an open cockpit
ROOF_ITEM_MODELS = {3, 12, 17, 22, 23, 27, 34, 38, 52, 54, 58, 63, 64, 67, 84}  # turret, light bars, ladder, gun, signs, rack, boom, stacks, dish


def body_type(car):
    """'boxy' (step-preserving roof reference) or 'car' (smooth roof curve); roof_items: raised items allowed."""
    m = car.get('model', -1)
    boxy = car.get('cls') in BOXY_CLASSES or m in BOXY_MODELS or m in OPEN_TOP_MODELS
    return ('boxy' if boxy else 'car'), m in ROOF_ITEM_MODELS or m in OPEN_TOP_MODELS


def load_mesh(path):
    scene = trimesh.load(path, force='scene')
    parts = []
    for node in scene.graph.nodes_geometry:
        T, gname = scene.graph[node]
        g = scene.geometry[gname]
        if isinstance(g, trimesh.Trimesh):
            g = g.copy(); g.apply_transform(T); parts.append(g)
    if not parts:
        raise RuntimeError('no mesh in ' + path)
    parts.sort(key=lambda m: -len(m.faces))
    mesh = parts[0]          # the body; light bars and other small parts are not scored
    tex = None
    for p in parts:
        vis = p.visual
        mat = getattr(vis, 'material', None)
        if mat is not None:
            im = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
            if im is not None:
                tex = im.convert('RGB'); break
    return mesh, tex


def symmetry(mesh, n=48):
    """Compare the width profile at the left and right of the long axis, slice by slice."""
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    cx = (lo[0] + hi[0]) / 2
    zs = np.linspace(lo[2], hi[2], n + 1)
    diffs = []
    for i in range(n):
        sel = v[(v[:, 2] >= zs[i]) & (v[:, 2] < zs[i + 1])]
        if len(sel) < 4:
            continue
        left = cx - sel[:, 0].min(); right = sel[:, 0].max() - cx
        w = max(left + right, 1e-6)
        diffs.append(abs(left - right) / w)
    if not diffs:
        return 0.0
    return float(max(0.0, 1.0 - 2.5 * np.mean(diffs)))


def smoothness(mesh):
    try:
        m = mesh.copy(); m.merge_vertices(); ang = m.face_adjacency_angles
    except Exception:
        return 0.5
    if len(ang) == 0:
        return 0.5
    sharp = float((ang > math.radians(60)).mean())
    return float(max(0.0, 1.0 - 3.0 * sharp))


def lumps(mesh, n=32, car=None):
    """Roof line: the max height per z-slice against the vehicle's own reference profile.
    Cars: a smoothed curve (a lump is a TRELLIS blob or a dent). Boxy bodies: a running median (5 slices),
    which keeps steps such as cab -> taller box, so only isolated spikes and dips count. Models with a
    roof item: tops above the reference (a gun, rack, sign, ladder) are not counted, dips still are.
    The tops come from points sampled over the surface, not the vertices: a decimated flat box roof is a
    few large triangles with no vertex in most slices, which read as deep dips (box truck 0.12 before)."""
    pts, _ = trimesh.sample.sample_surface(mesh, 60000, seed=0)
    v = np.concatenate([mesh.vertices, pts])
    lo, hi = v.min(0), v.max(0)
    h = max(hi[1] - lo[1], 1e-6)
    zs = np.linspace(lo[2], hi[2], n + 1)
    tops = []
    for i in range(n):
        sel = v[(v[:, 2] >= zs[i]) & (v[:, 2] < zs[i + 1])]
        tops.append(sel[:, 1].max() if len(sel) else np.nan)
    tops = np.array(tops)
    ok = ~np.isnan(tops)
    if ok.sum() < 6:
        return 0.5
    t = tops[ok]
    kind, items = body_type(car or {})
    if kind == 'boxy':
        tp = np.pad(t, 2, mode='edge')
        ref = np.array([np.median(tp[i:i + 5]) for i in range(len(t))])
    else:
        k = np.array([1, 2, 3, 2, 1], float) / 9
        ref = np.convolve(t, k, mode='same')
        ref[:2] = t[:2]; ref[-2:] = t[-2:]
    d = (t - ref) / h
    if items:
        d = np.minimum(d, 0.0)          # raised roof items are part of the vehicle
    return float(max(0.0, 1.0 - 4.0 * float((np.abs(d) > 0.08).mean())))


def wheels(mesh, car):
    """Find the two lowest-point clusters along z (wheels touch y=0) and compare with the CARI axle rows."""
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    length = max(hi[2] - lo[2], 1e-6)
    low = v[v[:, 1] < lo[1] + 0.06 * max(hi[1] - lo[1], 1e-6)]
    if len(low) < 8:
        return 0.0
    # axle rows from CARI: offsets from the sprite centre in px, nose = larger row = +z
    w = car.get('wheels_px') or {}
    body_len_px = car['body_px'][1]
    axles = []
    for key in ('front_offset', 'rear_offset'):
        if key in w:
            axles.append(w[key] / body_len_px)   # fraction of the length from the centre
    if not axles:
        return 0.5
    zc = (lo[2] + hi[2]) / 2
    hist, edges = np.histogram(low[:, 2], bins=24, range=(lo[2], hi[2]))
    peaks = [i for i in range(1, 23) if hist[i] >= hist[i - 1] and hist[i] >= hist[i + 1] and hist[i] > 0.05 * hist.sum()]
    centres = [(edges[i] + edges[i + 1]) / 2 for i in peaks]
    score = 0.0
    for a in axles:
        target = zc + a * length
        if any(abs(c - target) < 0.12 * length for c in centres):
            score += 0.5
    return score


def top_iou(mesh, sprite_path, car):
    """Footprint mask from the mesh vertices (projected to x,z) vs the sprite's alpha."""
    if not sprite_path or not os.path.exists(sprite_path):
        return 0.5
    sp = Image.open(sprite_path).convert('RGBA')
    a = np.array(sp)[:, :, 3] > 64
    # crop the sprite alpha to its bounding box and resample to the mesh grid
    ys, xs = np.where(a)
    if len(xs) == 0:
        return 0.5
    a = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    n = 64
    sa = np.array(Image.fromarray((a * 255).astype(np.uint8)).resize((n, n), Image.BILINEAR)) > 127
    # mesh footprint: rasterise triangles' xz projection coarsely by sampling face centroids and vertices
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    pts = np.concatenate([v, mesh.triangles_center])
    gx = np.clip(((pts[:, 0] - lo[0]) / max(hi[0] - lo[0], 1e-6) * (n - 1)).astype(int), 0, n - 1)
    gz = np.clip(((pts[:, 2] - lo[2]) / max(hi[2] - lo[2], 1e-6) * (n - 1)).astype(int), 0, n - 1)
    fm = np.zeros((n, n), bool)
    fm[(n - 1 - gz), gx] = True          # sprite rows run top=tail(-z) .. bottom=nose(+z): larger z = larger row
    fm = np.array(Image.fromarray((fm * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 127
    inter = (fm & sa).sum(); union = (fm | sa).sum()
    return float(inter / max(union, 1))


def flank_paint(mesh, tex):
    """The model's own flank paint (RGB 0-255): median texel colour of the side-facing faces in the
    lower body band, or None."""
    if tex is None or getattr(mesh.visual, 'uv', None) is None:
        return None
    a = np.asarray(tex.convert('RGB'), np.float32)
    c = np.asarray(mesh.visual.uv)[mesh.faces].mean(1)
    x = np.clip((c[:, 0] * (a.shape[1] - 1)).astype(int), 0, a.shape[1] - 1)
    y = np.clip(((1 - c[:, 1]) * (a.shape[0] - 1)).astype(int), 0, a.shape[0] - 1)
    v = mesh.vertices; lo, hi = v.min(0), v.max(0); hgt = max(hi[1] - lo[1], 1e-6)
    cy = (mesh.triangles_center[:, 1] - lo[1]) / hgt
    sel = (np.abs(mesh.face_normals[:, 0]) > 0.6) & (cy > 0.2) & (cy < 0.6)
    if sel.sum() < 10:
        return None
    col = a[y[sel], x[sel]]
    L = col.mean(1); keep = L > 25                     # not the tyres / dark window glass
    return np.median(col[keep] if keep.sum() > 10 else col, 0)


def texture_score(tex, mesh=None):
    if tex is None:
        return 0.3
    im = tex.resize((512, 512), Image.BILINEAR)
    g = np.array(im.convert('L'), float)
    lap = (np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]))
    sharp = min(1.0, lap.var() / 400.0)
    rgb = np.array(im, float)
    near = np.abs(rgb - BG).max(axis=2) < 14
    paint = flank_paint(mesh, tex) if mesh is not None else None
    if paint is not None:
        # light grey / cream paint is the car's own colour, not the concept background: texels near the
        # flank paint are not counted (round 6; it used to penalise every light-grey car)
        near &= np.abs(rgb - paint).max(axis=2) >= 24
    near_bg = near.mean()
    return float(0.6 * sharp + 0.4 * max(0.0, 1.0 - 3.0 * near_bg))


def _opp(rgb):
    """Lightness (L*/100, perceptually even, so dark paint is not over-weighted) and two opponent
    chroma channels (0-1 RGB in)."""
    Y = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    Ls = np.where(Y > 0.008856, 1.16 * np.cbrt(np.maximum(Y, 1e-6)) - 0.16, 9.033 * Y)
    s = np.maximum(rgb.sum(-1), 0.15)
    return Ls, (rgb[..., 0] - rgb[..., 1]) / s, (rgb[..., 0] + rgb[..., 1] - 2 * rgb[..., 2]) / (2 * s)


def _mottle(img, mask, fine=1.0, coarse=6.0, edge=0.10):
    """Paint unevenness over a masked image (H x W x 3, 0-1): band-pass std of lightness (blotches, smears
    a few cells wide), low-pass std (broad stains, dark/light patches) and chroma std (colour smears).
    Measured inside the regions bounded by sharp edges (livery panels, a two-tone cab and box, trim): a
    crisp colour change is design, a soft one is a smear."""
    from scipy import ndimage
    if mask.sum() < 40:
        return None
    Ls, ca, cb = _opp(img)
    w0 = mask.astype(np.float32)
    def nc(a, s, w):
        return ndimage.gaussian_filter(a * w, s) / np.maximum(ndimage.gaussian_filter(w, s), 1e-4)
    f, fa, fb = nc(Ls, fine, w0), nc(ca, fine, w0), nc(cb, fine, w0)
    g = np.hypot(*np.gradient(f)) + 0.5 * (np.hypot(*np.gradient(fa)) + np.hypot(*np.gradient(fb)))
    inner = mask & (g < edge)
    lab, n = ndimage.label(inner)
    acc = np.zeros(3); tot = 0
    for k in range(1, n + 1):
        r = lab == k
        if r.sum() < 30:
            continue
        w = r.astype(np.float32)
        c = nc(f, coarse, w)
        band = np.std((f - c)[r]); low = np.std(c[r])
        chroma = np.hypot(np.std(fa[r]), np.std(fb[r]))
        acc += r.sum() * np.array([band, low, chroma]); tot += r.sum()
    if tot < 30:
        return None
    busy = 1.0 - inner.sum() / max(mask.sum(), 1)      # share of the panel that is edges: scratches, streaks
    return tuple(float(x) for x in acc / tot) + (float(busy),)


def _paint_mask(img, valid):
    """Cells of the dominant paint: chroma near the chromaticity-histogram peak of the not-dark cells,
    lightness within a broad band of the paint's (smears stay in, tyres, glass and chrome trim drop out)."""
    Ls, ca, cb = _opp(img)
    base = valid & (Ls > 0.15)
    if base.sum() < 40:
        return base
    H, xe, ye = np.histogram2d(ca[base], cb[base], bins=20, range=[[-0.4, 0.4], [-0.4, 0.4]])
    i, j = np.unravel_index(np.argmax(H), H.shape)
    pa, pb = (xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2
    near = base & (np.hypot(ca - pa, cb - pb) < 0.08)
    Lm = np.median(Ls[near]) if near.sum() > 20 else np.median(Ls[base])
    return valid & (np.hypot(ca - pa, cb - pb) < 0.10) & (np.abs(Ls - Lm) < 0.35) & (Ls > 0.12)


def _view_grids(mesh, tex, nz=320, ny=128, count=800000):
    """The albedo without lighting seen from the left, the right and above: the surface sampled
    (area-weighted), each point's texel looked up through the UVs, a z-buffer per grid cell keeps the
    point nearest the viewer; cells whose surface faces away (< 0.35) are not valid. Side grids keep the
    lower flank panels only (12-58 % of the height, below the windows)."""
    a = np.asarray(tex.convert('RGB'), np.float32) / 255
    uv = np.asarray(mesh.visual.uv)
    v = mesh.vertices; lo, hi = v.min(0), v.max(0); ext = np.maximum(hi - lo, 1e-6)
    pts, fi = trimesh.sample.sample_surface(mesh, count, seed=0)
    bary = trimesh.triangles.points_to_barycentric(mesh.triangles[fi], pts)
    U = np.einsum('nc,ncd->nd', bary, uv[mesh.faces[fi]])
    tx = np.clip((U[:, 0] % 1.0) * (a.shape[1] - 1), 0, a.shape[1] - 1).astype(int)
    ty = np.clip((1 - U[:, 1] % 1.0) * (a.shape[0] - 1), 0, a.shape[0] - 1).astype(int)
    col = a[ty, tx]; N = mesh.face_normals[fi]
    gz = np.clip(((pts[:, 2] - lo[2]) / ext[2] * (nz - 1)).round().astype(int), 0, nz - 1)
    out = {}
    for name, ax, side, ax2 in (('left', 0, -1, 1), ('right', 0, 1, 1), ('top', 1, 1, 0)):
        n2 = ny if name != 'top' else max(16, int(nz * ext[0] / ext[2]))
        g2 = np.clip(((pts[:, ax2] - lo[ax2]) / ext[ax2] * (n2 - 1)).round().astype(int), 0, n2 - 1)
        o = np.argsort(pts[:, ax] * side)                  # nearest the viewer written last wins
        img = np.zeros((n2, nz, 3), np.float32); fac = np.zeros((n2, nz), bool); hit = np.zeros((n2, nz), bool)
        img[g2[o], gz[o]] = col[o]; fac[g2[o], gz[o]] = N[o, ax] * side > 0.35; hit[g2[o], gz[o]] = True
        valid = hit & fac
        if name != 'top':
            valid[:int(0.12 * n2)] = False; valid[int(0.58 * n2):] = False
        out[name] = (img, valid)
    return out


def sprite_mottle(sprite_path, nz=320):
    """The same measure on the game sprite's paint (top view, resized to the grids' length)."""
    if not sprite_path or not os.path.exists(sprite_path):
        return None
    sp = np.asarray(Image.open(sprite_path).convert('RGBA'), np.float32) / 255
    ys, xs = np.where(sp[..., 3] > 0.5)
    if len(xs) == 0:
        return None
    sp = sp[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = nz / sp.shape[0]
    im = Image.fromarray((sp * 255).astype(np.uint8)).resize((max(8, int(sp.shape[1] * s)), nz), Image.BILINEAR)
    sp = np.asarray(im, np.float32) / 255
    rgb, valid = sp[..., :3], sp[..., 3] > 0.5
    r = _mottle(rgb, _paint_mask(rgb, valid), fine=1.5, coarse=10.0, edge=0.06)
    return r[:3] if r else None


SMEAR_BASE = (0.035, 0.035, 0.03)     # band, low, chroma a clean model reaches (8 Nov 2026 calibration)
SMEAR_SCALE = (0.04, 0.08, 0.08)


def smear_score(mesh, tex, sprite_path=None, detail=False):
    """1 = flat, clean paint; 0 = blotched / smeared / stained. On the lower flank panels (left, right) and
    the top surfaces (hood, roof, trunk), the paint region (dominant chroma, dark streaks inside it closed
    in) is split at crisp colour edges (liveries, two-tone, trim) and each part measured for soft variation:
    band-pass lightness (blotches), low-pass lightness (stains, light/dark patches) and chroma (colour
    smears). The excess over a clean model's level, or over the sprite's own paint variation where that is
    higher (its drawn shading, capped), is the penalty; one flank with far less paint than the other (a
    black or stained far side) adds to it."""
    from scipy import ndimage
    if tex is None or getattr(mesh.visual, 'uv', None) is None:
        return (0.5, {}) if detail else 0.5
    feats = {}; cov = []
    for name, (img, valid) in _view_grids(mesh, tex).items():
        pm = _paint_mask(img, valid)
        pm = ndimage.binary_fill_holes(ndimage.binary_closing(pm, structure=np.ones((5, 5)))) & valid
        if name != 'top':
            cov.append(pm.sum() / max(valid.sum(), 1))
        r = _mottle(img, pm, fine=1.5, coarse=10.0, edge=0.06)
        if r is not None:
            feats[name] = r[:3]
    if not feats:
        return (0.3, {}) if detail else 0.3
    sm = sprite_mottle(sprite_path)
    ref = [max(b, min(x, 1.5 * b)) for b, x in zip(SMEAR_BASE, sm or SMEAR_BASE)]
    terms = []
    for name, f in feats.items():
        terms += [max(0.0, x - r_) / sc for x, r_, sc in zip(f, ref, SMEAR_SCALE)]
    side = 1.0 - min(cov) / max(max(cov), 1e-6) if len(cov) == 2 else 0.0
    ex = float(np.mean(terms)) + max(0.0, side - 0.25)
    sc = float(max(0.0, 1.0 - ex))
    if detail:
        return sc, dict(feats={k: [round(x, 4) for x in v] for k, v in feats.items()}, ref=[round(x, 4) for x in ref],
                        cover=[round(float(c), 3) for c in cov])
    return sc


def side_balance(mesh, tex):
    """1 = both flanks equally bright. Image-to-3D sees one side; the hidden side comes out in a
    baked shadow. Area-weighted texture luminance of the faces looking left vs right."""
    if tex is None or getattr(mesh.visual, 'uv', None) is None:
        return 0.5
    a = np.asarray(tex.convert('L'), np.float32) / 255
    c = np.asarray(mesh.visual.uv)[mesh.faces].mean(1)
    x = np.clip((c[:, 0] * (a.shape[1] - 1)).astype(int), 0, a.shape[1] - 1)
    y = np.clip(((1 - c[:, 1]) * (a.shape[0] - 1)).astype(int), 0, a.shape[0] - 1)
    L = a[y, x]; n = mesh.face_normals; ar = mesh.area_faces
    def m(sel):
        return float((L[sel] * ar[sel]).sum() / max(ar[sel].sum(), 1e-9))
    l, r = m(n[:, 0] < -0.5), m(n[:, 0] > 0.5)
    return float(max(0.0, 1.0 - (abs(l - r) / max(l, r, 1e-3)) / 0.4))


def lighting_score(tex, mesh=None):
    """1 = no baked lighting: few specular blobs, little low-frequency shading, both sides alike."""
    if tex is None:
        return 0.3
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import delight_texture as dt
    rgb = np.asarray(tex.resize((512, 512), Image.BILINEAR), np.float32) / 255
    hf = dt.highlight_fraction(rgb)          # blobs over the bilateral paint level: v1 models 0.03-0.8 %
    sv = dt.shading_variance(rgb)            # local vs regional bilateral low-pass: v1 models 0.0006-0.001
    terms = [max(0.0, 1.0 - hf / 0.006), max(0.0, 1.0 - sv / 0.0015)]
    if mesh is not None:
        terms.append(side_balance(mesh, tex))
    return float(np.mean(terms))


def aspect(mesh, car):
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    ratio = (hi[1] - lo[1]) / max(hi[2] - lo[2], 1e-6)
    band = HEIGHT_RATIO.get(car.get('cls', ''), (0.2, 0.8))
    if band[0] <= ratio <= band[1]:
        return 1.0
    d = (band[0] - ratio) if ratio < band[0] else (ratio - band[1])
    return float(max(0.0, 1.0 - d / 0.15))


def score(path, car, root):
    mesh, tex = load_mesh(path)
    sprite = os.path.join(root, car['remaps'][0]['file_x4']) if car.get('remaps') else None
    m = {
        'symmetry': symmetry(mesh), 'smooth': smoothness(mesh), 'lumps': lumps(mesh, car=car),
        'wheels': wheels(mesh, car), 'top_iou': top_iou(mesh, sprite, car), 'texture': texture_score(tex, mesh), 'lighting': lighting_score(tex, mesh),
        'aspect': aspect(mesh, car), 'smear': smear_score(mesh, tex, sprite),
    }
    m['total'] = float(np.mean(list(m.values())))
    m['faces'] = int(len(mesh.faces))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--catalog', required=True); ap.add_argument('glbs', nargs='+'); ap.add_argument('--json', default=None)
    a = ap.parse_args()
    cat = json.load(open(a.catalog)); root = os.path.dirname(os.path.abspath(a.catalog))
    cars = {c['model']: c for c in cat['cars']}
    rows = []
    for p in a.glbs:
        base = os.path.basename(p)
        try:
            model = int(base.split('_')[0])
        except ValueError:
            print('skip', p); continue
        car = cars.get(model)
        if car is None:
            continue
        try:
            m = score(p, car, root)
        except Exception as e:
            m = {'total': 0.0, 'error': str(e)[:80]}
        m['model'] = model; m['name'] = car['name']; m['cls'] = car['cls']; m['glb'] = p
        rows.append(m)
        print(f"{model:3d} {car['name'][:18]:18s} {car['cls'][:9]:9s} total {m['total']:.2f}  " +
              ' '.join(f"{k[:4]} {m.get(k, 0):.2f}" for k in ('symmetry', 'smooth', 'lumps', 'wheels', 'top_iou', 'texture', 'lighting', 'aspect', 'smear')))
    rows.sort(key=lambda r: r['total'])
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=1)
    print('\nworst 25:', [r['model'] for r in rows[:25]])


if __name__ == '__main__':
    main()
