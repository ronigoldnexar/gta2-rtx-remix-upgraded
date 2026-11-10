#!/usr/bin/env python3
"""VEHICLE-ART-13: read / write the game's .mesh (GMSH v2, tools/import_assets.py) for car bodies (no skins, no
animations), with node transforms resolved, so a shipped car can be inspected or extended without its glb."""
import struct
import numpy as np


def _str(b):
    return b.split(b"\0", 1)[0].decode("utf-8", "replace")


def read(path):
    d = open(path, "rb").read()
    assert d[:4] == b"GMSH"
    ver, nn, nm, na, ns = struct.unpack_from("<IIIII", d, 4)
    o = 24
    nodes = []
    for _ in range(nn):
        name = _str(d[o:o + 32]); o += 32
        par, = struct.unpack_from("<i", d, o); o += 4
        t = struct.unpack_from("<3f", d, o); o += 12
        r = struct.unpack_from("<4f", d, o); o += 16
        sc = struct.unpack_from("<3f", d, o); o += 12
        mi, = struct.unpack_from("<i", d, o); o += 4
        nodes.append(dict(name=name, parent=par, t=t, r=r, s=sc, mesh=mi))
    meshes = []
    for _ in range(nm):
        nv, ni = struct.unpack_from("<II", d, o); o += 8
        tex = _str(d[o:o + 64]); o += 64
        skin, = struct.unpack_from("<i", d, o); o += 4
        v = np.frombuffer(d, np.float32, nv * 8, o).reshape(nv, 8).copy(); o += nv * 32
        if skin >= 0:
            o += nv * 24
        idx = np.frombuffer(d, np.uint32, ni, o).copy(); o += ni * 4
        meshes.append(dict(tex=tex, skin=skin, v=v, idx=idx))
    tail = d[o:]
    assert na == 0 and ns == 0, "animated/skinned meshes are not handled"
    return dict(version=ver, nodes=nodes, meshes=meshes, tail=tail)


def write(m, path):
    out = [b"GMSH" + struct.pack("<IIIII", m["version"], len(m["nodes"]), len(m["meshes"]), 0, 0)]
    for n in m["nodes"]:
        b = n["name"].encode()[:31]
        out.append(b + b"\0" * (32 - len(b)))
        out.append(struct.pack("<i", n["parent"]) + struct.pack("<3f", *n["t"]) + struct.pack("<4f", *n["r"])
                   + struct.pack("<3f", *n["s"]) + struct.pack("<i", n["mesh"]))
    for me in m["meshes"]:
        b = me["tex"].encode()[:63]
        out.append(struct.pack("<II", len(me["v"]), len(me["idx"])) + b + b"\0" * (64 - len(b)) + struct.pack("<i", -1))
        out.append(np.ascontiguousarray(me["v"], np.float32).tobytes())
        out.append(np.ascontiguousarray(me["idx"], np.uint32).tobytes())
    out.append(m.get("tail", b""))
    open(path, "wb").write(b"".join(out))


def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def world(m):
    """[(node, mesh, V(n,3) world, N(n,3) world, UV(n,2), F(k,3))] for every node that draws a mesh"""
    mats = []
    for n in m["nodes"]:
        M = np.eye(4)
        M[:3, :3] = _qmat(n["r"]) * np.asarray(n["s"])[None, :]
        M[:3, 3] = n["t"]
        mats.append(M)
    W = []
    for i, n in enumerate(m["nodes"]):
        A = mats[i]; p = n["parent"]
        while p >= 0:
            A = mats[p] @ A; p = m["nodes"][p]["parent"]
        W.append(A)
    res = []
    for i, n in enumerate(m["nodes"]):
        if n["mesh"] < 0:
            continue
        me = m["meshes"][n["mesh"]]
        v = me["v"]
        P = v[:, :3] @ W[i][:3, :3].T + W[i][:3, 3]
        Nn = v[:, 3:6] @ np.linalg.inv(W[i][:3, :3]).T
        Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-9)
        res.append((n, me, P, Nn, v[:, 6:8], me["idx"].reshape(-1, 3)))
    return res
