#!/usr/bin/env python3
"""VEHICLE-ART-20: find holes in car meshes offline.

Car bodies draw with no culling (dll/src/car_bodies.cpp), so a gap in the shell shows the INSIDE of the far wall:
a pixel whose nearest face is seen from its back. This renders every car .mesh from an orbit of poses (1-3 blocks,
eye height to chase height), counts back-facing pixels per pose (glass and wheel-hub textures excluded, the
underside never looked at) and writes a sheet per flagged model with the back-face pixels in magenta.

  python hole_scan.py <models dir> <out dir> [model stem ...]
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_io
from preview import _persp, _look

SKIP_TEX = ("glass", "light", "lamp", "chrome_disc")


def load(path):
    m = mesh_io.read(path)
    V, F, T, UV = [], [], [], []
    off = 0
    NN = []
    for n, me, P, N, uv, Fi in mesh_io.world(m):
        V.append(P); F.append(Fi + off); T += [me["tex"]] * len(Fi); UV.append(uv); NN.append(N); off += len(P)
    load.normals = np.vstack(NN).astype(np.float32)
    return np.vstack(V).astype(np.float32), np.vstack(F).astype(np.int32), T, np.vstack(UV).astype(np.float32)


_acache = {}


def alpha_of(mdir, tex):
    """The alpha the two alpha-tested draws leave: max of the texture's and its _paint twin's (car_bodies.cpp)."""
    if tex in _acache:
        return _acache[tex]
    def rd(n):
        p = os.path.join(mdir, n)
        if not os.path.exists(p):
            return None
        im = Image.open(p)
        return np.asarray(im.convert("RGBA"))[..., 3].astype(np.float32) / 255.0 if im.mode in ("RGBA", "LA", "P") else None
    a = rd(tex)
    twin = tex.replace("_paint.tga", ".tga") if tex.endswith("_paint.tga") else tex[:-4] + "_paint.tga"
    out = None
    if a is not None:
        out = [a]
        if tex.endswith(".tga") and os.path.exists(os.path.join(mdir, twin)):
            b = rd(twin)
            if b is None:
                out = None
            elif b.shape == a.shape:
                out.append(b)
    _acache[tex] = out
    return out


def bilinear(a, u, v):
    h, w = a.shape
    x = (u % 1.0) * w - 0.5; y = (v % 1.0) * h - 0.5
    x0 = np.floor(x).astype(int); y0 = np.floor(y).astype(int); fx = x - x0; fy = y - y0
    x0c, x1c = np.clip(x0, 0, w - 1), np.clip(x0 + 1, 0, w - 1); y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    return (a[y0c, x0c] * (1 - fx) * (1 - fy) + a[y0c, x1c] * fx * (1 - fy) + a[y1c, x0c] * (1 - fx) * fy + a[y1c, x1c] * fx * fy)


def scan(path, glctx, size=(480, 320)):
    import torch, nvdiffrast.torch as dr
    V, F, T, UVn = load(path)
    mdir = os.path.dirname(path)
    texs = sorted(set(T)); tix = np.array([texs.index(t) for t in T])
    alph = [alpha_of(mdir, t) for t in texs]
    lo, hi = V.min(0), V.max(0); c = (lo + hi) / 2; ext = hi - lo
    L = max(ext[0], ext[2]); Hh = ext[1]
    skip = np.array([any(k in t.lower() for k in SKIP_TEX) for t in T])
    dev = "cuda"
    Vt = torch.tensor(V, device=dev); Ft = torch.tensor(F, device=dev); UVt = torch.tensor(UVn, device=dev); Nt = torch.tensor(load.normals, device=dev)
    mode = os.environ.get("HOLE_MODE", "normal")
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    cen = V[F].mean(1)
    res = []
    W, H = size
    for el in (0.45, 1.0, 1.9):          # eye height of a figure beside it .. chase height, in car heights
        for az in range(0, 360, 30):
            for dist in (0.75, 1.3):      # in car lengths from the centre
                a = math.radians(az)
                eye = c + np.array([math.sin(a) * L * dist, -ext[1] / 2 + Hh * el + 0.0, math.cos(a) * L * dist])
                P = _persp(55, W / H, n=0.01 * L); M = _look(eye, c)
                MVP = torch.tensor(P @ M, device=dev)
                clip = torch.cat([Vt, torch.ones_like(Vt[:, :1])], 1) @ MVP.T
                rast, _ = dr.rasterize(glctx, clip[None].contiguous(), Ft, resolution=[H, W])
                tri = (rast[0, ..., 3].long() - 1).cpu().numpy()
                cov = tri >= 0
                t = np.clip(tri, 0, None)
                uvp = dr.interpolate(UVt[None], rast, Ft)[0][0].cpu().numpy()
                back = np.zeros_like(cov)
                if mode == "normal":
                    nrm = dr.interpolate(Nt[None], rast, Ft)[0][0].cpu().numpy()
                    pos = dr.interpolate(Vt[None], rast, Ft)[0][0].cpu().numpy()
                    vd = pos - eye; vd /= np.maximum(np.linalg.norm(vd, axis=-1, keepdims=True), 1e-9)
                    nn = nrm / np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-9)
                    back = cov & ((nn * vd).sum(-1) > 0.25) & ~skip[t]
                    alph = [None] * len(alph)
                ti = tix[t]
                for k, a in enumerate(alph):
                    if a is None: continue
                    sel = cov & (ti == k) & ~skip[t]
                    if not sel.any(): continue
                    u = uvp[..., 0][sel]; v = uvp[..., 1][sel]
                    fail = np.ones(len(u), bool)
                    for half in a:
                        fail &= bilinear(half, u, v) < 0.5
                    bb = back[sel]; bb |= fail; back[sel] = bb
                res.append(dict(az=az, el=el, dist=dist, cov=int(cov.sum()), back=int(back.sum()),
                                frac=float(back.sum()) / max(1, int(cov.sum())), mask=(cov, back)))
    return res, (L, Hh)


def main():
    import torch, nvdiffrast.torch as dr
    mdir, odir = sys.argv[1], sys.argv[2]
    os.makedirs(odir, exist_ok=True)
    man = json.load(open(os.path.join(mdir, "manifest.json")))
    stems = sorted(set(man["cars"]["by_model"].values()))
    if len(sys.argv) > 3:
        stems = sys.argv[3:]
    glctx = dr.RasterizeCudaContext(device="cuda")
    rows = []
    for s in stems:
        p = os.path.join(mdir, s + ".mesh")
        if not os.path.exists(p):
            print(s, "no mesh"); continue
        r, _ = scan(p, glctx)
        worst = sorted(r, key=lambda x: -x["frac"])
        rows.append((s, worst[0]["frac"], float(np.mean([x["frac"] for x in r]))))
        print(f"{s:28s} max {worst[0]['frac']*100:5.2f} %  mean {rows[-1][2]*100:5.2f} %  (az {worst[0]['az']} el {worst[0]['el']} d {worst[0]['dist']})", flush=True)
        tiles = []
        for x in worst[:6]:
            cov, back = x["mask"]
            im = np.full(cov.shape + (3,), 235, np.uint8)
            im[cov] = (90, 90, 90); im[back] = (255, 0, 255)
            ti = Image.fromarray(im[::-1])
            ImageDraw.Draw(ti).text((4, 4), f"az {x['az']} el {x['el']} d {x['dist']}  {x['frac']*100:.1f}%", fill=(0, 0, 0))
            tiles.append(ti)
        S = Image.new("RGB", (tiles[0].width * 3, tiles[0].height * 2 + 16), (30, 30, 30))
        for i, ti in enumerate(tiles):
            S.paste(ti, ((i % 3) * ti.width, 16 + (i // 3) * ti.height))
        ImageDraw.Draw(S).text((4, 2), s, fill=(255, 255, 255))
        S.save(os.path.join(odir, s + ".png"))
    with open(os.path.join(odir, "scan.tsv"), "w") as f:
        for s, mx, mn in sorted(rows, key=lambda x: -x[1]):
            f.write(f"{s}\t{mx*100:.2f}\t{mn*100:.2f}\n")


if __name__ == "__main__":
    main()
