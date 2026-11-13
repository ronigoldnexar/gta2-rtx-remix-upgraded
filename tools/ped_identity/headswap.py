#!/usr/bin/env python3
"""PEDS-FACES test (not shipped): put avatar B's head (head mesh + hair cards, its own maps) on avatar A's body.

    headswap.py <models dir> <out dir> A:B ...
B's head vertices are re-bound to A's skeleton (for each joint they follow: A's bind matrix x B's inverse bind), so
they sit where A's head is; joints are matched by name. Writes <A>__<B>.mesh (A's nodes and skin, A's body, B's
head; no clips: render with anim_from=A) and prints the neck seam: B's head-mesh border against A's body border."""
import sys, os, struct, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh

def write(path, model):
    b = bytearray(b'GMSH') + struct.pack('<5I', 2, len(model['nodes']), len(model['meshes']), 0, len(model['skins']))
    for n in model['nodes']:
        b += n['name'].encode()[:31].ljust(32, b'\0') + struct.pack('<i3f4f3fi', n['parent'], *n['t'], *n['r'], *n['s'], n['mesh'])
    for me in model['meshes']:
        v = me['v']; b += struct.pack('<II', len(v), len(me['idx'])) + me['tex'].encode().ljust(64, b'\0') + struct.pack('<i', me['skin'])
        b += v.astype('<f4').tobytes()
        if me['skin'] >= 0:
            rec = np.zeros(len(v), np.dtype([('j', '<u2', 4), ('w', '<f4', 4)])); rec['j'] = me['J']; rec['w'] = me['W']; b += rec.tobytes()
        b += me['idx'].astype('<u4').tobytes()
    for jn, ibm in model['skins']:
        b += struct.pack('<I', len(jn)) + struct.pack(f'<{len(jn)}i', *jn) + ibm.astype('<f4').tobytes()
    open(path, 'wb').write(bytes(b))

def border(me):
    I = me['idx'].reshape(-1, 3); cnt = {}
    for f in I:
        for a, c in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            k = (min(a, c), max(a, c)); cnt[k] = cnt.get(k, 0) + 1
    return sorted({v for (a, c), n in cnt.items() if n == 1 for v in (a, c)})

def swap(M, A, B, out):
    a, b = gmsh.load(M + A + '.mesh'), gmsh.load(M + B + '.mesh')
    an = [n['name'] for n in a['nodes']]; bn = [n['name'] for n in b['nodes']]
    ajn, aibm = a['skins'][0]; bjn, bibm = b['skins'][0]
    aj_by = {an[j]: k for k, j in enumerate(ajn)}
    bindA = {k: np.linalg.inv(aibm[k].T) for k in range(len(ajn))}
    is_head = lambda me: me['tex'].endswith('_head.tga') or '_opacity' in me['tex']
    meshes = [me for me in a['meshes'] if not is_head(me)]
    seam = None
    for me in b['meshes']:
        if not is_head(me): continue
        v = me['v'].copy(); J = me['J'].copy(); W = me['W']
        P = np.c_[v[:, :3], np.ones(len(v))]
        newP = np.zeros((len(v), 3)); newN = np.zeros((len(v), 3))
        for i in range(len(v)):
            acc = np.zeros(4); accn = np.zeros(3)
            for s in range(4):
                if W[i, s] <= 0: continue
                name = bn[bjn[J[i, s]]]; ka = aj_by.get(name)
                if ka is None: continue
                Mx = bindA[ka] @ bibm[J[i, s]].T
                acc += W[i, s] * (Mx @ P[i]); accn += W[i, s] * (Mx[:3, :3] @ v[i, 3:6])
                J[i, s] = ka
            newP[i] = acc[:3]; newN[i] = accn / (np.linalg.norm(accn) + 1e-9)
        v[:, :3] = newP; v[:, 3:6] = newN
        meshes.append(dict(v=v, idx=me['idx'], tex=me['tex'], skin=0, J=J, W=W))
        if me['tex'].endswith('_head.tga'):
            bb = newP[border(dict(idx=me['idx']))]
            ah = [m for m in a['meshes'] if m['tex'].endswith('_head.tga')][0]
            ab = ah['v'][border(ah), :3]                                       # A's own head border = where the body meets it
            d = np.sqrt(((bb[:, None, :] - ab[None, :, :]) ** 2).sum(-1))
            seam = (np.median(d.min(1)), np.percentile(d.min(1), 95), np.median(d.min(0)), np.percentile(d.min(0), 95))
    nodes = [dict(n) for n in a['nodes']]
    for n in nodes: n['mesh'] = -1
    keep = [n for n in nodes]
    # one node per mesh, parented to the node that held A's first mesh
    host = [i for i, n in enumerate(a['nodes']) if n['mesh'] >= 0][0]
    for k in range(len(meshes)):
        if k == 0: nodes[host]['mesh'] = 0
        else: nodes.append(dict(name=f'swap{k}', parent=a['nodes'][host]['parent'], t=a['nodes'][host]['t'], r=a['nodes'][host]['r'], s=a['nodes'][host]['s'], mesh=k))
    write(os.path.join(out, f'{A}__{B}.mesh'), dict(nodes=nodes, meshes=meshes, skins=[(ajn, aibm)]))
    return seam

if __name__ == '__main__':
    M, out = sys.argv[1].rstrip('/') + '/', sys.argv[2]; os.makedirs(out, exist_ok=True)
    for pair in sys.argv[3:]:
        A, B = pair.split(':'); s = swap(M, A, B, out)
        print(f'{A} <- head of {B}: seam (mesh units, 1 = 2 m) B-border to A-border median {s[0]*2000:.1f} mm, 95% {s[1]*2000:.1f} mm; A-border to B median {s[2]*2000:.1f} mm, 95% {s[3]*2000:.1f} mm')
