#!/usr/bin/env python3
"""FIX-FP-ARMS-2: every first-person hand pose from ONE mesh, so the poses share topology, UVs and textures.

    gen3d/venv/bin/python tools/fp_arms_pose.py <work dir> <models out dir> [--blender <blender>]

tools/gen_fp_arms.py builds and bakes the relaxed hand (the rest mesh, `fp_hand_base` in <work>/base). Here each of its
low-poly vertices is skinned to the hand's skeleton (palm, forearm, three segments per finger and thumb, weights by
distance blended only between neighbouring bones), moved to the target pose by the bones' rigid motions, then
projected onto the target pose's own signed distance field (its own finger's field, so a finger never snaps onto its
neighbour), which removes the linear-skinning volume loss at the knuckles. The textures: the rest bake (albedo, no
shadowing) times an ambient occlusion baked in Blender on the posed mesh itself (warm: occluded skin goes red-brown,
not grey), one for the relaxed hand and one for the fist; the in-between curl meshes use one or the other.

Writes the renderer's .mesh files directly (GMSH v2, tools/import_assets.py's layout):
  fp_bare_relax_right, fp_bare_curl1_right, fp_bare_curl2_right, fp_bare_curl3_right, fp_bare_fist_right
  (the curl from relaxed to the fist in quarters) and their two textures.
"""
import json, math, os, struct, subprocess, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_fp_arms as G  # noqa: E402

SC = G.SCALE   # blocks a metre


# ---------------------------------------------------------------- the renderer's model file
def read_gmsh(path):
    b = open(path, "rb").read()
    assert b[:4] == b"GMSH"
    ver, nn, nm, na, ns = struct.unpack_from("<5I", b, 4)
    o = 24
    nodes = []
    for _ in range(nn):
        name = b[o:o + 32].split(b"\0")[0].decode(); o += 32
        parent, = struct.unpack_from("<i", b, o); o += 4
        trs = struct.unpack_from("<10f", b, o); o += 40
        mesh, = struct.unpack_from("<i", b, o); o += 4
        nodes.append(dict(name=name, parent=parent, trs=trs, mesh=mesh))
    meshes = []
    for _ in range(nm):
        nv, ni = struct.unpack_from("<2I", b, o); o += 8
        tex = b[o:o + 64].split(b"\0")[0].decode(); o += 64
        skin, = struct.unpack_from("<i", b, o); o += 4
        v = np.frombuffer(b, np.float32, nv * 8, o).reshape(nv, 8).copy(); o += nv * 32
        assert skin < 0
        idx = np.frombuffer(b, np.uint32, ni, o).copy(); o += ni * 4
        meshes.append(dict(v=v, idx=idx, tex=tex))
    return nodes, meshes


def write_gmsh(path, parts):
    """parts: [(node name, vertices (N,8) float32, indices, texture file)], one node and one mesh each, no transforms."""
    out = bytearray(b"GMSH") + struct.pack("<5I", 2, len(parts), len(parts), 0, 0)
    for i, (name, v, idx, tex) in enumerate(parts):
        out += name.encode()[:31].ljust(32, b"\0") + struct.pack("<i", -1)
        out += struct.pack("<10f", 0, 0, 0, 0, 0, 0, 1, 1, 1, 1) + struct.pack("<i", i)
    for name, v, idx, tex in parts:
        out += struct.pack("<2I", len(v), len(idx)) + tex.encode()[:63].ljust(64, b"\0") + struct.pack("<i", -1)
        out += np.ascontiguousarray(v, np.float32).tobytes() + np.ascontiguousarray(idx, np.uint32).tobytes()
    open(path + ".tmp", "wb").write(out)
    os.replace(path + ".tmp", path)


def vertex_normals(p, idx):
    """Smooth normals, welded across UV seams (vertices at the same place share one)."""
    key = np.round(p * 1e6).astype(np.int64)
    _, weld = np.unique(key, axis=0, return_inverse=True)
    weld = weld.ravel()
    f = idx.reshape(-1, 3)
    fn = np.cross(p[f[:, 1]] - p[f[:, 0]], p[f[:, 2]] - p[f[:, 0]])
    acc = np.zeros((weld.max() + 1, 3))
    for k in range(3):
        np.add.at(acc, weld[f[:, k]], fn)
    n = acc[weld]
    return (n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)).astype(np.float32)


# ---------------------------------------------------------------- poses
def lerp_pose(a, b, t):
    pa, pb = G.POSES[a], G.POSES[b]
    return dict(flex=[tuple((1 - t) * x + t * y for x, y in zip(fa, fb)) for fa, fb in zip(pa["flex"], pb["flex"])],
                thumb=[tuple(G.unit((1 - t) * G.unit(x) + t * G.unit(y))) for x, y in zip(pa["thumb"], pb["thumb"])],
                splay=(1 - t) * pa.get("splay", 1.0) + t * pb.get("splay", 1.0),
                wrist=(1 - t) * pa.get("wrist", 0.0) + t * pb.get("wrist", 0.0))


THUMB_REF = np.array([0.30, 0.90, -0.30])


def skeleton(pose):
    """Per chain (index..little, thumb): per segment (origin, frame columns x y z) in the HAND's space (before the wrist
    turn), the segment's end, and the wrist's rotation."""
    chains = []
    up = np.array([0.0, 1.0, 0.0])
    for fd, fl in zip(G.FINGERS, pose["flex"]):
        pts, fwd = G.finger_chain(fd, fl, pose.get("splay", 1.0))
        ax = G.unit(np.cross(up, fwd))
        segs = []
        for k in range(3):
            ez = G.unit(pts[k + 1] - pts[k]); ex = ax; ey = np.cross(ez, ex)
            segs.append((pts[k], np.stack([ex, ey, ez], 1), pts[k + 1]))
        chains.append(segs)
    tp = G.thumb_chain(pose)
    segs = []
    for k in range(3):
        ez = G.unit(tp[k + 1] - tp[k]); ex = G.unit(np.cross(THUMB_REF, ez)); ey = np.cross(ez, ex)
        segs.append((tp[k], np.stack([ex, ey, ez], 1), tp[k + 1]))
    chains.append(segs)
    return chains, G.wrist_rot(pose)


def seg_dist(v, a, b, r0, r1):
    ba = b - a
    t = np.clip(((v - a) @ ba) / (ba @ ba), 0, 1)
    return np.linalg.norm(v - (a + t[:, None] * ba), axis=1) - (r0 + (r1 - r0) * t)


def skin(v_arm, rest):
    """Weights (N, 1 + 15) over [palm, chain0 seg0..2, ..., thumb seg0..2], the forearm share (N,), the dominant chain."""
    chains, Rw = skeleton(rest)
    vh = v_arm @ Rw   # into the hand's space (row vectors: v @ R == R^T v)
    radii = [fd["r"] for fd in G.FINGERS] + [G.THUMB_R[1:]]
    d = [G.hand_parts(v_arm.astype(np.float32), rest)[0].astype(np.float64)]
    for ci, segs in enumerate(chains):
        r = radii[ci]
        for k, (o, F, e) in enumerate(segs):
            d.append(seg_dist(vh, o, e, r[k], r[k + 1]))
    d = np.stack(d, 1)
    best = d.argmin(1)
    tau = 0.0022
    w = np.zeros_like(d)
    for i in range(d.shape[1]):
        # neighbours of part i: the palm with every chain's first segment; a segment with the one before and after
        if i == 0:
            nb = [0] + [1 + 3 * c for c in range(5)]
        else:
            c, k = divmod(i - 1, 3)
            nb = [i] + ([0] if k == 0 else [i - 1]) + ([i + 1] if k < 2 else [])
        m = best == i
        if not m.any():
            continue
        dm = d[m][:, [i]]
        for j in nb:
            w[m, j] = np.exp(-(d[m, j] - dm[:, 0]) / tau)
    w /= w.sum(1, keepdims=True)
    fore = np.clip((-v_arm[:, 2] - 0.002) / 0.022, 0, 1)
    fore = fore * fore * (3 - 2 * fore)
    dom = np.where(best == 0, -1, (best - 1) // 3)
    return w, fore, dom


def pose_vertices(v_arm, w, fore, dom, rest, pose, project=True):
    c0, R0 = skeleton(rest)
    c1, R1 = skeleton(pose)
    vh = v_arm @ R0
    out = w[:, [0]] * vh
    i = 1
    for s0, s1 in zip(c0, c1):
        for (o0, F0, _), (o1, F1, _) in zip(s0, s1):
            loc = (vh - o0) @ F0          # F0^T (v - o0)
            out = out + w[:, [i]] * (o1 + loc @ F1.T)
            i += 1
    arm = out @ R1.T
    res = fore[:, None] * v_arm + (1 - fore[:, None]) * arm
    if not project:
        return res
    # onto the pose's own surface: each vertex onto its chain's field (or the wrist's), a few Newton steps
    for c in range(-1, 5):
        m = dom == c
        if not m.any():
            continue

        def phi(P, c=c):
            wr, chains, _, _ = G.hand_parts(P.astype(np.float32), pose)
            if c < 0:
                return wr.astype(np.float64)
            f, k = chains[c]
            return G.smin(wr, f, k).astype(np.float64)
        q = res[m]
        for _ in range(5):
            f0 = phi(q)
            g = np.zeros_like(q)
            e = 2e-4
            for a in range(3):
                dv = np.zeros(3); dv[a] = e
                g[:, a] = (phi(q + dv) - phi(q - dv)) / (2 * e)
            g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
            q = q - g * np.clip(f0, -0.0015, 0.0015)[:, None]
        res[m] = q
    return res


# ---------------------------------------------------------------- ambient occlusion per pose, baked in Blender
def write_obj(path, p_m, uv, idx):
    with open(path, "w") as fh:
        for x in p_m: fh.write("v %.6f %.6f %.6f\n" % tuple(x))
        for t in uv: fh.write("vt %.6f %.6f\n" % (t[0], 1.0 - t[1]))
        for f in idx.reshape(-1, 3) + 1: fh.write("f %d/%d %d/%d %d/%d\n" % (f[0], f[0], f[1], f[1], f[2], f[2]))


AO_SCRIPT = r'''
import bpy, sys
a = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
s = bpy.context.scene; s.render.engine = "CYCLES"; s.cycles.device = "CPU"; s.cycles.samples = 96
s.render.bake.margin = 12
w = bpy.data.worlds.new("w"); s.world = w; w.light_settings.distance = float(a[2])
bpy.ops.wm.obj_import(filepath=a[0], forward_axis="Y", up_axis="Z")
o = bpy.context.selected_objects[0]; bpy.context.view_layer.objects.active = o
bpy.ops.object.shade_smooth()
img = bpy.data.images.new("ao", 1024, 1024, alpha=False); img.colorspace_settings.name = "Non-Color"
m = bpy.data.materials.new("m"); m.use_nodes = True
t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = img; m.node_tree.nodes.active = t
o.data.materials.clear(); o.data.materials.append(m)
bpy.ops.object.bake(type="AO")
img.filepath_raw = a[1]; img.file_format = "PNG"; img.save()
'''


def bake_ao(blender, work, name, p_blocks, uv, idx):
    obj = os.path.join(work, name + "_ao.obj"); png = os.path.join(work, name + "_ao.png")
    write_obj(obj, p_blocks / SC, uv, idx)
    scr = os.path.join(work, "ao_bake.py"); open(scr, "w").write(AO_SCRIPT)
    subprocess.run([blender, "-b", "--factory-startup", "-noaudio", "--python", scr, "--", obj, png, "0.035"],
                   check=True, stdout=subprocess.DEVNULL)
    from PIL import Image
    return np.asarray(Image.open(png).convert("L"), np.float32) / 255.0


def shade(base, ao, strength=0.70):
    """The albedo darkened where the pose occludes it, warmly (skin in shadow goes red-brown)."""
    k = np.array([0.62, 0.74, 0.78]) * strength
    occ = (1.0 - ao)[..., None]
    return np.clip(base[..., :3] * (1.0 - occ * k), 0, 255)


# ---------------------------------------------------------------- the armed view models' hands (fp_arm_*)
# In the weapon's hand space (tools/gen_weapons.py: the grip at the origin, +z the barrel, +y up, +x right; drawn x1.30
# by the renderer, the weapon itself x k): the hand posed, scaled by S (the guns are drawn larger than life), turned so
# the hand's axes land on `hx` (the knuckle line, index -> little finger) and `hy` (the back of the hand), the point
# `c` of the hand (metres, hand space, where the grip's middle sits in the closed hand) put on `at`; the wrist turned
# so the forearm leaves along `fore`; the upper arm from the elbow along `upper`. mirror: a left hand (x -> -x after).
S = 1.5
ARMED = {
    "fp_arm_right": dict(pose="grip", mirror=False, hx=(0, -1, -0.28), hy=(1, 0, 0.0), c=(0.0, -0.034, 0.060),
                         at=(0.0, -0.0122, -0.0046), fore=(0.14, -0.32, -0.94), upper=(0.30, -0.55, -0.78)),
    "fp_arm_left_cup": dict(pose="cup", mirror=True, hx=(0, -1, -0.28), hy=(1, 0, -0.15), c=(0.0, -0.034, 0.058),
                            at=(0.0080, -0.0135, 0.0040), fore=(0.30, -0.40, -0.87), upper=(0.40, -0.50, -0.77)),
    "fp_arm_left": dict(pose="fore", mirror=True, hx=(0, 0, -1), hy=(0, -1, 0), c=(0.0, -0.030, 0.050),
                        at=(0.0, -0.0062, 0.0), fore=(0.35, -0.45, -0.82), upper=(0.40, -0.55, -0.73)),
}


def rot_between(a, b):
    """The rotation taking unit a onto unit b (the shortest)."""
    a = G.unit(a); b = G.unit(b)
    v = np.cross(a, b); c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else G.rot(np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0]), math.pi)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def armed_frame(spec):
    hx = G.unit(spec["hx"]); hy = G.unit(np.array(spec["hy"]) - hx * (hx @ spec["hy"])); hz = np.cross(hx, hy)
    return np.stack([hx, hy, hz], 1)   # weapon <- hand


def build_armed(name, spec, p_rest, w, fore, dom, v8, idx, tex, uparm, out):
    R = armed_frame(spec)
    # the wrist: the forearm (arm space -z) must leave along `fore`: in hand space that is R^T fore
    f_h = R.T @ G.unit(spec["fore"])
    Rw = rot_between(np.array([0.0, 0.0, -1.0]), f_h).T      # hand -> arm: Rw^T (arm -z) = f_h
    pose = dict(G.POSES[spec["pose"]]); pose["Rw"] = Rw
    p_arm = pose_vertices(p_rest, w, fore, dom, G.POSES["relax"], pose)
    p_hand = p_arm @ Rw          # Rw^T p (row vectors)
    k = SC * S / 1.30            # metres -> the renderer's hand units (drawn x1.30)
    c = np.array(spec["c"]); at = np.array(spec["at"])
    gun = (p_hand - c) @ R.T * k + at
    # the elbow (the arm's -z end) and the upper arm along `upper`
    elbow_h = (np.array([0.0, 0.0, -G.FOREARM]) @ Rw)
    elbow = (elbow_h - c) @ R.T * k + at
    zu = G.unit(spec["upper"]); yu = G.unit(np.cross(zu, [1.0, 0, 0])); xu = np.cross(yu, zu)
    Ru = np.stack([xu, yu, zu], 1)
    parts = []
    hv = v8.copy(); hv[:, :3] = gun
    hidx = idx.copy()
    for nm, (uv8, uidx, utex) in uparm:
        u = uv8.copy()
        u[:, :3] = (u[:, :3] / SC) @ Ru.T * k + elbow
        parts.append([nm, u, uidx.copy(), utex])
    parts.insert(0, ["skin", hv, hidx, tex])
    for pt in parts:
        if spec["mirror"]:
            pt[1][:, 0] *= -1
            pt[2] = pt[2].reshape(-1, 3)[:, ::-1].ravel()
        pt[1][:, 3:6] = vertex_normals(pt[1][:, :3].astype(np.float64), pt[2])
    write_gmsh(os.path.join(out, name + ".mesh"), [tuple(p) for p in parts])
    print("armed: %s (%s%s) %d tris" % (name, spec["pose"], ", left" if spec["mirror"] else "", sum(len(p[2]) for p in parts) // 3))


def main():
    work, out = sys.argv[1], sys.argv[2]
    args = sys.argv[3:]
    blender = args[args.index("--blender") + 1] if "--blender" in args else "blender"
    os.makedirs(out, exist_ok=True)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from import_assets import write_tga
    from PIL import Image
    nodes, meshes = read_gmsh(os.path.join(work, "base", "fp_hand_base.mesh"))
    assert len(meshes) == 1 and all(abs(x - y) < 1e-6 for x, y in zip(nodes[0]["trs"], (0, 0, 0, 0, 0, 0, 1, 1, 1, 1)))
    v8, idx = meshes[0]["v"], meshes[0]["idx"]
    base_tex = np.asarray(Image.open(os.path.join(work, "base", meshes[0]["tex"])).convert("RGBA"), np.float32)
    p_rest = v8[:, :3].astype(np.float64) / SC
    w, fore, dom = skin(p_rest, G.POSES["relax"])
    print("pose: skinned %d vertices (dominant palm/forearm %d)" % (len(p_rest), int((dom < 0).sum())))
    only_armed = args[args.index("--armed") + 1].split(",") if "--armed" in args else None
    curl = [("fp_bare_relax_right", 0.0), ("fp_bare_curl1_right", 0.25), ("fp_bare_curl2_right", 0.5),
            ("fp_bare_curl3_right", 0.75), ("fp_bare_fist_right", 1.0)]
    if only_armed:   # re-fitting the armed holds only: the textures and curl meshes already in <out>
        texs = {"fp_bare_relax_right": "fp_bare_relax_right_0.tga", "fp_bare_fist_right": "fp_bare_fist_right_0.tga"}
        models = []
        curl = []
    posed = {}
    for name, t in curl:
        pose = lerp_pose("relax", "fist", t)
        p = p_rest if t == 0.0 else pose_vertices(p_rest, w, fore, dom, G.POSES["relax"], pose)
        posed[name] = (p * SC).astype(np.float32)
    texs = texs if only_armed else {}
    for name in ([] if only_armed else ("fp_bare_relax_right", "fp_bare_fist_right")):
        ao = bake_ao(blender, work, name, posed[name], v8[:, 6:8], idx)
        rgb = shade(base_tex, ao)
        tag = name + "_0.tga"
        write_tga(Image.fromarray(np.concatenate([rgb, np.full(rgb.shape[:2] + (1,), 255.0)], 2).astype(np.uint8), "RGBA"),
                  os.path.join(out, tag), 1024)
        texs[name] = tag
    models = [] if not only_armed else models
    for name, t in curl:
        tex = texs["fp_bare_relax_right"] if t < 0.5 else texs["fp_bare_fist_right"]
        v = v8.copy(); v[:, :3] = posed[name]; v[:, 3:6] = vertex_normals(posed[name].astype(np.float64), idx)
        write_gmsh(os.path.join(out, name + ".mesh"), [("skin", v, idx, tex)])
        models.append(name)
        print("pose: %s (curl %.2f) %d tris, texture %s" % (name, t, len(idx) // 3, tex))
    # the armed view models' hands, on the fist's texture; the upper arm and sleeve from fp_uparm_right
    un, um = read_gmsh(os.path.join(out, "fp_uparm_right.mesh"))
    uparm = [(n["name"], um[n["mesh"]]["v"], um[n["mesh"]]["idx"], um[n["mesh"]]["tex"]) for n in un if n["mesh"] >= 0]
    uparm = [(n, (v, i, t)) for n, v, i, t in uparm]
    for name, spec in ARMED.items():
        if only_armed and name not in only_armed:
            continue
        build_armed(name, spec, p_rest, w, fore, dom, v8, idx, texs["fp_bare_fist_right"], uparm, out)
        models.append(name)
    json.dump({"models": models, "textures": sorted(set(texs.values()))}, open(os.path.join(out, "fp_arms_pose.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
