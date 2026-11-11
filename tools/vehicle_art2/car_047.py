#!/usr/bin/env python3
"""047 Meteor / 048 Meteor (VEHICLE-ART-25): the catalog's late-1950s sports-racing coupe (Jaguar XKSS / Testa Rossa
streamliner idiom, the era the round-8 regenerations chose) read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/047_meteor_default.png, body 32 x 63 px, 0.078 m per sprite px): pontoon wings swelling
over both axles (the sprite is 32 px over the haunches, 30 between), a low bonnet with a narrow power bulge (rows
49-55) and twin intakes near the nose (rows 56-58), corner lamps, a wraparound screen (rows 41-48) and side glass
round a narrow bubble cabin whose painted roof is the sprite's bright oval (rows 23-40, 20 of the 30 px), a roll bar
(rows 20-22), a small back light (rows 13-19), a long rear engine deck over the rear-mounted engine (rows 5-12: the
rear axle sits 13 px behind the centre, the front one 19 px ahead) and a dark lip across the cut-off tail (rows 1-4,
dark grey in every remap: trim, not paint). 048 is the same body with the sprite's exposed engine on the rear deck
and a chrome blower standing out of the bonnet. ONE paint over every body panel, the roof included (out/va24_r8:
the shells drew near-black flanks under a pale top). Neutral 235 paint: the identity record tints it.
Metres, +z nose, 1 block = 5 m (2.50 x 4.92 m; axles +19 / -13 px)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "047_meteor"
SPRITE = (152, 112, 80)          # the default remap's sprite paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # neutral: the identity record tints it
LEN = 63 / 64 * 5.0              # 4.92 m
HALF_W = 32 / 64 * 5.0 / 2       # 1.25 m
ZF, ZR = 19 / 64 * 5.0, -13 / 64 * 5.0     # +1.48 / -1.02
R_TYRE, W_TYRE = 0.34, 0.26
X_WHEEL = 0.98
R_ARCH = 0.40                    # arch top 0.74: the haunches' waist stays 0.08 above it (kit-wheel-split lesson)
BOT = 0.24
SV = 2.6
ZSB, ZST = 1.20, 0.64            # screen base / top (rows 41-48)
ZBB, ZBT = -1.48, -0.80          # back-light base / roll bar (rows 13-22)


def build(variant=0, name=None):
    car = Car(name or NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    # the waist: high over the haunches (their crowns), dipping at the doors, falling to the nose and the tail
    belt0 = spline([(zt, 0.74), (-2.10, 0.80), (-1.50, 0.86), (ZR, 0.88), (-0.45, 0.82), (0.40, 0.80), (1.00, 0.83),
                    (ZF, 0.87), (2.05, 0.80), (zn, 0.68)])
    # roof line: the Kamm tail's lip, the rear deck, the steep fastback, the short roof, the raked screen, the long
    # bonnet falling to the mouth
    top0 = spline([(zt, 0.80), (zt + 0.10, 0.86), (-2.00, 0.92), (ZBB, 0.97), (-1.20, 1.14), (ZBT, 1.29), (-0.50, 1.335),
                   (0.20, 1.335), (ZST, 1.29), (0.95, 1.06), (ZSB, 0.91), (1.60, 0.885), (2.00, 0.84), (zn - 0.06, 0.76), (zn, 0.72)])
    def hw0(z):
        z = np.asarray(z, float)
        swell = 0.22 * np.exp(-((z - ZF) / 0.78) ** 4) + 0.22 * np.exp(-((z - ZR) / 0.80) ** 4)
        base = np.interp(z, [zt, -2.0, -0.5, 0.6, 2.0, zn], [0.92, 1.00, 1.04, 1.04, 0.98, 0.84])
        return base + swell
    # the narrow glasshouse: the roof 16 px of the body's 28 over the cabin
    tumble0 = spline([(zt, 0.10), (ZBB, 0.26), (ZBT - 0.05, 0.40), (ZST + 0.03, 0.40), (ZSB - 0.05, 0.30), (1.6, 0.26), (zn, 0.12)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAIL = 0.62, 0.34
    def ends(z):
        dn = np.clip((z - (zn - NOSE)) / NOSE, 0, 1)
        dt = np.clip(((zt + TAIL) - z) / TAIL, 0, 1)
        fn = 1 - dn ** 2.2
        ft = np.sqrt(np.clip(1 - dt ** 2, 0, 1))
        return fn, ft

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn, ft = ends(z)
        hw = hw0(z) * (0.50 + 0.50 * fn) * (0.80 + 0.20 * ft) - inset
        belt = belt0(z)
        top = belt + (top0(z) - belt) * (0.80 + 0.20 * ft) - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        fh = (0.55 + 0.45 * fn) * (0.86 + 0.14 * ft)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * np.minimum(hw, 1.10) / 1.10
        xl = hw * sepow(c, 0.45)
        yl = belt - (belt - bot) * sepow(s, 0.55)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        xs = hw * (1 - t ** 4) ** (1 / 4) - tb * t ** 0.8
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** 4) ** (1 / 4) - tb * 0.95 ** 0.8
        xr = X0 * (1 - w)
        yr = belt + H * (0.92 + 0.08 * (1 - (1 - w) ** 2.4) ** 0.42)
        xu = np.where(v < 0.8, xs, xr)
        yu = np.where(v < 0.8, ys, yr)
        return np.where(lo, xl, xu), np.where(lo, yl, yu), z

    SU = 1.0
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    # the door glass (its front edge along the raked A pillar), the small rear quarter light tapering into the fastback
    D0, D1 = ZSB - 0.12, ZBT + 0.02
    side1 = win([(ZST - 0.02, 0.58), (ZBT + 0.10, 0.58), (ZBT + 0.10, 0.765), (ZST - 0.08, 0.765)], 0.06)
    side2 = win([(ZBT - 0.02, 0.60), (ZBT - 0.20, 0.60), (ZBT - 0.02, 0.76)], 0.03)
    # the wraparound screen: its ends run down and back round the A pillars (the sprite's dark V at rows 41-48)
    screen = win([(ZSB - 0.035, 0.70), (ZSB - 0.035, 1.03), (ZST + 0.035, 1.03), (ZST + 0.035, 0.78), (ZST + 0.12, 0.70)], 0.04)
    backl = win([(ZBT - 0.035, 0.82), (ZBT - 0.035, 1.03), (ZBB + 0.045, 1.03), (ZBB + 0.045, 0.82)], 0.05)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.016
    # twin intakes in the bonnet near the nose (the sprite's dark pair at rows 56-58), 047 only
    def intakes(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        x = np.abs(body(u, v)[0])
        d = np.hypot((x - 0.34) / 0.16, (u - 1.98) / 0.11) - 1.0
        return np.maximum(d, (0.82 - v) * SV) if variant == 0 else np.full_like(u, 1.0)
    # three-slot vents behind the front wheels
    VZ0, VZ1 = ZF - R_ARCH - 0.34, ZF - R_ARCH - 0.08
    def vent(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        return np.maximum(np.abs(u - (VZ0 + VZ1) / 2) - (VZ1 - VZ0) / 2, np.abs(v - 0.37) * SV - 0.12)
    under = lambda u, v: np.maximum(np.asarray(v) - 0.26, body(u, v)[1] - (BOT + 0.10))
    def bay(u, v):
        u = np.asarray(u, float); v = np.asarray(v, float)
        x = np.abs(body(u, v)[0])
        d = np.maximum(np.maximum((x - 0.60) * 2.0, (0.84 - v) * SV), np.maximum(zt + 0.32 - u, u - (-1.64)))
        return d if variant == 1 else np.full_like(u, 1.0)
    car.surface(body, zt, zn, 0.0, 1.0, 88, 34, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("intake", intakes), ("interior_dark", bay), ("vent", vent), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, ZBB, ZBT, D0, D1, VZ0, VZ1,
                       1.87, 2.09, zt + 0.32, -1.64],
                vkeys=[0.545, 0.775, 0.80, 0.815, 0.82, 0.50])
    # the vents' slats: their own patch a few mm proud, the slats running fore and aft (uv across the vent)
    car.surface(lambda u, v: body(u, v, inset=-0.006), VZ0 + 0.01, VZ1 - 0.01, 0.37 - 0.12 / SV + 0.01, 0.37 + 0.12 / SV - 0.01,
                10, 6, mirror=True, default="vent_slats",
                uvfn=lambda u, v: ((u - VZ0) / (VZ1 - VZ0), (v - 0.37 + 0.12 / SV) / (0.24 / SV)))
    # the ends: the tail's flat Kamm panel in its own unbaked paint, the nose's oval mouth a dark grille (VA23: caps
    # turned to face outward)
    k0 = len(car.parts["paint_trim"].p) if "paint_trim" in car.parts else 0
    car.cap(body, zt, 0.0, 1.0, 24, "paint_trim", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    face_out(car.parts["paint_trim"], k0, -1)
    k0 = len(car.parts["grille"].p) if "grille" in car.parts else 0
    car.cap(body, zn, 0.0, 1.0, 24, "grille", nr=4, uvfn=lambda r, v: (0.5 + 0.5 * np.asarray(r) * np.cos(np.asarray(v) * math.pi),
                                                                         0.5 + 0.5 * np.asarray(r) * np.sin(np.asarray(v) * math.pi)))
    face_out(car.parts["grille"], k0, +1)
    # the mouth's chrome lip: a ring round the nose section a few mm proud
    def lip(t):
        v = np.asarray(t, float)
        x, y, z = body(np.full_like(v, zn - 0.004), v)
        return np.stack([x * 1.01, y, z + 0.004], 1)
    for sgn in (1, -1):
        car.sweep(lambda t, sgn=sgn: lip(t) * np.array([sgn, 1, 1]), 0.016, 40, 8, "chrome")
    # cabin liner (light, normals leaning up: reads through the glass), arch liners
    car.surface(lambda u, v: body(u, v, inset=0.06), ZBB + 0.05, ZSB - 0.06, 0.28, 1.0, 22, 10, mirror=True,
                default="interior_liner", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    lp = car.parts["interior_liner"]
    lp.n = [(-np.asarray(n) + np.array([0.0, 2.5, 0.0])) for n in lp.n]
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.66, 1.20, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # covered headlamps at the wing tips: the bucket sunk in the wing's front, a clear cover over it
    uu, vv = np.meshgrid(np.linspace(zn - NOSE - 0.2, zn, 200), np.linspace(0.40, 0.75, 120))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.80) + np.abs(by - 0.80))
    LAMP = np.array([0.80, 0.80, bz[k] - 0.10])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.35, 0.12, 1.0)
        car.revolve([(0.115, -0.06), (0.110, 0.0), (0.098, 0.012)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.098, 0.008), (0.070, 0.022), (0.0, 0.028)], c, ax, 22, default="lamp_head", uv_mode="disc")
        # the indicator under the cover, at the wing's foot beside the mouth
        car.revolve([(0.040, 0.0), (0.040, 0.016), (0.0, 0.022)], (side * 0.66, 0.52, zn - 0.20), (side * 0.4, 0, 1), 12,
                    default="lamp_amber", uv_mode="disc")
    # quarter bumpers either side of the mouth and the tail panel
    for side in (1, -1):
        def qb(u, side=side):
            u = np.clip(np.asarray(u, float), 0, 1)
            x = side * (0.42 + 0.46 * u)
            z = zn - 0.12 - 0.40 * u ** 2
            return np.stack([x, 0.46 + 0 * u, z], 1)
        car.sweep(qb, 0.040, 16, 8, "chrome", squash=(0.5, 1.0))
        def qr(u, side=side):
            u = np.clip(np.asarray(u, float), 0, 1)
            x = side * (0.30 + 0.62 * u)
            z = zt - 0.03 + 0.30 * u ** 2.2
            return np.stack([x, 0.48 + 0 * u, z], 1)
        car.sweep(qr, 0.040, 16, 8, "chrome", squash=(0.5, 1.0))
        # twin round tail lamps on the Kamm panel
        for xl in (0.70,):
            c = (side * xl, 0.72, zt - 0.004)
            car.revolve([(0.072, -0.03), (0.070, 0.0), (0.064, 0.012)], c, (0, 0, -1), 18, default="chrome", uv_mode="disc")
            car.revolve([(0.064, 0.008), (0.040, 0.020), (0.0, 0.025)], c, (0, 0, -1), 18,
                        default="lamp_tail", uv_mode="disc")
        # quad tail pipes
        for xp in (0.16, 0.28):
            car.sweep(lambda u, x=side * xp: np.stack([x + 0 * u, 0.30 + 0 * u, zt + 0.06 - 0.12 * u], 1), 0.032, 6, 8, "chrome")
    car.box("trim_dark", (-0.20, 0.55, zt - 0.006), (0.20, 0.69, zt + 0.03))
    car.box("plate", (-0.17, 0.565, zt - 0.012), (0.17, 0.675, zt + 0.0))
    # door handle flush at the door's rear, a wing mirror on the driver's wing
    hx = float(body(np.array([D1 + 0.10]), np.array([0.47]))[0][0])
    for side in (1, -1):
        car.box("chrome", (side * hx - 0.012, 0.83, D1 + 0.04), (side * hx + 0.012, 0.86, D1 + 0.18))
    car.sweep(lambda u: np.stack([-0.98 - 0.10 * u, 0.93 + 0.06 * u, 1.05 + 0 * u], 1), 0.012, 4, 6, "chrome")
    car.revolve([(0.048, 0.0), (0.048, 0.02), (0.0, 0.026)], (-1.09, 1.01, 1.05), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: two buckets, a centre console, a dash with dials, a wood-rimmed wheel
    for sx in (-0.42, 0.42):
        car.box("seat", (sx - 0.26, 0.42, -0.36), (sx + 0.26, 0.56, 0.10))
        car.box("seat", (sx - 0.24, 0.54, -0.50), (sx + 0.24, 1.04, -0.36))
    car.box("interior_dark", (-0.12, 0.40, -0.44), (0.12, 0.62, 0.66))
    car.box("interior_dark", (-0.86, 0.70, 0.66), (0.86, 0.86, 0.84))
    car.revolve([(0.18, -0.014), (0.18, 0.014)], (-0.40, 0.86, 0.46), (0, 0.55, -1), 20, default="wood", uv_mode="disc")
    # the roll bar behind the cabin (the sprite's grey band at rows 20-22) shows through the back light
    car.sweep(lambda u: np.stack([(u - 0.5) * 1.10, 0.84 + 0.36 * np.sin(np.clip(u, 0, 1) * math.pi) ** 0.3, ZBT - 0.10 + 0 * u], 1),
              0.03, 20, 8, "trim_dark")
    # the tail's dark lip across the cut-off tail (rows 1-4: dark grey in every remap)
    car.box("trim_dark", (-0.70, 0.775, zt - 0.03), (0.70, 0.815, zt + 0.16))
    if variant == 1:
        # 048: the exposed engine in an open bay on the rear deck (rows 2-12), the blower through the bonnet (rows 49-58)
        dy = lambda z: float(body(np.array([z]), np.array([1.0]))[1][0])
        y0 = min(dy(-1.62), dy(zt + 0.30))
        # the bay itself is cut into the deck (region "bay" above); a floor under it
        car.box("interior_dark", (-0.60, y0 - 0.16, zt + 0.32), (0.60, y0 - 0.14, -1.64))
        for sx in (-0.26, 0.26):
            car.sweep(lambda u, sx=sx: np.stack([sx + 0 * u, y0 - 0.02 + 0 * u, zt + 0.42 + (-1.76 - zt - 0.42) * u], 1), 0.075, 16, 12,
                      "engine_chrome", squash=(1.0, 0.75))
            for k in range(6):
                zc = zt + 0.50 + k * (-1.84 - zt - 0.50) / 5
                car.revolve([(0.040, 0.0), (0.040, 0.08), (0.052, 0.10)], (sx * 0.30, y0 + 0.00, zc), (0, 1, 0), 12, default="chrome",
                            uv_mode="disc")
        by = dy(1.80)
        car.sweep(lambda u: np.stack([0 * u, by + 0.10 + 0 * u, 1.50 + 0.56 * u], 1), 0.17, 16, 14, "engine_chrome", squash=(1.0, 0.85))
        for sx in (-0.07, 0.07):
            car.sweep(lambda u, sx=sx: np.stack([sx + 0 * u, by + 0.24 + 0.10 * u, 1.70 + 0 * u], 1), 0.06, 6, 10, "chrome")

    style = dict(rim_r=0.64, rim_mat="wheel_alloy", cap_mat="chrome", whitewall=0.0, cap_dome=0.16)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)
        # the knock-off spinner's two ears
        sd = 1 if xw > 0 else -1
        car.box("chrome", (xw + sd * 0.11 - 0.012, R_TYRE - 0.012, zc - 0.10), (xw + sd * 0.11 + 0.012, R_TYRE + 0.012, zc + 0.10))

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(D0 + 0.08), 0.18, 0.52), (U(D1 - 0.04), 0.18, 0.52), (U(ZSB + 0.06), 0.50, 0.99), (U(ZBB - 0.06), 0.52, 0.99)]
    lines_v = [(0.86, U(ZSB + 0.06), U(zn - 0.10)), (0.86, U(zt + 0.10), U(ZBB - 0.06))]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.18, 0.36, 0.28)], seed=83)
    car.materials["paint_trim"] = tex_paint(PAINT, 64, seed=84)
    car.materials["intake"] = tex_flat((12, 12, 13))
    car.materials["vent"] = tex_flat((16, 16, 18))
    car.materials["vent_slats"] = tex_slats(64, 3)
    car.materials["glass"] = tex_glass(256, tint=(46, 58, 68), alpha=140)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_eggcrate(128)
    car.materials["wheel_alloy"] = tex_flat((178, 180, 184))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((16, 16, 17))
    car.materials["interior_liner"] = tex_flat((112, 98, 82))
    car.materials["trim_dark"] = tex_flat((22, 22, 24))
    car.materials["plate"] = tex_plate()
    car.materials["seat"] = tex_leather((120, 80, 52))
    car.materials["wood"] = tex_flat((96, 60, 34))
    car.materials["engine_chrome"] = tex_chrome()
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    return car


def face_out(part, k0, sign):
    """turn the chunks added to `part` since k0 so their mean normal points along sign * z (and flip the winding)"""
    for i in range(k0, len(part.n)):
        if np.sign(part.n[i][:, 2].mean()) != sign:
            part.n[i] = -part.n[i]
            part.f[i] = part.f[i][:, ::-1]


def tex_eggcrate(size=128, n=7):
    """the mouth's egg-crate grille: a satin grid on a black back, a dark rim"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    gx = np.abs(((xx * n) % 1.0) - 0.5) > 0.40
    gy = np.abs(((yy * n * 0.6) % 1.0) - 0.5) > 0.40
    v = np.where(gx | gy, 132.0, 14.0)
    r = np.hypot(xx - 0.5, yy - 0.5)
    v = np.where(r > 0.47, 20.0, v)
    return Image.fromarray(np.dstack([v, v * 0.99, v * 0.97]).clip(0, 255).astype(np.uint8))


def tex_slats(size=64, n=3):
    """three vent slots: dark openings between body-dark bars (u along the car)"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    f = (yy * n) % 1.0
    v = np.where(f < 0.62, 10.0, 70.0 + 50.0 * (f - 0.62) / 0.38)
    return Image.fromarray(np.dstack([v, v, v * 1.02]).clip(0, 255).astype(np.uint8))


def tex_plate(size=(128, 48)):
    from PIL import ImageDraw, ImageFont, ImageOps
    im = Image.new("RGB", size, (230, 228, 220))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, size[0] - 2, size[1] - 2], outline=(30, 30, 40), width=2)
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(p, 24) if os.path.exists(p) else ImageFont.load_default()
    t = "MT 047"
    w = d.textlength(t, font=f)
    d.text(((size[0] - w) / 2, 9), t, fill=(30, 30, 40), font=f)
    return ImageOps.flip(im)


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va25/p047.png", LEN)
