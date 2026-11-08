#!/usr/bin/env python3
"""Procedural pedestrian clips for the Rocketbox avatars: the states GTA2 shows
that the Rocketbox library has no clip for (it has walks, runs, idles, crouches
and gestures, no fighting, no dying).

    gen_ped_clips.py <avatar.glb> <idle.glb> <out.json>

The clips are key poses on the Biped skeleton, expressed as rotations about
the avatar's own axes (x right, y up, z forward) applied over a base pose (the
idle clip's first frame, arms down), and resolved root-down into local joint
rotations, so the same file poses every avatar that shares the skeleton. The
importer (tools/import_assets.py, "animations_json") merges them by joint name.

Clips: punch (0.5 s, one shot), the shooting stances aim (pistol, two-handed
grip), aim_dual, aim_heavy (rifle), aim_launcher (rocket launcher on the
shoulder), aim_flame (hip fire) - each with its recoil kick as the first 0.12 s,
restarted by the renderer on every shot - throw (0.62 s underarm lob, one shot),
handsup (held, the arrest), fall (0.7 s into lying on the back, held at its end:
dead or knocked down), hit (0.5 s stagger); getin/getout come from Rocketbox's
crouch clips instead.

ACTIONS-3D-4 (8 Nov 2026): guard, punch (right cross) and punch2 (left jab) for the
combo, hit_head / hit_head2 (taking a punch), enter_car / exit_car (upper-body layers
over legs that step the ground the game moves him), grab_door_r / _l (running beside a
moving car, a hand on the door), turn_step (a legs-only layer: stepping on the spot),
sprint (the run with a wider stride); and check_arms, which reports any clip with an
elbow, forearm or hand inside the torso. Layer kinds: upper=True (Bip01 Spine1 and up),
lower=True (the thighs and below), joints={...} (just those).
"""
import json, math, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_assets import load_glb, accessor  # noqa: E402


def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qinv(q):
    x, y, z, w = q
    return (-x, -y, -z, w)


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def qaxis(axis, deg):
    h = math.radians(deg) * 0.5
    s = math.sin(h)
    n = math.sqrt(sum(c * c for c in axis)) or 1.0
    return (axis[0] / n * s, axis[1] / n * s, axis[2] / n * s, math.cos(h))


def qrot(q, v):
    """Rotate vector v by quaternion q."""
    x, y, z, w = q
    vx, vy, vz = v
    # q * (v, 0) * q^-1
    ix = w * vx + y * vz - z * vy
    iy = w * vy + z * vx - x * vz
    iz = w * vz + x * vy - y * vx
    iw = -x * vx - y * vy - z * vz
    return (ix * w + iw * -x + iy * -z - iz * -y,
            iy * w + iw * -y + iz * -x - ix * -z,
            iz * w + iw * -z + ix * -y - iy * -x)


def slerp(a, b, t):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b = tuple(-c for c in b); dot = -dot
    if dot > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(dot)
    s = math.sin(th)
    return tuple((math.sin((1 - t) * th) * x + math.sin(t * th) * y) / s for x, y in zip(a, b))


class Skeleton:
    def __init__(self, avatar_glb, idle_glb):
        g, b = load_glb(avatar_glb)
        self.nodes = g["nodes"]
        self.names = [n.get("name") for n in self.nodes]
        self.index = {n: i for i, n in enumerate(self.names) if n}
        self.parent = [-1] * len(self.nodes)
        for i, n in enumerate(self.nodes):
            for c in n.get("children", []):
                self.parent[c] = i
        self.rest_t = [tuple(n.get("translation", [0, 0, 0])) for n in self.nodes]
        self.rest_r = [tuple(n.get("rotation", [0, 0, 0, 1])) for n in self.nodes]
        # The base pose: the idle clip's first key for every joint it animates.
        self.base_r = list(self.rest_r)
        self.base_t = list(self.rest_t)
        gi, bi = load_glb(idle_glb)
        inames = [n.get("name") for n in gi["nodes"]]
        for a in gi.get("animations", [])[:1]:
            for ch in a["channels"]:
                tgt = ch["target"]
                if "node" not in tgt:
                    continue
                nm = inames[tgt["node"]]
                if nm not in self.index:
                    continue
                sm = a["samplers"][ch["sampler"]]
                vals = accessor(gi, bi, sm["output"])
                if tgt["path"] == "rotation":
                    self.base_r[self.index[nm]] = tuple(vals[0])
                elif tgt["path"] == "translation" and nm != "Bip01":
                    self.base_t[self.index[nm]] = tuple(vals[0])
        # Order root-down.
        self.order = []
        seen = set()

        def visit(i):
            if i in seen:
                return
            if self.parent[i] >= 0:
                visit(self.parent[i])
            seen.add(i); self.order.append(i)
        for i in range(len(self.nodes)):
            visit(i)

    def world_rest(self):
        """World rotation and position of every joint in the base pose."""
        wr = [None] * len(self.nodes); wp = [None] * len(self.nodes)
        for i in self.order:
            p = self.parent[i]
            if p < 0:
                wr[i] = self.base_r[i]; wp[i] = self.base_t[i]
            else:
                wr[i] = qnorm(qmul(wr[p], self.base_r[i]))
                wp[i] = tuple(a + c for a, c in zip(wp[p], qrot(wr[p], self.base_t[i])))
        return wr, wp

    def pose(self, deltas, root_offset=(0, 0, 0)):
        """Local rotations for a pose: deltas = {joint: [(axis, deg), ...]} as world-axis
        rotations about the joint, applied over the base pose, resolved root-down so a
        child's delta composes with its parent's."""
        local_r = list(self.base_r)
        wr = [None] * len(self.nodes)
        for i in self.order:
            p = self.parent[i]
            pw = (0.0, 0.0, 0.0, 1.0) if p < 0 else wr[p]
            q = self.base_r[i]
            for axis, deg in deltas.get(self.names[i], []):
                d = qaxis(axis, deg)
                # world delta applied to this joint: local' = pw^-1 * d * pw * local
                q = qnorm(qmul(qinv(pw), qmul(d, qmul(pw, q))))
            local_r[i] = q
            wr[i] = qnorm(qmul(pw, q))
        root = self.index["Bip01"]
        t = tuple(a + b for a, b in zip(self.base_t[root], root_offset))
        return local_r, {root: t}


# Avatar axes (after FBX2glTF, measured from the base pose: nose and toes at +z,
# the right hand at -x): y up, faces +z, his right is -x.
RIGHT = (-1, 0, 0); UP = (0, 1, 0); FWD = (0, 0, 1)
# About his right axis by +90 brings an arm hanging down (0,-1,0) to forward (0,0,1).
R = "Bip01 R UpperArm"; RF = "Bip01 R Forearm"; L = "Bip01 L UpperArm"; LF = "Bip01 L Forearm"
SP = "Bip01 Spine1"; SP2 = "Bip01 Spine2"; HEAD = "Bip01 Head"; ROOT = "Bip01"
RT = "Bip01 R Thigh"; RC = "Bip01 R Calf"; LT = "Bip01 L Thigh"; LC = "Bip01 L Calf"


def upper_body(sk):
    """The joints of the upper-body layer: Bip01 Spine1 and everything under it
    (chest, neck, head, both arms). The thighs hang off Bip01 Spine, below it."""
    top = sk.index[SP]
    keep = set()
    for i in range(len(sk.nodes)):
        j = i
        while j >= 0:
            if j == top:
                keep.add(sk.names[i]); break
            j = sk.parent[j]
    return keep


def mirror(deltas):
    """The left-right mirror of a pose: L and R joints swapped, turns about the up
    and forward axes negated (the right axis is the mirror plane's normal)."""
    out = {}
    for joint, rots in deltas.items():
        other = joint.replace(" L ", " @ ").replace(" R ", " L ").replace(" @ ", " R ")
        out[other] = [(axis, deg if axis == RIGHT else -deg) for axis, deg in rots]
    return out


def ancestors(sk, i):
    """i and every joint above it."""
    out = []
    while i >= 0:
        out.append(i); i = sk.parent[i]
    return out


def lower_body(sk):
    """The joints of a legs-only layer: both thighs and everything under them."""
    keep = set()
    for i in range(len(sk.nodes)):
        j = i
        while j >= 0:
            if sk.names[j] in (RT, LT):
                keep.add(sk.names[i]); break
            j = sk.parent[j]
    return keep


def clip_keys(sk, name, keys, loop=False, upper=False, lower=False, joints=None):
    """keys: [(time, deltas, root_offset)] -> channels keyed by node name.

    upper=True writes a layer clip: only the joints from Bip01 Spine1 up
    (upper_body) get channels, and no root translation. The renderer draws such a
    clip blended at just under full weight over the walk, run or idle, and since a
    joint the second clip has no channel for keeps the first clip's value
    (model_store.cpp SampleClip writes over a copy of the first pose), the legs
    and hips keep walking while the arms hold the weapon."""
    poses = [(t, sk.pose(d, ro)) for t, d, ro in keys]
    keep = set(joints) if joints else (upper_body(sk) if upper else (lower_body(sk) if lower else None))
    channels = {}
    for i, nm in enumerate(sk.names):
        if not nm or (keep is not None and nm not in keep):
            continue
        rots = [(t, p[0][i]) for t, p in poses]
        # Keep every joint (the base pose differs from the rest pose).
        channels[nm] = {"rotation": {"times": [t for t, _ in rots], "values": [list(r) for _, r in rots]}}
    if not upper and not lower and not joints:
        root = sk.index[ROOT]
        channels[ROOT]["translation"] = {"times": [t for t, _ in poses], "values": [list(p[1][root]) for _, p in poses]}
    return {"name": name, "loop": loop, "upper": upper, "lower": lower, "channels": channels}


def clip_from_glb(sk, path):
    """A Rocketbox clip as key times and, per key, every joint's local rotation
    (the base pose where the clip has no channel)."""
    g, b = load_glb(path)
    names = [n.get("name") for n in g["nodes"]]
    a = g["animations"][0]
    chans = {}
    times = None
    for ch in a["channels"]:
        nm = names[ch["target"]["node"]]
        if ch["target"]["path"] != "rotation" or nm not in sk.index: continue
        sm = a["samplers"][ch["sampler"]]
        t = [x[0] for x in accessor(g, b, sm["input"])]
        if times is None or len(t) > len(times): times = t
        chans[sk.index[nm]] = (t, [tuple(v) for v in accessor(g, b, sm["output"])])
    seq = []
    for k in range(len(times)):
        lr = list(sk.base_r)
        for i, (t, vals) in chans.items():
            lr[i] = vals[min(k, len(vals) - 1)]
        seq.append(lr)
    return [round(t, 5) for t in times], seq


def run_root_y(sk, path):
    g, b = load_glb(path)
    names = [n.get("name") for n in g["nodes"]]
    a = g["animations"][0]
    for ch in a["channels"]:
        if names[ch["target"]["node"]] == ROOT and ch["target"]["path"] == "translation":
            return [v[1] for v in accessor(g, b, a["samplers"][ch["sampler"]]["output"])]
    return []


def qpow(q, k):
    x, y, z, w = qnorm(q)
    w = max(-1.0, min(1.0, w))
    th = math.acos(w)
    s = math.sin(th)
    if s < 1e-6: return (0.0, 0.0, 0.0, 1.0)
    th2 = th * k
    return (x / s * math.sin(th2), y / s * math.sin(th2), z / s * math.sin(th2), math.cos(th2))


def amplify(sk, seq, gains, offsets=None):
    """Each named joint's rotation swung `gain` times as far from its mean over the clip;
    `offsets` {joint: (axis, deg)} turns a joint by a fixed world-axis amount over the whole
    clip (the sprint's arms a little out from the hips)."""
    out = [list(lr) for lr in seq]
    for nm, k in gains.items():
        i = sk.index[nm]
        ref = seq[0][i]
        acc = [0.0, 0.0, 0.0, 0.0]
        for lr in seq:
            q = lr[i]
            if sum(a * b for a, b in zip(q, ref)) < 0: q = tuple(-c for c in q)
            acc = [a + c for a, c in zip(acc, q)]
        mean = qnorm(tuple(acc))
        for f, lr in enumerate(seq):
            d = qmul(qinv(mean), lr[i])
            if d[3] < 0: d = tuple(-c for c in d)
            out[f][i] = qnorm(qmul(mean, qpow(d, k)))
    for nm, (axis, deg) in (offsets or {}).items():
        i = sk.index[nm]
        for f in range(len(out)):
            wr, _ = fk(sk, out[f])
            p = sk.parent[i]
            pw = wr[p] if p >= 0 else (0.0, 0.0, 0.0, 1.0)
            out[f][i] = qnorm(qmul(qinv(pw), qmul(qaxis(axis, deg), qmul(pw, out[f][i]))))
    return out


def fk(sk, lr, root_t=None):
    wr = [None] * len(sk.nodes); wp = [None] * len(sk.nodes)
    for i in sk.order:
        p = sk.parent[i]
        t = sk.base_t[i] if not (root_t and i in root_t) else root_t[i]
        if p < 0:
            wr[i] = lr[i]; wp[i] = t
        else:
            wr[i] = qnorm(qmul(wr[p], lr[i]))
            wp[i] = tuple(a + c for a, c in zip(wp[p], qrot(wr[p], t)))
    return wr, wp


def stance_stride(sk, times, seq):
    """How far a cycle's feet reach fore and aft of the body (the larger foot's
    excursion along +z, metres). A run's ground per cycle scales with it, so the
    ratio of two clips' excursions is the ratio of their strides (the run itself is
    measured from its root motion on import)."""
    best = 0.0
    for f in (sk.index["Bip01 R Foot"], sk.index["Bip01 L Foot"]):
        zs = [fk(sk, lr)[1][f][2] for lr in seq]
        best = max(best, max(zs) - min(zs))
    return best


def check_arms(sk, clips):
    """Arms through the torso: for every clip, at its keys and halfway between
    them, the elbows, the middle of each forearm and the hands against the torso
    (an elliptic cylinder from the pelvis to the neck, 13 x 10 cm half-axes plus a
    3.5 cm limb radius, in the torso's own frame). Prints any that go inside."""
    top = sk.index["Bip01 Neck"]; bot = sk.index["Bip01 Pelvis"]
    shR, shL = sk.index[R], sk.index[L]
    pts = {"R elbow": (sk.index[RF], None), "L elbow": (sk.index[LF], None),
           "R forearm": (sk.index[RF], sk.index["Bip01 R Hand"]), "L forearm": (sk.index[LF], sk.index["Bip01 L Hand"]),
           "R hand": (sk.index["Bip01 R Hand"], None), "L hand": (sk.index["Bip01 L Hand"], None)}
    bad = 0
    for c in clips:
        rots = {nm: ch["rotation"] for nm, ch in c["channels"].items() if "rotation" in ch}
        if not rots: continue
        times = sorted(set(t for r in rots.values() for t in r["times"]))
        samples = times + [(a + b) / 2 for a, b in zip(times, times[1:])]
        worst = None
        for t in samples:
            lr = list(sk.base_r)
            for nm, r in rots.items():
                ts, vs = r["times"], r["values"]
                k = 0
                while k + 1 < len(ts) and ts[k + 1] <= t: k += 1
                k2 = min(k + 1, len(ts) - 1)
                f = (t - ts[k]) / (ts[k2] - ts[k]) if ts[k2] > ts[k] else 0.0
                lr[sk.index[nm]] = slerp(tuple(vs[k]), tuple(vs[k2]), f)
            _, wp = fk(sk, lr)
            up = [a - b for a, b in zip(wp[top], wp[bot])]
            ul = math.sqrt(sum(x * x for x in up)); up = [x / ul for x in up]
            lat = [a - b for a, b in zip(wp[shL], wp[shR])]
            d = sum(a * b for a, b in zip(lat, up)); lat = [a - d * b for a, b in zip(lat, up)]
            ll = math.sqrt(sum(x * x for x in lat)); lat = [x / ll for x in lat]
            fwd = (up[1] * lat[2] - up[2] * lat[1], up[2] * lat[0] - up[0] * lat[2], up[0] * lat[1] - up[1] * lat[0])
            for label, (a, b) in pts.items():
                p = wp[a] if b is None else tuple((x + y) / 2 for x, y in zip(wp[a], wp[b]))
                rel = [x - y for x, y in zip(p, wp[bot])]
                h = sum(x * y for x, y in zip(rel, up))
                if h < 0.06 or h > ul - 0.06: continue
                x = sum(x * y for x, y in zip(rel, lat)); z = sum(x * y for x, y in zip(rel, fwd))
                e = (x / (0.13 + 0.035)) ** 2 + (z / (0.10 + 0.035)) ** 2
                if e < 1.0 and (worst is None or e < worst[0]): worst = (e, label, round(t, 3), round(x, 3), round(z, 3), round(h, 3))
        if worst:
            bad += 1
            print("  ARMS THROUGH THE TORSO: %-14s %s at t=%.3f (depth %.2f; across %.3f ahead %.3f up %.3f m)" % (c["name"], worst[1], worst[2], 1 - worst[0], worst[3], worst[4], worst[5]))
    print("  arm/torso check: %d clip(s) with a limb inside the torso" % bad)


def main():
    avatar, idle, out = sys.argv[1:4]
    sk = Skeleton(avatar, idle)
    wr, wp = sk.world_rest()
    rh, lh = wp[sk.index["Bip01 R Hand"]], wp[sk.index["Bip01 L Hand"]]
    print("base pose: right hand at x=%.2f, left hand at x=%.2f, head y=%.2f, root y=%.2f" %
          (rh[0], lh[0], wp[sk.index[HEAD]][1], wp[sk.index[ROOT]][1]))
    root_y = sk.base_t[sk.index[ROOT]][1]
    clips = []

    # ---- Fists (ACTIONS-3D-4) ----------------------------------------------
    # Upper-body layers (Bip01 Spine1 and up), so the legs keep walking or stand
    # under them. GTA2 swings the fists over eight frames of 0.1 s (sprite frames
    # 115-122, repeated while the key is held), so a swing is 0.8 s; the renderer
    # restarts the clip on every repeat and alternates "punch" (a right cross) and
    # "punch2" (a left jab) for a combo. The arm angles were fitted to hand and
    # elbow targets on the base pose (fists at the chin, the strike at chin height
    # 0.55 m ahead), elbows never past straight; the hip and shoulder turn comes
    # from Spine1 / Spine2 (the thighs hang off Bip01 Spine, below the layer).
    # +UP turns the shoulders to his left (the right shoulder forward); +RIGHT
    # leans the torso back, -RIGHT forward.
    def fists(torso, l, r, head=None):
        d = {k: list(v) for k, v in torso.items()}
        d[L] = [(RIGHT, l[0]), (UP, l[1])]; d[LF] = [(RIGHT, l[2])]
        d[R] = [(RIGHT, r[0]), (UP, r[1])]; d[RF] = [(RIGHT, r[2])]
        if head: d[HEAD] = head
        return d
    g_l, g_r = (56, -19, 97), (46, 12, 103)          # the guard: both fists at the chin
    guard_pose = fists({SP: [(UP, -6)]}, g_l, g_r)
    clips.append(clip_keys(sk, "guard", [(0.0, guard_pose, (0, 0, 0)), (1.0, guard_pose, (0, 0, 0))], loop=True, upper=True))
    # Right cross: the wind-up (right shoulder and fist back, the hips turned away),
    # the strike with the torso leading (the shoulders turn through 50 degrees and
    # lean in, the arm straightens last), a follow-through, the recovery to the
    # guard; the left fist stays at the chin all the way.
    clips.append(clip_keys(sk, "punch", [
        (0.00, guard_pose, (0, 0, 0)),
        (0.20, fists({SP: [(UP, -24), (RIGHT, 4)], SP2: [(UP, -8)]}, (56, -31, 114), (-3, 45, 146)), (0, 0, 0)),
        (0.30, fists({SP: [(UP, 10), (RIGHT, -4)], SP2: [(UP, 4)]}, (57, -6, 95), (59, 19, 65), [(UP, -6)]), (0, 0, 0)),
        (0.36, fists({SP: [(UP, 26), (RIGHT, -8)], SP2: [(UP, 10)]}, (57, 12, 104), (91, 19, 4), [(UP, -12)]), (0, 0, 0)),
        (0.44, fists({SP: [(UP, 32), (RIGHT, -10)], SP2: [(UP, 12)]}, (57, 20, 111), (92, 21, 4), [(UP, -14)]), (0, 0, 0)),
        (0.60, fists({SP: [(UP, 6), (RIGHT, -3)]}, (57, -12, 94), (47, 22, 90)), (0, 0, 0)),
        (0.80, guard_pose, (0, 0, 0)),
    ], upper=True))
    # Left jab: a short load (left shoulder back a little), the snap out with the
    # shoulders turning the other way, the right fist guarding the chin.
    clips.append(clip_keys(sk, "punch2", [
        (0.00, guard_pose, (0, 0, 0)),
        (0.16, fists({SP: [(UP, 10)]}, (38, -9, 123), (46, 21, 106)), (0, 0, 0)),
        (0.26, fists({SP: [(UP, -12), (RIGHT, -3)], SP2: [(UP, -4)]}, (67, -18, 67), (47, 7, 103), [(UP, 5)]), (0, 0, 0)),
        (0.32, fists({SP: [(UP, -24), (RIGHT, -6)], SP2: [(UP, -8)]}, (100, -20, 4), (47, -4, 110), [(UP, 10)]), (0, 0, 0)),
        (0.40, fists({SP: [(UP, -28), (RIGHT, -8)], SP2: [(UP, -10)]}, (100, -20, 4), (47, -10, 115), [(UP, 12)]), (0, 0, 0)),
        (0.58, fists({SP: [(UP, -6)]}, (53, -19, 92), (46, 12, 103)), (0, 0, 0)),
        (0.80, guard_pose, (0, 0, 0)),
    ], upper=True))
    # Taking a punch (upper layer, 0.55 s): the head snaps back and turns away from
    # the fist, the chest recoils, both hands come up; then back. The renderer pushes
    # the figure back a step (the legs walk it) and, if the game knocks him down,
    # the lying clip takes over. "hit_head" turns his head to his right (a right
    # cross to his left cheek), "hit_head2" the mirror.
    hit1 = fists({SP: [(RIGHT, 8), (UP, -12)], SP2: [(RIGHT, 8)]}, (29, -15, 111), (17, 8, 105), [(RIGHT, 22), (UP, -20), (FWD, -10)])
    hit2 = fists({SP: [(RIGHT, 5), (UP, -6)], SP2: [(RIGHT, 4)]}, (-9, -45, 75), (-15, 45, 64), [(RIGHT, 10), (UP, -8)])
    hit_keys = [(0.00, {}, (0, 0, 0)), (0.07, hit1, (0, 0, 0)), (0.24, hit2, (0, 0, 0)), (0.55, {}, (0, 0, 0))]
    clips.append(clip_keys(sk, "hit_head", hit_keys, upper=True))
    clips.append(clip_keys(sk, "hit_head2", [(t, mirror(d), ro) for t, d, ro in hit_keys], upper=True))

    # ---- Cars (ACTIONS-3D-4) -----------------------------------------------
    # Upper-body layers over legs that step by the ground the game moves him
    # (the renderer's locomotion), so nothing glides while the game slides him
    # through the door. enter_car (1.3 s): the right hand reaches for the handle
    # (0.35), pulls the door out (0.65) - the renderer holds here while the game
    # says "reaching" (state 3 sub 4) - then he ducks under the roof, left hand on
    # the roof edge, right on the door (0.95), and folds in (1.3) while the game
    # climbs him in (state 3 sub 6). exit_car (0.9 s): from that duck, a hand on
    # the frame and one pushing the door, straightening as he steps out (state 4).
    def leaned(torso, l, r, head=None):
        return fists(torso, l, r, head)
    clips.append(clip_keys(sk, "enter_car", [
        (0.00, {}, (0, 0, 0)),
        (0.35, leaned({SP: [(RIGHT, -12)]}, (5, -9, 27), (55, 5, 6), [(RIGHT, -8)]), (0, 0, 0)),
        (0.65, leaned({SP: [(RIGHT, -8), (UP, -15)]}, (-12, -1, 39), (40, -44, 30)), (0, 0, 0)),
        (0.95, leaned({SP: [(RIGHT, -30)], SP2: [(RIGHT, -10)]}, (83, -3, 56), (57, -45, 67), [(RIGHT, -6)]), (0, 0, 0)),
        (1.30, leaned({SP: [(RIGHT, -38)], SP2: [(RIGHT, -12)]}, (65, -20, 47), (45, 45, 60), [(RIGHT, -4)]), (0, 0, 0)),
    ], upper=True))
    # exit_car is 0.7 s: the game's exit state lasts about 0.8 s, and the figure is
    # upright and on its own feet before it ends (the user's acceptance test: a stand-up
    # and step-out of 0.6-0.8 s, never a crouch held while the game slides him).
    clips.append(clip_keys(sk, "exit_car", [
        (0.00, leaned({SP: [(RIGHT, -35)], SP2: [(RIGHT, -10)]}, (78, 1, 74), (63, -32, 47), [(RIGHT, -6)]), (0, 0, 0)),
        (0.25, leaned({SP: [(RIGHT, -20)], SP2: [(RIGHT, -5)]}, (51, 7, 107), (44, -45, 42)), (0, 0, 0)),
        (0.48, leaned({SP: [(RIGHT, -6)]}, (-2, -22, 35), (-7, 45, 41)), (0, 0, 0)),
        (0.70, {}, (0, 0, 0)),
    ], upper=True))
    # Boarding a car that is moving (the game carries the ped along with it in state 3):
    # he runs beside it - his legs cycle at the car's pace, driven by the ground he
    # covers - with this layer over the run: the near hand out on the door handle at
    # waist height, the torso leaning toward the car, the head turned to it; the far
    # arm is left to the run's swing (only the spine, neck, head and the near arm have
    # channels). "grab_door_r" reaches to his right, "grab_door_l" to his left. The
    # pull-in is enter_car's duck once the game starts the climb.
    arm_r = {sk.names[i] for i in range(len(sk.nodes)) if sk.names[i] and
             any(sk.names[j] == "Bip01 R Clavicle" for j in ancestors(sk, i))}
    grab_joints = arm_r | {SP, SP2, "Bip01 Neck", HEAD}
    grab1 = {SP: [(FWD, 10), (RIGHT, -8)], SP2: [(FWD, 4)], HEAD: [(UP, -25)],
             R: [(RIGHT, 21), (UP, 5), (FWD, -47)], RF: [(RIGHT, 34)]}
    grab2 = {SP: [(FWD, 12), (RIGHT, -10)], SP2: [(FWD, 5)], HEAD: [(UP, -28)],
             R: [(RIGHT, 27), (UP, 5), (FWD, -50)], RF: [(RIGHT, 30)]}
    grab_keys = [(0.0, grab1, (0, 0, 0)), (0.3, grab2, (0, 0, 0)), (0.6, grab1, (0, 0, 0))]
    clips.append(clip_keys(sk, "grab_door_r", grab_keys, loop=True, joints=grab_joints))
    grab_joints_l = {n.replace(" R ", " L ") for n in grab_joints}
    clips.append(clip_keys(sk, "grab_door_l", [(t, mirror(d), ro) for t, d, ro in grab_keys], loop=True, joints=grab_joints_l))

    # ---- Turning on the spot (ACTIONS-3D-4) ----------------------------------
    # A legs-only layer (thighs and below) over the idle: the feet step in place,
    # right then left, a few centimetres up. The renderer advances it by the angle
    # he turns (one cycle per 100 degrees), so the feet step instead of the body
    # pivoting like a statue.
    def step(rt, rc, lt, lc):
        return {RT: [(RIGHT, rt)], RC: [(RIGHT, rc)], LT: [(RIGHT, lt)], LC: [(RIGHT, lc)]}
    clips.append(clip_keys(sk, "turn_step", [
        (0.00, step(0, 0, 0, 0), (0, 0, 0)),
        (0.25, step(18, -34, -2, 2), (0, 0, 0)),
        (0.50, step(0, 0, 0, 0), (0, 0, 0)),
        (0.75, step(-2, 2, 18, -34), (0, 0, 0)),
        (1.00, step(0, 0, 0, 0), (0, 0, 0)),
    ], loop=True, lower=True))

    # The shooting stances. Each aim clip starts with its recoil: key 0 is the
    # kick (the weapon back and up, the shoulders back), key 0.12 s the settle
    # into the stance, which is then held (the renderer clamps a non-looping clip
    # at its last key). The renderer restarts the clip from 0 on every shot the
    # game fires (a flash appearing beside the figure), so the kick plays per shot.
    def stance(name, hold, kick, settle=0.12, sway=None):
        keys = [(0.0, kick, (0, 0, 0)), (settle, hold, (0, 0, 0)), (0.6, hold, (0, 0, 0))]
        if sway:
            keys = [(0.0, kick, (0, 0, 0)), (settle, hold, (0, 0, 0)), (0.6, sway, (0, 0, 0)), (1.2, hold, (0, 0, 0))]
        # An upper-body layer: the legs keep walking under an aim (see clip_keys).
        return clip_keys(sk, name, keys, loop=False, upper=True)
    def merged(a, b):
        d = {k: list(v) for k, v in a.items()}
        for k, v in b.items():
            d[k] = d.get(k, []) + list(v)
        return d
    # Pistol: a two-handed isosceles grip, both arms out, the left hand cupped
    # under the right, the shoulders a little bladed, the head down the sights.
    aim = {R: [(RIGHT, 88), (UP, 18)], RF: [(RIGHT, 4)], L: [(RIGHT, 84), (UP, -26)], LF: [(RIGHT, 12)],
           SP: [(UP, -8)], HEAD: [(UP, 4), (RIGHT, 4)]}
    aim_kick = merged(aim, {R: [(RIGHT, 9)], L: [(RIGHT, 8)], RF: [(RIGHT, 6)], SP: [(RIGHT, -4)], HEAD: [(RIGHT, -3)]})
    clips.append(stance("aim", aim, aim_kick))
    # Dual pistols: both arms straight out and a little spread, each its own gun.
    dual = {R: [(RIGHT, 88), (UP, -10)], RF: [(RIGHT, 2)], L: [(RIGHT, 88), (UP, 10)], LF: [(RIGHT, 2)],
            HEAD: [(RIGHT, 4)]}
    dual_kick = merged(dual, {R: [(RIGHT, 10)], L: [(RIGHT, 10)], SP: [(RIGHT, -4)]})
    clips.append(stance("aim_dual", dual, dual_kick))
    # Hands up: the arrest.
    up = {R: [(RIGHT, 150), (UP, 0)], RF: [(RIGHT, -20)], L: [(RIGHT, 150)], LF: [(RIGHT, -20)]}
    clips.append(clip_keys(sk, "handsup", [(0.0, up, (0, 0, 0)), (1.0, up, (0, 0, 0))], loop=True, upper=True))
    # Fall onto the back: knees give, the torso tips back, the whole body turns
    # about the ground-level hip until it lies flat; held at the end.
    lying_root = (0, -root_y + 0.10, 0)
    clips.append(clip_keys(sk, "fall", [
        (0.00, {R: [(RIGHT, 30)], L: [(RIGHT, 30)]}, (0, 0, 0)),
        (0.18, {ROOT: [(RIGHT, 25)], RT: [(RIGHT, -40)], LT: [(RIGHT, -40)], RC: [(RIGHT, 50)], LC: [(RIGHT, 50)],
                R: [(RIGHT, 70), (UP, -30)], L: [(RIGHT, 70), (UP, 30)]}, (0, -0.18, 0.0)),
        (0.45, {ROOT: [(RIGHT, 80)], RT: [(RIGHT, -10)], LT: [(RIGHT, -10)], RC: [(RIGHT, 15)], LC: [(RIGHT, 15)],
                R: [(RIGHT, 60), (UP, -45)], L: [(RIGHT, 60), (UP, 45)], HEAD: [(RIGHT, -20)]}, (0, -root_y + 0.22, 0.0)),
        (0.70, {ROOT: [(RIGHT, 90)], RT: [(RIGHT, 0), (UP, 8)], LT: [(RIGHT, 0), (UP, -8)],
                R: [(RIGHT, 20), (UP, -45)], L: [(RIGHT, 20), (UP, 45)], HEAD: [(RIGHT, -10)]}, (lying_root[0], lying_root[1], 0.0)),
    ]))   # held at its last key by the renderer (one pose, one cached buffer)
    # Rifle (machine gun, silenced machine gun, shotgun): the stock in the right
    # shoulder, the right hand at the pistol grip by the chest, the left arm out
    # on the fore-end, the body bladed with the left shoulder leading, the cheek
    # on the stock. The renderer lays the weapon along the line from the right
    # hand to the left, so the two hands are what place it.
    heavy = {R: [(RIGHT, 91), (UP, 38), (FWD, -83)], RF: [(RIGHT, 65)], L: [(RIGHT, 78), (UP, -34)], LF: [(RIGHT, 22)],
             SP: [(UP, -22)], SP2: [(UP, -6)], HEAD: [(UP, 14), (RIGHT, 6)]}
    heavy_kick = merged(heavy, {RF: [(RIGHT, 8)], L: [(RIGHT, 5)], SP: [(RIGHT, -5)], SP2: [(RIGHT, -3)], HEAD: [(RIGHT, -4)]})
    clips.append(stance("aim_heavy", heavy, heavy_kick, settle=0.14))
    # Rocket launcher: the tube on the right shoulder, the right hand up at the
    # grip beside the cheek, the left arm out under the front of the tube, the
    # head tilted to it. Its kick is the shoulder check: the torso jolts right
    # and back as the rocket leaves.
    launcher = {R: [(RIGHT, 65), (UP, 40), (FWD, -50)], RF: [(RIGHT, 94)], L: [(RIGHT, 92), (UP, -36)], LF: [(RIGHT, 24)],
                SP: [(UP, -16)], HEAD: [(UP, 10), (RIGHT, -6)]}
    launcher_kick = merged(launcher, {SP: [(UP, -12), (RIGHT, -7)], SP2: [(RIGHT, -4)], HEAD: [(RIGHT, -6)], R: [(RIGHT, -6)]})
    clips.append(stance("aim_launcher", launcher, launcher_kick, settle=0.16))
    # Flamethrower: fired from the hip, the right hand at the grip by the waist,
    # the left out on the front grip, a slight crouch and lean into the stream;
    # held, with a slow sway.
    flame = {R: [(RIGHT, 22), (UP, 12)], RF: [(RIGHT, 72)], L: [(RIGHT, 64), (UP, -26)], LF: [(RIGHT, 18)],
             SP: [(RIGHT, 8), (UP, -6)], HEAD: [(RIGHT, 2)], RT: [(RIGHT, -8)], LT: [(RIGHT, -8)], RC: [(RIGHT, 12)], LC: [(RIGHT, 12)]}
    flame_sway = merged(flame, {SP: [(UP, 5)], L: [(UP, 3)]})
    clips.append(stance("aim_flame", flame, flame, settle=0.1, sway=flame_sway))
    # Throw (grenade, molotov): an underarm lob, one shot. The right arm swings
    # back with the shoulders turned away, then through and up past the hip
    # with the shoulders following; the left arm out for balance.
    clips.append(clip_keys(sk, "throw", [
        (0.00, {R: [(RIGHT, 10)], RF: [(RIGHT, 20)], L: [(RIGHT, 20), (UP, -10), (FWD, 18)], SP: [(UP, 8)]}, (0, 0, 0)),
        (0.18, {R: [(RIGHT, -48), (UP, 8), (FWD, -14)], RF: [(RIGHT, 12)], L: [(RIGHT, 45), (UP, -14), (FWD, 22)], SP: [(UP, 24), (RIGHT, 4)], HEAD: [(UP, -14)]}, (0, -0.01, 0)),
        (0.30, {R: [(RIGHT, 50), (FWD, -14)], RF: [(RIGHT, 4)], L: [(RIGHT, 35), (UP, -10), (FWD, 14)], SP: [(UP, -10), (RIGHT, 6)]}, (0, -0.01, 0)),
        (0.40, {R: [(RIGHT, 95), (UP, 10)], RF: [(RIGHT, 0)], L: [(RIGHT, 25)], SP: [(UP, -22), (RIGHT, 8)], SP2: [(UP, -6)]}, (0, 0, 0)),
        (0.62, {R: [(RIGHT, 40), (UP, 8)], RF: [(RIGHT, 30)], L: [(RIGHT, 20)], SP: [(UP, -6)]}, (0, 0, 0)),
    ], upper=True))
    # Swim: prone at the surface (the renderer sinks the figure to its shoulders),
    # a front crawl: the arms alternate reaching past the head and pulling back
    # along the body, the legs kick in opposition.
    prone = {ROOT: [(RIGHT, -90)], HEAD: [(RIGHT, -35)]}
    swim_root = (0, -root_y + 0.16, 0)
    def crawl(ra, la, rk):
        d = dict(prone)
        d[R] = [(RIGHT, ra)]; d[RF] = [(RIGHT, 10)]
        d[L] = [(RIGHT, la)]; d[LF] = [(RIGHT, 10)]
        d[RT] = [(RIGHT, rk)]; d[LT] = [(RIGHT, -rk)]
        return d
    clips.append(clip_keys(sk, "swim", [
        (0.00, crawl(165, 25, 14), swim_root),
        (0.50, crawl(95, 95, -14), swim_root),
        (1.00, crawl(25, 165, 14), swim_root),
        (1.50, crawl(95, 95, -14), swim_root),
        (2.00, crawl(165, 25, 14), swim_root),
    ], loop=True))
    # Hit: a stagger back and recover.
    clips.append(clip_keys(sk, "hit", [
        (0.00, {}, (0, 0, 0)),
        (0.12, {SP: [(RIGHT, -25)], SP2: [(RIGHT, -10)], HEAD: [(RIGHT, -15)], R: [(RIGHT, 40)], L: [(RIGHT, 40)]}, (0, -0.03, 0.0)),
        (0.30, {SP: [(RIGHT, -15)], R: [(RIGHT, 20)], L: [(RIGHT, 20)]}, (0, -0.02, 0.0)),
        (0.50, {}, (0, 0, 0)),
    ]))
    # ---- Carrying a weapon, not firing (upper-body layers, held) ----------
    # The renderer shows these whenever the game puts a weapon in the hands and
    # he is not shooting; the legs walk, run or idle underneath. The weapon is
    # placed by the hands exactly as in the stances (a pistol along the right
    # hand's fingers, a long weapon along the line from the right hand to the left).
    def held(name, pose):
        return clip_keys(sk, name, [(0.0, pose, (0, 0, 0)), (1.0, pose, (0, 0, 0))], loop=True, upper=True)
    # Pistol, grenade, molotov: low ready in the right hand, the muzzle forward
    # and down beside the thigh; the left arm is left to the walk.
    carry = {R: [(RIGHT, 20), (UP, 6)], RF: [(RIGHT, 40)], "Bip01 R Hand": [(RIGHT, -10)]}
    clips.append(held("carry", carry))
    # Dual pistols: the same in both hands.
    clips.append(held("carry_dual", dict(carry, **{L: [(RIGHT, 20), (UP, -6)], LF: [(RIGHT, 40)],
                                                   "Bip01 L Hand": [(RIGHT, -10)]})))
    # Machine gun, silenced machine gun, shotgun, electro gun: low ready across
    # the body, the right hand at the grip by the hip, the left forward and a
    # little lower on the fore-end, so the muzzle points ahead, down and in.
    clips.append(held("carry_heavy", {R: [(RIGHT, 18), (UP, 34), (FWD, -11)], RF: [(RIGHT, 74)],
                                      L: [(RIGHT, 40), (UP, -26)], LF: [(RIGHT, 18)], SP: [(UP, -8)]}))
    # Rocket launcher: the tube rests on the right shoulder, pointing ahead and a
    # little down, the left hand low under its front.
    clips.append(held("carry_launcher", {R: [(RIGHT, 49), (UP, 45), (FWD, -36)], RF: [(RIGHT, 104)],
                                         L: [(RIGHT, 66), (UP, -34)], LF: [(RIGHT, 40)], SP: [(UP, -8)]}))
    # Flamethrower: at the hip, the nozzle down and ahead.
    clips.append(held("carry_flame", {R: [(RIGHT, 12), (UP, 10)], RF: [(RIGHT, 64)],
                                      L: [(RIGHT, 36), (UP, -22)], LF: [(RIGHT, 30)]}))
    # ---- Reloading (QB-29, upper-body layers, one shot) --------------------
    # GTA2 has no magazines: the renderer counts the shots off the weapon object
    # and plays these when a notional magazine is spent and he stops firing
    # (live_geometry.cpp, kReloads: the times below are the drop and insert
    # events it spawns the falling magazine and the clicks on). Each starts and
    # ends on the weapon's carry pose so it fades in and out of it.
    rel_carry = dict(carry)
    pres = {R: [(RIGHT, 42), (UP, 24)], RF: [(RIGHT, 62)], "Bip01 R Hand": [(FWD, -25)], HEAD: [(RIGHT, -16)]}
    # Pistol (also the dual pistols' right gun): bring it up in front of the
    # chest, tip the mag out (a flick of the wrist, 0.30 s), the left hand to the
    # belt for a fresh one, up into the grip (0.80 s), over the top to rack the
    # slide, back to low ready.
    clips.append(clip_keys(sk, "reload", [
        (0.00, rel_carry, (0, 0, 0)),
        (0.18, merged(pres, {L: [(RIGHT, 22), (UP, -10)], LF: [(RIGHT, 30)]}), (0, 0, 0)),
        (0.30, merged(pres, {"Bip01 R Hand": [(RIGHT, -12)], L: [(RIGHT, 10), (UP, -6)], LF: [(RIGHT, 20)]}), (0, 0, 0)),
        (0.55, merged(pres, {L: [(RIGHT, -6), (FWD, 8)], LF: [(RIGHT, 28)], HEAD: [(UP, -8)]}), (0, 0, 0)),
        (0.68, merged(pres, {L: [(RIGHT, 30), (UP, -12)], LF: [(RIGHT, 46)]}), (0, 0, 0)),
        (0.80, merged(pres, {L: [(RIGHT, 52), (UP, -36)], LF: [(RIGHT, 58)]}), (0, 0, 0)),
        (0.98, merged(pres, {L: [(RIGHT, 58), (UP, -34)], LF: [(RIGHT, 62)], SP: [(UP, -4)]}), (0, 0, 0)),
        (1.12, merged(pres, {L: [(RIGHT, 50), (UP, -30)], LF: [(RIGHT, 38)]}), (0, 0, 0)),
        (1.24, merged(pres, {L: [(RIGHT, 30), (UP, 4)], LF: [(RIGHT, 16)]}), (0, 0, 0)),
        (1.40, rel_carry, (0, 0, 0)),
    ], upper=True))
    # Rifle (machine guns, shotgun): the gun rolled and raised a little, the
    # left hand off the fore-end to the magazine, pulled and dropped (0.35 s),
    # a fresh one from the chest pouch, seated under the gun (0.95 s), a slap and
    # a pull on the charging handle, back to low ready. The renderer keeps the
    # weapon in the right hand meanwhile (its carry line, see kReloads).
    heavy_carry = {R: [(RIGHT, 18), (UP, 34), (FWD, -11)], RF: [(RIGHT, 74)],
                   L: [(RIGHT, 40), (UP, -26)], LF: [(RIGHT, 18)], SP: [(UP, -8)]}
    hpres = {R: [(RIGHT, 26), (UP, 34), (FWD, -11)], RF: [(RIGHT, 78)], "Bip01 R Hand": [(FWD, -20)],
             SP: [(UP, -8)], HEAD: [(RIGHT, -18), (UP, 6)]}
    clips.append(clip_keys(sk, "reload_heavy", [
        (0.00, heavy_carry, (0, 0, 0)),
        (0.18, merged(hpres, {L: [(RIGHT, 46), (UP, -36)], LF: [(RIGHT, 48)]}), (0, 0, 0)),
        (0.35, merged(hpres, {L: [(RIGHT, 12), (UP, -14)], LF: [(RIGHT, 30)]}), (0, 0, 0)),
        (0.65, merged(hpres, {L: [(RIGHT, 18), (UP, -6)], LF: [(RIGHT, 112)], HEAD: [(UP, -10)]}), (0, 0, 0)),
        (0.95, merged(hpres, {L: [(RIGHT, 46), (UP, -36)], LF: [(RIGHT, 48)]}), (0, 0, 0)),
        (1.12, merged(hpres, {L: [(RIGHT, 50), (UP, -40)], LF: [(RIGHT, 66)]}), (0, 0, 0)),
        (1.28, merged(hpres, {L: [(RIGHT, 30), (UP, -30)], LF: [(RIGHT, 92)]}), (0, 0, 0)),
        (1.55, heavy_carry, (0, 0, 0)),
    ], upper=True))
    # Rocket launcher: the tube down off the shoulder to the hip, the left hand
    # back over the shoulder for a rocket (0.40 s), pushed into the front of the
    # tube (0.85 s), the tube back up on the shoulder.
    launch_carry = {R: [(RIGHT, 49), (UP, 45), (FWD, -36)], RF: [(RIGHT, 104)],
                    L: [(RIGHT, 66), (UP, -34)], LF: [(RIGHT, 40)], SP: [(UP, -8)]}
    lpres = {R: [(RIGHT, 30), (UP, 30), (FWD, -20)], RF: [(RIGHT, 70)], SP: [(UP, -12)], HEAD: [(RIGHT, -14)]}
    clips.append(clip_keys(sk, "reload_launcher", [
        (0.00, launch_carry, (0, 0, 0)),
        (0.20, merged(lpres, {L: [(RIGHT, 50), (UP, -30)], LF: [(RIGHT, 40)]}), (0, 0, 0)),
        (0.40, merged(lpres, {L: [(RIGHT, 150), (UP, -10)], LF: [(RIGHT, 70)], SP: [(UP, 10)]}), (0, 0, 0)),
        (0.65, merged(lpres, {L: [(RIGHT, 70), (UP, -36)], LF: [(RIGHT, 20)]}), (0, 0, 0)),
        (0.85, merged(lpres, {L: [(RIGHT, 82), (UP, -30)], LF: [(RIGHT, 6)]}), (0, 0, 0)),
        (1.20, launch_carry, (0, 0, 0)),
    ], upper=True))
    # Cuffed: the hands together behind the back, the head down (arrested, led
    # to the police car; the legs walk).
    clips.append(held("cuffed", {R: [(RIGHT, -24), (FWD, 6)], RF: [(FWD, 78)],
                                 L: [(RIGHT, -24), (FWD, -6)], LF: [(FWD, -78)],
                                 SP: [(RIGHT, -6)], HEAD: [(RIGHT, -22)]}))

    # On fire (upper-body layer, loop): both arms beat about the head while he
    # runs, the torso doubled a little, the head thrown side to side.
    def flail(r, l, sp, hd):
        return {R: r, RF: [(RIGHT, 50)], L: l, LF: [(RIGHT, 50)], SP: sp, HEAD: hd}
    clips.append(clip_keys(sk, "burn", [
        (0.0, flail([(RIGHT, 150), (FWD, -30)], [(RIGHT, 60), (FWD, 40)], [(RIGHT, -14)], [(UP, 22)]), (0, 0, 0)),
        (0.2, flail([(RIGHT, 60), (FWD, -55)], [(RIGHT, 160), (FWD, 22)], [(RIGHT, -10), (UP, 10)], [(UP, -22)]), (0, 0, 0)),
        (0.4, flail([(RIGHT, 168), (FWD, -10)], [(RIGHT, 80), (FWD, 50)], [(RIGHT, -18)], [(UP, 16), (RIGHT, 10)]), (0, 0, 0)),
        (0.6, flail([(RIGHT, 70), (FWD, -42)], [(RIGHT, 150), (FWD, 30)], [(RIGHT, -12), (UP, -10)], [(UP, -16)]), (0, 0, 0)),
        (0.8, flail([(RIGHT, 150), (FWD, -30)], [(RIGHT, 60), (FWD, 40)], [(RIGHT, -14)], [(UP, 22)]), (0, 0, 0)),
    ], loop=True, upper=True))

    # Drowning (whole body, loop): upright in the water, the head tipped back
    # gasping, the arms reaching up and slapping down in turn, the legs treading.
    # The renderer sinks the figure as the clip runs (the game kills him there).
    def tread(ra, la, rk, lk, hd):
        return {R: ra, RF: [(RIGHT, 30)], L: la, LF: [(RIGHT, 30)], HEAD: [(RIGHT, hd)], SP: [(RIGHT, 6)],
                RT: [(RIGHT, rk)], RC: [(RIGHT, -rk - 40)], LT: [(RIGHT, lk)], LC: [(RIGHT, -lk - 40)]}
    clips.append(clip_keys(sk, "drown", [
        (0.0, tread([(RIGHT, 168), (FWD, -12)], [(RIGHT, 95), (FWD, 45)], 35, 5, 28), (0, -0.02, 0)),
        (0.3, tread([(RIGHT, 105), (FWD, -50)], [(RIGHT, 165), (FWD, 14)], 5, 35, 18), (0, -0.06, 0)),
        (0.6, tread([(RIGHT, 160), (FWD, -20)], [(RIGHT, 100), (FWD, 40)], 35, 5, 30), (0, -0.02, 0)),
        (0.9, tread([(RIGHT, 100), (FWD, -46)], [(RIGHT, 170), (FWD, 10)], 5, 35, 16), (0, -0.07, 0)),
        (1.2, tread([(RIGHT, 168), (FWD, -12)], [(RIGHT, 95), (FWD, 45)], 35, 5, 28), (0, -0.02, 0)),
    ], loop=True))

    # Falling from a height (whole body, loop): the arms windmill, the legs
    # cycle, the head up looking for the ground.
    def air(ra, la, rt, lt):
        return {R: ra, RF: [(RIGHT, 30)], L: la, LF: [(RIGHT, 30)], SP: [(RIGHT, 10)], HEAD: [(RIGHT, 14)],
                RT: [(RIGHT, rt)], RC: [(RIGHT, -abs(rt) - 30)], LT: [(RIGHT, lt)], LC: [(RIGHT, -abs(lt) - 30)]}
    clips.append(clip_keys(sk, "fall_air", [
        (0.0, air([(RIGHT, 150), (FWD, -40)], [(RIGHT, 30), (FWD, 60)], 45, -10), (0, 0, 0)),
        (0.2, air([(RIGHT, 80), (FWD, -80)], [(RIGHT, 100), (FWD, 75)], 15, 20), (0, 0, 0)),
        (0.4, air([(RIGHT, 30), (FWD, -60)], [(RIGHT, 150), (FWD, 40)], -10, 45), (0, 0, 0)),
        (0.6, air([(RIGHT, 100), (FWD, -75)], [(RIGHT, 80), (FWD, 80)], 20, 15), (0, 0, 0)),
        (0.8, air([(RIGHT, 150), (FWD, -40)], [(RIGHT, 30), (FWD, 60)], 45, -10), (0, 0, 0)),
    ], loop=True))

    # ---- Death and knock-down poses (whole body, held at the last key) ----
    # The renderer picks one by what killed him (game::kPedDamageCause, the fire
    # around him); "fall" (onto the back, above) stays the default. Each ends on
    # the ground; a knock-down plays it backwards to get up.
    def y_at(h):
        return h - root_y   # root offset that puts the pelvis h above the ground
    # Face down: the knees give, he pitches forward onto his front, the arms
    # thrown out beside the head, the face turned to one side.
    face_down = {ROOT: [(RIGHT, -90)], R: [(UP, 70)], RF: [(UP, 40)], L: [(UP, -70)], LF: [(UP, -40)],
                 HEAD: [(FWD, 70)], RT: [(UP, 10)], LT: [(UP, -10)], LC: [(RIGHT, -35)]}
    clips.append(clip_keys(sk, "fall_front", [
        (0.00, {}, (0, 0, 0)),
        (0.25, {ROOT: [(RIGHT, -18)], RT: [(RIGHT, 30)], LT: [(RIGHT, 30)], RC: [(RIGHT, -60)], LC: [(RIGHT, -60)],
                R: [(RIGHT, 40)], L: [(RIGHT, 40)], SP: [(RIGHT, -10)]}, (0, -0.25, 0.04)),
        (0.50, {ROOT: [(RIGHT, -65)], R: [(RIGHT, 120)], L: [(RIGHT, 120)], RT: [(RIGHT, 20)], LT: [(RIGHT, 20)],
                RC: [(RIGHT, -30)], LC: [(RIGHT, -30)]}, (0, y_at(0.35), 0.1)),
        (0.75, face_down, (0, y_at(0.12), 0.1)),
    ]))
    # Run over / hit by a car: knocked off his feet, up and over in the air,
    # landing face down sprawled.
    sprawl = dict(face_down, **{LC: [(RIGHT, -40)], RT: [(UP, 22)], R: [(UP, 100)], HEAD: [(FWD, -70)]})
    clips.append(clip_keys(sk, "runover", [
        (0.00, {}, (0, 0, 0)),
        (0.12, {ROOT: [(RIGHT, 40), (FWD, 20)], R: [(FWD, -80)], L: [(FWD, 80)], RT: [(RIGHT, 40)], LT: [(RIGHT, -10)]},
         (0, 0.18, -0.08)),
        (0.40, {ROOT: [(RIGHT, 150), (FWD, 50)], R: [(FWD, 120)], L: [(FWD, -110)], RT: [(RIGHT, 60)], LT: [(RIGHT, 20)],
                RC: [(RIGHT, -60)]}, (0, 0.30, -0.30)),
        (0.68, {ROOT: [(RIGHT, 245), (FWD, 20)], R: [(FWD, 70)], L: [(FWD, -70)], RT: [(RIGHT, 20)]}, (0, y_at(0.40), -0.42)),
        (0.90, sprawl, (0, y_at(0.12), -0.48)),
        (1.05, sprawl, (0, y_at(0.12), -0.48)),
    ]))
    # Blown off his feet (an explosion): thrown up and back, landing on his back
    # with the arms and legs spread.
    spread = {ROOT: [(RIGHT, 90)], R: [(UP, -80)], RF: [(UP, -20)], L: [(UP, 80)], LF: [(UP, 20)],
              RT: [(UP, -15)], LT: [(UP, 15)], HEAD: [(FWD, 30)]}
    clips.append(clip_keys(sk, "blown", [
        (0.00, {}, (0, 0, 0)),
        (0.20, {ROOT: [(RIGHT, 45)], R: [(FWD, -120)], L: [(FWD, 120)], RT: [(RIGHT, 40)], LT: [(RIGHT, 20)],
                RC: [(RIGHT, -50)], HEAD: [(RIGHT, -20)]}, (0, 0.34, -0.18)),
        (0.50, {ROOT: [(RIGHT, 80)], R: [(FWD, -100)], L: [(FWD, 100)], RT: [(RIGHT, 30)], LT: [(RIGHT, 10)]},
         (0, 0.12, -0.42)),
        (0.75, spread, (0, y_at(0.11), -0.50)),
        (0.90, spread, (0, y_at(0.11), -0.50)),
    ]))
    # Burnt: the hands at the face, down onto the knees, then over onto his side
    # curled up.
    curled = {ROOT: [(FWD, 90)], SP: [(UP, 25)], HEAD: [(UP, 20)],
              RT: [(UP, -80)], LT: [(UP, -70)], RC: [(UP, 90)], LC: [(UP, 85)],
              R: [(UP, -130)], RF: [(UP, -45)], L: [(UP, -120)], LF: [(UP, -50)]}
    clips.append(clip_keys(sk, "burnt", [
        (0.00, {R: [(RIGHT, 130), (UP, 20)], RF: [(RIGHT, 70)], L: [(RIGHT, 130), (UP, -20)], LF: [(RIGHT, 70)],
                SP: [(RIGHT, -15)]}, (0, 0, 0)),
        (0.40, {RC: [(RIGHT, -90)], LC: [(RIGHT, -90)], R: [(RIGHT, 140), (UP, 20)], RF: [(RIGHT, 70)],
                L: [(RIGHT, 140), (UP, -20)], LF: [(RIGHT, 70)], SP: [(RIGHT, -25)], HEAD: [(RIGHT, -20)]},
         (0, -0.42, 0)),
        (0.85, curled, (0, y_at(0.16), 0)),
        (1.10, curled, (0, y_at(0.16), 0)),
    ]))

    # ---- Sprint (ACTIONS-3D-4) ----------------------------------------------
    # GTA2's people cover ground fast for their size (the player runs at about 1.9
    # blocks a second, four body heights): the Rocketbox run, driven by the ground
    # covered, would have to cycle at 3.6 a second. "sprint" is that run with the
    # legs' swing about their mean pose widened (x1.45; the arms x1.1 and a little
    # out from the hips), so each cycle covers more ground; the stride ratio,
    # measured below from the feet's reach, goes to the renderer
    # (kSprintStrideOverRun in live_geometry.cpp).
    run_glb = os.path.join(os.path.dirname(os.path.abspath(idle)), "run_neutral_01.glb")
    if os.path.exists(run_glb):
        times, seq = clip_from_glb(sk, run_glb)
        legs = {RT: 1.45, RC: 1.45, LT: 1.45, LC: 1.45, "Bip01 R Foot": 1.3, "Bip01 L Foot": 1.3,
                R: 1.1, RF: 1.1, L: 1.1, LF: 1.1}
        sprint = amplify(sk, seq, legs, offsets={R: (FWD, -7), L: (FWD, 7)})
        base_stride = stance_stride(sk, times, seq)
        sprint_stride = stance_stride(sk, times, sprint)
        print("  run foot excursion %.3f m, sprint %.3f m: stride x%.3f" % (base_stride, sprint_stride, sprint_stride / base_stride))
        channels = {}
        for i, nm in enumerate(sk.names):
            if not nm: continue
            channels[nm] = {"rotation": {"times": times, "values": [list(lr[i]) for lr in sprint]}}
        root = sk.index[ROOT]
        y0 = sk.base_t[root][1]
        channels[ROOT]["translation"] = {"times": times, "values": [[sk.base_t[root][0], ty, sk.base_t[root][2]] for ty in run_root_y(sk, run_glb)]}
        clips.append({"name": "sprint", "loop": True, "upper": False, "lower": False, "channels": channels,
                      "stride_over_run": round(sprint_stride / base_stride, 4)})

    check_arms(sk, clips)

    def posed_positions(local_r, root_t):
        wr = [None] * len(sk.nodes); wp = [None] * len(sk.nodes)
        for i in sk.order:
            p = sk.parent[i]
            t = root_t.get(i, sk.base_t[i])
            if p < 0:
                wr[i] = local_r[i]; wp[i] = t
            else:
                wr[i] = qnorm(qmul(wr[p], local_r[i]))
                wp[i] = tuple(a + c for a, c in zip(wp[p], qrot(wr[p], t)))
        return wp
    for c in clips:
        last = {nm: ch["rotation"]["values"][-1] for nm, ch in c["channels"].items()}
        lr = [tuple(last.get(nm, sk.base_r[i])) for i, nm in enumerate(sk.names)]
        tr = c["channels"].get(ROOT, {}).get("translation")
        rt = {sk.index[ROOT]: tuple(tr["values"][-1])} if tr else {}
        wp = posed_positions(lr, rt)
        print("  %-12s end: head %s  r.hand %s  l.hand %s  r.toe %s" % (c["name"],
              [round(v, 2) for v in wp[sk.index[HEAD]]], [round(v, 2) for v in wp[sk.index["Bip01 R Hand"]]],
              [round(v, 2) for v in wp[sk.index["Bip01 L Hand"]]], [round(v, 2) for v in wp[sk.index["Bip01 R Toe0"]]]))
    with open(out, "w") as f:
        json.dump({"skeleton": "Bip01", "clips": clips}, f)
    print("wrote", out, [(c["name"], len(c["channels"])) for c in clips])


if __name__ == "__main__":
    main()
