#!/usr/bin/env python3
"""FIX-CAR-IDENTITY-6: are the car bodies' faces turned outward?

The renderer draws car bodies without back-face culling and lights them by their vertex normals (one sun + ambient,
car_bodies.cpp). A body whose surfaces are wound and normalled INWARD still draws its shape, but the sun lights the
inside of each panel: the lids seen from above get the ambient alone (0.35 of the light instead of ~0.67 at the
default 24-degree sun), and the body reads 35-45 % darker than its classic sprite whatever the paint (the identity
gate's carkit 018 / remapped 004 / livery 051 failures, 10 Nov 2026; docs/identity-system.md section 11).

  check <models dir> [names...]   one line per authored car mesh (NNN_*.mesh with surface-named textures): the area-weighted normal of the topmost 5 % of
                                  its faces and the signed volume of its non-glass faces. INSIDE-OUT when the top
                                  faces look down. Exit status: the number of INSIDE-OUT meshes. numpy only.
  fix <in.mesh> <out.mesh>        re-orient one mesh: every connected patch (triangles sharing vertices inside one
                                  mesh) faces the side from which its triangles see more of the sky (cosine rays cast
                                  against the whole car, glass not an occluder: the rule tools/vehicle_art2/carkit.py
                                  bake_ao uses for 'outside'); an inward patch has its normals negated and its winding
                                  reversed. Needs open3d (gen3d venv). Never writes over its input; unlink a
                                  hard-linked destination first (assets/models and the stages share inodes).
"""
import os, struct, sys
import numpy as np


def read_mesh(path):
    d = bytearray(open(path, "rb").read())
    if d[:4] != b"GMSH":
        raise ValueError(f"{path}: not a GMSH file")
    o = 4
    ver, nn, nm, na = struct.unpack_from("<4I", d, o); o += 16
    if ver >= 2: o += 4
    nodes = []
    for _ in range(nn):
        name = d[o:o + 32].split(b"\0")[0].decode("latin-1"); o += 32
        par = struct.unpack_from("<i", d, o)[0]; o += 4
        t = struct.unpack_from("<3f", d, o); o += 12 + 16 + 12
        m = struct.unpack_from("<i", d, o)[0]; o += 4
        nodes.append((name, par, t, m))
    meshes = []
    for mi in range(nm):
        nv, ni = struct.unpack_from("<2I", d, o); o += 8
        tex = d[o:o + 64].split(b"\0")[0].decode("latin-1"); o += 64
        skin = -1
        if ver >= 2: skin = struct.unpack_from("<i", d, o)[0]; o += 4
        voff = o; o += nv * 32
        if skin >= 0: o += nv * 24
        ioff = o; o += ni * 4
        V = np.frombuffer(bytes(d[voff:voff + nv * 32]), np.float32).reshape(nv, 8).copy()
        I = np.frombuffer(bytes(d[ioff:ioff + ni * 4]), np.uint32).reshape(-1, 3).copy()
        # node translation chain (the car kits' nodes carry no rotation or scale)
        t = np.zeros(3)
        for n in nodes:
            if n[3] == mi:
                k = n
                while k is not None:
                    t += np.array(k[2]); k = nodes[k[1]] if k[1] >= 0 else None
                break
        meshes.append({"tex": tex, "V": V, "I": I, "T": t, "voff": voff, "ioff": ioff})
    return d, meshes


def tri_arrays(meshes, skip_glass=True):
    P, N, A, S = [], [], [], []
    for m in meshes:
        if skip_glass and "glass" in m["tex"]: continue
        if len(m["I"]) == 0: continue
        p = m["V"][:, :3] + m["T"]; I = m["I"]
        a, b, c = p[I[:, 0]], p[I[:, 1]], p[I[:, 2]]
        fn = np.cross(b - a, c - a); area = np.linalg.norm(fn, axis=1) / 2
        P.append((a + b + c) / 3); N.append(m["V"][I, 3:6].mean(1)); A.append(area)
        S.append(np.einsum("ij,ij->i", a, np.cross(b, c)) / 6)
    return np.concatenate(P), np.concatenate(N), np.concatenate(A), float(np.concatenate(S).sum())


AUTHORED = ("_glass", "_chrome", "_tyre", "_seal", "_underbody", "_interior", "_seat", "_whitewall", "_rubber")


def check(models_dir, names):
    files = sorted(f for f in os.listdir(models_dir) if f.endswith(".mesh") and f[:3].isdigit() and f[3] == "_")
    if names: files = [f for f in files if any(f.startswith(n) for n in names)]
    bad = 0
    for f in files:
        try:
            _, meshes = read_mesh(os.path.join(models_dir, f))
            # Authored bodies only (surface-named textures, model_store.cpp CarSurfaceFor): the image-to-3D shells are
            # wound either way by nature and get their normals welded at load (SmoothCarNormals).
            if not any(k in m["tex"] for m in meshes for k in AUTHORED):
                continue
            C, N, A, vol = tri_arrays(meshes)
        except Exception as e:  # a model the tool cannot read is not a verdict
            print(f"skip {f}: {e}"); continue
        hi = C[:, 1] >= np.percentile(C[:, 1], 95)
        n = N[hi] / np.maximum(np.linalg.norm(N[hi], axis=1, keepdims=True), 1e-9)
        top = float((n[:, 1] * A[hi]).sum() / max(A[hi].sum(), 1e-12))
        # The painted parts alone (what the identity tint lands on): the share of their area whose normal points away
        # from the body's centre. A roof plate can face out over a painted box that faces in (the 004 bank van).
        centre = 0.5 * (C.min(0) + C.max(0))
        inward = []
        for m in meshes:
            if "_paint" not in m["tex"] or "wheel" in m["tex"] or len(m["I"]) == 0: continue
            pc, pn, pa, _ = tri_arrays([m])
            out = np.einsum("ij,ij->i", pn, pc - centre) > 0
            share = float(pa[out].sum() / max(pa.sum(), 1e-12))
            if share < 0.5: inward.append(f"{m['tex'][len(f) - 5:]} {share:.0%} out")
        inside = top < -0.2 or bool(inward)
        bad += inside
        print(f"{'INSIDE-OUT' if inside else 'ok':10s} {f[:-5]:28s} top faces normal.y {top:+.2f}  signed volume {vol:+.4f}"
              + (f"  paint facing in: {', '.join(inward)}" if inward else ""))
    return bad


def fix(src, dst):
    import open3d as o3d
    if os.path.abspath(src) == os.path.abspath(dst): raise SystemExit("fix: write to another path")
    d, meshes = read_mesh(src)
    P_all, F_all, off = [], [], 0
    for m in meshes:
        if "glass" in m["tex"] or len(m["I"]) == 0: continue
        P_all.append(m["V"][:, :3] + m["T"]); F_all.append(m["I"] + off); off += len(m["V"])
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(np.concatenate(P_all).astype(np.float32)),
                        o3d.core.Tensor(np.concatenate(F_all).astype(np.uint32)))
    rng = np.random.default_rng(7); K = 24
    a = rng.random(K); b = rng.random(K); r = np.sqrt(a); th = 2 * np.pi * b
    local = np.stack([r * np.cos(th), r * np.sin(th), np.sqrt(1 - a)], 1)

    def sky(p, n):
        z = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        tmp = np.where(np.abs(z[:, :1]) < 0.9, np.array([[1.0, 0, 0]]), np.array([[0, 1.0, 0]]))
        x = np.cross(z, tmp); x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-12); y = np.cross(z, x)
        dirs = local[None, :, 0:1] * x[:, None] + local[None, :, 1:2] * y[:, None] + local[None, :, 2:3] * z[:, None]
        org = np.repeat((p + z * 1e-4)[:, None], K, 1)
        rays = np.concatenate([org, dirs], 2).reshape(-1, 6).astype(np.float32)
        return np.isinf(scene.cast_rays(o3d.core.Tensor(rays))["t_hit"].numpy().reshape(-1, K)).mean(1)

    tot = flipped = 0.0
    for m in meshes:
        V, I = m["V"], m["I"]
        if len(I) == 0: continue
        p = V[:, :3] + m["T"]
        a_, b_, c_ = p[I[:, 0]], p[I[:, 1]], p[I[:, 2]]
        area = np.linalg.norm(np.cross(b_ - a_, c_ - a_), axis=1) / 2
        vn = V[I, 3:6].mean(1); cen = (a_ + b_ + c_) / 3
        vote = (sky(cen, vn) - sky(cen, -vn)) * area
        par = np.arange(len(V))
        def find(x):
            while par[x] != x:
                par[x] = par[par[x]]; x = par[x]
            return x
        for t in I:
            r0 = find(t[0])
            for v in t[1:]:
                rv = find(v)
                if rv != r0: par[rv] = r0
        root = np.array([find(v) for v in range(len(V))])
        troot = root[I[:, 0]]
        flipv = np.zeros(len(V), bool); flipt = np.zeros(len(I), bool)
        for rt in np.unique(troot):
            sel = troot == rt
            if vote[sel].sum() < 0:
                flipt |= sel; flipv[root == rt] = True
        V[flipv, 3:6] *= -1
        I[flipt] = I[flipt][:, ::-1]
        d[m["voff"]:m["voff"] + V.nbytes] = V.astype(np.float32).tobytes()
        d[m["ioff"]:m["ioff"] + I.nbytes] = I.astype(np.uint32).tobytes()
        tot += area.sum(); flipped += area[flipt].sum()
        if flipt.any(): print(f"  {m['tex']}: {flipt.sum()} of {len(I)} triangles turned outward ({area[flipt].sum() / max(area.sum(), 1e-12):.0%} of its area)")
    if os.path.lexists(dst): os.unlink(dst)
    open(dst, "wb").write(bytes(d))
    print(f"{src}: {flipped / max(tot, 1e-12):.0%} of the area turned outward -> {dst}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        sys.exit(min(check(sys.argv[2], sys.argv[3:]), 125))
    if len(sys.argv) == 4 and sys.argv[1] == "fix":
        fix(sys.argv[2], sys.argv[3]); sys.exit(0)
    print(__doc__); sys.exit(2)
