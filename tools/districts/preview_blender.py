"""DISTRICTS-POC offline preview: the map's blocks round one building (walls and lids with the HD tiles, mapped
as the renderer maps them) with and without the facade kit, rendered in Blender (Cycles, CPU).

    blender -b -P preview_blender.py -- <work> <lvl> <hd dir> <kit dir> <kit file> <out prefix> [radius]

Writes <out>_<view>_{before,after}.png for views 'street' (eye 0.45 up across the street from the main front),
'corner' (a three-quarter view from 3 blocks up) and 'high' (the classic-like look down)."""
import bpy, bmesh, json, math, os, struct, sys
argv = sys.argv[sys.argv.index("--") + 1:]
work, lvl, hd, kitdir, kitfile, outp = argv[:6]
radius = int(argv[6]) if len(argv) > 6 else 10
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gmap
from gmap import FaceFrame, W, H, face_uvs

LID_FLAGS = (0x00, 0x08, 0x20, 0x28, 0x40, 0x48, 0x60, 0x68)
pick = json.load(open(os.path.join(work, f"{lvl}_pick.json")))
cat = {b["id"]: b for b in json.load(open(os.path.join(work, f"{lvl}_buildings.json")))["buildings"]}
b = cat[pick["id"]]
m = gmap.Map(os.path.join(os.environ.get("GTA2_DATA", "/mnt/gta2/gta2-linux/game/data"), f"{lvl}.gmp"))
x0, y0, x1, y1 = b["bbox"]
X0, Y0, X1, Y1 = max(0, x0 - radius), max(0, y0 - radius), min(255, x1 + radius), min(255, y1 + radius)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
mats = {}


def mat_for(key):
    if key in mats:
        return mats[key]
    kind, n = key
    path = os.path.join(hd, lvl, f"tile_{n:04d}.dds") if kind == "tile" else os.path.join(kitdir, f"kit_{n:02d}.dds")
    mt = bpy.data.materials.new(f"{kind}{n}")
    mt.use_nodes = True
    nt = mt.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.85
    if os.path.exists(path):
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(path)
        tex.interpolation = "Closest" if kind == "tile" else "Linear"
        tex.extension = "EXTEND" if kind == "tile" else "REPEAT"
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        mt.blend_method = "CLIP"
    mats[key] = mt
    return mt


def make_obj(name, polys):
    """polys: [(matkey, [(x,y,z) world renderer frame], [(u,v)])] -> Blender object (Blender: x, -z?, y up->z)"""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new()
    keys = []
    for key, pts, uvs in polys:
        vs = [bm.verts.new((p[0], p[2], p[1])) for p in pts]   # renderer (x, up, north) -> blender (x, y=north, z=up)
        try:
            f = bm.faces.new(vs)
        except ValueError:
            continue
        if key not in keys:
            keys.append(key)
        f.material_index = keys.index(key)
        for loop, uv in zip(f.loops, uvs):
            loop[uvl].uv = (uv[0], 1.0 - uv[1])
    bm.to_mesh(me); bm.free()
    for k in keys:
        me.materials.append(mat_for(k))
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob


# ---- the map round the building
polys = []
for yy in range(Y0, Y1 + 1):
    for xx in range(X0, X1 + 1):
        off, idx = m.columns[yy * W + xx]
        for i, bi in enumerate(idx):
            if bi >= len(m.blocks):
                continue
            blk = m.blocks[bi]
            lv = off + i
            st = blk[6] >> 2
            lid = blk[4]
            zs = float(H - yy - 1); zn = zs + 1
            if lid & 0x3FF and st in (0,) or (lid & 0x3FF and 41 <= st <= 60 and False):
                uv = face_uvs(lid, LID_FLAGS)
                polys.append((("tile", lid & 0x3FF), [(xx, lv + 1, zn), (xx + 1, lv + 1, zn), (xx + 1, lv + 1, zs), (xx, lv + 1, zs)], uv))
            elif lid & 0x3FF:
                uv = face_uvs(lid, LID_FLAGS)
                polys.append((("tile", lid & 0x3FF), [(xx, lv + 1, zn), (xx + 1, lv + 1, zn), (xx + 1, lv + 1, zs), (xx, lv + 1, zs)], uv))
            if st != 0:
                continue
            for side, (fi, table, nrm, d) in gmap.SIDES.items():
                raw = blk[fi]
                if not raw & 0x3FF:
                    continue
                c = gmap.wall_corners(xx, yy, lv, side)
                polys.append((("tile", raw & 0x3FF), c, face_uvs(raw, table)))
make_obj("map", polys)

# ---- the kit
def read_kit(path):
    data = open(path, "rb").read()
    assert data[:4] == b"GDK1"
    ng = struct.unpack_from("<I", data, 8)[0]
    p = 12
    out = []
    for _ in range(ng):
        tile, flags, nv, ni = struct.unpack_from("<iIII", data, p); p += 16
        vs = struct.unpack_from(f"<{nv * 8}f", data, p); p += nv * 32
        ix = struct.unpack_from(f"<{ni}I", data, p); p += ni * 4
        key = ("tile", tile) if tile >= 0 else ("kit", -1 - tile)
        for t in range(0, ni, 3):
            tri = [vs[ix[t + k] * 8: ix[t + k] * 8 + 8] for k in range(3)]
            out.append((key, [(v[0], v[1], v[2]) for v in tri], [(v[6], v[7]) for v in tri]))
    return out
kit_obj = make_obj("kit", read_kit(kitfile))

# ---- light, sky, cameras
world = bpy.data.worlds.new("w"); scene.world = world; world.use_nodes = True
world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.55, 0.65, 0.8, 1)
world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); scene.collection.objects.link(sun)
sun.data.energy = 3.5; sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(35))
scene.render.engine = "CYCLES"; scene.cycles.device = "CPU"; scene.cycles.samples = 24
scene.cycles.use_denoising = True
scene.render.resolution_x, scene.render.resolution_y = 960, 540
scene.render.film_transparent = False
scene.view_settings.view_transform = "Standard"

# the main front: the longest run of faces on one side
from collections import Counter
sides = Counter((f["side"]) for f in b["faces"] if f["lo"] <= b["street"])
front = sides.most_common(1)[0][0]
fs = [f for f in b["faces"] if f["side"] == front and f["lo"] <= b["street"]]
line = Counter((f["y"] if front in "NS" else f["x"]) for f in fs).most_common(1)[0][0]
fs = [f for f in fs if (f["y"] if front in "NS" else f["x"]) == line]
cx = sum(f["x"] for f in fs) / len(fs) + 0.5; cy = sum(f["y"] for f in fs) / len(fs) + 0.5
ox, oy = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}[front]
wx = cx + ox * 0.5; wz = H - cy - oy * 0.5
st_lv = b["street"]
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam); scene.camera = cam
cam.data.lens = 22


def look(eye, at):
    import mathutils
    e = mathutils.Vector((eye[0], eye[2], eye[1])); a = mathutils.Vector((at[0], at[2], at[1]))
    cam.location = e
    cam.rotation_euler = (a - e).to_track_quat("-Z", "Y").to_euler()


ax, az = (ox, -oy)
side_x, side_z = (-az, ax)
views = {
    "street": ((wx + ax * 3.2 + side_x * 2.0, st_lv + 0.45, wz + az * 3.2 + side_z * 2.0), (wx - side_x * 0.5, st_lv + 1.6, wz - side_z * 0.5)),
    "corner": ((wx + ax * 6 + side_x * 6, st_lv + 4.0, wz + az * 6 + side_z * 6), (wx - ax * 1.5, st_lv + 2.0, wz - az * 1.5)),
    "high": ((wx + ax * 9, st_lv + 11.0, wz + az * 9), (wx - ax * 2, st_lv, wz - az * 2)),
    "close": ((wx + ax * 1.6 + side_x * 0.8, st_lv + 1.2, wz + az * 1.6 + side_z * 0.8), (wx - side_x * 0.6, st_lv + 1.9, wz - side_z * 0.6)),
}
for vn, (eye, at) in views.items():
    look(eye, at)
    for state in ("before", "after"):
        kit_obj.hide_render = state == "before"
        scene.render.filepath = f"{outp}_{vn}_{state}.png"
        bpy.ops.render.render(write_still=True)
print("preview done", outp, front)
