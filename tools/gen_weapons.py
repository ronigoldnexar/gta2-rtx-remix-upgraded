#!/usr/bin/env python3
"""Hand-held weapon models for the street-level views: what a figure holds while
it aims and fires, as a modern game draws them, in place of the stylised pickup
sprites. Procedural, GTA2's own palette (the retro-modern 1950s look: blued
steel, walnut, brass), a few hundred triangles each.

    python3 tools/gen_weapons.py <out dir> [--sheet out/x.png]

Writes <out>/weapon_<name>.glb and manifest_fragment.json. Model space: +z is
the barrel (the way the shot goes), +y up, +x to the weapon's right; the origin
is the grip (where the right hand holds it), so the renderer places the grip at
the hand joint and the muzzle at +z * length_ahead.
Sizes in blocks (a block is a car's length, ~4.8 m): a pistol 0.065, a tommy gun
0.17, a shotgun 0.21, a rocket launcher 0.22, a flamethrower 0.18.
"""
import json, math, os, sys
import numpy as np
import trimesh
from trimesh.visual.material import PBRMaterial
from trimesh.visual import TextureVisuals
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_objects import Part, box_part, cylinder_part, scene_with  # noqa: E402

STEEL = (44, 46, 52)
BLUED = (28, 30, 38)
WALNUT = (92, 58, 32)
BRASS = (170, 140, 70)
OLIVE = (74, 82, 52)
RUBBER = (24, 24, 24)
GLASS = (120, 190, 220)
TANK = (120, 60, 30)


SKIN = (178, 128, 98)
# FIX-AVATAR-IDENTITY: the player's shirt as his figure wears it in third person and as the classic
# sprite draws it: near-black (the manifest's remap 25 top, ped_outfits[25] = 61,61,66), a short sleeve.
# (Was off-white with dark stripes, the old human_male_01 hero: the arms changed clothes at the V press.)
SLEEVE = (60, 60, 66)


def flat(rgb, size=4):
    return Image.new("RGBA", (size, size), tuple(int(v) for v in rgb) + (255,))


def grain(rgb, kind="metal", size=32, seed=7):
    """A small surface texture instead of a flat colour, so the parts read as
    materials when the first-person view model puts them a hand from the eye:
    brushed steel (fine streaks), wood (grain lines), cloth (weave), skin (soft
    mottling). Mean colour kept at `rgb`, so the chase-camera look is the same."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32) / size
    if kind == "metal":
        v = 0.06 * np.sin(2 * np.pi * (y * 9 + 0.3 * rng.standard_normal((size, 1)))) + 0.05 * rng.standard_normal((size, size))
    elif kind == "wood":
        v = 0.16 * np.sin(2 * np.pi * (x * 6 + 0.6 * np.sin(2 * np.pi * y * 1.5))) + 0.06 * rng.standard_normal((size, size))
    elif kind == "cloth":
        v = 0.07 * ((np.floor(x * size) + np.floor(y * size)) % 2 - 0.5) + 0.06 * rng.standard_normal((size, size))
    elif kind == "stripes":   # the shirt: dark bands round the arm
        v = np.where((np.floor(y * 8) % 2) == 0, -0.62, 0.0) + 0.04 * rng.standard_normal((size, size))
    else:   # skin
        v = 0.05 * rng.standard_normal((size, size))
        v = (v + np.roll(v, 1, 0) + np.roll(v, 1, 1) + np.roll(v, -1, 0)) * 0.5
    img = np.clip(np.array(rgb, np.float32)[None, None, :] * (1.0 + v[..., None]), 0, 255).astype(np.uint8)
    a = np.full((size, size, 1), 255, np.uint8)
    return Image.fromarray(np.concatenate([img, a], 2), "RGBA")


def fine(rgb, kind, size=256, seed=7):
    """FIX-FIGURE-11 (ptrmx27): the first-person arms' skin and sleeve at 256 px. The 32 px `grain` noise was
    magnified to 4-5 px square texels on a fist that fills a fifth of the frame. Skin: soft low-frequency
    mottling (blurred, no per-texel noise) with faint pores; sleeve: a 4 px weave, softened. Mean colour kept."""
    from PIL import ImageFilter
    rng = np.random.default_rng(seed)
    def soft(radius, amp):
        n = Image.fromarray(np.uint8(np.clip(128 + 60 * rng.standard_normal((size, size)), 0, 255)), "L")
        n = np.asarray(n.filter(ImageFilter.GaussianBlur(radius)), np.float32) - 128.0
        return n / (np.abs(n).max() + 1e-6) * amp
    if kind == "skin":
        v = soft(14, 0.07) + soft(3, 0.025) + 0.008 * rng.standard_normal((size, size))
    else:   # cloth
        y, x = np.mgrid[0:size, 0:size]
        w = (((x // 4) + (y // 4)) % 2 - 0.5) * 0.06
        v = np.asarray(Image.fromarray(np.uint8(128 + w * 255)).filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255.0 - 0.5
        v = v + soft(10, 0.05)
    img = np.clip(np.array(rgb, np.float32)[None, None, :] * (1.0 + v[..., None]), 0, 255).astype(np.uint8)
    a = np.full((size, size, 1), 255, np.uint8)
    return Image.fromarray(np.concatenate([img, a], 2), "RGBA")


def mat(rgb, metallic=0.8, roughness=0.35, emissive=None, name="m", kind=None, hires=False):
    if kind is None:
        kind = "metal" if metallic >= 0.5 else ("wood" if rgb == WALNUT else "plain")
    tex = fine(rgb, kind, seed=sum(rgb)) if hires else flat(rgb) if kind == "plain" else grain(rgb, kind, seed=sum(rgb))
    return PBRMaterial(name=name, baseColorTexture=tex, metallicFactor=metallic, roughnessFactor=roughness,
                       emissiveFactor=emissive)


def box(p, c, size):
    """A box centred at c with full size `size` (x, y, z)."""
    x0, y0, z0 = (c[i] - size[i] / 2 for i in range(3))
    x1, y1, z1 = (c[i] + size[i] / 2 for i in range(3))
    box_part(p, x0, x1, y0, y1, z0, z1)


def tube(p, c, radius, length, segments=12, r2=None):
    """A cylinder along +z centred at c (its middle), optionally tapering to r2 at the far end."""
    q = Part()
    r2 = radius if r2 is None else r2
    cylinder_part(q, lambda t: radius + (r2 - radius) * t, -length / 2, length / 2, segments=segments, rings=1, cap=True)
    # cylinder_part builds about +y; turn it to +z and move it
    rot = trimesh.transformations.rotation_matrix(math.radians(90), [1, 0, 0])
    v = np.array(q.v, np.float32)
    v = (rot[:3, :3] @ v.T).T + np.array(c, np.float32)
    n = (rot[:3, :3] @ np.array(q.n, np.float32).T).T
    b = len(p.v)
    p.v += list(v); p.n += list(n); p.uv += list(q.uv)
    p.f += [[a + b for a in f] for f in q.f]


def tube_between(p, a, b, r1, r2=None, segments=12):
    """A tapered cylinder from point a (radius r1) to point b (radius r2), capped."""
    a = np.array(a, np.float32); b = np.array(b, np.float32)
    r2 = r1 if r2 is None else r2
    axis = b - a
    length = float(np.linalg.norm(axis))
    q = Part()
    cylinder_part(q, lambda t: r1 + (r2 - r1) * t, 0.0, length, segments=segments, rings=2, cap=True)
    # +y onto the axis
    y = axis / length
    ref = np.array([0, 0, 1], np.float32) if abs(y[2]) < 0.9 else np.array([1, 0, 0], np.float32)
    x = np.cross(y, ref); x /= np.linalg.norm(x)
    z = np.cross(x, y)
    R = np.stack([x, y, z], 1)
    v = (R @ np.array(q.v, np.float32).T).T + a
    n = (R @ np.array(q.n, np.float32).T).T
    base = len(p.v)
    p.v += list(v); p.n += list(n); p.uv += list(q.uv)
    p.f += [[i + base for i in f] for f in q.f]


def blob(p, c, radii, segments=10, rings=6):
    """An ellipsoid centred at c with semi-axes `radii` (x, y, z): knuckles, palms."""
    base = len(p.v)
    for r in range(rings + 1):
        th = math.pi * r / rings
        for s in range(segments + 1):
            ph = 2 * math.pi * s / segments
            d = np.array([math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)], np.float32)
            p.v.append(np.array(c, np.float32) + d * np.array(radii, np.float32))
            nn = d / np.maximum(np.array(radii, np.float32), 1e-6)
            p.n.append(nn / np.linalg.norm(nn))
            p.uv.append((s / segments, r / rings))
    for r in range(rings):
        for s in range(segments):
            i0 = base + r * (segments + 1) + s
            i1 = i0 + segments + 1
            p.f += [[i0, i0 + 1, i1], [i0 + 1, i1 + 1, i1]]


def pistol():
    body = Part(); grip = Part(); trim = Part()
    # slide and frame along +z from the grip at the origin
    box(body, (0, 0.012, 0.018), (0.009, 0.010, 0.050))      # slide
    box(body, (0, 0.004, 0.012), (0.008, 0.007, 0.032))      # frame
    tube(body, (0, 0.012, 0.047), 0.0025, 0.012)             # barrel tip
    for k in range(5):                                        # slide serrations at the back
        box(trim, (0, 0.012, -0.004 + k * 0.0022), (0.0094, 0.0085, 0.0009))
    box(trim, (0.0046, 0.0135, 0.010), (0.0006, 0.004, 0.010))   # ejection port (dark inset)
    box(trim, (0, 0.019, 0.004), (0.003, 0.003, 0.006))      # rear sight
    box(trim, (0, 0.019, 0.040), (0.002, 0.003, 0.003))      # front sight
    box(trim, (0, 0.013, -0.009), (0.003, 0.004, 0.003))     # hammer
    box(grip, (0, -0.012, -0.004), (0.010, 0.026, 0.013))     # grip (walnut panels)
    box(body, (0, -0.002, 0.004), (0.006, 0.006, 0.010))      # trigger guard block
    box(trim, (0, -0.0035, 0.0055), (0.002, 0.005, 0.002))   # trigger
    return scene_with([("slide", body.mesh(mat(BLUED, 0.9, 0.3, name="slide"))),
                       ("grip", grip.mesh(mat(WALNUT, 0.1, 0.6, name="grip"))),
                       ("trim", trim.mesh(mat(STEEL, 0.8, 0.4, name="trim")))]), 0.065


def bevel_box(p, c, size, bev, axis=2):
    """A box centred at c with full size `size` whose four edges along `axis` are chamfered by `bev`
    (an octagonal prism): FIX-FIGURE-8 (pm10), the hard-edged brick read as a toy a hand from the eye."""
    a = axis; i, j = [k for k in range(3) if k != a]
    hi, hj, ha = size[i] / 2, size[j] / 2, size[a] / 2
    b = min(bev, hi * 0.9, hj * 0.9)
    ring = [(hi, -hj + b), (hi, hj - b), (hi - b, hj), (-hi + b, hj), (-hi, hj - b), (-hi, -hj + b), (-hi + b, -hj), (hi - b, -hj)]
    def pt(u, w, t):
        q = [0.0, 0.0, 0.0]; q[i] = c[i] + u; q[j] = c[j] + w; q[a] = c[a] + t; return q
    cen = np.array(c, np.float32)
    def quad(q0, q1, q2, q3):
        n = np.cross(np.array(q1) - np.array(q0), np.array(q3) - np.array(q0))
        mid = (np.array(q0) + np.array(q2)) / 2
        if np.dot(n, mid - cen) < 0: q0, q1, q2, q3 = q3, q2, q1, q0
        p.quad(q0, q1, q2, q3)
    for k in range(8):
        (u0, w0), (u1, w1) = ring[k], ring[(k + 1) % 8]
        quad(pt(u0, w0, -ha), pt(u1, w1, -ha), pt(u1, w1, ha), pt(u0, w0, ha))
    for t in (-ha, ha):   # the end caps: the octagon as three quads
        r = [pt(u, w, t) for (u, w) in ring]
        quad(r[0], r[1], r[2], r[7]); quad(r[2], r[3], r[6], r[7]); quad(r[3], r[4], r[5], r[6])


def machine_gun():
    """FIX-FIGURE-8 (pm24 / pm10): the game's machine gun is the S-Uzi (its HUD icon): a compact
    submachine gun, the magazine up through the pistol grip, a short barrel out of a squared
    receiver with a top cover, a polymer handguard under its front, a folding wire stock with a
    chamfered butt plate, folded. (Was a Thompson with a drum and a wooden brick stock.)
    Places the rig and the view model use (dll/src/weapon_rig.cpp GeoFor wMg, live_geometry.cpp
    fore[] for kWpnMg): bore y 0.017; handguard underside z 0.058, y -0.002; magazine foot
    z 0.0, y -0.056; charging knob z 0.050, y 0.028; the shoulder point (stock folded) z -0.078, y 0.004.
    Span 0.110 blocks: live_geometry.cpp kWeapons machine_gun length 0.110 (drawn at model scale 1)."""
    steel = Part(); poly = Part(); dark = Part()
    bevel_box(steel, (0, 0.016, 0.034), (0.015, 0.018, 0.086), 0.003)          # receiver
    bevel_box(steel, (0, 0.0262, 0.034), (0.011, 0.0028, 0.080), 0.0010)       # top cover
    tube(steel, (0, 0.017, 0.0790), 0.0058, 0.004, segments=16)                # barrel nut
    tube(steel, (0, 0.017, 0.0880), 0.0034, 0.016, segments=12)                # barrel
    tube(dark, (0, 0.017, 0.0963), 0.0021, 0.0006, segments=10)                # the bore (dark muzzle)
    box(steel, (0, 0.0300, 0.0700), (0.0025, 0.0050, 0.0030))                  # front sight post
    box(steel, (0.0035, 0.0290, 0.0700), (0.0012, 0.0035, 0.0040))            # its guards
    box(steel, (-0.0035, 0.0290, 0.0700), (0.0012, 0.0035, 0.0040))
    box(steel, (0, 0.0290, 0.0020), (0.0060, 0.0030, 0.0040))                  # rear sight
    bevel_box(dark, (0, 0.0287, 0.0500), (0.0050, 0.0030, 0.0070), 0.0012)     # charging knob on the cover
    bevel_box(poly, (0, 0.0025, 0.0580), (0.0150, 0.0090, 0.0400), 0.0025)     # handguard under the front
    bevel_box(poly, (0, -0.0090, 0.0000), (0.0115, 0.0340, 0.0160), 0.0030, axis=1)   # pistol grip, up into the receiver
    bevel_box(steel, (0, -0.0420, -0.0005), (0.0080, 0.0300, 0.0110), 0.0012, axis=1)  # magazine out of the grip
    box(dark, (0, -0.0565, -0.0005), (0.0095, 0.0020, 0.0125))                 # its base plate
    box(steel, (0, -0.0040, 0.0140), (0.0040, 0.0020, 0.0170))                 # trigger guard (bottom)
    box(steel, (0, 0.0005, 0.0225), (0.0040, 0.0080, 0.0020))                  # (front)
    box(dark, (0, 0.0010, 0.0105), (0.0020, 0.0060, 0.0020))                   # trigger
    box(dark, (0, -0.0020, -0.0110), (0.0070, 0.0060, 0.0050))                 # grip safety
    # the folding stock, folded (as the Uzi is carried, and the HUD icon's stub): a hinge at the receiver's
    # rear, two flat struts forward along its lower sides, the chamfered butt plate hanging under the
    # barrel nut. Open, its butt plate filled the first-person view's lower right corner.
    tube(steel, (0, 0.0090, -0.0110), 0.0030, 0.0030, segments=10)             # hinge
    for x in (-0.0089, 0.0089):
        tube_between(steel, (x, 0.0090, -0.0105), (x, 0.0040, 0.0740), 0.0014, 0.0014, 8)
    bevel_box(dark, (0, -0.0020, 0.0790), (0.0160, 0.0200, 0.0040), 0.0035)    # butt plate (rubber), chamfered
    return scene_with([("steel", steel.mesh(mat(BLUED, 0.9, 0.3, name="steel"))),
                       ("poly", poly.mesh(mat(OLIVE, 0.1, 0.7, name="poly", kind="skin"))),
                       ("dark", dark.mesh(mat(RUBBER, 0.3, 0.7, name="dark")))]), 0.110


def silenced_mg():
    steel = Part(); rubber = Part()
    box(steel, (0, 0.012, 0.028), (0.014, 0.016, 0.060))       # receiver
    box(steel, (0, -0.010, 0.012), (0.010, 0.030, 0.012))       # magazine in the grip
    tube(steel, (0, 0.014, 0.075), 0.004, 0.035)                # barrel
    tube(rubber, (0, 0.014, 0.115), 0.0075, 0.060)              # suppressor
    box(steel, (0, 0.010, -0.025), (0.004, 0.006, 0.040))       # folded stock bar
    return scene_with([("steel", steel.mesh(mat(STEEL, 0.85, 0.4, name="steel"))),
                       ("can", rubber.mesh(mat(RUBBER, 0.3, 0.7, name="can")))]), 0.15


def shotgun():
    """FIX-FIGURE-14 (pfl72): a pump-action (the game's HUD shotgun), at the old gun's span (-0.075 .. 0.175, so the
    rig's points and the table length still fit): the receiver over the trigger, one barrel with the magazine tube
    under it, the ribbed fore-end on the tube as its own node ("pump": the view model slides it back and forth
    after a shot), a pistol-grip wrist, the stock and a rubber butt pad. The bore stays 0.012 over the grip, the
    fore-end's middle at 0.080 (where the support hand goes). (Was two tubes over three wooden boxes.)"""
    steel = Part(); wood = Part(); dark = Part(); pump = Part()
    bevel_box(steel, (0, 0.008, 0.012), (0.014, 0.020, 0.046), 0.003)          # receiver -0.011 .. 0.035
    box(dark, (0.0071, 0.011, 0.016), (0.0006, 0.006, 0.016))                 # ejection port
    tube(steel, (0, 0.012, 0.105), 0.0042, 0.140, segments=16)                 # barrel 0.035 .. 0.175
    tube(dark, (0, 0.012, 0.1752), 0.0030, 0.0012, segments=16)                # the bore at the muzzle
    box(steel, (0, 0.0168, 0.171), (0.0016, 0.0022, 0.003))                    # front bead
    tube(steel, (0, 0.0015, 0.090), 0.0036, 0.110, segments=16)                # magazine tube 0.035 .. 0.145
    tube(steel, (0, 0.0015, 0.146), 0.0040, 0.003, segments=16)                # its cap
    box(steel, (0, 0.006, 0.148), (0.004, 0.008, 0.004))                       # barrel band
    bevel_box(pump, (0, 0.0015, 0.080), (0.016, 0.014, 0.050), 0.004)          # fore-end 0.055 .. 0.105
    pump_ribs = Part()                                                          # its grip ribs
    for k in range(6):
        for sx in (-1, 1):
            box(pump_ribs, (sx * 0.0081, 0.0015, 0.062 + k * 0.0072), (0.0006, 0.0100, 0.0022))
    box(steel, (0, -0.002, 0.009), (0.003, 0.004, 0.018))                      # trigger guard bottom
    box(steel, (0, -0.0035, 0.009), (0.0012, 0.005, 0.0016))                   # trigger
    bevel_box(wood, (0, -0.009, -0.002), (0.012, 0.020, 0.014), 0.003, axis=1)  # pistol-grip wrist
    bevel_box(wood, (0, -0.004, -0.040), (0.013, 0.024, 0.056), 0.003)         # stock -0.068 .. -0.012
    bevel_box(wood, (0, -0.008, -0.066), (0.0135, 0.030, 0.008), 0.003)        # the heel
    box(dark, (0, -0.008, -0.0720), (0.0140, 0.031, 0.006))                    # butt pad -0.075
    # (the ribs ride with the fore-end: they are part of the pump node's mesh)
    pump.v += pump_ribs.v; pump.n += pump_ribs.n; pump.uv += pump_ribs.uv
    base = len(pump.v) - len(pump_ribs.v)
    pump.f += [[i + base for i in f] for f in pump_ribs.f]
    return scene_with([("steel", steel.mesh(mat(BLUED, 0.9, 0.3, name="steel"))),
                       ("wood", wood.mesh(mat(WALNUT, 0.1, 0.55, name="wood"))),
                       ("dark", dark.mesh(mat(RUBBER, 0.2, 0.8, name="dark", kind="plain"))),
                       ("pump", pump.mesh(mat(WALNUT, 0.1, 0.55, name="pump")))]), 0.21


def rocket_launcher():
    olive = Part(); steel = Part(); glass = Part()
    tube(olive, (0, 0.030, 0.050), 0.020, 0.220, segments=16)    # the tube, on the shoulder
    tube(steel, (0, 0.030, 0.165), 0.024, 0.012, segments=16)    # muzzle ring
    tube(steel, (0, 0.030, -0.062), 0.024, 0.010, segments=16)   # breech ring
    box(steel, (0, 0.002, 0.000), (0.010, 0.030, 0.012))         # pistol grip
    box(steel, (0, 0.004, 0.060), (0.010, 0.026, 0.012))         # fore grip
    box(steel, (0.028, 0.040, 0.010), (0.006, 0.018, 0.020))     # sight post
    box(glass, (0.028, 0.050, 0.010), (0.008, 0.010, 0.002))     # sight glass
    return scene_with([("tube", olive.mesh(mat(OLIVE, 0.4, 0.6, name="tube"))),
                       ("steel", steel.mesh(mat(STEEL, 0.8, 0.4, name="steel"))),
                       ("glass", glass.mesh(mat(GLASS, 0.0, 0.1, emissive=(0.1, 0.2, 0.25), name="glass")))]), 0.22


def flamethrower():
    steel = Part(); tank = Part(); rubber = Part()
    tube(steel, (0, 0.012, 0.070), 0.006, 0.120)                 # lance
    tube(steel, (0, 0.012, 0.135), 0.010, 0.016, r2=0.014)       # nozzle bell
    box(steel, (0, 0.000, 0.000), (0.010, 0.026, 0.012))         # grip
    box(steel, (0, 0.000, 0.060), (0.010, 0.022, 0.012))         # fore grip
    tube(tank, (0, 0.010, -0.030), 0.012, 0.050)                 # fuel bottle under the lance
    tube(rubber, (0, 0.012, -0.070), 0.004, 0.040)               # hose stub (to the backpack)
    return scene_with([("steel", steel.mesh(mat(STEEL, 0.8, 0.4, name="steel"))),
                       ("tank", tank.mesh(mat(TANK, 0.6, 0.5, name="tank"))),
                       ("hose", rubber.mesh(mat(RUBBER, 0.2, 0.8, name="hose")))]), 0.18


TEAL = (38, 74, 78)
COPPER = (176, 104, 52)
CERAMIC = (222, 216, 200)


def electro_gun():
    """FIX-FIGURE-13 pfl50: an electro rifle that reads as one at the chase distance and from the eye (it was a
    0.10-block box with two prongs and a coil, drawn 1.6x up to the weapon table's 0.16 while the rig's points
    stayed at model scale: the grip went into the shoulder pocket, the gun at his face, the hands off it).
    A 1950s tesla gun: a battery pack behind the grip that sets into the shoulder like a stock, a teal enamel
    receiver with a glowing glass capacitor along its top in brass caps, copper coil rings round the barrel,
    two ceramic insulators and a brass emitter fork whose tips glow. Places the rig and the view model use
    (dll/src/weapon_rig.cpp GeoFor wElectro, live_geometry.cpp fore[] for kWpnElectro): bore y 0.017; the butt
    z -0.060, y 0.012; a vertical fore grip at z 0.052 (its top y 0.0, like the pistol grip's at the origin).
    Span 0.170 blocks: live_geometry.cpp kWeapons electro_gun length 0.170 (drawn at model scale 1)."""
    body = Part(); dark = Part(); glass = Part(); brass = Part(); copper = Part(); ceramic = Part(); glow = Part()
    # the battery (the stock): a round cell from the grip back to the shoulder in two copper bands, a dark
    # rubber butt pad (a box pack read as a flat dark slab filling the first-person view's lower right)
    tube(body, (0, 0.0135, -0.0360), 0.0085, 0.0420, segments=16)
    tube(dark, (0, 0.0135, -0.0585), 0.0095, 0.0030, segments=16)
    for z in (-0.048, -0.024):
        tube(copper, (0, 0.0135, z), 0.0091, 0.0028, segments=16)
    box(body, (0, 0.0100, -0.0120), (0.0090, 0.0120, 0.0100))                    # the cell's neck into the receiver
    # the receiver
    bevel_box(body, (0, 0.0165, 0.0200), (0.0160, 0.0200, 0.0700), 0.0030)
    # the capacitor along the top: a glass tube that glows, in brass caps on two posts
    tube(glass, (0, 0.0325, 0.0200), 0.0042, 0.0420, segments=14)
    for z in (-0.0020, 0.0420):
        tube(brass, (0, 0.0325, z), 0.0052, 0.0040, segments=14)
        box(brass, (0, 0.0285, z), (0.0030, 0.0040, 0.0030))
    # the barrel: a core through copper coil rings and two ceramic insulators to the fork
    tube(dark, (0, 0.0170, 0.0740), 0.0040, 0.0400, segments=12)
    for k in range(5):
        tube(copper, (0, 0.0170, 0.0590 + k * 0.0055), 0.0072, 0.0030, segments=16)
    for z in (0.0880, 0.0950):
        tube(ceramic, (0, 0.0170, z), 0.0062, 0.0035, segments=14)
    tube(brass, (0, 0.0170, 0.1010), 0.0050, 0.0030, segments=12)                # fork root
    for x in (-0.0055, 0.0055):
        tube_between(brass, (x * 0.5, 0.0170, 0.1010), (x, 0.0170, 0.1110), 0.0018, 0.0015, 8)
        blob(glow, (x, 0.0170, 0.1130), (0.0028, 0.0028, 0.0028), segments=10, rings=6)
    # grips: the pistol grip at the origin (up into the receiver), a vertical fore grip under the coils' back
    bevel_box(dark, (0, -0.0090, 0.0000), (0.0115, 0.0340, 0.0160), 0.0030, axis=1)
    bevel_box(dark, (0, -0.0110, 0.0520), (0.0100, 0.0260, 0.0110), 0.0025, axis=1)
    box(body, (0, -0.0040, 0.0140), (0.0040, 0.0020, 0.0170))                    # trigger guard (bottom)
    box(body, (0, 0.0005, 0.0225), (0.0040, 0.0080, 0.0020))                     # (front)
    box(brass, (0, 0.0010, 0.0105), (0.0020, 0.0060, 0.0020))                    # trigger
    box(brass, (0.0082, 0.0170, 0.0080), (0.0010, 0.0060, 0.0120))               # a brass dial plate on the right
    return scene_with([("enamel", body.mesh(mat(TEAL, 0.6, 0.35, name="enamel"))),
                       ("dark", dark.mesh(mat(RUBBER, 0.3, 0.7, name="dark"))),
                       ("glass", glass.mesh(mat(GLASS, 0.1, 0.15, emissive=(0.35, 0.75, 1.0), name="glass"))),
                       ("brass", brass.mesh(mat(BRASS, 0.9, 0.3, name="brass"))),
                       ("copper", copper.mesh(mat(COPPER, 0.9, 0.35, name="copper"))),
                       ("ceramic", ceramic.mesh(mat(CERAMIC, 0.0, 0.5, name="ceramic", kind="plain"))),
                       ("glow", glow.mesh(mat((200, 240, 255), 0.0, 0.2, emissive=(0.6, 0.9, 1.0), name="glow", kind="plain")))]), 0.170


def grenade():
    body = Part(); lever = Part()
    q = Part(); cylinder_part(q, lambda t: 0.010 * math.sin(math.pi * (0.08 + 0.84 * t)) + 0.002, -0.012, 0.012, segments=12, rings=5)
    body.v += q.v; body.n += q.n; body.uv += q.uv; body.f += q.f
    box(lever, (0, 0.014, 0.000), (0.004, 0.006, 0.006))         # fuse cap
    box(lever, (0.009, 0.006, 0.000), (0.002, 0.016, 0.005))     # spoon
    return scene_with([("casing", body.mesh(mat(OLIVE, 0.5, 0.6, name="casing"))),
                       ("lever", lever.mesh(mat(STEEL, 0.8, 0.4, name="lever")))]), 0.024


def molotov():
    """FIX-FIGURE-10 pmt3: a bottle you can read at a glance: a round green body with a heel and a
    shoulder, a round neck with a lip (it was a 4-sided grey box), a rag stuffed in the neck and
    a strip of it hanging down the side, the fuel showing through the lower glass as a darker band.
    Origin: where the fist closes (the upper body, under the shoulder); +y up the bottle."""
    glass = Part(); fuel = Part(); rag = Part()
    R = 0.0090
    def body(t):                                   # heel, body, shoulder, neck, lip (y -0.024 .. 0.021)
        y = -0.024 + t * 0.045
        if y < -0.022: return R * (0.86 + 0.14 * (y + 0.024) / 0.002)
        if y < 0.004: return R
        if y < 0.011: return R - (R - 0.0034) * math.sin(0.5 * math.pi * (y - 0.004) / 0.007)
        if y < 0.019: return 0.0034
        return 0.0041                               # the lip
    q = Part(); cylinder_part(q, body, -0.024, 0.021, segments=16, rings=22)
    glass.v += q.v; glass.n += q.n; glass.uv += q.uv; glass.f += q.f
    q = Part(); cylinder_part(q, lambda t: R * 1.004, -0.0215, -0.006, segments=16, rings=2, cap=False)
    fuel.v += q.v; fuel.n += q.n; fuel.uv += q.uv; fuel.f += q.f   # the fuel line inside the lower glass
    # the rag: a twisted wad out of the neck (tapering up, a little bent), a flap down the neck's side
    tube_between(rag, (0.0, 0.016, 0.0), (0.0005, 0.026, 0.0003), 0.0031, 0.0040, 10)
    tube_between(rag, (0.0005, 0.026, 0.0003), (0.0022, 0.034, -0.0006), 0.0040, 0.0018, 10)
    tube_between(rag, (0.0034, 0.021, 0.0), (0.0052, 0.012, 0.0006), 0.0019, 0.0013, 8)
    tube_between(rag, (0.0052, 0.012, 0.0006), (0.0060, 0.006, 0.0014), 0.0013, 0.0008, 8)
    return scene_with([("bottle", glass.mesh(mat((62, 118, 64), 0.0, 0.08, name="bottle", kind="plain"))),
                       ("fuel", fuel.mesh(mat((120, 84, 30), 0.0, 0.2, name="fuel", kind="plain"))),
                       ("rag", rag.mesh(mat((196, 184, 156), 0.0, 0.95, name="rag", kind="cloth")))]), 0.058


# First-person arms (the view model's hands): same model space as the weapons,
# blocks, +z ahead, +y up, +x right. The right hand closes round a grip at the
# origin (a pistol grip 0.010 x 0.026 x 0.013); its forearm runs back and down
# toward the eye, bare to the elbow, the upper arm in the dark short sleeve. The left: "fp_arm_left"
# cups a fore grip from below (its palm under the origin, fingers up the right
# side, thumb up the left), the forearm back and to the left; "fp_arm_left_cup"
# wraps the right fist from the left for a two-handed pistol hold.
def _forearm(skin, sleeve, hand_end, wrist, elbow, r, seg=10):
    """Hand to wrist, the bare forearm, the elbow and the player's dark short sleeve over the upper arm.
    FIX-FP-ENTRY (pm10): `elbow` gives only the forearm's direction. The forearm is a real one, about
    3.3 fists from wrist to elbow (it ran 12 fists, a thin tube with the sleeve never in frame); it swells
    from the wrist to the muscle and narrows to the elbow; the upper arm goes on out and down from the
    elbow inside the short sleeve (a hem, the cloth wider than the arm) and leaves the frame."""
    a = np.array(wrist, np.float32); e0 = np.array(elbow, np.float32)
    d = (e0 - a) / np.linalg.norm(e0 - a)
    fore = 0.040
    b = a + d * fore
    tube_between(skin, hand_end, wrist, r * 1.05, r, seg)
    m = a + d * fore * 0.55                                    # the forearm's muscle
    tube_between(skin, a, m, r, r * 1.45, seg)
    tube_between(skin, m, b, r * 1.45, r * 1.25, seg)
    blob(skin, tuple(b), (r * 1.3, r * 1.3, r * 1.3), segments=seg, rings=6)   # the elbow
    # the upper arm: bent at the elbow, out to the hand's side and down (the shoulder is under the eye)
    out = np.array([1.0 if wrist[0] >= 0 else -1.0, 0.0, 0.0], np.float32)
    u = d + out * 0.35 + np.array([0, -0.30, 0], np.float32)
    u /= np.linalg.norm(u)
    hem = b + u * 0.006
    tube_between(skin, b, hem + u * 0.004, r * 1.3, r * 1.45, seg)
    tube_between(sleeve, hem, hem + u * 0.004, r * 2.05, r * 2.15, seg + 2)   # the hem
    tube_between(sleeve, hem + u * 0.004, b + u * 0.200, r * 2.0, r * 2.3, seg + 2)


def fp_arm(side):
    skin = Part(); sleeve = Part()
    if side == "right":
        blob(skin, (0.0030, -0.0105, -0.0100), (0.0062, 0.0120, 0.0058))            # back of the hand behind the grip
        for k, y in enumerate((-0.0045, -0.0100, -0.0155, -0.0205)):                 # fingers round the front strap
            r = 0.0027 - 0.0002 * k
            blob(skin, (0.0005, y, 0.0045), (0.0064, r, r * 1.1))
        blob(skin, (0.0005, -0.0010, 0.0060), (0.0045, 0.0022, 0.0030))             # index finger on the trigger
        tube_between(skin, (-0.0045, -0.0040, -0.0095), (-0.0062, 0.0030, 0.0030), 0.0026, 0.0021, 8)   # thumb along the left
        _forearm(skin, sleeve, (0.0030, -0.0150, -0.0130), (0.0045, -0.0210, -0.0240), (0.0300, -0.0700, -0.1600), 0.0058)
    elif side == "left":
        blob(skin, (0.0000, -0.0098, 0.0000), (0.0080, 0.0038, 0.0105))            # palm under the fore grip
        for k, z in enumerate((0.0075, 0.0025, -0.0025, -0.0075)):                  # fingers up the right side
            blob(skin, (0.0074, -0.0035, z), (0.0026, 0.0065, 0.0023))
        tube_between(skin, (-0.0065, -0.0085, -0.0070), (-0.0075, 0.0005, 0.0070), 0.0025, 0.0021, 8)  # thumb up the left
        _forearm(skin, sleeve, (-0.0020, -0.0110, -0.0080), (-0.0070, -0.0150, -0.0170), (-0.0550, -0.0650, -0.1400), 0.0055)
    else:   # the left hand cupping the right fist (pistol, two hands)
        blob(skin, (-0.0088, -0.0140, -0.0030), (0.0040, 0.0110, 0.0085))           # palm on the left of the fist
        for k, y in enumerate((-0.0075, -0.0130, -0.0185, -0.0235)):                 # fingers over the right hand's
            blob(skin, (-0.0010, y, 0.0088), (0.0072, 0.0024, 0.0026))
        tube_between(skin, (-0.0095, -0.0060, -0.0060), (-0.0068, 0.0015, 0.0105), 0.0025, 0.0020, 8)  # thumb forward along the frame
        _forearm(skin, sleeve, (-0.0095, -0.0200, -0.0080), (-0.0140, -0.0260, -0.0180), (-0.0600, -0.0750, -0.1500), 0.0055)
    return scene_with([("skin", skin.mesh(mat(SKIN, 0.0, 0.6, name="skin", kind="skin", hires=True))),
                       ("sleeve", sleeve.mesh(mat(SLEEVE, 0.0, 0.9, name="sleeve", kind="cloth", hires=True)))]), 0.0


def fp_fist():
    """FIX-FIGURE-7 (pf2feel): the bare right fist of the first-person guard, in the arms' model space.
    A vertical fist: knuckles ahead (+z), the back of the hand to the right (+x), the palm to the left,
    the fingers stacked from the index (top) to the little finger (bottom). Each finger is curled: the
    first phalanx runs across the front (the flat of the fist), the second folds back into the palm, a
    knuckle at each bend; the thumb folds down over the second phalanges of the index and middle
    fingers on the palm side. (The fists were the pistol-grip hand with no gun: the trigger finger and
    the thumb along the frame stuck out ahead and read as a pointing hand.) The left fist is its mirror."""
    skin = Part(); sleeve = Part()
    blob(skin, (0.0008, -0.0095, -0.0050), (0.0046, 0.0112, 0.0075))          # the back of the hand and palm
    rows = ((-0.0010, 0.0030), (-0.0068, 0.0031), (-0.0124, 0.0029), (-0.0174, 0.0025))   # index .. little: y, radius
    for k, (y, r) in enumerate(rows):
        reach = 1.0 - 0.10 * k                                                 # the little finger is shorter
        kn = (0.0042, y, 0.0040 - 0.0006 * k)                                  # the knuckle (back of the hand side)
        bend = (-0.0040 * reach, y - 0.0004, 0.0058 - 0.0006 * k)             # the first bend, front left
        tip = (-0.0052 * reach, y - 0.0008, -0.0004)                          # folded back into the palm
        blob(skin, kn, (r * 1.10, r * 1.05, r * 1.10), segments=10, rings=6)
        tube_between(skin, kn, bend, r, r * 0.95, 10)                          # first phalanx: the flat of the fist
        blob(skin, bend, (r * 0.98, r * 0.95, r * 0.98), segments=10, rings=6)
        tube_between(skin, bend, tip, r * 0.92, r * 0.80, 10)                  # second phalanx into the palm
    blob(skin, (-0.0030, -0.0040, -0.0075), (0.0036, 0.0055, 0.0055))         # the ball of the thumb
    tj = (-0.0052, 0.0016, -0.0002)                                            # the thumb's knuckle, at the top
    tube_between(skin, (-0.0034, -0.0010, -0.0085), tj, 0.0030, 0.0027, 10)
    blob(skin, tj, (0.0027, 0.0027, 0.0027), segments=10, rings=6)
    tube_between(skin, tj, (-0.0068, -0.0075, 0.0028), 0.0026, 0.0021, 10)    # over the index and middle fingers
    blob(skin, (-0.0068, -0.0075, 0.0028), (0.0021, 0.0021, 0.0021), segments=8, rings=5)
    _forearm(skin, sleeve, (0.0015, -0.0175, -0.0105), (0.0020, -0.0180, -0.0150), (0.0280, -0.0600, -0.1600), 0.0056)
    return scene_with([("skin", skin.mesh(mat(SKIN, 0.0, 0.6, name="skin", kind="skin", hires=True))),
                       ("sleeve", sleeve.mesh(mat(SLEEVE, 0.0, 0.9, name="sleeve", kind="cloth", hires=True)))]), 0.0


def sblob(p, c, radii, e=0.6, disp=None, segments=24, rings=16):
    """A rounded box (superellipsoid, exponent e: 1 = ellipsoid, toward 0 = box) centred at c with
    semi-axes `radii`; `disp(point, outward)` returns an offset along the outward direction (grooves,
    bumps). Normals from the displaced grid, so the shading follows the grooves."""
    def sp(v):
        return math.copysign(abs(v) ** e, v)
    grid = []
    for r in range(rings + 1):
        th = math.pi * r / rings
        row = []
        for s_ in range(segments + 1):
            ph = 2 * math.pi * s_ / segments
            d = (math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph))
            q = np.array([radii[0] * sp(d[0]), radii[1] * sp(d[1]), radii[2] * sp(d[2])], np.float32)
            out = np.array(d, np.float32)
            if disp is not None:
                q = q + out * disp(q, out)
            row.append(q + np.array(c, np.float32))
        grid.append(row)
    base = len(p.v)
    for r in range(rings + 1):
        for s_ in range(segments + 1):
            a_ = grid[max(r - 1, 0)][s_]; b_ = grid[min(r + 1, rings)][s_]
            l_ = grid[r][(s_ - 1) % segments]; r_ = grid[r][(s_ + 1) % segments]
            n = np.cross(r_ - l_, b_ - a_)
            if np.linalg.norm(n) < 1e-12:
                n = np.array([0, 1 if r == 0 else -1, 0], np.float32)
            n = n / max(np.linalg.norm(n), 1e-12)
            if np.dot(n, grid[r][s_] - np.array(c, np.float32)) < 0:
                n = -n
            p.v.append(grid[r][s_]); p.n.append(n); p.uv.append((s_ / segments, r / rings))
    for r in range(rings):
        for s_ in range(segments):
            i0 = base + r * (segments + 1) + s_
            i1 = i0 + segments + 1
            p.f += [[i0, i0 + 1, i1], [i0 + 1, i1 + 1, i1]]


def fp_fist2():
    """FIX-FIGURE-14 (pfl67): the bare right fist rebuilt on the pistol hand (fp_arm "right"), so the bare
    hands and the armed view model share one hand and one arm: the same back of the hand, wrist, forearm,
    elbow and sleeve (`_forearm` with the pistol hand's points). A vertical fist (thumb on top, knuckles
    ahead +z, back of the hand +x): the four curled fingers are ONE rounded block (the flat of the fist,
    shallow grooves between the fingers on its front and palm side), the knuckle row a line of bumps on
    its front-back edge, the thumb folded across the front of the index and middle fingers.
    fp_fist (a tube per phalanx) read as a twisted rope knot at view-model size."""
    skin = Part(); sleeve = Part()
    sblob(skin, (0.0030, -0.0108, -0.0082), (0.0058, 0.0122, 0.0078), e=0.75)             # back of the hand + palm
    seams = (-0.0060, -0.0120, -0.0176)                                                    # between the fingers

    knuckles = (-0.0030, -0.0090, -0.0148, -0.0200)

    def grooves(q, out):
        y = q[1] - 0.0115                                                                  # model y
        front = max(0.0, out[2]) + 0.6 * max(0.0, -out[0])                                # the front and the palm side
        g = sum(math.exp(-((y - sy) / 0.0008) ** 2) for sy in seams)
        edge = max(0.0, out[0]) * max(0.0, out[2]) * 2.0                                   # the knuckle row: back-front edge
        kb = sum(math.exp(-((y - ky) / 0.0021) ** 2) for ky in knuckles)
        return -0.00075 * g * front + 0.0011 * kb * edge - 0.0006 * g * edge
    sblob(skin, (0.0004, -0.0115, 0.0002), (0.0070, 0.0122, 0.0055), e=0.55, disp=grooves, segments=32, rings=24)   # the curled fingers
    # the thumb: the ball of the thumb on the palm side, its joint at the fist's top front corner (no
    # higher than the index finger), the last phalanx lying flat across the index and middle fingers
    sblob(skin, (-0.0042, -0.0055, -0.0080), (0.0038, 0.0068, 0.0062), e=0.9, segments=16, rings=10)
    tj = (-0.0062, -0.0030, 0.0028)
    tube_between(skin, (-0.0050, -0.0040, -0.0080), tj, 0.0034, 0.0031, 16)
    blob(skin, tj, (0.0031, 0.0031, 0.0031), segments=14, rings=8)
    tt = (0.0002, -0.0070, 0.0062)
    tube_between(skin, tj, tt, 0.0030, 0.0026, 16)
    blob(skin, tt, (0.0026, 0.0026, 0.0024), segments=14, rings=8)
    _forearm(skin, sleeve, (0.0030, -0.0150, -0.0130), (0.0045, -0.0210, -0.0240), (0.0300, -0.0700, -0.1600), 0.0058, seg=20)
    return scene_with([("skin", skin.mesh(mat(SKIN, 0.0, 0.6, name="skin", kind="skin", hires=True))),
                       ("sleeve", sleeve.mesh(mat(SLEEVE, 0.0, 0.9, name="sleeve", kind="cloth", hires=True)))]), 0.0


ARMS = {"fp_arm_right": lambda: fp_arm("right"), "fp_arm_left": lambda: fp_arm("left"),
        "fp_arm_left_cup": lambda: fp_arm("cup"), "fp_fist_right": fp_fist, "fp_fist2_right": fp_fist2}

BUILDERS = {
    "pistol": pistol, "dual_pistol": pistol, "machine_gun": machine_gun, "silenced_mg": silenced_mg,
    "shotgun": shotgun, "rocket_launcher": rocket_launcher, "flamethrower": flamethrower,
    "electro_gun": electro_gun, "grenade": grenade, "molotov": molotov,
}


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    models = []
    for name, fn in BUILDERS.items():
        scene, length = fn()
        path = os.path.join(out, f"weapon_{name}.glb")
        scene.export(path)
        tris = sum(len(g.faces) for g in scene.geometry.values())
        print(f"weapon_{name}: {tris} tris, {length:.3f} blocks")
        models.append(dict(name=f"weapon_{name}", glb=f"weapons/weapon_{name}.glb", scale=1.0, texture_max=32, forward="+z",
                           _licence="procedural (this repository)"))
    for name, fn in ARMS.items():
        scene, _ = fn()
        scene.export(os.path.join(out, f"{name}.glb"))
        tris = sum(len(g.faces) for g in scene.geometry.values())
        print(f"{name}: {tris} tris")
        models.append(dict(name=name, glb=f"weapons/{name}.glb", scale=1.0, texture_max=256, forward="+z",
                           _licence="procedural (this repository)"))
    with open(os.path.join(out, "manifest_fragment.json"), "w") as f:
        json.dump({"models": models}, f, indent=1)


if __name__ == "__main__":
    main()
