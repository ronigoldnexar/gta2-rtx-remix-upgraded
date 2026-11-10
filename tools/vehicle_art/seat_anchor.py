#!/usr/bin/env python3
"""The driver's seat of each authored car body, for the manifest's "driver_seat" entry.

The renderer seats the driver (boarding.cpp) where the game's sprite suggests: its CARI window rows
and half its width. That fits the image-to-3D bodies, which were made from the sprite; an authored
carkit body has its own cockpit (036 Schmidt: a central tandem seat under a bubble), and the sprite's
guess put the hero at the rear deck, standing through the canopy (playfeel1). So each authored body
names its seat: the hip point on the driver's cushion and the headliner over it.

  "driver_seat": [x, y, z, roof]   model frame, blocks (as in the .mesh: +z the nose, y up from the
                                   model's lowest point): x = the hip's distance from the centre line
                                   (the side follows the door he used), y = the cushion's top, z = the
                                   hip (12 cm ahead of the seat back), roof = the headliner over the hip.

The seats below are read off the generators (tools/vehicle_art/m0*.py at 3.8 m a block,
tools/vehicle_art2/car_0*.py at 5 m a block); the headliner is found by casting a ray up through the
.mesh from the cushion, so it is the drawn roof, inner face or glass, whichever is lowest.

  python3 tools/vehicle_art/seat_anchor.py <models dir> [--write <manifest.json>]
"""
import json, os, sys
import numpy as np



def read_mesh(path):
    """(texture, vertices[n, 8], indices[m, 3]) per mesh of a GMSH file (tools/import_assets.py;
    the car models are one node at the origin, so node transforms are ignored)."""
    import struct
    d = open(path, "rb").read(); p = 4
    _, nn, nm, _, _ = struct.unpack_from("<IIIII", d, p); p += 20
    p += nn * (32 + 4 + 12 + 16 + 12 + 4)
    out = []
    for _ in range(nm):
        nv, ni = struct.unpack_from("<II", d, p); p += 8
        tex = d[p:p + 64].split(b"\0")[0].decode(); p += 64
        skin, = struct.unpack_from("<i", d, p); p += 4
        v = np.frombuffer(d, np.float32, nv * 8, p).reshape(nv, 8); p += nv * 32
        if skin >= 0: p += nv * 24
        idx = np.frombuffer(d, np.uint32, ni, p).reshape(-1, 3); p += ni * 4
        out.append((tex, v, idx))
    return out

# name: (hip x, cushion top y, hip z) in the generator's metres, metres a block
SEATS = {
    "013_minx": ((0.38, 0.66, -0.28), 3.8),        # bench x +-0.70, top 0.66, back -0.52..-0.40
    "063_truck_cab": ((0.51, 1.48, -0.04), 3.8),   # seats x 0.18..0.84, top 1.48, back -0.32..-0.16
    "068_van": ((0.55, 1.05, 1.12), 3.8),          # seats x 0.15..0.95, top 1.05, back 0.88..1.00
    "008_bug": ((0.38, 0.62, 0.16), 5.0),          # seats at x +-0.38, top 0.62, back -0.08..0.04
    "036_schmidt": ((0.0, 0.52, 0.19), 5.0),       # tandem: front seat centred, top 0.52, back -0.05..0.07
    "056_taxi": ((0.45, 0.72, 0.0), 5.0),          # front bench x +-1.02, top 0.72, back -0.25..-0.12
    "040_maurice": ((0.38, 0.64, 0.04), 5.0),      # FIX-CAR-TEX: seats x +-0.38, top 0.64, back -0.20..-0.08
    "050_b_type": ((0.45, 0.70, -0.04), 5.0),       # VEHICLE-ART-7: front bench x +-1.00, top 0.70, back -0.30..-0.16
    "051_taxi_xpress": ((0.45, 0.70, -0.04), 5.0),  # VEHICLE-ART-8: the 050 body (same benches)
    "038_big_bug": ((0.38, 1.12, 0.16), 5.0),      # VEHICLE-ART-9: the 008 seats lifted 0.50 m
    "018_shark": ((0.45, 0.70, 0.04), 5.0),        # VEHICLE-ART-9: front bench x +-0.92, top 0.70, back -0.22..-0.08
    "082_jagular_xk": ((0.40, 0.56, -0.38), 5.0),  # VEHICLE-ART-9: buckets x +-0.40, top 0.56, back -0.62..-0.50
    "058_tow_truck": ((0.50, 1.20, -0.14), 5.0),   # VEHICLE-ART-9: cab bench x +-1.00, top 1.20, back -0.38..-0.26
    "004_g4_bank_van": ((0.55, 1.26, 0.66), 5.0),  # VEHICLE-ART-10: cab bench x +-1.08, top 1.26, back 0.42..0.54
    "057_t_rex": ((0.42, 0.52, -0.43), 5.0),  # VEHICLE-ART-10: buckets x +-0.42, top 0.52, back -0.67..-0.55
    "053_michelli_roadster": ((0.40, 0.42, -0.58), 5.0),  # VEHICLE-ART-10: buckets x +-0.40, top 0.42, back -0.82..-0.70
}


def headliner(meshes, x, y, z):
    """The lowest face above (x, y + 0.08 block, z), any mesh: a vertical ray up."""
    best = None
    o = np.array([x, y + 0.08, z])
    for tex, v, idx in meshes:
        P = v[idx][:, :, :3].astype(np.float64)
        a, b, c = P[:, 0], P[:, 1], P[:, 2]
        # 2D point-in-triangle in x/z, then the height on the plane
        def cross(p, q):
            return (q[:, 0] - p[:, 0]) * (o[2] - p[:, 2]) - (q[:, 2] - p[:, 2]) * (o[0] - p[:, 0])
        d1, d2, d3 = cross(a, b), cross(b, c), cross(c, a)
        inside = ((d1 >= 0) & (d2 >= 0) & (d3 >= 0)) | ((d1 <= 0) & (d2 <= 0) & (d3 <= 0))
        if not inside.any(): continue
        n = np.cross(b - a, c - a)
        ok = inside & (np.abs(n[:, 1]) > 1e-9)
        if not ok.any(): continue
        yy = a[ok, 1] - (n[ok, 0] * (o[0] - a[ok, 0]) + n[ok, 2] * (o[2] - a[ok, 2])) / n[ok, 1]
        yy = yy[yy > o[1]]
        if len(yy) and (best is None or yy.min() < best[0]): best = (float(yy.min()), tex)
    return best


def main():
    folder = sys.argv[1]
    out = {}
    for name, ((x, y, z), mb) in SEATS.items():
        path = os.path.join(folder, name + ".mesh")
        if not os.path.exists(path): print(f"{name}: no mesh"); continue
        meshes = read_mesh(path)
        allv = np.concatenate([v[:, :3] for _, v, _ in meshes])
        lo, hi = allv.min(0), allv.max(0)
        xb, yb, zb = x / mb, y / mb + lo[1], z / mb
        roof = headliner(meshes, xb, yb, zb)
        roofY = roof[0] if roof else hi[1]
        out[name] = [round(float(v), 4) for v in (xb, yb - lo[1], zb, roofY - lo[1])]
        print(f"{name}: bounds x {lo[0]:+.3f}..{hi[0]:+.3f} y {lo[1]:.3f}..{hi[1]:.3f} z {lo[2]:+.3f}..{hi[2]:+.3f}; "
              f"seat x {xb:.3f} y {yb - lo[1]:.3f} z {zb:+.3f}, headliner {roofY - lo[1]:.3f} ({roof[1] if roof else 'none: the top'}), "
              f"room {roofY - yb:.3f}")
    if "--write" in sys.argv:
        path = sys.argv[sys.argv.index("--write") + 1]
        man = json.load(open(path))
        for e in man["models"]:
            if e.get("name") in out: e["driver_seat"] = out[e["name"]]
        text = json.dumps(man, indent=1)
        with open(path + ".tmp", "w") as f: f.write(text)
        os.replace(path + ".tmp", path)
        print("written", path)


if __name__ == "__main__":
    main()
