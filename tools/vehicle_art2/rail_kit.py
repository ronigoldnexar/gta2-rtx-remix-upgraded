#!/usr/bin/env python3
"""rail_kit (VEHICLE-ART-7): shared parts for the train cars (059 coach, 060 loco, 061 flat wagon) and the
truck trailers (055 tanker, 065 container, 066 car transporter), which were parametric loaves with the sprite
smeared over the roof and the ends (vr-trains-trailers-parametric-loaves-sprite-smear).

Metres, +z the nose (the sprite's lower end), +y up, 1 block = 5 m (carkit's write_glb scale 0.2). Every
model's bounds run exactly +-5 m along z (CARI 128 px = 2 blocks; the renderer fits the model's length to
the body's): GTA2 runs a train as cars overlapping by 0.41 block at each coupling, so a carriage's body
stops at +-BODY_HALF (3.95 m) and only a 1 cm marker under the floor holds the bounds at +-5 m.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from carkit import *  # noqa

HALF_LEN = 5.0
BODY_HALF = 3.95        # coupled carriages stand 7.95 m apart (10 m less the game's 0.41 block overlap)
GAUGE_X = 0.74          # wheel tread centre from the track's centre line
R_RAIL_WHEEL = 0.43


def bounds_markers(car):
    """1 cm cubes on the ground at +-5 m: the model's length is the game's 2 blocks"""
    car.box("underbody", (-0.005, 0.0, HALF_LEN - 0.01), (0.005, 0.01, HALF_LEN))
    car.box("underbody", (-0.005, 0.0, -HALF_LEN), (0.005, 0.01, -HALF_LEN + 0.01))


def rail_wheel(car, centre, side, marker=None):
    """a flanged rail wheel: tread, flange, a dished web and a hub boss (looking outward along +-x)"""
    r = R_RAIL_WHEEL
    prof = [(0.30 * r, -0.07), (0.88 * r, -0.07), (1.06 * r, -0.065), (1.06 * r, -0.045), (r, -0.035), (r, 0.065),
            (0.92 * r, 0.07), (0.70 * r, 0.05), (0.30 * r, 0.06), (0.22 * r, 0.11), (0.0, 0.115)]
    def mat(k):
        if k in (2, 3, 4):
            return "steel_bright"
        return "wheel_dark"
    car.revolve(prof, centre, (side, 0, 0), 26, mat_of=mat)
    if marker:
        car.marker(marker, centre)


def bogie(car, zc, wheelbase=2.0, y_axle=R_RAIL_WHEEL * 1.06, markers=None, frame="bogie"):
    """a two-axle bogie: wheelsets, outside side frames with leaf/coil spring blocks, a bolster across"""
    for k, dz in enumerate((-wheelbase / 2, wheelbase / 2)):
        for side in (1, -1):
            nm = markers[k][0 if side < 0 else 1] if markers else None
            rail_wheel(car, (side * GAUGE_X, y_axle, zc + dz), side, nm)
        # the axle
        car.sweep(lambda u, z=zc + dz: np.stack([(u - 0.5) * 2 * (GAUGE_X - 0.06), y_axle + 0 * u, z + 0 * u], 1), 0.07, 4, 8, "wheel_dark", up=(0, 0, 1))
    for side in (1, -1):
        x0 = side * (GAUGE_X + 0.13)
        # side frame: a deep plate between the axle boxes, arched over each wheel's top
        car.box(frame, (x0 - 0.04, y_axle - 0.10, zc - wheelbase / 2 - 0.40), (x0 + 0.04, y_axle + 0.12, zc + wheelbase / 2 + 0.40))
        car.box(frame, (x0 - 0.04, y_axle + 0.12, zc - 0.55), (x0 + 0.04, y_axle + 0.40, zc + 0.55))
        for dz in (-wheelbase / 2, wheelbase / 2):
            car.box("wheel_dark", (x0 - 0.07, y_axle - 0.09, zc + dz - 0.13), (x0 + 0.07, y_axle + 0.09, zc + dz + 0.13))   # axle box
        # coil springs (dark cylinders) between the frame and the bolster
        for dz in (-0.28, 0.0, 0.28):
            car.revolve([(0.075, 0.0), (0.075, 0.26), (0.0, 0.26)], (x0, y_axle + 0.12, zc + dz), (0, 1, 0), 10, default="wheel_dark", uv_mode="disc")
    car.box(frame, (-(GAUGE_X + 0.17), y_axle + 0.38, zc - 0.30), (GAUGE_X + 0.17, y_axle + 0.52, zc + 0.30))   # bolster


def buffers(car, z_face, sign, y=1.05, x=0.95, reach=0.42):
    """two sprung buffers and a centre coupler on a headstock at z_face, pointing along sign"""
    car.box("underbody", (-1.45, y - 0.20, min(z_face, z_face + sign * 0.10)), (1.45, y + 0.20, max(z_face, z_face + sign * 0.10)))
    for side in (1, -1):
        c = (side * x, y, z_face)
        car.revolve([(0.10, 0.0), (0.10, 0.20), (0.07, 0.22), (0.07, reach - 0.04)], c, (0, 0, sign), 14, default="wheel_dark", uv_mode="disc")
        car.revolve([(0.20, reach - 0.04), (0.20, reach), (0.0, reach + 0.01)], c, (0, 0, sign), 18, default="steel_bright", uv_mode="disc")
    car.box("wheel_dark", (-0.12, y - 0.20, min(z_face, z_face + sign * 0.36)), (0.12, y - 0.04, max(z_face, z_face + sign * 0.36)))


def road_axle(car, zc, names=None, x=1.12, r=0.50, w=0.30, dual=True):
    """a trailer axle with dual tyres each side (the outer pair carry the wheel markers)"""
    style = dict(rim_r=0.58, rim_mat="wheel_steel", cap_mat="steel_bright", whitewall=0.0, cap_dome=0.06)
    for side in (1, -1):
        nm = names[0 if side < 0 else 1] if names else None
        add_wheel(car, nm or "_tyre", (side * x, r, zc), r, w, side, style)
        if not nm:
            car.markers.pop()
        if dual:
            add_wheel(car, "_inner", (side * (x - w - 0.03), r, zc), r, w, side, style)
            car.markers.pop()
    car.sweep(lambda u: np.stack([(u - 0.5) * 2 * (x - 0.1), r + 0 * u, zc + 0 * u], 1), 0.06, 4, 8, "underbody")


def landing_legs(car, zc, x=0.95, top=1.30):
    for side in (1, -1):
        car.box("frame_dark", (side * x - 0.07, 0.10, zc - 0.07), (side * x + 0.07, top, zc + 0.07))
        car.box("frame_dark", (side * x - 0.16, 0.0, zc - 0.16), (side * x + 0.16, 0.06, zc + 0.16))   # sand shoe
    car.box("frame_dark", (-x, 0.80, zc - 0.04), (x, 0.86, zc + 0.04))


def trailer_chassis(car, z0, z1, y=1.40, x=0.55):
    """two deep I-beam rails, cross members, a bumper bar at the back"""
    for side in (1, -1):
        car.box("frame_dark", (side * x - 0.07, y - 0.30, z0), (side * x + 0.07, y, z1))
    for z in np.arange(z0 + 0.3, z1, 0.9):
        car.box("frame_dark", (-x, y - 0.12, z - 0.04), (x, y - 0.02, z + 0.04))
    # rear under-run bar and lamp board
    car.box("frame_dark", (-1.20, 0.55, z0 + 0.02), (1.20, 0.70, z0 + 0.12))
    for side in (1, -1):
        car.box("frame_dark", (side * 0.55 - 0.05, 0.62, z0 + 0.04), (side * 0.55 + 0.05, y - 0.30, z0 + 0.10))
        car.revolve([(0.07, 0.0), (0.07, 0.02), (0.0, 0.03)], (side * 1.10, 1.25, z0 - 0.01), (0, 0, -1), 12, default="lamp_tail", uv_mode="disc")
        car.revolve([(0.05, 0.0), (0.05, 0.02), (0.0, 0.03)], (side * 0.92, 1.25, z0 - 0.01), (0, 0, -1), 12, default="lamp_amber", uv_mode="disc")
        # mud flaps behind the rear axle
        car.box("rubber_flap", (side * 1.12 - 0.26, 0.18, z0 + 0.55), (side * 1.12 + 0.26, 0.75, z0 + 0.57))


def common_materials(car):
    car.materials["underbody"] = tex_flat((26, 25, 24))
    car.materials["wheel_dark"] = tex_flat((32, 30, 29))
    car.materials["steel_bright"] = tex_steel()
    car.materials["bogie"] = tex_grime((44, 40, 37), 128, seed=3)
    car.materials["frame_dark"] = tex_grime((36, 35, 34), 128, seed=4)
    car.materials["wheel_steel"] = tex_flat((120, 118, 112))
    car.materials["tyre_tread"] = tex_tread()
    car.materials["tyre_side"] = tex_tyre_side()
    car.materials["lamp_tail"] = tex_lamp("tail")
    car.materials["lamp_amber"] = tex_lamp("amber")
    car.materials["lamp_head"] = tex_lamp("head")
    car.materials["rubber_flap"] = tex_flat((22, 22, 22))


# ---- textures --------------------------------------------------------------------------------

def tex_steel(size=64):
    yy = np.linspace(0, 1, size)[:, None] * np.ones((1, size))
    v = 150 + 50 * np.cos(yy * math.pi * 2.0)
    return Image.fromarray(np.dstack([v, v + 2, v + 5]).clip(0, 255).astype(np.uint8))


def tex_grime(rgb, size=128, seed=1, streak=0.12):
    """a dull painted/oiled metal: soft noise and vertical streaks of road dirt"""
    n = noise(size, size, 5, seed) * 0.5 + noise(size, size, 30, seed + 1) * 0.5
    s = noise(size, 4, 1, seed + 2)
    s = np.asarray(Image.fromarray((s * 255).astype(np.uint8)).resize((size, size), Image.BILINEAR), float) / 255
    a = np.array(rgb, float)[None, None] * (0.90 + 0.16 * n - streak * s)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_corrugated(rgb, size=256, ribs=28, along_u=True, seed=5):
    """corrugated steel: ribs across the texture (u), soft shading of each rib, a little rust at the foot"""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    t = xx if along_u else yy
    rib = 0.80 + 0.20 * np.cos(t * ribs * 2 * math.pi)
    n = noise(size, size, 8, seed)
    a = np.array(rgb, float)[None, None] * (rib * (0.95 + 0.08 * n))[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_planks(size=256, n=10, rgb=(96, 72, 50), seed=7):
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    k = np.floor(xx * n)
    rng = np.random.default_rng(seed)
    tone = rng.uniform(0.82, 1.08, n + 1)[k.astype(int)]
    grain = 0.92 + 0.08 * noise(size, size, 3, seed)
    gap = (np.abs((xx * n) % 1.0 - 0.5) > 0.47)
    a = np.array(rgb, float)[None, None] * (tone * grain)[..., None]
    a[gap] *= 0.35
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_grating(size=128, rgb=(52, 50, 48), cells=16):
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    bar = (np.abs((xx * cells) % 1.0 - 0.5) > 0.36) | (np.abs((yy * cells / 2) % 1.0 - 0.5) > 0.42)
    v = np.where(bar, 1.0, 0.35)
    a = np.array(rgb, float)[None, None] * v[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_louvres(size=128, n=12, rgb=(150, 150, 150)):
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    s = (yy * n) % 1.0
    v = np.where(s < 0.55, 0.95 - 0.3 * s, 0.30)
    a = np.array(rgb, float)[None, None] * v[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
