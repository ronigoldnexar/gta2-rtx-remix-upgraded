#!/usr/bin/env python3
"""VEHICLE-ART-20: an offline replica of car_bodies.cpp BuildDoorSplit (exact cut, the box without the measured
top) over a shipped .mesh, for finding what the open door leaves on the body (teeth, voids) without a game run.
Car frame = the model's own (+z forward; the renderer's fit is close to a uniform scale for the kit bodies).

  door_split_sim.py <models dir> <stem> <zFront> <zRear> <side> <out.png> [--swing deg]
Renders the body with the door swung (default 70 deg about its front edge) from the side and 3/4, triangles coloured
by class: grey body, blue door, red = body triangles kept whole that reach into the door's box (the teeth suspects)."""
import os, sys, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mesh_io


def split(mdir, stem, zF, zR, side, roof=None):
    m = mesh_io.read(os.path.join(mdir, stem + ".mesh"))
    W = mesh_io.world(m)
    allV = np.vstack([w[2] for w in W])
    lo, hi = allV.min(0), allV.max(0)
    # the car frame: centred on the body's box in x/z, floor at its lowest point
    off = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    W = [(n, me, P - off, N, UV, F) for n, me, P, N, UV, F in W]
    lo, hi = lo - off, hi - off
    halfW = 0.5 * (hi[0] - lo[0])
    roof = roof if roof is not None else hi[1]
    boxTop = 0.95 * roof; mg = 0.015; sg = float(side)
    body, door, teeth = [], [], []   # (tri 3x3, tex, liner?)
    def inside(p):
        return sg * p[0] >= 0.5 * halfW - mg and p[1] >= 0.10 * roof - mg and p[1] <= boxTop + mg and zR - mg <= p[2] <= zF + mg
    def dist(pl, p):
        return [sg * p[0] - (0.5 * halfW - mg), p[1] - (0.10 * roof - mg), (boxTop + mg) - p[1], p[2] - (zR - mg), (zF + mg) - p[2]][pl]
    def clip(poly, pl, sign):
        out = []
        for i in range(len(poly)):
            A, B = poly[i], poly[(i + 1) % len(poly)]
            da, db = sign * dist(pl, A), sign * dist(pl, B)
            if da >= 0: out.append(A)
            if (da >= 0) != (db >= 0):
                k = da / (da - db); out.append(A + (B - A) * k)
            # (vertex attributes not needed for the picture)
        return out
    def emit(lst, poly, tex, tag):
        for i in range(1, len(poly) - 1):
            lst.append((np.array([poly[0], poly[i], poly[i + 1]]), tex, tag))
    for n, me, P, N, UV, F in W:
        tex = me["tex"]
        for f in F:
            q = P[f]; c = q.mean(0)
            nrm = np.cross(q[1] - q[0], q[2] - q[0]); nl = np.linalg.norm(nrm)
            lateral = nl > 1e-9 and abs(nrm[0]) / nl > 0.45
            outward = sg * N[f][:, 0].mean()
            ins = [inside(p) for p in q]
            centred = sg * c[0] > 0.5 * halfW and 0.10 * roof < c[1] < boxTop and zR < c[2] < zF
            sideFace = lateral or outward > 0.05
            crosses = sideFace and not all(ins) and (any(ins) or centred)
            isDoor = sideFace and (centred or crosses)
            liner = isDoor and outward < -0.3
            if liner and not crosses:
                continue
            if isDoor and not all(ins):
                poly = [p for p in q]
                for pl in range(5):
                    if len(poly) < 3: break
                    emit(body, clip(poly, pl, -1.0), tex, "cut")
                    poly = clip(poly, pl, 1.0)
                if not liner and len(poly) >= 3: emit(door, poly, tex, "door")
                continue
            if isDoor:
                door.append((q, tex, "door"))
            else:
                # kept whole on the body: does it reach into the box (a part of it over the opening)?
                reach = any(ins) or centred
                (teeth if reach else body).append((q, tex, "reach" if reach else "body"))
    return body, door, teeth, dict(halfW=halfW, roof=roof, lo=lo, hi=hi)


def render(groups, eye, tgt, size=(800, 450), fov=40):
    import torch, nvdiffrast.torch as dr
    from preview import _persp, _look
    glctx = dr.RasterizeCudaContext(device="cuda")
    V = np.vstack([g[0].reshape(-1, 3) for g in groups]).astype(np.float32)
    col = np.vstack([np.tile(g[1], (3, 1)) for g in groups]).astype(np.float32)
    F = np.arange(len(V), dtype=np.int32).reshape(-1, 3)
    W_, H = size
    MVP = torch.tensor(_persp(fov, W_ / H, n=0.01) @ _look(eye, tgt), device="cuda")
    Vt = torch.tensor(V, device="cuda"); Ft = torch.tensor(F, device="cuda"); Ct = torch.tensor(col, device="cuda")
    clip = torch.cat([Vt, torch.ones_like(Vt[:, :1])], 1) @ MVP.T
    rast, _ = dr.rasterize(glctx, clip[None].contiguous(), Ft, resolution=[H, W_])
    c, _ = dr.interpolate(Ct[None], rast, Ft)
    # flat shade by face normal
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]); fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    tri = rast[0, ..., 3].long() - 1
    shade = torch.tensor(0.55 + 0.45 * np.abs(fn @ np.array([0.3, 0.8, 0.5]) / np.linalg.norm([0.3, 0.8, 0.5])), dtype=torch.float32, device="cuda")
    s = torch.where(tri >= 0, shade[tri.clamp(min=0)], torch.zeros_like(tri, dtype=torch.float32))
    img = torch.where((tri >= 0)[..., None], c[0] * s[..., None], torch.tensor([0.85, 0.9, 1.0], device="cuda"))
    from PIL import Image
    return Image.fromarray((img.flip(0).clamp(0, 1).cpu().numpy() * 255).astype(np.uint8))


if __name__ == "__main__":
    from PIL import Image, ImageDraw
    mdir, stem, zF, zR, side, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5]), sys.argv[6]
    swing = float(sys.argv[sys.argv.index("--swing") + 1]) if "--swing" in sys.argv else 70.0
    body, door, teeth, info = split(mdir, stem, zF, zR, side)
    # swing the door about its front edge (x = side*halfW, z = zF), about +y
    a = math.radians(swing) * (-side)
    R = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    piv = np.array([side * info["halfW"], 0, zF])
    def cl(tex, tag):
        t = tex.lower()
        if "seal" in t: return (1.0, 0.9, 0.0) if tag != "door" else (0.0, 1.0, 0.2)
        if tag == "reach": return (1.0, 0.1, 0.1)
        if "interior" in t or "liner" in t or "seat" in t: return (0.25, 0.22, 0.2)
        if "glass" in t: return (0.4, 0.7, 0.8)
        if tag == "door": return (0.35, 0.45, 1.0)
        return (0.8, 0.8, 0.78)
    gs = [(q, cl(t, g)) for q, t, g in body] + [(q, cl(t, g)) for q, t, g in teeth] + [((q - piv) @ R.T + piv, cl(t, "door")) for q, t, g in door]
    lo, hi = info["lo"], info["hi"]; c = (lo + hi) / 2; L = hi[2] - lo[2]
    oc = np.array([side * info["halfW"], 0.55 * info["roof"], (zF + zR) / 2])
    tiles = [render(gs, oc + np.array([side * 0.9 * L, 0.05, 0.0]), oc, fov=30),
             render(gs, c + np.array([side * 1.0 * L, 0.35 * L, -0.9 * L]), c, fov=45),
             render([(q, cl(t, g)) for q, t, g in body] + [(q, cl(t, g)) for q, t, g in teeth], c + np.array([side * 1.2 * L, 0.1 * L, 0.5 * L]), c, fov=40)]
    S = Image.new("RGB", (800 * 3, 470), (30, 30, 30))
    for i, t in enumerate(tiles): S.paste(t, (800 * i, 20))
    ImageDraw.Draw(S).text((4, 4), f"{stem} side {side} z {zR}..{zF}: grey body, blue door (swung {swing:.0f}), dark interior, RED = body triangles kept whole reaching into the door box ({len(teeth)}); right: body only", fill=(255, 255, 255))
    S.save(out); print(len(body), len(door), len(teeth))
