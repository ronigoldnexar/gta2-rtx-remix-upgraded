#!/usr/bin/env python3
"""PEDS-FACES-2: head-swap combinations: avatar B's head (head mesh and hair cards, its own maps) on avatar A's body.

    headswap2.py <models dir> <out dir> [--manifest <manifest.json>] [--report <json>] A:B ...
    headswap2.py <models dir> <out dir> --candidates           (prints the candidate pairs: same sex, same skin group)

Each combination <A>^<B>.mesh is A's file with its head meshes replaced by B's, B's vertices re-bound to A's
skeleton (per joint: A's bind matrix x B's inverse bind), with no clips (the DLL plays A's: "detail_of"). A's nodes
and so its clothing zones are kept; textures are B's head maps and A's body maps (nothing new in memory but the mesh).
The seam (B's head border against A's own head border) is measured; the neck sheet (headswap_sheet) judges by eye."""
import sys, os, json, struct, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmsh
from headswap import write, border
from faces import hair_mask
from paint_resplit import read_tga

# bodies with a collar, a hood or a high neckline (judged on the avatar sheet); no scoop or V necks
BODIES_M = ['human_male_01', 'human_male_07', 'human_male_10', 'human_male_13', 'human_male_adult_06', 'human_male_adult_08',
            'human_male_adult_12', 'human_male_adult_16', 'human_male_adult_18', 'human_male_adult_20', 'human_business_male_04',
            'human_business_male_06', 'human_business_male_07']
BODIES_F = ['human_female_01', 'human_female_adult_02', 'human_female_adult_04', 'human_female_adult_09', 'human_female_adult_12',
            'human_female_adult_15', 'human_business_female_02', 'human_business_female_04']
HEADS_M = ['human_male_01', 'human_male_07', 'human_male_10', 'human_male_13', 'human_male_adult_02', 'human_male_adult_06',
           'human_male_adult_08', 'human_male_adult_09', 'human_male_adult_12', 'human_male_adult_16', 'human_male_adult_20',
           'human_business_male_04', 'human_business_male_06', 'human_business_male_07', 'human_male_04']
HEADS_F = ['human_female_01', 'human_female_03', 'human_female_05', 'human_female_08', 'human_female_adult_02', 'human_female_adult_04',
           'human_female_adult_07', 'human_female_adult_09', 'human_female_adult_11', 'human_female_adult_12', 'human_female_adult_13',
           'human_female_adult_14', 'human_female_adult_15', 'human_female_adult_17', 'human_business_female_01',
           'human_business_female_02', 'human_business_female_04']

def skin_of(M, name):
    m = gmsh.load(M + name + '.mesh')
    ht = [me['tex'] for me in m['meshes'] if me['tex'].endswith('_head.tga')][0]
    a = read_tga(M + ht)[..., :3].astype(np.float32)
    _, skin = hair_mask(a, 0.5)
    return skin

def same_group(sa, sb):
    """The face skins close enough that A's hands and B's face read as one person: luminance within 16, hue close."""
    la, lb = sa.mean(), sb.mean()
    ca, cb = sa / max(la, 1), sb / max(lb, 1)
    return abs(la - lb) < 16 and np.abs(ca - cb).max() < 0.08

def combo(M, out, A, B, head_only=True):
    a, b = gmsh.load(M + A + '.mesh'), gmsh.load(M + B + '.mesh')
    an = [n['name'] for n in a['nodes']]; bn = [n['name'] for n in b['nodes']]
    ajn, aibm = a['skins'][0]; bjn, bibm = b['skins'][0]
    aj_by = {an[j]: k for k, j in enumerate(ajn)}
    bindA = {k: np.linalg.inv(aibm[k].T) for k in range(len(ajn))}
    kind = lambda me: 'head' if me['tex'].endswith('_head.tga') else 'gl' if '_glasses' in me['tex'] else 'op' if '_opacity' in me['tex'] else None   # (glasses: the face's own)
    newb = {}
    seam = None
    for me in b['meshes']:
        k = kind(me)
        if not k: continue
        v = me['v'].copy(); J = me['J'].copy(); W = me['W']
        P = np.c_[v[:, :3], np.ones(len(v))]
        newP = np.zeros((len(v), 3)); newN = np.zeros((len(v), 3))
        for i in range(len(v)):
            acc = np.zeros(4); accn = np.zeros(3)
            for s in range(4):
                if W[i, s] <= 0: continue
                ka = aj_by.get(bn[bjn[J[i, s]]])
                if ka is None: continue
                Mx = bindA[ka] @ bibm[J[i, s]].T
                acc += W[i, s] * (Mx @ P[i]); accn += W[i, s] * (Mx[:3, :3] @ v[i, 3:6]); J[i, s] = ka
            newP[i] = acc[:3]; newN[i] = accn / (np.linalg.norm(accn) + 1e-9)
        v[:, :3] = newP; v[:, 3:6] = newN
        newb[k] = dict(v=v, idx=me['idx'], tex=me['tex'], skin=0, J=J, W=W)
    if head_only:   # PEDS-FACES-2: the head meshes alone on A's skeleton; the DLL draws A's body (head hidden), then this
        host = [n for n in a['nodes'] if n['mesh'] >= 0 and kind(a['meshes'][n['mesh']]) == 'head'][0]
        ah = a['meshes'][host['mesh']]
        ab = ah['v'][border(ah), :3]; bb = newb['head']['v'][border(newb['head']), :3]
        d = np.sqrt(((bb[:, None, :] - ab[None, :, :]) ** 2).sum(-1))
        seam = (float(np.median(d.min(1))), float(np.percentile(d.min(1), 95)))
        nodes = [dict(n, mesh=-1) for n in a['nodes']]; meshes = []
        for k in ('head', 'op', 'gl'):
            if k not in newb: continue
            meshes.append(newb[k])
            nodes.append(dict(name='swap_' + k, parent=host['parent'], t=host['t'], r=host['r'], s=host['s'], mesh=len(meshes) - 1))
        write(os.path.join(out, f'{A}^{B}.mesh'), dict(nodes=nodes, meshes=meshes, skins=[(ajn, aibm)]))
        return seam, [me['tex'] for me in b['meshes'] if kind(me)]
    meshes = [dict(me) for me in a['meshes']]
    nodes = [dict(n) for n in a['nodes']]
    for i, me in enumerate(a['meshes']):
        k = kind(me)
        if k == 'head':
            ab = me['v'][border(me), :3]; bb = newb['head']['v'][border(newb['head']), :3]
            d = np.sqrt(((bb[:, None, :] - ab[None, :, :]) ** 2).sum(-1))
            seam = (float(np.median(d.min(1))), float(np.percentile(d.min(1), 95)))
        if k in newb: meshes[i] = newb.pop(k)
        elif k in ('op', 'gl'):                                             # A has cards (or glasses), B none: drop them
            for n in nodes:
                if n['mesh'] == i: n['mesh'] = -1
    host = [n for n in nodes if n['mesh'] >= 0 and kind(a['meshes'][n['mesh']]) == 'head'][0]
    for k in ('op', 'gl'):                                                  # B has cards (or glasses), A none: nodes of their own
        if k in newb:
            meshes.append(newb.pop(k))
            nodes.append(dict(name='swap_' + k, parent=host['parent'], t=host['t'], r=host['r'], s=host['s'], mesh=len(meshes) - 1))
    write(os.path.join(out, f'{A}^{B}.mesh'), dict(nodes=nodes, meshes=meshes, skins=[(ajn, aibm)]))
    texB = [me['tex'] for me in b['meshes'] if kind(me)]
    return seam, texB

if __name__ == '__main__':
    args = sys.argv[1:]; man = rep = None
    if '--manifest' in args: i = args.index('--manifest'); man = args[i + 1]; del args[i:i + 2]
    if '--report' in args: i = args.index('--report'); rep = args[i + 1]; del args[i:i + 2]
    M, out = args[0].rstrip('/') + '/', args[1]; os.makedirs(out, exist_ok=True)
    if '--candidates' in args:
        skins = {n: skin_of(M, n) for n in set(BODIES_M + BODIES_F + HEADS_M + HEADS_F)}
        pairs = [f'{A}:{B}' for bodies, heads in ((BODIES_M, HEADS_M), (BODIES_F, HEADS_F)) for A in bodies for B in heads
                 if A != B and same_group(skins[A], skins[B])]
        print(' '.join(pairs)); sys.exit(0)
    report = {}
    for pair in args[2:]:
        A, B = pair.split(':'); seam, texB = combo(M, out, A, B)
        report[f'{A}^{B}'] = dict(seam_mm=[round(seam[0] * 2000, 1), round(seam[1] * 2000, 1)], tex=texB)
        print(f'{A}^{B} seam median {seam[0]*2000:.1f} mm 95% {seam[1]*2000:.1f} mm')
    if rep: json.dump(report, open(rep, 'w'), indent=1)
    if man:
        mm = json.load(open(man)); imp = {e['name']: e for e in mm['imported']}; have = {e['name'] for e in mm['models']}
        for c, r in report.items():
            A, B = c.split('^')
            if c not in have: mm['models'].append({'name': c, 'detail_of': A, 'head_of': B})
            e = json.loads(json.dumps(imp[A])); e['name'] = c
            e['textures'] = list(r['tex'])   # head-only: B's head maps
            mm['imported'] = [x for x in mm['imported'] if x['name'] != c] + [e]
        open(man, 'w').write(json.dumps(mm, indent=1))
