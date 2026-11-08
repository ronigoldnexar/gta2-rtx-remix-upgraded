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


def flat(rgb, size=4):
    return Image.new("RGBA", (size, size), tuple(int(v) for v in rgb) + (255,))


def mat(rgb, metallic=0.8, roughness=0.35, emissive=None, name="m"):
    return PBRMaterial(name=name, baseColorTexture=flat(rgb), metallicFactor=metallic, roughnessFactor=roughness,
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


def pistol():
    body = Part(); grip = Part(); trim = Part()
    # slide and frame along +z from the grip at the origin
    box(body, (0, 0.012, 0.018), (0.009, 0.010, 0.050))      # slide
    box(body, (0, 0.004, 0.012), (0.008, 0.007, 0.032))      # frame
    tube(body, (0, 0.012, 0.047), 0.0025, 0.012)             # barrel tip
    box(trim, (0, 0.019, 0.004), (0.003, 0.003, 0.006))      # rear sight
    box(trim, (0, 0.019, 0.040), (0.002, 0.003, 0.003))      # front sight
    box(grip, (0, -0.012, -0.004), (0.010, 0.026, 0.013))     # grip (walnut panels)
    box(body, (0, -0.002, 0.004), (0.006, 0.006, 0.010))      # trigger guard block
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
        models.append(dict(name=f"weapon_{name}", glb=f"weapons/weapon_{name}.glb", scale=1.0, texture_max=16, forward="+z",
                           _licence="procedural (this repository)"))
    with open(os.path.join(out, "manifest_fragment.json"), "w") as f:
        json.dump({"models": models}, f, indent=1)


if __name__ == "__main__":
    main()
