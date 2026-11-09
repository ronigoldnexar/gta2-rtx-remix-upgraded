#!/usr/bin/env python3
"""063 Truck Cab: a 1950s short-nose conventional tractor, laid out on the game's sprite.

Sprite (nose down, 40 x 63 px, 64 px = 1 block = 3.8 m here): chrome bumper and grille in
the bottom rows, a short hood with a centre strip, the cab roof (lit paint) with two round
roof lamps, and behind it the dark chassis with the fifth wheel's round plate. Axles at
rows 52 / 12, windscreen at row 49, rear window at row 28 (catalog rows are mirrored).
"""
import math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from carkit import *

MB = METRES_PER_BLOCK
L = 63 / 64 * MB          # 3.741 m
W = 40 / 64 * MB          # 2.375 m
ZF, ZR = L / 2, -L / 2
HW = W / 2


def rows_to_z(row):       # sprite row (from the top, nose-down drawing) -> z
    return (row - 31.5) / 64 * MB


# ------------------------------------------------------------------ shaders ----

def paint_shader(pos, nrm, part, col):
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    k = np.ones(len(pos))
    if part.name == "cab":
        side = np.abs(x) > 0.80
        # door shut lines: front edge just behind the windscreen pillar, rear edge, bottom
        def line(d, w=0.0045):
            return np.exp(-(d / w) ** 2)
        door = side & (y > 1.02) & (y < 2.30)
        k -= 0.55 * door * line(z - 0.82) * (y < 1.86)
        k -= 0.55 * door * line(z + 0.02)
        k -= 0.50 * side * line(y - 1.06) * (z > -0.02) * (z < 0.82)
        # a pressed swage line along the side, catching light above and shade below
        sw = y - 1.62
        k += side * (0.10 * np.exp(-((sw - 0.010) / 0.008) ** 2) - 0.14 * np.exp(-((sw + 0.008) / 0.008) ** 2))
        # the cab's back panel: a rain gutter shade under the roof edge
        k -= 0.25 * (np.abs(y - 2.30) < 0.006) * (nrm[:, 1] < 0.6)
    if part.name == "hood":
        # the hood's side louvres (vents), a row of dark slots on each side
        side = (np.abs(x) > 0.40) & (nrm[:, 1] < 0.55)
        for i in range(5):
            zc = 1.18 + i * 0.09
            k -= 0.6 * side * (np.abs(z - zc) < 0.012) * (y > 1.30) * (y < 1.55)
        # the hinge line along the top centre
        k -= 0.35 * np.exp(-(x / 0.004) ** 2) * (nrm[:, 1] > 0.8)
    return col * np.clip(k, 0.2, 1.3)[:, None]


def tyre_shader(pos, nrm, part, col):
    c = np.asarray(part.tag["center"]); a = np.asarray(part.tag["axis"]); r0 = part.tag["radius"]; w = part.tag["width"]
    d = pos - c
    t = d @ a                          # across the tread
    rad = np.linalg.norm(d - t[:, None] * a, axis=1)
    # angle round the axle
    e1 = np.array([0, 1.0, 0]); e2 = np.cross(a, e1)
    ang = np.arctan2(d @ e2, d @ e1)
    k = np.ones(len(pos))
    tread = rad > r0 - 0.03
    # circumferential grooves and lateral blocks (a rib/lug truck tread)
    g = np.zeros(len(pos))
    for gc in (-0.22, 0.0, 0.22):
        g = np.maximum(g, np.exp(-((t / w - gc) / 0.035) ** 2))
    lug = (np.sin(ang * 60 + (t / w > 0) * 1.4) > 0.55) * (np.abs(t / w) > 0.30)
    k -= tread * (0.55 * g + 0.45 * lug)
    # sidewall: a raised ring with lettering-like modulation, the bead dark
    side = ~tread
    ring = np.exp(-((rad - (r0 * 0.86)) / 0.012) ** 2)
    k += side * 0.35 * ring * (np.sin(ang * 40) > 0.1)
    k += side * 0.12 * np.exp(-((rad - (r0 * 0.94)) / 0.02) ** 2)
    rough = np.where(tread, 0.92, 0.85)
    return col * np.clip(k, 0.25, 1.6)[:, None], rough, None


def rim_shader(pos, nrm, part, col):
    c = np.asarray(part.tag["center"]); a = np.asarray(part.tag["axis"]); r0 = part.tag["radius"]
    d = pos - c
    t = d @ a
    rad = np.linalg.norm(d - t[:, None] * a, axis=1)
    e1 = np.array([0, 1.0, 0]); e2 = np.cross(a, e1)
    ang = np.arctan2(d @ e2, d @ e1)
    out = col.copy()
    rough = np.full(len(pos), 0.35); metal = np.full(len(pos), 0.6)
    # disc wheel painted off-white; the hub chrome
    hub = rad < r0 * 0.42
    out[~hub] = np.array([0.80, 0.79, 0.74])
    rough[~hub] = 0.45; metal[~hub] = 0.0
    out[hub] = np.array([0.86, 0.87, 0.88])
    # ventilation holes in the disc (dark)
    holes = (np.abs(rad - r0 * 0.63) < r0 * 0.08) & (np.cos(ang * 6) > 0.72)
    out[holes] = np.array([0.04, 0.04, 0.04]); rough[holes] = 0.9; metal[holes] = 0.0
    # wheel nuts on the hub flange
    nuts = (np.abs(rad - r0 * 0.36) < 0.016) & (np.cos(ang * 10) > 0.85)
    out[nuts] = np.array([0.55, 0.55, 0.56])
    # the rim's outer lip darker (dirt) and a dark ring where the disc meets the hub
    out[np.abs(rad - r0 * 0.44) < 0.008] *= 0.35
    out[rad > r0 * 0.93] *= 0.55
    return out, rough, metal


def grille_shader(pos, nrm, part, col):
    # a dark mesh behind the bars: fine horizontal wires
    y = pos[:, 1]
    k = 1.0 + 0.8 * (np.sin(y * 2 * math.pi / 0.02) > 0.6)
    return col * k[:, None]


def headlamp_shader(pos, nrm, part, col):
    c = np.asarray(part.tag["center"]); d = pos - c
    rr = np.sqrt(d[:, 0] ** 2 + d[:, 1] ** 2) / part.tag["r"]
    # fluted lens: concentric rings and a vertical prism pattern, brighter centre (reflector)
    k = 0.80 + 0.20 * np.cos(rr * 22) * (rr > 0.25) + 0.25 * np.exp(-(rr / 0.25) ** 2)
    k += 0.08 * (np.sin(d[:, 0] / part.tag["r"] * 40) > 0.5)
    return col * k[:, None]


def sealed_beam_shader(pos, nrm, part, col):
    """VEHICLE-ART-6 (vv-063): a 1950s sealed-beam lamp seen by day: a silvered parabolic reflector behind
    clear prism glass (a square grid of lens cells), the bulb's dark shield and chrome cap in the middle, a
    dark rubber seal where the glass meets the bezel. The flat grey dome read as a hubcap."""
    c = np.asarray(part.tag["center"]); d = pos - c
    r0 = part.tag["r"]
    x, y = d[:, 0] / r0, d[:, 1] / r0
    rr = np.sqrt(x ** 2 + y ** 2)
    # the reflector: bright annulus (it mirrors the sky round the bulb), darker towards the rim and centre
    b = 0.50 + 0.42 * np.exp(-((rr - 0.52) / 0.24) ** 2) + 0.10 * np.clip(y, 0, 1)
    # prism cells: thin dark lines on a 0.17 r grid inside the glass's clear area
    cell = 0.17
    gx = np.abs(((x / cell) % 1.0) - 0.5) > 0.40
    gy = np.abs(((y / cell) % 1.0) - 0.5) > 0.40
    b = np.where((gx | gy) & (rr < 0.86), b * 0.74, b)
    # bulb shield (dark disc) with a bright chrome cap ring round it
    b = np.where(rr < 0.11, 0.30, b)
    b = np.where((rr >= 0.11) & (rr < 0.16), 0.98, b)
    # the seal at the rim
    b = np.where(rr > 0.90, 0.16, b)
    tint = np.array([0.90, 0.92, 0.95])
    out = b[:, None] * tint[None, :]
    # a warm cast in the reflector's hot ring (the filament's colour)
    out[:, 0] += 0.04 * np.exp(-((rr - 0.30) / 0.10) ** 2)
    return out.clip(0, 1)


def tank_shader(pos, nrm, part, col):
    z = pos[:, 2]
    out = col.copy()
    for zc in part.tag.get("straps", []):
        s = np.abs(z - zc) < 0.025
        out[s] = np.array([0.08, 0.08, 0.08])
    # a fine brushed streak along the tank
    out *= (1 + 0.04 * np.sin(pos[:, 1] * 400))[:, None]
    return out


def fifth_shader(pos, nrm, part, col):
    c = np.array([0, 0, -1.05]); d = pos - c
    out = col.copy()
    # the V throat and the slot toward the rear
    slot = (np.abs(d[:, 0]) < 0.05 + np.clip(-(d[:, 2] + 0.15), 0, 1) * 0.6) & (d[:, 2] < 0.05) & (nrm[:, 1] > 0.5)
    out[slot] = np.array([0.02, 0.02, 0.02])
    # grease sheen ring
    rr = np.sqrt(d[:, 0] ** 2 + d[:, 2] ** 2)
    out *= (1 + 0.25 * np.exp(-((rr - 0.25) / 0.06) ** 2))[:, None]
    return out


def shield_shader(pos, nrm, part, col):
    # perforated heat shield: a grid of dark holes
    y = pos[:, 1]; a = np.arctan2(pos[:, 0] - part.tag["cx"], pos[:, 2] - part.tag["cz"])
    holes = (np.sin(y * 2 * math.pi / 0.035) > 0.55) & (np.sin(a * 24) > 0.55)
    out = col.copy(); out[holes] *= 0.25
    return out


def glass_shader(pos, nrm, part, col):
    # tinted glass: the sky in the upper half of the pane, the dark cab inside lower down,
    # a soft diagonal streak
    up = nrm[:, 1]
    refl = sky_env(nrm)
    y = pos[:, 1]
    k = np.clip((y - part.tag.get("y0", 1.8)) / max(part.tag.get("h", 0.4), 0.05), 0, 1)
    streak = 0.10 * np.exp(-(((pos[:, 0] + pos[:, 2]) * 3.0 - 0.4) % 2.0 - 1.0) ** 2 / 0.02)
    base = np.array([0.05, 0.06, 0.07])
    out = base * (1 - 0.6 * k[:, None]) + refl * (0.18 + 0.30 * k[:, None]) + streak[:, None]
    return out, np.full(len(pos), 0.05), np.zeros(len(pos))


# ---------------------------------------------------------------- materials ----

M = dict(
    paint=Mat("paint", "paint", PAINT_NEUTRAL, rough=0.32, metal=0.0, shader=paint_shader, ao=0.9),
    chrome=Mat("chrome", "rest", (0.80, 0.81, 0.83), rough=0.10, metal=1.0, env=0.92, ao=0.45),
    tyre=Mat("rubber_tyre", "rest", (0.085, 0.085, 0.09), rough=0.9, shader=tyre_shader, ao=0.8),
    rim=Mat("wheel_disc", "rest", (0.8, 0.8, 0.76), rough=0.4, metal=0.5, shader=rim_shader, ao=0.8, env=0.15),
    under=Mat("chassis", "rest", (0.06, 0.06, 0.065), rough=0.7, ao=0.6),
    black=Mat("black_trim", "rest", (0.075, 0.075, 0.08), rough=0.55, ao=0.7),
    rubber=Mat("rubber_seal", "rest", (0.05, 0.05, 0.05), rough=0.8, ao=0.5),
    grille=Mat("grille_mesh", "rest", (0.04, 0.04, 0.045), rough=0.6, shader=grille_shader, ao=0.4),
    steel=Mat("steel_dark", "rest", (0.20, 0.20, 0.21), rough=0.45, metal=0.7, shader=fifth_shader, ao=0.7),
    tank=Mat("chrome_tank", "rest", (0.80, 0.81, 0.83), rough=0.14, metal=1.0, env=0.8, ao=0.55, shader=tank_shader, glbname="chrome"),
    shield=Mat("chrome_shield", "rest", (0.78, 0.79, 0.80), rough=0.2, metal=1.0, env=0.75, ao=0.5, shader=shield_shader, glbname="chrome"),
    head=Mat("headlamp_lens", "rest", (0.93, 0.95, 0.97), rough=0.05, emit=(1.0, 0.95, 0.85), shader=headlamp_shader, env=0.45, ao=0.2),
    beam=Mat("headlamp_beam", "rest", (0.93, 0.95, 0.97), rough=0.05, emit=(1.0, 0.95, 0.85), shader=sealed_beam_shader, env=0.12, ao=0.1,
             glbname="headlamp_lens"),
    tail=Mat("taillamp_lens", "rest", (0.62, 0.05, 0.04), rough=0.1, emit=(1.0, 0.08, 0.04), ao=0.3),
    amber=Mat("marker_lamp", "rest", (0.95, 0.55, 0.10), rough=0.1, emit=(1.0, 0.55, 0.1), ao=0.3),
    interior=Mat("interior", "rest", (0.20, 0.17, 0.14), rough=0.85, ao=0.9),
    seat=Mat("interior_seat", "rest", (0.34, 0.12, 0.10), rough=0.8, ao=0.9, glbname="interior"),
    glass=Mat("glass", "glass", (0.05, 0.06, 0.07), rough=0.05, shader=glass_shader, ao=0.2),
    mirror=Mat("mirror_glass", "rest", (0.55, 0.60, 0.66), rough=0.03, metal=1.0, env=0.7, ao=0.2, glbname="chrome"),
)


def both(parts):
    out = []
    for p in parts:
        out.append(p); out.append(p.mirrored_x())
    return out


# ------------------------------------------------------------------ model ------

def build_truck():
    P = []
    zFA, zRA = rows_to_z(52), rows_to_z(12)      # front / rear axle
    RT = 0.50                                    # tyre radius
    cab_z0, cab_z1 = -0.42, 1.02
    # ---- cab (paint) with window holes
    cab = body_loft("cab", M["paint"], [
        (cab_z0, (1.00, 2.34, 0.97, 0.90, 4.5, 0.03, 0)),
        (cab_z0 + 0.07, (0.98, 2.42, 1.02, 0.95, 4.8, 0.05, 0)),
        (0.45, (0.98, 2.45, 1.03, 0.96, 4.8, 0.06, 0)),
        (0.76, (0.98, 2.41, 1.03, 0.95, 4.8, 0.05, 0)),
        (0.98, (0.98, 1.88, 1.01, 0.88, 4.5, 0.03, 0)),
        (cab_z1, (1.00, 1.80, 0.98, 0.84, 4.5, 0.02, 0)),
    ], R=44, S=30, nb=9)
    slope_up = np.array([0, 0.53, -0.21]); slope_up /= np.linalg.norm(slope_up)
    slope_n = np.array([0, 0.21, 0.53]); slope_n /= np.linalg.norm(slope_n)
    wins = [
        # (centre, u, v, half_u, half_v, into-body direction, tag)
        ((0.43, 2.13, 0.875), (1, 0, 0), slope_up, 0.36, 0.215, -slope_n, dict(y0=1.95, h=0.35)),
        ((-0.43, 2.13, 0.875), (1, 0, 0), slope_up, 0.36, 0.215, -slope_n, dict(y0=1.95, h=0.35)),
        ((1.05, 2.02, 0.42), (0, 0, 1), (0, 1, 0), 0.33, 0.24, (-1, 0, 0), dict(y0=1.85, h=0.4)),
        ((-1.05, 2.02, 0.42), (0, 0, 1), (0, 1, 0), 0.33, 0.24, (1, 0, 0), dict(y0=1.85, h=0.4)),
        ((0.0, 2.04, -0.45), (1, 0, 0), (0, 1, 0), 0.48, 0.16, (0, 0, 1), dict(y0=1.95, h=0.25)),
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
    cab_cut = cut(cab, keep)
    P.append(cab_cut)
    for i, (ce, u, v, hu, hv, d, tg) in enumerate(wins):
        P += window(f"win{i}", M["glass"], M["rubber"], [cab], ce, u, v, hu, hv, d, n=7, nu=9, nv=7,
                    offset=0.005, frame_r=0.016, tag=tg)
    # centre post of the split windscreen (chrome strip)
    post = conform([cab], np.array([[0, 2.13 + s * 0.22 * slope_up[1], 0.875 + s * 0.22 * slope_up[2]] for s in np.linspace(-1, 1, 6)]),
                   -slope_n, 0.012)[0]
    P.append(tube("ws_post", M["chrome"], post, 0.018, R=6))
    # interior seen through the glass: a liner (faces inward), dash, seats, wheel
    # the liner: the cab's own shape 5 cm inside, facing inward
    liner = body_loft("liner", M["interior"], [
        (cab_z0 + 0.08, (1.03, 2.37, 0.93, 0.85, 4.8, 0.03, 0)),
        (0.45, (1.03, 2.40, 0.98, 0.90, 4.8, 0.05, 0)),
        (0.72, (1.03, 2.36, 0.98, 0.90, 4.8, 0.04, 0)),
        (0.93, (1.03, 1.84, 0.95, 0.82, 4.5, 0.02, 0)),
    ], R=24, S=10, nb=9)
    liner = Part("liner", M["interior"], liner.V, liner.F[:, ::-1], -liner.N)
    P.append(liner)
    P.append(box("dash", M["black"], (-0.92, 1.45, 0.58), (0.92, 1.78, 0.74)))
    for sx in (1, -1):
        P.append(box(f"seat{sx}", M["seat"], (min(0.18 * sx, 0.84 * sx), 1.04, -0.20), (max(0.18 * sx, 0.84 * sx), 1.48, 0.28)))
        P.append(box(f"back{sx}", M["seat"], (min(0.18 * sx, 0.84 * sx), 1.40, -0.32), (max(0.18 * sx, 0.84 * sx), 2.02, -0.16)))
    th = np.linspace(0, 2 * math.pi, 17)
    wc = np.array([0.50, 1.86, 0.50]); tilt = math.radians(55)
    ring = np.stack([wc[0] + 0.21 * np.cos(th), wc[1] + 0.21 * np.sin(th) * math.cos(tilt), wc[2] - 0.21 * np.sin(th) * math.sin(tilt)], 1)
    P.append(tube("steering", M["black"], ring, 0.018, R=6, cap0=False, cap1=False))
    P.append(tube("column", M["black"], [wc, wc + [0, -0.30, 0.22]], 0.03, R=6))
    # ---- sun visor over the windscreen (paint)
    visor = body_loft("visor", M["paint"], [
        (0.74, (2.405, 2.445, 0.88, 0.88, 10, 0.0, 0)), (0.86, (2.40, 2.44, 0.88, 0.88, 10, 0.0, 0)),
        (1.00, (2.37, 2.40, 0.86, 0.86, 10, 0.0, 0))], R=20, S=6)
    P.append(visor)
    # ---- hood (paint), the chrome centre strip
    hood = body_loft("hood", M["paint"], [
        (0.92, (1.00, 1.80, 0.53, 0.48, 5, 0.06, 0)),
        (1.30, (1.00, 1.79, 0.53, 0.48, 5, 0.07, 0)),
        (1.62, (1.00, 1.76, 0.52, 0.47, 5, 0.06, 0)),
        (1.71, (1.02, 1.72, 0.50, 0.45, 5, 0.04, 0)),
    ], R=36, S=13)
    P.append(hood)
    strip = conform([hood], np.array([[0, 2.0, z] for z in np.linspace(1.0, 1.68, 8)]), (0, -1, 0), 0.006)[0]
    P.append(tube("hood_strip", M["chrome"], strip, 0.012, R=6))
    # ---- grille: chrome surround, dark mesh, vertical bars, an emblem
    P.append(rbox("grille_frame", M["chrome"], (-0.53, 0.70, 1.62), (0.53, 1.80, 1.76), r=0.05, R=20))
    P.append(box("grille_mesh", M["grille"], (-0.44, 0.80, 1.70), (0.44, 1.69, 1.765)))
    for i in range(11):
        x = -0.40 + i * 0.08
        P.append(box(f"bar{i}", M["chrome"], (x - 0.012, 0.81, 1.765), (x + 0.012, 1.68, 1.785)))
    P.append(rbox("emblem", M["chrome"], (-0.16, 1.70, 1.74), (0.16, 1.77, 1.79), r=0.015, R=12))
    # hood ornament
    P.append(revolve("ornament", M["chrome"], [(0.0001, 0.0), (0.025, 0.01), (0.02, 0.06), (0.0001, 0.08)],
                     (0, 1.77, 1.68), (0, 0, 1), R=10))
    # ---- front bumper (laid along x)
    bump = body_loft("bumper", M["chrome"], [
        (-1.16, (0.40, 0.62, 0.035, 0.035, 6, 0.0, 1.73)),
        (-1.06, (0.37, 0.65, 0.065, 0.065, 6, 0.0, 1.79)),
        (0.0, (0.36, 0.66, 0.07, 0.07, 6, 0.0, 1.80)),
        (1.06, (0.37, 0.65, 0.065, 0.065, 6, 0.0, 1.79)),
        (1.16, (0.40, 0.62, 0.035, 0.035, 6, 0.0, 1.73)),
    ], R=18, S=15)
    P.append(transformed(bump, SWAP_ZX, name="bumper"))
    # license plate
    P.append(box("plate", M["black"], (-0.17, 0.42, 1.865), (0.17, 0.60, 1.875)))
    # ---- front fenders (paint), swept over the wheels, and the apron under the hood
    def fender_path(zc, y0=RT, r=0.62, a0=8, a1=172, back=None):
        a = np.radians(np.linspace(a0, a1, 18))
        path = np.stack([np.zeros_like(a), y0 + r * np.sin(a), zc + r * np.cos(a)], 1)
        return path
    fx0, fx1 = 0.50, 1.175
    def fsec(i, t):
        R = 16
        hw = 0.5 * (fx1 - fx0)
        th = np.linspace(0, 2 * math.pi, R, endpoint=False) - math.pi / 2
        u = sexp(np.cos(th), 3.2); v = sexp(np.sin(th), 3.2)
        thick = 0.055 + 0.03 * math.sin(math.pi * t)
        return np.stack([0.5 * (fx0 + fx1) + u * hw, v * thick + 0.02], 1)
    fpath = fender_path(zFA)
    # the fender flows back and down into a running board at the cab
    tail = np.array([[0, 0.5 + 0.62 * math.sin(math.radians(172)) - 0.02 * k, zFA - 0.62 - 0.08 * k] for k in range(1, 4)])
    fpath = np.vstack([fpath, tail])
    fl = sweep("fender", M["paint"], fpath, fsec, lateral=(1, 0, 0))
    P += both([fl])
    P += both([box("apron", M["under"], (0.40, 0.62, 0.95), (0.55, 1.05, 1.68))])
    # ---- headlamps on pods beside the grille, turn lamps on the fenders
    for sx in (1, -1):
        c = np.array([0.80 * sx, 1.22, 1.62])
        P.append(revolve(f"hl_bucket{sx}", M["chrome"], [(0.02, -0.17), (0.09, -0.15), (0.13, -0.08), (0.145, -0.01), (0.15, 0.0),
                                                         (0.135, 0.012)], c, (0, 0, 1), R=24))
        # VEHICLE-ART-6: a sealed-beam lens (flatter glass, prism grid, reflector, bulb cap) under a proud chrome bezel
        P.append(revolve(f"hl_lens{sx}", M["beam"], [(0.135, 0.010), (0.11, 0.018), (0.06, 0.023), (0.0001, 0.025)], c, (0, 0, 1), R=32,
                         tag=dict(center=list(c), r=0.135)))
        P.append(revolve(f"hl_bezel{sx}", M["chrome"], [(0.122, 0.016), (0.130, 0.027), (0.146, 0.026), (0.156, 0.012), (0.152, -0.004)], c,
                         (0, 0, 1), R=32))
        P.append(tube(f"hl_stalk{sx}", M["chrome"], [c + [-0.20 * sx, -0.06, -0.12], c + [-0.05 * sx, -0.02, -0.10]], 0.025, R=6))
        tc = np.array([0.86 * sx, 1.13, 1.40])
        P.append(revolve(f"turn{sx}", M["amber"], [(0.0001, 0.0), (0.045, 0.0), (0.04, 0.03), (0.0001, 0.045)], tc, (0, 1, 0), R=12))
    # ---- frame rails, fifth wheel, rear crossmember, mudflaps, tail lamps
    for sx in (1, -1):
        P.append(rbox(f"rail{sx}", M["under"], (min(0.33 * sx, 0.43 * sx), 0.60, ZR + 0.02), (max(0.33 * sx, 0.43 * sx), 0.88, 1.66), r=0.02, R=8))
    P.append(box("fw_mount", M["under"], (-0.36, 0.86, -1.32), (0.36, 0.99, -0.78)))
    P.append(revolve("fifth_wheel", M["steel"], [(0.0001, 0.0), (0.44, 0.0), (0.44, 0.07), (0.42, 0.09), (0.0001, 0.09)],
                     (0, 0.98, -1.05), (0, 1, 0), R=32))
    P.append(box("deck_plate", M["steel"], (-0.43, 0.88, -1.85), (0.43, 0.93, -1.40)))
    P.append(box("rear_xmember", M["under"], (-0.62, 0.58, ZR + 0.02), (0.62, 0.80, ZR + 0.12)))
    for sx in (1, -1):
        # pm120: the 2 cm flap down to 16 cm off the road read as a black rod edge-on: 4 cm thick, ending 30 cm up
        P.append(rbox(f"flap{sx}", M["rubber"], (min(0.64 * sx, 1.15 * sx), 0.30, -1.84), (max(0.64 * sx, 1.15 * sx), 0.86, -1.80), r=0.012, R=8))
        P.append(box(f"flap_bar{sx}", M["chrome"], (min(0.62 * sx, 1.16 * sx), 0.86, -1.84), (max(0.62 * sx, 1.16 * sx), 0.90, -1.79)))
        P.append(tube(f"flap_hanger{sx}", M["under"], [[0.40 * sx, 0.84, -1.82], [0.90 * sx, 0.88, -1.82]], 0.025, R=6))
        P.append(rbox(f"tail{sx}", M["tail"], (min(0.86 * sx, 1.06 * sx), 0.92, -1.86), (max(0.86 * sx, 1.06 * sx), 1.00, -1.80), r=0.012, R=8))
    # quarter fenders over the duals (black)
    def qsec(i, t):
        th = np.linspace(0, 2 * math.pi, 14, endpoint=False) - math.pi / 2
        return np.stack([0.905 + sexp(np.cos(th), 4) * 0.27, sexp(np.sin(th), 4) * 0.02], 1)
    qa = np.radians(np.linspace(40, 140, 12))
    qpath = np.stack([np.zeros_like(qa), RT + 0.60 * np.sin(qa), zRA + 0.60 * np.cos(qa)], 1)
    P += both([sweep("qfender", M["black"], qpath, qsec)])
    # ---- fuel tanks under the doors (chrome), steps on them
    for sx in (1, -1):
        c = np.array([0.86 * sx, 0.70, -0.32])
        prof = [(0.0001, 0.0), (0.16, 0.005), (0.22, 0.03), (0.24, 0.08), (0.24, 0.78), (0.22, 0.83), (0.16, 0.855), (0.0001, 0.86)]
        P.append(revolve(f"tank{sx}", M["tank"], prof, c, (0, 0, 1), R=24, tag=dict(straps=[-0.32 + 0.18, -0.32 + 0.68])))
        P.append(box(f"step{sx}", M["steel"], (min(0.70 * sx, 1.08 * sx), 0.95, -0.15), (max(0.70 * sx, 1.08 * sx), 0.97, 0.40)))
    # ---- exhaust stacks behind the cab with perforated heat shields
    for sx in (1, -1):
        cx, cz = 0.80 * sx, -0.54
        path = [[cx, 0.88, cz], [cx, 1.6, cz], [cx, 2.55, cz], [cx, 2.78, cz - 0.03], [cx, 2.86, cz - 0.10]]
        P.append(tube(f"stack{sx}", M["chrome"], path, 0.065, R=14))
        P.append(revolve(f"shield{sx}", M["shield"], [(0.088, 0.0), (0.088, 0.70)], (cx, 1.55, cz), (0, 1, 0), R=16,
                         cap0=True, cap1=True, tag=dict(cx=cx, cz=cz)))
        P.append(box(f"stack_bracket{sx}", M["black"], (min(cx, 0.80 * sx) - 0.03, 1.40, cz + 0.02), (max(cx, 0.80 * sx) + 0.03, 1.44, cab_z0 + 0.04)))
    # ---- mirrors (west coast) and their arms, grab handles, door handles
    for sx in (1, -1):
        arm = [[0.97 * sx, 1.72, 0.80], [1.10 * sx, 1.74, 0.86], [1.12 * sx, 1.82, 0.88]]
        P.append(tube(f"mirror_arm{sx}", M["chrome"], arm, 0.014, R=6))
        P.append(tube(f"mirror_arm_t{sx}", M["chrome"], [[0.96 * sx, 2.22, 0.74], [1.12 * sx, 2.20, 0.86]], 0.012, R=6))
        P.append(rbox(f"mirror{sx}", M["chrome"], (min(1.09 * sx, 1.165 * sx), 1.78, 0.84), (max(1.09 * sx, 1.165 * sx), 2.22, 0.90), r=0.02, R=8))
        P.append(box(f"mirror_glass{sx}", M["mirror"], (min(1.10 * sx, 1.155 * sx), 1.80, 0.832), (max(1.10 * sx, 1.155 * sx), 2.20, 0.84)))
        P.append(tube(f"grab{sx}", M["chrome"], [[1.01 * sx, 1.22, -0.06], [1.045 * sx, 1.25, -0.08], [1.045 * sx, 1.95, -0.08], [1.01 * sx, 1.98, -0.06]], 0.014, R=6))
        P.append(box(f"door_handle{sx}", M["chrome"], (min(1.015 * sx, 1.04 * sx), 1.80, 0.06), (max(1.015 * sx, 1.04 * sx), 1.825, 0.17)))
    # ---- roof: the sprite's two round roof lamps, amber clearance lamps along the front edge
    for sx in (1, -1):
        c = np.array([0.42 * sx, 2.56, 0.30])
        # FIX-CABIN-DOME: the housings are painted black steel with a thin chrome bezel at the lens.
        # Mirror-chrome cans read from the chase camera as pale sky-blue domes on the roof (and filled
        # the frame when the camera passed over them into the cab).
        P.append(revolve(f"roof_lamp{sx}", M["black"], [(0.02, -0.10), (0.07, -0.08), (0.095, -0.02), (0.097, -0.005)], c, (0, 0, 1), R=16))
        P.append(revolve(f"roof_bezel{sx}", M["chrome"], [(0.097, -0.005), (0.10, 0.0), (0.09, 0.01)], c, (0, 0, 1), R=16))
        P.append(revolve(f"roof_lens{sx}", M["head"], [(0.09, 0.008), (0.0001, 0.02)], c, (0, 0, 1), R=16, tag=dict(center=list(c), r=0.09)))
        P.append(tube(f"roof_lamp_post{sx}", M["black"], [c + [0, -0.12, -0.06], c + [0, -0.03, -0.05]], 0.015, R=6))
    for i in range(5):
        x = -0.40 + 0.20 * i
        P.append(revolve(f"marker{i}", M["amber"], [(0.0001, 0.0), (0.04, 0.0), (0.035, 0.03), (0.0001, 0.04)], (x, 2.455, 0.66), (0, 1, 0), R=8))
    # ---- wheels: front singles, rear duals
    wm = dict(tyre=M["tyre"], rim=M["rim"], under=M["under"])
    for sx in (1, -1):
        P += wheel(f"wf{sx}", (0.95 * sx, RT, zFA), sx, RT, 0.30, 0.31, wm, R=26)
        P += wheel(f"wro{sx}", (1.03 * sx, RT, zRA), sx, RT, 0.25, 0.31, wm, R=26, hub_out=0.03)
        inner = wheel(f"wri{sx}", (0.765 * sx, RT, zRA), sx, RT, 0.25, 0.31, wm, R=18)
        P += [inner[0]]
        # axle hub
        P.append(tube(f"axle{sx}", M["under"], [[0.0, RT, zRA], [0.70 * sx, RT, zRA]], 0.06, R=8))
        P.append(tube(f"faxle{sx}", M["under"], [[0.0, RT + 0.05, zFA], [0.78 * sx, RT, zFA]], 0.05, R=8))
    P.append(box("diff", M["under"], (-0.18, 0.38, zRA - 0.16), (0.18, 0.62, zRA + 0.16)))
    # ---- engine sump / underside closure under the hood, cab floor
    P.append(box("sump", M["under"], (-0.42, 0.62, 0.95), (0.42, 1.00, 1.66)))
    P.append(box("cab_floor", M["under"], (-1.00, 0.95, cab_z0 + 0.05), (1.00, 1.00, 0.96)))
    return P


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/gta2-linux/assets-src/cars/models_art/063_truck_cab.glb"))
    ap.add_argument("--preview", default=None)
    ap.add_argument("--sprite", default=os.path.expanduser("~/gta2-linux/assets-src/cars/sprites_x4/063_truck_cab_default.png"))
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    parts = build_truck()
    rep, groups = build(parts, a.out, report=dict(model=63, name="Truck Cab", forward="+z", maker="tools/vehicle_art/m063_truck_cab.py"))
    print(rep)
    if a.preview:
        import preview
        preview.sheet(groups, L, W, 2.9, a.sprite, a.preview, paint=(150, 121, 99), title="063 Truck Cab (carkit)")
