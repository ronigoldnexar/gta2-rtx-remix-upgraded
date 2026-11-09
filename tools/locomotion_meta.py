#!/usr/bin/env python3
"""Locomotion metadata for the mocap clips retargeted onto the Rocketbox avatars
(QB-20/21/39, tools/import_assets.py "retarget": true in animations_from).

The Rocketbox animation library (github.com/microsoft/Microsoft-Rocketbox,
Assets/Animations, MIT) is motion capture on the 3ds Max Biped skeleton, the
skeleton every avatar shares, but each recording has its own bone lengths (the
female clips a 0.426 calf, the male ones 0.399, and so on). The importer copies
the clip's joint rotations (Biped's joint frames agree across the library) and
drops its joint translations, so every avatar keeps its own bones; the root's
height is scaled by the avatars' hip-height ratio and so is the ground a clip
covers.

For the renderer this module measures, per clip, at 15 samples a second:
  d  - the ground covered since the clip's start (its stripped root motion), in
       the avatar's model units;
  ph - the clip's foot phase on its reference cycle (the walk for walking clips,
       the run for running ones): the cycle phase whose feet match best, from the
       feet's forward and up offsets (forward kinematics on the clip's own bones).
The renderer uses them to drive a start by the ground the figure covers, to leave
a start on the cycle phase it ends in, to enter a stop on the phase the figure is
at, and to line the run and the sprint up with the walk.

    locomotion_meta.py <clip.glb> [<reference cycle.glb>]   prints the tables
"""
import math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_assets import load_glb, accessor  # noqa: E402

RATE = 15.0


def _qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def _qrot(q, v):
    x, y, z, w = q
    vx, vy, vz = v
    ix = w * vx + y * vz - z * vy
    iy = w * vy + z * vx - x * vz
    iz = w * vz + x * vy - y * vx
    iw = -x * vx - y * vy - z * vz
    return (ix * w + iw * -x + iy * -z - iz * -y,
            iy * w + iw * -y + iz * -x - ix * -z,
            iz * w + iw * -z + ix * -y - iy * -x)


def _sample(times, values, t):
    if t <= times[0]: return values[0]
    if t >= times[-1]: return values[-1]
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t: lo = mid
        else: hi = mid
    f = (t - times[lo]) / max(1e-9, times[hi] - times[lo])
    a, b = values[lo], values[hi]
    if len(a) == 4:
        if sum(x * y for x, y in zip(a, b)) < 0: b = tuple(-c for c in b)
        q = tuple(x + (y - x) * f for x, y in zip(a, b))
        n = math.sqrt(sum(c * c for c in q)) or 1.0
        return tuple(c / n for c in q)
    return tuple(x + (y - x) * f for x, y in zip(a, b))


class Clip:
    """One animation of a glb on its own skeleton."""

    def __init__(self, path):
        g, b = load_glb(path)
        self.nodes = g["nodes"]
        self.parent = [-1] * len(self.nodes)
        for i, n in enumerate(self.nodes):
            for c in n.get("children", []): self.parent[c] = i
        self.by = {n.get("name"): i for i, n in enumerate(self.nodes)}
        a = g["animations"][0]
        self.ch = {}
        self.length = 0.0
        for c in a["channels"]:
            path_ = c["target"]["path"]
            if path_ not in ("translation", "rotation"): continue
            s = a["samplers"][c["sampler"]]
            t = [x[0] for x in accessor(g, b, s["input"])]
            self.ch[(c["target"]["node"], path_)] = (t, accessor(g, b, s["output"]))
            self.length = max(self.length, t[-1])
        root = self.by["Bip01"]
        self.hip = self.nodes[root].get("translation", [0, 1, 0])[1]

    def local(self, i, t):
        n = self.nodes[i]
        tr = self.ch.get((i, "translation"))
        ro = self.ch.get((i, "rotation"))
        return (_sample(*tr, t) if tr else tuple(n.get("translation", (0, 0, 0))),
                _sample(*ro, t) if ro else tuple(n.get("rotation", (0, 0, 0, 1))))

    def world(self, i, t, cache):
        if i in cache: return cache[i]
        tr, ro = self.local(i, t)
        p = self.parent[i]
        if p < 0:
            out = (tr, ro)
        else:
            pt, pr = self.world(p, t, cache)
            r = _qrot(pr, tr)
            out = ((pt[0] + r[0], pt[1] + r[1], pt[2] + r[2]), _qmul(pr, ro))
        cache[i] = out
        return out

    def root_xz(self, t):
        tr = self.ch.get((self.by["Bip01"], "translation"))
        v = _sample(*tr, t) if tr else (0, 0, 0)
        return v[0], v[2]

    def feet(self, t):
        """(left - right) foot offset: forward along +z, up along +y, over the hip height."""
        cache = {}
        l = self.world(self.by["Bip01 L Foot"], t, cache)[0]
        r = self.world(self.by["Bip01 R Foot"], t, cache)[0]
        lc = self.world(self.by["Bip01 L Calf"], t, cache)[0]
        rc = self.world(self.by["Bip01 R Calf"], t, cache)[0]
        h = self.hip or 1.0
        return ((l[2] - r[2]) / h, (l[1] - r[1]) / h, (lc[2] - rc[2]) / h)

    def times(self):
        n = int(self.length * RATE + 1e-6)
        return [k / RATE for k in range(n + 1)]


def phase_on(cycle, clip, t, samples=60):
    """The phase (0..1) of `cycle` whose feet match `clip` at time t best."""
    f = clip.feet(t)
    best, bestd = 0.0, 1e9
    for k in range(samples):
        g = cycle.feet(k / samples * cycle.length)
        d = sum((x - y) ** 2 for x, y in zip(f, g))
        if d < bestd: best, bestd = k / samples, d
    return best


def tables(clip_path, ref_path=None, ratio=1.0, scale=1.0):
    """(d, ph) at 15 a second; d in model units (ratio: avatar hip / clip hip; scale: import scale)."""
    clip = Clip(clip_path)
    ref = Clip(ref_path) if ref_path else None
    ts = clip.times()
    x0, z0 = clip.root_xz(0.0)
    d = []
    for t in ts:
        x, z = clip.root_xz(t)
        d.append(round(math.hypot(x - x0, z - z0) * ratio * scale, 4))
    ph = [round(phase_on(ref, clip, t), 3) for t in ts] if ref else []
    return d, ph


def encode(name, d, ph):
    """One clip's entry of the manifest's "loco" string: name:d,d,...:ph,ph,..."""
    return name + ":" + ",".join("%g" % v for v in d) + ":" + ",".join("%g" % v for v in ph)


if __name__ == "__main__":
    d, ph = tables(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print("d ", d)
    print("ph", ph)
