#!/usr/bin/env python3
"""PEDS-VARIETY-3 prototype: garment detail baked into a zoned avatar's clothing textures, tint-safe.

    garment_detail.py <models dir> <model> <variant> <out dir>
variants: yoke   (shoulder yoke a darker tone of the shirt colour, a fine off-white piping on its edge)
          band   (a chest band in a fixed off-white, with graphite piping)
          sleeve (two-tone sleeves: the forearms a darker tone, an off-white cuff stripe)
A tone change stays in the paint half (greyscale x k: the outfit's colour, darker); a fixed neutral moves the
texel to the rest half (never tinted). Writes <out dir>/<model>.mesh (a copy) and its textures, the detail in the
body and body_paint maps. Positions come from the bind pose (T-pose), measured per avatar."""
import sys, os, shutil, glob, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh
from paint_resplit import read_tga, write_tga
M, name, variant, out = sys.argv[1].rstrip('/') + '/', sys.argv[2], sys.argv[3], sys.argv[4]
mesh = gmsh.load(M + name + '.mesh')
nodes_by_mesh = {n['mesh']: n['name'] for n in mesh['nodes'] if n['mesh'] >= 0}
paint_tex = [me['tex'] for i, me in enumerate(mesh['meshes']) if nodes_by_mesh.get(i, '').endswith('#pt')][0]
rest_tex = paint_tex.replace('_paint', '')
paint = read_tga(M + paint_tex).astype(np.float32); rest = read_tga(M + rest_tex).astype(np.float32)
H, W = paint.shape[:2]
# texel -> bind-pose position (mesh space: z up, x lateral, the arms out along x) and zone, by rasterising the zone meshes' triangles in UV space
pos = np.zeros((H, W, 3), np.float32); zone = np.zeros((H, W), np.uint8); bone = np.zeros((H, W), np.int32) - 1
for i, me in enumerate(mesh['meshes']):
    nm = nodes_by_mesh.get(i, '')
    zv = 1 if nm.endswith('#pt') else 2 if nm.endswith('#pb') else 0
    if not zv or me['tex'] != paint_tex: continue
    P = me['v'][:, :3]; UV = me['v'][:, 6:8] * np.array([W, H])
    if me['skin'] >= 0:
        jn = mesh['skins'][me['skin']][0]
        dom = np.array([jn[me['J'][v][np.argmax(me['W'][v])]] for v in range(len(P))])   # the vertex's main bone (node index)
    else: dom = np.full(len(P), -1)
    for k in range(0, len(me['idx']) - 2, 3):
        t = me['idx'][k:k + 3]; a, b, c = UV[t]
        x0, y0 = np.floor(np.minimum(np.minimum(a, b), c)).astype(int); x1, y1 = np.ceil(np.maximum(np.maximum(a, b), c)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0); x1, y1 = min(x1, W - 1), min(y1, H - 1)
        if x1 < x0 or y1 < y0: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-9: continue
        l1 = ((b[1] - c[1]) * (gx - c[0]) + (c[0] - b[0]) * (gy - c[1])) / den
        l2 = ((c[1] - a[1]) * (gx - c[0]) + (a[0] - c[0]) * (gy - c[1])) / den
        l3 = 1 - l1 - l2
        ins = (l1 >= -0.02) & (l2 >= -0.02) & (l3 >= -0.02)
        p = l1[..., None] * P[t[0]] + l2[..., None] * P[t[1]] + l3[..., None] * P[t[2]]
        ys, xs = np.nonzero(ins)
        pos[y0 + ys, x0 + xs] = p[ys, xs]; zone[y0 + ys, x0 + xs] = zv
        best = np.argmax(np.stack([l1, l2, l3]), 0)
        bone[y0 + ys, x0 + xs] = dom[t][best[ys, xs]]
top = (zone == 1) & (paint[..., 3] >= 128)
tp = pos[top]
# axes (mesh space): z up; x lateral (the arms out in the T-pose); measured on the top garment
up = 2; lat = 0
neck_y = tp[np.abs(tp[:, lat]) < 0.06][:, up].max()
height = tp[:, up].max() - tp[:, up].min()
names = [n['name'] for n in mesh['nodes']]
is_arm = np.vectorize(lambda b: b >= 0 and any(k in names[b] for k in ('UpperArm', 'Forearm', 'Hand')))(bone)
is_fore = np.vectorize(lambda b: b >= 0 and any(k in names[b] for k in ('Forearm', 'Hand')))(bone)
torso_x = np.percentile(np.abs(tp[~is_arm[top]][:, lat]), 98)
arm_max = np.abs(tp[:, lat]).max()
print('neck_y %.3f top height %.3f torso half-width %.3f arm reach %.3f' % (neck_y, height, torso_x, arm_max))
X = np.abs(pos[..., lat]); Y = pos[..., up]
torso = top & ~is_arm; sleeve = top & is_arm
def tone(m, k): paint[m, :3] = np.clip(paint[m, :3] * k, 0, 255)
def fixed(m, rgb):
    lum = paint[m, 0] / 128.0                                          # keep the cloth's shading
    rest[m, :3] = np.clip(np.array(rgb)[None] * lum[:, None], 0, 255); rest[m, 3] = 255; paint[m, 3] = 0
u = height
if variant == 'yoke':
    line = neck_y - 0.17 * u
    yoke = top & (Y > line) & (~is_arm | (X < torso_x + 0.06 * u))
    tone(yoke, 0.55)
    fixed(top & (np.abs(Y - line) < 0.006 * u) & (~is_arm | (X < torso_x + 0.06 * u)), (226, 224, 216))
elif variant == 'band':
    c = neck_y - 0.30 * u; hw = 0.035 * u
    fixed(torso & (np.abs(Y - c) < hw), (222, 220, 212))
    fixed(torso & (np.abs(np.abs(Y - c) - hw - 0.006 * u) < 0.005 * u), (52, 54, 60))
elif variant == 'sleeve':
    # the elbow plane (the inverse bind matrices are stored column-major): the forearm joint's bind position, the arm running toward the hand; a clean cut, not the
    # skin weights' ragged border
    jn, ibm = mesh['skins'][0]
    bind = {names[j]: np.linalg.inv(ibm[k].T)[:3, 3] for k, j in enumerate(jn)}
    fore = np.zeros_like(top); ring = np.zeros_like(top)
    for side in ('L', 'R'):
        e = bind.get(f'Bip01 {side} Forearm'); h = bind.get(f'Bip01 {side} Hand')
        if e is None or h is None: continue
        ax = (h - e) / np.linalg.norm(h - e); L = np.linalg.norm(h - e)
        t = (pos - e) @ ax
        near = np.linalg.norm(pos - e - t[..., None] * ax, axis=-1) < 0.6 * L      # this arm, not the other or the torso
        fore |= sleeve & near & (t > 0.05 * L)
        ring |= sleeve & near & (np.abs(t - 0.05 * L) < 0.035 * L)
    tone(fore, 0.52)
    fixed(ring, (226, 224, 216))
os.makedirs(out, exist_ok=True)
for f in glob.glob(M + name + '.mesh') + glob.glob(M + name + '_*.tga'): shutil.copy(f, out)
write_tga(paint.astype(np.uint8), os.path.join(out, paint_tex)); write_tga(rest.astype(np.uint8), os.path.join(out, rest_tex))
print('wrote', out, variant)
