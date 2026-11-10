#!/usr/bin/env python3
"""040 Maurice: a rounded early-1950s two-door saloon (Morris Minor idiom) read from the GTA2 sprite (sprite 35,
nose down in the sprite: a long domed bonnet with a centre crease, a big oval glasshouse the sprite paints lilac,
a short round boot; wheels +16 / -17 px, windscreen +10 px, rear window -19 px of 58). Separate front wings with
the headlamps in their noses, bulged rear wings, a split windscreen, chrome blade bumpers, a plain number plate.
Replaces the image-to-3D shell (FIX-CAR-TEX, pm70: torn window outlines, patchy paint, a garbled plate).
Metres, +z nose, 1 block = 5 m (catalog body 0.469 x 0.906 blocks: 2.34 x 4.53 m; the sprite is wider than a
real Minor and the model keeps the sprite's footprint)."""
import math
import os
import sys
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from carkit import *  # noqa

NAME = "040_maurice"
PAINT = (235.0, 235.0, 235.0)    # neutral base, tinted by the live paint (identity.cpp; see car_036.py)
SPRITE = (73, 87, 65)            # the bil player car's green (pm70), for previews
LEN = 0.906 * 5.0                # 4.53 m
ZF, ZR = 16 / 64 * 5.0, -17 / 64 * 5.0     # axles: 1.25, -1.33
R_TYRE, W_TYRE = 0.34, 0.21
X_WHEEL = 0.93
R_ARCH = 0.40
BOT = 0.30


def build():
    car = Car(NAME)
    car.preview_tint = SPRITE
    zn, zt = LEN / 2, -LEN / 2

    # centre line top: bonnet (crowned, falling to the nose), windscreen, roof, rear window, boot
    top0 = spline([(zt, 0.70), (-2.05, 0.86), (-1.75, 0.98), (-1.45, 1.06), (-1.20, 1.30), (-0.85, 1.52), (-0.40, 1.62),
                   (0.10, 1.63), (0.45, 1.56), (0.62, 1.38), (0.86, 1.08), (1.30, 1.00), (1.80, 0.90), (2.10, 0.78), (zn, 0.66)])
    belt0 = spline([(zt, 0.70), (-1.9, 0.92), (-1.3, 1.02), (0.7, 1.02), (1.3, 0.94), (1.9, 0.80), (zn, 0.66)])
    hw0 = spline([(zt, 0.52), (-2.00, 0.70), (-1.45, 0.80), (0.75, 0.82), (1.40, 0.70), (1.95, 0.56), (zn, 0.44)])
    bot0 = spline([(zt, 0.50), (-1.95, BOT), (1.95, BOT), (zn, 0.48)])

    def ends(z, nose=0.26, tail=0.30):
        dn = np.clip((z - (zn - nose)) / nose, 0, 1)
        dt = np.clip(((zt + tail) - z) / tail, 0, 1)
        return np.sqrt(np.clip(1 - dn ** 2, 0, 1)) * np.sqrt(np.clip(1 - dt ** 2, 0, 1))

    def body(u, v, inset=0.0):
        """u = z; v in 0..1: bottom centre -> belt (v = 0.5) -> roof centre"""
        z = np.asarray(u, float); v = np.asarray(v, float)
        f = ends(z)
        hw = hw0(z) * f - inset
        belt = belt0(z)
        top = belt + (top0(z) - belt) * f - inset
        bot = belt - (belt - bot0(z)) * f + inset
        lo = v < 0.5
        a = np.where(lo, (0.5 - v) * math.pi, (v - 0.5) * math.pi)
        c, s = np.cos(a), np.sin(a)
        # the glasshouse tumbles in more than the Beetle's dome (a narrower roof over a wide waist)
        x = np.where(lo, hw * (0.88 + 0.12 * sepow(c, 1.4)), hw * sepow(c, 0.70) * (0.80 + 0.20 * c))
        y = np.where(lo, belt - (belt - bot) * sepow(s, 0.55), belt + (top - belt) * sepow(s, 0.90))
        return x, y, z

    SU, SV = 1.0, 2.4
    def win(poly, r):
        p = np.array(poly, float)
        c = p.mean(0)
        d = p - c
        shrink = p - d / np.linalg.norm(d * [SU, SV], axis=1, keepdims=True) * r / np.array([SU, SV])
        f = poly_sdf(shrink, SU, SV)
        return lambda u, v: f(u, v) - r
    # (the glass stops at v 0.79, 50 degrees round the roof's shoulder: higher, and from the chase camera the
    # roof read as a glass bubble with the cabin showing through)
    # two doors: one long door glass with a quarter light, then a rear side window; the split windscreen; the
    # small rear window (the sprite: windscreen at +0.78 m, rear window at -1.48 m)
    side_front = win([(0.58, 0.585), (-0.30, 0.585), (-0.30, 0.79), (0.40, 0.79)], 0.05)
    side_rear = win([(-0.40, 0.585), (-1.08, 0.585), (-0.86, 0.79), (-0.40, 0.79)], 0.07)
    screen_l = win([(0.80, 0.62), (0.80, 0.985), (0.52, 0.985), (0.52, 0.88)], 0.05)
    screen = lambda u, v: np.maximum(screen_l(u, v), 0.90 - np.asarray(v))
    rear = win([(-1.12, 0.90), (-1.12, 1.03), (-1.42, 1.03), (-1.42, 0.90)], 0.08)
    glass = sdf_union(side_front, side_rear, screen, rear)
    seal = lambda u, v: glass(u, v) - 0.012
    # chrome: the split windscreen's centre bar (the screen's two halves meet at the centre line, v = 1)
    def screen_bar(u, v):
        return np.maximum(np.abs(1 - np.asarray(v)) * 2.4 - 0.022, screen_l(u, v) - 0.03)
    # the bonnet's centre crease (the sprite's pale stripe down the bonnet) as a chrome strip
    def bonnet_strip(u, v):
        z = np.asarray(u, float)
        return np.maximum(np.abs(1 - np.asarray(v)) * 2.4 - 0.014, np.maximum(0.95 - z, z - 2.12))
    # the belt moulding: a thin chrome line along the waist between the wings
    def belt_line(u, v):
        z = np.asarray(u, float)
        return np.maximum(np.abs(np.asarray(v) - 0.555) * 2.4 - 0.010, np.maximum(-1.55 - z, z - 0.85))
    def under(u, v):
        x, y, z = body(u, v)
        return np.maximum(np.asarray(v) - 0.30, y - (BOT + 0.10))
    car.surface(body, zt, zn, 0.0, 1.0, 72, 40, mirror=True,
                regions=[("chrome", screen_bar), ("glass", glass), ("seal", seal), ("chrome", bonnet_strip),
                         ("chrome", belt_line), ("underbody", under)],
                default="paint_body", uvfn=lambda u, v: ((u - zt) / LEN, v),
                ukeys=[0.80, 0.52, 0.58, -0.30, -0.40, -1.08, -1.12, -1.42], vkeys=[0.585, 0.79, 0.88, 0.90, 1.03])
    # the cabin's inside: a dark shell a few cm in
    car.surface(lambda u, v: body(u, v, inset=0.05), -1.45, 0.82, 0.25, 1.0, 24, 12, mirror=True, default="interior_dark",
                uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # wings: pontoons over each wheel; the front ones run forward into the lamp nacelles, the rear ones bulge
    def wing(zc, z0, z1, x0, a_max, top_y, round_front, round_back, sweep_back, sweep_front):
        def fn(u, v):
            z = np.asarray(u, float); phi = np.asarray(v, float)
            tb = np.clip((z - z0) / round_back, 0, 1) if round_back > 0 else np.ones_like(z)
            tf = np.clip((z1 - z) / round_front, 0, 1) if round_front > 0 else np.ones_like(z)
            e = np.sqrt(1 - (1 - tb) ** 2) * np.sqrt(1 - (1 - tf) ** 2)
            sb = smoothstep(z0 + sweep_back, z0, z) if sweep_back > 0 else np.zeros_like(z)
            sf = smoothstep(z1 - sweep_front, z1, z) if sweep_front > 0 else np.zeros_like(z)
            sw = np.maximum(sb, sf)
            dz = z - zc
            yc = np.where(np.abs(dz) < R_ARCH, R_TYRE + np.sqrt(np.clip(R_ARCH ** 2 - dz ** 2, 0, None)), R_TYRE)
            yc = np.maximum(yc, BOT + 0.06)
            yc = yc * (1 - sw) + (BOT + 0.06) * sw
            crown = top_y - 0.08 * np.clip(np.abs(dz) / 1.0, 0, 1) ** 2
            ytop = yc + (crown - yc) * e
            ytop = ytop * (1 - sw) + (BOT + 0.12) * sw
            a = a_max * (0.82 + 0.18 * np.clip(1 - (dz / 1.0) ** 2, 0, 1)) * np.maximum(e, 0.0)
            a = a * (1 - 0.15 * sw)
            b = np.maximum(ytop - yc, 1e-4)
            x = x0 + a * sepow(np.cos(phi), 0.8)
            y = yc + b * sepow(np.sin(phi), 0.9)
            return x, y, z
        return fn
    wf = wing(ZF, 0.35, zn - 0.02, X_WHEEL - 0.05, 0.26, 0.90, 0.30, 0.0, 0.62, 0.0)
    wr = wing(ZR, -2.18, -0.55, X_WHEEL - 0.05, 0.25, 0.96, 0.0, 0.34, 0.0, 0.55)
    wings = (("paint_fender_f", wf, 0.35, zn - 0.02), ("paint_fender_r", wr, -2.18, -0.55))
    for mname, fn, z0, z1 in wings:
        car.surface(fn, z0, z1, 0.0, math.pi, 32, 12, mirror=True, default=mname,
                    uvfn=lambda u, v, z0=z0, z1=z1: ((u - z0) / (z1 - z0), v / math.pi))
    # sills between the wings
    for side in (1, -1):
        car.box("running_board_rubber", (min(side * 0.74, side * 1.02), BOT + 0.01, -0.55), (max(side * 0.74, side * 1.02), BOT + 0.07, 0.35))
    # wheel arch liners
    for zc in (ZF, ZR):
        for side in (1, -1):
            def liner(u, v, zc=zc, side=side):
                a = np.asarray(u, float); x = np.asarray(v, float)
                return side * x, R_TYRE + (R_ARCH - 0.01) * np.sin(a), zc + (R_ARCH - 0.01) * np.cos(a)
            car.surface(liner, 0.05, math.pi - 0.05, 0.60, 1.10, 16, 2, default="underbody",
                        uvfn=lambda u, v: (0.5 + 0 * u, 0.5 + 0 * v))

    # headlamps in the wing noses, side lamps under them, tail lamps on the rear wings' backs
    for side in (1, -1):
        c = np.array([side * (X_WHEEL - 0.05), 0.76, 2.17])     # sunk in the wing's nose, on its axis
        ax = (0.0, 0.08, 1.0)
        car.revolve([(0.115, -0.03), (0.118, 0.012), (0.105, 0.028)], c, ax, 22, default="chrome", uv_mode="disc")
        car.revolve([(0.104, 0.024), (0.07, 0.045), (0.0, 0.052)], c, ax, 22, default="lamp_head", uv_mode="disc")
        car.revolve([(0.03, 0.0), (0.0, 0.014)], np.array([side * 0.52, 0.66, 2.24]), (0, 0, 1), 12, default="lamp_amber", uv_mode="disc")
        t = np.array([side * (X_WHEEL - 0.03), 0.82, -2.12])
        car.revolve([(0.055, -0.02), (0.058, 0.02), (0.0, 0.036)], t, (side * 0.15, 0.25, -1.0), 16, default="lamp_tail", uv_mode="disc")

    # grille: a dark slatted panel in the nose under the bonnet, with a chrome surround
    car.box("grille", (-0.30, 0.44, zn - 0.06), (0.30, 0.62, zn + 0.005))
    car.sweep(lambda u: np.stack([(u - 0.5) * 0.62, 0.63 + 0 * u, zn - 0.01 + 0 * u], 1), 0.014, 10, 6, "chrome")
    # blade bumpers with over-riders
    def blade(zc, sign, y):
        def path(u):
            x = (u - 0.5) * 2 * 0.96
            z = zc - sign * 0.18 * (x / 0.96) ** 2
            return np.stack([x, np.full_like(x, y), z], 1)
        return path
    car.sweep(blade(zn + 0.05, 1, 0.42), 0.065, 22, 8, "chrome", squash=(0.35, 1.0))
    car.sweep(blade(zt - 0.05, -1, 0.46), 0.065, 22, 8, "chrome", squash=(0.35, 1.0))
    for zc, sgn, y in ((zn + 0.04, 1, 0.36), (zt - 0.04, -1, 0.40)):
        for side in (1, -1):
            x = side * 0.42
            car.sweep(lambda u, x=x, zc=zc, sgn=sgn, y=y: np.stack([x + 0 * u, y + 0.20 * u, zc - sgn * 0.10 - sgn * 0.02 * u], 1),
                      0.024, 6, 8, "chrome")
    # number plate on the boot lid's lower edge, square to the road, in a dark frame
    yp, zp = 0.60, zt + 0.06
    car.box("seal", (-0.215, yp - 0.075, zp - 0.012), (0.215, yp + 0.075, zp + 0.004))
    car.box("plate", (-0.20, yp - 0.062, zp - 0.022), (0.20, yp + 0.062, zp - 0.010))
    # boot handle, door handles, a mirror
    car.box("chrome", (-0.06, 0.74, zt + 0.07), (0.06, 0.77, zt + 0.12))
    for side in (1, -1):
        car.box("chrome", (side * 0.83 - 0.012, 1.00, -0.24), (side * 0.83 + 0.012, 1.025, -0.12))
    car.sweep(lambda u: np.stack([-0.82 - 0.10 * u, 1.10 + 0.04 * u, 0.50 + 0 * u], 1), 0.012, 4, 6, "chrome")
    car.revolve([(0.045, 0.0), (0.045, 0.02), (0.0, 0.03)], (-0.94, 1.15, 0.50), (0, 0, -1), 14, default="chrome", uv_mode="disc")

    # interior: two front seats, a rear bench, a dash, the wheel
    for xs in (-0.38, 0.38):
        car.box("seat", (xs - 0.25, 0.50, -0.10), (xs + 0.25, 0.64, 0.40))
        car.box("seat", (xs - 0.25, 0.60, -0.20), (xs + 0.25, 1.20, -0.08))
    car.box("seat", (-0.66, 0.50, -1.05), (0.66, 0.64, -0.60))
    car.box("seat", (-0.66, 0.60, -1.18), (0.66, 1.16, -1.05))
    car.box("interior_dark", (-0.72, 0.84, 0.62), (0.72, 1.02, 0.80))
    car.revolve([(0.17, -0.01), (0.17, 0.01), (0.15, 0.01), (0.15, -0.01), (0.17, -0.01)], (-0.38, 1.06, 0.48),
                (0, 0.45, -1.0), 20, default="interior_dark", uv_mode="disc")

    style = dict(rim_r=0.56, rim_mat="paint_wheel", cap_mat="chrome", whitewall=0.0, cap_dome=0.14)
    for nm, zc, xw in (("wheel_fl", ZF, -X_WHEEL), ("wheel_fr", ZF, X_WHEEL), ("wheel_rl", ZR, -X_WHEEL), ("wheel_rr", ZR, X_WHEEL)):
        add_wheel(car, nm, (xw, R_TYRE, zc), R_TYRE, W_TYRE, 1 if xw > 0 else -1, style)

    # paint: door gaps (two doors), bonnet and boot lid outlines
    U = lambda z: (z - zt) / LEN
    lines_u = [(U(0.60), 0.36, 0.585), (U(-0.36), 0.36, 0.585), (U(0.88), 0.80, 1.0), (U(-1.50), 0.74, 1.0), (U(-2.10), 0.74, 1.0)]
    car.materials["paint_body"] = tex_paint(PAINT, 512, lines_u=lines_u, ao_v=[(0.16, 0.34, 0.30)], seed=40)
    car.materials["paint_wheel"] = tex_paint(PAINT, 64, seed=41)
    for mname, fn, z0, z1 in wings:
        car.materials[mname] = tex_paint(PAINT, 256, seed=42)
    bake_ao(car, body, zt, zn, 0.0, 1.0, "paint_body")
    for mname, fn, z0, z1 in wings:
        bake_ao(car, fn, z0, z1, 0.0, math.pi, mname, size=96)
    # the sprite's lilac glass (sprite 35's window colour), kept dark enough to read as glass
    car.materials["glass"] = tex_glass(256, tint=(84, 82, 112), alpha=128)
    car.materials["seal"] = tex_flat((20, 20, 22))
    car.materials["chrome"] = tex_chrome()
    car.materials["grille"] = tex_grille(128, bars=9)
    car.materials["plate"] = tex_plate("M040")
    car.materials["underbody"] = tex_underbody()
    car.materials["running_board_rubber"] = tex_flat((34, 33, 32))
    car.materials["interior_dark"] = tex_flat((44, 40, 36))
    car.materials["seat"] = tex_leather((120, 46, 40))
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    return car


def tex_plate(text, w=256, h=80):
    """a 1950s British plate: white characters on black, a thin silver edge (box UVs map the whole picture to
    each face; only the outward face is seen)"""
    from PIL import Image, ImageDraw, ImageFont
    im = Image.new("RGB", (w, h), (18, 18, 20))
    d = ImageDraw.Draw(im)
    d.rectangle([1, 1, w - 2, h - 2], outline=(170, 170, 175), width=3)
    try:
        font = ImageFont.truetype("DejaVuSansMono-Bold.ttf", int(h * 0.62))
    except OSError:
        font = ImageFont.load_default()
    b = d.textbbox((0, 0), text, font=font)
    d.text(((w - (b[2] - b[0])) / 2 - b[0], (h - (b[3] - b[1])) / 2 - b[1]), text, font=font, fill=(225, 225, 225))
    # box() maps v up the face (glTF v runs down the picture): store it upside down so it reads upright
    return im.transpose(Image.FLIP_TOP_BOTTOM)


if __name__ == "__main__":
    car = build()
    print(NAME, "vertices %d, triangles %d" % car.stats())
    import preview
    preview.sheet(car, sys.argv[1] if len(sys.argv) > 1 else "/tmp/va2/p040.png", LEN)
