#!/usr/bin/env python3
"""068 Van: a 1960s forward-control panel van (Econoline / A100 class), laid out on the sprite.

Sprite (nose down, body 42 x 72 px, 64 px = 1 block = 3.8 m): a long ribbed roof, the
windscreen in row 61 right behind the nose, the rear window row 6, axles at rows 61 / 13
(catalog rows mirrored), front doors near the nose and cargo doors behind them on both
sides. Shares its sprite with the 067 TV Van. Default paint: the sprite's khaki tan.
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carkit import *
from m063_truck_cab import tyre_shader, headlamp_shader, glass_shader, grille_shader

MB = METRES_PER_BLOCK
L = 72 / 64 * MB          # 4.275 m
W = 42 / 64 * MB          # 2.494 m
ZF, ZR = L / 2, -L / 2
BW = 1.17                 # half width of the body (the mirrors reach the footprint)
RT = 0.37                 # tyre radius
ZFA, ZRA = (61 - 37) / 64 * MB, (13 - 37) / 64 * MB   # axles: +1.425 / -1.425
ROOF = 2.10
SILL = 0.30


def line(d, w=0.0045):
    return np.exp(-(d / w) ** 2)


def paint_shader(pos, nrm, part, col):
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    k = np.ones(len(pos))
    side = np.abs(nrm[:, 0]) > 0.7
    # cab doors: front edge behind the front corner, rear edge; the cargo doors behind them
    k -= 0.55 * side * line(z - 1.98) * (y > 0.45) * (y < 1.95)
    k -= 0.55 * side * line(z - 1.02) * (y > 0.42) * (y < 1.98)
    k -= 0.55 * side * line(y - 1.98) * (z > 1.02) * (z < 1.98)
    k -= 0.55 * side * line(y - 0.42) * (z > 0.80) * (z < 1.98) * 0
    # cargo doors (both sides, as the sprite draws them): a pair behind the cab door
    for zz in (0.98, 0.06, -0.86):
        k -= 0.50 * side * line(z - zz) * (y > 0.40) * (y < 1.96)
    k -= 0.50 * side * line(y - 1.96) * (z > -0.86) * (z < 0.98)
    # a pressed waist moulding along the sides, light above, dark below
    sw = y - 1.10
    k += side * (0.09 * np.exp(-((sw - 0.012) / 0.010) ** 2) - 0.16 * np.exp(-((sw + 0.010) / 0.010) ** 2))
    # rear doors: the centre split and a frame
    rear = nrm[:, 2] < -0.7
    k -= 0.6 * rear * line(x) * (y > 0.40) * (y < 1.98)
    k -= 0.5 * rear * line(np.abs(x) - 1.02) * (y > 0.40) * (y < 1.98)
    k -= 0.5 * rear * line(y - 1.98) * (np.abs(x) < 1.02)
    # roof ribs read as light/shade stripes (the sprite's long roof streaks)
    top = nrm[:, 1] > 0.85
    rib = np.cos(x / 0.16 * math.pi)
    k += top * 0.05 * rib * (z < 1.75) * (z > -1.95)
    return col * np.clip(k, 0.2, 1.3)[:, None]


def rim_shader(pos, nrm, part, col):
    c = np.asarray(part.tag["center"]); a = np.asarray(part.tag["axis"]); r0 = part.tag["radius"]
    d = pos - c
    t = d @ a
    rad = np.linalg.norm(d - t[:, None] * a, axis=1)
    e1 = np.array([0, 1.0, 0]); e2 = np.cross(a, e1)
    ang = np.arctan2(d @ e2, d @ e1)
    out = col.copy()
    rough = np.full(len(pos), 0.4); metal = np.full(len(pos), 0.0)
    # painted steel wheel (off-white), a chrome dome hubcap with a ring
    cap = rad < r0 * 0.70
    out[~cap] = np.array([0.78, 0.77, 0.72])
    out[cap] = sky_env(nrm[cap]) * 0.95
    rough[cap] = 0.1; metal[cap] = 1.0
    out[np.abs(rad - r0 * 0.70) < 0.006] *= 0.3
    out[(rad < r0 * 0.30) & (rad > r0 * 0.26)] *= 0.5
    # slots in the wheel between cap and rim
    slots = (np.abs(rad - r0 * 0.82) < r0 * 0.05) & (np.cos(ang * 5) > 0.75)
    out[slots] = 0.05
    out[rad > r0 * 0.94] *= 0.55
    return out, rough, metal


M = dict(
    paint=Mat("paint", "paint", PAINT_NEUTRAL, rough=0.32, shader=paint_shader, ao=0.9),
    chrome=Mat("chrome", "rest", (0.80, 0.81, 0.83), rough=0.10, metal=1.0, env=0.92, ao=0.45),
    tyre=Mat("rubber_tyre", "rest", (0.085, 0.085, 0.09), rough=0.9, shader=tyre_shader, ao=0.8),
    rim=Mat("wheel_disc", "rest", (0.78, 0.77, 0.72), rough=0.4, shader=rim_shader, ao=0.8),
    under=Mat("chassis", "rest", (0.06, 0.06, 0.065), rough=0.7, ao=0.6),
    black=Mat("black_trim", "rest", (0.075, 0.075, 0.08), rough=0.55, ao=0.7),
    rubber=Mat("rubber_seal", "rest", (0.05, 0.05, 0.05), rough=0.8, ao=0.5),
    grille=Mat("grille_mesh", "rest", (0.05, 0.05, 0.055), rough=0.6, shader=grille_shader, ao=0.4),
    head=Mat("headlamp_lens", "rest", (0.93, 0.95, 0.97), rough=0.05, emit=(1.0, 0.95, 0.85), shader=headlamp_shader, env=0.45, ao=0.2),
    tail=Mat("taillamp_lens", "rest", (0.62, 0.05, 0.04), rough=0.1, emit=(1.0, 0.08, 0.04), ao=0.3),
    amber=Mat("marker_lamp", "rest", (0.95, 0.55, 0.10), rough=0.1, emit=(1.0, 0.55, 0.1), ao=0.3),
    interior=Mat("interior", "rest", (0.20, 0.17, 0.14), rough=0.85, ao=0.9),
    seat=Mat("interior_seat", "rest", (0.30, 0.26, 0.20), rough=0.8, ao=0.9, glbname="interior"),
    glass=Mat("glass", "glass", (0.05, 0.06, 0.07), rough=0.05, shader=glass_shader, ao=0.2),
    mirror=Mat("mirror_glass", "rest", (0.55, 0.60, 0.66), rough=0.03, metal=1.0, env=0.7, ao=0.2, glbname="chrome"),
)


def build_van():
    P = []
    AR = 0.45          # wheel arch radius
    def arch(cz):
        a = math.degrees(math.asin((SILL - RT) / AR))   # where the circle meets the sill
        return ("arc", cz, RT, AR, 180 - a, a)
    prof = rounded_profile([
        ("p", ZR, SILL, 0.05),
        arch(ZRA),
        arch(ZFA),
        ("p", ZF - 0.04, SILL, 0.06),
        ("p", ZF, 0.62, 0.10),
        ("p", ZF - 0.01, 1.18, 0.10),            # the windscreen base
        ("p", ZF - 0.16, 1.92, 0.10),            # windscreen top
        ("p", ZF - 0.40, ROOF, 0.30),            # roof front
        ("p", ZR + 0.22, ROOF, 0.22),            # roof rear
        ("p", ZR, 1.86, 0.12),
    ], step=0.07)
    def zshift(x, z, y):    # a gently bowed nose and tail in plan view
        f = np.clip((z - (ZF - 0.5)) / 0.5, 0, 1); r_ = np.clip(((ZR + 0.4) - z) / 0.4, 0, 1)
        return -0.07 * (x / BW) ** 2 * f + 0.04 * (x / BW) ** 2 * r_
    body = extrude_profile("body", M["paint"], prof, BW, r=0.11, mid=7, zshift=zshift, grid=0.11)
    # windows (holes + glass)
    ws_up = np.array([0, 0.74, -0.15]); ws_up /= np.linalg.norm(ws_up)
    ws_n = np.array([0, 0.15, 0.74]); ws_n /= np.linalg.norm(ws_n)
    wins = [
        ((0.53, 1.55, ZF - 0.08), (1, 0, 0), ws_up, 0.47, 0.30, -ws_n, dict(y0=1.4, h=0.45)),
        ((-0.53, 1.55, ZF - 0.08), (1, 0, 0), ws_up, 0.47, 0.30, -ws_n, dict(y0=1.4, h=0.45)),
        ((BW, 1.58, 1.52), (0, 0, 1), (0, 1, 0), 0.38, 0.30, (-1, 0, 0), dict(y0=1.4, h=0.5)),
        ((-BW, 1.58, 1.52), (0, 0, 1), (0, 1, 0), 0.38, 0.30, (1, 0, 0), dict(y0=1.4, h=0.5)),
        ((0.52, 1.58, ZR), (1, 0, 0), (0, 1, 0), 0.36, 0.22, (0, 0, 1), dict(y0=1.45, h=0.35)),
        ((-0.52, 1.58, ZR), (1, 0, 0), (0, 1, 0), 0.36, 0.22, (0, 0, 1), dict(y0=1.45, h=0.35)),
    ]
    def keep(c):
        k = np.ones(len(c), bool)
        for (ce, u, v, hu, hv, d, _) in wins:
            ce, u, v, d = (np.asarray(a, float) for a in (ce, u, v, d))
            dd = c - ce
            a_ = dd @ u / (hu * 0.97); b_ = dd @ v / (hv * 0.96)
            near = np.abs(dd @ d) < 0.30
            k &= ~(near & (np.abs(a_) ** 6 + np.abs(b_) ** 6 < 1))
        return k
    body_cut = [cut(b, keep) for b in body]
    P += body_cut
    for i, (ce, u, v, hu, hv, d, tg) in enumerate(wins):
        P += window(f"win{i}", M["glass"], M["rubber"], body, ce, u, v, hu, hv, d, n=7, nu=9, nv=7, offset=0.005,
                    frame_r=0.016, tag=tg)
    # windscreen centre post and wipers
    P.append(tube("ws_post", M["paint"], conform(body, np.array([[0, 1.55 + s * 0.28 * ws_up[1], ZF - 0.08 + s * 0.28 * ws_up[2]]
                                                                  for s in np.linspace(-1, 1, 5)]), -ws_n, 0.010)[0], 0.022, R=6))
    for sx in (1, -1):     # wipers parked along the base of each pane
        a0 = np.array([0.53 * sx - 0.40, 1.27, ZF + 0.012]); a1 = np.array([0.53 * sx + 0.30, 1.29, ZF + 0.008])
        P.append(tube(f"wiper{sx}", M["black"], conform(body, np.array([a0, a1]), (0, 0, -1), 0.012)[0], 0.009, R=5))
    # interior through the glass
    # the liner: the body's outline 6 cm inside (no arches), facing inward
    lprof = rounded_profile([("p", ZR + 0.06, SILL + 0.06, 0.0), ("p", ZF - 0.07, SILL + 0.06, 0.0), ("p", ZF - 0.07, 1.18, 0.08),
                             ("p", ZF - 0.22, 1.90, 0.08), ("p", ZF - 0.44, ROOF - 0.06, 0.26), ("p", ZR + 0.26, ROOF - 0.06, 0.18),
                             ("p", ZR + 0.06, 1.86, 0.10)], step=0.25)
    for lp in extrude_profile("liner", M["interior"], lprof, BW - 0.06, r=0.06, mid=1, zshift=zshift, grid=0.5):
        P.append(Part("liner", M["interior"], lp.V, lp.F[:, ::-1], -lp.N))
    P.append(box("dash", M["black"], (-1.08, 1.05, ZF - 0.45), (1.08, 1.25, ZF - 0.25)))
    for sx in (1, -1):
        P.append(box(f"seat{sx}", M["seat"], (min(0.15 * sx, 0.95 * sx), 0.80, 0.95), (max(0.15 * sx, 0.95 * sx), 1.05, 1.45)))
        P.append(box(f"back{sx}", M["seat"], (min(0.15 * sx, 0.95 * sx), 1.0, 0.88), (max(0.15 * sx, 0.95 * sx), 1.60, 1.00)))
    th = np.linspace(0, 2 * math.pi, 17)
    wc = np.array([0.55, 1.32, ZF - 0.52]); tilt = math.radians(30)
    ring = np.stack([wc[0] + 0.19 * np.cos(th), wc[1] + 0.19 * np.sin(th) * math.cos(tilt), wc[2] - 0.19 * np.sin(th) * math.sin(tilt)], 1)
    P.append(tube("steering", M["black"], ring, 0.016, R=6, cap0=False, cap1=False))
    # front: chrome bumper, grille band with slots, headlamps in chrome rings, parking lamps
    bump = body_loft("bumper", M["chrome"], [
        (-1.20, (0.30, 0.50, 0.03, 0.03, 6, 0.0, ZF - 0.16)),
        (-1.10, (0.28, 0.52, 0.06, 0.06, 6, 0.0, ZF - 0.08)),
        (0.0, (0.28, 0.52, 0.065, 0.065, 6, 0.0, ZF - 0.065)),
        (1.10, (0.28, 0.52, 0.06, 0.06, 6, 0.0, ZF - 0.08)),
        (1.20, (0.30, 0.50, 0.03, 0.03, 6, 0.0, ZF - 0.16)),
    ], R=18, S=15)
    P.append(transformed(bump, SWAP_ZX, name="bumper"))
    rbump = body_loft("rbumper", M["chrome"], [
        (-1.18, (0.30, 0.46, 0.03, 0.03, 6, 0.0, ZR + 0.16)),
        (-1.08, (0.28, 0.48, 0.055, 0.055, 6, 0.0, ZR + 0.08)),
        (0.0, (0.28, 0.48, 0.06, 0.06, 6, 0.0, ZR + 0.065)),
        (1.08, (0.28, 0.48, 0.055, 0.055, 6, 0.0, ZR + 0.08)),
        (1.18, (0.30, 0.46, 0.03, 0.03, 6, 0.0, ZR + 0.16)),
    ], R=18, S=15)
    P.append(transformed(rbump, SWAP_ZX, name="rbumper"))
    zfront = ZF - 0.005
    P.append(rbox("grille_band", M["chrome"], (-0.62, 0.66, zfront - 0.06), (0.62, 0.92, zfront + 0.02), r=0.03, R=16))
    P.append(box("grille_slots", M["grille"], (-0.56, 0.69, zfront - 0.03), (0.56, 0.89, zfront + 0.025)))
    for i in range(4):
        y = 0.715 + i * 0.05
        P.append(box(f"slot_bar{i}", M["chrome"], (-0.56, y - 0.008, zfront + 0.02), (0.56, y + 0.008, zfront + 0.035)))
    P.append(rbox("badge", M["chrome"], (-0.20, 1.02, zfront - 0.03), (0.20, 1.07, zfront + 0.02), r=0.012, R=10))
    for sx in (1, -1):
        c = np.array([0.86 * sx, 0.80, zfront - 0.04])
        P.append(revolve(f"hl_ring{sx}", M["chrome"], [(0.10, -0.04), (0.125, 0.0), (0.13, 0.03), (0.12, 0.05), (0.10, 0.045)], c, (0, 0, 1), R=20))
        P.append(revolve(f"hl_lens{sx}", M["head"], [(0.10, 0.04), (0.06, 0.055), (0.0001, 0.062)], c, (0, 0, 1), R=20,
                         tag=dict(center=list(c), r=0.10)))
        P.append(rbox(f"park{sx}", M["amber"], (min(0.60 * sx, 0.74 * sx), 0.58, zfront - 0.05), (max(0.60 * sx, 0.74 * sx), 0.64, zfront + 0.02), r=0.01, R=8))
        # rear: vertical tail lamps on the corners, reversing lamps
        P.append(rbox(f"tail{sx}", M["tail"], (min(1.02 * sx, 1.13 * sx), 0.62, ZR - 0.02), (max(1.02 * sx, 1.13 * sx), 1.02, ZR + 0.06), r=0.015, R=8))
        # mirrors on the A-pillars
        c0 = np.array([1.12 * sx, 1.50, ZF - 0.20])
        P.append(tube(f"mirror_arm{sx}", M["chrome"], [c0, c0 + [0.02 * sx, 0.06, -0.02], c0 + [0.02 * sx, 0.18, -0.03]], 0.012, R=6))
        mc = c0 + [0.02 * sx, 0.24, -0.04]
        P.append(revolve(f"mirror{sx}", M["chrome"], [(0.0001, -0.03), (0.07, -0.02), (0.08, 0.0), (0.075, 0.008)], mc, (0, 0, -1), R=14))
        P.append(revolve(f"mirror_glass{sx}", M["mirror"], [(0.072, 0.006), (0.0001, 0.009)], mc, (0, 0, -1), R=14))
        # door handles: cab door and cargo door
        P.append(box(f"handle_cab{sx}", M["chrome"], (min(BW * sx, (BW + 0.02) * sx), 1.30, 1.10), (max(BW * sx, (BW + 0.02) * sx), 1.33, 1.24)))
        P.append(box(f"handle_cargo{sx}", M["chrome"], (min(BW * sx, (BW + 0.02) * sx), 1.25, 0.10), (max(BW * sx, (BW + 0.02) * sx), 1.28, 0.24)))
        # drip rail along the roof edge
        P.append(tube(f"drip{sx}", M["chrome"], [[(BW - 0.035) * sx, ROOF - 0.07, ZF - 0.36], [(BW - 0.035) * sx, ROOF - 0.07, ZR + 0.25]], 0.012, R=6))
        # wheel arch liners (dark): the upper part of a drum inside each arch, so the arch shows depth
        for cz in (ZFA, ZRA):
            a = np.radians(np.linspace(-10, 190, 18))
            path = np.stack([np.full_like(a, (BW - 0.16) * sx), RT + (AR - 0.012) * np.sin(a), cz + (AR - 0.012) * np.cos(a)], 1)
            def wsec(i, t, sx=sx):
                return np.array([[-0.17, 0.0], [0.17, 0.0], [0.17, 0.01], [-0.17, 0.01]])
            P.append(sweep(f"well{sx}{cz:.1f}", M["under"], path, wsec, lateral=(1, 0, 0), cap0=False, cap1=False))
    P.append(box("rear_handle", M["chrome"], (0.06, 1.28, ZR - 0.03), (0.20, 1.31, ZR + 0.01)))
    P.append(box("plate", M["black"], (-0.17, 0.52, ZR - 0.05), (0.17, 0.69, ZR - 0.04)))
    # roof ribs (the sprite's roof streaks)
    for i in range(5):
        x = -0.64 + i * 0.32
        P.append(tube(f"rib{i}", M["paint"], [[x, ROOF - 0.005, ZF - 0.55], [x, ROOF - 0.005, ZR + 0.30]], 0.022, R=6))
    # chassis and wheels
    P.append(box("floor", M["under"], (-1.05, 0.28, ZR + 0.15), (1.05, 0.34, ZF - 0.15)))
    wm = dict(tyre=M["tyre"], rim=M["rim"], under=M["under"])
    for sx in (1, -1):
        for cz in (ZFA, ZRA):
            P += wheel(f"w{sx}{cz:.1f}", ((BW - 0.16) * sx, RT, cz), sx, RT, 0.24, 0.20, wm, R=26, hub="cap")
    P.append(tube("raxle", M["under"], [[-0.9, RT, ZRA], [0.9, RT, ZRA]], 0.05, R=8))
    P.append(box("diff", M["under"], (-0.14, RT - 0.12, ZRA - 0.12), (0.14, RT + 0.12, ZRA + 0.12)))
    P.append(tube("exhaust", M["under"], [[-0.55, 0.24, 0.6], [-0.55, 0.24, ZR + 0.25], [-0.58, 0.22, ZR - 0.02]], 0.03, R=8))
    return P


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/gta2-linux/assets-src/cars/models_art/068_van.glb"))
    ap.add_argument("--preview", default=None)
    ap.add_argument("--sprite", default=os.path.expanduser("~/gta2-linux/assets-src/cars/sprites_x4/068_van_default.png"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    parts = build_van()
    rep, groups = build(parts, a.out, report=dict(model=68, name="Van", forward="+z", maker="tools/vehicle_art/m068_van.py"))
    print(rep)
    if a.preview:
        import preview
        preview.sheet(groups, L, W, ROOF, a.sprite, a.preview, paint=(160, 150, 125), title="068 Van (carkit)")
