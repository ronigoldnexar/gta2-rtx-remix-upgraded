#!/usr/bin/env python3
"""PEDS-VARIETY-3: garment detail baked into a zoned avatar's clothing textures, tint-safe, as variant models.

    garment_detail.py <models dir> <out dir> <avatar>:<variant>[,<variant>...] ...   [--manifest <manifest.json>]

variants (suffix): yoke (_dy)   the shoulder yoke a darker tone of the shirt colour, a fine off-white piping on its edge
                   sleeve (_ds) two-tone long sleeves: the forearms a darker tone below the elbow plane, an off-white stripe
                   cuff (_ds)   hoodies: a darker cuff only, no stripe (shares the sleeve slot)
                   band (_db)   hoodies, tracksuits, zip jackets: a narrow chest band a darker tone, graphite piping
A tone change stays in the paint half (greyscale x k: the outfit's colour, darker); a fixed neutral moves the texel to
the rest half (never tinted). Each variant is <avatar><suffix>.mesh, a copy whose body and body_paint references
name the variant's two maps and that carries no clips (the DLL plays the avatar's: Model::animOwner); the head and
hair maps stay the avatar's own (one texture in memory). With --manifest,
the variants' "models" and "imported" entries are added (copies of the avatar's, renamed). The DLL deals them
(identity.cpp CrowdVariety: DetailPick). Positions come from the bind pose, measured per avatar."""
import sys, os, json, struct, numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh
from paint_resplit import read_tga, write_tga
SUFFIX = {'yoke': '_dy', 'sleeve': '_ds', 'cuff': '_ds', 'band': '_db'}

def maps(M, name):
    mesh = gmsh.load(M + name + '.mesh')
    nb = {n['mesh']: n['name'] for n in mesh['nodes'] if n['mesh'] >= 0}
    paint_tex = [me['tex'] for i, me in enumerate(mesh['meshes']) if nb.get(i, '').endswith('#pt')][0]
    paint = read_tga(M + paint_tex).astype(np.float32); rest = read_tga(M + paint_tex.replace('_paint', '')).astype(np.float32)
    H, W = paint.shape[:2]
    pos = np.zeros((H, W, 3), np.float32); zone = np.zeros((H, W), np.uint8); bone = np.zeros((H, W), np.int32) - 1
    for i, me in enumerate(mesh['meshes']):
        nm = nb.get(i, ''); zv = 1 if nm.endswith('#pt') else 2 if nm.endswith('#pb') else 0
        if not zv or me['tex'] != paint_tex: continue
        P = me['v'][:, :3]; UV = me['v'][:, 6:8] * np.array([W, H])
        jn = mesh['skins'][me['skin']][0] if me['skin'] >= 0 else None
        dom = np.array([jn[me['J'][v][np.argmax(me['W'][v])]] for v in range(len(P))]) if jn else np.full(len(P), -1)
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
            bone[y0 + ys, x0 + xs] = dom[t][np.argmax(np.stack([l1, l2, l3]), 0)[ys, xs]]
    return mesh, paint_tex, paint, rest, pos, zone, bone

def detail(mesh, paint, rest, pos, zone, bone, variant):
    paint = paint.copy(); rest = rest.copy()
    names = [n['name'] for n in mesh['nodes']]
    top = (zone == 1) & (paint[..., 3] >= 128); tp = pos[top]
    up, lat = 2, 0                                                   # mesh space: z up, x lateral
    is_arm = np.vectorize(lambda b: b >= 0 and any(k in names[b] for k in ('UpperArm', 'Forearm', 'Hand')))(bone)
    neck_y = tp[np.abs(tp[:, lat]) < 0.06][:, up].max(); u = tp[:, up].max() - tp[:, up].min()
    torso_x = np.percentile(np.abs(tp[~is_arm[top]][:, lat]), 98)
    X = np.abs(pos[..., lat]); Y = pos[..., up]
    torso = top & ~is_arm; sleeve = top & is_arm
    def tone(m, k): paint[m, :3] = np.clip(paint[m, :3] * k, 0, 255)
    def fixed(m, rgb):
        lum = paint[m, 0] / 128.0
        rest[m, :3] = np.clip(np.array(rgb)[None] * lum[:, None], 0, 255); rest[m, 3] = 255; paint[m, 3] = 0
    if variant == 'yoke':
        line = neck_y - 0.17 * u; near = ~is_arm | (X < torso_x + 0.06 * u)
        tone(top & (Y > line) & near, 0.55)
        fixed(top & (np.abs(Y - line) < 0.006 * u) & near, (226, 224, 216))
    elif variant == 'band':
        c = neck_y - 0.30 * u; hw = 0.021 * u                        # 60% of the first prototype's width
        tone(torso & (np.abs(Y - c) < hw), 0.50)
        fixed(torso & (np.abs(np.abs(Y - c) - hw - 0.005 * u) < 0.004 * u), (52, 54, 60))
    elif variant in ('sleeve', 'cuff'):
        jn, ibm = mesh['skins'][0]
        bind = {names[j]: np.linalg.inv(ibm[k].T)[:3, 3] for k, j in enumerate(jn)}   # inverse bind matrices: column-major
        fore = np.zeros_like(top); ring = np.zeros_like(top)
        for side in ('L', 'R'):
            e = bind.get(f'Bip01 {side} Forearm'); h = bind.get(f'Bip01 {side} Hand')
            if e is None or h is None: continue
            ax = (h - e) / np.linalg.norm(h - e); L = np.linalg.norm(h - e)
            t = (pos - e) @ ax
            near = np.linalg.norm(pos - e - t[..., None] * ax, axis=-1) < 0.6 * L
            start = 0.05 * L if variant == 'sleeve' else 0.70 * L        # a hoodie: the last stretch above the wrist only
            fore |= sleeve & near & (t > start)
            if variant == 'sleeve': ring |= sleeve & near & (np.abs(t - start) < 0.035 * L)
        tone(fore, 0.52)
        if variant == 'sleeve': fixed(ring, (226, 224, 216))
    return paint, rest

def strip_clips(d):
    """The GMSH bytes without the animation block (header count 0): a variant plays its avatar's clips."""
    d = bytearray(d); o = 4
    ver, nn, nm, na, ns = struct.unpack_from('<5I', d, o); o += 20
    o += nn * 80
    for _ in range(nm):
        nv, ni = struct.unpack_from('<II', d, o); o += 8 + 64
        skin, = struct.unpack_from('<i', d, o); o += 4
        o += nv * 32 + (nv * 24 if skin >= 0 else 0) + ni * 4
    a0 = o
    for _ in range(na):
        o += 32; nc, = struct.unpack_from('<I', d, o); o += 4
        for _ in range(nc):
            node, path, k = struct.unpack_from('<iII', d, o); o += 12
            o += 4 * k + 4 * k * (4 if path == 1 else 3)
    struct.pack_into('<I', d, 4 + 12, 0)
    return bytes(d[:a0] + d[o:])

def write_variant(M, out, name, variant, mesh_bytes, paint_tex, paint, rest):
    suf = SUFFIX[variant]; vname = name + suf
    rest_tex = paint_tex.replace('_paint', '')
    new_paint, new_rest = paint_tex.replace(name + '_', vname + '_', 1), rest_tex.replace(name + '_', vname + '_', 1)
    b = bytearray(mesh_bytes)
    for old, new in ((paint_tex, new_paint), (rest_tex, new_rest)):   # the 64-byte texture fields
        o = old.encode().ljust(64, b'\0'); n = new.encode().ljust(64, b'\0'); assert len(n) == 64
        k = 0; hits = 0
        while (k := b.find(o, k)) >= 0: b[k:k + 64] = n; k += 64; hits += 1
        assert hits, (name, old)
    open(os.path.join(out, vname + '.mesh'), 'wb').write(strip_clips(b))
    write_tga(paint.astype(np.uint8), os.path.join(out, new_paint)); write_tga(rest.astype(np.uint8), os.path.join(out, new_rest))
    return vname, new_rest, new_paint

if __name__ == '__main__':
    args = [a for a in sys.argv[1:]]
    man_path = None
    if '--manifest' in args: i = args.index('--manifest'); man_path = args[i + 1]; del args[i:i + 2]
    M, out, specs = args[0].rstrip('/') + '/', args[1], args[2:]
    os.makedirs(out, exist_ok=True)
    made = []
    for spec in specs:
        name, vs = spec.split(':')
        mesh, paint_tex, paint, rest, pos, zone, bone = maps(M, name)
        raw = open(M + name + '.mesh', 'rb').read()
        for v in vs.split(','):
            p2, r2 = detail(mesh, paint, rest, pos, zone, bone, v)
            vname, nr, npt = write_variant(M, out, name, v, raw, paint_tex, p2, r2)
            made.append((name, vname, paint_tex, nr, npt)); print('wrote', vname, v)
    if man_path:
        m = json.load(open(man_path)); raw_m = open(man_path).read()
        by = {e['name']: e for e in m['models']}; rep = {e['name']: e for e in m['imported']}
        for name, vname, paint_tex, nr, npt in made:
            e = json.loads(json.dumps(by[name])); e['name'] = vname; e['detail_of'] = name
            m['models'] = [x for x in m['models'] if x['name'] != vname] + [e]
            r = json.loads(json.dumps(rep[name])); r['name'] = vname
            r['textures'] = [nr if t == paint_tex.replace('_paint', '') else npt if t == paint_tex else t for t in r.get('textures', [])]
            m['imported'] = [x for x in m['imported'] if x['name'] != vname] + [r]
        open(man_path, 'w').write(json.dumps(m, indent=1))
        print('manifest:', len(made), 'variant entries')
