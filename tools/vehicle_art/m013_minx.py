#!/usr/bin/env python3
"""013 Minx: an early-1960s compact two-door (Hillman Minx / Dodge Dart / Falcon class).

Sprite (nose down, body 30 x 58 px, 64 px = 1 block = 3.8 m): the hood with a centre ridge
and the two headlamps lit at the nose, a dark greenhouse from the windscreen (row 38) to
the rear window (row 16) - read as a black vinyl roof over dark glass - a short trunk and
small fins with lamps at the rear corners. Axles at rows 46 / 14 (catalog rows mirrored).
Default paint: the sprite's copper tan.
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carkit import *
from m063_truck_cab import headlamp_shader, glass_shader, grille_shader
from m068_van import rim_shader

MB = METRES_PER_BLOCK
L = 58 / 64 * MB          # 3.444 m
W = 30 / 64 * MB          # 1.781 m
ZF, ZR = L / 2, -L / 2
BW = 0.86                 # body half width (mirrors to the footprint)
RT = 0.31
ZFA, ZRA = (46 - 29) / 64 * MB, (14 - 29) / 64 * MB      # +1.009 / -0.891
SILL = 0.27
BELT = 0.90
ROOF = 1.40
ZWS, ZRW = 0.58, -0.86    # windscreen base, rear window base


def line(d, w=0.004):
    return np.exp(-(d / w) ** 2)


def paint_shader(pos, nrm, part, col):
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    k = np.ones(len(pos))
    side = np.abs(nrm[:, 0]) > 0.6
    if part.name.startswith("body"):
        # the door (one per side), the hood and trunk shut lines
        k -= 0.55 * side * line(z - 0.52) * (y > 0.34) * (y < BELT)
        k -= 0.55 * side * line(z + 0.50) * (y > 0.34) * (y < BELT)
        top = nrm[:, 1] > 0.6
        k -= 0.5 * top * line(z - (ZWS + 0.06)) * (np.abs(x) < BW - 0.10)
        k -= 0.5 * top * line(np.abs(x) - (BW - 0.10)) * (z > ZWS + 0.06) * (z < ZF - 0.12)
        k -= 0.5 * top * line(z - (ZRW - 0.06)) * (np.abs(x) < BW - 0.10)
        k -= 0.5 * top * line(np.abs(x) - (BW - 0.10)) * (z < ZRW - 0.06) * (z > ZR + 0.12)
        # the hood's centre ridge (the sprite's hood line)
        k += top * (z > ZWS) * (0.10 * np.exp(-((x - 0.012) / 0.010) ** 2) - 0.10 * np.exp(-((x + 0.012) / 0.010) ** 2))
        # a shoulder crease along the belt: light above, shade below
        sw = y - (BELT - 0.06)
        k += side * (0.10 * np.exp(-((sw - 0.010) / 0.010) ** 2) - 0.16 * np.exp(-((sw + 0.010) / 0.010) ** 2))
    if part.name == "house":
        # black vinyl roof: everything above the side glass, with a fine grain
        roof = (y > ROOF - 0.10) | ((nrm[:, 1] > 0.75) & (y > 1.2))
        g = 0.11 + 0.015 * np.sin(x * 900) * np.sin(z * 700)
        out = col * k[:, None]
        out[roof] = np.array([0.06, 0.06, 0.06]) + 0.02 * np.sin(x[roof] * 900)[:, None] * np.sin(z[roof] * 700)[:, None]
        return out
    return col * np.clip(k, 0.2, 1.3)[:, None]


def ww_tyre_shader(pos, nrm, part, col):
    c = np.asarray(part.tag["center"]); a = np.asarray(part.tag["axis"]); r0 = part.tag["radius"]; w = part.tag["width"]
    d = pos - c
    t = d @ a
    rad = np.linalg.norm(d - t[:, None] * a, axis=1)
    e1 = np.array([0, 1.0, 0]); e2 = np.cross(a, e1)
    ang = np.arctan2(d @ e2, d @ e1)
    out = col.copy()
    tread = rad > r0 - 0.025
    g = np.zeros(len(pos))
    for gc in (-0.2, 0.0, 0.2):
        g = np.maximum(g, np.exp(-((t / w - gc) / 0.04) ** 2))
    out[tread] *= (1 - 0.5 * g[tread] - 0.35 * (np.sin(ang[tread] * 70) > 0.6))[:, None]
    # the whitewall on the outer sidewall
    outer = (t > 0) & ~tread
    ww = outer & (rad > r0 * 0.74) & (rad < r0 * 0.88)
    out[ww] = np.array([0.86, 0.85, 0.82])
    rough = np.where(tread, 0.92, 0.8)
    return out, rough, None


M = dict(
    paint=Mat("paint", "paint", PAINT_NEUTRAL, rough=0.3, shader=paint_shader, ao=0.9),
    chrome=Mat("chrome", "rest", (0.80, 0.81, 0.83), rough=0.10, metal=1.0, env=0.92, ao=0.45),
    tyre=Mat("rubber_tyre", "rest", (0.085, 0.085, 0.09), rough=0.9, shader=ww_tyre_shader, ao=0.8),
    rim=Mat("wheel_disc", "rest", (0.78, 0.77, 0.72), rough=0.4, shader=rim_shader, ao=0.8),
    under=Mat("chassis", "rest", (0.06, 0.06, 0.065), rough=0.7, ao=0.6),
    black=Mat("black_trim", "rest", (0.075, 0.075, 0.08), rough=0.55, ao=0.7),
    rubber=Mat("rubber_seal", "rest", (0.05, 0.05, 0.05), rough=0.8, ao=0.5),
    # VEHICLE-ART-5 (vv-013): no painted wires behind the bars (a 2 cm hard-edged stripe aliased into stair
    # steps at the bake's texel size); the slats are geometry (gbar below), the mesh behind them plain dark.
    grille=Mat("grille_mesh", "rest", (0.035, 0.035, 0.04), rough=0.6, ao=0.4),
    head=Mat("headlamp_lens", "rest", (0.93, 0.95, 0.97), rough=0.05, emit=(1.0, 0.95, 0.85), shader=headlamp_shader, env=0.45, ao=0.2),
    tail=Mat("taillamp_lens", "rest", (0.62, 0.05, 0.04), rough=0.1, emit=(1.0, 0.08, 0.04), ao=0.3),
    amber=Mat("marker_lamp", "rest", (0.95, 0.55, 0.10), rough=0.1, emit=(1.0, 0.55, 0.1), ao=0.3),
    interior=Mat("interior", "rest", (0.24, 0.20, 0.16), rough=0.85, ao=0.9),
    seat=Mat("interior_seat", "rest", (0.55, 0.45, 0.33), rough=0.8, ao=0.9, glbname="interior"),
    glass=Mat("glass", "glass", (0.05, 0.06, 0.07), rough=0.05, shader=glass_shader, ao=0.2),
    mirror=Mat("mirror_glass", "rest", (0.55, 0.60, 0.66), rough=0.03, metal=1.0, env=0.7, ao=0.2, glbname="chrome"),
)


def build_minx():
    P = []
    AR = 0.385
    def arch(cz):
        a = math.degrees(math.asin((SILL - RT) / AR))
        return ("arc", cz, RT, AR, 180 - a, a)
    prof = rounded_profile([
        ("p", ZR + 0.05, SILL, 0.06),
        arch(ZRA), arch(ZFA),
        ("p", ZF - 0.07, SILL, 0.07),
        ("p", ZF, 0.50, 0.12),
        ("p", ZF - 0.06, 0.80, 0.10),
        ("p", ZWS, BELT + 0.02, 0.0),
        ("p", ZRW, BELT + 0.02, 0.0),
        ("p", ZR + 0.08, BELT, 0.10),
        ("p", ZR, 0.62, 0.10),
    ], step=0.05)
    def zshift(x, z, y):
        f = np.clip((z - (ZF - 0.6)) / 0.6, 0, 1); r_ = np.clip(((ZR + 0.4) - z) / 0.4, 0, 1)
        return -0.16 * (x / BW) ** 2 * f ** 1.5 + 0.03 * (x / BW) ** 2 * r_
    def hw(y):   # slight tumblehome above the shoulder, tuck under below the sill line
        return BW - 0.05 * np.clip((y - 0.70) / 0.25, 0, 1) - 0.04 * np.clip((0.40 - y) / 0.13, 0, 1)
    body = extrude_profile("body", M["paint"], prof, BW, r=0.10, mid=7, zshift=zshift, xfun=hw, grid=0.10)
    P += body
    # greenhouse (paint pillars, the vinyl roof painted by the shader), window holes
    house = body_loft("house", M["paint"], [
        (ZRW - 0.04, (0.84, BELT + 0.04, 0.78, 0.74, 3.6, 0.0, 0)),
        (ZRW + 0.18, (0.84, 1.28, 0.78, 0.66, 3.6, 0.02, 0)),
        (-0.48, (0.84, ROOF, 0.78, 0.65, 3.8, 0.03, 0)),
        (0.18, (0.84, ROOF + 0.01, 0.78, 0.65, 3.8, 0.03, 0)),
        (0.36, (0.84, 1.33, 0.78, 0.67, 3.6, 0.02, 0)),
        (ZWS + 0.04, (0.84, BELT + 0.04, 0.78, 0.74, 3.6, 0.0, 0)),
    ], R=56, S=30, nb=8)
    ws_up = np.array([0, 0.48, -0.30]); ws_up /= np.linalg.norm(ws_up)
    ws_n = np.array([0, 0.30, 0.48]); ws_n /= np.linalg.norm(ws_n)
    rw_up = np.array([0, 0.40, 0.30]); rw_up /= np.linalg.norm(rw_up)
    rw_n = np.array([0, 0.30, -0.40]); rw_n /= np.linalg.norm(rw_n)
    wins = [
        ((0.0, 1.14, 0.46), (1, 0, 0), ws_up, 0.60, 0.21, -ws_n, dict(y0=1.0, h=0.35)),
        ((0.0, 1.13, -0.74), (1, 0, 0), rw_up, 0.58, 0.19, -rw_n, dict(y0=1.0, h=0.35)),
        ((0.75, 1.15, 0.05), (0, 0, 1), (0, 1, 0), 0.38, 0.17, (-1, 0, 0), dict(y0=1.05, h=0.3)),
        ((-0.75, 1.15, 0.05), (0, 0, 1), (0, 1, 0), 0.38, 0.17, (1, 0, 0), dict(y0=1.05, h=0.3)),
        ((0.73, 1.14, -0.52), (0, 0, 1), (0, 1, 0), 0.14, 0.14, (-1, 0, 0), dict(y0=1.05, h=0.3)),
        ((-0.73, 1.14, -0.52), (0, 0, 1), (0, 1, 0), 0.14, 0.14, (1, 0, 0), dict(y0=1.05, h=0.3)),
    ]
    def keep(c):
        k = np.ones(len(c), bool)
        for (ce, u, v, hu, hv, d, _) in wins:
            ce, u, v, d = (np.asarray(a, float) for a in (ce, u, v, d))
            dd = c - ce
            a_ = dd @ u / (hu * 0.97); b_ = dd @ v / (hv * 0.95)
            near = np.abs(dd @ d) < 0.25
            k &= ~(near & (np.abs(a_) ** 5 + np.abs(b_) ** 5 < 1))
        return k
    P.append(cut(house, keep))
    for i, (ce, u, v, hu, hv, d, tg) in enumerate(wins):
        P += window(f"win{i}", M["glass"], M["chrome"], [house], ce, u, v, hu, hv, d, n=5 if i < 2 else 6, nu=10, nv=6,
                    offset=0.004, frame_r=0.011, tag=tg)
    # interior: inset greenhouse liner, seats, dash, wheel
    liner = body_loft("liner", M["interior"], [
        (ZRW + 0.06, (0.80, 1.05, 0.72, 0.64, 3.6, 0.0, 0)), (-0.48, (0.80, ROOF - 0.05, 0.72, 0.60, 3.8, 0.02, 0)),
        (0.18, (0.80, ROOF - 0.04, 0.72, 0.60, 3.8, 0.02, 0)), (ZWS - 0.06, (0.80, 1.02, 0.72, 0.66, 3.6, 0.0, 0))], R=20, S=8, nb=8)
    P.append(Part("liner", M["interior"], liner.V, liner.F[:, ::-1], -liner.N))
    P.append(box("dash", M["black"], (-0.74, 0.80, ZWS - 0.18), (0.74, 0.96, ZWS)))
    P.append(box("bench", M["seat"], (-0.70, 0.45, -0.45), (0.70, 0.66, 0.10)))
    P.append(box("bench_back", M["seat"], (-0.70, 0.62, -0.52), (0.70, 1.12, -0.40)))
    th = np.linspace(0, 2 * math.pi, 17)
    wc = np.array([0.36, 1.00, 0.22]); tilt = math.radians(55)
    ring = np.stack([wc[0] + 0.17 * np.cos(th), wc[1] + 0.17 * np.sin(th) * math.cos(tilt), wc[2] - 0.17 * np.sin(th) * math.sin(tilt)], 1)
    P.append(tube("steering", M["black"], ring, 0.014, R=6, cap0=False, cap1=False))
    # tail fins with round lamps at the rear corners (the sprite's corner points)
    for sx in (1, -1):
        def fsec(i, t):
            th = np.linspace(0, 2 * math.pi, 12, endpoint=False) - math.pi / 2
            h = 0.02 + 0.06 * t
            return np.stack([sexp(np.cos(th), 3) * 0.05, sexp(np.sin(th), 3) * h], 1)
        zz = np.linspace(-0.30, ZR + 0.05, 10)
        path = np.stack([np.full_like(zz, (BW - 0.10) * sx), BELT - 0.02 + 0.07 * ((zz - zz[0]) / (zz[-1] - zz[0])) ** 2, zz], 1)
        P.append(sweep(f"fin{sx}", M["paint"], path, fsec, lateral=(1, 0, 0)))
        c = np.array([(BW - 0.12) * sx, 0.80, ZR + 0.02])
        P.append(revolve(f"tail{sx}", M["tail"], [(0.0001, 0.02), (0.06, 0.0), (0.075, -0.04)], c, (0, 0, -1), R=16))
        P.append(revolve(f"tail_ring{sx}", M["chrome"], [(0.075, -0.04), (0.085, -0.03), (0.08, 0.0), (0.06, 0.005)], c, (0, 0, -1), R=16))
        # headlamps with chrome rings and hooded fenders; parking lamps
        hc = np.array([(BW - 0.20) * sx, 0.66, ZF - 0.11])
        P.append(revolve(f"hl_ring{sx}", M["chrome"], [(0.085, -0.03), (0.10, 0.0), (0.105, 0.02), (0.095, 0.035), (0.085, 0.03)], hc, (0, 0, 1), R=18))
        P.append(revolve(f"hl_lens{sx}", M["head"], [(0.085, 0.028), (0.05, 0.04), (0.0001, 0.046)], hc, (0, 0, 1), R=18,
                         tag=dict(center=list(hc), r=0.085)))
        P.append(rbox(f"park{sx}", M["amber"], (min(0.42 * sx, 0.56 * sx), 0.40, ZF - 0.10), (max(0.42 * sx, 0.56 * sx), 0.45, ZF - 0.03), r=0.01, R=8))
        # side spear moulding, door handle, mirror on the door
        sp = conform(body, np.array([[BW * sx, 0.70, z] for z in np.linspace(ZF - 0.25, ZR + 0.20, 10)]), (-sx, 0, 0), 0.004)[0]
        P.append(tube(f"spear{sx}", M["chrome"], sp, 0.011, R=6))
        P.append(box(f"handle{sx}", M["chrome"], (min((BW - 0.04) * sx, (BW + 0.005) * sx), 0.84, -0.38), (max((BW - 0.04) * sx, (BW + 0.005) * sx), 0.86, -0.27)))
        mc = np.array([(BW + 0.0) * sx, 1.0, 0.48])
        P.append(tube(f"mirror_stalk{sx}", M["chrome"], [mc + [-0.08 * sx, -0.08, 0.0], mc], 0.01, R=6))
        P.append(revolve(f"mirror{sx}", M["chrome"], [(0.0001, -0.025), (0.05, -0.015), (0.055, 0.0), (0.05, 0.006)], mc, (0, 0, -1), R=12))
        P.append(revolve(f"mirror_glass{sx}", M["mirror"], [(0.05, 0.005), (0.0001, 0.007)], mc, (0, 0, -1), R=12))
    # grille between the headlamps, bumpers, plate
    # VEHICLE-ART-5 (vv-013): the grille follows the nose. The nose's plan curve (zshift) pulls its sides
    # back 5 cm at the grille's ends while the grille was flat boxes, so the prow buried their middle
    # and the bars showed as stair-stepped wedges. Now a dark pane conformed to the nose with a chrome
    # rim, five chrome slats and a centre bar laid on it, and the badge on the slats.
    P += window("grille_mesh", M["grille"], M["chrome"], body, (0.0, 0.59, ZF + 0.3), (1, 0, 0), (0, 1, 0), 0.47, 0.085,
                (0, 0, -1), n=8.0, nu=24, nv=6, offset=0.003, frame_r=0.014)
    xs = np.linspace(-0.45, 0.45, 19)
    for i in range(5):
        y = 0.533 + i * 0.029
        pts = conform(body, np.array([[x, y, ZF + 0.3] for x in xs]), (0, 0, -1), 0.010)[0]
        P.append(tube(f"gbar{i}", M["chrome"], pts, 0.0058, R=8))
    pts = conform(body, np.array([[0.0, y, ZF + 0.3] for y in np.linspace(0.515, 0.665, 6)]), (0, 0, -1), 0.012)[0]
    P.append(tube("gbar_mid", M["chrome"], pts, 0.008, R=8))
    bc = conform(body, np.array([[0.0, 0.59, ZF + 0.3]]), (0, 0, -1), 0.0)[0][0]
    P.append(rbox("badge", M["chrome"], (-0.05, 0.56, bc[2] + 0.010), (0.05, 0.62, bc[2] + 0.024), r=0.01, R=8))
    def bumper(zc, back):
        s = -1 if back else 1
        b = body_loft("bump", M["chrome"], [
            (-0.88, (0.30, 0.42, 0.03, 0.03, 6, 0.0, zc - s * 0.16)),
            (-0.80, (0.28, 0.45, 0.055, 0.055, 6, 0.0, zc - s * 0.05)),
            (0.0, (0.28, 0.45, 0.06, 0.06, 6, 0.0, zc)),
            (0.80, (0.28, 0.45, 0.055, 0.055, 6, 0.0, zc - s * 0.05)),
            (0.88, (0.30, 0.42, 0.03, 0.03, 6, 0.0, zc - s * 0.16))], R=16, S=13)
        return transformed(b, SWAP_ZX, name="bumper_r" if back else "bumper")
    P.append(bumper(ZF - 0.065, False)); P.append(bumper(ZR + 0.065, True))
    P.append(box("plate", M["black"], (-0.16, 0.48, ZR - 0.01), (0.16, 0.62, ZR + 0.005)))
    # underside, arch liners, wheels
    P.append(box("floor", M["under"], (-0.80, 0.24, ZR + 0.25), (0.80, 0.30, ZF - 0.25)))
    for sx in (1, -1):
        for cz in (ZFA, ZRA):
            a = np.radians(np.linspace(-15, 195, 16))
            path = np.stack([np.full_like(a, (BW - 0.14) * sx), RT + (AR - 0.01) * np.sin(a), cz + (AR - 0.01) * np.cos(a)], 1)
            P.append(sweep(f"well{sx}{cz:.1f}", M["under"], path, lambda i, t: np.array([[-0.15, 0.0], [0.15, 0.0], [0.15, 0.01], [-0.15, 0.01]]),
                           cap0=False, cap1=False))
    wm = dict(tyre=M["tyre"], rim=M["rim"], under=M["under"])
    for sx in (1, -1):
        for cz in (ZFA, ZRA):
            P += wheel(f"w{sx}{cz:.1f}", ((BW - 0.15) * sx, RT, cz), sx, RT, 0.19, 0.18, wm, R=26, hub="cap")
    P.append(tube("exhaust", M["under"], [[0.45, 0.20, 0.4], [0.45, 0.20, ZR + 0.15], [0.47, 0.19, ZR - 0.01]], 0.025, R=8))
    return P


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/gta2-linux/assets-src/cars/models_art/013_minx.glb"))
    ap.add_argument("--preview", default=None)
    ap.add_argument("--sprite", default=os.path.expanduser("~/gta2-linux/assets-src/cars/sprites_x4/013_minx_default.png"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    parts = build_minx()
    rep, groups = build(parts, a.out, report=dict(model=13, name="Minx", forward="+z", maker="tools/vehicle_art/m013_minx.py"))
    print(rep)
    if a.preview:
        import preview
        preview.sheet(groups, L, W, ROOF, a.sprite, a.preview, paint=(173, 120, 90), title="013 Minx (carkit)")
