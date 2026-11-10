#!/usr/bin/env python3
"""038 Big Bug (VEHICLE-ART-9): a Baja Bug / monster Beetle read from the GTA2 sprite (front up in the sprite):
the Beetle's domed body and long roof highlight lifted high on four oversized off-road tyres, short flared
fibreglass wings over the front wheels, cut-back rear wings, the engine left bare behind the body (crankcase,
cooling shroud, a chrome air cleaner and two upswept exhausts: the sprite's bright tail), a tube push-bar at the
nose and a tube cage round the engine, exposed coil-over shocks and a ladder frame under the body.
It replaces the image-to-3D shell (faceted wings and bonnet in big flat planes, lamps painted on).
Metres, +z nose, 1 block = 5 m (catalog body 0.594 x 0.891 blocks: 2.97 x 4.45 m)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "038_big_bug"
PAINT = (235.0, 235.0, 235.0)    # neutral base, tinted by live paint / own paint (identity.cpp)
SPRITE = (147, 98, 66)           # the default remap's copper, for previews
LEN = 0.891 * 5.0                # 4.455 m
HALF_W = 0.594 * 5.0 / 2         # 1.485 m over the tyres
ZF, ZR = 1.40, -1.12             # axles (CARI: 19 px forward, 14 px back of the centre; pulled in to fit the tyres)
R_TYRE, W_TYRE = 0.60, 0.46
X_WHEEL = 1.15
R_ARCH = 0.70
LIFT = 0.50                      # the body sits this much higher than a road Beetle
BOT = 0.30 + LIFT
SZ = 2.05 / 2.03                 # the 008 body's length scaled onto this footprint
TAIL = -1.42                     # the body stops here: the engine stands bare behind it


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = 2.05, TAIL
    L = lambda keys: spline([(z * SZ, y + LIFT) for z, y in keys])

    # centre line top: the front lid, windscreen, dome roof, rear window, the cut tail (no engine lid)
    top0 = L([(-1.48, 0.90), (-1.30, 1.10), (-1.15, 1.20), (-0.80, 1.47), (-0.40, 1.62), (0.05, 1.66),
              (0.40, 1.60), (0.62, 1.44), (0.86, 1.04), (1.25, 0.95), (1.65, 0.84), (1.92, 0.70), (2.03, 0.62)])
    belt0 = L([(-1.48, 0.90), (-1.0, 0.98), (0.6, 0.98), (1.2, 0.86), (1.8, 0.72), (2.03, 0.62)])
    hw_keys = [(-1.48, 0.70), (-1.25, 0.76), (0.70, 0.80), (1.35, 0.70), (1.80, 0.56), (2.03, 0.42)]
    hw0 = spline([(z * SZ, w) for z, w in hw_keys])
    bot0 = L([(-1.48, 0.42), (-1.30, 0.30), (1.75, 0.30), (2.03, 0.44)])

    def ends(z, nose=0.22, tail=0.10):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    R_CUT = R_TYRE + 0.08
    def arch(z):
        """the Baja cut-outs: the body's lower edge lifts in a circle round each tyre, clear of the renderer's wheel disc"""
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip((R_CUT + 0.06) ** 2 - np.minimum(dz, R_CUT + 0.06) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_CUT + 0.06, y, 0))
        return lift

    def body(u, v, inset=0.0):
        """u = z; v in 0..1: bottom centre -> belt (v = 0.5) -> roof centre"""
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * f - inset
        belt = belt0(z)
        top = belt + (top0(z) - belt) * f - inset
        b0 = np.minimum(np.maximum(bot0(z), arch(z)), belt - 0.06)
        bot = belt - (belt - b0) * f + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        x = np.where(lo, hw * (0.86 + 0.14 * sepow(c, 1.4)), hw * sepow(c, 0.78))
        y = np.where(lo, belt - (belt - bot) * sepow(s, 0.55), belt + (top - belt) * sepow(s, 0.92))
        return x, y, z

    SU, SV = 1.0, 2.4
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    s = SZ
    side_front = win([(0.70 * s, 0.585), (-0.16 * s, 0.585), (-0.16 * s, 0.835), (0.30 * s, 0.835)], 0.05)
    side_rear = win([(-0.26 * s, 0.585), (-0.98 * s, 0.585), (-0.70 * s, 0.835), (-0.26 * s, 0.835)], 0.06)
    screen = win([(0.84 * s, 0.60), (0.84 * s, 1.02), (0.48 * s, 1.02), (0.48 * s, 0.87)], 0.05)
    screen = (lambda f: (lambda u, v: np.maximum(f(u, v), 0.885 - np.asarray(v))))(screen)
    rear = win([(-0.86 * s, 0.90), (-0.86 * s, 1.02), (-1.12 * s, 1.02), (-1.12 * s, 0.90)], 0.07)
    glass = sdf_union(side_front, side_rear, screen, rear)
    seal = lambda u, v: glass(u, v) - 0.012
    def lid_strip(u, v):
        z = np.asarray(u, float)
        return np.maximum(np.abs(1 - np.asarray(v)) * 2.4 - 0.016, np.maximum(1.0 * s - z, z - 1.95 * s))
    def under(u, v):
        x, y, z = body(u, v)
        return np.maximum(np.asarray(v) - 0.30, y - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 56, 28, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", lid_strip), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / (zn - zt), v),
                ukeys=[0.84 * s, 0.48 * s, -0.16 * s, -0.26 * s, -0.86 * s, -1.12 * s], vkeys=[0.585, 0.835, 0.87, 0.90])
    car.surface(lambda u, v: body(u, v, inset=0.05), -1.15, 0.85, 0.50, 1.0, 24, 12, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # flared fibreglass wings: a short shell over the top of each tyre, open underneath, standing off the body
    def wing(zc, z0, z1, x_in, x_out, crown):
        def fn(u, v):
            z = np.asarray(u, float); phi = np.asarray(v, float)
            t = (z - z0) / (z1 - z0)
            e = np.sqrt(np.clip(1 - (2 * t - 1) ** 8, 0, 1))
            dz = z - zc
            yc = R_TYRE + np.sqrt(np.clip((R_ARCH + 0.04) ** 2 - np.minimum(np.abs(dz), R_ARCH + 0.04) ** 2, 0, None))
            yc = np.maximum(yc, R_TYRE + 0.42)   # a flare, not a skirt: its ends stop well above the axle
            ytop = yc + (crown - 0.05 * (dz / 0.7) ** 2) * (0.25 + 0.75 * e)
            xm = 0.5 * (x_in + x_out); a = 0.5 * (x_out - x_in)
            x = xm + a * sepow(np.cos(phi), 0.5)
            y = yc + (ytop - yc) * sepow(np.sin(phi), 0.7)
            return x, y, z
        return fn
    wf = wing(ZF, ZF - 0.62, ZF + 0.58, 0.46, X_WHEEL + W_TYRE / 2 + 0.05, 0.10)
    wr = wing(ZR, ZR - 0.55, ZR + 0.66, 0.50, X_WHEEL + W_TYRE / 2 + 0.05, 0.10)
    wings = (("paint_wing_f", wf, ZF - 0.62, ZF + 0.58), ("paint_wing_r", wr, ZR - 0.55, ZR + 0.66))
    for mname, fn, z0, z1 in wings:
        car.surface(fn, z0, z1, 0.0, math.pi, 28, 12, mirror=True, default=mname,
                    uvfn=lambda u, v, z0=z0, z1=z1: ((u - z0) / (z1 - z0), v / math.pi))
        # the underside of the shell (seen from low and from the chase camera's height)
        car.surface(fn, z0, z1, 0.0, math.pi, 14, 6, mirror=True, default="underbody", flip=True,
                    uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # ladder frame, axles, coil-over shocks, skid plate
    for side in (1, -1):
        car.box("frame", (side * 0.52 - 0.05, BOT - 0.20, -2.00), (side * 0.52 + 0.05, BOT - 0.06, 1.95))
    for zc in (ZF, ZR):
        car.sweep(lambda u, zc=zc: np.stack([(u - 0.5) * 2 * (X_WHEEL - 0.12), R_TYRE + 0 * u, zc + 0 * u], 1), 0.065, 8, 10, "frame")
        car.box("frame", (-0.18, R_TYRE - 0.10, zc - 0.16), (0.18, R_TYRE + 0.12, zc + 0.16))   # diff pumpkin
        car.box("frame", (-0.42, BOT - 0.22, zc - 0.05), (0.42, BOT - 0.10, zc + 0.05))          # cross member
        for side in (1, -1):
            for dz in (-0.16, 0.16):
                x0 = side * 0.30
                p0 = np.array([x0, R_TYRE + 0.04, zc + dz]); p1 = np.array([side * 0.30, BOT + 0.20, zc + dz * 1.4])
                car.sweep(lambda u, p0=p0, p1=p1: p0[None, :] + (p1 - p0)[None, :] * u[:, None], 0.045, 6, 10, "shock")
                def coil(u, p0=p0, p1=p1):
                    a = p0 + (p1 - p0) * 0.35; b = p0 + (p1 - p0) * 0.90
                    ax = (b - a) / np.linalg.norm(b - a)
                    e1 = np.cross(ax, [0, 0, 1.0]); e1 /= np.linalg.norm(e1); e2 = np.cross(ax, e1)
                    t = u * 7 * 2 * math.pi
                    return a[None, :] + (b - a)[None, :] * u[:, None] + 0.075 * (np.cos(t)[:, None] * e1 + np.sin(t)[:, None] * e2)
                car.sweep(coil, 0.016, 70, 6, "spring")
            # trailing arm from the frame to the axle
            car.sweep(lambda u, side=side, zc=zc: np.stack([side * (0.42 - 0.12 * u), BOT - 0.14 - (BOT - 0.14 - R_TYRE) * u,
                                                             zc - np.sign(zc) * 0.9 * (1 - u)], 1), 0.045, 8, 8, "frame")
    car.box("underbody", (-0.40, BOT - 0.30, 1.55), (0.40, BOT - 0.24, 2.00))   # skid plate

    # the bare engine behind the body: crankcase, cylinder barrels, fan shroud, air cleaner, upswept exhausts
    ze = TAIL - 0.30
    car.box("engine", (-0.36, BOT - 0.10, ze - 0.26), (0.36, BOT + 0.30, ze + 0.30))
    for side in (1, -1):
        for k in range(4):
            car.box("engine_fin", (side * 0.36, BOT + 0.02 + k * 0.07, ze - 0.22), (side * 0.56, BOT + 0.06 + k * 0.07, ze + 0.22))
    car.box("engine", (-0.30, BOT + 0.30, ze - 0.20), (0.30, BOT + 0.62, ze + 0.24))           # fan shroud
    car.revolve([(0.0, 0.0), (0.20, 0.0), (0.21, 0.04), (0.21, 0.14), (0.20, 0.18), (0.0, 0.18)],
                (0.0, BOT + 0.62, ze), (0, 1, 0), 26, default="chrome", uv_mode="disc")       # air cleaner
    car.revolve([(0.10, 0.0), (0.12, 0.10), (0.0, 0.12)], (-0.45, BOT + 0.40, ze + 0.06), (-1, 0.2, 0), 16, default="chrome", uv_mode="disc")
    for side in (1, -1):
        def pipe(u, side=side):
            a = np.clip(u * 1.6, 0, 1); b = np.clip(u * 1.6 - 0.6, 0, 1)
            x = side * (0.20 + 0.18 * a)
            y = BOT - 0.04 + 0.90 * b ** 1.2
            z = ze - 0.18 - 0.30 * np.sin(a * math.pi / 2) + 0.06 * b
            return np.stack([x, y, z], 1)
        car.sweep(pipe, 0.042, 24, 10, "chrome")
        car.revolve([(0.050, 0.0), (0.050, 0.06), (0.036, 0.06), (0.036, 0.0)], (side * 0.38, BOT + 0.90, ze - 0.42),
                    (0, 1, 0), 14, default="frame", uv_mode="disc")
    # tube cage round the engine and a push-bar at the nose (black tube)
    def cage(u):
        t = u * 4
        pts = np.array([[-0.62, BOT + 0.42, TAIL + 0.05], [-0.62, BOT + 0.95, TAIL - 0.10], [-0.48, BOT + 1.00, -2.10],
                        [0.48, BOT + 1.00, -2.10], [0.62, BOT + 0.95, TAIL - 0.10]])  # noqa
        i = np.clip(t.astype(int), 0, 3); f = (t - i)[:, None]
        return pts[i] * (1 - f) + pts[i + 1] * f
    car.sweep(cage, 0.040, 64, 10, "tube", caps=False)
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.62 + 0 * u, BOT + 0.42 + 0 * u, TAIL + 0.05 - 0.6 * u], 1), 0.040, 8, 10, "tube")
        car.sweep(lambda u, side=side: np.stack([side * (0.62 - 0.14 * u), BOT + 0.42 + 0.58 * u, -2.0 - 0.10 * u], 1), 0.040, 8, 10, "tube")
    def bar(zc, sign, y, half):
        def path(u):
            x = (u - 0.5) * 2 * half
            return np.stack([x, np.full_like(x, y), zc - sign * 0.10 * (x / half) ** 2], 1)
        return path
    car.sweep(bar(2.18, 1, BOT + 0.02, 0.86), 0.055, 24, 10, "tube")
    car.sweep(bar(2.20, 1, BOT + 0.30, 0.62), 0.040, 20, 10, "tube")
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.50 + 0 * u, BOT + 0.02 + 0.28 * u, 2.18 - 0.03 * u], 1), 0.040, 6, 10, "tube")
        car.sweep(lambda u, side=side: np.stack([side * 0.36 + 0 * u, BOT - 0.10 + 0 * u, 1.90 + 0.28 * u], 1), 0.040, 6, 10, "tube")
    car.sweep(bar(-2.10, -1, BOT - 0.02, 0.70), 0.050, 20, 10, "tube")

    # lamps: round headlamps in the Beetle's front lid corners, a pair of roof spot lamps, tail lamps on the cage
    for side in (1, -1):
        c = np.array([side * 0.52, 0.66 + LIFT + 0.08, 1.97])
        ax = (side * 0.10, 0.10, 1.0)
        car.revolve([(0.105, -0.05), (0.108, 0.012), (0.096, 0.028)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.095, 0.024), (0.06, 0.042), (0.0, 0.048)], c, ax, 22, default="lamp_head", uv_mode="disc")
        r = np.array([side * 0.36, 1.66 + LIFT + 0.10, 0.62])
        car.box("tube", (side * 0.36 - 0.02, 1.62 + LIFT, 0.58), (side * 0.36 + 0.02, 1.62 + LIFT + 0.10, 0.62))
        car.revolve([(0.080, -0.07), (0.085, 0.0), (0.075, 0.02)], r, (0, -0.05, 1), 18, default="tube", uv_mode="disc")
        car.revolve([(0.072, 0.016), (0.04, 0.03), (0.0, 0.034)], r, (0, -0.05, 1), 18, default="lamp_head", uv_mode="disc")
        t = np.array([side * 0.62, BOT + 0.70, TAIL - 0.13])
        car.revolve([(0.045, -0.02), (0.048, 0.02), (0.0, 0.032)], t, (0, 0, -1), 14, default="lamp_tail", uv_mode="disc")
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.72, 1.62 + LIFT + 0.0 * u, 0.58 + 0 * u], 1), 0.022, 10, 8, "tube")
    # door handles, a mirror
    for side in (1, -1):
        car.box("chrome", (side * 0.825 - 0.012, 1.00 + LIFT, 0.18), (side * 0.825 + 0.012, 1.025 + LIFT, 0.30))
    car.sweep(lambda u: np.stack([-0.82 - 0.10 * u, 1.10 + LIFT + 0.04 * u, 0.62 + 0 * u], 1), 0.012, 4, 6, "chrome")
    car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (-0.94, 1.15 + LIFT, 0.62), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: bucket seats, dash, a small steering wheel, a roll bar behind the seats
    for xs in (-0.38, 0.38):
        car.box("seat", (xs - 0.24, 0.48 + LIFT, 0.0), (xs + 0.24, 0.62 + LIFT, 0.50))
        car.box("seat", (xs - 0.24, 0.58 + LIFT, -0.08), (xs + 0.24, 1.18 + LIFT, 0.04))
    car.box("interior_dark", (-0.72, 0.80 + LIFT, 0.72), (0.72, 1.00 + LIFT, 0.90))
    car.revolve([(0.15, -0.01), (0.15, 0.01), (0.13, 0.01), (0.13, -0.01), (0.15, -0.01)], (-0.38, 1.05 + LIFT, 0.62),
                (0, 0.45, -1.0), 20, default="interior_dark", uv_mode="disc")

    # off-road tyres: square shoulders, deep lugs (texture), small steel wheels with a chrome hub
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        side = 1 if xw > 0 else -1
        r, w = R_TYRE, W_TYRE
        rim_r = 0.50 * r
        prof = [(rim_r * 1.02, -0.42 * w), (0.70 * r, -0.50 * w), (0.90 * r, -0.50 * w), (0.97 * r, -0.48 * w),
                (r, -0.40 * w), (r, 0.40 * w), (0.97 * r, 0.48 * w), (0.90 * r, 0.50 * w), (0.70 * r, 0.50 * w),
                (rim_r * 1.02, 0.42 * w)]
        car.revolve(prof, (xw, r, zc), (side, 0, 0), 40, mat_of=lambda k: "tyre_tread" if 3 <= k <= 5 else "tyre_side")
        rim = [(rim_r * 1.02, 0.42 * w), (rim_r * 0.96, 0.40 * w), (rim_r * 0.90, 0.12 * w), (rim_r * 0.55, 0.10 * w), (rim_r * 0.40, 0.20 * w)]
        car.revolve(rim, (xw, r, zc), (side, 0, 0), 24, default="wheel_steel", uv_mode="disc")
        cap = [(rim_r * 0.40, 0.20 * w), (rim_r * 0.30, 0.26 * w), (rim_r * 0.10, 0.28 * w), (0.0001, 0.28 * w)]
        car.revolve(cap, (xw, r, zc), (side, 0, 0), 16, default="chrome", uv_mode="disc")
        car.revolve([(rim_r * 1.02, -0.42 * w), (0.001, -0.30 * w)], (xw, r, zc), (side, 0, 0), 20, default="underbody", uv_mode="disc")
        car.marker(nm, (xw, r, zc))

    # textures
    U = lambda z: (z - zt) / (zn - zt)
    lines_u = [(U(0.70 * s), 0.36, 0.585), (U(-0.20 * s), 0.36, 0.585), (U(1.88 * s), 0.78, 1.0)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.16, 0.34, 0.30)], seed=38)
    for mname, fn, z0, z1 in wings:
        car.materials[mname] = tex_paint(PAINT, 256, seed=39)
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    car.materials["glass"] = tex_glass(256, tint=(58, 74, 88), alpha=120)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["underbody"] = tex_underbody()
    car.materials["frame"] = tex_flat((30, 30, 32))
    car.materials["tube"] = tex_flat((24, 24, 26))
    car.materials["shock"] = tex_flat((150, 150, 155))
    car.materials["spring"] = tex_flat((190, 40, 30))
    car.materials["engine"] = tex_flat((70, 70, 72))
    car.materials["engine_fin"] = tex_flat((110, 110, 112))
    car.materials["wheel_steel"] = tex_wheel()
    car.materials["interior_dark"] = tex_flat((44, 40, 36))
    car.materials["seat"] = tex_leather((60, 56, 52))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["tyre_tread"] = tex_lugs()
    car.materials["tyre_side"] = tex_tyre_side()
    return car


def tex_wheel(size=128):
    """a painted steel wheel seen as a disc (uv_mode disc): dark grey with a ring of lug holes and a bright lip"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    r = np.hypot(xx - 0.5, yy - 0.5) * 2
    a = np.arctan2(yy - 0.5, xx - 0.5)
    v = 96 + 30 * (r > 0.86) - 20 * (r < 0.5)
    holes = (np.abs(r - 0.68) < 0.07) & (np.cos(a * 8) > 0.82)
    v = np.where(holes, 18, v) + 4 * noise(size, size, 10, 4)
    return Image.fromarray(np.dstack([v, v, v * 1.03]).clip(0, 255).astype(np.uint8))


def tex_lugs(size=256):
    """off-road tread: u around the tyre (64 lug rows), v across it: staggered chevron lugs with deep voids"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    row = (xx * 32) % 1.0
    half = yy < 0.5
    shift = np.where(half, (0.5 - yy) * 0.9, (yy - 0.5) * 0.9)
    lug = ((row + shift) % 1.0) < 0.55
    lug &= np.abs(yy - 0.5) > 0.03
    v = np.where(lug, 46, 14) + 5 * noise(size, size, 12, 9)
    return Image.fromarray(np.dstack([v, v, v * 1.02]).clip(0, 255).astype(np.uint8))


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va9/p038.png", LEN)
