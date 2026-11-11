#!/usr/bin/env python3
"""016 Panto (VEHICLE-ART-25): the catalog's 1960 Mini read from the GTA2 sprite nose down
(assets-src/cars/sprites_x4/016_panto_default.png, body 32 x 56 px, 0.078 m per sprite px): a two-box body whose
roof runs over 34 of the 56 px (rows 6-40: the sprite's long bright roof panel), a near-upright screen (the dark band
at rows 40-41) over a short sloping bonnet (rows 42-52), a wide grille and a bumper at the nose (rows 52-55), an
upright back light (row 6) over a short boot that drops straight to the bumper (rows 0-5), two side windows a side
(the sprite's dark columns: the door glass rows 21-36, the rear quarter light rows 9-18, split at the B pillar), tiny
wheels pushed to the corners (axles +15 / -16 px), the Mini's external welded seams (the roof's drip rails, the
flanges down the front and rear quarters, the sill seam), round headlamps in the wing fronts, tall tail lamps on the
rear corners, chrome blade bumpers with over-riders, silver steel wheels with chrome caps.
ONE paint over every body panel, the roof included (every remap recolours the whole sprite: out/va24_r8p showed the
shipped round-8 shell keeping the sprite's tan roof under a red body). Neutral 235 paint: the identity record tints it.
It replaces the round-8 image-to-3D shell (models3d_r8 r8A82). Metres, +z nose, 1 block = 5 m (2.50 x 4.375 m)."""
import math
import os
import sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "016_panto"
SPRITE = (170, 138, 116)         # catalog default remap paint (previews only)
PAINT = (235.0, 235.0, 235.0)    # neutral: the identity record tints it
LEN = 56 / 64 * 5.0              # 4.375 m
HALF_W = 32 / 64 * 5.0 / 2       # 1.25 m
ZF, ZR = 15 / 64 * 5.0, -16 / 64 * 5.0     # +1.17 / -1.25
R_TYRE, W_TYRE = 0.32, 0.26
X_WHEEL = 1.06                   # the Mini's wheels sit at the corners, nearly flush with the flanks
R_ARCH = 0.39                    # arch top 0.71, the waist 1.10: well clear (kit-wheel-split lesson)
BOT = 0.23
SV = 2.6
ZSB, ZST = 1.16, 0.90            # screen base / top (the sprite's dark band rows 40-42)
ZBB, ZBT = -1.98, -1.78          # back-light base / top (row 6)
V_BELT = 0.512


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    belt0 = spline([(zt, 1.04), (-2.02, 1.09), (-1.2, 1.10), (1.10, 1.095), (1.60, 1.06), (2.0, 0.99), (zn, 0.92)])
    top0 = spline([(zt, 1.095), (-2.08, 1.13), (ZBB, 1.14), (-1.90, 1.44), (ZBT, 1.67), (-1.62, 1.715), (-0.6, 1.735),
                   (0.50, 1.73), (0.78, 1.715), (ZST, 1.675), (1.03, 1.40), (ZSB, 1.155), (1.45, 1.125), (1.85, 1.075),
                   (2.05, 1.03), (zn - 0.05, 0.995), (zn, 0.975)])
    hw0 = spline([(zt, 1.18), (-1.95, 1.235), (-1.25, 1.25), (1.20, 1.25), (1.80, 1.235), (zn, 1.19)])
    tumble0 = spline([(zt, 0.0), (ZBB + 0.02, 0.0), (ZBT - 0.04, 0.33), (ZST + 0.02, 0.33), (ZSB - 0.04, 0.0), (zn, 0.0)])

    def arch(z):
        lift = np.zeros_like(z)
        for zc in (ZF, ZR):
            dz = np.abs(z - zc)
            y = R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - np.minimum(dz, R_ARCH) ** 2, 0, None))
            lift = np.maximum(lift, np.where(dz < R_ARCH, y, 0))
        return lift

    NOSE, TAIL = 0.42, 0.26
    def ends(z):
        dn = np.clip((z - (zn - NOSE)) / NOSE, 0, 1)
        dt = np.clip(((zt + TAIL) - z) / TAIL, 0, 1)
        fn = np.sqrt(np.clip(1 - dn ** 2, 0, 1))
        ft = np.sqrt(np.clip(1 - dt ** 2, 0, 1))
        return fn, ft

    def body(u, v, inset=0.0):
        z = np.asarray(u, float); v = np.asarray(v, float)
        fn, ft = ends(z)
        hw = hw0(z) * (0.68 + 0.32 * fn) * (0.80 + 0.20 * ft) - inset
        f = np.minimum(fn, ft)
        belt = belt0(z)
        fh = 0.86 + 0.14 * f
        top = belt + (top0(z) - belt) * (0.80 + 0.20 * ft) - inset
        bot = np.maximum(BOT, arch(z))
        bot = np.minimum(bot, belt - 0.08)
        bot = belt - (belt - bot) * fh + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        tb = tumble0(z) * hw / 1.25
        # the Mini's flank: near upright with a soft swell under the waist, rolling under to the sill seam
        xl = hw * (0.95 + 0.05 * sepow(c, 1.3))
        xl = np.where(s > 0.90, xl * sepow(c, 0.07), xl)
        yl = belt - (belt - bot) * sepow(s, 0.32)
        H = top - belt
        t = np.clip((v - 0.5) / 0.3, 0, 1) * 0.95
        ex = 6.0
        xs = hw * (1 - t ** ex) ** (1 / ex) - tb * t
        ys = belt + H * t
        w = np.clip((v - 0.8) / 0.2, 0, 1)
        X0 = hw * (1 - 0.95 ** ex) ** (1 / ex) - tb * 0.95
        xr = X0 * (1 - w)
        yr = belt + H * (0.95 + 0.05 * (1 - (1 - w) ** 4) ** 0.25)
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
    # the door glass (front edge along the A pillar), the rear quarter light, the upright screen and back light
    D0, D1, Q0, Q1 = 0.96, -0.52, -0.66, -1.74
    side1 = win([(D0, 0.55), (D1, 0.55), (D1, 0.765), (ZST - 0.04, 0.765)], 0.05)
    side2 = win([(Q0, 0.55), (Q1, 0.55), (ZBT + 0.08, 0.765), (Q0, 0.765)], 0.08)
    screen = win([(ZSB - 0.035, 0.815), (ZSB - 0.035, 1.03), (ZST + 0.03, 1.03), (ZST + 0.03, 0.815)], 0.03)
    backl = win([(ZBT - 0.03, 0.815), (ZBT - 0.03, 1.03), (ZBB + 0.035, 1.03), (ZBB + 0.035, 0.815)], 0.035)
    glass = sdf_union(side1, side2, screen, backl)
    seal = lambda u, v: glass(u, v) - 0.016
    belt_chrome = lambda u, v: np.maximum(np.maximum(0.5 - np.asarray(v), np.asarray(v) - V_BELT),
                                          np.maximum(np.asarray(u) - (ZST + 0.06), Q1 - 0.02 - np.asarray(u)))
    under = lambda u, v: np.maximum(np.asarray(v) - 0.30, body(u, v)[1] - (BOT + 0.11))
    car.surface(body, zt, zn, 0.0, 1.0, 76, 32, mirror=True,
                regions=[("glass", glass), ("seal", seal), ("chrome", belt_chrome), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[ZF - R_ARCH, ZF + R_ARCH, ZR - R_ARCH, ZR + R_ARCH, ZSB, ZST, ZBB, ZBT, D0, D1, Q0, Q1],
                vkeys=[0.55, 0.765, 0.80, 0.815, 0.50, V_BELT])
    # the flat ends: their own unbaked paint (the side's AO picture sampled across a planar face drew specks, VA23),
    # turned to face outward (the 004/058 fan caps came out facing in)
    k0 = len(car.parts["paint_trim"].p) if "paint_trim" in car.parts else 0
    car.cap(body, zt, 0.0, 1.0, 24, "paint_trim", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    face_out(car.parts["paint_trim"], k0, -1)
    k0 = len(car.parts["paint_trim"].p)
    car.cap(body, zn, 0.0, 1.0, 24, "paint_trim", regions=[("underbody", lambda u, v: np.asarray(v) - 0.12)])
    face_out(car.parts["paint_trim"], k0, +1)
    # the cabin liner: light grey-beige with its normals leaning up, so the cabin reads through the glass
    car.surface(lambda u, v: body(u, v, inset=0.06), ZBB + 0.06, ZSB - 0.06, 0.30, 1.0, 24, 10, mirror=True,
                default="interior_liner", uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))
    lp = car.parts["interior_liner"]
    lp.n = [(-np.asarray(n) + np.array([0.0, 2.5, 0.0])) for n in lp.n]
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.72, 1.22, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # the external welded seams: the roof's drip rails, the flanges down the front of the door and the rear quarter,
    # the sill seam between the arches
    def on_body(z, v, out=0.012):
        x, y, zz = body(np.asarray(z, float), np.full_like(np.asarray(z, float), v))
        return x + out, y, zz
    def drip(u):
        z = ZBT + 0.10 + (ZST - 0.10 - ZBT - 0.10) * np.asarray(u, float)
        x, y, zz = on_body(z, 0.80, 0.010)
        return np.stack([x, y + 0.012, zz], 1)
    for side in (1, -1):
        car.sweep(lambda u, side=side: drip(u) * np.array([side, 1, 1]), 0.014, 40, 6, "paint_trim", squash=(0.6, 1.0))
        for zs in (ZF - R_ARCH - 0.04, ZR + R_ARCH + 0.05):
            def flange(u, zs=zs, side=side):
                vv = 0.20 + (0.50 - 0.20) * np.asarray(u, float)
                x, y, zz = body(np.full_like(vv, zs), vv)
                return np.stack([side * (x + 0.008), y, zz], 1)
            car.sweep(flange, 0.012, 12, 6, "paint_trim", squash=(1.0, 0.6), up=(0, 0, 1))
        def sill(u, side=side):
            z = ZR + R_ARCH + 0.06 + (ZF - R_ARCH - 0.06 - ZR - R_ARCH - 0.06) * np.asarray(u, float)
            x, y, zz = body(z, np.full_like(z, 0.20))
            return np.stack([side * (x + 0.006), y, zz], 1)
        car.sweep(sill, 0.014, 20, 6, "paint_trim", squash=(0.6, 1.0))
        # external door hinges at the front of the door, the chrome push-button handle at its rear
        hz = ZF - R_ARCH - 0.10
        hx = float(body(np.array([hz]), np.array([0.40]))[0][0])
        for hy in (0.62, 0.96):
            car.box("paint_trim", (side * hx - 0.02, hy - 0.035, hz - 0.03), (side * hx + 0.02, hy + 0.035, hz + 0.03))
        car.box("chrome", (side * 1.245 - 0.014, 0.98, D1 + 0.05), (side * 1.245 + 0.014, 1.01, D1 + 0.19))

    # front: the wide grille (horizontal bars, a chrome surround with the moustache's dropped corners), round headlamps
    # in chrome bezels in the wing fronts, small side lamps under them, a slim blade bumper with over-riders
    GZ = zn + 0.004
    car.box("grille", (-0.58, 0.51, zn - 0.06), (0.58, 0.86, GZ))
    def surround(u, y0, y1):
        t = (np.asarray(u, float) - 0.5) * 2
        y = y0 + (y1 - y0) * np.abs(t) ** 3
        return np.stack([t * 0.60, y, GZ + 0.006 + 0 * t], 1)
    car.sweep(lambda u: surround(u, 0.875, 0.875), 0.016, 20, 8, "chrome")
    car.sweep(lambda u: surround(u, 0.50, 0.61), 0.015, 20, 8, "chrome")
    for side in (1, -1):
        car.sweep(lambda u, side=side: np.stack([side * 0.60 + 0 * u, 0.61 + 0.265 * u, GZ + 0.006 + 0 * u], 1), 0.015, 6, 8, "chrome")
    car.sweep(lambda u: np.stack([0 * u, 0.52 + 0.34 * u, GZ + 0.010 + 0 * u], 1), 0.010, 6, 6, "chrome")
    # lamp seats: the point on the wing's rounded front at x 0.86, y 0.82 (the bucket half sunk into the panel)
    uu, vv = np.meshgrid(np.linspace(zn - NOSE, zn, 160), np.linspace(0.2, 0.5, 90))
    bx, by, bz = body(uu.ravel(), vv.ravel())
    k = np.argmin(np.abs(bx - 0.86) + np.abs(by - 0.82))
    LAMP = np.array([0.86, 0.82, bz[k] + 0.02])
    for side in (1, -1):
        c = LAMP * np.array([side, 1.0, 1.0])
        ax = (side * 0.22, 0.03, 1.0)
        car.revolve([(0.128, -0.22), (0.126, -0.06), (0.118, -0.01), (0.112, 0.008)], c, ax, 24, default="paint_wheel", uv_mode="disc")
        car.revolve([(0.112, -0.01), (0.108, 0.018), (0.094, 0.030)], c, ax, 24, default="chrome", uv_mode="disc")
        car.revolve([(0.094, 0.026), (0.066, 0.038), (0.0, 0.044)], c, ax, 24, default="lamp_head", uv_mode="disc")
        car.revolve([(0.036, 0.0), (0.036, 0.016), (0.0, 0.022)], (side * 0.80, 0.60, zn - 0.03), (side * 0.15, 0, 1), 12,
                    default="lamp_amber", uv_mode="disc")
    def wrap(zc, sign, y, half):
        def path(u):
            t = (u - 0.5) * 2
            x = t * half
            e = np.clip(np.abs(t) - 0.82, 0, None) / 0.18
            z = zc - sign * (0.03 * t ** 2 + 0.16 * e * e)
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(wrap(zn + 0.06, 1, 0.38, 1.10), 0.060, 30, 10, "chrome", squash=(0.45, 1.0))
    car.sweep(wrap(zt - 0.05, -1, 0.39, 1.06), 0.058, 30, 10, "chrome", squash=(0.45, 1.0))
    for zc, dz in ((zn + 0.07, -0.02), (zt - 0.06, 0.02)):
        for side in (1, -1):
            car.sweep(lambda u, x=side * 0.42, zc=zc, dz=dz: np.stack([x + 0 * u, 0.30 + 0.20 * u, zc + dz * u], 1), 0.030, 6, 8, "chrome")
    # tail: tall lamps on the rear corners, the boot lid's plate (hinged at its foot, the Mini's) and lock
    for side in (1, -1):
        x0, x1 = sorted((side * 0.64, side * 0.84))
        car.box("trim_dark", (x0 - 0.01, 0.585, zt - 0.012), (x1 + 0.01, 1.00, zt + 0.03))
        car.box("lamp_tail", (x0, 0.745, zt - 0.020), (x1, 0.985, zt + 0.02))
        car.box("lamp_amber", (x0, 0.655, zt - 0.020), (x1, 0.74, zt + 0.02))
        car.box("lamp_head", (x0, 0.60, zt - 0.020), (x1, 0.65, zt + 0.02))
    car.box("trim_dark", (-0.24, 0.49, zt - 0.006), (0.24, 0.66, zt + 0.03))
    car.box("plate", (-0.21, 0.505, zt - 0.012), (0.21, 0.645, zt + 0.0))
    car.revolve([(0.022, 0.0), (0.022, 0.01), (0.0, 0.014)], (0, 0.90, zt - 0.003), (0, 0, -1), 12, default="chrome", uv_mode="disc")
    # door mirror on the driver's wing
    car.sweep(lambda u: np.stack([-1.10 - 0.10 * u, 1.08 + 0.08 * u, 1.45 + 0 * u], 1), 0.012, 4, 6, "chrome")
    car.revolve([(0.050, 0.0), (0.050, 0.02), (0.0, 0.026)], (-1.21, 1.18, 1.45), (0, 0, -1), 14, default="chrome", uv_mode="disc")
    # interior: two buckets, a rear bench, the parcel shelf, the dash rail with the centre speedo, a near-flat wheel
    for sx in (-0.48, 0.48):
        car.box("seat", (sx - 0.30, 0.54, -0.10), (sx + 0.30, 0.70, 0.38))
        car.box("seat", (sx - 0.28, 0.68, -0.22), (sx + 0.28, 1.28, -0.09))
    car.box("seat", (-0.96, 0.54, -1.30), (0.96, 0.70, -0.80))
    car.box("seat", (-0.96, 0.68, -1.42), (0.96, 1.22, -1.30))
    car.box("interior_dark", (-1.02, 1.06, -1.86), (1.02, 1.10, -1.46))
    car.box("interior_dark", (-1.04, 0.92, 0.86), (1.04, 1.08, 1.02))
    car.revolve([(0.075, -0.01), (0.075, 0.02)], (0, 1.10, 0.84), (0, 0.4, -1), 16, default="chrome", uv_mode="disc")
    car.revolve([(0.19, -0.012), (0.19, 0.012)], (-0.48, 1.04, 0.62), (0, 0.85, -1), 18, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.66, rim_mat="wheel_silver", cap_mat="chrome", whitewall=0.0, cap_dome=0.10)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    U = lambda z: (z - zt) / LEN
    lines_u = [(U(ZF - R_ARCH - 0.07), 0.16, 0.50), (U(D1 - 0.03), 0.16, 0.50), (U(ZSB + 0.04), 0.50, 1.0),
               (U(ZBB - 0.05), 0.50, 1.0)]
    lines_v = [(0.86, U(ZSB + 0.04), U(zn - 0.02))]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, lines_v=lines_v, ao_v=[(0.18, 0.36, 0.28)], seed=16)
    car.materials["paint_trim"] = tex_paint(PAINT, 64, seed=17)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=18)
    car.materials["glass"] = tex_glass(256, tint=(46, 58, 68), alpha=140)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_hgrille(128, bars=8)
    car.materials["wheel_silver"] = tex_flat((172, 174, 178))
    car.materials["underbody"] = tex_underbody()
    car.materials["interior_dark"] = tex_flat((16, 16, 17))
    car.materials["interior_liner"] = tex_flat((118, 111, 99))
    car.materials["trim_dark"] = tex_flat((22, 22, 24))
    car.materials["plate"] = tex_plate()
    car.materials["seat"] = tex_leather((112, 84, 62))
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


def tex_hgrille(size=128, bars=8):
    """the Mini's grille: horizontal satin bars on a dark back (t = up the box face), each lit on its top edge"""
    yy, xx = np.mgrid[0:size, 0:size] / float(size)
    f = (yy * bars) % 1.0
    bar = f < 0.42
    shade = np.where(bar, 112 + 64 * (1 - f / 0.42), 22 + 10 * f)
    v = shade
    return Image.fromarray(np.dstack([v, v * 0.99, v * 0.97]).clip(0, 255).astype(np.uint8))


def tex_plate(size=(128, 48)):
    from PIL import ImageDraw, ImageFont, ImageOps
    im = Image.new("RGB", size, (226, 222, 205))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, size[0] - 2, size[1] - 2], outline=(30, 30, 40), width=2)
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    f = ImageFont.truetype(p, 24) if os.path.exists(p) else ImageFont.load_default()
    t = "PT 016"
    w = d.textlength(t, font=f)
    d.text(((size[0] - w) / 2, 9), t, fill=(30, 30, 40), font=f)
    return ImageOps.flip(im)        # the box's -z face reads its picture upside down


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va25/p016.png", LEN)
