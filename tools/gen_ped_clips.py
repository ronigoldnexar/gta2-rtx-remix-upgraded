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

Clips: punch (0.5 s, one shot), aim (held), handsup (held, the arrest), fall
(0.7 s into lying on the back, held at its end: dead or knocked down), hit
(0.5 s stagger), getin/getout come from Rocketbox's crouch clips instead.
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


def clip_keys(sk, name, keys, loop=False):
    """keys: [(time, deltas, root_offset)] -> channels keyed by node name."""
    poses = [(t, sk.pose(d, ro)) for t, d, ro in keys]
    channels = {}
    for i, nm in enumerate(sk.names):
        if not nm:
            continue
        rots = [(t, p[0][i]) for t, p in poses]
        if any(r != sk.base_r[i] for _, r in rots) or True:
            # Keep every animated joint (the base pose differs from the rest pose).
            channels[nm] = {"rotation": {"times": [t for t, _ in rots], "values": [list(r) for _, r in rots]}}
    root = sk.index[ROOT]
    channels[ROOT]["translation"] = {"times": [t for t, _ in poses], "values": [list(p[1][root]) for _, p in poses]}
    return {"name": name, "loop": loop, "channels": channels}


def main():
    avatar, idle, out = sys.argv[1:4]
    sk = Skeleton(avatar, idle)
    wr, wp = sk.world_rest()
    rh, lh = wp[sk.index["Bip01 R Hand"]], wp[sk.index["Bip01 L Hand"]]
    print("base pose: right hand at x=%.2f, left hand at x=%.2f, head y=%.2f, root y=%.2f" %
          (rh[0], lh[0], wp[sk.index[HEAD]][1], wp[sk.index[ROOT]][1]))
    root_y = sk.base_t[sk.index[ROOT]][1]
    clips = []

    # Punch: right arm from down to a straight jab forward, elbow bent on the way;
    # the left arm up as a guard; the shoulders turn into it.
    # A low guard (fists at the chest, elbows in), so from the chase camera's
    # height the stance does not read as raised arms.
    guard = {L: [(RIGHT, 35), (UP, -15)], LF: [(RIGHT, 75)]}
    clips.append(clip_keys(sk, "punch", [
        (0.00, dict(guard, **{R: [(RIGHT, 30), (UP, 15)], RF: [(RIGHT, 80)], SP: [(UP, 15)]}), (0, 0, 0)),
        (0.12, dict(guard, **{R: [(RIGHT, 90)], RF: [(RIGHT, 5)], SP: [(UP, -25)], SP2: [(UP, -10)]}), (0, 0, 0)),
        (0.22, dict(guard, **{R: [(RIGHT, 90)], RF: [(RIGHT, 0)], SP: [(UP, -25)], SP2: [(UP, -10)]}), (0, 0, 0)),
        (0.40, dict(guard, **{R: [(RIGHT, 35), (UP, 15)], RF: [(RIGHT, 70)], SP: [(UP, 10)]}), (0, 0, 0)),
        (0.50, dict(guard, **{R: [(RIGHT, 30), (UP, 15)], RF: [(RIGHT, 80)], SP: [(UP, 15)]}), (0, 0, 0)),
    ]))
    # Aim: both arms straight forward, the head on the target.
    aim = {R: [(RIGHT, 90), (UP, 20)], RF: [(RIGHT, 0)], L: [(RIGHT, 85), (UP, -25)], LF: [(RIGHT, 10)]}
    clips.append(clip_keys(sk, "aim", [(0.0, aim, (0, 0, 0)), (1.0, aim, (0, 0, 0))], loop=True))
    # Hands up: the arrest.
    up = {R: [(RIGHT, 150), (UP, 0)], RF: [(RIGHT, -20)], L: [(RIGHT, 150)], LF: [(RIGHT, -20)]}
    clips.append(clip_keys(sk, "handsup", [(0.0, up, (0, 0, 0)), (1.0, up, (0, 0, 0))], loop=True))
    # Fall onto the back: knees give, the torso tips back, the whole body turns
    # about the ground-level hip until it lies flat; held at the end.
    lying_root = (0, -root_y + 0.10, 0)
    clips.append(clip_keys(sk, "fall", [
        (0.00, {R: [(RIGHT, 30)], L: [(RIGHT, 30)]}, (0, 0, 0)),
        (0.18, {ROOT: [(RIGHT, 25)], RT: [(RIGHT, -40)], LT: [(RIGHT, -40)], RC: [(RIGHT, 50)], LC: [(RIGHT, 50)],
                R: [(RIGHT, 70), (UP, 30)], L: [(RIGHT, 70), (UP, -30)]}, (0, -0.18, 0.0)),
        (0.45, {ROOT: [(RIGHT, 80)], RT: [(RIGHT, -10)], LT: [(RIGHT, -10)], RC: [(RIGHT, 15)], LC: [(RIGHT, 15)],
                R: [(RIGHT, 60), (UP, 60)], L: [(RIGHT, 60), (UP, -60)], HEAD: [(RIGHT, -20)]}, (0, -root_y + 0.22, 0.0)),
        (0.70, {ROOT: [(RIGHT, 90)], RT: [(RIGHT, 0), (UP, 8)], LT: [(RIGHT, 0), (UP, -8)],
                R: [(RIGHT, 20), (UP, 70)], L: [(RIGHT, 20), (UP, -70)], HEAD: [(RIGHT, -10)]}, (lying_root[0], lying_root[1], 0.0)),
    ]))   # held at its last key by the renderer (one pose, one cached buffer)
    # Hit: a stagger back and recover.
    clips.append(clip_keys(sk, "hit", [
        (0.00, {}, (0, 0, 0)),
        (0.12, {SP: [(RIGHT, -25)], SP2: [(RIGHT, -10)], HEAD: [(RIGHT, -15)], R: [(RIGHT, 40)], L: [(RIGHT, 40)]}, (0, -0.03, 0.0)),
        (0.30, {SP: [(RIGHT, -15)], R: [(RIGHT, 20)], L: [(RIGHT, 20)]}, (0, -0.02, 0.0)),
        (0.50, {}, (0, 0, 0)),
    ]))
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
        rt = {sk.index[ROOT]: tuple(c["channels"][ROOT]["translation"]["values"][-1])}
        wp = posed_positions(lr, rt)
        print("  %-8s end: head %s  r.hand %s  r.toe %s" % (c["name"],
              [round(v, 2) for v in wp[sk.index[HEAD]]], [round(v, 2) for v in wp[sk.index["Bip01 R Hand"]]],
              [round(v, 2) for v in wp[sk.index["Bip01 R Toe0"]]]))
    with open(out, "w") as f:
        json.dump({"skeleton": "Bip01", "clips": clips}, f)
    print("wrote", out, [(c["name"], len(c["channels"])) for c in clips])


if __name__ == "__main__":
    main()
