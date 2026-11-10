#!/usr/bin/env python3
"""064 Truck Cab SX: the 063 tractor's chassis and cab (m063_truck_cab.py) with what the 064 sprite draws differently.

VEHICLE-ART-19 (qav17: in ste traffic the image-to-3D 064 drew a flat tan featureless bar across the cab back, a
silver slab at each end that read as torn chrome, and the two roof lamps as crumpled shards). The sprite (nose down,
42 x 64 px, x4 in assets-src/cars/sprites_x4/064_truck_cab_sx_default.png) shows, from the nose:
  - a broad rounded hood that fills the width between the front wings (the 063's is a narrow centre hood), a small
    chrome grille low in its face, the bumper below;
  - the dark windscreen band;
  - the lit cab roof with two OBLONG chrome-rimmed roof lights lying fore-aft (amber-lit, ~0.25 x 0.7 m);
  - a pale band across the whole cab back at roof height: a raised roof lip / fairing over the back wall (the 3D
    shell's 'tan bar');
  - at the cab's two rear corners, upright chrome exhaust stacks (the shell's 'torn chrome' slabs);
  - behind, the dark chassis with the fifth wheel.
Same carkit, same units and same paint rules as 063 (paint group tinted by the identity record), so the cab, doors,
tanks, wheels and lamps keep everything VEHICLE-ART-6/11/12/17 did for the 063.
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carkit import *
import m063_truck_cab as B

M = B.M
L, W = B.L, B.W
DROP = ("hood", "hood_strip", "grille_frame", "grille_mesh", "emblem", "ornament", "roof_lamp", "roof_bezel", "roof_lens",
        "roof_lamp_base", "stack", "shield", "stack_bracket", "hl_bucket", "hl_lens", "hl_bezel", "hl_stalk", "turn", "apron")


def dropped(name):
    if name.startswith("bar") and name[3:].isdigit():
        return True
    return any(name == d or (name.startswith(d) and name[len(d):] in ("1", "-1", "")) for d in DROP)


def build_truck_sx():
    P = [p for p in B.build_truck() if not dropped(p.name)]
    cab_z0 = -0.42
    # ---- the broad rounded hood: fills the width between the wings, rounds down into the nose
    hood = body_loft("hood", M["paint"], [
        (0.92, (1.00, 1.86, 0.80, 0.70, 3.6, 0.10, 0)),
        (1.30, (1.00, 1.84, 0.80, 0.70, 3.6, 0.11, 0)),
        (1.56, (1.00, 1.76, 0.79, 0.68, 3.4, 0.09, 0)),
        (1.70, (1.02, 1.60, 0.74, 0.62, 3.0, 0.06, 0)),
        (1.76, (1.06, 1.42, 0.66, 0.56, 2.8, 0.03, 0)),
    ], R=40, S=15)
    P.append(hood)
    # a chrome centre strip along the crown, and a hood ornament
    strip = conform([hood], np.array([[0, 2.1, z] for z in np.linspace(1.0, 1.66, 8)]), (0, -1, 0), 0.006)[0]
    P.append(tube("hood_strip", M["chrome"], strip, 0.012, R=6))
    # ---- the small chrome grille low in the hood's face (the sprite's chrome bit above the bumper)
    P.append(rbox("grille_frame", M["chrome"], (-0.36, 0.72, 1.72), (0.36, 1.22, 1.80), r=0.04, R=16))
    P.append(box("grille_mesh", M["grille"], (-0.29, 0.78, 1.76), (0.29, 1.16, 1.805)))
    for i in range(7):
        y = 0.82 + i * 0.05
        P.append(box(f"bar{i}", M["chrome"], (-0.29, y - 0.008, 1.805), (0.29, y + 0.008, 1.82)))
    P.append(rbox("emblem", M["chrome"], (-0.12, 1.26, 1.74), (0.12, 1.31, 1.79), r=0.012, R=10))
    # ---- headlamps set into the hood's front corners (sealed beams in chrome bezels), turn lamps below
    for sx in (1, -1):
        c = np.array([0.56 * sx, 1.30, 1.72])
        P.append(revolve(f"hl_bucket{sx}", M["chrome"], [(0.02, -0.12), (0.08, -0.10), (0.12, -0.05), (0.13, -0.01), (0.135, 0.0),
                                                         (0.122, 0.012)], c, (0, 0, 1), R=24))
        P.append(revolve(f"hl_lens{sx}", M["beam"], [(0.122, 0.010), (0.10, 0.017), (0.055, 0.022), (0.0001, 0.024)], c, (0, 0, 1), R=32,
                         tag=dict(center=list(c), r=0.122)))
        P.append(revolve(f"hl_bezel{sx}", M["chrome"], [(0.110, 0.015), (0.118, 0.025), (0.133, 0.024), (0.142, 0.011), (0.138, -0.004)], c,
                         (0, 0, 1), R=32))
        tc = np.array([0.56 * sx, 1.02, 1.75])
        P.append(revolve(f"turn{sx}", M["amber"], [(0.0001, 0.0), (0.05, 0.0), (0.045, 0.025), (0.0001, 0.035)], tc, (0, 0, 1), R=14))
    # ---- roof: two oblong chrome-rimmed roof lights lying fore-aft (the sprite's), amber-lit lenses facing up
    for sx in (1, -1):
        x = 0.42 * sx
        P.append(rbox(f"roof_light{sx}", M["chrome"], (x - 0.115, 2.43, -0.02), (x + 0.115, 2.53, 0.62), r=0.045, R=16))
        P.append(rbox(f"roof_lens{sx}", M["amber"], (x - 0.085, 2.50, 0.02), (x + 0.085, 2.545, 0.58), r=0.035, R=16))
        P.append(rbox(f"roof_light_base{sx}", M["black"], (x - 0.07, 2.36, 0.06), (x + 0.07, 2.45, 0.54), r=0.02, R=8))
    # ---- the raised roof lip across the cab back (the sprite's pale band): a rounded painted fairing overhanging the
    # back wall, its underside in shade, with a chrome rain strip along its lower edge
    lip = body_loft("roof_lip", M["paint"], [
        (cab_z0 - 0.16, (2.30, 2.40, 0.92, 0.90, 4.0, 0.02, 0)),
        (cab_z0 - 0.10, (2.27, 2.47, 0.97, 0.95, 4.5, 0.03, 0)),
        (cab_z0 + 0.10, (2.27, 2.48, 0.98, 0.96, 4.5, 0.03, 0)),
        (cab_z0 + 0.18, (2.30, 2.44, 0.97, 0.95, 4.5, 0.02, 0)),
    ], R=36, S=8)
    P.append(lip)
    P.append(tube("lip_strip", M["chrome"], [[-0.90, 2.272, cab_z0 - 0.105], [0.90, 2.272, cab_z0 - 0.105]], 0.010, R=6))
    # two pressed ribs down the back wall under the lip (the back no longer one plain panel)
    for sx in (1, -1):
        P.append(rbox(f"back_rib{sx}", M["paint"], (0.62 * sx - 0.035, 1.10, cab_z0 - 0.035), (0.62 * sx + 0.035, 2.24, cab_z0 + 0.02),
                      r=0.02, R=8))
    # ---- upright chrome stacks at the cab's two rear corners, perforated shields, a cut top, brackets to the cab
    for sx in (1, -1):
        cx, cz = 1.08 * sx, cab_z0 - 0.10
        P.append(tube(f"stack{sx}", M["chrome"], [[cx, 0.92, cz], [cx, 1.8, cz], [cx, 2.92, cz]], 0.068, R=16))
        P.append(revolve(f"stack_top{sx}", M["black"], [(0.0001, 0.0), (0.058, 0.0)], (cx, 2.925, cz), (0, 1, 0), R=16))
        P.append(revolve(f"shield{sx}", M["shield"], [(0.092, 0.0), (0.092, 0.78)], (cx, 1.50, cz), (0, 1, 0), R=16,
                         cap0=True, cap1=True, tag=dict(cx=cx, cz=cz)))
        for yb in (1.62, 2.40):
            P.append(box(f"stack_bracket{sx}{int(yb * 10)}", M["black"], (min(cx, 0.96 * sx) - 0.02, yb, cz - 0.02),
                         (max(cx, 0.96 * sx) + 0.02, yb + 0.04, cz + 0.06)))
    return P


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/gta2-linux/assets-src/cars/models_art/064_truck_cab_sx.glb"))
    ap.add_argument("--preview", default=None)
    ap.add_argument("--sprite", default=os.path.expanduser("~/gta2-linux/assets-src/cars/sprites_x4/064_truck_cab_sx_default.png"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    parts = build_truck_sx()
    rep, groups = build(parts, a.out, report=dict(model=64, name="Truck Cab SX", forward="+z", maker="tools/vehicle_art/m064_truck_cab_sx.py"))
    print(rep)
    if a.preview:
        import preview
        preview.sheet(groups, L, W, 2.9, a.sprite, a.preview, paint=(150, 121, 99), title="064 Truck Cab SX (carkit)")
