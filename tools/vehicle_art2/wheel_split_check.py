#!/usr/bin/env python3
"""VEHICLE-ART-9: which triangles of an authored car the renderer's wheel split (car_bodies.cpp BuildWheelSplit) hands to
the wheels: a triangle goes to a wheel when all three vertices lie within the tyre radius (= the wheel marker's height)
of the axle in the side view and outboard of |x| - 1.2 r on that side. Anything but tyre/rim/hub parts there spins and
steers with the wheel. Model frame as in the .mesh (blocks); the wheel markers are read from the authored car module.
    gen3d/venv/bin/python tools/vehicle_art2/wheel_split_check.py <models dir> <NNN> [...]"""
import importlib, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "..", "vehicle_art"))
from seat_anchor import read_mesh

WHEEL = ("tyre", "wheel", "whitewall", "chrome_disc", "rim", "hub")


def main():
    folder = sys.argv[1]
    for num in sys.argv[2:]:
        mod = importlib.import_module(f"car_{num}")
        car = mod.build()
        meshes = read_mesh(os.path.join(folder, mod.NAME + ".mesh"))
        allv = np.concatenate([v[:, :3] for _, v, _ in meshes])
        lo = allv.min(0)
        s = 0.2   # metres -> blocks (build.py writes the glb at scale 0.2)
        wheels = [(np.array(p, float) * s) for n, p in car.markers if n.startswith("wheel_")]
        bad = {}
        for tex, v, f in meshes:
            if any(k in tex for k in WHEEL):
                continue
            P = v[:, :3]
            for c in wheels:
                c2 = c.copy(); c2[1] += lo[1] * 0   # the mesh's y already starts at the ground
                r = c[1]
                side = np.sign(c[0]); xin = max(0.25 * 0.5, abs(c[0]) - 1.2 * r)
                d = np.hypot(P[:, 1] - c[1], P[:, 2] - c[2])
                inside = (d < r) & (side * P[:, 0] > xin)
                tri = inside[f].all(1)
                if tri.any():
                    bad[tex] = bad.get(tex, 0) + int(tri.sum())
        print(mod.NAME, "non-wheel triangles taken by the wheels:", bad or "none")


if __name__ == "__main__":
    main()
