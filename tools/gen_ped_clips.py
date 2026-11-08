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


def clip_keys(sk, name, keys, loop=False, upper=False):
    """keys: [(time, deltas, root_offset)] -> channels keyed by node name.

    upper=True writes a layer clip: only the joints from Bip01 Spine1 up
    (upper_body) get channels, and no root translation. The renderer draws such a
    clip blended at just under full weight over the walk, run or idle, and since a
    joint the second clip has no channel for keeps the first clip's value
    (model_store.cpp SampleClip writes over a copy of the first pose), the legs
    and hips keep walking while the arms hold the weapon."""
    poses = [(t, sk.pose(d, ro)) for t, d, ro in keys]
    keep = upper_body(sk) if upper else None
    channels = {}
    for i, nm in enumerate(sk.names):
        if not nm or (keep is not None and nm not in keep):
            continue
        rots = [(t, p[0][i]) for t, p in poses]
        # Keep every joint (the base pose differs from the rest pose).
        channels[nm] = {"rotation": {"times": [t for t, _ in rots], "values": [list(r) for _, r in rots]}}
    if not upper:
        root = sk.index[ROOT]
        channels[ROOT]["translation"] = {"times": [t for t, _ in poses], "values": [list(p[1][root]) for _, p in poses]}
    return {"name": name, "loop": loop, "upper": upper, "channels": channels}


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
                R: [(RIGHT, 70), (UP, 30)], L: [(RIGHT, 70), (UP, -30)]}, (0, -0.18, 0.0)),
        (0.45, {ROOT: [(RIGHT, 80)], RT: [(RIGHT, -10)], LT: [(RIGHT, -10)], RC: [(RIGHT, 15)], LC: [(RIGHT, 15)],
                R: [(RIGHT, 60), (UP, 60)], L: [(RIGHT, 60), (UP, -60)], HEAD: [(RIGHT, -20)]}, (0, -root_y + 0.22, 0.0)),
        (0.70, {ROOT: [(RIGHT, 90)], RT: [(RIGHT, 0), (UP, 8)], LT: [(RIGHT, 0), (UP, -8)],
                R: [(RIGHT, 20), (UP, 70)], L: [(RIGHT, 20), (UP, -70)], HEAD: [(RIGHT, -10)]}, (lying_root[0], lying_root[1], 0.0)),
    ]))   # held at its last key by the renderer (one pose, one cached buffer)
    # Rifle (machine gun, silenced machine gun, shotgun): the stock in the right
    # shoulder, the right hand at the pistol grip by the chest, the left arm out
    # on the fore-end, the body bladed with the left shoulder leading, the cheek
    # on the stock. The renderer lays the weapon along the line from the right
    # hand to the left, so the two hands are what place it.
    heavy = {R: [(RIGHT, 48), (UP, 28)], RF: [(RIGHT, 78)], L: [(RIGHT, 78), (UP, -34)], LF: [(RIGHT, 22)],
             SP: [(UP, -22)], SP2: [(UP, -6)], HEAD: [(UP, 14), (RIGHT, 6)]}
    heavy_kick = merged(heavy, {RF: [(RIGHT, 8)], L: [(RIGHT, 5)], SP: [(RIGHT, -5)], SP2: [(RIGHT, -3)], HEAD: [(RIGHT, -4)]})
    clips.append(stance("aim_heavy", heavy, heavy_kick, settle=0.14))
    # Rocket launcher: the tube on the right shoulder, the right hand up at the
    # grip beside the cheek, the left arm out under the front of the tube, the
    # head tilted to it. Its kick is the shoulder check: the torso jolts right
    # and back as the rocket leaves.
    launcher = {R: [(RIGHT, 42), (UP, 22)], RF: [(RIGHT, 98)], L: [(RIGHT, 92), (UP, -36)], LF: [(RIGHT, 24)],
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
        (0.00, {R: [(RIGHT, 10)], RF: [(RIGHT, 20)], L: [(RIGHT, 20), (UP, -10)], SP: [(UP, 8)]}, (0, 0, 0)),
        (0.18, {R: [(RIGHT, -48), (UP, 8)], RF: [(RIGHT, 12)], L: [(RIGHT, 45), (UP, -14)], SP: [(UP, 24), (RIGHT, 4)], HEAD: [(UP, -14)]}, (0, -0.01, 0)),
        (0.30, {R: [(RIGHT, 50)], RF: [(RIGHT, 4)], L: [(RIGHT, 35), (UP, -10)], SP: [(UP, -10), (RIGHT, 6)]}, (0, -0.01, 0)),
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
    clips.append(held("carry_heavy", {R: [(RIGHT, 10), (FWD, 4)], RF: [(RIGHT, 82)],
                                      L: [(RIGHT, 40), (UP, -26)], LF: [(RIGHT, 18)], SP: [(UP, -8)]}))
    # Rocket launcher: the tube rests on the right shoulder, pointing ahead and a
    # little down, the left hand low under its front.
    clips.append(held("carry_launcher", {R: [(RIGHT, 32), (UP, 22)], RF: [(RIGHT, 104)],
                                         L: [(RIGHT, 66), (UP, -34)], LF: [(RIGHT, 40)], SP: [(UP, -8)]}))
    # Flamethrower: at the hip, the nozzle down and ahead.
    clips.append(held("carry_flame", {R: [(RIGHT, 12), (UP, 10)], RF: [(RIGHT, 64)],
                                      L: [(RIGHT, 36), (UP, -22)], LF: [(RIGHT, 30)]}))
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
        (0.40, {ROOT: [(RIGHT, 150), (FWD, 50)], R: [(FWD, -120)], L: [(FWD, 110)], RT: [(RIGHT, 60)], LT: [(RIGHT, 20)],
                RC: [(RIGHT, -60)]}, (0, 0.30, -0.30)),
        (0.68, {ROOT: [(RIGHT, 245), (FWD, 20)], R: [(FWD, -70)], L: [(FWD, 70)], RT: [(RIGHT, 20)]}, (0, y_at(0.40), -0.42)),
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
