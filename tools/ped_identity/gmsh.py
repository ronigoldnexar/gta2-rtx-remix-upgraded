"""ASSET-PEDS: reader for the renderer's GMSH v2 model files (tools/import_assets.py) and CPU skinning of one clip frame."""
import struct, numpy as np

def _s(b): return b.split(b'\0')[0].decode('latin1')

def load(path):
    d = open(path, 'rb').read(); o = 4
    ver, nn, nm, na, ns = struct.unpack_from('<5I', d, o); o += 20
    nodes = []
    for _ in range(nn):
        name = _s(d[o:o+32]); o += 32
        par, = struct.unpack_from('<i', d, o); o += 4
        t = struct.unpack_from('<3f', d, o); o += 12
        r = struct.unpack_from('<4f', d, o); o += 16
        s = struct.unpack_from('<3f', d, o); o += 12
        mesh, = struct.unpack_from('<i', d, o); o += 4
        nodes.append(dict(name=name, parent=par, t=t, r=r, s=s, mesh=mesh))
    meshes = []
    for _ in range(nm):
        nv, ni = struct.unpack_from('<II', d, o); o += 8
        tex = _s(d[o:o+64]); o += 64
        skin, = struct.unpack_from('<i', d, o); o += 4
        v = np.frombuffer(d, np.float32, nv*8, o).reshape(nv, 8).copy(); o += nv*32
        J = W = None
        if skin >= 0:
            rec = np.dtype([('j', '<u2', 4), ('w', '<f4', 4)])
            a = np.frombuffer(d, rec, nv, o); o += nv*24
            J = a['j'].astype(np.int64); W = a['w'].astype(np.float32)
        idx = np.frombuffer(d, np.uint32, ni, o).astype(np.int64); o += ni*4
        meshes.append(dict(v=v, idx=idx, tex=tex, skin=skin, J=J, W=W))
    anims = {}
    for _ in range(na):
        name = _s(d[o:o+32]); o += 32
        nc, = struct.unpack_from('<I', d, o); o += 4
        ch = []
        for _ in range(nc):
            node, path, k = struct.unpack_from('<iII', d, o); o += 12
            times = np.frombuffer(d, np.float32, k, o); o += 4*k
            w = 4 if path == 1 else 3
            vals = np.frombuffer(d, np.float32, k*w, o).reshape(k, w); o += 4*k*w
            ch.append((node, path, times, vals))
        anims[name] = ch
    skins = []
    for _ in range(ns):
        nj, = struct.unpack_from('<I', d, o); o += 4
        jn = struct.unpack_from(f'<{nj}i', d, o); o += 4*nj
        ibm = np.frombuffer(d, np.float32, 16*nj, o).reshape(nj, 4, 4).copy(); o += 64*nj
        skins.append((list(jn), ibm))
    return dict(nodes=nodes, meshes=meshes, anims=anims, skins=skins)

def quat(q):
    x, y, z, w = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def trs(t, r, s):
    m = np.eye(4); m[:3, :3] = quat(r) * np.array(s)[None, :]; m[:3, 3] = t; return m

def pose(model, clip=None, frame=0):
    nodes = model['nodes']
    T = [list(n['t']) for n in nodes]; R = [list(n['r']) for n in nodes]; S = [list(n['s']) for n in nodes]
    if clip and clip in model['anims']:
        for node, path, times, vals in model['anims'][clip]:
            v = vals[min(frame, len(vals)-1)]
            if node < 0 or node >= len(nodes): continue
            if path == 0: T[node] = list(v)
            elif path == 1: R[node] = list(v)
            else: S[node] = list(v)
    world = [None]*len(nodes)
    def w(i):
        if world[i] is None:
            l = trs(T[i], R[i], S[i]); p = nodes[i]['parent']
            world[i] = l if p < 0 else w(p) @ l
        return world[i]
    for i in range(len(nodes)): w(i)
    out = []   # (positions Nx3, normals, uv, idx, tex, node index)
    for i, n in enumerate(nodes):
        mi = n['mesh']
        if mi < 0: continue
        m = model['meshes'][mi]; v = m['v']
        P = np.c_[v[:, :3], np.ones(len(v))]; N = v[:, 3:6]
        if m['skin'] >= 0:
            jn, ibm = model['skins'][m['skin']]
            # glTF matrices are column-major: stored transposed
            mats = np.stack([world[j] @ ibm[k].T for k, j in enumerate(jn)])
            M = np.einsum('vk,vkij->vij', m['W'], mats[m['J']])
            p = np.einsum('vij,vj->vi', M, P)[:, :3]; nn = np.einsum('vij,vj->vi', M[:, :3, :3], N)
        else:
            p = (world[i] @ P.T).T[:, :3]; nn = (world[i][:3, :3] @ N.T).T
        nn /= np.linalg.norm(nn, axis=1, keepdims=True) + 1e-9
        out.append((p, nn, v[:, 6:8], m['idx'].reshape(-1, 3), m['tex'], i))
    return out, world
