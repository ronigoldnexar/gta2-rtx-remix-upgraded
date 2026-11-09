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


def mat(rgb, metallic=0.8, roughness=0.35, emissive=None, name="m", kind=None):
    if kind is None:
        kind = "metal" if metallic >= 0.5 else ("wood" if rgb == WALNUT else "plain")
    tex = flat(rgb) if kind == "plain" else grain(rgb, kind, seed=sum(rgb))
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


def machine_gun():
    """A Thompson-style submachine gun: receiver, finned barrel, drum magazine,
    pistol grip, fore grip, wooden stock."""
    steel = Part(); wood = Part(); brass = Part()
    box(steel, (0, 0.016, 0.040), (0.016, 0.018, 0.090))      # receiver
    tube(steel, (0, 0.019, 0.120), 0.0045, 0.075, r2=0.004)   # barrel
    for k in range(5):                                          # cooling fins
        tube(steel, (0, 0.019, 0.092 + k * 0.010), 0.0065, 0.003)
    tube(steel, (0, 0.019, 0.160), 0.006, 0.010)               # compensator
    tube(brass, (0, -0.004, 0.040), 0.018, 0.012, segments=20)  # drum magazine
    box(wood, (0, -0.012, 0.000), (0.011, 0.028, 0.014))        # pistol grip
    box(wood, (0, 0.000, 0.090), (0.012, 0.012, 0.024))         # fore grip
    box(wood, (0, 0.006, -0.040), (0.014, 0.026, 0.060))        # stock
    box(steel, (0, 0.027, 0.075), (0.003, 0.004, 0.004))        # front sight
    return scene_with([("steel", steel.mesh(mat(BLUED, 0.9, 0.3, name="steel"))),
                       ("wood", wood.mesh(mat(WALNUT, 0.1, 0.55, name="wood"))),
                       ("drum", brass.mesh(mat(STEEL, 0.85, 0.35, name="drum")))]), 0.17


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
    steel = Part(); wood = Part()
    tube(steel, (-0.004, 0.012, 0.100), 0.004, 0.150)           # twin barrels
    tube(steel, (0.004, 0.012, 0.100), 0.004, 0.150)
    box(steel, (0, 0.010, 0.012), (0.014, 0.016, 0.040))        # breech
    box(wood, (0, 0.004, 0.080), (0.016, 0.012, 0.050))         # fore-end
    box(wood, (0, -0.004, -0.040), (0.014, 0.024, 0.070))       # stock
    box(wood, (0, -0.010, 0.000), (0.012, 0.016, 0.016))        # wrist
    return scene_with([("steel", steel.mesh(mat(BLUED, 0.9, 0.3, name="steel"))),
                       ("wood", wood.mesh(mat(WALNUT, 0.1, 0.55, name="wood")))]), 0.21


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


def electro_gun():
    steel = Part(); glass = Part(); brass = Part()
    box(steel, (0, 0.012, 0.020), (0.018, 0.020, 0.050))         # the box
    box(steel, (0, -0.010, 0.000), (0.010, 0.026, 0.012))        # grip
    for x in (-0.010, 0.010):                                     # two prongs
        tube(brass, (x, 0.014, 0.065), 0.003, 0.040)
        tube(glass, (x, 0.014, 0.088), 0.005, 0.006)              # the tips glow
    tube(glass, (0, 0.028, 0.020), 0.008, 0.030)                 # the coil on top
    return scene_with([("steel", steel.mesh(mat(STEEL, 0.8, 0.4, name="steel"))),
                       ("prongs", brass.mesh(mat(BRASS, 0.9, 0.3, name="prongs"))),
                       ("coil", glass.mesh(mat(GLASS, 0.1, 0.2, emissive=(0.3, 0.6, 0.9), name="coil")))]), 0.11


def grenade():
    body = Part(); lever = Part()
    q = Part(); cylinder_part(q, lambda t: 0.010 * math.sin(math.pi * (0.08 + 0.84 * t)) + 0.002, -0.012, 0.012, segments=12, rings=5)
    body.v += q.v; body.n += q.n; body.uv += q.uv; body.f += q.f
    box(lever, (0, 0.014, 0.000), (0.004, 0.006, 0.006))         # fuse cap
    box(lever, (0.009, 0.006, 0.000), (0.002, 0.016, 0.005))     # spoon
    return scene_with([("casing", body.mesh(mat(OLIVE, 0.5, 0.6, name="casing"))),
                       ("lever", lever.mesh(mat(STEEL, 0.8, 0.4, name="lever")))]), 0.024


def molotov():
    glass = Part(); rag = Part()
    q = Part(); cylinder_part(q, lambda t: 0.009 if t < 0.6 else 0.009 - (t - 0.6) * 0.012, -0.020, 0.020, segments=12, rings=5)
    glass.v += q.v; glass.n += q.n; glass.uv += q.uv; glass.f += q.f
    box(rag, (0, 0.026, 0.000), (0.008, 0.014, 0.008))            # the rag out of the neck
    return scene_with([("bottle", glass.mesh(mat((110, 140, 90), 0.0, 0.1, name="bottle"))),
                       ("rag", rag.mesh(mat((210, 200, 180), 0.0, 0.9, name="rag")))]), 0.05


# First-person arms (the view model's hands): same model space as the weapons,
# blocks, +z ahead, +y up, +x right. The right hand closes round a grip at the
# origin (a pistol grip 0.010 x 0.026 x 0.013); its forearm runs back and down
# toward the eye, bare to the dark short sleeve at the elbow. The left: "fp_arm_left"
# cups a fore grip from below (its palm under the origin, fingers up the right
# side, thumb up the left), the forearm back and to the left; "fp_arm_left_cup"
# wraps the right fist from the left for a two-handed pistol hold.
def _forearm(skin, sleeve, hand_end, wrist, elbow, r):
    """Hand to wrist, the bare forearm, and the edge of the player's dark
    short-sleeved shirt at the elbow (as his figure wears it in the other views)."""
    a = np.array(wrist, np.float32); b = np.array(elbow, np.float32)
    tube_between(skin, hand_end, wrist, r * 1.05, r, 10)
    tube_between(skin, a, a + (b - a) * 0.80, r, r * 1.35, 10)
    tube_between(sleeve, a + (b - a) * 0.74, b, r * 1.75, r * 1.95, 12)


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
    return scene_with([("skin", skin.mesh(mat(SKIN, 0.0, 0.6, name="skin", kind="skin"))),
                       ("sleeve", sleeve.mesh(mat(SLEEVE, 0.0, 0.9, name="sleeve", kind="cloth")))]), 0.0


ARMS = {"fp_arm_right": lambda: fp_arm("right"), "fp_arm_left": lambda: fp_arm("left"),
        "fp_arm_left_cup": lambda: fp_arm("cup")}

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
        models.append(dict(name=name, glb=f"weapons/{name}.glb", scale=1.0, texture_max=32, forward="+z",
                           _licence="procedural (this repository)"))
    with open(os.path.join(out, "manifest_fragment.json"), "w") as f:
        json.dump({"models": models}, f, indent=1)


if __name__ == "__main__":
    main()
