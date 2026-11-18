#!/usr/bin/env python3
"""FIX-FP-ARMS: the first-person bare arms and hands, modelled as one surface each (hand, wrist, forearm) instead
of tubes and blobs, in a few hand poses, plus the upper arm in the player's short sleeve.

    gen3d/venv/bin/python tools/gen_fp_arms.py <work dir> [--blender <blender>] [--import <models out dir>] [--only relax,fist,uparm]

Shipped: the three models' .mesh/.tga are in assets/models (code objects, in git) with entries in its manifest.json
("glb": "weapons/<name>.glb"); regenerate into a scratch dir with --import, copy the files over and merge the entries.
About 4 minutes (marching cubes, then one Blender bake per model).

How: each pose is a signed distance field built from an anatomical skeleton (a metacarpal and three phalanges per
finger, the thumb's metacarpal and two phalanges, the forearm's tapering elliptical section, the thenar and
hypothenar pads, the knuckle heads, the ulna's head at the wrist), the bones' capsules blended smoothly into the
palm but kept apart from each other, so the fingers stay fingers (a smooth union of everything makes a mitten).
Marching cubes at 0.9 mm gives the detailed surface; each vertex gets a colour from the anatomy (nails, knuckle and
joint creases on both sides, the redder knuckles and finger tips, the lighter palm, a cavity term from the field
for the shadow between the fingers). tools/fp_arms_bake.py (Blender 4.2, headless) then decimates it to a few
thousand triangles, unwraps it and bakes the high mesh's colour into a 1024 px texture (then a fine skin
grain), and exports a .glb that tools/import_assets.py turns into the renderer's .mesh + .tga.

Model space (metres x SCALE = blocks, the renderer's units): origin at the wrist's centre, +z along the hand (the
fingers), +y the back of the hand, +x the little finger's side of a RIGHT hand (the thumb toward -x); the
forearm runs back along -z to the elbow at z = -FOREARM. The upper arm (fp_uparm_right): origin at the elbow,
+z up the arm to the shoulder, the sleeve over its upper part. Nodes: "skin" (and "sleeve", tinted by the
renderer to the player's shirt). The left hand is the right one reflected by the renderer.

Poses: relax (fingers loosely curled, the cascade from the index to the little finger, the thumb alongside),
fist (a boxer's fist, the thumb across the index and middle fingers' middle phalanges).
"""
import json, math, os, subprocess, sys
import numpy as np

SCALE = 4.8 ** -1          # blocks a metre (a block ~4.8 m)
FOREARM = 0.265            # wrist to elbow
SKIN = np.array([190, 147, 126], np.float32)   # the base skin (sRGB); less orange than the old (178,128,98)
SLEEVE = np.array([150, 150, 156], np.float32)  # light neutral cloth: the renderer tints it to the player's shirt


# ---------------------------------------------------------------- field primitives (vectorised over points p: (N,3))
def smin(a, b, k):
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def capsule(p, a, b, ra, rb):
    """A round cone from a (radius ra) to b (radius rb)."""
    a = np.asarray(a, np.float32); b = np.asarray(b, np.float32)
    ba = b - a
    L2 = float(ba @ ba)
    t = np.clip(((p - a) @ ba) / L2, 0.0, 1.0)
    q = p - (a + t[:, None] * ba)
    return np.linalg.norm(q, axis=1) - (ra + (rb - ra) * t)


def ellipsoid(p, c, r, R=None):
    q = p - np.asarray(c, np.float32)
    if R is not None:
        q = q @ R
    r = np.asarray(r, np.float32)
    k0 = np.linalg.norm(q / r, axis=1)
    k1 = np.linalg.norm(q / (r * r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def rbox(p, c, half, rad):
    q = np.abs(p - np.asarray(c, np.float32)) - (np.asarray(half, np.float32) - rad)
    return np.linalg.norm(np.maximum(q, 0.0), axis=1) + np.minimum(q.max(axis=1), 0.0) - rad


def unit(v):
    v = np.asarray(v, np.float64)
    return v / np.linalg.norm(v)


def rot(axis, ang):
    axis = unit(axis); x, y, z = axis; c, s = math.cos(ang), math.sin(ang); C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


# ---------------------------------------------------------------- the hand's skeleton
# index, middle, ring, little: knuckle (MCP head) centres, the metacarpal's base at the wrist, phalanx lengths,
# radii (proximal, middle, distal, tip), the splay (radians about +y; + toward the little finger's side).
FINGERS = [
    dict(mcp=(-0.0270, 0.0010, 0.0880), base=(-0.0150, 0.0020, 0.0130), L=(0.0440, 0.0255, 0.0215), r=(0.0094, 0.0085, 0.0077, 0.0068), splay=-0.06),
    dict(mcp=(-0.0075, 0.0030, 0.0920), base=(-0.0040, 0.0030, 0.0120), L=(0.0480, 0.0295, 0.0235), r=(0.0097, 0.0088, 0.0079, 0.0069), splay=0.00),
    dict(mcp=(0.0115, 0.0018, 0.0880), base=(0.0070, 0.0025, 0.0130), L=(0.0450, 0.0285, 0.0225), r=(0.0091, 0.0082, 0.0074, 0.0065), splay=0.06),
    dict(mcp=(0.0285, -0.0010, 0.0790), base=(0.0170, 0.0010, 0.0150), L=(0.0350, 0.0205, 0.0195), r=(0.0080, 0.0072, 0.0066, 0.0058), splay=0.14),
]

POSES = {
    # flexion (radians) at the MCP, PIP and DIP joints per finger; the thumb by its three segment directions
    "relax": dict(flex=[(0.30, 0.55, 0.28), (0.36, 0.62, 0.30), (0.44, 0.70, 0.32), (0.52, 0.78, 0.34)],
                  thumb=[(-0.50, -0.42, 0.76), (-0.18, -0.45, 0.87), (0.02, -0.45, 0.89)], splay=0.25, wrist=0.18),
    "fist": dict(flex=[(1.42, 1.98, 1.00), (1.48, 2.00, 1.00), (1.52, 2.02, 1.00), (1.58, 2.05, 1.00)],
                 thumb=[(-0.42, -0.55, 0.72), (0.55, -0.50, 0.67), (0.98, -0.15, 0.10)], splay=1.0, wrist=0.0),
    # FIX-FP-ARMS-2: the armed holds (tools/fp_arms_pose.py places them on the weapon). grip: round a pistol grip
    # (middle..little fingers wrapped, the index forward along the frame to the trigger, the thumb along the far side);
    # fore: under a fore grip or handguard (all four fingers up its far side); cup: the support hand round the
    # shooting hand's fingers.
    "grip": dict(flex=[(0.42, 0.62, 0.30), (1.42, 1.50, 0.70), (1.48, 1.55, 0.72), (1.55, 1.60, 0.75)],
                 thumb=[(-0.42, -0.55, 0.72), (-0.05, -0.62, 0.78), (0.10, -0.55, 0.83)], splay=0.4, wrist=0.0),
    "fore": dict(flex=[(1.05, 1.15, 0.50), (1.10, 1.20, 0.52), (1.15, 1.25, 0.55), (1.22, 1.30, 0.58)],
                 thumb=[(-0.50, -0.50, 0.70), (-0.20, -0.55, 0.81), (0.00, -0.55, 0.84)], splay=0.3, wrist=0.0),
    "cup": dict(flex=[(1.00, 1.05, 0.45), (1.05, 1.10, 0.48), (1.10, 1.15, 0.50), (1.18, 1.20, 0.52)],
                thumb=[(-0.55, -0.35, 0.76), (-0.25, -0.30, 0.92), (-0.10, -0.25, 0.96)], splay=0.3, wrist=0.0),
}


def finger_chain(fd, flex, splay=1.0):
    """The four joint points (MCP, PIP, DIP, tip) of a finger in a pose."""
    fwd = rot((0, 1, 0), fd["splay"] * splay) @ np.array([0.0, 0.0, 1.0])
    upv = np.array([0.0, 1.0, 0.0])
    pts = [np.array(fd["mcp"], np.float64)]
    a = 0.0
    for L, f in zip(fd["L"], flex):
        a += f
        d = math.cos(a) * fwd - math.sin(a) * upv
        pts.append(pts[-1] + d * L)
    return pts, fwd


THUMB_CMC = np.array([-0.0215, -0.0080, 0.0150])
THUMB_L = (0.0420, 0.0330, 0.0285)
THUMB_R = (0.0125, 0.0108, 0.0098, 0.0090, 0.0080)


def thumb_chain(pose):
    pts = [THUMB_CMC.copy()]
    for L, d in zip(THUMB_L, pose["thumb"]):
        pts.append(pts[-1] + unit(d) * L)
    return pts


def forearm_field(p):
    """The forearm: an elliptical section along -z from the wrist (flat, 5.8 x 3.9 cm) to the muscle belly
    (8.2 x 7.0 cm, toward the elbow on the back and thumb side) and down to the elbow."""
    z = p[:, 2]
    zs = np.array([0.045, 0.0, -0.040, -0.110, -0.175, -0.225, -FOREARM + 0.01, -FOREARM])
    rx = np.array([0.0270, 0.0272, 0.0295, 0.0345, 0.0385, 0.0370, 0.0340, 0.0300])
    ry = np.array([0.0150, 0.0178, 0.0205, 0.0275, 0.0315, 0.0315, 0.0310, 0.0290])
    cy = np.array([0.0000, 0.0000, 0.0010, 0.0030, 0.0040, 0.0030, 0.0020, 0.0020])
    cx = np.array([0.0000, 0.0000, -0.0010, -0.0030, -0.0040, -0.0020, 0.0000, 0.0000])
    zz = np.clip(z, zs[-1], zs[0])
    ax = np.interp(-zz, -zs, rx); ay = np.interp(-zz, -zs, ry)
    ox = np.interp(-zz, -zs, cx); oy = np.interp(-zz, -zs, cy)
    qx = (p[:, 0] - ox) / ax; qy = (p[:, 1] - oy) / ay
    d = (np.sqrt(qx * qx + qy * qy) - 1.0) * np.minimum(ax, ay)
    # capped: past the ends, the distance to the end disc grows
    over = np.maximum(z - zs[0], 0.0) + np.maximum(zs[-1] - z, 0.0)
    return np.where(over > 0, np.sqrt(np.maximum(d, 0) ** 2 + over ** 2), d)


def wrist_rot(pose):
    """The hand's turn at the wrist (arm space <- hand space): "Rw" when the pose gives the whole rotation (the armed
    holds), else "wrist" radians of flexion toward the palm."""
    return np.asarray(pose["Rw"]) if "Rw" in pose else rot((1, 0, 0), pose.get("wrist", 0.0))


def hand_parts(p_arm, pose):
    """The pose's field split by part: the wrist (palm, pads, knuckle heads, tendons, forearm) and one field per finger
    (the index..little fingers, then the thumb), each to be blended into the wrist; plus the joints for the colours."""
    # the hand turned at the wrist (pose "wrist": + bends it toward the palm); the forearm stays
    Rw = wrist_rot(pose)
    p = (p_arm @ Rw).astype(np.float32)
    # the palm: a slab with the metacarpals in it, the pads under, the knuckle heads on the front edge
    palm = rbox(p, (0.0010, -0.0025, 0.0500), (0.0300, 0.0110, 0.0400), 0.0095)
    for fd in FINGERS:
        palm = smin(palm, capsule(p, fd["base"], np.array(fd["mcp"]) + (0, -0.001, -0.004), 0.0085, fd["r"][0] * 1.02), 0.008)
    palm = smin(palm, ellipsoid(p, (-0.0215, -0.0095, 0.0330), (0.0155, 0.0130, 0.0255), rot((0, 1, 0), -0.45)), 0.010)   # thenar
    palm = smin(palm, ellipsoid(p, (0.0245, -0.0080, 0.0420), (0.0105, 0.0105, 0.0300)), 0.010)                          # hypothenar
    palm = smin(palm, ellipsoid(p, (0.0000, -0.0105, 0.0740), (0.0300, 0.0070, 0.0120)), 0.008)                            # the pad under the knuckles
    flexed = [min(1.0, max(0.0, fl[0] / 1.4)) for fl in pose["flex"]]
    for fd, fx in zip(FINGERS, flexed):
        # the metacarpal head: stands out as a knuckle as the finger bends away from it
        r0 = fd["r"][0]
        palm = smin(palm, ellipsoid(p, np.array(fd["mcp"]) + (0, 0.0012 * fx, 0.0015 * fx), (r0 * 1.05, r0 * (1.0 + 0.06 * fx), r0 * 1.0)), 0.004)
        # the extensor tendon from the wrist to the knuckle, a fine ridge on the back of the hand
        palm = smin(palm, capsule(p, (fd["base"][0] * 0.6, 0.0105, 0.012), np.array(fd["mcp"]) + (0, r0 * 0.78, -0.006), 0.0019, 0.0021), 0.0035)
    fa = smin(forearm_field(p_arm), ellipsoid(p_arm, (0.0, 0.002, -FOREARM), (0.033, 0.031, 0.028)), 0.01)   # rounded at the elbow
    # the forearm's muscles: the brachioradialis swelling on the thumb side toward the elbow, the flexors under,
    # the extensors on the back; they thin into tendons at the lower third, so the wrist tapers
    fa = smin(fa, ellipsoid(p_arm, (-0.0230, 0.0090, -0.1800), (0.0200, 0.0190, 0.0750), rot((0, 1, 0), 0.10)), 0.016)
    fa = smin(fa, ellipsoid(p_arm, (0.0040, -0.0190, -0.1550), (0.0300, 0.0170, 0.0850)), 0.018)
    fa = smin(fa, ellipsoid(p_arm, (0.0080, 0.0200, -0.1650), (0.0240, 0.0140, 0.0700)), 0.016)
    wrist = smin(palm, fa, 0.026)
    wrist = smin(wrist, ellipsoid(p_arm, (0.0240, 0.0070, -0.0060), (0.0045, 0.0040, 0.0060)), 0.007)   # the ulna's head
    # the fingers: each blended into the palm, never into each other
    chains = []
    joints = []
    for fd, fl in zip(FINGERS, pose["flex"]):
        pts, _ = finger_chain(fd, fl, pose.get("splay", 1.0))
        joints.append(pts)
        r = fd["r"]
        f = capsule(p, pts[0], pts[1], r[0], r[1])
        f = smin(f, capsule(p, pts[1], pts[2], r[1] * 0.98, r[2]), 0.002)
        f = smin(f, capsule(p, pts[2], pts[3] - unit(pts[3] - pts[2]) * r[3] * 0.4, r[2] * 0.98, r[3]), 0.002)
        f = smin(f, ellipsoid(p, pts[1], (r[1] * 1.08, r[1] * 1.06, r[1] * 1.06)), 0.002)   # PIP knuckle
        f = smin(f, ellipsoid(p, pts[2], (r[2] * 1.04, r[2] * 1.03, r[2] * 1.03)), 0.0015)   # DIP
        chains.append((f, 0.0045))
    tp = thumb_chain(pose)
    tr = THUMB_R
    t = capsule(p, tp[0], tp[1], tr[0], tr[1])
    t = smin(t, capsule(p, tp[1], tp[2], tr[1] * 0.98, tr[2]), 0.002)
    t = smin(t, capsule(p, tp[2], tp[3] - unit(tp[3] - tp[2]) * tr[4] * 0.4, tr[3], tr[4]), 0.002)
    t = smin(t, ellipsoid(p, tp[1], (tr[1] * 1.08,) * 3), 0.002)
    chains.append((t, 0.009))
    joints = [[Rw @ q for q in pts] for pts in joints]
    tp = [Rw @ q for q in tp]
    return wrist, chains, joints, tp


def hand_field(p_arm, pose):
    wrist, chains, joints, tp = hand_parts(p_arm, pose)
    total = None
    for f, k in chains:
        u = smin(wrist, f, k)
        total = u if total is None else np.minimum(total, u)
    return total, joints, tp


def uparm_field(p):
    """The upper arm from the elbow (origin) up +z to the shoulder: the elbow's point at the back, the biceps, the
    short sleeve from 0.10 up (a hem, a little slack, two soft folds)."""
    zs = np.array([0.03, 0.0, 0.06, 0.14, 0.22, 0.30, 0.34])
    rx = np.array([0.030, 0.036, 0.039, 0.043, 0.046, 0.050, 0.050])
    ry = np.array([0.028, 0.035, 0.040, 0.046, 0.048, 0.052, 0.052])
    z = p[:, 2]
    zz = np.clip(z, -0.03, 0.34)
    zsv = np.array([-0.03, 0.0, 0.06, 0.14, 0.22, 0.30, 0.34])
    ax = np.interp(zz, zsv, rx); ay = np.interp(zz, zsv, ry)
    q = np.sqrt((p[:, 0] / ax) ** 2 + (p[:, 1] / ay) ** 2)
    d = (q - 1.0) * np.minimum(ax, ay)
    over = np.maximum(z - 0.34, 0.0) + np.maximum(-0.03 - z, 0.0)
    skin = np.where(over > 0, np.sqrt(np.maximum(d, 0) ** 2 + over ** 2), d)
    skin = smin(skin, ellipsoid(p, (0.0, -0.012, 0.0), (0.024, 0.022, 0.026)), 0.01)   # the olecranon at the back
    # the sleeve: a shell 6 mm out from 0.105 up, the hem rolled
    hem = 0.105
    ang = np.arctan2(p[:, 1], p[:, 0])
    fold = (0.0020 * np.sin(ang * 2.0 + 0.6) * np.clip((z - hem) / 0.08, 0, 1) + 0.0012 * np.sin(z * 70.0 + ang * 3.0)
            + 0.0008 * np.sin(z * 150.0 - ang * 5.0) * np.clip((0.2 - (z - hem)) / 0.2, 0, 1))   # creases near the hem
    sl = (q - 1.0) * np.minimum(ax, ay) - 0.0062 - fold
    sl = np.maximum(sl, hem - z)
    sl = np.maximum(sl, z - 0.36)
    ring = np.sqrt(((q - 1.0) * np.minimum(ax, ay) - 0.0062) ** 2 + (z - hem - 0.0035) ** 2) - 0.0036   # the rolled hem
    sl = smin(sl, ring, 0.002)
    return skin, sl


# ---------------------------------------------------------------- meshing and colour
def mesh_field(fn, lo, hi, h):
    from skimage import measure
    xs = np.arange(lo[0], hi[0] + h, h); ys = np.arange(lo[1], hi[1] + h, h); zs = np.arange(lo[2], hi[2] + h, h)
    vol = np.empty((len(xs), len(ys), len(zs)), np.float32)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    chunk = 8
    for k0 in range(0, len(zs), chunk):
        zz = zs[k0:k0 + chunk]
        P = np.stack([np.repeat(X[..., None], len(zz), 2), np.repeat(Y[..., None], len(zz), 2),
                      np.broadcast_to(zz, X.shape + (len(zz),))], -1).reshape(-1, 3).astype(np.float32)
        vol[:, :, k0:k0 + chunk] = fn(P).reshape(len(xs), len(ys), len(zz))
    v, f, n, _ = measure.marching_cubes(vol, 0.0, spacing=(h, h, h))
    v = v + np.array(lo, np.float32)
    return v.astype(np.float32), f.astype(np.int32)   # (skimage's winding is outward for a field negative inside)


def field_normals(fn, v, e=0.0004):
    g = np.zeros_like(v)
    for i in range(3):
        d = np.zeros(3, np.float32); d[i] = e
        g[:, i] = fn(v + d) - fn(v - d)
    return g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)


def cavity(fn, v, n):
    """Ambient occlusion from the field: how much the surface's surroundings close in along the normal."""
    occ = np.zeros(len(v), np.float32)
    for dist, w in ((0.0025, 0.9), (0.005, 0.55), (0.009, 0.35), (0.015, 0.2)):
        occ += w * np.clip((dist - fn(v + n * dist)) / dist, 0.0, 1.0)
    return np.clip(1.0 - 0.42 * occ, 0.45, 1.0)


def seg_param(v, a, b):
    ba = b - a
    t = np.clip(((v - a) @ ba) / (ba @ ba), 0, 1)
    q = v - (a + t[:, None] * ba)
    return t, np.linalg.norm(q, axis=1), q


def hand_colour(v, n, fn, joints, tp, rng):
    col = np.tile(SKIN, (len(v), 1))
    dorsal = np.clip(n[:, 1], -1, 1)
    # the palm side and the inside of the fingers lighter and pinker, the back a touch darker and browner
    palmk = np.clip(-dorsal, 0, 1)
    col = col * (1 + 0.06 * palmk[:, None]) + np.array([10, 0, -2]) * palmk[:, None]
    col = col * (1 - 0.04 * np.clip(dorsal, 0, 1)[:, None])
    # per finger: redder knuckles and tips, creases at the joints (both sides), nails
    for pts in joints + [tp]:
        thumb = pts is tp
        for j in range(1, 3):
            a, b = pts[j - 1], pts[j]
            # joint crease rings round each joint: dark lines on the palm side, wrinkle bands on the back
            jp = pts[j]
            axis = unit(pts[j + 1] - pts[j - 1]) if j + 1 < len(pts) else unit(pts[j] - pts[j - 1])
            s = (v - jp) @ axis
            near = np.linalg.norm(v - jp, axis=1) < 0.016
            dirj = unit(np.cross(axis, np.cross(np.array([0, 1.0, 0]), axis)) + 1e-9) if not thumb else axis
            for off in (-0.0015, 0.0012) if j == 1 else (-0.001, 0.001):
                line = np.exp(-((s - off) / 0.00055) ** 2) * near * (0.25 * palmk + 0.07 * np.clip(dorsal, 0, 1) + 0.03)
                col = col * (1 - line[:, None])
            red = np.exp(-(np.linalg.norm(v - jp, axis=1) / 0.009) ** 2)
            col = col + np.array([12, -6, -8]) * red[:, None] * np.clip(dorsal, 0.2, 1)[:, None]
        # the nail on the distal phalanx's back
        a, b = pts[-2], pts[-1]
        t, rad, q = seg_param(v, a, b)
        dax = unit(b - a)
        back = unit(np.array([0, 1.0, 0]) - dax * dax[1]) if not thumb else unit(np.cross(dax, np.array([0, 0, 1.0])) * -1)
        if thumb:   # the thumb nail faces away from the palm: the side of the distal segment opposite the index
            back = unit(np.array([-0.6, 0.6, 0.0]) - dax * (dax @ np.array([-0.6, 0.6, 0.0])))
        qn = q / np.maximum(rad[:, None], 1e-9)
        facing = qn @ back
        nail = np.clip((facing - 0.45) / 0.15, 0, 1) * np.clip((t - 0.25) / 0.08, 0, 1) * (rad < 0.012)
        tip = nail * np.clip((t - 0.88) / 0.05, 0, 1)
        lun = nail * np.exp(-((t - 0.30) / 0.03) ** 2)
        nailc = np.array([214, 168, 156])
        col = col * (1 - nail[:, None]) + nailc * nail[:, None]
        col = col + np.array([30, 34, 30]) * tip[:, None] + np.array([16, 18, 16]) * lun[:, None]
        rim = np.exp(-((facing - 0.45) / 0.05) ** 2) * np.clip((t - 0.25) / 0.08, 0, 1) * (rad < 0.012)
        col = col * (1 - 0.18 * rim[:, None])
        tipred = np.exp(-(np.linalg.norm(v - b, axis=1) / 0.012) ** 2) * (1 - nail)
        col = col + np.array([10, -4, -4]) * tipred[:, None]
    # the veins on the back of the hand and the wrist: faint blue-green lines
    for (a, b) in (((-0.012, 0.010, 0.060), (-0.006, 0.014, -0.030)), ((0.010, 0.011, 0.055), (0.004, 0.015, -0.020)),
                   ((-0.006, 0.014, 0.020), (0.010, 0.012, 0.030))):
        t, rad, q = seg_param(v, np.array(a), np.array(b))
        dd = np.linalg.norm(q[:, [0, 2]], axis=1)
        vein = np.exp(-(dd / 0.0016) ** 2) * np.clip(dorsal, 0, 1) * 0.5
        col = col + np.array([-14, -4, 6]) * vein[:, None]
    # the wrist's crease on the palm side
    wl = np.exp(-((v[:, 2] - 0.004) / 0.0009) ** 2) * palmk + np.exp(-((v[:, 2] - 0.012) / 0.0008) ** 2) * palmk
    col = col * (1 - 0.18 * wl[:, None])
    # the forearm: a little paler on the inside, faint hair shading on the back toward the elbow
    fa = np.clip(-v[:, 2] / 0.05, 0, 1)
    col = col * (1 - 0.05 * fa[:, None] * np.clip(dorsal, 0, 1)[:, None]) + np.array([6, 4, 4]) * (fa * palmk)[:, None]
    # fine hair on the back of the forearm and the wrist (short dark strokes along the arm) and a few freckles
    def hash3(q):
        h = np.sin(q[:, 0] * 127.1 + q[:, 1] * 311.7 + q[:, 2] * 74.7) * 43758.5453
        return h - np.floor(h)
    cell = np.floor(v / np.array([0.0008, 0.0008, 0.0026]))
    hair = (hash3(cell) > 0.86) * np.clip(dorsal + 0.2, 0, 1) * np.clip((-v[:, 2] - 0.005) / 0.03, 0, 1)
    col = col * (1 - 0.05 * hair[:, None])
    fr = (hash3(np.floor(v / 0.0016) + 7.0) > 0.985) * np.clip(dorsal, 0, 1)
    col = col * (1 - 0.12 * fr[:, None]) + np.array([4, -2, -4]) * fr[:, None]
    return np.clip(col, 0, 255)


def write_ply(path, v, f, c):
    with open(path, "wb") as fh:
        fh.write(("ply\nformat binary_little_endian 1.0\nelement vertex %d\nproperty float x\nproperty float y\nproperty float z\n"
                  "property uchar red\nproperty uchar green\nproperty uchar blue\nelement face %d\nproperty list uchar int vertex_indices\nend_header\n"
                  % (len(v), len(f))).encode())
        rec = np.zeros(len(v), dtype=[("p", "<f4", 3), ("c", "u1", 3)])
        rec["p"] = v; rec["c"] = np.clip(c, 0, 255).astype(np.uint8)
        fh.write(rec.tobytes())
        fr = np.zeros(len(f), dtype=[("n", "u1"), ("i", "<i4", 3)])
        fr["n"] = 3; fr["i"] = f
        fh.write(fr.tobytes())


def build_hand(pose_name, work, h):
    pose = POSES[pose_name]
    fn = lambda P: hand_field(P, pose)[0]
    _, joints, tp = hand_field(np.zeros((1, 3), np.float32), pose)
    v, f = mesh_field(fn, (-0.085, -0.125, -FOREARM - 0.040), (0.080, 0.050, 0.220), h)
    n = field_normals(fn, v)
    c = hand_colour(v, n, fn, joints, tp, np.random.default_rng(3))
    path = os.path.join(work, f"hand_{pose_name}.ply")
    write_ply(path, v, f, c)
    print(f"hand {pose_name}: {len(v)} verts {len(f)} tris (high)")
    return path


def build_uparm(work, h):
    sk = lambda P: uparm_field(P)[0]
    sl = lambda P: uparm_field(P)[1]
    out = []
    for name, fn in (("skin", sk), ("sleeve", sl)):
        v, f = mesh_field(fn, (-0.065, -0.065, -0.06), (0.065, 0.065, 0.37), h * 1.4)
        n = field_normals(fn, v)
        if name == "skin":
            c = np.tile(SKIN * 0.97, (len(v), 1))
        else:
            c = np.tile(SLEEVE, (len(v), 1))
            hem = np.exp(-((v[:, 2] - 0.112) / 0.0018) ** 2)
            ang = np.arctan2(v[:, 1], v[:, 0])
            seam = np.exp(-((ang + 1.5708) / 0.03) ** 2) + np.exp(-((v[:, 2] - 0.118) / 0.0007) ** 2) * 0.6   # the seam, the hem's stitching
            c = c * (1 - 0.25 * hem[:, None] - 0.18 * seam[:, None])
        c = c * cavity(fn, v, n)[:, None]
        path = os.path.join(work, f"uparm_{name}.ply")
        write_ply(path, v, f, c)
        out.append(path)
        print(f"uparm {name}: {len(v)} verts {len(f)} tris (high)")
    return out


def main():
    work = sys.argv[1]
    os.makedirs(work, exist_ok=True)
    args = sys.argv[2:]
    blender = args[args.index("--blender") + 1] if "--blender" in args else None
    imp = args[args.index("--import") + 1] if "--import" in args else None
    only = args[args.index("--only") + 1].split(",") if "--only" in args else ["hand", "uparm"]
    h = 0.0009
    jobs = []
    if "hand" in only:   # the relaxed hand: the rest mesh every pose is made from (tools/fp_arms_pose.py)
        jobs.append(("fp_hand_base", [build_hand("relax", work, h)], ["skin"], 8000, os.path.join(work, "base")))
    if "uparm" in only:
        jobs.append(("fp_uparm_right", build_uparm(work, h), ["skin", "sleeve"], 2400, imp))
    if not blender:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for name, plys, nodes, tris, dest in jobs:
        glb = os.path.join(work, name + ".glb")
        cmd = [blender, "-b", "--factory-startup", "-noaudio", "--python", os.path.join(here, "fp_arms_bake.py"), "--",
               glb, str(SCALE), str(tris)] + [f"{n}={p}" for n, p in zip(nodes, plys)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL if "-q" in args else None)
        man = os.path.join(work, f"manifest_{name}.json")
        json.dump({"models": [dict(name=name, glb=os.path.basename(glb), scale=1.0, texture_max=512 if name == "fp_uparm_right" else 1024,
                                   forward="+z", _licence="procedural (this repository, tools/gen_fp_arms.py)")]}, open(man, "w"), indent=1)
        if dest:
            os.makedirs(dest, exist_ok=True)
            subprocess.run([sys.executable, os.path.join(here, "import_assets.py"), man, dest], check=True, stdout=subprocess.DEVNULL)
    if imp and "hand" in only:
        subprocess.run([sys.executable, os.path.join(here, "fp_arms_pose.py"), work, imp, "--blender", blender], check=True)


if __name__ == "__main__":
    main()
