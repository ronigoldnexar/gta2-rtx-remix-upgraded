#!/usr/bin/env python3
"""Score a game-ready car GLB for visual quality, so the worst models can be
ranked and regenerated first. Geometry-only metrics need numpy + trimesh; the
top-view IoU against the sprite uses the mesh's own footprint, no renderer.

    score_car_model.py --catalog assets-src/cars/catalog.json <glb> [<glb> ...] [--json out.json]

Metrics, each 0 (bad) .. 1 (good):
  symmetry   left/right mirror distance of the silhouette about the long (z) axis
  smooth     1 - (share of edges with a dihedral angle > 60 deg, outside wheel arches)
  lumps      1 - share of vertices whose local height deviates > 8 % of the body height from a smoothed roof line
  wheels     wheel-well positions along z vs the CARI axle rows (0.5 per axle found within 12 % of the length)
  top_iou    footprint of the mesh seen from above vs the sprite alpha
  texture    sharpness (Laplacian variance) and background-free (share of texels near the SDXL grey background)
  lighting   no baked light: specular blobs and shading over the bilateral paint level, left/right flank balance
  aspect     the body height is plausible for the class (sedan 0.30-0.42 of the length etc.)
Total = mean of the metrics. Models under 0.55 are candidates for regeneration.
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


def lumps(mesh, n=32):
    """Roof line: the max height per z-slice should vary smoothly along the car."""
    v = mesh.vertices
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
    k = np.array([1, 2, 3, 2, 1], float) / 9
    sm = np.convolve(t, k, mode='same')
    sm[:2] = t[:2]; sm[-2:] = t[-2:]
    dev = np.abs(t - sm) / h
    return float(max(0.0, 1.0 - 4.0 * float((dev > 0.08).mean())))


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


def texture_score(tex):
    if tex is None:
        return 0.3
    im = tex.resize((512, 512), Image.BILINEAR)
    g = np.array(im.convert('L'), float)
    lap = (np.abs(4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]))
    sharp = min(1.0, lap.var() / 400.0)
    rgb = np.array(im, float)
    near_bg = (np.abs(rgb - BG).max(axis=2) < 14).mean()
    return float(0.6 * sharp + 0.4 * max(0.0, 1.0 - 3.0 * near_bg))


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
        'symmetry': symmetry(mesh), 'smooth': smoothness(mesh), 'lumps': lumps(mesh),
        'wheels': wheels(mesh, car), 'top_iou': top_iou(mesh, sprite, car), 'texture': texture_score(tex), 'lighting': lighting_score(tex, mesh),
        'aspect': aspect(mesh, car),
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
              ' '.join(f"{k[:4]} {m.get(k, 0):.2f}" for k in ('symmetry', 'smooth', 'lumps', 'wheels', 'top_iou', 'texture', 'lighting', 'aspect')))
    rows.sort(key=lambda r: r['total'])
    if a.json:
        json.dump(rows, open(a.json, 'w'), indent=1)
    print('\nworst 25:', [r['model'] for r in rows[:25]])


if __name__ == '__main__':
    main()
