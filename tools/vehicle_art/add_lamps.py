#!/usr/bin/env python3
"""VEHICLE-ART-6 (vr-prewar-sedans): give an image-to-3D body legible headlamps.

TRELLIS fuses free-standing 1930s-50s lamps into the wings; the bake leaves a pale blob with no rim, lens or
reflector. This adds, at each lamp the caller names (glb units, the body's own frame, mirrored to -x), a carkit
chrome bezel and a sealed-beam lens (tools/vehicle_art/m063_truck_cab.py sealed_beam_shader) sitting on the
blob's front, and writes the body with the lamps as one glb. The body's mesh, UVs and texture are untouched (the
lamps are a second material, image index 1), so the body's imported/resplit textures stay valid.

  gen3d/venv/bin/python tools/vehicle_art/add_lamps.py <body.glb> <out.glb> x,y,r[,tilt_deg] [x,y,r ...] [--preview p.png]
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carkit
from carkit import Mat, revolve, build, METRES_PER_BLOCK
from m063_truck_cab import sealed_beam_shader

CHROME = Mat("chrome", "rest", (0.80, 0.81, 0.83), rough=0.10, metal=1.0, env=0.92, ao=0.45)
BEAM = Mat("headlamp_lens", "rest", (0.93, 0.95, 0.97), rough=0.05, emit=(1.0, 0.95, 0.85), shader=sealed_beam_shader, env=0.12, ao=0.1)
DARK = Mat("black_trim", "rest", (0.06, 0.06, 0.065), rough=0.6, ao=0.6)


def lamp_face(V, x, y, r):
    """The front of the blob at (x, y): the highest z among the body's vertices within r of the lamp axis."""
    m = (V[:, 0] - x) ** 2 + (V[:, 1] - y) ** 2 < r * r
    if not m.any(): raise SystemExit(f"no body vertices near the lamp at {x},{y}")
    return float(V[m, 2].max())


def main():
    import trimesh
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    body, out = args[0], args[1]
    prev = sys.argv[sys.argv.index("--preview") + 1] if "--preview" in sys.argv else None
    if prev in args: args.remove(prev)
    scene = trimesh.load(body, force="scene")
    geoms = list(scene.dump())
    V = np.vstack([g.vertices for g in geoms])
    k = METRES_PER_BLOCK          # carkit works in metres, writes blocks: build in glb units x k
    P = []
    for spec in args[2:]:
        vals = [float(v) for v in spec.split(",")]
        x, y, r = vals[:3]
        tilt = math.radians(vals[3]) if len(vals) > 3 else 0.0
        zf = lamp_face(V, x, y, 0.8 * r)
        for sx in (1, -1):
            c = np.array([sx * x, y, zf - 0.25 * r]) * k
            ax = (0.0, math.sin(tilt), math.cos(tilt))
            R = r * k
            # a short chrome bucket sunk into the blob, its rim proud of the blob's front, a dark seal ring, the lens
            P.append(revolve(f"lamp_bucket{sx}", CHROME, [(0.55 * R, -0.60 * R), (0.92 * R, -0.35 * R), (1.02 * R, 0.0), (1.05 * R, 0.20 * R),
                                                          (1.00 * R, 0.34 * R), (0.90 * R, 0.36 * R), (0.86 * R, 0.30 * R)], c, ax, R=32))
            P.append(revolve(f"lamp_seal{sx}", DARK, [(0.87 * R, 0.29 * R), (0.80 * R, 0.30 * R)], c, ax, R=32))
            P.append(revolve(f"lamp_lens{sx}", BEAM, [(0.82 * R, 0.29 * R), (0.60 * R, 0.36 * R), (0.30 * R, 0.40 * R), (0.0001, 0.41 * R)], c, ax,
                             R=32, tag=dict(center=list(c), r=0.82 * R)))
    tmp = out[:-4] + "_lamps.glb"
    rep, groups = build(P, tmp, res={"rest": 256, "paint": 64, "glass": 64})
    lamps = trimesh.load(tmp, force="scene")
    for name, g in lamps.geometry.items():
        scene.add_geometry(g, geom_name="lamps_" + name)
    scene.export(out)
    print("lamps:", rep["vertices"], "vertices,", rep["faces"], "faces ->", out)
    if prev:
        import preview
        preview.sheet(groups, 1.0 * k, 0.6 * k, 0.43 * k, None, prev, title="lamps only")


if __name__ == "__main__":
    main()
